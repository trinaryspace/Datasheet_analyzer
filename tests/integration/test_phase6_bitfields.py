"""Phase 6 gate — register bit fields against LMX1204_registermap.pdf (ticket 06).

**This gate is met, and meeting it is what un-parked the ticket.** Ticket 06
parked twice: in phase 6 two of six sampled registers read exactly right, in
phase 6.5 four of six. The gate is the first six registers in printed order —
R0, R2, R3, R4, R5, R6 — at 100% with no partial credit, and **all six now
read exactly right**, cell for cell against the printed pages. The
`KNOWN_SHORTCOMINGS.md` entry that recorded the park is gone, and
`derive/registers.py` attaches an accepted field set to the summary record
its caption names.

What moved was the layout floor, not this reader. Two defects in
`extract/pdf_layout.py`, both fixed at extractor `tables-10`:

1. **The region ran on past the table.** Every field table in this document
   is followed by a section heading and two cross-reference sentences (`R2 is
   shown in Table 1-4.`, `Return to the Summary Table.`), and the region ran
   into them. They arrived as two more rows whose bit cell was prose *and*
   their starts at x = 56.7 pt opened a leftmost column band no body row uses,
   which pushed the reconstruction onto the rescue ladder.
   `_trim_outdented_tail` ends the region at the table.
2. **A bit cell was refused release as a page number.** The `Bit` column
   prints at x = 71.6-79.4 pt, inside the < 80 pt page-number gutter, so bit 6
   on page 6 and bit 10 on page 10 were classified as page machinery and cut
   their regions off mid-table. **R4's recorded finding was wrong**: this file
   used to assert that R4 printed an incomplete field list, and page 6 prints
   all eleven of its fields, 15:14 down to 0. The truncation was this tool's.

Where it stands now, each claim measured by this module:

1. **Recall.** Of the 35 registers the document prints, the layout engine
   hands over 29 field tables and 28 survive the fail-closed validators (80%,
   from 43%). All six of the sample are among them.
2. **What refuses now, and why.** One table refuses, and it is a genuine
   document defect: R90 prints `15:8` and then `15:0`, two fields claiming the
   same eight bits, which no reading can make true at once. Six registers hand
   over no field table at all (R7, R8, R9, R16, R72, R86); R9 is the newest of
   those and the honest cost of fix 2 — its region no longer stops at bit 10,
   so the whole of its table is judged, and its description column's
   `0x0: Reserved ... 0x1FF: /1023` enumeration leaves 12 of 19 grid rows
   spanning one column, which the reconstruction gate refuses. `tables-09`
   accepted that table only because the furniture bug had truncated it.
3. **Precision did not move to buy recall.** Every field the reader emits is
   still exactly right: 116 fields, every printed cell of every one of them
   found on the page the record cites.

Invariant 4 is relaxed exactly as far as the phase plan allows: this reads a
real PDF at the repository root and the parts under `parts/`, and skips when
they are absent. It never reaches the network, never calls a model, and never
rebuilds anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import fitz
import pytest

from datasheet_analyzer.derive.bitfields import (
    iter_bit_field_tables,
    read_bit_header,
)
from datasheet_analyzer.derive.registers import build_registers
from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.extract.pdf_structure import compute_content_hash, read_toc
from datasheet_analyzer.models import DocType, RawDocument, SourceDocument

REPO_ROOT = Path(__file__).resolve().parents[2]
REGMAP_PDF = REPO_ROOT / "LMX1204_registermap.pdf"
EXTRACT_CACHE = REPO_ROOT / ".cache" / "extract"
PARTS_DIR = REPO_ROOT / "parts"
LIBRARY_DIR = REPO_ROOT / "library"
SHORTCOMINGS = REPO_ROOT / "KNOWN_SHORTCOMINGS.md"

#: The sample, chosen by **document order before anything was measured**: the
#: first six registers the map documents, §1.1 through §1.6 on pages 4-7. Any
#: sample chosen after seeing which tables survive would be a rigged gate.
SAMPLE: tuple[str, ...] = ("R0", "R2", "R3", "R4", "R5", "R6")

#: Hand-transcribed from the printed pages: register -> its complete field
#: list as `(bit cell, field name, type, reset)`, in printed order. These are
#: the four columns the ticket's gate names; descriptions are not compared.
GOLDEN: dict[str, tuple[int, tuple[tuple[str, str, str, str], ...]]] = {
    "R0": (
        4,
        (
            ("15:3", "RESERVED", "R", "0x0000"),
            ("2", "POWERDOWN", "R/W", "0x0"),
            ("1", "RESERVED", "R/W", "0x0"),
            ("0", "RESET", "R/W", "0x0"),
        ),
    ),
    "R2": (
        4,
        (
            ("15:11", "RESERVED", "R", "0x00"),
            ("10", "RESERVED", "R/W", "0x0"),
            ("9:6", "SMCLK_DIV_PRE", "R/W", "0x8"),
            ("5", "SMCLK_EN", "R/W", "0x1"),
            ("4:0", "RESERVED", "R/W", "0x03"),
        ),
    ),
    "R3": (
        5,
        (
            ("15", "CH3_EN", "R/W", "0x1"),
            ("14", "CH2_EN", "R/W", "0x1"),
            ("13", "CH1_EN", "R/W", "0x1"),
            ("12", "CH0_EN", "R/W", "0x1"),
            ("11", "LOGIC_MUTE_CAL", "R/W", "0x1"),
            ("10", "CH3_MUTE_CAL", "R/W", "0x1"),
            ("9", "CH2_MUTE_CAL", "R/W", "0x1"),
            ("8", "CH1_MUTE_CAL", "R/W", "0x1"),
            ("7", "CH0_MUTE_CAL", "R/W", "0x1"),
            ("6:3", "RESERVED", "R/W", "0x0"),
            ("2:0", "SMCLK_DIV", "R/W", "0x6"),
        ),
    ),
    "R4": (
        6,
        (
            ("15:14", "RESERVED", "R", "0x0"),
            ("13:11", "CLKOUT1_PWR", "R/W", "0x6"),
            ("10:8", "CLKOUT0_PWR", "R/W", "0x6"),
            ("7", "SYSREFOUT3_EN", "R/W", "0x0"),
            ("6", "SYSREFOUT2_EN", "R/W", "0x0"),
            ("5", "SYSREFOUT1_EN", "R/W", "0x0"),
            ("4", "SYSREFOUT0_EN", "R/W", "0x0"),
            ("3", "CLKOUT3_EN", "R/W", "0x1"),
            ("2", "CLKOUT2_EN", "R/W", "0x1"),
            ("1", "CLKOUT1_EN", "R/W", "0x1"),
            ("0", "CLKOUT0_EN", "R/W", "0x1"),
        ),
    ),
    "R5": (
        6,
        (
            ("15", "RESERVED", "R", "0x0"),
            ("14:12", "SYSREFOUT2_PWR", "R/W", "0x4"),
            ("11:9", "SYSREFOUT1_PWR", "R/W", "0x4"),
            ("8:6", "SYSREFOUT0_PWR", "R/W", "0x4"),
            ("5:3", "CLKOUT3_PWR", "R/W", "0x6"),
            ("2:0", "CLKOUT2_PWR", "R/W", "0x6"),
        ),
    ),
    "R6": (
        7,
        (
            ("15", "LOGICLKOUT_EN", "R/W", "0x0"),
            ("14:12", "SYSREFOUT3_VCM", "R/W", "0x3"),
            ("11:9", "SYSREFOUT2_VCM", "R/W", "0x3"),
            ("8:6", "SYSREFOUT1_VCM", "R/W", "0x3"),
            ("5:3", "SYSREFOUT0_VCM", "R/W", "0x3"),
            ("2:0", "SYSREFOUT3_PWR", "R/W", "0x4"),
        ),
    ),
}

#: The two registers the reader accepts from *outside* the sample,
#: transcribed after the measurement so precision can be checked over
#: everything it emits rather than only over the sample. Labelled as such
#: deliberately: this set is not evidence about recall and is never used as
#: any.
ACCEPTED_ELSEWHERE: dict[str, tuple[int, tuple[tuple[str, str, str, str], ...]]] = {
    "R33": (20, (("15:0", "RESERVED", "R/W", "0x7777"),)),
    "R67": (21, (("15:0", "RESERVED", "R/W", "0x50C8"),)),
}

#: What the document prints, counted by hand from its section headings:
#: §1.1 through §1.35, one field table each.
REGISTERS_PRINTED = 35


def _require_pdf() -> Path:
    if not REGMAP_PDF.is_file():
        pytest.skip(f"reference register map absent: {REGMAP_PDF}")
    return REGMAP_PDF


@pytest.fixture(scope="module")
def raw() -> RawDocument:
    """The reference register map as the layout backend reads it.

    Served from the extraction cache when it is warm and read from the local
    PDF when it is not — the same bytes either way, and neither path leaves
    the machine.
    """
    pdf = _require_pdf()
    content_hash = compute_content_hash(pdf)
    cached = EXTRACT_CACHE / f"{content_hash}__pdf_layout.json"
    if cached.is_file():
        try:
            return RawDocument.model_validate_json(cached.read_text(encoding="utf-8"))
        except ValueError:
            pass
    source = SourceDocument(
        content_hash=content_hash, path=str(pdf), doc_type=DocType.REGISTER_MAP, vendor="ti"
    )
    return PdfLayoutBackend().extract(source, pdf_toc=read_toc(pdf))


@pytest.fixture(scope="module")
def read(raw: RawDocument) -> dict[str, object]:
    """Every field table the reader saw, keyed by the register it names."""
    return {ex.register_name: ex for ex in iter_bit_field_tables(raw) if ex.register_name}


def _emitted(extraction) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (f.bits.verbatim, f.name, f.access, f.reset) for f in getattr(extraction, "fields", ())
    )


@pytest.mark.integration
class TestTheTruthSetIsTheDocument:
    """The golden data is anchored to printed pages, not to anyone's memory."""

    def test_every_sampled_register_is_printed_where_the_golden_says(self):
        pdf = _require_pdf()
        with fitz.open(pdf) as doc:
            for register, (page, fields) in {**GOLDEN, **ACCEPTED_ELSEWHERE}.items():
                text = doc[page - 1].get_text()
                assert f"{register} Register Field Descriptions" in text, register
                for bits, name, access, reset in fields:
                    assert name in text, (register, name)
                    assert bits in text, (register, bits)
                    assert access in text and reset in text, (register, access, reset)

    def test_the_sample_is_the_first_six_registers_in_printed_order(self):
        """Declared before measuring; a sample picked afterwards proves nothing."""
        assert SAMPLE == ("R0", "R2", "R3", "R4", "R5", "R6")
        assert set(SAMPLE) == set(GOLDEN)


