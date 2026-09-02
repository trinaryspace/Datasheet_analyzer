"""Design cards: selection, margin, honest emptiness, and the invariant-8 walk.

Ticket 07. The most important test in this file — and, per the phase plan, in
the phase — is `TestInvariantEight`: it walks every `source` on every card and
resolves it back to a real record and a printed page. A card is a *derived*
artifact, which is exactly the thing invariant 8 exists to constrain, so a
value nobody can trace to a page is the failure this whole phase is written to
prevent.

The rest of the file guards the three behaviours a reader would otherwise have
to take on trust:

- **the honest empty card** — a part lacking a card's data emits a card with no
  rows and a stated reason, never a fabricated or interpolated one;
- **margin only where both sides parsed** — and every pair that could not be
  compared is named on the card rather than dropped, including the zero-margin
  hazard where the recommended maximum equals the absolute maximum;
- **selectors are data** — a new rail-naming convention is an edit to
  `registry/cards.yaml`, proved by pointing the lexicon at a temp file.

Hermetic per invariant 4: corpora are either hand-published from models or
built in-test from a synthetic PDF written with fitz, into a temp
`parts_dir` / `cache_dir` / `library_dir`. No network, no model, no
subprocess.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer.config import (
    CARDS_SCHEMA_VERSION,
    SPECS_SCHEMA_VERSION,
    Settings,
    reset_settings_cache,
)
from datasheet_analyzer.derive.cards import (
    BANNER,
    DERIVATION_MARGIN,
    DERIVATION_PIN_COUNT,
    FLAG_NEGATIVE_MARGIN,
    FLAG_ZERO_MARGIN,
    GROUP_SEPARATOR,
    CardLexicon,
    audit_card,
    base_unit,
    build_card,
    build_part_cards,
    card_paths,
    clear_card_lexicon_cache,
    cli_card,
    compute_margin,
    format_number,
    load_card,
    load_card_corpus,
    load_card_lexicon,
    load_or_build_card,
    matches_group,
    part_corpus_key,
    publish_part_cards,
    render_card,
    row_citation,
    write_card,
)
from datasheet_analyzer.derive.provenance import (
    CARDS_DIRNAME,
    PINS_ARTIFACT,
    SPECS_ARTIFACT,
    check_provenance,
    describe_problems,
    is_derivation_rule,
)
from datasheet_analyzer.models import (
    CARD_INTERFACE,
    CARD_KINDS,
    CARD_LIMITS,
    CARD_POWER,
    CARD_THERMAL,
    DERIVATION_LEXICON,
    DERIVATION_VERBATIM,
    Card,
    Confidence,
    CorpusManifest,
    DocType,
    PinRecord,
    PinSet,
    SectionFile,
    SourceDocument,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.publish import cards_current, retire_cards

DOC = "datasheet-1f2e3d4c"
DOC_HASH = "1f2e3d4c" + "0" * 56


# --- hand-published corpora -------------------------------------------------
#
# A card reads *published artifacts*, so the honest hermetic input for a card
# test is a published corpus rather than a PDF. `TestPipelineBuiltCorpus`
# below closes the loop by building one through `build_part` from a synthetic
# PDF, so the two shapes are proved to agree.


def _spec(
    section: str,
    row: int,
    symbol: str,
    name: str = "",
    *,
    table: int = 0,
    min: str = "",
    typ: str = "",
    max: str = "",
    value: str = "",
    unit: str = "",
    page: int = 4,
    conditions: str = "",
    table_conditions: str = "",
) -> SpecRecord:
    return SpecRecord(
        section=section,
        table_index=table,
        row_index=row,
        symbol=symbol,
        name=name,
        conditions=conditions,
        table_conditions=table_conditions,
        min=min,
        typ=typ,
        max=max,
        value=value,
        unit=SpecUnit(verbatim=unit, canonical=unit),
        page=page,
        confidence=Confidence.HIGH,
    )


def publish_corpus(
    part_dir: Path,
    part: str,
    records: list[SpecRecord],
    *,
    sections: list[tuple[str, str]] | None = None,
    pins: list[PinRecord] | None = None,
) -> Path:
    """Write the smallest corpus `CorpusIndex` will read: manifest + specs."""
    doc_dir = part_dir / "docs" / DOC
    doc_dir.mkdir(parents=True, exist_ok=True)
    manifest = CorpusManifest(
        part_number=part,
        documents=[
            SourceDocument(
                content_hash=DOC_HASH,
                path=f"{part}.pdf",
                doc_type=DocType.DATASHEET,
                page_count=32,
            )
        ],
        sections=[
            SectionFile(
                number=number,
                title=title,
                file=f"docs/{DOC}/sections/{number}.md",
                doc_hash=DOC_HASH,
                page_start=4,
            )
            for number, title in (sections or [])
        ],
    )
    (part_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (doc_dir / SPECS_ARTIFACT).write_text(
        SpecSet(
            schema_version=SPECS_SCHEMA_VERSION,
            part_number=part,
            doc_hash=DOC_HASH,
            records=records,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    if pins is not None:
        (doc_dir / PINS_ARTIFACT).write_text(
            PinSet(part_number=part, doc_hash=DOC_HASH, pins=pins).model_dump_json(indent=2),
            encoding="utf-8",
        )
    return part_dir


#: A TI-shaped part: an absolute-maximum table on p.4 and a
#: recommended-operating table on p.6, plus the thermal, power and interface
#: rows the other three cards select. Deliberately includes rows that *cannot*
#: be compared, because listing those is half of what the limits card is for.
SECTIONS = [
    ("4.1", "Absolute Maximum Ratings"),
    ("4.3", "Recommended Operating Conditions"),
    ("4.4", "Thermal Information"),
    ("4.8", "Digital Electrical Characteristics"),
    ("4.9", "Power Supply Electrical Characteristics"),
]


#: The shipped derivation-rule version. Most of this file pins `"1"` on
#: purpose — a card built and read at the same version must round-trip
#: whatever that version is — but the three assertions below go through the
#: default (`publish_part_cards`, `cli_card`), so they have to read it rather
#: than repeat it.
SHIPPED_CARD_VERSION = Settings().card_version


def reference_records() -> list[SpecRecord]:
    return [
        # --- 4.1 absolute maximum ratings (p.4)
        _spec("4.1", 0, "TJ", "Junction temperature", max="150", unit="°C"),
        _spec("4.1", 1, "Tstg", "Storage temperature", min="-65", max="150", unit="°C"),
        _spec("4.1", 2, "VIN18", "Digital input voltage", min="-0.5", max="3.6", unit="V"),
        _spec("4.1", 3, "PMAX", "Peak RF input power", max="See Figure 7", unit="dBm"),
        _spec("4.1", 4, "Supply Voltage Range", "DVDD0P9", min="-0.3", max="1.2", unit="V"),
        # --- 4.3 recommended operating conditions (p.6)
        _spec("4.3", 0, "TJ", "Operating junction temperature", max="110", unit="°C", page=6),
        _spec("4.3", 1, "TA", "Ambient temperature", min="-40", max="85", unit="°C", page=6),
        _spec("4.3", 2, "VIN18", "Digital input voltage", min="0", max="3.6", unit="V", page=6),
        _spec("4.3", 3, "PMAX", "Peak RF input power", max="Note 2", unit="dBm", page=6),
        _spec(
            "4.3",
            4,
            "DVDD0P9",
            "Supply voltage 0.9V",
            min="0.9",
            typ="0.925",
            max="0.95",
            unit="V",
            page=6,
        ),
        # --- 4.4 thermal information (p.6)
        _spec(
            "4.4",
            0,
            "RθJA",
            "Junction-to-ambient thermal resistance",
            value="16.2",
            unit="°C/W",
            page=6,
        ),
        _spec(
            "4.4",
            1,
            "RθJC(top)",
            "Junction-to-case (top) thermal resistance",
            value="0.42",
            unit="°C/W",
            page=6,
        ),
        _spec(
            "4.4",
            2,
            "ΨJT",
            "Junction-to-top characterization parameter",
            value="0.12",
            unit="°C/W",
            page=6,
        ),
        _spec(
            "4.4",
            3,
            "ΨJB",
            "Junction-to-board characterization parameter",
            value="4.6",
            unit="°C/W",
            page=6,
        ),
        # --- 4.8 digital / interface (p.20)
        _spec("4.8", 0, "FSerDes", "SerDes Bit Rate", min="19", max="29.5", unit="Gbps", page=20),
        _spec(
            "4.8",
            1,
            "Standards Compliance",
            "JESD204B and JESD204C support",
            typ="JESD204B and JESD204C",
            page=20,
        ),
        _spec(
            "4.8",
            2,
            "t(SCLK)_W",
            "Minimum SCLK period: registers write",
            typ="25",
            unit="ns",
            page=20,
        ),
        # --- 4.9 power supply (p.21)
        _spec("4.9", 0, "IVDD1P8", "Supply current, group 3A", typ="948.2", unit="mA", page=21),
        _spec("4.9", 1, "Pdiss", "Power Dissipation", typ="6027.1", unit="mW", page=21),
        # a heading row: matches a group, prints no value in any of its cells
        _spec("4.8", 3, "JESD204 DATA INPUTS", "", page=20),
    ]


@pytest.fixture
def reference_part(tmp_path) -> tuple[Path, str]:
    part_dir = tmp_path / "parts" / "REF9000"
    publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
    return part_dir, "REF9000"


@pytest.fixture
def reference_cards(reference_part) -> dict[str, Card]:
    part_dir, part = reference_part
    return build_part_cards(part_dir, part, card_version="1")


# --- the selector lexicon ---------------------------------------------------


class TestCardLexicon:
    def test_the_shipped_lexicon_declares_exactly_the_frozen_card_kinds(self):
        lexicon = load_card_lexicon()
        assert set(lexicon.kinds) == set(CARD_KINDS)

    def test_every_group_names_itself_and_says_what_it_selects(self):
        for kind in (CARD_POWER, CARD_THERMAL, CARD_INTERFACE):
            spec = load_card_lexicon().get(kind)
            assert spec is not None and spec.groups, f"{kind} declares no groups"
            for group in spec.groups:
                assert group.id, f"{kind} has an unnamed group"
                assert group.families or group.patterns or group.pin_types, (
                    f"{kind}/{group.id} selects nothing"
                )
                assert group.describe()

    def test_the_limits_card_declares_exactly_two_sides_to_join(self):
        spec = load_card_lexicon().get(CARD_LIMITS)
        assert spec is not None
        assert len(spec.sides) == 2
        for side in spec.sides:
            assert side.section_patterns or side.text_patterns
            assert side.compare_cells

    def test_a_malformed_entry_is_skipped_rather_than_taking_the_lexicon_down(self):
        lexicon = CardLexicon.from_mapping(
            {"cards": {"power": "not a mapping", "thermal": {"groups": [{"id": "tj"}]}}}
        )
        assert lexicon.kinds == ("thermal",)

    def test_an_unreadable_lexicon_degrades_to_an_empty_one(self, tmp_path):
        clear_card_lexicon_cache()
        missing = tmp_path / "nope.yaml"
        assert CardLexicon.read(missing).cards == ()

    def test_a_card_with_no_selectors_says_so_instead_of_claiming_emptiness(self, reference_part):
        part_dir, part = reference_part
        corpus = load_card_corpus(part_dir, part)
        card = build_card(corpus, CARD_POWER, card_lexicon=CardLexicon(), card_version="1")
        assert card.rows == []
        assert any("no selectors" in line for line in card.unresolved)

    def test_selectors_are_data_a_new_rail_name_is_a_lexicon_edit(self, tmp_path):
        """The acceptance criterion, tested as written: a new rail-naming
        convention must be a change to `cards.yaml`, not to Python."""
        part_dir = tmp_path / "parts" / "VBATPART"
        publish_corpus(
            part_dir,
            "VBATPART",
            [_spec("1", 0, "VBAT", "Battery rail", min="2.7", max="4.2", unit="V")],
            sections=[("1", "Recommended Operating Conditions")],
        )
        corpus = load_card_corpus(part_dir, "VBATPART")

        shipped = build_card(corpus, CARD_POWER, card_version="1")
        assert shipped.rows == [], "the shipped lexicon does not know 'battery rail'"

        taught = CardLexicon.from_mapping(
            {
                "cards": {
                    "power": {
                        "title": "Power",
                        "groups": [
                            {
                                "id": "rails",
                                "heading": "Supply voltage",
                                "cells": ["min", "typ", "max"],
                                "patterns": ["battery rail"],
                                "units": ["V"],
                            }
                        ],
                    }
                }
            }
        )
        card = build_card(corpus, CARD_POWER, card_lexicon=taught, card_version="1")
        assert [row.label for row in card.rows] == ["Battery rail"]
        assert card.rows[0].values["max"].verbatim == "4.2"


class TestSelectors:
    def test_a_family_hit_selects_and_a_wrong_unit_rejects(self):
        group = load_card_lexicon().get(CARD_POWER).groups[0]  # rails
        rail = _spec("4.3", 0, "DVDD0P9", "Supply voltage 0.9V", max="0.95", unit="V")
        current = _spec("4.9", 0, "IVDD1P8", "Supply current", typ="948", unit="mA")
        assert matches_group(rail, group, "VDD")
        assert not matches_group(current, group, "IDD")

    def test_an_excluded_phrase_rejects_a_record_a_pattern_would_have_taken(self):
        group = load_card_lexicon().get(CARD_POWER).groups[0]
        pin = _spec("4.1", 3, "Pin Volatge Range", "Supply voltage on RXIN", max="1.4", unit="V")
        assert not matches_group(pin, group, "")

    def test_a_unitless_group_accepts_a_record_that_printed_no_unit(self):
        groups = {g.id: g for g in load_card_lexicon().get(CARD_INTERFACE).groups}
        record = _spec("4.8", 1, "Standards Compliance", typ="JESD204B and JESD204C")
        assert matches_group(record, groups["standards"], "")

    def test_base_unit_resolves_a_printed_prefix_to_the_base(self):
        assert base_unit(_spec("1", 0, "I", unit="mA")) == "A"
        assert base_unit(_spec("1", 0, "F", unit="GHz")) == "Hz"
        assert base_unit(_spec("1", 0, "T", unit="°C")) == "°C"
        assert base_unit(_spec("1", 0, "X")) == ""


# --- the arithmetic ---------------------------------------------------------


class TestMarginArithmetic:
    def _q(self, text: str, unit: str):
        from datasheet_analyzer.structure.quantities import parse_quantity

        return parse_quantity(text, SpecUnit(verbatim=unit, canonical=unit))

    def test_margin_is_the_difference_in_the_shared_unit(self):
        assert compute_margin(self._q("150", "°C"), self._q("110", "°C")) == (40.0, "°C")

    def test_a_prefixed_unit_is_normalized_before_subtracting(self):
        margin, unit = compute_margin(self._q("1500", "mA"), self._q("1.2", "A"))
        assert unit == "A"
        assert margin == pytest.approx(0.3)

    def test_no_margin_when_either_side_did_not_parse(self):
        assert compute_margin(None, self._q("110", "°C")) is None
        assert compute_margin(self._q("150", "°C"), None) is None
        assert self._q("See Figure 7", "dBm") is None

    def test_no_margin_across_units_that_are_not_the_same_thing(self):
        assert compute_margin(self._q("150", "°C"), self._q("1.2", "V")) is None

    def test_format_number_prints_the_way_a_datasheet_would(self):
        assert format_number(40.0) == "40"
        assert format_number(0.25) == "0.25"
        assert format_number(-0.3) == "-0.3"


# --- the invariant-8 walk ---------------------------------------------------


class TestInvariantEight:
    """The phase's most important test: every value traces to a printed page."""

    def test_every_card_builds_and_every_value_resolves_to_a_record_and_a_page(
        self, reference_part, reference_cards
    ):
        part_dir, _part = reference_part
        assert set(reference_cards) == set(CARD_KINDS)
        total = 0
        for kind, card in reference_cards.items():
            audit = audit_card(card, part_dir=part_dir)
            assert audit.ok, audit.describe()
            assert audit.resolved == audit.checked
            total += audit.checked
            assert audit.checked > 0, f"{kind} put nothing on the card to check"
        assert total > 20

    def test_the_shared_structural_checker_agrees(self, reference_cards):
        for card in reference_cards.values():
            problems = check_provenance(card)
            assert problems == [], describe_problems(problems, subject=card.card)

    def test_every_filled_value_names_a_source_a_page_and_a_documented_rule(self, reference_cards):
        seen_rules = set()
        for card in reference_cards.values():
            for row in card.rows:
                for key, value in row.values.items():
                    if not value.filled:
                        assert value.null_reason, f"{card.card}/{row.label}/{key}"
                        continue
                    assert value.source and "#" in value.source
                    assert value.page and value.page >= 1
                    assert is_derivation_rule(value.derivation), value.derivation
                    seen_rules.add(value.derivation)
        assert DERIVATION_VERBATIM in seen_rules
        assert DERIVATION_MARGIN in seen_rules

    def test_a_card_citing_a_page_the_record_is_not_printed_on_is_caught(
        self, reference_part, reference_cards
    ):
        """The walk has to be able to fail, or it proves nothing."""
        part_dir, _part = reference_part
        card = reference_cards[CARD_THERMAL]
        row = card.rows[0]
        key = next(iter(row.values))
        broken = card.model_copy(deep=True)
        broken.rows[0].values[key] = row.values[key].model_copy(update={"page": 999})
        audit = audit_card(broken, part_dir=part_dir)
        assert not audit.ok
        assert any("printed on p." in problem for problem in audit.problems)

    def test_a_card_citing_a_record_that_does_not_exist_is_caught(
        self, reference_part, reference_cards
    ):
        part_dir, _part = reference_part
        card = reference_cards[CARD_POWER]
        row = card.rows[0]
        key = next(iter(row.values))
        broken = card.model_copy(deep=True)
        broken.rows[0].values[key] = row.values[key].model_copy(
            update={"source": f"docs/{DOC}/{SPECS_ARTIFACT}#rec_s9.9-t9-r9"}
        )
        audit = audit_card(broken, part_dir=part_dir)
        assert not audit.ok
        assert any("resolves to no record" in problem for problem in audit.problems)


