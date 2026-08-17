---
title: GUI execution plan — contracts-first, 21-way parallel
labels: [ready-for-agent]
---

# Execution plan

23 tickets in three waves. One ticket freezes every contract; twenty-one then
run **concurrently with zero coordination**; one integrates. No ticket asks a
human anything — every design decision is already made and recorded in
`SPEC.md`, `docs/adr/0005-documents-apply-to-parts.md` and
`docs/adr/0006-auto-resolved-scope.md`.

## Why this is safely parallel

Two rules do all the work.

**1. Contracts are frozen before any implementation.** Ticket 00 writes every
type, every endpoint request/response model, every function signature, and the
TypeScript mirror of all of it. Nothing in wave 1 negotiates an interface with
anything else in wave 1 — each ticket codes against a signature that already
exists on disk, and tests against fakes it constructs itself.

**2. Every file has exactly one owner.** The `Owns:` field on each ticket is
exclusive. Two wave-1 agents never open the same file, so they can share one
working tree with no merge step and no lock. Where a shared file would
normally be the coordination point, the design removes the sharing instead:

| Would-be contention | Removed by |
|---|---|
| `app/main.py` registering each router | `main.py` auto-discovers `app/routers/*.py` and includes each module's `router`. Written once in 00; never edited again. |
| `web/src/App.tsx` registering each route | File-based route discovery via Vite `import.meta.glob`. Written once in 00. |
| `models.py` gaining fields from several tickets | All model additions land in 00. |
| `config.py` gaining settings from several tickets | All settings land in 00. |
| `pipeline.py` and `publish/writer.py` changing together | 00 freezes `write_corpus`'s new signature; ticket 03 writes the caller, ticket 04 writes the callee. |
| `cli.py` gaining `serve` and losing `_scope` | Both edits belong to ticket 05 alone. |

## The constraint that shapes the data model

`SourceDocument` is embedded in `RawDocument`, and `RawDocument` is what
`.cache/extract/<hash>__<backend>.json` serializes. **Changing
`SourceDocument`'s shape invalidates every cached extraction** — adding a
required field breaks validation of existing cache files, and the cache is the
most expensive thing in the repo to rebuild.

Therefore applicability and labels are **not** fields on `SourceDocument`. They
live on a `LibraryDocument` that wraps it:

```
LibraryDocument
├── source: SourceDocument      # unchanged, still cache-compatible
├── applicability: Applicability
└── labels: list[str]
```

`SourceDocument.part_number` keeps its current meaning — the part a document
was registered under — and becomes advisory rather than authoritative.
`PdfLayoutBackend.output_version` is **not** bumped by any ticket in this plan.

## Waves

```
wave 0        wave 1  (21 agents, no ordering between them)        wave 2
┌──────┐      ┌──────────────────────────────────────────┐        ┌──────┐
│  00  │─────▶│ 01 02 03 04 05 06 07 08 09 10 11         │───────▶│  22  │
│ con- │      │ 12 13 14 15 16 17 18 19 20 21            │        │ e2e  │
│tracts│      └──────────────────────────────────────────┘        └──────┘
└──────┘
```

| Wave | Tickets | Agents | Gate to advance |
|---|---|---|---|
| 0 | 00 | 1 | `pytest tests/unit/test_contracts.py -q` green; `npm run typecheck` green |
| 1 | 01–21 | 21 | every ticket's own test file green |
| 2 | 22 | 1 | full `pytest -q` green (342 existing + new); `ruff check` clean |

## Ticket index

| # | Ticket | Lane | Owns (primary) |
|---|---|---|---|
| 00 | Freeze contracts | core | `models.py`, `config.py`, `app/contracts.py`, `web/` scaffold, `web/src/api/types.ts` |
| 01 | Library store and labels | pipeline | `library/store.py` |
| 02 | Part number and applicability inference | pipeline | `acquire/applicability.py` |
| 03 | Library-backed acquire | pipeline | `acquire/inventory.py`, `pipeline.py` |
| 04 | Publish once, reference many | pipeline | `publish/writer.py`, `publish/plots.py` |
| 05 | Extract `_scope`, add `serve`, `SectionHit.as_dict` | seam | `cli.py`, `retrieve/scope.py`, `retrieve/results.py`, `mcp_server/server.py` |
| 06 | App skeleton and dependency wiring | backend | `app/main.py`, `app/deps.py` |
| 07 | Analyze jobs and progress stream | backend | `app/jobs.py`, `app/routers/analyze.py` |
| 08 | Review endpoints | backend | `app/routers/review.py` |
| 09 | Library and label endpoints | backend | `app/routers/library.py` |
| 10 | Scope resolver | backend | `app/scope_resolver.py` |
| 11 | Agent tool functions | backend | `app/tools.py` |
| 12 | Chat loop and token stream | backend | `app/chat.py`, `app/routers/chat.py` |
| 13 | Locate a citation on the page | backend | `app/locate.py`, `app/routers/locate.py` |
| 14 | PDF byte serving | backend | `app/routers/pdf.py` |
| 15 | Session persistence and export | backend | `app/sessions.py`, `app/routers/sessions.py` |
| 16 | App shell, theme, layout | frontend | `web/src/shell/**` |
| 17 | Analyze and review screens | frontend | `web/src/routes/analyze/**` |
| 18 | Chat pane | frontend | `web/src/routes/chat/**` |
| 19 | PDF pane and highlight overlay | frontend | `web/src/routes/pdf/**` |
| 20 | Library, labels and sessions screens | frontend | `web/src/routes/library/**` |
| 21 | Documentation and hygiene | docs | `CONTEXT.md`, `AGENTS.md`, `README.md`, `.gitignore` |
| 22 | End-to-end integration | integration | `tests/integration/test_gui_e2e.py` |

