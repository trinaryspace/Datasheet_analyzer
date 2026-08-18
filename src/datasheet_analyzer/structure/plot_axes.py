"""Geometric axis catalog for cataloged figures (phase 6, ticket 08).

514 figures for one part, catalogued by caption and conditions only, means an
agent burns a vision call to discover it opened the wrong one. This module
reads what the plot itself prints — the axis titles, the tick labels — so that
`find_plots --y-label Gain --near-x 3.5GHz` narrows the gallery *before* a
single vision token is spent, and `get_figure` hands back the one PNG.

**Everything here is geometry, and nothing here is a model call.** A vector
plot in a datasheet PDF prints its axes as ordinary text laid out in a shape
that is the same for every vendor:

    Output Full Scale (dBm)   <- rotated 90 deg, left of the y tick column
      7 |                          (PyMuPDF reports it via the line's `dir`)
      6 |    . . .
      ...|                     <- y tick labels: a column of numbers whose
     -2 |____________________     right edges align, evenly spaced
        600  750 ... 1500      <- x tick labels: a row of numbers whose
         Output Frequency (MHz)   baselines align, evenly spaced
      Figure 4-1. TX Output Fullscale vs Output Frequency

So the catalog is read, not inferred:

1. **Find tick clusters.** Numeric text lines whose right edges align form a
   candidate y column; whose baselines align, a candidate x row. Alignment
   alone is not enough — two side-by-side plots print their x ticks on the
   same baseline — so each cluster is then split wherever its spacing jumps
   to several times its own tightest step.
2. **Validate.** A cluster is a real axis only if it has at least
   `_MIN_TICKS` labels, is evenly spaced in *position*, and its *values* are
   affine in position. When the values are affine in log-position instead,
   the axis is logarithmic and is recorded as such (see below).
3. **Pair.** An x row and the y column immediately to its left form one
   plot's frame; the frame's caption is the nearest caption line below it
   that overlaps it horizontally. That is what ties a frame to a
   `PlotRecord`, via the printed figure number.
4. **Read the titles.** The x title is the non-numeric line just below the x
   tick row set in the tick's own type size (which is what separates it from
   the 8pt test-conditions note under it); the y title is the rotated line
   just left of the y tick column.

**Anything uncertain stays null.** A tick row that does not validate leaves
`x_min`/`x_max` `None` — never an interpolated endpoint, never a plausible
default — and says so through `axis_confidence`. A figure whose axes cannot
be read at all keeps its caption, conditions, tags and pixels: the axis
catalog is strictly additive and no plot is ever lost to a failed axis parse.

**Log axes are marked, not linearised.** A decade axis has a true range (its
first and last printed tick) and a false *mapping* (position is not
proportional to value). The range is recorded because it is printed; the
record is graded `low` so that no later consumer — in particular the curve
digitisation this catalog is groundwork for — can read a linear mapping into
it. That is the ticket's "handled or explicitly marked low-confidence, never
linearly misreported", chosen deliberately over dropping the values.

**Grades** (`PlotRecord.axis_confidence`):

| grade | meaning |
|---|---|
| `high` | both axes: title *and* validated linear range |
| `medium` | some of those four read, none of them log |
| `low` | attempted; nothing usable, or a log axis (values kept, mapping not implied) |
| `unknown` | never attempted — no PDF for this document, or a corpus built before the field existed |

Image *analysis* of the rendered PNG is a future consumer of this catalog and
is explicitly not built here; `PlotRecord`'s axis fields are additive and
independently optional, so a digitisation pass can add per-curve data later
without reshaping `plots.json`.
"""

from __future__ import annotations

import itertools
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from datasheet_analyzer.models import Confidence, PlotRecord, PlotSet

log = logging.getLogger(__name__)

