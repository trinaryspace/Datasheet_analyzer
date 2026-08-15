"""Per-record confidence (Phase 5, ticket 04).

What these prove:

- each of the three grades is produced by a targeted fixture — a pinned clean
  row (`high`), a section-range row (`medium`), a retry-ladder-rescued row
  (`low`) — and `low` wins whenever two clauses disagree;
- the `low` inputs are **measured, not assumed**: the layout engine records
  whether a grid was reconstructed from the table's own header-declared
  columns or only from a rescue split, proven on two real PDFs built in-test;
- `expect_unit` still only ever *ranks* in retrieval — lowering a grade is not
  filtering, and the unitless record is still returned;
- the schema change is additive: a corpus with no grade on disk loads and
  reads `unknown`, never a fabricated `high`;
- the mix is recorded per part in the manifest and printed by `dsa status`;
- every answer path renders the grade: `dsa query` and `dsa plots`, text and
  `--json`.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.acquire import append_to_inventory, register_source
from datasheet_analyzer.config import Settings
from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.models import (
    RECONSTRUCTION_HEADER,
    RECONSTRUCTION_RESCUED,
    Confidence,
    CorpusManifest,
    PlotRecord,
    PlotSet,
    SectionFile,
    SectionNode,
    SpecRecord,
    SpecSet,
    SpecUnit,
    TableBlock,
)
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.retrieve import Retriever
from datasheet_analyzer.structure.confidence import grade_of, grade_plot_record, mix
from datasheet_analyzer.structure.specs import build_specset, table_to_records

DOC = "datasheet-a1b2c3d4"
DOC_HASH = "a1b2c3d4" + "0" * 56
PAGE_W, PAGE_H = 612.0, 792.0

HEADERS = ["PARAMETER", "MIN", "TYP", "MAX", "UNIT"]


def _table(**kwargs) -> TableBlock:
    """A one-row parametric grid, header-declared and pinned unless told not to."""
    defaults = {
        "headers": HEADERS,
        "grid": [["TJ Operating junction temperature", "-40", "", "105", "°C"]],
        "page": 7,
        "reconstruction": RECONSTRUCTION_HEADER,
    }
    return TableBlock(**{**defaults, **kwargs})


def _section(**kwargs) -> SectionNode:
    defaults = {
        "number": "4.3",
        "title": "Recommended Operating Conditions",
        "page_start": 7,
        "page_end": 7,
    }
    return SectionNode(**{**defaults, **kwargs})


def _only(table: TableBlock, section: SectionNode) -> SpecRecord:
    records, _info = table_to_records(section, table, 0)
    assert len(records) == 1
    return records[0]


class TestEachGradeHasAFixture:
    """The ticket's rule table, one targeted fixture per row of it."""

    def test_pinned_clean_row_is_high(self):
        record = _only(_table(), _section())
        assert record.page == 7
        assert record.confidence is Confidence.HIGH

    def test_section_range_row_is_medium(self):
        # unpinned table inside a multi-page section: the row's page is the
        # section's start, which is a range, not a printed page
        record = _only(_table(page=None), _section(page_start=7, page_end=13))
        assert record.page == 7
        assert record.confidence is Confidence.MEDIUM

    def test_a_one_page_section_still_pins_the_row(self):
        """A section that occupies one page cites that page unambiguously —
        the range and the printed page are the same number."""
        record = _only(_table(page=None), _section(page_start=7, page_end=7))
        assert record.confidence is Confidence.HIGH

    def test_a_row_with_no_value_at_all_is_medium(self):
        table = _table(grid=[["ANALOG SUPPLY VOLTAGE RANGE", "", "", "", ""]])
        assert _only(table, _section()).confidence is Confidence.MEDIUM

    def test_retry_ladder_rescued_row_is_low(self):
        table = _table(reconstruction=RECONSTRUCTION_RESCUED)
        assert _only(table, _section()).confidence is Confidence.LOW

    def test_unit_missing_where_the_lexicon_expects_one_is_low(self):
        """`TJ` is an alias family with `expect_unit: °C`; a TJ row that
        printed no unit at all is a reconstruction to check on the page."""
        table = _table(
            grid=[["TJ Operating junction temperature", "-40", "", "105", ""]]
        )
        record = _only(table, _section())
        assert record.unit.canonical == ""
        assert record.confidence is Confidence.LOW

    def test_a_unit_the_lexicon_never_expected_is_not_punished(self):
        """No alias entry, no expectation: a unitless row of an unknown
        parameter is graded on its page and its values like any other."""
        table = _table(grid=[["Widget flange torque index", "1", "", "3", ""]])
        assert _only(table, _section()).confidence is Confidence.HIGH

    def test_low_beats_medium_when_both_apply(self):
        table = _table(page=None, reconstruction=RECONSTRUCTION_RESCUED)
        record = _only(table, _section(page_start=7, page_end=13))
        assert record.confidence is Confidence.LOW

    def test_grading_never_touches_the_answer(self):
        """A grade is metadata: the row's values and its page are byte-identical
        whether it grades high or low."""
        clean = _only(_table(), _section())
        rescued = _only(_table(reconstruction=RECONSTRUCTION_RESCUED), _section())
        assert clean.confidence is not rescued.confidence
        for field in ("symbol", "name", "min", "typ", "max", "value", "page"):
            assert getattr(clean, field) == getattr(rescued, field)
        assert clean.unit == rescued.unit
        assert clean.row_verbatim == rescued.row_verbatim


