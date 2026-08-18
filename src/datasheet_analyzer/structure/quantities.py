"""The parsed numeric layer over verbatim spec strings (phase 6, ticket 02).

`specs.json` records what the datasheet *printed*: `"1350 mA"`, `"-40 to +85"`,
`"< 5"`, `"See Figure 7"`. Those strings are the answer a designer checks
against the page, so they are authoritative and this module never mutates
them. What it adds beside them is a *parse*: a number in a canonical unit, so
a machine can sort, compare, and compute a margin.

Three rules govern everything here, and they are the reason this layer is
allowed to exist under invariant 8 (ADR 0007):

- **Additive, never destructive.** `parse_quantity` is a pure function of a
  string. Nothing it produces replaces a verbatim field; `annotate_record`
  writes only the additive `*_si` / `value_kind` / `parse_confidence` fields
  that `models.SpecRecord` froze for it.
- **Failing is a first-class outcome.** `"See Figure 7"` is a perfectly good
  datasheet cell and is not a quantity. It returns `None`, is recorded as
  `parse_confidence: none`, and stays that way. Nothing here interpolates, and
  nothing guesses a unit that was neither printed nor hinted.
- **A consumer that sorts must say what it could not sort.** `coverage()` is
  the documented helper for that: it returns the unparsed population with a
  citation per row, so `dsa compare` and the design cards report "3 of 47 rows
  could not be parsed, listed below" instead of quietly dropping them.

## The shapes it parses

| shape | example | `value_kind` | result |
|---|---|---|---|
| plain | `105` | `point` | 105.0 |
| signed / unicode minus | `-40`, `+85` | `point` | -40.0, 85.0 |
| range | `-40 to +85`, `-40...125` | `range` | low + high |
| inequality | `< 5`, `>= 1.8` | `bound` | the bound + its operator |
| tolerance | `+/-0.5` | `tolerance` | the magnitude |
| SI prefix | `1350 mA`, `12 GSPS` | `point` | 1.35 A, 1.2e10 SPS |
| scientific | `1.2e-9` | `point` | 1.2e-09 |
| anything else | `See Figure 7`, `Note 2`, an em dash, `` | - | **`None`** |

The grammar is *anchored*: a string parses only if the whole of it is a
quantity. That is what makes `"See Figure 7"` fail rather than yield `7`, and
it is deliberately stricter than a scan-for-the-first-number heuristic, which
is the single easiest way for this layer to produce a confidently wrong number.

**Shapes deliberately not parsed** (they return `None` rather than an
approximation): a centre-with-tolerance pair (`2.5 +/-0.1`), hex literals
(`0x1A04` - register addresses belong to `derive/registers.py`), values
qualified by prose (`5 max`, `2 typ`), and multi-quantity cells.

## Units

Canonicalisation reuses `structure/units.py` - including **both** ohm glyphs
(U+2126 OHM SIGN and U+03A9 GREEK CAPITAL LETTER OMEGA), which is why that
mapping lives in one place. On top of it this module knows two things
`units.py` deliberately does not: which units take an SI prefix (`mA` is
milli-`A`; `dBm` is not milli-`dB`), and what scale that prefix implies.

`unit_si` is the **base** unit and `value_si` is scaled into it, so `1350 mA`
and `1.35 A` compare equal. Two documented exceptions to "SI":

- **Temperature stays degrees Celsius.** Datasheets print it, a designer reads
  it, and differences are identical in either scale. Converting to kelvin
  would make every printed number unrecognisable for no gain.
- **Logarithmic and dimensionless units are atomic** (`dB`, `dBm`, `dBc/Hz`,
  `%`, `ppm`, `UI`, `bits`, `LSB`): they take no prefix and no scaling.

An unrecognised unit does not fail the parse - the number is real - but it
caps `parse_confidence` at `low` and leaves the unit uncanonicalised, so a
consumer comparing across parts can see that it should not.

## `unit_hint`

Spec tables usually print the unit in its own column, not in the value cell:
the row says `1350` and the table says `mA`. `parse_quantity(text, unit_hint)`
takes that column, and uses it **only when the value cell names no unit of its
own**. A unit printed in the cell always wins over the hint.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from datasheet_analyzer.models import (
    VALUE_KIND_BOUND,
    VALUE_KIND_POINT,
    VALUE_KIND_RANGE,
    VALUE_KIND_TOLERANCE,
    Confidence,
    DerivedValue,
    ParseConfidence,
    SpecRecord,
    SpecUnit,
)
from datasheet_analyzer.structure.units import canonical_unit, normalize_text

__all__ = [
    "ATOMIC_UNITS",
    "BASE_UNITS",
    "CELL_ROLES",
    "DERIVATION_PARSE",
    "DERIVATION_PARSE_SI",
    "SI_PREFIXES",
    "ParseCoverage",
    "Quantity",
    "UnitResolution",
    "UnparsedCell",
    "annotate_record",
    "annotate_records",
    "coverage",
    "parse_quantity",
    "parse_record_cells",
    "resolve_unit",
]

# The two derivation rule names this module answers to (invariant 8, clause
# (b)). `derive/provenance.is_derivation_rule` checks their shape; a value that
# needed no scaling says so, because "+si_normalize" on an unscaled number
# claims an arithmetic step that never happened.
DERIVATION_PARSE = "parse_quantity"
DERIVATION_PARSE_SI = "parse_quantity+si_normalize"

#: SI prefixes, as printed in datasheets. `K` is accepted alongside `k` because
#: vendors print `KHz`; kelvin is spelled `K` *alone* and is resolved as an
#: atomic unit before any prefix is considered.
SI_PREFIXES: dict[str, float] = {
    "T": 1e12,
    "G": 1e9,
    "M": 1e6,
    "k": 1e3,
    "K": 1e3,
    "m": 1e-3,
    "µ": 1e-6,  # MICRO SIGN - what PDFs actually carry
    "μ": 1e-6,  # GREEK SMALL LETTER MU
    "u": 1e-6,  # ASCII fallback
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
    "a": 1e-18,
}

#: Units that take an SI prefix. `value_si` is expressed in these.
BASE_UNITS: frozenset[str] = frozenset(
    {
        "V",
        "A",
        "s",
        "Hz",
        "F",
        "W",
        "H",
        "J",
        "ohm",  # what `units.canonical_unit` returns for either ohm glyph
        "SPS",
        "bps",
        "Vpp",
        "Vppdiff",
        "Vrms",
        "B",
    }
)

#: Units that take no prefix and no scaling: logarithmic, angular,
#: dimensionless, or temperature. Checked *before* the prefix split, which is
#: what keeps `dBm` from being read as milli-`dB`.
ATOMIC_UNITS: frozenset[str] = frozenset(
    {
        "dB",
        "dBc",
        "dBm",
        "dBW",
        "dBV",
        "dBi",
        "dBFS",
        "dBc/Hz",
        "dBm/Hz",
        "dBFS/Hz",
        "°C",
        "°C/W",
        "°F",
        "K",
        "K/W",
        "deg",
        "°",
        "%",
        "ppm",
        "ppb",
        "UI",
        "bit",
        "bits",
        "LSB",
        "V/V",
    }
)

#: Words that occupy the unit slot grammatically but are not units. A cell like
#: `5 max` is a qualified value, not a quantity in the sense this layer
#: promises, so it fails the parse outright rather than yielding `5 "max"`.
NON_UNIT_WORDS: frozenset[str] = frozenset(
    {
        "and",
        "each",
        "fig",
        "figure",
        "max",
        "maximum",
        "min",
        "minimum",
        "n/a",
        "na",
        "nom",
        "nominal",
        "note",
        "notes",
        "or",
        "page",
        "per",
        "ref",
        "see",
        "table",
        "tbd",
        "to",
        "total",
        "typ",
        "typical",
    }
)

#: The `SpecRecord` cells this layer parses, in the order `annotate_record`
#: prefers them when choosing the record's *primary* value. `value` is the
#: single-value tables' one cell; after it, a typical summarises a row better
#: than either limit does.
CELL_ROLES: tuple[str, ...] = ("value", "typ", "max", "min")

# --- grammar ---------------------------------------------------------------
# Anchored, whole-string patterns. Order of application is tolerance -> bound
# -> range -> point: the first three are recognisable by a leading operator or
# an infix separator, and `point` is what is left.

_NUM = r"[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
# A unit token: no whitespace, digits, operators, brackets or commas. `/` is
# allowed *between* segments so `degC/W` and `V/us` are single tokens.
_UNIT_ATOM = r"[^\s\d<>=±,()\[\]/]+"
# The lookahead keeps a range's separator word out of the unit slot: without
# it `125 to -40` matches as `125` with a unit of "to", separated by the
# hyphen, and the whole range is lost to the non-unit-word check.
_UNIT = rf"(?!(?:to|through|thru)\b){_UNIT_ATOM}(?:/{_UNIT_ATOM})*"
# Range separators. `-` is included: after `units.normalize_text` every en, em
# and minus dash is already a plain hyphen, so `-40 to +85`, `-40...125` and
# `-40 - 125` all arrive here in the same shape.
_SEP = r"(?:\bto\b|\bthrough\b|\bthru\b|\.{2,3}|…|~|-)"
_OPERATORS = {"<": "<", "<=": "<=", "≤": "<=", ">": ">", ">=": ">=", "≥": ">="}

_POINT_RE = re.compile(rf"^(?P<num>{_NUM})\s*(?P<unit>{_UNIT})?$")
_BOUND_RE = re.compile(rf"^(?P<op><=|>=|≤|≥|<|>)\s*(?P<num>{_NUM})\s*(?P<unit>{_UNIT})?$")
_TOLERANCE_RE = re.compile(rf"^(?:±|\+/-|\+-)\s*(?P<num>{_NUM})\s*(?P<unit>{_UNIT})?$")
_RANGE_RE = re.compile(
    rf"^(?P<lo>{_NUM})\s*(?P<lounit>{_UNIT})?\s*{_SEP}\s*(?P<hi>{_NUM})\s*(?P<hiunit>{_UNIT})?$"
)
#: Trailing footnote markers (`105(1)`, `2.5 (1)(2)`) are provenance, not part
#: of the value. Stripping them is the one cleanup this layer performs, and it
#: costs a confidence step so the leniency stays visible.
_FOOTNOTE_RE = re.compile(r"(?:\s*\(\s*\d+\s*\))+$")

#: Whitespace PDFs emit that `str.strip` does not treat as space.
_ODD_SPACES = (" ", " ", " ", " ")


@dataclass(frozen=True)
class UnitResolution:
    """A unit token resolved to a base unit and the scale that reaches it.

    `known` is the honest half: an unrecognised unit still resolves (the number
    beside it is real) but with `scale == 1.0`, the token passed through as
    `unit_si`, and `known=False` so the caller can cap confidence.
    """

    verbatim: str
    unit_si: str
    scale: float
    known: bool


def _resolve_atom(token: str) -> tuple[str, float] | None:
    """One unprefixed-or-prefixed unit token -> (base unit, scale), or `None`."""
    if not token:
        return None
    if token in ATOMIC_UNITS:
        return canonical_unit(token).canonical, 1.0
    canonical = canonical_unit(token).canonical
    if canonical in ATOMIC_UNITS or canonical in BASE_UNITS:
        return canonical, 1.0
    prefix, rest = token[:1], token[1:]
    if prefix in SI_PREFIXES and rest and rest not in ATOMIC_UNITS:
        rest_canonical = canonical_unit(rest).canonical
        if rest_canonical in BASE_UNITS:
            return rest_canonical, SI_PREFIXES[prefix]
    return None


def resolve_unit(text: str | SpecUnit | None) -> UnitResolution | None:
    """Resolve a printed unit to `(unit_si, scale)`; `None` when there is no unit.

    Composite units divide: `V/us` resolves as volts over microseconds, giving
    base `V/s` and scale 1e6. Units printed with a solidus that mean one thing
    (`degC/W`, `dBc/Hz`) are listed in `ATOMIC_UNITS` and never split.
    """
    if isinstance(text, SpecUnit):
        text = text.verbatim
    token = (text or "").strip()
    if not token:
        return None
    if token.lower() in NON_UNIT_WORDS:
        return UnitResolution(verbatim=token, unit_si="", scale=1.0, known=False)

    direct = _resolve_atom(token)
    if direct is not None:
        return UnitResolution(verbatim=token, unit_si=direct[0], scale=direct[1], known=True)

    if "/" in token:
        parts = [_resolve_atom(part) for part in token.split("/")]
        if all(part is not None for part in parts):
            resolved = [part for part in parts if part is not None]
            scale = resolved[0][1]
            for base, denominator in resolved[1:]:
                del base
                scale /= denominator
            return UnitResolution(
                verbatim=token,
                unit_si="/".join(base for base, _ in resolved),
                scale=scale,
                known=True,
            )

    # Unrecognised: keep the token as printed, do not scale, say it is unknown.
    return UnitResolution(
        verbatim=token, unit_si=canonical_unit(token).canonical, scale=1.0, known=False
    )


@dataclass(frozen=True)
class Quantity:
    """One printed value, parsed. Immutable, and never a replacement for the print.

    `value` is always expressed in `unit_si`:

    - `point` - `value` is the number; `value_hi` is `None`.
    - `range` - `value` is the low end, `value_hi` the high end.
    - `bound` - `value` is the bound and `operator` says which side of it the
      real value lies on (`<`, `<=`, `>`, `>=`).
    - `tolerance` - `value` is the magnitude (`+/-0.5` -> 0.5), which is what
      makes it comparable; the sign is in the kind, not the number.

    `confidence` is never `NONE`: a `Quantity` exists only when something
    parsed. `NONE` is what `parse_quantity` returning `None` records.
    """

    verbatim: str
    kind: str
    value: float
    value_hi: float | None = None
    unit_si: str = ""
    unit_verbatim: str = ""
    operator: str = ""
    unit_from_hint: bool = False
    confidence: ParseConfidence = ParseConfidence.HIGH
    derivation: str = DERIVATION_PARSE

    @property
    def low(self) -> float:
        """The low end of what this value permits - the number itself unless a range."""
        return self.value

    @property
    def high(self) -> float:
        """The high end: a range's top, otherwise the number itself."""
        return self.value if self.value_hi is None else self.value_hi

    def to_derived_value(
        self,
        *,
        source: str,
        page: int | None,
        confidence: Confidence = Confidence.UNKNOWN,
        verbatim: str = "",
    ) -> DerivedValue:
        """Wrap this parse in the invariant-8 envelope, citing the record it came from.

        `verbatim` defaults to the string that was parsed, because the printed
        value is the answer and the number beside it is the convenience.
        """
        return DerivedValue(
            verbatim=verbatim or self.verbatim,
            value_si=self.value,
            value_si_hi=self.value_hi,
            unit_si=self.unit_si,
            value_kind=self.kind,
            source=source,
            page=page,
            derivation=self.derivation,
            confidence=confidence,
        )


