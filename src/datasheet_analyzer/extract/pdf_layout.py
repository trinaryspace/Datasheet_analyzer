"""Vendor-neutral PDF layout backend — the guaranteed extraction floor.

`pdf_layout` converts any datasheet PDF into a corpus-grade RawDocument
fully offline (PyMuPDF only), with zero layout assumptions keyed to any
vendor. Ticket 02 is the paragraph core: furniture stripping and the
structure ladder. Ticket 03 adds tables: caption-anchored hypotheses with a
reconstruction gate (every accepted grid re-produces the region's own word
stream), so any vendor's datasheet gets atomic tables + specs.json while
captionless clusters stay paragraphs and garbage layouts yield nothing.
Ticket 05 adds the remaining content kinds: table footnotes (superscript
markers from span font geometry, trailing numbered lines attached with
bare-canonical markers + positional marker-less attach) and figures
("Figure N." captions cataloged as FigureRefs and clip-rendered by the
publisher from the vector region above the caption).

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

Tables (caption-anchored hypotheses + best-scoring retry ladder):
- a candidate region starts at a "Table N." caption line and runs to the
  next caption/heading/page end; rows are baseline clusters (pitch-based
  continuation merging, so wrapped cells stay one row); columns are word-x
  clusters anchored on the header row, with an all-word retry ladder for
  coarser splits; partial rulings are hints (occupancy relaxation), never
  requirements;
- every band set is gated and scored: the best reconstruction-scoring grid
  wins — the score is the share of header-anchored column edges the
  candidate's own band edges reproduce, so a split that merges the
  header's declared columns never outvotes the grid the header declares
  (ties keep ladder order); the winner's measured word fidelity lands in
  `ExtractionStats` as mean_fidelity;
- (ticket 05) numbered footnote lines detach from the region as Footnote
  bodies attached to the block: superscript citation markers detected from
  span geometry (small, raised, glued spans land in `cited_markers`);
  wrapped footnote continuations merge into the open footnote; marker-less
  bodies attach positionally to the table directly above them; prose rows
  (confined to one band, sentence-long) drop out and stay paragraphs;
- every "Figure N." caption becomes a FigureRef (caption line consumed, the
  caption ends any table region above it) and the publisher clip-renders
  the vector region above the caption via `figure_anchor_map`;
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
    FigureRef,
    Footnote,
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


def _span_line_text(spans: list) -> str:
    """Join spans with a glue rule: no space when the next span starts
    right at the previous one's end (sub/superscripts), else a space —
    mirrors the project's glued-sub/superscript convention. Accepts both
    dict-mode spans and the engine's own ``_Span`` objects."""
    parts: list[str] = []
    prev_x1: float | None = None
    prev_size = 0.0
    for sp in spans:
        if isinstance(sp, _Span):
            text, x0, x1, size = sp.text, sp.x0, sp.x1, sp.size
        else:
            text, x0, x1, size = sp["text"], sp["bbox"][0], sp["bbox"][2], sp["size"]
        if not text:
            continue
        if prev_x1 is not None and x0 - prev_x1 > 0.5 * prev_size:
            parts.append(" ")
        parts.append(text)
        prev_x1 = x1
        prev_size = size
    return _WS.sub(" ", "".join(parts)).strip()


class _Span:
    """One text span of a line, with the font geometry ticket 05 needs.

    ``size`` is the span's font size — a superscript marker is a small
    span (measured ≤ 0.75× the line's size on AD9081/HMC520A) whose glyph
    box sits above the line's vertical middle; ``y0``/``y1`` are that box's
    top/bottom. ``x0``/``x1`` are the span's exact extents — never rounded
    (see ``_cluster_lefts``).
    """

    __slots__ = ("size", "text", "x0", "x1", "y0", "y1")

    def __init__(self, x0: float, x1: float, y0: float, y1: float,
                 size: float, text: str):
        self.x0 = x0
        self.x1 = x1
        self.y0 = y0
        self.y1 = y1
        self.size = size
        self.text = text


class _Line:
    __slots__ = ("block", "spans", "text", "x", "y")

    def __init__(self, block: int, y: float, x: float, text: str,
                 spans: list[_Span] | None = None):
        self.block = block
        self.y = y
        self.x = x
        self.text = text
        self.spans = spans or []    # in reading order


class _Page:
    __slots__ = ("_boxes", "_path", "_rulings", "index", "is_toc_page",
                 "lines", "text")

    def __init__(self, index: int, lines: list[_Line], text: str, path: Path):
        self.index = index          # 1-based PDF page number
        self.lines = lines          # sorted by (y, x)
        self.text = text
        self.is_toc_page = False    # set by the printed-TOC scan
        self._path = path
        self._rulings: list[tuple[float, float, float]] | None = None
        self._boxes: list[tuple[float, float, float, float]] | None = None

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

    def boxes(self) -> list[tuple[float, float, float, float]]:
        """All drawing rects on this page as (x0, y0, x1, y1), lazy.

        Ticket 09's title-anchored figure hypothesis reads drawn structure:
        a figure title sits inside a small emphasis band with a large
        content rect directly below (measured on QPA1003P: 16-18 pt heading
        bands over 187-232 pt diagram/plot boxes)."""
        if self._boxes is None:
            self._boxes = []
            try:
                with fitz.open(self._path) as doc:
                    for d in doc[self.index - 1].get_drawings():
                        r = d["rect"]
                        if r.width > 1.0 and r.height > 1.0:
                            self._boxes.append((r.x0, r.y0, r.x1, r.y1))
            except Exception:  # noqa: BLE001 — honesty over crash
                log.warning("pdf_layout: box scan failed on page %d", self.index)
        return self._boxes


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
                    spans = [
                        _Span(s["bbox"][0], s["bbox"][2], s["bbox"][1], s["bbox"][3],
                              s["size"], s["text"])
                        for s in raw["spans"]
                        if s["text"].strip()
                    ]
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


