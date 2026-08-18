"""Plot axis catalog — geometry, honesty, and the filters it enables (ticket 08).

Hermetic per invariant 4: every PDF here is built in-process with PyMuPDF, so
the geometry under test is geometry this file drew and can therefore state the
right answer for. The real-document gate lives in
`tests/integration/test_phase6_plot_axes.py`.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from datasheet_analyzer.config import PLOTS_SCHEMA_VERSION
from datasheet_analyzer.models import Confidence, PlotRecord, PlotSet
from datasheet_analyzer.query import find_plots
from datasheet_analyzer.structure.plot_axes import (
    Axis,
    annotate_plot_axes,
    axis_contains,
    grade_axes,
    page_axes,
    parse_axis_point,
    parse_tick,
    read_axis_catalog,
    split_title,
)

# --- synthetic plot drawing -------------------------------------------------
#
# One helper draws one plot the way a datasheet prints one: a right-aligned
# column of y tick labels, a centred row of x tick labels, a rotated y title,
# a horizontal x title, and a caption underneath. Everything the module reads
# is a coordinate this function chose, which is what makes the assertions
# below statements of fact rather than of hope.


def _draw_plot(
    page: fitz.Page,
    *,
    x0: float,
    y0: float,
    width: float,
    height: float,
    x_ticks: list[str],
    y_ticks: list[str],
    x_title: str = "Output Frequency (MHz)",
    y_title: str = "Output Full Scale (dBm)",
    caption: str = "Figure 4-1. Synthetic Plot",
    size: float = 6.0,
) -> None:
    """Draw one plot frame with evenly spaced, printed tick labels."""
    left = x0
    top, bottom = y0, y0 + height
    step = width / (len(x_ticks) - 1)
    for i, label in enumerate(x_ticks):
        cx = left + i * step
        w = fitz.get_text_length(label, fontsize=size)
        page.insert_text((cx - w / 2, bottom + 8), label, fontsize=size)
    pitch = height / (len(y_ticks) - 1)
    for i, label in enumerate(y_ticks):  # bottom-up
        cy = bottom - i * pitch
        w = fitz.get_text_length(label, fontsize=size)
        page.insert_text((left - 4 - w, cy), label, fontsize=size)
    if x_title:
        page.insert_text((left + width / 4, bottom + 22), x_title, fontsize=size)
    if y_title:
        page.insert_text((left - 26, top + height / 2), y_title, fontsize=size, rotate=90)
    if caption:
        page.insert_text((left - 8, bottom + 40), caption, fontsize=8)


def _one_plot_pdf(path: Path, **kwargs) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=320, height=340)
    _draw_plot(page, x0=70, y0=60, width=190, height=180, **kwargs)
    doc.save(str(path))
    doc.close()
    return path


LINEAR = {
    "x_ticks": ["600", "750", "900", "1050", "1200", "1350", "1500"],
    "y_ticks": ["-2", "0", "2", "4", "6"],
}


# --- the pure functions -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0.0),
        ("1500", 1500.0),
        ("-40", -40.0),
        ("−40", -40.0),  # unicode minus, which is what TI prints
        ("+85", 85.0),
        ("0.85", 0.85),
        (".5", 0.5),
        ("1,000", 1000.0),
        ("10k", 10_000.0),
        ("1.5M", 1_500_000.0),
        ("1.2e-9", 1.2e-9),
    ],
)
def test_parse_tick_reads_printed_labels(text, expected):
    assert parse_tick(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text", ["", "1TX", "50%", "See Figure 7", "Note 2", "—", "0-fDAC", "3.5 GHz"]
)
def test_parse_tick_refuses_what_is_not_a_tick(text):
    """`None` is a first-class outcome: a label this cannot read is never
    coerced into a number that would then anchor an axis range."""
    assert parse_tick(text) is None


@pytest.mark.parametrize(
    ("title", "label", "unit"),
    [
        ("Output Frequency (MHz)", "Output Frequency", "MHz"),
        ("Gain [dB]", "Gain", "dB"),
        ("DSA (dB)", "DSA", "dB"),
        ("Temperature (Cq)", "Temperature", "°C"),  # Symbol-font degree
        ("Phase Noise", "Phase Noise", ""),
        ("freq_offset(KHz)", "freq_offset", "KHz"),
    ],
)
def test_split_title(title, label, unit):
    assert split_title(title) == (label, unit)


def test_axis_contains_converts_si_prefixes():
    """A query in GHz narrows an axis printed in MHz — same base unit, one
    documented multiplier, no unit inference."""
    axis = Axis(label="Output Frequency", unit="MHz", min=600.0, max=1500.0)
    assert axis_contains(axis, "1.2GHz")
    assert axis_contains(axis, "900MHz")
    assert not axis_contains(axis, "3.5GHz")


def test_axis_contains_refuses_incomparable_and_missing():
    axis = Axis(label="Output Frequency", unit="MHz", min=600.0, max=1500.0)
    assert not axis_contains(axis, "900dBm")  # different base unit
    assert not axis_contains(axis, "not a number")
    assert not axis_contains(Axis(label="Gain", unit="dB"), "3")  # no range at all
    assert axis_contains(Axis(unit="", min=0.0, max=40.0), "12")  # unitless both sides


def test_parse_axis_point():
    assert parse_axis_point("3.5GHz") == (3.5e9, "hz")
    assert parse_axis_point("-40") == (-40.0, "")
    assert parse_axis_point("banana") is None


def test_grade_axes_marks_log_low_and_keeps_nothing_else_high():
    full = Axis(label="F", unit="MHz", min=1.0, max=10.0, scale="linear")
    assert grade_axes(full, full) is Confidence.HIGH
    assert grade_axes(full, Axis(label="Gain")) is Confidence.MEDIUM
    assert grade_axes(Axis(), Axis()) is Confidence.LOW
    logged = Axis(label="Offset", unit="Hz", min=1e3, max=1e8, scale="log")
    assert grade_axes(logged, full) is Confidence.LOW


# --- reading a drawn plot ---------------------------------------------------


def test_reads_both_axes_including_the_rotated_y_title(tmp_path):
    """The y title is drawn rotated 90 degrees, as every datasheet prints it,
    and must come back as text rather than as a column of glyphs."""
    pdf = _one_plot_pdf(tmp_path / "linear.pdf", **LINEAR)
    (axes,) = read_axis_catalog(pdf)
    assert axes.figure_number == "4-1"
    assert (axes.x.label, axes.x.unit) == ("Output Frequency", "MHz")
    assert (axes.x.min, axes.x.max) == (600.0, 1500.0)
    assert (axes.y.label, axes.y.unit) == ("Output Full Scale", "dBm")
    assert (axes.y.min, axes.y.max) == (-2.0, 6.0)
    assert axes.x.scale == axes.y.scale == "linear"
    assert axes.confidence is Confidence.HIGH


def test_side_by_side_plots_do_not_share_a_tick_row(tmp_path):
    """Two plots print their x ticks on one baseline. Splitting that row at
    its own pitch is what stops the left plot's range running to the right
    plot's last tick — the failure that would silently misreport a range."""
    doc = fitz.open()
    page = doc.new_page(width=620, height=340)
    _draw_plot(
        page,
        x0=70,
        y0=60,
        width=190,
        height=180,
        x_ticks=["600", "750", "900", "1050", "1200", "1350", "1500"],
        y_ticks=["-2", "0", "2", "4", "6"],
        caption="Figure 4-1. Left Plot",
    )
    _draw_plot(
        page,
        x0=380,
        y0=60,
        width=190,
        height=180,
        x_ticks=["-40", "-15", "10", "35", "60", "85"],
        y_ticks=["2", "3", "4", "5", "6"],
        x_title="Temperature (Cq)",
        y_title="Output Power (dBm)",
        caption="Figure 4-2. Right Plot",
    )
    path = tmp_path / "pair.pdf"
    doc.save(str(path))
    doc.close()

    catalog = {a.figure_number: a for a in read_axis_catalog(path)}
    assert set(catalog) == {"4-1", "4-2"}
    assert (catalog["4-1"].x.min, catalog["4-1"].x.max) == (600.0, 1500.0)
    assert (catalog["4-2"].x.min, catalog["4-2"].x.max) == (-40.0, 85.0)
    assert catalog["4-2"].x.unit == "°C"
    assert catalog["4-1"].y.label == "Output Full Scale"
    assert catalog["4-2"].y.label == "Output Power"