# --- what each card selects -------------------------------------------------


class TestCardContents:
    def test_the_power_card_finds_rails_currents_and_dissipation(self, reference_cards):
        card = reference_cards[CARD_POWER]
        labels = {row.label for row in card.rows}
        assert "Supply voltage 0.9V" in labels
        assert "Supply current, group 3A" in labels
        assert "Power Dissipation" in labels
        rail = next(row for row in card.rows if row.label == "Supply voltage 0.9V")
        assert rail.values["min"].verbatim == "0.9"
        assert rail.values["typ"].value_si == pytest.approx(0.925)
        assert rail.values["max"].unit_si == "V"

    def test_a_matching_row_that_printed_no_value_is_left_out_and_said_so(self, reference_cards):
        """A table's own heading row matches the selectors and prints nothing.

        Showing it would put a blank parameter on the card, which reads as
        "the datasheet does not say" about something the datasheet never
        claimed was a parameter at all."""
        card = reference_cards[CARD_INTERFACE]
        assert "JESD204 DATA INPUTS" not in {row.label or row.symbol for row in card.rows}
        assert any("printed nothing" in line for line in card.unresolved)

    def test_the_thermal_card_finds_the_resistances_and_the_temperatures(self, reference_cards):
        card = reference_cards[CARD_THERMAL]
        labels = {row.label for row in card.rows}
        assert "Junction-to-ambient thermal resistance" in labels
        assert "Junction-to-case (top) thermal resistance" in labels
        assert "Junction-to-top characterization parameter" in labels
        assert "Junction-to-board characterization parameter" in labels
        assert "Storage temperature" in labels
        assert "Ambient temperature" in labels
        rtheta = next(row for row in card.rows if row.label.startswith("Junction-to-ambient"))
        assert rtheta.values["value"].verbatim == "16.2"
        assert rtheta.values["value"].unit_si == "°C/W"

    def test_the_interface_card_finds_the_standard_the_rate_and_the_spi_timing(
        self, reference_cards
    ):
        card = reference_cards[CARD_INTERFACE]
        labels = {row.label for row in card.rows}
        assert "JESD204B and JESD204C support" in labels
        assert "SerDes Bit Rate" in labels
        assert "Minimum SCLK period: registers write" in labels
        rate = next(row for row in card.rows if row.label == "SerDes Bit Rate")
        assert rate.values["max"].value_si == pytest.approx(29.5e9)
        assert rate.values["max"].unit_si == "bps"

    def test_supply_pins_become_one_row_per_rail_name_with_a_counted_value(self, tmp_path):
        part_dir = tmp_path / "parts" / "PINPART"
        pins = [
            PinRecord(pin=p, name="VDD18", type="power", table_index=0, row_index=r, page=9)
            for r, p in enumerate(("A1", "A2", "B1"))
        ] + [PinRecord(pin="C3", name="VSS", type="ground", table_index=0, row_index=3, page=9)]
        publish_corpus(
            part_dir,
            "PINPART",
            [_spec("1", 0, "VDD18", "Supply voltage", max="1.9", unit="V")],
            sections=[("1", "Recommended Operating Conditions")],
            pins=pins,
        )
        card = build_part_cards(part_dir, "PINPART", [CARD_POWER], card_version="1")[CARD_POWER]
        rows = {row.label: row for row in card.rows if "count" in row.values}
        assert set(rows) == {"VDD18", "VSS"}
        assert rows["VDD18"].values["count"].value_si == 3.0
        assert rows["VDD18"].values["count"].derivation == DERIVATION_PIN_COUNT
        assert rows["VDD18"].values["type"].derivation == DERIVATION_LEXICON
        assert rows["VDD18"].values["pin"].verbatim == "A1"
        assert audit_card(card, part_dir=part_dir).ok


