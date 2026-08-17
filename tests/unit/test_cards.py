"""Design cards (phase 6, ticket 07): selection, derivation, honesty, render.

The rules under test are ADR 0005's, applied to the first artifact that is a
*view* rather than an extraction:

- every published value carries a resolvable `source`, its printed page and the
  named rule that produced it;
- a computed value (a margin, a pin count, a reduction over rows) has no
  `verbatim`, because no page printed it;
- an empty card is a valid card and says what it looked for;
- anything the card compared reports its unparsed population, and anything it
  could not compare is listed rather than dropped;
- an ambiguous join is refused, never resolved.

The real corpora exercise the same code in
`tests/integration/test_afe7950_build.py` and `test_phase4_layout_gate.py`;
this module is where each rule is pinned in isolation, including the ones no
reference part happens to print (a zero margin, a recommended limit above an
absolute maximum).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.cards import (
    DERIVATION_CELL,
    DERIVATION_CELL_SI,
    DERIVATION_MARGIN,
    DERIVATION_PIN_COUNT,
    DERIVATION_REDUCE_MAX,
    FLAG_OVER_ABS_MAX,
    FLAG_ZERO_MARGIN,
    ROLE_ABS_MAX,
    ROLE_MARGIN,
    ROLE_RECOMMENDED_MAX,
    CardDoc,
    CardLexicon,
    build_card,
    build_cards,
    load_card_lexicon,
    render_card,
)
from datasheet_analyzer.cards.render import BANNER_PREFIX
from datasheet_analyzer.config import CARD_VERSION, CARDS_SCHEMA_VERSION, Settings
from datasheet_analyzer.models import (
    Confidence,
    CorpusManifest,
    DesignCard,
    PinRecord,
    PinType,
    SectionFile,
    SpecRecord,
    SpecSet,
)
from datasheet_analyzer.publish import CARDS_DIRNAME, cards_current, write_cards
from datasheet_analyzer.retrieve import Retriever
from datasheet_analyzer.structure.units import canonical_unit

ABS_MAX = "Absolute Maximum Ratings"
RECOMMENDED = "Recommended Operating Conditions"

DOC = "datasheet-a1b2c3d4"


def rec(
    ordinal: int,
    *,
    symbol: str = "",
    name: str = "",
    section_title: str = RECOMMENDED,
    section: str = "4.3",
    unit: str = "V",
    page: int = 6,
    conditions: str = "",
    confidence: Confidence = Confidence.HIGH,
    **cells: str,
) -> SpecRecord:
    """One published spec record, as `structure/specs.py` would have written it."""
    return SpecRecord(
        id=f"rec_{ordinal}",
        section=section,
        section_title=section_title,
        symbol=symbol,
        name=name,
        conditions=conditions,
        unit=canonical_unit(unit),
        page=page,
        confidence=confidence,
        **cells,
    )


def pin(ordinal: int, *, pin: str, name: str, type: PinType, page: int = 22) -> PinRecord:
    return PinRecord(
        id=f"pin_{ordinal}",
        pin=pin,
        name=name,
        type=type,
        section="",
        page=page,
        confidence=Confidence.HIGH,
    )


def doc(*, specs=(), pins=()) -> CardDoc:
    return CardDoc(name=DOC, specs=tuple(specs), pins=tuple(pins))


def card_of(name: str, *docs: CardDoc, part: str = "TEST") -> DesignCard:
    return build_card(name, part, list(docs))


class TestTheShippedLexicon:
    """`registry/cards.yaml` is data, and the four cards are what it declares."""

    def test_declares_the_four_cards_of_the_ticket(self):
        assert load_card_lexicon().names == ("power", "thermal", "interface", "limits")

    def test_every_group_can_claim_something(self):
        """A group with no predicate would claim every row it is pointed at."""
        for spec in load_card_lexicon().cards:
            for group in spec.groups:
                assert group.has_row_predicate or group.pin_types, f"{spec.name}/{group.id}"

    def test_only_limits_declares_a_join(self):
        by_name = {c.name: c for c in load_card_lexicon().cards}
        assert by_name["limits"].join is not None
        assert by_name["limits"].join.role == "max"
        assert all(by_name[n].join is None for n in ("power", "thermal", "interface"))

    def test_a_malformed_entry_is_skipped_not_fatal(self, caplog):
        """One bad card must never take the other three down with it."""
        lexicon = CardLexicon.from_mapping(
            {
                "broken": "not a mapping",
                "empty": {"groups": []},
                "ok": {"groups": [{"id": "g", "symbol_contains": ["vdd"]}]},
            }
        )
        assert lexicon.names == ("ok",)

    def test_an_unknown_reduce_or_kind_or_pin_type_degrades(self):
        lexicon = CardLexicon.from_mapping(
            {
                "c": {
                    "groups": [
                        {"id": "a", "symbol_contains": ["vdd"], "reduce": "average"},
                        {"id": "b", "kind": "registers", "symbol_contains": ["x"]},
                        {"id": "c", "kind": "pins", "pin_types": ["supply"]},
                    ]
                }
            }
        )
        groups = lexicon.card("c").groups
        # the unknown reduce is dropped and the group kept; the unknown kind and
        # the unknown pin type leave their groups unusable, so they are skipped
        assert [g.id for g in groups] == ["a"]
        assert groups[0].reduce == ""

    def test_an_unreadable_lexicon_publishes_no_cards(self, tmp_path):
        assert CardLexicon.read(tmp_path / "nope.yaml").cards == ()

    def test_a_new_rail_naming_convention_is_a_data_change(self, tmp_path):
        """The ticket's last criterion, proved through a lexicon *file*.

        A vendor that calls its rail `VBAT` is served by an edit to
        `registry/cards.yaml` and by nothing else: no Python change, no looser
        match. The shipped lexicon does not know that word, and the same records
        land on the card the moment a file says it does.
        """
        record = rec(1, symbol="VBAT1", typ="3.6", unit="V")
        assert card_of("power", doc(specs=[record])).rows == []

        path = tmp_path / "cards.yaml"
        path.write_text(
            "power:\n"
            "  title: Power\n"
            "  groups:\n"
            "    - id: rails\n"
            "      title: Supply rails\n"
            "      roles: [min, typ, max]\n"
            "      section_titles: [recommended operating conditions]\n"
            "      unit_bases: [V]\n"
            "      symbol_contains: [vbat]\n",
            encoding="utf-8",
        )
        card = build_card(
            "power", "TEST", [doc(specs=[record])], lexicon=load_card_lexicon(path)
        )
        assert [r.label for r in card.rows] == ["VBAT1"]
        assert card.rows[0].selector == "rails+symbol_contains:vbat"


class TestSelection:
    """Which printed rows land on a card, and which deliberately do not."""

    def test_a_rail_row_is_claimed_and_carries_its_selector(self):
        card = card_of("power", doc(specs=[rec(1, symbol="AVDD1", min="0.95", typ="1.0",
                                              max="1.05")]))
        assert [r.label for r in card.rows] == ["AVDD1"]
        assert card.rows[0].selector.startswith("rails+")
        assert card.rows[0].group == "Supply rails"

    def test_a_row_on_the_wrong_table_is_not_a_rail(self):
        """`section_titles` says *which table*: an abs-max rating is not a rail."""
        card = card_of(
            "power",
            doc(specs=[rec(1, symbol="AVDD1", section_title=ABS_MAX, max="2.1")]),
        )
        assert card.rows == []
        assert "no power card" in card.empty_reason

    def test_a_row_with_no_section_title_never_satisfies_a_title_restriction(self):
        """A corpus published before `section_title` existed: unknown is not right."""
        card = card_of("power", doc(specs=[rec(1, symbol="AVDD1", section_title="",
                                              max="1.05")]))
        assert card.rows == []

    def test_the_unit_separates_a_rail_from_its_own_current(self):
        """AD9081 prints both on two tables of one section, both named `AVDD2`."""
        card = card_of(
            "power",
            doc(
                specs=[
                    rec(1, symbol="AVDD2", typ="2.0", unit="V"),
                    rec(2, symbol="AVDD2 (IAVDD2)", typ="205", unit="mA"),
                ]
            ),
        )
        assert [(r.group, r.label) for r in card.rows] == [
            ("Supply rails", "AVDD2"),
            ("Supply current", "AVDD2 (IAVDD2)"),
        ]

    def test_one_printed_symbol_two_quantities_is_split_by_unit(self):
        """AFE7950's `TJ` is a junction temperature *and* a total jitter."""
        card = card_of(
            "thermal",
            doc(
                specs=[
                    rec(1, symbol="TJ", name="Junction temperature", unit="°C",
                        section_title=ABS_MAX, max="150"),
                    rec(2, symbol="TJ", name="Total Jitter Tolerance", unit="UI",
                        section_title="Digital Electrical Characteristics", max="0.42"),
                ]
            ),
        )
        assert [r.values["max"].verbatim for r in card.rows] == ["150 °C"]

    def test_a_spanning_heading_row_is_not_a_parameter(self):
        """TI flattens a `<th colspan>` into a row that repeats itself."""
        heading = rec(1, symbol="CMOS I/O: SPICLK, SPISDIO", min="CMOS I/O: SPICLK, SPISDIO",
                      typ="CMOS I/O: SPICLK, SPISDIO", max="CMOS I/O: SPICLK, SPISDIO",
                      unit="", section_title="Digital Electrical Characteristics")
        real = rec(2, symbol="t(SCLK)", name="Minimum SCLK period", typ="25", unit="ns",
                   section_title="Timing Requirements")
        card = card_of("interface", doc(specs=[heading, real]))
        assert [r.label for r in card.rows] == ["t(SCLK)"]

    def test_a_row_printing_nothing_in_the_group_roles_is_not_a_row(self):
        card = card_of("power", doc(specs=[rec(1, symbol="AVDD1")]))
        assert card.rows == []

    def test_a_record_with_no_id_is_listed_rather_than_published(self):
        """An uncited value has no business on a card — but it is not silent."""
        record = rec(1, symbol="AVDD1", typ="1.0")
        record.id = ""
        card = card_of("power", doc(specs=[record]))
        assert card.rows == []
        assert any("no addressable record id" in line for line in card.unparsed)


