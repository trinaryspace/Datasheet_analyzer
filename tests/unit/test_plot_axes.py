"""The plot axis catalog — geometric axis reading (phase 6, ticket 08).

Synthetic fitz PDFs modeled on the measured real geometry: AFE7950 prints two
plots to a row under their own `Figure N.` captions, tick labels at 6 pt with the
axis title at the same size a few points further out, a test-conditions sentence
at 8 pt below that, a rotated y-axis title beside the tick column, and — on its
phase-noise pages — a log x axis printed `1E+3 … 1E+8`.

Coverage:
- a linear plot reads both axes, labels, units, ranges and scales;
- the **rotated** y-axis title is read (the synthetic half of the ticket's
  criterion; the real half is in `tests/integration/test_phase3_plots.py`);
- a log axis is marked `log`, never linearly misreported, and an irregular tick
  sequence gets *no* scale rather than a plausible one;
- tick labels the PDF lays out as one run ("600 750 900 …") are still ticks;
- side-by-side figures split at the midpoint between their captions, and a tick
  column that belongs to a *neighbour's* plot is refused rather than paired;
- a legend of numbers is not an axis, and a conditions sentence is not a title;
- a figure whose axes cannot be read keeps its caption, conditions, page and
  image — no plot is lost to a failed axis parse — and says `low`;
- the schema is additive in both directions: a `plots.json` written before the
  catalog existed still loads, and one carrying a future digitization field
  loads too, so a later pass needs no migration.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import ClassVar

import fitz
import pytest

from datasheet_analyzer.config import PLOTS_SCHEMA_VERSION, Settings
from datasheet_analyzer.extract.pdf_layout import (
    FigureRegion,
    TextRun,
    figure_text_regions,
)
from datasheet_analyzer.models import AxisScale, Confidence, PlotRecord, PlotSet
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.structure.plot_axes import (
    DERIVATION,
    annotate_record,
    axis_population,
    axis_scale,
    read_axes,
    region_for,
    scale_agrees_with_geometry,
    split_title,
    tick_values,
)

PAGE_W, PAGE_H = 612.0, 792.0


def _plot_lines(
    x0: float,
    y_axis_x: float,
    y_base: float,
    *,
    x_ticks: list[str],
    y_ticks: list[str],
    x_title: str,
    y_title: str,
    caption: str,
    conditions: str = "",
    merged_x: bool = False,
) -> list[tuple]:
    """One synthetic vector plot: tick row, tick column, both titles, caption.

    Geometry mirrors the measured real thing — the tick row sits just above the
    axis title, which sits above an 8 pt conditions line and then the caption.
    """
    lines: list[tuple] = []
    tick_y = y_base
    if merged_x:
        lines.append((x0 + 6.0, tick_y, " ".join(x_ticks), 6.0, 0))
    else:
        for i, text in enumerate(x_ticks):
            lines.append((x0 + 6.0 + i * 27.0, tick_y, text, 6.0, 0))
    for i, text in enumerate(y_ticks):
        # right-aligned against the axis, top tick first
        lines.append((y_axis_x, tick_y - 8.0 - i * 13.0, text, 6.0, 0))
    lines.append((x0 + 40.0, tick_y + 7.0, x_title, 6.0, 0))
    lines.append((y_axis_x - 8.0, tick_y - 20.0, y_title, 6.0, 90))
    if conditions:
        lines.append((x0 - 4.0, tick_y + 20.0, conditions, 8.0, 0))
    lines.append((x0, tick_y + 40.0, caption, 8.0, 0))
    return lines


def _make_pdf(path: Path, pages: list[list[tuple]], toc: list[list] | None = None) -> None:
    """pages: list of pages; each page a list of (x, y, text, size, rotate)."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text, size, rotate in lines:
            page.insert_text((x, y), text, fontsize=size, rotate=rotate)
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()


def _regions(tmp_path: Path, pages: list[list[tuple]], name: str = "p.pdf"):
    pdf = tmp_path / name
    _make_pdf(pdf, pages)
    return figure_text_regions(pdf)