def _to_float(token: str) -> float | None:
    try:
        return float(token.replace(",", ""))
    except ValueError:  # pragma: no cover - the grammar admits nothing else
        return None


def _prepare(text: str) -> tuple[str, bool]:
    """Normalize a printed cell for parsing; report whether cleanup was needed.

    Dash unification and whitespace collapsing come from
    `structure/units.normalize_text` - the same normalizer the spec records
    themselves were built with - so a minus sign, an en dash and a hyphen are
    one shape here. Footnote markers are stripped, and that *is* leniency: it
    is reported so the parse is graded a step lower.
    """
    raw = text or ""
    for space in _ODD_SPACES:
        raw = raw.replace(space, " ")
    prepared = normalize_text(raw)
    stripped = _FOOTNOTE_RE.sub("", prepared).strip()
    lenient = stripped != prepared or "," in stripped
    return stripped, lenient


def _grade(lenient: bool, unit_known: bool | None) -> ParseConfidence:
    """The documented confidence rule for a successful parse.

    - `high` - the whole cell matched the grammar cleanly and its unit is
      either recognised or genuinely absent (a dimensionless number).
    - `medium` - a cleanup step was needed (a footnote marker stripped, a
      thousands separator removed). The number is right; the cell was untidy.
    - `low` - a unit was printed that this module does not recognise, so the
      number cannot be safely compared against another part's.
    """
    if unit_known is False:
        return ParseConfidence.LOW
    if lenient:
        return ParseConfidence.MEDIUM
    return ParseConfidence.HIGH


