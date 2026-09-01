"""Register bit fields — the geometric read, and every rule that refuses one.

Hermetic per invariant 4: every fixture is a synthetic PDF built in-test with
PyMuPDF and read by the real layout backend, or a hand-built `TableBlock` for
the validators, which only ever see cells. No network, no model, no
subprocess, no built part on disk. The gate against the real reference
register map — `LMX1204_registermap.pdf`, the one that decided this ticket
parks — lives in `tests/integration/test_phase6_bitfields.py`.

One class per acceptance checkbox of ticket 06:

- **geometry**: a field's bit range comes from the bit header row's column
  boundaries, never from the name cell's text, proven by moving one unchanged
  cell to a different column and watching its bits change;
- **honest absence**: a register whose fields could not be read keeps its
  summary record with `fields: []` and a recorded reason, and is never
  dropped from the map;
- **reserved and unnamed spans** are kept rather than filtered, which is what
  makes a field list's coverage of the register width checkable at all;
- **width validation**: an overlap, an overflow, or a gap refuses the whole
  register's field set with a reason, because a partial field list is a false
  statement about the bits it left out;
- **parked**: nothing in this module reaches a published artifact, asserted
  by import rather than by intention.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer.derive.bitfields import (
    BIT_RANGE_DERIVATION,
    BIT_SPAN_DERIVATION,
    MAX_REGISTER_WIDTH,
    MIN_DIAGRAM_COLUMNS,
    SHAPE_DESCRIPTION,
    SHAPE_DIAGRAM,
    WIDTH_DECLARED,
    WIDTH_OBSERVED,
    extract_bit_fields,
    iter_bit_field_tables,
    map_description_columns,
    parse_bit_range,
    read_bit_header,
    register_name_from_caption,
    validate_fields,
)
from datasheet_analyzer.derive.registers import build_registers
from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.models import (
    BitField,
    BitRange,
    Confidence,
    DocType,
    RawDocument,
    SectionNode,
    SourceDocument,
    TableBlock,
)
from datasheet_analyzer.structure.device_tables import clear_device_lexicon_cache

PAGE_W, PAGE_H = 612.0, 792.0
RIGHT_EDGE = 560.0
PITCH = 13.0
CAP_Y = 140.0
BODY_Y = 153.0
TOC = [[1, "5 Register Map", 1]]

#: A bit-position diagram exactly as the ticket draws it: a header row of bit
#: numbers over field-name cells that span columns, with the access and reset
#: rows aligned to the same columns underneath.
DIAGRAM_COLS = [56.0] + [120.0 + 50.0 * i for i in range(8)]
DIAGRAM_CAPTION = "Table 5-2. TXDIG_CTRL0 Register Field Descriptions"
DIAGRAM_ROWS: list[list[str]] = [
    ["Bit", "7", "6", "5", "4", "3", "2", "1", "0"],
    ["Field", "RESERVED", "", "", "", "NCO_EN", "GAIN", "", ""],
    ["Type", "R", "", "", "", "R/W", "R/W", "", ""],
    ["Reset", "0x0", "", "", "", "0", "0x0", "", ""],
]

#: A field-description table, the other printed shape: one row per field.
DESC_COLS = [56.0, 120.0, 260.0, 330.0, 410.0]
DESC_CAPTION = "Table 5-3. TXDIG_CTRL1 Register Field Descriptions"
DESC_ROWS: list[list[str]] = [
    ["Bit", "Field", "Type", "Reset", "Description"],
    ["7:4", "RESERVED", "R", "0x0", "Reserved (not used)."],
    ["3", "NCO_EN", "R/W", "0", "Enable NCO"],
    ["2:0", "GAIN", "R/W", "0x0", "Output gain trim"],
]


@pytest.fixture(autouse=True)
def _fresh_lexicon():
    """The device lexicon is process-cached; no test may inherit another's."""
    clear_device_lexicon_cache()
    yield
    clear_device_lexicon_cache()