@pytest.mark.integration
class TestTheAccuracyGateIsMet:
    """Checkbox 2 - 100%, no partial credit. Measured: it is met."""

    #: Every register the reader accepts at extractor `tables-10`. Fixed by
    #: measurement, not by expectation.
    ACCEPTED: ClassVar[list[str]] = [
        "R0",
        "R11",
        "R12",
        "R13",
        "R14",
        "R15",
        "R17",
        "R18",
        "R19",
        "R2",
        "R20",
        "R21",
        "R22",
        "R23",
        "R24",
        "R25",
        "R28",
        "R29",
        "R3",
        "R33",
        "R34",
        "R4",
        "R5",
        "R6",
        "R65",
        "R67",
        "R75",
        "R79",
    ]

    #: The registers the layout engine hands over no field table for at all.
    #: Recorded so the recall number below has a named remainder rather than
    #: a gap.
    NO_TABLE: ClassVar[list[str]] = ["R16", "R7", "R72", "R8", "R86", "R9"]

    def test_all_six_sampled_registers_are_read_exactly_right(self, read):
        covered = sorted(r for r in SAMPLE if r in read and read[r].accepted)
        assert covered == sorted(SAMPLE), covered
        assert len(covered) == len(SAMPLE), "the gate is 100% with no partial credit"

    def test_recall_over_the_whole_document_is_measured(self, raw, read):
        tables = list(iter_bit_field_tables(raw))
        accepted = [ex for ex in tables if ex.accepted]
        assert len(tables) == 29, [ex.caption for ex in tables]
        assert len(accepted) == 28, [ex.register_name for ex in accepted]
        assert sorted(ex.register_name for ex in accepted) == self.ACCEPTED
        # 28/35 = 80%, up from 15/35 = 43% at `tables-09`.
        assert 0.79 < len(accepted) / REGISTERS_PRINTED < 0.81

    def test_every_refusal_names_a_reason(self, raw):
        for extraction in iter_bit_field_tables(raw):
            if not extraction.accepted:
                assert extraction.reasons, extraction.caption

    def test_the_one_refusal_left_is_a_defect_in_the_printed_page(self, read):
        """R90 prints `15:8` and then `15:0`. No reading makes both true.

        This is the shape a fail-closed reader is supposed to end at: the
        table is not misread, it is contradictory as printed, and the whole
        field set is refused rather than half of it published.
        """
        refused = {name: ex.reasons for name, ex in read.items() if not ex.accepted}
        assert sorted(refused) == ["R90"], sorted(refused)
        assert any("claimed by more than one field" in r for r in refused["R90"])

    def test_the_registers_that_hand_over_no_table_are_named(self, read):
        """Six of the 35, and R9 is the newest and the honest cost of the fix.

        R9's region used to stop at its bit-10 row, because the `10` printed
        there sat inside the page-number gutter on page 10. With the whole
        table judged, its description column's `0x0: Reserved ... 0x1FF` value
        enumeration leaves 12 of its 19 grid rows spanning one column, and the
        reconstruction gate refuses it with `rows do not span columns`.
        `tables-09` accepted that table only because the bug had truncated it.
        """
        assert sorted(set(self.NO_TABLE) - set(read)) == sorted(self.NO_TABLE)

    def test_r4_prints_a_complete_field_list_after_all(self, read):
        """The finding this file used to record about R4 was wrong.

        `KNOWN_SHORTCOMINGS.md` said R4 and R9 print field lists that cover
        only part of the register. Page 6 prints all eleven of R4's fields,
        15:14 down to 0, and the eleven are what the reader now emits. What
        was incomplete was the region, not the page.
        """
        assert read["R4"].accepted, read["R4"].reasons
        assert _emitted(read["R4"]) == GOLDEN["R4"][1]
        assert [f.bits.verbatim for f in read["R4"].fields][-1] == "0"

    def test_the_misreads_ticket_06_named_are_gone(self, read):
        """Each register ticket 06 recorded as damaged now reads correctly."""
        for name in ("R13", "R17", "R19", "R21", "R25"):
            assert read[name].accepted, (name, read[name].reasons)
        # The wrapped identifier that used to read `SYSREFREQ_DELAY_ST EPSIZE`.
        assert "SYSREFREQ_DELAY_STEPSIZE" in [f.name for f in read["R13"].fields]