def _is_non_unit(token: str | None) -> bool:
    """Whether a matched unit token is a word that disqualifies the whole parse."""
    return bool(token) and (token or "").lower() in NON_UNIT_WORDS


def _units_for(
    cell_unit: str | None, hint: str | SpecUnit | None
) -> tuple[UnitResolution | None, bool]:
    """Pick the unit that applies: the one printed in the cell, else the hint."""
    printed = resolve_unit(cell_unit)
    if printed is not None:
        return printed, False
    hinted = resolve_unit(hint)
    if hinted is not None:
        return hinted, True
    return None, False


def _build(
    *,
    verbatim: str,
    kind: str,
    raw_value: float,
    raw_value_hi: float | None,
    unit: UnitResolution | None,
    from_hint: bool,
    operator: str,
    lenient: bool,
    scaled: bool | None = None,
) -> Quantity:
    """Assemble a `Quantity`, applying the unit's scale to the raw number(s).

    `scaled` overrides the derivation name for a caller that already applied
    the scale itself (a range scales each end by its own prefix): the rule
    name must say whether arithmetic happened, not whether this function did
    it.
    """
    scale = unit.scale if unit else 1.0
    if scaled is None:
        scaled = scale != 1.0
    return Quantity(
        verbatim=verbatim,
        kind=kind,
        value=raw_value * scale,
        value_hi=None if raw_value_hi is None else raw_value_hi * scale,
        unit_si=unit.unit_si if unit else "",
        unit_verbatim=unit.verbatim if unit else "",
        operator=operator,
        unit_from_hint=from_hint,
        confidence=_grade(lenient, None if unit is None else unit.known),
        derivation=DERIVATION_PARSE_SI if scaled else DERIVATION_PARSE,
    )


