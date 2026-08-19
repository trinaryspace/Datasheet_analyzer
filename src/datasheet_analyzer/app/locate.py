"""Derive highlight geometry on demand (ticket 13).

**Signature frozen by ticket 00; the body is ticket 13's.**

No bounding box is persisted anywhere in this repo: geometry lives in
transient `_Span` / `_Line` slots inside `pdf_layout.py` and is discarded
when extraction returns. Rather than persist it — which would change
`RawDocument`, bump `output_version`, and invalidate every cached extraction
— this opens the PDF when the user clicks a citation and searches the page
for the record's own text.

**Needle selection is the hard part, not the search.** A spec row's needle is
the most distinctive cell of `SpecRecord.row_verbatim`, preferring a symbol
or a name over a bare number: `-40` appears fifty times on a page,
`OPERATING JUNCTION TEMPERATURE` appears once. A table's needle is its
caption; a section or search hit's is the opening of its first paragraph,
truncated to stay on one line. This is the discipline
`structure/pagemap.pin_table_pages()` already follows — squashed distinctive
needles, enough evidence required, and **unpinned rather than guessed**.

A miss is honest: `found=False`, empty `rects`, and a human-readable reason,
so the viewer opens the page with no highlight. A box around the wrong row
turns the verification step this application exists for into a lie.

This module must not import or modify `extract/pdf_layout.py`, and must not
move `output_version`: leaving the extraction cache valid is the entire
reason this approach was chosen over persisting geometry.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

import fitz

from datasheet_analyzer.app.contracts import LocateOut, RectOut

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datasheet_analyzer.models import SpecRecord, TableBlock

log = logging.getLogger(__name__)

__all__ = [
    "MAX_NEEDLE_CHARS",
    "MIN_NEEDLE_CHARS",
    "locate",
    "needle_for_spec_row",
    "needle_for_table",
    "needle_for_text",
    "normalize_needle",
]

#: A needle shorter than this cannot be located honestly — two characters of
#: punctuation match half the page — so it is refused rather than guessed at.
MIN_NEEDLE_CHARS = 3

#: Longest needle handed to `search_for`. A phrase that wraps to the next
#: printed line never matches as one string, so a long paragraph opening is
#: truncated to something that stays on one line.
MAX_NEEDLE_CHARS = 60

# Characters that differ between a record's stored text and the same text as
# printed, and that must not decide a match. Written as escapes because a
# literal soft hyphen in source is invisible to the next reader:
#   - soft hyphen, zero-width space/joiners, BOM: never in printed text
#   - non-breaking, figure and narrow spaces: a plain space once printed
_INVISIBLE = "\u00ad\u200b\u200c\u200d\u2060\ufeff"
_SPACES = "\u00a0\u2007\u202f\u2009\u200a"
# Every dash a datasheet prints for "minus" or "to". `−40` and `-40` are the
# same cell; which one a PDF happens to encode must not decide a match.
_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2043\ufe63\uff0d"
_WHITESPACE = re.compile(r"\s+")
# A parameter symbol as datasheets print them: `ATTstep`, `Pmax_FS`, `TJ`.
_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9_+/().-]{1,}$")


def normalize_needle(text: str) -> str:
    """The needle as the page prints it: NFKC, no invisibles, one space.

    Ligatures (`ﬁ`), non-breaking spaces and the soft hyphens a vendor's
    typesetter inserted are differences between a stored string and the same
    string on the page, never differences in meaning. Normalizing them away
    before the search is what keeps a correct citation from reading as a miss.
    """
    if not text:
        return ""
    out = text.translate({ord(ch): None for ch in _INVISIBLE})
    out = out.translate({ord(ch): " " for ch in _SPACES})
    out = unicodedata.normalize("NFKC", out)
    return _WHITESPACE.sub(" ", out).strip()


def _dash_variants(needle: str) -> list[str]:
    """`needle` with each dash spelling, most-likely first, deduplicated.

    Bounded on purpose: these are the *same* characters typeset differently,
    not looser matches. Nothing here trades precision for a hit.
    """
    candidates = (
        needle,
        needle.translate({ord(ch): "-" for ch in _DASHES}),
        needle.translate({ord(ch): "\u2212" for ch in _DASHES + "-"}),
        needle.translate({ord(ch): "\u2013" for ch in _DASHES + "-"}),
    )
    out: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def _truncate(text: str, max_chars: int) -> str:
    """Trim to `max_chars` on a word boundary, never mid-word."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    if " " in cut:
        head, _, _tail = cut.rpartition(" ")
        if len(head) >= MIN_NEEDLE_CHARS:
            return head.strip()
    return cut.strip()


