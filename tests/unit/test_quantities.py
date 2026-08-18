"""`structure/quantities.py` - the parsed numeric layer (phase 6, ticket 02).

Two things are being defended here, and they pull in opposite directions:

- **Every shape in the plan's table parses**, with the right kind, the right
  number, and the right canonical unit.
- **Everything else returns `None`.** A datasheet cell is prose as often as it
  is a number, and the failure that would matter is not a missing parse but a
  confident wrong one - `"See Figure 7"` yielding `7`, `"5 max"` yielding 5 in
  a unit called "max". So the unparseable cases are tested as carefully as the
  parseable ones, and `None` is asserted as an outcome, never tolerated as a
  gap.

The third defence is the one invariant 8 rests on: the verbatim strings are
snapshotted before the layer runs and compared field by field after it, so
"additive" is a checked property rather than a claim in a docstring.
"""

from __future__ import annotations

import pytest

from datasheet_analyzer.derive.provenance import check_provenance, is_derivation_rule
from datasheet_analyzer.models import (
    VALUE_KIND_BOUND,
    VALUE_KIND_POINT,
    VALUE_KIND_RANGE,
    VALUE_KIND_TOLERANCE,
    ParseConfidence,
    SpecRecord,
    SpecUnit,
)
from datasheet_analyzer.structure.quantities import (
    DERIVATION_PARSE,
    DERIVATION_PARSE_SI,
    Quantity,
    annotate_record,
    annotate_records,
    coverage,
    parse_quantity,
    parse_record_cells,
    resolve_unit,
)
from datasheet_analyzer.structure.units import canonical_unit

# The two ohm glyphs, spelled by code point so no editor or encoding step can
# quietly fold them together. `structure/units.py` maps both to "ohm"; this
# module must inherit that rather than reimplement it.
OHM_SIGN = "Ω"  # OHM SIGN, what TI's PDFs carry
GREEK_OMEGA = "Ω"  # GREEK CAPITAL LETTER OMEGA, what other sources carry
MINUS = "−"  # MINUS SIGN
EN_DASH = "–"
EM_DASH = "—"
ELLIPSIS = "…"
MICRO = "µ"


def _record(**cells: object) -> SpecRecord:
    """A spec record with the given value cells; unit given as a plain string."""
    unit = str(cells.pop("unit", ""))
    return SpecRecord(
        section=str(cells.pop("section", "4.1")),
        table_index=int(cells.pop("table_index", 0)),
        row_index=int(cells.pop("row_index", 0)),
        symbol=str(cells.pop("symbol", "SYM")),
        page=int(cells.pop("page", 7)),
        unit=SpecUnit(verbatim=unit, canonical=canonical_unit(unit).canonical),
        **{key: str(value) for key, value in cells.items()},
    )


# --- one case per row of the plan's shapes table ---------------------------


def test_plain_integer_is_a_point() -> None:
    quantity = parse_quantity("105")
    assert quantity is not None
    assert (quantity.kind, quantity.value, quantity.value_hi) == (VALUE_KIND_POINT, 105.0, None)
    assert quantity.confidence is ParseConfidence.HIGH


def test_unicode_minus_sign_is_a_negative_point() -> None:
    quantity = parse_quantity(f"{MINUS}40")
    assert quantity is not None
    assert (quantity.kind, quantity.value) == (VALUE_KIND_POINT, -40.0)
    # The print is preserved exactly: the parse never rewrites the glyph.
    assert quantity.verbatim == f"{MINUS}40"


def test_explicit_plus_sign_is_a_positive_point() -> None:
    quantity = parse_quantity("+85")
    assert quantity is not None
    assert (quantity.kind, quantity.value) == (VALUE_KIND_POINT, 85.0)


def test_word_separated_range() -> None:
    quantity = parse_quantity(f"{MINUS}40 to +85")
    assert quantity is not None
    assert quantity.kind == VALUE_KIND_RANGE
    assert (quantity.value, quantity.value_hi) == (-40.0, 85.0)
    assert (quantity.low, quantity.high) == (-40.0, 85.0)


