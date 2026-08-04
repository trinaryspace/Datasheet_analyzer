"""Vendor-neutral PDF layout backend — the guaranteed extraction floor.

`pdf_layout` converts any datasheet PDF into a corpus-grade RawDocument
fully offline (PyMuPDF only), with zero layout assumptions keyed to any
vendor. Ticket 02 is the paragraph core: furniture stripping and the
structure ladder. Ticket 03 adds tables: caption-anchored hypotheses with a
reconstruction gate (every accepted grid re-produces the region's own word
stream), so any vendor's datasheet gets atomic tables + specs.json while
captionless clusters stay paragraphs and garbage layouts yield nothing.
Footnotes/figures land in tickets 05-06.

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

Tables (caption-anchored hypotheses + reconstruction gate):
- a candidate region starts at a "Table N." caption line and runs to the
  next caption/heading/page end; rows are baseline clusters (pitch-based
  continuation merging, so wrapped cells stay one row); columns are word-x
  clusters anchored on the header row, with an all-word retry ladder for
  coarser splits; partial rulings are hints (occupancy relaxation), never
  requirements;
- numbered footnote lines detach from the region by signature; prose rows
  (confined to one band, sentence-long) drop out and stay paragraphs;
- the gate accepts only grids with >= 2 rows and >= 2 stable, tight columns
  with a tabular occupancy pattern; rejected hypotheses are recorded in
  `ExtractionStats` with reasons — the words they covered remain paragraphs;
- repeated captions (multi-page tables) merge continuations into the one
  atomic block; the test-conditions preamble above the caption attaches to
  the block; the caption page becomes the table's page.
"""

from __future__ import annotations

import itertools
import logging
import math
import re
from pathlib import Path

import fitz  # PyMuPDF

from datasheet_analyzer.extract.pdf_structure import read_toc
from datasheet_analyzer.models import (
    ExtractionStats,
    RawDocument,
    SectionNode,
    SourceDocument,
    TableBlock,
    TOCEntry,
)
from datasheet_analyzer.structure.tables import grid_csv, grid_markdown

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
    __slots__ = ("block", "spans", "text", "x", "y")

    def __init__(self, block: int, y: float, x: float, text: str,
                 spans: list[tuple[float, float, str]] | None = None):
        self.block = block
        self.y = y
        self.x = x
        self.text = text
        self.spans = spans or []    # (x0, x1, text) in reading order


