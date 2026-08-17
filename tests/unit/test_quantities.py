"""The numeric layer (phase 6, ticket 02) — every shape, and every refusal.

Three things are asserted here, and only the first is about arithmetic:

- the grammar reads each shape a datasheet prints, and **refuses** everything
  else — `Note 2` contains a digit and must still parse to nothing;
- the layer never touches a verbatim string, checked by snapshotting every
  printed cell of a real recorded table before and after it runs;
- a consumer that sorts or compares gets a population report it cannot ignore,
  because silently dropping an unparseable row from a decision is the defect
  invariant 8 names.

Unicode is written as escapes where the glyph is the point of the test: the
minus sign (U+2212), the ellipsis (U+2026) and the two ohm glyphs (U+2126,
U+03A9) are all indistinguishable from their neighbours in a diff.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from datasheet_analyzer.models import (
    ParseConfidence,
    RawDocument,
    SourceDocument,
    SpecRecord,
    SpecUnit,
    ValueKind,
)
from datasheet_analyzer.structure.quantities import (
    SI_UNITS,
    VALUE_ROLES,
    Quantity,
    annotate_record,
    annotate_records,
    parse_population,
    parse_quantity,
    parse_rate,
    record_quantities,
    record_quantity,
)
from datasheet_analyzer.structure.specs import build_specset, table_to_records
from datasheet_analyzer.structure.units import CANONICAL_UNITS

MINUS = "−"  # U+2212 MINUS SIGN, as TI prints a negative limit
ELLIPSIS = "…"  # U+2026 HORIZONTAL ELLIPSIS, as a range separator
OHM_SIGN = "Ω"  # U+2126 OHM SIGN (TI)
GREEK_OMEGA = "Ω"  # U+03A9 GREEK CAPITAL LETTER OMEGA (ADI)
MICRO = "µ"  # U+00B5 MICRO SIGN, the lexicon's key
GREEK_MU = "μ"  # U+03BC GREEK SMALL LETTER MU, the same unit

DOC_HASH = "a" * 64


def _record(**cells) -> SpecRecord:
    """A spec record with only the cells a test cares about."""
    unit = cells.pop("unit", "")
    return SpecRecord(unit=SpecUnit(verbatim=unit, canonical=unit), **cells)


class TestShapesTable:
    """One case per row of the plan's shapes table."""

    def test_plain(self):
        q = parse_quantity("105")
        assert q is not None
        assert q.kind is ValueKind.POINT
        assert q.value_si == 105.0
        assert q.confidence is ParseConfidence.EXACT

    @pytest.mark.parametrize(
        ("text", "expected"), [(f"{MINUS}40", -40.0), ("+85", 85.0), ("-40", -40.0)]
    )
    def test_signed_and_unicode_minus(self, text, expected):
        q = parse_quantity(text)
        assert q is not None and q.kind is ValueKind.POINT
        assert q.value_si == expected

    @pytest.mark.parametrize(
        ("text", "low", "high"),
        [
            (f"{MINUS}40 to +85", -40.0, 85.0),
            (f"-40{ELLIPSIS}125", -40.0, 125.0),
            ("-40...125", -40.0, 125.0),
            (f"{MINUS}40 {MINUS} +85", -40.0, 85.0),  # dash separator, spaced
        ],
    )
    def test_range(self, text, low, high):
        q = parse_quantity(text)
        assert q is not None and q.kind is ValueKind.RANGE
        assert (q.low_si, q.high_si) == (low, high)
        # a range states an interval, not a number: value_si stays null rather
        # than quietly becoming one of the endpoints
        assert q.value_si is None
        assert q.span == (low, high)

    @pytest.mark.parametrize(
        ("text", "operator", "low", "high"),
        [
            ("< 5", "<", None, 5.0),
            ("<= 5", "<=", None, 5.0),
            ("≤ 5", "<=", None, 5.0),
            ("≥ 1.8", ">=", 1.8, None),
            ("> 1.8", ">", 1.8, None),
        ],
    )
    def test_inequality(self, text, operator, low, high):
        q = parse_quantity(text)
        assert q is not None and q.kind is ValueKind.BOUND
        assert q.operator == operator
        assert (q.low_si, q.high_si) == (low, high)
        assert q.value_si is None

    def test_tolerance(self):
        q = parse_quantity("±0.5")
        assert q is not None and q.kind is ValueKind.TOLERANCE
        assert q.value_si == 0.5
        # a spread has no interval without a nominal this cell never printed
        assert (q.low_si, q.high_si) == (None, None)
        assert q.span == (None, None)

    @pytest.mark.parametrize(
        ("text", "value", "unit"),
        [
            ("1350 mA", 1.35, "A"),
            ("1350mA", 1.35, "A"),
            ("12 GSPS", 12e9, "SPS"),
            ("1.8 V", 1.8, "V"),
            (f"10 {MICRO}A", 1e-5, "A"),
            (f"10 {GREEK_MU}A", 1e-5, "A"),  # the same unit, a different glyph
        ],
    )
    def test_si_prefix_scales(self, text, value, unit):
        q = parse_quantity(text)
        assert q is not None and q.kind is ValueKind.POINT
        assert q.unit_si == unit
        assert q.value_si == pytest.approx(value)

    def test_scientific(self):
        q = parse_quantity("1.2e-9")
        assert q is not None and q.kind is ValueKind.POINT
        assert q.value_si == pytest.approx(1.2e-9)

    def test_scientific_with_unit_hint(self):
        q = parse_quantity("1.2E-9", "s")
        assert q is not None and q.unit_si == "s"
        assert q.value_si == pytest.approx(1.2e-9)


