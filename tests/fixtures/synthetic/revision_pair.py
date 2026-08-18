"""A synthetic two-revision part: rev A, rev B, and the exact edits between them.

Phase 7, ticket 03. This repo holds exactly **one** revision of every part it
carries, so there is no real revision pair to diff. The honest substitute is a
*declared* one: two PDFs built here with a fixed, hand-written list of edits
between them, pushed through the real extraction pipeline, so `dsa diff-rev` is
verified against an expectation that is exact rather than approximate. That is a
stronger check than a real pair would give — with a real pair the expected delta
would itself have to be read off two PDFs by hand and could be wrong.

The PDFs are built with the same fitz geometry the layout-floor tests use (a
six-column spec table on AD9081 proportions, a four-column pin table on TI "Pin
Functions" proportions), so what the diff sees is what the real
`PdfLayoutBackend` extracted, not hand-written records.

`EDITS` below is the contract. Every entry is something rev B does to rev A, and
the gate asserts the diff reports **exactly** these and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import fitz

PAGE_W, PAGE_H = 612.0, 792.0

# AD9081-style spec-table column geometry (see tests/unit/test_pdf_layout_tables.py).
SPEC_X = {"param": 56.0, "conditions": 222.0, "min": 435.0, "typ": 460.0,
          "max": 515.0, "unit": 548.0}
# TI "Pin Functions" four-column geometry (see tests/unit/test_device_tables.py).
PIN_X = {"key": 56.0, "name": 130.0, "type": 240.0, "desc": 300.0}
PITCH = 13.0
CAP_Y = 140.0
HDR_Y = 153.0

PART = "REVTEST1"

#: The edits rev B makes to rev A. The gate reads this list as its expectation,
#: which is why each entry names the artifact, the change and the two printed
#: values — a test that asserted "some spec changed" would pass on a diff that
#: found the wrong row.
EDITS: tuple[str, ...] = (
    "spec: TJ max 105 -> 125 (°C), a numeric delta of +20",
    "spec: IDD typ 120 -> 135 (mA), a numeric delta of +15",
    "spec: Output noise typ 'See Figure 7' -> 'See Figure 9' — no numeric delta",
    "spec: Turn-on time added (typ 5 ms)",
    "spec: Gain error removed (was typ 1.5 % FSR)",
    "section: §5 retitled 'Pin Functions' -> 'Pin Configuration and Functions'",
    "section: §5 page-shifted p.3 -> p.4 (rev B inserts a page before it)",
    "section: §4.2 added (rev B prints a thermal table rev A does not)",
    "section: §4 page range p.2 -> p.2-3 (it now spans the inserted page)",
    "pin: A2 renamed VDD -> VDD1P8",
    "pin: B3 added",
    "pin: A4 removed",
)

#: Rows shared by both revisions, printed identically. They exist so the gate can
#: assert the diff is *quiet* about what did not move — an unchanged row that
#: prints an unreadable value (`See Figure 12`) is the one most likely to be
#: reported spuriously by a diff that compares strings without aligning them.
_SHARED_SPECS: tuple[tuple[str, str, str, str, str, str], ...] = (
    # parameter, conditions, min, typ, max, unit
    ("Supply voltage", "", "1.7", "1.8", "1.9", "V"),
    ("Phase noise", "10 kHz offset", "", "See Figure 12", "", "dBc/Hz"),
)


def _spec_rows(revision: str) -> tuple[tuple[str, str, str, str, str, str], ...]:
    """The electrical-characteristics rows one revision prints."""
    tj_max = "105" if revision == "A" else "125"
    idd_typ = "120" if revision == "A" else "135"
    noise = "See Figure 7" if revision == "A" else "See Figure 9"
    rows = [
        *_SHARED_SPECS,
        ("Junction temperature", "", "-40", "", tj_max, "°C"),
        ("Supply current", "All channels on", "", idd_typ, "150", "mA"),
        ("Output noise", "", "", noise, "", "nV/rtHz"),
    ]
    if revision == "A":
        rows.append(("Gain error", "", "", "1.5", "", "% FSR"))
    else:
        rows.append(("Turn-on time", "", "", "5", "", "ms"))
    return tuple(rows)


def _pin_rows(revision: str) -> tuple[tuple[str, str, str, str], ...]:
    """The pin-table rows one revision prints (pin, name, I/O, description)."""
    rows = [
        ("A1", "GND", "P", "Ground return for the analog supply"),
        ("A2", "VDD" if revision == "A" else "VDD1P8", "P", "Analog supply input"),
        ("A3", "CLKIN", "I", "Reference clock input"),
        ("B1", "DOUT", "O", "Serial data output"),
        ("B2", "SDIO", "I/O", "Serial data input and output"),
    ]
    if revision == "A":
        rows.append(("A4", "NC", "-", "No connect"))
    else:
        rows.append(("B3", "SYNC", "I", "Synchronisation input"))
    return tuple(rows)


def _features_page(revision: str) -> list[tuple[float, float, str]]:
    return [
        (56.0, 72.0, f"{PART} quad RF sampling transceiver. Revision {revision}."),
        (56.0, 90.0, "Wideband transmit and receive paths with an integrated PLL."),
    ]


def _spec_page(revision: str) -> list[tuple[float, float, str]]:
    """A captioned six-column spec table on real datasheet proportions."""
    lines: list[tuple[float, float, str]] = [
        (56.0, 112.0, "Nominal supplies over the operating temperature range, unless noted."),
        (56.0, CAP_Y, "Table 1. Electrical Characteristics"),
        (SPEC_X["param"], HDR_Y, "Parameter"),
        (SPEC_X["conditions"], HDR_Y, "Test Conditions/Comments"),
        (SPEC_X["min"], HDR_Y, "Min"),
        (SPEC_X["typ"], HDR_Y, "Typ"),
        (SPEC_X["max"], HDR_Y, "Max"),
        (SPEC_X["unit"], HDR_Y, "Unit"),
    ]
    for i, row in enumerate(_spec_rows(revision), start=1):
        y = HDR_Y + i * PITCH
        for key, text in zip(
            ("param", "conditions", "min", "typ", "max", "unit"), row
        ):
            if text:
                lines.append((SPEC_X[key], y, text))
    return lines


def _thermal_page() -> list[tuple[float, float, str]]:
    """The page rev B inserts: a new section, which also shifts §5 by one page."""
    return [
        (56.0, CAP_Y, "Table 2. Thermal Information"),
        (SPEC_X["param"], HDR_Y, "Parameter"),
        (SPEC_X["typ"], HDR_Y, "Typ"),
        (SPEC_X["unit"], HDR_Y, "Unit"),
        (SPEC_X["param"], HDR_Y + PITCH, "RthetaJA Junction-to-ambient"),
        (SPEC_X["typ"], HDR_Y + PITCH, "24.5"),
        (SPEC_X["unit"], HDR_Y + PITCH, "°C/W"),
    ]


def _pin_page(revision: str) -> list[tuple[float, float, str]]:
    """A captioned four-column pin table; the layout floor needs its column rules."""
    lines: list[tuple[float, float, str]] = [
        (PIN_X["key"], CAP_Y, "Table 3. Pin Functions"),
    ]
    rows = [("PIN", "NAME", "I/O", "DESCRIPTION"), *_pin_rows(revision)]
    for i, row in enumerate(rows):
        y = HDR_Y + i * PITCH
        for key, text in zip(("key", "name", "type", "desc"), row):
            if text:
                lines.append((PIN_X[key], y, text))
    return lines


def _toc(revision: str) -> list[list]:
    """The printed TOC: rev B's inserted page moves §5, and retitles it."""
    if revision == "A":
        return [
            [1, "1 Features", 1],
            [1, "4 Specifications", 2],
            [2, "4.1 Electrical Characteristics", 2],
            [1, "5 Pin Functions", 3],
        ]
    return [
        [1, "1 Features", 1],
        [1, "4 Specifications", 2],
        [2, "4.1 Electrical Characteristics", 2],
        [2, "4.2 Thermal Information", 3],
        [1, "5 Pin Configuration and Functions", 4],
    ]


