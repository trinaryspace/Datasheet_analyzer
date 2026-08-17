"""Integration: full AFE7950 build from recorded TI pages (hermetic —
ReplayFetcher cannot touch the network) + golden Q&A verification + a
whole-corpus footnote-orphan audit.

This is the end-to-end proof that Phase 1 works on the real target.

It also carries the ticket-04 confidence measurement of the *second*
reference corpus, AFE7953 (see `TestCommittedReferenceCorpora`): that part
cannot be rebuilt in a hermetic test — the recorded TI document-viewer pages
under `tests/fixtures/recorded_http/` are AFE7950's only — so its mix is
measured off the corpus committed under `parts/`, by a regrade whose fidelity
is proven here against a fresh AFE7950 build.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import ClassVar

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.evalh.citations import load_golden_yaml, verify_questions
from datasheet_analyzer.evalh.golden import estimate_lookup_tokens
from datasheet_analyzer.extract import get_backend
from datasheet_analyzer.extract.http import ReplayBinaryFetcher, ReplayFetcher
from datasheet_analyzer.extract.pdf_structure import page_texts
from datasheet_analyzer.models import (
    CorpusManifest,
    PlotSet,
    SectionNode,
    SpecSet,
    TableBlock,
)
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.publish import doc_dir_name_for_source
from datasheet_analyzer.structure.confidence import (
    grade_plot_record,
    grade_spec_record,
    mix,
)
from datasheet_analyzer.structure.footnotes import audit_table_footnotes
from datasheet_analyzer.structure.pagemap import pin_table_pages

RECORDED = Path(__file__).parent.parent / "fixtures" / "recorded_http"
RECORDED_BIN = Path(__file__).parent.parent / "fixtures" / "recorded_http_bin"
GOLDEN = Path(__file__).parent.parent / "fixtures" / "golden_qa_AFE7950.yaml"
PARTS = Path(__file__).parent.parent.parent / "parts"

TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory, afe7950_pdf, monkeymodule):
    """Build the real corpus once per module, replaying recorded HTTP."""
    if not RECORDED.is_dir():
        pytest.skip("recorded HTTP fixtures not present")

    tmp = tmp_path_factory.mktemp("built")
    settings = Settings(parts_dir=tmp / "parts", cache_dir=tmp / ".cache").resolve()

    backend = get_backend("ti_html")
    backend.fetcher = ReplayFetcher(RECORDED)
    monkeymodule.setattr("datasheet_analyzer.pipeline.get_backend", lambda name: backend)

    # Plot pixels must be hermetic too; use real recordings for golden plots
    # and a tiny stand-in GIF for everything else.
    bin_fetcher = ReplayBinaryFetcher(RECORDED_BIN, default=TINY_GIF)
    monkeymodule.setattr(
        "datasheet_analyzer.pipeline.CachingBinaryFetcher",
        lambda *args, **kwargs: bin_fetcher,
    )

    result = build_part(afe7950_pdf, part_number="AFE7950", settings=settings,
                        use_llm=False, use_cache=False)
    return result, settings


@pytest.fixture(scope="module")
def monkeymodule():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.mark.integration
class TestRealBuild:
    def test_corpus_shape(self, built):
        result, _ = built
        s = result.manifest.stats
        assert s.n_documents == 1
        assert s.n_sections == 39  # 40 TOC anchors minus the cover page
        assert s.n_tables >= 15
        assert s.n_figures >= 500  # the plot gallery is fully cataloged
        assert s.n_footnotes >= 20
        assert s.n_specs >= 150  # Phase 2: parametric rows normalized
        assert s.index_tokens <= 3000  # INDEX.md stays inside its budget

    def test_page_coverage_complete(self, built):
        result, _ = built
        for s in result.manifest.sections:
            assert s.page_start is not None, f"{s.number} {s.title} has no pages"
            assert 1 <= s.page_start <= 146
            assert (s.page_end or s.page_start) >= s.page_start

    def test_every_manifest_file_exists(self, built):
        result, _ = built
        for s in result.manifest.sections:
            assert (result.part_dir / s.file).exists(), s.file
        # Phase 2: specs.json written next to the sections dir
        doc_dir = result.part_dir / f"docs/datasheet-{result.manifest.documents[0].content_hash[:8]}"
        assert (doc_dir / "specs.json").exists()

    def test_manifest_schema_roundtrip(self, built):
        result, _ = built
        data = json.loads((result.part_dir / "manifest.json").read_text(encoding="utf-8"))
        m = CorpusManifest.model_validate(data)
        assert m.part_number == "AFE7950"

    def test_no_footnote_orphans_in_whole_corpus(self, built):
        """Every footnote marker cited in any table resolves to a note."""
        result, settings = built
        from datasheet_analyzer.models import RawDocument

        cache = result.manifest.documents[0].content_hash
        raw_path = settings.cache_dir / "extract" / f"{cache}__ti_html.json"
        raw = RawDocument.model_validate_json(raw_path.read_text(encoding="utf-8"))
        orphans = []
        for sec in raw.sections:
            for t in sec.tables:
                audit = audit_table_footnotes(t, set(t.cited_markers))
                if not audit.ok:
                    orphans.append((sec.number, sorted(audit.orphans)))
        assert orphans == [], f"orphan footnote citations: {orphans}"

    def test_exact_spec_values_in_corpus_files(self, built):
        result, _ = built
        tx45 = next(
            f for f in result.part_dir.rglob("4-5-transmitter-electrical-characteristics.md")
        )
        text = tx45.read_text(encoding="utf-8")
        for needle in ["DAC resolution", "14", "DSA Attenuation range", "±0.1",
                       "After DSA calibration procedure", "Typical values at"]:
            assert needle in text, f"{needle!r} missing from 4.5 section file"

    def test_confidence_mix_is_recorded_and_complete(self, built, capsys):
        """Phase 5, ticket 04: the reference TI corpus is graded too, and the
        mix it produces is a measured number in its manifest. TI's tables come
        from real HTML — nothing is reconstructed — so their rows are graded
        purely on page pinning and printed values, which is the other half of
        the rule from the layout-floor gate corpora."""
        result, _ = built
        stats = result.manifest.stats
        assert sum(stats.spec_confidence.values()) == stats.n_specs
        assert "unknown" not in stats.spec_confidence
        assert stats.spec_confidence["high"] > 0
        assert sum(stats.plot_confidence.values()) == stats.n_figures
        with capsys.disabled():
            print(f"\nconfidence mix, AFE7950: specs {stats.spec_confidence} "
                  f"plots {stats.plot_confidence}\n")

    def test_golden_qa_all_pass(self, built, afe7950_pdf):
        result, _ = built
        questions = load_golden_yaml(GOLDEN)
        results = verify_questions(questions, result.part_dir, page_texts(afe7950_pdf))
        failed = [r.question.id for r in results if not r.passed]
        assert failed == [], f"golden QA failures: {failed}"

    def test_token_economics(self, built):
        result, _ = built
        questions = load_golden_yaml(GOLDEN)
        results = verify_questions(questions, result.part_dir, ["x"] * 146)
        est = estimate_lookup_tokens(result.part_dir, results)
        # the whole point of the architecture: lookups are far cheaper
        # than dumping the corpus into context
        assert est["avg_per_question"] < est["full_dump_tokens"] / 5
        assert est["max_per_question"] < est["full_dump_tokens"] / 3

    def test_rebuild_uses_extraction_cache(self, built, monkeymodule):
        result, settings = built
        backend = get_backend("ti_html")  # fetcher still wired by fixture
        monkeymodule.setattr("datasheet_analyzer.pipeline.get_backend", lambda name: backend)
        second = build_part(
            Path(result.manifest.documents[0].path),
            part_number="AFE7950", settings=settings, use_llm=False,
        )
        assert second.cached_extraction


# --------------------------------------------------------------------------
# Ticket 04, box 5: the confidence mix of the *committed* reference corpora.
#
# Four of the six built parts are measured by the phase-4 gate (it builds them
# from `tests/fixtures/pdf/`), and AFE7950 is measured by the fresh build
# above. AFE7953 is the sixth, and it has no offline build path at all: it is
# a TI part, so it routes to `ti_html`, and the only recorded document-viewer
# pages in the repo are AFE7950's. What *is* available is the corpus committed
# under `parts/AFE7953` — the same substrate `tests/fixtures/alias_seed_symbols.json`
# was harvested from — plus the printed PDF.
#
# So the mix is recovered rather than rebuilt. Everything the grading rule
# reads is recoverable from published artifacts: the row itself and its page
# come from `specs.json`, the section's range from `manifest.json`, the grid
# from the `tables/*.csv` twin (which is `TableBlock.csv` verbatim), and the
# table's exact page by re-running the very pinning pass the pipeline runs,
# `pin_table_pages`, against the PDF's printed text. `reconstruction` and
# `row_pages` are empty for every HTML-extracted table by construction.
#
# That is a reconstruction, so it is only worth what it can be checked
# against: `test_regrade_matches_a_fresh_build` runs it on AFE7950, where a
# real build exists in the same module, and requires an exact match before the
# AFE7953 number is believed.
# --------------------------------------------------------------------------


def _committed_nodes(part_dir: Path, manifest: CorpusManifest) -> list[SectionNode]:
    """Rebuild each published section as a `SectionNode` carrying its grids."""
    nodes: list[SectionNode] = []
    for doc in manifest.documents:
        doc_dir = part_dir / "docs" / doc_dir_name_for_source(doc)
        for sec in manifest.sections:
            if sec.doc_hash != doc.content_hash:
                continue
            stem = Path(sec.file).stem
            tables: list[TableBlock] = []
            while True:
                path = doc_dir / "tables" / f"{stem}-t{len(tables) + 1:02d}.csv"
                if not path.exists():
                    break
                rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
                tables.append(
                    TableBlock(headers=rows[0] if rows else [], grid=rows[1:])
                )
            nodes.append(
                SectionNode(
                    number=sec.number,
                    title=sec.title,
                    page_start=sec.page_start,
                    page_end=sec.page_end,
                    tables=tables,
                )
            )
    return nodes


def regrade_committed_corpus(part_dir: Path, pdf: Path) -> dict:
    """Grade a committed corpus's records from its published artifacts.

    Returns the spec mix, the plot mix, and how many spec records could not
    be matched back to a published grid — which the caller asserts is zero, so
    a corpus this reconstruction cannot fully cover fails loudly instead of
    reporting a quietly partial mix.
    """
    manifest = CorpusManifest.model_validate_json(
        (part_dir / "manifest.json").read_text(encoding="utf-8")
    )
    nodes = _committed_nodes(part_dir, manifest)
    pin_table_pages(nodes, page_texts(pdf))
    by_number = {node.number: node for node in nodes}

    specs, plots, unmatched = [], [], 0
    for doc in manifest.documents:
        doc_dir = part_dir / "docs" / doc_dir_name_for_source(doc)
        specset = SpecSet.model_validate_json(
            (doc_dir / "specs.json").read_text(encoding="utf-8")
        )
        for rec in specset.records:
            node = by_number.get(rec.section)
            if node is None or len(node.tables) <= rec.table_index:
                unmatched += 1
                continue
            rec.confidence = grade_spec_record(rec, node.tables[rec.table_index], node)
            specs.append(rec)
        plotset = PlotSet.model_validate_json(
            (doc_dir / "plots.json").read_text(encoding="utf-8")
        )
        for plot in plotset.plots:
            plot.confidence = grade_plot_record(plot)
            plots.append(plot)

    return {
        "specs": mix(specs),
        "plots": mix(plots),
        "n_specs": len(specs),
        "n_plots": len(plots),
        "unmatched": unmatched,
    }


@pytest.mark.integration
class TestAnswerPacksOnTheRealCorpus:
    """Phase 5, ticket 05: `dsa ask` over the AFE7950 golden set.

    The reference part is where the ask path has the most to prove: 39
    sections, 619 spec rows and 514 figures, and a golden set whose questions
    are written the way a designer speaks. Same three claims as the gate
    corpora (`tests/integration/test_phase4_layout_gate.py::TestAnswerPacks`):
    every pack inside its budget, citations un-truncatable at a tight one, and
    natural-language twin agreement with the symbol path — with the residuals
    recorded per question so neither a regression nor an unrecorded fix can
    pass silently.
    """

    BUDGET = 3000
    TIGHT_BUDGET = 400

    # Recorded, not tolerated: the residual is never the pack inventing or
    # dropping an answer. It was probed against the corpus.
    #
    #   q07 "how many integrated VCOs are there and what frequency range do
    #       they cover?" — the only VCO-specific token in it is `VCOs`, and
    #       `VCO` is a *symbol prefix* here (`fVCO1`…`fVCO4`), not a phrase a
    #       whole-phrase lexicon can match; the longest alias phrase the
    #       question does contain is `frequency range`, which §4.5's RF output
    #       rows print verbatim, so the pack answers those and says so
    #       (`matched_via: alias:frequency range`). Nor would a VCO rung
    #       satisfy the twin rule: the answer spans eight sibling rows
    #       (`fVCO1 min frequency` … `fVCO4 max frequency`) and the expected
    #       extremes 7.2 and 12.08 are the first and the last of them, so the
    #       per-route cap of `MAX_SPEC_ANSWERS` rows would drop 12.08. The
    #       symbol path only reaches it because its twin filters to §4.7 —
    #       a scope the natural-language question never states.
    KNOWN_ASK_MISSES: ClassVar[set[str]] = {"q07-vco-coverage"}

    def _questions(self):
        return load_golden_yaml(GOLDEN)

    def test_the_tickets_own_question_on_the_real_reference_corpus(self, built):
        """`dsa ask --part AFE7950 "max junction temperature" --budget 3000`.

        The plan illustrates this with `§4.3, p.6`; the AFE7950 actually
        prints its junction-temperature limit in §4.1 Absolute Maximum
        Ratings on page 4, and that is what the pack cites — the corpus
        answers from the datasheet, never from the example.
        """
        from datasheet_analyzer.retrieve import ROUTE_SPEC, Retriever

        result, _ = built
        pack = Retriever.for_part(result.part_dir).ask(
            "max junction temperature", budget=3000
        )
        assert pack.route == ROUTE_SPEC
        top = pack.answers[0]
        assert top.text.startswith("TJ")
        assert "150 °C" in top.text
        assert top.citation == "§4.1, p.4"
        assert top.matched_via == "alias:max junction temperature"
        assert top.confidence in ("high", "medium", "low")
        assert f"Confidence: {top.confidence}." in pack.verify
        assert "of afe7950.pdf" in pack.verify
        assert pack.tokens <= 3000

    def test_every_golden_question_answers_inside_its_budget(self, built, capsys):
        from datasheet_analyzer.retrieve import ROUTE_NONE, Retriever

        result, _ = built
        retriever = Retriever.for_part(result.part_dir)
        routes: dict[str, int] = {}
        costs = []
        for q in self._questions():
            pack = retriever.ask(q.question, budget=self.BUDGET)
            assert pack.tokens <= self.BUDGET, q.id
            assert not pack.over_budget, q.id
            if pack.route != ROUTE_NONE:
                assert pack.citations, f"{q.id}: an answer with no citation"
                assert all(line.citation for line in pack.answers), q.id
            routes[pack.route] = routes.get(pack.route, 0) + 1
            costs.append(pack.tokens)
        with capsys.disabled():
            print(
                f"\nanswer packs, AFE7950 (budget {self.BUDGET}): "
                f"{len(costs)} questions, mean {sum(costs) / len(costs):.0f} tok, "
                f"max {max(costs)} tok — "
                + "  ".join(f"{r}: {n}" for r, n in sorted(routes.items()))
                + "\n"
            )
        assert costs

    def test_a_tight_budget_costs_prose_and_never_the_citation(self, built):
        from datasheet_analyzer.retrieve import ROUTE_NONE, Retriever

        result, _ = built
        retriever = Retriever.for_part(result.part_dir)
        for q in self._questions():
            wide = retriever.ask(q.question, budget=self.BUDGET)
            tight = retriever.ask(q.question, budget=self.TIGHT_BUDGET)
            assert tight.tokens <= self.TIGHT_BUDGET, q.id
            assert tight.route == wide.route, q.id
            if wide.route == ROUTE_NONE:
                continue
            assert tight.citations and tight.citations[0] == wide.citations[0], q.id
            assert tight.answers[0] == wide.answers[0], q.id

    def test_natural_language_lands_on_the_symbol_paths_answer(self, built, capsys):
        # the shipped rule (`dsa verify`'s own, ticket 09), not a copy of it
        from datasheet_analyzer.evalh.citations import pack_answers_question
        from datasheet_analyzer.retrieve import Retriever

        result, _ = built
        retriever = Retriever.for_part(result.part_dir)
        twins = [q for q in self._questions() if q.spec_query or q.plot_query]
        misses = set()
        for q in twins:
            pack = retriever.ask(q.question, budget=self.BUDGET)
            if not pack_answers_question(q, pack):
                misses.add(q.id)
        with capsys.disabled():
            print(
                f"\nask-path twin agreement, AFE7950: "
                f"{len(twins) - len(misses)}/{len(twins)}"
                + (f"   missed: {', '.join(sorted(misses))}" if misses else "")
                + "\n"
            )
        assert misses == self.KNOWN_ASK_MISSES, (
            f"AFE7950 ask-path twin agreement moved — expected misses "
            f"{sorted(self.KNOWN_ASK_MISSES)}, got {sorted(misses)}"
        )

    def test_the_json_pack_validates_against_its_declared_schema(self, built):
        from datasheet_analyzer.retrieve import Retriever, validate_pack

        result, _ = built
        retriever = Retriever.for_part(result.part_dir)
        for q in self._questions():
            payload = retriever.ask(q.question, budget=self.BUDGET).as_dict()
            assert validate_pack(payload) == [], q.id


@pytest.mark.integration
class TestAnswerPacksOnAfe7953:
    """Phase 5, ticket 05: the *sixth* built part answers too.

    Until this ticket's repair, AFE7953 was the one built corpus with no
    golden set at all — so "every golden question across all six parts"
    was measured over five. `tests/fixtures/golden_qa_AFE7953.yaml` closes
    that: 11 questions whose expected substrings were read off the printed
    pages of `afe7953.pdf` and cross-checked against the committed corpus,
    the same substrate `TestCommittedReferenceCorpora` measures on (this part
    has no offline build path — no recorded TI document-viewer pages exist
    for it).

    It is also the only place the ask path is exercised against a corpus
    published *before* `search_index.json` existed, which is the honest-
    degradation case the answer pack must not read as absence.
    """

    BUDGET = 3000
    TIGHT_BUDGET = 400
    GOLDEN: ClassVar[Path] = Path(__file__).parent.parent / "fixtures" / "golden_qa_AFE7953.yaml"

    @pytest.fixture
    def part_dir(self) -> Path:
        if not (PARTS / "AFE7953" / "manifest.json").exists():
            pytest.skip("committed parts/AFE7953 corpus not present")
        return PARTS / "AFE7953"

    def _questions(self):
        assert self.GOLDEN.exists(), (
            "AFE7953 is a built part and every built part carries a benchmark "
            "(AGENTS.md invariant 5)"
        )
        return load_golden_yaml(self.GOLDEN)

    def test_the_benchmark_verifies_100_percent(self, part_dir, afe7953_pdf):
        """The set is ground truth before it is used to judge the ask path."""
        from datasheet_analyzer.evalh.citations import (
            verify_plot_queries,
            verify_spec_queries,
        )

        questions = self._questions()
        assert len(questions) >= 10
        pages = page_texts(afe7953_pdf)
        for res in verify_questions(questions, part_dir, pages):
            assert res.corpus_contains, f"{res.question.id}: not in the cited section"
            assert res.page_truth, f"{res.question.id}: not on the printed page"
        for res in verify_spec_queries(questions, part_dir):
            assert res.ok, f"{res.question.id}: symbol path missed"
        for res in verify_plot_queries(questions, part_dir):
            assert res.ok, f"{res.question.id}: plot path missed"

    def test_natural_language_lands_on_the_symbol_paths_answer(self, part_dir, capsys):
        from datasheet_analyzer.evalh.citations import pack_answers_question
        from datasheet_analyzer.retrieve import Retriever

        retriever = Retriever.for_part(part_dir)
        twins = [q for q in self._questions() if q.spec_query or q.plot_query]
        misses = set()
        for q in twins:
            pack = retriever.ask(q.question, budget=self.BUDGET)
            if not pack_answers_question(q, pack):
                misses.add(q.id)
        with capsys.disabled():
            print(
                f"\nask-path twin agreement, AFE7953: "
                f"{len(twins) - len(misses)}/{len(twins)}\n"
            )
        assert len(twins) >= 8
        assert misses == set(), f"AFE7953 twins regressed: {sorted(misses)}"

    def test_every_golden_question_answers_inside_its_budget(self, part_dir):
        from datasheet_analyzer.retrieve import ROUTE_NONE, Retriever

        retriever = Retriever.for_part(part_dir)
        for q in self._questions():
            wide = retriever.ask(q.question, budget=self.BUDGET)
            tight = retriever.ask(q.question, budget=self.TIGHT_BUDGET)
            assert wide.tokens <= self.BUDGET and not wide.over_budget, q.id
            assert tight.tokens <= self.TIGHT_BUDGET, q.id
            assert tight.route == wide.route, f"{q.id}: routing moved"
            assert wide.route != ROUTE_NONE, (
                f"{q.id}: this corpus provably answers it — a no-match is wrong"
            )
            if wide.citations:
                assert tight.citations[0] == wide.citations[0], q.id
                assert tight.answers[0] == wide.answers[0], q.id

    def test_a_corpus_published_before_search_says_rebuild_not_no_match(self, part_dir):
        """The committed AFE7953 corpus predates `search_index.json`.

        A question that reaches neither a record nor a figure therefore has
        no path left to run — and the pack must say the path could not run,
        not that nothing in the datasheet answers it.
        """
        from datasheet_analyzer.retrieve import ROUTE_UNAVAILABLE, Retriever

        retriever = Retriever.for_part(part_dir)
        assert retriever.search_unavailable(), (
            "recorded state: this corpus has no current search index. If it "
            "has been republished, assert the search route here instead."
        )
        pack = retriever.ask("What package does the AFE7953 come in?", budget=self.BUDGET)
        assert pack.route == ROUTE_UNAVAILABLE
        assert "No spec record, figure or section in this corpus answers" not in (
            pack.markdown
        )
        assert "Rebuild to enable search" in pack.markdown

    def test_the_json_pack_validates_against_its_declared_schema(self, part_dir):
        from datasheet_analyzer.retrieve import Retriever, validate_pack

        retriever = Retriever.for_part(part_dir)
        for q in self._questions():
            payload = retriever.ask(q.question, budget=self.BUDGET).as_dict()
            assert validate_pack(payload) == [], q.id


def search_index_committed_corpus(src: Path, dst: Path) -> Path:
    """Copy a committed corpus and give it the search index publish now writes.

    The two reference corpora under `parts/` were published before
    `search_index.json` existed, and AFE7953 cannot be rebuilt in a hermetic
    test (no recorded TI pages). The index is *derived data*: it is built from
    exactly the section markdown that is on disk, by the same
    `build_search_index` the writer calls, so indexing a copy adds nothing to
    the corpus and changes nothing in it — it only performs the publish step
    the corpus predates. The committed corpus itself is left untouched, which
    is what keeps `TestAnswerPacksOnAfe7953`'s "predates search" case honest.

    `figures/` is deliberately not copied: the search path reads markdown.
    """
    import shutil

    from datasheet_analyzer.publish.search_index import (
        build_search_index,
        write_search_index,
    )
    from datasheet_analyzer.structure.corpus import SectionPlan

    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("figures"))
    manifest = CorpusManifest.model_validate_json(
        (dst / "manifest.json").read_text(encoding="utf-8")
    )
    plans: dict[str, list[SectionPlan]] = {}
    for sec in manifest.sections:
        doc_dir, _, rel = sec.file.partition("/sections/")
        plans.setdefault(doc_dir, []).append(
            SectionPlan(
                section=SectionNode(number=sec.number, title=sec.title),
                file=f"sections/{rel}",
                markdown=(dst / sec.file).read_text(encoding="utf-8"),
                token_count=sec.token_count,
            )
        )
    for doc_dir, doc_plans in plans.items():
        write_search_index(
            dst / doc_dir,
            build_search_index(
                doc_plans,
                part_number=manifest.part_number,
                doc_hash=doc_dir.rsplit("-", 1)[-1],
            ),
        )
    return dst


@pytest.mark.integration
class TestGoldenPathsOnTheReferenceCorpora:
    """Phase 5, ticket 09 — the two new golden paths on the TI reference parts.

    The gate proves them on the four layout-floor corpora; these are the
    other two of the six built parts, and the ones with the most to lose: 39
    sections and 619 spec rows on AFE7950, and on AFE7953 a corpus published
    before half of this phase existed.

    Both are judged by the shipped verifiers — the code `dsa verify` runs —
    against the ground truth the sets already carried.
    """

    BUDGET = 3000

    def test_afe7950_answers_its_ask_path_golden(self, built, capsys):
        from datasheet_analyzer.evalh.citations import verify_ask_queries

        result, _ = built
        results = verify_ask_queries(
            load_golden_yaml(GOLDEN), result.part_dir, budget=self.BUDGET
        )
        assert results, "AFE7950 carries no ask-path question"
        assert [r.question.id for r in results if not r.ok] == []
        with capsys.disabled():
            for r in results:
                print(f"\nask-path golden, AFE7950: {r.question.id} -> "
                      f"{r.route}, {r.detail}\n")

    def test_afe7950_ranks_the_answering_section_first(self, built, capsys):
        from datasheet_analyzer.evalh.citations import verify_search_queries

        result, _ = built
        results = verify_search_queries(load_golden_yaml(GOLDEN), result.part_dir)
        assert results, "AFE7950 carries no search-path question"
        assert [(r.question.id, r.detail) for r in results if not r.ok] == []
        with capsys.disabled():
            for r in results:
                print(f"\nsearch-path golden, AFE7950: {r.question.id} -> "
                      f"{r.detail}\n")

    def test_afe7953_answers_its_ask_path_golden(self, capsys):
        """The ask path needs no search index when a record answers, so this
        runs against the committed corpus exactly as a user's would."""
        from datasheet_analyzer.evalh.citations import verify_ask_queries

        if not (PARTS / "AFE7953" / "manifest.json").exists():
            pytest.skip("committed parts/AFE7953 corpus not present")
        golden = TestAnswerPacksOnAfe7953.GOLDEN
        results = verify_ask_queries(
            load_golden_yaml(golden), PARTS / "AFE7953", budget=self.BUDGET
        )
        assert results
        assert [r.question.id for r in results if not r.ok] == []
        with capsys.disabled():
            for r in results:
                print(f"\nask-path golden, AFE7953: {r.question.id} -> "
                      f"{r.route}, {r.detail}\n")

    def test_afe7953_search_path_needs_the_index_the_corpus_predates(
        self, tmp_path, capsys
    ):
        """Two facts, in one test, because they are the same fact.

        Against the committed corpus the search-path golden **fails, loudly**:
        that corpus has no index, so the path never ran and nothing was
        established — which is exactly what the verifier must say rather than
        pass or shrug. Given the index that publish now writes, the same
        question puts the answering section at rank 1.
        """
        from datasheet_analyzer.evalh.citations import verify_search_queries
        from datasheet_analyzer.retrieve import clear_index_cache

        if not (PARTS / "AFE7953" / "manifest.json").exists():
            pytest.skip("committed parts/AFE7953 corpus not present")
        questions = load_golden_yaml(TestAnswerPacksOnAfe7953.GOLDEN)

        (stale,) = verify_search_queries(questions, PARTS / "AFE7953")
        assert not stale.ok
        assert "search unavailable" in stale.detail

        indexed = search_index_committed_corpus(
            PARTS / "AFE7953", tmp_path / "AFE7953"
        )
        clear_index_cache()
        (fresh,) = verify_search_queries(questions, indexed)
        assert fresh.ok, fresh.detail
        with capsys.disabled():
            print(f"\nsearch-path golden, AFE7953 (index rebuilt from the "
                  f"published markdown): {fresh.detail}\n")


