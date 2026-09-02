"""Device-table abstraction — identify -> map columns -> validate -> emit.

Hermetic per invariant 4: every fixture is a synthetic PDF built in-test with
PyMuPDF and read by the real layout backend, so the `TableBlock`s under test are
the ones a datasheet build would actually produce (grid, headers, `row_pages`,
`reconstruction`) rather than hand-written stand-ins. No network, no model, no
subprocess, no built part.

Geometry models a real pin table: four ruled columns, a `Table N-M.` caption,
a section heading in the outline. Pin tables are fully packed — every cell
carries text — which the layout engine only accepts as tabular when the page
also carries the vertical rulings a real pin table is printed with.

Coverage, one class per acceptance checkbox:
- header lexicon is data (a header variant added to a temp YAML maps, no code);
- column mapping via full headers, via abbreviated headers, via headers in any
  order, and via the positional fallback for a table with no header row at all
  (while a header row the lexicon does not know is refused, not guessed at);
- the two printed shapes that are layout rather than content: band labels and
  wrapped continuation rows;
- validation failures reject the whole table with a recorded reason
  (duplicate keys, non-monotonic addresses, an unreadable key column);
- a multi-device table's rows scoped to the *other* device are not rows about
  this part, and only when the table names this part too;
- rejection reasons join `ExtractionStats.rejection_reasons`;
- multi-value key cells expand, each expanded record keeping the row's page;
- a prose table that merely looks tabular is not accepted, and a parametric
  spec table is not reported as a rejected device table either.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import ClassVar

import fitz
import pytest

from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.models import Confidence, ExtractionStats, RawDocument, SourceDocument
from datasheet_analyzer.structure.device_tables import (
    KIND_PIN,
    KIND_REGISTER,
    METHOD_HEADER,
    METHOD_POSITIONAL,
    clear_device_lexicon_cache,
    expand_keys,
    extract_device_tables,
    identify,
    load_device_lexicon,
    map_columns_by_header,
    normalize_header,
    parse_address,
    record_rejections,
)

PAGE_W, PAGE_H = 612.0, 792.0
# Four ruled columns, left edges as a TI pin table prints them.
COL_X = (56.0, 140.0, 250.0, 340.0)
RIGHT_EDGE = 560.0
PITCH = 13.0
CAP_Y = 140.0
BODY_Y = 153.0

PIN_HEADERS = ["Pin", "Name", "Type", "Description"]
PIN_ROWS = [
    ["A1", "VSSA", "Ground", "Analog ground"],
    ["A2", "VDDA", "Power", "Analog supply"],
    ["B1", "CLKP", "Input", "Clock input positive"],
    ["B2", "CLKN", "Input", "Clock input negative"],
    ["B3", "NC", "NC", "No connect"],
]
PIN_TOC = [[1, "6 Pin Configuration and Functions", 1]]

REG_HEADERS = ["Address", "Register", "Reset", "Access"]
REG_ROWS = [
    ["0x00", "CHIP_ID", "0x1204", "R"],
    ["0x04", "TXDIG_CTRL0", "0x00", "R/W"],
    ["0x08", "TXDIG_CTRL1", "0x0F", "R/W"],
    ["0x0C", "MUXOUT", "0x01", "R/W"],
]
REG_TOC = [[1, "8 Register Maps", 1]]


def _extract(
    tmp_path: Path, name: str, caption: str, rows: list[list[str]], toc: list[list]
) -> RawDocument:
    """One synthetic ruled table -> the RawDocument the layout backend builds."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    y0 = BODY_Y if caption else CAP_Y
    if caption:
        page.insert_text((COL_X[0], CAP_Y), caption)
    for r, row in enumerate(rows):
        for x, cell in zip(COL_X, row):
            if cell:
                page.insert_text((x, y0 + r * PITCH), cell)
    top, bottom = y0 - 10.0, y0 + len(rows) * PITCH + 2.0
    for x in (*COL_X, RIGHT_EDGE):
        page.draw_line((x - 4.0, top), (x - 4.0, bottom))
    doc.set_toc(toc)
    pdf = tmp_path / name
    doc.save(str(pdf))
    doc.close()
    source = SourceDocument(
        content_hash=hashlib.sha256(pdf.read_bytes()).hexdigest(), path=str(pdf)
    )
    return PdfLayoutBackend().extract(source)


