"""Source inventory: a part is a folder of documents.

sources.json (per part) tracks every input document with its content hash
(identity), detected document type, revision and NDA flag. Companion
documents (register map, errata, app notes) drop into the same folder and
are picked up on the next build — the corpus layout does not change.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from datasheet_analyzer.extract.pdf_structure import make_source
from datasheet_analyzer.models import DocType, SourceDocument

log = logging.getLogger(__name__)

SOURCES_FILE = "sources.json"

_HINTS: list[tuple[re.Pattern[str], DocType]] = [
    (re.compile(r"errata", re.IGNORECASE), DocType.ERRATA),
    (re.compile(r"register|regmap|reg[-_ ]?map|programming", re.IGNORECASE), DocType.REGISTER_MAP),
    (re.compile(r"app[-_ ]?note|sbaa|slaa|swra", re.IGNORECASE), DocType.APP_NOTE),
    (re.compile(r"datasheet|data[-_ ]?sheet|^[a-z0-9]+\.pdf$", re.IGNORECASE), DocType.DATASHEET),
]


def detect_doc_type(path: Path) -> DocType:
    name = path.name.lower()
    for pat, dtype in _HINTS:
        if pat.search(name):
            return dtype
    return DocType.UNKNOWN


def register_source(
    path: Path,
    *,
    part_number: str = "",
    doc_type: DocType | None = None,
    nda: bool = False,
) -> SourceDocument:
    """Register one input document (identity = sha256 of its bytes)."""
    src = make_source(
        Path(path),
        part_number=part_number,
        doc_type=doc_type or detect_doc_type(Path(path)),
        nda=nda,
    )
    log.info(
        "registered %s: type=%s rev=%s pages=%d hash=%s…",
        Path(path).name, src.doc_type.value, src.revision or "?",
        src.page_count, src.content_hash[:10],
    )
    return src


def save_inventory(sources: list[SourceDocument], part_dir: Path) -> Path:
    part_dir = Path(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)
    dest = part_dir / SOURCES_FILE
    dest.write_text(
        json.dumps([s.model_dump(mode="json") for s in sources], indent=2),
        encoding="utf-8",
    )
    return dest


def load_inventory(part_dir: Path) -> list[SourceDocument]:
    dest = Path(part_dir) / SOURCES_FILE
    if not dest.exists():
        return []
    data = json.loads(dest.read_text(encoding="utf-8"))
    return [SourceDocument.model_validate(d) for d in data]


def append_to_inventory(
    new_sources: list[SourceDocument], part_dir: Path
) -> list[SourceDocument]:
    """Append new sources to an existing inventory, deduping by content_hash.

    Returns the merged inventory. Re-adding an existing source is a no-op
    (logged) so `dsa add-doc` is idempotent.
    """
    existing = load_inventory(part_dir)
    by_hash = {s.content_hash: s for s in existing}
    added = 0
    for src in new_sources:
        if src.content_hash in by_hash:
            log.info(
                "source already registered: %s (hash %s…)",
                Path(src.path).name, src.content_hash[:10],
            )
            continue
        by_hash[src.content_hash] = src
        added += 1
    merged = list(by_hash.values())
    if added:
        log.info("added %d new source(s) to inventory for %s", added, part_dir.name)
    save_inventory(merged, part_dir)
    return merged
