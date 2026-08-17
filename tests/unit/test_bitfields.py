"""Register bit fields (phase 6, ticket 06) — every rule, and every refusal.

The gate (`tests/integration/test_phase6_registers.py`,
`TestBitFieldAccuracy...`) proves this against the real LMX1204 programmer's
guide, hand-verified field by field. What is proven *here* is each rule on its
own, and — the point of a rule test — that each one **fails closed**:

- a **bit range is read from the cell alone**, anchored, and an inverted or
  half-printed range is no range at all;
- a **register width comes from something printed**, and with no width there
  are no fields: a field list nobody can check against a width is exactly the
  artifact this ticket refuses to ship;
- **overlap and overflow reject the whole field set** with a recorded reason,
  never the "good" half of it;
- **gaps are published, not hidden** (`unaccounted_bits`), so the coverage of a
  field list is checkable by reading it;
- a **register is never dropped** for having no readable fields — it keeps its
  summary record, `fields: []`, and a reason;
- the **column route needs the table's own header row**; a table read
  positionally publishes nothing, because a bit range from the wrong column is
  indistinguishable from a right one;
- the **diagram route is geometric**: a field's bits come from which columns of
  the bit-position header row its cell spans, not from its text — proven
  through the real layout floor on a synthetic PDF, since neither reference
  document prints that shape;
- a **continuation line contributes text and never a key**, so the rowspan fill
  ticket 09 leaves in a wrapped row's bit cell cannot become a field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import fitz
import pytest

from datasheet_analyzer.acquire import register_source
from datasheet_analyzer.config import PIPELINE_VERSION, REGISTERS_SCHEMA_VERSION
from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.models import (
    RECONSTRUCTION_HEADER,
    RECONSTRUCTION_RESCUED,
    Confidence,
    DocType,
    ExtractionStats,
    RawDocument,
    RegisterRecord,
    SectionNode,
    SourceDocument,
    TableBlock,
)
from datasheet_analyzer.publish import registers_current, write_corpus
from datasheet_analyzer.query import format_register_hits
from datasheet_analyzer.retrieve import CorpusIndex, Retriever, clear_index_cache
from datasheet_analyzer.structure.bitfields import (
    BIT_RANGE_DERIVATION,
    BIT_SPAN_DERIVATION,
    ROUTE_COLUMN,
    ROUTE_DIAGRAM,
    WIDTH_FROM_BIT_HEADER,
    WIDTH_FROM_RESET,
    field_table_register,
    parse_bit_range,
    read_field_tables,
    register_width,
)
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.structure.registers import build_registerset

DOC_HASH = "beef" + "0" * 60

REG_HEADERS = ["Address", "Acronym", "Features Requiring This Register", "Section"]
REG_ROWS = [
    ["0x0", "R0", "Powerdown, Reset", "Go"],
    ["0x2", "R2", "Multiplier Mode", "Go"],
]
#: The declaration headings that state each register's reset — and therefore,
#: four hex digits at a time, its width.
DECLARATIONS = [
    "1.1 R0 Register (Offset = 0x0) [Reset = 0x0000]",
    "1.2 R2 Register (Offset = 0x2) [Reset = 0x0223]",
]

FIELD_HEADERS = ["Bit", "Field", "Type", "Reset", "Description"]

#: R0's field table exactly as SNAU269A p.4 prints it (the gate's own sample).
R0_FIELDS = [
    ["15:3", "RESERVED", "R", "0x0000", "Reserved (not used)."],
    ["2", "POWERDOWN", "R/W", "0x0", "Sets the device in a low-power state."],
    ["1", "RESERVED", "R/W", "0x0", "Reserved. If this register is written, set 0x0."],
    ["0", "RESET", "R/W", "0x0", "Soft Reset. Resets the entire logic and registers."],
]


def _summary(**kwargs) -> TableBlock:
    defaults = {
        "caption": "Table 1-1. LMX1204 Registers",
        "headers": list(REG_HEADERS),
        "grid": [list(row) for row in REG_ROWS],
        "page": 2,
        "reconstruction": RECONSTRUCTION_HEADER,
    }
    return TableBlock(**{**defaults, **kwargs})


def _field_table(
    register: str = "R0",
    rows: list[list[str]] | None = None,
    *,
    headers: list[str] | None = None,
    caption: str | None = None,
    page: int = 4,
    reconstruction: str = RECONSTRUCTION_HEADER,
    conditions: str = "",
) -> TableBlock:
    return TableBlock(
        caption=caption if caption is not None
        else f"Table 1-3. {register} Register Field Descriptions",
        headers=list(headers if headers is not None else FIELD_HEADERS),
        grid=[list(row) for row in (rows if rows is not None else R0_FIELDS)],
        page=page,
        conditions=conditions,
        reconstruction=reconstruction,
    )


def _raw(tables: list[TableBlock] | None = None, **kwargs) -> RawDocument:
    defaults = {
        "source": SourceDocument(
            content_hash=DOC_HASH, path="regmap.pdf", part_number="TESTPART",
            doc_type=DocType.REGISTER_MAP, page_count=25,
        ),
        "sections": [
            SectionNode(
                number="1",
                title="Device Registers",
                page_start=2,
                page_end=6,
                paragraphs=list(DECLARATIONS),
                tables=tables if tables is not None else [_summary(), _field_table()],
            )
        ],
        "extractor": "pdf_layout",
        "extractor_version": "test-1",
        "extraction_stats": ExtractionStats(backend="pdf_layout"),
    }
    return RawDocument(**{**defaults, **kwargs})


def _records(raw: RawDocument | None = None) -> dict[str, RegisterRecord]:
    """`{acronym: record}` for one document, through the real publisher path."""
    result = build_registerset(_raw() if raw is None else raw, "TESTPART")
    return {record.name: record for record in result.registers}


class TestBitRangeGrammar:
    """A bit range is read from its own cell, wholly, or not at all."""

    @pytest.mark.parametrize(
        ("text", "hi", "lo"),
        [
            ("15:3", 15, 3),
            ("2", 2, 2),
            ("0", 0, 0),
            ("[3]", 3, 3),
            ("[15:8]", 15, 8),
            ("7..0", 7, 0),
            (" 5 : 4 ", 5, 4),
            ("15:15", 15, 15),
        ],
    )
    def test_every_printed_form_reads_as_the_bits_it_prints(self, text, hi, lo):
        bits = parse_bit_range(text)
        assert bits is not None, text
        assert (bits.hi, bits.lo) == (hi, lo)
        assert bits.derivation == BIT_RANGE_DERIVATION
        assert bits.n_bits == hi - lo + 1

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "15:",            # half a range is not a range
            ":3",
            "3:15",           # inverted — a misread grid, not a field
            "150",            # no register is 100 bits wide
            "0x3",            # a value, in the wrong column
            "RESERVED",
            "R2 is shown in",  # the navigation line a region sweeps up
            "15:3 (note 2)",
            "bit 3",
        ],
    )
    def test_anything_else_has_no_bit_range_in_it(self, text):
        assert parse_bit_range(text) is None

    def test_the_verbatim_cell_is_kept_exactly_as_printed(self):
        bits = parse_bit_range("[15:8]")
        assert bits is not None and bits.verbatim == "[15:8]"


class TestWidthComesFromSomethingPrinted:
    @pytest.mark.parametrize(
        ("word", "width"),
        [("0x0000", 16), ("0xFF", 8), ("FF86h", 16), ("0x0", 4), ("0x00000000", 32)],
    )
    def test_a_hex_reset_word_states_the_register_width(self, word, width):
        assert register_width(word) == width

    @pytest.mark.parametrize("word", ["", "0", "12", "R/W", "0xZZ", "See Table 7-1"])
    def test_anything_that_is_not_a_hex_word_states_no_width(self, word):
        assert register_width(word) is None

    def test_no_width_means_no_fields_and_a_recorded_reason(self):
        """A field list that cannot be checked against a width is not published."""
        raw = _raw([_summary(grid=[["0x0", "R0", "Powerdown", "Go"]]), _field_table()])
        # ...with a *decimal* declaration, so nothing states a width.
        raw.sections[0].paragraphs = ["1.1 R0 Register (Offset = 0x0) [Reset = 0]"]
        record = _records(raw)["R0"]
        assert record.fields == []
        assert record.width is None
        assert "width unknown" in record.fields_reason
        # the register itself is still published, reset and all
        assert record.reset is not None and record.reset.verbatim == "0"

    def test_the_width_names_the_printed_word_and_the_rule(self):
        record = _records()["R0"]
        assert (record.width, record.width_evidence) == (16, "0x0000")
        assert record.width_derivation == WIDTH_FROM_RESET


class TestFieldsArePublishedWholeOrNotAtAll:
    def test_a_clean_field_table_publishes_every_printed_field_verbatim(self):
        record = _records()["R0"]
        assert [f.bits.verbatim for f in record.fields] == ["15:3", "2", "1", "0"]
        assert [(f.bits.hi, f.bits.lo) for f in record.fields] == [
            (15, 3), (2, 2), (1, 1), (0, 0)
        ]
        assert [f.name for f in record.fields] == [
            "RESERVED", "POWERDOWN", "RESERVED", "RESET"
        ]
        assert [f.access for f in record.fields] == ["R", "R/W", "R/W", "R/W"]
        assert [f.reset for f in record.fields] == ["0x0000", "0x0", "0x0", "0x0"]
        assert record.fields[1].description.startswith("Sets the device")
        assert record.unaccounted_bits == []
        assert record.fields_route == ROUTE_COLUMN
        assert record.fields_reason == ""
        assert record.fields_evidence == "Table 1-3. R0 Register Field Descriptions"

    def test_every_field_cites_its_own_printed_page_and_row(self):
        record = _records()["R0"]
        for index, field in enumerate(record.fields):
            assert field.page == 4
            assert field.row_index == index
            assert field.row_verbatim == R0_FIELDS[index]

    def test_a_reserved_range_is_a_field_because_the_document_printed_it(self):
        """Dropping `RESERVED` is what would make a gap invisible."""
        record = _records()["R0"]
        assert [f.name for f in record.fields].count("RESERVED") == 2
        assert sum(f.bits.n_bits for f in record.fields) == 16

    def test_overlapping_ranges_reject_the_whole_set_with_a_reason(self):
        """The reference document's own R90 shape: `15:8` then `15:0`."""
        rows = [
            ["15:8", "RESERVED", "R", "0x00", "Reserved (not used)."],
            ["15:0", "RESERVED", "R/W", "0x00", "Reserved. Set to 0x60."],
        ]
        record = _records(_raw([_summary(), _field_table(rows=rows)]))["R0"]
        assert record.fields == [], "not even the first, unambiguous field"
        assert "both" in record.fields_reason and "claim bit 8" in record.fields_reason
        assert "15:8" in record.fields_reason and "15:0" in record.fields_reason

    def test_a_range_past_the_register_width_rejects_the_whole_set(self):
        rows = [
            ["16", "OVERFLOW", "R/W", "0x0", "A bit a 16-bit register does not have."],
            ["15:0", "RESERVED", "R/W", "0x0", "Everything else."],
        ]
        record = _records(_raw([_summary(), _field_table(rows=rows)]))["R0"]
        assert record.fields == []
        assert "claims bit 16 of a 16-bit register" in record.fields_reason

    def test_a_gap_is_published_rather_than_refused_or_hidden(self):
        rows = [
            ["15:8", "TOP", "R/W", "0x0", "The top half."],
            ["3:0", "BOTTOM", "R/W", "0x0", "The bottom nibble."],
        ]
        record = _records(_raw([_summary(), _field_table(rows=rows)]))["R0"]
        assert [f.name for f in record.fields] == ["TOP", "BOTTOM"]
        assert record.unaccounted_bits == ["7:4"]
        # ...and the grade says the list is incomplete, which is what `low` is for
        assert record.fields_confidence is Confidence.LOW

    def test_a_register_with_no_field_table_keeps_its_record_and_says_why(self):
        records = _records(_raw([_summary(), _field_table("R0")]))
        assert set(records) == {"R0", "R2"}
        assert records["R2"].fields == []
        assert "no bit-field table was read for R2" in records["R2"].fields_reason
        assert records["R2"].address.verbatim == "0x2"  # never dropped

    def test_two_tables_claiming_one_register_publish_nothing_for_it(self):
        raw = _raw([
            _summary(),
            _field_table("R0", caption="Table 1-3. R0 Register Field Descriptions"),
            _field_table("R0", caption="Table 1-4. R0 Register Field Descriptions"),
        ])
        record = _records(raw)["R0"]
        assert record.fields == []
        assert "2 field tables claim R0" in record.fields_reason

    def test_a_caption_and_a_preamble_naming_different_registers_refuse(self):
        raw = _raw([
            _summary(),
            _field_table(
                "R0",
                conditions="1.2 R2 Register (Offset = 0x2) [Reset = 0x0223]",
            ),
        ])
        record = _records(raw)["R0"]
        assert record.fields == []
        assert "caption names R0 but its preamble declares R2" in record.fields_reason

    def test_a_table_read_positionally_publishes_no_fields(self):
        """Headers the lexicon does not know: a bit range could be any column."""
        raw = _raw([
            _summary(),
            _field_table(headers=["Col A", "Col B", "Col C", "Col D", "Col E"]),
        ])
        record = _records(raw)["R0"]
        assert record.fields == []
        assert "does not declare its Bit and Field columns" in record.fields_reason

    def test_a_field_table_of_prose_publishes_nothing(self):
        rows = [
            ["R2 is shown in", "Table 1-4", ".", "", ""],
            ["Return to the", "Summary Table", ".", "", ""],
        ]
        record = _records(_raw([_summary(), _field_table(rows=rows)]))["R0"]
        assert record.fields == []
        assert record.fields_reason