class TestDerivedValues:
    """Every value ships in ADR 0005's envelope, or it does not ship."""

    def test_a_copied_cell_carries_verbatim_si_source_page_and_rule(self):
        card = card_of("power", doc(specs=[rec(7, symbol="AVDD1 (IAVDD1)", typ="1350",
                                              unit="mA", page=21)]))
        value = card.rows[0].values["typ"]
        assert value.verbatim == "1350 mA"  # the printed cell *and* its printed unit
        assert (value.value_si, value.unit_si) == (pytest.approx(1.35), "A")
        assert value.source == f"docs/{DOC}/specs.json#rec_7"
        assert value.page == 21
        assert value.derivation == DERIVATION_CELL_SI
        assert value.confidence is Confidence.HIGH

    def test_an_unparseable_cell_stays_verbatim_with_no_number(self):
        card = card_of(
            "power",
            doc(specs=[rec(1, symbol="AVDD1", typ="See Figure 7", unit="V")]),
        )
        value = card.rows[0].values["typ"]
        assert value.verbatim == "See Figure 7 V"
        assert value.value_si is None and value.unit_si == ""
        assert value.derivation == DERIVATION_CELL

    def test_a_computed_value_has_no_verbatim(self):
        """No page printed a margin, so no page is quoted for one."""
        card = card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol="TJ", section_title=ABS_MAX, section="4.1", page=4,
                        unit="°C", max="150"),
                    rec(2, symbol="TJ", section_title=RECOMMENDED, unit="°C", max="110"),
                ]
            ),
        )
        margin = card.rows[0].values[ROLE_MARGIN]
        assert margin.verbatim == ""
        assert margin.value_si == pytest.approx(40.0)
        assert margin.unit_si == "°C"
        assert margin.derivation == DERIVATION_MARGIN

    def test_a_computed_value_cites_both_of_its_operands(self):
        card = card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol="TJ", section_title=ABS_MAX, section="4.1", page=4,
                        unit="°C", max="150"),
                    rec(2, symbol="TJ", section_title=RECOMMENDED, unit="°C", max="110"),
                ]
            ),
        )
        margin = card.rows[0].values[ROLE_MARGIN]
        assert margin.refs == [
            f"docs/{DOC}/specs.json#rec_2",
            f"docs/{DOC}/specs.json#rec_1",
        ]
        assert margin.page == 6  # the recommended limit's page; the rating's is rec_1's

    def test_the_weaker_grade_wins_on_a_computed_value(self):
        card = card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol="TJ", section_title=ABS_MAX, unit="°C", max="150",
                        confidence=Confidence.LOW),
                    rec(2, symbol="TJ", section_title=RECOMMENDED, unit="°C", max="110",
                        confidence=Confidence.HIGH),
                ]
            ),
        )
        assert card.rows[0].values[ROLE_MARGIN].confidence is Confidence.LOW


