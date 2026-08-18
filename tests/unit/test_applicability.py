"""Ticket 02 — part-number and applicability inference.

Hermetic by construction (AGENTS.md invariant 4): every PDF is built in-test
with `fitz`, every classification goes through a fake `LLMClient` that records
its calls, and no test touches the network, a live model, a subprocess or a
browser. `infer()` itself reads no settings and writes nothing — it returns a
proposal — but the `reset_settings_cache` hook is still installed so this file
can never see a real `parts_dir`.

The two properties under test are the ones the review screen depends on:
a deterministic first stage that does not call a model when it does not have
to, and an `evidence` string that is never blank on any path, fallbacks
included.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from datasheet_analyzer.acquire.applicability import infer
from datasheet_analyzer.app.contracts import DocProposal
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.enrich.llm import FakeClient

# --- fixtures and doubles -----------------------------------------------------

DATASHEET_LINES = [
    "AD9081 Quad, 16-Bit, 12 GSPS RF DAC and Quad, 12-Bit, 4 GSPS RF ADC",
    "Data Sheet",
    "FEATURES",
    "JESD204B and JESD204C serial interface",
]


@pytest.fixture(autouse=True)
def hermetic_settings(tmp_path: Path):
    """No test here may resolve against the developer's real corpus."""
    reset_settings_cache()
    yield Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        library_dir=tmp_path / "library",
    ).resolve()
    reset_settings_cache()


@pytest.fixture
def make_pdf(tmp_path: Path):
    """Build a synthetic PDF whose first page holds `lines`, one per line."""

    def _make(name: str, lines: list[str], extra_pages: int = 0) -> Path:
        path = tmp_path / name
        doc = fitz.open()
        page = doc.new_page()
        for i, line in enumerate(lines):
            page.insert_text((72, 72 + 14 * i), line)
        for i in range(extra_pages):
            doc.new_page().insert_text((72, 72), f"page {i + 2} body text")
        doc.save(path)
        doc.close()
        return path

    return _make


class RaisingClient:
    """A classifier that fails the way a real one does: mid-call."""

    model = "raising-1"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def complete(self, system: str, prompt: str, max_tokens: int) -> str:
        self.calls.append((system, prompt, max_tokens))
        raise RuntimeError("connection reset")


# --- checkbox 1: one part token, no model call --------------------------------


def test_single_part_token_returns_that_part_with_no_model_call(make_pdf):
    client = FakeClient(response='{"kind": "all"}')
    pdf = make_pdf("ad9081-datasheet.pdf", DATASHEET_LINES, extra_pages=2)

    proposal = infer(pdf, known_parts=[], client=client)

    assert isinstance(proposal, DocProposal)
    assert proposal.part_number == "AD9081"
    assert proposal.applicability.kind == "parts"
    assert proposal.applicability.parts == ["AD9081"]
    assert "AD9081 Quad" in proposal.evidence
    assert "page 1" in proposal.evidence
    # The whole point of stage 1: the deterministic path spends nothing.
    assert client.calls == []
    # Read straight off the synthetic file, in the same open as the text.
    assert proposal.page_count == 3
    assert proposal.filename == "ad9081-datasheet.pdf"
    assert proposal.pdf_path == str(pdf)


# --- checkbox 2: a family token ----------------------------------------------


def test_family_token_returns_family_applicability(make_pdf):
    pdf = make_pdf(
        "sbaa511.pdf",
        [
            "AFE79xx JESD204C Interface Implementation Guide",
            "Application Report",
        ],
    )

    proposal = infer(pdf, known_parts=[], client=None)

    assert proposal.applicability.kind == "family"
    assert proposal.applicability.family == "AFE79xx"
    assert proposal.evidence
    # A family is a genuine wildcard, not a literal prefix.
    assert proposal.applicability.covers("AFE7950")
    assert not proposal.applicability.covers("AD9081")


def test_family_wildcard_is_normalized_to_its_printed_form(make_pdf):
    pdf = make_pdf("guide.pdf", ["afe79XX Power Supply Design Guide"])

    proposal = infer(pdf, client=None)

    assert proposal.applicability.family == "AFE79xx"


# --- checkbox 3: several parts route to the classifier ------------------------