class TestUnparseableIsFirstClass:
    """`None` is the outcome, not a failure to fix."""

    @pytest.mark.parametrize(
        "text",
        [
            "See Figure 7",
            "Note 2",  # holds a digit and still means nothing numerically
            "—",  # em dash: the printed "no value"
            "-",
            "",
            "   ",
            "TBD",
            "1350 mA typ",  # a trailing word the grammar will not swallow
            "-40-85",  # ambiguous with a negative number: refused, not guessed
            "5 apples",  # a unit with no scale is a unit we cannot state
        ],
    )
    def test_returns_none(self, text):
        assert parse_quantity(text) is None

    @pytest.mark.parametrize("text", ["See Figure 7", "Note 2", "—", ""])
    def test_record_records_parse_confidence_none(self, text):
        record = annotate_record(_record(typ=text, unit="V"))
        assert record.parse_confidence is ParseConfidence.NONE
        assert record.value_si is None
        assert record.value_low_si is None and record.value_high_si is None
        assert record.value_kind is None
        assert record.unit_si == ""

    def test_a_unit_we_cannot_scale_is_refused_not_passed_through(self):
        """Dropping a factor of 1000 silently is the ADR-0005 failure mode."""
        assert parse_quantity("50", "furlongs") is None
        assert parse_quantity("50 dBmV") is None


class TestUnitCanonicalization:
    """The unit lexicon is `structure/units.py`; this layer only scales it."""

    @pytest.mark.parametrize("glyph", [OHM_SIGN, GREEK_OMEGA, "ohm"])
    def test_both_ohm_glyphs_reach_the_same_si_unit(self, glyph):
        from_cell = parse_quantity(f"50 {glyph}")
        from_hint = parse_quantity("50", glyph)
        assert from_cell is not None and from_hint is not None
        assert from_cell.unit_si == from_hint.unit_si == "ohm"
        assert from_cell.value_si == from_hint.value_si == 50.0

    def test_every_canonical_unit_has_a_scale(self):
        """A unit added to the lexicon without a scale would silently unparse
        every row that prints it — so adding one must fail here first."""
        missing = sorted(set(CANONICAL_UNITS.values()) - set(SI_UNITS))
        assert not missing, f"units.py canonical units with no SI scale: {missing}"

    def test_the_cells_own_unit_beats_the_row_unit_column(self):
        q = parse_quantity("1350 mA", "V")
        assert q is not None and q.unit_si == "A" and q.value_si == 1.35

    def test_an_empty_unit_is_a_unit(self):
        q = parse_quantity("8")
        assert q is not None and q.unit_si == "" and q.value_si == 8.0

    def test_a_footnote_marker_on_the_unit_column_is_stripped_too(self):
        """AFE7950 prints `Vppdiff(3)` as a unit; the marker is provenance."""
        q = parse_quantity("1.4", "Vppdiff(3)")
        assert q is not None and q.unit_si == "Vppdiff" and q.value_si == 1.4

    @pytest.mark.parametrize("unit", ["dBc", "dBFS/Hz", "%"])
    def test_the_ratio_units_the_corpora_actually_print_scale(self, unit):
        q = parse_quantity("-60", unit)
        assert q is not None and q.unit_si == unit and q.value_si == -60.0

    def test_a_trailing_footnote_marker_is_provenance_not_value(self):
        q = parse_quantity("1350(2) mA")
        assert q is None  # a marker mid-cell is not the documented shape
        q = parse_quantity("1350 mA(2)(3)")
        assert q is not None and q.value_si == 1.35
        assert q.verbatim == "1350 mA(2)(3)"  # quoted back exactly as printed