class TestReduction:
    """`reduce: max` — one row per parameter, and it says what it was largest of."""

    def _currents(self):
        return doc(
            specs=[
                rec(1, symbol="IVDD1P8", name="Group 3A", typ="948.2", unit="mA",
                    conditions="Mode 1"),
                rec(2, symbol="IVDD1P8", name="Group 3A", typ="1668.6", unit="mA",
                    conditions="Mode 3"),
                rec(3, symbol="IVDD1P8", name="Group 3B", typ="533.7", unit="mA",
                    conditions="Mode 1"),
            ]
        )

    def test_one_row_per_parameter_with_the_largest_printed_value(self):
        card = card_of("power", self._currents())
        assert [(r.label, r.values["typ"].verbatim) for r in card.rows] == [
            ("IVDD1P8", "1668.6 mA"),
            ("IVDD1P8", "533.7 mA"),
        ]
        assert card.rows[0].selector.endswith(DERIVATION_REDUCE_MAX)
        assert "largest of 2 printed values" in card.rows[0].note
        assert card.rows[1].note == ""  # one printed value: nothing was chosen

    def test_the_comparison_reports_its_population(self):
        card = card_of("power", self._currents())
        assert any("2 parameters from 3 printed rows" in note for note in card.notes)
        assert any("all 3 rows parsed" in note for note in card.notes)

    def test_an_unparsed_row_is_listed_never_dropped(self):
        card = card_of(
            "power",
            doc(
                specs=[
                    rec(1, symbol="IVDD1P8", name="Group 3A", typ="948.2", unit="mA"),
                    rec(2, symbol="IVDD1P8", name="Group 3A", typ="See Figure 7",
                        unit="mA"),
                ]
            ),
        )
        assert any("1 of 2 rows could not be parsed" in note for note in card.notes)
        assert any("See Figure 7" in line for line in card.unparsed)

    def test_a_parameter_whose_rows_all_fail_to_parse_is_still_published(self):
        """"No comparable value" is a reason to show it unranked, not to drop it."""
        card = card_of(
            "power",
            doc(
                specs=[
                    rec(1, symbol="IVDD1P8", name="Group 3A", typ="See Figure 7",
                        unit="mA"),
                    rec(2, symbol="IVDD1P8", name="Group 3A", typ="Note 2", unit="mA"),
                ]
            ),
        )
        assert [r.values["typ"].verbatim for r in card.rows] == ["See Figure 7 mA"]
        assert "could be parsed" in card.rows[0].note


