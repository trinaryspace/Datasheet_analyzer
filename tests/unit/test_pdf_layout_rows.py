"""Row reconstruction: what the page prints, not what a span lends it.

Phase 6.5, ticket 06. Four measured misreads, all in the same layer and all
caught downstream as refusals rather than published as wrong values — so the
cost was recall, never precision. Each has a class here.

| Symptom | Measured on |
|---|---|
| a lent first cell read as a key | HMC520A `Table 4`, 24 pins lost |
| a column edge crossed by float noise | LMX1204 `Table 1-1`, every address fused to its acronym |
| a data row folded into the header | LMX1204 R11/R12/R28/R34/R79 |
| an identifier split across two lines | LMX1204 R13/R17, `SYSREFREQ_DELAY_ST EPSIZE` |

The fixtures are synthetic and each one reproduces its symptom's *geometry*,
because that is what the fix reads. Where a rule could plausibly fire on
innocent input, the opposite case is asserted in the same class — the point of
each fix is the discrimination, not the permissiveness.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import fitz

from datasheet_analyzer.extract.pdf_layout import (
    _COLUMN_EDGE_EPS,
    _block_from,
    _cell,
    _furniture_sets,
    _group_rows,
    _in_band,
    _load_pages,
    _materialize_band0,
    _TableExtraction,
    _wrapped_identifier,
)

PAGE_W, PAGE_H = 612.0, 792.0


def _pdf(path: Path, pages, rulings=None) -> Path:
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text in lines:
            page.insert_text((x, y), text)
        for x in rulings or ():
            page.draw_line((x - 4.0, 100.0), (x - 4.0, 300.0))
    doc.save(str(path))
    doc.close()
    return path


# --- a lent first cell is not a key ----------------------------------------


class TestLentFirstCells:
    """`_materialize_band0` lends a spanning parent's cell downward.

    That is right for reading (a spec row under a parameter spanning four
    condition rows needs the parameter's name) and wrong for keying. The fix
    is not to stop lending — it is to *say* which cells were lent.
    """

    def test_a_lent_cell_is_recorded(self):
        grid = [
            ["15", "LO", "LO Port."],
            ["", "EPAD", "Exposed Pad."],
        ]
        lent = _materialize_band0(grid, [100.0, 112.0], [None, None], [54.0, 131.0, 185.0])

        assert lent == [1], "the row that printed no first cell must be named"
        assert grid[1][0] == "15", "the text is still lent — readers want it"

    def test_a_printed_cell_is_never_recorded(self):
        grid = [["15", "LO", "LO Port."], ["16", "EPAD", "Exposed Pad."]]
        assert _materialize_band0(grid, [100.0, 112.0], [None, None], [54.0, 131.0, 185.0]) == []

    def test_an_indent_chain_child_is_not_lent(self):
        """It printed its own text; the parent's is a prefix, not a loan."""
        grid = [
            ["Full-Scale Output Current Range", "", ""],
            ["AC Coupling", "50 O shunt", "6.43"],
        ]
        lent = _materialize_band0(grid, [100.0, 113.0], [56.0, 72.0], [56.0, 222.0, 435.0])
        assert lent == []


# --- column edges carry typographic noise ----------------------------------


class TestColumnEdgeTolerance:
    """LMX1204's body cells start 1.5e-5 pt left of the header that declares
    their column. A strict half-open interval put every acronym in the address
    column, so `0x0 | R0` read as one cell and the address column stopped
    being addresses — 0 of 35 rows keyed."""

    HEADER_X = 100.24400329589844
    BODY_X = 100.24398803710938  # measured, from the real document

    def test_a_span_a_hair_left_of_its_edge_stays_in_its_column(self):
        assert _in_band(self.BODY_X, self.HEADER_X, 141.79)
        assert not _in_band(self.BODY_X, 61.54, self.HEADER_X)

    def test_the_tolerance_cannot_swallow_a_real_column(self):
        """The tightest real gap in the corpus is Min|Typ at 25 pt."""
        assert _COLUMN_EDGE_EPS < 1.0
        assert not _in_band(435.0, 460.0, 515.0)  # Min value stays out of Typ

    def test_bands_still_partition_a_row(self):
        """Shifting both edges keeps every span in exactly one band."""
        lefts = [56.0, 222.0, 435.0, 460.0]
        for x in (56.0, 55.95, 221.9, 222.0, 434.99, 460.0, 700.0):
            hits = sum(
                _in_band(x, lo, hi) for lo, hi in zip(lefts, lefts[1:] + [float("inf")])
            )
            assert hits == 1, f"x={x} landed in {hits} bands"


# --- a data row folded into the header -------------------------------------


class TestHeaderUnfold:
    """Wrap-merging uses the region's row pitch, and the pitch is wrong when
    the region caught text that is not the table's. LMX1204's field tables are
    followed by the next section's prose at 18 pt, which lifted the wrap
    threshold above the table's own 14 pt row gap and swallowed the first data
    row into the header — 5 tables, each reading `Bit 15:0 | Field
    rb_CLKPOS[31:16] | ...`, with the header's declaration destroyed."""

    LEFTS: ClassVar[list[float]] = [76.0, 140.0, 260.0, 340.0, 420.0]

    def _row(self, *lines):
        """One wrap-merged row from (x, y, text) triples."""
        pdf = _pdf(Path(self._dir) / "row.pdf", [list(lines)])
        page = _load_pages(pdf)[0]
        merged = _group_rows(page.lines, wrap=False)
        joined = merged[0]
        for extra in merged[1:]:
            joined.lines.extend(extra.lines)
            joined.spans.extend(extra.spans)
        return joined

    def test_a_folded_data_row_is_given_back(self, tmp_path):
        self._dir = tmp_path
        row = self._row(
            (76.0, 120.0, "Bit"), (140.0, 120.0, "Field"), (260.0, 120.0, "Type"),
            (340.0, 120.0, "Reset"), (420.0, 120.0, "Description"),
            (76.0, 134.0, "15:0"), (140.0, 134.0, "rb_CLKPOS"), (260.0, 134.0, "R"),
            (340.0, 134.0, "0xFFFF"), (420.0, 134.0, "MSBs of the field."),
        )
        block = _block_from([row], self.LEFTS, "Table 1-13.", "", 11)

        assert block.headers == ["Bit", "Field", "Type", "Reset", "Description"]
        assert block.grid == [["15:0", "rb_CLKPOS", "R", "0xFFFF", "MSBs of the field."]]

    def test_a_genuinely_wrapped_header_stays_merged(self, tmp_path):
        """AFE7950's ordering table: 2 of 8 header cells continue onto a
        second line. It fills *some* columns, not every one the header did."""
        self._dir = tmp_path
        row = self._row(
            (76.0, 120.0, "Pin"), (140.0, 120.0, "Lead finish/"),
            (260.0, 120.0, "MSL rating/"), (340.0, 120.0, "Qty"),
            (420.0, 120.0, "Package"),
            (140.0, 130.0, "Ball material"), (260.0, 130.0, "Peak reflow"),
        )
        block = _block_from([row], self.LEFTS, "", "", 3)

        assert block.headers[1] == "Lead finish/ Ball material"
        assert block.headers[2] == "MSL rating/ Peak reflow"
        assert block.grid == []


# --- an identifier split across two lines ----------------------------------


class TestWrappedIdentifiers:
    """A cell that wraps mid-token must not gain a space at the break.

    LMX1204 R13 and R17 print `SYSREFREQ_DELAY_STEPSIZE` across two lines; the
    grid read `SYSREFREQ_DELAY_ST EPSIZE`, a field name that does not exist.
    Geometry does not decide it — the line had 5.6 pt of room against a 4.7 pt
    character, so the break was not forced at that glyph — so the rule is
    lexical and deliberately narrow.
    """

    def test_an_identifier_is_rejoined_without_a_space(self):
        assert _wrapped_identifier("SYSREFREQ_DELAY_ST", "EPSIZE")

    def test_two_words_keep_their_space(self):
        """`POWER` over `SUPPLIES` is a band label printed on two lines."""
        assert not _wrapped_identifier("POWER", "SUPPLIES")

    def test_prose_keeps_its_space(self):
        assert not _wrapped_identifier("Analog supply for the analog", "section and the core.")

    @staticmethod
    def _merged(tmp_path, name, lines):
        """One cell's worth of spans, as wrap-merging hands them to `_cell`."""
        page = _load_pages(_pdf(tmp_path / name, [lines]))[0]
        rows = _group_rows(page.lines, wrap=False)
        spans = [span for row in rows for span in row.spans]
        return spans

    def test_the_join_happens_in_the_cell(self, tmp_path):
        spans = self._merged(tmp_path, "ident.pdf", [
            (108.73, 120.0, "SYSREFREQ_DELAY_ST"),
            (108.73, 130.0, "EPSIZE"),
        ])
        assert _cell(spans, 108.0, 400.0) == "SYSREFREQ_DELAY_STEPSIZE"

    def test_a_wrapped_sentence_in_the_same_cell_keeps_its_space(self, tmp_path):
        spans = self._merged(tmp_path, "prose.pdf", [
            (108.73, 120.0, "Analog supply for the analog"),
            (108.73, 130.0, "section and the clock core."),
        ])
        assert _cell(spans, 108.0, 400.0) == (
            "Analog supply for the analog section and the clock core."
        )


# --- the whole chain, on one synthetic page --------------------------------


class TestTheChainEndToEnd:
    def test_a_pin_table_with_an_unkeyed_last_row_reconstructs(self, tmp_path):
        """Every fix above, on the shape that lost HMC520A its 24 pins."""
        pdf = _pdf(
            tmp_path / "pins.pdf",
            [[
                (54.0, 110.0, "Table 4. Pin Function Descriptions"),
                (54.0, 130.0, "Pin No."), (131.0, 130.0, "Mnemonic"),
                (185.0, 130.0, "Description"),
                (54.0, 144.0, "12"), (131.0, 144.0, "GND"),
                (185.0, 144.0, "Ground return."),
                (54.0, 158.0, "15"), (131.0, 158.0, "LO"),
                (185.0, 158.0, "LO Port. See Figure 4."),
                (131.0, 172.0, "EPAD"),
                (185.0, 172.0, "Exposed Pad. Connect to GND."),
            ]],
            rulings=(54.0, 131.0, 185.0),
        )
        pages = _load_pages(pdf)
        extraction = _TableExtraction(pages)
        for page, marked in zip(pages, _furniture_sets(pages)):
            extraction.run(page, marked, frozenset())

        block = next(b for blocks in extraction.by_page.values() for b in blocks)
        assert [row[0] for row in block.grid] == ["12", "15", "15"]
        assert block.lent_first_cells == [2], (
            "the exposed-pad row prints no pin number; the `15` is lent, and "
            "saying so is what lets the other pins publish"
        )
