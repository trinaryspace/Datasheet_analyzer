"""Serve the built frontend, when there is one (ticket 06).

`dsa serve` is one process: the API and the UI come off the same origin, so
the browser needs no CORS and the client needs no base URL. That is only true
when `web/dist` exists — a developer running `npm run dev` has Vite serving
the UI on another port and proxying `/api` back here, and for them mounting
is **skipped silently**. A missing `dist` is a normal state, not an error.

Two rules make the mount safe to add last:

- **`/api/*` always wins.** `main.py` calls `mount_static()` after every
  router, and the SPA catch-all refuses anything under `API_PREFIX` outright,
  so an unknown API path 404s as an API path instead of quietly returning
  `index.html` — a fetch that receives HTML where it expected JSON fails in
  the least legible way there is.
- **A deep link falls back to `index.html`.** `/chat/abc` is a client route
  with no file behind it; the router in the browser resolves it. Anything
  that *is* a real file under `dist` is served as itself.

Path handling copies `CorpusIndex.corpus_path`'s rule: a request that is
absolute, drive-qualified, null-bearing or contains `..` is refused rather
than normalized, and the resolved target is checked back against the dist
root so a symlink cannot escape either.

**Content types are decided here, not by the machine.** `mimetypes.guess_type`
seeds itself from the Windows registry, and a machine whose `.js` key there
carries `Content Type = text/plain` (measured on this one) makes every bundle
come off the wire as plain text. A browser applies strict MIME checking to
`<script type="module">` and refuses such a response outright, so `dsa serve`
in production mode renders a blank page while `/api/*` answers normally --- a
failure that reproduces on one developer's laptop and nowhere else. Every
extension a build emits therefore gets its type from `WEB_MEDIA_TYPES` below,
on all three serving paths (`/`, the SPA fallback, and the `assets` mount).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from datasheet_analyzer.app.contracts import API_PREFIX
from datasheet_analyzer.config import Settings

log = logging.getLogger(__name__)

__all__ = [
    "ASSETS_DIRNAME",
    "INDEX_FILENAME",
    "WEB_DIST_ENV",
    "WEB_MEDIA_TYPES",
    "default_dist_dir",
    "mount_static",
    "web_media_type",
]

#: `vite.config.ts` sets `build.outDir` to `dist`; this is the other half of
#: that contract.
WEB_DIRNAME = "web"
DIST_DIRNAME = "dist"
INDEX_FILENAME = "index.html"
#: Vite writes hashed bundles here; served by `StaticFiles` so it gets
#: conditional requests and range handling for free.
ASSETS_DIRNAME = "assets"
#: Escape hatch for an install where the built UI is not beside the source
#: tree. Read from the environment rather than from `Settings` because
#: `config.py` is frozen by ticket 00 and carries no `web_dist` field.
WEB_DIST_ENV = "DSA_WEB_DIST"

#: The content type served for each extension a Vite build emits, keyed by a
#: lowercase suffix. This table exists *instead of* `mimetypes.guess_type`,
#: not beside it: `guess_type` reads `HKEY_CLASSES_ROOT` on Windows, so the
#: type a `.js` bundle is served with becomes a property of the machine
#: rather than of the build. `text/javascript` is the type the HTML standard
#: names for JavaScript; the charset suffix is left to `Response`, which
#: appends `; charset=utf-8` to every `text/*`.
WEB_MEDIA_TYPES: dict[str, str] = {
    ".css": "text/css",
    ".html": "text/html",
    ".ico": "image/vnd.microsoft.icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript",
    ".json": "application/json",
    ".map": "application/json",
    ".mjs": "text/javascript",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
    ".txt": "text/plain",
    ".wasm": "application/wasm",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def web_media_type(path: Path | str) -> str | None:
    """The content type for `path`'s extension, or `None` when unlisted.

    `None` means "not a kind this build serves by name" and leaves the
    response to its own default (`application/octet-stream`), which is the
    safe answer for a file whose type this module has never measured.
    """
    return WEB_MEDIA_TYPES.get(Path(path).suffix.lower())


class _TypedStaticFiles(StaticFiles):
    """`StaticFiles` with `WEB_MEDIA_TYPES` in place of the registry.

    `StaticFiles.file_response` builds a `FileResponse` without a media type,
    which makes `FileResponse` call `mimetypes.guess_type`. Overriding the
    header afterwards is the whole change; conditional requests, range
    handling and the 304 path stay Starlette's.
    """

    def file_response(
        self,
        full_path: os.PathLike[str] | str,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        media = web_media_type(full_path)
        if media is not None and "content-type" in response.headers:
            if media.startswith("text/"):
                media = f"{media}; charset={response.charset}"
            response.headers["content-type"] = media
        return response


def default_dist_dir() -> Path:
    """`<repo>/web/dist`, or `$DSA_WEB_DIST` when it is set.

    Derived from this file's location (`src/datasheet_analyzer/app/`) so the
    editable install every developer runs finds the build without
    configuration. Existence is not checked here — that is `mount_static`'s
    decision to report.
    """
    override = os.environ.get(WEB_DIST_ENV, "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / WEB_DIRNAME / DIST_DIRNAME


def mount_static(
    app: FastAPI,
    *,
    settings: Settings | None = None,
    dist_dir: Path | str | None = None,
) -> bool:
    """Serve `web/dist` at `/` with an SPA fallback; `False` when absent.

    `settings` is accepted because `main.py` passes it and a later ticket may
    want it; nothing here reads a corpus path.
    """
    del settings  # the frontend build location is not corpus state
    root = Path(dist_dir) if dist_dir is not None else default_dist_dir()
    index = root / INDEX_FILENAME
    if not root.is_dir():
        log.info("no built frontend at %s; serving %s/* only", root, API_PREFIX)
        return False
    if not index.is_file():
        log.warning("%s has no %s; frontend not served", root, INDEX_FILENAME)
        return False

    root = root.resolve()
    index = root / INDEX_FILENAME
    assets = root / ASSETS_DIRNAME
    if assets.is_dir():
        app.mount(f"/{ASSETS_DIRNAME}", _TypedStaticFiles(directory=assets), name="assets")

    api_root = API_PREFIX.strip("/")

    @app.get("/", include_in_schema=False)
    def _index() -> FileResponse:
        return FileResponse(index, media_type="text/html")

    @app.get("/{spa_path:path}", include_in_schema=False)
    def _spa(spa_path: str) -> FileResponse:
        # An unmatched API path is an API 404. Returning the shell here would
        # hand a `fetch` HTML where it expected JSON.
        if spa_path == api_root or spa_path.startswith(f"{api_root}/"):
            raise HTTPException(status_code=404, detail=f"no such endpoint: /{spa_path}")
        target = _safe_file(root, spa_path)
        if target is not None:
            return FileResponse(target, media_type=web_media_type(target))
        return FileResponse(index, media_type="text/html")

    app.state.web_dist = root
    log.info("serving built frontend from %s", root)
    return True


def _safe_file(root: Path, rel: str) -> Path | None:
    """The real file `rel` names inside `root`, or `None`.

    `None` means "not a file of this build" for every reason — outside the
    root, traversal, or simply absent — because each of them ends the same
    way: the SPA shell is served and the browser's router decides.
    """
    rel = (rel or "").strip().replace("\\", "/")
    if not rel or "\0" in rel:
        return None
    candidate = Path(rel)
    if rel.startswith("/") or candidate.is_absolute() or candidate.drive:
        return None
    if any(part == ".." for part in candidate.parts):
        return None
    target = (root / candidate).resolve()
    if target != root and root not in target.parents:
        return None
    return target if target.is_file() else None
