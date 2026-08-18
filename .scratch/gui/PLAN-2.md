---
title: GUI round 2 — make the shelf legible and the project the starting point
labels: [ready-for-agent]
---

# Why

The engine already caches correctly. `.cache/extract/<hash>__<backend>.json`,
`parts/<PART>/` and `library/<hash>.json` all persist, and `app/jobs.py` calls
`batch.skip_reason` — the same gate `dsa batch` uses — so a re-analyze of an
unchanged directory is near-free and emits `JobState.SKIPPED`.

**None of that is visible.** A scan of a directory whose PDFs are all built
returns proposals indistinguishable from forty new ones: `DocProposal` carries
`content_hash`, so the backend knows, and the review screen never asks. The
user cannot tell "nothing to do" from "three hours of work", so they hesitate
over a button that would have cost nothing.

The second problem is ordering. A project is the last thing the UI lets you
choose when it should be the first: you pick a directory, build, go to
Library, and only then select a working set. Nothing records that the folder
and the project are the same thing — recent directories live in browser
`localStorage`, so they die with the browser cache and the server never learns
them.

Five tickets. 26 fixes the trust problem, 27 fixes the ordering problem, and
the rest fall out of those two.

| # | Ticket | Owns (primary) |
|---|---|---|
| 26 | Scan says what it already knows | `app/buildstate.py`, `app/routers/review.py`, `app/contracts.py` |
| 27 | The working set is app-wide | `web/src/shell/workingSet.tsx`, `web/src/routes/chat/**` |
| 28 | A project remembers its directory | `models.py`, `projects/store.py`, `app/routers/projects.py` |
| 29 | Analyze collapses when there is nothing to do | `web/src/routes/analyze/**` |
| 30 | Build an unbuilt part where you meet it | `web/src/routes/library/**` |

## Rules

1. Never edit `extract/pdf_layout.py`; never bump `output_version`. The
   extraction cache must stay valid.
2. Tests hermetic: no network, no live model, no subprocess, no browser.
3. `SourceDocument` keeps its shape.
4. ADR 0006 holds: scope is resolved, **shown**, and editable. A working set
   may supply a scope; it may never hide which scope an answer used.
5. `ruff check` and `npm run typecheck` clean; every acceptance box a real test.
