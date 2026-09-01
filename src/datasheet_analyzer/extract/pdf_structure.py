"""PDF structure extraction via PyMuPDF: identity, page count, TOC, page text.

Layout analysis lives in the vendor-neutral layout core (`extract.pdf_layout`,
reconstruction-verified per ADR 0003) — never here. This module provides
content-hash identity, page count, the printed TOC (authoritative page
numbers for citations), and per-page text for verification/pinning only.
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
    """ "4.5 Transmitter Electrical Characteristics" -> ("4.5", "Transmitter ...").
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
            out.append(TOCEntry(number=number, title=clean, level=level, page=page or None))
    return out


def page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


def page_texts(path: Path) -> list[str]:
    """Text of every page (index 0 = page 1). Used for citation verification
    and table-page pinning — not for content extraction."""
    with fitz.open(path) as doc:
        return [p.get_text() for p in doc]


def first_page_text(path: Path) -> str:
    """Text of page 1 only (vendor detection); '' for an empty document."""
    with fitz.open(path) as doc:
        return doc[0].get_text() if doc.page_count else ""


#: Metadata fields a publisher stamps its own name into. `producer`/`creator`
#: name the typesetting tool ("Antenna House", "iText"), never the vendor, so
#: they are deliberately not read as brand evidence.
_BRAND_METADATA_FIELDS = ("author", "title", "subject")


def document_metadata_text(path: Path) -> str:
    """Publisher-bearing PDF metadata, joined (vendor detection).

    A datasheet cover page often prints its brand as a *logo* — an image, with
    no text for a page-1 scan to find (measured: AFE7950, AFE7953, LMX1204 and
    LM741 all print no vendor word on page 1). The document's own metadata
    still carries it ("Texas Instruments, Incorporated", "Analog Devices,
    Inc."), so this is real recorded evidence rather than a guess about what a
    brand-less document probably is. '' when the file cannot be read.
    """
    try:
        with fitz.open(path) as doc:
            meta = doc.metadata or {}
    except Exception:  # noqa: BLE001 - detection is best-effort
        return ""
    return " ".join(str(meta.get(field) or "") for field in _BRAND_METADATA_FIELDS)


# Revision shapes from a shared lexicon (SPEC story 23): "Rev. "-token
# captions for any vendor's era ("Rev. 0", "Rev. A", "Rev. I", and
# revision-history "Rev. N to Rev. M" — the last token is the current
# revision) and TI document ids. TI ids always carry a digit
# ("SBASA41E", "SNOSC25D") — requiring one keeps bare all-letter S-words
# like "SUPPORT" from reading as document ids (measured AD9081 p.1 trap).
# Capital "Rev" only: "Revision N"/"REVISED"/"REVISION HISTORY" are not
# tokens. The Rev-token form wins within a page, the TI id otherwise.
_REV_SHAPE = re.compile(r"\bRev[.\s]*([A-Z][A-Z0-9]?|\d{1,3})")
_TI_DOC_ID = re.compile(r"\bS[A-Z]{2}[A-Z0-9]*\d[A-Z0-9]*\b")


def sniff_revision(path: Path, max_pages: int = 3) -> str:
    """Sniff the document revision from the first pages.

    Returns the normalized "Rev. N" token ("Rev. 0", "Rev. A", ...) or the
    TI document id; "" is the honest no-match answer.
    """
    with fitz.open(path) as doc:
        for page in list(doc)[:max_pages]:
            text = page.get_text()
            revs = _REV_SHAPE.findall(text)
            if revs:
                return f"Rev. {revs[-1]}"
            m = _TI_DOC_ID.search(text)
            if m:
                return m.group(0)
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
