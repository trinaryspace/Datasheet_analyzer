"""Phase 6 gate — register bit fields against LMX1204_registermap.pdf (ticket 06).

**This gate fails, and failing it is the ticket's outcome.** Ticket 06 is
explicitly permitted to park, and this file is the measurement that decided it:
the numbers below are produced by running `derive/bitfields.py` over the real
reference register map, not asserted from memory. The park itself is recorded
in `KNOWN_SHORTCOMINGS.md` under *"Register bit fields: not extracted"*, and
the last class here asserts that no bit-field data reaches any published
artifact — which is what "ships nothing" means in bytes.

Three separate things fail, and they fail for different reasons:

1. **Recall.** Of the 35 registers the document prints, the layout engine
   hands over 12 field tables at all, and only 4 of those survive the
   fail-closed validators. A gate over a sample chosen by *document order* —
   the first six registers, R0 through R6 — is met for two of them.
2. **Fidelity, where a table does arrive.** The engine re-joins wrapped name
   cells as `SYSREFREQ_DELAY_ST EPSIZE`, truncates R19 and R21 to their first
   field, and folds two body lines into the header of R12's table. Each is
   caught and refuses the register, so nothing wrong is emitted — but nothing
   is emitted either.
3. **Nowhere to put them.** The reference map's own summary table
   (`Table 1-1`) is not recovered — ticket 05's recorded shortcoming — so the
   document publishes no `registers.json` at all. Even a perfect field reader
   would have no summary record in this document to hang fields off.

What *does* hold, and is asserted rather than claimed: **every field the
reader emits is exactly right.** Precision is 100% over 13 fields; it is
recall that is 11%. That is the shape a fail-closed reader is supposed to
have, and it is why the module is kept rather than deleted.

Invariant 4 is relaxed exactly as far as the phase plan allows: this reads a
real PDF at the repository root and the parts under `parts/`, and skips when
they are absent. It never reaches the network, never calls a model, and never
rebuilds anything.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    """Checkbox 2 — 100%, no partial credit. Measured: it is not met."""

    def test_most_of_the_sample_yields_no_fields_at_all(self, read):
        covered = sorted(r for r in SAMPLE if r in read and read[r].accepted)
        assert covered == ["R2", "R5"], covered
        assert len(covered) < len(SAMPLE)

    def test_four_of_the_sampled_registers_never_reach_the_reader(self, read):
        """R0, R3, R4 and R6 print a field table the layout engine drops whole."""
        missing = sorted(r for r in SAMPLE if r not in read)
        assert missing == ["R0", "R3", "R4", "R6"], missing

    def test_recall_over_the_whole_document_is_measured_and_low(self, raw, read):
        tables = list(iter_bit_field_tables(raw))
        accepted = [ex for ex in tables if ex.accepted]
        assert len(tables) == 12, [ex.caption for ex in tables]
        assert len(accepted) == 4, [ex.register_name for ex in accepted]
        assert sorted(ex.register_name for ex in accepted) == ["R2", "R33", "R5", "R67"]
        assert len(accepted) / REGISTERS_PRINTED < 0.15

    def test_every_refusal_names_a_reason(self, raw):
        for extraction in iter_bit_field_tables(raw):
            if not extraction.accepted:
                assert extraction.reasons, extraction.caption

    def test_the_named_failure_modes_are_the_ones_measured(self, read):
        """The three that decided the park, each asserted on the register it broke."""
        assert any("not identifiers" in r for r in read["R13"].reasons)
        assert any("not identifiers" in r for r in read["R17"].reasons)
        assert any("covered by no field" in r for r in read["R19"].reasons)
        assert any("covered by no field" in r for r in read["R21"].reasons)
        assert any("print no reset" in r for r in read["R79"].reasons)


@pytest.mark.integration
class TestNothingWrongIsEmitted:
    """The half that holds: precision is 100% over everything the reader emits."""

    def test_every_accepted_register_matches_the_printed_page_exactly(self, read):
        truth = {**GOLDEN, **ACCEPTED_ELSEWHERE}
        accepted = {name: ex for name, ex in read.items() if ex.accepted}
        assert set(accepted) == set(truth) & set(accepted)
        for name, extraction in sorted(accepted.items()):
            assert _emitted(extraction) == truth[name][1], name

    def test_a_refused_register_emits_no_field_at_all(self, read):
        """No partial field list ever leaves the reader — the fail-closed rule."""
        for name, extraction in read.items():
            if extraction.reasons:
                assert _emitted(extraction) == (), name

    def test_thirteen_fields_are_emitted_in_total(self, read):
        emitted = [f for ex in read.values() for f in ex.fields]
        assert len(emitted) == 13
        assert all(f.page is not None for f in emitted)


@pytest.mark.integration
class TestWhyThereIsNowhereToPutThem:
    """The structural blocker underneath the accuracy one (ticket 05's park)."""

    def test_the_reference_map_publishes_no_register_set_to_attach_fields_to(self, raw):
        build = build_registers(raw, "LMX1204")
        assert build.registerset is None
        assert build.n_registers == 0

    def test_the_document_prints_no_bit_position_diagram(self, raw):
        """Said out loud: checkbox 1's shape does not occur in this document.

        The geometric column-span reader is exercised only by the synthetic
        fixtures in `tests/unit/test_bitfields.py`. This map prints every
        register as a field-description table, so no real document in this
        repository gates the diagram path — a gap a reader deserves to know
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