def test_ellipsis_separated_range() -> None:
    quantity = parse_quantity(f"-40{ELLIPSIS}125")
    assert quantity is not None
    assert (quantity.kind, quantity.value, quantity.value_hi) == (VALUE_KIND_RANGE, -40.0, 125.0)


def test_dash_separated_range_survives_dash_normalisation() -> None:
    # `units.normalize_text` folds en/em/minus dashes to a hyphen, so a range
    # printed with any of them arrives here in one shape.
    for text in (f"-40 {EN_DASH} 125", f"{MINUS}40 {EM_DASH} 125", "-40 - 125"):
        quantity = parse_quantity(text)
        assert quantity is not None, text
        assert (quantity.value, quantity.value_hi) == (-40.0, 125.0), text


def test_less_than_is_a_bound() -> None:
    quantity = parse_quantity("< 5")
    assert quantity is not None
    assert (quantity.kind, quantity.value, quantity.operator) == (VALUE_KIND_BOUND, 5.0, "<")


def test_greater_or_equal_glyph_is_a_bound() -> None:
    quantity = parse_quantity("≥ 1.8")
    assert quantity is not None
    assert (quantity.kind, quantity.value, quantity.operator) == (VALUE_KIND_BOUND, 1.8, ">=")


def test_tolerance_carries_the_magnitude() -> None:
    quantity = parse_quantity("±0.5")
    assert quantity is not None
    assert (quantity.kind, quantity.value, quantity.operator) == (VALUE_KIND_TOLERANCE, 0.5, "±")
    # The magnitude is what compares; the sign lives in the kind.
    assert quantity.value > 0


def test_si_prefix_milli_scales_to_the_base_unit() -> None:
    quantity = parse_quantity("1350 mA")
    assert quantity is not None
    assert (quantity.kind, quantity.value, quantity.unit_si) == (VALUE_KIND_POINT, 1.35, "A")
    assert quantity.unit_verbatim == "mA"
    assert quantity.derivation == DERIVATION_PARSE_SI


def test_si_prefix_giga_on_a_sample_rate() -> None:
    quantity = parse_quantity("12 GSPS")
    assert quantity is not None
    assert (quantity.value, quantity.unit_si) == (12e9, "SPS")


def test_scientific_notation_is_one_point_not_a_range() -> None:
    # The regression this pins: a range matcher run first reads `1.2e-9` as
    # `1.2` .. `9` with a unit of "e".
    quantity = parse_quantity("1.2e-9")
    assert quantity is not None
    assert (quantity.kind, quantity.value, quantity.value_hi) == (VALUE_KIND_POINT, 1.2e-9, None)


# --- the unparseable population, asserted case by case ---------------------


@pytest.mark.parametrize(
    "text",
    [
        "See Figure 7",
        "Note 2",
        EM_DASH,
        "",
        "   ",
        "N/A",
        "TBD",
        "Guaranteed",
        "5 max",
        "2 typ",
        "0x1A04",
        "JESD204B and JESD204C",
        "1, 2, 3, 4, 6 or 8",
        "2.5 ±0.1",
        "AC Coupling Only",
    ],
)
def test_unparseable_returns_none(text: str) -> None:
    """`None` is the outcome, not a failure to fix - and it is never a number."""
    assert parse_quantity(text) is None
    # A unit hint must not rescue prose: the hint says what unit *would* apply,
    # never that a value exists.
    assert parse_quantity(text, "mA") is None


@pytest.mark.parametrize(
    "text",
    ["See Figure 7", "Note 2", EM_DASH, "", "N/A", "5 max"],
)
def test_unparseable_record_is_recorded_as_parse_confidence_none(text: str) -> None:
    record = annotate_record(_record(typ=text, unit="mA"))
    assert record.parse_confidence is ParseConfidence.NONE
    assert record.value_si is None
    assert record.value_si_hi is None
    assert record.value_kind == ""
    assert record.value_si_cell == ""
    assert record.unit_si == ""
    # …and the print itself is untouched.
    assert record.typ == text


def test_figure_reference_never_yields_its_figure_number() -> None:
    """The failure this whole grammar is anchored to prevent."""
    for text in ("See Figure 7", "Figure 12", "Note 2", "Table 4"):
        assert parse_quantity(text) is None