class TestFieldSetsAreGraded:
    def test_a_header_declared_grid_covering_the_width_is_high(self):
        assert _records()["R0"].fields_confidence is Confidence.HIGH

    def test_a_rescued_grid_covering_the_width_is_medium(self):
        """A mis-split grid does not accidentally tile a register, so a rescue
        that tiles it is trustworthy — with "confirm on the page" attached."""
        raw = _raw([_summary(), _field_table(reconstruction=RECONSTRUCTION_RESCUED)])
        assert _records(raw)["R0"].fields_confidence is Confidence.MEDIUM

    def test_a_register_with_no_fields_is_graded_unknown(self):
        records = _records(_raw([_summary(), _field_table("R0")]))
        assert records["R2"].fields_confidence is Confidence.UNKNOWN


class TestWrappedRowsContributeTextAndNeverAKey:
    """Ticket 09 replicates the bit cell into a wrapped line; that is not a field."""

    def test_a_continuation_line_extends_the_description_above_it(self):
        rows = [
            ["15:6", "RESERVED", "R", "0x000", "Reserved (not used)."],
            ["5:3", "SMCLK_DIV_PRE", "R/W", "0x2", "Sets pre-divider for the"],
            # the rowspan fill of the *next* field, on a line that names none
            ["2:0", "", "", "", "state machine clock."],
            ["2:0", "CLK_MUX", "R/W", "0x1", "Selects the function of the device."],
        ]
        record = _records(_raw([_summary(), _field_table(rows=rows)]))["R0"]
        assert [f.bits.verbatim for f in record.fields] == ["15:6", "5:3", "2:0"]
        assert record.fields[1].description == (
            "Sets pre-divider for the state machine clock."
        )
        assert [f.name for f in record.fields] == [
            "RESERVED", "SMCLK_DIV_PRE", "CLK_MUX"
        ]
        assert record.unaccounted_bits == []

    def test_the_fill_never_becomes_a_second_field_with_the_wrong_name(self):
        """Reading `2:0` off the continuation line would publish
        SMCLK_DIV_PRE at bits 2:0 *and* duplicate the key."""
        rows = [
            ["15:1", "RESERVED", "R", "0x000", "Reserved."],
            ["0", "", "", "", "more of the reserved description"],
            ["0", "RESET", "R/W", "0x0", "Soft reset."],
        ]
        record = _records(_raw([_summary(), _field_table(rows=rows)]))["R0"]
        assert [(f.name, f.bits.verbatim) for f in record.fields] == [
            ("RESERVED", "15:1"), ("RESET", "0")
        ]