def _region_by_number(regions, number: str) -> FigureRegion:
    hits = [r for r in regions if r.figure_number == number]
    assert hits, f"no region for figure {number}: {[r.figure_number for r in regions]}"
    return hits[0]


LINEAR_PLOT = {
    "x_ticks": ["600", "750", "900", "1050", "1200", "1350", "1500"],
    "y_ticks": ["7", "6", "5", "4", "3", "2", "1", "0", "-1", "-2"],
    "x_title": "Output Frequency (MHz)",
    "y_title": "Output Full Scale (dBm)",
    "caption": "Figure 4-1. TX Output Fullscale vs Output Frequency",
    "conditions": "including PCB and cable losses, DSA = 0",
}


class TestTickGrammar:
    def test_a_tick_is_a_number_and_nothing_else(self):
        assert tick_values("600") == [600.0]
        assert tick_values("-2") == [-2.0]
        assert tick_values("−40") == [-40.0]  # unicode minus
        assert tick_values("1E+3") == [1000.0]
        assert tick_values("2.5") == [2.5]

    def test_prose_and_legends_are_not_ticks(self):
        assert tick_values("Tone = -8.4dBm") is None
        assert tick_values("25qC") is None
        assert tick_values("") is None
        assert tick_values("Output Frequency (MHz)") is None

    def test_a_letter_run_is_never_a_number(self):
        # Regression: a `-` written between `+` and the unicode minus inside a
        # character class is a *range* spanning half the Latin alphabet, which
        # reads the AD9081 drawing label "D095" as a number.
        assert tick_values("D095") is None
        assert tick_values("A1") is None

    def test_a_merged_run_is_the_whole_tick_row(self):
        assert tick_values("1200 1350 1500 1650") == [1200.0, 1350.0, 1500.0, 1650.0]
        assert tick_values("1200 1350 note") is None


class TestAxisScale:
    def test_uniform_differences_are_linear(self):
        assert axis_scale([600, 750, 900, 1050]) is AxisScale.LINEAR

    def test_a_truncated_last_step_is_still_linear(self):
        # AFE7950's temperature axis: -40, -15, 10, 35, 60, 85, **105**
        assert axis_scale([-40, -15, 10, 35, 60, 85, 105]) is AxisScale.LINEAR

    def test_uniform_ratios_are_log(self):
        assert axis_scale([1e3, 1e4, 1e5, 1e6, 1e7, 1e8]) is AxisScale.LOG

    def test_octaves_are_log_too(self):
        assert axis_scale([1, 2, 4, 8]) is AxisScale.LOG

    def test_neither_has_no_scale(self):
        # A rising sequence that is neither: taking logarithms compresses
        # everything, so the log bar has to be tight or this reads as log.
        assert axis_scale([1, 2, 4, 9]) is None
        assert axis_scale([5, 3, 8]) is None  # not monotone
        assert axis_scale([1]) is None