def _cell_score(cell: str) -> float:
    """How distinctive one table cell is, higher is better.

    A bare number is the *least* distinctive thing on a page — `-40` appears
    fifty times — so it scores below every cell carrying letters, and a
    multi-word name outranks a bare symbol because it is rarer still.
    """
    text = normalize_needle(cell)
    if not text:
        return -1.0
    letters = sum(1 for ch in text if ch.isalpha())
    if letters == 0:
        # A bare numeric / punctuation cell: usable only as a last resort,
        # and longer digit runs are marginally less ambiguous than shorter.
        return min(len(text), 8) / 100.0
    words = len(text.split())
    score = float(letters) + 2.0 * min(words, 8)
    if _SYMBOL.match(text) and not any(ch.isdigit() for ch in text):
        score += 1.0
    if len(text) < MIN_NEEDLE_CHARS:
        score -= 5.0
    return score


def needle_for_spec_row(record: SpecRecord | Any) -> str:
    """The most distinctive cell of a spec row, as printed.

    Chosen from `row_verbatim` — the row exactly as the PDF prints it — so the
    needle is text that really is on the page, not a normalized field. A cell
    carrying a name or a symbol always beats a bare numeric cell; when the row
    is nothing but numbers the record's own `name`/`symbol` is the fallback,
    and `""` (locate refuses to guess) when there is nothing distinctive.
    """
    cells = list(getattr(record, "row_verbatim", None) or [])
    best, best_score = "", 0.0
    for cell in cells:
        score = _cell_score(cell)
        if score > best_score:
            best, best_score = normalize_needle(cell), score
    if best_score >= 1.0:
        return _truncate(best, MAX_NEEDLE_CHARS)
    for fallback in (getattr(record, "name", ""), getattr(record, "symbol", "")):
        text = normalize_needle(fallback)
        if len(text) >= MIN_NEEDLE_CHARS:
            return _truncate(text, MAX_NEEDLE_CHARS)
    if best and len(best) >= MIN_NEEDLE_CHARS:
        return _truncate(best, MAX_NEEDLE_CHARS)
    return ""


def needle_for_table(table: TableBlock | Any) -> str:
    """A table's caption, or its most distinctive header/first-row cell."""
    caption = normalize_needle(getattr(table, "caption", "") or "")
    if len(caption) >= MIN_NEEDLE_CHARS:
        return _truncate(caption, MAX_NEEDLE_CHARS)
    rows: list[list[str]] = []
    headers = list(getattr(table, "headers", None) or [])
    if headers:
        rows.append(headers)
    rows.extend(list(getattr(table, "grid", None) or [])[:2])
    best, best_score = "", 0.0
    for row in rows:
        for cell in row:
            score = _cell_score(cell)
            if score > best_score:
                best, best_score = normalize_needle(cell), score
    if best_score >= 1.0 and len(best) >= MIN_NEEDLE_CHARS:
        return _truncate(best, MAX_NEEDLE_CHARS)
    return ""


def needle_for_text(text: str, *, max_chars: int = MAX_NEEDLE_CHARS) -> str:
    """The opening of a paragraph, truncated to stay on one printed line.

    Used for a section or a search hit, whose "own text" is its first
    paragraph. A needle long enough to wrap never matches, so this is capped
    at a word boundary rather than mid-word.
    """
    opening = normalize_needle(text)
    if not opening:
        return ""
    truncated = _truncate(opening, max(max_chars, MIN_NEEDLE_CHARS))
    return truncated if len(truncated) >= MIN_NEEDLE_CHARS else ""


def _text_blocks(page: fitz.Page) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of the page's non-empty text blocks."""
    boxes: list[tuple[float, float, float, float]] = []
    try:
        blocks = page.get_text("blocks")
    except Exception as exc:  # noqa: BLE001 - geometry is best-effort
        log.debug("could not read text blocks: %s", exc)
        return boxes
    for block in blocks:
        if len(block) < 7:
            continue
        x0, y0, x1, y1, text, _number, kind = block[:7]
        if kind != 0 or not str(text).strip():
            continue
        boxes.append((float(x0), float(y0), float(x1), float(y1)))
    return boxes


def _row_extent(
    rect: fitz.Rect,
    boxes: list[tuple[float, float, float, float]],
) -> tuple[float, float] | None:
    """The horizontal extent of the text sharing `rect`'s vertical band.

    A matched cell is not a row: the highlight has to span the table for a
    user to read it as one. The band is the match's own vertical extent, and
    the width comes from every text block that overlaps it — which on a
    parametric table is the whole row and on a paragraph is the whole column.
    Falls back to the page's full text extent when nothing overlaps.
    """
    if not boxes:
        return None
    overlapping = [b for b in boxes if b[1] < rect.y1 and b[3] > rect.y0]
    chosen = overlapping or boxes
    return min(b[0] for b in chosen), max(b[2] for b in chosen)