class TestGluedHeaderRowIsRecovered:
    """The layout floor sometimes merges a field table's header line with its
    first data line, cell by cell. Five of the reference document's 35
    registers land that way, three of them with that line as their only field."""

    GLUED: ClassVar[list[str]] = [
        "Bit 15:13", "Field RESERVED", "Type R", "Reset 0x0",
        "Description Reserved (not used).",
    ]

    def test_the_merged_first_row_is_recovered_as_data(self):
        rows = [
            ["12", "FORCE_VCO", "R/W", "0x0", "Forces the VCO."],
            ["11:0", "RESERVED", "R/W", "0x008", "Reserved."],
        ]
        raw = _raw([_summary(), _field_table(headers=self.GLUED, rows=rows)])
        record = _records(raw)["R0"]
        assert [f.bits.verbatim for f in record.fields] == ["15:13", "12", "11:0"]
        assert [f.name for f in record.fields] == ["RESERVED", "FORCE_VCO", "RESERVED"]
        assert [f.access for f in record.fields] == ["R", "R/W", "R/W"]
        assert [f.reset for f in record.fields] == ["0x0", "0x0", "0x008"]
        assert record.unaccounted_bits == []

    def test_a_register_whose_only_field_was_merged_still_publishes_it(self):
        glued = [
            "Bit 15:0", "Field rb_CLKPOS[15:0]", "Type R", "Reset 0xFFFF",
            "Description Stores a snapshot of the CLKIN signal.",
        ]
        raw = _raw([_summary(), _field_table(headers=glued, rows=[])])
        record = _records(raw)["R0"]
        assert [(f.name, f.bits.verbatim) for f in record.fields] == [
            ("rb_CLKPOS[15:0]", "15:0")
        ]

    def test_a_genuine_header_row_is_never_split(self):
        record = _records()["R0"]
        assert [f.bits.verbatim for f in record.fields] == ["15:3", "2", "1", "0"]

    def test_nothing_is_recovered_when_the_bit_column_is_a_plain_header(self):
        """The repair needs the *key* column to be the glued one, because the
        recovered bit range is what proves the split was real. A header row
        glued everywhere *except* its bit column therefore keeps its unreadable
        headers, no column but `Bit` is understood, and nothing is published —
        rather than a field list whose name and access came from a guess."""
        glued = ["Bit", "Field RESERVED", "Type R", "Reset 0x0", "Description Reserved."]
        raw = _raw([_summary(), _field_table(headers=glued, rows=R0_FIELDS)])
        record = _records(raw)["R0"]
        assert record.fields == []
        assert "does not declare its Bit and Field columns" in record.fields_reason

    def test_a_header_whose_remainder_is_not_a_bit_range_is_never_split(self):
        """`Bit Position Names` is a header cell, not `Bit Position` plus data,
        and refusing the split leaves the table with no bit column at all."""
        glued = [
            "Bit Position Names", "Field RESERVED", "Type R", "Reset 0x0",
            "Description Reserved.",
        ]
        raw = _raw([_summary(), _field_table(headers=glued)])
        record = _records(raw)["R0"]
        assert record.fields == []
        assert record.fields_reason