def _build_pdf(path: Path, rows: list[list[str]], columns: list[float], caption: str) -> Path:
    """A one-page synthetic register document: a ruled table under a caption.

    The shape the layout engine accepts as tabular, so the `TableBlock` under
    test is the one a real build would produce rather than one hand-written to
    suit the parser.
    """
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((columns[0], CAP_Y), caption)
    for r, row in enumerate(rows):
        for x, cell in zip(columns, row):
            if cell:
                page.insert_text((x, BODY_Y + r * PITCH), cell)
    top, bottom = CAP_Y + 3.0, BODY_Y + len(rows) * PITCH + 2.0
    for x in (*columns, RIGHT_EDGE):
        page.draw_line((x - 4.0, top), (x - 4.0, bottom))
    doc.set_toc(TOC)
    doc.save(str(path))
    doc.close()
    return path


def _extract(tmp_path: Path, name: str, rows, columns, caption) -> RawDocument:
    pdf = _build_pdf(tmp_path / name, rows, columns, caption)
    source = SourceDocument(
        content_hash=hashlib.sha256(pdf.read_bytes()).hexdigest(),
        path=str(pdf),
        doc_type=DocType.REGISTER_MAP,
    )
    return PdfLayoutBackend().extract(source)


def _only(raw: RawDocument):
    """The one bit-field extraction a single-table fixture produced."""
    found = list(iter_bit_field_tables(raw))
    assert len(found) == 1, [e.caption for e in found]
    return found[0]


def _diagram(tmp_path: Path, rows=None, name: str = "diagram.pdf"):
    return _only(_extract(tmp_path, name, rows or DIAGRAM_ROWS, DIAGRAM_COLS, DIAGRAM_CAPTION))


def _description(tmp_path: Path, rows=None, name: str = "desc.pdf"):
    return _only(_extract(tmp_path, name, rows or DESC_ROWS, DESC_COLS, DESC_CAPTION))


def _table(headers: list[str], grid: list[list[str]], caption: str = DESC_CAPTION) -> TableBlock:
    return TableBlock(caption=caption, headers=headers, grid=grid, page=7)


def _section() -> SectionNode:
    return SectionNode(number="5", title="Register Map", page_start=7, page_end=7)


def _field(name: str, hi: int, lo: int, access: str = "R/W", reset: str = "0x0") -> BitField:
    return BitField(
        name=name,
        bits=BitRange(verbatim=f"{hi}:{lo}" if hi != lo else str(hi), hi=hi, lo=lo),
        access=access,
        reset=reset,
    )


class TestBitRangeParsing:
    """Shape (a)'s pure function: a printed bit cell, and nothing invented."""

    @pytest.mark.parametrize(
        ("printed", "hi", "lo"),
        [
            ("15:3", 15, 3),
            ("[7:4]", 7, 4),
            ("15..8", 15, 8),
            ("7 to 4", 7, 4),
            ("15-8", 15, 8),
            ("3:15", 15, 3),  # printed low-first; hi is always the larger
            ("7", 7, 7),
            ("[3]", 3, 3),
            ("b7", 7, 7),
            ("D0", 0, 0),
            ("bit 5", 5, 5),
        ],
    )
    def test_printed_forms_parse_to_the_same_bits(self, printed, hi, lo):
        bits = parse_bit_range(printed)
        assert (bits.hi, bits.lo) == (hi, lo)
        assert bits.verbatim == printed
        assert bits.width == hi - lo + 1

    @pytest.mark.parametrize("printed", ["", "—", "See Table 5-2", "RESERVED", "0x1A"])
    def test_an_unreadable_cell_keeps_its_print_and_refuses_a_range(self, printed):
        """`None` is the answer, and the printed form survives to be cited."""
        bits = parse_bit_range(printed)
        assert bits.hi is None and bits.lo is None and bits.width is None
        assert bits.verbatim == printed.strip()

    def test_a_caption_names_the_register_or_says_nothing(self):
        assert register_name_from_caption("Table 1-4. R2 Register Field Descriptions") == "R2"
        assert register_name_from_caption("Table 5-2. TXDIG_CTRL0 Register Bit Fields") == (
            "TXDIG_CTRL0"
        )
        assert register_name_from_caption("Table 1-1. LMX1204 Registers") == ""
        assert register_name_from_caption("") == ""