def test_several_part_tokens_route_to_classifier_and_keep_every_part(make_pdf):
    client = FakeClient(
        response=(
            '{"kind": "parts", "parts": ["AFE7950", "AFE7952", "AFE7951"],'
            ' "part_number": "AFE7950", "reason": "covers three transceivers"}'
        )
    )
    pdf = make_pdf(
        "migration.pdf",
        [
            "Migrating from AFE7950 to AFE7952",
            "This note also applies to AFE7951.",
        ],
    )

    proposal = infer(pdf, known_parts=["AFE7950"], client=client)

    assert len(client.calls) == 1
    assert proposal.applicability.kind == "parts"
    assert proposal.applicability.parts == ["AFE7950", "AFE7952", "AFE7951"]
    assert proposal.part_number == "AFE7950"
    assert proposal.evidence.startswith("llm:fake-1")
    assert "covers three transceivers" in proposal.evidence
    assert proposal.applicability.evidence == proposal.evidence


def test_classifier_can_widen_a_multi_part_document_to_all(make_pdf):
    client = FakeClient(response='{"kind": "all", "reason": "generic layout note"}')
    pdf = make_pdf("layout.pdf", ["Board layout for AFE7950, AD9081 and LM7171"])

    proposal = infer(pdf, client=client)

    assert len(client.calls) == 1
    assert proposal.applicability.kind == "all"
    assert proposal.applicability.covers("ANYTHING")
    assert proposal.evidence.startswith("llm:fake-1")
    # `all` still names a part to file the document under, from the sweep.
    assert proposal.part_number == "AFE7950"


# --- checkbox 4: a generic document, with no model call -----------------------


def test_generic_document_returns_all_with_no_model_call(make_pdf):
    client = FakeClient(response='{"kind": "parts", "parts": ["WRONG1"]}')
    pdf = make_pdf(
        "thermal_notes.pdf",
        [
            "Thermal Design Considerations for High Power Amplifiers",
            "Application Report",
            "Copyright Texas Instruments Incorporated",
        ],
    )

    proposal = infer(pdf, known_parts=["AD9081"], client=client)

    assert proposal.applicability.kind == "all"
    assert client.calls == []
    assert proposal.evidence


# --- checkbox 5: `client=None` never raises -----------------------------------


@pytest.mark.parametrize(
    "name,lines",
    [
        ("one.pdf", DATASHEET_LINES),
        ("family.pdf", ["AFE79xx Interface Guide"]),
        ("many.pdf", ["AFE7950 and AFE7952 comparison"]),
        ("generic.pdf", ["Thermal design for power amplifiers"]),
        ("empty.pdf", [""]),
        ("mixed.pdf", ["AFE79xx family overview, tested on AFE7950"]),
    ],
)
def test_client_none_never_raises_and_always_falls_back(make_pdf, name, lines):
    proposal = infer(make_pdf(name, lines), known_parts=["AFE7950"], client=None)

    assert isinstance(proposal, DocProposal)
    assert proposal.applicability.kind in ("parts", "family", "all")
    assert proposal.evidence
    assert proposal.applicability.evidence


def test_a_missing_file_degrades_instead_of_raising(tmp_path: Path):
    proposal = infer(tmp_path / "nope.pdf", client=None)

    assert proposal.applicability.kind == "all"
    assert proposal.page_count == 0
    assert proposal.evidence


# --- checkbox 6: a raising classifier falls back to the sweep -----------------


def test_classifier_error_falls_back_to_the_sweep_and_says_so(make_pdf):
    client = RaisingClient()
    pdf = make_pdf("compare.pdf", ["AFE7950 versus AFE7952 receiver comparison"])

    proposal = infer(pdf, known_parts=["AFE7952"], client=client)

    assert len(client.calls) == 1
    assert proposal.applicability.kind == "parts"
    # `known_parts` decided which of the two ambiguous tokens won.
    assert proposal.part_number == "AFE7952"
    assert proposal.evidence.startswith("fallback: classifier error (RuntimeError)")
    assert "AFE7950 versus AFE7952" in proposal.evidence


# --- checkbox 7: malformed JSON is a failure, not a loose parse ---------------


@pytest.mark.parametrize(
    "response",
    [
        "",
        "I could not determine the parts.",
        'Sure! Here you go: {"kind": "parts", "parts": ["AFE7950"]}',
        '{"kind": "parts", "parts": ["AFE7950"]',
        '["AFE7950"]',
        '"AFE7950"',
        '{"parts": ["AFE7950"]}',
        '{"kind": "everything", "parts": ["AFE7950"]}',
        '{"kind": "parts", "parts": []}',
        '{"kind": "parts", "parts": "AFE7950"}',
        '{"kind": "family", "family": "   "}',
        '{"kind": "family"}',
        '```json\n{"kind": "parts", "parts": ["AFE7950"]}',
    ],
)
def test_malformed_classifier_output_is_a_failure(make_pdf, response):
    client = FakeClient(response=response)
    pdf = make_pdf("compare.pdf", ["AFE7950 versus AFE7952 receiver comparison"])

    proposal = infer(pdf, known_parts=["AFE7950"], client=client)

    assert len(client.calls) == 1
    assert proposal.evidence.startswith("fallback: classifier returned malformed JSON")
    assert proposal.part_number == "AFE7950"
    assert proposal.applicability.kind == "parts"


