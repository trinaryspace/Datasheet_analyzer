"""Vendor-neutral PDF layout backend — the guaranteed extraction floor.

`pdf_layout` converts any datasheet PDF into a corpus-grade RawDocument
fully offline (PyMuPDF only), with zero layout assumptions keyed to any
vendor. Ticket 02 is the paragraph core: furniture stripping, the structure
ladder, and page-ranged sections. Tables/footnotes/figures land in tickets
03-06; until then paragraphs honestly carry the page's flat text.

Furniture rule (no vendor strings, by design):
- a *slot* is a y-window that recurs on enough pages (>= 40%, at least 2);
- a line in a recurring slot is furniture iff its text is constant there
  (the same text at the same y-window on enough pages) or it matches a
  universal page-machinery pattern: "N of M", "Page N [of M]", "Rev. +token"
  or a bare page number that equals the page's own index;
- the page's printed section heading is dropped from its own paragraph
  stream (the heading is the section title, not a paragraph), and nothing
  else — a furniture-free PDF keeps every line.

Structure ladder (citations right whatever the PDF's era):
1. PDF outline (bookmarks) — titles keep printed numbers, stay "" otherwise
   (never fabricated);
2. generic printed-TOC dot-leader parse (indentation = hierarchy), with a
   small deterministic delta search for printed-vs-PDF page offsets
   (failure keeps parsed values + a warning);
3. neither -> one "Page N" section per page (pdf_text honesty).
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path

import fitz  # PyMuPDF

from datasheet_analyzer.extract.pdf_structure import read_toc
from datasheet_analyzer.models import RawDocument, SectionNode, SourceDocument, TOCEntry

log = logging.getLogger(__name__)

# Furniture geometry: a slot is a y-window of this width (pt) recurring on
# at least these fractions/amounts of pages.
_BUCKET = 15.0
_MIN_PAGES_FRAC = 0.4
_MIN_PAGES = 2

_WS = re.compile(r"\s+")
_NONALNUM = re.compile(r"[^a-z0-9]+")

# Universal page-machinery patterns — deliberately anchored to the whole
# line so mid-prose mentions ("see Rev. B text", "2 of 45 units") survive.
_N_OF_M = re.compile(
    r"^\s*(?:rev\.?\s+[a-z0-9][^|\n]*\s*[|·•]?\s*)?[-–—]?\s*\d+\s+of\s+\d+\s*[-–—]?\s*$",
    re.IGNORECASE,
)
_PAGE_OF = re.compile(
    r"^\s*(?:rev\.?\s+[a-z0-9]\s*[|·•]\s*)?page\s+\d+(?:\s+of\s+\d+)?\s*$",
    re.IGNORECASE,
)
_REV_BARE = re.compile(r"^\s*rev\.?\s*[.|×: ]*\s*[a-z0-9]\s*$", re.IGNORECASE)

# Printed-TOC dot-leader line: "1 Features ............. 3"
_DOT_ENTRY = re.compile(r"^\s*(?:(\d+(?:\.\d+)*)\s+)?(.+?)[\s\u00a0.·•]*\.{2,}\s*(\d+)\s*$")


def _squash(text: str) -> str:
    return _NONALNUM.sub("", _WS.sub(" ", text).lower())


def _span_line_text(spans: list[dict]) -> str:
    """Join spans with a glue rule: no space when the next span starts
    right at the previous one's end (sub/superscripts), else a space —
    mirrors the project's glued-sub/superscript convention."""
    parts: list[str] = []
    prev_x1: float | None = None
    prev_size = 0.0
    for sp in spans:
        text = sp["text"]
        if not text:
            continue
        if prev_x1 is not None and sp["bbox"][0] - prev_x1 > 0.5 * prev_size:
            parts.append(" ")
        parts.append(text)
        prev_x1 = sp["bbox"][2]
        prev_size = sp["size"]
    return _WS.sub(" ", "".join(parts)).strip()


class _Line:
    __slots__ = ("block", "text", "x", "y")

    def __init__(self, block: int, y: float, x: float, text: str):
        self.block = block
        self.y = y
        self.x = x
        self.text = text


class _Page:
    __slots__ = ("index", "is_toc_page", "lines", "text")

    def __init__(self, index: int, lines: list[_Line], text: str):
        self.index = index          # 1-based PDF page number
        self.lines = lines
        self.text = text
        self.is_toc_page = False    # set by the printed-TOC scan


def _load_pages(path: Path) -> list[_Page]:
    pages: list[_Page] = []
    with fitz.open(path) as doc:
        for pi in range(doc.page_count):
            page = doc[pi]
            lines: list[_Line] = []
            for bi, block in enumerate(page.get_text("dict")["blocks"]):
                if block.get("type") != 0:
                    continue
                for raw in block["lines"]:
                    text = _span_line_text(raw["spans"])
                    if not text:
                        continue
                    lines.append(_Line(bi, raw["bbox"][1], raw["bbox"][0], text))
            pages.append(_Page(pi + 1, lines, page.get_text()))
    return pages