def _pin_doc(
    tmp_path: Path, name: str, headers: list[str] | None = None, rows: list[list[str]] | None = None
) -> RawDocument:
    body = list(rows if rows is not None else PIN_ROWS)
    printed = ([headers] if headers is not None else []) + body
    return _extract(tmp_path, name, "Table 6-1. Pin Functions", printed, PIN_TOC)


def _reg_doc(tmp_path: Path, name: str, rows: list[list[str]] | None = None) -> RawDocument:
    body = list(rows if rows is not None else REG_ROWS)
    return _extract(tmp_path, name, "Table 8-1. Register Map", [REG_HEADERS] + body, REG_TOC)


@pytest.fixture(autouse=True)
def _fresh_lexicon():
    """The lexicon is process-cached; a test that loads one from a temp path
    must not leave it standing for the next."""
    clear_device_lexicon_cache()
    yield
    clear_device_lexicon_cache()


def DEVICE_LEXICON_TEXT() -> str:
    from datasheet_analyzer.structure.device_tables import DEVICE_LEXICON_PATH

    return DEVICE_LEXICON_PATH.read_text(encoding="utf-8")


class TestLexiconIsData:
    """A header variant is a YAML edit, never a Python change."""

    def test_shipped_lexicon_declares_both_kinds(self):
        lex = load_device_lexicon()
        assert {s.kind for s in lex.kinds} == {KIND_PIN, KIND_REGISTER}
        pin = lex.kind(KIND_PIN)
        assert pin.key_role == "pin"
        assert pin.required_roles == ("pin", "name")
        assert lex.kind(KIND_REGISTER).key_role == "address"

    def test_header_variant_is_a_data_change(self, tmp_path):
        """`Bump` is nobody's header word — until the lexicon says it is."""
        lex = load_device_lexicon()
        pin = lex.kind(KIND_PIN)
        headers = ["Bump", "Net", "Type", "Description"]
        assert map_columns_by_header(headers, pin) is None

        text = DEVICE_LEXICON_TEXT().replace("        - ball\n", "        - ball\n        - bump\n")
        text = text.replace("        - signal\n", "        - signal\n        - net\n")
        path = tmp_path / "device_tables.yaml"
        path.write_text(text, encoding="utf-8")

        patched = load_device_lexicon(path).kind(KIND_PIN)
        mapping = map_columns_by_header(headers, patched)
        assert mapping is not None
        assert mapping.columns == {"pin": 0, "name": 1, "type": 2, "description": 3}

    def test_normalize_header_folds_markers_and_case(self):
        assert normalize_header("Pin No.(2)") == "pin no"
        assert normalize_header("  I/O  ") == "i/o"
        assert normalize_header("PIN #") == "pin #"

    def test_longest_phrase_wins_over_a_shorter_one(self):
        pin = load_device_lexicon().kind(KIND_PIN)
        mapping = map_columns_by_header(["Pin", "Pin Name", "Pin Type", "Function"], pin)
        assert mapping.columns == {"pin": 0, "name": 1, "type": 2, "description": 3}