def _matches_pattern(text: str, page_index: int, x: float = 0.0,
                     y: float = 0.0) -> bool:
    """Universal page-machinery patterns, plus the bare page number when it
    prints in the page's own number gutters (x < 80 pt or the footer band)
    — the LM741 prints values that equal the page index in its tables
    (measured: p5's '5' max column), and a mid-body digit is data, never
    furniture."""
    return bool(
        _N_OF_M.match(text)
        or _PAGE_OF.match(text)
        or _REV_BARE.match(text)
        or (text.isdigit() and int(text) == page_index
            and (x < 80.0 or y > 700.0))
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
            if _matches_pattern(line.text, page.index, line.x, line.y):
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
    figures: _FigureExtraction | None = None,
) -> list[SectionNode]:
    title_keys = _title_keys(entries)
    ranges = _section_ranges(entries, len(pages))
    sections: list[SectionNode] = []
    attached: set[int] = set()  # a table block lands in exactly one section
    attached_figs: set[int] = set()  # a figure lands in exactly one section
    for entry, rng in zip(entries, ranges):
        if rng is None:
            continue
        start, end = rng
        paragraphs: list[str] = []
        owned_tables: list[TableBlock] = []
        owned_figures: list[FigureRef] = []
        for page in pages[start - 1 : end]:
            if _page_owned_by_deeper(page.index, entry, ranges, entries):
                continue
            fi = page.index - 1
            consumed = (tables.consumed[fi] if tables else set()) \
                | (figures.consumed[fi] if figures else set())
            paragraphs.extend(_page_paragraphs(
                page, furniture[fi], title_keys, consumed))
            if tables:
                for block in tables.by_page.get(page.index, []):
                    if id(block) in attached:
                        continue
                    attached.add(id(block))
                    owned_tables.append(block)
            if figures:
                for ref in figures.by_page.get(page.index, []):
                    if id(ref) in attached_figs:
                        continue
                    attached_figs.add(id(ref))
                    owned_figures.append(ref)
        sections.append(
            SectionNode(
                number=entry.number,
                title=entry.title,
                level=entry.level,
                page_start=start,
                page_end=end,
                paragraphs=paragraphs,
                tables=owned_tables,
                figures=owned_figures,
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
                       tables: _TableExtraction | None = None,
                       figures: _FigureExtraction | None = None
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
                (tables.consumed[page.index - 1] if tables else set())
                | (figures.consumed[page.index - 1] if figures else set())),
            tables=tables.by_page.get(page.index, []) if tables else [],
            figures=figures.by_page.get(page.index, []) if figures else [],
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

# "Figure 5. Pin Configuration" / "Figure 1." — the dot/colon right after
# the number is REQUIRED, so prose references ("the waveforms in Figure 2
# show ...", "Figure 83 shows the typical ...") never become figures.
_FIGURE_CAPTION_RE = re.compile(
    r"^\s*figure\s+(\d+(?:[.-]\d+)*[a-z]?)\s*[.:]\s*(.*)$", re.IGNORECASE)
# Region-above geometry: the next figure's clip starts below the previous
# caption's text box (caption line box + descender room).
_FIGURE_MARGIN = 12.0

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

# Numbered footnote signatures: a marker ("1", "2", "†"; glued like
# "1Reference...", punctuated like "1. NIC ..."/"(1) Status:", or spaced
# like "1  For dc-coupled ...") followed by a long sentence — detached from
# the grid so footnote lines never become rows. "6 GHz TO 10 GHz ..." is NOT
# one (unit-guard on the second word), "2.7 GHz to 3.8 GHz" is not either.
_FOOTNOTE_RE = re.compile(
    r"^\s*(?:\(\d{1,2}\)|[†*‡§#]|\d{1,2}[.)]?)\s*[A-Za-z]"
)
# The bare-canonical marker of a matched footnote row: "(1)" and "1." both
# become "1", matching the superscript citation form printed in cells.
_FOOTNOTE_MARKER_RE = re.compile(
    r"^\s*(\(?\d{1,2}\)?|[†*‡§#])[.)]?\s*(.*)$"
)
# A superscript citation marker span: bare digits or a symbol — real markers
# measured on AD9081/HMC520A are 0.61-0.75x the line's size on a raised
# baseline ("AC Coupling2"). Chemical subscripts ("f0") sit below the row's
# middle and are rejected by geometry; a "10^6"-style exponent is
# geometrically identical to a glued marker and lands in cited_markers as an
# audit-level orphan (recorded in KNOWN_SHORTCOMINGS.md).
_MARKER_TEXT_RE = re.compile(r"^\d{1,2}$|^[†*‡§#]$")
_MARKER_SIZE_RATIO = 0.82
# Trailing footnotes: the first attached line sits within this of the grid's
# last row (measured 12-26 pt on AD9081/HMC520A); continuations then follow
# at the wrap threshold of the table's own pitch.
_FOOTNOTE_GAP = 28.0
# Rowspan materialization (ticket 09): an empty parameter cell inherits the
# nearest anchor by baseline distance; this epsilon keeps exact-distance
# ties (measured 12.8 pt above and below on AD9081 p5) on the anchor printed
# above the empty row.
_ROW_ANCHOR_TIE = 0.01
# Heading-anchored table hypothesis (ticket 09, SPEC story 10): a region
# under a printed section heading is hypothesized exactly like a captioned
# region — the same ladder, gate and honesty rules decide. A heading is an
# anchor when its printed line matches a section title key OR its spans are
# heading-sized (measured: LM741 body headings 11.0 pt, QPA1003P 14.04 pt,
# and HMC520A's 10.98 pt table sub-labels must NOT fire the anchor).
_HEADING_SIZE = 11.0
# Captionless-era tables carry a real header row — measured on every gate
# part: LM741's 'MIN MAX UNIT' / 'PARAMETER TEST CONDITIONS MIN TYP MAX
# UNIT' / 'THERMAL METRIC(1) ... UNIT', QPA1003P's 'Parameter Value /
# Range' / 'Parameter Min Typ Max Units'. The prose sections and plot-axis
# labels that would otherwise reconstruct as ragged grids have none, so a
# heading-anchored region whose first row carries no parameter-header token
# stays honestly a paragraph (SPEC story 10's rejection gate).
_HEADER_TOKENS = frozenset({
    "min", "max", "typ", "tpy", "nom",
    "unit", "units", "value", "values", "valuerange", "parameter",
    "rating", "ratings",
    "testconditions", "testcondition", "thermal", "thermalmetric",
    "partno", "partnumber",
})
# The side-by-side fallback: when a heading-anchored region fails the gate,
# and its header row's word clusters show one inter-group gap this wide
# (measured 106 pt between QPA1003P's side-by-side Absolute Maximum Ratings
# and Recommended Operating Conditions — vs LM741's widest legit intra-table
# gap of ~120 pt between its own far-apart columns), the region is split at
# that gap and each side is hypothesized as its own table.
_SPLIT_GAP = 90.0
# Lateral-uniformity rule in the gate: a band whose cell starts cluster into
# two groups tens of points apart fuses two side-by-side columns (measured
# 78 pt in QPA1003P's fused pair vs < 25 pt spread inside any real column).
_SUB_COLUMN_GAP = 60.0
# Title-anchored figure hypothesis (ticket 09): a figure title is a
# heading-sized line that sits inside a drawn heading band, with the band's
# own large rect (≥ this size) or vector content directly below. Measured:
# QPA1003P's headings print inside 16-18 pt emphasis bands over 170-232 pt
# diagram/plot boxes; prose headings ('Product Features', 'Applications')
# sit outside any band and never fire.
_TITLE_SIZE = 13.0
_TITLE_BAND_H_MIN = 10.0
_TITLE_RECT_MIN = 25.0
# The figure title's emphasis band may be followed by a small gap before the
# drawn content (measured 6.5 pt on QPA1003P p1); the region scan counts
# rects that start within this window of the band's bottom.
_TITLE_CONTENT_GAP = 20.0
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
        self.spans: list[_Span] = []


def _row_pitch(rows: list[_Row]) -> float | None:
    """The row pitch of a baseline-clustered set: median gap of consecutive
    fine rows (skew-merged pairs excluded), None when there is no spread."""
    gaps = [rows[i + 1].y - rows[i].y for i in range(len(rows) - 1)
            if rows[i + 1].y - rows[i].y > _BASELINE_SKEW]
    if not gaps:
        return None
    return sorted(gaps)[len(gaps) // 2]


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

    pitch = _row_pitch(rows)
    if pitch is None:
        return rows
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
    return _cluster_count(row) <= 2


def _row_markers(row: _Row) -> list[str]:
    """Superscript citation markers in a row's spans, in reading order.

    A marker span is a bare digit run or symbol, far smaller than the row's
    biggest span (measured 0.61-0.75x on AD9081/HMC520A), glued to the
    previous span, and raised — its glyph box center sits above the row's
    vertical middle, so subscript chemistry ("f0") never cites. A "10^6"
    exponent is geometrically identical to a glued marker (measured) and
    lands in ``cited_markers`` as an audit-level orphan; real markers glued
    after digits ("29001", "× 0.8142") keep their citation.
    """
    if len(row.spans) < 2:
        return []
    max_size = max(s.size for s in row.spans)
    top = min(s.y0 for s in row.spans)
    bottom = max(s.y1 for s in row.spans)
    mid = (top + bottom) / 2.0
    out: list[str] = []
    for i, s in enumerate(row.spans[1:], 1):
        if not _MARKER_TEXT_RE.match(s.text):
            continue
        if s.size > _MARKER_SIZE_RATIO * max_size or max_size - s.size < 1.0:
            continue
        if (s.y0 + s.y1) / 2.0 >= mid:  # subscript, not a citation
            continue
        prev = row.spans[i - 1]
        if s.x0 - prev.x1 > 2.5:       # a spaced word, not a glued marker
            continue
        out.append(s.text)
    return out


def _footnote_marker_and_text(text: str) -> tuple[str, str]:
    """Bare-canonical marker + body of a footnote row: "(1) Status: ...",
    "1. NIC ...", "1Reference..." and "2 The actual ..." all give marker
    "2"/"1" and the body without the prefix."""
    m = _FOOTNOTE_MARKER_RE.match(text)
    marker, body = m.group(1), m.group(2).strip()
    return marker.strip("()"), body


def _footnote_prose_like(row: _Row) -> bool:
    """A marker-less footnote body: a real sentence. Headings ("NOTES", "6 GHZ
    TO 10 GHZ ...") are never footnote bodies."""
    text = _row_joined_text(row)
    if len(text.split()) < 4:
        return False
    letters = "".join(ch for ch in text if ch.isalpha())
    return not (letters and letters.upper() == letters)


def _cluster_count(row: _Row) -> int:
    """How many x-clusters a row's spans touch. Multi-band rows are grid
    data; footnote bodies and their wrapped continuations are single-band,
    and a footnote's sentence must not spread across the table's columns.

    The cluster boundary is the *inter-span* gap (next span's start minus
    the previous span's end), not the start-to-start distance: a span
    covers several words (measured: TI printers emit one span per few
    words), so consecutive spans of one sentence sit ~2.4 pt apart while
    their starts diverge by the span's own width — start-to-start
    clustering would read every footnote line as multi-column (LM741's
    '(N)' notes measure 6-10 such false columns)."""
    spans = sorted(row.spans, key=lambda s: s.x0)
    clusters = 1
    for a, b in itertools.pairwise(spans):
        if b.x0 - a.x1 > _HDR_ANCHOR_TAU:
            clusters += 1
    return clusters


def _row_band_count(row: _Row) -> int:
    """How many x-clusters a row touches (alias used by the footnote
    scan's grid-end rule, where "multi-band" means grid data)."""
    return _cluster_count(row)


def _scan_table_footnotes(rows: list[_Row], grid_end_y: float,
                          pitch: float | None) -> tuple[list[Footnote], list[_Row]]:
    """Trailing lines below the accepted grid -> enumerated Footnote bodies.

    ``grid_end_y`` is the last row that *spans* column bands — wrapped
    footnote continuations are single-band rows below it that belong to the
    footnote block, not to the grid (AD9081 page 5: "...maximum full-scale
    output" + "current is limited by ..." underneath the grid).

    Rules, deterministic and vendor-neutral:
    - the whole trailing block is positional: its first row — marker-prefixed
      or not — must sit within ``_FOOTNOTE_GAP`` of the grid's last row, and
      each further row within the same window of the last attached one, so a
      numbered line far below the table never gets claimed by it;
    - a marker-prefixed row (bare-canonical marker) opens a footnote;
    - a marker-less first row reads as a sentence and attaches positionally
      (the ticket's positional attach);
    - continuation rows (single-band, non-marker) within the table's own
      wrap threshold join the open footnote (multi-line bodies merge);
    - a multi-band row after the grid end means the grid itself continues —
      the block is over (honest stop);
    - anything else ends the block — those lines stay honest paragraphs
      (test-conditions notes below a marked block, "Stresses at or above..."
      warnings, distant prose).

    Returns (footnotes, attached rows); the caller consumes the attached
    rows and excludes them from the grid so the block is never duplicated.
    """
    cont_th = max((pitch or 0.0) * _WRAP_FACTOR, _BASELINE_SKEW)
    out: list[Footnote] = []
    attached: list[_Row] = []
    open_fn: Footnote | None = None
    for row in rows:
        if row.y <= grid_end_y:
            continue
        text = _row_joined_text(row)
        if open_fn is not None and row.y - attached[-1].y > _FOOTNOTE_GAP:
            break  # a row beyond the positional window ends the block
        if _is_footnote_row(row):
            marker, body = _footnote_marker_and_text(text)
            open_fn = Footnote(marker=marker, text=body)
            out.append(open_fn)
            attached.append(row)
            continue
        if _row_band_count(row) > 1:
            break  # the grid itself continues after the trailing block
        if open_fn is None:
            if row.y - grid_end_y > _FOOTNOTE_GAP:
                break
            if not _footnote_prose_like(row):
                continue
            open_fn = Footnote(marker="", text=text)
            out.append(open_fn)
            attached.append(row)
            continue
        if row.y - attached[-1].y > cont_th:
            break
        open_fn.text += " " + text
        attached.append(row)
    return out, attached


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
    return _cluster_lefts([s.x0 for s in rows[0].spans], _HDR_ANCHOR_TAU)


def _word_bands(rows: list[_Row], tau: float) -> list[float]:
    return _cluster_lefts([s.x0 for row in rows for s in row.spans], tau)


def _cell(span_texts: list[_Span], left: float,
          right: float) -> str:
    """Join the spans whose x0 falls in [left, right), with the project's
    glue rule: sub/superscripts (next span starts right at the previous
    one's end) stay glued; a true overlap (> 0.5pt) is a separate word and
    gets a space; a real gap gets a space."""
    parts: list[str] = []
    prev_x1: float | None = None
    prev_size = 8.0
    for s in span_texts:
        if not (left <= s.x0 < right):
            continue
        if prev_x1 is not None:
            gap = s.x0 - prev_x1
            if gap < -0.5 or gap > 0.5 * prev_size:
                parts.append(" ")
        parts.append(s.text)
        prev_x1 = s.x1
        prev_size = s.size
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

    # (ticket 09) Reconstruction completeness: every word of a grid row must
    # fall inside some band — the bands tile from lefts[0] to +inf, so any
    # span left of the first band is a word the grid would silently drop.
    # LM741's MIN/MAX/UNIT-only header would otherwise strand the whole
    # parameter column outside the bands while still passing occupancy.
    for row in rows:
        if any(s.x0 < lefts[0] for s in row.spans):
            return "words fall outside the column bands"

    # (ticket 09) Lateral uniformity: a band whose cell starts cluster into
    # two groups far apart fuses two side-by-side columns (QPA1003P's pair of
    # 2-column tables would otherwise fuse into a 4-column grid with two
    # stable columns). The fusion is judged per row — a *row* carrying
    # starts tens of points apart inside one band means the band holds two
    # columns; a wide column whose rows simply start at different offsets
    # (LM741's conditions column spans 120 pt) never trips it. Glued
    # superscript citation markers sit inside their cell by geometry
    # (measured "AC Coupling2" 143 pt in from the cell's start) and must
    # not read as a second column.
    for lo, hi in zip(lefts, lefts[1:] + [math.inf]):
        for row in rows:
            max_size = max((s.size for s in row.spans), default=0.0)
            raw = sorted((s for s in row.spans if lo <= s.x0 < hi),
                         key=lambda s: s.x0)
            starts = [
                s.x0 for s in raw
                if not (s.size <= _MARKER_SIZE_RATIO * max_size
                        and max_size - s.size >= 1.0)
            ]
            clusters = _cluster_lefts(starts, _HDR_ANCHOR_TAU)
            for a, z in itertools.pairwise(clusters):
                if z - a < _SUB_COLUMN_GAP:
                    continue
                # a glued composite (superscript/subscript fragments of one
                # cell, e.g. "Output Power @ f0 (dBm)", or AD9081's RSET
                # superscript bridging to its '= 5 kΩ' tail) is not a
                # fusion — the second group must start as a genuinely
                # separate text run: a real gap from its *raw* predecessor
                # (marker-bridges included), of real words
                second = [s for s in raw if s.x0 >= z]
                if not any(len(s.text.strip()) >= 3 for s in second):
                    continue
                first_of_z = second[0]
                prev = raw[raw.index(first_of_z) - 1]
                if first_of_z.x0 - prev.x1 > 0.5 * prev.size:
                    return "side-by-side columns fused into one band"

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
            for s in row_spans:
                if lo <= s.x0 < hi:
                    first_devs[b].append(s.x0 - lo)
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


def _row_y(row: _Row) -> float:
    return row.lines[0].y if row.lines else row.y


def _materialize_band0(grid: list[list[str]], row_ys: list[float],
                       starts: list[float | None], lefts: list[float]) -> None:
    """Ticket 09: rowspan materialization of the parameter column.

    The engine's grids are band-expanded but span-silent — a parent cell
    that spans several rows keeps its association only if it replicates.
    Two measured shapes are reconstructed:

    1. **Indent chain** (AD9081 Table 3, QPA1003P p2): the parent's text
       prints on its own row and the children print one indent level deeper
       (band start >= the header-anchor tau away from the column's left
       edge — measured 14.9-17.0 pt vs 6.4-8.5 pt for ordinary rows). The
       child's cell becomes "parent + own text", so 'AC Coupling' under
       'Full-Scale Output Current Range' reads
       'Full-Scale Output Current Range AC Coupling'. Band headers on the
       column's own left edge ('DAC ACCURACY') never replicate into
       single-indent rows ('Gain Error'), which stay clean.
    2. **Empty child rows** (continuation rows of a multi-row span: AD9081
       p5's second DC Coupling shunt row, QPA1003P's 'Frequency = 1 GHz'
       rows whose parent prints mid-span): the empty first cell inherits
       the *nearest* anchor row's first cell (above or below, by baseline
       distance — ties prefer the anchor printed above). The parent text
       vertically centered over its span puts the closest anchor inside
       the span, so the nearest anchor is the true parent.
    """
    if len(grid) <= 1 or not lefts:
        return
    band0 = lefts[0]
    parent = -1
    anchors = [i for i, row in enumerate(grid) if row[0].strip()]
    for i, row in enumerate(grid):
        if starts[i] is not None:
            depth = starts[i] - band0
            # a parent is an *indented, value-less* row (conditions allowed):
            # 'Full-Scale Output Current Range' spans its 'AC Coupling'
            # children, while top-level band headers ('DAC ACCURACY', depth
            # 0) and value-carrying rows ('Gain Error') never replicate
            # (measured indent levels: 6.4-8.5 pt rows vs 14.9-17.0 pt
            # children on AD9081; band headers sit on the column's own edge)
            if depth >= _HDR_ANCHOR_TAU and parent >= 0:
                row[0] = f"{grid[parent][0]} {row[0]}"
            elif 0.0 < depth < _HDR_ANCHOR_TAU:
                has_values = any(c.strip() for c in row[2:])
                parent = i if not has_values else parent
            continue
        if not row[0].strip():
            above = [a for a in anchors if a < i]
            below = [a for a in anchors if a > i]
            best: tuple[float, int] | None = None
            if above:
                best = (row_ys[i] - row_ys[above[-1]], above[-1])
            if below:
                cand = (row_ys[below[0]] - row_ys[i], below[0])
                # ties keep the anchor printed above (AD9081 p5)
                if best is None or cand[0] < best[0] - _ROW_ANCHOR_TIE:
                    best = cand
            if best is not None:
                row[0] = grid[best[1]][0]


def _block_from(rows: list[_Row], lefts: list[float], caption: str,
                conditions: str, page_number: int,
                footnotes: list[Footnote] | None = None,
                cited_markers: list[str] | None = None) -> TableBlock:
    headers = _row_cells(rows[0], lefts)
    kept = [(r, _row_cells(r, lefts)) for r in rows[1:]
            if any(c.strip() for c in _row_cells(r, lefts))]
    grid = [cells for _r, cells in kept]
    row_ys = [_row_y(r) for r, _c in kept]
    band1 = lefts[1] if len(lefts) > 1 else math.inf
    starts = [
        min((s.x0 for s in r.spans if lefts[0] <= s.x0 < band1), default=None)
        for r, _c in kept
    ]
    row_pages = [page_number] * len(grid)
    _materialize_band0(grid, row_ys, starts, lefts)
    return TableBlock(
        caption=caption,
        headers=headers,
        grid=grid,
        conditions=conditions,
        footnotes=footnotes or [],
        cited_markers=cited_markers or [],
        markdown=grid_markdown(headers, grid),
        csv=grid_csv(headers, grid),
        page=page_number,
        row_pages=row_pages,
    )


def _merge_footnotes(base: list[Footnote], extra: list[Footnote]) -> list[Footnote]:
    """Merge two footnote lists by marker (first occurrence wins), so
    continuation pages never duplicate a footnote already attached."""
    merged = {f.marker: f for f in base}
    for f in extra:
        merged.setdefault(f.marker, f)
    return list(merged.values())


class _AcceptedTable:
    """An accepted table + the geometry it was accepted with (continuations
    reuse the exact same columns so multi-page tables stay one atomic grid).

    ``last_anchor`` is the block's most recently printed parameter-cell
    text (ticket 09): continuation rows with an empty parameter cell carry
    it across the page break in reading order."""

    __slots__ = ("block", "header_sig", "last_anchor", "lefts")

    def __init__(self, block: TableBlock, lefts: list[float]):
        self.block = block
        self.lefts = lefts
        self.header_sig = _squash(" ".join(block.headers))
        self.last_anchor = block.grid[-1][0] if block.grid else ""


def _is_repeated_header(row: _Row, lefts: list[float], header_sig: str) -> bool:
    return _squash(" ".join(c for c in _row_cells(row, lefts) if c)) == header_sig


def _advice_share(lefts: list[float], advice: list[float]) -> float:
    """Reconstruction score of a candidate grid: the share of the
    header-anchored column edges the candidate's own band edges reproduce.

    A candidate whose bands merge the header's declared columns (e.g. a
    coarse split that collapses "Min" and "Typ" into one band) loses the
    edges it merged; bands the header never declared neither help nor hurt
    (rescue splits keep the grid's data columns). The header-anchored
    candidate reproduces every advice edge by construction, so it is the
    score maximum whenever it passes the gate.
    """
    if not advice:
        return 1.0
    hits = 0
    for edge in advice:
        if any(abs(edge - left) <= 0.75 for left in lefts):
            hits += 1
    return hits / len(advice)


def _hypothesis(region: list[_Line], page: _Page
                ) -> tuple[list[float] | None, str | None, float,
                            list[_Row]]:
    """Score one region against the retry ladder.

    Every band set (header-anchored first, then the all-word retry ladder)
    is gated and scored; the best reconstruction-scoring grid wins the
    ladder. The score is ``_advice_share``: the share of the header-anchored
    column edges the candidate's own band edges reproduce — a candidate
    whose bands merge the header's declared columns (a coarse split that
    collapses Min|Typ into one cell) loses the edges it merged, so it never
    outvotes the grid the header itself declares (which reproduces every
    advice edge by construction). Ties keep the ladder's exploration order
    (primary split first).

    Ties prefer the *coarsest* passing split (fewest bands): a fine
    all-word split that reproduces every header edge scores 1.0 too, and
    its extra bands are degenerate — they carve the interior words of wide
    cells (measured: LM741's 'Supply voltage' word gap of 31 pt, QPA1003P's
    superscript + wrapped 'Frequency = N GHz' continuation lines) into
    separate columns. The header row's own declaration wins a tie by band
    count; a split that merged real columns (Min|Typ 25-34 pt apart) loses
    the advice edges it merged and scores below.

    Returns (lefts, reason, fidelity, kept_rows): lefts is the accepted
    column geometry (or None), reason the rejection string, fidelity the
    measured reconstruction of the accepted grid — the share of the
    region's words the grid reconstructs (footnote and prose rows detract
    honestly, so tables with footnotes score below 1.0), kept_rows the
    accepted fine rows (marker citation context for ticket 05's superscript
    detection; footnote and prose rows never enter the set, and
    wrap-merging happens afterwards on their lines).
    """
    region_words = sum(len(s.text.split()) for ln in region for s in ln.spans)
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
    best: tuple[float, list[float], list[_Line], list[_Row]] | None = None
    best_fidelity = 0.0
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
        if reason is not None:
            keep_reason = reason
            continue
        grid_words = sum(len(s.text.split())
                         for ln in lines for s in ln.spans)
        fidelity = (grid_words / region_words) if region_words else 1.0
        score = _advice_share(lefts, band_sets[0])
        # strictly greater scores replace; ties keep the coarsest candidate
        # (fewest bands — the header-anchored split is the table's own
        # declaration and equals the fineness of the declaration; a finer
        # tie can only be carving interior words of declared columns)
        if best is None or score > best[0] or (
                score == best[0] and len(lefts) < len(best[1])):
            best = (score, lefts, lines, candidate)
            best_fidelity = fidelity
    if best is None:
        return None, keep_reason, 0.0, []
    return best[1], None, best_fidelity, best[3]


def _is_heading_anchor(line: _Line, title_keys: frozenset[str]) -> bool:
    """A printed section heading is a table-anchor candidate (ticket 09,
    SPEC story 10): its line matches a section title key, or its spans are
    heading-sized (measured: LM741 body headings 11.0 pt, QPA1003P
    14.04 pt — HMC520A's 10.98 pt table sub-labels never fire).

    A heading-sized line that reads as a known parameter-header token is a
    table header cell, never a heading (measured on QPA1003P: its
    'Parameter'/'Min'/'Units'/'Part No.'/'Value / Range' header words
    print at 11.04-12.0 pt — treating them as anchors would carve the
    region into empty slivers between header words and starve every
    heading-anchored table under them). LM741's lone section-number lines
    ('6.1', '6.5') stay anchors — they are printed section prefixes, not
    header cells."""
    if title_keys and _squash(line.text) in title_keys:
        return True
    if _squash(line.text) in _HEADER_TOKENS:
        return False
    return any(s.size >= _HEADING_SIZE for s in line.spans)


def _strip_leading_preamble(region: list[tuple[int, _Line]]
                            ) -> list[tuple[int, _Line]]:
    """Heading-anchored regions start below the printed heading; a leading
    single-band sentence line directly under it is the test-conditions
    preamble (measured: LM741 'over operating free-air temperature range
    (unless otherwise noted)...', QPA1003P 'Test conditions unless otherwise
    noted: 25 °C, ...'). The captioned path attaches preambles as
    conditions; here the equivalent rows drop out of the grid and rejoin
    the paragraph stream when the region is rejected."""
    out = list(region)
    while out:
        line = out[0][1]
        # a preamble is ONE glued text run: every next span starts right at
        # the previous one's end (LM741's condition line measures 2.7 pt
        # joins, sub/superscript tails included) — a real header row's
        # column starts sit tens of points apart ('MIN' vs 'MAX' vs 'UNIT')
        spans = sorted(line.spans, key=lambda s: s.x0)
        glued = len(spans) <= 1 or all(
            b.x0 - a.x1 <= 0.5 * a.size for a, b in itertools.pairwise(spans))
        if not glued:
            break
        # the whole sentence stays a preamble at the prose-word boundary
        # too (LM741's condition line measures exactly 8 words); a real
        # header row ('PARAMETER TEST CONDITIONS MIN TYP MAX UNIT' = 7)
        # never pops
        if len(_WS.sub(" ", line.text).split()) < _PROSE_WORDS:
            break
        out.pop(0)
    return out


def _has_header_row(region: list[tuple[int, _Line]]) -> bool:
    """The region's first row must read like a parametric header (see
    ``_HEADER_TOKENS``) — the captionless-era rejection gate. The row is
    the first baseline group — QPA1003P prints each header word as its own
    line on one baseline, and a full-width header row spans several lines
    ('PARAMETER TEST CONDITIONS MIN TYP MAX UNIT' prints as words too)."""
    if not region:
        return False
    rows = _group_rows([ln for _i, ln in region], wrap=False)
    if not rows:
        return False
    tokens = {_squash(t) for ln in rows[0].lines for t in ln.text.split()}
    return bool(tokens & _HEADER_TOKENS)


def _mirror_split(region: list[tuple[int, _Line]]) -> list[list[tuple[int, _Line]]]:
    """Side-by-side pairs share one heading band (QPA1003P p2: 'Absolute
    Maximum Ratings | Recommended Operating Conditions' — two 2-column
    tables on one baseline group). When the region's header word clusters
    reflect in pairs ('Parameter | Value / Range | Parameter | Value /
    Range'), the region splits at the pair midpoint and each side is
    hypothesized independently. Returns [] when the header does not mirror.

    The header row is the region's first *baseline group* (QPA1003P prints
    each header word as its own line at the same y), never one physical
    line."""
    region_lines = [ln for _i, ln in region]
    rows = _group_rows(region_lines, wrap=False)
    if not rows:
        return []
    clusters: list[tuple[float, list[_Span]]] = []
    for s in sorted(rows[0].spans, key=lambda sp: sp.x0):
        if clusters and s.x0 - clusters[-1][0] < _HDR_ANCHOR_TAU:
            clusters[-1][1].append(s)
        else:
            clusters.append((s.x0, [s]))
    n = len(clusters)
    if n < 4 or n % 2:
        return []
    for i in range(n // 2):
        left = _squash(" ".join(s.text for s in clusters[i][1]))
        right = _squash(" ".join(s.text for s in clusters[i + n // 2][1]))
        if left != right:
            return []
    mid = (clusters[n // 2 - 1][0] + clusters[n // 2][0]) / 2.0
    zones: list[list[tuple[int, _Line]]] = [[], []]
    for idx, ln in region:
        kept = [s for s in ln.spans if s.x0 < mid]
        if kept:
            out = _Line(ln.block, ln.y, min(s.x0 for s in kept), ln.text, kept)
            zones[0].append((idx, out))
        kept = [s for s in ln.spans if s.x0 >= mid]
        if kept:
            out = _Line(ln.block, ln.y, min(s.x0 for s in kept), ln.text, kept)
            zones[1].append((idx, out))
    return [z for z in zones if z]


class _TableExtraction:
    """Per-document table extraction state + statistics.

    Runs one page at a time; repeated captions (multi-page tables) merge
    their continuation rows into the first page's atomic block, reusing the
    exact column geometry the block was accepted with. Ticket 09 adds the
    heading-anchored pass (SPEC story 10) with the same ladder + gate, and
    per-row page attribution for merged multi-page grids.
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
        self._last_reason = ""

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
                        or _FIGURE_CAPTION_RE.match(line.text.strip())
                        or (title_keys and _squash(line.text) in title_keys)):
                    break
                region.append((j, line))
                j += 1

            self.detected += 1
            acc = self.accs.get(key)
            if acc is not None:
                # continuation page: extend the existing atomic grid with the
                # same columns; footnotes and a repeated header row are
                # dropped by signature. Every appended row records the page
                # it was printed on (ticket 09: per-row page attribution),
                # and rows whose parameter cell is empty carry the block's
                # last printed parameter text (the page-13 'fOUT' rows of a
                # page-12 'fDAC' group inherit their parent across the page
                # break — the measured ACLR continuation shape).
                rows = _group_rows([ln for _i, ln in region], wrap=False)
                kept_ids: set[int] = set()
                grid_rows: list[_Row] = []
                carried = acc.last_anchor
                for row in rows:
                    if _is_footnote_row(row):
                        continue  # collected as a footnote below
                    if _is_repeated_header(row, acc.lefts, acc.header_sig):
                        kept_ids.update(id(ln) for ln in row.lines)
                        continue  # repeated header row: caption-like furniture
                    cells = _row_cells(row, acc.lefts)
                    if not cells[0].strip() and carried:
                        cells[0] = carried
                    elif cells[0].strip():
                        carried = cells[0]
                        acc.last_anchor = carried
                    acc.block.grid.append(cells)
                    acc.block.row_pages.append(page.index)
                    kept_ids.update(id(ln) for ln in row.lines)
                    grid_rows.append(row)
                acc.block.csv = grid_csv(acc.block.headers, acc.block.grid)
                acc.block.markdown = grid_markdown(acc.block.headers, acc.block.grid)
                # same grid-end rule as the first page: the last row that
                # spans bands (single-band sub-headers are not the grid end)
                grid_end = max((r.y for r in grid_rows
                                if _row_band_count(r) > 1), default=0.0)
                footnotes, fn_rows = _scan_table_footnotes(
                    rows, grid_end, _row_pitch(rows))
                acc.block.footnotes = _merge_footnotes(
                    acc.block.footnotes, footnotes)
                for row in grid_rows:
                    acc.block.cited_markers = list(dict.fromkeys(
                        acc.block.cited_markers + _row_markers(row)))
                by_id = {id(ln): idx for idx, ln in region}
                self._consume(page, [idx for idx, ln in region
                                     if id(ln) in kept_ids] + [i]
                              + [by_id[id(ln)] for row in fn_rows
                                 for ln in row.lines])
                self.accepted += 1
                self.fidelities.append(1.0)
                i = j
                continue

            pre_idx, conditions = self._preamble(
                page, i, furniture, title_keys, self.consumed[page.index - 1])
            block, lefts, _fidelity, reason = self._accept_hypothesis(
                page, region, lines[i].text.strip(), conditions)
            if block is not None and lefts is not None:
                self.accs[key] = _AcceptedTable(block, lefts)
                self._consume(page, pre_idx + [i])
            else:
                self.rejected += 1
                self.reasons.append(reason)
            i = j

        self._run_heading_anchored(page, furniture, title_keys)

    def _run_heading_anchored(self, page: _Page, furniture: set[int],
                              title_keys: frozenset[str]) -> None:
        """Ticket 09, SPEC story 10: captionless-era tables are anchored by
        their printed section heading and hypothesized with the exact same
        ladder + gate as captioned tables — a captionless double either
        reconstructs honestly or stays paragraphs. Side-by-side pairs
        (QPA1003P p2) split first at their mirrored header into two zones;
        when a zone fails, the region-wide hypothesis and the old
        reject-then-split fallback keep their honesty.
        """
        consumed = self.consumed[page.index - 1]
        lines = page.lines
        i = 0
        while i < len(lines):
            if (i in furniture or i in consumed
                    or _CAPTION_RE.match(lines[i].text.strip())
                    or not _is_heading_anchor(lines[i], title_keys)):
                i += 1
                continue
            region: list[tuple[int, _Line]] = []
            j = i + 1
            while j < len(lines):
                line = lines[j]
                if (j in furniture or j in consumed
                        or _CAPTION_RE.match(line.text.strip())
                        or _FIGURE_CAPTION_RE.match(line.text.strip())
                        or _is_heading_anchor(line, title_keys)):
                    break
                region.append((j, line))
                j += 1
            region = _strip_leading_preamble(region)
            if not region:
                i = j
                continue
            if not _has_header_row(region):
                i = j
                continue
            self.detected += 1
            zones = _mirror_split(region)
            split_blocks: list[TableBlock] = []
            for zone in zones:
                part, _l2, _f2, zone_reason = self._accept_hypothesis(
                    page, zone)
                if part is not None:
                    split_blocks.append(part)
                else:
                    self.rejected += 1
                    self.reasons.append(zone_reason)
            # a mirrored header declares two tables side by side (QPA1003P
            # p2): shipping both halves beats shipping the fused grid; only
            # when a zone fails does the region-wide hypothesis get its say
            if len(split_blocks) == len(zones) and zones:
                i = j
                continue
            block, _lefts, _fid, reason = self._accept_hypothesis(page, region)
            if block is None and not zones:
                self.rejected += 1
                self.reasons.append(reason)
            i = j

    def _accept_hypothesis(
        self, page: _Page, region: list[tuple[int, _Line]],
        caption: str = "", conditions: str = "",
    ) -> tuple[TableBlock | None, list[float] | None, float, str]:
        """Run the ladder + gate over a region and, when accepted, build the
        block, consume its rows + footnotes and return (block, lefts,
        fidelity, ""). The shared implementation of the captioned and
        heading-anchored paths (ticket 09)."""
        region_lines = [ln for _i, ln in region]
        lefts, reason, fidelity, kept_rows = _hypothesis(region_lines, page)
        if lefts is None:
            self._last_reason = reason
            return None, None, 0.0, reason
        fine = _group_rows(region_lines, wrap=False)
        # the grid's last row is the last one that spans bands; single-band
        # rows below it are footnote continuations
        grid_end = max((r.y for r in kept_rows
                        if _row_band_count(r) > 1), default=0.0)
        footnotes, fn_rows = _scan_table_footnotes(
            fine, grid_end, _row_pitch(fine))
        attached_ids = {id(ln) for row in fn_rows for ln in row.lines}
        grid_rows = [r for r in kept_rows
                     if not any(id(ln) in attached_ids for ln in r.lines)]
        markers = list(dict.fromkeys(
            m for row in grid_rows for m in _row_markers(row)))
        block = _block_from(_group_rows(
            [ln for r in grid_rows for ln in r.lines]), lefts,
            caption, conditions,
            page.index,
            footnotes=footnotes,
            cited_markers=markers)
        self.by_page.setdefault(page.index, []).append(block)
        by_id = {id(ln): idx for idx, ln in region}
        consumed = [by_id[id(ln)] for row in grid_rows
                    for ln in row.lines]
        consumed += [by_id[id(ln)] for row in fn_rows
                     for ln in row.lines]
        self._consume(page, consumed)
        self.accepted += 1
        self.fidelities.append(fidelity)
        return block, lefts, fidelity, ""

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


class _FigureExtraction:
    """Per-page figure catalog: every "Figure N." caption line becomes a
    FigureRef (caption + exact page); the caption line is consumed so it is
    never duplicated into the paragraph stream. Nothing else is consumed:
    figure-internal labels stay honest paragraphs, and the clip geometry
    for rendering is recomputed at publish time via ``figure_anchor_map``
    (same caption scan, drift-free).

    Ticket 09 adds title-anchored figures (SPEC story 10's guard applied to
    figures): a captionless-era drawing gets its own FigureRef when its
    title — a heading-sized line inside a drawn emphasis band — has a large
    vector rect directly below and no body-prose lines between (the QPA1003P
    block diagram and its performance-plot bands; prose headings like
    'Product Features' sit outside any band and never fire).
    """

    def __init__(self, pages: list[_Page]):
        self.pages = pages
        self.by_page: dict[int, list[FigureRef]] = {}
        self.consumed: list[set[int]] = [set() for _ in pages]

    def run(self, page: _Page, furniture: set[int],
            title_keys: frozenset[str],
            consumed_tables: set[int] | None = None) -> None:
        consumed = consumed_tables or set()
        for i, line in enumerate(page.lines):
            m = _FIGURE_CAPTION_RE.match(line.text.strip())
            if not m:
                continue
            caption = line.text.strip()
            self.by_page.setdefault(page.index, []).append(
                FigureRef(caption=caption, conditions="",
                          image_url="", page=page.index)
            )
            self.consumed[page.index - 1].add(i)
        self._run_title_anchored(page, furniture, title_keys, consumed)

    def _run_title_anchored(self, page: _Page, furniture: set[int],
                            title_keys: frozenset[str],
                            consumed_tables: set[int]) -> None:
        lines = page.lines
        boxes = page.boxes()
        anchors: list[tuple[int, float, tuple[float, float, float, float]]] = []
        for i, line in enumerate(lines):
            if (i in furniture or i in consumed_tables
                    or (title_keys and _squash(line.text) in title_keys)
                    or _FIGURE_CAPTION_RE.match(line.text.strip())
                    or _CAPTION_RE.match(line.text.strip())
                    or max((s.size for s in line.spans), default=0.0) < _TITLE_SIZE):
                continue
            band = None
            for b in boxes:
                if (b[0] <= line.x <= b[2] and b[1] - 2.0 <= line.y <= b[3]
                        and b[3] - b[1] >= _TITLE_BAND_H_MIN):
                    band = b
                    break
            if band is None:
                continue
            if len(line.text.split()) < 3:
                continue  # 'GND'/'VG' labels inside a drawn diagram are
                # not figure titles (measured 14.1 pt on QPA1003P p17)
            anchors.append((i, line.y, band))
        page_bottom = max((ln.y for ln in lines), default=700.0) + 40.0
        for k, (i, _y, band) in enumerate(anchors):
            bottom = anchors[k + 1][2][1] if k + 1 < len(anchors) else page_bottom
            content_ok = any(
                bx[2] - bx[0] >= _TITLE_RECT_MIN and bx[3] - bx[1] >= _TITLE_RECT_MIN
                and bx[0] <= line.x <= bx[2]  # the rect sits under the title's
                and bx[1] <= band[3] + _TITLE_CONTENT_GAP  # own column — a side
                and bx[3] >= band[3] + _TITLE_CONTENT_GAP   # box never counts
                for bx in boxes
            )
            prose_ok = all(
                not (len(ln.text.split()) >= 6 and
                     max((s.size for s in ln.spans), default=0.0) >= 8.5)
                and not (len(ln.text.split()) >= 4 and
                         max((s.size for s in ln.spans), default=0.0) >= 11.0)
                for ln in page.lines
                if band[3] < ln.y <= bottom
                # prose in the *title's own x-column* only: QPA1003P's block
                # diagram sits left of the 'Applications' bullets + ordering
                # table on the same page (measured x: band 36-295 vs text
                # at 316+) — a neighboring column is not body prose of the
                # figure. The clip itself stays the full-width band (the
                # side-by-side artifact class of caption-anchored figures).
                and max((s.x1 for s in ln.spans), default=0.0) >= band[0]
                and ln.x <= band[2]
            )
            if not (content_ok and prose_ok):
                continue
            self.by_page.setdefault(page.index, []).append(
                FigureRef(caption=lines[i].text.strip(), conditions="",
                          image_url="", page=page.index)
            )
            self.consumed[page.index - 1].add(i)
            log.info("pdf_layout: title-anchored figure on page %d: %r",
                     page.index, lines[i].text.strip()[:60])


def figure_anchor_map(path: Path) -> dict[tuple[int, str], tuple[float, float]]:
    """(page, squashed caption) -> (region_top, caption_y) for every figure
    caption in a PDF.

    Clip geometry, recomputed deterministically for the publish stage from
    the same caption scan the extractor used: the region above a caption
    runs from the previous caption's text box (shared band when two
    captions sit on one baseline — HMC520A's side-by-side pair) or the page
    top down to the caption line. The pipeline renders with this map so the
    image always matches what extraction cataloged.
    """
    pages = _load_pages(path)
    out: dict[tuple[int, str], tuple[float, float]] = {}
    for page in pages:
        prev_y: float | None = None
        prev_top: float | None = None
        for ln in page.lines:
            m = _FIGURE_CAPTION_RE.match(ln.text.strip())
            if not m:
                continue
            # side-by-side captions sit on one baseline within the margin of
            # each other (measured offsets 0.07-7.9 pt on AD9081/HMC520A, e.g.
            # 482.0 vs 482.7, 453.5 vs 461.4) and share the band clip;
            # stacked captions are tens of points apart (row pitch >= 180 pt)
            if prev_y is not None and ln.y - prev_y <= _FIGURE_MARGIN:
                top = prev_top if prev_top is not None else 0.0
            else:
                top = prev_y + _FIGURE_MARGIN if prev_y is not None else 0.0
            out[(page.index, figure_caption_key(ln.text.strip()))] = (top, ln.y)
            prev_y = ln.y
            prev_top = top
    return out


def figure_caption_key(caption: str) -> str:
    """The anchor-map key of a caption line (squashed, space- and
    punctuation-immune) — the publisher matches PlotRecord captions to
    their clip geometry with it."""
    return _squash(caption)


def figure_title_anchor_map(path: Path
                            ) -> dict[tuple[int, str], tuple[float, float]]:
    """(page, squashed title) -> (clip_top, clip_bottom) for every
    title-anchored figure in a PDF (ticket 09).

    The clip runs from the title's drawn emphasis band down to the next
    banded title (or page bottom), so the rendered image is exactly the
    drawing band the extractor cataloged. Recomputed deterministically at
    publish time with the same scan, mirroring ``figure_anchor_map``.
    """
    pages = _load_pages(path)
    out: dict[tuple[int, str], tuple[float, float]] = {}
    for page in pages:
        boxes = page.boxes()
        anchors: list[tuple[float, tuple[float, float, float, float]]] = []
        for ln in page.lines:
            if max((s.size for s in ln.spans), default=0.0) < _TITLE_SIZE:
                continue
            band = None
            for b in boxes:
                if (b[0] <= ln.x <= b[2] and b[1] - 2.0 <= ln.y <= b[3]
                        and b[3] - b[1] >= _TITLE_BAND_H_MIN):
                    band = b
                    break
            if band is not None:
                anchors.append((ln.y, band))
        page_bottom = max((ln.y for ln in page.lines), default=700.0) + 40.0
        for k, (y, band) in enumerate(anchors):
            bottom = anchors[k + 1][1][1] if k + 1 < len(anchors) else page_bottom
            out[(page.index, figure_caption_key(next(
                ln.text.strip() for ln in page.lines if ln.y == y)))] = (
                band[1], bottom)
    return out


class PdfLayoutBackend:
    """Offline, vendor-neutral layout extraction (PyMuPDF only)."""

    name = "pdf_layout"
    output_version = "tables-07"

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
        figures = _FigureExtraction(pages)
        title_keys = _title_keys(entries)
        for page in pages:
            tables.run(page, furniture[page.index - 1], title_keys)
            figures.run(page, furniture[page.index - 1], title_keys,
                        consumed_tables=tables.consumed[page.index - 1])
        if entries:
            sections = _sections_from_entries(
                pages, entries, furniture, tables, figures)
        else:
            sections = _sections_per_page(pages, furniture, tables, figures)
        log.info(
            "pdf_layout: %d pages, %d sections, %d tables "
            "(%d detected, %d accepted, %d rejected), %d figures, "
            "%d furniture lines (ladder=%s)",
            len(pages), len(sections), tables.accepted, tables.detected,
            tables.accepted, tables.rejected, sum(len(v) for v in figures.by_page.values()),
            sum(len(s) for s in furniture), ladder,
        )
        return RawDocument(
            source=source, toc=entries, sections=sections,
            extractor=self.name, extractor_version=self.output_version,
            extraction_stats=tables.stats(),
        )
