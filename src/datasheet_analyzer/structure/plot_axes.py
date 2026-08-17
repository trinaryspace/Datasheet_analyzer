"""The plot axis catalog — what a figure's two axes say, read geometrically.

Phase 6, ticket 08. A part like AFE7950 prints **514** figures cataloged by
caption and test conditions alone, which is enough to grep and not enough to
choose: an agent that wants "gain versus frequency around 3.5 GHz" opens one,
spends a vision call discovering it was the wrong one, and opens another. This
module reads the axes off the page so that choice can be made from text.

Everything here is geometry over the text a PDF already prints inside a
figure's own caption-anchored region (`extract/pdf_layout.figure_text_regions`),
and every rule is allowed to fail:

- **The tick row and the tick column find themselves.** Tick labels are
  numbers, they share a baseline along the bottom edge and a right edge along
  the left one, and they run monotonically. So the x row is the bottom-most
  baseline cluster of numeric runs whose values are monotone, and the y column
  the leftmost right-edge cluster of the same. A legend of numbers does not
  qualify — it is neither monotone nor evenly spaced.
- **The two must form an L.** A reading is only accepted when the tick column
  sits left of the middle of the tick row and the tick row sits just below the
  column's last tick (`_frame_ok`). This is what stops the left plot's y axis
  being paired with the right plot's x axis when a band holds two figures —
  a *wrong* axis pair is far worse than none, because it looks exactly like a
  right one.
- **No title, no axis.** A tick sequence whose title the page did not print (or
  printed somewhere this reader could not follow) is discarded rather than
  published as a bare range. A number nobody can name is unusable to every
  consumer — `--near-x` needs the unit, which lives in the title — and it is
  worse than unusable when it is not an axis at all: AD9081 prints a
  324-ball package outline as `Figure 100.`, and its dimension callouts form a
  perfectly monotone right-aligned column that reads as a y axis from 1.44
  upward. A range with no name is exactly how that becomes a published number.
- **An axis title is the text run parallel to its edge.** The x title is the
  nearest non-numeric run below the tick row, inside the row's own x span; the
  y title is the rotated run nearest the tick column, which PyMuPDF reports by
  line direction rather than by a guess from the box shape. Both are bounded to
  roughly tick-label size, which is what keeps a figure's own test-conditions
  sentence — printed a few points further down, in the body font — out of the
  `x_label` field.
- **A scale is read, never assumed.** Uniform differences are `LINEAR`, uniform
  ratios `LOG` (measured: AFE7950 prints 15 log axes, `1E+3 … 1E+8` under
  "Offset Frequency (Hz)"). A sequence that is neither has no scale at all, and
  the field says so instead of implying that a linear interpolation is safe —
  which is precisely the confidently-wrong number invariant 8 exists to
  prevent, and the reason curve digitization is out of scope until it has a
  gate of its own. The values alone cannot tell one shape apart — a log axis
  labelled at its *minor* ticks (`10 20 30 … 100`) prints uniform differences —
  so where the ticks were laid out individually the rule is checked against
  **where they are printed** (`scale_agrees_with_geometry`) and a contradiction
  refuses the tick set.

What the module never does is **lose a figure**. `annotate_plots` writes into
additive fields only; a figure whose region held no text at all (AD9081's plots
are raster images, so nothing is printed inside them) keeps its caption, its
conditions, its page and its image file, and reports `axis_confidence: low`
with every axis field null. `axis_population` is the honesty half a filter on a
derived value needs (invariant 8): a consumer narrowing 514 figures by axis
must be able to say how many it could not consider.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING

from datasheet_analyzer.models import AxisScale, Confidence, PlotRecord, PlotSet
from datasheet_analyzer.structure.confidence import grade_plot_axes

if TYPE_CHECKING:  # pragma: no cover - typing only
    # The region reader lives in the extraction layer (it is PDF geometry); this
    # module is pure over what it hands back, so the import stays a type-only
    # one and nothing in `structure/` or `retrieve/` drags PyMuPDF in to read a
    # published record's axis fields.
    from datasheet_analyzer.extract.pdf_layout import FigureRegion, TextRun

#: The rule name a plot record's axis block records as its `derivation`
#: (invariant 8): the figure's caption-anchored region, the tick clusters inside
#: it, and the parallel text run that titles each edge.
DERIVATION = "figure_region+tick_cluster+axis_title_run"

# A printed tick label. Anchored, like the numeric layer's grammar: a tick is a
# number and nothing else, so "25qC" (a legend entry whose degree glyph the font
# mangled) is not a tick and "1E+3" is. The unicode minus is listed explicitly
# and last inside the class — a bare `-` between `+` and `−` would be a *range*
# spanning half the Latin alphabet, which reads "D095" as a number.
_NUMBER_RE = re.compile(r"^[-+−]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$")

# The unit a title parenthesizes: "Output Frequency (MHz)", "S21 [dB]". Bounded
# in length so a title ending in a parenthetical phrase ("(see Note 2)") is not
# read as a unit — and read only at the very end of the run, which is where an
# axis title prints it.
_UNIT_RE = re.compile(r"[(\[]([^()\[\]]{1,16})[)\]]\s*$")

#: Fewest tick labels an axis must print to be read at all. Two numbers state a
#: range but say nothing about the spacing between them, and the spacing is what
#: makes the scale checkable — so three is the floor.
MIN_TICKS = 3

# Tick geometry, all in points. Labels of one row share a baseline to within a
# fraction of their own height; labels of one column share a right edge (they
# are right-aligned against the axis, so their *left* edges differ by a digit's
# width).
_BASELINE_TAU = 2.0
_RIGHT_EDGE_TAU = 2.5
# How far from the printed sequence a spacing may drift and still count as
# uniform. AFE7950's temperature axis prints -40, -15, 10, 35, 60, 85, **105**
# — a truncated last step of 20 against 25 — so the bar has to admit 1.25, and
# it is deliberately nowhere near loose enough to call an arbitrary sequence
# linear (a legend of 1, 2, 4, 8 is 2.0 and stays unread).
_SPACING_TOLERANCE = 1.35
# The log bar is far tighter than the linear one, and deliberately so: taking
# logarithms compresses everything, so 1.35 in log space calls an arbitrary
# rising sequence logarithmic (1, 2, 4, 9 comes out at 1.17). A real log axis
# prints exact decades or exact octaves, so near-equality is the right bar and a
# sequence that misses it has no scale rather than the wrong one.
_LOG_TOLERANCE = 1.05
# How much better the *other* spacing rule has to fit the printed tick positions
# before the value-derived rule is treated as contradicted (`scale_agrees_with_
# geometry`). A real axis fits its own rule at r² ≈ 1, and the losing rule on a
# six-decade log axis comes out near 0.7, so the two are never close; this margin
# only absorbs a wide tick label's off-centre glyph box.
_FIT_MARGIN = 0.02
# The axis frame: how far below the tick column's last label the tick row may
# sit, and how far left of the row's first label the column may sit, before the
# two are no longer one figure's axes. Both are a plot label's own scale, not a
# page's.
_FRAME_GAP = 40.0
_FRAME_SKEW = 4.0
# An axis title is printed at about tick-label size and within a line or two of
# its edge. The size bar is what separates a title from the figure's
# test-conditions sentence (measured on AFE7950: 6.0 pt ticks and title against
# an 8.0 pt conditions line a dozen points lower).
_TITLE_GAP = 20.0
_TITLE_SIZE_RATIO = 1.35
_TITLE_X_SLACK = 8.0
_TITLE_Y_SLACK = 20.0
_TITLE_X_EDGE = 4.0


@dataclass(frozen=True)
class Axis:
    """One axis of one figure, as far as the page states it.

    `label` and `unit` are verbatim halves of the printed title; `lo`/`hi` are
    the first and last **tick label**, in the printed unit, which is a narrower
    claim than the drawn axis line's endpoints (no text states those).

    All of it travels together or not at all — an axis with no printed title is
    not published, see this module's docstring — so a reader has one state to
    reason about, and a `scale` of `None` on a published axis means the printed
    ticks follow neither a uniform difference nor a uniform ratio: the range is
    true and nothing may be interpolated across it.
    """

    label: str = ""
    unit: str = ""
    lo: float | None = None
    hi: float | None = None
    scale: AxisScale | None = None

    @property
    def has_range(self) -> bool:
        return self.lo is not None and self.hi is not None

    @property
    def complete(self) -> bool:
        """True when the axis states a title, a range and a spacing rule."""
        return bool(self.label) and self.has_range and self.scale is not None


@dataclass(frozen=True)
class AxisReading:
    """Both axes of one figure, plus the page they were read from."""

    x: Axis = field(default_factory=Axis)
    y: Axis = field(default_factory=Axis)
    page: int | None = None

    @property
    def any_read(self) -> bool:
        return self.x.complete or self.y.complete


@dataclass(frozen=True)
class _Ticks:
    """One accepted tick sequence: its runs, its values, its box."""

    runs: tuple[TextRun, ...]
    values: tuple[float, ...]
    scale: AxisScale

    @property
    def x0(self) -> float:
        return min(r.x0 for r in self.runs)

    @property
    def x1(self) -> float:
        return max(r.x1 for r in self.runs)

    @property
    def y0(self) -> float:
        return min(r.y0 for r in self.runs)

    @property
    def y1(self) -> float:
        return max(r.y1 for r in self.runs)

    @property
    def size(self) -> float:
        return max(r.size for r in self.runs)


def tick_values(text: str) -> list[float] | None:
    """The tick labels one text run holds, or `None` when it is not ticks.

    A run is ticks when *every* whitespace-separated token of it is a number.
    That double duty is deliberate: PyMuPDF lays a plot's x-tick labels out as
    one line as often as as several ("1200 1350 1500 1650 …" is one run,
    measured on 30 AFE7950 figures), and reading only single-number runs would
    silently lose exactly those axes. One token that is not a number makes the
    whole run text, because "Tone = -8.4dBm" is a legend, not an axis.
    """
    tokens = text.split()
    if not tokens:
        return None
    values: list[float] = []
    for token in tokens:
        if not _NUMBER_RE.match(token):
            return None
        values.append(float(token.replace("−", "-")))
    return values


def axis_scale(values: Sequence[float]) -> AxisScale | None:
    """The spacing rule a printed tick sequence follows, or `None`.

    Monotone with near-uniform differences is `LINEAR`; monotone with
    near-uniform ratios (and no non-positive value, where a log axis cannot go)
    is `LOG`. Anything else — a legend, a mis-clustered pair of columns, a
    genuinely irregular axis — has no rule, and saying so is what keeps a later
    digitization pass from interpolating across it.
    """
    if len(values) < 2:
        return None
    diffs = [b - a for a, b in pairwise(values)]
    if not (all(d > 0 for d in diffs) or all(d < 0 for d in diffs)):
        return None
    magnitudes = [abs(d) for d in diffs]
    if min(magnitudes) > 0 and max(magnitudes) / min(magnitudes) <= _SPACING_TOLERANCE:
        return AxisScale.LINEAR
    if all(v > 0 for v in values):
        ratios = [abs(math.log10(b / a)) for a, b in pairwise(values)]
        if min(ratios) > 0 and max(ratios) / min(ratios) <= _LOG_TOLERANCE:
            return AxisScale.LOG
    return None


def split_title(text: str) -> tuple[str, str]:
    """An axis title split into its label and its parenthesized unit.

    Both halves stay verbatim — `"Output Frequency (MHz)"` is
    `("Output Frequency", "MHz")` — because the printed unit is what a designer
    reads and canonicalizing it here would put a string on the record that no
    page printed. A title with no parenthetical has no unit, which is a
    legitimate axis ("Code", "Sample").

    A title whose bracket the page's own text stream never closes
    (`"…Nonlinearity (dB"`, measured on 5 of AFE7950's 514 figures — PyMuPDF
    hands back exactly that, closing paren and all, missing) has **no** unit and
    keeps the fragment in the label, because the label is what the page printed
    and inferring the unit from an unclosed bracket is a guess. The figure stays
    findable by `--y-label` and is honestly unmatchable by range
    (`KNOWN_SHORTCOMINGS.md`).
    """
    match = _UNIT_RE.search(text)
    if not match:
        return text.strip(), ""
    return text[: match.start()].strip().rstrip(",").strip(), match.group(1).strip()


def _r2(xs: Sequence[float], ys: Sequence[float]) -> float:
    """How well `ys` follows a straight line in `xs` (0…1), 0 when degenerate."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0.0 or syy <= 0.0:
        return 0.0
    return (sxy * sxy) / (sxx * syy)