# --- units -----------------------------------------------------------------


@pytest.mark.parametrize("glyph", [OHM_SIGN, GREEK_OMEGA])
def test_both_ohm_glyphs_canonicalise_through_units_module(glyph: str) -> None:
    assert glyph != OHM_SIGN or glyph != GREEK_OMEGA  # the two are distinct code points
    quantity = parse_quantity(f"50 {glyph}")
    assert quantity is not None
    assert quantity.unit_si == "ohm" == canonical_unit(glyph).canonical
    assert quantity.value == 50.0


@pytest.mark.parametrize("glyph", [OHM_SIGN, GREEK_OMEGA])
def test_prefixed_ohm_scales(glyph: str) -> None:
    quantity = parse_quantity(f"4.7 k{glyph}")
    assert quantity is not None
    assert (quantity.value, quantity.unit_si) == (4700.0, "ohm")


@pytest.mark.parametrize(
    ("text", "value", "unit_si"),
    [
        ("1.8 V", 1.8, "V"),
        ("500 mV", 0.5, "V"),
        (f"3 {MICRO}A", 3e-6, "A"),
        ("10 kHz", 1e4, "Hz"),
        ("2.5 GHz", 2.5e9, "Hz"),
        ("400 MSPS", 4e8, "SPS"),
        ("12.5 Gbps", 1.25e10, "bps"),
        ("250 ps", 250e-12, "s"),
        ("5 ns", 5e-9, "s"),
        ("1.5 pF", 1.5e-12, "F"),
        ("3 W", 3.0, "W"),
        ("750 mW", 0.75, "W"),
        (f"1 V/{MICRO}s", 1e6, "V/s"),
    ],
)
def test_si_prefixes_scale_into_the_base_unit(text: str, value: float, unit_si: str) -> None:
    quantity = parse_quantity(text)
    assert quantity is not None
    assert quantity.unit_si == unit_si
    assert quantity.value == pytest.approx(value)


@pytest.mark.parametrize(
    "text",
    ["-3 dBm", "70 dB", "-155 dBc/Hz", "105 °C", "38.5 °C/W", "2 %", "5 ppm", "0.3 UI", "14 bits"],
)
def test_logarithmic_and_dimensionless_units_are_never_prefix_scaled(text: str) -> None:
    """`dBm` is not milli-`dB`, and degrees Celsius stay degrees Celsius."""
    quantity = parse_quantity(text)
    assert quantity is not None
    printed_number = float(text.split()[0])
    assert quantity.value == pytest.approx(printed_number)
    assert quantity.derivation == DERIVATION_PARSE  # no scaling step happened
    assert quantity.confidence is ParseConfidence.HIGH


def test_unit_hint_applies_only_when_the_cell_prints_no_unit() -> None:
    hinted = parse_quantity("1350", "mA")
    assert hinted is not None
    assert (hinted.value, hinted.unit_si, hinted.unit_from_hint) == (1.35, "A", True)

    printed = parse_quantity("1.35 A", "mA")
    assert printed is not None
    assert (printed.value, printed.unit_si, printed.unit_from_hint) == (1.35, "A", False)


def test_unit_hint_accepts_a_spec_unit_object() -> None:
    quantity = parse_quantity("105", SpecUnit(verbatim="°C", canonical="°C"))
    assert quantity is not None
    assert quantity.unit_si == "°C"


def test_unrecognised_unit_keeps_the_number_but_caps_confidence() -> None:
    quantity = parse_quantity("5 flurbs")
    assert quantity is not None
    assert quantity.value == 5.0
    assert quantity.confidence is ParseConfidence.LOW
    assert quantity.unit_si == "flurbs"  # passed through, not invented
    resolution = resolve_unit("flurbs")
    assert resolution is not None and resolution.known is False


def test_dimensionless_number_with_no_unit_is_still_high_confidence() -> None:
    quantity = parse_quantity("2.5")
    assert quantity is not None
    assert quantity.unit_si == ""
    assert quantity.confidence is ParseConfidence.HIGH


