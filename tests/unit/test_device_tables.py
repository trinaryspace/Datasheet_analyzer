"""Device tables (phase 6, ticket 03) — identify, map, validate, emit.

The abstraction that will serve `pins.json` and `registers.json`. No consumer
ships with it, so everything here runs against synthetic fitz-built PDFs pushed
through the real layout floor (`PdfLayoutBackend`), plus hand-built
`TableBlock`s where the point of a case is a shape a PDF cannot reliably be
made to produce.

What these prove, in the order the ticket asks for them:

- the header lexicon is **data**: an unknown header variant leaves its field
  unmapped, and teaching it is an edit to `device_tables.yaml` — asserted by
  loading the shipped file, adding one phrase to it, and watching the mapping
  change with no code touched;
- column mapping works with abbreviated headers (`NO.`, `I/O`) and with **no
  header row at all**, where the layout floor puts the first pin in `headers`
  and the positional fallback has to read it as data rather than lose it;
- a table that fails validation is **rejected whole, with a reason** — a
  duplicate-key pin table and an out-of-order register summary both emit zero
  records, not a partial set;
- those reasons join `ExtractionStats.rejection_reasons`, beside the
  reconstruction gate's own, without disturbing the counts that measure
  reconstruction;
- multi-value key cells (`A1, A2, B1`, `A1-A4`) expand, and every expanded
  record still cites the one row the datasheet printed;
- prose laid out in columns is not a pin table, and a parametric spec table is
  not a device table at all (no records *and* no rejection noise).
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz
import pytest
import yaml

from datasheet_analyzer.acquire import register_source
from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.models import (
    ExtractionStats,
    RawDocument,
    SectionNode,
    SourceDocument,
    TableBlock,
)
from datasheet_analyzer.structure.device_tables import (
    HEADER_ROW_INDEX,
    LEXICON_PATH,
    PIN,
    REGISTER,
    REJECTION_PREFIX,
    DeviceLexicon,
    DeviceTableRejection,
    cross_check_count,
    expand_keys,
    identify_table,
    load_device_lexicon,
    map_columns,
    normalize_header,
    read_device_table,
    read_device_tables,
    record_rejections,
)

PAGE_W, PAGE_H = 612.0, 792.0
PITCH = 13.0
CAP_Y = 140.0
HDR_Y = 153.0

# Four-column device-table geometry (TI "Pin Functions" proportions).
X = {"key": 56.0, "name": 130.0, "type": 240.0, "desc": 300.0}

EN_DASH = "–"  # U+2013, as a datasheet prints a pin range


def _make_pdf(path: Path, pages, toc=None, rulings=True) -> None:
    """pages: list of pages; each page = list of (x, y, text) lines.

    Device tables are drawn tables: every cell of a pin table is filled, which
    is indistinguishable from scattered junk to the layout floor's occupancy
    check *unless* the PDF draws a rule — so the fixtures draw the column
    rules real pin tables print.
    """
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text in lines:
            page.insert_text((x, y), text)
        if rulings:
            for x in (52.0, 126.0, 236.0, 296.0, 560.0):
                page.draw_line((x, CAP_Y + 6.0), (x, CAP_Y + 6.0 + 9 * PITCH))
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()


def _rows(rows: list[tuple[str, str, str, str]], y0: float) -> list[tuple[float, float, str]]:
    """Four-column rows on the shared column geometry, one PITCH apart."""
    out: list[tuple[float, float, str]] = []
    for i, (a, b, c, d) in enumerate(rows):
        y = y0 + i * PITCH
        for x, text in zip((X["key"], X["name"], X["type"], X["desc"]), (a, b, c, d)):
            if text:
                out.append((x, y, text))
    return out


def _table_page(caption: str, header: tuple[str, str, str, str] | None,
                body: list[tuple[str, str, str, str]]) -> list[tuple[float, float, str]]:
    """A captioned four-column table; `header=None` prints no header row."""
    lines = [(X["key"], CAP_Y, caption)]
    rows = ([header] if header else []) + body
    lines += _rows(rows, HDR_Y)
    return lines


PIN_BODY = [
    ("A1", "VSSA", "G", "Analog ground"),
    ("A2", "VDD1P8", "P", "1.8 V analog supply"),
    ("B1", "RXCLK", "I", "Receiver clock input"),
]

REG_BODY = [
    ("0x0000", "CHIP_ID", "0x01", "R"),
    ("0x0004", "SCRATCH", "0x00", "R/W"),
    ("0x0008", "TXDIG_CTRL0", "0x00", "R/W"),
]


def _extract(path: Path) -> RawDocument:
    """One synthetic PDF through the real layout floor."""
    source = register_source(path, part_number="P1", doc_type="datasheet")
    return PdfLayoutBackend().extract(source)


def _built(tmp_path, name: str, lines, *,
           section: str = "5 Pin Configuration and Functions") -> RawDocument:
    pdf = Path(tmp_path) / name
    _make_pdf(pdf, [lines], toc=[[1, section, 1]])
    return _extract(pdf)


def _one_table(raw: RawDocument) -> tuple[SectionNode, TableBlock]:
    pairs = [(s, t) for s in raw.sections for t in s.tables]
    assert len(pairs) == 1, f"expected exactly one extracted table, got {len(pairs)}"
    return pairs[0]


def _block(**kwargs) -> TableBlock:
    """A hand-built block, for shapes a PDF cannot be made to produce reliably."""
    defaults = {"caption": "Table 5-1. Pin Functions", "page": 4}
    return TableBlock(**{**defaults, **kwargs})


def _section(**kwargs) -> SectionNode:
    defaults = {"number": "5.1", "title": "Pin Functions", "page_start": 4, "page_end": 4}
    return SectionNode(**{**defaults, **kwargs})


def _raw(sections: list[SectionNode], extractor: str = "pdf_layout") -> RawDocument:
    return RawDocument(
        source=SourceDocument(content_hash="a" * 64, path="p1.pdf"),
        sections=sections,
        extractor=extractor,
    )


class TestLexiconIsCheckedInData:
    """Criterion 1: adding a header variant is a data change, not a code change."""

    def test_the_shipped_lexicon_describes_both_kinds(self):
        lexicon = load_device_lexicon()
        assert lexicon.kinds == (PIN, REGISTER)
        pin, register = lexicon.by_kind(PIN), lexicon.by_kind(REGISTER)
        assert pin is not None and register is not None
        assert (pin.key_field, register.key_field) == ("pin", "address")
        # the two behavioural switches the plan calls out, as data
        assert pin.expand_key and not pin.monotonic_key
        assert register.monotonic_key and not register.expand_key

    def test_every_word_the_abstraction_matches_on_comes_from_the_lexicon(self):
        """A lexicon of words this repo has never printed still works, which is
        what "no rule is hard-coded" means operationally."""
        invented = DeviceLexicon.from_mapping(
            {
                "widget": {
                    "key": "slot",
                    "columns": {"slot": ["slot id"], "label": ["flange label"]},
                    "captions": ["widget schedule"],
                    "key_shape": "^W[0-9]+$",
                }
            }
        )
        table = _block(caption="Table 9-1. Widget Schedule",
                       headers=["Slot ID", "Flange Label"],
                       grid=[["W1", "left"], ["W2", "right"]])
        assert identify_table(table, lexicon=invented) == "widget"
        accepted, rejected = read_device_table(_section(), table, 0, lexicon=invented)
        assert rejected is None and accepted is not None
        assert [(r.key, r.field("label")) for r in accepted.records] == [
            ("W1", "left"), ("W2", "right"),
        ]

    def test_an_unknown_header_leaves_its_field_unmapped(self, tmp_path):
        """The honest half of the map: a word we do not know is *said* to be
        unmapped, never filled in by position beside headers we did know."""
        raw = _built(
            tmp_path, "unknown-header.pdf",
            _table_page("Table 5-1. Pin Functions",
                        ("NO.", "NAME", "I/O", "Ball Location"), PIN_BODY),
        )
        _section_node, table = _one_table(raw)
        spec = load_device_lexicon().by_kind(PIN)
        column_map = map_columns(spec, table)
        assert column_map.via == "header"
        assert column_map.columns == {"pin": 0, "name": 1, "type": 2}
        assert column_map.missing == ("description",)

    def test_teaching_the_variant_is_one_yaml_line(self, tmp_path):
        """The same table, the same code, one phrase added to the shipped
        lexicon file — and the column maps."""
        data = yaml.safe_load(LEXICON_PATH.read_text(encoding="utf-8"))
        data["pin"]["columns"]["description"].append("ball location")
        edited = tmp_path / "device_tables.yaml"
        edited.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

        raw = _built(
            tmp_path, "taught-header.pdf",
            _table_page("Table 5-1. Pin Functions",
                        ("NO.", "NAME", "I/O", "Ball Location"), PIN_BODY),
        )
        _section_node, table = _one_table(raw)
        spec = DeviceLexicon.read(edited).by_kind(PIN)
        assert map_columns(spec, table).columns == {
            "pin": 0, "name": 1, "type": 2, "description": 3,
        }

    def test_a_malformed_entry_never_takes_the_lexicon_down(self, tmp_path, caplog):
        path = tmp_path / "broken.yaml"
        path.write_text(
            "bad_kind: not-a-mapping\n"
            "keyless:\n"
            "  key: nope\n"
            "  columns: {a: [a]}\n"
            "pin:\n"
            "  key: pin\n"
            "  columns:\n"
            "    pin: [pin]\n"
            "    name: [name]\n",
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING):
            lexicon = DeviceLexicon.read(path)
        assert lexicon.kinds == (PIN,)
        # skipped, and *said* to be skipped — a silent drop is a lexicon that
        # quietly stops covering a vendor
        assert "skipping malformed device-table entry" in caplog.text
        assert "keyless" in caplog.text

    def test_an_unreadable_lexicon_identifies_nothing(self, tmp_path):
        """Honest degradation: no device tables, never tables read by a rule
        nobody can see."""
        lexicon = DeviceLexicon.read(tmp_path / "absent.yaml")
        assert lexicon.specs == ()
        assert identify_table(_block(headers=["NO.", "NAME"]), lexicon=lexicon) == ""

    def test_header_normalization_keeps_the_punctuation_that_carries_meaning(self):
        assert normalize_header("  NO.(2) ") == "no."
        assert normalize_header("I/O") == "i/o"
        assert normalize_header("Pin  Number:") == "pin number"


class TestIdentify:
    def test_headers_declare_a_pin_table(self, tmp_path):
        raw = _built(tmp_path, "pins.pdf",
                     _table_page("Table 5-1. Pin Functions",
                                 ("NO.", "NAME", "I/O", "DESCRIPTION"), PIN_BODY))
        section, table = _one_table(raw)
        assert identify_table(table, section_title=section.full_title) == PIN

    def test_headers_declare_a_register_summary(self, tmp_path):
        raw = _built(tmp_path, "regs.pdf",
                     _table_page("Table 7-1. Register Summary",
                                 ("ADDRESS", "NAME", "RESET", "ACCESS"), REG_BODY))
        _section_node, table = _one_table(raw)
        assert identify_table(table) == REGISTER

    def test_a_lone_key_header_is_a_coincidence_not_a_table(self):
        """`No.` alone does not make a pin table — the key column plus one
        more field is the least a header row can declare and be believed."""
        assert identify_table(_block(caption="Table 2. Ordering Information",
                                     headers=["No.", "Comments"],
                                     grid=[["1", "Tape and reel"]])) == ""

    def test_a_field_column_without_the_key_column_claims_nothing(self):
        """`Type` is a register `access` header and a pin `type` header; with
        no address and no pin column beside it, it belongs to neither."""
        assert identify_table(_block(caption="Table 2. Ordering Information",
                                     headers=["Part Number", "Type"],
                                     grid=[["AFE7950IAAV", "BGA"]])) == ""

    def test_a_parametric_spec_table_is_not_a_device_table(self, tmp_path):
        raw = _built(
            tmp_path, "spec.pdf",
            _table_page("Table 3. DAC DC Specifications",
                        ("Parameter", "Min", "Typ", "Unit"),
                        [("DAC RESOLUTION", "16", "", "Bit"),
                         ("Gain Error", "", "1.5", "% FSR"),
                         ("Offset Error", "", "0.05", "% FSR")]),
            section="7 Specifications",
        )
        section, table = _one_table(raw)
        assert identify_table(table, section_title=section.full_title) == ""

    def test_a_caption_names_a_table_its_headers_do_not(self, tmp_path):
        raw = _built(tmp_path, "capless.pdf",
                     _table_page("Table 5-2. Pin Functions", None, PIN_BODY))
        _section_node, table = _one_table(raw)
        assert identify_table(table) == PIN

    def test_a_kind_filter_asks_about_one_kind_only(self, tmp_path):
        raw = _built(tmp_path, "pins-only.pdf",
                     _table_page("Table 5-1. Pin Functions",
                                 ("NO.", "NAME", "I/O", "DESCRIPTION"), PIN_BODY))
        _section_node, table = _one_table(raw)
        assert identify_table(table, kind=REGISTER) == ""
        assert identify_table(table, kind=PIN) == PIN


class TestColumnMapping:
    """Criterion 2: abbreviated headers and no headers at all, each from a PDF."""

    def test_abbreviated_headers_map_by_the_lexicon(self, tmp_path):
        raw = _built(tmp_path, "abbrev.pdf",
                     _table_page("Table 5-1. Pin Functions",
                                 ("NO.", "NAME", "I/O", "DESCRIPTION"), PIN_BODY))
        section, table = _one_table(raw)
        accepted, rejected = read_device_table(section, table, 0)
        assert rejected is None and accepted is not None
        assert accepted.column_map.via == "header"
        assert accepted.column_map.missing == ()
        assert [r.key for r in accepted.records] == ["A1", "A2", "B1"]
        first = accepted.records[0]
        assert first.field("name") == "VSSA"
        assert first.field("type") == "G"
        assert first.field("description") == "Analog ground"
        assert (first.section, first.table_index, first.row_index) == ("5", 0, 0)
        assert first.page == 1

    def test_columns_out_of_the_lexicons_printed_order_still_map(self, tmp_path):
        """TI prints NAME before NO.; the map follows the headers, not the order
        the schema happens to list its fields in."""
        raw = _built(
            tmp_path, "swapped.pdf",
            _table_page("Table 5-1. Pin Functions",
                        ("NAME", "NO.", "I/O", "DESCRIPTION"),
                        [(b, a, c, d) for a, b, c, d in PIN_BODY]),
        )
        section, table = _one_table(raw)
        accepted, _rejected = read_device_table(section, table, 0)
        assert accepted is not None
        assert accepted.column_map.columns == {
            "name": 0, "pin": 1, "type": 2, "description": 3,
        }
        assert [r.key for r in accepted.records] == ["A1", "A2", "B1"]

    def test_a_table_with_no_header_row_maps_positionally(self, tmp_path):
        """The layout floor puts the first row of every region in `headers`, so
        a table that prints no header row puts its first *pin* there. Reading it
        as data is what keeps that pin in the corpus."""
        raw = _built(tmp_path, "headerless.pdf",
                     _table_page("Table 5-2. Pin Functions", None, PIN_BODY))
        section, table = _one_table(raw)
        assert table.headers[0] == "A1", "fixture precondition: no header row"

        accepted, rejected = read_device_table(section, table, 0)
        assert rejected is None and accepted is not None
        assert accepted.column_map.via == "positional"
        assert accepted.column_map.header_row_is_data
        assert [r.key for r in accepted.records] == ["A1", "A2", "B1"]
        assert accepted.records[0].row_index == HEADER_ROW_INDEX
        assert accepted.records[0].field("description") == "Analog ground"

    def test_a_row_that_prints_no_key_is_skipped_and_counted(self):
        """A band row inside a pin table is not a pin; it is also not something
        to drop quietly."""
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[
                ["", "POWER SUPPLIES", "", ""],
                ["A2", "VDD1P8", "P", "1.8 V analog supply"],
                ["B1", "RXCLK", "I", "Receiver clock input"],
            ],
        )
        accepted, _rejected = read_device_table(_section(), table, 0)
        assert accepted is not None
        assert [r.key for r in accepted.records] == ["A2", "B1"]
        assert accepted.unkeyed_rows == (0,)
        assert any("print no pin" in w for w in accepted.warnings)


class TestValidationRejectsWholeTables:
    """Criterion 3: rejected with a reason, never emitted partially."""

    def test_a_duplicate_pin_rejects_the_table(self, tmp_path):
        raw = _built(
            tmp_path, "dup.pdf",
            _table_page("Table 5-1. Pin Functions",
                        ("NO.", "NAME", "I/O", "DESCRIPTION"),
                        [("A1", "VSSA", "G", "Analog ground"),
                         ("A2", "VDD1P8", "P", "1.8 V analog supply"),
                         ("A1", "RXCLK", "I", "Receiver clock input")]),
        )
        section, table = _one_table(raw)
        accepted, rejected = read_device_table(section, table, 0)
        assert accepted is None and rejected is not None
        assert rejected.kind == PIN
        assert 'duplicate pin "A1"' in rejected.reason

        # nothing partial reaches a consumer
        assert read_device_tables(raw).records == []

    def test_addresses_out_of_order_reject_the_table(self, tmp_path):
        raw = _built(
            tmp_path, "nonmono.pdf",
            _table_page("Table 7-1. Register Summary",
                        ("ADDRESS", "NAME", "RESET", "ACCESS"),
                        [("0x0000", "CHIP_ID", "0x01", "R"),
                         ("0x0008", "SCRATCH", "0x00", "R/W"),
                         ("0x0004", "TXDIG_CTRL0", "0x00", "R/W")]),
        )
        section, table = _one_table(raw)
        accepted, rejected = read_device_table(section, table, 0)
        assert accepted is None and rejected is not None
        assert rejected.kind == REGISTER
        assert '"0x0008" then "0x0004"' in rejected.reason
        assert read_device_tables(raw).records == []

    def test_the_same_register_table_in_order_is_accepted(self, tmp_path):
        raw = _built(tmp_path, "mono.pdf",
                     _table_page("Table 7-1. Register Summary",
                                 ("ADDRESS", "NAME", "RESET", "ACCESS"), REG_BODY))
        section, table = _one_table(raw)
        accepted, rejected = read_device_table(section, table, 0)
        assert rejected is None and accepted is not None
        assert [r.key for r in accepted.records] == ["0x0000", "0x0004", "0x0008"]
        assert accepted.records[1].field("reset") == "0x00"
        assert accepted.records[1].field("access") == "R/W"

    def test_a_table_with_no_key_column_is_rejected_not_guessed(self):
        table = _block(
            caption="Table 5-1. Pin Functions",
            headers=["NAME", "DESCRIPTION"],
            grid=[["VSSA", "Analog ground"], ["VDD1P8", "1.8 V analog supply"]],
        )
        accepted, rejected = read_device_table(_section(), table, 0)
        assert accepted is None and rejected is not None
        assert rejected.reason == "no pin column"

    def test_a_repeated_address_rejects_a_register_summary(self):
        table = _block(
            caption="Table 7-1. Register Summary",
            headers=["ADDRESS", "NAME", "RESET", "ACCESS"],
            grid=[["0x0000", "CHIP_ID", "0x01", "R"],
                  ["0x0000", "CHIP_ID_COPY", "0x01", "R"]],
        )
        _accepted, rejected = read_device_table(_section(number="7.1"), table, 0)
        assert rejected is not None
        assert 'duplicate address "0x0000"' in rejected.reason


class TestProseIsNotADeviceTable:
    """Criterion 6: the device-table half of the no-hallucinated-tables rule."""

    def test_columns_of_prose_under_a_pin_caption_are_rejected(self):
        table = _block(
            caption="Table 5-3. Pin Configuration",
            headers=["Overview", "Remarks"],
            grid=[
                ["The device powers up in standby", "See the bring-up sequence"],
                ["Each supply requires local decoupling", "Place close to the ball"],
                ["Unused inputs must be terminated", "Do not float"],
            ],
        )
        accepted, rejected = read_device_table(_section(), table, 0)
        assert accepted is None and rejected is not None
        assert "does not hold pin keys" in rejected.reason

    def test_a_spec_table_is_neither_accepted_nor_recorded_as_a_rejection(self, tmp_path):
        """Not a device table is not a finding: a manifest full of reasons about
        spec tables would bury the real ones."""
        raw = _built(
            tmp_path, "spec-quiet.pdf",
            _table_page("Table 3. DAC DC Specifications",
                        ("Parameter", "Min", "Typ", "Unit"),
                        [("DAC RESOLUTION", "16", "", "Bit"),
                         ("Gain Error", "", "1.5", "% FSR"),
                         ("Offset Error", "", "0.05", "% FSR")]),
            section="7 Specifications",
        )
        result = read_device_tables(raw)
        assert (result.n_candidates, result.n_accepted, result.n_rejected) == (0, 0, 0)
        assert result.records == []


class TestMultiValueKeysExpand:
    """Criterion 5: `A1, A2, B1` and `A1-A4`, each record still citing its row."""

    @pytest.mark.parametrize(
        ("cell", "keys"),
        [
            ("A1, A2, B1", ["A1", "A2", "B1"]),
            ("A1-A4", ["A1", "A2", "A3", "A4"]),
            (f"A1{EN_DASH}A4", ["A1", "A2", "A3", "A4"]),
            ("12 to 14", ["12", "13", "14"]),
            ("A1, B1-B3", ["A1", "B1", "B2", "B3"]),
            ("A01-A03", ["A01", "A02", "A03"]),  # printed width is preserved
            ("A1", ["A1"]),
            ("", []),
        ],
    )
    def test_expansion_shapes(self, cell, keys):
        assert expand_keys(cell) == keys

    @pytest.mark.parametrize("cell", ["RXA-CLK", "VDD-VSS", "A1-B4"])
    def test_a_dash_that_is_not_a_range_stays_one_key(self, cell):
        """A range needs a shared alphabetic prefix and a count upward.
        Everything else is a name that happens to hold a hyphen."""
        assert expand_keys(cell) == [cell]

    def test_a_range_too_wide_to_believe_is_kept_whole_and_said_so(self):
        assert expand_keys("A1-A9999") == ["A1-A9999"]
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[["A1-A9999", "VSSA", "G", "Analog ground"],
                  ["B1", "RXCLK", "I", "Receiver clock input"],
                  ["B2", "RXCLKB", "I", "Receiver clock input"],
                  ["B3", "TXCLK", "O", "Transmitter clock output"]],
        )
        accepted, _rejected = read_device_table(_section(), table, 0)
        assert accepted is not None
        assert any("spans more than" in w for w in accepted.warnings)

    def test_a_hyphenated_name_is_not_reported_as_an_oversized_range(self):
        """`A1-B4` crosses prefixes, so it is a name, not a range that was too
        wide — reporting it as one would be a warning about nothing."""
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[["A1-B4", "VSSA", "G", "Analog ground"],
                  ["B1", "RXCLK", "I", "Receiver clock input"],
                  ["B2", "RXCLKB", "I", "Receiver clock input"],
                  ["B3", "TXCLK", "O", "Transmitter clock output"]],
        )
        accepted, _rejected = read_device_table(_section(), table, 0)
        assert accepted is not None
        assert accepted.warnings == ()
        assert [r.key for r in accepted.records] == ["A1-B4", "B1", "B2", "B3"]

    def test_an_address_range_is_never_expanded(self):
        """`0x00-0xFF` is one block; 256 records would be 255 inventions."""
        assert expand_keys("0x00-0xFF", expand=False) == ["0x00-0xFF"]

    def test_every_expanded_record_keeps_its_rows_provenance(self):
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[
                ["A1, A2, B1", "VSSA", "G", "Analog ground"],
                ["C1-C3", "VDD1P8", "P", "1.8 V analog supply"],
            ],
            row_pages=[4, 5],
        )
        accepted, _rejected = read_device_table(_section(), table, 2)
        assert accepted is not None
        assert [r.key for r in accepted.records] == [
            "A1", "A2", "B1", "C1", "C2", "C3",
        ]
        for record in accepted.records[:3]:
            assert record.key_verbatim == "A1, A2, B1"
            assert (record.section, record.table_index, record.row_index) == ("5.1", 2, 0)
            assert record.page == 4
            assert record.field("name") == "VSSA"
            assert record.row_verbatim == ("A1, A2, B1", "VSSA", "G", "Analog ground")
        for record in accepted.records[3:]:
            assert record.key_verbatim == "C1-C3"
            assert record.row_index == 1
            assert record.page == 5, "a continuation row cites its own printed page"

    def test_an_expansion_that_collides_rejects_the_table(self):
        """Two rows claiming A2 is a misread grid, and it is refused whole —
        even though only the expansion makes the collision visible."""
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[["A1-A3", "VSSA", "G", "Analog ground"],
                  ["A2", "VDD1P8", "P", "1.8 V analog supply"]],
        )
        accepted, rejected = read_device_table(_section(), table, 0)
        assert accepted is None and rejected is not None
        assert 'duplicate pin "A2"' in rejected.reason


class TestWrappedRowsAreOneEntry:
    """Phase 6, ticket 04's addition: a printed entry that occupies several
    grid rows is one entry.

    A real ADI pin table breaks a long description — and a long key list, and
    sometimes the name itself — over several lines, and the ticket-09 rowspan
    materialization replicates the key cell into each of them. Read literally
    that is a duplicate key, and a duplicate key rejects the whole table: a
    322-pin table would be thrown away because its descriptions are long.

    The reading is deliberately narrow, and each of the four cases below is one
    half of that narrowness.
    """

    def test_a_line_with_no_name_continues_the_entry_above(self):
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[
                ["D10, R10", "VDD1_NVG", "Input", "Analog 1.0 V Supply Inputs for the"],
                ["D10, R10", "", "", "Negative Voltage Generator."],
                ["B1", "RXCLK", "I", "Receiver clock input"],
            ],
        )
        accepted, rejected = read_device_table(_section(), table, 0)
        assert rejected is None and accepted is not None
        assert [r.key for r in accepted.records] == ["D10", "R10", "B1"]
        assert accepted.records[0].field("description") == (
            "Analog 1.0 V Supply Inputs for the Negative Voltage Generator."
        )

    def test_a_wrapped_key_list_adds_its_keys_to_the_entry_above(self):
        """`GND` prints one name and eight lines of ball numbers; every one of
        those balls is a GND pin, and a designer greping for the last of them
        must find it."""
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[
                ["A1, A3, A4", "GND", "Input/output", "Ground References."],
                ["B2 to B4, C2", "", "", ""],
            ],
        )
        accepted, _rejected = read_device_table(_section(), table, 0)
        assert accepted is not None
        assert [r.key for r in accepted.records] == [
            "A1", "A3", "A4", "B2", "B3", "B4", "C2",
        ]
        assert {r.field("name") for r in accepted.records} == {"GND"}
        # each key still quotes the line it was printed on
        assert accepted.records[-1].key_verbatim == "B2 to B4, C2"
        assert accepted.records[-1].row_index == 1

    def test_a_repeated_key_continues_only_an_unfinished_name(self):
        """`SERDOUT0+,` has not finished naming itself, so the next line — which
        repeats the key cell — is the rest of that name."""
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[
                ["A15, A14", "SERDOUT0+,", "Output", "JTx Lane 0 Outputs,"],
                ["A15, A14", "SERDOUT0−", "", "Data True/Complement."],
            ],
        )
        accepted, rejected = read_device_table(_section(), table, 0)
        assert rejected is None and accepted is not None
        assert [r.key for r in accepted.records] == ["A15", "A14"]
        assert accepted.records[0].field("name") == "SERDOUT0+, SERDOUT0−"

    def test_a_repeated_key_under_a_finished_name_is_still_a_duplicate(self):
        """The other half of the rule, and the one that keeps it honest: two
        complete entries claiming pin 15 is a misread grid, and the table is
        refused whole even though merging them would have "worked"."""
        table = _block(
            headers=["NO.", "NAME", "DESCRIPTION"],
            grid=[
                ["15", "LO", "LO Port, dc-coupled and matched to 50 ohm."],
                ["15", "EPAD", "Exposed Pad. Connect to the GND pin."],
            ],
        )
        accepted, rejected = read_device_table(_section(), table, 0)
        assert accepted is None and rejected is not None
        assert 'duplicate pin "15"' in rejected.reason

    def test_a_name_ending_in_a_mnemonic_character_is_a_finished_name(self):
        """Regression: `+`, `-` and `/` end ordinary mnemonics, so they may not
        read as "this name is unfinished".

        `VREF+` and `VREF-` are two complete pin names. If a trailing `+` were
        a continuation marker, a misread grid claiming ball A1 twice would be
        *merged* — one pin silently lost and two names fused into a string the
        page never printed, published with a page citation — instead of being
        refused whole. A partial pin table that looks complete is precisely the
        failure invariant 8 exists to prevent, so only the list separator marks
        an unfinished name.
        """
        for finished, wrapped in (("VREF+", "VREF-"), ("RESET-", "SDIO"), ("CS/", "SDO")):
            table = _block(
                headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
                grid=[
                    ["A1", finished, "Input", "Positive reference input."],
                    ["A1", wrapped, "Input", "Negative reference input."],
                    ["A2", "GND", "Ground", "Ground."],
                ],
            )
            accepted, rejected = read_device_table(_section(), table, 0)
            assert accepted is None, f"{finished}/{wrapped} must not merge"
            assert rejected is not None and 'duplicate pin "A1"' in rejected.reason

    def test_a_merge_never_chains_past_the_line_that_finished_the_name(self):
        """A third line claiming the same key is a duplicate again: absorbing a
        continuation must not leave the entry permanently open."""
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[
                ["A15, A14", "SERDOUT0+,", "Output", "JTx Lane 0 Outputs,"],
                ["A15, A14", "SERDOUT0−", "", "Data True/Complement."],
                ["A15, A14", "SPARE", "", "Something else entirely."],
            ],
        )
        accepted, rejected = read_device_table(_section(), table, 0)
        assert accepted is None and rejected is not None
        assert 'duplicate pin "A15"' in rejected.reason

    def test_a_band_header_before_the_first_entry_is_not_a_key(self):
        """`POWER SUPPLIES` opens an ADI pin table and belongs to no pin.
        Emitting it as one would put a record in `pins.json` keyed on a
        sentence."""
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[
                ["POWER SUPPLIES", "", "", ""],
                ["A2", "VDD1P8", "P", "1.8 V analog supply"],
                ["B1", "RXCLK", "I", "Receiver clock input"],
            ],
        )
        accepted, _rejected = read_device_table(_section(), table, 0)
        assert accepted is not None
        assert [r.key for r in accepted.records] == ["A2", "B1"]
        assert accepted.unkeyed_rows == (0,)

    def test_a_kind_that_declares_no_identity_reads_every_line_as_an_entry(self):
        """The reading is opt-in per kind (`identity:` in the lexicon), so a
        kind that has not said which column identifies a row keeps the exact
        behaviour it had before — including rejecting on a repeated key."""
        assert load_device_lexicon().by_kind(REGISTER).identity_field == ""
        table = _block(
            caption="Table 7-1. Register Summary",
            headers=["ADDRESS", "NAME", "RESET", "ACCESS"],
            grid=[["0x0000", "CHIP_ID", "0x01", "R"],
                  ["0x0000", "", "", "continued"]],
        )
        _accepted, rejected = read_device_table(_section(number="7.1"), table, 0)
        assert rejected is not None
        assert 'duplicate address "0x0000"' in rejected.reason

    def test_an_identity_naming_a_column_that_does_not_exist_is_refused(self, caplog):
        with caplog.at_level(logging.WARNING):
            lexicon = DeviceLexicon.from_mapping(
                {"pin": {"key": "pin", "identity": "nope",
                         "columns": {"pin": ["pin"], "name": ["name"]}}}
            )
        assert lexicon.by_kind(PIN).identity_field == ""
        assert "identity 'nope' is not one of its columns" in caplog.text


class TestRejectionsAreMeasurable:
    """Criterion 4: the reasons land where the reconstruction gate's do."""

    def test_reasons_join_extraction_stats(self, tmp_path):
        raw = _built(
            tmp_path, "measurable.pdf",
            _table_page("Table 5-1. Pin Functions",
                        ("NO.", "NAME", "I/O", "DESCRIPTION"),
                        [("A1", "VSSA", "G", "Analog ground"),
                         ("A2", "VDD1P8", "P", "1.8 V analog supply"),
                         ("A1", "RXCLK", "I", "Receiver clock input")]),
        )
        result = read_device_tables(raw)
        assert (result.n_candidates, result.n_rejected) == (1, 1)

        stats = raw.extraction_stats
        assert stats is not None
        before = (stats.tables_detected, stats.tables_accepted, stats.tables_rejected)
        record_rejections(stats, result.rejections)

        line = stats.rejection_reasons[-1]
        assert line.startswith(f"{REJECTION_PREFIX} (pin) §5 table 0")
        assert 'duplicate pin "A1"' in line
        # the counts measure *reconstruction*: this table reconstructed fine
        assert (stats.tables_detected, stats.tables_accepted, stats.tables_rejected) == before

    def test_recording_is_idempotent_and_capped(self):
        stats = ExtractionStats(backend="pdf_layout", rejection_reasons=["columns not stable"])
        rejections = [
            DeviceTableRejection(kind=PIN, section="5", table_index=i,
                                 reason="no rows carry a pin")
            for i in range(12)
        ]
        record_rejections(stats, rejections)
        record_rejections(stats, rejections)
        device_lines = [r for r in stats.rejection_reasons if r.startswith(REJECTION_PREFIX)]
        assert len(device_lines) == 8
        assert stats.rejection_reasons[0] == "columns not stable", "gate reasons survive"

    def test_a_rejection_describes_where_it_happened(self):
        rejection = DeviceTableRejection(
            kind=REGISTER, section="7.2", table_index=1, page=212,
            reason="addresses out of order",
        )
        assert rejection.describe() == (
            "device-table (register) §7.2 table 1 p.212: addresses out of order"
        )


