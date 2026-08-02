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


def pin_table_pages(sections: list[SectionNode], page_texts: list[str]) -> int:
    """Pin each table's exact page by locating its cell values in PDF text.

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
