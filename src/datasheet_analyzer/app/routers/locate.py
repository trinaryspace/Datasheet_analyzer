"""`GET /api/locate` — where to draw the highlight (ticket 13).

The one job this router has that `app/locate.py` does not is **resolving the
PDF**, and it does it by the manifest join: `doc_hash` ->
`manifest.documents[*].content_hash` -> that document's recorded `path`. The
client never supplies a path, so there is no user-controlled path component
to sanitize — even `part` is matched against the directories
`discover_parts()` found rather than joined onto `parts_dir`, which makes
traversal structurally impossible instead of filtered.

Two different failures, two different answers, and the distinction is the
point:

- **The document cannot be resolved** — unknown part, unknown hash, or a
  recorded path that has moved — is a `404` naming what is missing. The user
  reorganized a folder and needs to know which file went away.
- **The document resolved but its text was not found** on that page is a
  `200` carrying `LocateOut.miss(...)`: `found=False`, no rects, a readable
  reason. The viewer opens the page with no highlight, because a box around
  the wrong row makes the verification step lie.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from datasheet_analyzer.app.contracts import API_PREFIX, LocateOut
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.app.locate import locate as locate_needle
from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import CorpusManifest, SourceDocument
from datasheet_analyzer.retrieve.index import discover_parts

log = logging.getLogger(__name__)

__all__ = ["get_locate", "router"]

router = APIRouter(prefix=API_PREFIX, tags=["locate"])

MANIFEST_FILENAME = "manifest.json"


def _load_manifest(part_dir: Path) -> CorpusManifest | None:
    """One part's manifest, or None when it is absent or will not parse.

    Unreadable is warned about and skipped, never guessed at — the same rule
    `retrieve/index.py` applies to the same file.
    """
    path = part_dir / MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        return CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - one bad manifest is not fatal
        log.warning("skipping unreadable %s: %s", path, exc)
        return None


def _candidate_dirs(settings: Settings, part: str) -> list[Path]:
    """Part directories to search, honouring an explicit `part` filter.

    `part` is compared against discovered directory *names*; it is never
    joined onto a path, so `../..` names no directory and finds nothing.
    """
    dirs = discover_parts(settings.parts_dir)
    wanted = part.strip()
    if not wanted:
        return dirs
    return [d for d in dirs if d.name.casefold() == wanted.casefold()]


def _resolve_document(settings: Settings, part: str, doc_hash: str) -> Path:
    """The PDF `doc_hash` names, via the manifest join. 404s, never guesses."""
    wanted = doc_hash.strip().casefold()
    if not wanted:
        raise HTTPException(status_code=400, detail="doc_hash is required to locate a citation")

    dirs = _candidate_dirs(settings, part)
    if part.strip() and not dirs:
        raise HTTPException(
            status_code=404,
            detail=f"no part named {part!r} under {settings.parts_dir}",
        )

    found: SourceDocument | None = None
    for part_dir in dirs:
        manifest = _load_manifest(part_dir)
        if manifest is None:
            continue
        for document in manifest.documents:
            if document.content_hash.strip().casefold() == wanted:
                found = document
                break
        if found is not None:
            break

    if found is None:
        where = f"part {part!r}" if part.strip() else f"any part under {settings.parts_dir}"
        raise HTTPException(
            status_code=404,
            detail=f"no document with content_hash {doc_hash!r} in {where}",
        )

    recorded = found.path
    # `SourceDocument.path` is whatever the CLI was handed — often relative to
    # the directory the part was built from — so a relative record resolves
    # against the current working directory, the same one that registered it.
    resolved = Path(recorded)
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                f"the PDF recorded for {doc_hash} is not on disk: {recorded} "
                f"(looked in {resolved.parent})"
            ),
        )
    return resolved


@router.get("/locate", response_model=LocateOut, summary="Locate a citation on a page")
def get_locate(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    part: Annotated[str, Query(description="Part directory the citation belongs to")] = "",
    doc_hash: Annotated[str, Query(description="`content_hash` of the cited PDF")] = "",
    page: Annotated[int, Query(description="1-based printed page the citation names")] = 1,
    needle: Annotated[str, Query(description="The record's own text: cell, caption, opening")] = "",
) -> LocateOut:
    """Rectangles to highlight for one citation, or an honest miss."""
    pdf_path = _resolve_document(settings, part, doc_hash)
    return locate_needle(pdf_path, page, needle)