def parse_quantity(text: str, unit_hint: str | SpecUnit | None = "") -> Quantity | None:
    """Parse one printed value into a `Quantity`, or `None` if it is not one.

    `None` is a first-class outcome - `"See Figure 7"`, `"Note 2"`, an em dash
    and `""` are all legitimate datasheet cells that are not quantities - and
    it is recorded downstream as `parse_confidence: none`, never as a zero, a
    default, or an interpolation.

    `unit_hint` is the table's unit column and applies only when the cell
    itself prints no unit.
    """
    original = (text or "").strip()
    prepared, lenient = _prepare(text)
    if not prepared:
        return None

    match = _TOLERANCE_RE.match(prepared)
    if match:
        value = _to_float(match.group("num"))
        if value is None or _is_non_unit(match.group("unit")):
            return None
        unit, from_hint = _units_for(match.group("unit"), unit_hint)
        return _build(
            verbatim=original,
            kind=VALUE_KIND_TOLERANCE,
            raw_value=abs(value),
            raw_value_hi=None,
            unit=unit,
            from_hint=from_hint,
            operator="±",
            lenient=lenient,
        )

    match = _BOUND_RE.match(prepared)
    if match:
        value = _to_float(match.group("num"))
        if value is None or _is_non_unit(match.group("unit")):
            return None
        unit, from_hint = _units_for(match.group("unit"), unit_hint)
        return _build(
            verbatim=original,
            kind=VALUE_KIND_BOUND,
            raw_value=value,
            raw_value_hi=None,
            unit=unit,
            from_hint=from_hint,
            operator=_OPERATORS[match.group("op")],
            lenient=lenient,
        )

    # `point` is tried *before* `range` because the two grammars overlap on
    # scientific notation: `1.2e-9` is one number, and a range matcher run
    # first reads it as `1.2` .. `9` with a unit of "e". A real range never
    # matches `point`, whose unit token admits no digits.
    match = _POINT_RE.match(prepared)
    if match:
        value = _to_float(match.group("num"))
        if value is None or _is_non_unit(match.group("unit")):
            # `5 max` is a qualified value, not a quantity. Refusing it is the
            # difference between an honest gap and a number with a wrong unit.
            return None
        unit, from_hint = _units_for(match.group("unit"), unit_hint)
        return _build(
            verbatim=original,
            kind=VALUE_KIND_POINT,
            raw_value=value,
            raw_value_hi=None,
            unit=unit,
            from_hint=from_hint,
            operator="",
            lenient=lenient,
        )

    match = _RANGE_RE.match(prepared)
    if match:
        return _parse_range(original, match, unit_hint, lenient)

    return None