class TestColumnMapping:
    def test_full_headers_map_and_emit_with_provenance(self, tmp_path):
        raw = _pin_doc(tmp_path, "pins.pdf", PIN_HEADERS)
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert found.rejection_reasons == ()
        assert len(found.accepted) == 1
        assert [r.key for r in found.rows] == ["A1", "A2", "B1", "B2", "B3"]

        first = found.rows[0]
        assert first.values == {
            "pin": "A1",
            "name": "VSSA",
            "type": "Ground",
            "description": "Analog ground",
        }
        assert first.method == METHOD_HEADER
        assert first.section == "6"
        assert first.table_index == 0
        assert first.row_index == 0
        assert first.page == 1
        assert first.row_verbatim == ("A1", "VSSA", "Ground", "Analog ground")
        assert first.confidence is Confidence.HIGH
        # row index counts printed body rows, in printed order
        assert [r.row_index for r in found.rows] == [0, 1, 2, 3, 4]

    def test_abbreviated_headers_map_through_the_lexicon(self, tmp_path):
        raw = _pin_doc(tmp_path, "abbrev.pdf", ["No.", "Signal", "I/O", "Function"])
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert [r.key for r in found.rows] == ["A1", "A2", "B1", "B2", "B3"]
        assert found.accepted[0].mapping.method == METHOD_HEADER
        assert found.rows[0].values["description"] == "Analog ground"

    def test_headers_in_any_order_map_by_what_they_say(self, tmp_path):
        """LMX1204 Table 4-1 prints NAME before NO.; the mapping follows the
        headers, not the column order."""
        raw = _pin_doc(
            tmp_path,
            "reordered.pdf",
            ["NAME", "NO.", "TYPE(1)", "DESCRIPTION"],
            [[name, pin, typ, desc] for pin, name, typ, desc in PIN_ROWS],
        )
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert found.accepted[0].mapping.columns == {
            "name": 0,
            "pin": 1,
            "type": 2,
            "description": 3,
        }
        assert [r.key for r in found.rows] == ["A1", "A2", "B1", "B2", "B3"]
        assert found.rows[0].values["name"] == "VSSA"

    def test_unrecognized_headers_are_not_guessed_at(self, tmp_path):
        """A header row the lexicon does not know is evidence of a schema, not
        the absence of one. Teaching it the header is a data change."""
        raw = _pin_doc(tmp_path, "unknown_hdr.pdf", ["Ref", "Net", "Dir", "Notes"])
        assert extract_device_tables(raw, kind=KIND_PIN).results == ()

        text = DEVICE_LEXICON_TEXT()
        for old, new in (('- "no"', "- ref"), ("- signal", "- net"), ("- dir", "- notes")):
            text = text.replace(f"        {old}\n", f"        {old}\n        {new}\n")
        path = tmp_path / "device_tables.yaml"
        path.write_text(text, encoding="utf-8")
        taught = extract_device_tables(raw, kind=KIND_PIN, lexicon=load_device_lexicon(path))
        assert [r.key for r in taught.rows] == ["A1", "A2", "B1", "B2", "B3"]

    def test_no_header_row_at_all_keeps_the_first_printed_row(self, tmp_path):
        """The layout engine takes the first data row for a header; the
        positional fallback recognizes it as data and emits it, so a pin is
        not lost to a table that printed no header."""
        raw = _pin_doc(tmp_path, "headerless.pdf", headers=None)
        table = raw.sections[0].tables[0]
        assert table.headers == PIN_ROWS[0]  # the engine really did take it

        found = extract_device_tables(raw, kind=KIND_PIN)
        mapping = found.accepted[0].mapping
        assert mapping.method == METHOD_POSITIONAL
        assert mapping.header_row_is_data is True
        assert [r.key for r in found.rows] == ["A1", "A2", "B1", "B2", "B3"]
        assert found.rows[0].values["name"] == "VSSA"
        assert [r.row_index for r in found.rows] == [0, 1, 2, 3, 4]
        assert found.rows[0].page == 1

    def test_positional_fallback_needs_an_explicit_kind(self, tmp_path):
        """A headerless grid of designators is evidence for no schema in
        particular, so autodetection does not guess one."""
        raw = _pin_doc(tmp_path, "headerless2.pdf", headers=None)
        assert extract_device_tables(raw, kind=KIND_PIN).rows
        table = raw.sections[0].tables[0]

        assert identify(table, kind=None) is None

    def test_positional_fallback_needs_the_table_declared(self, tmp_path):
        """Without a caption or section saying what it is, a headerless grid of
        designators reads as a pin table and a register table at once — which
        is two guesses, not one reading."""
        raw = _extract(
            tmp_path,
            "undeclared.pdf",
            "Table 9-1. Configuration Options",
            PIN_ROWS,
            [[1, "9 Detailed Description", 1]],
        )
        assert extract_device_tables(raw, kind=KIND_PIN).results == ()
        assert extract_device_tables(raw, kind=KIND_REGISTER).results == ()

    def test_register_table_maps_its_own_vocabulary(self, tmp_path):
        raw = _reg_doc(tmp_path, "regs.pdf")
        found = extract_device_tables(raw, kind=KIND_REGISTER)

        assert [r.key for r in found.rows] == ["0x00", "0x04", "0x08", "0x0C"]
        assert found.rows[1].values == {
            "address": "0x04",
            "name": "TXDIG_CTRL0",
            "reset": "0x00",
            "access": "R/W",
        }
        assert found.rows[0].page == 1
        assert found.rows[0].section == "8"


