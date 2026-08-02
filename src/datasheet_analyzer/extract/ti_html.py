"""TI document-viewer extraction backend.

For TI parts this is the highest-fidelity source: real HTML tables (with
rowspan/colspan), MathML, section structure, tablenotes — no PDF layout
analysis, no OCR, no hallucination risk. The viewer page is a TOC shell;
each section's content lives at a GUID URL.

Parsing model per section page: the requested section lives in
`div.subsection[id=<GUID>]`; its inner `div.subsection` holds flat blocks:
h2 title, text blocks (p/span), <table> (parametric), <table> wrappers
around <img> (figures), and <div class="tablenote"> footnotes that belong
to the nearest preceding table.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from datasheet_analyzer.extract.base import BackendUnavailableError
from datasheet_analyzer.extract.http import CachingFetcher, Fetcher
from datasheet_analyzer.models import (
    FigureRef,
    RawDocument,
    SectionNode,
    SourceDocument,
    TOCEntry,
)
from datasheet_analyzer.structure.footnotes import tablenotes_from_elements
from datasheet_analyzer.structure.pagemap import assign_pages
from datasheet_analyzer.structure.tables import cited_markers, html_table_to_block

log = logging.getLogger(__name__)

_GUID_URL = re.compile(r'/document-viewer/([^/]+)/datasheet/(GUID-[^#\s"]+)')
_SECTION_NUMBER = re.compile(r"^\d+(?:\.\d+)*$")
_WS = re.compile(r"\s+")

# Words that mark a paragraph as a table's test-conditions preamble.
_CONDITION_HINTS = (
    "typical values",
    "unless otherwise noted",
    "over operating free-air",
    "over free-air temperature",
    "test conditions",
    "nominal power supplies",
)

# Text blocks that are UI furniture, not content (case-insensitive exact match).
_SKIP_TEXTS = {"request full data sheet"}

# Span/div classes that never carry content (section number decorations).
_SKIP_CLASSES = {"section-label"}


def parse_toc(main_html: str, part_number: str) -> list[TOCEntry]:
    """Parse the viewer TOC shell into entries with per-section URLs."""
    soup = BeautifulSoup(main_html, "lxml")
    entries: list[TOCEntry] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=_GUID_URL):
        href = a["href"]
        url = href if href.startswith("http") else "https:" + href
        if url in seen:
            continue
        seen.add(url)
        number = (a.get("id") or "").strip()
        title = _WS.sub(" ", (a.get("data-navtitle") or a.get_text(" ", strip=True))).strip()
        if not _SECTION_NUMBER.match(number):
            number = ""
            # the datasheet cover page appears in the TOC with an empty id and
            # a numeric-only navtitle — it is not a content section
            if not title or title.isdigit():
                continue
        level = number.count(".") + 1 if number else 1
        entries.append(TOCEntry(number=number, title=title, level=level, url=url))
    return entries


def _section_guid(url: str) -> str:
    """The section's content GUID = first GUID in the URL path."""
    m = re.search(r'(GUID-[^#\s"]+)', url)
    return m.group(1) if m else ""


def _looks_like_conditions(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in _CONDITION_HINTS)


def _block_text(el: Tag) -> str:
    # join with "" so sub/superscripts stay glued to their base ("T_A",
    # "1st"), then collapse whitespace runs (source newlines become spaces)
    return _WS.sub(" ", el.get_text("", strip=False)).strip()


def _candidate_blocks(container: Tag) -> list[Tag]:
    """Flatten a section container into an ordered list of content blocks.

    Handles the two TI layouts seen in the wild:
    - spec sections: h2 + span/p blocks + table + div.tablenote siblings,
      sometimes nested inside div.body > div.subsection wrappers;
    - plot sections: dozens of div.graph > div.textnote > div.subsection >
      table.frame-none > img figure wrappers.
    Rules: nothing inside a <table> becomes a text block; nested p/span
    collapse to their outermost element; only div.tablenote divs count as divs.
    """
    blocks: list[Tag] = []
    for el in container.find_all(["p", "span", "table", "div", "li"]):
        if el.find_parent("div", class_="graph") is not None:
            continue  # figure internals are handled by _parse_figures
        if el.find_parent("table") is not None:
            continue  # content inside tables is handled by the table parser
        classes = set(el.get("class") or [])
        if classes & _SKIP_CLASSES:
            continue  # decorative labels (e.g. the bare section number)
        if el.name in ("p", "span") and el.find_parent(["p", "span"]) is not None:
            continue  # nested inline wrappers: take the outermost only
        if el.name == "div" and "tablenote" not in classes:
            continue  # layout wrapper divs are not content
        # NOTE: <li> elements are never skipped for having <li> ancestors —
        # each list item is its own block; _li_text excludes nested lists.
        blocks.append(el)
    return blocks


def _li_text(el: Tag) -> str:
    """Text of a list item EXCLUDING nested lists (those become their own
    blocks). Depth comes from counting <ul>/<ol> ancestors."""
    parts: list[str] = []
    for child in el.children:
        if isinstance(child, Tag) and child.name in ("ul", "ol"):
            continue
        parts.append(child.get_text("", strip=False) if isinstance(child, Tag) else str(child))
    return _WS.sub(" ", "".join(parts)).strip()


def _li_depth(el: Tag) -> int:
    return sum(1 for p in el.parents if getattr(p, "name", None) in ("ul", "ol"))