@pytest.mark.integration
class TestCommittedReferenceCorpora:
    """Phase 5, ticket 04, box 5 — the sixth built part's mix.

    Five of the six built parts are graded by a build that happens inside the
    test suite. AFE7953 cannot be: no recorded TI pages exist for it. Its mix
    is measured off the committed corpus instead, by a regrade that must first
    reproduce a real build exactly.
    """

    def test_regrade_matches_a_fresh_build(self, built, afe7950_pdf):
        """The method check. Regrading the committed AFE7950 corpus must
        reproduce, exactly, the mix the freshly built AFE7950 corpus recorded
        in its manifest — otherwise the AFE7953 number below means nothing."""
        if not (PARTS / "AFE7950" / "manifest.json").exists():
            pytest.skip("committed parts/AFE7950 corpus not present")
        result, _ = built
        stats = result.manifest.stats
        measured = regrade_committed_corpus(PARTS / "AFE7950", afe7950_pdf)
        assert measured["unmatched"] == 0
        assert measured["specs"] == stats.spec_confidence
        assert measured["plots"] == stats.plot_confidence

    def test_afe7953_confidence_mix_is_measured(self, afe7953_pdf, capsys):
        """The sixth part, recorded for the phase report."""
        if not (PARTS / "AFE7953" / "manifest.json").exists():
            pytest.skip("committed parts/AFE7953 corpus not present")
        measured = regrade_committed_corpus(PARTS / "AFE7953", afe7953_pdf)
        assert measured["unmatched"] == 0
        # complete: every record got a grade, none read `unknown`
        assert sum(measured["specs"].values()) == measured["n_specs"] > 0
        assert sum(measured["plots"].values()) == measured["n_plots"] > 0
        assert "unknown" not in measured["specs"]
        assert "unknown" not in measured["plots"]
        # the TI half of the rule: real HTML tables are never rescued, so the
        # mix is dominated by `high` exactly as AFE7950's is
        assert measured["specs"]["high"] > measured["specs"]["medium"]
        with capsys.disabled():
            print(f"\nconfidence mix, AFE7953: specs {measured['specs']} "
                  f"plots {measured['plots']}\n")


