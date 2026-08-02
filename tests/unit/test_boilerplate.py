"""Pain point: repeated page furniture inflates every read.

A 146-page TI datasheet repeats ~5 boilerplate lines per page. These tests
pin each rule, prove real page footers are caught, and verify meaningful
lines are never stripped.
"""

from __future__ import annotations

from datasheet_analyzer.structure.boilerplate import (
    is_boilerplate,
    strip_boilerplate,
    strip_boilerplate_lines,
)
from datasheet_analyzer.tokens import count_tokens

# Verbatim footer block lifted from AFE7950 p.27 text extraction
REAL_PAGE_FOOTER = """\
tRESET
Minimum RESETZ Pulse Width
1
ms
(1)
SDEN\\ need to be held one more extra clock cycle with the last SCLK edge
www.ti.com
AFE7950
SBASA41E – FEBRUARY 2021 – REVISED MAY 2025
Copyright © 2025 Texas Instruments Incorporated
Submit Document Feedback
27
Product Folder Links: AFE7950
"""


def test_each_rule_hits_canonical_ti_lines():
    assert is_boilerplate("Product Folder Links: AFE7950")
    assert is_boilerplate("Submit Document Feedback")
    assert is_boilerplate("Copyright © 2025 Texas Instruments Incorporated")
    assert is_boilerplate("www.ti.com")
    assert is_boilerplate("SBASA41E – FEBRUARY 2021 – REVISED MAY 2025")
    assert is_boilerplate("PRODUCTION DATA")
    assert not is_boilerplate("27")  # digits-only = maybe real data, keep


def test_real_page_footer_is_stripped_but_content_survives():
    clean, removed = strip_boilerplate(REAL_PAGE_FOOTER)
    # www.ti.com, doc-id, copyright, feedback, folder links — but NOT the
    # bare "27" page number: digits-only lines are often real table values
    # (the "1" ms RESETZ value in this very fragment), so they are kept.
    assert removed == 5
    assert "SDEN" in clean  # the real footnote survives
    assert "tRESET" in clean
    assert "Product Folder Links" not in clean
    assert "SBASA41E" not in clean


def test_digits_only_lines_are_data_not_boilerplate():
    # regression: a bare-number rule would have eaten the "1" ms RESETZ
    # timing value and the "27" here could be a real spec value too.
    kept, removed = strip_boilerplate_lines(["tRESET", "1", "ms", "27"])
    assert removed == 0
    assert kept == ["tRESET", "1", "ms", "27"]


def test_meaningful_lines_are_never_stripped():
    content = [
        "DSA Attenuation range 40 dB",
        "fDAC = 8847.36MSPS; fADC = 2949.12MSPS",
        "Measured with differential 50 ohm across TxP/M.",
        "AFE7950 is a high performance transceiver",  # part name inside prose
        "1.8.2 Some numbered section heading",
    ]
    kept, removed = strip_boilerplate_lines(content)
    assert removed == 0
    assert kept == content


def test_blank_runs_collapse_after_stripping():
    text = "para one\nwww.ti.com\nCopyright © 2025 X\n\n\n\npara two"
    clean, _ = strip_boilerplate(text)
    assert "\n\n\n" not in clean
    assert "para one" in clean and "para two" in clean


def test_stripping_measurably_reduces_tokens():
    page = REAL_PAGE_FOOTER
    before = count_tokens(page)
    clean, _ = strip_boilerplate(page)
    after = count_tokens(clean)
    assert after < before
    # footer junk is >40% of this page fragment's tokens
    assert (before - after) / before > 0.4