def _parse_range(
    original: str, match: re.Match[str], unit_hint: str | SpecUnit | None, lenient: bool
) -> Quantity | None:
    """Finish a range match: both ends, one unit, both scaled into it.

    A range whose two ends print *incompatible* units (`1 mA to 2 V`) is not a
    range this module will guess at - it returns `None` rather than pick one.
    """
    low = _to_float(match.group("lo"))
    high = _to_float(match.group("hi"))
    lo_unit_text = match.group("lounit") or ""
    hi_unit_text = match.group("hiunit") or ""
    if low is None or high is None:
        return None
    if _is_non_unit(lo_unit_text) or _is_non_unit(hi_unit_text):
        return None

    lo_unit = resolve_unit(lo_unit_text)
    hi_unit = resolve_unit(hi_unit_text)
    from_hint = False
    if lo_unit is not None and hi_unit is not None:
        if lo_unit.unit_si != hi_unit.unit_si:
            return None
        # Each end carries its own prefix (`500 mA to 2 A` is legal print), so
        # they are scaled separately and the shared base unit is what remains.
        scaled = lo_unit.scale != 1.0 or hi_unit.scale != 1.0
        low *= lo_unit.scale
        high *= hi_unit.scale
        unit: UnitResolution | None = UnitResolution(
            verbatim=hi_unit.verbatim,
            unit_si=hi_unit.unit_si,
            scale=1.0,
            known=lo_unit.known and hi_unit.known,
        )
    else:
        unit, from_hint = _units_for(hi_unit_text or lo_unit_text, unit_hint)
        scaled = unit is not None and unit.scale != 1.0
        if unit is not None:
            low *= unit.scale
            high *= unit.scale
            unit = UnitResolution(
                verbatim=unit.verbatim, unit_si=unit.unit_si, scale=1.0, known=unit.known
            )

    if high < low:
        low, high = high, low
    return _build(
        verbatim=original,
        kind=VALUE_KIND_RANGE,
        raw_value=low,
        raw_value_hi=high,
        unit=unit,
        from_hint=from_hint,
        operator="",
        lenient=lenient,
        scaled=scaled,
    )


