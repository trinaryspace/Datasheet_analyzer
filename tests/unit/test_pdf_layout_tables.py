"""pdf_layout tables — caption-anchored hypotheses + reconstruction gate.

External corpus behavior only (the spec's single seam): synthetic fitz-built
PDFs through `build_part` with temp-dir settings; assertions land on the
published corpus product — section markdown + CSV twins, specs.json records
resolved through the user-facing `SpecQuery`, manifest extraction stats, and
page-pin verification against the PDF's own page text. No engine internals.

Geometry models real datasheets (AD9081 page 5): a 6-column spec table with
partial rulings (no vertical lines between Min/Typ/Max), an indented
sub-row column (param at x=56, sub-rows at x=62.4), a test-conditions
preamble paragraph above the caption, numbered footnote lines below the
last row, and 13pt row pitch with 11pt wrapped lines.

Coverage:
- caption-anchored spec table: atomic block (headers/grid/caption/conditions/
  CSV twin), specs.json roles incl. the "Test Conditions/Comments" variant,
  `SpecQuery` resolution, page pinning verified against the PDF page text;
- honest degradation: captionless tabular clusters -> paragraphs; a
  garbage-spacing layout under a real caption -> no table at all, with the
  rejection recorded in manifest extraction stats;
- region edge cases: multi-line wrapped cells merge into one grid row;
  repeated captions on continuation pages merge into one atomic block;
- mechanics: extraction stats (detected/accepted/rejected/reasons/fidelity)
  on the manifest, stale pre-03 extraction cache ignored by version check.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from datasheet_analyzer.config import Settings
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.query import SpecQuery

PAGE_W, PAGE_H = 612.0, 792.0

# AD9081-style column left edges (x0 of each column's text).
X = {"param": 56.0, "conditions": 222.0, "min": 435.0, "typ": 460.0,
     "max": 515.0, "unit": 548.0}
PITCH = 13.0
CAP_Y = 140.0
HDR_Y = 153.0


def _make_pdf(path: Path, pages, toc: list[list] | None = None,
              drawings: list[tuple[float, float, float, float]] | None = None
              ) -> None:
    """pages: list of pages; each page = list of (x, y, text) lines.
    drawings: optional (x0, y0, x1, y1) ruling strokes drawn on page 1."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text in lines:
            page.insert_text((x, y), text)
    if drawings:
        for x0, y0, x1, y1 in drawings:
            doc[0].draw_line((x0, y0), (x1, y1))
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()


def _spec_header() -> list[tuple[float, float, str]]:
    return [
        (X["param"], HDR_Y, "Parameter"),
        (X["conditions"], HDR_Y, "Test Conditions/Comments"),
        (X["min"], HDR_Y, "Min"),
        (X["typ"], HDR_Y, "Typ"),
        (X["max"], HDR_Y, "Max"),
        (X["unit"], HDR_Y, "Unit"),
    ]


def _build(tmp_path, name: str, pages, toc=None) -> object:
    pdf = Path(tmp_path) / name
    _make_pdf(pdf, pages, toc)
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    return build_part(pdf, part_number="P1", settings=settings,
                      vendor="unknown", use_llm=False)


def _doc_dir(result) -> Path:
    return result.part_dir / "docs" / f"datasheet-{result.manifest.documents[0].content_hash[:8]}"


def _section_md(result, stem: str) -> str:
    path = _doc_dir(result) / "sections" / f"{stem}.md"
    assert path.exists(), f"missing section file {path.name}"
    return path.read_text(encoding="utf-8")


def _blob(result) -> str:
    return "\n".join(
        (result.part_dir / sec.file).read_text(encoding="utf-8")
        for sec in result.manifest.sections
    )


def _specs_path(result) -> Path:
    return _doc_dir(result) / "specs.json"