class TestGeometricBitRanges:
    """Checkbox 1 — the span comes from the header row, never from the text."""

    def test_a_bit_diagram_reads_as_the_ticket_draws_it(self, tmp_path):
        extraction = _diagram(tmp_path)
        assert extraction.shape == SHAPE_DIAGRAM
        assert extraction.derivation == BIT_SPAN_DERIVATION
        assert extraction.register_name == "TXDIG_CTRL0"
        assert [(f.name, f.bits.hi, f.bits.lo, f.access, f.reset) for f in extraction.fields] == [
            ("RESERVED", 7, 4, "R", "0x0"),
            ("NCO_EN", 3, 3, "R/W", "0"),
            ("GAIN", 2, 0, "R/W", "0x0"),
        ]

    def test_the_same_cell_in_a_different_column_means_different_bits(self, tmp_path):
        """The proof that the mapping is geometric rather than textual.

        `NCO_EN` is the identical string in both fixtures. Printed under the
        header's `3` it is bit 3; printed under its `5` it is bit 5. Nothing
        in the cell says either number.
        """
        moved = [
            ["Bit", "7", "6", "5", "4", "3", "2", "1", "0"],
            ["Field", "RESERVED", "", "NCO_EN", "GAIN", "", "", "", ""],
            ["Type", "R", "", "R/W", "R/W", "", "", "", ""],
            ["Reset", "0x0", "", "0", "0x0", "", "", "", ""],
        ]
        first = {f.name: (f.bits.hi, f.bits.lo) for f in _diagram(tmp_path).fields}
        second = {
            f.name: (f.bits.hi, f.bits.lo)
            for f in _diagram(tmp_path, moved, name="moved.pdf").fields
        }
        assert first["NCO_EN"] == (3, 3)
        assert second["NCO_EN"] == (5, 5)
        assert second["RESERVED"] == (7, 6)
        assert second["GAIN"] == (4, 0)

    def test_an_ascending_bit_header_is_read_in_its_own_order(self):
        """`0 1 2 … 7` is the same diagram printed the other way round."""
        assert read_bit_header(["Bit", "0", "1", "2", "3"]) == {1: 0, 2: 1, 3: 2, 4: 3}
        assert read_bit_header(["Bit", "7", "6", "5", "4"]) == {1: 7, 2: 6, 3: 5, 4: 4}

    @pytest.mark.parametrize(
        "cells",
        [
            ["Bit", "7", "6", "5"],  # shorter than MIN_DIAGRAM_COLUMNS
            ["Bit", "7", "5", "3", "1"],  # not consecutive
            ["Address", "7", "6", "5", "4"],  # not a bit label
            ["Bit", "7", "6", "Name", "4", "3"],  # the run is interrupted
            ["Bit", *[str(MAX_REGISTER_WIDTH + i) for i in range(8)]],  # not a register
        ],
    )
    def test_a_row_that_is_not_a_bit_header_is_refused_as_one(self, cells):
        """A run of small integers is common; a bit diagram is not."""
        assert read_bit_header(cells) == {}
        assert MIN_DIAGRAM_COLUMNS == 4

    def test_an_unlabelled_span_becomes_a_field_with_no_name(self, tmp_path):
        """Checkbox 4 — an unnamed range is represented, never omitted.

        Bits 5 and 4 carry no printed name here. They are emitted as a field
        with an empty name rather than skipped, so the field list still covers
        the register and its coverage stays checkable.
        """
        rows = [
            ["Bit", "7", "6", "5", "4", "3", "2", "1", "0"],
            ["Field", "MODE", "", "", "", "NCO_EN", "GAIN", "", ""],
            ["Type", "R/W", "", "", "", "R/W", "R/W", "", ""],
            ["Reset", "0x0", "", "", "", "0", "0x0", "", ""],
        ]
        extraction = _diagram(tmp_path, rows, name="unnamed.pdf")
        # MODE's cell extends over the empty columns beside it, which is the
        # only reading the printed grid supports.
        assert [(f.name, f.bits.hi, f.bits.lo) for f in extraction.fields] == [
            ("MODE", 7, 4),
            ("NCO_EN", 3, 3),
            ("GAIN", 2, 0),
        ]
        covered = {b for f in extraction.fields for b in range(f.bits.lo, f.bits.hi + 1)}
        assert covered == set(range(8))

    def test_a_span_the_diagram_labels_nowhere_is_kept_as_an_unnamed_field(self):
        """Checkbox 4 again, in its literal form: an unnamed range is a field.

        Bits 7:4 carry no name, no type and no reset — the page prints nothing
        over those columns. They are emitted with an empty name rather than
        dropped, so the field list still covers the register, and the blank
        access/reset do not refuse the set: nothing was lost, because nothing
        was printed.
        """
        table = _table(
            ["Bit", "7", "6", "5", "4", "3", "2", "1", "0"],
            [
                ["Field", "", "", "", "", "NCO_EN", "GAIN", "GAIN", "GAIN"],
                ["Type", "", "", "", "", "R/W", "R/W", "R/W", "R/W"],
                ["Reset", "", "", "", "", "0", "0x0", "0x0", "0x0"],
            ],
            caption="Table 5-4. CTRL0 Register Field Descriptions",
        )
        extraction = extract_bit_fields(_section(), table)
        assert extraction is not None
        assert extraction.reasons == ()
        assert [(f.name, f.bits.verbatim, f.access) for f in extraction.fields] == [
            ("", "7:4", ""),
            ("NCO_EN", "3", "R/W"),
            ("GAIN", "2:0", "R/W"),
        ]

    def test_a_named_field_missing_its_printed_access_still_refuses_the_set(self):
        """The other half of the same rule: a lost value is not a blank one."""
        table = _table(
            ["Bit", "7", "6", "5", "4", "3", "2", "1", "0"],
            [
                ["Field", "MODE", "", "", "", "NCO_EN", "GAIN", "GAIN", "GAIN"],
                ["Type", "", "", "", "", "R/W", "R/W", "R/W", "R/W"],
                ["Reset", "0x0", "", "", "", "0", "0x0", "0x0", "0x0"],
            ],
            caption="Table 5-5. CTRL1 Register Field Descriptions",
        )
        extraction = extract_bit_fields(_section(), table)
        assert extraction is not None
        assert any("print no access" in r for r in extraction.reasons)
        assert extraction.fields == ()

    def test_the_width_comes_from_the_header_and_is_labelled_declared(self, tmp_path):
        extraction = _diagram(tmp_path)
        assert (extraction.width, extraction.width_source) == (8, WIDTH_DECLARED)


