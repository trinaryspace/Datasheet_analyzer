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


def first_page_text(path: Path) -> str:
    """Text of page 1 only (vendor detection); '' for an empty document."""
    with fitz.open(path) as doc:
        return doc[0].get_text() if doc.page_count else ""


# Revision shapes from a shared lexicon (SPEC story 23): "Rev. "-token
# captions for any vendor's era ("Rev. 0", "Rev. A", "Rev. I", and
# revision-history "Rev. N to Rev. M" — the last token is the current
# revision) and TI document ids. Capital "Rev" only: "Revision N"/"REVISED"/
# "REVISION HISTORY" are not tokens. The Rev-token form wins within a page,
# the TI id otherwise.
_REV_SHAPE = re.compile(r"\bRev[.\s]*([A-Z][A-Z0-9]?|\d{1,3})")

# A TI literature number is a *shape*, and the shape has to be tight enough to
# tell a document id from a signal name printed on the same page (phase 7,
# ticket 02). The former pattern — `S` + two capitals + anything containing a
# digit — read LMX1204's page-1 pin name `SYSREFOUT0` as this document's id and
# returned it, because `.search()` takes the first match and the real number
# `SNAS800B` is printed last. Three constraints, each doing real work:
#
#   S + three more letters   the four-letter series code (SBAS, SNAS, SNOS, SNAU…)
#   2–3 alphanumerics        the short tail, which must contain a **digit** —
#                            this is what keeps bare all-letter S-words like
#                            "SUPPORT" out (measured AD9081 p.1 trap)
#   a final letter           the revision letter every literature number ends in
#
# Measured against all eight documents committed to this repo: `SBASA41E`,
# `SBASAN1A`, `SNOSC25D`, `SNAS800B`, `SNAU269A` all match; `SYSREFOUT0`
# (ten characters), `SYSREF1` (ends in a digit) and `SUPPORT` (no digit) do
# not. Deliberately *not* "take the last match": that fixes LMX1204 by accident
# of print order and would break the first document whose page 1 cites another
# literature number after its own. `scripts/seed_datasheet_registry.py` holds
# the stricter twin of this rule — a closed list of series codes — because it
# may refuse rather than degrade; here a shape has to serve every vendor's
# document, so it stays a shape.
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
    and must never stage the download inside a part directory to do it — a
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