class TestRecordSelector:
    """Which of a row's cells becomes the record's representative quantity."""

    def test_value_wins(self):
        q = record_quantity(_record(value="2000", typ="1", max="2", min="3", unit="V"))
        assert q is not None and q.value_si == 2000.0

    def test_typ_beats_the_limits(self):
        q = record_quantity(_record(typ="1.8", max="1.9", min="1.7", unit="V"))
        assert q is not None and q.value_si == 1.8

    def test_max_beats_min(self):
        q = record_quantity(_record(max="1.9", min="1.7", unit="V"))
        assert q is not None and q.value_si == 1.9

    def test_min_only(self):
        q = record_quantity(_record(min="1.7", unit="V"))
        assert q is not None and q.value_si == 1.7

    def test_min_and_max_are_never_joined_into_a_printed_range(self):
        """Joining two cells would put a verbatim string on the record that the
        datasheet never printed — the interval comes from both cells instead."""
        record = _record(min=f"{MINUS}40", max="+85", unit="°C")
        representative = record_quantity(record)
        assert representative is not None
        assert representative.kind is ValueKind.POINT  # the max cell, on its own
        assert representative.verbatim == "+85"
        cells = record_quantities(record)
        assert cells["min"].value_si == -40.0 and cells["max"].value_si == 85.0

    def test_a_row_with_no_readable_cell_has_no_quantity(self):
        assert record_quantity(_record(name="ANALOG SUPPLY VOLTAGE RANGE")) is None

    def test_every_value_role_is_offered(self):
        cells = record_quantities(_record(min="1", typ="2", max="3", value="4"))
        assert set(cells) == set(VALUE_ROLES)
        assert all(q is not None for q in cells.values())


class TestVerbatimIsNeverMutated:
    """The additive promise, checked field by field."""

    VERBATIM_FIELDS = (
        "symbol", "name", "conditions", "table_conditions",
        "min", "typ", "max", "value",
    )

    def _snapshot(self, record: SpecRecord) -> tuple:
        return (
            tuple(getattr(record, f) for f in self.VERBATIM_FIELDS),
            record.unit.verbatim,
            record.unit.canonical,
            tuple(record.row_verbatim),
        )

    def test_annotating_one_record_changes_only_the_numeric_fields(self):
        record = _record(
            symbol="IDD1P8", name="1.8V supply current",
            min=f"{MINUS}40", typ="1200", max="1350", unit="mA",
        )
        record.row_verbatim = ["IDD1P8", "1350", "mA"]
        before = self._snapshot(record)
        annotate_record(record)
        assert self._snapshot(record) == before
        assert record.value_si == 1.2  # ...and the layer did do its job

    def test_annotating_is_idempotent(self):
        record = _record(typ="1350", unit="mA")
        annotate_record(record)
        first = record.model_dump()
        annotate_record(record)
        assert record.model_dump() == first

    def test_a_real_tables_printed_cells_survive_the_published_path(
        self, ti_sec_4_5_html
    ):
        """Every printed cell of a recorded TI table, before the layer and
        after the pipeline's own published records."""
        unannotated = [
            record
            for section in _raw_from(ti_sec_4_5_html).sections
            for index, table in enumerate(section.tables)
            for record in table_to_records(section, table, index)[0]
        ]
        published = build_specset(_raw_from(ti_sec_4_5_html), "AFE7950").records
        assert unannotated, "the recorded fixture produced no records"
        assert len(published) == len(unannotated)
        assert [self._snapshot(r) for r in published] == [
            self._snapshot(r) for r in unannotated
        ]

    def test_published_records_carry_the_numeric_layer(self, ti_sec_4_5_html):
        specset = build_specset(_raw_from(ti_sec_4_5_html), "AFE7950")
        parsed = [r for r in specset.records if r.parse_confidence is ParseConfidence.EXACT]
        assert parsed, "a real characteristics table must parse something"
        assert all(r.value_kind is not None for r in parsed)
        # ...and it survives the on-disk round trip
        from datasheet_analyzer.models import SpecSet

        again = SpecSet.model_validate_json(specset.model_dump_json())
        assert [r.value_si for r in again.records] == [r.value_si for r in specset.records]
        assert [r.value_kind for r in again.records] == [
            r.value_kind for r in specset.records
        ]