class TestLoweringAGradeIsNotFiltering:
    def test_the_unitless_record_is_still_an_answer(self, tmp_path):
        """`expect_unit` lowers this row's grade; retrieval must still return
        it, ranked exactly as before. Honesty over tidiness."""
        part = _write_part(
            tmp_path / "AFE7950",
            [
                SpecRecord(symbol="TJ", name="Junction temperature", max="150",
                           page=4, confidence=Confidence.LOW),
                SpecRecord(symbol="TJ", name="Operating junction temperature",
                           max="105", page=6, confidence=Confidence.HIGH,
                           unit=SpecUnit(verbatim="°C", canonical="°C")),
            ],
        )
        hits = Retriever.for_part(part).specs(name="junction temperature")
        assert [h.confidence for h in hits] == ["high", "low"]
        assert "150" in {h.record.max for h in hits}


class TestPlotGrades:
    def test_exact_page_and_caption_is_high(self):
        rec = PlotRecord(caption="Figure 4-1 TX Output", page_start=29, page_end=29)
        assert grade_plot_record(rec) is Confidence.HIGH

    def test_section_range_page_is_medium(self):
        rec = PlotRecord(caption="Figure 4-1 TX Output", page_start=29, page_end=37)
        assert grade_plot_record(rec) is Confidence.MEDIUM

    def test_captionless_figure_is_medium(self):
        rec = PlotRecord(caption="  ", page_start=29, page_end=29)
        assert grade_plot_record(rec) is Confidence.MEDIUM

    def test_uncitable_figure_is_low(self):
        assert grade_plot_record(PlotRecord(caption="Figure 4-1")) is Confidence.LOW

    def test_build_plotset_grades_every_record(self):
        from datasheet_analyzer.models import FigureRef, RawDocument, SourceDocument
        from datasheet_analyzer.structure.plots import build_plotset

        raw = RawDocument(
            source=SourceDocument(content_hash="f" * 64, path="x.pdf"),
            sections=[
                SectionNode(number="4.12", title="TX", page_start=29, page_end=29,
                            figures=[FigureRef(caption="Figure 4-1 TX Output")]),
                SectionNode(number="4.13", title="RX", page_start=30, page_end=37,
                            figures=[FigureRef(caption="Figure 4-2 RX Output")]),
            ],
        )
        grades = [p.confidence for p in build_plotset(raw, "TEST").plots]
        assert grades == [Confidence.HIGH, Confidence.MEDIUM]


def _make_pdf(path: Path, pages, toc=None) -> None:
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text in lines:
            page.insert_text((x, y), text)
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()


def _header_declared_page() -> list[tuple[float, float, str]]:
    """A grid whose header row declares the columns its data actually uses."""
    return [
        (56.0, 140.0, "Table 3. DAC DC Specifications"),
        (56.0, 153.0, "Parameter"),
        (222.0, 153.0, "Test Conditions/Comments"),
        (435.0, 153.0, "Min"),
        (460.0, 153.0, "Typ"),
        (515.0, 153.0, "Max"),
        (548.0, 153.0, "Unit"),
        (56.0, 166.0, "DAC RESOLUTION"),
        (435.0, 166.0, "16"),
        (548.0, 166.0, "Bit"),
        (62.4, 179.0, "Gain Error"),
        (460.0, 179.0, "1.5"),
        (548.0, 179.0, "% FSR"),
    ]


def _rescue_only_page() -> list[tuple[float, float, str]]:
    """A grid the header row does *not* describe: every data word starts left
    of the column edge its header declares, so the header-anchored split fails
    the gate and only a coarser all-word split reconstructs anything. The
    resulting grid is measurably skewed (values land under the wrong header) —
    which is exactly what makes its rows `low`."""
    rows = [
        (56.0, 140.0, "Table 4. ADC DC Specifications"),
        (120.0, 153.0, "Parameter"),
        (300.0, 153.0, "Min"),
        (400.0, 153.0, "Typ"),
        (500.0, 153.0, "Unit"),
    ]
    for i, y in enumerate((166.0, 179.0, 192.0)):
        rows += [
            (56.0, y, f"ADC PARAM {i}"),
            (290.0, y, f"{i + 1}.0"),
            (395.0, y, f"{i + 1}.5"),
            (505.0, y, "V"),
        ]
    return rows


