"""The numeric layer — printed value text to a comparable SI number.

The enabling primitive for design cards, cross-part comparison and margin
checks (phase 6, ticket 02). Pure: no I/O, no network, no model call, so it is
a legal step in an invariant-8 derivation path (`parse_quantity+si_normalize`
is the rule name a `DerivedValue` records).

Three rules govern everything here.

**Verbatim stays authoritative.** This layer is strictly additive. It never
mutates a record's printed strings, and where the printed string and the parsed
number disagree the printed string is correct by definition — the number is a
convenience for sorting, the string is the datasheet.

**Returning `None` is a first-class outcome.** `See Figure 7`, `Note 2`, `—`
and an empty cell have no number in them, and the layer says so
(`ParseConfidence.NONE`) rather than reaching for a plausible one. The grammar
is therefore **anchored**: a cell parses only when the whole of it is a
quantity. `Note 2` contains a digit and still parses to nothing, which is the
point. The one thing removed before matching is a trailing footnote marker
(`1350(2)`), because a marker is provenance the record already carries in
`cited_markers` — it is not part of the value.

**A unit we cannot scale is a unit we cannot state.** An unrecognised unit
yields `None` rather than an unscaled number: silently dropping a factor of
1000 is exactly the confident-and-wrong failure ADR 0005 exists to prevent.
`SI_UNITS` therefore covers every entry of `units.CANONICAL_UNITS` and a test
fails the moment a canonical unit is added without a scale.

Two shapes of API sit on top of the grammar:

- `record_quantities` parses each value-bearing cell of a `SpecRecord`
  independently, and is what a consumer comparing a *specific* limit must use;
  `record_quantity` picks the record's representative one by the documented
  selector below; `annotate_records` writes that representative into the
  record's additive fields at structure time.
- `parse_population` is the honest-arithmetic helper: any consumer that sorts,
  compares or computes margins must report the rows it could not parse
  (invariant 8), and this is the shape that report takes. `parse_rate` is its
  measurement twin, broken down by section, for the phase report.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from datasheet_analyzer.models import ParseConfidence, SpecRecord, ValueKind
from datasheet_analyzer.structure.units import canonical_unit, normalize_text

#: Every canonical unit of `units.CANONICAL_UNITS`, mapped to the base unit the
#: numeric layer expresses values in and the factor that gets there. The base
#: is SI where SI has one; `SPS`, `bps`, `UI`, `bits` and the dB family are kept
#: as their own base because they have no SI equivalent, and **°C is not
#: converted to kelvin** — a datasheet's thermal margins are read in the units
#: it printed, and 233.15 K helps nobody design with a −40 °C part.
SI_UNITS: dict[str, tuple[str, float]] = {
    # dimensionless: an empty unit is a legitimate unit, not a missing one
    "": ("", 1.0),
    # resistance (both ohm glyphs canonicalize to "ohm" in units.py; a
    # prefixed ohm has no lexicon entry yet, so it stays honestly unparsed)
    "ohm": ("ohm", 1.0),
    # logarithmic / angle / ratio — already relative, so there is nothing to
    # scale; each is its own base and a dB is never folded into another dB
    "dB": ("dB", 1.0),
    "dBm": ("dBm", 1.0),
    "dBc": ("dBc", 1.0),
    "dBc/Hz": ("dBc/Hz", 1.0),
    "dBFS": ("dBFS", 1.0),
    "dBFS/Hz": ("dBFS/Hz", 1.0),
    "deg": ("deg", 1.0),
    "%": ("%", 1.0),
    # voltage
    "V": ("V", 1.0),
    "kV": ("V", 1e3),
    "mV": ("V", 1e-3),
    "µV": ("V", 1e-6),
    "mVpp": ("Vpp", 1e-3),
    "Vppdiff": ("Vppdiff", 1.0),
    # current
    "A": ("A", 1.0),
    "mA": ("A", 1e-3),
    "µA": ("A", 1e-6),
    "nA": ("A", 1e-9),
    "pA": ("A", 1e-12),
    # temperature (see the note above: °C stays °C)
    "°C": ("°C", 1.0),
    "°C/W": ("°C/W", 1.0),
    # frequency / sample rate / data rate
    "Hz": ("Hz", 1.0),
    "kHz": ("Hz", 1e3),
    "MHz": ("Hz", 1e6),
    "GHz": ("Hz", 1e9),
    "SPS": ("SPS", 1.0),
    "MSPS": ("SPS", 1e6),
    "GSPS": ("SPS", 1e9),
    "bps": ("bps", 1.0),
    "Mbps": ("bps", 1e6),
    "Gbps": ("bps", 1e9),
    # time
    "s": ("s", 1.0),
    "ms": ("s", 1e-3),
    "µs": ("s", 1e-6),
    "ns": ("s", 1e-9),
    "ps": ("s", 1e-12),
    "UI": ("UI", 1.0),
    # misc
    "F": ("F", 1.0),
    "µF": ("F", 1e-6),
    "nF": ("F", 1e-9),
    "pF": ("F", 1e-12),
    "W": ("W", 1.0),
    "mW": ("W", 1e-3),
    "µW": ("W", 1e-6),
    "bits": ("bits", 1.0),
}

#: The value-bearing cells of a spec record, in the order the selector below
#: consults them. Mirrors `confidence.VALUE_ROLES`, which is printed order.
VALUE_ROLES: tuple[str, ...] = ("min", "typ", "max", "value")

#: The representative-quantity selector (see `record_quantity`).
SELECTOR_ORDER: tuple[str, ...] = ("value", "typ", "max", "min")

#: The rule name a `DerivedValue` produced from this layer records.
DERIVATION = "parse_quantity+si_normalize"

# A number, as datasheets print them: optional sign (the unicode minus is
# already folded to "-" by `units.normalize_text`), decimal point either side,
# optional exponent.
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"

# A trailing unit token. Units carry no internal whitespace ("°C/W", "dBc/Hz",
# "GSPS"), so one non-space run is the whole of it — and anything that is not a
# unit we can scale makes the whole cell unparseable, by design.
_UNIT = r"(?P<unit>\S+)?"

# A range separator. `units.normalize_text` has already folded en/em/minus
# dashes to "-", so a hyphen range is only recognised **whitespace-delimited**:
# "-40 - +85" is a range, "-40-85" is ambiguous with a negative number and is
# left unparsed rather than guessed at.
_RANGE_SEP = r"(?:\s*(?:to|\.\.\.|\.\.|…)\s*|\s-\s)"

_TOLERANCE_RE = re.compile(rf"^(?:±|\+/-)\s*(?P<mag>{_NUMBER})\s*{_UNIT}$", re.IGNORECASE)
_BOUND_RE = re.compile(rf"^(?P<op><=|>=|<|>|≤|≥)\s*(?P<v>{_NUMBER})\s*{_UNIT}$")
_RANGE_RE = re.compile(
    rf"^(?P<lo>{_NUMBER}){_RANGE_SEP}(?P<hi>{_NUMBER})\s*{_UNIT}$", re.IGNORECASE
)
_POINT_RE = re.compile(rf"^(?P<v>{_NUMBER})\s*{_UNIT}$")

# Trailing footnote markers: "1350(2)", "1.8 V(2)(3)". The marker is provenance
# (`SpecRecord.cited_markers` already carries it), never part of the value.
_TRAILING_MARKERS_RE = re.compile(r"(?:\s*\(\d+\))+$")

# The micro sign the unit lexicon is keyed on (U+00B5) and the Greek mu some
# PDFs emit for it (U+03BC) are the same unit; fold before canonicalizing so
# "10 μA" is not thrown away over a glyph. The ohm pair needs no fold — both
# glyphs are keys of `CANONICAL_UNITS` already.
_MICRO_FOLD = {"μ": "µ"}

#: Bounds that state an upper limit; the rest state a lower one.
_UPPER_OPS = frozenset({"<", "<=", "≤"})


@dataclass(frozen=True)
class Quantity:
    """One printed value, parsed — the full-fidelity form.

    `SpecRecord`'s flat `value_si` / `value_low_si` / `value_high_si` fields are
    this object flattened for publication; a consumer that needs the operator of
    a bound, or the exact text it read, asks for the `Quantity`.

    - `value_si` — the number for a `POINT`, the magnitude for a `TOLERANCE`,
      and `None` for a `RANGE` or a `BOUND`, which state an interval instead.
    - `low_si` / `high_si` — the interval a `RANGE` states, or the one side a
      `BOUND` states (the other stays `None`). A `TOLERANCE` states neither:
      ±0.5 is a spread around a nominal this cell does not print, and inventing
      the nominal is exactly the interpolation invariant 8 forbids.
    - `operator` — the bound's printed relation, normalized to `<`, `<=`, `>`
      or `>=`; empty for every other kind.
    """

    verbatim: str
    kind: ValueKind
    unit_si: str
    value_si: float | None = None
    low_si: float | None = None
    high_si: float | None = None
    operator: str = ""
    confidence: ParseConfidence = ParseConfidence.EXACT

    @property
    def span(self) -> tuple[float | None, float | None]:
        """The closed interval this quantity constrains, as far as it states one.

        A point constrains a single number, a range and a bound their endpoints,
        and a tolerance nothing at all without a nominal. Consumers that sort or
        compute margins want this; they must still report what did not parse
        (`parse_population`).
        """
        if self.kind is ValueKind.POINT:
            return (self.value_si, self.value_si)
        if self.kind is ValueKind.TOLERANCE:
            return (None, None)
        return (self.low_si, self.high_si)


def parse_quantity(text: str, unit_hint: str = "") -> Quantity | None:
    """Parse one printed value cell; `None` when it holds no quantity.

    `unit_hint` is the row's unit column — used only when the cell itself does
    not print a unit, because what the cell prints is what the cell means.

    `None` is returned, deliberately and without complaint, for prose (`See
    Figure 7`), a footnote pointer (`Note 2`), a printed dash (`—`), an empty
    cell, a number whose unit cannot be scaled, and anything else the anchored
    grammar does not consume whole.
    """
    cleaned = _TRAILING_MARKERS_RE.sub("", normalize_text(text or "")).strip()
    if not cleaned:
        return None

    verbatim = (text or "").strip()

    match = _TOLERANCE_RE.match(cleaned)
    if match:
        si = _si(match.group("unit"), unit_hint)
        if si is None:
            return None
        unit_si, factor = si
        return Quantity(
            verbatim=verbatim,
            kind=ValueKind.TOLERANCE,
            unit_si=unit_si,
            value_si=abs(float(match.group("mag"))) * factor,
        )

    match = _BOUND_RE.match(cleaned)
    if match:
        si = _si(match.group("unit"), unit_hint)
        if si is None:
            return None
        unit_si, factor = si
        operator = {"≤": "<=", "≥": ">="}.get(match.group("op"), match.group("op"))
        value = float(match.group("v")) * factor
        upper = operator in _UPPER_OPS
        return Quantity(
            verbatim=verbatim,
            kind=ValueKind.BOUND,
            unit_si=unit_si,
            low_si=None if upper else value,
            high_si=value if upper else None,
            operator=operator,
        )

    match = _RANGE_RE.match(cleaned)
    if match:
        si = _si(match.group("unit"), unit_hint)
        if si is None:
            return None
        unit_si, factor = si
        return Quantity(
            verbatim=verbatim,
            kind=ValueKind.RANGE,
            unit_si=unit_si,
            low_si=float(match.group("lo")) * factor,
            high_si=float(match.group("hi")) * factor,
        )

    match = _POINT_RE.match(cleaned)
    if match:
        si = _si(match.group("unit"), unit_hint)
        if si is None:
            return None
        unit_si, factor = si
        return Quantity(
            verbatim=verbatim,
            kind=ValueKind.POINT,
            unit_si=unit_si,
            value_si=float(match.group("v")) * factor,
        )

    return None


def _si(cell_unit: str | None, unit_hint: str) -> tuple[str, float] | None:
    """(base unit, factor) for the cell's unit, or `None` when unscalable.

    The cell's own unit wins over the row's unit column; an unrecognised unit
    is refused rather than passed through unscaled. A footnote marker on the
    unit column (`Vppdiff(3)`) is stripped by the same rule that strips it from
    a value cell — it is provenance either way, never part of the unit.
    """
    raw = (cell_unit or "").strip() or _TRAILING_MARKERS_RE.sub("", unit_hint or "").strip()
    for greek, micro in _MICRO_FOLD.items():
        raw = raw.replace(greek, micro)
    canonical = canonical_unit(raw).canonical
    return SI_UNITS.get(canonical)


def record_quantities(record: SpecRecord) -> dict[str, Quantity | None]:
    """Every value-bearing cell of a record, parsed independently.

    This is what a consumer comparing one *specific* limit must use — an
    abs-max-versus-recommended margin is a statement about the `max` columns,
    and reading the record's representative quantity instead would silently
    compare a typical against a maximum.
    """
    hint = record.unit.verbatim or record.unit.canonical
    return {role: parse_quantity(getattr(record, role), hint) for role in VALUE_ROLES}


def record_quantity(record: SpecRecord) -> Quantity | None:
    """The record's representative quantity, or `None` when nothing parsed.

    The selector is `value` → `typ` → `max` → `min`, first cell that parses:

    - `value` — a single-value table (ESD, thermal) prints exactly one number
      per row, so there is nothing to choose between;
    - `typ` — where a row prints a typical, that is the number a designer
      quotes back;
    - `max`, then `min` — otherwise the row states limits, and the maximum is
      the one a design is usually bounded by.

    Nothing is combined across cells: a `min` of −40 and a `max` of +85 stay two
    quantities, because joining them into "−40 to +85" would put a verbatim
    string on a record that the datasheet never printed. A consumer that wants
    that interval takes both from `record_quantities`.
    """
    cells = record_quantities(record)
    for role in SELECTOR_ORDER:
        quantity = cells.get(role)
        if quantity is not None:
            return quantity
    return None


def annotate_record(record: SpecRecord) -> SpecRecord:
    """Write the record's representative quantity into its additive fields.

    Mutates **only** the numeric fields; every verbatim string is left exactly
    as extracted. Idempotent and pure over the record's own cells, so running it
    twice — or on a corpus that already carries the layer — changes nothing.
    """
    quantity = record_quantity(record)
    record.value_si = quantity.value_si if quantity else None
    record.value_low_si = quantity.low_si if quantity else None
    record.value_high_si = quantity.high_si if quantity else None
    record.unit_si = quantity.unit_si if quantity else ""
    record.value_kind = quantity.kind if quantity else None
    record.parse_confidence = quantity.confidence if quantity else ParseConfidence.NONE
    return record


def annotate_records(records: Iterable[SpecRecord]) -> list[SpecRecord]:
    """`annotate_record` over a document's record list."""
    return [annotate_record(record) for record in records]