# --- the limits card --------------------------------------------------------


class TestLimitsCard:
    def test_margin_is_computed_where_both_sides_parsed(self, reference_cards):
        card = reference_cards[CARD_LIMITS]
        row = next(row for row in card.rows if row.label == "Junction temperature")
        assert row.values["abs_max"].verbatim == "150"
        assert row.values["recommended"].verbatim == "110"
        margin = row.values["margin"]
        assert margin.value_si == pytest.approx(40.0)
        assert margin.unit_si == "°C"
        assert margin.verbatim == "40 °C"
        assert margin.derivation == DERIVATION_MARGIN
        assert margin.page == 4

    def test_the_join_pairs_rows_the_two_tables_named_the_same_way(self, reference_cards):
        card = reference_cards[CARD_LIMITS]
        compared = {
            row.label
            for row in card.rows
            if row.values.get("margin", None) and row.values["margin"].filled
        }
        assert "Junction temperature" in compared
        assert "DVDD0P9" in compared

    def test_a_recommended_maximum_equal_to_the_rating_is_flagged_zero_margin(
        self, reference_cards
    ):
        """The hazard the card exists for: no headroom, printed two pages apart."""
        card = reference_cards[CARD_LIMITS]
        row = next(row for row in card.rows if row.label == "Digital input voltage")
        assert row.values["abs_max"].verbatim == "3.6"
        assert row.values["recommended"].verbatim == "3.6"
        assert row.values["margin"].value_si == 0.0
        assert FLAG_ZERO_MARGIN in row.flags
        assert "zero margin" in row.note

    def test_a_recommended_maximum_above_the_rating_is_flagged_too(self, tmp_path):
        part_dir = tmp_path / "parts" / "BADPART"
        publish_corpus(
            part_dir,
            "BADPART",
            [
                _spec("1", 0, "TJ", "Junction temperature", max="105", unit="°C"),
                _spec("2", 0, "TJ", "Junction temperature", max="125", unit="°C", page=6),
            ],
            sections=[("1", "Absolute Maximum Ratings"), ("2", "Recommended Operating Conditions")],
        )
        card = build_part_cards(part_dir, "BADPART", [CARD_LIMITS], card_version="1")[CARD_LIMITS]
        row = card.rows[0]
        assert FLAG_NEGATIVE_MARGIN in row.flags
        assert row.values["margin"].value_si == pytest.approx(-20.0)
        assert audit_card(card, part_dir=part_dir).ok

    def test_a_pair_where_one_side_did_not_parse_is_listed_not_dropped(self, reference_cards):
        card = reference_cards[CARD_LIMITS]
        row = next(row for row in card.rows if row.label == "Peak RF input power")
        assert row.values["abs_max"].verbatim == "See Figure 7"
        assert row.values["recommended"].verbatim == "Note 2"
        assert not row.values["margin"].filled
        assert "did not both parse" in row.values["margin"].null_reason
        assert any("Peak RF input power" in line for line in card.unresolved)

    def test_a_one_sided_parameter_is_shown_with_the_reason_it_is_one_sided(self, reference_cards):
        card = reference_cards[CARD_LIMITS]
        storage = next(row for row in card.rows if row.label == "Storage temperature")
        assert storage.values["abs_max"].verbatim == "150"
        assert not storage.values["recommended"].filled
        assert "recommended operating" in storage.values["recommended"].null_reason
        ambient = next(row for row in card.rows if row.label == "Ambient temperature")
        assert ambient.values["recommended"].verbatim == "85"
        assert not ambient.values["abs_max"].filled

    def test_every_uncomparable_pair_is_named_in_unresolved(self, reference_cards):
        card = reference_cards[CARD_LIMITS]
        uncomparable = [row.label for row in card.rows if not row.values["margin"].filled]
        assert uncomparable
        text = "\n".join(card.unresolved)
        for label in uncomparable:
            assert label in text, f"{label} is uncompared but never said so"

    def test_an_ambiguous_family_is_refused_rather_than_paired_by_position(self, tmp_path):
        """Three rails against three rails is a pairing the datasheet made and
        this tool did not read. Guessing it puts a margin on the wrong rail."""
        part_dir = tmp_path / "parts" / "AMBIG"
        publish_corpus(
            part_dir,
            "AMBIG",
            [
                _spec("1", 0, "Supply Voltage Range", "VDD1P2 group", max="1.4", unit="V"),
                _spec("1", 1, "Supply Voltage Range", "VDD1P8 group", max="2.1", unit="V"),
                _spec("2", 0, "VDD1P2{RX/TX}", "Supply voltage 1.2V", max="1.25", unit="V", page=6),
                _spec("2", 1, "VDD1P8{RX/TX}", "Supply voltage 1.8V", max="1.85", unit="V", page=6),
            ],
            sections=[("1", "Absolute Maximum Ratings"), ("2", "Recommended Operating Conditions")],
        )
        card = build_part_cards(part_dir, "AMBIG", [CARD_LIMITS], card_version="1")[CARD_LIMITS]
        assert all(not row.values["margin"].filled for row in card.rows)
        assert any("share the symbol family" in line for line in card.unresolved)
        assert audit_card(card, part_dir=part_dir).ok

    def test_a_part_with_only_one_side_says_so_before_listing_the_rows(self, tmp_path):
        part_dir = tmp_path / "parts" / "ONESIDE"
        publish_corpus(
            part_dir,
            "ONESIDE",
            [_spec("1", 0, "TJ", "Junction temperature", max="150", unit="°C")],
            sections=[("1", "Absolute Maximum Ratings")],
        )
        card = build_part_cards(part_dir, "ONESIDE", [CARD_LIMITS], card_version="1")[CARD_LIMITS]
        assert any("no recommended operating table" in line for line in card.unresolved)
        assert len(card.rows) == 1