def _extract(path: Path) -> object:
    source = register_source(path, part_number="P1", doc_type="datasheet")
    return PdfLayoutBackend().extract(source)


class TestReconstructionProvenanceIsMeasured:
    """The `low` rule's first clause is a fact the layout engine records, not a
    guess made later: which rung of the retry ladder actually won."""

    def test_header_declared_columns_are_recorded_as_the_first_try(self, tmp_path):
        pdf = tmp_path / "declared.pdf"
        _make_pdf(pdf, [_header_declared_page()], toc=[[1, "1 Spec", 1]])
        tables = [t for s in _extract(pdf).sections for t in s.tables]
        assert [t.reconstruction for t in tables] == [RECONSTRUCTION_HEADER]

    def test_a_grid_only_a_rescue_split_reconstructs_says_so(self, tmp_path):
        pdf = tmp_path / "rescued.pdf"
        _make_pdf(pdf, [_rescue_only_page()], toc=[[1, "1 Spec", 1]])
        tables = [t for s in _extract(pdf).sections for t in s.tables]
        assert [t.reconstruction for t in tables] == [RECONSTRUCTION_RESCUED]

    def test_the_two_pdfs_grade_their_rows_differently_end_to_end(self, tmp_path):
        declared, rescued = tmp_path / "d.pdf", tmp_path / "r.pdf"
        _make_pdf(declared, [_header_declared_page()], toc=[[1, "1 Spec", 1]])
        _make_pdf(rescued, [_rescue_only_page()], toc=[[1, "1 Spec", 1]])
        good = build_specset(_extract(declared), "P1").records
        bad = build_specset(_extract(rescued), "P1").records
        assert good and bad
        assert {r.confidence for r in good} == {Confidence.HIGH}
        assert {r.confidence for r in bad} == {Confidence.LOW}


class TestSchemaIsAdditive:
    def test_a_corpus_with_no_grade_on_disk_reads_unknown(self, tmp_path):
        """The pre-ticket-04 shape: specs.json rows with no `confidence` key."""
        doc_dir = tmp_path / "P1" / "docs" / DOC
        doc_dir.mkdir(parents=True)
        legacy = {
            "schema_version": "1",
            "part_number": "P1",
            "doc_hash": DOC_HASH,
            "records": [{"symbol": "DACRES", "name": "DAC resolution",
                         "typ": "14", "page": 7}],
            "tables": [],
        }
        (doc_dir / "specs.json").write_text(json.dumps(legacy), encoding="utf-8")
        loaded = SpecSet.model_validate_json(
            (doc_dir / "specs.json").read_text(encoding="utf-8")
        )
        assert loaded.records[0].confidence is Confidence.UNKNOWN
        hits = Retriever.for_part(tmp_path / "P1").specs(symbol="DACRES")
        assert [h.confidence for h in hits] == ["unknown"]

    def test_a_grade_survives_the_json_round_trip(self):
        record = SpecRecord(symbol="TJ", confidence=Confidence.LOW)
        again = SpecRecord.model_validate_json(record.model_dump_json())
        assert again.confidence is Confidence.LOW
        assert '"confidence":"low"' in record.model_dump_json().replace(" ", "")

    def test_a_plot_with_no_grade_on_disk_reads_unknown(self):
        plots = PlotSet.model_validate_json(
            json.dumps({"plots": [{"id": "4.1-f001", "caption": "Figure 1"}]})
        )
        assert plots.plots[0].confidence is Confidence.UNKNOWN

    def test_an_unreadable_grade_degrades_instead_of_lying(self):
        """`grade_of` is what the mix counts with; anything it does not
        recognise is ungraded, never assumed good."""

        class Odd:
            confidence = "excellent"

        assert grade_of(Odd()) is Confidence.UNKNOWN
        assert grade_of(SpecRecord()) is Confidence.UNKNOWN


class TestTheMix:
    def test_counts_every_grade_and_stays_quiet_about_unknown(self):
        records = [
            SpecRecord(confidence=Confidence.HIGH),
            SpecRecord(confidence=Confidence.LOW),
            SpecRecord(confidence=Confidence.LOW),
        ]
        assert mix(records) == {"high": 1, "medium": 0, "low": 2}

    def test_an_ungraded_record_shows_up_as_unknown(self):
        assert mix([SpecRecord()]) == {
            "high": 0, "medium": 0, "low": 0, "unknown": 1
        }


def _build_part(tmp_path: Path, settings: Settings) -> object:
    pdf = tmp_path / "graded.pdf"
    _make_pdf(pdf, [_header_declared_page()], toc=[[1, "1 Spec", 1]])
    source = register_source(pdf, part_number="P1", doc_type="datasheet")
    append_to_inventory([source], settings.parts_dir / "P1")
    return build_part(pdf, part_number="P1", settings=settings, vendor="unknown",
                      use_llm=False)


