"""PDF structure extraction via PyMuPDF: identity, page count, TOC, page text.

This is NOT the content extractor (layout analysis of dense parametric
tables from raw PDF text is the failure mode this project avoids). The PDF
provides: content-hash identity, page count, the printed TOC (authoritative
page numbers for citations), and per-page text for verification/pinning.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import fitz  # PyMuPDF

from datasheet_analyzer.models import SourceDocument, TOCEntry

_NUM_PREFIX = re.compile(r"^(\d+(?:\.\d+)*)\s*[. ]?\s*(.*)$")


def compute_content_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split_number(title: str) -> tuple[str, str]:
    """"4.5 Transmitter Electrical Characteristics" -> ("4.5", "Transmitter ...").
    Unnumbered titles -> ("", title)."""
    m = _NUM_PREFIX.match(title.strip())
    if not m:
        return "", title.strip()
    return m.group(1), m.group(2).strip()


def read_toc(path: Path) -> list[TOCEntry]:
    """Read the PDF's printed TOC (bookmarks). Pages are 1-based."""
    out: list[TOCEntry] = []
    with fitz.open(path) as doc:
        for level, title, page in doc.get_toc():
            number, clean = split_number(title)
            out.append(
                TOCEntry(number=number, title=clean, level=level, page=page or None)
            )
    return out


def page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


def page_texts(path: Path) -> list[str]:
    """Text of every page (index 0 = page 1). Used for citation verification
    and table-page pinning — not for content extraction."""
    with fitz.open(path) as doc:
        return [p.get_text() for p in doc]


def sniff_revision(path: Path, max_pages: int = 3) -> str:
    """Pull the TI document id (e.g. 'SBASA41E') from the first pages."""
    pat = re.compile(r"\b(S[A-Z]{2}[A-Z0-9]{2,6}[A-Z]?)\b")
    with fitz.open(path) as doc:
        for page in list(doc)[:max_pages]:
            m = pat.search(page.get_text())
            if m:
                return m.group(1)
    return ""


def make_source(path: Path, *, part_number: str = "", **kw) -> SourceDocument:
    return SourceDocument(
        content_hash=compute_content_hash(path),
        path=str(path),
        part_number=part_number,
        page_count=page_count(path),
        revision=sniff_revision(path),
        **kw,
    )