class TestCaptionAnchoredTables:
    def _pages(self) -> list[list[tuple[float, float, str]]]:
        return [[
            (56.0, 112.0, "Nominal supplies with DAC output current = 26 mA, unless noted."),
            (56.0, 124.0, "For the minimum and maximum values, TA corresponds to 80 C."),
            (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
            *_spec_header(),
            (56.0, HDR_Y + PITCH, "DAC RESOLUTION"),
            (X["min"], HDR_Y + PITCH, "16"),
            (X["unit"], HDR_Y + PITCH, "Bit"),
            (62.4, HDR_Y + 2 * PITCH, "Gain Error"),
            (X["typ"], HDR_Y + 2 * PITCH, "1.5"),
            (X["unit"], HDR_Y + 2 * PITCH, "% FSR"),
            (56.0, HDR_Y + 3 * PITCH, "Integral Nonlinearity (INL)"),
            (X["conditions"], HDR_Y + 3 * PITCH, "Shuffling disabled"),
            (X["typ"], HDR_Y + 3 * PITCH, "8.0"),
            (X["unit"], HDR_Y + 3 * PITCH, "LSB"),
            (62.4, HDR_Y + 4 * PITCH, "Gain Matching"),
            (X["typ"], HDR_Y + 4 * PITCH, "0.7"),
            (X["unit"], HDR_Y + 4 * PITCH, "% FSR"),
            (59.5, CAP_Y + 78.0, "1  For dc-coupled applications, the maximum output current applies."),
            (56.0, CAP_Y + 91.0, "Stresses at or above those listed under the rating table may cause damage."),
        ]]

    def test_spec_table_builds_atomic_block_with_conditions(self, tmp_path):
        result = _build(tmp_path, "t3.pdf", self._pages(),
                        toc=[[1, "1 Specifications", 1]])
        assert result.manifest.stats.n_tables == 1

        md = _section_md(result, "1-specifications")
        assert "## Table 3. DAC DC Specifications" in md
        assert "> **Test conditions:** Nominal supplies with DAC output current = 26 mA," \
               " unless noted. For the minimum and maximum values, TA corresponds to 80 C." in md
        header_md = "| Parameter | Test Conditions/Comments | Min | Typ | Max | Unit |"
        assert header_md in md
        # indented sub-row shares the parameter column; empty cells stay empty
        assert "| Gain Error |  |  | 1.5 |  | % FSR |" in md
        assert "| Integral Nonlinearity (INL) | Shuffling disabled |  | 8.0 |  | LSB |" in md
        # the footnote and the trailing prose stay honest paragraphs, never rows
        assert "1 For dc-coupled applications, the maximum output current applies." in md
        assert "Stresses at or above those listed under the rating table may cause damage." in md
        # the footnote text does not appear as a table row
        table_region = md.split("## Table 3.")[1].split("**Test conditions:**")[1]
        assert "dc-coupled applications" not in table_region

        csv = (_doc_dir(result) / "tables" / "1-specifications-t01.csv").read_text(
            encoding="utf-8")
        assert "Parameter,Test Conditions/Comments,Min,Typ,Max,Unit" in csv
        assert "Integral Nonlinearity (INL),Shuffling disabled,,8.0,,LSB" in csv

    def test_spec_records_resolve_via_query(self, tmp_path):
        result = _build(tmp_path, "t3q.pdf", self._pages(),
                        toc=[[1, "1 Specifications", 1]])
        specs = json.loads(_specs_path(result).read_text(encoding="utf-8"))
        assert specs["records"], "specs.json has no records"

        q = SpecQuery(result.part_dir)
        inl = q.find(symbol="Integral Nonlinearity")
        assert len(inl) == 1
        rec = inl[0]
        assert rec.symbol == "Integral Nonlinearity (INL)"
        assert rec.conditions == "Shuffling disabled"
        assert rec.typ == "8.0" and rec.min == "" and rec.max == ""
        assert rec.unit.canonical == "LSB"
        assert rec.page == 1
        assert rec.section == "1"

        gain = q.find(symbol="Gain Error")
        assert gain[0].typ == "1.5"
        assert gain[0].unit.canonical == "% FSR"

    def test_table_page_pinned_and_verified_against_pdf_text(self, tmp_path):
        pdf = Path(tmp_path) / "t3p.pdf"
        _make_pdf(pdf, self._pages(), toc=[[1, "1 Specifications", 1]])
        settings = Settings(parts_dir=tmp_path / "parts",
                            cache_dir=tmp_path / ".cache").resolve()
        result = build_part(pdf, part_number="P1", settings=settings,
                            vendor="unknown", use_llm=False)
        record = SpecQuery(result.part_dir).find(symbol="Gain Error")[0]
        assert record.page == 1
        # the pinned page's own text must contain the table's cells
        page_text = fitz.open(pdf)[0].get_text()
        for needle in ("Gain Error", "1.5", "% FSR"):
            assert needle in page_text


class TestHonestDegradation:
    def test_captionless_tabular_cluster_stays_paragraphs(self, tmp_path):
        pages = [[
            (56.0, 96.0, "Gain Error"),
            (X["typ"], 96.0, "1.5"),
            (X["unit"], 96.0, "% FSR"),
            (56.0, 109.0, "Gain Matching"),
            (X["typ"], 109.0, "0.7"),
            (X["unit"], 109.0, "% FSR"),
            (56.0, 122.0, "Offset Error"),
            (X["typ"], 122.0, "0.05"),
            (X["unit"], 122.0, "% FSR"),
        ]]
        result = _build(tmp_path, "nocap.pdf", pages)
        assert result.manifest.stats.n_tables == 0
        assert not list(_doc_dir(result).glob("tables/*")), "no CSV twins expected"
        md = _section_md(result, "1-page-1")
        assert "Gain Error" in md and "1.5" in md and "% FSR" in md
        # every aligned line stays an ordinary paragraph — no table anywhere
        assert "| --- |" not in md
        assert "Parameter |" not in md

    def test_garbage_spacing_under_caption_yields_no_table(self, tmp_path):
        # every row scatters its words at positions no other row shares — no
        # column is stable across rows, so the reconstruction gate rejects;
        # the words stay honest paragraphs, nothing is dropped
        pages = [[
            (56.0, 96.0, "Table 7. Noise"),
            (56.0, 120.0, "Alpha Beta Gamma"),
            (300.0, 120.0, "Delta"),
            (166.0, 134.0, "Epsilon Zeta"),
            (450.0, 134.0, "Eta"),
            (86.0, 148.0, "Theta"),
            (380.0, 148.0, "Iota"),
            (240.0, 162.0, "Kappa Lambda"),
            (120.0, 162.0, "Mu"),
        ]]
        result = _build(tmp_path, "garbage.pdf", pages)
        assert result.manifest.stats.n_tables == 0
        doc = result.manifest.documents[0]
        stats = result.manifest.extraction_stats[doc.content_hash]
        assert stats.tables_detected >= 1
        assert stats.tables_accepted == 0
        assert stats.tables_rejected >= 1
        assert stats.rejection_reasons, "rejection reason must be recorded"
        assert any("column" in r for r in stats.rejection_reasons)
        # the words are preserved as paragraphs (nothing is dropped)
        blob = _blob(result)
        for needle in ("Alpha Beta Gamma", "Epsilon Zeta", "Kappa Lambda"):
            assert needle in blob

    def test_dense_unruled_layout_rejected_without_ruling_evidence(self, tmp_path):
        # perfectly row-aligned x positions with every cell filled and zero
        # rulings is geometrically indistinguishable from a dense table only
        # when the PDF draws a ruling; without one the gate stays honest and
        # yields no table
        pages = [[
            (56.0, 96.0, "Table 7. Noise"),
            (56.0, 120.0, "Alpha"),
            (340.0, 120.0, "Beta"),
            (500.0, 120.0, "Gamma"),
            (120.0, 134.0, "Delta"),
            (380.0, 134.0, "Epsilon"),
            (520.0, 134.0, "Zeta"),
            (90.0, 148.0, "Eta"),
            (300.0, 148.0, "Theta"),
            (480.0, 148.0, "Iota"),
            (150.0, 162.0, "Kappa"),
            (290.0, 162.0, "Lambda"),
            (540.0, 162.0, "Mu"),
        ]]
        result = _build(tmp_path, "dense.pdf", pages)
        assert result.manifest.stats.n_tables == 0
        doc = result.manifest.documents[0]
        stats = result.manifest.extraction_stats[doc.content_hash]
        assert stats.tables_rejected >= 1
        assert stats.rejection_reasons, "rejection reason must be recorded"


class TestRegionEdgeCases:
    def test_multiline_wrapped_cell_merges_into_one_row(self, tmp_path):
        pages = [[
            (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
            *_spec_header(),
            (56.0, HDR_Y + PITCH, "Output Common-Mode Voltage"),
            (X["conditions"], HDR_Y + PITCH, "Bias each output to a negative rail"),
            (X["min"], HDR_Y + PITCH, "0"),
            (X["max"], HDR_Y + PITCH, "0.3"),
            (X["unit"], HDR_Y + PITCH, "V"),
            # wrapped continuation: 11pt gap (0.85 * 13pt pitch) -> same row;
            # the continued value sits slightly inside its column, as PDFs do
            (X["conditions"], HDR_Y + PITCH + 11.0, "across a 25 ohm resistor, selected"),
            (X["min"] + 4.0, HDR_Y + PITCH + 11.0, "0.2"),
            (56.0, HDR_Y + PITCH + 24.0, "Differential Resistance"),
            (X["max"], HDR_Y + PITCH + 24.0, "100"),
            (X["unit"], HDR_Y + PITCH + 24.0, "Ohm"),
        ]]
        result = _build(tmp_path, "wrap.pdf", pages)
        md = _section_md(result, "1-page-1")
        # one grid row, one cell with the full wrapped text
        assert ("| Output Common-Mode Voltage | Bias each output to a negative rail"
                " across a 25 ohm resistor, selected | 0 0.2 |  | 0.3 | V |") in md
        # the continuation text must not appear as its own row
        row_blob = md.split("## Table 3.")[1]
        assert "| across a 25 ohm" not in row_blob
        assert "| Differential Resistance |  |  |  | 100 | Ohm |" in md

    def test_repeated_caption_on_continuation_page_merges_block(self, tmp_path):
        page1 = [
            (56.0, CAP_Y, "Table 9. Input Data Rate Specifications"),
            *_spec_header(),
            (56.0, HDR_Y + PITCH, "DAC Data Rate"),
            (X["typ"], HDR_Y + PITCH, "9"),
            (X["unit"], HDR_Y + PITCH, "GSPS"),
            (62.4, HDR_Y + 2 * PITCH, "ADC Data Rate"),
            (X["typ"], HDR_Y + 2 * PITCH, "3"),
            (X["unit"], HDR_Y + 2 * PITCH, "GSPS"),
        ]
        page2 = [
            (56.0, 96.0, "Table 9. Input Data Rate Specifications"),
            (56.0, 120.0, "JESD204 Data Rate"),
            (X["typ"], 120.0, "16"),
            (X["unit"], 120.0, "Gbps"),
            (62.4, 134.0, "SYSREF Data Rate"),
            (X["typ"], 134.0, "300"),
            (X["unit"], 134.0, "MHz"),
        ]
        toc = [[1, "1 Specifications", 1], [1, "2 More", 2]]
        result = _build(tmp_path, "cont.pdf", [page1, page2], toc)
        assert result.manifest.stats.n_tables == 1
        md = _section_md(result, "1-specifications")
        # one atomic block carrying both pages' rows
        assert "| DAC Data Rate |  |  | 9 |  | GSPS |" in md
        assert "| JESD204 Data Rate |  |  | 16 |  | Gbps |" in md
        second = _section_md(result, "2-more")
        assert "JESD204" not in second
        # every row lands in one section; spec records keep page = first page
        records = [r for r in json.loads(_specs_path(result).read_text(encoding="utf-8"))["records"]
                   if r["symbol"] == "JESD204 Data Rate"]
        assert records and records[0]["page"] == 1


class TestMechanics:
    def test_extraction_stats_recorded_in_manifest(self, tmp_path):
        result = _build(tmp_path, "mech.pdf", [
            [
                (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
                *_spec_header(),
                (56.0, HDR_Y + PITCH, "DAC RESOLUTION"),
                (X["min"], HDR_Y + PITCH, "16"),
                (X["unit"], HDR_Y + PITCH, "Bit"),
                (62.4, HDR_Y + 2 * PITCH, "Gain Error"),
                (X["typ"], HDR_Y + 2 * PITCH, "1.5"),
                (X["unit"], HDR_Y + 2 * PITCH, "% FSR"),
            ]
        ])
        doc = result.manifest.documents[0]
        stats = result.manifest.extraction_stats[doc.content_hash]
        assert stats.backend == "pdf_layout"
        assert stats.tables_detected == 1
        assert stats.tables_accepted == 1
        assert stats.tables_rejected == 0
        assert stats.mean_fidelity > 0.9
        assert stats.rejection_reasons == []
        manifest = json.loads((result.part_dir / "manifest.json").read_text(encoding="utf-8"))
        saved = manifest["extraction_stats"][doc.content_hash]
        assert saved["tables_accepted"] == 1 and saved["tables_detected"] == 1

    def test_stale_pre_tables_cache_invalidated_by_version(self, tmp_path):
        page = [
            (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
            *_spec_header(),
            (56.0, HDR_Y + PITCH, "DAC RESOLUTION"),
            (X["min"], HDR_Y + PITCH, "16"),
            (X["unit"], HDR_Y + PITCH, "Bit"),
            (62.4, HDR_Y + 2 * PITCH, "Gain Error"),
            (X["typ"], HDR_Y + 2 * PITCH, "1.5"),
            (X["unit"], HDR_Y + 2 * PITCH, "% FSR"),
        ]
        result = _build(tmp_path, "stale.pdf", [page])
        assert result.manifest.stats.n_tables == 1  # sanity: tables on the first pass
        # rewrite the cache entry as a pre-03 raw (no extractor_version): it
        # must be treated as stale and re-extracted
        cache_dir = tmp_path / ".cache" / "extract"
        cache_file = next(cache_dir.glob("*__pdf_layout.json"))
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        payload["extractor_version"] = ""
        cache_file.write_text(json.dumps(payload), encoding="utf-8")

        settings = Settings(parts_dir=tmp_path / "parts",
                            cache_dir=tmp_path / ".cache").resolve()
        again = build_part(Path(tmp_path) / "stale.pdf", part_number="P1",
                           settings=settings, vendor="unknown", use_llm=False)
        assert not again.cached_extraction, "stale pdf_layout cache must be re-extracted"
        assert again.manifest.stats.n_tables == 1

    def test_dashed_caption_separator_accepted_with_ruling(self, tmp_path):
        # dense two-column value table (every cell filled, no header row):
        # the ruling hint lets the gate accept what geometry alone cannot
        # distinguish from garbage
        pages = [[
            (56.0, 96.0, "Table 2-1 - Power Consumption"),
            (56.0, 120.0, "Power"),
            (X["typ"], 120.0, "1.2"),
            (X["unit"], 120.0, "W"),
            (56.0, 134.0, "Aux"),
            (X["typ"], 134.0, "0.3"),
            (X["unit"], 134.0, "W"),
        ]]
        pdf = Path(tmp_path) / "dash.pdf"
        _make_pdf(pdf, pages,
                  drawings=[(X["unit"] - 6.0, 112.0, X["unit"] - 6.0, 148.0)])
        settings = Settings(parts_dir=tmp_path / "parts",
                            cache_dir=tmp_path / ".cache").resolve()
        result = build_part(pdf, part_number="P1", settings=settings,
                            vendor="unknown", use_llm=False)
        assert result.manifest.stats.n_tables == 1
        md = _blob(result)
        assert re.search(r"## Table 2-1", md)
        # grid rows survive intact: param + typ + unit columns
        assert "| Power |  |  | 1.2 |  | W |" in md or "| Power | 1.2 | W |" in md
        assert "| Aux | 0.3 | W |" in md or "| Aux |  |  | 0.3 |  | W |" in md