def test_a_correctly_fenced_object_is_still_read(make_pdf):
    client = FakeClient(response='```json\n{"kind": "family", "family": "AFE79xx"}\n```')
    pdf = make_pdf("compare.pdf", ["AFE7950 versus AFE7952 receiver comparison"])

    proposal = infer(pdf, client=client)

    assert proposal.applicability.kind == "family"
    assert proposal.applicability.family == "AFE79xx"
    assert proposal.evidence.startswith("llm:fake-1")


# --- checkbox 8: evidence is never blank --------------------------------------


@pytest.mark.parametrize(
    "lines",
    [
        DATASHEET_LINES,
        ["AFE79xx Interface Guide"],
        ["AFE7950 and AFE7952 comparison"],
        ["Thermal design for power amplifiers"],
        [""],
    ],
)
@pytest.mark.parametrize(
    "client_factory",
    [
        lambda: None,
        lambda: FakeClient(response='{"kind": "all", "reason": "generic"}'),
        lambda: FakeClient(response="garbage"),
        RaisingClient,
    ],
)
def test_evidence_is_non_empty_on_every_path(make_pdf, lines, client_factory):
    proposal = infer(make_pdf("doc.pdf", lines), known_parts=["AFE7950"], client=client_factory())

    assert proposal.evidence.strip()
    assert proposal.applicability.evidence.strip()


# --- checkbox 9: known_parts outranks an unknown token ------------------------


def test_a_known_part_outranks_an_unknown_one_that_came_first(make_pdf):
    lines = [
        "LM741 Operational Amplifier reference design",
        "Measured with an AD9081 data converter",
    ]
    pdf = make_pdf("bench.pdf", lines)

    unknown = infer(pdf, known_parts=[], client=None)
    known = infer(pdf, known_parts=["ad9081"], client=None)

    # With nothing known, position decides: the first line wins.
    assert unknown.part_number == "LM741"
    # A token naming a built part wins even from the second line, and the
    # evidence quotes the line it actually came from.
    assert known.part_number == "AD9081"
    assert "AD9081 data converter" in known.evidence


# --- checkbox 10 + 11: the filename stem is the last resort -------------------


def test_the_stem_is_used_only_when_the_sweep_finds_nothing(make_pdf):
    pdf = make_pdf("thermal_notes.pdf", ["Thermal design for power amplifiers"])

    proposal = infer(pdf, client=None)

    assert proposal.part_number == "THERMAL_NOTES"
    assert "fallback: no part token found" in proposal.evidence
    assert 'stem "thermal_notes"' in proposal.evidence
    assert proposal.applicability.kind == "all"
    assert proposal.applicability.evidence == "fallback: no part token found"


def test_a_document_id_filename_proposes_the_part_its_title_block_names(make_pdf):
    pdf = make_pdf(
        "sbas123e.pdf",
        [
            "AFE7950 Quad-Channel RF Transceiver",
            "SBAS123E – DECEMBER 2021 – REVISED MARCH 2023",
            "1 Features",
        ],
    )
    client = FakeClient(response='{"kind": "parts", "parts": ["SBAS123E"]}')

    proposal = infer(pdf, known_parts=[], client=client)

    assert proposal.part_number == "AFE7950"
    assert proposal.applicability.parts == ["AFE7950"]
    assert "SBAS123E" not in proposal.part_number
    # The document ID is not a part token, so the sweep stayed unambiguous.
    assert client.calls == []
    assert "stem" not in proposal.evidence


# --- caller-supplied text and inference's read-only promise -------------------


def test_supplied_first_page_text_is_used_without_opening_the_file(tmp_path: Path):
    """The scan endpoint already has the text; inference must not re-open."""
    missing = tmp_path / "never-created.pdf"

    proposal = infer(
        missing,
        first_page_text="AD9081 Quad, 16-Bit RF DAC\nData Sheet",
        client=None,
    )

    assert proposal.part_number == "AD9081"
    assert proposal.page_count == 0
    assert not missing.exists()


def test_inference_never_writes(make_pdf, tmp_path: Path):
    pdf = make_pdf("ad9081.pdf", DATASHEET_LINES)
    before = sorted(p.name for p in tmp_path.iterdir())

    infer(pdf, known_parts=["AD9081"], client=FakeClient(response='{"kind": "all"}'))

    assert sorted(p.name for p in tmp_path.iterdir()) == before