def test_footnote_marker_is_stripped_and_costs_a_confidence_step() -> None:
    quantity = parse_quantity("2.5 (1)(2)", "V")
    assert quantity is not None
    assert quantity.value == 2.5
    assert quantity.confidence is ParseConfidence.MEDIUM
    assert quantity.verbatim == "2.5 (1)(2)"  # the print, unchanged


def test_thousands_separator_is_tolerated_at_medium_confidence() -> None:
    quantity = parse_quantity("1,350 mA")
    assert quantity is not None
    assert quantity.value == pytest.approx(1.35)
    assert quantity.confidence is ParseConfidence.MEDIUM


def test_range_scales_each_end_by_its_own_prefix() -> None:
    quantity = parse_quantity("500 mA to 2 A")
    assert quantity is not None
    assert (quantity.value, quantity.value_hi, quantity.unit_si) == (0.5, 2.0, "A")
    assert quantity.derivation == DERIVATION_PARSE_SI


def test_range_with_incompatible_units_refuses_to_guess() -> None:
    assert parse_quantity("1 mA to 2 V") is None


def test_range_printed_high_to_low_is_normalised() -> None:
    quantity = parse_quantity("125 to -40")
    assert quantity is not None
    assert (quantity.value, quantity.value_hi) == (-40.0, 125.0)


def test_derivation_names_are_well_formed_rule_names() -> None:
    """Invariant 8 clause (b): the rule that produced a value has a name."""
    assert is_derivation_rule(DERIVATION_PARSE)
    assert is_derivation_rule(DERIVATION_PARSE_SI)


def test_quantity_becomes_a_provenance_clean_derived_value() -> None:
    quantity = parse_quantity("1350 mA")
    assert quantity is not None
    value = quantity.to_derived_value(source="specs.json#rec_s4.9-t0-r12", page=21)
    assert value.verbatim == "1350 mA"  # the print is the answer
    assert value.value_si == pytest.approx(1.35)
    assert check_provenance(value) == []


def test_parse_quantity_is_pure() -> None:
    text = "1350 mA"
    first, second = parse_quantity(text, "V"), parse_quantity(text, "V")
    assert first == second
    assert text == "1350 mA"
    assert isinstance(first, Quantity)


# --- the layer over SpecRecord ---------------------------------------------

#: Every field of a `SpecRecord` that holds something the datasheet printed.
#: The layer may not touch any of them.
VERBATIM_FIELDS = (
    "symbol",
    "name",
    "conditions",
    "table_conditions",
    "min",
    "typ",
    "max",
    "value",
    "row_verbatim",
    "unit",
)


def _verbatim_snapshot(records: list[SpecRecord]) -> list[dict[str, object]]:
    return [{field: record.model_dump()[field] for field in VERBATIM_FIELDS} for record in records]


def test_no_verbatim_field_is_mutated_by_the_layer() -> None:
    """The invariant-8 property: the parsed layer is strictly additive.

    Snapshot every printed field of every record, run the layer, compare. A
    parse that rewrote `-40` to `-40.0`, or normalised an ohm glyph in place,
    would be caught here - and would be a corpus that no longer matches its
    printed page.
    """
    records = [
        _record(min=f"{MINUS}40", max="+85", unit="°C", symbol="TA"),
        _record(typ=f"50 {OHM_SIGN}", unit=OHM_SIGN, symbol="ZIN", row_index=1),
        _record(value="See Figure 7", unit="dB", symbol="GAIN", row_index=2),
        _record(min="1,350 (1)", typ="", max="", unit="mA", symbol="IDD", row_index=3),
    ]
    for record in records:
        record.row_verbatim = [record.min, record.typ, record.max, record.value]
    before = _verbatim_snapshot(records)

    annotate_records(records)

    assert _verbatim_snapshot(records) == before
    # …and the layer did run: at least one record gained a number.
    assert any(record.value_si is not None for record in records)


def test_annotate_fills_per_cell_parses_and_names_the_primary_cell() -> None:
    record = annotate_record(_record(typ="1350", max="1500", unit="mA", symbol="IDD"))
    assert record.typ_si == pytest.approx(1.35)
    assert record.max_si == pytest.approx(1.5)
    assert record.min_si is None
    # A typical is a better summary of a row than its limit, and the record
    # says which cell the number came from so it is never read as a max.
    assert record.value_si_cell == "typ"
    assert record.value_si == pytest.approx(1.35)
    assert record.unit_si == "A"
    assert record.value_kind == VALUE_KIND_POINT
    assert record.parse_confidence is ParseConfidence.HIGH