# --- honest emptiness -------------------------------------------------------


class TestHonestEmptyCard:
    @pytest.fixture
    def no_interface(self, tmp_path) -> tuple[Path, str]:
        """An op-amp-shaped part: real specs, and no digital interface at all."""
        part_dir = tmp_path / "parts" / "OPAMP1"
        publish_corpus(
            part_dir,
            "OPAMP1",
            [
                _spec("1", 0, "VS", "Supply voltage", max="±22", unit="V"),
                _spec("1", 1, "TJ", "Junction temperature", max="150", unit="°C"),
                _spec("2", 0, "SR", "Slew rate", typ="0.5", unit="V/us", page=5),
            ],
            sections=[("1", "Absolute Maximum Ratings"), ("2", "Electrical Characteristics")],
        )
        return part_dir, "OPAMP1"

    def test_a_part_with_no_interface_section_emits_an_empty_card_with_reasons(self, no_interface):
        part_dir, part = no_interface
        card = build_part_cards(part_dir, part, [CARD_INTERFACE], card_version="1")[CARD_INTERFACE]
        assert card.rows == []
        assert card.is_empty
        assert len(card.unresolved) == 4, card.unresolved
        for group in ("standards", "lanes", "lane_rate", "spi_timing"):
            assert any(f"interface/{group}" in line for line in card.unresolved)

    def test_an_empty_card_is_never_padded_with_a_plausible_default(self, no_interface):
        part_dir, part = no_interface
        card = build_part_cards(part_dir, part, [CARD_INTERFACE], card_version="1")[CARD_INTERFACE]
        assert json.loads(card.model_dump_json())["rows"] == []
        assert check_provenance(card) == []

    def test_the_rendered_empty_card_says_it_is_empty(self, no_interface):
        part_dir, part = no_interface
        card = build_part_cards(part_dir, part, [CARD_INTERFACE], card_version="1")[CARD_INTERFACE]
        text = render_card(card)
        assert "This card is empty" in text
        assert "interface/standards" in text

    def test_a_part_that_publishes_no_spec_records_says_which_kind_of_empty(self, tmp_path):
        part_dir = tmp_path / "parts" / "NOSPECS"
        publish_corpus(part_dir, "NOSPECS", [], sections=[("1", "Description")])
        cards = build_part_cards(part_dir, "NOSPECS", card_version="1")
        for card in cards.values():
            assert card.is_empty
            assert any("publishes no spec records" in line for line in card.unresolved)


