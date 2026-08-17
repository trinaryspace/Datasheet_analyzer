"""Shared fixtures and helpers.

Layout:
- tests/fixtures/pdf/       the four real phase-4 gate PDFs (ungated —
                            committed fixtures, pdf_layout never touches
                            the network)
- tests/fixtures/ti_html/   recorded real TI document-viewer pages (no network in tests)
- tests/fixtures/synthetic/ hand-built edge-case HTML
- tests/fixtures/golden_qa_<PART>.yaml  per-part golden Q&A eval sets
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TI_HTML = FIXTURES / "ti_html"
SYNTHETIC = FIXTURES / "synthetic"
GATE_PDFS = FIXTURES / "pdf"
REPO_ROOT = Path(__file__).parent.parent
AFE7950_PDF = REPO_ROOT / "afe7950.pdf"
AFE7953_PDF = REPO_ROOT / "afe7953.pdf"
# Phase 4 gate: real PDFs under tests/fixtures/pdf, ungated by
# construction (committed fixtures; pdf_layout never touches the
# network). AFE7950_PDF above stays skip-guarded like the TI path.
AD9081_PDF = GATE_PDFS / "ad9081.pdf"
LM741_PDF = GATE_PDFS / "lm741.pdf"
QPA1003P_PDF = GATE_PDFS / "QPA1003P.pdf"
HMC520A_PDF = GATE_PDFS / "hmc520a.pdf"


@pytest.fixture(autouse=True)
def fresh_retrieval_cache():
    """Hermetic per invariant #4: the retrieval core caches a loaded corpus
    in-process, so one test's part must never be visible to the next."""
    from datasheet_analyzer.retrieve import clear_index_cache

    clear_index_cache()
    yield
    clear_index_cache()


@pytest.fixture
def resolve_source():
    """Resolve a derived value's `source` back to the record and page it names.

    The invariant-8 helper (ADR 0005, phase 6 ticket 01). Later tickets walk
    every `source` on every derived artifact through this and assert it lands
    on a real record with a printed page — that walk is what makes the derived
    layer provably traceable instead of asserted to be. Call it as
    `resolve_source(part_dir, value.source)`.

    It returns `None` rather than raising for anything unresolvable (a
    malformed reference, an unknown document, a missing record, an ambiguous
    shorthand), so a test can collect and name *every* untraceable value
    instead of dying on the first one.
    """
    from datasheet_analyzer.provenance import resolve_source as _resolve

    return _resolve


@pytest.fixture
def make_synthetic_pdf():
    """Factory for the shared synthetic part PDF: 2 pages, TOC with
    Features (p.1) + Absolute Maximum Ratings (p.2). One fixture so every
    pipeline-level test builds the same input bytes; ``marker`` (default "")
    appends to the page-1 text to produce deliberately different bytes while
    keeping the structural shape identical."""

    def _make(path: Path, marker: str = "") -> None:
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text(
            (72, 72),
            "TEST9000 Features page. Quad RF sampling 12GSPS transmit DACs."
            + marker,
        )
        p2 = doc.new_page()
        p2.insert_text(
            (72, 72),
            "4.1 Absolute Maximum Ratings VDD1P2 Supply voltage 1.2V –0.3 1.4 V TJ 150 °C",
        )
        doc.set_toc(
            [
                [1, "1 Features", 1],
                [1, "4 Specifications", 2],
                [2, "4.1 Absolute Maximum Ratings", 2],
            ]
        )
        doc.save(path)
        doc.close()

    return _make


@pytest.fixture
def ti_main_html() -> str:
    """Recorded TI document-viewer TOC page for AFE7950."""
    return (TI_HTML / "afe7950_main.html").read_text(encoding="utf-8")


@pytest.fixture
def ti_sec_4_5_html() -> str:
    """Recorded section 4.5 (Transmitter Electrical Characteristics)."""
    return (TI_HTML / "sec_4_5.html").read_text(encoding="utf-8")


@pytest.fixture
def ti_sec_4_12_1_html() -> str:
    """Recorded section 4.12.1 (TX Typical Characteristics 800 MHz, plots)."""
    return (TI_HTML / "sec_4_12_1.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def afe7950_pdf() -> Path:
    if not AFE7950_PDF.exists():
        pytest.skip("afe7950.pdf not present at repo root")
    return AFE7950_PDF


@pytest.fixture(scope="module")
def afe7953_pdf() -> Path:
    """The second reference PDF, skip-guarded like AFE7950's.

    Only the printed page *text* is ever read from it — the AFE7953 corpus
    itself is the one committed under `parts/`, because no recorded TI
    document-viewer pages exist for this part and the ti_html backend cannot
    be replayed offline for it.
    """
    if not AFE7953_PDF.exists():
        pytest.skip("afe7953.pdf not present at repo root")
    return AFE7953_PDF