class TestDocumentLevelRead:
    def test_a_document_reports_accepted_rejected_and_records(self):
        good = TableBlock(
            caption="Table 5-1. Pin Functions",
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[["A1", "VSSA", "G", "Analog ground"],
                  ["A2", "VDD1P8", "P", "1.8 V analog supply"]],
            page=4,
        )
        bad = TableBlock(
            caption="Table 5-2. Pin Functions",
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[["B1", "RXCLK", "I", "Receiver clock input"],
                  ["B1", "RXCLKB", "I", "Receiver clock input"]],
            page=5,
        )
        raw = _raw([_section(tables=[good, bad])])
        result = read_device_tables(raw, kind=PIN)
        assert (result.n_candidates, result.n_accepted, result.n_rejected) == (2, 1, 1)
        assert [r.key for r in result.records] == ["A1", "A2"]
        assert result.describe() == "1 of 2 device tables accepted, 2 records"

    def test_a_degraded_backend_yields_no_device_tables(self):
        """`pdf_text` carries no trusted tables — the same rule `build_specset`
        applies. A device table read out of one would be a table nobody
        extracted."""
        table = TableBlock(headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
                           grid=[["A1", "VSSA", "G", "Analog ground"],
                                 ["A2", "VDD1P8", "P", "1.8 V supply"]])
        raw = _raw([_section(tables=[table])], extractor="pdf_text")
        assert read_device_tables(raw).n_candidates == 0


