"""Pain point: footnote→table association.

"±1(2)" is meaningless without footnote (2) "After DSA calibration
procedure". These tests pin parsing, attachment, and orphan detection.
"""

from __future__ import annotations

from datasheet_analyzer.models import Footnote, TableBlock
from datasheet_analyzer.structure.footnotes import (
    attach_footnotes,
    audit_table_footnotes,
    parse_tablenote,
)


def test_parse_numeric_paren_note():
    fn = parse_tablenote("(1) Measured with differential 50 ohm across TxP/M.")
    assert fn is not None
    assert fn.marker == "(1)"
    assert fn.text.startswith("Measured with differential 50 ohm")


def test_parse_symbol_and_number_notes():
    assert parse_tablenote("† Some note").marker == "†"
    assert parse_tablenote("2) Another note").marker == "2)"
    assert parse_tablenote("‡ Double dagger note").marker == "‡"


def test_parse_rejects_garbage_and_empty_body():
    assert parse_tablenote("No marker here, just prose") is None
    assert parse_tablenote("(1)") is None
    assert parse_tablenote("") is None


def test_parse_collapses_embedded_whitespace():
    fn = parse_tablenote("(2) After DSA calibration\n   procedure")
    assert fn.text == "After DSA calibration procedure"


def test_attach_makes_notes_travel_with_table():
    table = TableBlock(headers=["A"], grid=[["1"]])
    notes = [Footnote(marker="(2)", text="After DSA calibration procedure")]
    out = attach_footnotes(table, notes)
    assert out.footnotes[0].marker == "(2)"
    assert "calibration" in out.footnotes[0].text
    # original untouched (copy semantics)
    assert table.footnotes == []


def test_attach_does_not_overwrite_existing_marker():
    table = TableBlock(footnotes=[Footnote(marker="(1)", text="original")])
    out = attach_footnotes(table, [Footnote(marker="(1)", text="duplicate")])
    assert out.footnotes[0].text == "original"


def test_audit_flags_orphan_citations():
    table = TableBlock(footnotes=[Footnote(marker="(1)", text="x")])
    audit = audit_table_footnotes(table, cited={"(1)", "(2)"})
    assert not audit.ok
    assert audit.orphans == {"(2)"}
    assert audit.uncited == set()


def test_audit_reports_uncited_notes_as_nonfatal():
    table = TableBlock(
        footnotes=[Footnote(marker="(1)", text="x"), Footnote(marker="(9)", text="y")]
    )
    audit = audit_table_footnotes(table, cited={"(1)"})
    assert audit.ok
    assert audit.uncited == {"(9)"}