class TestDescriptionTables:
    """Shape (a) — one printed row per field, the shape LMX1204 prints."""

    def test_a_field_description_table_reads_row_by_row(self, tmp_path):
        extraction = _description(tmp_path)
        assert extraction.shape == SHAPE_DESCRIPTION
        assert extraction.derivation == BIT_RANGE_DERIVATION
        assert extraction.register_name == "TXDIG_CTRL1"
        assert [
            (f.name, f.bits.hi, f.bits.lo, f.access, f.reset, f.description)
            for f in extraction.fields
        ] == [
            ("RESERVED", 7, 4, "R", "0x0", "Reserved (not used)."),
            ("NCO_EN", 3, 3, "R/W", "0", "Enable NCO"),
            ("GAIN", 2, 0, "R/W", "0x0", "Output gain trim"),
        ]

    def test_reserved_rows_are_kept_rather_than_filtered(self, tmp_path):
        """Checkbox 4 — `RESERVED` is a field, and dropping it hides bits."""
        names = [f.name for f in _description(tmp_path).fields]
        assert "RESERVED" in names

    def test_a_table_needs_both_a_bit_and_a_field_column_to_be_one(self):
        assert map_description_columns(["Bit", "Field", "Type"]) is not None
        assert map_description_columns(["Bits", "Name", "Access", "Default"]) is not None
        assert map_description_columns(["Address", "Register", "Reset"]) is None
        assert map_description_columns(["Bit", "Description"]) is None

    def test_a_wrapped_description_continues_the_field_above_it(self):
        """A row carrying only description text is the previous field's tail.

        Its *bit* cell is not believed: the layout engine files a continuation
        under the next field's range often enough that trusting it would
        invent a field.
        """
        table = _table(
            ["Bit", "Field", "Type", "Reset", "Description"],
            [
                ["7:4", "RESERVED", "R", "0x0", "Reserved (not used)."],
                ["3", "NCO_EN", "R/W", "0", "Enable NCO."],
                ["2:0", "", "", "", "Cleared on reset."],
                ["2:0", "GAIN", "R/W", "0x0", "Output gain trim."],
            ],
        )
        extraction = extract_bit_fields(_section(), table)
        assert extraction is not None
        assert [(f.name, f.bits.hi, f.bits.lo) for f in extraction.fields] == [
            ("RESERVED", 7, 4),
            ("NCO_EN", 3, 3),
            ("GAIN", 2, 0),
        ]
        assert extraction.fields[1].description == "Enable NCO. Cleared on reset."

    def test_a_table_that_is_not_about_bits_is_passed_over_in_silence(self):
        """Not every table is a field table; saying so each time is noise."""
        table = _table(
            ["Address", "Register", "Reset", "Access"],
            [["0x1A04", "TXDIG_CTRL0", "0x00", "R/W"]],
            caption="Table 5-1. Device Registers",
        )
        assert extract_bit_fields(_section(), table) is None