def test_a_caption_never_claims_the_neighbouring_columns_plot(tmp_path):
    """Two columns of plots, and the right column's caption reaching left.

    Measured on page 75 of the AFE7950: the right column's caption began 19
    pt to the left of where the left column's frame ended and sat 2 pt higher
    than its own column's, so a nearest-caption rule with any horizontal
    slack handed the left plot's axes to the right plot's figure number — the
    one failure mode that produces a *confidently wrong* catalog entry rather
    than an honest null. A caption must genuinely overlap the frame it names.
    """
    doc = fitz.open()
    page = doc.new_page(width=500, height=340)
    _draw_plot(
        page,
        x0=70,
        y0=120,
        width=170,
        height=120,
        x_ticks=["0", "10", "20", "30", "40"],
        y_ticks=["-80", "-70", "-60", "-50"],
        x_title="DSA Setting (dB)",
        y_title="IMD3 (dBc)",
        caption="",
    )
    _draw_plot(
        page,
        x0=290,
        y0=63,
        width=170,
        height=120,
        x_ticks=["-60", "-45", "-30", "-15", "0"],
        y_ticks=["30", "40", "50", "60"],
        x_title="Tone Amplitude (dBFS)",
        y_title="2-tone SFDR (dBFS)",
        caption="",
    )
    # 4-221's caption reaches back to x=255, 12 pt left of the left frame's
    # right edge, and sits 20 pt *nearer* to that frame than 4-220's own
    # caption does: nearest-with-slack picks it, overlap does not.
    page.insert_text((62, 300), "Figure 4-220. TX IMD3 vs DSA Setting", fontsize=8)
    page.insert_text((255, 280), "Figure 4-221. TX 2-Tone SFDR vs Amplitude", fontsize=8)
    path = tmp_path / "grid.pdf"
    doc.save(str(path))
    doc.close()

    catalog = {a.figure_number: a for a in read_axis_catalog(path)}
    assert set(catalog) == {"4-220", "4-221"}
    assert catalog["4-220"].x.label == "DSA Setting"
    assert catalog["4-220"].y.label == "IMD3"
    assert catalog["4-221"].x.label == "Tone Amplitude"
    assert catalog["4-221"].y.label == "2-tone SFDR"


