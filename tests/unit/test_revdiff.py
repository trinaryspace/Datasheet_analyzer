"""Revision diff (phase 7, ticket 03) - `dsa diff-rev`, rule by rule.

Ported from `feat/phase7-reach-trust` onto this branch's layout. What is proven
here is every rule on its own, and - the point of a rule test - that each one
fails for the right reason:

- a parameter the vendor **renamed** is one `changed` row, not a removal plus an
  addition, because the alias lexicon claims both spellings;
- a **numeric delta exists only where both sides parsed** the same printed column
  into the same SI base; everything else is quoted verbatim under "review by
  hand" and carries no score, no sign and no direction;
- a **section retitle, a page shift and an addition are three different facts**,
  and a numbered section that was reworded stays the same section;
- a **pin rename is not a pin removed plus a pin added** - the designator is the
  identity, because that is what the package fixes;
- a **register reset change is called out on its own**, and is never subtracted:
  a reset is a bit pattern, and its bit fields' ranges are diffed beside it
  because a field that moved from `2:0` to `3:1` misconfigures silicon silently;
- an **ambiguous alignment is refused**, listed with its printed values, and
  never reported as added + removed;
- a diff of a document **against itself is empty and says so**, which is the
  determinism check;
- every value carries a **document-qualified `source`** that resolves, because
  both revisions of one part publish a `rec_1`.

Two things differ from the source lineage and are asserted here rather than
assumed. The pair on disk is two **register maps**, not two datasheets: on this
branch `acquire.inventory.single_datasheet` builds one datasheet per part, so
two datasheet revisions do not coexist under one part and `dsa build --rev` does
not make them. And `revision_label` lives on `LibraryDocument`, not on
`SourceDocument`, whose shape is frozen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.config import PIPELINE_VERSION, REVDIFF_SCHEMA_VERSION, Settings
from datasheet_analyzer.models import (
    BitField,
    BitRange,
    Confidence,
    DocType,
    ExtractionStats,
    LibraryDocument,
    PinRecord,
    RawDocument,
    RegisterRecord,
    RegisterValue,
    RevisionState,
    SectionFile,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecUnit,
    Staleness,
)
from datasheet_analyzer.publish import write_corpus, write_revision_diff
from datasheet_analyzer.retrieve import clear_index_cache
from datasheet_analyzer.retrieve.revdiff import RevisionPair, select_revision
from datasheet_analyzer.revdiff import (
    CHANGE_ADDED,
    CHANGE_CHANGED,
    CHANGE_PAGE_SHIFTED,
    CHANGE_REMOVED,
    CHANGE_RENAMED,
    CHANGE_RESET,
    CHANGE_RETITLED,
    DERIVATION_PIN_TYPE,
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

HASH_A = "aa" + "0" * 62
HASH_B = "bb" + "0" * 62


# --- literal record helpers ---------------------------------------------------


def _spec(row: int, **kwargs) -> SpecRecord:
    """One spec record. `row` fixes the computed id (`rec_s4.1-t0-r<row>`)."""
    defaults = {
        "section": "4.1",
        "section_key": "4.1",
        "table_index": 0,
        "row_index": row,
        "unit": SpecUnit(verbatim="\u00b0C", canonical="\u00b0C"),
        "page": 4,
        "confidence": Confidence.HIGH,
    }
    return SpecRecord(**{**defaults, **kwargs})


def _pin(row: int, pin: str, name: str, **kwargs) -> PinRecord:
    defaults = {
        "pin": pin,
        "name": name,
        "type": "power",
        "section": "6",
        "table_index": 0,
        "row_index": row,
        "page": 9,
        "confidence": Confidence.HIGH,
    }
    return PinRecord(**{**defaults, **kwargs})


def _register(
    row: int,
    addr: str,
    value: int | None,
    name: str,
    reset: str = "",
    fields: list[BitField] | None = None,
    **kwargs,
) -> RegisterRecord:
    defaults = {
        "address": RegisterValue(verbatim=addr, value=value),
        "name": name,
        "section": "1",
        "table_index": 0,
        "row_index": row,
        "doc_key": "d0",
        "page": 2,
        "confidence": Confidence.HIGH,
        "fields": fields or [],
        "reset": RegisterValue(verbatim=reset) if reset else RegisterValue(),
    }
    return RegisterRecord(**{**defaults, **kwargs})


def _field(name: str, bits: str, reset: str = "") -> BitField:
    hi, _, lo = bits.partition(":")
    return BitField(
        name=name,
        bits=BitRange(verbatim=bits, hi=int(hi), lo=int(lo or hi)),
        reset=reset,
        page=3,
        confidence=Confidence.HIGH,
    )


def _section(
    number: str, title: str, start: int, end: int | None = None, doc_hash: str = HASH_A
) -> SectionFile:
    return SectionFile(
        number=number,
        title=title,
        file=f"docs/datasheet-{doc_hash[:8]}/sections/{number or title}.md",
        doc_hash=doc_hash,
        page_start=start,
        page_end=end if end is not None else start,
    )


def _side(label: str, doc_hash: str = HASH_A, **kwargs) -> RevisionSide:
    doc = f"datasheet-{doc_hash[:8]}"
    return RevisionSide(
        part_number="REVPART",
        label=label,
        doc=doc,
        ref_base=f"docs/{doc}",
        revision=f"SBAS999{label}",
        **kwargs,
    )


def _of(diff, kind: str, change: str = "") -> list:
    return [c for c in diff.of_kind(kind) if not change or c.change == change]


# --- specs --------------------------------------------------------------------


class TestSpecAlignment:
    def test_renamed_parameter_is_one_changed_row_not_a_removal_and_addition(self):
        """The ticket's second criterion: the alias lexicon claims both spellings.

        Rev A prints `TJ`, rev B prints the designer's words. Reporting that as
        `TJ removed` + `Junction temperature added` is how a review misses the
        20 degrees the vendor actually moved.
        """
        before = _side("A", specs=(_spec(0, symbol="TJ", max="105"),))
        after = _side(
            "B",
            HASH_B,
            specs=(_spec(0, symbol="", name="Junction temperature", max="125"),),
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
                _spec(0, symbol="TJ", max="105"),
                _spec(1, symbol="OutputNoise", typ="See Figure 7"),
            ),
        )
        after = _side(
            "B",
            HASH_B,
            specs=(
                _spec(0, symbol="TJ", max="125"),
                _spec(1, symbol="OutputNoise", typ="See Figure 9"),
            ),
        )
        diff = build_revision_diff(before, after)

        scored = [c for c in diff.changes if c.delta is not None]
        unscored = [c for c in diff.changes if c.delta is None]
        assert len(scored) == 1
        assert scored[0].key == "TJ"
        assert scored[0].delta.value_si == pytest.approx(20.0)
        assert scored[0].delta.derivation == "si_delta:max"
        assert scored[0].delta.source == scored[0].after.source
        assert scored[0].delta.sources == [scored[0].before.source]
        assert len(unscored) == 1
        assert FLAG_REVIEW in unscored[0].flags
        assert diff.n_deltas == 1

    def test_unscored_change_is_quoted_verbatim_under_review_by_hand(self):
        before = _side("A", specs=(_spec(0, symbol="OutputNoise", typ="See Figure 7"),))
        after = _side("B", HASH_B, specs=(_spec(0, symbol="OutputNoise", typ="See Figure 9"),))
        diff = build_revision_diff(before, after)

        assert len(diff.review_by_hand) == 1
        line = diff.review_by_hand[0]
        assert "See Figure 7" in line and "See Figure 9" in line

    def test_a_reprinted_prefix_is_scaled_and_the_unit_move_is_its_own_row(self):
        """1.8 V -> 1900 mV is +0.1 V; the unit move is a second, unscored row."""
        volts = SpecUnit(verbatim="V", canonical="V")
        millivolts = SpecUnit(verbatim="mV", canonical="mV")
        before = _side("A", specs=(_spec(0, symbol="VDD", typ="1.8", unit=volts),))
        after = _side("B", HASH_B, specs=(_spec(0, symbol="VDD", typ="1900", unit=millivolts),))
        diff = build_revision_diff(before, after)

        by_field = {c.field: c for c in _of(diff, KIND_SPEC, CHANGE_CHANGED)}
        assert set(by_field) == {"typ", "unit"}
        assert by_field["typ"].delta is not None
        assert by_field["typ"].delta.value_si == pytest.approx(0.1)
        assert by_field["typ"].delta.unit_si == "V"
        assert by_field["unit"].delta is None
        assert FLAG_REVIEW in by_field["unit"].flags

    def test_a_changed_base_is_a_change_to_review_and_never_a_delta(self):
        """1.8 V -> 1.9 A is not a 0.1 of anything."""
        volts = SpecUnit(verbatim="V", canonical="V")
        amps = SpecUnit(verbatim="A", canonical="A")
        before = _side("A", specs=(_spec(0, symbol="VDD", typ="1.8", unit=volts),))
        after = _side("B", HASH_B, specs=(_spec(0, symbol="VDD", typ="1.9", unit=amps),))
        diff = build_revision_diff(before, after)

        typ = next(c for c in diff.changes if c.field == "typ")
        assert typ.delta is None
        assert "different bases" in typ.note
        assert FLAG_REVIEW in typ.flags

    def test_added_and_removed_rows_are_both_reported_with_what_they_printed(self):
        before = _side("A", specs=(_spec(0, symbol="GainError", max="2"),))
        after = _side("B", HASH_B, specs=(_spec(0, symbol="TurnOnTime", max="30"),))
        diff = build_revision_diff(before, after)

        added = _of(diff, KIND_SPEC, CHANGE_ADDED)
        removed = _of(diff, KIND_SPEC, CHANGE_REMOVED)
        assert len(added) == 1 and len(removed) == 1
        assert "30" in added[0].summary
        assert "2" in removed[0].summary
        assert added[0].delta is None and removed[0].delta is None

    def test_ambiguous_parameter_is_refused_not_reported_as_added_and_removed(self):
        """Two rows per side sharing no printed identity cell: listed, not guessed."""
        before = _side(
            "A",
            specs=(
                _spec(0, symbol="TJ", conditions="commercial", max="105"),
                _spec(1, symbol="TJ", conditions="industrial", max="115"),
            ),
        )
        after = _side(
            "B",
            HASH_B,
            specs=(
                _spec(0, symbol="TJ", conditions="grade 1", max="125"),
                _spec(1, symbol="TJ", conditions="grade 2", max="135"),
            ),
        )
        diff = build_revision_diff(before, after)

        assert not _of(diff, KIND_SPEC, CHANGE_ADDED)
        assert not _of(diff, KIND_SPEC, CHANGE_REMOVED)
        assert any("uncomparable: TJ" in line for line in diff.unparsed)
        listed = "\n".join(diff.unparsed)
        for printed in ("105", "115", "125", "135"):
            assert printed in listed

    def test_matching_conditions_still_pair_inside_an_ambiguous_key(self):
        """One pair shares a printed identity cell exactly; only the rest is refused."""
        before = _side(
            "A",
            specs=(
                _spec(0, symbol="TJ", conditions="commercial", max="105"),
                _spec(1, symbol="TJ", conditions="industrial", max="115"),
            ),
        )
        after = _side(
            "B",
            HASH_B,
            specs=(
                _spec(0, symbol="TJ", conditions="commercial", max="125"),
                _spec(1, symbol="TJ", conditions="automotive", max="135"),
            ),
        )
        diff = build_revision_diff(before, after)

        changed = _of(diff, KIND_SPEC, CHANGE_CHANGED)
        assert len(changed) == 1
        assert changed[0].delta.value_si == pytest.approx(20.0)
        assert diff.unparsed

    def test_records_with_no_printed_value_take_no_part_and_are_still_counted(self):
        """The layout floor valueless rows never enter the alignment, and are stated."""
        before = _side(
            "A",
            specs=(
                _spec(0, symbol="TJ", max="105"),
                _spec(1, symbol="", name="Supply"),
                _spec(2, symbol="", name="Input"),
            ),
        )
        after = _side("B", HASH_B, specs=(_spec(0, symbol="TJ", max="125"),))
        diff = build_revision_diff(before, after)

        assert not _of(diff, KIND_SPEC, CHANGE_REMOVED)
        assert len(_of(diff, KIND_SPEC, CHANGE_CHANGED)) == 1
        assert any("take no part in the alignment" in note for note in diff.notes)
        assert any("2 of those spec records" in note for note in diff.notes)


# --- sections -----------------------------------------------------------------


class TestSectionChanges:
    def test_retitle_page_shift_and_addition_are_three_distinct_facts(self):
        before = _side(
            "A",
            sections=(
                _section("4", "Specifications", 2, 2),
                _section("5", "Detailed Description", 3),
            ),
        )
        after = _side(
            "B",
            HASH_B,
            sections=(
                _section("4", "Specifications", 2, 3, doc_hash=HASH_B),
                _section("4.2", "Thermal Information", 3, doc_hash=HASH_B),
                _section("5", "Application Information", 4, doc_hash=HASH_B),
            ),
        )
        diff = build_revision_diff(before, after)

        kinds = {(c.key, c.change) for c in diff.of_kind(KIND_SECTION)}
        assert ("4", CHANGE_PAGE_SHIFTED) in kinds
        assert ("4.2", CHANGE_ADDED) in kinds
        assert ("5", CHANGE_RETITLED) in kinds
        assert ("5", CHANGE_PAGE_SHIFTED) in kinds
        assert not _of(diff, KIND_SECTION, CHANGE_REMOVED)
        # A section is a file, not a record: its reference is that file.
        retitle = next(c for c in diff.of_kind(KIND_SECTION) if c.change == CHANGE_RETITLED)
        assert retitle.after.source.endswith("/sections/5.md")
        assert "#" not in retitle.after.source

    def test_a_removed_section_is_not_a_retitle_of_the_one_after_it(self):
        before = _side("A", sections=(_section("7", "Layout", 9),))
        after = _side("B", HASH_B, sections=(_section("8", "Ordering", 10, doc_hash=HASH_B),))
        diff = build_revision_diff(before, after)

        assert {(c.key, c.change) for c in diff.of_kind(KIND_SECTION)} == {
            ("7", CHANGE_REMOVED),
            ("8", CHANGE_ADDED),
        }

    def test_unnumbered_sections_align_on_their_title(self):
        before = _side("A", sections=(_section("", "Revision History", 12),))
        after = _side(
            "B", HASH_B, sections=(_section("", "Revision History", 14, doc_hash=HASH_B),)
        )
        diff = build_revision_diff(before, after)

        changes = diff.of_kind(KIND_SECTION)
        assert len(changes) == 1
        assert changes[0].change == CHANGE_PAGE_SHIFTED
        assert changes[0].aligned_on == "section-title"


# --- pins ---------------------------------------------------------------------


class TestPinChanges:
    def test_a_renamed_pin_is_one_pin_not_two(self):
        """The designator is the identity: the package fixed it, so the ball did not move."""
        before = _side("A", pins=(_pin(0, "A2", "VDD"),))
        after = _side("B", HASH_B, pins=(_pin(0, "A2", "VDD1P8"),))
        diff = build_revision_diff(before, after)

        changes = diff.of_kind(KIND_PIN)
        assert len(changes) == 1
        assert changes[0].change == CHANGE_RENAMED
        assert changes[0].key == "A2"
        assert changes[0].aligned_on == "pin-designator"
        assert changes[0].delta is None

    def test_added_and_removed_pins_and_a_changed_type(self):
        before = _side("A", pins=(_pin(0, "A4", "NC"), _pin(1, "C1", "CLK", type="power")))
        after = _side(
            "B",
            HASH_B,
            pins=(_pin(0, "B3", "GPIO0"), _pin(1, "C1", "CLK", type="input")),
        )
        diff = build_revision_diff(before, after)

        by = {(c.key, c.change) for c in diff.of_kind(KIND_PIN)}
        assert ("B3", CHANGE_ADDED) in by
        assert ("A4", CHANGE_REMOVED) in by
        retyped = next(c for c in diff.of_kind(KIND_PIN) if c.key == "C1" and c.field == "type")
        assert retyped.before.verbatim == "power"
        assert retyped.after.verbatim == "input"
        # A pin type is a lexicon classification, so its envelope names that rule
        # rather than claiming a page printed the word.
        assert retyped.after.derivation == DERIVATION_PIN_TYPE


# --- registers ----------------------------------------------------------------


class TestRegisterChanges:
    def test_reset_change_is_called_out_and_never_subtracted(self):
        """A reset is a bit pattern; +16 between two of them means nothing."""
        before = _side("A", registers=(_register(0, "0x2", 2, "R2", reset="0x0223"),))
        after = _side("B", HASH_B, registers=(_register(0, "0x2", 2, "R2", reset="0x0233"),))
        diff = build_revision_diff(before, after)

        changes = diff.of_kind(KIND_REGISTER)
        assert len(changes) == 1
        assert changes[0].change == CHANGE_RESET
        assert changes[0].delta is None
        assert FLAG_REVIEW in changes[0].flags
        assert changes[0].before.value_si is None and changes[0].after.value_si is None
        assert "never subtracted" in changes[0].note
        assert "0x0223" in changes[0].summary and "0x0233" in changes[0].summary

    def test_a_register_the_document_states_no_reset_for_reads_as_none_stated(self):
        before = _side("A", registers=(_register(0, "0x4", 4, "R4"),))
        after = _side("B", HASH_B, registers=(_register(0, "0x4", 4, "R4", reset="0x1"),))
        diff = build_revision_diff(before, after)

        change = diff.of_kind(KIND_REGISTER)[0]
        assert change.before.verbatim == "(none stated)"
        assert "0x0" not in change.before.verbatim

    def test_addresses_align_by_value_not_by_notation(self):
        """`0x1A04`, `0x1a04` and `6660` are one register."""
        before = _side("A", registers=(_register(0, "0x1A04", 6660, "CTRL", reset="0x0"),))
        after = _side("B", HASH_B, registers=(_register(0, "6660", 6660, "CTRL", reset="0x1"),))
        diff = build_revision_diff(before, after)

        assert not _of(diff, KIND_REGISTER, CHANGE_ADDED)
        assert not _of(diff, KIND_REGISTER, CHANGE_REMOVED)
        assert _of(diff, KIND_REGISTER, CHANGE_RESET)

    def test_bit_field_range_and_reset_moves_are_their_own_changes(self):
        """A field that moved from 2:0 to 3:1 compiles and misconfigures silicon."""
        before = _side(
            "A",
            registers=(
                _register(
                    0,
                    "0x2",
                    2,
                    "R2",
                    reset="0x0",
                    fields=[_field("MULT", "2:0", reset="0x1"), _field("OLD", "7:4")],
                ),
            ),
        )
        after = _side(
            "B",
            HASH_B,
            registers=(
                _register(
                    0,
                    "0x2",
                    2,
                    "R2",
                    reset="0x0",
                    fields=[
                        _field("MULT", "3:1", reset="0x2"),
                        _field("NEW", "7:4"),
                    ],
                ),
            ),
        )
        diff = build_revision_diff(before, after)

        fields = {(c.key, c.field or c.change) for c in diff.of_kind(KIND_FIELD)}
        assert ("0x2.MULT", "bits") in fields
        assert ("0x2.MULT", "reset") in fields
        assert ("0x2.NEW", CHANGE_ADDED) in fields
        assert ("0x2.OLD", CHANGE_REMOVED) in fields
        # A bit field has no id of its own: it cites the register that holds it.
        moved = next(c for c in diff.of_kind(KIND_FIELD) if c.field == "bits")
        assert moved.after.source.endswith("/registers.json#reg_dd0-t0-r0")
        assert moved.delta is None

    def test_ambiguous_register_rows_are_listed_not_guessed(self):
        before = _side(
            "A",
            registers=(
                _register(0, "0x2", 2, "R2A", reset="0x1"),
                _register(1, "0x2", 2, "R2B", reset="0x2"),
            ),
        )
        after = _side(
            "B",
            HASH_B,
            registers=(
                _register(0, "0x2", 2, "R2C", reset="0x3"),
                _register(1, "0x2", 2, "R2D", reset="0x4"),
            ),
        )
        diff = build_revision_diff(before, after)

        assert not diff.of_kind(KIND_REGISTER)
        assert any("uncomparable: register 0x2" in line for line in diff.unparsed)


# --- determinism and rendering ------------------------------------------------


class TestDeterminism:
    def test_identical_revisions_produce_an_empty_diff_not_noise(self):
        specs = (_spec(0, symbol="TJ", max="105"),)
        sections = (_section("4", "Specifications", 2),)
        before = _side("A", specs=specs, sections=sections)
        after = _side("B", HASH_B, specs=specs, sections=sections)
        diff = build_revision_diff(before, after)

        assert diff.changes == []
        assert diff.identical is True
        assert "no differences" in diff.empty_reason
        assert "Nothing was suppressed" in diff.empty_reason

    def test_diffing_a_revision_against_itself_says_which_empty_it_is(self):
        side = _side("A", specs=(_spec(0, symbol="TJ", max="105"),))
        diff = build_revision_diff(side, side)

        assert diff.identical is True
        assert "same document" in diff.empty_reason
        assert "determinism check" in diff.empty_reason

    def test_two_runs_over_the_same_input_produce_the_same_diff(self):
        before = _side("A", specs=(_spec(0, symbol="TJ", max="105"),))
        after = _side("B", HASH_B, specs=(_spec(0, symbol="TJ", max="125"),))

        first = build_revision_diff(before, after)
        second = build_revision_diff(before, after)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert render_revision_diff(first) == render_revision_diff(second)


class TestRendering:
    def test_report_carries_its_rule_version_and_marks_every_derived_number(self):
        from datasheet_analyzer.config import get_settings

        before = _side("A", specs=(_spec(0, symbol="TJ", max="105"),))
        after = _side("B", HASH_B, specs=(_spec(0, symbol="TJ", max="125"),))
        text = render_revision_diff(build_revision_diff(before, after))

        assert text.startswith(banner(get_settings().card_version))
        assert "*(derived)*" in text
        assert "+20" in text
        assert "p.4" in text

    def test_everything_unscored_has_its_own_heading(self):
        before = _side("A", specs=(_spec(0, symbol="OutputNoise", typ="See Figure 7"),))
        after = _side("B", HASH_B, specs=(_spec(0, symbol="OutputNoise", typ="See Figure 9"),))
        text = render_revision_diff(build_revision_diff(before, after))

        assert REVIEW_HEADING in text
        assert "review by hand" in text
        assert "See Figure 7" in text and "See Figure 9" in text

    def test_an_empty_diff_says_identical_rather_than_showing_nothing(self):
        side = _side("A", specs=(_spec(0, symbol="TJ", max="105"),))
        text = render_revision_diff(build_revision_diff(side, side))

        assert "**No differences.**" in text
        assert "determinism check" in text


# --- a two-revision corpus on disk --------------------------------------------


def _raw(doc_hash: str, label: str, *, path: Path, reset: str, page: int) -> RawDocument:
    """A one-section register-map document, published by the real writer."""
    from datasheet_analyzer.models import RECONSTRUCTION_HEADER, TableBlock

    table = TableBlock(
        caption="Table 1-1. Registers",
        headers=["Address", "Acronym", "Reset", "Access"],
        grid=[
            ["0x0", "R0", "0x0000", "R/W"],
            ["0x2", "R2", reset, "R/W"],
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
            path=str(path),
            part_number="REVPART",
            doc_type=DocType.REGISTER_MAP,
            revision=f"SNAU269{label}",
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

    Register maps, not datasheets, and that is the port's central adaptation:
    `acquire.inventory.single_datasheet` builds one datasheet per part on this
    branch, so a datasheet pair cannot coexist under one part. A companion pair
    can, and does — which is exactly the shape `dsa diff-rev` reads.

    Published by the real writer through the real register builder, so the diff
    reads exactly what a build would have written, and filed into the real
    Library so the `--rev` labels are read back from where they live.
    """
    from datasheet_analyzer.derive.registers import build_registers, write_registerset
    from datasheet_analyzer.library.store import LibraryStore
    from datasheet_analyzer.models import Applicability
    from datasheet_analyzer.publish.writer import doc_dir_name

    settings = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        library_dir=tmp_path / "library",
    ).resolve()
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    part_dir = settings.parts_dir / "REVPART"
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir(parents=True, exist_ok=True)

    raws = []
    for doc_hash, label, reset, page in (
        (HASH_A, "A", "0x0223", 2),
        (HASH_B, "B", "0x0233", 3),
    ):
        pdf = pdfs / f"regmap_{label}.pdf"
        pdf.write_bytes(b"%PDF-1.4 stub")
        raws.append(_raw(doc_hash, label, path=pdf, reset=reset, page=page))

    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {}) for raw in raws],
        "# REVPART\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        shared_docs_dir=None,
    )
    store = LibraryStore(settings.library_dir)
    for raw in raws:
        build = build_registers(raw, "REVPART")
        assert build.registerset is not None
        write_registerset(part_dir / "docs" / doc_dir_name(raw), build.registerset)
        store.put(
            LibraryDocument(
                source=raw.source,
                applicability=Applicability.for_parts(["REVPART"], evidence="test"),
            )
        )
        store.set_revision_label(raw.source.content_hash, raw.source.revision[-1])
    clear_index_cache()
    return part_dir, settings