class TestTheDiagramRouteIsGeometric:
    """A bit diagram states a field's range only in the layout, so the range is
    derived from the bit header row's cell boundaries.

    Neither reference document prints this shape, so the gate for it is a
    synthetic PDF read by the **real layout floor** — which reconstructs it
    exactly, header run and span row (recorded in `KNOWN_SHORTCOMINGS.md`: the
    route has no real-document gate).
    """

    PAGE_W, PAGE_H, PITCH, CAP_Y = 612.0, 792.0, 13.0, 140.0
    COLS: ClassVar[list[float]] = [56.0 + 64.0 * i for i in range(8)]

    def _diagram_pdf(self, path: Path, field_row: list[tuple[int, str]]) -> RawDocument:
        doc = fitz.open()
        page = doc.new_page(width=self.PAGE_W, height=self.PAGE_H)
        page.insert_text((56.0, self.CAP_Y), "Table 9-1. R0 Register Field Descriptions")
        for index, x in enumerate(self.COLS):
            page.insert_text((x, self.CAP_Y + self.PITCH), str(7 - index))
        for column, text in field_row:
            page.insert_text((self.COLS[column], self.CAP_Y + 2 * self.PITCH), text)
        # the access row TI prints under a diagram: unreadable as a bit header,
        # and therefore ignored rather than mangled into a field
        page.insert_text((self.COLS[0], self.CAP_Y + 3 * self.PITCH), "R/W")
        for x in [52.0, *[c - 4.0 for c in self.COLS[1:]], 560.0]:
            page.draw_line((x, self.CAP_Y + 6.0), (x, self.CAP_Y + 6.0 + 4 * self.PITCH))
        doc.set_toc([[1, "9 Register Map", 1]])
        doc.save(str(path))
        doc.close()
        source = register_source(path, part_number="TESTPART", doc_type=DocType.REGISTER_MAP)
        return PdfLayoutBackend().extract(source)

    def test_the_layout_floor_hands_back_the_header_run_and_the_span_row(self, tmp_path):
        raw = self._diagram_pdf(
            tmp_path / "diagram.pdf", [(0, "RESERVED"), (4, "NCO_EN"), (6, "MODE")]
        )
        (table,) = [t for s in raw.sections for t in s.tables]
        assert table.headers == ["7", "6", "5", "4", "3", "2", "1", "0"]
        assert table.grid[0] == ["RESERVED", "", "", "", "NCO_EN", "", "MODE", ""]

    def _block(self, headers: list[str], grid: list[list[str]]) -> TableBlock:
        """A hand-built diagram, for span shapes a PDF cannot be made to
        produce reliably (the floor merges an adjacent access row into a field
        row whose first column is empty, which is a fixture problem, not a
        rule)."""
        return TableBlock(
            caption="Table 9-1. R0 Register Field Descriptions",
            headers=headers,
            grid=[list(row) for row in grid],
            page=4,
            reconstruction=RECONSTRUCTION_HEADER,
        )

    def test_a_field_cell_spans_the_bits_of_the_columns_it_covers(self, tmp_path):
        raw = self._diagram_pdf(
            tmp_path / "diagram.pdf", [(0, "RESERVED"), (4, "NCO_EN"), (6, "MODE")]
        )
        (read,) = read_field_tables(raw).tables
        assert read.route == ROUTE_DIAGRAM
        assert read.register == "R0"
        # An empty column continues the field to its left — a spanning cell, as
        # the diagram prints it — so the eight bits tile with no gap.
        assert [(f.name, f.bits.hi, f.bits.lo) for f in read.fields] == [
            ("RESERVED", 7, 4), ("NCO_EN", 3, 2), ("MODE", 1, 0)
        ]
        assert [f.bits.verbatim for f in read.fields] == ["7:4", "3:2", "1:0"]
        assert all(f.bits.derivation == BIT_SPAN_DERIVATION for f in read.fields)
        # A diagram prints no per-field access or reset column, so neither is
        # invented: null and says so (ADR 0005).
        assert all(f.access == "" and f.reset == "" for f in read.fields)
        # the bit header row states the width, and the fields tile it
        assert read.declared_width == 8

    def test_a_field_cell_in_every_column_spans_one_bit_each(self):
        read = read_field_tables(
            _raw([self._block(
                ["3", "2", "1", "0"], [["A", "B", "C", "D"]]
            )])
        ).tables[0]
        assert [(f.name, f.bits.verbatim) for f in read.fields] == [
            ("A", "3"), ("B", "2"), ("C", "1"), ("D", "0")
        ]

    def test_unnamed_leading_columns_become_unaccounted_bits(self):
        """A diagram that names nothing over its top bits has a gap there, and
        the field beside them is never widened leftwards to cover it."""
        block = self._block(["7", "6", "5", "4", "3", "2", "1", "0"],
                            [["", "", "", "", "NCO_EN", "", "MODE", ""]])
        record = _records(_raw([_summary(), block]))["R0"]
        assert [(f.name, f.bits.verbatim) for f in record.fields] == [
            ("NCO_EN", "3:2"), ("MODE", "1:0")
        ]
        assert record.unaccounted_bits == ["15:4"]
        assert record.fields_confidence is Confidence.LOW

    def test_a_diagram_register_publishes_its_width_from_the_header_row(self, tmp_path):
        """No printed reset word, so the width comes from the bit header row."""
        raw = self._diagram_pdf(
            tmp_path / "diagram.pdf", [(0, "RESERVED"), (4, "NCO_EN"), (6, "MODE")]
        )
        (diagram,) = [t for s in raw.sections for t in s.tables]
        raw = _raw([_summary(grid=[["0x0", "R0", "Powerdown", "Go"]]), diagram])
        raw.sections[0].paragraphs = []  # nothing declares a reset
        record = _records(raw)["R0"]
        assert record.reset is None
        assert (record.width, record.width_derivation) == (8, WIDTH_FROM_BIT_HEADER)
        assert record.fields_route == ROUTE_DIAGRAM
        assert [f.bits.verbatim for f in record.fields] == ["7:4", "3:2", "1:0"]
        assert record.unaccounted_bits == []

    def test_a_diagram_narrower_than_the_stated_reset_reports_the_gap(self):
        """An 8-bit diagram under a 16-bit reset word is a gap, not a rewrite."""
        diagram = self._block(["7", "6", "5", "4", "3", "2", "1", "0"],
                              [["MODE", "", "", "", "NCO_EN", "", "", ""]])
        record = _records(_raw([_summary(), diagram]))["R0"]
        assert (record.width, record.width_derivation) == (16, WIDTH_FROM_RESET)
        assert record.unaccounted_bits == ["15:8"]
        assert [f.bits.verbatim for f in record.fields] == ["7:4", "3:0"]

    @pytest.mark.parametrize(
        ("headers", "expected"),
        [
            # a run that skips a bit numbers no column
            (["7", "6", "4", "3"], "does not declare its Bit and Field columns"),
            # ascending is not a bit header row either
            (["0", "1", "2", "3"], "does not declare its Bit and Field columns"),
        ],
    )
    def test_a_header_row_that_is_not_a_descending_run_is_no_diagram(
        self, headers, expected
    ):
        """It falls through to the column route, which refuses it — the one
        thing that must never happen is a range read off a header nobody could
        map to a column."""
        block = self._block(headers, [["RESERVED", "", "NCO_EN", ""]])
        record = _records(_raw([_summary(), block]))["R0"]
        assert record.fields == []
        assert expected in record.fields_reason

    def test_a_field_cell_outside_the_numbered_columns_refuses_the_table(self):
        """The header row numbers four columns; a fifth cell has no bit at all."""
        block = self._block(
            ["7", "6", "5", "4", ""], [["RESERVED", "", "NCO_EN", "", "oops"]]
        )
        record = _records(_raw([_summary(), block]))["R0"]
        assert record.fields == []
        assert "outside the columns" in record.fields_reason

    def test_two_stacked_bit_header_runs_both_contribute(self):
        """A 16-bit register printed as two rows of eight."""
        block = self._block(
            ["15", "14", "13", "12", "11", "10", "9", "8"],
            [
                ["TOP", "", "", "", "", "", "", ""],
                ["7", "6", "5", "4", "3", "2", "1", "0"],
                ["MID", "", "", "", "LOW", "", "", ""],
            ],
        )
        record = _records(_raw([_summary(), block]))["R0"]
        assert [(f.name, f.bits.verbatim) for f in record.fields] == [
            ("TOP", "15:8"), ("MID", "7:4"), ("LOW", "3:0")
        ]
        assert record.unaccounted_bits == []
        assert record.fields_confidence is Confidence.HIGH