# --- rendering --------------------------------------------------------------


class TestRendering:
    def test_the_banner_names_the_card_version(self, reference_cards):
        for card in reference_cards.values():
            text = render_card(card)
            assert text.splitlines()[0] == BANNER.format(version="1")
            assert "<!-- derived: card_version 1 -->" in text

    def test_every_rendered_row_carries_a_citation(self, reference_cards):
        for card in reference_cards.values():
            for line in render_card(card).splitlines():
                if not line.startswith("|") or line.startswith("|---"):
                    continue
                cells = [c.strip() for c in line.strip("|").split("|")]
                if cells[0] == "Parameter":
                    continue
                assert cells[-1] not in ("", "—"), f"{card.card}: uncited row {line}"

    def test_row_citation_names_the_pages_the_values_came_from(self, reference_cards):
        card = reference_cards[CARD_LIMITS]
        row = next(row for row in card.rows if row.label == "Junction temperature")
        assert row_citation(row) == "p.4, p.6"

    def test_rows_are_grouped_under_the_heading_their_group_declares(self, reference_cards):
        text = render_card(reference_cards[CARD_POWER])
        assert "## Supply voltage" in text
        assert "## Supply current" in text
        assert "## Power dissipation" in text

    def test_the_group_heading_survives_a_json_round_trip(self, reference_cards, tmp_path):
        card = reference_cards[CARD_THERMAL]
        assert all(GROUP_SEPARATOR in row.note or row.note for row in card.rows)
        again = Card.model_validate_json(card.model_dump_json())
        assert render_card(again) == render_card(card)

    def test_a_printed_pipe_never_becomes_a_column_break(self, tmp_path):
        part_dir = tmp_path / "parts" / "PIPEY"
        publish_corpus(
            part_dir,
            "PIPEY",
            [_spec("1", 0, "TJ", "Junction temperature | note", max="150", unit="°C")],
            sections=[("1", "Absolute Maximum Ratings")],
        )
        card = build_part_cards(part_dir, "PIPEY", [CARD_THERMAL], card_version="1")[CARD_THERMAL]
        rendered = render_card(card).splitlines()
        row_line = next(
            line for line in rendered if line.startswith("|") and "Junction temperature" in line
        )
        header = next(line for line in rendered if line.startswith("| Parameter"))
        assert "Junction temperature \\| note" in row_line
        unescaped = re.compile(r"(?<!\\)\|")
        assert len(unescaped.split(row_line)) == len(unescaped.split(header))


# --- publishing and the card version ---------------------------------------