class TestReadingIsPureAndReproducible:
    """The abstraction quotes tables; it never edits them, and it says the same
    thing twice — a derived artifact built on it has to be reproducible."""

    def test_no_verbatim_cell_is_touched(self):
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[[f"C1{EN_DASH}C3", "VSSA", "G", "Analog  ground"],
                  ["B1", "RXCLK", "I", "Receiver clock input"]],
        )
        before = ([list(row) for row in table.grid], list(table.headers))
        raw = _raw([_section(tables=[table])])
        result = read_device_tables(raw)
        assert ([list(row) for row in table.grid], list(table.headers)) == before
        # the *keys* are normalized so they can be compared and grepped; the
        # cell the datasheet printed travels with each of them, untouched
        assert [r.key for r in result.records] == ["C1", "C2", "C3", "B1"]
        assert result.records[0].key_verbatim == f"C1{EN_DASH}C3"
        assert result.records[0].row_verbatim[3] == "Analog  ground"

    def test_two_reads_of_one_document_agree(self):
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[["A1, A2", "VSSA", "G", "Analog ground"],
                  ["B1", "RXCLK", "I", "Receiver clock input"]],
        )
        raw = _raw([_section(tables=[table])])
        first = [(r.key, r.page, r.row_index) for r in read_device_tables(raw).records]
        second = [(r.key, r.page, r.row_index) for r in read_device_tables(raw).records]
        assert first == second == [
            ("A1", 4, 0), ("A2", 4, 0), ("B1", 4, 1),
        ]


class TestCountCrossCheckWarnsAndIsRecorded:
    """ADR 0005: a count parsed from prose may not suppress a good table."""

    def test_a_mismatch_warns_and_keeps_every_record(self):
        table = _block(
            headers=["NO.", "NAME", "I/O", "DESCRIPTION"],
            grid=[["A1", "VSSA", "G", "Analog ground"],
                  ["A2", "VDD1P8", "P", "1.8 V analog supply"]],
        )
        raw = _raw([_section(tables=[table])])
        result = read_device_tables(raw, kind=PIN, expected_count=196)
        assert len(result.records) == 2, "a bad count never throws away a good table"
        assert result.n_rejected == 0
        assert result.warnings[-1] == (
            "pin count mismatch: document states 196, table yields 2"
        )

    def test_an_agreeing_count_says_nothing(self):
        assert cross_check_count([], 0) == ""