@pytest.mark.integration
class TestTheReferencePartsPrintNoPinTable:
    """Phase 6, ticket 04 — the fifth and sixth built parts, honestly empty.

    The ticket asks that pin tables extract for all six built parts *or* that
    the part publishes no `pins.json` rather than a partial one. AFE7950 and
    AFE7953 are the "or": their datasheets are specification documents — 39
    sections of characteristics and typical-characteristics galleries — and
    neither prints a pin section at all. There is nothing to extract, nothing
    to reject, and therefore no pin file and no recorded reason: an absence in
    the *document* is not a finding about the extraction.

    Asserted rather than assumed, because "this part has no pins.json" would
    otherwise be indistinguishable from a pin reader that silently stopped
    working.
    """

    def test_the_fresh_afe7950_build_publishes_no_pin_file(self, built):
        result, _ = built
        assert result.manifest.stats.n_pins == 0
        assert result.manifest.stats.pin_confidence == {}
        assert not list((result.part_dir / "docs").glob("*/pins.json"))
        # nothing was rejected either — the datasheet simply has no pin table
        assert not [
            reason
            for stats in result.manifest.extraction_stats.values()
            for reason in stats.rejection_reasons
            if reason.startswith("device-table")
        ]

    def test_a_pin_lookup_on_afe7950_establishes_nothing_and_says_so(self, built):
        from datasheet_analyzer.retrieve import Retriever

        result, _ = built
        retriever = Retriever.for_part(result.part_dir)
        assert retriever.pins() == []
        assert "establishes nothing" in retriever.pin_gap()

    @pytest.mark.parametrize("part", ["AFE7950", "AFE7953"])
    def test_neither_reference_datasheet_prints_a_pin_section(self, part):
        """The reason there is nothing to extract, stated as a fact about the
        committed corpora rather than as a claim in a report."""
        manifest_path = PARTS / part / "manifest.json"
        if not manifest_path.exists():
            pytest.skip(f"committed parts/{part} corpus not present")
        manifest = CorpusManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        titles = [s.title.lower() for s in manifest.sections]
        assert titles, part
        assert not [t for t in titles if "pin" in t], titles