def _parse_figures(container: Tag) -> list[FigureRef]:
    """Figures are div.graph bundles: img + div.textnote (plot conditions)
    + span.caption ("Figure 4-1 …")."""
    figures: list[FigureRef] = []
    for graph in container.find_all("div", class_="graph"):
        img = graph.find("img")
        if img is None:
            continue
        cap_el = graph.find("span", class_="caption")
        note_el = graph.find("div", class_="textnote")
        caption = _block_text(cap_el) if cap_el else (img.get("alt") or "").strip()
        figures.append(
            FigureRef(
                caption=caption,
                conditions=_block_text(note_el) if note_el else "",
                image_url=img.get("src") or "",
            )
        )
    return figures


def parse_section(html: str, url: str, *, number: str = "", title: str = "") -> SectionNode:
    """Parse one fetched section page into a SectionNode."""
    soup = BeautifulSoup(html, "lxml")
    guid = _section_guid(url)
    container = soup.find("div", id=guid) if guid else None
    if container is None:
        # fall back: the subsection containing a heading matching our title
        for sub in soup.find_all("div", class_="subsection"):
            h = sub.find(["h1", "h2", "h3"])
            if h and title and title.lower() in h.get_text().lower():
                container = sub
                break
    if container is None:
        # last resort (e.g. TI revision-history pages carry no ids/headings):
        # the first subsection with substantial text
        for sub in soup.find_all("div", class_="subsection"):
            if len(sub.get_text(strip=True)) > 100:
                container = sub
                break
    if container is None:
        raise ValueError(f"section container not found for {number} {title!r}")

    heading = container.find(["h1", "h2", "h3"])
    full_title = _WS.sub(" ", heading.get_text(" ", strip=True)).strip() if heading else ""
    if full_title:
        m = re.match(r"^(\d+(?:\.\d+)*)\s+(.*)$", full_title)
        if m:
            number = number or m.group(1)
            title = title or m.group(2)
        else:
            title = title or full_title

    paragraphs: list[str] = []
    tables = []
    figures: list[FigureRef] = _parse_figures(container)
    pending_notes: list[Tag] = []
    last_text: tuple[str, list[str]] | None = None  # (text, classes) of previous block

    def flush_notes():
        nonlocal pending_notes
        if tables and pending_notes:
            notes = tablenotes_from_elements(pending_notes)
            if notes:
                merged = {f.marker: f for f in tables[-1].footnotes}
                for n in notes:
                    merged.setdefault(n.marker, n)
                tables[-1].footnotes = list(merged.values())
        pending_notes = []

    for el in _candidate_blocks(container):
        classes = el.get("class") or []
        if el.name == "div" and "tablenote" in classes:
            pending_notes.append(el)
            last_text = None
            continue
        if el.name == "table":
            if el.find("img") is not None:
                last_text = None
                continue  # stray image table not inside div.graph: skip
            block = html_table_to_block(el)
            if not block.grid:
                last_text = None
                continue  # empty layout table (frame-none furniture): skip
            flush_notes()
            caption, conditions = "", ""
            if last_text is not None:
                text, classes = last_text
                if "caption" in classes:
                    caption = paragraphs.pop()
                elif _looks_like_conditions(text):
                    conditions = paragraphs.pop()
            block.caption, block.conditions = caption, conditions
            # capture cited footnote markers while HTML structure is available
            block.cited_markers = sorted(cited_markers(el))
            tables.append(block)
            last_text = None
            continue
        # text block (li items render as bullets, nested lists indented)
        if el.name == "li":
            text = _li_text(el)
        else:
            text = _block_text(el)
        if not text or text.lower() in _SKIP_TEXTS:
            continue
        flush_notes()
        if el.name == "li":
            paragraphs.append("  " * (_li_depth(el) - 1) + "• " + text)
        else:
            paragraphs.append(text)
        last_text = (text, list(classes))

    flush_notes()

    level = number.count(".") + 1 if number else 1
    return SectionNode(
        number=number, title=title, level=level,
        paragraphs=paragraphs, tables=tables, figures=figures,
    )


class TiHtmlBackend:
    """Extract from TI's HTML document viewer (network or injected fetcher)."""

    name = "ti_html"

    def __init__(self, fetcher: Fetcher | None = None, *, cache_dir: Path | None = None):
        # fetcher=None means "create a default CachingFetcher at extract time"
        # (pipeline injects one; tests inject a replaying MappingFetcher).
        self.fetcher = fetcher
        self._cache_dir = cache_dir

    def is_available(self) -> tuple[bool, str]:
        return True, "ok"

    def main_url(self, part_number: str) -> str:
        return f"https://www.ti.com/document-viewer/{part_number}/datasheet"

    def extract(
        self,
        source: SourceDocument,
        *,
        pdf_toc: list[TOCEntry] | None = None,
    ) -> RawDocument:
        part = source.part_number
        if not part:
            raise BackendUnavailableError("ti_html backend needs source.part_number")

        fetcher = self.fetcher or CachingFetcher(self._cache_dir or Path(".cache/http"))
        main_html = fetcher(self.main_url(part))
        toc = parse_toc(main_html, part)
        if not toc:
            raise BackendUnavailableError(f"no TOC entries parsed for {part}")

        sections: list[SectionNode] = []
        for entry in toc:
            try:
                html = fetcher(entry.url)
                node = parse_section(html, entry.url, number=entry.number, title=entry.title)
                node.level = entry.level
                sections.append(node)
            except Exception as exc:  # noqa: BLE001 - one bad section must not kill 38 others
                log.warning("section %s %r failed: %s", entry.number, entry.title, exc)
                sections.append(
                    SectionNode(number=entry.number, title=entry.title, level=entry.level)
                )

        if pdf_toc:
            sections, report = assign_pages(sections, pdf_toc)
            log.info(
                "page assignment: %d exact, %d fuzzy, %d inherited, %d unmatched",
                report.n_exact, report.n_fuzzy, report.n_inherited, report.n_unmatched,
            )

        return RawDocument(source=source, toc=toc, sections=sections, extractor=self.name)