class TestParsePopulation:
    """The helper a sorting or comparing consumer must call (invariant 8)."""

    RECORDS = (
        ("VDD", "1.8", ""),
        ("TJ", "105", ""),
        ("PSRR", "See Figure 7", ""),
    )

    def _records(self) -> list[SpecRecord]:
        return [
            _record(symbol=symbol, max=value, unit="V", page=21 if not note else None)
            for symbol, value, note in self.RECORDS
        ]

    def test_reports_both_populations_and_drops_nothing(self):
        population = parse_population(self._records(), role="max")
        assert population.total == 3
        assert population.n_parsed == 2 and population.n_unparsed == 1
        assert [r.symbol for r in population.unparsed] == ["PSRR"]
        assert [r.symbol for r, _ in population.parsed] == ["VDD", "TJ"]

    def test_describe_is_the_sentence_the_adr_asks_for(self):
        assert parse_population(self._records(), role="max").describe() == (
            "1 of 3 rows could not be parsed"
        )
        assert parse_population(self._records()[:2]).describe() == "all 2 rows parsed"
        assert parse_population([]).describe() == "0 rows to compare"

    def test_listing_names_each_excluded_row_with_what_it_printed(self):
        lines = parse_population(self._records(), role="max").listing()
        assert lines == ["PSRR: See Figure 7 (p.21)"]

    def test_default_role_uses_the_representative_quantity(self):
        population = parse_population(self._records())
        assert population.role == ""
        assert population.n_unparsed == 1

    def test_an_unknown_role_is_refused(self):
        with pytest.raises(ValueError):
            parse_population(self._records(), role="conditions")


class TestParseRate:
    """The measurement, broken down by section, for the phase report."""

    def _records(self) -> list[SpecRecord]:
        return [
            _record(section="4.3", max="1.8", unit="V"),
            _record(section="4.3", max="105", unit="°C"),
            _record(section="4.9", max="See Figure 7", unit="dB"),
            _record(section="4.9", max="—"),
        ]

    def test_counts_by_section_and_overall(self):
        rate = parse_rate(self._records())
        assert rate.n_records == 4 and rate.n_parsed == 2
        assert rate.rate == 0.5
        assert rate.by_section == {"4.3": (2, 2), "4.9": (0, 2)}

    def test_empty_set_is_zero_not_a_division_error(self):
        rate = parse_rate([])
        assert rate.n_records == 0 and rate.rate == 0.0

    def test_renders_a_markdown_table_per_section(self):
        table = parse_rate(self._records()).as_table(title="TEST")
        assert "### TEST" in table
        assert "| 4.3 | 2 | 2 | 100% |" in table
        assert "| 4.9 | 2 | 0 | 0% |" in table
        assert "| **all** | **4** | **2** | **50%** |" in table

    def test_measures_records_that_were_never_annotated(self):
        """A corpus published before the layer existed must measure the same as
        a fresh one — the rate re-parses instead of reading stored fields."""
        stale = self._records()
        for record in stale:
            record.value_si = None
            record.parse_confidence = ParseConfidence.NONE
        assert parse_rate(stale).n_parsed == 2

    def test_annotate_records_returns_the_same_objects(self):
        records = self._records()
        assert annotate_records(records) == records
        assert records[0].value_si == 1.8


class TestQuantityIsAValueObject:
    def test_frozen_so_a_consumer_cannot_edit_a_parsed_value(self):
        q = parse_quantity("105", "°C")
        assert isinstance(q, Quantity)
        with pytest.raises(FrozenInstanceError):
            q.value_si = 106.0  # type: ignore[misc]


def _raw_from(html: str) -> RawDocument:
    """Section 4.5 of the recorded AFE7950 page, as a one-section document."""
    from datasheet_analyzer.extract.ti_html import parse_section

    sec = parse_section(
        html,
        "https://www.ti.com/document-viewer/AFE7950/datasheet/GUID-X#GUID-Y",
        number="4.5",
        title="Transmitter Electrical Characteristics",
    )
    sec.page_start, sec.page_end = 7, 13
    return RawDocument(
        source=SourceDocument(content_hash=DOC_HASH, path="afe7950.pdf"),
        sections=[sec],
        extractor="ti_html",
    )
