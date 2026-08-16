# 06 — App skeleton and dependency wiring

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/deps.py`
- `src/datasheet_analyzer/app/routers/catalog.py`
- `src/datasheet_analyzer/app/static.py`
- `tests/unit/test_app_deps.py`

**What to build:** The dependency providers every router injects, the two
catalog endpoints, and static-file serving for the built frontend. `app/main.py`
already exists from ticket 00 and auto-discovers routers — **do not edit it**.

`deps.py` implements the providers stubbed in 00:

- `get_settings_dep()` → the cached `Settings`
- `get_library()` → a `LibraryStore` built from settings
- `get_retriever(scope: ScopeRef)` → delegates to
  `retrieve.scope.resolve_scope` (ticket 05) and raises a 400 carrying the
  refusal text when the scope is invalid — the GUI must not invent its own
  scope rules
- `get_job_registry()` → the process-wide registry ticket 07 fills in
- `get_session_store()` → ticket 15's store

Each provider is a plain callable suitable for FastAPI `Depends`, and each is
overridable in tests via `app.dependency_overrides` — that overridability is
what lets tickets 07–15 test their routers against fakes without importing
each other's implementations.

`routers/catalog.py` serves `GET /api/parts` and `GET /api/projects` using
`retrieve.index.discover_parts()` and `projects.store.list_projects()`. Parts
include half-built ones, because `discover_parts` deliberately lists them and
the UI needs to show a part that has no manifest yet.

`static.py` mounts `web/dist` at `/` when it exists, with an SPA fallback so a
deep link like `/chat/abc` serves `index.html` rather than 404. When
`web/dist` is absent — a dev running Vite separately — mounting is skipped
silently and only `/api/*` is served.

- [ ] Every provider in `deps.py` is importable and returns the right type
- [ ] `get_retriever` returns a `Retriever` for a part scope and a `ProjectRetriever` for a project scope
- [ ] `get_retriever` with an unknown part raises a 400 whose body carries the scope refusal text, not a 500
- [ ] Every provider is overridable through `app.dependency_overrides` in a `TestClient`
- [ ] `GET /api/parts` lists built and half-built parts, and marks which is which
- [ ] `GET /api/parts` on an empty `parts_dir` returns an empty list with 200, not 404
- [ ] `GET /api/projects` lists projects and returns an empty list when `projects_dir` does not exist
- [ ] Both responses validate against their `app/contracts.py` models
- [ ] `web/dist` present → `/` serves `index.html` and a deep link falls back to it
- [ ] `web/dist` absent → the app still starts and `/api/parts` works
- [ ] `app/main.py` is not modified by this ticket
- [ ] Tests use `TestClient` with a temp `parts_dir`; no network, no LLM, no browser