# --- the layer over `SpecRecord` -------------------------------------------


def parse_record_cells(record: SpecRecord) -> dict[str, Quantity | None]:
    """Parse each of a record's value cells, keyed by cell role.

    Every printed cell appears in the result, including the ones that did not
    parse (as `None`). A cell the record never printed is absent - nothing was
    attempted, so there is nothing to report.
    """
    parsed: dict[str, Quantity | None] = {}
    for role in CELL_ROLES:
        printed = (getattr(record, role, "") or "").strip()
        if printed:
            parsed[role] = parse_quantity(printed, record.unit)
    return parsed


_CONFIDENCE_ORDER = (
    ParseConfidence.NONE,
    ParseConfidence.LOW,
    ParseConfidence.MEDIUM,
    ParseConfidence.HIGH,
)


def _weakest(*grades: ParseConfidence) -> ParseConfidence:
    return min(grades, key=_CONFIDENCE_ORDER.index)


def _scalar(quantity: Quantity | None, *, high: bool) -> float | None:
    """The single number a per-cell field carries, or `None`.

    A cell that printed a range in a limit column (`-40 to 125` under `MAX`)
    contributes its top for `max_si` and its bottom otherwise - the end of the
    range that column is actually asserting.
    """
    if quantity is None:
        return None
    return quantity.high if high else quantity.low


