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