class TestTwoRevisionCorpus:
    def test_both_revisions_coexist_and_stay_independently_queryable(self, two_revision_part):
        """Two document directories, two register sets, one part."""
        part_dir, _settings = two_revision_part
        docs = sorted(p.name for p in (part_dir / "docs").iterdir())
        assert len(docs) == 2
        for name in docs:
            assert (part_dir / "docs" / name / "registers.json").is_file()

    def test_the_diff_finds_the_reset_move_and_the_page_shift(self, two_revision_part):
        part_dir, _settings = two_revision_part
        pair, error = RevisionPair.for_part(part_dir)
        assert pair is not None, error
        diff = pair.diff()

        resets = _of(diff, KIND_REGISTER, CHANGE_RESET)
        assert len(resets) == 1
        assert "0x0223" in resets[0].summary and "0x0233" in resets[0].summary
        assert resets[0].delta is None
        assert _of(diff, KIND_SECTION, CHANGE_PAGE_SHIFTED)
        assert diff.identical is False

    def test_every_record_value_carries_a_source_that_resolves(self, two_revision_part):
        """Both revisions publish a `reg_…-r1`, so a bare reference would be wrong."""
        from datasheet_analyzer.derive.provenance import resolve_source

        part_dir, _settings = two_revision_part
        pair, _error = RevisionPair.for_part(part_dir)
        diff = pair.diff()

        seen = 0
        for change in diff.changes:
            for value in (change.before, change.after):
                if value is None or not value.source or "#" not in value.source:
                    continue
                assert value.source.startswith("docs/")
                assert resolve_source(value.source, roots=part_dir) is not None
                seen += 1
        assert seen, "no record-backed value in the diff to resolve"

    def test_the_two_sides_are_qualified_by_different_documents(self, two_revision_part):
        part_dir, _settings = two_revision_part
        pair, _error = RevisionPair.for_part(part_dir)
        diff = pair.diff()

        reset = _of(diff, KIND_REGISTER, CHANGE_RESET)[0]
        assert reset.before.source != reset.after.source
        assert diff.before_doc != diff.after_doc