class TestValidationRejectsWholeTables:
    def test_duplicate_key_rejects_the_table_with_a_reason(self, tmp_path):
        rows = [r[:] for r in PIN_ROWS]
        rows[3][0] = "A1"  # B2 reprinted as A1
        raw = _pin_doc(tmp_path, "dupe.pdf", PIN_HEADERS, rows)
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert found.rows == ()  # never half-parsed
        assert len(found.rejected) == 1
        reason = found.rejected[0].reason
        assert reason.startswith("pin table: duplicate key 'A1'")
        assert "rows 0 and 3" in reason

    def test_non_monotonic_address_rejects_the_table_with_a_reason(self, tmp_path):
        rows = [r[:] for r in REG_ROWS]
        rows[2][0] = "0x02"  # steps backwards under 0x04
        raw = _reg_doc(tmp_path, "backwards.pdf", rows)
        found = extract_device_tables(raw, kind=KIND_REGISTER)

        assert found.rows == ()
        reason = found.rejected[0].reason
        assert reason.startswith("register table: address '0x02' (row 2)")
        assert "'0x04' (row 1)" in reason

    def test_repeated_address_rejects_before_it_is_emitted(self, tmp_path):
        rows = [r[:] for r in REG_ROWS]
        rows[2][0] = "0x04"
        raw = _reg_doc(tmp_path, "dupe_addr.pdf", rows)
        found = extract_device_tables(raw, kind=KIND_REGISTER)

        assert found.rows == ()
        assert "duplicate key '0x04'" in found.rejected[0].reason

    def test_unreadable_key_column_rejects_the_table(self, tmp_path):
        """The count cross-check's sibling: a key column of prose is not a key
        column, however tabular the grid around it is."""
        rows = [
            ["Power supply", "VDDA", "Power", "Analog supply"],
            ["Ground return", "VSSA", "Ground", "Analog ground"],
            ["Clock input", "CLKP", "Input", "Clock input positive"],
            ["Clock return", "CLKN", "Input", "Clock input negative"],
        ]
        raw = _pin_doc(tmp_path, "prose_keys.pdf", PIN_HEADERS, rows)
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert found.rows == ()
        assert found.rejected[0].reason == (
            "pin table: key column is not pin table keys (0 of 4 rows)"
        )

    def test_a_mostly_empty_key_column_fails_the_count_cross_check(self, tmp_path):
        """Enough keys to pass the shape check, too few to have understood the
        table: the rows that happened to parse are not shipped alone.

        The key column is printed second here (as LMX1204 Table 4-1 prints it),
        because `pdf_layout` materializes a *first* column's empty cells from
        the row above and a blank first column therefore never reaches this
        code.
        """
        rows = [
            ["VSSA", "A1", "Ground", "Analog ground"],
            ["VDDA", "", "Power", "Analog supply"],
            ["CLKP", "", "Input", "Clock input positive"],
            ["CLKN", "", "Input", "Clock input negative"],
        ]
        raw = _pin_doc(tmp_path, "sparse_keys.pdf", ["Name", "No.", "Type", "Description"], rows)
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert found.rows == ()
        assert "1 of 4 printed rows" in found.rejected[0].reason