def test_a_tick_row_drawn_as_one_text_line_is_still_read(tmp_path):
    """Some plots draw the whole tick row as a single text line
    (`"1200 1350 1500 1650"`). Exploding it on its own glyph boxes is what
    keeps that class of figure out of the honestly-null population."""
    doc = fitz.open()
    page = doc.new_page(width=320, height=340)
    page.insert_text((70, 248), "1200  1350  1500  1650  1800", fontsize=6)
    for i, label in enumerate(["-2", "0", "2", "4", "6"]):
        w = fitz.get_text_length(label, fontsize=6)
        page.insert_text((66 - w, 240 - i * 40), label, fontsize=6)
    page.insert_text((100, 262), "Output Frequency (MHz)", fontsize=6)
    page.insert_text((44, 150), "HD3 (dBFS)", fontsize=6, rotate=90)
    page.insert_text((62, 280), "Figure 4-9. One-Line Ticks", fontsize=8)
    path = tmp_path / "oneline.pdf"
    doc.save(str(path))
    doc.close()

    (axes,) = read_axis_catalog(path)
    assert (axes.x.min, axes.x.max) == (1200.0, 1800.0)
    assert axes.y.label == "HD3"
    assert axes.confidence is Confidence.HIGH


def test_log_axis_is_marked_low_and_never_linearly_misreported(tmp_path):
    """A decade axis has a true range and a false linear mapping. The
    endpoints are printed, so they are kept; the grade drops to `low` so no
    consumer reads a linear mapping into them."""
    pdf = _one_plot_pdf(
        tmp_path / "log.pdf",
        x_ticks=["1", "10", "100", "1000", "10000"],
        y_ticks=["-160", "-140", "-120", "-100", "-80"],
        x_title="Offset Frequency (kHz)",
        y_title="Phase Noise (dBc/Hz)",
        caption="Figure 4-3. Phase Noise",
    )
    (axes,) = read_axis_catalog(pdf)
    assert axes.x.scale == "log"
    assert (axes.x.min, axes.x.max) == (1.0, 10000.0)  # printed endpoints, kept
    assert axes.y.scale == "linear"
    assert axes.confidence is Confidence.LOW


