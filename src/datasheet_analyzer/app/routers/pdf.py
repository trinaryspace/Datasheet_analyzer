"""`GET /api/pdf/{content_hash}` — the source PDF, streamed and range-aware.

This is the one endpoint that hands raw filesystem bytes to a browser, so its
safety properties matter more than its size.

**There is no user-controlled path component.** `content_hash` is a
`SourceDocument`'s identity, so the library *is* the lookup: a hash that is not
in the store is a 404 before anything touches the filesystem. Path traversal is
structurally impossible rather than filtered — `../../etc/passwd` is simply a
hash nobody registered.

`SourceDocument.path` is whatever string the CLI was given, often relative
(`"ad9081.pdf"`), so it is only meaningful against the working directory that
registered it. It is resolved against the cwd, checked for containment in the
document roots, and checked for being a regular file. A file that has moved is
a 404 **naming the recorded path**: a user who reorganized their folders needs
to know which file went missing, not a stack trace.

Range requests are supported because PDF.js depends on them. Opening page 47 of
a 200-page datasheet fetches two small ranges; answering 200 OK with the whole
body defeats that on exactly the documents where it matters most. Bytes are
streamed from a seeked file handle in `CHUNK_SIZE` pieces, so a 40 MB datasheet
never becomes a 40 MB buffer.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, NamedTuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from datasheet_analyzer.app.contracts import API_PREFIX, ErrorOut
from datasheet_analyzer.app.deps import get_library, get_settings_dep
from datasheet_analyzer.config import Settings
from datasheet_analyzer.library.store import LibraryStore

__all__ = [
    "CHUNK_SIZE",
    "MEDIA_TYPE",
    "PDF_ROOTS_ENV",
    "UNSATISFIABLE",
    "ByteRange",
    "allowed_roots",
    "iter_file_range",
    "parse_range",
    "resolve_document_path",
    "router",
]

#: Read size for the streaming body. Small enough that memory is bounded by the
#: chunk rather than by the document, large enough that a 40 MB datasheet is not
#: ten thousand syscalls.
CHUNK_SIZE = 64 * 1024

MEDIA_TYPE = "application/pdf"

#: `os.pathsep`-separated extra document roots. A library record may legitimately
#: point at a folder outside the corpus and outside the user's home — a mounted
#: share, a second drive — and this is how that folder is declared servable.
#: Read from the environment here rather than added to `Settings` because
#: `config.py` is frozen by ticket 00 (recorded as a contract gap).
PDF_ROOTS_ENV = "DSA_PDF_ROOTS"

router = APIRouter(prefix=f"{API_PREFIX}/pdf", tags=["pdf"])


class ByteRange(NamedTuple):
    """One inclusive byte range, already clamped to the file's size."""

    start: int
    end: int

    @property
    def length(self) -> int:
        """Bytes in the range — `0` for the empty range of an empty file."""
        return max(self.end - self.start + 1, 0)


#: The parse result meaning "416": the client asked for bytes that do not exist.
UNSATISFIABLE = ByteRange(-1, -1)


def _user_home() -> Path | None:
    """The user's home directory, or `None` where the platform has none.

    A seam, not a convenience: it is the widest default root, so a test needs
    to control it to assert that anything outside the roots is refused.
    """
    try:
        return Path.home()
    except (RuntimeError, OSError):  # pragma: no cover - platform dependent
        return None


def allowed_roots(settings: Settings) -> list[Path]:
    """Directories a recorded document path may resolve inside.

    The corpus directories, the working directory that relative paths are
    resolved against, the user's own files, and anything named in
    `DSA_PDF_ROOTS`. The point is not to filter a hostile request — no request
    reaches here with a path in it — but to bound the blast radius of a
    hand-edited or corrupted library record to files the user owns anyway.
    """
    candidates: list[Path | None] = [
        settings.parts_dir,
        settings.cache_dir,
        settings.library_dir,
        settings.projects_dir,
        settings.sessions_dir,
        Path.cwd(),
        _user_home(),
    ]
    for entry in os.environ.get(PDF_ROOTS_ENV, "").split(os.pathsep):
        if entry.strip():
            candidates.append(Path(entry.strip()).expanduser())

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            resolved = Path(candidate).resolve()
        except OSError:  # pragma: no cover - unreachable on a sane filesystem
            continue
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            roots.append(resolved)
    return roots


def _within(path: Path, roots: list[Path]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def resolve_document_path(recorded: str, settings: Settings) -> Path:
    """The absolute file to serve for a library record's `path`.

    Raises `HTTPException(403)` when the record resolves outside every document
    root, and `HTTPException(404)` — naming the recorded path — when the file
    has moved, was deleted, or is not a regular file.
    """
    if not recorded.strip():
        raise HTTPException(
            status_code=404,
            detail="This document has no recorded path; re-analyze the PDF to register it.",
        )
    candidate = Path(recorded).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        resolved = candidate.resolve()
    except OSError:  # pragma: no cover - unreachable on a sane filesystem
        raise HTTPException(
            status_code=404, detail=f"Recorded path cannot be resolved: {recorded}"
        ) from None

    if not _within(resolved, allowed_roots(settings)):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Recorded path resolves outside the document roots and will not be "
                f"served: {recorded}. Add its folder to {PDF_ROOTS_ENV} if it belongs "
                f"to this library."
            ),
        )
    if not resolved.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"The recorded path for this document no longer exists: {recorded}. "
                f"Move the file back or re-analyze it from its new location."
            ),
        )
    if not resolved.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"The recorded path for this document is not a regular file: {recorded}",
        )
    return resolved