class TestSelection:
    def test_selecting_by_label_printed_revision_or_document_directory(self, two_revision_part):
        part_dir, _settings = two_revision_part
        docs = sorted(p.name for p in (part_dir / "docs").iterdir())

        by_label, error = RevisionPair.for_part(part_dir, before="A", after="B")
        assert by_label is not None, error
        by_revision, error = RevisionPair.for_part(part_dir, before="SNAU269A", after="SNAU269B")
        assert by_revision is not None, error
        by_dir, error = RevisionPair.for_part(part_dir, before=docs[0], after=docs[1])
        assert by_dir is not None, error
        assert by_label.before.doc.name == by_revision.before.doc.name

    def test_an_unknown_selector_lists_what_the_part_actually_holds(self, two_revision_part):
        part_dir, _settings = two_revision_part
        pair, error = RevisionPair.for_part(part_dir, before="Z", after="B")
        assert pair is None
        assert "no document of this part matches 'Z'" in error
        assert "SNAU269A" in error and "SNAU269B" in error

    def test_naming_only_one_side_is_refused(self, two_revision_part):
        part_dir, _settings = two_revision_part
        pair, error = RevisionPair.for_part(part_dir, before="A")
        assert pair is None
        assert "name both sides" in error

    def test_defaulting_picks_the_two_documents_in_registration_order(self, two_revision_part):
        part_dir, _settings = two_revision_part
        pair, _error = RevisionPair.for_part(part_dir)
        assert pair.before.source.revision == "SNAU269A"
        assert pair.after.source.revision == "SNAU269B"

    def test_a_document_diffed_against_itself_is_the_determinism_check(self, two_revision_part):
        part_dir, _settings = two_revision_part
        pair, _error = RevisionPair.for_part(part_dir, before="A", after="A")
        diff = pair.diff()
        assert diff.identical is True
        assert "same document" in diff.empty_reason

    def test_an_ambiguous_selector_names_both_candidates(self, two_revision_part):
        """`SNAU269` prefixes both printed revisions, so it selects neither."""
        part_dir, _settings = two_revision_part
        pair, _error = RevisionPair.for_part(part_dir)
        documents = [pair.before, pair.after]

        chosen, error = select_revision(documents, "SNAU269")
        assert chosen is None
        assert "matches 2 documents" in error
        assert all(doc.doc.name in error for doc in documents)