class _Page:
    __slots__ = ("_path", "_rulings", "index", "is_toc_page", "lines", "text")

    def __init__(self, index: int, lines: list[_Line], text: str, path: Path):
        self.index = index          # 1-based PDF page number
        self.lines = lines          # sorted by (y, x)
        self.text = text
        self.is_toc_page = False    # set by the printed-TOC scan
        self._path = path
        self._rulings: list[tuple[float, float, float]] | None = None

    def v_rulings(self) -> list[tuple[float, float, float]]:
        """Vertical drawing lines on this page as (x, y0, y1), lazy.

        Used only as a hint: a real vertical rule relaxes the occupancy
        check (dense 2-column tables like HMC520A "Table 2." have every
        cell filled but are unmistakably tables).
        """
        if self._rulings is None:
            self._rulings = []
            try:
                with fitz.open(self._path) as doc:
                    for d in doc[self.index - 1].get_drawings():
                        r = d["rect"]
                        if 0.0 <= r.width <= 1.5 and r.height > 1.5:
                            self._rulings.append((r.x0, r.y0, r.y1))
            except Exception:  # noqa: BLE001 — honesty over crash
                log.warning("pdf_layout: drawing scan failed on page %d", self.index)
        return self._rulings


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
                    spans = [(s["bbox"][0], s["bbox"][2], s["text"])
                             for s in raw["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    text = _span_line_text(raw["spans"])
                    if not text.strip():
                        continue
                    lines.append(_Line(bi, raw["bbox"][1], raw["bbox"][0],
                                       text, spans))
            lines.sort(key=lambda ln: (ln.y, ln.x))
            pages.append(_Page(pi + 1, lines, page.get_text(), path))
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
    page: _Page, furniture: set[int], title_keys: frozenset[str],
    consumed: set[int] | None = None,
) -> list[str]:
    """Block paragraphs of one page minus furniture, minus the printed
    section headings (they are titles, not paragraphs), minus the lines of
    accepted tables (captions, preambles, grid rows — never duplicated)."""
    consumed = consumed or set()
    by_block: dict[int, list[str]] = {}
    for i, line in enumerate(page.lines):
        if i in furniture or i in consumed:
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
    pages: list[_Page], entries: list[TOCEntry], furniture: list[set[int]],
    tables: _TableExtraction | None = None,
) -> list[SectionNode]:
    title_keys = _title_keys(entries)
    ranges = _section_ranges(entries, len(pages))
    sections: list[SectionNode] = []
    attached: set[int] = set()  # a table block lands in exactly one section
    for entry, rng in zip(entries, ranges):
        if rng is None:
            continue
        start, end = rng
        paragraphs: list[str] = []
        owned_tables: list[TableBlock] = []
        for page in pages[start - 1 : end]:
            if _page_owned_by_deeper(page.index, entry, ranges, entries):
                continue
            fi = page.index - 1
            paragraphs.extend(_page_paragraphs(
                page, furniture[fi], title_keys,
                tables.consumed[fi] if tables else None))
            if not tables:
                continue
            for block in tables.by_page.get(page.index, []):
                if id(block) in attached:
                    continue
                attached.add(id(block))
                owned_tables.append(block)
        sections.append(
            SectionNode(
                number=entry.number,
                title=entry.title,
                level=entry.level,
                page_start=start,
                page_end=end,
                paragraphs=paragraphs,
                tables=owned_tables,
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


def _sections_per_page(pages: list[_Page], furniture: list[set[int]],
                       tables: _TableExtraction | None = None
                       ) -> list[SectionNode]:
    return [
        SectionNode(
            number=str(page.index),
            title=f"Page {page.index}",
            level=1,
            page_start=page.index,
            page_end=page.index,
            paragraphs=_page_paragraphs(
                page, furniture[page.index - 1], frozenset(),
                tables.consumed[page.index - 1] if tables else None),
            tables=tables.by_page.get(page.index, []) if tables else [],
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


# ---------------------------------------------------------------------------
# Tables: caption-anchored hypotheses + reconstruction gate.

# "Table 3. DAC DC Specifications", "Table 2-1 - Power Consumption", "Table 1."
_CAPTION_RE = re.compile(r"^\s*table\s+(\d+(?:[.-]\d+)*)\s*[-.:]\s*(.*)$",
                         re.IGNORECASE)

# Column anchors: the header row's words are clustered at this tolerance,
# which merges the words of one multi-word header cell ("Test Conditions/
# Comments" lands at 226.2, 235.9, 244.x) while keeping distinct columns
# apart — AD9081's Min|Typ|Max starts are 27pt apart, lm741's 36pt.
_HDR_ANCHOR_TAU = 12.0
# Retry ladder: only when the header-anchored split fails does the engine
# retry with coarser all-word clusterings (rescue over drop).
_COLUMN_TAUS = (12.0, 8.0, 19.0, 28.0, 42.0)
# Row geometry: baselines skewed up to this are one visual row (LM741 values
# sit ~1.7pt below their parameter text); a line following within this
# fraction of the row pitch wraps the same cell (AD9081 wraps at 10.8 vs
# 12.8pt pitch); a fine row confined to one band with a sentence-long cell
# is prose, never a grid row.
_BASELINE_SKEW = 2.0
_WRAP_FACTOR = 0.92
_PROSE_WORDS = 8
# Test-conditions preamble: consecutive unconsumed lines within this gap
# above the caption join the table as its conditions.
_PREAMBLE_GAP = 24.0

# Numbered footnote signatures: a marker ("1", "2", "†", glued like
# "1The values..." or spaced like "1  For dc-coupled ...") followed by a
# long sentence — detached from the grid so footnote lines never become
# rows. "6 GHz TO 10 GHz ..." is NOT one (unit-guard on the second word),
# "2.7 GHz to 3.8 GHz" is not either.
_FOOTNOTE_RE = re.compile(r"^\s*(?:\d{1,2}|[†*‡])\s*[A-Za-z]")
_UNIT_WORDS = frozenset({
    "ghz", "mhz", "khz", "hz", "dbm", "dbc", "db", "v", "mv", "kv", "uv",
    "a", "ma", "ua", "ohm", "ω", "kω", "mω", "w", "mw", "lsb", "bits",
    "s", "ms", "ns", "f", "pf", "uf", "rms", "dbfs", "sps", "msps", "gsps",
})


class _Row:
    __slots__ = ("lines", "spans", "y")

    def __init__(self, y: float):
        self.lines: list[_Line] = []
        self.y = y
        self.spans: list[tuple[float, float, str]] = []


def _group_rows(lines: list[_Line], *, wrap: bool = True) -> list[_Row]:
    """Baseline clustering: sub-baseline skew merges; wrapped continuation
    lines merge at < wrap-factor x pitch; new rows open at the pitch.

    With ``wrap=False`` only the baseline skew is merged: footnote/prose
    classification happens on these *fine* rows, because wrap-merging can
    swallow a footnote marker ("parameters." + "2 The ...") and hide it.
    """
    rows: list[_Row] = []
    for line in lines:
        if rows and line.y - rows[-1].y <= _BASELINE_SKEW:
            rows[-1].lines.append(line)
            rows[-1].spans.extend(line.spans)
            continue
        rows.append(_Row(line.y))
        rows[-1].lines.append(line)
        rows[-1].spans.extend(line.spans)
    if not wrap or len(rows) < 2:
        return rows

    gaps = [rows[i + 1].y - rows[i].y for i in range(len(rows) - 1)
            if rows[i + 1].y - rows[i].y > _BASELINE_SKEW]
    if not gaps:
        return rows
    pitch = sorted(gaps)[len(gaps) // 2]
    merged: list[_Row] = [rows[0]]
    for row in rows[1:]:
        if row.y - merged[-1].y <= max(pitch * _WRAP_FACTOR, _BASELINE_SKEW):
            merged[-1].lines.extend(row.lines)
            merged[-1].spans.extend(row.spans)
        else:
            merged.append(row)
    return merged


def _row_joined_text(row: _Row) -> str:
    return _WS.sub(" ", " ".join(ln.text for ln in row.lines)).strip()


def _is_footnote_row(row: _Row) -> bool:
    text = _row_joined_text(row)
    m = _FOOTNOTE_RE.match(text)
    if not m:
        return False
    words = text.split()
    if len(words) < 6:
        return False
    if words[1].lower() in _UNIT_WORDS:
        return False
    # a footnote is a plain sentence: its spans sit in at most two x-clusters
    # to the left of the table body. A quantity row ("2 J1, J2 (RF, LO) ...
    # 104935") starts with a number but spreads across the real columns.
    xs = sorted({round(x0, 1) for x0, _x1, _t in row.spans})
    clusters = 1 + sum(1 for a, b in itertools.pairwise(xs) if b - a > _HDR_ANCHOR_TAU)
    return clusters <= 2


def _cluster_lefts(xs: list[float], tau: float) -> list[float]:
    """Cluster x0 positions (single linkage, gap < tau) -> cluster lefts.

    Lefts stay exact floats: a rounded left (up to 0.05pt right of its own
    cluster's min) would exclude the cluster's own edge-most spans, which
    would then fall into the previous band — corrupting cell boundaries.
    """
    xs = sorted(set(xs))
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] < tau:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [min(c) for c in clusters]


def _header_bands(rows: list[_Row]) -> list[float]:
    """Column lefts anchored on the first row's word starts."""
    if not rows:
        return []
    return _cluster_lefts([x0 for x0, _x1, _t in rows[0].spans], _HDR_ANCHOR_TAU)


def _word_bands(rows: list[_Row], tau: float) -> list[float]:
    return _cluster_lefts([x0 for row in rows for x0, _x1, _t in row.spans], tau)


def _cell(span_texts: list[tuple[float, float, str]], left: float,
          right: float) -> str:
    """Join the spans whose x0 falls in [left, right), with the project's
    glue rule: sub/superscripts (next span starts right at the previous
    one's end) stay glued; a true overlap (> 0.5pt) is a separate word and
    gets a space; a real gap gets a space."""
    parts: list[str] = []
    prev_x1: float | None = None
    prev_size = 8.0
    for x0, x1, text in span_texts:
        if not (left <= x0 < right):
            continue
        if prev_x1 is not None:
            gap = x0 - prev_x1
            if gap < -0.5 or gap > 0.5 * prev_size:
                parts.append(" ")
        parts.append(text)
        prev_x1 = x1
    return _WS.sub(" ", "".join(parts)).strip()


def _row_cells(row: _Row, lefts: list[float]) -> list[str]:
    bounds = list(zip(lefts, lefts[1:] + [math.inf]))
    return [_cell(row.spans, lo, hi) for lo, hi in bounds]


def _gate(rows: list[_Row], lefts: list[float], page: _Page,
          region_y0: float, region_y1: float) -> str | None:
    """Reconstruction gate. Returns None when the grid may be accepted, else
    the rejection reason. Deterministic order; every rule is vendor-neutral.

    A grid is tabular iff it has enough rows, at least two columns that are
    stable across rows (shared x-anchors) and tight (rows start their cells
    near the band's left edge), rows that span columns, and an occupancy
    pattern that is neither scattered junk nor prose — with a vertical
    ruling hint relaxing the dense case. Every word lands in a cell by
    construction (bands are contiguous from word starts); the gate therefore
    verifies the *structure* of that reconstruction.
    """
    n = len(rows)
    if n < 2:
        return "fewer than 2 rows"
    if len(lefts) < 2:
        return "single column"

    ruled = any(
        (lefts[0] - 4.0 <= x <= lefts[-1] + 60.0)
        and y1 > region_y0 and y0 < region_y1
        for x, y0, y1 in page.v_rulings()
    )
    cells = [_row_cells(r, lefts) for r in rows]
    occ = [sum(1 for c in row if c) for row in cells]
    # Column tightness: a real column's rows start their cells near the
    # band's left edge (left-aligned cells at the edge, right-aligned ones
    # within a character width of it, since the band's left is the longest
    # cell's start); scattered first-words mean bands are spanning junk that
    # merely looks tabular.
    first_devs: list[list[float]] = [[] for _ in lefts]
    for row_spans in (r.spans for r in rows):
        for b, (lo, hi) in enumerate(zip(lefts, lefts[1:] + [math.inf])):
            for x0, _x1, _t in row_spans:
                if lo <= x0 < hi:
                    first_devs[b].append(x0 - lo)
                    break
    tight = [bool(d) and sorted(d)[len(d) // 2] <= 30.0 for d in first_devs]
    strength = [sum(1 for row in cells if row[b]) for b in range(len(lefts))]
    # a column is stable only when a real share of the rows anchor it and
    # its starts are tight; ruling evidence relaxes the share (dense ruled
    # tables like HMC "Table 2.").
    strong_needed = 2 if ruled else max(3, math.ceil(0.5 * n))
    if sum(1 for s, t in zip(strength, tight)
           if s >= strong_needed and t) < 2:
        return "columns not stable across rows"
    if sum(1 for o in occ if o >= 2) * 2 < n:
        return "rows do not span columns"

    total = n * len(lefts)
    mean_occ = (sum(occ) / total) if total else 0.0
    # A fully-packed unruled grid is not distinguishable from scattered
    # junk; the ruling hint relaxes that (dense ruled tables like HMC
    # "Table 2." or AD9081 "Table 19."). Sparse real spec tables sit at
    # ~0.5-0.7 occupancy.
    if mean_occ < 0.2 or (mean_occ > 0.9 and not ruled):
        return "occupancy pattern not tabular"
    return None


def _block_from(rows: list[_Row], lefts: list[float], caption: str,
                conditions: str, page_number: int) -> TableBlock:
    headers = _row_cells(rows[0], lefts)
    grid = [r for r in (_row_cells(r, lefts) for r in rows[1:])
            if any(c.strip() for c in r)]
    return TableBlock(
        caption=caption,
        headers=headers,
        grid=grid,
        conditions=conditions,
        markdown=grid_markdown(headers, grid),
        csv=grid_csv(headers, grid),
        page=page_number,
    )


class _AcceptedTable:
    """An accepted table + the geometry it was accepted with (continuations
    reuse the exact same columns so multi-page tables stay one atomic grid)."""

    __slots__ = ("block", "header_sig", "lefts")

    def __init__(self, block: TableBlock, lefts: list[float]):
        self.block = block
        self.lefts = lefts
        self.header_sig = _squash(" ".join(block.headers))


def _is_repeated_header(row: _Row, lefts: list[float], header_sig: str) -> bool:
    return _squash(" ".join(c for c in _row_cells(row, lefts) if c)) == header_sig


def _hypothesis(region: list[_Line], page: _Page
                ) -> tuple[list[float] | None, str | None, float,
                            list[_Line]]:
    """Score one region against the retry ladder.

    Returns (lefts, reason, fidelity, candidate): lefts is the accepted
    column geometry (or None), reason the rejection string, fidelity the
    reconstruction score of the accepted grid — the share of the region's
    words the grid reconstructs (footnote and prose rows detract honestly,
    so tables with footnotes score below 1.0), candidate the region lines
    that make up the accepted grid (footnote and prose rows never enter it;
    wrap-merging happens only afterwards, on the accepted lines).
    """
    region_words = sum(len(t.split()) for ln in region for _x0, _x1, t in ln.spans)
    fine = _group_rows(region, wrap=False)
    kept: list[_Row] = []
    for row in fine:
        if not _is_footnote_row(row):
            kept.append(row)
    if not kept:
        return None, "no rows", 0.0, []

    band_sets = [_header_bands(kept)] + [
        _word_bands(kept, tau) for tau in _COLUMN_TAUS
    ]
    y0 = min(r.y for r in kept) - 2.0
    y1 = max(r.y for r in kept) + 2.0
    keep_reason = "no viable column split"
    for lefts in band_sets:
        if len(lefts) < 2:
            continue
        # Prose rows drop out: a fine row confined to one band whose cell is
        # a sentence is text, not a grid row (footnotes already went the
        # same way). Runs on FINE rows so a wrap-merged line can never hide
        # a marker.
        cells = [_row_cells(r, lefts) for r in kept]
        candidate: list[_Row] = []
        for i, row in enumerate(kept):
            occ = [c for c in cells[i] if c]
            if len(occ) <= 1 and occ and len(occ[0].split()) > _PROSE_WORDS:
                continue
            candidate.append(row)
        lines = [ln for row in candidate for ln in row.lines]
        grid_rows = _group_rows(lines)
        if len(grid_rows) < 2:
            continue
        # the gate judges the wrap-merged grid (fragmented cells of fine
        # rows would otherwise look like non-spanning single-band rows)
        reason = _gate(grid_rows, lefts, page, y0, y1)
        if reason is None:
            grid_words = sum(len(t.split())
                             for ln in lines for _x0, _x1, t in ln.spans)
            fidelity = (grid_words / region_words) if region_words else 1.0
            return lefts, None, fidelity, lines
        keep_reason = reason
    return None, keep_reason, 0.0, []


class _TableExtraction:
    """Per-document table extraction state + statistics.

    Runs one page at a time; repeated captions (multi-page tables) merge
    their continuation rows into the first page's atomic block, reusing the
    exact column geometry the block was accepted with.
    """

    def __init__(self, pages: list[_Page]):
        self.pages = pages
        self.by_page: dict[int, list[TableBlock]] = {}
        self.consumed: list[set[int]] = [set() for _ in pages]
        self.accs: dict[tuple[str, str], _AcceptedTable] = {}
        self.detected = 0
        self.accepted = 0
        self.rejected = 0
        self.reasons: list[str] = []
        self.fidelities: list[float] = []

    def _preamble(self, page: _Page, cap_idx: int, furniture: set[int],
                  title_keys: frozenset[str], consumed: set[int]
                  ) -> tuple[list[int], str]:
        """Consecutive unconsumed lines directly above the caption: the
        test-conditions preamble that must travel with its table."""
        idxs: list[int] = []
        texts: list[str] = []
        prev_y = page.lines[cap_idx].y
        for i in range(cap_idx - 1, -1, -1):
            line = page.lines[i]
            if (i in furniture or i in consumed
                    or (title_keys and _squash(line.text) in title_keys)
                    or _CAPTION_RE.match(line.text)):
                break
            if prev_y - line.y > _PREAMBLE_GAP:
                break
            idxs.append(i)
            texts.append(line.text)
            prev_y = line.y
        return list(reversed(idxs)), " ".join(reversed(texts)).strip()

    def _consume(self, page: _Page, indices: list[int]) -> None:
        self.consumed[page.index - 1].update(indices)

    def run(self, page: _Page, furniture: set[int],
            title_keys: frozenset[str]) -> None:
        i = 0
        lines = page.lines
        while i < len(lines):
            m = _CAPTION_RE.match(lines[i].text.strip())
            if not m:
                i += 1
                continue
            key = (m.group(1), _squash(m.group(2).strip()))
            region: list[tuple[int, _Line]] = []
            j = i + 1
            while j < len(lines):
                line = lines[j]
                if (j in furniture or _CAPTION_RE.match(line.text.strip())
                        or (title_keys and _squash(line.text) in title_keys)):
                    break
                region.append((j, line))
                j += 1

            self.detected += 1
            acc = self.accs.get(key)
            if acc is not None:
                # continuation page: extend the existing atomic grid with the
                # same columns; footnotes and a repeated header row are
                # dropped by signature
                rows = _group_rows([ln for _i, ln in region], wrap=False)
                kept_ids: set[int] = set()
                for row in rows:
                    if _is_footnote_row(row):
                        continue  # footnotes stay paragraphs
                    if _is_repeated_header(row, acc.lefts, acc.header_sig):
                        kept_ids.update(id(ln) for ln in row.lines)
                        continue  # repeated header row: caption-like furniture
                    acc.block.grid.append(_row_cells(row, acc.lefts))
                    kept_ids.update(id(ln) for ln in row.lines)
                acc.block.csv = grid_csv(acc.block.headers, acc.block.grid)
                acc.block.markdown = grid_markdown(acc.block.headers, acc.block.grid)
                self._consume(page, [idx for idx, ln in region
                                     if id(ln) in kept_ids] + [i])
                self.accepted += 1
                self.fidelities.append(1.0)
                i = j
                continue

            pre_idx, conditions = self._preamble(
                page, i, furniture, title_keys, self.consumed[page.index - 1])
            region_lines = [ln for _i, ln in region]
            lefts, reason, fidelity, candidate = _hypothesis(
                region_lines, page)
            if lefts is not None:
                block = _block_from(_group_rows(candidate), lefts,
                                    lines[i].text.strip(), conditions,
                                    page.index)
                self.by_page.setdefault(page.index, []).append(block)
                self.accs[key] = _AcceptedTable(block, lefts)
                by_id = {id(ln): idx for idx, ln in region}
                consumed = [by_id[id(ln)] for ln in candidate]
                self._consume(page, consumed + pre_idx + [i])
                self.accepted += 1
                self.fidelities.append(fidelity)
            else:
                self.rejected += 1
                self.reasons.append(reason)
            i = j

    def stats(self) -> ExtractionStats:
        return ExtractionStats(
            backend="pdf_layout",
            tables_detected=self.detected,
            tables_accepted=self.accepted,
            tables_rejected=self.rejected,
            rejection_reasons=self.reasons[:8],
            mean_fidelity=(sum(self.fidelities) / len(self.fidelities)
                           if self.fidelities else 0.0),
        )


class PdfLayoutBackend:
    """Offline, vendor-neutral layout extraction (PyMuPDF only)."""

    name = "pdf_layout"
    output_version = "tables-03"

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
        tables = _TableExtraction(pages)
        title_keys = _title_keys(entries)
        for page in pages:
            tables.run(page, furniture[page.index - 1], title_keys)
        if entries:
            sections = _sections_from_entries(pages, entries, furniture, tables)
        else:
            sections = _sections_per_page(pages, furniture, tables)
        log.info(
            "pdf_layout: %d pages, %d sections, %d tables "
            "(%d detected, %d accepted, %d rejected), %d furniture lines "
            "(ladder=%s)",
            len(pages), len(sections), tables.accepted, tables.detected,
            tables.accepted, tables.rejected,
            sum(len(s) for s in furniture), ladder,
        )
        return RawDocument(
            source=source, toc=entries, sections=sections,
            extractor=self.name, extractor_version=self.output_version,
            extraction_stats=tables.stats(),
        )