def write_revision(path: Path, revision: str) -> Path:
    """Write revision `A` or `B` of the synthetic part to `path`.

    The two differ only by `EDITS`: same geometry, same fonts, same page shapes,
    so every difference the diff reports is one this module declared.
    """
    if revision not in ("A", "B"):
        raise ValueError(f"unknown revision {revision!r}; expected 'A' or 'B'")
    pages = [_features_page(revision), _spec_page(revision)]
    if revision == "B":
        pages.append(_thermal_page())
    pages.append(_pin_page(revision))
    pin_page_index = len(pages) - 1

    doc = fitz.open()
    for index, lines in enumerate(pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text in lines:
            page.insert_text((x, y), text)
        if index == pin_page_index:
            # A pin table's cells are all filled, which reads as scattered text to
            # the layout floor's occupancy check unless the page draws the column
            # rules a real pin table prints.
            for x in (52.0, 126.0, 236.0, 296.0, 560.0):
                page.draw_line((x, CAP_Y + 6.0), (x, CAP_Y + 6.0 + 9 * PITCH))
    doc.set_toc(_toc(revision))
    doc.save(str(path))
    doc.close()
    return path


def write_pair(directory: Path) -> tuple[Path, Path]:
    """Both revisions in one directory; returns `(rev A path, rev B path)`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return (
        write_revision(directory / f"{PART.lower()}_reva.pdf", "A"),
        write_revision(directory / f"{PART.lower()}_revb.pdf", "B"),
    )