def test_uneven_or_nonaffine_numbers_are_not_an_axis(tmp_path):
    """A legend column of unrelated numbers is not a tick sequence, and the
    honest outcome is a null range rather than a plausible one."""
    doc = fitz.open()
    page = doc.new_page(width=320, height=340)
    for i, label in enumerate(["600", "750", "900", "1050", "1200"]):
        w = fitz.get_text_length(label, fontsize=6)
        page.insert_text((66 - w, 90 + i * 40), label, fontsize=6)
    # a row of numbers that is aligned but neither evenly spaced nor affine
    for x, label in ((80, "3"), (95, "17"), (150, "4"), (210, "91")):
        page.insert_text((x, 248), label, fontsize=6)
    page.insert_text((62, 280), "Figure 4-4. Not A Plot", fontsize=8)
    path = tmp_path / "notaplot.pdf"
    doc.save(str(path))
    doc.close()
    assert read_axis_catalog(path) == []


def test_a_frame_without_a_caption_is_not_reported(tmp_path):
    """Without a caption there is no `PlotRecord` a frame could belong to,
    and guessing which one it is would be worse than not reporting it."""
    pdf = _one_plot_pdf(tmp_path / "nocaption.pdf", caption="", **LINEAR)
    assert read_axis_catalog(pdf) == []


def test_page_axes_is_deterministic(tmp_path):
    pdf = _one_plot_pdf(tmp_path / "det.pdf", **LINEAR)
    with fitz.open(str(pdf)) as doc:
        first = page_axes(doc[0])
        second = page_axes(doc[0])
    assert first == second


# --- annotating a catalog ---------------------------------------------------


def _record(**kwargs) -> PlotRecord:
    base = {
        "id": "4.1-f001",
        "section": "4.1",
        "caption": "Figure 4-1 Synthetic Plot",
        "figure_number": "4-1",
        "conditions": "TA = 25 C",
        "page_start": 1,
        "page_end": 1,
        "file": "docs/datasheet-aaaaaaaa/figures/4-1/4.1-f001.png",
        "tags": ["tx"],
    }
    base.update(kwargs)
    return PlotRecord(**base)


def _plotset(records: list[PlotRecord]) -> PlotSet:
    return PlotSet(
        schema_version=PLOTS_SCHEMA_VERSION,
        part_number="TEST",
        doc_hash="x" * 64,
        plots=records,
    )


def test_annotate_fills_the_record_and_reports_coverage(tmp_path):
    pdf = _one_plot_pdf(tmp_path / "one.pdf", **LINEAR)
    plotset = _plotset([_record()])
    coverage = annotate_plot_axes(plotset, pdf)

    (rec,) = plotset.plots
    assert (rec.x_label, rec.x_unit, rec.x_min, rec.x_max) == (
        "Output Frequency",
        "MHz",
        600.0,
        1500.0,
    )
    assert (rec.y_label, rec.y_unit, rec.y_min, rec.y_max) == (
        "Output Full Scale",
        "dBm",
        -2.0,
        6.0,
    )
    assert rec.axis_confidence is Confidence.HIGH
    assert coverage.total == 1
    assert coverage.high == 1
    assert coverage.high_fraction == 1.0
    assert coverage.as_dict()["by_confidence"] == {"high": 1}