class TestRowsPrintedForAnotherDevice:
    """A datasheet that covers two part numbers prints one table for both and
    scopes the rows that differ.

    Measured on ADC12DJ5200RF's `Table 5-1 Pin Functions`: six of seventy rows
    open their description with a part number --- two `ADC12DJ5200RF:` and four
    `ADC12DJ5210RF:` --- and the sibling's four rows re-key twenty-two ball
    designators the device's own rows already keyed (`DGND` on `D9, D10, J9,
    J10`, `SGND` on the eight balls `DGND` claims, `VD11`/`VS11` likewise).
    Reading all seventy as one pinout made `unique_keys` refuse the table for
    `duplicate key 'D9' (rows 38 and 39)`, and a 221-page ADC published no pins
    at all.
    """

    SCOPED_ROWS: ClassVar[list[list[str]]] = [
        ["A1", "VSSA", "Ground", "Analog ground"],
        ["A2", "VDDA", "Power", "Analog supply"],
        ["B1", "CLKP", "Input", "Clock input positive"],
        ["B2, B3", "DGND", "Ground", "DEVA1000: digital ground on both balls"],
        ["B2", "DGND", "Ground", "DEVB2000: digital ground on one ball"],
    ]

    def test_the_sibling_device_s_rows_are_not_rows_about_this_part(self, tmp_path):
        raw = _pin_doc(tmp_path, "two_devices.pdf", PIN_HEADERS, self.SCOPED_ROWS)
        found = extract_device_tables(raw, kind=KIND_PIN, part_number="DEVA1000")

        assert [row.key for row in found.rows] == ["A1", "A2", "B1", "B2", "B3"]
        assert found.rejected == ()
        assert "row 4: printed for DEVB2000, not DEVA1000" in found.accepted[0].notes

    def test_the_same_table_read_as_the_sibling_keeps_the_other_row(self, tmp_path):
        """Symmetry, and the proof that nothing here is keyed to one vendor:
        the same printed table read as DEVB2000 drops DEVA1000's row instead."""
        raw = _pin_doc(tmp_path, "two_devices_b.pdf", PIN_HEADERS, self.SCOPED_ROWS)
        found = extract_device_tables(raw, kind=KIND_PIN, part_number="DEVB2000")

        assert [row.key for row in found.rows] == ["A1", "A2", "B1", "B2"]
        assert "row 3: printed for DEVA1000, not DEVB2000" in found.accepted[0].notes

    def test_without_a_part_number_nothing_is_dropped(self, tmp_path):
        """The refusal is the default. A caller that does not say which device
        it is asking about gets the reading it got before this rule existed."""
        raw = _pin_doc(tmp_path, "no_part.pdf", PIN_HEADERS, self.SCOPED_ROWS)
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert found.rows == ()
        assert "duplicate key 'B2'" in found.rejected[0].reason

    def test_a_table_that_never_names_this_part_is_judged_unchanged(self, tmp_path):
        """What makes the rule evidence rather than a guess: it fires only when
        the table names *this* corpus's part as one of its row scopes. A table
        that scopes rows to devices this part is not among says nothing about
        which of them is meant, so it is refused exactly as before."""
        raw = _pin_doc(tmp_path, "third_device.pdf", PIN_HEADERS, self.SCOPED_ROWS)
        found = extract_device_tables(raw, kind=KIND_PIN, part_number="DEVC9000")

        assert found.rows == ()
        assert "duplicate key 'B2'" in found.rejected[0].reason

    def test_a_leading_word_that_is_not_a_device_name_is_not_a_scope(self, tmp_path):
        """`Note:` and `Warning:` open cells all over real datasheets. A scope
        token has to carry a digit and be four characters or more, so prose
        labels cannot be read as device names --- checked here by giving the
        colliding rows `Note:` prefixes and watching the table stay refused."""
        rows = [r[:] for r in self.SCOPED_ROWS]
        rows[3][3] = "Note: digital ground on both balls"
        rows[4][3] = "Warning: digital ground on one ball"
        raw = _pin_doc(tmp_path, "prose_prefix.pdf", PIN_HEADERS, rows)
        found = extract_device_tables(raw, kind=KIND_PIN, part_number="DEVA1000")

        assert found.rows == ()
        assert "duplicate key 'B2'" in found.rejected[0].reason