def annotate_record(record: SpecRecord) -> SpecRecord:
    """Fill a record's additive numeric fields in place; return the same record.

    **No verbatim field is touched** - `min`, `typ`, `max`, `value`, `unit`,
    `symbol`, `name`, `conditions` and `row_verbatim` are exactly what
    extraction printed, before and after. This writes only the fields
    `models.SpecRecord` froze for the parsed layer.

    Two documented rules decide the record's *primary* value:

    1. `min_si` / `typ_si` / `max_si` are the per-cell parses, and they are
       what a margin check joins on (abs-max against recommended-max).
    2. `value_si` is the primary cell's parse, and `value_si_cell` names which
       cell that was, so a typical is never read as a maximum. A row that
       printed only a min and a max is the one composite case: it *is* a
       range, and is recorded as `value_kind: range` spanning the two, with
       `value_si_cell` naming the cell the low end came from.

    A record where nothing parsed keeps `parse_confidence: none` and every
    numeric field `None` - the honest empty, never a zero.
    """
    parsed = parse_record_cells(record)
    record.min_si = _scalar(parsed.get("min"), high=False)
    record.typ_si = _scalar(parsed.get("typ"), high=False)
    record.max_si = _scalar(parsed.get("max"), high=True)

    primary_role = ""
    primary: Quantity | None = None
    for role in CELL_ROLES:
        candidate = parsed.get(role)
        if candidate is not None:
            primary_role, primary = role, candidate
            break

    if primary is None:
        record.value_si = None
        record.value_si_hi = None
        record.value_si_cell = ""
        record.unit_si = ""
        record.value_kind = ""
        record.parse_confidence = ParseConfidence.NONE
        return record

    low_q, high_q = parsed.get("min"), parsed.get("max")
    spans_min_max = (
        primary_role in ("max", "min")
        and low_q is not None
        and high_q is not None
        and low_q.unit_si == high_q.unit_si
        and low_q.kind == VALUE_KIND_POINT
        and high_q.kind == VALUE_KIND_POINT
    )
    if spans_min_max and low_q is not None and high_q is not None:
        record.value_si = min(low_q.value, high_q.value)
        record.value_si_hi = max(low_q.value, high_q.value)
        record.value_si_cell = "min"
        record.unit_si = low_q.unit_si
        record.value_kind = VALUE_KIND_RANGE
        record.parse_confidence = _weakest(low_q.confidence, high_q.confidence)
        return record

    record.value_si = primary.value
    record.value_si_hi = primary.value_hi
    record.value_si_cell = primary_role
    record.unit_si = primary.unit_si
    record.value_kind = primary.kind
    record.parse_confidence = primary.confidence
    return record


def annotate_records(records: Iterable[SpecRecord]) -> list[SpecRecord]:
    """`annotate_record` over a corpus's records, returned as a list.

    Written for consumers loading a `specs.json` published before this layer
    existed: the parse is a pure function of strings already on disk, so an old
    corpus gains the numeric layer in memory without a rebuild.
    """
    return [annotate_record(record) for record in records]