def scale_agrees_with_geometry(
    positions: Sequence[float], values: Sequence[float], scale: AxisScale
) -> bool:
    """True unless where the labels are *printed* contradicts `scale`.

    `axis_scale` reads the spacing rule out of the tick **values** alone, and
    there is one printed shape it cannot tell apart: a log axis labelled at its
    minor ticks (`10 20 30 … 100`) prints values with a uniform difference and
    positions with a logarithmic one. Reading that as linear is exactly the
    "never linearly misreported" failure — the range would be right and every
    interpolation across it wrong.

    So where the ticks were laid out individually (a merged run states no
    positions and this cannot run), the value-derived rule is checked against the
    geometry: whichever of value-vs-position and log(value)-vs-position is the
    straighter line is what the page actually drew. A contradiction refuses the
    tick set rather than publishing the other rule — the same "no range without a
    rule" decision the module makes for an irregular sequence, for the same
    reason. `_FIT_MARGIN` keeps float noise and a wide label's off-centre box
    from counting as a contradiction; measured on AFE7950, all 446 individually
    laid-out tick rows agree, so this refuses nothing that reads today.
    """
    if len(positions) != len(values) or len(values) < MIN_TICKS:
        return True
    linear = _r2(positions, values)
    logarithmic = (
        _r2(positions, [math.log10(v) for v in values])
        if all(v > 0 for v in values)
        else 0.0
    )
    if scale is AxisScale.LINEAR:
        return logarithmic <= linear + _FIT_MARGIN
    return linear <= logarithmic + _FIT_MARGIN