class TestPinGroups:
    """A pin group counts records and cites every one of them."""

    def _pins(self):
        return doc(
            pins=[
                pin(1, pin="A2", name="AVDD2", type=PinType.POWER),
                pin(2, pin="E2", name="AVDD2", type=PinType.POWER),
                pin(3, pin="A1", name="GND", type=PinType.GROUND),
                pin(4, pin="B4", name="SERDIN0", type=PinType.DIGITAL),
            ]
        )

    def test_one_row_per_pin_name_with_a_counted_derived_value(self):
        card = card_of("power", self._pins())
        rows = [r for r in card.rows if r.group == "Supply and ground pins"]
        assert [(r.label, r.detail, r.values["pins"].value_si) for r in rows] == [
            ("AVDD2", "power", 2.0),
            ("GND", "ground", 1.0),
        ]
        assert rows[0].values["pins"].derivation == DERIVATION_PIN_COUNT
        assert rows[0].values["pins"].verbatim == ""  # nothing printed a count

    def test_the_count_cites_every_record_it_counted(self):
        card = card_of("power", self._pins())
        value = card.rows[0].values["pins"]
        assert value.refs == [
            f"docs/{DOC}/pins.json#pin_1",
            f"docs/{DOC}/pins.json#pin_2",
        ]

    def test_the_designators_are_named_on_the_row(self):
        card = card_of("power", self._pins())
        assert card.rows[0].note == "designators: A2, E2"

    def test_a_long_pin_group_points_at_the_pin_table(self):
        many = doc(pins=[pin(i, pin=f"A{i}", name="GND", type=PinType.GROUND)
                         for i in range(1, 21)])
        card = card_of("power", many)
        assert card.rows[0].values["pins"].value_si == 20.0
        assert "+12 more in pins.json" in card.rows[0].note