# --- tuning constants, all in PDF points -----------------------------------
#: Ticks whose cross-axis coordinate is within this of the *first* tick of a
#: group belong to the same row/column. Loose enough for the sub-point jitter
#: a PDF prints, tight enough that the gap split below is what separates two
#: side-by-side plots printing their x ticks 1.1 pt apart (AFE7950 p.29:
#: 282.3 vs 283.4).
_ALIGN_TOL = 2.5
#: A cluster is split wherever the gap between neighbouring ticks exceeds this
#: multiple of the cluster's own *tightest* step. Tick pitch inside one plot
#: is constant, so the tightest step is the pitch; the jump to the next plot
#: is several times it. Measured against the median instead, two adjacent
#: plots of unequal pitch hide their own join inside the average (AFE7950
#: p.38: an 85 pt join under an 87 pt threshold).
_GAP_SPLIT = 2.5
#: Fewer labelled ticks than this is not enough evidence to call a set of
#: aligned numbers an axis. Three would admit one stray number per column of a
#: three-column figure grid; four does not.
_MIN_TICKS = 4
#: Tick spacing may deviate from the cluster median by this fraction.
_EVEN_TOL = 0.35
#: Max residual of the value-vs-position fit, as a fraction of the value span.
_FIT_TOL = 0.02
#: An axis title is set in the tick labels' own type size, give or take.
_TITLE_SIZE_TOL = 1.5
#: How far below the x tick row the x title may sit.
_X_TITLE_GAP = 26.0
#: How far left of the y tick column the y title may sit.
_Y_TITLE_GAP = 90.0
#: How far a caption may sit below its own plot frame.
_CAPTION_GAP = 140.0
#: How far the bottom y tick label may sit from the x tick row's own top. The
#: lowest y label is printed at the axis origin, so this is what tells one
#: plot's y column from the column of the plot stacked above it — which is at
#: the same x and would otherwise win on nearness alone.
_ORIGIN_TOL = 40.0

#: Printed figure captions. Anchored: "see Figure 4-1" inside a paragraph is a
#: cross-reference, not a caption, and must not anchor a frame.
_CAPTION_RE = re.compile(r"^Figure\s+([0-9]+(?:[-.][0-9]+)?[a-z]?)\b", re.IGNORECASE)

#: A tick label: an optional sign, a number, an optional exponent and an
#: optional single SI prefix ("10k", "1.5M"). Anything else — "1TX", "50%",
#: "See Note 2" — is not a tick and is never coerced into one.
_TICK_RE = re.compile(
    r"^([+\-−–‐])?(\d{1,3}(?:,\d{3})+|\d*\.?\d+)"
    r"(?:[eE]([+\-]?\d+))?\s*([kKMGTmµμnpu])?$"
)

#: SI prefixes admitted on a tick label. Single character only, so a stray
#: word can never be read as a scale factor.
_SI_PREFIX: dict[str, float] = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "μ": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
}

#: Glyph repairs for axis titles, as a checked-in lexicon (invariant 8 (c)).
#: TI draws the degree sign from the Symbol font, which extracts as a bare
#: "q" — "Temperature (Cq)" is a printed "Temperature (°C)". Only exact,
#: observed substitutions live here; nothing is guessed.
_GLYPH_FIXES: tuple[tuple[str, str], ...] = (
    ("Cq", "°C"),
    ("°C", "°C"),
    ("q C", "°C"),
)

#: Units that name a *ratio* and so carry no SI prefix, however much they look
#: like one: the "m" of "mm" scales, the "m" of "dBm" does not.
_ATOMIC_UNITS = frozenset({"dbm", "dbc", "dbfs", "dbi", "db", "mhz/v", "ppm"})


@dataclass(frozen=True)
class Axis:
    """One axis as printed: its title, its unit, its endpoints, its scale.

    Every field is independently optional. A title that reads while the ticks
    do not gives `label` with `min`/`max` `None` — the honest half-answer,
    which still lets `find_plots --y-label Gain` do its job.
    """

    label: str = ""
    unit: str = ""
    min: float | None = None
    max: float | None = None
    #: "linear", "log", or "" when no tick sequence validated.
    scale: str = ""

    @property
    def has_range(self) -> bool:
        return self.min is not None and self.max is not None