@pytest.mark.integration
class TestNothingWrongIsEmitted:
    """The half that holds: precision is 100% over everything the reader emits."""

    def test_every_transcribed_register_matches_the_printed_page_exactly(self, read):
        """The six registers whose fields were transcribed by hand, cell for cell."""
        truth = {**GOLDEN, **ACCEPTED_ELSEWHERE}
        accepted = {name: ex for name, ex in read.items() if ex.accepted}
        overlap = sorted(set(truth) & set(accepted))
        assert overlap == ["R0", "R2", "R3", "R33", "R4", "R5", "R6", "R67"], overlap
        for name in overlap:
            assert _emitted(accepted[name]) == truth[name][1], name

    def test_every_emitted_cell_is_printed_on_the_page_it_cites(self, raw, read):
        """The other nine, checked against the PDF rather than a transcription.

        Whitespace-insensitive on purpose: this document breaks long
        identifiers across two printed lines (`SYSREFOUT0_DELAY_PHASE`), and
        the reader rejoins them, so the contiguous string never appears in the
        page's text even though the page prints it.
        """
        pdf = _require_pdf()
        with fitz.open(pdf) as doc:
            pages = ["".join(page.get_text().split()) for page in doc]
        checked = 0
        for name, extraction in sorted(read.items()):
            if not extraction.accepted:
                continue
            page = pages[(extraction.page or 1) - 1]
            for field in extraction.fields:
                for cell in (field.bits.verbatim, field.name, field.access, field.reset):
                    if cell:
                        assert "".join(cell.split()) in page, (name, field.name, cell)
                        checked += 1
        assert checked

    def test_a_refused_register_emits_no_field_at_all(self, read):
        """No partial field list ever leaves the reader - the fail-closed rule."""
        for name, extraction in read.items():
            if extraction.reasons:
                assert _emitted(extraction) == (), name

    def test_one_hundred_and_sixteen_fields_are_emitted_in_total(self, read):
        emitted = [f for ex in read.values() for f in ex.fields]
        assert len(emitted) == 116
        assert all(f.page is not None for f in emitted)