def _cluster(runs: Sequence[TextRun], coord, tau: float) -> list[list[TextRun]]:
    """Runs grouped into chains whose successive `coord` differ by ≤ `tau`."""
    groups: list[list[TextRun]] = []
    for run in sorted(runs, key=coord):
        if groups and abs(coord(run) - coord(groups[-1][-1])) <= tau:
            groups[-1].append(run)
        else:
            groups.append([run])
    return groups


def _accept(runs: Sequence[TextRun], values: Sequence[float], coord) -> _Ticks | None:
    """A tick group, if it prints enough labels on a readable spacing.

    `coord` is where a run sits *along* the axis, which is what lets the spacing
    rule be checked against the page's own geometry (`scale_agrees_with_geometry`)
    instead of being trusted from the values alone.
    """
    if len(values) < MIN_TICKS:
        return None
    scale = axis_scale(values)
    if scale is None:
        return None
    if not scale_agrees_with_geometry([coord(r) for r in runs], values, scale):
        return None
    return _Ticks(runs=tuple(runs), values=tuple(values), scale=scale)


def _x_ticks(numeric: Sequence[tuple[TextRun, list[float]]]) -> _Ticks | None:
    """The bottom-most horizontal tick row of a region.

    Bottom-most because that is where a plot prints its x axis; a chart with a
    second numeric row higher up (a table of results inside the figure) loses to
    it rather than confusing it.
    """
    by_run = {id(run): vals for run, vals in numeric}
    best: _Ticks | None = None
    for group in _cluster([run for run, _ in numeric], lambda r: r.y0, _BASELINE_TAU):
        ordered = sorted(group, key=lambda r: r.x0)
        values = [v for run in ordered for v in by_run[id(run)]]
        ticks = _accept(ordered, values, lambda r: r.x_center)
        if ticks is not None and (best is None or ticks.y0 > best.y0):
            best = ticks
    return best