class TestLimits:
    """The card that earns its keep: margins, refusals and the zero-margin flag."""

    def _pair(self, *, abs_max: str, recommended: str, unit: str = "V",
              symbol: str = "VIN") -> DesignCard:
        return card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol=symbol, section_title=ABS_MAX, section="4.1", page=4,
                        unit=unit, max=abs_max),
                    rec(2, symbol=symbol, section_title=RECOMMENDED, unit=unit,
                        max=recommended),
                ]
            ),
        )

    def test_a_margin_is_computed_where_both_sides_parsed(self):
        card = self._pair(abs_max="2.1", recommended="1.85")
        assert card.rows[0].values[ROLE_MARGIN].value_si == pytest.approx(0.25)
        assert set(card.rows[0].values) == {ROLE_ABS_MAX, ROLE_RECOMMENDED_MAX, ROLE_MARGIN}
        assert not card.rows[0].flags

    def test_a_margin_survives_a_unit_prefix_difference(self):
        card = self._pair(abs_max="2100", recommended="1.85", unit="mV")
        # both sides scale to volts before anything is subtracted
        assert card.rows[0].values[ROLE_MARGIN].unit_si == "V"

    def test_zero_margin_is_flagged(self):
        """The hazard the card exists for: no headroom at all."""
        card = self._pair(abs_max="1.85", recommended="1.85")
        row = card.rows[0]
        assert FLAG_ZERO_MARGIN in row.flags
        assert row.values[ROLE_MARGIN].value_si == pytest.approx(0.0)
        assert "no headroom" in row.note

    def test_zero_margin_is_flagged_across_a_unit_prefix(self):
        """1850 mV and 1.85 V are the same limit, and float scaling must not hide it."""
        card = card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol="VIN", section_title=ABS_MAX, unit="mV", max="1850"),
                    rec(2, symbol="VIN", section_title=RECOMMENDED, unit="V", max="1.85"),
                ]
            ),
        )
        assert FLAG_ZERO_MARGIN in card.rows[0].flags

    def test_a_recommended_limit_above_the_rating_is_flagged(self):
        card = self._pair(abs_max="1.8", recommended="1.85")
        assert FLAG_OVER_ABS_MAX in card.rows[0].flags
        assert card.rows[0].values[ROLE_MARGIN].value_si < 0

    def test_an_unparsed_side_publishes_both_values_and_no_margin(self):
        card = self._pair(abs_max="VDD1P8 + 0.3", recommended="1.85")
        row = card.rows[0]
        assert ROLE_MARGIN not in row.values
        assert row.values[ROLE_ABS_MAX].verbatim == "VDD1P8 + 0.3 V"
        assert any("could not be read as a number" in line for line in card.unparsed)

    def test_units_with_different_bases_are_never_subtracted(self):
        card = card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol="VIN", section_title=ABS_MAX, unit="V", max="2.1"),
                    rec(2, symbol="VIN", section_title=RECOMMENDED, unit="mA", max="1.85"),
                ]
            ),
        )
        assert ROLE_MARGIN not in card.rows[0].values
        assert any("different bases" in line for line in card.unparsed)

    def test_a_one_sided_parameter_is_listed_with_its_side(self):
        card = card_of(
            "limits",
            doc(specs=[rec(1, symbol="Tstg", section_title=ABS_MAX, unit="°C",
                           max="150")]),
        )
        assert card.rows == []
        assert any(
            "printed only on the absolute maximum table" in line for line in card.unparsed
        )

    def test_an_ambiguous_join_is_refused_with_the_counts(self):
        """Three ratings against three rails: pairing them would be a guess."""
        card = card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol="Supply Voltage Range", name="rail A",
                        section_title=ABS_MAX, unit="V", max="1.2"),
                    rec(2, symbol="Supply Voltage Range", name="rail B",
                        section_title=ABS_MAX, unit="V", max="2.1"),
                    rec(3, symbol="VDD1", name="Supply voltage 0.9V",
                        section_title=RECOMMENDED, unit="V", max="0.95"),
                    rec(4, symbol="VDD2", name="Supply voltage 1.8V",
                        section_title=RECOMMENDED, unit="V", max="1.85"),
                ]
            ),
        )
        assert card.rows == []
        assert any("ambiguous join" in line for line in card.unparsed)

    def test_rows_sharing_a_printed_identity_cell_are_paired(self):
        """TI's abs-max table names the rail in its *name* column, not its symbol."""
        card = card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol="Supply Voltage Range", name="DVDD0P9, VDDT0P9",
                        section_title=ABS_MAX, section="4.1", page=4, unit="V",
                        max="1.2"),
                    rec(2, symbol="Supply Voltage Range", name="VDD1P8, VDDA1P8",
                        section_title=ABS_MAX, section="4.1", page=4, unit="V",
                        max="2.1"),
                    rec(3, symbol="DVDD0P9, VDDT0P9", name="Supply voltage 0.9V",
                        section_title=RECOMMENDED, unit="V", max="0.95"),
                    rec(4, symbol="VDD1P8, VDDA1P8", name="Supply voltage 1.8V",
                        section_title=RECOMMENDED, unit="V", max="1.85"),
                ]
            ),
        )
        assert [r.values[ROLE_MARGIN].value_si for r in card.rows] == [
            pytest.approx(0.25),
            pytest.approx(0.25),
        ]
        assert all("DVDD0P9" in r.label or "VDD1P8" in r.label for r in card.rows)

    def test_a_cell_matching_two_rows_opposite_stays_ambiguous(self):
        """A shared name that does not identify one row proves nothing."""
        card = card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol="VDD1", name="rail", section_title=ABS_MAX,
                        unit="V", max="2.1"),
                    rec(2, symbol="VDD2", name="rail", section_title=ABS_MAX,
                        unit="V", max="1.2"),
                    rec(3, symbol="VDD3", name="rail", section_title=RECOMMENDED,
                        unit="V", max="1.85"),
                ]
            ),
        )
        assert card.rows == []
        assert any("ambiguous join" in line for line in card.unparsed)

    def test_the_population_of_both_tables_is_reported(self):
        card = self._pair(abs_max="VDD1P8 + 0.3", recommended="1.85")
        assert any(note.startswith("absolute maximum max:") for note in card.notes)
        assert any(note.startswith("recommended operating max:") for note in card.notes)
        assert any("parameter pairs have a computed margin" in note for note in card.notes)