def test_no_plot_is_lost_to_a_failed_axis_parse(tmp_path):
    """The one thing the axis pass may never do: cost the catalog a figure.
    An unreadable plot keeps caption, conditions, tags and pixels and simply
    says `low`."""
    pdf = _one_plot_pdf(tmp_path / "one.pdf", **LINEAR)
    readable = _record()
    unreadable = _record(
        id="4.1-f002",
        figure_number="9-9",
        caption="Figure 9-9 Raster Spectrum Screenshot",
        conditions="TM1.1, POUT = -13 dBFS",
        tags=["tx", "acpr"],
        file="docs/datasheet-aaaaaaaa/figures/4-1/4.1-f002.png",
    )
    plotset = _plotset([readable, unreadable])
    coverage = annotate_plot_axes(plotset, pdf)

    assert len(plotset.plots) == 2
    kept = plotset.plots[1]
    assert kept.caption == "Figure 9-9 Raster Spectrum Screenshot"
    assert kept.conditions == "TM1.1, POUT = -13 dBFS"
    assert kept.tags == ["tx", "acpr"]
    assert kept.file.endswith("4.1-f002.png")
    assert kept.x_label == "" and kept.y_label == ""
    assert kept.x_min is None and kept.x_max is None
    assert kept.y_min is None and kept.y_max is None
    assert kept.axis_confidence is Confidence.LOW
    assert coverage.by_confidence == {"high": 1, "low": 1}


def test_annotate_is_idempotent(tmp_path):
    pdf = _one_plot_pdf(tmp_path / "one.pdf", **LINEAR)
    first = _plotset([_record()])
    second = _plotset([_record()])
    annotate_plot_axes(first, pdf)
    annotate_plot_axes(second, pdf)
    annotate_plot_axes(second, pdf)
    assert first.model_dump() == second.model_dump()


def test_a_catalog_written_before_the_axis_fields_still_loads(tmp_path):
    """The schema is additive, which is what "no migration" means here.

    A `plots.json` published before ticket 08 carries none of the nine axis
    keys. It must load — as *unknown*, not as a confident empty read — so the
    later digitisation pass this catalog is groundwork for can add its own
    fields the same way.
    """
    old = {
        "schema_version": PLOTS_SCHEMA_VERSION,
        "part_number": "TEST",
        "doc_hash": "x" * 64,
        "plots": [
            {
                "id": "4.1-f001",
                "section": "4.1",
                "caption": "Figure 4-1 Pre-Phase-6 Record",
                "figure_number": "4-1",
                "conditions": "TA = 25 C",
                "page_start": 1,
                "page_end": 1,
                "file": "docs/datasheet-aaaaaaaa/figures/4-1/4.1-f001.png",
                "tags": ["tx"],
                "confidence": "high",
            }
        ],
    }
    plotset = PlotSet.model_validate(old)
    (rec,) = plotset.plots
    assert rec.caption == "Figure 4-1 Pre-Phase-6 Record"
    assert rec.axis_confidence is Confidence.UNKNOWN
    assert (rec.x_label, rec.y_label, rec.x_unit, rec.y_unit) == ("", "", "", "")
    assert rec.x_min is rec.x_max is rec.y_min is rec.y_max is None


# --- the pipeline seam ------------------------------------------------------


def _raw_document(pdf: Path, extractor: str) -> object:
    from datasheet_analyzer.models import (
        DocType,
        FigureRef,
        RawDocument,
        SectionNode,
        SourceDocument,
    )

    section = SectionNode(
        number="4.1",
        title="Typical Characteristics",
        page_start=1,
        page_end=1,
        figures=[FigureRef(caption="Figure 4-1. Synthetic Plot", conditions="TA=25C", page=1)],
    )
    source = SourceDocument(
        path=str(pdf),
        part_number="TEST",
        doc_type=DocType.DATASHEET,
        content_hash="a" * 64,
    )
    return RawDocument(source=source, sections=[section], extractor=extractor)


def test_pipeline_annotates_from_the_pdf_whatever_the_extractor(tmp_path):
    """A TI part's figure catalog comes from the HTML datasheet while its
    axes are printed in the PDF, so the pass is keyed on the source file
    rather than on `raw.extractor`."""
    from datasheet_analyzer import pipeline
    from datasheet_analyzer.structure.plots import build_plotset

    pdf = _one_plot_pdf(tmp_path / "wired.pdf", **LINEAR)
    for extractor in ("pdf_layout", "ti_html"):
        raw = _raw_document(pdf, extractor)
        plotset = build_plotset(raw, "TEST")
        pipeline._annotate_axes(plotset, raw)
        (rec,) = plotset.plots
        assert (rec.x_label, rec.x_min, rec.x_max) == ("Output Frequency", 600.0, 1500.0)
        assert rec.axis_confidence is Confidence.HIGH


