# 28 — A project remembers the directory it came from

**Owns:** `src/datasheet_analyzer/models.py` (Project only),
`src/datasheet_analyzer/app/routers/projects.py`,
`src/datasheet_analyzer/app/contracts.py` (project models only),
`web/src/api/client.ts`, `web/src/api/types.ts`,
`tests/unit/test_projects_api.py`

**Problem.** "A directory of datasheets" *is* the project, but the association
lives in browser `localStorage` — it dies with the cache and the server never
learns it. Reopening means retyping a path.

**Build.** `Project.directory: str = ""`, additive, absolutized nowhere (it is
a server-side path recorded verbatim, exactly as `ScanIn.directory` is given).
`PATCH /api/projects/{name}` with `ProjectPatchIn{directory?, interfaces?, notes?}`.

An old `project.json` without the field must load and read `""`.

- [ ] A project round-trips its directory through save and load
- [ ] A `project.json` written before this ticket still loads, with `directory == ""`
- [ ] PATCH sets the directory and leaves parts, interfaces and notes alone
- [ ] PATCH on an unknown project is a 404 naming it
- [ ] The response is the shape a later GET returns