class TestEmptyCards:
    """An empty card is a valid card (ADR 0005), and it says why."""

    def test_an_absent_interface_section_yields_an_honest_card(self):
        card = card_of("interface", doc(specs=[rec(1, symbol="AVDD1", typ="1.0")]))
        assert card.rows == []
        assert card.card == "interface"
        assert card.card_version == CARD_VERSION
        assert "none of this part's 1 spec records" in card.empty_reason
        assert "registry/cards.yaml" in card.empty_reason
        assert "jesd" in card.empty_reason  # what it looked for

    def test_a_corpus_with_no_records_says_nothing_was_searched(self):
        card = card_of("power", doc())
        assert "no spec or pin records at all" in card.empty_reason

    def test_a_card_with_rows_has_no_empty_reason(self):
        card = card_of("power", doc(specs=[rec(1, symbol="AVDD1", typ="1.0")]))
        assert card.empty_reason == ""

    def test_an_unknown_card_name_is_none_not_an_empty_card(self):
        """A typo must never read as a finding about the datasheet."""
        assert build_card("powr", "TEST", [doc()]) is None


class TestTheCardSet:
    """`build_cards` is what the publisher writes, and it is deterministic."""

    def test_every_declared_card_is_built_even_when_empty(self):
        cards = build_cards("TEST", [doc()])
        assert [c.card for c in cards] == list(load_card_lexicon().names)
        assert all(c.schema_version == CARDS_SCHEMA_VERSION for c in cards)
        assert all(c.empty_reason for c in cards)

    def test_the_card_version_is_stamped_from_the_caller(self):
        cards = build_cards("TEST", [doc()], card_version="99")
        assert {c.card_version for c in cards} == {"99"}

    def test_building_twice_produces_identical_json(self):
        """A derived artifact of identical input must be byte-identical."""
        docs = [doc(specs=[rec(1, symbol="AVDD1", typ="1.0"),
                           rec(2, symbol="IVDD1", typ="205", unit="mA")])]
        first = [c.model_dump_json(indent=2) for c in build_cards("TEST", docs)]
        second = [c.model_dump_json(indent=2) for c in build_cards("TEST", docs)]
        assert first == second

    def test_a_card_round_trips_through_json(self):
        card = card_of("power", doc(specs=[rec(1, symbol="AVDD1", typ="1.0")]))
        again = DesignCard.model_validate(json.loads(card.model_dump_json()))
        assert again == card