def parse_range(header: str | None, size: int) -> ByteRange | None:
    """Interpret a `Range` header against a known file size.

    Returns the clamped inclusive range, `None` when the header is absent or
    must be ignored (junk, or a multi-range request this endpoint does not
    serve — RFC 9110 says ignore rather than fail), or `UNSATISFIABLE` when the
    client asked for bytes past the end of the file.
    """
    if not header:
        return None
    value = header.strip()
    unit, _, spec = value.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first, sep, last = spec.strip().partition("-")
    if not sep:
        return None
    first, last = first.strip(), last.strip()
    if not first and not last:
        return None
    if (first and not first.isdigit()) or (last and not last.isdigit()):
        return None

    if not first:  # suffix range: the last N bytes
        wanted = int(last)
        if wanted == 0 or size == 0:
            return UNSATISFIABLE
        return ByteRange(max(0, size - wanted), size - 1)

    start = int(first)
    if start >= size:  # includes every range against an empty file
        return UNSATISFIABLE
    end = size - 1 if not last else min(int(last), size - 1)
    if end < start:  # an invalid spec is ignored, not an error
        return None
    return ByteRange(start, end)


def iter_file_range(
    path: Path, start: int, end: int, chunk_size: int | None = None
) -> Iterator[bytes]:
    """Yield `path[start:end+1]` in bounded pieces, opening the file lazily.

    Bounded is the whole point: the response never holds more than one chunk,
    so a 200-page datasheet costs `chunk_size` bytes of memory, not its size.
    """
    size = chunk_size or CHUNK_SIZE
    remaining = end - start + 1
    if remaining <= 0:
        return
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(size, remaining))
            if not chunk:  # truncated under us; stop rather than spin
                break
            remaining -= len(chunk)
            yield chunk


def _content_disposition(filename: str) -> str:
    """`inline`, so the browser renders the PDF instead of downloading it.

    The filename comes from a stored record, so the quoted form is reduced to
    characters that cannot break out of the header and the exact name is
    carried in the RFC 5987 `filename*` parameter.
    """
    safe = "".join(ch for ch in filename if ch.isalnum() or ch in "._-()[] ").strip()
    safe = safe[:120] or "document.pdf"
    return f"inline; filename=\"{safe}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get(
    "/{content_hash}",
    response_class=StreamingResponse,
    responses={
        200: {"content": {MEDIA_TYPE: {}}, "description": "The whole document"},
        206: {"content": {MEDIA_TYPE: {}}, "description": "The requested byte range"},
        403: {"model": ErrorOut, "description": "Recorded path is outside the document roots"},
        404: {"model": ErrorOut, "description": "Unknown hash, or the file has moved"},
        416: {"model": ErrorOut, "description": "Range past the end of the file"},
    },
    summary="Stream a source PDF by content hash",
)
async def get_pdf(
    content_hash: str,
    request: Request,
    library: Annotated[LibraryStore, Depends(get_library)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> Response:
    """Stream the registered PDF with this content hash.

    Honours `Range` (206 + `Content-Range`), refuses a range past the end of
    the file (416 + `bytes */size`), and otherwise returns the whole document.
    """
    document = library.get(content_hash)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"No document with content hash {content_hash!r} is in the library.",
        )
    path = resolve_document_path(document.source.path, settings)
    size = path.stat().st_size
    etag = f'"{content_hash}"'

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": _content_disposition(document.filename or path.name),
        "ETag": etag,
        # Identity is the content hash, so a cached body can never be stale.
        "Cache-Control": "private, max-age=3600",
    }

    range_header = request.headers.get("range")
    if_range = request.headers.get("if-range")
    if if_range and if_range.strip() != etag:
        range_header = None  # the client cached a different body; send all of this one

    requested = parse_range(range_header, size)
    if requested == UNSATISFIABLE:
        return Response(
            status_code=416,
            headers={**headers, "Content-Range": f"bytes */{size}"},
        )

    status_code = 200
    if requested is None:
        requested = ByteRange(0, size - 1)
    else:
        status_code = 206
        headers["Content-Range"] = f"bytes {requested.start}-{requested.end}/{size}"
    headers["Content-Length"] = str(requested.length)

    return StreamingResponse(
        iter_file_range(path, requested.start, requested.end),
        status_code=status_code,
        media_type=MEDIA_TYPE,
        headers=headers,
    )
