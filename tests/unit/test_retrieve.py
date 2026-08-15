"""The retrieval core seam (Phase 5, ticket 01).

`retrieve/` is the single implementation of every corpus lookup:

- `CorpusIndex` loads a part once and caches it on corpus identity
  (part dir + manifest.json mtime/size + PIPELINE_VERSION), so an MCP-style
  session asking twenty questions parses the JSON once — asserted by counting
  file reads, never by timing;
- a rebuilt corpus invalidates that cache by construction;
- `Retriever` returns typed hits carrying doc, page/range and `matched_via`,
  so no front end builds a citation string of its own;
- `query.py` keeps its signatures but delegates;
- `cli.py` formats only — the guard test below fails if retrieval logic
  creeps back into it;
- corrupt corpus JSON degrades with a warning, never a crash.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.models import (
    CorpusManifest,
    PlotRecord,
    PlotSet,
    SectionFile,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.query import SpecQuery, find_plots
from datasheet_analyzer.retrieve import Citation, CorpusIndex, Retriever

DOC = "datasheet-a1b2c3d4"
DOC_HASH = "a1b2c3d4" + "0" * 56


def _spec_records() -> list[SpecRecord]:
    return [
        SpecRecord(
            section="4.5",
            table_index=0,
            row_index=0,
            symbol="DACRES",
            name="DAC resolution",
            typ="14",
            unit=SpecUnit(verbatim="bits", canonical="bits"),
            page=7,
        ),
        SpecRecord(
            section="4.3",
            table_index=0,
            row_index=0,
            symbol="TJ",
            name="Operating junction temperature",
            max="105",
            unit=SpecUnit(verbatim="°C", canonical="°C"),
            page=6,
        ),
        SpecRecord(
            section="4.3",
            table_index=0,
            row_index=1,
            symbol="VDD1P2",
            name="1.2V supply",
            min="1.15",
            unit=SpecUnit(verbatim="V", canonical="V"),
            # deliberately unpinned: the citation must stay honestly p.?
            page=None,
        ),
    ]


def _plot_records() -> list[PlotRecord]:
    return [
        PlotRecord(
            id="4.12.1-f001",
            section="4.12.1",
            caption="Figure 4-1 TX Output Fullscale vs Output Frequency",
            conditions="DSA = 0",
            page_start=29,
            page_end=37,
            file=f"docs/{DOC}/figures/4.12.1-f001.png",
            tags=["tx", "fullscale"],
        ),
        PlotRecord(
            id="4.12.8-f001",
            section="4.12.8",
            caption="Figure 4-100 RX Input Fullscale vs Frequency",
            conditions="gain = max",
            page_start=38,
            page_end=38,
            tags=["rx", "fullscale"],
        ),
    ]


def _write_part(part_dir: Path) -> Path:
    """A minimal but structurally real built corpus."""
    doc_dir = part_dir / "docs" / DOC
    (doc_dir / "sections").mkdir(parents=True, exist_ok=True)
    (doc_dir / "sections" / "4-5.md").write_text(
        "<!-- source: datasheet p.7 -->\n# 4.5 DAC\nDAC resolution 14 bits.\n",
        encoding="utf-8",
    )
    (doc_dir / "specs.json").write_text(
        SpecSet(
            schema_version="1",
            part_number="TEST",
            doc_hash=DOC_HASH,
            records=_spec_records(),
        ).model_dump_json(),
        encoding="utf-8",
    )
    (doc_dir / "plots.json").write_text(
        PlotSet(
            schema_version="1",
            part_number="TEST",
            doc_hash=DOC_HASH,
            plots=_plot_records(),
        ).model_dump_json(),
        encoding="utf-8",
    )
    manifest = CorpusManifest(
        part_number="TEST",
        pipeline_version="0.4.0",
        sections=[
            SectionFile(
                number="4.5",
                title="DAC Electrical Characteristics",
                file=f"docs/{DOC}/sections/4-5.md",
                doc_hash=DOC_HASH,
                page_start=7,
                page_end=8,
            ),
            SectionFile(
                number="4.3",
                title="Recommended Operating Conditions",
                file=f"docs/{DOC}/sections/4-3.md",
                doc_hash=DOC_HASH,
                page_start=6,
                page_end=6,
            ),
        ],
    )
    (part_dir / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return part_dir


@pytest.fixture
def part(tmp_path: Path) -> Path:
    return _write_part(tmp_path / "parts" / "TEST")


@pytest.fixture
def count_reads(monkeypatch) -> list[str]:
    """Every `Path.read_text` performed while the fixture is active."""
    reads: list[str] = []
    original = Path.read_text

    def counting(self, *args, **kwargs):
        reads.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    return reads


class TestCorpusIndex:
    def test_loads_manifest_specs_plots_and_sections(self, part):
        index = CorpusIndex.load(part)
        assert index.part_number == "TEST"
        assert [d.name for d in index.docs] == [DOC]
        assert len(index.docs[0].specs) == 3
        assert len(index.docs[0].plots) == 2
        assert index.docs[0].doc_hash == DOC_HASH
        assert {s.number for s in index.sections} == {"4.5", "4.3"}

    def test_second_load_reuses_cached_index(self, part, count_reads):
        CorpusIndex.load(part)
        after_first = len(count_reads)
        assert after_first >= 3  # manifest + specs.json + plots.json

        CorpusIndex.load(part)
        assert len(count_reads) == after_first, "cached index must re-read nothing"

    def test_manifest_mtime_change_invalidates_cache(self, part, count_reads):
        CorpusIndex.load(part)
        after_first = len(count_reads)

        # A rebuild rewrites manifest.json; bump only the mtime so the test
        # proves mtime alone is load-bearing, with no clock-granularity race.
        manifest = part / "manifest.json"
        bumped = manifest.stat().st_mtime_ns + 10_000_000_000
        os.utime(manifest, ns=(bumped, bumped))

        CorpusIndex.load(part)
        assert len(count_reads) > after_first, "stale index must be dropped"

    def test_rebuilt_corpus_is_visible_after_invalidation(self, part):
        assert len(CorpusIndex.load(part).docs[0].specs) == 3

        specs_path = part / "docs" / DOC / "specs.json"
        specs_path.write_text(
            SpecSet(
                schema_version="1", part_number="TEST", doc_hash=DOC_HASH, records=[]
            ).model_dump_json(),
            encoding="utf-8",
        )
        manifest = part / "manifest.json"
        bumped = manifest.stat().st_mtime_ns + 10_000_000_000
        os.utime(manifest, ns=(bumped, bumped))

        assert CorpusIndex.load(part).docs[0].specs == ()

    def test_unbuilt_part_is_never_cached(self, tmp_path, count_reads):
        """No manifest = no identity to key on; re-read rather than go stale."""
        bare = tmp_path / "BARE"
        (bare / "docs" / DOC).mkdir(parents=True)
        (bare / "docs" / DOC / "specs.json").write_text(
            SpecSet(schema_version="1", part_number="BARE", records=[]).model_dump_json(),
            encoding="utf-8",
        )
        CorpusIndex.load(bare)
        after_first = len(count_reads)
        CorpusIndex.load(bare)
        assert len(count_reads) > after_first

    def test_section_text_is_read_lazily_then_cached(self, part, count_reads):
        index = CorpusIndex.load(part)
        after_load = len(count_reads)
        section = next(s for s in index.sections if s.number == "4.5")

        assert "DAC resolution 14 bits" in index.section_text(section)
        after_read = len(count_reads)
        assert after_read == after_load + 1, "section bodies load only on demand"

        index.section_text(section)
        assert len(count_reads) == after_read


class TestHonestDegradation:
    def test_unreadable_specs_json_warns_and_keeps_going(self, part, caplog):
        (part / "docs" / DOC / "specs.json").write_text("{ not json", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            hits = Retriever.for_part(part).specs(symbol="DACRES")
        assert hits == []
        assert "skipping unreadable specs.json" in caplog.text
        # the sibling plot catalog still answers
        assert Retriever.for_part(part).plots(q="Fullscale")

    def test_unreadable_plots_json_warns_and_keeps_going(self, part, caplog):
        (part / "docs" / DOC / "plots.json").write_text("[]", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            hits = Retriever.for_part(part).plots(q="Fullscale")
        assert hits == []
        assert "skipping unreadable plots.json" in caplog.text
        assert Retriever.for_part(part).specs(symbol="DACRES")

    def test_unreadable_manifest_warns_and_keeps_specs(self, part, caplog):
        (part / "manifest.json").write_text('{"sections": []}', encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            index = CorpusIndex.load(part)
        assert "skipping unreadable manifest.json" in caplog.text
        assert index.manifest is None
        assert index.sections == ()
        assert len(index.docs[0].specs) == 3

    def test_missing_specs_json_is_silent_absence(self, part, caplog):
        (part / "docs" / DOC / "specs.json").unlink()
        with caplog.at_level(logging.WARNING):
            assert Retriever.for_part(part).specs(symbol="DACRES") == []
        assert "unreadable" not in caplog.text

    def test_missing_section_file_reads_as_empty(self, part, caplog):
        index = CorpusIndex.load(part)
        missing = next(s for s in index.sections if s.number == "4.3")
        with caplog.at_level(logging.WARNING):
            assert index.section_text(missing) == ""
        assert "skipping unreadable section file" in caplog.text


class TestTypedResults:
    def test_spec_hit_carries_doc_page_and_matched_via(self, part):
        hit = Retriever.for_part(part).specs(symbol="DACRES")[0]
        assert hit.citation.doc == DOC
        assert hit.citation.doc_hash == DOC_HASH
        assert hit.citation.section == "4.5"
        assert hit.citation.pages == "p.7"
        assert hit.citation.label == "§4.5, p.7"
        assert hit.matched_via == "symbol"
        assert hit.confidence == "unknown"  # ticket 04 grades it

    def test_matched_via_distinguishes_exact_symbol_from_substring(self, part):
        r = Retriever.for_part(part)
        assert r.specs(symbol="dacres")[0].matched_via == "symbol"
        assert r.specs(symbol="ACRE")[0].matched_via == "symbol-substring"
        assert r.specs(name="junction")[0].matched_via == "name-substring"
        assert r.specs(section="4.3")[0].matched_via == "section"
        assert r.specs()[0].matched_via == "all"

    def test_unpinned_page_stays_honest(self, part):
        hit = Retriever.for_part(part).specs(symbol="VDD1P2")[0]
        assert hit.record.page is None
        assert hit.citation.pages == "p.?"

    def test_plot_hit_carries_page_range_and_file(self, part):
        hit = Retriever.for_part(part).plots(caption="TX Output Fullscale")[0]
        assert hit.citation.doc == DOC
        assert hit.citation.pages == "p.29-37"
        assert hit.matched_via == "caption"
        assert hit.file.endswith("4.12.1-f001.png")

    def test_plot_matched_via_reports_the_rung(self, part):
        r = Retriever.for_part(part)
        assert r.plots(q="Fullscale")[0].matched_via == "caption"
        assert r.plots(q="DSA = 0")[0].matched_via == "conditions"
        assert r.plots(section="4.12.8")[0].matched_via == "section"
        assert r.plots(tags=["rx"])[0].matched_via == "tag"

    def test_section_hit_carries_citation(self, part):
        hit = Retriever.for_part(part).sections(number="4.5")[0]
        assert hit.citation.doc == DOC
        assert hit.citation.doc_hash == DOC_HASH
        assert hit.citation.label == "§4.5, p.7-8"
        assert hit.matched_via == "number"

    def test_sections_by_covered_page(self, part):
        hits = Retriever.for_part(part).sections(page=8)
        assert [h.section.number for h in hits] == ["4.5"]
        assert hits[0].matched_via == "page"
        assert Retriever.for_part(part).sections(page=99) == []

    def test_citation_renders_without_a_section(self):
        assert Citation(page_start=6).label == "p.6"
        assert Citation().label == "p.?"


class TestQueryShimDelegates:
    def test_spec_query_goes_through_the_retriever(self, part, monkeypatch):
        seen: list[dict] = []
        original = Retriever.specs

        def spy(self, **kwargs):
            seen.append(kwargs)
            return original(self, **kwargs)

        monkeypatch.setattr(Retriever, "specs", spy)
        recs = SpecQuery(part).find(symbol="DACRES", section="4.5")
        assert seen == [{"symbol": "DACRES", "name": "", "section": "4.5"}]
        assert [r.symbol for r in recs] == ["DACRES"]
        assert all(isinstance(r, SpecRecord) for r in recs)

    def test_find_plots_goes_through_the_retriever(self, part, monkeypatch):
        seen: list[dict] = []
        original = Retriever.plots

        def spy(self, **kwargs):
            seen.append(kwargs)
            return original(self, **kwargs)

        monkeypatch.setattr(Retriever, "plots", spy)
        recs = find_plots(part, q="Fullscale", tags=["tx"])
        assert seen and seen[0]["q"] == "Fullscale" and seen[0]["tags"] == ["tx"]
        assert [r.id for r in recs] == ["4.12.1-f001"]
        assert all(isinstance(r, PlotRecord) for r in recs)

    def test_repeat_shim_lookups_reuse_the_cached_index(self, part, count_reads):
        SpecQuery(part).find(symbol="DACRES")
        after_first = len(count_reads)
        assert after_first >= 3

        SpecQuery(part).find(symbol="TJ")
        find_plots(part, q="Fullscale")
        assert len(count_reads) == after_first


class TestCliIsFormatOnly:
    """`cli.py` must never regain a retrieval implementation of its own.

    A grep-shaped guard is crude, but it is the only assertion that fails the
    moment someone re-inlines a `rglob`/`specs.json` walk or hand-builds a
    citation in a front end — which is exactly the drift the seam prevents.
    """

    SOURCE = Path(cli.__file__).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "token",
        [
            "rglob",              # walking the corpus
            "specs.json",         # parsing corpus artifacts
            "plots.json",
            "search_index.json",
            "model_validate_json",
            "SpecSet",
            "PlotSet",
            "SpecRecord",
            "PlotRecord",
            "SearchIndex",
            "bm25",               # ranking belongs to retrieve/search.py
            "§",                  # hand-built citation strings
            "p.{",
        ],
    )
    def test_cli_source_has_no_retrieval_logic(self, token):
        assert token not in self.SOURCE

    def test_cli_query_still_answers_through_the_core(self, part, monkeypatch, capsys):
        from datasheet_analyzer.config import Settings

        settings = Settings(parts_dir=part.parent, cache_dir=part.parent / ".cache").resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)

        assert cli.main(["query", "--part", "TEST", "--symbol", "DACRES"]) == 0
        out = capsys.readouterr().out
        assert "§4.5, p.7" in out

    def test_cli_plots_still_answers_through_the_core(self, part, monkeypatch, capsys):
        from datasheet_analyzer.config import Settings

        settings = Settings(parts_dir=part.parent, cache_dir=part.parent / ".cache").resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)

        assert cli.main(["plots", "--part", "TEST", "--q", "Fullscale"]) == 0
        out = capsys.readouterr().out
        assert "p.29-37" in out