class TestValidationRefusesTheWholeSet:
    """Checkbox 5 — an overlap, an overflow or a gap costs the register its fields."""

    def test_overlapping_ranges_are_refused_because_no_reading_is_true(self):
        reasons, _w, _s = validate_fields([_field("A", 15, 8), _field("B", 15, 0)])
        assert any("more than one field" in r for r in reasons)

    def test_a_range_outside_the_declared_width_is_refused(self):
        reasons, width, source = validate_fields(
            [_field("A", 7, 4), _field("B", 3, 0), _field("C", 19, 16)], declared_width=8
        )
        assert (width, source) == (8, WIDTH_DECLARED)
        assert any("outside the 8-bit register" in r for r in reasons)

    def test_a_gap_is_refused_because_the_field_list_is_incomplete(self):
        """The reference map's R19 survives extraction as its first field alone."""
        reasons, width, _s = validate_fields([_field("A", 15, 9)], declared_width=16)
        assert width == 16
        assert any("covered by no field" in r for r in reasons)

    def test_a_complete_set_passes_and_records_the_width_it_was_checked_at(self):
        reasons, width, source = validate_fields(
            [_field("A", 7, 4), _field("B", 3, 3), _field("C", 2, 0)]
        )
        assert reasons == []
        assert (width, source) == (8, WIDTH_OBSERVED)

    def test_an_undeclared_width_is_labelled_observed_not_printed(self):
        """Nothing may mistake the set's own top bit for a datasheet fact."""
        _r, width, source = validate_fields([_field("A", 15, 0)])
        assert (width, source) == (16, WIDTH_OBSERVED)

    def test_a_name_that_is_not_an_identifier_is_a_misread(self):
        """`SYSREFREQ_DELAY_ST EPSIZE` is a re-joined wrapped cell, not a name."""
        reasons, _w, _s = validate_fields(
            [_field("SYSREFREQ_DELAY_ST EPSIZE", 15, 2), _field("OK", 1, 0)]
        )
        assert any("not identifiers" in r for r in reasons)

    def test_a_field_slice_in_a_name_is_a_name(self):
        """`rb_CLKPOS[31:16]` is printed exactly like that and is legitimate."""
        reasons, _w, _s = validate_fields([_field("rb_CLKPOS[31:16]", 15, 0)])
        assert reasons == []

    def test_a_blank_access_or_reset_is_refused_where_the_table_declares_one(self):
        blank = _field("GAIN", 15, 0, access="", reset="")
        reasons, _w, _s = validate_fields([blank], require_access=True, require_reset=True)
        assert any("print no access" in r for r in reasons)
        assert any("print no reset" in r for r in reasons)
        assert validate_fields([blank])[0] == []

    def test_an_unparsed_bit_cell_refuses_the_set(self):
        unreadable = BitField(name="GAIN", bits=BitRange(verbatim="see note"))
        reasons, _w, _s = validate_fields([unreadable])
        assert any("did not parse" in r for r in reasons)

    def test_a_refused_set_ships_no_fields_at_all(self):
        """No partial field list, ever — that is the whole fail-closed rule."""
        table = _table(
            ["Bit", "Field", "Type", "Reset", "Description"],
            [["15:9", "SYSREFOUT2_DELAY_I", "R/W", "0x7F", "Sets the delay step."]],
        )
        extraction = extract_bit_fields(_section(), table, declared_width=16)
        assert extraction is not None
        assert extraction.fields == ()
        assert extraction.reasons
        assert extraction.accepted is False
        assert extraction.width_source == ""