@dataclass(frozen=True)
class ParsePopulation:
    """What a comparison could and could not read — invariant 8's honesty half.

    Any consumer that sorts, compares or computes margins must report the rows
    it could not parse instead of dropping them from the decision, and this is
    the shape that report takes: `parsed` is what may be arithmetic'd on,
    `unparsed` is what must still be shown to the reader, and `describe()` is
    the one line that says so.
    """

    role: str
    parsed: list[tuple[SpecRecord, Quantity]] = field(default_factory=list)
    unparsed: list[SpecRecord] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.parsed) + len(self.unparsed)

    @property
    def n_parsed(self) -> int:
        return len(self.parsed)

    @property
    def n_unparsed(self) -> int:
        return len(self.unparsed)

    def describe(self) -> str:
        """The sentence a consumer prints beside its comparison."""
        if not self.total:
            return "0 rows to compare"
        if not self.unparsed:
            return f"all {self.total} rows parsed"
        return f"{self.n_unparsed} of {self.total} rows could not be parsed"

    def listing(self) -> list[str]:
        """One line per unparsed row — never a silent exclusion.

        Names the row the way a citation does (symbol or name, what it printed,
        the page to open), so "listed below" in the ADR is literally satisfiable.
        """
        lines = []
        for record in self.unparsed:
            label = record.symbol or record.name or record.id or "(unnamed row)"
            printed = _printed_cell(record, self.role) or "(no value printed)"
            page = f"p.{record.page}" if record.page is not None else "p.?"
            lines.append(f"{label}: {printed} ({page})")
        return lines