def _y_ticks(
    numeric: Sequence[tuple[TextRun, list[float]]], used: frozenset[int]
) -> _Ticks | None:
    """The leftmost vertical tick column of a region.

    Only single-number runs qualify: a y-tick label is one number on its own
    baseline, and a run holding several is a row, not a column. Leftmost because
    a plot prints its y axis on the left; a right-hand second y axis is
    deliberately not read rather than read as the first one.
    """
    singles = [(run, vals) for run, vals in numeric
               if len(vals) == 1 and id(run) not in used]
    by_run = {id(run): vals for run, vals in singles}
    best: _Ticks | None = None
    for group in _cluster([run for run, _ in singles], lambda r: r.x1, _RIGHT_EDGE_TAU):
        ordered = sorted(group, key=lambda r: r.y0)
        values = [by_run[id(run)][0] for run in ordered]
        ticks = _accept(ordered, values, lambda r: (r.y0 + r.y1) / 2.0)
        if ticks is not None and (best is None or ticks.x1 < best.x1):
            best = ticks
    return best


def _frame_ok(x: _Ticks, y: _Ticks) -> bool:
    """True when the two tick sets are plausibly one figure's axis frame.

    The x row must start at or right of the y column (the origin label of an
    x axis sits over the y labels, so the comparison is against the row's
    *middle*, not its left edge), and it must sit just below the column's last
    label. Two plots side by side fail the first test — their x spans are
    hundreds of points apart — and two plots stacked fail the second.
    """
    if y.x1 > (x.x0 + x.x1) / 2.0:
        return False
    if y.x1 < x.x0 - _FRAME_GAP:
        return False
    return -_FRAME_SKEW <= x.y0 - y.y1 <= _FRAME_GAP


