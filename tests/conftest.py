"""Shared fixtures and helpers.

Layout:
- tests/fixtures/ti_html/   recorded real TI document-viewer pages (no network in tests)
- tests/fixtures/synthetic/ hand-built edge-case HTML
- tests/fixtures/golden_qa.yaml  the golden Q&A eval set
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TI_HTML = FIXTURES / "ti_html"
SYNTHETIC = FIXTURES / "synthetic"
GOLDEN_QA = FIXTURES / "golden_qa.yaml"
REPO_ROOT = Path(__file__).parent.parent
AFE7950_PDF = REPO_ROOT / "afe7950.pdf"
# Phase 4 gate: real PDFs at the repo root, ungated-offline by construction
# (pdf_layout never touches the network); skip-guarded like AFE7950_PDF.
AD9081_PDF = REPO_ROOT / "ad9081.pdf"
LM741_PDF = REPO_ROOT / "lm741.pdf"
QPA1003P_PDF = REPO_ROOT / "QPA1003P.pdf"
HMC520A_PDF = REPO_ROOT / "hmc520a.pdf"


@pytest.fixture
def make_synthetic_pdf():
    """Factory for the shared synthetic part PDF: 2 pages, TOC with
    Features (p.1) + Absolute Maximum Ratings (p.2). One fixture so every
    pipeline-level test builds the same input bytes."""

    def _make(path: Path) -> None:
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text(
            (72, 72),
            "TEST9000 Features page. Quad RF sampling 12GSPS transmit DACs.",
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