class TestRender:
    """The markdown a reader gets: banner, citations, and no invented value."""

    def _card(self) -> DesignCard:
        return card_of(
            "limits",
            doc(
                specs=[
                    rec(1, symbol="TJ", name="Junction temperature", section_title=ABS_MAX,
                        section="4.1", page=4, unit="°C", max="150"),
                    rec(2, symbol="TJ", name="Operating Junction Temperature",
                        section_title=RECOMMENDED, unit="°C", max="110"),
                ]
            ),
        )

    def test_the_banner_names_the_card_version(self):
        text = render_card(self._card())
        assert text.startswith(f"{BANNER_PREFIX} {CARD_VERSION} -->")

    def test_every_row_carries_a_citation(self):
        text = render_card(self._card())
        rows = [line for line in text.splitlines() if line.startswith("| TJ")]
        assert rows and all("p." in line for line in rows)
        assert "§4.1, p.4 / §4.3, p.6" in text

    def test_a_computed_value_is_marked_as_derived(self):
        assert "40 °C *(derived)*" in render_card(self._card())

    def test_an_absent_value_prints_a_dash_not_a_blank(self):
        """One rail prints a min and the other does not; the gap is explicit."""
        card = card_of(
            "power",
            doc(
                specs=[
                    rec(1, symbol="AVDD1", min="0.95", typ="1.0"),
                    rec(2, symbol="AVDD2", typ="2.0"),
                ]
            ),
        )
        line = next(ln for ln in render_card(card).splitlines() if ln.startswith("| AVDD2"))
        assert "| — |" in line

    def test_an_empty_card_renders_its_reason(self):
        text = render_card(card_of("interface", doc()))
        assert "**No rows.**" in text
        assert "no interface card" in text

    def test_a_pipe_in_printed_text_cannot_break_the_table(self):
        card = card_of(
            "power",
            doc(specs=[rec(1, symbol="VDD|A", name="rail", typ="1.0")]),
        )
        line = next(ln for ln in render_card(card).splitlines() if "VDD\\|A" in ln)
        # Parameter | Typ | Grade | Source — the printed pipe is escaped, so it
        # adds no cell to the row.
        assert line.count("|") - line.count("\\|") == 5

    def test_the_unparsed_listing_is_rendered(self):
        card = card_of(
            "limits",
            doc(specs=[rec(1, symbol="Tstg", section_title=ABS_MAX, unit="°C",
                           max="150")]),
        )
        text = render_card(card)
        assert "## Not on this card" in text
        assert "printed only on the absolute maximum table" in text


DOC_HASH = "a1b2c3d4" + "0" * 56