class TestRegistersKeepTheirSummaryRecord:
    """Checkbox 3 — a register whose bits could not be read is not dropped."""

    def test_a_summary_record_survives_a_refused_field_table(self, tmp_path):
        """The summary row is the answer to most bring-up questions on its own."""
        rows = [
            ["Address", "Register", "Reset", "Access"],
            ["0x1A04", "TXDIG_CTRL0", "0x00", "R/W"],
            ["0x1A05", "TXDIG_CTRL1", "0x0F", "RO"],
            ["0x1A08", "NCO_FTW", "0x00", "R/W"],
            ["0x1A0C", "GAIN_CTRL", "0x80", "R/W"],
        ]
        raw = _extract(
            tmp_path, "summary.pdf", rows, DESC_COLS[:4] + [500.0], "Table 5-1. Device Registers"
        )
        build = build_registers(raw, "REGTEST")
        assert build.registerset is not None
        assert [r.name for r in build.registerset.registers] == [
            "TXDIG_CTRL0",
            "TXDIG_CTRL1",
            "NCO_FTW",
            "GAIN_CTRL",
        ]
        assert all(r.fields == [] for r in build.registerset.registers)

    def test_the_reason_a_field_set_was_refused_is_recorded_not_swallowed(self):
        table = _table(
            ["Bit", "Field", "Type", "Reset", "Description"],
            [
                ["15:8", "RESERVED", "R", "0x00", "Reserved."],
                ["15:0", "RESERVED", "R/W", "0x00", ""],
            ],
        )
        extraction = extract_bit_fields(_section(), table)
        assert extraction is not None
        assert extraction.register_name == "TXDIG_CTRL1"
        assert extraction.reasons and extraction.fields == ()


class TestWhatReachesAPublishedArtifact:
    """Checkbox 6 — the gate is met, so the data ships, through one door."""

    def test_the_register_set_is_the_only_shipping_importer(self):
        """One door in, so there is one place to look when a field is wrong.

        The park's version of this test asserted that *nothing* imported the
        reader. What replaces it is the property that still matters: a bit
        field reaches an artifact only by way of `derive/registers.py`, which
        attaches an accepted field set to the summary record its caption
        names. Nothing else parses a bit range or invents one.
        """
        src = Path(__file__).resolve().parents[2] / "src" / "datasheet_analyzer"
        importers = sorted(
            path.relative_to(src).as_posix()
            for path in src.rglob("*.py")
            if path.name != "bitfields.py" and "bitfields" in path.read_text(encoding="utf-8")
        )
        assert importers == ["derive/registers.py"]

    def test_a_field_read_still_carries_the_page_it_was_printed_on(self, tmp_path):
        """Whatever the gate decides, a field is citable or it is not a field."""
        extraction = _diagram(tmp_path)
        assert extraction.page == 1
        assert all(f.page == 1 for f in extraction.fields)
        assert all(f.confidence is not Confidence.UNKNOWN for f in extraction.fields)