class TestRevisionStateReachesTheDiff:
    """`content_drift` / `upstream_sha256` finally have a consumer (ticket 02).

    Ticket 02 recorded both on `RevisionState` and named `dsa diff-rev` as the
    command that would read them. A diff compares two documents **on disk**, so
    a side whose upstream has moved has to say so in the report a designer
    reads, or the report quietly claims to be about the current documents.
    """

    def test_an_unchecked_side_says_it_was_never_checked(self, two_revision_part):
        part_dir, _settings = two_revision_part
        pair, _error = RevisionPair.for_part(part_dir)
        diff = pair.diff()
        assert any("never been checked against upstream" in n for n in diff.notes)

    def test_content_drift_is_quoted_and_never_reads_as_a_new_revision(self, two_revision_part):
        part_dir, settings = two_revision_part
        from datasheet_analyzer.library.store import LibraryStore

        store = LibraryStore(settings.library_dir)
        store.set_revision_state(
            HASH_B,
            RevisionState(
                staleness=Staleness.CURRENT,
                content_drift=True,
                upstream_sha256="cc" + "1" * 62,
                note="regenerated, not revised",
            ),
        )
        clear_index_cache()
        pair, _error = RevisionPair.for_part(part_dir)
        diff = pair.diff()

        drift = [n for n in diff.notes if "regenerated" in n]
        assert drift, diff.notes
        assert "cc111111" in drift[0]
        for forbidden in ("new revision is", "available upstream", "superseded"):
            assert forbidden not in drift[0]

    def test_a_stale_side_names_the_upstream_revision_it_is_behind(self, two_revision_part):
        part_dir, settings = two_revision_part
        from datasheet_analyzer.library.store import LibraryStore

        LibraryStore(settings.library_dir).set_revision_state(
            HASH_A,
            RevisionState(staleness=Staleness.STALE, upstream_revision="SNAU269C"),
        )
        clear_index_cache()
        pair, _error = RevisionPair.for_part(part_dir)
        diff = pair.diff()

        stale = [n for n in diff.notes if "superseded upstream" in n]
        assert stale and "SNAU269C" in stale[0]
        assert "not what upstream now serves" in stale[0]