@pytest.fixture
def part(tmp_path) -> Path:
    """A minimal but structurally real built corpus, with no cards yet."""
    part_dir = tmp_path / "parts" / "TEST"
    doc_dir = part_dir / "docs" / DOC
    (doc_dir / "sections").mkdir(parents=True, exist_ok=True)
    (doc_dir / "sections" / "4-3.md").write_text("# 4.3 Recommended\n", encoding="utf-8")
    (doc_dir / "specs.json").write_text(
        SpecSet(
            schema_version="5",
            part_number="TEST",
            doc_hash=DOC_HASH,
            records=[
                rec(1, symbol="AVDD1", min="0.95", typ="1.0", max="1.05"),
                rec(2, symbol="TJ", section_title=ABS_MAX, section="4.1", page=4,
                    unit="°C", max="150"),
                rec(3, symbol="TJ", unit="°C", max="110"),
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    (part_dir / "manifest.json").write_text(
        CorpusManifest(
            part_number="TEST",
            card_version=CARD_VERSION,
            sections=[
                SectionFile(
                    number="4.3",
                    title=RECOMMENDED,
                    file=f"docs/{DOC}/sections/4-3.md",
                    doc_hash=DOC_HASH,
                    page_start=6,
                )
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    return part_dir


class TestThePublishedCards:
    """`cards/*.json` + `cards/*.md`, and the gate that keeps them current."""

    def test_both_forms_are_written_for_every_card(self, part):
        written = write_cards(part, build_cards("TEST", [doc()]))
        names = load_card_lexicon().names
        assert {p.name for p in written} == {
            f"{n}.{ext}" for n in names for ext in ("json", "md")
        }
        assert all(p.exists() for p in written)

    def test_an_empty_card_is_written_like_any_other(self, part):
        """A missing file would read as "not built yet" (ADR 0005)."""
        write_cards(part, build_cards("TEST", [doc()]))
        text = (part / CARDS_DIRNAME / "interface.md").read_text(encoding="utf-8")
        assert "**No rows.**" in text

    def test_the_markdown_on_disk_is_what_the_renderer_produces(self, part):
        """One string, two destinations: the file and `dsa card`."""
        cards = build_cards("TEST", [doc(specs=[rec(1, symbol="AVDD1", typ="1.0")])])
        write_cards(part, cards)
        for card in cards:
            on_disk = (part / CARDS_DIRNAME / f"{card.card}.md").read_text(encoding="utf-8")
            assert on_disk == render_card(card)

    def test_a_card_the_lexicon_no_longer_declares_is_removed(self, part):
        write_cards(part, build_cards("TEST", [doc()]))
        stale = part / CARDS_DIRNAME / "clocking.json"
        stale.write_text("{}", encoding="utf-8")
        write_cards(part, build_cards("TEST", [doc()]))
        assert not stale.exists()

    def test_cards_current_is_true_only_for_this_rule_version(self, part):
        assert not cards_current(part), "no cards at all is staleness, not absence"
        write_cards(part, build_cards("TEST", [doc()], card_version=CARD_VERSION))
        assert cards_current(part, CARD_VERSION)
        assert not cards_current(part, "99")

    def test_a_card_derived_under_another_rule_version_is_stale(self, part):
        write_cards(part, build_cards("TEST", [doc()], card_version="1"))
        assert not cards_current(part, CARD_VERSION)

    def test_an_unreadable_card_is_stale(self, part):
        write_cards(part, build_cards("TEST", [doc()]))
        (part / CARDS_DIRNAME / "power.json").write_text("{oops", encoding="utf-8")
        assert not cards_current(part, CARD_VERSION)


class TestTheRetrievalSeam:
    """`dsa card` reaches the cards the way every other command reaches records."""

    def test_a_card_is_derived_live_from_the_published_records(self, part):
        card = Retriever.for_part(part).card("power")
        assert card is not None
        assert [r.label for r in card.rows] == ["AVDD1"]
        assert card.part_number == "TEST"

    def test_the_live_card_is_the_card_on_disk(self, part):
        retriever = Retriever.for_part(part)
        write_cards(part, retriever.cards())
        for card in retriever.cards():
            on_disk = (part / CARDS_DIRNAME / f"{card.card}.json").read_text(
                encoding="utf-8"
            )
            assert json.loads(on_disk) == json.loads(card.model_dump_json())

    def test_an_unknown_card_name_resolves_to_nothing(self, part):
        assert Retriever.for_part(part).card("clocking") is None

    def test_the_declared_card_names_are_offered(self, part):
        assert Retriever.for_part(part).card_names() == list(load_card_lexicon().names)

    def test_every_source_on_every_row_resolves_to_a_record_and_a_page(
        self, part, resolve_source
    ):
        """The invariant-8 walk, in miniature (the real one runs on real corpora)."""
        for card in Retriever.for_part(part).cards():
            for row in card.rows:
                for role, value in row.values.items():
                    assert value.refs, f"{card.card}/{row.label}/{role} has no source"
                    for ref in value.refs:
                        resolved = resolve_source(part, ref)
                        assert resolved is not None, ref
                        assert resolved.page is not None


class TestTheCli:
    """`cli.py` formats; it holds no card logic of its own."""

    @pytest.fixture
    def scoped(self, part, monkeypatch):
        from datasheet_analyzer import cli

        settings = Settings(
            parts_dir=part.parent, cache_dir=part.parent / ".cache"
        ).resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        return cli

    def test_a_card_prints_the_rendered_markdown(self, scoped, capsys):
        assert scoped.main(["card", "--part", "TEST", "--card", "power"]) == 0
        out = capsys.readouterr().out
        assert BANNER_PREFIX in out
        assert "| AVDD1 |" in out
        assert "§4.3, p.6" in out

    def test_the_limits_card_prints_its_margin(self, scoped, capsys):
        assert scoped.main(["card", "--part", "TEST", "--card", "limits"]) == 0
        assert "40 °C *(derived)*" in capsys.readouterr().out

    def test_an_empty_card_exits_one_and_says_why(self, scoped, capsys):
        assert scoped.main(["card", "--part", "TEST", "--card", "interface"]) == 1
        assert "no interface card" in capsys.readouterr().out

    def test_an_unknown_card_exits_two_and_lists_the_real_ones(self, scoped, capsys):
        assert scoped.main(["card", "--part", "TEST", "--card", "clocking"]) == 2
        assert "power" in capsys.readouterr().err

    def test_no_card_argument_lists_them(self, scoped, capsys):
        assert scoped.main(["card", "--part", "TEST"]) == 0
        assert "power, thermal, interface, limits" in capsys.readouterr().out

    def test_json_carries_the_provenance_envelope(self, scoped, capsys):
        assert scoped.main(["card", "--part", "TEST", "--card", "limits", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        margin = payload["rows"][0]["values"]["margin"]
        assert margin["derivation"] == DERIVATION_MARGIN
        assert margin["source"].startswith("docs/")
        assert margin["sources"]
        assert payload["card_version"] == CARD_VERSION

    def test_an_unbuilt_part_exits_two(self, scoped, capsys):
        assert scoped.main(["card", "--part", "NOPE", "--card", "power"]) == 2
        assert "no corpus" in capsys.readouterr().err