class TestManifestAndStatus:
    @pytest.fixture
    def settings(self, tmp_path) -> Settings:
        return Settings(parts_dir=tmp_path / "parts",
                        cache_dir=tmp_path / ".cache").resolve()

    def test_the_manifest_records_the_part_mix(self, tmp_path, settings):
        result = _build_part(tmp_path, settings)
        stats = result.manifest.stats
        assert stats.n_specs == 2
        assert stats.spec_confidence == {"high": 2, "medium": 0, "low": 0}
        # round-trips with the manifest like every other stat
        again = CorpusManifest.model_validate_json(
            (result.part_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert again.stats.spec_confidence == stats.spec_confidence

    def test_status_prints_the_mix(self, tmp_path, settings, monkeypatch, capsys):
        _build_part(tmp_path, settings)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["status"]) == 0
        out = capsys.readouterr().out
        assert "confidence: specs 2 high / 0 medium / 0 low" in out

    def test_status_says_nothing_about_an_ungraded_corpus(
        self, tmp_path, settings, monkeypatch, capsys
    ):
        """A corpus built before grading existed prints no line at all, rather
        than zeros that would read like a graded corpus with no confidence."""
        part = settings.parts_dir / "OLD"
        _write_part(part, [SpecRecord(symbol="DACRES", typ="14", page=7)])
        (part / "INDEX.md").write_text("# OLD\n", encoding="utf-8")
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["status"]) == 0
        assert "confidence:" not in capsys.readouterr().out


def _write_part(part_dir: Path, records: list[SpecRecord],
                plots: list[PlotRecord] | None = None) -> Path:
    """A structurally real corpus whose specs/plots are exactly `records`."""
    doc_dir = part_dir / "docs" / DOC
    doc_dir.mkdir(parents=True, exist_ok=True)
    for i, rec in enumerate(records):
        rec.row_index = i
    (doc_dir / "specs.json").write_text(
        SpecSet(schema_version="1", part_number=part_dir.name, doc_hash=DOC_HASH,
                records=records).model_dump_json(),
        encoding="utf-8",
    )
    if plots is not None:
        (doc_dir / "plots.json").write_text(
            PlotSet(schema_version="1", part_number=part_dir.name,
                    doc_hash=DOC_HASH, plots=plots).model_dump_json(),
            encoding="utf-8",
        )
    (part_dir / "manifest.json").write_text(
        CorpusManifest(
            part_number=part_dir.name,
            pipeline_version="0.4.0",
            sections=[
                SectionFile(number="4.3", title="Recommended Operating Conditions",
                            file=f"docs/{DOC}/sections/4-3.md", doc_hash=DOC_HASH,
                            page_start=4, page_end=6)
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    return part_dir


class TestEveryAnswerPathRendersTheGrade:
    @pytest.fixture
    def settings(self, tmp_path, monkeypatch) -> Settings:
        _write_part(
            tmp_path / "parts" / "P1",
            [
                SpecRecord(symbol="DACRES", name="DAC resolution", typ="14",
                           page=7, section="4.5", confidence=Confidence.HIGH,
                           unit=SpecUnit(verbatim="bits", canonical="bits")),
            ],
            plots=[
                PlotRecord(id="4.12-f001", section="4.12",
                           caption="Figure 4-1 TX Output Fullscale",
                           page_start=29, page_end=37, tags=["tx"],
                           confidence=Confidence.MEDIUM),
            ],
        )
        resolved = Settings(parts_dir=tmp_path / "parts",
                            cache_dir=tmp_path / ".cache").resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: resolved)
        return resolved

    def test_query_text_shows_the_grade(self, settings, capsys):
        assert cli.main(["query", "--part", "P1", "--symbol", "DACRES"]) == 0
        assert "· high]" in capsys.readouterr().out

    def test_query_json_carries_the_grade(self, settings, capsys):
        assert cli.main(["query", "--part", "P1", "--symbol", "DACRES", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["hits"][0]["confidence"] == "high"

    def test_plots_text_shows_the_grade(self, settings, capsys):
        assert cli.main(["plots", "--part", "P1", "--q", "fullscale"]) == 0
        out = capsys.readouterr().out
        assert "Figure 4-1 TX Output Fullscale" in out
        assert "· medium]" in out

    def test_plots_json_carries_the_grade_and_the_citation(self, settings, capsys):
        assert cli.main(["plots", "--part", "P1", "--q", "fullscale", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        hit = payload["hits"][0]
        assert hit["confidence"] == "medium"
        assert hit["citation"] == "§4.12, p.29-37"
        assert hit["matched_via"] == "caption"
