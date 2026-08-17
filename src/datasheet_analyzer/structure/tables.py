"""HTML table -> atomic TableBlock, with full rowspan/colspan expansion.

Pain point addressed: datasheet parametric tables merge cells vertically
(one parameter symbol spanning many condition rows) and horizontally (one
"PARAMETER" header over symbol+description columns). If spans are not
expanded, a downstream agent reading row N loses the parameter it belongs
to — silently producing wrong min/typ/max associations.

The expanded `grid` guarantees: grid[r][c] is the effective value of that
cell with all merges resolved. We also precompute markdown and CSV so the
corpus writer never re-derives them.
"""

from __future__ import annotations

import csv
import io
import re
from collections import deque

from bs4 import BeautifulSoup, Tag

from datasheet_analyzer.models import Footnote, TableBlock

_WS = re.compile(r"\s+")

#: C0 control characters (tab excepted) that a broken font ToUnicode map can
#: leave in extracted text. LMX1204's figures print ligatures whose CMap points
#: at U+0000 / U+0001 / U+0002 rather than at `fi` / `ft` / `ti`, and a NUL in
#: particular makes `csv.writer` raise "need to escape, but no escapechar set"
#: — the whole build dies on one glyph. These are not characters the datasheet
#: printed; they cannot be rendered, and they cannot be written to CSV at all.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def cell_text(cell: Tag) -> str:
    """Flatten a cell's text, keeping sub/sup content joined to its base.

    `get_text("")` keeps inline math like `f` + `<sub>RFout</sub>` as
    "fRFout" and sup footnote refs like `<sup>(2)</sup>` attached to their
    value ("±1(2)") — exactly the associations we must preserve. Whitespace
    runs are then collapsed.
    """
    text = cell.get_text("", strip=False)
    return _WS.sub(" ", text).strip()


def _expand_rows(rows: list[list[Tag]]) -> list[list[str]]:
    """Expand a matrix of cells (with rowspan/colspan attrs) to a full grid.

    Active rowspans are tracked per column and filled (and decremented) on
    every subsequent row, including rows that run out of explicit cells —
    malformed short rows still consume their spans, then get padded.
    """
    grid: list[list[str]] = []
    spans: dict[int, list] = {}  # col -> [remaining_rows, text]

    for row_cells in rows:
        out: list[str] = []
        cells = deque(row_cells)
        col = 0
        while True:
            if col in spans:
                out.append(spans[col][1])
                spans[col][0] -= 1
                if spans[col][0] <= 0:
                    del spans[col]
                col += 1
                continue
            if not cells:
                break
            cell = cells.popleft()
            text = cell_text(cell)
            try:
                colspan = max(1, int(cell.get("colspan", 1)))
            except (TypeError, ValueError):
                colspan = 1
            try:
                rowspan = max(1, int(cell.get("rowspan", 1)))
            except (TypeError, ValueError):
                rowspan = 1
            for k in range(colspan):
                out.append(text)
                if rowspan > 1:
                    spans[col + k] = [rowspan - 1, text]
            col += colspan
        # cells exhausted: drain any spans still active at/after this column
        # so every row consumes its rowspans exactly once.
        while spans and col <= max(spans):
            if col in spans:
                out.append(spans[col][1])
                spans[col][0] -= 1
                if spans[col][0] <= 0:
                    del spans[col]
            else:
                out.append("")
            col += 1
        grid.append(out)

    n_cols = max((len(r) for r in grid), default=0)
    for r in grid:
        r.extend([""] * (n_cols - len(r)))
    return grid


def _disambiguate(headers: list[str]) -> list[str]:
    """Make header names unique for CSV (a colspan header like 'PARAMETER'
    over two body columns would otherwise collide)."""
    seen: dict[str, int] = {}
    out = []
    for h in headers:
        if h in seen:
            seen[h] += 1
            out.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 1
            out.append(h)
    return out