# --- reporting the unparsed population -------------------------------------


@dataclass(frozen=True)
class UnparsedCell:
    """One printed cell that did not parse, with enough to cite it on a page."""

    record_id: str
    cell: str
    verbatim: str
    section: str = ""
    symbol: str = ""
    name: str = ""
    page: int | None = None

    def describe(self) -> str:
        where = f"p.{self.page}" if self.page else "page unknown"
        label = self.symbol or self.name or self.record_id
        return f"{label} [{self.cell}] = {self.verbatim!r} ({where}, {self.record_id})"


@dataclass(frozen=True)
class ParseCoverage:
    """What a consumer could and could not turn into a number.

    The point of this type is that **a consumer that sorts or compares cannot
    silently drop rows**: it holds the unparsed population, each item citable,
    so `dsa compare` and the design cards can print "3 of 47 rows could not be
    parsed, listed below" instead of showing a short table that looks complete.

    `blank` counts records that printed nothing at all in the cells asked
    about. Those are not failures - there was nothing to parse - and folding
    them into the rate would understate it.
    """

    considered: int
    parsed: int
    unparsed: tuple[UnparsedCell, ...] = ()
    blank: int = 0

    @property
    def unparsed_count(self) -> int:
        return len(self.unparsed)

    @property
    def rate(self) -> float:
        """Parsed fraction of the cells that printed something. 1.0 when none did."""
        return 1.0 if self.considered == 0 else self.parsed / self.considered

    def describe(self, *, limit: int = 20, subject: str = "rows") -> str:
        """The sentence a consumer prints. Never empty, never silently short."""
        if self.considered == 0:
            return f"no {subject} printed a value to parse"
        if not self.unparsed:
            return f"all {self.considered} {subject} parsed"
        head = (
            f"{self.unparsed_count} of {self.considered} {subject} could not be parsed, "
            f"listed below:"
        )
        lines = "\n".join(f"  - {item.describe()}" for item in self.unparsed[:limit])
        if len(self.unparsed) > limit:
            lines += f"\n  - ... and {len(self.unparsed) - limit} more"
        return f"{head}\n{lines}"


def _cells_of(record: SpecRecord, cells: Sequence[str]) -> Iterator[tuple[str, str]]:
    for role in cells:
        printed = (getattr(record, role, "") or "").strip()
        if printed:
            yield role, printed


def coverage(
    records: Iterable[SpecRecord],
    *,
    cells: Sequence[str] = CELL_ROLES,
    primary_only: bool = True,
) -> ParseCoverage:
    """Measure what parsed across `records`, and collect what did not.

    `primary_only` (the default) asks the question a sorting consumer asks:
    *does this record have a number at all?* It considers each record once,
    counting it parsed if any of `cells` parsed and reporting its first
    unparsed cell otherwise. With `primary_only=False` every printed cell is
    counted separately, which is the question a coverage report asks.

    Records printing nothing in `cells` are counted in `blank`, not held
    against the rate: nothing was printed, so nothing failed.
    """
    considered = parsed = blank = 0
    unparsed: list[UnparsedCell] = []
    for record in records:
        printed = list(_cells_of(record, cells))
        if not printed:
            blank += 1
            continue
        failures = [
            UnparsedCell(
                record_id=record.id,
                cell=role,
                verbatim=text,
                section=record.section,
                symbol=record.symbol,
                name=record.name,
                page=record.page,
            )
            for role, text in printed
            if parse_quantity(text, record.unit) is None
        ]
        if primary_only:
            considered += 1
            if len(failures) < len(printed):
                parsed += 1
            else:
                unparsed.append(failures[0])
        else:
            considered += len(printed)
            parsed += len(printed) - len(failures)
            unparsed.extend(failures)
    return ParseCoverage(
        considered=considered, parsed=parsed, unparsed=tuple(unparsed), blank=blank
    )