class TestPublishing:
    def test_write_card_publishes_json_and_markdown_beside_the_part(
        self, reference_part, reference_cards
    ):
        part_dir, _part = reference_part
        json_path, md_path = write_card(part_dir, reference_cards[CARD_POWER])
        assert json_path == part_dir / CARDS_DIRNAME / "power.json"
        assert md_path == part_dir / CARDS_DIRNAME / "power.md"
        assert json.loads(json_path.read_text(encoding="utf-8"))["card"] == CARD_POWER
        assert md_path.read_text(encoding="utf-8").startswith("<!-- derived: card_version 1 -->")

    def test_republishing_unchanged_bytes_does_not_touch_the_file(
        self, reference_part, reference_cards
    ):
        part_dir, _part = reference_part
        json_path, _md = write_card(part_dir, reference_cards[CARD_THERMAL])
        before = json_path.stat().st_mtime_ns
        write_card(part_dir, reference_cards[CARD_THERMAL])
        assert json_path.stat().st_mtime_ns == before

    def test_load_card_refuses_a_card_built_by_other_rules(self, reference_part, reference_cards):
        part_dir, _part = reference_part
        write_card(part_dir, reference_cards[CARD_POWER])
        assert load_card(part_dir, CARD_POWER, card_version="1") is not None
        assert load_card(part_dir, CARD_POWER, card_version="2") is None

    def test_changing_the_card_version_regenerates_rather_than_leaving_a_stale_card(
        self, reference_part, monkeypatch
    ):
        """`DSA_CARD_VERSION` versions the *derivation rules*, so a bump has to
        replace the published card, not shadow it."""
        part_dir, part = reference_part
        monkeypatch.setenv("DSA_CARD_VERSION", "1")
        reset_settings_cache()
        first = load_or_build_card(part_dir, part, CARD_POWER)
        json_path, md_path = card_paths(part_dir, CARD_POWER)
        assert first.card_version == "1"
        assert json.loads(json_path.read_text(encoding="utf-8"))["card_version"] == "1"
        assert cards_current(part_dir, "1")
        assert not cards_current(part_dir, "2")

        monkeypatch.setenv("DSA_CARD_VERSION", "2")
        reset_settings_cache()
        second = load_or_build_card(part_dir, part, CARD_POWER)
        assert second.card_version == "2"
        assert json.loads(json_path.read_text(encoding="utf-8"))["card_version"] == "2"
        assert "card_version 2" in md_path.read_text(encoding="utf-8")
        assert cards_current(part_dir, "2")
        reset_settings_cache()

    def test_publish_part_cards_writes_every_card(self, reference_part, monkeypatch):
        part_dir, part = reference_part
        monkeypatch.setenv("DSA_CARD_VERSION", "1")
        reset_settings_cache()
        cards = publish_part_cards(part_dir, part)
        assert set(cards) == set(CARD_KINDS)
        for kind in CARD_KINDS:
            json_path, md_path = card_paths(part_dir, kind)
            assert json_path.is_file() and md_path.is_file()
        assert cards_current(part_dir, "1")
        reset_settings_cache()


# --- the record-id collision workaround ------------------------------------


class TestUnaddressableRecords:
    """When two records do compute one id, a card cites neither ambiguously.

    Phase 6.5 ticket 08 removed the *cause* — an id is keyed on the section's
    file stem now, so AD9081 went from 259 distinct ids over 549 records to
    549 — but the refusal must stay: any future collision has to be visible
    rather than resolved by picking whichever record was read first. The
    records below are constructed with a colliding key on purpose.
    """

    def test_only_the_addressable_record_of_a_colliding_pair_is_cited(self, tmp_path):
        part_dir = tmp_path / "parts" / "COLLIDE"
        publish_corpus(
            part_dir,
            "COLLIDE",
            [
                _spec("", 0, "Supply voltage", "AVDD2 rail", max="2.1", unit="V", page=4),
                _spec("", 0, "Supply voltage", "DVDD1 rail", max="1.05", unit="V", page=12),
            ],
            sections=[],
        )
        card = build_part_cards(part_dir, "COLLIDE", [CARD_POWER], card_version="1")[CARD_POWER]
        assert [row.label for row in card.rows] == ["AVDD2 rail"]
        assert any("could not be cited" in line for line in card.unresolved)
        assert any("share a record id" in line for line in card.warnings)
        audit = audit_card(card, part_dir=part_dir)
        assert audit.ok, audit.describe()

    def test_a_record_with_no_printed_page_is_never_cited(self, tmp_path):
        part_dir = tmp_path / "parts" / "NOPAGE"
        record = _spec("1", 0, "TJ", "Junction temperature", max="150", unit="°C")
        record.page = None
        publish_corpus(part_dir, "NOPAGE", [record], sections=[("1", "Thermal Information")])
        card = build_part_cards(part_dir, "NOPAGE", [CARD_THERMAL], card_version="1")[CARD_THERMAL]
        assert card.rows == []
        assert any("could not be cited" in line for line in card.unresolved)


# --- a corpus published by the real pipeline -------------------------------


PAGE_W, PAGE_H = 612.0, 792.0
X = {"param": 56.0, "conditions": 222.0, "min": 435.0, "typ": 460.0, "max": 515.0, "unit": 548.0}
PITCH = 13.0


def _write_card_pdf(path: Path) -> None:
    """One page, one section, one acceptable parametric table.

    The geometry is the one `test_derived_contract.py` established as a table
    the layout engine actually accepts; only the row text differs. Both cards
    that select from it (`power`, `thermal`) are exercised, and the section is
    titled so the `limits` card recognises the side it came from.
    """
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    rows = [
        {"param": "Junction Temperature", "max": "150", "unit": "°C"},
        {"param": "Storage Temperature", "min": "-65", "max": "150", "unit": "°C"},
        {
            "param": "Supply Voltage",
            "conditions": "VDD1P2 rail",
            "min": "-0.3",
            "max": "1.4",
            "unit": "V",
        },
        {
            "param": "Supply Current",
            "conditions": "Shuffling disabled",
            "typ": "1350",
            "max": "1500",
            "unit": "mA",
        },
        {
            "param": "Peak Input Power",
            "conditions": "RF input",
            "max": "See Figure 7",
            "unit": "dBm",
        },
    ]
    lines = [
        (56.0, 112.0, "Stresses beyond those listed may cause permanent damage."),
        (56.0, 140.0, "Table 1. Absolute Maximum Ratings"),
        (X["param"], 153.0, "Parameter"),
        (X["conditions"], 153.0, "Test Conditions/Comments"),
        (X["min"], 153.0, "Min"),
        (X["typ"], 153.0, "Typ"),
        (X["max"], 153.0, "Max"),
        (X["unit"], 153.0, "Unit"),
    ]
    for index, row in enumerate(rows, start=1):
        y = 153.0 + index * PITCH
        for key, text in row.items():
            lines.append((X[key], y, text))
    for x, y, text in lines:
        page.insert_text((x, y), text)
    doc.set_toc([[1, "1 Absolute Maximum Ratings", 1]])
    doc.save(str(path))
    doc.close()


