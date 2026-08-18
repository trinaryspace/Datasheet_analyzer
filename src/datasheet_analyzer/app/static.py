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
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from datasheet_analyzer.app.contracts import API_PREFIX
from datasheet_analyzer.config import Settings

log = logging.getLogger(__name__)

__all__ = [
    "ASSETS_DIRNAME",
    "INDEX_FILENAME",
    "WEB_DIST_ENV",
    "default_dist_dir",
    "mount_static",
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
        app.mount(f"/{ASSETS_DIRNAME}", StaticFiles(directory=assets), name="assets")

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
            return FileResponse(target)
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