def _x_title(runs: Sequence[TextRun], ticks: _Ticks) -> tuple[str, str]:
    """The label + unit printed under a tick row, or two empty strings."""
    candidates = [
        run for run in runs
        if not run.rotated
        and tick_values(run.text) is None
        and 0.0 < run.y0 - ticks.y0 <= _TITLE_GAP
        and run.x0 >= ticks.x0 - _TITLE_X_SLACK
        and run.x1 <= ticks.x1 + _TITLE_X_SLACK
        and run.size <= _TITLE_SIZE_RATIO * ticks.size
    ]
    if not candidates:
        return "", ""
    return split_title(min(candidates, key=lambda r: (r.y0, r.x0)).text)


def _y_title(runs: Sequence[TextRun], ticks: _Ticks) -> tuple[str, str]:
    """The label + unit printed rotated beside a tick column."""
    candidates = [
        run for run in runs
        if run.rotated
        and tick_values(run.text) is None
        and run.x1 <= ticks.x0 + _TITLE_X_EDGE
        and run.y1 >= ticks.y0 - _TITLE_Y_SLACK
        and run.y0 <= ticks.y1 + _TITLE_Y_SLACK
        and run.size <= _TITLE_SIZE_RATIO * ticks.size
    ]
    if not candidates:
        return "", ""
    return split_title(max(candidates, key=lambda r: (r.x1, -r.y0)).text)


def read_axes(region: FigureRegion) -> AxisReading:
    """Read both axes of one figure region. Pure, and allowed to read nothing.

    A region with no text inside it (a raster plot), one whose numbers are a
    legend rather than an axis, and one whose two tick sets do not form a frame
    all return an empty reading — which is the outcome the caller publishes as
    `axis_confidence: low` with every field null.
    """
    numeric: list[tuple[TextRun, list[float]]] = []
    for run in region.runs:
        if run.rotated:
            continue
        values = tick_values(run.text)
        if values:
            numeric.append((run, values))
    x_ticks = _x_ticks(numeric)
    used = frozenset(id(run) for run in x_ticks.runs) if x_ticks else frozenset()
    y_ticks = _y_ticks(numeric, used)
    if x_ticks is not None and y_ticks is not None and not _frame_ok(x_ticks, y_ticks):
        # Two tick sets that are not one figure's frame are two figures' — and
        # pairing them would publish an axis this figure does not have.
        x_ticks = y_ticks = None
    x_axis, y_axis = Axis(), Axis()
    if x_ticks is not None:
        label, unit = _x_title(region.runs, x_ticks)
        if label:
            x_axis = Axis(label=label, unit=unit, lo=min(x_ticks.values),
                          hi=max(x_ticks.values), scale=x_ticks.scale)
    if y_ticks is not None:
        label, unit = _y_title(region.runs, y_ticks)
        if label:
            y_axis = Axis(label=label, unit=unit, lo=min(y_ticks.values),
                          hi=max(y_ticks.values), scale=y_ticks.scale)
    return AxisReading(x=x_axis, y=y_axis, page=region.page)


def region_for(
    record: PlotRecord, regions: Iterable[FigureRegion]
) -> FigureRegion | None:
    """The figure region a plot record cites, or `None`.

    Matched on the **printed figure number**, which is the one identity both
    sides always agree on: a catalog caption comes from a vendor's HTML and the
    printed caption wraps over two lines, so the caption strings differ far more
    often than they match (measured on AFE7950: 320 of 514). The record's own
    page range is preferred, and a number that occurs exactly once in the
    document resolves outside it too — a figure number is document-unique, and a
    section range that stops one page short of its last figure is a page-mapping
    gap, not evidence about the figure. A number that occurs twice resolves to
    nothing rather than to a coin flip.
    """
    if not record.figure_number:
        return None
    same = [r for r in regions if r.figure_number == record.figure_number]
    if not same:
        return None
    in_range = [
        r for r in same
        if (record.page_start is None or r.page >= record.page_start)
        and (record.page_end is None or r.page <= record.page_end)
    ]
    if len(in_range) == 1:
        return in_range[0]
    if in_range:
        return None
    return same[0] if len(same) == 1 else None


