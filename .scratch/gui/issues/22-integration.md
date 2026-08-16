# 22 — End-to-end integration

**Wave:** 2
**Blocked by:** 00–21
**Status:** ready-for-agent

**Owns:**
- `tests/integration/test_gui_e2e.py`
- integration-level fixes anywhere (this ticket alone may cross ownership lines)

**What to build:** Prove the twenty-one parallel tickets compose. Every wave-1
agent verified its own module against fakes and frozen signatures; nobody has
yet run the real pieces against each other, so this is where contract drift
surfaces.

Run the full suite (`pytest -q` — 342 existing tests plus everything new),
`ruff check` over the repo, and `npm run typecheck && npm test` in `web/`.
**Fix integration-level breakage only.** A module that fails its own unit test
is that ticket's bug, not yours: record it and re-dispatch rather than
rewriting someone's implementation from the outside.

The end-to-end test is one hermetic pass through the whole path, with synthetic
PDFs built by `fitz` and a fake LLM client:

1. Build a directory holding three PDFs — a datasheet for `AD9081`, a register
   map for `AD9081`, and an app note whose text names `AFE7950` and `AFE7952`.
2. `POST /api/analyze/scan` → three proposals with the right parts and a
   family or multi-part applicability on the app note.
3. `POST /api/analyze/start` → drive to completion, asserting the event
   sequence.
4. Assert the app note was **published once** and is referenced by both parts,
   and that `AFE7952` exists as a part whose corpus is only the app note.
5. `POST /api/chat/resolve-scope` with a question naming `AD9081` → confident.
6. Send the question with a scripted fake model that calls `find_spec` → assert
   the streamed events, and that the citation came from a real tool result.
7. `GET /api/locate` for that citation → assert a rect on the right page.
8. Export the session → assert both formats.

Then the regressions that matter most, because they are the ones this design
put at risk:

- An existing `.cache/extract/*.json` fixture still deserializes into a
  `RawDocument`. If this fails, `SourceDocument` changed shape and the whole
  cache is invalid.
- `PdfLayoutBackend.output_version` is still `"tables-07"`.
- The existing golden Q&A for `AFE7950` still passes.
- `dsa build`, `dsa batch`, `dsa query`, `dsa plots`, `dsa status`, `dsa verify`
  and `dsa serve --mcp` all still work.

- [ ] Full `pytest -q` green, including all 342 pre-existing tests
- [ ] `ruff check` and `ruff format --check` clean repo-wide
- [ ] `npm run typecheck` and `npm test` green in `web/`
- [ ] The eight-step end-to-end path passes hermetically — no network, no live model, no browser
- [ ] The app note is published once and referenced by both parts
- [ ] `AFE7952` exists with the app note as its whole corpus
- [ ] A cached `RawDocument` fixture still deserializes
- [ ] `output_version` is unchanged
- [ ] The `AFE7950` golden Q&A still passes
- [ ] Every existing CLI subcommand still works, `serve --mcp` included
- [ ] A report naming every ticket whose module failed its own tests, with the failure, so it can be re-dispatched rather than patched here
- [ ] Any file touched outside this ticket's ownership is listed in the report with the reason