def _band_key(y: float) -> int:
    return math.floor(y / _BUCKET)


def _threshold(n_pages: int) -> int:
    return max(_MIN_PAGES, math.ceil(_MIN_PAGES_FRAC * n_pages))


def _matches_pattern(text: str, page_index: int) -> bool:
    return bool(
        _N_OF_M.match(text)
        or _PAGE_OF.match(text)
        or _REV_BARE.match(text)
        or (text.isdigit() and int(text) == page_index)
    )


def _furniture_sets(pages: list[_Page]) -> list[set[int]]:
    """Per-page sets of furniture line indices (recurrence + constants +
    universal patterns; a line must sit in a recurring y-slot to qualify)."""
    n = len(pages)
    threshold = _threshold(n)
    band_pages: dict[int, set[int]] = {}
    text_at_band: dict[tuple[int, str], set[int]] = {}
    for page in pages:
        for line in page.lines:
            key = _band_key(line.y)
            band_pages.setdefault(key, set()).add(page.index)
            text_at_band.setdefault((key, line.text), set()).add(page.index)

    recurring: set[int] = set()
    for key, own in band_pages.items():
        window = own | band_pages.get(key - 1, set()) | band_pages.get(key + 1, set())
        if len(window) >= threshold:
            recurring.add(key)

    out: list[set[int]] = [set() for _ in pages]
    for page in pages:
        for i, line in enumerate(page.lines):
            key = _band_key(line.y)
            if key not in recurring:
                continue
            if _matches_pattern(line.text, page.index):
                out[page.index - 1].add(i)
                continue
            same_text = set()
            for k in (key - 1, key, key + 1):
                same_text |= text_at_band.get((k, line.text), set())
            if len(same_text) >= threshold:
                out[page.index - 1].add(i)
    return out


def _title_keys(entries: list[TOCEntry]) -> frozenset[str]:
    """Squashed printed-heading forms for every section — headings are the
    section titles, never paragraphs, wherever they print."""
    keys: set[str] = set()
    for entry in entries:
        keys.add(_squash(entry.title))
        if entry.number:
            keys.add(_squash(f"{entry.number} {entry.title}"))
    return frozenset(keys)


def _page_paragraphs(
    page: _Page, furniture: set[int], title_keys: frozenset[str]
) -> list[str]:
    """Block paragraphs of one page minus furniture, minus the printed
    section headings (they are titles, not paragraphs)."""
    by_block: dict[int, list[str]] = {}
    for i, line in enumerate(page.lines):
        if i in furniture:
            continue
        if title_keys and _squash(line.text) in title_keys:
            continue
        by_block.setdefault(line.block, []).append(line.text)
    return [" ".join(parts) for parts in by_block.values() if parts]


def _section_ranges(entries: list[TOCEntry], n_pages: int) -> list[tuple[int, int] | None]:
    """A section spans from its own page to the page before the next entry
    at the same-or-higher level (pdf_text semantics), clamped to the doc."""
    ranges: list[tuple[int, int] | None] = []
    for i, entry in enumerate(entries):
        if entry.page is None:
            ranges.append(None)
            continue
        start = max(1, min(entry.page, n_pages))
        end = n_pages
        for later in entries[i + 1 :]:
            if later.page is not None and later.level <= entry.level:
                end = later.page - 1
                break
        end = max(start, min(end, n_pages))
        ranges.append((start, end))
    return ranges


def _page_owned_by_deeper(
    page_idx: int, entry: TOCEntry, ranges: list[tuple[int, int] | None],
    entries: list[TOCEntry],
) -> bool:
    """True when a strictly deeper section also covers this page — then the
    deeper section owns the page's words (parents never duplicate children;
    equally-nested siblings sharing a page keep it, as printed)."""
    for later, rng in zip(entries, ranges):
        if (
            rng is not None
            and later.level > entry.level
            and rng[0] <= page_idx <= rng[1]
        ):
            return True
    return False


def _sections_from_entries(
    pages: list[_Page], entries: list[TOCEntry], furniture: list[set[int]]
) -> list[SectionNode]:
    title_keys = _title_keys(entries)
    ranges = _section_ranges(entries, len(pages))
    sections: list[SectionNode] = []
    for entry, rng in zip(entries, ranges):
        if rng is None:
            continue
        start, end = rng
        paragraphs: list[str] = []
        for page in pages[start - 1 : end]:
            if _page_owned_by_deeper(page.index, entry, ranges, entries):
                continue
            paragraphs.extend(_page_paragraphs(page, furniture[page.index - 1], title_keys))
        sections.append(
            SectionNode(
                number=entry.number,
                title=entry.title,
                level=entry.level,
                page_start=start,
                page_end=end,
                paragraphs=paragraphs,
            )
        )
    return sections