def _to_markdown(headers: list[str], grid: list[list[str]]) -> str:
    def esc(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", " ").strip()

    lines: list[str] = []
    if headers:
        lines.append("| " + " | ".join(esc(h) for h in headers) + " |")
        lines.append("|" + "|".join([" --- "] * len(headers)) + "|")
    for row in grid:
        lines.append("| " + " | ".join(esc(c) for c in row) + " |")
    return "\n".join(lines)


def _csv_safe(cell: str) -> str:
    """One cell as CSV can carry it: control characters dropped.

    The *only* mutation this module performs, and deliberately confined to the
    machine twin — `TableBlock.grid` keeps whatever the extractor read, because
    verbatim stays authoritative. A C0 control character is not a printed
    character at all: it is what a PDF's font map yields when it points a
    ligature glyph at U+0001 instead of at `ft`, and `csv.writer` cannot encode
    a NUL under any dialect (it reads as an unset escapechar and raises). One
    such glyph in one figure would otherwise take the whole part's build down,
    which is the crash-instead-of-degrade failure invariant 7 forbids.
    """
    return _CONTROL.sub("", cell)


def _to_csv(headers: list[str], grid: list[list[str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if headers:
        w.writerow(_csv_safe(h) for h in _disambiguate(headers))
    w.writerows([_csv_safe(c) for c in row] for row in grid)
    return buf.getvalue()


def grid_markdown(headers: list[str], grid: list[list[str]]) -> str:
    """Precomputed markdown rendering of a header+grid pair.

    Public so non-HTML backends (pdf_layout) can build corpus-grade
    TableBlocks with the exact same encoding as HTML tables.
    """
    return _to_markdown(headers, grid)


def grid_csv(headers: list[str], grid: list[list[str]]) -> str:
    """Precomputed CSV rendering of a header+grid pair (machine twin)."""
    return _to_csv(headers, grid)


def html_table_to_block(
    table_el: Tag | str,
    *,
    caption: str = "",
    conditions: str = "",
    footnotes: list[Footnote] | None = None,
    page: int | None = None,
) -> TableBlock:
    """Convert a BeautifulSoup <table> (or HTML string) to a TableBlock."""
    if isinstance(table_el, str):
        table_el = BeautifulSoup(table_el, "lxml").find("table")
    if table_el is None:
        raise ValueError("no <table> found in input")

    # Headers: thead rows, expanded for colspans. Multi-row theads are
    # flattened: later header rows refine earlier ones per column.
    headers: list[str] = []
    thead = table_el.find("thead")
    if thead:
        header_rows = [[c for c in tr.find_all(["th", "td"], recursive=False)]
                       for tr in thead.find_all("tr", recursive=False)]
        expanded = _expand_rows(header_rows)
        if expanded:
            n_cols = max(len(r) for r in expanded)
            headers = []
            for c in range(n_cols):
                parts = [r[c] for r in expanded if c < len(r) and r[c]]
                # dedupe consecutive repeats from rowspans in the thead
                deduped = [p for i, p in enumerate(parts) if i == 0 or p != parts[i - 1]]
                headers.append(" ".join(deduped))

    body_root = table_el.find("tbody") or table_el
    body_rows = [
        [c for c in tr.find_all(["td", "th"], recursive=False)]
        for tr in body_root.find_all("tr", recursive=False)
    ]
    grid = _expand_rows(body_rows)
    # drop fully-empty rows (TI uses spacer rows)
    grid = [r for r in grid if any(c.strip() for c in r)]

    return TableBlock(
        caption=caption.strip(),
        headers=headers,
        grid=grid,
        conditions=conditions.strip(),
        footnotes=footnotes or [],
        markdown=_to_markdown(headers, grid),
        csv=_to_csv(headers, grid),
        html=str(table_el),
        page=page,
    )


def cited_markers(table_el: Tag | str) -> set[str]:
    """Footnote markers actually cited inside a table's cells.

    Markers are read from <sup> elements only — after flattening, a
    parenthesized number is ambiguous (could be a real value), so we catch
    them while the HTML structure is still available.
    """
    if isinstance(table_el, str):
        table_el = BeautifulSoup(table_el, "lxml").find("table")
    markers: set[str] = set()
    for sup in table_el.find_all("sup"):
        m = re.fullmatch(r"\s*(\(\d+\))\s*", sup.get_text())
        if m:
            markers.add(m.group(1))
    return markers
