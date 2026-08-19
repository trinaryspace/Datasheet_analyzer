"""A needle recovered from a section's own published markdown.

Some documents defeat heading detection entirely, and the structure stage
falls back to one section per page titled `Page 1`, `Page 2`, … That title is
page furniture: it appears on the page exactly once, in the running footer.
`retrieve.results.section_needle` therefore refuses it, which stops the
highlight being *wrong* but leaves those documents with no highlight at all —
and on a shelf of Mini-Circuits and Qorvo datasheets that is every document.

So the needle is recovered here, from the section markdown the publisher
already wrote. Two rules decide which line to take, and both come from what
page text actually looks like:

**Furniture is what recurs.** `CONTEXT.md` defines Furniture as universal
patterns plus recurrence, and that is the only reliable test — a vendor's
`www.minicircuits.com  P.O. Box 350166 …` banner is not matched by any pattern
worth writing, but it appears on every page. So the other sections of the same
document are read and any line they share is disqualified.

**A column gap is not a space.** `50Ω     0.05 to 10 GHz     Wideband
Amplifier` is three columns, not a sentence; searched for as one string it
matches nothing, because the PDF's spacing is not the markdown's. Lines are
split on runs of whitespace and the longest surviving fragment wins.

This runs at **locate time**, not at citation time. `SPEC.md` fixes that
principle for the geometry — "derived on demand, not persisted… resolution
happens lazily when the user clicks a citation" — and the needle is the same
kind of thing: a handful of small file reads when somebody clicks, rather than
a read per hit on every search whether or not anyone ever looks.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

from datasheet_analyzer.retrieve.index import CorpusIndex
from datasheet_analyzer.retrieve.results import MIN_NEEDLE_CHARS, is_furniture

log = logging.getLogger(__name__)

#: Long enough to be distinctive on a page, short enough to survive the line
#: wrapping PDF text extraction imposes. A whole paragraph never matches.
MAX_NEEDLE_CHARS = 60

#: How many sibling sections are read to learn what recurs. A banner repeats
#: on every page, so a handful is plenty, and this bounds the cost of a click.
FURNITURE_SAMPLE = 8

#: A line appearing in this many sections of one document is furniture.
FURNITURE_MIN_REPEATS = 2

_MARKUP = re.compile(r"^[#>\s*_`\-|]+|[*_`]+$")
_NOT_PROSE = re.compile(r"^(<!--|\||[-=|:\s]+$|!\[)")
#: Column gaps, and the tab the extractor leaves between cells.
_GAP = re.compile(r"\s{2,}|\t")


#: How many candidates to offer. The caller tries them in order and keeps the
#: first that lands on content, so a line that turns out to be a stray footer
#: costs one more search rather than a wrong highlight.
MAX_CANDIDATES = 5


def needles_from_section(index: CorpusIndex, doc_hash: str, page: int) -> list[str]:
    """Findable fragments of the section covering `page`, best first.

    A list rather than one string because the best *textual* candidate is not
    always the best *positional* one: `REV. A` is a perfectly distinctive line
    that happens to live in the footer. The caller searches in order and keeps
    the first that lands outside the page's furniture band.

    Reads only; never raises. Returns `[]` when the markdown cannot be read,
    and an empty needle opens the page unhighlighted, which is the honest
    answer.
    """
    manifest = getattr(index, "manifest", None)
    if manifest is None:
        return []

    sections = [s for s in manifest.sections if not doc_hash or s.doc_hash == doc_hash]
    target = _section_for(sections, page)
    if target is None:
        return []

    lines = _lines(index, target)
    if not lines:
        return []

    recurring = _recurring(index, [s for s in sections if s is not target])
    return _fragments(lines, recurring)


def _section_for(sections, page: int):
    """The narrowest section covering `page`.

    Narrowest because a page-per-section fallback and a real heading can both
    cover one page in a mixed corpus, and the tighter span is the one whose
    text is actually on this page.
    """
    covering = []
    for section in sections:
        start = section.page_start
        if start is None:
            continue
        end = section.page_end if section.page_end is not None else start
        if start <= page <= end:
            covering.append((end - start, section))
    if not covering:
        return None
    return min(covering, key=lambda pair: pair[0])[1]


def _lines(index: CorpusIndex, section) -> list[str]:
    """The section's markdown as candidate text lines, markup stripped."""
    try:
        text = Path(index.corpus_path(section.file)).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        log.debug("locate: could not read %s: %s", getattr(section, "file", "?"), exc)
        return []
    out: list[str] = []
    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue  # the section's own heading — the title we already refused
        line = _MARKUP.sub("", raw).strip()
        if line and not _NOT_PROSE.match(line):
            out.append(line)
    return out


def _recurring(index: CorpusIndex, others) -> set[str]:
    """Lines shared across sibling sections — the document's furniture."""
    seen: Counter[str] = Counter()
    for section in others[:FURNITURE_SAMPLE]:
        for line in set(_lines(index, section)):
            seen[line] += 1
    return {line for line, n in seen.items() if n >= FURNITURE_MIN_REPEATS - 1}


def _fragments(lines: list[str], recurring: set[str]) -> list[str]:
    """Findable, non-furniture fragments in reading order, deduplicated.

    Reading order rather than longest-first: the top of the page is where a
    reader looks, and a section's opening line is what its citation means.
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line in recurring:
            continue
        best = ""
        for fragment in _GAP.split(line):
            candidate = fragment.strip()
            if len(candidate) < MIN_NEEDLE_CHARS or is_furniture(candidate):
                continue
            # Needs letters: a run of numbers and units matches half the page.
            if sum(ch.isalpha() for ch in candidate) < MIN_NEEDLE_CHARS:
                continue
            if len(candidate) > len(best):
                best = candidate
        trimmed = _trim(best)
        if trimmed and trimmed not in seen:
            seen.add(trimmed)
            out.append(trimmed)
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def _trim(line: str) -> str:
    """Cut at a word boundary — a needle split mid-word matches nothing."""
    if len(line) <= MAX_NEEDLE_CHARS:
        return line
    cut = line[:MAX_NEEDLE_CHARS]
    spaced = cut.rsplit(" ", 1)[0]
    return spaced if len(spaced) >= MIN_NEEDLE_CHARS else cut
