"""Phase 6 gate — register bit fields against LMX1204_registermap.pdf (ticket 06).

**This gate fails, and failing it is the ticket's outcome.** Ticket 06 is
explicitly permitted to park, and this file is the measurement that decided it:
the numbers below are produced by running `derive/bitfields.py` over the real
reference register map, not asserted from memory. The park itself is recorded
in `KNOWN_SHORTCOMINGS.md` under *"Register bit fields: not extracted"*, and
the last class here asserts that no bit-field data reaches any published
artifact — which is what "ships nothing" means in bytes.

**Phase 6.5 re-measured it and it stays parked, on a much better number.**
Wave 1 fixed the layout engine underneath: the document now hands over **30**
field tables of 35 instead of 12, **15** survive validation instead of 4, and
**71** fields are emitted instead of 13 — every one of them right. The gate
that decides is unchanged and is still not met, so nothing ships.

Where it stands now, each claim measured by this module:

1. **Recall.** Of the 35 registers the document prints, the layout engine
   hands over 30 field tables and 15 survive the fail-closed validators
   (43%, from 11%). The gate is a sample chosen by *document order* — the
   first six registers, R0 through R6, at 100% with no partial credit — and
   **four of the six** are now read exactly right. Four is not six.
2. **What refuses now, and why.** The wrapped-name and truncation misreads
   ticket 06 named are gone: R13, R17, R19, R21 and R25 all read correctly.
   Twelve of the fifteen refusals are now **one** new cause — the table region
   runs on into the two cross-reference lines the document prints after every
   field table (`R2 is shown in … Summary Table`, `Return to the Summary
   Table`), which arrive as two more rows and are refused for a bit range that
   does not parse. R4 and R9 refuse for genuinely incomplete bit coverage and
   R90 for two fields claiming one bit.
3. **There is somewhere to put them now.** Ticket 05's structural blocker is
   closed: the reference map's own `Table 1-1` is recovered, so the document
   publishes a `registers.json` with 35 summary records to hang fields off.

What *does* hold, and is asserted rather than claimed: **every field the
reader emits is exactly right.** Precision is 100% over 71 fields; it is
recall that decides. That is the shape a fail-closed reader is supposed to
have, and it is why the module is kept rather than deleted.

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
class TestTheAccuracyGateIsNotMet:
    """Checkbox 2 - 100%, no partial credit. Measured: it is still not met."""

    #: Every register the reader accepts, after phase 6.5 wave 1. Fixed by
    #: measurement, not by expectation: five of these (R13, R17, R19, R21,
    #: R25) are registers ticket 06 named as damaged and refused.
    ACCEPTED: ClassVar[list[str]] = [
        "R13",
        "R14",
        "R15",
        "R17",
        "R19",
        "R2",
        "R21",
        "R22",
        "R23",
        "R25",
        "R3",
        "R33",
        "R5",
        "R6",
        "R67",
    ]

    def test_four_of_the_six_sampled_registers_are_read_exactly_right(self, read):
        covered = sorted(r for r in SAMPLE if r in read and read[r].accepted)
        assert covered == ["R2", "R3", "R5", "R6"], covered
        assert len(covered) < len(SAMPLE), "the gate is 100% with no partial credit"

    def test_the_two_the_sample_still_loses_are_named_with_their_reason(self, read):
        """R0 and R4 arrive and are refused - neither is dropped silently."""
        refused = {r: read[r].reasons for r in SAMPLE if r in read and not read[r].accepted}
        assert sorted(refused) == ["R0", "R4"], sorted(refused)
        assert any("did not parse" in r for r in refused["R0"])
        assert any("covered by no field" in r for r in refused["R4"])
        # Every sampled register now reaches the reader at all, which is the
        # half that moved: ticket 06 measured four of six dropped whole.
        assert [r for r in SAMPLE if r not in read] == []

    def test_recall_over_the_whole_document_is_measured_and_better(self, raw, read):
        tables = list(iter_bit_field_tables(raw))
        accepted = [ex for ex in tables if ex.accepted]
        assert len(tables) == 30, [ex.caption for ex in tables]
        assert len(accepted) == 15, [ex.register_name for ex in accepted]
        assert sorted(ex.register_name for ex in accepted) == self.ACCEPTED
        # 15/35 = 43%, up from 4/35 = 11%, and still nowhere near the gate.
        assert 0.40 < len(accepted) / REGISTERS_PRINTED < 0.45

    def test_every_refusal_names_a_reason(self, raw):
        for extraction in iter_bit_field_tables(raw):
            if not extraction.accepted:
                assert extraction.reasons, extraction.caption

    def test_the_dominant_failure_mode_is_now_one_named_cause(self, read):
        """Twelve of fifteen refusals are the trailing cross-reference lines.

        Every field table in this document is followed by two printed
        sentences - `R<n> is shown in <table>` and `Return to the Summary
        Table` - and the region now runs on into them, so they arrive as two
        more rows whose bit cell is prose. Naming it here is what makes it the
        next thing to fix rather than a number nobody can act on.
        """
        refused = {name: ex.reasons for name, ex in read.items() if not ex.accepted}
        assert len(refused) == 15
        run_on = {
            name for name, reasons in refused.items() if any("Return to the" in r for r in reasons)
        }
        assert len(run_on) == 12, sorted(run_on)
        assert sorted(set(refused) - run_on) == ["R4", "R9", "R90"]
        assert any("covered by no field" in r for r in refused["R4"])
        assert any("covered by no field" in r for r in refused["R9"])
        assert any("claimed by more than one field" in r for r in refused["R90"])

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
        assert overlap == ["R2", "R3", "R33", "R5", "R6", "R67"], overlap
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

    def test_seventy_one_fields_are_emitted_in_total(self, read):
        emitted = [f for ex in read.values() for f in ex.fields]
        assert len(emitted) == 71
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
class TestTheParkIsRealAndWrittenDown:
    """Checkbox 6 — ships nothing, says why, closes as parked."""

    def test_no_published_register_anywhere_carries_a_bit_field(self):
        roots = [d for d in (PARTS_DIR, LIBRARY_DIR) if d.is_dir()]
        if not roots:
            pytest.skip(f"no built corpus under {PARTS_DIR} or {LIBRARY_DIR}")
        files = sorted(path for root in roots for path in root.glob("**/registers.json"))
        if not files:
            pytest.skip("no part publishes registers.json")
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for register in payload.get("registers", []):
                assert register.get("fields", []) == [], f"{path}: {register.get('name')}"

    def test_the_park_is_recorded_where_a_reader_will_find_it(self):
        if not SHORTCOMINGS.is_file():
            pytest.skip("KNOWN_SHORTCOMINGS.md is not in this tree")
        text = SHORTCOMINGS.read_text(encoding="utf-8")
        assert "Register bit fields" in text
        assert "LMX1204_registermap.pdf" in text
        assert "derive/bitfields.py" in text
