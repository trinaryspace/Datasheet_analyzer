"""Shared fixtures and helpers.

Layout:
- tests/fixtures/ti_html/   recorded real TI document-viewer pages (no network in tests)
- tests/fixtures/synthetic/ hand-built edge-case HTML
- tests/fixtures/golden_qa.yaml  the golden Q&A eval set
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TI_HTML = FIXTURES / "ti_html"
SYNTHETIC = FIXTURES / "synthetic"
GOLDEN_QA = FIXTURES / "golden_qa.yaml"
REPO_ROOT = Path(__file__).parent.parent
AFE7950_PDF = REPO_ROOT / "afe7950.pdf"


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
