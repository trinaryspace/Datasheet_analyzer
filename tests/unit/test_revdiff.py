"""Revision diff (phase 7, ticket 03) — `dsa diff-rev`, rule by rule.

The gate (`tests/integration/test_phase7_revdiff.py`) proves the command against
a synthetic revision **pair** pushed through the real extraction pipeline, with a
declared edit list. What is proven here is every rule on its own, and — the point
of a rule test — that each one fails for the right reason:

- a parameter the vendor **renamed** is one `changed` row, not a removal plus an
  addition, because the alias lexicon claims both spellings;
- a **numeric delta exists only where both sides parsed** the same printed column
  into the same SI base; everything else is quoted verbatim under "review by
  hand" and carries no score, no sign and no direction;
- a **section retitle, a page shift and an addition are three different facts**,
  and a numbered section that was reworded stays the same section;
- a **pin rename is not a pin removed plus a pin added** — the designator is the
  identity, because that is what the package fixes;
- a **register reset change is called out on its own**, and is never subtracted:
  a reset is a bit pattern, and its bit fields' ranges are diffed beside it
  because a field that moved from `2:0` to `3:1` misconfigures silicon silently;
- an **ambiguous alignment is refused**, listed with its printed values, and
  never reported as added + removed;
- a diff of a document **against itself is empty and says so**, which is the
  determinism check;
- every value carries a **part- and document-qualified `source`** that resolves,
  because both revisions of one part publish a `rec_1`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.config import PIPELINE_VERSION, REVDIFF_SCHEMA_VERSION, Settings
from datasheet_analyzer.models import (
    BitRange,
    Confidence,
    DocType,
    ExtractionStats,
    PinRecord,
    PinType,
    RawDocument,
    RegisterField,
    RegisterRecord,
    RegisterWord,
    SectionFile,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecUnit,
)
from datasheet_analyzer.publish import write_corpus, write_revision_diff
from datasheet_analyzer.publish.writer import doc_dir_name_for_source, revision_slug
from datasheet_analyzer.retrieve import Retriever, clear_index_cache
from datasheet_analyzer.retrieve.revdiff import RevisionPair, select_revision
from datasheet_analyzer.revdiff import (
    CHANGE_ADDED,
    CHANGE_CHANGED,
    CHANGE_PAGE_SHIFTED,
    CHANGE_REMOVED,
    CHANGE_RENAMED,
    CHANGE_RESET,
    CHANGE_RETITLED,
    FLAG_REVIEW,
    KIND_FIELD,
    KIND_PIN,
    KIND_REGISTER,
    KIND_SECTION,
    KIND_SPEC,
    REVIEW_HEADING,
    RevisionSide,
    banner,
    build_revision_diff,
    render_revision_diff,
)
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.structure.registers import build_registerset

HASH_A = "aa" + "0" * 62
HASH_B = "bb" + "0" * 62


# --- literal record helpers ---------------------------------------------------


def _spec(rec_id: str, **kwargs) -> SpecRecord:
    defaults = {
        "id": rec_id,
        "section": "4.1",
        "section_title": "Electrical Characteristics",
        "unit": SpecUnit(verbatim="°C", canonical="°C"),
        "page": 4,
        "confidence": Confidence.HIGH,
    }
    return SpecRecord(**{**defaults, **kwargs})


def _pin(rec_id: str, pin: str, name: str, **kwargs) -> PinRecord:
    defaults = {
        "id": rec_id,
        "pin": pin,
        "name": name,
        "type": PinType.POWER,
        "section": "6",
        "page": 9,
        "confidence": Confidence.HIGH,
    }
    return PinRecord(**{**defaults, **kwargs})


def _register(rec_id: str, addr: str, value: int, name: str, reset: str = "",
              fields: list[RegisterField] | None = None, **kwargs) -> RegisterRecord:
    defaults = {
        "id": rec_id,
        "address": RegisterWord(verbatim=addr, value=value, page=2),
        "name": name,
        "section": "1",
        "page": 2,
        "confidence": Confidence.HIGH,
        "fields": fields or [],
    }
    if reset:
        defaults["reset"] = RegisterWord(verbatim=reset, value=None, page=2)
    return RegisterRecord(**{**defaults, **kwargs})


def _field(name: str, bits: str, reset: str = "") -> RegisterField:
    hi, _, lo = bits.partition(":")
    return RegisterField(
        name=name,
        bits=BitRange(verbatim=bits, hi=int(hi), lo=int(lo or hi)),
        reset=reset,
        page=3,
    )


def _section(number: str, title: str, start: int, end: int | None = None,
             doc_hash: str = HASH_A) -> SectionFile:
    return SectionFile(
        number=number,
        title=title,
        file=f"docs/datasheet-{doc_hash[:8]}/sections/{number}.md",
        doc_hash=doc_hash,
        page_start=start,
        page_end=end if end is not None else start,
    )


def _side(label: str, doc_hash: str = HASH_A, **kwargs) -> RevisionSide:
    return RevisionSide(
        part_number="REVPART",
        label=label,
        doc=f"datasheet-{doc_hash[:8]}-rev{label.lower()}",
        revision=f"SBAS999{label}",
        **kwargs,
    )


def _of(diff, kind: str, change: str = "") -> list:
    return [
        c for c in diff.of_kind(kind) if not change or c.change == change
    ]


# --- specs --------------------------------------------------------------------


class TestSpecAlignment:
    def test_renamed_parameter_is_one_changed_row_not_a_removal_and_addition(self):
        """The ticket's second criterion: the alias lexicon claims both spellings.

        Rev A prints `TJ`, rev B prints the designer's words. Reporting that as
        `TJ removed` + `Junction temperature added` is how a review misses the
        20 °C the vendor actually moved.
        """
        before = _side("A", specs=(_spec("rec_1", symbol="TJ", max="105"),))
        after = _side(
            "B", HASH_B,
            specs=(_spec("rec_1", symbol="", name="Junction temperature", max="125"),),
        )
        diff = build_revision_diff(before, after)

        assert not _of(diff, KIND_SPEC, CHANGE_ADDED)
        assert not _of(diff, KIND_SPEC, CHANGE_REMOVED)
        changed = _of(diff, KIND_SPEC, CHANGE_CHANGED)
        assert len(changed) == 1
        assert changed[0].key == "TJ"
        assert changed[0].aligned_on == "alias:TJ"
        assert changed[0].field == "max"

    def test_numeric_delta_appears_only_where_both_sides_parsed(self):
        """One row parses on both sides; the other prints prose on both."""
        before = _side(
            "A",
            specs=(
                _spec("rec_1", symbol="TJ", max="105"),
                _spec("rec_2", symbol="Noise", typ="See Figure 7"),
            ),
        )
        after = _side(
            "B", HASH_B,
            specs=(
                _spec("rec_1", symbol="TJ", max="125"),
                _spec("rec_2", symbol="Noise", typ="See Figure 9"),
            ),
        )
        diff = build_revision_diff(before, after)

        scored = [c for c in diff.changes if c.delta is not None]
        assert len(scored) == 1
        assert scored[0].key == "TJ"
        assert scored[0].delta.value_si == pytest.approx(20.0)
        assert scored[0].delta.derivation == "si_delta:max"
        # both operands cited: a delta traceable by half is not traceable
        assert scored[0].delta.sources == [scored[0].before.source]
        assert "105 °C -> 125 °C" in scored[0].summary
        assert "+20" in scored[0].summary

        unscored = [c for c in diff.changes if c.delta is None]
        assert [c.key for c in unscored] == ["Noise"]
        assert FLAG_REVIEW in unscored[0].flags
        assert unscored[0].delta is None

    def test_unscored_change_is_quoted_verbatim_under_review_by_hand(self):
        before = _side("A", specs=(_spec("rec_1", symbol="Noise", typ="See Figure 7"),))
        after = _side(
            "B", HASH_B, specs=(_spec("rec_1", symbol="Noise", typ="See Figure 9"),)
        )
        diff = build_revision_diff(before, after)

        assert len(diff.review_by_hand) == 1
        line = diff.review_by_hand[0]
        assert "See Figure 7" in line and "See Figure 9" in line
        # never scored: no arrow of improvement, no number, no sign
        assert "+" not in line and "-0" not in line

    def test_a_reprinted_prefix_is_scaled_and_the_unit_move_is_its_own_row(self):
        """1.8 V against 1900 mV is a delta of +0.1 V, in the base both parsed to.

        The prefix is not the finding — the SI layer exists precisely so a vendor
        who switched from volts to millivolts does not read as a 1898-fold change
        — and the notation move is reported beside it as its own unscored row, so
        a reader who cares about the printed unit is still told.
        """
        before = _side(
            "A",
            specs=(_spec("rec_1", symbol="VDD", typ="1.8",
                         unit=SpecUnit(verbatim="V", canonical="V")),),
        )
        after = _side(
            "B", HASH_B,
            specs=(_spec("rec_1", symbol="VDD", typ="1900",
                         unit=SpecUnit(verbatim="mV", canonical="mV")),),
        )
        diff = build_revision_diff(before, after)

        typ = [c for c in diff.of_kind(KIND_SPEC) if c.field == "typ"]
        assert len(typ) == 1
        assert typ[0].delta.value_si == pytest.approx(0.1)
        assert typ[0].delta.unit_si == "V"
        units = [c for c in diff.of_kind(KIND_SPEC) if c.field == "unit"]
        assert [(c.before.verbatim, c.after.verbatim) for c in units] == [("V", "mV")]
        assert FLAG_REVIEW in units[0].flags

    def test_a_changed_base_is_a_change_to_review_and_never_a_delta(self):
        """A volt is not an amp: 1.8 V against 1.8 A is not a delta of 0 of
        anything, and the reason is stated rather than left as a blank cell."""
        before = _side(
            "A",
            specs=(_spec("rec_1", symbol="VDD", typ="1.8",
                         unit=SpecUnit(verbatim="V", canonical="V")),),
        )
        after = _side(
            "B", HASH_B,
            specs=(_spec("rec_1", symbol="VDD", typ="1.9",
                         unit=SpecUnit(verbatim="A", canonical="A")),),
        )
        diff = build_revision_diff(before, after)

        typ = [c for c in diff.of_kind(KIND_SPEC) if c.field == "typ"]
        assert typ[0].delta is None
        assert FLAG_REVIEW in typ[0].flags
        assert "different bases" in typ[0].note

    def test_added_and_removed_rows_are_both_reported_with_what_they_printed(self):
        before = _side("A", specs=(_spec("rec_1", symbol="Gain error", typ="1.5"),))
        after = _side("B", HASH_B, specs=(_spec("rec_1", symbol="Ton", typ="5"),))
        diff = build_revision_diff(before, after)

        added = _of(diff, KIND_SPEC, CHANGE_ADDED)
        removed = _of(diff, KIND_SPEC, CHANGE_REMOVED)
        assert [c.key for c in added] == ["Ton"]
        # the lexicon claims `Gain error`, so the row is keyed by the canonical
        # symbol a designer knows and still carries the printed spelling
        assert [c.key for c in removed] == ["Gain Error"]
        assert [c.label for c in removed] == ["Gain error"]
        assert removed[0].aligned_on == "alias:Gain Error"
        assert added[0].before is None and added[0].after is not None
        assert removed[0].after is None and removed[0].before is not None
        # an addition can never be scored: there is nothing to subtract from
        assert added[0].delta is None and removed[0].delta is None

    def test_ambiguous_parameter_is_refused_not_reported_as_added_and_removed(self):
        """Two rows under one key on each side, sharing no printed identity.

        Reporting them as two removals and two additions would be a claim about
        the device. They are listed with their printed values instead.
        """
        before = _side(
            "A",
            specs=(
                _spec("rec_1", symbol="TJ", conditions="industrial", max="105"),
                _spec("rec_2", symbol="TJ", conditions="commercial", max="85"),
            ),
        )
        after = _side(
            "B", HASH_B,
            specs=(
                _spec("rec_1", symbol="TJ", conditions="extended", max="125"),
                _spec("rec_2", symbol="TJ", conditions="automotive", max="105"),
            ),
        )
        diff = build_revision_diff(before, after)

        assert not diff.of_kind(KIND_SPEC)
        assert any("uncomparable: TJ" in line for line in diff.unparsed)
        # every refused row is quoted with its printed value and its page
        assert sum("uncomparable: TJ /" in line for line in diff.unparsed) == 4
        assert any("105 °C" in line for line in diff.unparsed)

    def test_matching_conditions_still_pair_inside_an_ambiguous_key(self):
        before = _side(
            "A",
            specs=(
                _spec("rec_1", symbol="TJ", conditions="industrial", max="105"),
                _spec("rec_2", symbol="TJ", conditions="commercial", max="85"),
            ),
        )
        after = _side(
            "B", HASH_B,
            specs=(
                _spec("rec_1", symbol="TJ", conditions="industrial", max="125"),
                _spec("rec_2", symbol="TJ", conditions="commercial", max="85"),
            ),
        )
        diff = build_revision_diff(before, after)

        changed = _of(diff, KIND_SPEC, CHANGE_CHANGED)
        assert len(changed) == 1
        assert changed[0].delta.value_si == pytest.approx(20.0)
        assert not diff.unparsed

    def test_records_with_no_printed_value_take_no_part_and_are_still_counted(self):
        """The layout floor emits a valueless record for every neighbouring
        pin-table row. They must not collapse onto one key and bury the real
        changes — and they must not vanish from the report either."""
        before = _side(
            "A",
            specs=(
                _spec("rec_1", symbol="TJ", max="105"),
                _spec("rec_2"),
                _spec("rec_3"),
            ),
        )
        after = _side(
            "B", HASH_B,
            specs=(_spec("rec_1", symbol="TJ", max="125"), _spec("rec_2")),
        )
        diff = build_revision_diff(before, after)

        assert [c.key for c in diff.of_kind(KIND_SPEC)] == ["TJ"]
        assert not diff.unparsed
        assert any("2 of those spec records print no value" in n for n in diff.notes)
        assert any("1 of those spec records print no value" in n for n in diff.notes)


# --- sections -----------------------------------------------------------------


class TestSectionChanges:
    def test_retitle_page_shift_and_addition_are_three_distinct_facts(self):
        before = _side(
            "A",
            sections=(
                _section("4.1", "Electrical Characteristics", 4),
                _section("5", "Pin Functions", 9),
            ),
        )
        after = _side(
            "B", HASH_B,
            sections=(
                _section("4.1", "Electrical Characteristics", 4, doc_hash=HASH_B),
                _section("4.2", "Thermal Information", 6, doc_hash=HASH_B),
                _section("5", "Pin Configuration and Functions", 10, doc_hash=HASH_B),
            ),
        )
        diff = build_revision_diff(before, after)

        kinds = [(c.change, c.key) for c in diff.of_kind(KIND_SECTION)]
        assert ("added", "4.2") in kinds
        assert (CHANGE_RETITLED, "5") in kinds
        assert (CHANGE_PAGE_SHIFTED, "5") in kinds
        # the unchanged section says nothing at all
        assert not [c for c in diff.of_kind(KIND_SECTION) if c.key == "4.1"]
        retitle = next(c for c in diff.of_kind(KIND_SECTION) if c.change == CHANGE_RETITLED)
        assert retitle.before.verbatim == "Pin Functions"
        assert retitle.after.verbatim == "Pin Configuration and Functions"
        shift = next(
            c for c in diff.of_kind(KIND_SECTION) if c.change == CHANGE_PAGE_SHIFTED
        )
        assert (shift.before.verbatim, shift.after.verbatim) == ("p.9", "p.10")

    def test_a_removed_section_is_not_a_retitle_of_the_one_after_it(self):
        before = _side("A", sections=(_section("7", "JESD204C Interface", 20),))
        after = _side("B", HASH_B, sections=(_section("8", "SPI", 22, doc_hash=HASH_B),))
        diff = build_revision_diff(before, after)

        assert [(c.change, c.key) for c in diff.of_kind(KIND_SECTION)] == [
            (CHANGE_ADDED, "8"),
            (CHANGE_REMOVED, "7"),
        ]

    def test_unnumbered_sections_align_on_their_title(self):
        before = _side("A", sections=(_section("", "Revision History", 30),))
        after = _side(
            "B", HASH_B, sections=(_section("", "Revision History", 32, doc_hash=HASH_B),)
        )
        diff = build_revision_diff(before, after)

        changes = diff.of_kind(KIND_SECTION)
        assert [c.change for c in changes] == [CHANGE_PAGE_SHIFTED]
        assert changes[0].aligned_on == "section-title"


# --- pins ---------------------------------------------------------------------


class TestPinChanges:
    def test_a_renamed_pin_is_one_pin_not_two(self):
        before = _side("A", pins=(_pin("pin_1", "A2", "VDD"),))
        after = _side("B", HASH_B, pins=(_pin("pin_1", "A2", "VDD1P8"),))
        diff = build_revision_diff(before, after)

        changes = diff.of_kind(KIND_PIN)
        assert [c.change for c in changes] == [CHANGE_RENAMED]
        assert changes[0].key == "A2"
        assert (changes[0].before.verbatim, changes[0].after.verbatim) == (
            "VDD", "VDD1P8",
        )
        assert FLAG_REVIEW in changes[0].flags

    def test_added_and_removed_pins_and_a_changed_type(self):
        before = _side(
            "A",
            pins=(_pin("pin_1", "A4", "NC", type=PinType.NC), _pin("pin_2", "A1", "GND")),
        )
        after = _side(
            "B", HASH_B,
            pins=(
                _pin("pin_1", "B3", "SYNC", type=PinType.DIGITAL),
                _pin("pin_2", "A1", "GND", type=PinType.GROUND),
            ),
        )
        diff = build_revision_diff(before, after)

        by_change = {(c.change, c.key) for c in diff.of_kind(KIND_PIN)}
        assert (CHANGE_ADDED, "B3") in by_change
        assert (CHANGE_REMOVED, "A4") in by_change
        assert (CHANGE_CHANGED, "A1") in by_change
        typed = next(c for c in diff.of_kind(KIND_PIN) if c.change == CHANGE_CHANGED)
        assert typed.field == "type"
        assert (typed.before.verbatim, typed.after.verbatim) == ("power", "ground")


# --- registers and bit fields -------------------------------------------------


class TestRegisterChanges:
    def test_reset_change_is_called_out_and_never_subtracted(self):
        before = _side("A", registers=(_register("reg_1", "0x2", 2, "R2", "0x0223"),))
        after = _side(
            "B", HASH_B, registers=(_register("reg_1", "0x2", 2, "R2", "0x0233"),)
        )
        diff = build_revision_diff(before, after)

        changes = diff.of_kind(KIND_REGISTER)
        assert [c.change for c in changes] == [CHANGE_RESET]
        assert changes[0].field == "reset"
        assert (changes[0].before.verbatim, changes[0].after.verbatim) == (
            "0x0223", "0x0233",
        )
        # a bit pattern is not a magnitude: nothing here is on the numeric layer
        assert changes[0].delta is None
        assert changes[0].before.value_si is None
        assert changes[0].after.value_si is None
        assert any("0x0223" in line for line in diff.review_by_hand)

    def test_a_register_the_document_states_no_reset_for_reads_as_none_stated(self):
        before = _side("A", registers=(_register("reg_1", "0x2", 2, "R2"),))
        after = _side(
            "B", HASH_B, registers=(_register("reg_1", "0x2", 2, "R2", "0x0000"),)
        )
        diff = build_revision_diff(before, after)

        changes = diff.of_kind(KIND_REGISTER)
        assert changes[0].before.verbatim == "(none stated)"
        assert changes[0].after.verbatim == "0x0000"

    def test_addresses_align_by_value_not_by_notation(self):
        before = _side("A", registers=(_register("reg_1", "0x1A04", 6660, "TXDIG"),))
        after = _side(
            "B", HASH_B, registers=(_register("reg_1", "0x1a04", 6660, "TX_DIGITAL"),)
        )
        diff = build_revision_diff(before, after)

        changes = diff.of_kind(KIND_REGISTER)
        assert [c.change for c in changes] == [CHANGE_RENAMED]

    def test_bit_field_range_and_reset_moves_are_their_own_changes(self):
        before = _side(
            "A",
            registers=(
                _register(
                    "reg_1", "0x19", 25, "R25", "0x0000",
                    fields=[_field("CLK_MUX", "2:0", "0x0"), _field("SPARE", "7:3")],
                ),
            ),
        )
        after = _side(
            "B", HASH_B,
            registers=(
                _register(
                    "reg_1", "0x19", 25, "R25", "0x0000",
                    fields=[_field("CLK_MUX", "3:1", "0x1"), _field("SYNC_EN", "0:0")],
                ),
            ),
        )
        diff = build_revision_diff(before, after)

        fields = {(c.change, c.key, c.field) for c in diff.of_kind(KIND_FIELD)}
        assert (CHANGE_CHANGED, "0x19.CLK_MUX", "bits") in fields
        assert (CHANGE_RESET, "0x19.CLK_MUX", "reset") in fields
        assert (CHANGE_ADDED, "0x19.SYNC_EN", "") in fields
        assert (CHANGE_REMOVED, "0x19.SPARE", "") in fields
        # the register itself did not move, so it reports nothing
        assert not diff.of_kind(KIND_REGISTER)
        bits = next(c for c in diff.of_kind(KIND_FIELD) if c.field == "bits")
        assert (bits.before.verbatim, bits.after.verbatim) == ("2:0", "3:1")
        assert bits.delta is None


# --- determinism and empty diffs ----------------------------------------------


class TestDeterminism:
    def test_identical_revisions_produce_an_empty_diff_not_noise(self):
        specs = (
            _spec("rec_1", symbol="TJ", max="105"),
            _spec("rec_2", symbol="Noise", typ="See Figure 7"),
        )
        pins = (_pin("pin_1", "A1", "GND"),)
        registers = (_register("reg_1", "0x2", 2, "R2", "0x0223"),)
        sections = (_section("4.1", "Electrical Characteristics", 4),)
        before = _side("A", specs=specs, pins=pins, registers=registers, sections=sections)
        after = _side("A", specs=specs, pins=pins, registers=registers, sections=sections)

        diff = build_revision_diff(before, after)

        assert diff.changes == []
        assert diff.identical is True
        assert diff.review_by_hand == []
        assert "no differences" in diff.empty_reason
        assert "determinism check" in diff.empty_reason

    def test_two_runs_over_the_same_input_produce_the_same_diff(self):
        before = _side("A", specs=(_spec("rec_1", symbol="TJ", max="105"),))
        after = _side("B", HASH_B, specs=(_spec("rec_1", symbol="TJ", max="125"),))

        first = build_revision_diff(before, after).model_dump_json()
        second = build_revision_diff(before, after).model_dump_json()
        assert first == second


# --- rendering ----------------------------------------------------------------


class TestRendering:
    def test_report_carries_its_rule_version_and_marks_every_derived_number(self):
        before = _side("A", specs=(_spec("rec_1", symbol="TJ", max="105"),))
        after = _side("B", HASH_B, specs=(_spec("rec_1", symbol="TJ", max="125"),))
        diff = build_revision_diff(before, after)

        text = render_revision_diff(diff)
        assert text.startswith(banner(diff.card_version))
        assert "REVPART — revision diff: A (SBAS999A) -> B (SBAS999B)" in text
        assert "*(derived)*" in text
        assert "125 °C" in text and "105 °C" in text
        assert "docs/datasheet-aa000000-reva" in text

    def test_everything_unscored_has_its_own_heading(self):
        before = _side("A", specs=(_spec("rec_1", symbol="Noise", typ="See Figure 7"),))
        after = _side(
            "B", HASH_B, specs=(_spec("rec_1", symbol="Noise", typ="See Figure 9"),)
        )
        text = render_revision_diff(build_revision_diff(before, after))

        assert REVIEW_HEADING in text
        assert "See Figure 7" in text.split(REVIEW_HEADING)[1]

    def test_an_empty_diff_says_identical_rather_than_showing_nothing(self):
        side = _side("A", specs=(_spec("rec_1", symbol="TJ", max="105"),))
        text = render_revision_diff(build_revision_diff(side, side))

        assert "**No differences.**" in text
        assert "## Specs" not in text


# --- a two-revision corpus on disk --------------------------------------------


def _raw(doc_hash: str, label: str, *, reset: str, page: int) -> RawDocument:
    """A one-section register-map document, published by the real writer."""
    from datasheet_analyzer.models import RECONSTRUCTION_HEADER, TableBlock

    table = TableBlock(
        caption="Table 1-1. Registers",
        headers=["Address", "Acronym", "Features Requiring This Register", "Section"],
        grid=[
            ["0x0", "R0", "Powerdown, Reset, Multiplier Mode Calibration", "Go"],
            ["0x2", "R2", "Multiplier Mode (State Machine Clock)", "Go"],
        ],
        page=page,
        reconstruction=RECONSTRUCTION_HEADER,
    )
    section = SectionNode(
        number="1",
        title="Device Registers",
        page_start=page,
        page_end=page,
        paragraphs=[
            "1.1 R0 Register (Offset = 0x0) [Reset = 0x0000]",
            f"1.2 R2 Register (Offset = 0x2) [Reset = {reset}]",
        ],
        tables=[table],
    )
    return RawDocument(
        source=SourceDocument(
            content_hash=doc_hash,
            path=f"regmap_{label}.pdf",
            part_number="REVPART",
            doc_type=DocType.REGISTER_MAP,
            revision=f"SNAU269{label}",
            revision_label=label,
            page_count=25,
        ),
        sections=[section],
        extractor="pdf_layout",
        extractor_version="test-1",
        extraction_stats=ExtractionStats(backend="pdf_layout"),
    )


@pytest.fixture
def two_revision_part(tmp_path, monkeypatch):
    """A part holding two labelled revisions of one register map, on disk.

    Published by the real writer through the real register builder, so the diff
    reads exactly what a build would have written — and so the two revisions
    coexist under one part directory the way `dsa build --rev` files them.
    """
    from datasheet_analyzer.acquire.inventory import save_inventory

    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    part_dir = settings.parts_dir / "REVPART"

    raws = [
        _raw(HASH_A, "A", reset="0x0223", page=2),
        _raw(HASH_B, "B", reset="0x0233", page=3),
    ]
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {}) for raw in raws],
        "# REVPART\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        registersets=[build_registerset(raw, "REVPART") for raw in raws],
    )
    save_inventory([raw.source for raw in raws], part_dir)
    clear_index_cache()
    return part_dir, settings


class TestTwoRevisionCorpus:
    def test_both_revisions_coexist_and_stay_independently_queryable(
        self, two_revision_part
    ):
        """The ticket's first criterion, on disk: two document directories, two
        register sets, and a lookup that reaches both with distinct citations."""
        part_dir, _ = two_revision_part
        docs = sorted(d.name for d in (part_dir / "docs").iterdir())
        assert docs == [
            f"register_map-{HASH_A[:8]}-reva",
            f"register_map-{HASH_B[:8]}-revb",
        ]
        for doc in docs:
            assert (part_dir / "docs" / doc / "registers.json").exists()

        hits = Retriever.for_part(part_dir).registers(addr="0x2")
        assert len(hits) == 2
        assert sorted(hit.citation.doc for hit in hits) == docs
        assert sorted(hit.record.reset.verbatim for hit in hits) == ["0x0223", "0x0233"]

    def test_the_diff_finds_the_reset_move_and_the_page_shift(self, two_revision_part):
        part_dir, _ = two_revision_part
        pair, error = RevisionPair.for_part(part_dir, before="A", after="B")
        assert error == ""
        diff = pair.diff()

        resets = [c for c in diff.of_kind(KIND_REGISTER) if c.change == CHANGE_RESET]
        assert [(c.before.verbatim, c.after.verbatim) for c in resets] == [
            ("0x0223", "0x0233")
        ]
        shifts = [c for c in diff.of_kind(KIND_SECTION)]
        assert [c.change for c in shifts] == [CHANGE_PAGE_SHIFTED]
        assert diff.before_doc.endswith("-reva") and diff.after_doc.endswith("-revb")

    def test_every_record_value_carries_a_source_that_resolves(
        self, two_revision_part, resolve_source
    ):
        """Invariant 8's round trip, on the artifact that most needs it: both
        revisions publish a `reg_1`, so a reference that named neither the part
        nor the document would resolve to a confident, wrong record."""
        part_dir, _ = two_revision_part
        pair, _ = RevisionPair.for_part(part_dir, before="A", after="B")
        diff = pair.diff()

        checked = 0
        for change in diff.changes:
            for value in (change.before, change.after):
                if value is None or not value.source:
                    continue
                if not value.source.endswith(".json") and "#" not in value.source:
                    continue  # a section is a file, not a record (see build.py)
                assert value.source.startswith("parts/REVPART/docs/")
                assert resolve_source(part_dir, value.source) is not None
                checked += 1
        assert checked >= 1

    def test_selecting_by_printed_revision_or_by_document_directory(
        self, two_revision_part
    ):
        part_dir, _ = two_revision_part
        for before, after in (
            ("SNAU269A", "SNAU269B"),
            (f"register_map-{HASH_A[:8]}-reva", f"register_map-{HASH_B[:8]}-revb"),
        ):
            pair, error = RevisionPair.for_part(part_dir, before=before, after=after)
            assert error == "", error
            assert pair.before.label == "A" and pair.after.label == "B"

    def test_an_unknown_selector_lists_what_the_part_actually_holds(
        self, two_revision_part
    ):
        part_dir, _ = two_revision_part
        pair, error = RevisionPair.for_part(part_dir, before="A", after="Z")
        assert pair is None
        assert "'Z'" in error
        assert "label A" in error and "label B" in error

    def test_defaulting_picks_the_two_documents_in_registration_order(
        self, two_revision_part
    ):
        part_dir, _ = two_revision_part
        pair, error = RevisionPair.for_part(part_dir)
        assert error == ""
        assert (pair.before.label, pair.after.label) == ("A", "B")

    def test_a_document_diffed_against_itself_is_the_determinism_check(
        self, two_revision_part
    ):
        part_dir, _ = two_revision_part
        pair, error = RevisionPair.for_part(part_dir, before="A", after="A")
        assert error == ""
        diff = pair.diff()
        assert diff.identical and diff.changes == []
        assert "same document" in diff.empty_reason


class TestSelectRevision:
    def test_an_ambiguous_selector_names_both_candidates(self, two_revision_part):
        from datasheet_analyzer.retrieve.revdiff import revision_documents

        part_dir, _ = two_revision_part
        documents = revision_documents(__import__(
            "datasheet_analyzer.retrieve", fromlist=["CorpusIndex"]
        ).CorpusIndex.load(part_dir))
        # "register_map-" prefixes both document directories
        chosen, error = select_revision(documents, "register_map-")
        assert chosen is None
        assert "matches 2 documents" in error


# --- the command --------------------------------------------------------------


class TestCli:
    def test_diff_rev_writes_the_report_and_prints_it(self, two_revision_part, capsys):
        part_dir, _ = two_revision_part
        assert cli.main(["diff-rev", "--part", "REVPART", "--from", "A", "--to", "B"]) == 0

        written = part_dir / "REVISION_DIFF.md"
        assert written.exists()
        text = written.read_text(encoding="utf-8")
        assert "0x0223" in text and "0x0233" in text
        out = capsys.readouterr()
        assert "0x0233" in out.out
        assert "REVISION_DIFF.md" in out.err

    def test_json_carries_the_schema_version_and_the_envelopes(
        self, two_revision_part, capsys
    ):
        assert cli.main(
            ["diff-rev", "--part", "REVPART", "--from", "A", "--to", "B", "--json"]
        ) == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["schema_version"] == REVDIFF_SCHEMA_VERSION
        assert payload["part_number"] == "REVPART"
        reset = next(c for c in payload["changes"] if c["change"] == CHANGE_RESET)
        assert reset["before"]["derivation"] == "copy_cell"
        assert reset["delta"] is None
        assert FLAG_REVIEW in reset["flags"]

    def test_no_write_leaves_the_corpus_untouched(self, two_revision_part):
        part_dir, _ = two_revision_part
        assert cli.main(
            ["diff-rev", "--part", "REVPART", "--from", "A", "--to", "B", "--no-write"]
        ) == 0
        assert not (part_dir / "REVISION_DIFF.md").exists()

    def test_an_unbuilt_part_names_the_build_command(self, two_revision_part, capsys):
        assert cli.main(["diff-rev", "--part", "NOSUCH"]) == 2
        err = capsys.readouterr().err
        assert "no corpus for NOSUCH" in err
        assert "--rev" in err

    def test_a_part_with_one_document_says_how_to_add_the_other(
        self, tmp_path, monkeypatch, capsys
    ):
        from datasheet_analyzer.acquire.inventory import save_inventory

        settings = Settings(
            parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache"
        ).resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        part_dir = settings.parts_dir / "SOLO"
        raw = _raw(HASH_A, "A", reset="0x0223", page=2)
        write_corpus(
            part_dir,
            [(raw, build_section_plans(raw), {})],
            "# SOLO\n",
            pipeline_version=PIPELINE_VERSION,
            vendor="ti",
            registersets=[build_registerset(raw, "SOLO")],
        )
        save_inventory([raw.source], part_dir)
        clear_index_cache()

        assert cli.main(["diff-rev", "--part", "SOLO"]) == 2
        err = capsys.readouterr().err
        assert "one built document" in err
        assert "dsa build" in err and "--rev" in err


# --- the document directory ---------------------------------------------------


class TestRevisionDirectoryNames:
    def test_a_label_suffixes_the_directory_and_no_label_changes_nothing(self):
        plain = SourceDocument(
            content_hash=HASH_A, path="x.pdf", doc_type=DocType.DATASHEET
        )
        labelled = plain.model_copy(update={"revision_label": "Rev. F"})
        assert doc_dir_name_for_source(plain) == f"datasheet-{HASH_A[:8]}"
        assert doc_dir_name_for_source(labelled) == f"datasheet-{HASH_A[:8]}-revrev-f"

    def test_a_label_of_only_punctuation_is_not_a_directory_name(self):
        assert revision_slug("  --  ") == ""
        source = SourceDocument(
            content_hash=HASH_A, path="x.pdf", doc_type=DocType.DATASHEET,
            revision_label="--",
        )
        assert doc_dir_name_for_source(source) == f"datasheet-{HASH_A[:8]}"


class TestWriteRevisionDiff:
    def test_the_written_file_is_the_rendered_report(self, tmp_path):
        before = _side("A", specs=(_spec("rec_1", symbol="TJ", max="105"),))
        after = _side("B", HASH_B, specs=(_spec("rec_1", symbol="TJ", max="125"),))
        markdown = render_revision_diff(build_revision_diff(before, after))

        path = write_revision_diff(tmp_path / "PART", markdown)
        assert path == Path(tmp_path / "PART" / "REVISION_DIFF.md")
        assert path.read_text(encoding="utf-8") == markdown
