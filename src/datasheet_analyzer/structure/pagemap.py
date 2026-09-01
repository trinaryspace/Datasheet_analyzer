"""Page assignment: reconcile HTML sections with the PDF's printed TOC.

Pain point addressed: answers must cite PDF pages, but the HTML source has
no page numbers. The PDF TOC does. We match sections to TOC entries —
primary key is the section number ("4.5"), fallback is normalized-title
fuzzy match, last resort is inheriting the parent's range — and record the
provenance of every assignment so coverage is measurable and testable.

Also provides `pin_table_pages`: tables inside a multi-page section get
their exact page pinned by locating distinctive cell values in the PDF's
per-page text. "p.7" beats "p.7-13" when an agent cites a spec.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from datasheet_analyzer.models import SectionNode, TOCEntry

_WS = re.compile(r"\s+")
_NONALNUM = re.compile(r"[^a-z0-9]+")


def _norm(title: str) -> str:
    return _NONALNUM.sub(" ", title.lower()).strip()


@dataclass
class PageAssignReport:
    n_exact: int = 0
    n_fuzzy: int = 0
    n_inherited: int = 0
    n_unmatched: int = 0
    unmatched: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        total = self.n_exact + self.n_fuzzy + self.n_inherited + self.n_unmatched
        return 1.0 if total == 0 else (total - self.n_unmatched) / total


def _section_page_ranges(toc: list[TOCEntry]) -> dict[str, tuple[int, int]]:
    """Section number -> (start, end) page range from a flat TOC: a section's
    range ends where the next entry of same-or-higher level begins."""
    ranges: dict[str, tuple[int, int]] = {}
    keyed = [(i, e) for i, e in enumerate(toc) if e.number and e.page]
    for pos, (i, entry) in enumerate(keyed):
        end = entry.page
        for _j, later in keyed[pos + 1 :]:
            if later.level <= entry.level:
                # ends on the page before the next sibling/parent starts,
                # but never before its own start page
                end = max(entry.page, (later.page or entry.page) - 1)
                break
        else:
            end = entry.page
        ranges[entry.number] = (entry.page, max(entry.page, end))
    return ranges


def assign_pages(
    sections: list[SectionNode], pdf_toc: list[TOCEntry], *, fuzzy_cutoff: float = 0.86
) -> tuple[list[SectionNode], PageAssignReport]:
    """Assign page_start/page_end to each section from the PDF TOC."""
    report = PageAssignReport()
    by_number = {e.number: e for e in pdf_toc if e.number}
    ranges = _section_page_ranges(pdf_toc)
    title_index = {_norm(e.title): e.number for e in pdf_toc if e.number}

    out: list[SectionNode] = []
    last_with_pages: SectionNode | None = None
    for sec in sections:
        number, start, end = sec.number, None, None
        if number and number in by_number:
            start, end = ranges[number]
            report.n_exact += 1
        else:
            key = _norm(sec.title)
            if key in title_index and title_index[key] in ranges:
                start, end = ranges[title_index[key]]
                report.n_fuzzy += 1
            else:
                # fuzzy title match ("RX Typical Characteristics at 1.75 GHz – 1.9 GHz")
                best = difflib.get_close_matches(key, list(title_index), n=1, cutoff=fuzzy_cutoff)
                if best and title_index[best[0]] in ranges:
                    start, end = ranges[title_index[best[0]]]
                    report.n_fuzzy += 1
                elif last_with_pages is not None and sec.level > last_with_pages.level:
                    start, end = last_with_pages.page_start, last_with_pages.page_end
                    report.n_inherited += 1
                else:
                    report.n_unmatched += 1
                    report.unmatched.append(sec.full_title or sec.title)
        sec = sec.model_copy(update={"page_start": start, "page_end": end})
        if start is not None:
            last_with_pages = sec
        out.append(sec)
    return out, report


_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9_+/().-]{2,}$")


def _distinctive_needles(table) -> list[str]:
    """Pick cell values likely to locate the table in the PDF page text:
    decimals-with-units and parameter symbols (Pmax_FS, ATTrange, …)."""
    needles: list[str] = []
    for row in table.grid[:3]:  # first rows are enough to locate the table
        for cell in row:
            c = cell.strip()
            has_digit = any(ch.isdigit() for ch in c)
            if has_digit and len(c) >= 3 and not c.isdigit() or _SYMBOL.match(c) and not has_digit:
                needles.append(c)
        if len(needles) >= 6:
            break
    return needles


def _squash(text: str) -> str:
    """Aggressive normalizer: lowercase alnum only — immune to the dash,
    space and ligature differences between HTML cells and PDF text."""
    return _NONALNUM.sub("", text.lower())


def _caption_page(table, page_texts: list[str], lo: int, hi: int) -> int | None:
    """The page a captioned table's own caption prints on, when unambiguous.

    A caption is the strongest needle a table has: `Table 1-25. R24 Register
    Field Descriptions` prints once and names the table it belongs to, where
    cell values are shared with every neighbouring table of the same shape.
    Only a caption that prints on **exactly one** page of the section counts —
    two hits is not evidence about which one is the table.
    """
    caption = _squash(table.caption or "")
    if len(caption) < 8:
        return None
    hits = [
        p + 1 for p in range(lo, min(hi + 1, len(page_texts))) if caption in _squash(page_texts[p])
    ]
    return hits[0] if len(hits) == 1 else None


def pin_table_pages(sections: list[SectionNode], page_texts: list[str]) -> int:
    """Pin each table's exact page by locating it in the PDF's page text.

    Its own **caption** first, where it has one that prints on exactly one
    page of the section: a caption names the table, and cell values do not.
    Measured over this project's eleven parts, **117 of 118** captioned tables
    already agreed with the cell-value search and one did not — `Table 7-25 R24
    Register Field Descriptions` in `lmx1204.pdf`, pinned to p.47 by the cell
    values it shares with R22's near-identical field table and printed on p.49.
    Eight published bit fields cited p.47 because of it.

    Falls back to the cell-value search (`_distinctive_needles`) for a table
    with no caption, or whose caption prints on no page or more than one.
    Only searches within the section's page range. Returns the number of
    tables pinned. Tables that can't be located keep page=None (honest).
    """
    pinned = 0
    for sec in sections:
        if not sec.tables or sec.page_start is None:
            continue
        lo = sec.page_start - 1
        hi = (sec.page_end or sec.page_start) - 1
        for table in sec.tables:
            by_caption = _caption_page(table, page_texts, lo, hi)
            if by_caption is not None:
                table.page = by_caption
                pinned += 1
                continue
            needles = [_squash(n) for n in _distinctive_needles(table)]
            needles = [n for n in needles if len(n) >= 2]
            best_page, best_hits = None, 0
            for p in range(lo, min(hi + 1, len(page_texts))):
                text = _squash(page_texts[p])
                hits = sum(1 for n in needles if n in text)
                if hits > best_hits:
                    best_page, best_hits = p + 1, hits
            if best_page is not None and best_hits >= 2:
                table.page = best_page
                pinned += 1
    return pinned


#: A row is pinned only on this many distinctive cells found together on one
#: page — the same bar `pin_table_pages` sets for a whole table, because a
#: single coincidental match is not evidence about where a row printed.
_ROW_MIN_HITS = 2


def _row_needles(row: list[str]) -> list[str]:
    """The cells of one row distinctive enough to locate it in page text.

    The same test `_distinctive_needles` applies to a table, read one level
    down: a value carrying digits, or a symbol carrying none. A row of `—`
    or of bare single digits yields nothing, which is the honest answer —
    such a row cannot be located and must keep its table's page.
    """
    out: list[str] = []
    for cell in row:
        c = cell.strip()
        has_digit = any(ch.isdigit() for ch in c)
        if (has_digit and len(c) >= 3 and not c.isdigit()) or (_SYMBOL.match(c) and not has_digit):
            out.append(_squash(c))
    return [n for n in out if len(n) >= 2]


def pin_table_row_pages(sections: list[SectionNode], page_texts: list[str]) -> tuple[int, int]:
    """Pin each grid row's printed page. Returns `(rows_pinned, rows_total)`.

    `TableBlock.row_pages` is real geometry on the `pdf_layout` path, and the
    HTML path has none — so every row of an HTML-derived table cited the page
    its *table* began on. Measured on LMX1204's `Table 7-1`: 1 row of 35
    (`0x5A` / `R90`) prints on page 33 and cited page 32, and the spec records
    read from it inherited the error.

    One row in thirty-five is small, and small is the dangerous size: a
    citation that is *nearly* right is the one a reader trusts without
    opening the page.

    This applies `pin_table_pages`'s rule one level down rather than inventing
    a second one — locate the row's distinctive cells in the PDF's per-page
    text — plus the structural fact that makes it safe: **a printed table
    advances one page at a time.** Rows are walked in order, and each row is
    only ever asked whether it stayed on the page the row above printed on or
    moved to the next. Searching the whole section instead is what a first
    attempt did, and it fails on exactly the row this ticket exists for:
    `0x5A` and `R90` both also appear on page 54, twenty-two pages past a
    35-row table, and the resulting tie left the row unpinned.

    **A row that cannot be located stays where the row above printed.** Not
    the nearest match anywhere in the section, not a guess: a pinning rule
    confident where it should not be turns one wrong row in thirty-five into
    an unknown number of them, which is worse than the defect it replaces.
    Rows already carrying geometry are left alone.
    """
    row_pinned = row_total = 0
    for sec in sections:
        if not sec.tables or sec.page_start is None:
            continue
        # One page past the section's recorded end. That range comes from the
        # TOC and is a *heading* boundary, not a content one: the next section
        # starts partway down a page, so a table can legitimately finish on
        # it. Measured: 12 rows of LMX1204's 6.3.6.1.1 print on the page after
        # its recorded end and cited the page before. The walk still advances
        # one page at a time and only on stronger evidence, so widening the
        # bound cannot reach a distant coincidence.
        last_page = (sec.page_end or sec.page_start) + 1
        for table in sec.tables:
            if not table.grid or table.page is None:
                continue
            if len(table.row_pages) == len(table.grid) and any(
                p is not None for p in table.row_pages
            ):
                continue  # `pdf_layout` measured these; do not overwrite
            pinned_rows: list[int | None] = []
            current = table.page
            for row in table.grid:
                row_total += 1
                needles = _row_needles(row)
                nxt = current + 1
                here = _hits(needles, page_texts, current)
                there = _hits(needles, page_texts, nxt) if nxt <= last_page else 0
                # Two distinctive cells found together is the bar, the same
                # one whole tables are pinned at. A row that prints only one
                # such cell can still turn the page on *all* of its evidence
                # — measured: LMX1204's 6.3.6.1.1 rows carry one decimal each
                # and 12 of them cited the page before the one they print on.
                bar = min(_ROW_MIN_HITS, len(needles))
                # Staying is the default; only clear evidence turns the page.
                if there >= bar and there > here:
                    current = nxt
                    row_pinned += 1
                elif here >= bar and here:
                    row_pinned += 1
                pinned_rows.append(current)
            table.row_pages = pinned_rows
    return row_pinned, row_total


def reconcile_table_pages(sections: list[SectionNode]) -> list[tuple[str, int, int]]:
    """A table's page is the page its **first row** prints on.

    Two producers answer "what page is this table on" and they can disagree.
    `pin_table_pages` searches a whole section for the table's distinctive
    cells and takes the page with the most hits — a text search over a range,
    which a neighbouring register's near-identical field table can win.
    `TableBlock.row_pages` is stronger evidence in both of the ways it is
    produced: on the `pdf_layout` path it is measured geometry, and on the
    HTML path it is a walk that advances one page at a time and only on
    strictly better evidence than staying put.

    So where they disagree, the rows win, and the table's own page becomes
    the page its first row printed on. Measured over this project's eleven
    parts: **3 tables of 158** disagreed, and all three had the table page
    wrong — `Table 1-25. R24 Register Field Descriptions` was pinned to p.17
    by the section-wide search and prints on p.19, which is where its five
    measured rows already said it was. Its bit fields cited p.17, and a bit
    field that cites the wrong page is exactly the "nearly right" citation
    `pin_table_row_pages` was written to stop.

    Returns one `(caption, was, now)` per correction, so the caller can log
    what moved instead of moving it silently.
    """
    moved: list[tuple[str, int, int]] = []
    for sec in sections:
        for table in sec.tables:
            first = next((p for p in table.row_pages if p is not None), None)
            if first is None or table.page is None or first == table.page:
                continue
            moved.append((table.caption or "(unnumbered)", table.page, first))
            table.page = first
    return moved


def _hits(needles: list[str], page_texts: list[str], page: int) -> int:
    """How many of a row's needles print on `page` (1-based)."""
    if page < 1 or page > len(page_texts):
        return 0
    text = _squash(page_texts[page - 1])
    return sum(1 for n in needles if n in text)
