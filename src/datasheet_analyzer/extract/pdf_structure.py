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
# revision-history "Rev. N to Rev. M" - the last token is the current
# revision) and TI document ids. Capital "Rev" only: "Revision N"/"REVISED"/
# "REVISION HISTORY" are not tokens. The Rev-token form wins within a page,
# the TI id otherwise.
#
# `_TI_DOC_ID` is a *tight* shape, and each of its three constraints was
# bought with a measured misreading (phase 7, ticket 02):
#
#   | constraint                      | keeps out                          |
#   |---------------------------------|------------------------------------|
#   | 4 letters + 2-3 alphanumerics   | `SYSREFOUT0` (lmx1204.pdf p.1)     |
#   | a digit in the middle group     | `SUPPORT` (ad9081.pdf p.1)         |
#   | a final *letter* (the revision) | `SYSREF1`, `SPECIFICATIONS1`       |
#
# The predecessor `\bS[A-Z]{2}[A-Z0-9]*\d[A-Z0-9]*\b` matched any capitalised
# S-word containing a digit, so it read a *pin name* as a literature number on
# `lmx1204.pdf` (`SYSREFOUT0` prints before `SNAS800B`) and the heading word
# `SPECIFICATIONS1` as one on all three Mini-Circuits datasheets. Deliberately
# not "take the last match on the page", which would fix LMX1204 by accident of
# print order and break the first document whose page 1 cites another
# literature number after its own. `SBASAN1A` carries only one digit, which is
# why the rule is "a digit" rather than the more tempting "two".
_REV_SHAPE = re.compile(r"\bRev[.\s]*([A-Z][A-Z0-9]?|\d{1,3})")
_TI_DOC_ID = re.compile(r"\bS[A-Z]{3}([A-Z0-9]{2,3})[A-Z]\b")


def _ti_doc_id(text: str) -> str:
    """The first TI-literature-shaped token on a page; `""` when there is none."""
    for m in _TI_DOC_ID.finditer(text):
        if any(ch.isdigit() for ch in m.group(1)):
            return m.group(0)
    return ""


def revision_from_texts(texts: list[str]) -> str:
    """The revision printed on these pages, in order; `""` is the honest miss.

    Pure, so the same lexicon reads a document on disk (`sniff_revision`) and
    one that only exists as downloaded bytes (`sniff_revision_bytes`, phase 7
    ticket 02's upstream check) without either growing its own rules.
    """
    for text in texts:
        revs = _REV_SHAPE.findall(text)
        if revs:
            return f"Rev. {revs[-1]}"
        doc_id = _ti_doc_id(text)
        if doc_id:
            return doc_id
    return ""


def sniff_revision(path: Path, max_pages: int = 3) -> str:
    """Sniff the document revision from the first pages.

    Returns the normalized "Rev. N" token ("Rev. 0", "Rev. A", ...) or the
    TI document id; "" is the honest no-match answer.
    """
    with fitz.open(path) as doc:
        return revision_from_texts([p.get_text() for p in list(doc)[:max_pages]])


def sniff_revision_bytes(payload: bytes, max_pages: int = 3) -> str:
    """`sniff_revision` for bytes that were never written to disk.

    `dsa check-revisions` compares an upstream document against a built corpus
    and must never stage the download inside a part directory to do it - a
    document that was not verified has no business being where a datasheet
    lives, even briefly. Unreadable bytes are `""` (the same honest miss a
    document with no printed revision gives), never an exception: the caller
    reports "could not read a revision", which is a finding, not a crash.
    """
    try:
        with fitz.open(stream=payload, filetype="pdf") as doc:
            return revision_from_texts([p.get_text() for p in list(doc)[:max_pages]])
    except Exception:  # noqa: BLE001 - any open failure is the same finding
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