@pytest.fixture(scope="module")
def built_part(tmp_path_factory):
    """A corpus published by `build_part` itself, into a shared document store."""
    from datasheet_analyzer.pipeline import build_part

    root = tmp_path_factory.mktemp("cards-pipeline")
    pdf = root / "synthetic.pdf"
    _write_card_pdf(pdf)
    settings = Settings(
        parts_dir=root / "parts", cache_dir=root / "cache", library_dir=root / "library"
    ).resolve()
    result = build_part(
        pdf, part_number="TEST9000", settings=settings, vendor="unknown", use_llm=False
    )
    return result.part_dir, "TEST9000", settings


class TestPipelineBuiltCorpus:
    def test_the_synthetic_build_published_records_to_select_from(self, built_part):
        part_dir, part, _settings = built_part
        corpus = load_card_corpus(part_dir, part)
        assert corpus.has_records
        # Published once into the shared store, so the card cites it there.
        assert all(doc.ref_base.startswith("@library/") for doc in corpus.documents)

    def test_all_four_cards_build_and_every_value_resolves(self, built_part):
        part_dir, part, settings = built_part
        cards = build_part_cards(part_dir, part, card_version="1")
        assert set(cards) == set(CARD_KINDS)
        checked = 0
        for card in cards.values():
            audit = audit_card(card, part_dir=part_dir, library_dir=settings.library_dir)
            assert audit.ok, audit.describe()
            checked += audit.checked
        assert checked > 0

    def test_the_cards_read_the_values_the_pdf_printed(self, built_part):
        part_dir, part, _settings = built_part
        cards = build_part_cards(part_dir, part, card_version="1")
        thermal = {row.label: row for row in cards[CARD_THERMAL].rows}
        assert thermal["Junction Temperature"].values["max"].verbatim == "150"
        power = {row.label: row for row in cards[CARD_POWER].rows}
        assert power["Supply Current"].values["typ"].verbatim == "1350"
        assert power["Supply Current"].values["typ"].value_si == pytest.approx(1.35)

    def test_a_card_version_bump_republishes_the_file_on_disk(self, built_part, monkeypatch):
        part_dir, part, _settings = built_part
        monkeypatch.setenv("DSA_CARD_VERSION", "7")
        reset_settings_cache()
        card = load_or_build_card(part_dir, part, CARD_THERMAL)
        json_path, _md = card_paths(part_dir, CARD_THERMAL)
        assert card.card_version == "7"
        assert json.loads(json_path.read_text(encoding="utf-8"))["card_version"] == "7"
        assert cards_current(part_dir, "7")
        reset_settings_cache()


# --- the CLI ----------------------------------------------------------------