def annotate_record(record: PlotRecord, reading: AxisReading | None) -> PlotRecord:
    """Write one figure's axis reading into its additive fields.

    Mutates the axis block and nothing else — caption, conditions, tags, page
    and file are extraction's and stay exactly as cataloged. Idempotent, so
    running it twice, or over a corpus that already carries the block, produces
    the same record.

    `reading is None` means the figure's region could not be located at all;
    it grades `low` with every field null, exactly like a region that held no
    readable axes, because both are "this figure's axes are not available".
    """
    axes = reading or AxisReading()
    record.x_label, record.x_unit = axes.x.label, axes.x.unit
    record.x_min, record.x_max, record.x_scale = axes.x.lo, axes.x.hi, axes.x.scale
    record.y_label, record.y_unit = axes.y.label, axes.y.unit
    record.y_min, record.y_max, record.y_scale = axes.y.lo, axes.y.hi, axes.y.scale
    record.axis_confidence = grade_plot_axes(record)
    # The envelope is filled only where a value exists to carry it: a figure
    # with no reading cites no page and names no rule, rather than pointing at a
    # page that printed nothing we could use.
    read_anything = bool(axes.x.has_range or axes.y.has_range)
    record.axis_page = axes.page if read_anything else None
    record.axis_derivation = DERIVATION if read_anything else ""
    return record


def annotate_plots(plotset: PlotSet, regions: Iterable[FigureRegion]) -> int:
    """Annotate every record of a plot set; returns how many graded `high`.

    Every record is visited, including the ones whose axes cannot be read: that
    is what turns "no axes" from an absent field into a stated finding, and it
    is why a figure is never lost to a failed axis parse.
    """
    regions = list(regions)
    high = 0
    for record in plotset.plots:
        region = region_for(record, regions)
        annotate_record(record, read_axes(region) if region is not None else None)
        if record.axis_confidence is Confidence.HIGH:
            high += 1
    return high


@dataclass(frozen=True)
class AxisPopulation:
    """What an axis filter could and could not consider (invariant 8).

    `dsa plots --near-x` selects on a *derived* value, so it owes the caller the
    population it never looked at — exactly as the numeric layer's
    `ParsePopulation` does for a comparison, and as `--field` does for a bit
    field. An empty result must never be readable as "this part has no such
    figure" when the truth is "half these figures print their axes as pixels".
    """

    axis: str
    total: int = 0
    readable: int = 0
    ungraded: int = 0

    @property
    def unreadable(self) -> int:
        return self.total - self.readable

    def describe(self) -> str:
        """The sentence a filter prints beside its result."""
        if not self.total:
            return "0 figures cataloged"
        if not self.unreadable:
            return f"all {self.total} figures publish a readable {self.axis} axis"
        return (
            f"{self.unreadable} of {self.total} figures publish no readable "
            f"{self.axis} axis and cannot be filtered on it"
            + (f" ({self.ungraded} were never read)" if self.ungraded else "")
        )


def axis_population(records: Iterable[PlotRecord], *, axis: str = "x") -> AxisPopulation:
    """Split a plot catalog into what an axis filter can and cannot consider.

    `axis` is `"x"` or `"y"`; a record counts as readable when that axis states
    both a label and a range, which is exactly what a label or range filter
    needs. Records are never dropped — that is the point.
    """
    if axis not in {"x", "y"}:
        raise ValueError(f"unknown axis {axis!r}; expected 'x' or 'y'")
    total = readable = ungraded = 0
    for record in records:
        total += 1
        label = getattr(record, f"{axis}_label")
        low = getattr(record, f"{axis}_min")
        if label and low is not None:
            readable += 1
        if record.axis_confidence is Confidence.UNKNOWN:
            ungraded += 1
    return AxisPopulation(axis=axis, total=total, readable=readable, ungraded=ungraded)
