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
from typing import ClassVar

import fitz

from datasheet_analyzer.config import Settings
from datasheet_analyzer.corpus_ref import corpus_relative
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.publish.plots import artifact_root
from datasheet_analyzer.publish.writer import document_dirs
from datasheet_analyzer.query import SpecQuery

PAGE_W, PAGE_H = 612.0, 792.0


def _squash_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# AD9081-style column left edges (x0 of each column's text).
X = {"param": 56.0, "conditions": 222.0, "min": 435.0, "typ": 460.0, "max": 515.0, "unit": 548.0}
PITCH = 13.0
CAP_Y = 140.0
HDR_Y = 153.0


def _make_pdf(
    path: Path,
    pages,
    toc: list[list] | None = None,
    drawings: list[tuple[float, float, float, float]] | None = None,
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


def _spec_pages() -> list[list[tuple[float, float, str]]]:
    """The canonical 6-column spec table (AD9081 page 5 geometry): partial
    rulings (no vertical lines between Min/Typ/Max), indented sub-rows,
    conditions preamble above the caption, footnote + prose lines below."""
    return [
        [
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
            (
                59.5,
                CAP_Y + 78.0,
                "1  For dc-coupled applications, the maximum output current applies.",
            ),
            (
                56.0,
                CAP_Y + 91.0,
                "Stresses at or above those listed under the rating table may cause damage.",
            ),
        ]
    ]


def _build(tmp_path, name: str, pages, toc=None) -> object:
    pdf = Path(tmp_path) / name
    _make_pdf(pdf, pages, toc)
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    return build_part(pdf, part_number="P1", settings=settings, vendor="unknown", use_llm=False)


def _doc_dir(result) -> Path:
    """Where this build actually published the document's artifacts.

    Resolved through the manifest rather than assumed to be
    `part_dir/docs/<doc>`: ticket 04 publishes a document *once* into the
    shared store and has every part that references it point there, so the
    directory a build wrote to is a fact of the manifest, not of the layout.
    """
    return document_dirs(result.manifest, part_dir=result.part_dir)[
        result.manifest.documents[0].content_hash
    ]


def _artifact(result, ref: str) -> Path:
    """Absolute path of one artifact reference, per the root it hangs off.

    Ticket 04 gave a document two possible homes — under the part, or once in
    the shared store — so a reference is no longer a plain join onto
    `part_dir`. Section references carry the `@library/` marker; a
    `PlotRecord.file` deliberately does not, because `plots.json` lives inside
    the document directory and therefore already names its own root
    (`publish.plots.artifact_root`). Both resolve against the root this
    build's document directory sits in.
    """
    return artifact_root(_doc_dir(result)) / corpus_relative(ref)


def _section_md(result, stem: str) -> str:
    path = _doc_dir(result) / "sections" / f"{stem}.md"
    assert path.exists(), f"missing section file {path.name}"
    return path.read_text(encoding="utf-8")


def _blob(result) -> str:
    return "\n".join(
        _artifact(result, sec.file).read_text(encoding="utf-8") for sec in result.manifest.sections
    )


def _specs_path(result) -> Path:
    return _doc_dir(result) / "specs.json"


class TestCaptionAnchoredTables:
    _pages = staticmethod(_spec_pages)

    def test_spec_table_builds_atomic_block_with_conditions(self, tmp_path):
        result = _build(tmp_path, "t3.pdf", self._pages(), toc=[[1, "1 Specifications", 1]])
        assert result.manifest.stats.n_tables == 1

        md = _section_md(result, "1-specifications")
        assert "## Table 3. DAC DC Specifications" in md
        assert (
            "> **Test conditions:** Nominal supplies with DAC output current = 26 mA,"
            " unless noted. For the minimum and maximum values, TA corresponds to 80 C." in md
        )
        header_md = "| Parameter | Test Conditions/Comments | Min | Typ | Max | Unit |"
        assert header_md in md
        # indented sub-row shares the parameter column; empty cells stay empty
        assert "| Gain Error |  |  | 1.5 |  | % FSR |" in md
        assert "| Integral Nonlinearity (INL) | Shuffling disabled |  | 8.0 |  | LSB |" in md
        # ticket 05: the numbered footnote attaches to the block under its
        # own "**Footnotes:**" heading — never a grid row; the trailing
        # unmarked note stays an honest paragraph
        foot = md.split("## Table 3.")[1].split("**Footnotes:**")[1].split("##")[0]
        assert "- 1 For dc-coupled applications, the maximum output current applies." in foot
        assert "Stresses at or above those listed under the rating table may cause damage." in md
        # the footnote text does not appear as a table row
        table_rows = md.split("## Table 3.")[1].split("**Test conditions:**")[1]
        assert "| 1 For dc-coupled" not in table_rows

        csv = (_doc_dir(result) / "tables" / "1-specifications-t01.csv").read_text(encoding="utf-8")
        assert "Parameter,Test Conditions/Comments,Min,Typ,Max,Unit" in csv
        assert "Integral Nonlinearity (INL),Shuffling disabled,,8.0,,LSB" in csv

    def test_spec_records_resolve_via_query(self, tmp_path):
        result = _build(tmp_path, "t3q.pdf", self._pages(), toc=[[1, "1 Specifications", 1]])
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
        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        result = build_part(
            pdf, part_number="P1", settings=settings, vendor="unknown", use_llm=False
        )
        record = SpecQuery(result.part_dir).find(symbol="Gain Error")[0]
        assert record.page == 1
        # the pinned page's own text must contain the table's cells
        page_text = fitz.open(pdf)[0].get_text()
        for needle in ("Gain Error", "1.5", "% FSR"):
            assert needle in page_text


class TestHonestDegradation:
    def test_captionless_tabular_cluster_stays_paragraphs(self, tmp_path):
        pages = [
            [
                (56.0, 96.0, "Gain Error"),
                (X["typ"], 96.0, "1.5"),
                (X["unit"], 96.0, "% FSR"),
                (56.0, 109.0, "Gain Matching"),
                (X["typ"], 109.0, "0.7"),
                (X["unit"], 109.0, "% FSR"),
                (56.0, 122.0, "Offset Error"),
                (X["typ"], 122.0, "0.05"),
                (X["unit"], 122.0, "% FSR"),
            ]
        ]
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
        pages = [
            [
                (56.0, 96.0, "Table 7. Noise"),
                (56.0, 120.0, "Alpha Beta Gamma"),
                (300.0, 120.0, "Delta"),
                (166.0, 134.0, "Epsilon Zeta"),
                (450.0, 134.0, "Eta"),
                (86.0, 148.0, "Theta"),
                (380.0, 148.0, "Iota"),
                (240.0, 162.0, "Kappa Lambda"),
                (120.0, 162.0, "Mu"),
            ]
        ]
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
        pages = [
            [
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
            ]
        ]
        result = _build(tmp_path, "dense.pdf", pages)
        assert result.manifest.stats.n_tables == 0
        doc = result.manifest.documents[0]
        stats = result.manifest.extraction_stats[doc.content_hash]
        assert stats.tables_rejected >= 1
        assert stats.rejection_reasons, "rejection reason must be recorded"


class TestRegionEdgeCases:
    def test_multiline_wrapped_cell_merges_into_one_row(self, tmp_path):
        pages = [
            [
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
            ]
        ]
        result = _build(tmp_path, "wrap.pdf", pages)
        md = _section_md(result, "1-page-1")
        # one grid row, one cell with the full wrapped text
        assert (
            "| Output Common-Mode Voltage | Bias each output to a negative rail"
            " across a 25 ohm resistor, selected | 0 0.2 |  | 0.3 | V |"
        ) in md
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
        # ticket 09: every row lands in one section and keeps the page it
        # was printed on — continuation rows cite their own page, not the
        # block's caption page
        records = [
            r
            for r in json.loads(_specs_path(result).read_text(encoding="utf-8"))["records"]
            if r["symbol"] == "JESD204 Data Rate"
        ]
        assert records and records[0]["page"] == 2
        first_page = [
            r
            for r in json.loads(_specs_path(result).read_text(encoding="utf-8"))["records"]
            if r["symbol"] == "DAC Data Rate"
        ]
        assert first_page and first_page[0]["page"] == 1

    def test_continuation_rows_verify_on_their_own_page(self, tmp_path):
        # ticket 09 (citations): a merged multi-page block's rows must be
        # pinned to the exact PDF page that printed them — the corpus-verify
        # gate's ≥80% band closes towards 100% minus the known blind spots
        pdf = Path(tmp_path) / "contp.pdf"
        _make_pdf(
            pdf,
            [
                [
                    (56.0, CAP_Y, "Table 9. Input Data Rate Specifications"),
                    *_spec_header(),
                    (56.0, HDR_Y + PITCH, "DAC Data Rate"),
                    (X["typ"], HDR_Y + PITCH, "9"),
                    (X["unit"], HDR_Y + PITCH, "GSPS"),
                    (62.4, HDR_Y + 2 * PITCH, "ADC Data Rate"),
                    (X["typ"], HDR_Y + 2 * PITCH, "3"),
                    (X["unit"], HDR_Y + 2 * PITCH, "GSPS"),
                ],
                [
                    (56.0, 96.0, "Table 9. Input Data Rate Specifications"),
                    (56.0, 120.0, "JESD204 Data Rate"),
                    (X["typ"], 120.0, "16"),
                    (X["unit"], 120.0, "Gbps"),
                    (62.4, 134.0, "SYSREF Data Rate"),
                    (X["typ"], 134.0, "300"),
                    (X["unit"], 134.0, "MHz"),
                ],
            ],
            toc=[[1, "1 Specifications", 1]],
        )
        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        result = build_part(
            pdf, part_number="P1", settings=settings, vendor="unknown", use_llm=False
        )
        page_texts = [_squash_text(p.get_text()) for p in fitz.open(str(pdf))]
        checked = 0
        for rec in json.loads(_specs_path(result).read_text(encoding="utf-8"))["records"]:
            if rec["page"] is None or not (rec["typ"] or rec["min"] or rec["max"] or rec["value"]):
                continue
            needle = _squash_text(rec["row_verbatim"][0] if rec["row_verbatim"] else "")
            if len(needle) < 4:
                continue
            checked += 1
            assert needle in page_texts[rec["page"] - 1], (rec["symbol"], rec["page"])
        assert checked >= 3


class TestRowSpanMaterialization:
    """Ticket 09 (grid materialization): a parameter symbol spanning
    condition rows replicates into the child rows' symbol cells.

    Synthetic fixture mirrors the measured AD9081 Table 3 geometry
    (probe09): band headers at the header word's x0, parameters indented
    one level, span children indented one level deeper; a parent row
    carries symbol + conditions but no values, and its children carry the
    values. The 'DAC ACCURACY' band header must NOT be replicated into the
    independent 'Gain Error' row below it (the indent/hierarchy signal is
    the printer's own declaration).

    Cells are written through fitz.TextWriter with a tiny per-cell size
    jitter: plain insert_text fuses same-y inserts into one span (a
    fixture-builder artifact), while the real PDFs carry one span per cell
    (measured 62.4 vs 222.0 cell starts in AD9081 Table 3) — the jitter
    reproduces that span separation.
    """

    XB: ClassVar[dict[str, float]] = {"band": 56.0, "param": 62.4, "child": 70.9}
    # header-word / param / child levels
    _PAGE_W, _PAGE_H = 612.0, 792.0

    @staticmethod
    def _make_span_pdf(path: Path, lines: list[tuple[float, float, str]]) -> None:
        doc = fitz.open()
        page = doc.new_page(width=612.0, height=792.0)
        font = fitz.Font("helv")
        per_row: dict[float, list[tuple[float, float, str]]] = {}
        for x, y, text in lines:
            per_row.setdefault(round(y, 3), []).append((x, text))
        for y, cells in sorted(per_row.items()):
            tw = fitz.TextWriter(page.rect)
            for k, (x, text) in enumerate(cells):
                tw.append((x, y), text, font=font, fontsize=11.0 + 0.06 * (k % 2))
            tw.write_text(page)
        doc.set_toc([[1, "1 Specifications", 1]])
        doc.save(str(path))
        doc.close()

    def _span_pages(self):
        return [
            [
                (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
                *_spec_header(),
                (56.0, HDR_Y + PITCH, "DAC RESOLUTION"),
                (X["min"], HDR_Y + PITCH, "16"),
                (X["unit"], HDR_Y + PITCH, "Bit"),
                (self.XB["band"], HDR_Y + 2 * PITCH, "DAC ACCURACY"),
                (self.XB["param"], HDR_Y + 3 * PITCH, "Gain Error"),
                (X["typ"], HDR_Y + 3 * PITCH, "1.5"),
                (X["unit"], HDR_Y + 3 * PITCH, "% FSR"),
                (self.XB["param"], HDR_Y + 4 * PITCH, "Full-Scale Output Current Range"),
                (
                    X["conditions"],
                    HDR_Y + 4 * PITCH,
                    "AC coupling, setting resistance (RSET) = 5 kOhm",
                ),
                (self.XB["child"], HDR_Y + 5 * PITCH, "AC Coupling"),
                (X["conditions"], HDR_Y + 5 * PITCH, "Output common-mode voltage (VCM) = 0 V"),
                (X["min"], HDR_Y + 5 * PITCH, "6.43"),
                (X["typ"], HDR_Y + 5 * PITCH, "37.75"),
                (X["unit"], HDR_Y + 5 * PITCH, "mA"),
                (self.XB["child"], HDR_Y + 6 * PITCH, "DC Coupling"),
                (X["conditions"], HDR_Y + 6 * PITCH, "50 ohm shunt to a negative supply"),
                (X["min"], HDR_Y + 6 * PITCH, "6.43"),
                (X["typ"], HDR_Y + 6 * PITCH, "37.75"),
                (X["unit"], HDR_Y + 6 * PITCH, "mA"),
            ]
        ]

    def _build(self, tmp_path, name: str) -> object:
        pdf = Path(tmp_path) / name
        self._make_span_pdf(pdf, self._span_pages()[0])
        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        return build_part(pdf, part_number="P1", settings=settings, vendor="unknown", use_llm=False)

    def test_child_rows_materialize_the_spanning_symbol(self, tmp_path):
        result = self._build(tmp_path, "span.pdf")
        assert result.manifest.stats.n_tables == 1
        md = _section_md(result, "1-specifications")
        # children carry the parent symbol verbatim in front of their own
        # text — the association the unruled grid loses today
        assert (
            "| Full-Scale Output Current Range AC Coupling "
            "| Output common-mode voltage (VCM) = 0 V "
            "| 6.43 | 37.75 |  | mA |"
        ) in md
        assert (
            "| Full-Scale Output Current Range DC Coupling "
            "| 50 ohm shunt to a negative supply "
            "| 6.43 | 37.75 |  | mA |"
        ) in md
        # the parent row itself is unchanged and still honestly value-less
        assert (
            "| Full-Scale Output Current Range "
            "| AC coupling, setting resistance (RSET) = 5 kOhm |  |  |  |  |"
        ) in md
        # the band header is never replicated into an independent row
        assert "| DAC ACCURACY Gain Error" not in md
        assert "| Gain Error |  |  | 1.5 |  | % FSR |" in md

    def test_materialized_records_resolve_the_parent_symbol(self, tmp_path):
        # the 07-recorded reason q2's original AD9081 spec_query could not
        # pass: no record for the parent symbol carries values. After
        # materialization a symbol query resolves the children with
        # complete min/typ + units.
        result = self._build(tmp_path, "spanq.pdf")
        q = SpecQuery(result.part_dir)
        hits = q.find(symbol="Full-Scale Output Current Range")
        # children (2) + parent (1): parent keeps honest empty values
        assert len(hits) == 3
        children = [r for r in hits if r.min or r.typ]
        assert len(children) == 2
        ac = next(r for r in children if "AC Coupling" in r.symbol)
        assert ac.min == "6.43" and ac.typ == "37.75" and ac.unit.canonical == "mA"
        dc = next(r for r in children if "DC Coupling" in r.symbol)
        assert dc.typ == "37.75" and dc.unit.canonical == "mA"
        csv = (_doc_dir(result) / "tables" / "1-specifications-t01.csv").read_text(encoding="utf-8")
        assert "Full-Scale Output Current Range AC Coupling," in csv
        assert "DAC ACCURACY Gain Error" not in csv


class TestCaptionlessSemantics:
    """Ticket 09: heading-anchored tables (SPEC story 10) landed for the
    captionless era — QPA1003P-shaped synthetic geometry (14 pt heading
    inside a drawn emphasis band, 12 pt header words, 10 pt data rows,
    drawn cell rulings) through the build_part seam. Pins: header words
    never act as heading anchors, the mirrored side-by-side pair splits
    into two atomic tables, trailing "(N)" note lines attach as footnotes
    (inter-span clustering), and captionless tables render as "Unnumbered
    table" — never a fabricated "Table N"."""

    X: ClassVar[dict[str, float]] = {
        "p": 42.8,
        "min": 322.9,
        "typ": 391.8,
        "max": 460.0,
        "unit": 526.1,
    }

    @staticmethod
    def _make_span_pdf(
        path: Path,
        lines: list[tuple[float, float, str]],
        toc,
        rects: list[tuple[float, float, float, float]],
        rulings: list[tuple[float, float, float]] | None = None,
    ) -> None:
        """lines: (x, y, text, fontsize); one fitz.TextWriter item per cell
        on the shared row baseline, with a strictly *decreasing* per-cell
        size (sz - 0.06k). The real PDFs print one span per cell on one
        baseline; fitz merges adjacent same-size items into one span, so
        the sizes must differ — and a decreasing size keeps the (y, x)
        line order honest: the larger glyph box sits higher on the page
        (smaller y0), so x-ascending cells sort x-ascending. rects: drawn
        emphasis/cell bands; rulings: vertical (x, y0, y1) strokes — the
        gate's ruling hint, drawn as lines because draw_rect sides are not
        line segments."""
        doc = fitz.open()
        page = doc.new_page(width=612.0, height=792.0)
        font = fitz.Font("helv")
        per_row: dict[float, list[tuple[float, str, float]]] = {}
        for x, y, text, sz in lines:
            per_row.setdefault(round(y, 3), []).append((x, text, sz))
        for y, cells in sorted(per_row.items()):
            tw = fitz.TextWriter(page.rect)
            for k, (x, text, sz) in enumerate(cells):
                tw.append((x, y), text, font=font, fontsize=sz - 0.06 * k)
            tw.write_text(page)
        for x0, y0, x1, y1 in rects:
            page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=1.0)
        for x, y0, y1 in rulings or []:
            page.draw_line((x, y0), (x, y1))
        doc.set_toc(toc)
        doc.save(str(path))
        doc.close()

    def _build(self, tmp_path, name: str, lines, toc, rects, rulings=None) -> object:
        pdf = Path(tmp_path) / name
        self._make_span_pdf(pdf, lines, toc, rects, rulings)
        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        return build_part(pdf, part_number="P1", settings=settings, vendor="unknown", use_llm=False)

    def test_heading_anchored_table_with_12pt_header_words(self, tmp_path):
        # QPA1003P p2 electrical shape: the 14 pt heading is inside a drawn
        # band, the header words print at 12 pt (each as its own line) —
        # they must not be heading anchors carving the region to nothing
        lines = [
            (36.0, 100.0, "Electrical Specifications", 14.04),
            (self.X["p"], 126.0, "Parameter", 12.0),
            (self.X["min"], 126.0, "Min", 12.0),
            (self.X["typ"], 126.0, "Typ", 12.0),
            (self.X["max"], 126.0, "Max", 12.0),
            (self.X["unit"], 126.0, "Units", 12.0),
            (self.X["p"], 140.5, "Operational Frequency Range", 10.0),
            (self.X["min"], 140.5, "1", 10.0),
            (self.X["typ"], 140.5, "-", 10.0),
            (self.X["max"], 140.5, "8", 10.0),
            (self.X["unit"], 140.5, "GHz", 10.0),
            (self.X["p"], 155.0, "Output Power @ PIN = 15 dBm", 10.0),
            (self.X["min"], 155.0, "39.7", 10.0),
            (self.X["typ"], 155.0, "40.7", 10.0),
            (self.X["max"], 155.0, "41.3", 10.0),
            (self.X["unit"], 155.0, "dBm", 10.0),
            (self.X["p"], 169.5, "Output Power @ PIN = 15 dBm", 10.0),
            (self.X["min"], 169.5, "39.7", 10.0),
            (self.X["typ"], 169.5, "40.7", 10.0),
            (self.X["max"], 169.5, "41.3", 10.0),
            (self.X["unit"], 169.5, "dBm", 10.0),
        ]
        rects = [(36.0, 92.0, 576.0, 110.0)]
        rulings = [
            (x, 135.0, 181.0)
            for x in (self.X["p"], self.X["min"], self.X["typ"], self.X["max"], self.X["unit"])
        ]
        result = self._build(
            tmp_path,
            "hdr.pdf",
            lines,
            toc=[[1, "1 Specifications", 1]],
            rects=rects,
            rulings=rulings,
        )
        assert result.manifest.stats.n_tables == 1
        md = _section_md(result, "1-specifications")
        # rendered as the honest captionless form, never a fabricated number
        assert "## Unnumbered table" in md
        assert not re.search(r"^## Table \d", md, re.MULTILINE)
        assert "| Parameter | Min | Typ | Max | Units |" in md
        assert "| Operational Frequency Range | 1 | - | 8 | GHz |" in md
        recs = SpecQuery(result.part_dir).find(symbol="Operational Frequency Range")
        assert len(recs) == 1
        assert recs[0].min == "1" and recs[0].max == "8"
        assert recs[0].unit.canonical == "GHz"

    def test_mirrored_side_by_side_pair_splits_into_two_tables(self, tmp_path):
        # QPA1003P p2 shape: 'Absolute Maximum Ratings' + 'Recommended
        # Operating Conditions' share one baseline; their header rows mirror
        # ('Parameter Value / Range' twice) and the region splits at the
        # midpoint into two atomic tables
        lines = [
            (36.0, 100.0, "Absolute Maximum Ratings", 14.04),
            (316.0, 100.0, "Recommended Operating Conditions", 14.04),
            (48.6, 126.0, "Parameter", 12.0),
            (217.1, 126.0, "Value / Range", 12.0),
            (323.3, 126.0, "Parameter", 12.0),
            (486.5, 126.0, "Value / Range", 12.0),
            (39.6, 140.5, "Drain Voltage (VD)", 10.0),
            (235.4, 140.5, "+29.5 V", 10.0),
            (319.7, 140.5, "Drain Voltage (VD)", 10.0),
            (508.8, 140.5, "+28 V", 10.0),
            (39.6, 155.0, "Drain Current", 10.0),
            (235.4, 155.0, "1300 mA", 10.0),
            (319.7, 155.0, "Drain Current (IDQ)", 10.0),
            (508.8, 155.0, "650 mA", 10.0),
            (39.6, 169.5, "Storage Temperature", 10.0),
            (235.4, 169.5, "-55 to 150 C", 10.0),
            (319.7, 169.5, "Temperature (TBASE)", 10.0),
            (508.8, 169.5, "-40 to 85 C", 10.0),
        ]
        rects = [(36.0, 92.0, 295.0, 110.0), (316.0, 92.0, 576.0, 110.0)]
        rulings = [(x, 121.0, 192.0) for x in (39.6, 217.1, 319.7, 486.5)]
        result = self._build(
            tmp_path, "pair.pdf", lines, toc=[[1, "1 Pair", 1]], rects=rects, rulings=rulings
        )
        assert result.manifest.stats.n_tables == 2
        md = _section_md(result, "1-pair")
        assert md.count("## Unnumbered table") == 2
        # left zone: header starts inside the body (48.6 vs 39.6) so the
        # honest grid carries the empty declared columns around the pair
        assert "| Drain Voltage (VD) |  |  | +29.5 V |" in md
        assert "| Drain Current |  |  | 1300 mA |" in md
        # right zone: clean parameter/value pair with values in the value role
        right = md.split("## Unnumbered table")[2]
        assert "| Parameter | Value / Range |" in right
        assert "| Drain Voltage (VD) | +28 V |" in right
        assert "| Drain Current (IDQ) | 650 mA |" in right
        assert "| Temperature (TBASE) | -40 to 85 C |" in right
        # every printed line is in the corpus exactly once across the grids
        blob = _blob(result)
        for needle in ("+29.5 V", "+28 V", "1300 mA", "650 mA", "-55 to 150 C"):
            assert blob.count(needle) == 1, needle

    def test_prose_under_heading_stays_paragraphs(self, tmp_path):
        # SPEC story 10's rejection guard, pinned: a heading-anchored
        # region whose first row carries no parameter-header token is
        # prose, never a grid (the captionless-doubles guard) — even with
        # a drawn emphasis band under the heading
        lines = [
            (36.0, 100.0, "Product Description", 14.04),
            (36.0, 132.0, "The QPA1003P is a wideband high power MMIC", 10.0),
            (36.0, 146.0, "amplifier on GaN on SiC process with 1 to 8 GHz", 10.0),
            (36.0, 160.0, "coverage and 10 W of saturated output power.", 10.0),
        ]
        result = self._build(
            tmp_path,
            "prose.pdf",
            lines,
            toc=[[1, "1 Page One", 1]],
            rects=[(36.0, 92.0, 576.0, 110.0)],
            rulings=[],
        )
        assert result.manifest.stats.n_tables == 0
        md = _section_md(result, "1-page-one")
        assert "## Unnumbered table" not in md
        for needle in ("wideband high power MMIC", "GaN on SiC", "10 W of saturated"):
            assert needle in md, needle

    def test_trailing_note_lines_attach_as_footnotes_not_grid_rows(self, tmp_path):
        # LM741 p4 shape: note lines print as multi-word spans whose starts
        # sit far apart (word-span width) while the inter-span gaps are tiny
        # (~2.4 pt) — the inter-span cluster rule keeps them footnotes, so a
        # grid never gains their ragged fragments as cells
        lines = [
            (56.0, 96.0, "Table 1. Electrical Characteristics", 11.0),
            (56.0, 116.0, "PARAMETER", 8.5),
            (450.0, 116.0, "MIN", 8.5),
            (520.0, 116.0, "UNIT", 8.5),
            (56.0, 140.0, "Input offset voltage", 8.5),
            (450.0, 140.0, "5", 8.5),
            (520.0, 140.0, "mV", 8.5),
            (56.0, 148.0, "Input bias current", 8.5),
            (450.0, 148.0, "80", 8.5),
            (56.0, 156.0, "Input resistance", 8.5),
            (450.0, 156.0, "2", 8.5),
            (520.0, 156.0, "MOhm", 8.5),
            (56.0, 164.0, "Slew rate", 8.5),
            (520.0, 164.0, "V/us", 8.5),
            (54.0, 192.0, "(1)", 8.06),
            (71.88, 192.0, "For military specifications", 8.0),
            (164.39, 192.0, "see", 7.94),
            (179.69, 192.0, "RETS741X for", 7.88),
            (233.80, 192.0, "LM741", 7.82),
            (260.66, 192.0, "and RETS741AX for", 7.76),
            (335.84, 192.0, "LM741A.", 7.7),
        ]
        result = self._build(
            tmp_path, "notes.pdf", lines, toc=[[1, "1 Specifications", 1]], rects=[]
        )
        assert result.manifest.stats.n_tables == 1
        md = _section_md(result, "1-specifications")
        foot = md.split("**Footnotes:**")[1].split("##")[0]
        body = "For military specifications see RETS741X for LM741 and RETS741AX for LM741A."
        assert "- 1 " + body in foot
        # the grid stays clean: data rows only, no note fragments
        assert "| Input offset voltage | 5 | mV |" in md
        assert "| Input resistance | 2 | MOhm |" in md
        assert "| Slew rate |  | V/us |" in md
        assert "| For military" not in md.split("**Footnotes:**")[0]

    def test_heading_anchored_table_never_renames_to_table_n(self, tmp_path):
        # the honest form is '## Unnumbered table', never '## Table 4' —
        # a fabricated number would invite bogus citations. QPA1003P p20
        # shape: header words ('Parameter', 'Rating') print at 9.96 pt —
        # comfortably below the 11 pt heading size; a 12 pt 'Rating' would
        # be caught by the header-token guard anyway.
        lines = [
            (36.0, 100.0, "Handling Precautions", 14.04),
            (39.6, 126.0, "Parameter", 9.96),
            (197.8, 126.0, "Rating", 9.96),
            (39.6, 140.5, "ESD - Human Body Model (HBM)", 10.0),
            (213.5, 140.5, "0B", 10.0),
            (39.6, 155.0, "MSL - Moisture Sensitivity Level", 10.0),
            (206.6, 155.0, "MSL3", 10.0),
        ]
        rects = [(36.0, 92.0, 576.0, 110.0)]
        rulings = [(39.6, 135.0, 166.0), (213.5, 135.0, 166.0)]
        result = self._build(
            tmp_path, "prec.pdf", lines, toc=[[1, "1 Handling", 1]], rects=rects, rulings=rulings
        )
        assert result.manifest.stats.n_tables == 1
        md = _section_md(result, "1-handling")
        assert "## Unnumbered table" in md
        assert not re.search(r"^## Table \d", md, re.MULTILINE)
        assert "| ESD - Human Body Model (HBM) | 0B |" in md
        assert "| MSL - Moisture Sensitivity Level | MSL3 |" in md


class TestRetryLadder:
    """Ticket 04: every band set is scored and the best-scoring grid wins.

    The ladder's rescue claim, the unrecoverable->paragraphs+reason path
    and the selection rule are pinned here, all through the publish seam:
    the corpus product must never show a grid the header didn't declare
    (a coarse τ split that merges Min|Typ is a corruption even though it
    would score higher on raw word fidelity).
    """

    def test_header_fail_anchor_recovers_at_coarser_all_word_split(self, tmp_path):
        # The header row's words sit at positions no body row shares: the
        # header-anchored split leaves every body word outside the bands
        # (unstable -> rejected) and only the all-word splits recover the
        # table. Mirrors AD9081 Tables 17/20/21 (2-word headers over body
        # columns the header never declares).
        pages = [
            [
                (56.0, CAP_Y, "Table 4. Reference Clock"),
                (350.0, HDR_Y, "SYMBOL"),
                (480.0, HDR_Y, "VALUE"),
                (56.0, HDR_Y + PITCH, "LVDS Clock Divide"),
                (406.0, HDR_Y + PITCH, "1.2"),
                (540.0, HDR_Y + PITCH, "V"),
                (56.0, HDR_Y + 2 * PITCH, "CMOS Clock Divide"),
                (406.0, HDR_Y + 2 * PITCH, "3.3"),
                (540.0, HDR_Y + 2 * PITCH, "V"),
                (56.0, HDR_Y + 3 * PITCH, "Device Clock Divide"),
                (406.0, HDR_Y + 3 * PITCH, "0.9"),
                (540.0, HDR_Y + 3 * PITCH, "V"),
                (56.0, HDR_Y + 4 * PITCH, "SYSREF Clock Divide"),
                (406.0, HDR_Y + 4 * PITCH, "1.8"),
                (540.0, HDR_Y + 4 * PITCH, "V"),
            ]
        ]
        result = _build(tmp_path, "rescue.pdf", pages)
        assert result.manifest.stats.n_tables == 1
        md = _section_md(result, "1-page-1")
        # the body columns are recovered and every data row survives
        assert "| LVDS Clock Divide |  | 1.2 |  | V |" in md
        assert "| SYSREF Clock Divide |  | 1.8 |  | V |" in md
        doc = result.manifest.documents[0]
        stats = result.manifest.extraction_stats[doc.content_hash]
        assert (stats.tables_detected, stats.tables_accepted, stats.tables_rejected) == (1, 1, 0)

    def test_coarse_split_never_beats_the_header_declared_columns(self, tmp_path):
        # Min@435 and Typ@460 sit 25 pt apart: a coarse τ=28 all-word split
        # merges them into one column and, with the prose row dropped by the
        # fine split but kept by the coarse one, would win a raw word-fidelity
        # comparison. The header-declared separation must win: the merged cell
        # must never reach the corpus.
        result = _build(tmp_path, "guard.pdf", _spec_pages(), toc=[[1, "1 Specifications", 1]])
        assert result.manifest.stats.n_tables == 1
        md = _section_md(result, "1-specifications")
        assert "| Parameter | Test Conditions/Comments | Min | Typ | Max | Unit |" in md
        table_region = md.split("## Table 3.")[1]
        assert "| Min Typ |" not in table_region
        assert (
            "| Integral Nonlinearity (INL) | Shuffling disabled |  | 8.0 |  | LSB |" in table_region
        )

    def test_unrecoverable_ladder_degrades_to_paragraphs_with_exact_reason(self, tmp_path):
        # Every row scatters its words on tracks no other row shares: every
        # split of every tau yields an unstable grid. The ladder exhausts,
        # the words stay honest paragraphs and the gate's own verdict is the
        # recorded reason.
        pages = [
            [
                (56.0, 96.0, "Table 7. Noise"),
                (56.0, 120.0, "Alpha Beta"),
                (306.0, 120.0, "Gamma"),
                (100.0, 134.0, "Delta Epsilon"),
                (410.0, 134.0, "Zeta"),
                (175.0, 148.0, "Eta"),
                (465.0, 148.0, "Theta"),
                (240.0, 162.0, "Iota Kappa"),
                (520.0, 162.0, "Lambda"),
                (560.0, 176.0, "Mu Nu"),
            ]
        ]
        result = _build(tmp_path, "trapped.pdf", pages)
        assert result.manifest.stats.n_tables == 0
        doc = result.manifest.documents[0]
        stats = result.manifest.extraction_stats[doc.content_hash]
        assert stats.tables_detected == 1
        assert stats.tables_accepted == 0
        assert stats.tables_rejected == 1
        assert stats.rejection_reasons == ["columns not stable across rows"]
        blob = _blob(result)
        for needle in ("Alpha Beta", "Iota Kappa", "Mu Nu"):
            assert needle in blob


class TestMechanics:
    def test_extraction_stats_recorded_in_manifest(self, tmp_path):
        result = _build(
            tmp_path,
            "mech.pdf",
            [
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
            ],
        )
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

        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        again = build_part(
            Path(tmp_path) / "stale.pdf",
            part_number="P1",
            settings=settings,
            vendor="unknown",
            use_llm=False,
        )
        assert not again.cached_extraction, "stale pdf_layout cache must be re-extracted"
        assert again.manifest.stats.n_tables == 1

    def test_dashed_caption_separator_accepted_with_ruling(self, tmp_path):
        # dense two-column value table (every cell filled, no header row):
        # the ruling hint lets the gate accept what geometry alone cannot
        # distinguish from garbage
        pages = [
            [
                (56.0, 96.0, "Table 2-1 - Power Consumption"),
                (56.0, 120.0, "Power"),
                (X["typ"], 120.0, "1.2"),
                (X["unit"], 120.0, "W"),
                (56.0, 134.0, "Aux"),
                (X["typ"], 134.0, "0.3"),
                (X["unit"], 134.0, "W"),
            ]
        ]
        pdf = Path(tmp_path) / "dash.pdf"
        _make_pdf(pdf, pages, drawings=[(X["unit"] - 6.0, 112.0, X["unit"] - 6.0, 148.0)])
        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        result = build_part(
            pdf, part_number="P1", settings=settings, vendor="unknown", use_llm=False
        )
        assert result.manifest.stats.n_tables == 1
        md = _blob(result)
        assert re.search(r"## Table 2-1", md)
        # grid rows survive intact: param + typ + unit columns
        assert "| Power |  |  | 1.2 |  | W |" in md or "| Power | 1.2 | W |" in md
        assert "| Aux | 0.3 | W |" in md or "| Aux |  |  | 0.3 |  | W |" in md