def parse_population(
    records: Iterable[SpecRecord], *, role: str = ""
) -> ParsePopulation:
    """Split records into what parsed and what did not, for one comparison.

    `role` names the column being compared (`"max"`, `"min"`, …); the default
    `""` uses each record's representative quantity. Records are never dropped —
    that is the whole point — and order is preserved so a report reads in
    document order.
    """
    if role and role not in VALUE_ROLES:
        raise ValueError(f"unknown value role {role!r}; expected one of {VALUE_ROLES}")
    population = ParsePopulation(role=role)
    for record in records:
        quantity = (
            record_quantity(record)
            if not role
            else parse_quantity(
                getattr(record, role), record.unit.verbatim or record.unit.canonical
            )
        )
        if quantity is None:
            population.unparsed.append(record)
        else:
            population.parsed.append((record, quantity))
    return population


def _printed_cell(record: SpecRecord, role: str) -> str:
    """The verbatim text a listing quotes back for one row."""
    if role:
        return getattr(record, role).strip()
    for candidate in SELECTOR_ORDER:
        text = getattr(record, candidate).strip()
        if text:
            return text
    return ""


@dataclass(frozen=True)
class ParseRate:
    """Parse coverage over a record set, broken down by section.

    A measurement, not a target: a low rate on a section of prose-valued rows
    ("See Figure 7") is the correct answer, and the number exists so the phase
    report can state it rather than so a rule can be tuned until it looks good.
    """

    n_records: int = 0
    n_parsed: int = 0
    by_section: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def rate(self) -> float:
        """Parsed share in 0.0–1.0; 0.0 for an empty set."""
        return self.n_parsed / self.n_records if self.n_records else 0.0

    def as_table(self, *, title: str = "") -> str:
        """Markdown table, section by section, for the phase report."""
        lines = [f"### {title}"] if title else []
        lines += ["| Section | Records | Parsed | Rate |", "|---|---:|---:|---:|"]
        for section, (parsed, total) in self.by_section.items():
            share = parsed / total if total else 0.0
            lines.append(f"| {section or '(unnumbered)'} | {total} | {parsed} | {share:.0%} |")
        lines.append(
            f"| **all** | **{self.n_records}** | **{self.n_parsed}** "
            f"| **{self.rate:.0%}** |"
        )
        return "\n".join(lines)


def parse_rate(records: Sequence[SpecRecord]) -> ParseRate:
    """Measure how much of a record set the numeric layer can read.

    Re-parses rather than reading the stored fields, so a corpus published
    before this layer existed is measurable exactly like a fresh one.
    """
    by_section: dict[str, tuple[int, int]] = {}
    n_parsed = 0
    for record in records:
        parsed = record_quantity(record) is not None
        n_parsed += parsed
        done, total = by_section.get(record.section, (0, 0))
        by_section[record.section] = (done + parsed, total + 1)
    return ParseRate(n_records=len(records), n_parsed=n_parsed, by_section=by_section)
