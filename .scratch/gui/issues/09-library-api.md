# 09 — Library and label endpoints

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/routers/library.py`
- `tests/unit/test_library_api.py`

**What to build:** Read the whole library and correct it by hand. `GET
/api/library` lists every `LibraryDocument` with its applicability, its labels,
and which parts it currently reaches. `PATCH /api/library/{content_hash}`
changes applicability, labels, or both.

This is the only user-writable surface in the application — everything else in
the corpus is derived from the PDFs and must stay reproducible. Labels are
free text; applicability is validated against the `Applicability` model, so a
`kind="parts"` patch with an empty `parts` list is a 400, not a silently
inert write.

Two behaviours matter more than they look:

- **A patch that widens applicability may name a part that does not exist
  yet.** That is legal and intended (ADR 0005): the part comes into existence
  with that document as its corpus. Return the affected part list in the
  response so the UI can say what just changed, and mark parts that have no
  manifest as unbuilt rather than rejecting them.
- **A patch never triggers a rebuild.** Changing applicability changes which
  parts a document *reaches*; materializing that into `parts/` is a build's
  job. The response carries a `rebuild_needed` list so the UI can offer it.

- [ ] `GET /api/library` returns every document with applicability, labels, and the parts it reaches
- [ ] `GET /api/library` on an empty library returns an empty list with 200
- [ ] `PATCH` with only `labels` leaves applicability untouched, and vice versa
- [ ] `PATCH` with both changes both in one write
- [ ] `PATCH` on an unknown `content_hash` returns 404
- [ ] `PATCH` with `kind="parts"` and an empty `parts` list returns 400
- [ ] `PATCH` with `kind="family"` and a blank `family` returns 400
- [ ] A patch naming an unbuilt part succeeds and reports that part as unbuilt
- [ ] The response lists the parts affected by the change and which need a rebuild
- [ ] No patch writes to `parts/` or the extraction cache
- [ ] Labels survive a subsequent `LibraryStore.put()` for the same document (assert via the store's contract, not its implementation)
- [ ] Tests use a fake `LibraryStore` through `dependency_overrides`; no network