class TestCli:
    def _args(self, **kw) -> argparse.Namespace:
        base = {"part": "", "project": "", "card": CARD_POWER, "json": False}
        base.update(kw)
        return argparse.Namespace(**base)

    def test_a_card_with_rows_exits_zero_and_prints_the_rendered_markdown(
        self, reference_part, monkeypatch, capsys
    ):
        part_dir, part = reference_part
        monkeypatch.setenv("DSA_PARTS_DIR", str(part_dir.parent))
        reset_settings_cache()
        assert cli_card(self._args(part=part)) == 0
        out = capsys.readouterr().out
        assert BANNER.format(version=SHIPPED_CARD_VERSION) in out
        assert "Supply voltage 0.9V" in out
        reset_settings_cache()

    def test_json_output_is_the_card_with_its_provenance(self, reference_part, monkeypatch, capsys):
        part_dir, part = reference_part
        monkeypatch.setenv("DSA_PARTS_DIR", str(part_dir.parent))
        reset_settings_cache()
        assert cli_card(self._args(part=part, card=CARD_LIMITS, json=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["card"] == CARD_LIMITS
        row = next(r for r in payload["cards"][0]["rows"] if r["label"] == "Junction temperature")
        assert row["values"]["margin"]["derivation"] == DERIVATION_MARGIN
        assert row["values"]["margin"]["page"] == 4
        reset_settings_cache()

    def test_an_honestly_empty_card_exits_one_rather_than_pretending_to_fail(
        self, tmp_path, monkeypatch, capsys
    ):
        part_dir = tmp_path / "parts" / "OPAMP2"
        publish_corpus(
            part_dir,
            "OPAMP2",
            [_spec("1", 0, "VS", "Supply voltage", max="±22", unit="V")],
            sections=[("1", "Absolute Maximum Ratings")],
        )
        monkeypatch.setenv("DSA_PARTS_DIR", str(part_dir.parent))
        reset_settings_cache()
        assert cli_card(self._args(part="OPAMP2", card=CARD_INTERFACE)) == 1
        assert "This card is empty" in capsys.readouterr().out
        reset_settings_cache()

    def test_a_scope_that_cannot_be_resolved_exits_two(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("DSA_PARTS_DIR", str(tmp_path / "parts"))
        reset_settings_cache()
        assert cli_card(self._args(part="", project="")) == 2
        assert cli_card(self._args(part="NOPE")) == 2
        assert capsys.readouterr().err
        reset_settings_cache()

    def test_an_unknown_card_kind_exits_two_rather_than_building_nothing(
        self, reference_part, monkeypatch
    ):
        part_dir, part = reference_part
        monkeypatch.setenv("DSA_PARTS_DIR", str(part_dir.parent))
        reset_settings_cache()
        assert cli_card(self._args(part=part, card="voltage")) == 2
        reset_settings_cache()


# --- staleness when a document moves (phase 6.5, ticket 03) ----------------


def _republish_to_library(part_dir: Path, library_dir: Path) -> None:
    """Move a part's one document into the shared store, as `publish` would.

    Exactly the transition that produced the defect: the artifacts are
    untouched, the manifest now names them through `@library/`, and nothing a
    card records about its *rules* has changed.
    """
    import shutil

    shared = library_dir / "docs" / DOC
    shared.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(part_dir / "docs" / DOC), str(shared))
    (part_dir / "docs").rmdir()

    manifest = CorpusManifest.model_validate_json(
        (part_dir / "manifest.json").read_text(encoding="utf-8")
    )
    moved = manifest.model_copy(
        update={
            "library_root": str(library_dir),
            "sections": [
                section.model_copy(update={"file": f"@library/docs/{DOC}/sections/{s}.md"})
                for section in manifest.sections
                for s in [section.number]
            ],
        }
    )
    (part_dir / "manifest.json").write_text(moved.model_dump_json(indent=2), encoding="utf-8")


class TestCorpusKey:
    """A card is stale when its documents no longer resolve where they did.

    `schema_version` and `card_version` describe the *rules* a card was built
    by, and neither moves when a document is republished to the shared store.
    Before this key, the card kept citing a directory that no longer existed —
    87 of 87 filled values on AD9081's power card resolved to no record, and
    only `audit_card` noticed.
    """

    def test_the_key_is_stable_across_an_identical_rebuild(self, reference_part):
        part_dir, part = reference_part
        first = build_part_cards(part_dir, part, [CARD_POWER], card_version="1")[CARD_POWER]
        second = build_part_cards(part_dir, part, [CARD_POWER], card_version="1")[CARD_POWER]
        assert first.corpus_key
        assert first.corpus_key == second.corpus_key == part_corpus_key(part_dir)

    def test_the_key_does_not_depend_on_where_the_part_is_checked_out(self, tmp_path):
        """No absolute path may reach the digest, or a clone is born stale."""
        keys = []
        for clone in ("checkout-a", "checkout-b"):
            part_dir = tmp_path / clone / "parts" / "REF9000"
            publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
            keys.append(part_corpus_key(part_dir))
        assert keys[0] == keys[1]

    def test_a_card_whose_document_moved_is_rebuilt_not_served(self, tmp_path):
        part_dir = tmp_path / "parts" / "REF9000"
        publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
        before = load_or_build_card(part_dir, "REF9000", CARD_POWER, card_version="1")
        assert before.rows, "the fixture must fill a power card, or this proves nothing"
        assert all(source.startswith(f"docs/{DOC}") for source in before.sources)

        _republish_to_library(part_dir, tmp_path / "library")
        after = load_or_build_card(part_dir, "REF9000", CARD_POWER, card_version="1")

        assert after.corpus_key != before.corpus_key
        assert all(source.startswith(f"@library/docs/{DOC}") for source in after.sources)

    def test_the_rebuilt_card_audits_clean(self, tmp_path):
        """The point of rebuilding: every citation resolves again."""
        part_dir = tmp_path / "parts" / "REF9000"
        publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
        load_or_build_card(part_dir, "REF9000", CARD_POWER, card_version="1")

        _republish_to_library(part_dir, tmp_path / "library")
        card = load_or_build_card(part_dir, "REF9000", CARD_POWER, card_version="1")
        audit = audit_card(
            card, part_dir=part_dir, library_dir=load_card_corpus(part_dir, "REF9000").library_dir
        )

        assert audit.problems == ()
        assert audit.resolved == audit.checked > 0

    def test_without_the_key_the_stale_card_would_have_been_served(self, tmp_path):
        """The defect itself, pinned: the two old terms cannot see the move."""
        part_dir = tmp_path / "parts" / "REF9000"
        publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
        before = load_or_build_card(part_dir, "REF9000", CARD_POWER, card_version="1")
        _republish_to_library(part_dir, tmp_path / "library")

        stale = json.loads((part_dir / CARDS_DIRNAME / f"{CARD_POWER}.json").read_text("utf-8"))
        assert stale["schema_version"] == CARDS_SCHEMA_VERSION
        assert stale["card_version"] == "1"  # unchanged by the move — that was the hole
        assert stale["corpus_key"] == before.corpus_key != part_corpus_key(part_dir)

        # And what serving it would have cost, measured on the file as written.
        moved = load_card_corpus(part_dir, "REF9000")
        audit = audit_card(
            Card.model_validate(stale), part_dir=part_dir, library_dir=moved.library_dir
        )
        assert audit.resolved == 0 and audit.checked > 0

    def test_the_batch_gate_agrees_with_the_reader(self, tmp_path):
        """One staleness rule. Two that could disagree is a rebuild loop."""
        part_dir = tmp_path / "parts" / "REF9000"
        publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
        publish_part_cards(part_dir, "REF9000")
        assert cards_current(part_dir, SHIPPED_CARD_VERSION) is True

        _republish_to_library(part_dir, tmp_path / "library")
        assert cards_current(part_dir, SHIPPED_CARD_VERSION) is False
        assert load_card(part_dir, CARD_POWER, card_version=SHIPPED_CARD_VERSION) is None


class TestRetiringCardsOnRepublish:
    """The hole `corpus_key` cannot close, and what closes it instead.

    `corpus_key` keys on *where* each document resolved, which is exactly what
    a move changes — and exactly what a **rebuild in place** does not. Phase
    6.5's rebuild found the cost: AFE7950's power card survived with a matching
    `corpus_key`, `card_version` and `schema_version`, and 112 of its 143
    values then cited p.21 for a record the rebuilt corpus prints on p.22,
    because per-row page pinning had moved them.

    So a build retires the cards it supersedes. Missing is a documented state
    that rebuilds on demand; stale-but-current-looking is the one state
    invariant 8 exists to prevent.
    """

    def test_a_rebuild_in_place_leaves_the_key_unchanged(self, tmp_path):
        """The defect itself, pinned: the key cannot see a republish in place."""
        part_dir = tmp_path / "parts" / "REF9000"
        publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
        before = part_corpus_key(part_dir)
        publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
        assert part_corpus_key(part_dir) == before

    def test_retiring_removes_every_card_file_and_reports_how_many(self, tmp_path):
        part_dir = tmp_path / "parts" / "REF9000"
        publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
        publish_part_cards(part_dir, "REF9000")
        cards_dir = part_dir / CARDS_DIRNAME
        published = sorted(path.name for path in cards_dir.iterdir())
        assert published, "the fixture must publish cards, or this proves nothing"

        removed = retire_cards(part_dir)

        assert removed == len(published)
        assert sorted(path.name for path in cards_dir.iterdir()) == []

    def test_retiring_a_part_with_no_cards_is_a_no_op(self, tmp_path):
        part_dir = tmp_path / "parts" / "REF9000"
        publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
        assert retire_cards(part_dir) == 0

    def test_the_reader_rebuilds_what_the_build_retired(self, tmp_path):
        part_dir = tmp_path / "parts" / "REF9000"
        publish_corpus(part_dir, "REF9000", reference_records(), sections=SECTIONS)
        before = load_or_build_card(part_dir, "REF9000", CARD_POWER, card_version="1")
        assert before.rows

        retire_cards(part_dir)
        assert load_card(part_dir, CARD_POWER, card_version="1") is None

        after = load_or_build_card(part_dir, "REF9000", CARD_POWER, card_version="1")
        assert [row.label for row in after.rows] == [row.label for row in before.rows]