def _as_rows(
    hits: list[fitz.Rect],
    boxes: list[tuple[float, float, float, float]],
    page_rect: fitz.Rect,
) -> list[RectOut]:
    """Matched rects widened into row bands, top to bottom, deduplicated."""
    ordered = sorted(hits, key=lambda r: (round(r.y0, 1), round(r.x0, 1)))
    out: list[RectOut] = []
    seen: set[tuple[float, float, float, float]] = set()
    for rect in ordered:
        extent = _row_extent(rect, boxes)
        x0, x1 = rect.x0, rect.x1
        if extent is not None:
            # Only ever widen: a row highlight that clipped the match itself
            # would point at the wrong text.
            x0, x1 = min(x0, extent[0]), max(x1, extent[1])
        x0 = max(x0, page_rect.x0)
        x1 = min(x1, page_rect.x1)
        key = (round(x0, 2), round(rect.y0, 2), round(x1, 2), round(rect.y1, 2))
        if key in seen:
            # Two hits on one printed row widen to the same band; one box is
            # the honest rendering of one row.
            continue
        seen.add(key)
        out.append(RectOut(x0=key[0], y0=key[1], x1=key[2], y1=key[3]))
    return out


#: The bands a running header and footer live in, as a fraction of page
#: height. Only consulted for a *recovered* needle (see `content_only`): a
#: record's own text is trusted wherever it lands, because a spec row really
#: can sit low on the page.
HEADER_BAND = 0.07
FOOTER_BAND = 0.88


def locate(
    pdf_path: Path, page: int, needle: str, *, content_only: bool = False
) -> LocateOut:
    """Rectangles for `needle` on 1-based `page` of `pdf_path`.

    Returns `LocateOut.miss(reason)` — never raises — for a missing or
    unreadable file, a page outside the document, an empty needle, or text
    that simply is not there.

    `content_only` discards matches inside the page's header/footer bands. Set
    it when the needle was *recovered* from section text rather than supplied
    by the record: `REV. A` is a distinctive line that lives in the footer, and
    a highlight there tells the reader the answer came from the page number.
    A record's own needle is never filtered — a spec row may legitimately sit
    low on the page, and second-guessing it would break the citations that
    work. Rects are PyMuPDF page points, top-left origin,
    ordered top to bottom; a row rect keeps the matched vertical band and is
    widened horizontally to the text extent so it reads as a row.
    """
    wanted = normalize_needle(needle)
    if not wanted:
        return LocateOut.miss("no text to search for: the citation carried no needle", page=page)
    if len(wanted) < MIN_NEEDLE_CHARS:
        return LocateOut.miss(
            f"needle {wanted!r} is too short to locate without guessing",
            page=page,
            needle=wanted,
        )

    path = Path(pdf_path)
    if not path.is_file():
        return LocateOut.miss(f"no readable PDF at {path}", page=page, needle=wanted)

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 - a bad PDF is a miss, not a 500
        log.warning("locate could not open %s: %s", path, exc)
        return LocateOut.miss(f"could not open {path.name}: {exc}", page=page, needle=wanted)

    try:
        n_pages = doc.page_count
        if page < 1 or page > n_pages:
            return LocateOut.miss(
                f"page {page} is outside {path.name}, which has {n_pages} page(s)",
                page=page,
                needle=wanted,
            )
        try:
            pdf_page = doc.load_page(page - 1)
            hits: list[fitz.Rect] = []
            for variant in _dash_variants(wanted):
                hits = list(pdf_page.search_for(variant))
                if hits:
                    break
            boxes = _text_blocks(pdf_page)
            page_rect = fitz.Rect(pdf_page.rect)
            rotation = int(pdf_page.rotation)
        except Exception as exc:  # noqa: BLE001 - unreadable page is a miss
            log.warning("locate could not read page %s of %s: %s", page, path, exc)
            return LocateOut.miss(
                f"could not read page {page} of {path.name}: {exc}",
                page=page,
                needle=wanted,
            )
    finally:
        doc.close()

    if not hits:
        return LocateOut.miss(
            f"{wanted!r} does not appear on page {page} of {path.name}",
            page=page,
            needle=wanted,
        )

    if content_only:
        height = float(page_rect.height) or 1.0
        body = [
            hit
            for hit in hits
            if HEADER_BAND * height <= float(hit.y0) <= FOOTER_BAND * height
        ]
        if not body:
            return LocateOut.miss(
                f"{wanted!r} appears on page {page} only in the running "
                f"header or footer, which is not where the answer came from",
                page=page,
                needle=wanted,
            )
        hits = body

    return LocateOut(
        found=True,
        page=page,
        rects=_as_rows(hits, boxes, page_rect),
        reason="",
        needle=wanted,
        page_width=round(float(page_rect.width), 2),
        page_height=round(float(page_rect.height), 2),
        rotation=rotation,
    )