class TestPrintedShapesThatAreLayoutNotContent:
    """Two shapes measured in the built corpora, both read here rather than
    left for a validator to trip over."""

    _rows: ClassVar[list[list[str]]] = [
        ["POWER SUPPLIES", "", "", ""],
        ["A1", "VSSA", "Ground", "Analog ground"],
        ["A2", "VDDA", "Power", "Analog supply for the analog"],
        ["", "", "", "section and the clock core."],
        ["B1", "CLKP", "Input", "Clock input positive"],
    ]

    def test_band_label_and_continuation_rows(self, tmp_path):
        raw = _pin_doc(tmp_path, "bands.pdf", PIN_HEADERS, self._rows)
        found = extract_device_tables(raw, kind=KIND_PIN)
        result = found.accepted[0]

        # the band heading is not a pin, and the wrapped tail is not a row
        assert [r.key for r in found.rows] == ["A1", "A2", "B1"]
        assert found.rows[1].values["description"] == (
            "Analog supply for the analog section and the clock core."
        )
        assert "band label 'POWER SUPPLIES'" in " ".join(result.notes)
        assert any("continues row" in n for n in result.notes)

    def test_a_row_that_prints_no_key_costs_only_itself(self, tmp_path):
        """HMC520A Table 4: the exposed-pad row prints no pin number.

        Phase 6 read the lent `15` as a second claim on pin 15 and refused
        the whole table — correct given what it could see, and it cost all 24
        of the datasheet's real pins. Phase 6.5 ticket 06 tells the layout
        engine to record which first cells it lent, so an unkeyed row reads
        as unkeyed: the pins that *are* numbered publish, the row that is not
        becomes no record, and the note says so rather than leaving the table
        looking complete.
        """
        rows = [
            ["12", "GND", "Ground", "Ground return."],
            ["15", "LO", "Input", "LO port. See Figure 4."],
            ["", "EPAD", "Ground", "Exposed pad. Connect to GND."],
            ["17", "RF", "Output", "RF port."],
        ]
        raw = _pin_doc(tmp_path, "epad.pdf", PIN_HEADERS, rows)
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert found.rejected == ()
        assert [r.key for r in found.rows] == ["12", "15", "17"]
        assert "prints no key of its own" in " ".join(found.accepted[0].notes)

    def test_a_printed_repeat_is_still_a_duplicate(self, tmp_path):
        """The refusal ticket 06 was careful to keep.

        A row that prints `15` a second time is a real contradiction, not a
        span: reading it as one pin would attach one pin's description to
        another. Only a cell the engine *lent* is forgiven.
        """
        rows = [
            ["12", "GND", "Ground", "Ground return."],
            ["15", "LO", "Input", "LO port. See Figure 4."],
            ["15", "EPAD", "Ground", "Exposed pad. Connect to GND."],
            ["17", "RF", "Output", "RF port."],
        ]
        raw = _pin_doc(tmp_path, "dupe.pdf", PIN_HEADERS, rows)
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert found.rows == ()
        assert "duplicate key '15'" in found.rejected[0].reason


class TestRejectionsAreMeasurable:
    def test_reasons_join_extraction_stats(self, tmp_path):
        rows = [r[:] for r in PIN_ROWS]
        rows[3][0] = "A1"
        raw = _pin_doc(tmp_path, "dupe_stats.pdf", PIN_HEADERS, rows)
        found = extract_device_tables(raw, kind=KIND_PIN)

        stats = raw.extraction_stats or ExtractionStats()
        before = (stats.tables_detected, stats.tables_accepted, stats.tables_rejected)
        record_rejections(stats, found.rejection_reasons)

        assert any("duplicate key 'A1'" in r for r in stats.rejection_reasons)
        # the layout engine already counted this table; counting it twice would
        # make one table two
        assert (stats.tables_detected, stats.tables_accepted, stats.tables_rejected) == before

    def test_reasons_are_deduplicated_and_capped(self):
        stats = ExtractionStats(rejection_reasons=["pin table: duplicate key 'A1'"])
        record_rejections(
            stats,
            ["pin table: duplicate key 'A1'", "pin table: only 1 of 4", "third", "fourth"],
            limit=2,
        )
        assert stats.rejection_reasons == [
            "pin table: duplicate key 'A1'",
            "pin table: only 1 of 4",
            "third",
        ]

    def test_no_stats_is_not_an_error(self):
        assert record_rejections(None, ["anything"]) is None