## Rules every wave-1 agent follows

1. **Touch only the files in your `Owns:` list.** If you believe you need a
   file you do not own, you have found a contract gap — record it in your
   ticket's notes and code against the frozen signature anyway. Do not edit it.
2. **Never edit `src/datasheet_analyzer/extract/pdf_layout.py`** or bump
   `output_version`. The extraction cache must stay valid.
3. **Run only your own test file** (`pytest tests/unit/test_<module>.py -q`).
   The full suite is wave 2's job; running it concurrently wastes minutes and
   surfaces other agents' in-flight work as false failures.
4. **Tests are hermetic** — no network, no live model, no subprocess, no
   browser. Build synthetic PDFs in-test with `fitz`, use a fake LLM client,
   and set `Settings(parts_dir=tmp, cache_dir=tmp, ...)` with the
   `reset_settings_cache` hook. This is AGENTS.md invariant 4 and it is not
   negotiable.
5. **Honour the invariants.** No model call in a derivation path. Provenance on
   every content element. Unpinned stays honestly `None` — never guessed.
6. **`ruff check <your files>` and `ruff format <your files>`** before you
   finish. Line length 100, target py310.

## Suggested workflow script

Shared working tree, no worktree isolation — file ownership is disjoint, so
there is nothing to merge. Reserve `isolation: 'worktree'` for a re-run where
you suspect an ownership violation.

```js
export const meta = {
  name: 'gui-build',
  description: 'Build the datasheet workbench: contracts, then 21 parallel tickets, then integration',
  phases: [
    { title: 'Contracts' },
    { title: 'Build' },
    { title: 'Integrate' },
  ],
}

const TICKETS = [
  '01-library-store', '02-applicability-inference', '03-library-backed-acquire',
  '04-publish-shared-docs', '05-scope-seam', '06-app-skeleton',
  '07-analyze-jobs', '08-review-api', '09-library-api', '10-scope-resolver',
  '11-agent-tools', '12-chat-stream', '13-locate', '14-pdf-serve',
  '15-sessions', '16-fe-shell', '17-fe-analyze', '18-fe-chat',
  '19-fe-pdf', '20-fe-library', '21-docs',
]

const brief = (id) => `Read .scratch/gui/issues/${id}.md and implement it exactly.
Also read .scratch/gui/PLAN.md ("Rules every wave-1 agent follows") and
.scratch/gui/SPEC.md for the decisions behind the ticket.
Touch ONLY the files in the ticket's Owns list. Do not edit
src/datasheet_analyzer/extract/pdf_layout.py or bump output_version.
Every acceptance checkbox must be satisfied by a real, hermetic test.
Run only your own test file, plus ruff on your own files.
Return: files created/modified, the test command you ran and its result, and
any contract gap you had to code around.`

phase('Contracts')
await agent(`Read .scratch/gui/issues/00-contracts.md and implement it exactly.
This ticket freezes every interface the other 21 tickets code against — a
missing or wrong signature here blocks all of them, so be exhaustive.
${brief('00-contracts').split('\n').slice(2).join('\n')}`,
  { label: 'contracts', effort: 'xhigh' })

phase('Build')
const built = await parallel(TICKETS.map(id => () =>
  agent(brief(id), { label: id, phase: 'Build' })))

phase('Integrate')
const report = await agent(`Read .scratch/gui/issues/22-integration.md and
implement it. ${built.filter(Boolean).length} of ${TICKETS.length} build
tickets reported completion. Run the FULL suite (pytest -q) and ruff over the
whole repo, fix integration-level breakage only, and report what is red and
why.`, { label: 'integrate', effort: 'xhigh' })

return report
```

## What this plan does not do

- It does not implement part families, a document registry, an "all parts"
  scope, embedding search, or curve digitization. All are out of scope per
  `SPEC.md`.
- It does not merge `feat/phase5-retrieval`. Every ticket assumes `retrieve/`,
  `projects/`, `publish/search_index.py` and `mcp_server/` are present. **Land
  that branch before starting wave 0.**
- It does not touch the extraction layer at all.
