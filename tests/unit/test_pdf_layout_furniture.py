"""Furniture detection must not eat table content.

Phase 6.5, ticket 05. Recurrence is the right signal for a running header and
the wrong one for a register map, which prints the same short strings in the
same slots on every field-description page.

Measured on `LMX1204_registermap.pdf`: `0x0` — the reset value of a field —
prints in one y-band on **11 of the document's 25 pages**, against a
recurrence threshold of 10. The first body row of its register summary
(`Table 1-1`, 35 rows) was therefore classified as page machinery; the table
region was cut off after its header row, reconstruction was rejected with
`no viable column split`, and the cell was gone from the paragraph stream too,
so nothing downstream could recover it.

The fixture below is that document in miniature, and it must hold **both**
directions at once: a document dense in repeated cells whose table survives,
and running headers and footers in the same document that are still stripped.
A fix that only satisfies the first is the bug in the other direction.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from datasheet_analyzer.extract.pdf_layout import (
    _MIN_PAGES,
    _MIN_PAGES_FRAC,
    _band_key,
    _furniture_sets,
    _load_pages,
    _TableExtraction,
    _threshold,
)

PAGE_W, PAGE_H = 612.0, 792.0

HEADER_Y = 31.9
FOOTER_Y = 750.7
#: The band the summary table's first body row and every field table's reset
#: value share. That collision is the whole defect.
COLLIDING_Y = 200.0
SITE = "www.example.com"
#: Column left edges, from the real document's geometry.
X_ADDR, X_ACRONYM, X_FEATURES, X_SECTION = 71.1, 140.0, 210.0, 520.0


def _running_header(page_index: int, *, varying_left: bool = False):
    """A real running header: the same two strings, in the same slot, always.

    `varying_left` reproduces the shape that defeats a row-sharing rule on its
    own — pages 1 and 24 of the real document print the site beside a heading
    unique to that page, so the recurring half shares its row with content and
    would be released if only the row were consulted.
    """
    left = f"Chapter {page_index}" if varying_left else "PART9000 Registers"
    return [(54.0, HEADER_Y, left), (517.6, HEADER_Y, SITE)]


def _running_footer(page_index: int):
    return [
        (54.0, FOOTER_Y, str(page_index)),
        (100.0, FOOTER_Y, "PART9000 Register Map"),
        (300.0, FOOTER_Y, "SNAU269A - AUGUST 2021"),
    ]


def _summary_page():
    """Page 1: the register summary, whose first body row starts with `0x0`."""
    rows = [
        ("0x0", "R0", "Powerdown, Reset, Multiplier Mode Calibration", "Go"),
        ("0x2", "R2", "Multiplier Mode (State Machine Clock)", "Go"),
        ("0x3", "R3", "Output Enables, CLKOUT Power", "Go"),
        ("0x4", "R4", "CLKOUT Power, SYSREFOUT Power", "Go"),
        ("0x5", "R5", "LOGICLK Enable, SYSREFOUT Power/VCM", "Go"),
    ]
    lines = [
        *_running_header(1),
        (236.1, 160.0, "Table 1-1. PART9000 Registers"),
        (X_ADDR, 186.0, "Address"),
        (X_ACRONYM, 186.0, "Acronym"),
        (X_FEATURES, 186.0, "Features Requiring This Register"),
        (X_SECTION, 186.0, "Section"),
    ]
    for n, (addr, acronym, features, section) in enumerate(rows):
        y = COLLIDING_Y + n * 14.0
        lines += [
            (X_ADDR, y, addr),
            (X_ACRONYM, y, acronym),
            (X_FEATURES, y, features),
            (X_SECTION, y, section),
        ]
    return lines


def _field_page(page_index: int):
    """A field-description page: `0x0` prints in the colliding slot again.

    Every one of these pushes the recurrence count over the threshold, and
    every one is also genuine table content.

    The row around it is deliberately **unique to its page**, because that is
    what the real document looks like and it is what the release rule reads:
    the colliding band is mostly content (24% furniture, measured on
    LMX1204's), while the header band is almost entirely machinery (96%). A
    fixture whose field pages were identical would make the colliding band
    machinery too, and would be testing a different document.
    """
    return [
        *_running_header(page_index, varying_left=(page_index == 12)),
        (236.1, 160.0, f"Table 1-{page_index}. R{page_index} Register Field Descriptions"),
        (108.7, 186.0, "Field"),
        (208.5, 186.0, "Bits"),
        (258.3, 186.0, "Reset"),
        (330.0, 186.0, "Type"),
        (390.0, 186.0, "Default"),
        (450.0, 186.0, "Description"),
        (108.7, COLLIDING_Y, f"MUXOUT_SEL_{page_index}"),
        (208.5, COLLIDING_Y, f"[{page_index}:0]"),
        (258.3, COLLIDING_Y, "0x0"),
        (330.0, COLLIDING_Y, f"RW{page_index}"),
        (390.0, COLLIDING_Y, f"{page_index}d"),
        (450.0, COLLIDING_Y, f"Selects readback source {page_index}."),
        (108.7, COLLIDING_Y + 14.0, f"SYSREF_DLY_{page_index}"),
        (208.5, COLLIDING_Y + 14.0, f"[{page_index + 4}:{page_index}]"),
        (258.3, COLLIDING_Y + 14.0, f"0x{page_index:X}"),
        (330.0, COLLIDING_Y + 14.0, f"RW{page_index}"),
        (390.0, COLLIDING_Y + 14.0, f"{page_index}h"),
        (450.0, COLLIDING_Y + 14.0, f"Delay step {page_index}."),
        *_running_footer(page_index),
    ]


def _register_map(path: Path, n_pages: int = 12) -> Path:
    doc = fitz.open()
    for index in range(1, n_pages + 1):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        lines = _summary_page() if index == 1 else _field_page(index)
        for x, y, text in lines:
            page.insert_text((x, y), text)
        # Column rulings, because a register map draws them and because a
        # fully-packed unruled grid is indistinguishable from scattered junk —
        # the reconstruction gate says so, and it is right to.
        columns = (
            (X_ADDR, X_ACRONYM, X_FEATURES, X_SECTION)
            if index == 1
            else (108.7, 208.5, 258.3, 330.0, 390.0, 450.0)
        )
        for x in columns:
            page.draw_line((x - 4.0, 165.0), (x - 4.0, COLLIDING_Y + 80.0))
    doc.save(str(path))
    doc.close()
    return path


def _pages_and_furniture(tmp_path, n_pages: int = 12):
    pages = _load_pages(_register_map(tmp_path / "regmap.pdf", n_pages))
    return pages, _furniture_sets(pages)


def _texts(page, indices) -> set[str]:
    return {page.lines[i].text for i in indices}


class TestTheFixtureReallyReproducesTheDefect:
    """A fixture that does not trip the threshold would prove nothing."""

    def test_the_colliding_value_recurs_past_the_threshold(self, tmp_path):
        pages, _furniture = _pages_and_furniture(tmp_path)
        bands = {
            _band_key(line.y)
            for page in pages
            for line in page.lines
            if line.text == "0x0"
        }
        printing_it = [
            page.index
            for page in pages
            if any(line.text == "0x0" and _band_key(line.y) in bands for line in page.lines)
        ]
        assert len(bands) == 1, "the colliding value must print in one band, as it does"
        assert len(printing_it) >= _threshold(len(pages)), (
            "the fixture must print the same value in the same slot often enough "
            "to be mistaken for page machinery, or this module tests nothing"
        )


class TestReleasedContent:
    def test_the_summary_s_first_row_survives(self, tmp_path):
        pages, furniture = _pages_and_furniture(tmp_path)
        assert "0x0" not in _texts(pages[0], furniture[0])

    def test_a_field_table_s_reset_value_survives(self, tmp_path):
        pages, furniture = _pages_and_furniture(tmp_path)
        for page, marked in zip(pages[1:], furniture[1:]):
            assert "0x0" not in _texts(page, marked)

    def test_the_summary_table_reconstructs_whole(self, tmp_path):
        """The consequence, end to end: every row the page prints."""
        pages, furniture = _pages_and_furniture(tmp_path)
        extraction = _TableExtraction(pages)
        for page, marked in zip(pages, furniture):
            extraction.run(page, marked, frozenset())

        summary = [
            block
            for blocks in extraction.by_page.values()
            for block in blocks
            if block.caption.startswith("Table 1-1.")
        ]
        assert len(summary) == 1, "the register summary must be accepted"
        assert [row[0] for row in summary[0].grid] == ["0x0", "0x2", "0x3", "0x4", "0x5"]


class TestStrippedMachinery:
    """The other direction, in the same document."""

    def test_a_running_header_is_still_stripped(self, tmp_path):
        pages, furniture = _pages_and_furniture(tmp_path)
        assert SITE in _texts(pages[0], furniture[0])
        assert "PART9000 Registers" in _texts(pages[1], furniture[1])

    def test_a_running_header_beside_varying_text_is_still_stripped(self, tmp_path):
        """The case a row-sharing rule alone gets wrong.

        On page 12 the site prints beside a heading unique to that page, so
        the recurring half *does* share its row with content. It is still
        machinery, because its band is machinery document-wide — which is why
        the release rule consults the band and not only the row.
        """
        pages, furniture = _pages_and_furniture(tmp_path)
        last = next(p for p in pages if p.index == 12)
        assert SITE in _texts(last, furniture[last.index - 1])

    def test_a_running_footer_is_still_stripped(self, tmp_path):
        pages, furniture = _pages_and_furniture(tmp_path)
        stripped = _texts(pages[1], furniture[1])
        assert "PART9000 Register Map" in stripped
        assert "SNAU269A - AUGUST 2021" in stripped

    def test_a_bare_page_number_in_the_gutter_is_still_stripped(self, tmp_path):
        """Machinery by shape, never released whatever its row holds."""
        pages, furniture = _pages_and_furniture(tmp_path)
        for page, marked in list(zip(pages, furniture))[1:]:
            assert str(page.index) in _texts(page, marked)


class TestTheThresholdIsNotTheFix:
    """Raising the recurrence threshold would break header stripping.

    Recorded as a test because it is the obvious wrong fix: it makes this
    document pass and silently stops stripping headers on any document with
    more pages.
    """

    def test_the_recurrence_constants_are_unchanged(self):
        assert (_MIN_PAGES, _MIN_PAGES_FRAC) == (2, 0.4)
        assert _threshold(25) == 10  # the real document's threshold