@dataclass(frozen=True)
class FigureAxes:
    """The axes of one plot frame found on one page, with what names it."""

    page: int
    figure_number: str
    caption_key: str
    x: Axis
    y: Axis

    @property
    def confidence(self) -> Confidence:
        return grade_axes(self.x, self.y)


@dataclass
class AxisCoverage:
    """What the axis pass actually managed, per document — for the report.

    Counts, not a verdict: the phase gate reads `high_fraction` and the phase
    report prints the whole table, including the population that stayed null.
    """

    total: int = 0
    by_confidence: dict[str, int] = field(default_factory=dict)
    log_axes: int = 0
    with_x_range: int = 0
    with_y_range: int = 0
    with_x_label: int = 0
    with_y_label: int = 0

    @property
    def high(self) -> int:
        return self.by_confidence.get(Confidence.HIGH.value, 0)

    @property
    def high_fraction(self) -> float:
        return self.high / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "by_confidence": dict(self.by_confidence),
            "high_fraction": round(self.high_fraction, 4),
            "log_axes": self.log_axes,
            "with_x_range": self.with_x_range,
            "with_y_range": self.with_y_range,
            "with_x_label": self.with_x_label,
            "with_y_label": self.with_y_label,
        }


# --- pure text/number helpers ----------------------------------------------


def parse_tick(text: str) -> float | None:
    """A printed tick label as a number, or `None` when it is not one.

    Documented pure function (invariant 8 (b)): sign — including the unicode
    minus TI prints — digits, optional exponent, optional single SI prefix.
    `None` is a first-class outcome; a label this cannot read is never
    guessed at.
    """
    stripped = text.strip()
    if not stripped:
        return None
    m = _TICK_RE.match(stripped)
    if m is None:
        return None
    sign, digits, exponent, prefix = m.groups()
    try:
        value = float(digits.replace(",", ""))
    except ValueError:  # pragma: no cover - regex admits only floats
        return None
    if exponent:
        value *= 10.0 ** int(exponent)
    if prefix:
        value *= _SI_PREFIX[prefix]
    if sign and sign != "+":
        value = -value
    return value


def split_title(text: str) -> tuple[str, str]:
    """`"Output Frequency (MHz)"` -> `("Output Frequency", "MHz")`.

    The unit is only ever taken from a trailing parenthesised or bracketed
    group — the one place a datasheet axis title reliably puts it. A title
    without one yields an empty unit rather than a unit guessed out of the
    words.
    """
    cleaned = " ".join(text.split())
    for bad, good in _GLYPH_FIXES:
        cleaned = cleaned.replace(bad, good)
    m = re.search(r"[(\[]\s*([^()\[\]]{1,24})\s*[)\]]\s*$", cleaned)
    if m is None:
        return cleaned.strip(" .,:"), ""
    label = cleaned[: m.start()].strip(" .,:")
    unit = m.group(1).strip()
    return label, unit


def unit_scale(unit: str) -> tuple[str, float]:
    """Split a unit into its base and its SI multiplier: `"GHz" -> ("hz", 1e9)`.

    Used only to compare a query ("3.5GHz") against a printed axis range
    ("600 ... 1500 MHz"). Ratio units are atomic — "dBm" is not milli-dB — so
    they are listed rather than parsed, and an unrecognised unit keeps a
    multiplier of 1.0 and its own name, which makes it comparable with itself
    and with nothing else.
    """
    text = unit.strip()
    if not text:
        return "", 1.0
    if text.lower() in _ATOMIC_UNITS:
        return text.lower(), 1.0
    head, rest = text[0], text[1:]
    if rest and head in _SI_PREFIX and rest.lower() not in _ATOMIC_UNITS:
        return rest.lower(), _SI_PREFIX[head]
    return text.lower(), 1.0


