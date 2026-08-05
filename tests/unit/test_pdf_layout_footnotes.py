"""pdf_layout footnotes — markers from font geometry + trailing-body attach.

Ticket 05, through the spec's single seam (`build_part` with temp-dir
settings, assertions on the corpus product): synthetic fitz PDFs whose span
geometry models the measured real PDFs — AD9081's glued superscript markers
(5.85pt span on a 7.79pt line, baseline raised ~1-3pt, e.g. "AC Coupling2"),
hmc520a's "1Reference"/"1." body forms, QPA's subscript traps — and
trailing numbered lines below the table region.

Coverage:
- glued superscript markers -> cell text keeps the marker (glued rule) and
  `cited_markers` carries it; the marked spec record cites the footnote and
  `format_answer` prints its text;
- trailing numbered lines attach as enumerated footnotes, wrapped
  continuations merge into the open footnote, and the block is never
  duplicated into paragraphs;
- a footnote with no detectable marker still attaches positionally to the
  table immediately above it;
- guards: marker-less paragraphs after a marked footnote or gapped beyond
  tolerance stay paragraphs; subscripts ("f0") are never markers; a
  "10^6"-style exponent is geometrically identical to a glued superscript
  marker and lands in cited_markers as an audit-level orphan (measured and
  recorded in KNOWN_SHORTCOMINGS.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from datasheet_analyzer.config import Settings
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.query import SpecQuery, format_answer

PAGE_W, PAGE_H = 612.0, 792.0

X = {"param": 56.0, "conditions": 222.0, "min": 435.0, "typ": 460.0,
     "max": 515.0, "unit": 548.0}
PITCH = 13.0
CAP_Y = 140.0
HDR_Y = 153.0
BASE_SIZE = 10.0
SUP_SIZE = 6.5


def _make_pdf(path: Path, pages, toc: list[list] | None = None,
              drawings: list[tuple[float, float, float, float]] | None = None
              ) -> None:
    """pages: list of pages; each page = list of lines.

    A line is either (x, y, text) — one regular-size span — or
    (x, y, [(text, size, raise), ...]) — one visual line of several spans
    with real font geometry (built with fitz.TextWriter, so spans merge
    into a single line exactly like a real PDF's).
    """
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for item in lines:
            x, y = item[0], item[1]
            if isinstance(item[2], str):
                spans = [(item[2], BASE_SIZE, 0.0)]
            else:
                spans = list(item[2])
            tw = fitz.TextWriter(page.rect)
            font = fitz.Font("helv")
            cx = x
            for text, size, rise in spans:
                tw.append((cx, y - rise), text, font=font, fontsize=size)
                cx += fitz.get_text_length(text, fontname="helv", fontsize=size)
            tw.write_text(page)
    if drawings:
        for x0, y0, x1, y1 in drawings:
            doc[0].draw_line((x0, y0), (x1, y1))
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()


def _glue(x: float, text: str, size: float = BASE_SIZE) -> float:
    """x just past the end of `text` drawn at (x, ...) — exact glue."""
    return x + fitz.get_text_length(text, fontname="helv", fontsize=size)


def _ruling() -> list[tuple[float, float, float, float]]:
    """A real vertical ruling beside the unit column (AD9081-style): the
    ruling hint lets the gate accept minimal two/three-row synthetic tables
    that geometry alone would conservatively reject."""
    return [(X["unit"] - 6.0, CAP_Y - 5.0, X["unit"] - 6.0, HDR_Y + 9 * PITCH)]


def _sup(marker: str, rise: float = 3.0) -> tuple:
    return (marker, SUP_SIZE, rise)


def _spec_header() -> list[tuple[float, float, str]]:
    return [
        (X["param"], HDR_Y, "Parameter"),
        (X["conditions"], HDR_Y, "Test Conditions/Comments"),
        (X["min"], HDR_Y, "Min"),
        (X["typ"], HDR_Y, "Typ"),
        (X["max"], HDR_Y, "Max"),
        (X["unit"], HDR_Y, "Unit"),
    ]


def _table_with_marker_and_footnotes() -> list:
    """Table 3-style page: a superscript-glued 'AC Coupling2' cell, footnote
    lines '1 ...' + wrapped continuation + '2 ...' below the grid."""
    ac_cell = "DAC Output Power AC Coupling"
    return [
        (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
        *_spec_header(),
        (56.0, HDR_Y + PITCH, [
            (ac_cell, BASE_SIZE, 0.0),
            _sup("2"),
        ]),
        (X["typ"], HDR_Y + PITCH, "3.3"),
        (X["unit"], HDR_Y + PITCH, "dBm"),
        (62.4, HDR_Y + 2 * PITCH, "Gain Error"),
        (X["typ"], HDR_Y + 2 * PITCH, "1.5"),
        (X["unit"], HDR_Y + 2 * PITCH, "% FSR"),
        (56.0, HDR_Y + 4 * PITCH,
         "1 For dc-coupled applications, the maximum full-scale output"),
        (56.0, HDR_Y + 5 * PITCH - 4.0,
         "current is limited by the maximum VCMOUT specification."),
        (56.0, HDR_Y + 6 * PITCH,
         "2 The actual measured full-scale power is frequency dependent."),
    ]


def _build(tmp_path, name: str, pages, toc=None) -> object:
    pdf = Path(tmp_path) / name
    _make_pdf(pdf, pages, toc, drawings=_ruling())
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    return build_part(pdf, part_number="P1", settings=settings,
                      vendor="unknown", use_llm=False)


def _doc_dir(result) -> Path:
    return result.part_dir / "docs" / f"datasheet-{result.manifest.documents[0].content_hash[:8]}"


def _section_md(result, stem: str) -> str:
    path = _doc_dir(result) / "sections" / f"{stem}.md"
    assert path.exists(), f"missing section file {path.name}"
    return path.read_text(encoding="utf-8")


def _footnotes_blob(md: str) -> str:
    head = md.split("**Footnotes:**", 1)[1]
    return head.split("##", 1)[0]


class TestSuperscriptMarkers:
    def test_glued_marker_cites_footnote_and_body_attaches(self, tmp_path):
        result = _build(tmp_path, "fn1.pdf", [_table_with_marker_and_footnotes()],
                        toc=[[1, "1 Specifications", 1]])
        md = _section_md(result, "1-specifications")
        # the cell keeps the glued marker text
        assert ("| DAC Output Power AC Coupling2"
                " |  |  | 3.3 |  | dBm |") in md
        # footnotes attach as an enumerated block under the table, in order,
        # with the wrapped continuation merged into footnote 1
        foot = _footnotes_blob(md)
        assert ("- 1 For dc-coupled applications, the maximum full-scale output"
                " current is limited by the maximum VCMOUT specification.") in foot
        assert "- 2 The actual measured full-scale power is frequency dependent." in foot
        # never duplicated into the paragraph stream
        assert md.count("For dc-coupled applications, the maximum full-scale output") == 1
        assert md.count("The actual measured full-scale power is frequency dependent") == 1

    def test_spec_record_cites_the_marker_and_answer_prints_footnote(self, tmp_path):
        result = _build(tmp_path, "fn2.pdf", [_table_with_marker_and_footnotes()])
        specs = json.loads(
            (_doc_dir(result) / "specs.json").read_text(encoding="utf-8"))
        row = next(r for r in specs["records"]
                   if "AC Coupling2" in r["symbol"])
        assert row["cited_markers"] == ["2"]
        assert [f["marker"] for f in row["footnotes"]] == ["1", "2"]
        assert any("frequency dependent" in f["text"] for f in row["footnotes"])

        q = SpecQuery(result.part_dir)
        rec = q.find(symbol="DAC Output Power AC Coupling")[0]
        answer = format_answer([rec])
        assert "AC Coupling2" in answer
        assert "The actual measured full-scale power is frequency dependent." in answer


class TestPositionalAttach:
    def test_markerless_footnote_attaches_positionally(self, tmp_path):
        # ticket item: a footnote with no detectable marker still attaches to
        # the table sitting directly above it
        page = [
            (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
            *_spec_header(),
            (56.0, HDR_Y + PITCH, "DAC RESOLUTION"),
            (X["min"], HDR_Y + PITCH, "16"),
            (X["unit"], HDR_Y + PITCH, "Bit"),
            (56.0, HDR_Y + 2 * PITCH,
             "For dc-coupled applications, the maximum output current applies at all times."),
        ]
        result = _build(tmp_path, "fn3.pdf", [page])
        md = _section_md(result, "1-page-1")
        sentence = "For dc-coupled applications, the maximum output current applies at all times."
        assert f"- {sentence}" in md
        assert md.count(sentence) == 1

    def test_markerless_line_after_marked_footnote_stays_paragraph(self, tmp_path):
        # the guard: generic note text following a *marked* footnote block is
        # beyond the continuation window -> stays an honest paragraph
        page = [
            (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
            *_spec_header(),
            (56.0, HDR_Y + PITCH, "DAC RESOLUTION"),
            (X["min"], HDR_Y + PITCH, "16"),
            (X["unit"], HDR_Y + PITCH, "Bit"),
            (56.0, HDR_Y + 2 * PITCH,
             "1 For dc-coupled applications, the maximum output current applies."),
            (56.0, HDR_Y + 3 * PITCH,
             "Stresses at or above those listed under the rating table may cause damage."),
        ]
        result = _build(tmp_path, "fn4.pdf", [page])
        md = _section_md(result, "1-page-1")
        foot = _footnotes_blob(md)
        assert "- 1 For dc-coupled applications, the maximum output current applies." in foot
        assert "Stresses at or above" not in foot
        assert ("Stresses at or above those listed under the rating table may cause"
                " damage.") in md  # stays a paragraph, verbatim

    def test_gapped_markerless_line_stays_paragraph(self, tmp_path):
        page = [
            (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
            *_spec_header(),
            (56.0, HDR_Y + PITCH, "DAC RESOLUTION"),
            (X["min"], HDR_Y + PITCH, "16"),
            (X["unit"], HDR_Y + PITCH, "Bit"),
            (56.0, HDR_Y + 4 * PITCH,
             "A distant note has no business becoming a footnote of this table."),
        ]
        result = _build(tmp_path, "fn5.pdf", [page])
        md = _section_md(result, "1-page-1")
        assert "**Footnotes:**" not in md
        assert "A distant note has no business becoming a footnote" in md

    def test_uppercase_heading_between_grid_and_note_stays_out(self, tmp_path):
        # hmc520a p3 shape: an all-caps sub-table heading sits between grid
        # rows and the marked footnote — it must never attach positionally
        page = [
            (56.0, CAP_Y, "Table 7. RF Performance"),
            *_spec_header(),
            (56.0, HDR_Y + PITCH, "Conversion Loss"),
            (X["max"], HDR_Y + PITCH, "10"),
            (X["unit"], HDR_Y + PITCH, "dB"),
            (56.0, HDR_Y + 2 * PITCH, "6 GHZ TO 10 GHZ UPCONVERTER PERFORMANCE"),
            (56.0, HDR_Y + 3 * PITCH, "Conversion Loss"),
            (X["max"], HDR_Y + 3 * PITCH, "9.5"),
            (X["unit"], HDR_Y + 3 * PITCH, "dB"),
            (56.0, HDR_Y + 5 * PITCH,
             "1 For RF performance from 10 GHz to 13 GHz, see the Performance to 13 GHz section."),
        ]
        result = _build(tmp_path, "fn6.pdf", [page])
        md = _section_md(result, "1-page-1")
        foot = _footnotes_blob(md)
        assert "- 1 For RF performance from 10 GHz to 13 GHz" in foot
        assert "UPCONVERTER PERFORMANCE" not in foot
        assert "6 GHZ TO 10 GHZ UPCONVERTER PERFORMANCE" in md


class TestMarkerGeometryTraps:
    def test_subscript_rejected_exponent_cited_as_orphan(self, tmp_path):
        # QPA-style 'f0' subscript sits below the row's middle -> never cited;
        # a '10^6'-style exponent is geometrically identical to a glued
        # superscript marker (measured rise ~0.3pt on HMC520A) and lands in
        # cited_markers as an audit-level orphan (recorded in the ledger)
        page = [
            (56.0, CAP_Y, "Table 7. Output Power"),
            *_spec_header(),
            (56.0, HDR_Y + PITCH, [
                ("Output Power @ f", BASE_SIZE, 0.0),
                _sup("0", rise=-3.0),
                (" (dBm)", BASE_SIZE, 0.0),
            ]),
            (X["typ"], HDR_Y + PITCH, "9"),
            (X["unit"], HDR_Y + PITCH, "dBm"),
            (62.4, HDR_Y + 2 * PITCH, [
                ("Reliability >1 x 10", BASE_SIZE, 0.0),
                _sup("6", rise=2.5),
            ]),
            (X["typ"], HDR_Y + 2 * PITCH, "ok"),
            (X["unit"], HDR_Y + 2 * PITCH, "Hrs"),
        ]
        result = _build(tmp_path, "fn7.pdf", [page])
        records = json.loads(
            (_doc_dir(result) / "specs.json").read_text(encoding="utf-8"))["records"]
        power = next(r for r in records if "Output Power @ f" in r["symbol"])
        assert power["cited_markers"] == [], "subscript must not cite"
        # glued cell text is preserved either way
        assert "Output Power @ f0 (dBm)" in power["symbol"]
        rel = next(r for r in records if "Reliability" in r["symbol"])
        # exponent: documented orphan — a real marker glued after a digit
        # ("29001", "× 0.8142") is indistinguishable from it, and real
        # after-digit markers must keep their citations
        assert rel["cited_markers"] == ["6"]


class TestFootnoteBlockNotDuplicated:
    def test_footnote_lines_appear_exactly_once_corpus_wide(self, tmp_path):
        result = _build(tmp_path, "fn8.pdf", [_table_with_marker_and_footnotes()])
        blob = "\n".join((result.part_dir / sec.file).read_text(encoding="utf-8")
                         for sec in result.manifest.sections)
        assert blob.count("actual measured full-scale power is frequency dependent") == 1
        assert blob.count("limited by the maximum VCMOUT specification") == 1
