"""A row cites the page it is printed on, not the page its table began on.

Phase 6.5, ticket 07. `TableBlock.row_pages` is real geometry on the
`pdf_layout` path; the HTML path has none, so every row of an HTML-derived
table inherited its table's page. Measured on LMX1204's `Table 7-1`: 1 row of
35 (`0x5A` / `R90`) prints on page 33 and cited page 32, and the spec records
read from it inherited the error.

One row in thirty-five is small, and small is the dangerous size — a citation
that is *nearly* right is the one a reader trusts without opening the page.

Every fixture here is page *text*, not a PDF: the rule under test is "find the
row's distinctive cells in the page's words", and feeding it words is the
honest way to ask. The classes are organized around the ways it must refuse.
"""

from __future__ import annotations

from datasheet_analyzer.models import SectionNode, TableBlock
from datasheet_analyzer.structure.pagemap import (
    _row_needles,
    pin_table_row_pages,
    reconcile_table_pages,
)


def _section(table: TableBlock, *, start: int, end: int) -> SectionNode:
    return SectionNode(
        number="7.1", title="Registers", page_start=start, page_end=end, tables=[table]
    )


def _table(grid, *, page, headers=("Address", "Acronym", "Features"), row_pages=()):
    return TableBlock(
        caption="Table 7-1. Registers",
        headers=list(headers),
        grid=[list(r) for r in grid],
        page=page,
        row_pages=list(row_pages),
    )


#: LMX1204's register summary in miniature: 34 rows on one page and a last row
#: that printed on the next. Page 3 also repeats the last row's values, the way
#: the real document repeats them 22 pages later in its field descriptions —
#: the reason a "best page in the section" rule got this row wrong.
REGISTER_PAGES = [
    "",  # p.1 — nothing
    "0x0 R0 Powerdown 0x56 R86 CLKOUT Divider",  # p.2 — the table starts
    "0x5A R90 LOGICLK Divider",  # p.3 — the last row spills onto it
    "0x5A R90 mentioned again in a field description",  # p.4 — a decoy
]


class TestTheRowThatSpills:
    def test_the_last_row_cites_the_page_it_printed_on(self):
        table = _table(
            [
                ["0x0", "R0", "Powerdown"],
                ["0x56", "R86", "CLKOUT Divider"],
                ["0x5A", "R90", "LOGICLK Divider"],
            ],
            page=2,
        )
        pinned, total = pin_table_row_pages([_section(table, start=2, end=3)], REGISTER_PAGES)

        assert table.row_pages == [2, 2, 3]
        assert (pinned, total) == (3, 3)

    def test_a_decoy_further_down_the_document_is_never_reached(self):
        """The walk advances one page at a time, so a later repeat cannot win.

        Searching the whole section for the best page is what a first attempt
        did, and it tied page 3 against the decoy and left the row unpinned.
        """
        table = _table([["0x5A", "R90", "LOGICLK Divider"]], page=2)
        pin_table_row_pages([_section(table, start=2, end=4)], REGISTER_PAGES)

        assert table.row_pages == [3], "the decoy on p.4 must not attract the row"

    def test_a_table_may_finish_on_the_page_the_next_section_starts(self):
        """The section range is a heading boundary, not a content one."""
        table = _table([["0x0", "R0", "Powerdown"], ["0x5A", "R90", "LOGICLK Divider"]], page=2)
        pin_table_row_pages([_section(table, start=2, end=2)], REGISTER_PAGES)

        assert table.row_pages == [2, 3]