def _cross_validate_outline(pages: list[_Page], entries: list[TOCEntry]) -> None:
    """When outline AND printed TOC both exist: warn about titles the printed
    TOC promises that the outline lacks (the outline wins either way)."""
    printed = parse_printed_toc(pages)
    if not printed:
        return
    outline_titles = {_squash(e.title) for e in entries if e.title}
    missing = sorted({_squash(e.title) for e in printed} - outline_titles)
    if missing:
        log.warning(
            "outline/printed-TOC discrepancy: %d printed title(s) absent from "
            "the outline (e.g. %r) — outline wins",
            len(missing), missing[:3],
        )
    else:
        log.info("outline and printed TOC agree (%d titles)", len(printed))


def _sections_per_page(pages: list[_Page], furniture: list[set[int]]) -> list[SectionNode]:
    return [
        SectionNode(
            number=str(page.index),
            title=f"Page {page.index}",
            level=1,
            page_start=page.index,
            page_end=page.index,
            paragraphs=_page_paragraphs(page, furniture[page.index - 1], frozenset()),
        )
        for page in pages
    ]


def parse_printed_toc(pages: list[_Page]) -> list[TOCEntry]:
    """Generic dot-leader TOC parse (bookmark-less PDFs, e.g. Qorvo-era).
    Dot leaders + trailing page number, indentation = hierarchy, numbers
    taken only when printed."""
    rows: list[tuple[float, str, str, int]] = []
    scan = pages[: min(6, len(pages))]
    for page in scan:
        found = []
        for line in page.lines:
            m = _DOT_ENTRY.match(line.text)
            if not m:
                continue
            title = m.group(2).strip()
            if len(title) < 3:
                continue
            found.append((line.x, m.group(1) or "", title, int(m.group(3))))
        if len(found) >= 3:
            page.is_toc_page = True
            rows.extend(found)
    if not rows:
        return []

    xs = sorted({round(x) for x, _, _, _ in rows})
    rank = {x: i + 1 for i, x in enumerate(xs)}
    delta = _best_delta(rows, pages)
    if delta is None:
        # dot-leader lines whose page numbers map to nothing are revision
        # notes, not a TOC (e.g. "Changes to Table 1 .... 3")
        log.warning(
            "dot-leader lines found but page numbers map to no matching "
            "content — not treating them as a printed TOC"
        )
        return []
    entries = [
        TOCEntry(
            number=number,
            title=title,
            level=rank[round(x)],
            page=max(1, min(len(pages), printed + delta)),
        )
        for x, number, title, printed in rows
    ]
    log.info("printed-TOC parse: %d entries, page delta %d", len(entries), delta)
    return entries


def _best_delta(rows: list[tuple[float, str, str, int]], pages: list[_Page]) -> int | None:
    """Printed page numbers -> PDF pages: pick delta in {-2..+2} maximizing
    title matches on the mapped pages (TOC pages themselves excluded).
    Ties prefer 0; zero matches means this is revision-history dot-leader
    text, not a TOC — return None (the parse then degrades honestly)."""
    n = len(pages)
    best_delta, best_hits = 0, -1
    for delta in (0, 1, -1, 2, -2):
        hits = 0
        for _x, _number, title, printed in rows:
            target = printed + delta
            if not (1 <= target <= n) or pages[target - 1].is_toc_page:
                continue
            if _squash(title) in _squash(pages[target - 1].text):
                hits += 1
        if hits > best_hits:
            best_delta, best_hits = delta, hits
    if best_hits == 0:
        return None
    return best_delta


class PdfLayoutBackend:
    """Offline, vendor-neutral layout extraction (PyMuPDF only)."""

    name = "pdf_layout"

    def is_available(self) -> tuple[bool, str]:
        try:
            import fitz  # noqa: F401
            return True, ""
        except ImportError as exc:
            return False, str(exc)

    def extract(
        self,
        source: SourceDocument,
        *,
        pdf_toc: list[TOCEntry] | None = None,
    ) -> RawDocument:
        pages = _load_pages(Path(source.path))
        entries = list(pdf_toc) if pdf_toc is not None else read_toc(Path(source.path))
        ladder = "outline"
        if not entries:
            entries = parse_printed_toc(pages)
            ladder = "printed_toc" if entries else "per_page"
        else:
            _cross_validate_outline(pages, entries)
        furniture = _furniture_sets(pages)
        if entries:
            sections = _sections_from_entries(pages, entries, furniture)
        else:
            sections = _sections_per_page(pages, furniture)
        log.info(
            "pdf_layout: %d pages, %d sections, %d furniture lines (ladder=%s)",
            len(pages), len(sections),
            sum(len(s) for s in furniture), ladder,
        )
        return RawDocument(source=source, toc=entries, sections=sections,
                           extractor=self.name)