def test_pipeline_leaves_a_document_with_no_local_pdf_unattempted(tmp_path):
    """`unknown` means nobody looked; `low` means someone looked and found
    nothing. A document the pass cannot open must claim the first."""
    from datasheet_analyzer import pipeline
    from datasheet_analyzer.structure.plots import build_plotset

    raw = _raw_document(Path("https://www.ti.com/lit/nope.html"), "ti_html")
    plotset = build_plotset(raw, "TEST")
    pipeline._annotate_axes(plotset, raw)
    (rec,) = plotset.plots
    assert rec.axis_confidence is Confidence.UNKNOWN
    assert rec.x_min is None and rec.y_min is None


# --- the filters the catalog exists to enable -------------------------------


def _corpus(tmp_path: Path, records: list[PlotRecord]) -> Path:
    part_dir = tmp_path / "parts" / "TEST"
    doc_dir = part_dir / "docs" / "datasheet-aaaaaaaa"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "plots.json").write_text(
        _plotset(records).model_dump_json(indent=2), encoding="utf-8"
    )
    return part_dir


@pytest.fixture
def axis_corpus(tmp_path) -> Path:
    """Three figures whose axes are known by construction: an output-power
    sweep over 600-1500 MHz, a gain sweep over 2-6 GHz, and one figure whose
    axes could not be read at all."""
    return _corpus(
        tmp_path,
        [
            _record(
                id="4.1-f001",
                figure_number="4-1",
                caption="Figure 4-1 TX Output Power vs Output Frequency",
                x_label="Output Frequency",
                x_unit="MHz",
                x_min=600.0,
                x_max=1500.0,
                y_label="Output Power",
                y_unit="dBm",
                y_min=-35.0,
                y_max=5.0,
                axis_confidence=Confidence.HIGH,
            ),
            _record(
                id="4.1-f002",
                figure_number="4-2",
                caption="Figure 4-2 RX Gain vs Input Frequency",
                x_label="Input Frequency",
                x_unit="GHz",
                x_min=2.0,
                x_max=6.0,
                y_label="Gain",
                y_unit="dB",
                y_min=10.0,
                y_max=30.0,
                axis_confidence=Confidence.HIGH,
            ),
            _record(
                id="4.1-f003",
                figure_number="4-3",
                caption="Figure 4-3 TX Output Spectrum",
                axis_confidence=Confidence.LOW,
            ),
        ],
    )


def test_find_plots_narrows_by_axis_label(axis_corpus):
    hits = find_plots(axis_corpus, y_label="gain")
    assert [h.id for h in hits] == ["4.1-f002"]


def test_find_plots_narrows_by_near_x_across_units(axis_corpus):
    """3.5 GHz is inside figure 4-2's 2-6 GHz sweep and outside figure 4-1's
    600-1500 MHz one; both comparisons are made on the same base unit."""
    assert [h.id for h in find_plots(axis_corpus, near_x="3.5GHz")] == ["4.1-f002"]
    assert [h.id for h in find_plots(axis_corpus, near_x="900MHz")] == ["4.1-f001"]
    assert [h.id for h in find_plots(axis_corpus, near_x="1.2GHz")] == ["4.1-f001"]


def test_axis_filters_and_together_and_rule_out_unread_figures(axis_corpus):
    assert find_plots(axis_corpus, x_label="Frequency", near_x="3.5GHz") == [
        h for h in find_plots(axis_corpus, near_x="3.5GHz")
    ]
    # the figure whose axes could not be read is never swept in by an axis
    # filter, however permissive
    for hits in (
        find_plots(axis_corpus, x_label="Frequency"),
        find_plots(axis_corpus, near_x="900MHz"),
        find_plots(axis_corpus, near_y="0"),
    ):
        assert "4.1-f003" not in [h.id for h in hits]
    # ... and is still in the catalog when nothing filters it
    assert len(find_plots(axis_corpus)) == 3