def test_single_value_cell_wins_over_the_limits() -> None:
    record = annotate_record(_record(value="3.3", min="3.0", unit="V"))
    assert record.value_si_cell == "value"
    assert record.value_si == pytest.approx(3.3)


def test_a_row_printing_only_min_and_max_is_recorded_as_a_range() -> None:
    record = annotate_record(_record(min=f"{MINUS}40", max="125", unit="°C", symbol="TA"))
    assert record.value_kind == VALUE_KIND_RANGE
    assert (record.value_si, record.value_si_hi) == (-40.0, 125.0)
    assert record.value_si_cell == "min"
    assert (record.min_si, record.max_si) == (-40.0, 125.0)


def test_a_range_printed_in_a_max_cell_contributes_its_top_to_max_si() -> None:
    record = annotate_record(_record(max="-40 to 125", unit="°C"))
    assert record.max_si == 125.0
    assert record.value_kind == VALUE_KIND_RANGE


def test_partially_parseable_record_keeps_the_half_it_got() -> None:
    record = annotate_record(_record(typ="See Figure 7", max="1500", unit="mA"))
    assert record.typ_si is None
    assert record.max_si == pytest.approx(1.5)
    assert record.value_si_cell == "max"
    assert record.parse_confidence is ParseConfidence.HIGH


def test_annotate_is_idempotent() -> None:
    record = _record(min="1350", max="1500", unit="mA")
    once = annotate_record(record).model_dump()
    twice = annotate_record(record).model_dump()
    assert once == twice


def test_parse_record_cells_reports_the_cells_that_failed() -> None:
    parsed = parse_record_cells(_record(typ="See Figure 7", max="1500", unit="mA"))
    assert set(parsed) == {"typ", "max"}
    assert parsed["typ"] is None
    assert parsed["max"] is not None


# --- the unparsed-population helper ----------------------------------------


def test_coverage_counts_and_lists_what_could_not_be_parsed() -> None:
    records = [
        _record(typ="1350", unit="mA", row_index=0, symbol="IDD"),
        _record(typ="1.8", unit="V", row_index=1, symbol="VDD"),
        _record(typ="See Figure 7", unit="dB", row_index=2, symbol="GAIN", page=42),
        _record(row_index=3, symbol="BLANK"),  # printed nothing at all
    ]
    result = coverage(records)
    assert (result.considered, result.parsed, result.blank) == (3, 2, 1)
    assert result.unparsed_count == 1
    assert result.rate == pytest.approx(2 / 3)

    (missing,) = result.unparsed
    assert missing.verbatim == "See Figure 7"
    assert missing.symbol == "GAIN"
    assert missing.page == 42
    assert missing.record_id == records[2].id  # citable back to the record

    described = result.describe()
    assert "1 of 3 rows could not be parsed" in described
    assert "See Figure 7" in described
    assert "p.42" in described


def test_coverage_never_reports_an_empty_population_as_success() -> None:
    result = coverage([_record(typ="1350", unit="mA")])
    assert result.unparsed == ()
    assert result.describe() == "all 1 rows parsed"
    assert coverage([]).describe() == "no rows printed a value to parse"


def test_coverage_per_cell_counts_every_printed_cell() -> None:
    records = [_record(min="1350", typ="See Figure 7", max="1500", unit="mA")]
    per_cell = coverage(records, primary_only=False)
    assert (per_cell.considered, per_cell.parsed, per_cell.unparsed_count) == (3, 2, 1)

    per_record = coverage(records)
    assert (per_record.considered, per_record.parsed) == (1, 1)


def test_coverage_describe_truncates_but_says_how_many_it_hid() -> None:
    records = [
        _record(typ=f"See Figure {index}", unit="dB", row_index=index) for index in range(25)
    ]
    described = coverage(records).describe(limit=5)
    assert "25 of 25 rows could not be parsed" in described
    assert "... and 20 more" in described