class TestRevisionLabel:
    """`dsa build --rev` files a label on the Library record, not on the corpus.

    Where the label lands is the port's other adaptation. `SourceDocument` is
    shape-frozen (`test_contracts.py::test_source_document_shape_is_unchanged`)
    and `sources.json` is regenerated at publish, so the only durable home is
    `LibraryDocument` — beside `labels` and `revision_state`, and preserved by
    `put()` for the same reason those are.
    """

    def _document(self, store, path: Path) -> str:
        from datasheet_analyzer.models import Applicability

        source = SourceDocument(content_hash="ee" + "0" * 62, path=str(path))
        store.put(
            LibraryDocument(
                source=source,
                applicability=Applicability.for_parts(["REVPART"], evidence="test"),
            )
        )
        return source.content_hash

    def test_the_label_survives_a_rebuild(self, tmp_path):
        from datasheet_analyzer.library.store import LibraryStore

        store = LibraryStore(tmp_path / "library")
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        digest = self._document(store, pdf)

        store.set_revision_label(digest, " F ")
        assert store.get(digest).revision_label == "F"

        # A build calls `put()` on every PDF it sees, carrying no label.
        self._document(store, pdf)
        assert store.get(digest).revision_label == "F"

    def test_a_contradicting_label_is_refused_and_the_stored_one_survives(
        self, tmp_path, monkeypatch
    ):
        from datasheet_analyzer.library.store import LibraryStore
        from datasheet_analyzer.pipeline import BuildRefused, _file_revision_label

        store = LibraryStore(tmp_path / "library")
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        from datasheet_analyzer.extract.pdf_structure import compute_content_hash
        from datasheet_analyzer.models import Applicability

        digest = compute_content_hash(pdf)
        store.put(
            LibraryDocument(
                source=SourceDocument(content_hash=digest, path=str(pdf)),
                applicability=Applicability.for_parts(["REVPART"], evidence="test"),
            )
        )
        store.set_revision_label(digest, "E")

        with pytest.raises(BuildRefused) as excinfo:
            _file_revision_label(
                pdf, part_number="REVPART", inventory=[], store=store, revision_label="F"
            )
        assert "already filed" in str(excinfo.value)
        assert store.get(digest).revision_label == "E"

    def test_re_filing_the_same_label_is_a_no_op(self, tmp_path):
        from datasheet_analyzer.extract.pdf_structure import compute_content_hash
        from datasheet_analyzer.library.store import LibraryStore
        from datasheet_analyzer.models import Applicability
        from datasheet_analyzer.pipeline import _file_revision_label

        store = LibraryStore(tmp_path / "library")
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        digest = compute_content_hash(pdf)
        store.put(
            LibraryDocument(
                source=SourceDocument(content_hash=digest, path=str(pdf)),
                applicability=Applicability.for_parts(["REVPART"], evidence="test"),
            )
        )
        store.set_revision_label(digest, "F")
        _file_revision_label(
            pdf, part_number="REVPART", inventory=[], store=store, revision_label="F"
        )
        assert store.get(digest).revision_label == "F"