def parse_axis_point(text: str) -> tuple[float, str] | None:
    """`"3.5GHz"` -> `(3.5e9, "hz")`; `None` when it is not a quantity.

    The query-side twin of `parse_tick`: a `--near-x` argument is a number
    with an optional unit, and comparing it to an axis means putting both on
    the same base unit. A bare number returns an empty base unit and compares
    only against an axis that prints no unit either.
    """
    stripped = " ".join(str(text).split())
    m = re.match(r"^([+\-−–]?\s*\d*\.?\d+(?:[eE][+\-]?\d+)?)\s*([^\s]*)$", stripped)
    if m is None:
        return None
    number, unit = m.group(1), m.group(2)
    value = parse_tick(number.replace(" ", ""))
    if value is None:
        return None
    if not unit:
        return value, ""
    base, mult = unit_scale(unit)
    return value * mult, base


def axis_contains(axis: Axis, query: str) -> bool:
    """True when `query` falls inside this axis's printed range.

    False — never a maybe — when the axis has no range, when the query does
    not parse, or when the two units are not comparable. `find_plots
    --near-x` is a *narrowing* filter: a figure it cannot rule in is ruled
    out, and the caller still has the unfiltered catalog.
    """
    if not axis.has_range:
        return False
    point = parse_axis_point(query)
    if point is None:
        return False
    value, base = point
    axis_base, axis_mult = unit_scale(axis.unit)
    if base and axis_base and base != axis_base:
        return False
    if base and not axis_base:
        return False
    lo = min(axis.min, axis.max) * (axis_mult if base else 1.0)  # type: ignore[operator]
    hi = max(axis.min, axis.max) * (axis_mult if base else 1.0)  # type: ignore[operator]
    return lo <= value <= hi


def grade_axes(x: Axis, y: Axis) -> Confidence:
    """The record's `axis_confidence` from what the two axes actually hold.

    Log is graded `low` on purpose (see the module docstring): the endpoints
    are printed and are kept, the *mapping* is not linear, and nothing
    downstream may assume otherwise.
    """
    if "log" in (x.scale, y.scale):
        return Confidence.LOW
    read = [bool(x.label), bool(y.label), x.has_range, y.has_range]
    if all(read):
        return Confidence.HIGH
    if any(read):
        return Confidence.MEDIUM
    return Confidence.LOW


# --- page geometry ---------------------------------------------------------


@dataclass(frozen=True)
class _Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    rotated: bool

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0


@dataclass(frozen=True)
class _Ticks:
    """A validated tick sequence: its labels' geometry and its fit."""

    lines: tuple[_Line, ...]
    values: tuple[float, ...]
    scale: str

    @property
    def lo(self) -> float:
        return min(self.values)

    @property
    def hi(self) -> float:
        return max(self.values)


def _tick_words(text: str) -> list[str] | None:
    """The whitespace-separated tokens of `text` when *every* one is a tick.

    A PDF is free to draw a whole tick row as one text line —
    `"1200 1350 1500 1650 1800"` — and several of the AFE7950's plots do.
    Such a line is exploded into one pseudo-line per label so the alignment
    machinery sees the same thing either way. The all-numeric condition is
    what keeps a legend ("1TX, -12dBFS") or a title out of it, and `None`
    means "leave this line alone".
    """
    tokens = text.split()
    if len(tokens) < 2:
        return None
    if any(parse_tick(token) is None for token in tokens):
        return None
    return tokens


def _explode(
    chars: list[tuple[tuple[float, float, float, float], str]],
    size: float,
    rotated: bool,
) -> list[_Line]:
    """One drawn line, cut into its whitespace-separated words.

    The bounding box of each word is the union of its own glyph boxes, so an
    exploded tick sits exactly where it is printed — this is geometry read
    off the page, never a width estimated from the character count.
    """
    out: list[_Line] = []
    current: list[tuple[tuple[float, float, float, float], str]] = []

    def flush() -> None:
        if not current:
            return
        x0 = min(c[0][0] for c in current)
        y0 = min(c[0][1] for c in current)
        x1 = max(c[0][2] for c in current)
        y1 = max(c[0][3] for c in current)
        out.append(
            _Line(
                text="".join(c[1] for c in current),
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                size=size,
                rotated=rotated,
            )
        )
        current.clear()

    for bbox, char in chars:
        if char.isspace():
            flush()
        else:
            current.append((bbox, char))
    flush()
    return out