class TestMultiValueKeys:
    def test_list_and_run_cells_expand_keeping_row_provenance(self, tmp_path):
        rows = [
            ["A1, A2, B1", "VSSA", "Ground", "Analog ground"],
            ["C1-C4", "VDDA", "Power", "Analog supply"],
            ["D1", "CLKP", "Input", "Clock input positive"],
            ["D2", "CLKN", "Input", "Clock input negative"],
        ]
        raw = _pin_doc(tmp_path, "expand.pdf", PIN_HEADERS, rows)
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert [r.key for r in found.rows] == [
            "A1",
            "A2",
            "B1",
            "C1",
            "C2",
            "C3",
            "C4",
            "D1",
            "D2",
        ]
        expanded = [r for r in found.rows if r.key in {"A1", "A2", "B1"}]
        assert {r.expanded_from for r in expanded} == {"A1, A2, B1"}
        for row in expanded:
            # every expanded record cites the row it was printed on
            assert row.row_index == 0
            assert row.page == 1
            assert row.values["name"] == "VSSA"
            assert row.row_verbatim == ("A1, A2, B1", "VSSA", "Ground", "Analog ground")
        assert [r.key for r in found.rows if r.key == "D1"] and found.rows[-1].expanded_from == ""

    @pytest.mark.parametrize(
        ("cell", "keys"),
        [
            ("A1", ["A1"]),
            ("A1, A2, B1", ["A1", "A2", "B1"]),
            ("A1; A2", ["A1", "A2"]),
            ("A1-A4", ["A1", "A2", "A3", "A4"]),
            ("A1 – A4", ["A1", "A2", "A3", "A4"]),
            ("12 to 15", ["12", "13", "14", "15"]),
            ("A01-A03", ["A01", "A02", "A03"]),
            ("A1-4", ["A1", "A2", "A3", "A4"]),
            ("", []),
        ],
    )
    def test_expansion_shapes(self, cell, keys):
        assert expand_keys(cell)[0] == keys

    @pytest.mark.parametrize(
        ("cell", "note"),
        [("A4-A1", "counts down"), ("A1-B4", "spans two prefixes"), ("A1-A9999", "more than")],
    )
    def test_an_unreadable_run_stays_verbatim_and_says_why(self, cell, note):
        keys, why = expand_keys(cell)
        assert keys == [cell]  # never invented members
        assert cell in why and note in why


class TestNotDeviceTables:
    def test_a_prose_table_is_not_a_pin_table(self, tmp_path):
        """Two columns of sentences under headers the lexicon half-recognizes:
        not a device table, and not reported as a rejected one either."""
        rows = [
            ["Signal Name", "Description"],
            ["Supply", "The device operates from a single supply rail"],
            ["Ground", "Return current flows through the exposed pad"],
            ["Clock", "A differential clock drives the sampling core"],
            ["Reset", "Asserting reset returns every register to default"],
        ]
        raw = _extract(tmp_path, "prose.pdf", "Table 2-1. Signal Overview", rows, PIN_TOC)
        found = extract_device_tables(raw, kind=KIND_PIN)

        assert found.results == ()
        assert found.rows == ()
        assert found.rejection_reasons == ()

    def test_a_parametric_spec_table_is_silently_not_a_device_table(self, tmp_path):
        rows = [
            ["Parameter", "Min", "Typ", "Max"],
            ["Supply voltage", "1.7", "1.8", "1.9"],
            ["Supply current", "100", "120", "150"],
            ["Junction temperature", "-40", "25", "125"],
        ]
        raw = _extract(
            tmp_path,
            "spec.pdf",
            "Table 5-1. Electrical Characteristics",
            rows,
            [[1, "5 Specifications", 1]],
        )
        for kind in (KIND_PIN, KIND_REGISTER):
            found = extract_device_tables(raw, kind=kind)
            assert found.results == ()
            assert found.rejection_reasons == ()


class TestAddressParsing:
    @pytest.mark.parametrize(
        ("text", "value"),
        [
            ("0x1A04", 6660),
            ("0x00", 0),
            ("1A04h", 6660),
            ("12", 12),
            ("", None),
            ("See Table 5", None),
            ("1A04", None),
            ("0x", None),
        ],
    )
    def test_printed_forms(self, text, value):
        assert parse_address(text) == value

    def test_a_bare_hex_column_parses_only_when_the_column_says_so(self):
        assert parse_address("1A04", hex_default=True) == 6660
        assert parse_address("10", hex_default=True) == 16
        assert parse_address("10") == 10