class TestScaleAgreesWithGeometry:
    """A log axis labelled at its minor ticks must not read as linear.

    `10 20 30 … 100` prints uniform *differences* and logarithmic *positions*, so
    the values alone say linear — which is the one shape the ticket's "never
    linearly misreported" clause is actually about. Where the ticks were laid out
    individually the rule is checked against the page's own geometry.
    """

    #: Six decades, printed one per equal step — the ordinary log axis.
    DECADES: ClassVar[list[float]] = [1e3, 1e4, 1e5, 1e6, 1e7, 1e8]

    def test_a_linear_axis_on_linear_positions_agrees(self):
        values = [0.0, 10.0, 20.0, 30.0, 40.0]
        positions = [100.0 + 20.0 * i for i in range(5)]
        assert scale_agrees_with_geometry(positions, values, AxisScale.LINEAR)

    def test_a_log_axis_on_log_positions_agrees(self):
        positions = [100.0 + 20.0 * i for i in range(6)]
        assert scale_agrees_with_geometry(positions, self.DECADES, AxisScale.LOG)

    def test_minor_tick_labels_on_a_log_axis_contradict_linear(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        # printed where a log axis puts them: position ∝ log10(value)
        positions = [100.0 + 200.0 * math.log10(v / 10.0) for v in values]
        assert axis_scale(values) is AxisScale.LINEAR  # the values alone lie
        assert not scale_agrees_with_geometry(positions, values, AxisScale.LINEAR)

    def test_a_merged_tick_run_states_no_positions_and_is_trusted(self):
        # One run holding the whole row: there is no per-tick position to check
        # against, so the value-derived rule stands rather than being refused on
        # evidence that does not exist.
        assert scale_agrees_with_geometry([120.0], [1.0, 2.0, 3.0], AxisScale.LINEAR)

    def test_a_contradicted_row_publishes_no_axis_at_all(self):
        """End to end, on hand-built runs so the tick positions are exact: no
        range without a rule, exactly as for an irregular sequence — the range
        would be right and every interpolation across it wrong."""
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        row = tuple(
            TextRun(
                text=str(v),
                x0=80.0 + 500.0 * math.log10(v / 10.0),
                y0=300.0,
                x1=94.0 + 500.0 * math.log10(v / 10.0),
                y1=306.0,
                size=6.0,
                rotated=False,
            )
            for v in values
        )
        title = (
            TextRun(text="Offset Frequency (Hz)", x0=250.0, y0=310.0, x1=340.0,
                    y1=316.0, size=6.0, rotated=False),
        )
        reading = read_axes(FigureRegion(
            page=1, caption="Figure 7. Phase Noise vs Offset Frequency",
            figure_number="7", x0=0.0, y0=0.0, x1=600.0, y1=330.0,
            runs=row + title,
        ))
        assert reading.x.scale is None
        assert reading.x.lo is None and reading.x.label == ""


class TestSplitTitle:
    def test_parenthesized_unit_splits_off_verbatim(self):
        assert split_title("Output Frequency (MHz)") == ("Output Frequency", "MHz")
        assert split_title("S21 [dB]") == ("S21", "dB")
        assert split_title("Temperature (Cq)") == ("Temperature", "Cq")

    def test_a_title_may_have_no_unit(self):
        assert split_title("Code") == ("Code", "")

    def test_a_long_parenthetical_is_not_a_unit(self):
        label, unit = split_title("Gain (see the note below the figure)")
        assert unit == ""
        assert label.startswith("Gain")

    def test_an_unclosed_bracket_yields_no_unit_and_keeps_the_fragment(self):
        """Measured on 5 of AFE7950's 514 figures (4-187, 4-189, 4-192, 4-236,
        4-238): PyMuPDF hands the rotated y title back as
        `'Uncalibrated Amplitude Differential Nonlinearity (dB'` — the closing
        bracket is simply not in the page's text stream. The label is what the
        page printed, fragment and all, and the unit stays empty rather than
        being guessed out of an unclosed bracket: those figures answer
        `--y-label` and honestly never `--near-x`.
        """
        label, unit = split_title(
            "Uncalibrated Amplitude Differential Nonlinearity (dB"
        )
        assert unit == ""
        assert label == "Uncalibrated Amplitude Differential Nonlinearity (dB"


class TestLinearFigure:
    @pytest.fixture
    def reading(self, tmp_path):
        regions = _regions(tmp_path, [_plot_lines(80.0, 100.0, 300.0, **LINEAR_PLOT)])
        return read_axes(_region_by_number(regions, "4-1"))

    def test_both_axes_read(self, reading):
        assert reading.x.label == "Output Frequency"
        assert reading.x.unit == "MHz"
        assert (reading.x.lo, reading.x.hi) == (600.0, 1500.0)
        assert reading.x.scale is AxisScale.LINEAR
        assert reading.y.label == "Output Full Scale"
        assert reading.y.unit == "dBm"
        assert (reading.y.lo, reading.y.hi) == (-2.0, 7.0)
        assert reading.y.scale is AxisScale.LINEAR

    def test_the_rotated_y_title_is_read(self, reading):
        # The synthetic half of the ticket's rotated-title criterion: the title
        # is inserted at rotate=90 and comes back whole, unit and all.
        assert reading.y.label == "Output Full Scale"

    def test_the_conditions_sentence_is_not_the_x_label(self, reading):
        assert "PCB" not in reading.x.label
        assert "losses" not in reading.x.label

    def test_the_record_grades_high_with_its_envelope(self, tmp_path):
        regions = _regions(tmp_path, [_plot_lines(80.0, 100.0, 300.0, **LINEAR_PLOT)])
        record = PlotRecord(id="p1", figure_number="4-1", page_start=1, page_end=1)
        annotate_record(record, read_axes(_region_by_number(regions, "4-1")))
        assert record.axis_confidence is Confidence.HIGH
        assert record.axis_page == 1
        assert record.axis_derivation == DERIVATION

    def test_annotating_is_idempotent(self, tmp_path):
        regions = _regions(tmp_path, [_plot_lines(80.0, 100.0, 300.0, **LINEAR_PLOT)])
        reading = read_axes(_region_by_number(regions, "4-1"))
        record = PlotRecord(id="p1", figure_number="4-1")
        first = annotate_record(record, reading).model_dump()
        second = annotate_record(record, reading).model_dump()
        assert first == second

    def test_a_merged_tick_run_still_reads(self, tmp_path):
        regions = _regions(
            tmp_path, [_plot_lines(80.0, 100.0, 300.0, merged_x=True, **LINEAR_PLOT)]
        )
        reading = read_axes(_region_by_number(regions, "4-1"))
        assert (reading.x.lo, reading.x.hi) == (600.0, 1500.0)
        assert reading.x.label == "Output Frequency"


class TestLogAxis:
    def test_a_log_axis_is_marked_log(self, tmp_path):
        regions = _regions(tmp_path, [_plot_lines(
            80.0, 100.0, 300.0,
            x_ticks=["1E+3", "1E+4", "1E+5", "1E+6", "1E+7", "1E+8"],
            y_ticks=["-80", "-90", "-100", "-110", "-120", "-130", "-140"],
            x_title="Offset Frequency (Hz)",
            y_title="Phase Noise (dBc/Hz)",
            caption="Figure 4-491. Phase Noise vs Offset Frequency",
        )])
        reading = read_axes(_region_by_number(regions, "4-491"))
        assert reading.x.scale is AxisScale.LOG
        assert (reading.x.lo, reading.x.hi) == (1000.0, 1e8)
        assert reading.y.scale is AxisScale.LINEAR

    def test_an_irregular_axis_is_refused_not_called_linear(self, tmp_path):
        regions = _regions(tmp_path, [_plot_lines(
            80.0, 100.0, 300.0,
            x_ticks=["1", "2", "4", "9"],
            y_ticks=["10", "20", "30", "40"],
            x_title="Something (dB)",
            y_title="Other (dB)",
            caption="Figure 9. Irregular",
        )])
        reading = read_axes(_region_by_number(regions, "9"))
        assert reading.x.scale is None
        assert reading.x.lo is None  # refused whole: no range without a rule
        assert reading.x.label == ""


class TestSideBySide:
    """Two figures on one baseline must not lend each other an axis."""

    @pytest.fixture
    def regions(self, tmp_path):
        left = _plot_lines(
            80.0, 100.0, 300.0,
            x_ticks=["600", "750", "900", "1050"],
            y_ticks=["7", "6", "5", "4"],
            x_title="Output Frequency (MHz)",
            y_title="Output Full Scale (dBm)",
            caption="Figure 4-1. TX Output Fullscale vs Output Frequency",
        )
        right = _plot_lines(
            340.0, 360.0, 300.0,
            x_ticks=["-40", "-15", "10", "35"],
            y_ticks=["6", "5", "4", "3"],
            x_title="Temperature (Cq)",
            y_title="Output Power (dBm)",
            caption="Figure 4-2. TX Output Fullscale vs Temperature",
        )
        return _regions(tmp_path, [left + right])

    def test_each_figure_gets_two_regions(self, regions):
        assert sorted(r.figure_number for r in regions) == ["4-1", "4-2"]

    def test_each_reads_its_own_axes(self, regions):
        left = read_axes(_region_by_number(regions, "4-1"))
        right = read_axes(_region_by_number(regions, "4-2"))
        assert left.x.label == "Output Frequency"
        assert (left.x.lo, left.x.hi) == (600.0, 1050.0)
        assert right.x.label == "Temperature"
        assert (right.x.lo, right.x.hi) == (-40.0, 35.0)
        assert right.y.label == "Output Power"


class TestRefusals:
    def test_a_region_with_no_text_reads_nothing(self):
        reading = read_axes(FigureRegion(
            page=3, caption="Figure 6. HD2 vs fOUT", figure_number="6",
            x0=0.0, y0=0.0, x1=600.0, y1=300.0, runs=(),
        ))
        assert reading.x.lo is None and reading.y.lo is None
        assert not reading.any_read

    def test_a_legend_of_numbers_is_not_an_axis(self):
        # Three numeric runs stacked mid-figure with no monotone order.
        runs = tuple(
            TextRun(text=t, x0=200.0, y0=100.0 + i * 8.0, x1=214.0,
                    y1=106.0 + i * 8.0, size=6.0, rotated=False)
            for i, t in enumerate(["5", "1", "9"])
        )
        reading = read_axes(FigureRegion(
            page=1, caption="Figure 1. X", figure_number="1",
            x0=0.0, y0=0.0, x1=600.0, y1=300.0, runs=runs,
        ))
        assert not reading.any_read

    def test_a_range_nobody_named_is_not_published(self):
        """AD9081's `Figure 100.` is a 324-ball package outline whose dimension
        callouts form a monotone right-aligned column reading as a y axis from
        1.44 upward. No title names it, so no axis exists — a number nobody can
        name is unusable to every consumer and a false value here."""
        column = tuple(
            TextRun(text=t, x0=90.0, y0=100.0 + i * 13.0, x1=104.0,
                    y1=106.0 + i * 13.0, size=6.0, rotated=False)
            for i, t in enumerate(["3.44", "2.44", "1.44"])
        )
        row = tuple(
            TextRun(text=t, x0=110.0 + i * 27.0, y0=150.0, x1=124.0 + i * 27.0,
                    y1=156.0, size=6.0, rotated=False)
            for i, t in enumerate(["1.0", "2.0", "3.0"])
        )
        reading = read_axes(FigureRegion(
            page=45, caption="Figure 100. 324-Ball Ball Grid Array",
            figure_number="100", x0=0.0, y0=0.0, x1=600.0, y1=300.0,
            runs=column + row,
        ))
        assert not reading.any_read
        assert reading.x.lo is None and reading.y.lo is None

    def test_a_neighbours_tick_row_is_not_paired(self):
        """A y column on the left and an x row 300 pt to its right are two
        figures' axes, and pairing them would publish an axis this figure does
        not have."""
        y_col = tuple(
            TextRun(text=t, x0=90.0, y0=100.0 + i * 13.0, x1=104.0,
                    y1=106.0 + i * 13.0, size=6.0, rotated=False)
            for i, t in enumerate(["30", "20", "10"])
        )
        x_row = tuple(
            TextRun(text=t, x0=400.0 + i * 27.0, y0=160.0, x1=414.0 + i * 27.0,
                    y1=166.0, size=6.0, rotated=False)
            for i, t in enumerate(["600", "750", "900"])
        )
        reading = read_axes(FigureRegion(
            page=1, caption="Figure 1. X", figure_number="1",
            x0=0.0, y0=0.0, x1=600.0, y1=300.0, runs=y_col + x_row,
        ))
        assert reading.x.lo is None
        assert reading.y.lo is None

    def test_an_unlocatable_region_grades_low_with_nothing_filled(self):
        record = PlotRecord(id="p1", figure_number="99", x_label="stale",
                            x_min=1.0, x_scale=AxisScale.LINEAR)
        annotate_record(record, None)
        assert record.axis_confidence is Confidence.LOW
        assert record.x_label == "" and record.x_min is None
        assert record.x_scale is None
        assert record.axis_page is None and record.axis_derivation == ""


class TestRegionFor:
    def _regions(self, tmp_path):
        page1 = _plot_lines(80.0, 100.0, 300.0, **LINEAR_PLOT)
        page2 = _plot_lines(
            80.0, 100.0, 300.0,
            x_ticks=["1", "2", "3", "4"], y_ticks=["4", "3", "2", "1"],
            x_title="A (dB)", y_title="B (dB)",
            caption="Figure 4-9. Something Else",
        )
        return _regions(tmp_path, [page1, page2])

    def test_matched_on_the_printed_figure_number(self, tmp_path):
        regions = self._regions(tmp_path)
        record = PlotRecord(id="p", figure_number="4-9", page_start=1, page_end=2)
        assert region_for(record, regions).page == 2

    def test_a_number_unique_in_the_document_resolves_outside_the_range(self, tmp_path):
        # A section range that stops one page short of its last figure is a
        # page-mapping gap, not evidence about the figure (measured: 4 of
        # AFE7950's 514 records).
        regions = self._regions(tmp_path)
        record = PlotRecord(id="p", figure_number="4-9", page_start=1, page_end=1)
        assert region_for(record, regions).page == 2

    def test_a_record_with_no_figure_number_resolves_to_nothing(self, tmp_path):
        regions = self._regions(tmp_path)
        assert region_for(PlotRecord(id="p"), regions) is None

    def test_an_ambiguous_number_resolves_to_nothing(self, tmp_path):
        # The same number printed twice in one document is not a coin flip.
        lines = _plot_lines(80.0, 100.0, 300.0, **LINEAR_PLOT)
        regions = _regions(tmp_path, [lines, lines])
        record = PlotRecord(id="p", figure_number="4-1", page_start=1, page_end=2)
        assert region_for(record, regions) is None


class TestAxisPopulation:
    def _records(self) -> list[PlotRecord]:
        good = PlotRecord(
            id="a", x_label="Output Frequency", x_min=600.0, x_max=1500.0,
            x_scale=AxisScale.LINEAR, y_label="Gain", y_min=0.0, y_max=10.0,
            y_scale=AxisScale.LINEAR, axis_confidence=Confidence.HIGH,
        )
        blind = PlotRecord(id="b", axis_confidence=Confidence.LOW)
        never = PlotRecord(id="c")
        return [good, blind, never]

    def test_counts_and_sentence(self):
        population = axis_population(self._records())
        assert (population.total, population.readable, population.unreadable) == (3, 1, 2)
        assert "2 of 3 figures publish no readable x axis" in population.describe()
        assert "1 were never read" in population.describe()

    def test_all_readable_says_so(self):
        population = axis_population(self._records()[:1])
        assert population.describe() == "all 1 figures publish a readable x axis"

    def test_empty_catalog(self):
        assert axis_population([]).describe() == "0 figures cataloged"

    def test_unknown_axis_is_refused(self):
        with pytest.raises(ValueError, match="unknown axis"):
            axis_population([], axis="z")


class TestSchemaIsAdditive:
    """A later digitization pass must land without a migration."""

    def test_a_plotset_written_before_the_catalog_still_loads(self):
        legacy = json.dumps({
            "schema_version": "2", "part_number": "TEST", "doc_hash": "x" * 64,
            "plots": [{"id": "4.1-f001", "caption": "Figure 1. X",
                       "conditions": "TA = 25C", "page_start": 4, "page_end": 4}],
        })
        plotset = PlotSet.model_validate_json(legacy)
        record = plotset.plots[0]
        assert record.caption == "Figure 1. X"
        assert record.conditions == "TA = 25C"
        # Never graded, rather than optimistically graded.
        assert record.axis_confidence is Confidence.UNKNOWN
        assert record.x_label == "" and record.x_min is None and record.x_scale is None

    def test_a_plotset_carrying_a_future_field_still_loads(self):
        future = json.dumps({
            "schema_version": "9", "part_number": "TEST", "doc_hash": "x" * 64,
            "plots": [{
                "id": "4.1-f001", "caption": "Figure 1. X",
                "x_label": "Frequency", "x_unit": "MHz", "x_min": 600.0,
                "x_max": 1500.0, "x_scale": "linear",
                # what a digitization pass would add beside the axis frame
                "curves": [{"name": "typ", "samples": [[600.0, 1.0]]}],
            }],
        })
        record = PlotSet.model_validate_json(future).plots[0]
        assert record.x_label == "Frequency"
        assert record.x_scale is AxisScale.LINEAR

    def test_the_schema_version_moved_with_the_catalog(self):
        assert PLOTS_SCHEMA_VERSION == "3"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """A corpus built through the real pipeline seam, holding two figures: one
    vector plot with readable axes and one whose plot is a raster image (no text
    inside its region at all — measured: all 100 AD9081 plots)."""
    tmp = tmp_path_factory.mktemp("axes_build")
    readable = _plot_lines(80.0, 100.0, 300.0, **LINEAR_PLOT)
    blind = [
        (80.0, 500.0, "TM1.1, POUT_RMS = -13 dBFS", 8.0, 0),
        (80.0, 540.0, "Figure 4-32. TX Output FFT", 8.0, 0),
    ]
    pdf = tmp / "axes.pdf"
    _make_pdf(pdf, [readable + blind], toc=[[1, "4 Typical Characteristics", 1]])
    settings = Settings(parts_dir=tmp / "parts", cache_dir=tmp / ".cache").resolve()
    result = build_part(pdf, part_number="AXES", settings=settings,
                        vendor="unknown", use_llm=False)
    doc_dir = (result.part_dir / "docs"
               / f"datasheet-{result.manifest.documents[0].content_hash[:8]}")
    return json.loads((doc_dir / "plots.json").read_text(encoding="utf-8"))


class TestPublishedCorpus:
    """The pipeline seam: a built corpus carries the catalog, and no figure is
    lost to a failed axis parse."""

    def test_the_readable_figure_publishes_its_axes(self, built):
        assert built["schema_version"] == PLOTS_SCHEMA_VERSION
        rec = next(p for p in built["plots"] if p["figure_number"] == "4-1")
        assert rec["x_label"] == "Output Frequency"
        assert rec["x_unit"] == "MHz"
        assert rec["x_min"] == 600.0 and rec["x_max"] == 1500.0
        assert rec["x_scale"] == "linear"
        assert rec["y_label"] == "Output Full Scale"
        assert rec["axis_confidence"] == "high"
        assert rec["axis_page"] == 1
        assert rec["axis_derivation"] == DERIVATION

    def test_the_unreadable_figure_keeps_everything_but_the_axes(self, built):
        rec = next(p for p in built["plots"] if p["figure_number"] == "4-32")
        assert rec["caption"] == "Figure 4-32. TX Output FFT"
        assert rec["page_start"] == 1
        assert rec["file"], "the figure still renders a PNG"
        assert rec["axis_confidence"] == "low"
        for field in ("x_label", "x_unit", "y_label", "y_unit", "axis_derivation"):
            assert rec[field] == ""
        for field in ("x_min", "x_max", "y_min", "y_max", "x_scale", "y_scale",
                      "axis_page"):
            assert rec[field] is None

    def test_no_figure_is_lost(self, built):
        assert sorted(p["figure_number"] for p in built["plots"]) == ["4-1", "4-32"]
