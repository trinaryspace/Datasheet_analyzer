# 15 — Session persistence and export

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/sessions.py`
- `src/datasheet_analyzer/app/routers/sessions.py`
- `tests/unit/test_sessions.py`

**What to build:** Conversations survive a restart, and an answer can leave the
application. `SessionStore` persists a `ChatSession` — its messages, their
citations, and the scope each was answered under — as one JSON file per session
under `settings.sessions_dir`. Ticket 12 appends to it; this ticket owns the
storage and the HTTP surface.

Export is the point, not a convenience. A verified answer is the artifact a
user pastes into a design review, so `GET /api/sessions/{id}/export` returns
markdown with the claim, its citation in the repo's own `§4.5, p.7` form, and
the part it was answered under. Reuse `Citation.label` rather than formatting
citations here — `Citation.label` deliberately omits the part because printing
it is the front end's job, so the exporter is the thing that adds it back.

There is a second payoff worth building for. AGENTS.md invariant 5 makes golden
Q&A the objective function, and an exported session is nearly a
`tests/fixtures/golden_qa_<PART>.yaml` entry already: a question, an expected
substring, and the pages it should cite. Emit a second export format keyed to
that shape so a confirmed answer can become a regression test.

Writes are atomic and Windows-safe (temp then `.replace()` with a
`PermissionError` retry), matching the pattern in `pipeline.py`. Session ids
are opaque and generated server-side; a client-supplied id is never used as a
filename.

- [ ] `POST /api/sessions` creates a session and returns its id
- [ ] `GET /api/sessions` lists sessions newest first with title, scope and message count
- [ ] `GET /api/sessions/{id}` returns the full transcript with citations intact
- [ ] A session round-trips through disk with citations, scope and timestamps unchanged
- [ ] Appending a message updates `updated_at` and leaves earlier messages untouched
- [ ] `GET /api/sessions/{id}` on an unknown id returns 404
- [ ] Markdown export contains each answer, its citations in `§4.5, p.7` form, and the part it was answered under
- [ ] The golden-Q&A export emits `id`, `question`, `expected_substrings` and `pages` matching the existing fixture schema
- [ ] Exporting a session with no assistant messages produces a valid empty document, not an error
- [ ] A client-supplied session id cannot influence the filename written
- [ ] Writes are atomic; no `.tmp` file survives a successful save
- [ ] A malformed session file is skipped in listings with a warning rather than failing the whole list
- [ ] Tests use `Settings(sessions_dir=tmp)`; no network