class TestTheSetReportsItsOwnCoverage:
    def test_the_coverage_of_a_document_that_prints_field_tables_is_stated(self):
        raw = _raw([_summary(), _field_table("R0")])
        result = build_registerset(raw, "TESTPART")
        assert result.n_field_sets == 1
        assert any(
            "bit fields published for 1 of 2 registers" in w for w in result.warnings
        ), result.warnings

    def test_a_document_that_prints_none_says_nothing(self):
        """An absence in the document is not a finding about the extraction —
        the same stance ticket 04 took on a datasheet with no pin table."""
        result = build_registerset(_raw([_summary()]), "TESTPART")
        assert result.n_field_sets == 0
        assert result.warnings == []
        assert all("no bit-field table" in r.fields_reason for r in result.registers)

    def test_rows_with_no_readable_bit_range_are_counted_out_loud(self):
        rows = [
            *R0_FIELDS,
            ["R2 is shown in", "Table 1-4", ".", "", ""],
            ["Return to the", "Summary Table", ".", "", ""],
        ]
        result = build_registerset(_raw([_summary(), _field_table(rows=rows)]), "TESTPART")
        assert any(
            "2 field-table row(s) print no readable bit range" in w
            for w in result.warnings
        ), result.warnings
        # ...and the fields the table did print are published unharmed
        record = next(r for r in result.registers if r.name == "R0")
        assert [f.bits.verbatim for f in record.fields] == ["15:3", "2", "1", "0"]

    def test_a_field_table_belonging_to_no_listed_register_is_reported(self):
        raw = _raw([_summary(), _field_table("R99")])
        result = build_registerset(raw, "TESTPART")
        assert any("belong to no register" in w and "R99" in w for w in result.warnings)

    def test_a_refused_field_table_joins_the_documents_rejection_reasons(self):
        rows = [["R2 is shown in", "Table 1-4", ".", "", ""]]
        raw = _raw([_summary(), _field_table(rows=rows)])
        build_registerset(raw, "TESTPART")
        reasons = raw.extraction_stats.rejection_reasons
        assert any(r.startswith("device-table (bitfield)") for r in reasons), reasons


