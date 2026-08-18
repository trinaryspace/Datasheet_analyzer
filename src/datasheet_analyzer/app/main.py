"""The FastAPI application: built once here, extended only by adding files.

`create_app()` **auto-discovers routers**. Every `app/routers/*.py` that
exposes a module-level `router` is imported and included, so a ticket adding
an endpoint group adds one file and edits nothing shared. This file is
written once, by ticket 00, and no later ticket modifies it — a router
registry that every ticket must edit is a merge conflict with twenty-one
authors, and route discovery costs one directory listing at startup.

The frontend is mounted the same way: if `app/static.py` (ticket 06) is
importable and exposes `mount_static(app, settings=...)`, it is called last,
after the API routes, so `/api/*` always wins over the SPA fallback. A dev
running Vite separately has no `web/dist`; mounting is then skipped and only
`/api/*` is served.

A router module that fails to import does not take the whole application
down: the failure is logged and recorded in `app.state.router_errors`, so a
half-finished module is visible as one broken endpoint group rather than as
a server that will not start. Nothing is swallowed silently.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from fastapi import FastAPI

from datasheet_analyzer.config import PIPELINE_VERSION, Settings, get_settings

log = logging.getLogger(__name__)

APP_TITLE = "datasheet-analyzer"
APP_DESCRIPTION = (
    "Local workbench for a citation-verified datasheet corpus: analyze a "
    "directory of PDFs, ask questions in plain language, and verify every "
    "answer against the printed page."
)

#: Where `discover_routers` looks. One module per endpoint group.
ROUTERS_PACKAGE = "datasheet_analyzer.app.routers"


def discover_routers() -> tuple[list[object], dict[str, str]]:
    """Import every `app/routers/*.py` and return their `router` objects.

    Returns `(routers, errors)` where `errors` maps a module name to the
    import failure that kept it out — reported rather than hidden, and
    surfaced on `app.state.router_errors`.
    """
    routers: list[object] = []
    errors: dict[str, str] = {}
    importlib.invalidate_caches()
    package = importlib.import_module(ROUTERS_PACKAGE)
    names = sorted(
        info.name
        for info in pkgutil.iter_modules(package.__path__)
        if not info.ispkg and not info.name.startswith("_")
    )
    for name in names:
        qualified = f"{ROUTERS_PACKAGE}.{name}"
        try:
            module = importlib.import_module(qualified)
        except Exception as exc:  # noqa: BLE001 - one bad router is not fatal
            errors[name] = f"{type(exc).__name__}: {exc}"
            log.warning("router %s failed to import: %s", qualified, exc)
            continue
        router = getattr(module, "router", None)
        if router is None:
            errors[name] = "module exposes no `router`"
            log.warning("router module %s exposes no `router`; skipped", qualified)
            continue
        routers.append(router)
    return routers, errors


def _mount_static(app: FastAPI, settings: Settings) -> bool:
    """Serve the built frontend, when ticket 06's `static.py` is present."""
    try:
        from datasheet_analyzer.app import static as static_module
    except ImportError:
        return False
    mount = getattr(static_module, "mount_static", None)
    if not callable(mount):
        log.warning("app.static exposes no callable `mount_static`; frontend not served")
        return False
    return bool(mount(app, settings=settings))


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application: every discovered router, then the frontend.

    Takes its settings by argument for the same reason the pipeline and the
    MCP server do — a test points one app at a temporary corpus tree without
    touching the environment.
    """
    settings = settings or get_settings()
    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=PIPELINE_VERSION,
    )
    app.state.settings = settings
    routers, errors = discover_routers()
    for router in routers:
        app.include_router(router)
    app.state.router_errors = errors
    app.state.static_mounted = _mount_static(app, settings)
    return app


#: Module-level instance for `uvicorn datasheet_analyzer.app.main:app` and for
#: `dsa serve` (ticket 05), which imports this module lazily so a plain
#: install without the `web` extra never pays for FastAPI.
app = create_app()
