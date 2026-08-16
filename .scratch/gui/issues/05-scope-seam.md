# 05 — Extract `_scope`, add `serve`, add `SectionHit.as_dict`

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/retrieve/scope.py`
- `src/datasheet_analyzer/retrieve/results.py`
- `src/datasheet_analyzer/cli.py`
- `src/datasheet_analyzer/mcp_server/server.py`
- `pyproject.toml`
- `tests/unit/test_scope_seam.py`

**What to build:** Three small changes to the existing seam, grouped because
they are the only tickets that touch `cli.py` and `server.py` — no other agent
may open those files.

**1. One `_scope`, not three.** `cli.py::_scope` and
`mcp_server/server.py::_scope` are the same twenty lines: take a `part` and a
`project` string, enforce that exactly one is set, and return a `Retriever` or
a `ProjectRetriever`. The GUI would be the third copy. Move it to
`retrieve/scope.py` as `resolve_scope(part, project, *, settings) -> tuple[Retriever | ProjectRetriever | None, str]`
and have both callers delegate. The XOR precondition and its error text are
the invariant from ADR 0006 — the message explaining why "everything" is not a
default must survive the move verbatim, because it is the only place that
rationale is written down in code.

**2. `SectionHit.as_dict()`.** It is the one result type without a JSON view,
which makes it the one thing an adapter has to hand-serialize. Give it the
same treatment as its siblings: mirror `SearchHit.as_dict()`'s key set minus
the search-only fields (`score`, `snippet`, `terms`).

**3. `dsa serve` without `--mcp`.** Today `_cmd_serve` refuses unless `--mcp`
is passed. Add the plain form: bind `settings.serve_host` /
`settings.serve_port`, import the FastAPI app from
`datasheet_analyzer.app.main` lazily inside the handler, and run it with
uvicorn. Mirror the existing MCP branch's `ImportError` handling — print an
install hint naming the optional extra rather than a traceback, since the web
dependencies are optional the way `mcp` already is. Add `web` to
`[project.optional-dependencies]`.

- [ ] `resolve_scope` returns a `Retriever` for a built part and a `ProjectRetriever` for a project
- [ ] Passing both `part` and `project` returns `(None, reason)`; passing neither returns the same
- [ ] The XOR error text is unchanged from today's, character for character
- [ ] `cli.py` and `mcp_server/server.py` both call `resolve_scope` and define no local copy
- [ ] Every existing CLI and MCP test still passes untouched — this is a refactor, not a behaviour change
- [ ] `SectionHit.as_dict()` returns `section, title, file, part, doc, page_start, page_end, citation, matched_via, confidence`
- [ ] `SectionHit.as_dict()` is exercised by a test asserting the exact key set, matching how `SearchHit`'s is tested
- [ ] `dsa serve` with no flags starts the app on the configured host and port
- [ ] `dsa serve --mcp` behaves exactly as before
- [ ] `dsa serve` without the web extra installed prints an install hint and exits 2, never a traceback
- [ ] The server is bound to `127.0.0.1` by default — a local single-user tool must not listen on all interfaces
- [ ] Tests assert the CLI wiring without starting a real server (patch the runner)