class TestWhatItRefusesToGuess:
    def test_a_row_with_no_distinctive_cell_keeps_its_place(self):
        """A row of dashes and bare digits cannot be located, and says so."""
        assert _row_needles(["—", "—", "5"]) == []

        table = _table([["0x0", "R0", "Powerdown"], ["—", "—", "5"]], page=2)
        pinned, total = pin_table_row_pages([_section(table, start=2, end=3)], REGISTER_PAGES)

        assert table.row_pages == [2, 2]
        assert (pinned, total) == (1, 2), "the unlocatable row is not counted as pinned"

    def test_a_blank_row_keeps_its_place(self):
        table = _table([["0x0", "R0", "Powerdown"], ["", "", ""]], page=2)
        pin_table_row_pages([_section(table, start=2, end=3)], REGISTER_PAGES)

        assert table.row_pages == [2, 2]

    def test_staying_is_the_default_when_evidence_is_equal(self):
        """Both pages print the row: no reason to move it, so it does not."""
        pages = ["", "VDD 1.8 V rail", "VDD 1.8 V rail"]
        table = _table([["VDD", "1.8 V", "rail"]], page=2)
        pin_table_row_pages([_section(table, start=2, end=3)], pages)

        assert table.row_pages == [2]

    def test_a_row_never_moves_backwards(self):
        """A row cannot print before the table it belongs to starts."""
        pages = ["0x5A R90 LOGICLK Divider", "0x0 R0", "0x5A R90 LOGICLK Divider"]
        table = _table([["0x5A", "R90", "LOGICLK Divider"]], page=2)
        pin_table_row_pages([_section(table, start=1, end=3)], pages)

        assert table.row_pages == [2] or table.row_pages == [3]
        assert table.row_pages[0] >= 2


class TestMeasuredGeometryIsLeftAlone:
    def test_a_layout_derived_table_is_not_overwritten(self):
        """`pdf_layout` read these off the page; this rule only guesses."""
        table = _table(
            [["0x0", "R0", "Powerdown"], ["0x5A", "R90", "LOGICLK Divider"]],
            page=2,
            row_pages=[7, 8],
        )
        pinned, total = pin_table_row_pages([_section(table, start=2, end=3)], REGISTER_PAGES)

        assert table.row_pages == [7, 8]
        assert (pinned, total) == (0, 0), "a table with geometry is not counted"

    def test_a_table_with_no_page_is_skipped(self):
        table = _table([["0x0", "R0", "Powerdown"]], page=None)
        pin_table_row_pages([_section(table, start=2, end=3)], REGISTER_PAGES)

        assert table.row_pages == []


class TestTheNeedleRule:
    """Row needles read the same way `_distinctive_needles` reads a table."""

    def test_a_value_with_digits_is_distinctive(self):
        assert _row_needles(["0x5A"]) == ["0x5a"]

    def test_a_symbol_without_digits_is_distinctive(self):
        assert _row_needles(["ATTrange"]) == ["attrange"]

    def test_a_bare_digit_is_not(self):
        assert _row_needles(["5", "12"]) == []


class TestTheTableFollowsItsRows:
    """A table's page is the page its first row prints on.

    Two producers answer "what page is this table on". `pin_table_pages`
    searches the whole section for the table's distinctive cells and takes the
    page with the most hits; `row_pages` is either measured geometry (the
    `pdf_layout` path) or a walk that turns the page only on strictly better
    evidence. Where they disagree, the rows are the stronger evidence.

    Measured on `LMX1204_registermap.pdf`: `Table 1-25. R24 Register Field
    Descriptions` prints on page 19 — its caption is there and its five rows
    were measured there — and the section-wide search pinned it to page 17,
    where R22's near-identical field table prints. Eight published bit fields
    cited p.17 as a result.
    """

    def test_a_table_whose_rows_all_print_later_moves_to_them(self):
        table = _table([["0x16", "R22", "a"]], page=17, row_pages=[19])
        moved = reconcile_table_pages([_section(table, start=2, end=23)])
        assert table.page == 19
        assert moved == [("Table 7-1. Registers", 17, 19)]

    def test_a_table_that_already_agrees_is_left_alone(self):
        table = _table([["0x16", "R22", "a"], ["0x17", "R23", "b"]], page=19, row_pages=[19, 20])
        assert reconcile_table_pages([_section(table, start=2, end=23)]) == []
        assert table.page == 19

    def test_a_table_with_no_pinned_row_keeps_its_page(self):
        table = _table([["0x16", "R22", "a"]], page=17, row_pages=[None])
        assert reconcile_table_pages([_section(table, start=2, end=23)]) == []
        assert table.page == 17

    def test_a_table_with_no_page_of_its_own_is_not_invented(self):
        table = _table([["0x16", "R22", "a"]], page=None, row_pages=[19])
        assert reconcile_table_pages([_section(table, start=2, end=23)]) == []
        assert table.page is None