class TestFieldTableCaptionIsTheJoin:
    @pytest.mark.parametrize(
        ("caption", "register"),
        [
            ("Table 1-3. R0 Register Field Descriptions", "R0"),
            ("Table 7-26. R25 Register Field Descriptions", "R25"),
            ("TXDIG_CTRL0 Register Field Descriptions", "TXDIG_CTRL0"),
            ("Table 1-1. LMX1204 Registers", ""),
            ("Table 1-2. Device Access Type Codes", ""),
            ("", ""),
        ],
    )
    def test_only_a_caption_that_names_a_register_claims_one(self, caption, register):
        assert field_table_register(caption) == register


class TestPublishedAndQueryable:
    """The fields survive the round trip and are reachable by name."""

    def _corpus(self, tmp_path: Path) -> Path:
        raw = _raw()
        part_dir = tmp_path / "TESTPART"
        write_corpus(
            part_dir,
            [(raw, build_section_plans(raw), {})],
            "# TESTPART\n",
            pipeline_version=PIPELINE_VERSION,
            vendor="ti",
            registersets=[build_registerset(raw, "TESTPART")],
        )
        clear_index_cache()
        return part_dir

    def test_registers_json_carries_the_fields_and_its_new_schema_version(self, tmp_path):
        part_dir = self._corpus(tmp_path)
        doc_dir = next((part_dir / "docs").iterdir())
        payload = json.loads((doc_dir / "registers.json").read_text(encoding="utf-8"))
        assert payload["schema_version"] == REGISTERS_SCHEMA_VERSION
        assert payload["n_field_sets"] == 1
        r0 = payload["registers"][0]
        assert r0["width"] == 16
        assert [f["bits"]["verbatim"] for f in r0["fields"]] == ["15:3", "2", "1", "0"]
        assert r0["unaccounted_bits"] == []
        assert registers_current(part_dir)

    def test_a_loaded_corpus_answers_a_field_lookup(self, tmp_path):
        part_dir = self._corpus(tmp_path)
        retriever = Retriever.for_part(part_dir)
        hits = retriever.registers(field="POWERDOWN")
        assert [h.record.name for h in hits] == ["R0"]
        assert hits[0].matched_via == "field"
        # a field no register publishes is simply no hit — never a guess
        assert retriever.registers(field="NCO_EN") == []

    def test_the_json_view_publishes_width_coverage_and_the_reason(self, tmp_path):
        part_dir = self._corpus(tmp_path)
        by_name = {
            h.record.name: h.as_dict()
            for h in Retriever.for_part(part_dir).registers()
        }
        assert by_name["R0"]["width"] == 16
        assert by_name["R0"]["fields"][1]["name"] == "POWERDOWN"
        assert by_name["R0"]["fields"][1]["bits"] == {
            "verbatim": "2", "hi": 2, "lo": 2, "derivation": BIT_RANGE_DERIVATION
        }
        assert by_name["R0"]["fields_unaccounted_for"] == []
        assert by_name["R0"]["fields_reason"] == ""
        assert by_name["R2"]["fields"] == []
        assert "no bit-field table was read for R2" in by_name["R2"]["fields_reason"]

    def test_the_records_survive_the_round_trip_field_for_field(self, tmp_path):
        part_dir = self._corpus(tmp_path)
        (doc,) = [d for d in CorpusIndex.load(part_dir).docs if d.registers]
        r0 = next(r for r in doc.registers if r.name == "R0")
        assert [(f.name, f.bits.hi, f.bits.lo, f.access, f.reset) for f in r0.fields] == [
            ("RESERVED", 15, 3, "R", "0x0000"),
            ("POWERDOWN", 2, 2, "R/W", "0x0"),
            ("RESERVED", 1, 1, "R/W", "0x0"),
            ("RESET", 0, 0, "R/W", "0x0"),
        ]

    def test_dsa_regs_field_prints_the_register_that_holds_it(
        self, tmp_path, monkeypatch, capsys
    ):
        from datasheet_analyzer import cli
        from datasheet_analyzer.config import Settings

        parts = tmp_path / "parts"
        self._corpus(parts)
        monkeypatch.setattr(
            cli, "get_settings", lambda: Settings(parts_dir=parts).resolve()
        )
        assert cli.main(["regs", "--part", "TESTPART", "--field", "POWERDOWN"]) == 0
        captured = capsys.readouterr()
        assert "0x0: R0" in captured.out
        assert "[2] POWERDOWN [R/W] reset=0x0" in captured.out
        # invariant 8: a filter on a derived value states what it could not
        # consider — here R2, which publishes no fields.
        assert "1 of 2 registers" in captured.err
        assert "cannot establish that a field does not exist" in captured.err
        # a field nothing publishes is an ordinary no-match (exit 1), never a
        # claim that the device has no such field
        assert cli.main(["regs", "--part", "TESTPART", "--field", "NCO_EN"]) == 1
        assert "1 of 2 registers" in capsys.readouterr().err

    def test_the_field_gap_is_silent_when_every_register_publishes_fields(
        self, tmp_path
    ):
        raw = _raw([
            _summary(grid=[["0x0", "R0", "Powerdown", "Go"]]), _field_table("R0")
        ])
        part_dir = tmp_path / "TESTPART"
        write_corpus(
            part_dir,
            [(raw, build_section_plans(raw), {})],
            "# TESTPART\n",
            pipeline_version=PIPELINE_VERSION,
            vendor="ti",
            registersets=[build_registerset(raw, "TESTPART")],
        )
        clear_index_cache()
        assert Retriever.for_part(part_dir).register_field_gap() == ""

    def test_the_renderer_prints_the_fields_and_the_reason_for_none(self, tmp_path):
        part_dir = self._corpus(tmp_path)
        hits = Retriever.for_part(part_dir).registers()
        rendered = format_register_hits(hits, show_fields=True)
        assert "[15:3] RESERVED [R] reset=0x0000" in rendered
        assert "16-bit" in rendered
        assert "(no bit fields published: no bit-field table was read for R2" in rendered
        # ...and nothing about fields when the caller did not ask
        assert "[15:3]" not in format_register_hits(hits)