class TestCli:
    def test_diff_rev_writes_the_report_and_prints_it(self, two_revision_part, capsys):
        part_dir, _settings = two_revision_part
        assert cli.main(["diff-rev", "--part", "REVPART"]) == 0

        out = capsys.readouterr()
        written = part_dir / "REVISION_DIFF.md"
        assert written.is_file()
        assert written.read_text(encoding="utf-8") in out.out
        assert "0x0223" in out.out and "0x0233" in out.out
        assert str(written) in out.err

    def test_json_carries_the_schema_version_and_the_envelopes(self, two_revision_part, capsys):
        _part_dir, _settings = two_revision_part
        assert cli.main(["diff-rev", "--part", "REVPART", "--json"]) == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["schema_version"] == REVDIFF_SCHEMA_VERSION
        assert payload["part_number"] == "REVPART"
        reset = next(c for c in payload["changes"] if c["change"] == CHANGE_RESET)
        assert reset["before"]["derivation"] == "copy_cell"
        assert reset["before"]["source"].startswith("docs/")
        assert reset["delta"] is None
        assert FLAG_REVIEW in reset["flags"]

    def test_no_write_leaves_the_corpus_untouched(self, two_revision_part):
        part_dir, _settings = two_revision_part
        assert cli.main(["diff-rev", "--part", "REVPART", "--no-write"]) == 0
        assert not (part_dir / "REVISION_DIFF.md").exists()

    def test_an_unbuilt_part_names_the_build_command(self, two_revision_part, capsys):
        assert cli.main(["diff-rev", "--part", "NOSUCH"]) == 2
        err = capsys.readouterr().err
        assert "no corpus for NOSUCH" in err
        assert "dsa build" in err

    def test_a_part_with_one_document_says_which_rule_is_in_the_way(
        self, two_revision_part, capsys
    ):
        """The refusal names `single_datasheet`, not a `--rev` flag that cannot help."""
        import shutil

        part_dir, settings = two_revision_part
        second = settings.parts_dir / "ONEDOC"
        shutil.copytree(part_dir, second)
        doc_dirs = sorted((second / "docs").iterdir())
        shutil.rmtree(doc_dirs[1])
        manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
        manifest["part_number"] = "ONEDOC"
        manifest["documents"] = manifest["documents"][:1]
        manifest["sections"] = [s for s in manifest["sections"] if s["doc_hash"] == HASH_A]
        (second / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        # The surviving document has to cover the new part too: a part is a
        # *view* of the Library here, not the contents of a folder.
        from datasheet_analyzer.library.store import LibraryStore
        from datasheet_analyzer.models import Applicability

        LibraryStore(settings.library_dir).set_applicability(
            HASH_A, Applicability.for_parts(["REVPART", "ONEDOC"], evidence="test")
        )
        clear_index_cache()

        assert cli.main(["diff-rev", "--part", "ONEDOC"]) == 2
        err = capsys.readouterr().err
        assert "a revision diff needs two" in err
        assert "single_datasheet" in err
        assert "--rev" not in err


class TestWriteRevisionDiff:
    def test_the_written_file_is_the_rendered_report(self, tmp_path):
        before = _side("A", specs=(_spec(0, symbol="TJ", max="105"),))
        after = _side("B", HASH_B, specs=(_spec(0, symbol="TJ", max="125"),))
        markdown = render_revision_diff(build_revision_diff(before, after))

        path = write_revision_diff(tmp_path / "REVPART", markdown)
        assert path.name == "REVISION_DIFF.md"
        assert path.read_text(encoding="utf-8") == markdown

    def test_a_json_refusal_is_still_json_on_stdout(self, two_revision_part, capsys):
        """A machine caller asked for one payload shape and gets it either way."""
        assert cli.main(["diff-rev", "--part", "NOSUCH", "--json"]) == 2
        out = capsys.readouterr()
        payload = json.loads(out.out)
        assert payload["ok"] is False
        assert payload["schema_version"] == REVDIFF_SCHEMA_VERSION
        assert payload["part_number"] == "NOSUCH"
        assert "no corpus for NOSUCH" in payload["error"]
        assert "diff-rev error" in out.err