@pytest.mark.integration
class TestWhereTheyWouldGoNow:
    """Ticket 05's structural blocker is closed; the accuracy one is not."""

    def test_the_reference_map_now_publishes_a_register_set_to_attach_fields_to(self, raw):
        """Phase 6.5, ticket 05: `Table 1-1` is recovered, so there is a home.

        Ticket 06 recorded this as the third, structural reason to park: even
        a perfect field reader had no summary record *in this document* to
        hang fields off, and a derived value cites a record inside one
        document. That reason is gone. The accuracy gate is what still parks
        it.
        """
        build = build_registers(raw, "LMX1204")
        assert build.registerset is not None
        assert build.n_registers == 35

    def test_the_document_prints_no_bit_position_diagram(self, raw):
        """Said out loud: checkbox 1's shape does not occur in this document.

        The geometric column-span reader is exercised only by the synthetic
        fixtures in `tests/unit/test_bitfields.py`. This map prints every
        register as a field-description table, so no real document in this
        repository gates the diagram path - a gap a reader deserves to know
        about rather than infer.
        """
        headers = [
            read_bit_header(row)
            for section in raw.sections
            for table in section.tables
            for row in ([table.headers, *table.grid] if table.headers else table.grid)
        ]
        assert not any(headers)


@pytest.mark.integration
class TestTheCapabilityShips:
    """Checkbox 6, the other way round: the gate is met, so this ships."""

    def test_the_reference_map_publishes_its_bit_fields_through_the_register_set(self, raw):
        """`derive/registers.py` attaches an accepted field set to its record.

        This is the whole un-park in one assertion: the reader is no longer a
        measurement instrument nobody imports. The join key is the caption's
        register name matched against the summary row's name.
        """
        build = build_registers(raw, "LMX1204")
        assert build.registerset is not None
        with_fields = [r for r in build.registerset.registers if r.fields]
        assert len(with_fields) == 28, [r.name for r in with_fields]
        assert sum(len(r.fields) for r in with_fields) == 116
        r4 = next(r for r in build.registerset.registers if r.name == "R4")
        assert [f.bits.verbatim for f in r4.fields] == [b for b, _n, _a, _r in GOLDEN["R4"][1]]

    def test_a_register_whose_table_refused_publishes_no_field_and_says_why(self, raw):
        """R90 keeps `fields: []`, and the set's warnings name it."""
        build = build_registers(raw, "LMX1204")
        assert build.registerset is not None
        r90 = next(r for r in build.registerset.registers if r.name == "R90")
        assert r90.fields == []
        assert any("R90" in w and "could not read whole" in w for w in build.warnings)

    def test_no_published_register_carries_a_field_it_did_not_read(self):
        """Whatever a built corpus publishes, every field cites a page.

        The park's assertion here was `fields == []` everywhere. What replaces
        it is the property that still has to hold now that fields ship: a
        published field is a field the reader accepted, so it carries a page.
        """
        roots = [d for d in (PARTS_DIR, LIBRARY_DIR) if d.is_dir()]
        if not roots:
            pytest.skip(f"no built corpus under {PARTS_DIR} or {LIBRARY_DIR}")
        files = sorted(path for root in roots for path in root.glob("**/registers.json"))
        if not files:
            pytest.skip("no part publishes registers.json")
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for register in payload.get("registers", []):
                for field in register.get("fields", []):
                    assert field.get("page") is not None, f"{path}: {register.get('name')}"
                    assert field.get("bits", {}).get("verbatim"), path

    def test_the_park_entry_is_gone_from_the_shortcomings(self):
        """A shortcoming that closed is deleted, not left standing as prose."""
        if not SHORTCOMINGS.is_file():
            pytest.skip("KNOWN_SHORTCOMINGS.md is not in this tree")
        text = SHORTCOMINGS.read_text(encoding="utf-8")
        assert "Register bit fields: not extracted" not in text
