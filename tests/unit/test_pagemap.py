"""Pain point: wrong page citations. Sections must map to PDF TOC pages
exactly (by number), fuzzily (by title), or by inheritance — with honest
reporting. Tables get exact pages pinned from PDF page text."""

from __future__ import annotations

from datasheet_analyzer.models import SectionNode, TableBlock, TOCEntry
from datasheet_analyzer.structure.pagemap import (
    _section_page_ranges,
    assign_pages,
    pin_table_pages,
)

PDF_TOC = [
    TOCEntry(number="1", title="Features", level=1, page=1),
    TOCEntry(number="4", title="Specifications", level=1, page=4),
    TOCEntry(number="4.1", title="Absolute Maximum Ratings", level=2, page=4),
    TOCEntry(number="4.5", title="Transmitter Electrical Characteristics", level=2, page=7),
    TOCEntry(number="4.6", title="RF ADC Electrical Characteristics", level=2, page=14),
    TOCEntry(number="4.7", title="PLL/VCO/Clock Electrical Characteristics", level=2, page=18),
    TOCEntry(
        number="4.12.9",
        title="RX Typical Characteristics at 1.75 GHz – 1.9 GHz",
        level=3,
        page=97,
    ),
    TOCEntry(number="5", title="Revision History", level=1, page=134),
]


def _sec(number, title, level):
    return SectionNode(number=number, title=title, level=level)


class TestPageRanges:
    def test_range_ends_at_next_same_or_higher_level(self):
        ranges = _section_page_ranges(PDF_TOC)
        assert ranges["4.5"] == (7, 13)  # ends where 4.6 starts (p14)
        assert ranges["4.6"] == (14, 17)
        assert ranges["1"] == (1, 3)  # ends where 4 starts (p4)

    def test_last_entry_ends_on_own_page(self):
        ranges = _section_page_ranges(PDF_TOC)
        assert ranges["5"] == (134, 134)


class TestAssignPages:
    def test_exact_number_match(self):
        sections, report = assign_pages([_sec("4.5", "anything", 2)], PDF_TOC)
        assert (sections[0].page_start, sections[0].page_end) == (7, 13)
        assert report.n_exact == 1 and report.coverage == 1.0

    def test_fuzzy_title_match_for_en_dash_variants(self):
        # HTML title uses an en-dash/spacing variant of the PDF TOC title
        sec = _sec("", "RX Typical Characteristics at 1.75 GHz - 1.9 GHz", 3)
        sections, report = assign_pages([sec], PDF_TOC)
        # 4.12.9 starts p97; range ends where "5 Revision History" starts (p134)
        assert (sections[0].page_start, sections[0].page_end) == (97, 133)
        assert report.n_fuzzy == 1

    def test_inherit_from_parent_when_unmatched(self):
        parent = _sec("4.5", "Transmitter Electrical Characteristics", 2)
        child = _sec("", "Some unnumbered subsection", 3)
        sections, report = assign_pages([parent, child], PDF_TOC)
        assert sections[1].page_start == 7
        assert report.n_inherited == 1

    def test_unmatched_reported_honestly(self):
        sections, report = assign_pages([_sec("", "Mystery Appendix", 1)], PDF_TOC)
        assert sections[0].page_start is None
        assert report.n_unmatched == 1
        assert "Mystery Appendix" in report.unmatched[0]
        assert report.coverage == 0.0


class TestPinTablePages:
    def _table(self):
        return TableBlock(
            headers=["PARAMETER", "TYP", "UNIT"],
            grid=[
                ["Pmax_FS", "4.2", "dBm"],
                ["RTERM", "50", "Ω"],
                ["ATTrange", "40", "dB"],
            ],
        )

    def test_pins_page_by_distinctive_values(self):
        pages = [""] * 13  # 13 pages
        pages[6] = "Pmax_FS 4.2 dBm RTERM 50 Ω ATTrange 40 dB"  # page 7
        pages[8] = "unrelated content"
        sec = SectionNode(
            number="4.5",
            title="TX",
            level=2,
            page_start=7,
            page_end=13,
            tables=[self._table()],
        )
        pinned = pin_table_pages([sec], pages)
        assert pinned == 1
        assert sec.tables[0].page == 7

    def test_no_pin_when_values_absent(self):
        pages = ["nothing relevant"] * 13
        sec = SectionNode(
            number="4.5",
            title="TX",
            level=2,
            page_start=7,
            page_end=13,
            tables=[self._table()],
        )
        assert pin_table_pages([sec], pages) == 0
        assert sec.tables[0].page is None

    def test_search_confined_to_section_range(self):
        pages = ["Pmax_FS 4.2 dBm RTERM 50 Ω ATTrange 40 dB"] + [""] * 20
        # table's values live on page 1, but section starts at p7: must NOT pin
        sec = SectionNode(
            number="4.5",
            title="TX",
            level=2,
            page_start=7,
            page_end=13,
            tables=[self._table()],
        )
        assert pin_table_pages([sec], pages) == 0