def _page_lines(page: fitz.Page) -> list[_Line]:
    """Every drawn text line on a page, with all-numeric lines exploded.

    Read through `rawdict` rather than `dict` because the explosion needs
    per-glyph boxes; the extra cost is a few milliseconds a page and it buys
    the whole class of plots that print their tick row as one line.
    """
    out: list[_Line] = []
    data = page.get_text("rawdict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            chars: list[tuple[tuple[float, float, float, float], str]] = []
            for span in spans:
                for char in span.get("chars", []):
                    chars.append((char["bbox"], char["c"]))
            text = "".join(c[1] for c in chars)
            if not text.strip():
                continue
            x0, y0, x1, y1 = line["bbox"]
            direction = line.get("dir", (1.0, 0.0))
            size = max((s.get("size", 0.0) for s in spans), default=0.0)
            rotated = abs(direction[1]) > 0.5
            if _tick_words(text) is not None:
                out.extend(_explode(chars, size, rotated))
                continue
            out.append(_Line(text=text, x0=x0, y0=y0, x1=x1, y1=y1, size=size, rotated=rotated))
    return out


def _cluster(items: list[_Line], key, tol: float) -> list[list[_Line]]:
    """Group lines whose `key` is within `tol` of the group's first member.

    Measured from the *seed*, not from the previous member, and that is the
    whole point: chaining would walk a 2.5 pt tolerance across a 4 pt spread
    and pull one plot's x tick into its neighbour's y tick column, where it
    sits 6 pt from the column's last label and so survives the gap split that
    would otherwise drop it. Aligned means aligned with one edge, not
    reachable from it.
    """
    groups: list[list[_Line]] = []
    for line in sorted(items, key=key):
        if groups and abs(key(line) - key(groups[-1][0])) <= tol:
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def _split_runs(group: list[_Line], key) -> list[list[_Line]]:
    """Split one alignment group where its spacing jumps.

    Two plots side by side print their x ticks on one baseline; inside a plot
    the tick pitch is constant, and the step to the neighbouring plot is
    several times it. Splitting on that ratio is what keeps one frame's ticks
    from being read as a continuation of another's.
    """
    ordered = sorted(group, key=key)
    if len(ordered) < 2:
        return [ordered]
    gaps = [key(b) - key(a) for a, b in itertools.pairwise(ordered)]
    positive = [g for g in gaps if g > 0]
    if not positive:
        return [ordered]
    pitch = min(positive)
    runs: list[list[_Line]] = [[ordered[0]]]
    for gap, line in zip(gaps, ordered[1:]):
        if pitch > 0 and gap > _GAP_SPLIT * pitch:
            runs.append([line])
        else:
            runs[-1].append(line)
    return runs


def _fit_residual(positions: list[float], values: list[float]) -> float:
    """Max residual of a least-squares line through (position, value), scaled.

    Returned relative to the value span so the tolerance is unit-free. `inf`
    when the fit is meaningless (no spread in position or in value).
    """
    n = len(positions)
    span = max(values) - min(values)
    p_span = max(positions) - min(positions)
    if n < 2 or span <= 0 or p_span <= 0:
        return math.inf
    mean_p = sum(positions) / n
    mean_v = sum(values) / n
    sxx = sum((p - mean_p) ** 2 for p in positions)
    if sxx <= 0:
        return math.inf
    slope = sum((p - mean_p) * (v - mean_v) for p, v in zip(positions, values)) / sxx
    intercept = mean_v - slope * mean_p
    worst = max(abs(v - (slope * p + intercept)) for p, v in zip(positions, values))
    return worst / span


def _validate(lines: list[_Line], key) -> _Ticks | None:
    """A run of aligned numbers, if it behaves like a tick sequence.

    Three conditions, all of them geometric: enough labels, even spacing in
    position, and values affine in position (or in log-position, which is a
    decade axis). Failing any of them returns `None` — the axis stays null.
    """
    if len(lines) < _MIN_TICKS:
        return None
    values: list[float] = []
    for line in lines:
        value = parse_tick(line.text)
        if value is None:
            return None
        values.append(value)
    positions = [key(line) for line in lines]
    gaps = [b - a for a, b in itertools.pairwise(positions)]
    if not gaps or min(gaps) <= 0:
        return None
    mean_gap = sum(gaps) / len(gaps)
    if any(abs(g - mean_gap) > _EVEN_TOL * mean_gap for g in gaps):
        return None
    if len(set(values)) < 2:
        return None
    if _fit_residual(positions, values) <= _FIT_TOL:
        return _Ticks(tuple(lines), tuple(values), "linear")
    if all(v > 0 for v in values):
        logs = [math.log10(v) for v in values]
        if _fit_residual(positions, logs) <= _FIT_TOL:
            return _Ticks(tuple(lines), tuple(values), "log")
    return None


@dataclass(frozen=True)
class _Frame:
    """One plot's axis frame: the x tick row and the y tick column that
    bracket it, plus the box they enclose."""

    x_ticks: _Ticks
    y_ticks: _Ticks

    @property
    def left(self) -> float:
        return min(line.x0 for line in self.x_ticks.lines)

    @property
    def right(self) -> float:
        return max(line.x1 for line in self.x_ticks.lines)

    @property
    def bottom(self) -> float:
        return max(line.y1 for line in self.x_ticks.lines)

    @property
    def top(self) -> float:
        return min(line.y0 for line in self.y_ticks.lines)

    @property
    def tick_size(self) -> float:
        sizes = sorted(line.size for line in self.x_ticks.lines)
        return sizes[len(sizes) // 2]


def _tick_rows(lines: list[_Line]) -> list[_Ticks]:
    numeric = [ln for ln in lines if not ln.rotated and parse_tick(ln.text) is not None]
    rows: list[_Ticks] = []
    for group in _cluster(numeric, lambda ln: ln.y0, _ALIGN_TOL):
        for run in _split_runs(group, lambda ln: ln.cx):
            ticks = _validate(run, lambda ln: ln.cx)
            if ticks is not None:
                rows.append(ticks)
    return rows


def _tick_cols(lines: list[_Line]) -> list[_Ticks]:
    numeric = [ln for ln in lines if not ln.rotated and parse_tick(ln.text) is not None]
    cols: list[_Ticks] = []
    for group in _cluster(numeric, lambda ln: ln.x1, _ALIGN_TOL):
        for run in _split_runs(group, lambda ln: -ln.cy):
            ticks = _validate(run, lambda ln: -ln.cy)
            if ticks is not None:
                cols.append(ticks)
    return cols


def _pair_frames(rows: list[_Ticks], cols: list[_Ticks]) -> list[_Frame]:
    """Match each x tick row with the y tick column that brackets it.

    The y labels sit just left of where the x labels start and just above the
    baseline they sit on; that is the whole rule, and a row with no such
    column is not a plot frame.
    """
    frames: list[_Frame] = []
    used: set[int] = set()
    for row in sorted(rows, key=lambda t: min(ln.x0 for ln in t.lines)):
        row_left = min(ln.x0 for ln in row.lines)
        row_top = min(ln.y0 for ln in row.lines)
        best: tuple[float, float, int] | None = None
        for idx, col in enumerate(cols):
            if idx in used:
                continue
            col_right = max(ln.x1 for ln in col.lines)
            col_bottom = max(ln.y1 for ln in col.lines)
            if not (row_left - _Y_TITLE_GAP <= col_right <= row_left + 10.0):
                continue
            # the lowest y label sits at the origin, level with the row it
            # belongs to; a column that far above belongs to the plot above
            offset = abs(row_top - col_bottom)
            if col_bottom > row_top + 8.0 or offset > _ORIGIN_TOL:
                continue
            score = (offset, -col_right, idx)
            if best is None or score < best:
                best = score
        if best is not None:
            used.add(best[2])
            frames.append(_Frame(x_ticks=row, y_ticks=cols[best[2]]))
    return frames


def _x_title(frame: _Frame, lines: list[_Line]) -> str:
    best: tuple[float, str] | None = None
    for line in lines:
        if line.rotated or parse_tick(line.text) is not None:
            continue
        if abs(line.size - frame.tick_size) > _TITLE_SIZE_TOL:
            continue
        if not (frame.bottom - 2.0 <= line.y0 <= frame.bottom + _X_TITLE_GAP):
            continue
        if not (frame.left - 40.0 <= line.cx <= frame.right + 40.0):
            continue
        if best is None or line.y0 < best[0]:
            best = (line.y0, line.text)
    return best[1] if best else ""


def _y_title(frame: _Frame, lines: list[_Line]) -> str:
    col_right = max(ln.x1 for ln in frame.y_ticks.lines)
    best: tuple[float, str] | None = None
    for line in lines:
        if not line.rotated:
            continue
        if abs(line.size - frame.tick_size) > _TITLE_SIZE_TOL:
            continue
        if not (col_right - _Y_TITLE_GAP <= line.x1 <= col_right + 3.0):
            continue
        overlap = min(line.y1, frame.bottom) - max(line.y0, frame.top)
        if overlap <= 0.25 * (line.y1 - line.y0):
            continue
        if best is None or line.x1 > best[0]:
            best = (line.x1, line.text)
    return best[1] if best else ""


def _captions(lines: list[_Line]) -> list[tuple[str, _Line]]:
    out: list[tuple[str, _Line]] = []
    for line in lines:
        if line.rotated:
            continue
        m = _CAPTION_RE.match(line.text.strip())
        if m is not None:
            out.append((m.group(1).lower(), line))
    return out


def _axes_for_frame(frame: _Frame, lines: list[_Line]) -> tuple[Axis, Axis]:
    x_label, x_unit = split_title(_x_title(frame, lines))
    y_label, y_unit = split_title(_y_title(frame, lines))
    return (
        Axis(
            label=x_label,
            unit=x_unit,
            min=frame.x_ticks.lo,
            max=frame.x_ticks.hi,
            scale=frame.x_ticks.scale,
        ),
        Axis(
            label=y_label,
            unit=y_unit,
            min=frame.y_ticks.lo,
            max=frame.y_ticks.hi,
            scale=frame.y_ticks.scale,
        ),
    )


def page_axes(page: fitz.Page) -> list[FigureAxes]:
    """Every plot frame printed on one page, tied to the caption below it.

    A frame and a caption go together when the caption sits below it, close
    to it, and *overlaps it horizontally*; among the pairs that qualify, the
    nearest are assigned first and each frame and caption is used once. A
    frame left without a caption is dropped rather than reported against a
    guess — without a caption there is no `PlotRecord` it could belong to,
    and a wrong figure number is worse than a missing one.
    """
    lines = _page_lines(page)
    frames = _pair_frames(_tick_rows(lines), _tick_cols(lines))
    captions = _captions(lines)

    # Every frame/caption pair that is geometrically possible — the caption
    # sits below the frame, near it, and shares horizontal extent with it —
    # scored and then assigned greedily nearest-first. Assigning per frame in
    # page order instead would let one column's frame claim the *other*
    # column's caption when that caption happens to sit two points higher,
    # which is how a plot ends up cataloged under its neighbour's number.
    pairs: list[tuple[float, float, int, int]] = []
    for fi, frame in enumerate(frames):
        for ci, (_number, line) in enumerate(captions):
            gap = line.y0 - frame.bottom
            if gap <= 0 or gap > _CAPTION_GAP:
                continue
            overlap = min(line.x1, frame.right) - max(line.x0, frame.left)
            if overlap <= 0:
                continue
            pairs.append((gap, -overlap, fi, ci))
    pairs.sort()

    out: list[FigureAxes] = []
    used_frames: set[int] = set()
    used_captions: set[int] = set()
    for _gap, _overlap, fi, ci in pairs:
        if fi in used_frames or ci in used_captions:
            continue
        used_frames.add(fi)
        used_captions.add(ci)
        number, line = captions[ci]
        x_axis, y_axis = _axes_for_frame(frames[fi], lines)
        out.append(
            FigureAxes(
                page=page.number + 1,
                figure_number=number,
                caption_key=_caption_key(line.text),
                x=x_axis,
                y=y_axis,
            )
        )
    out.sort(key=lambda entry: entry.figure_number)
    return out


def _caption_key(text: str) -> str:
    """Squash a caption to letters and digits, so wrapping and punctuation
    cannot make the same printed caption two different strings."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def read_axis_catalog(pdf_path: Path | str) -> list[FigureAxes]:
    """Every readable plot frame in a PDF, in page order.

    Deterministic and offline: the same bytes give the same catalog on any
    machine. Opens the PDF once; a page that cannot be read is logged and
    skipped rather than aborting the document.
    """
    out: list[FigureAxes] = []
    with fitz.open(str(pdf_path)) as pdf:
        for page in pdf:
            try:
                out.extend(page_axes(page))
            except Exception as exc:  # noqa: BLE001 - honesty over crash
                log.warning("axis scan failed on page %d: %s", page.number + 1, exc)
    return out


def _match(record: PlotRecord, catalog: list[FigureAxes]) -> FigureAxes | None:
    """The catalog entry a `PlotRecord` names, by printed figure number.

    The number is what survives the two ways a caption differs between the
    PDF and the HTML catalog it may have been built from: the PDF wraps long
    captions across lines, and prints "Figure 4-1." where the catalog holds
    "Figure 4-1". Falling back to the squashed caption covers figures that
    print no number at all.
    """
    number = record.figure_number.strip().lower()
    key = _caption_key(record.caption)
    in_range = [
        entry
        for entry in catalog
        if (record.page_start is None or entry.page >= record.page_start)
        and (record.page_end is None or entry.page <= record.page_end)
    ]
    for pool in (in_range, catalog):
        if number:
            hits = [e for e in pool if e.figure_number == number]
            if len(hits) == 1:
                return hits[0]
        if key:
            hits = [e for e in pool if e.caption_key and e.caption_key.startswith(key[:40])]
            if len(hits) == 1:
                return hits[0]
    return None


def annotate_plot_axes(plotset: PlotSet, pdf_path: Path | str) -> AxisCoverage:
    """Fill every `PlotRecord`'s axis fields from `pdf_path`, in place.

    Additive by construction: nothing already on the record is touched, and a
    record with no readable frame keeps its caption, conditions, tags and
    pixels and is graded `low` — attempted, nothing found. Returns the
    coverage counts the phase report prints.
    """
    catalog = read_axis_catalog(pdf_path)
    coverage = AxisCoverage()
    for record in plotset.plots:
        entry = _match(record, catalog)
        x = entry.x if entry else Axis()
        y = entry.y if entry else Axis()
        record.x_label, record.x_unit = x.label, x.unit
        record.x_min, record.x_max = x.min, x.max
        record.y_label, record.y_unit = y.label, y.unit
        record.y_min, record.y_max = y.min, y.max
        record.axis_confidence = grade_axes(x, y)
        coverage.total += 1
        grade = record.axis_confidence.value
        coverage.by_confidence[grade] = coverage.by_confidence.get(grade, 0) + 1
        coverage.log_axes += 1 if "log" in (x.scale, y.scale) else 0
        coverage.with_x_range += 1 if x.has_range else 0
        coverage.with_y_range += 1 if y.has_range else 0
        coverage.with_x_label += 1 if x.label else 0
        coverage.with_y_label += 1 if y.label else 0
    return coverage
