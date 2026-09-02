# This branch is superseded. Do not merge it.

`feat/phase7-reach-trust` is closed. Everything it built for **Phase 7** now
lives on `feat/gui-workbench`, ported commit by commit and re-measured there.
Nothing here is lost; nothing here should be merged.

This file is the only change in this commit. No code on this branch was
touched, and the branch is kept rather than deleted so the original work — and
the reports written against it — stay readable.

## Why it may not be merged

The two branches share a merge base (`4d413ee`) and then implemented **Phase 6
twice, differently**. Thirteen of this branch's twenty-nine commits are that
second Phase 6, and it landed as separate top-level packages:

| here (`feat/phase7-reach-trust`) | there (`feat/gui-workbench`) |
|---|---|
| `src/datasheet_analyzer/cards/` | `src/datasheet_analyzer/derive/cards.py` |
| `src/datasheet_analyzer/compare/` | `src/datasheet_analyzer/derive/compare.py` |
| `src/datasheet_analyzer/provenance.py` | `src/datasheet_analyzer/derive/provenance.py` |
| — | `src/datasheet_analyzer/app/` and `web/`, the local workbench, which this branch has never seen |

Measured with `git merge-tree --write-tree` on 2026-09-01: **94 files
conflict**, across `src/datasheet_analyzer/` (retrieve, families, evalh,
errata, audit, revdiff, registry, acquire, structure, extract, publish,
mcp_server and the top-level modules), `tests/unit`, `tests/integration`, and
every root document. An earlier reading, taken before the port began, counted
161. Either number says the same thing: this is not a merge that can be
resolved row by row. Resolving it would mean picking one Phase 6 layout and
rewriting the other branch's half against it.

So the features were **ported**, not merged: each one reimplemented against
`derive/`, its tests rewritten to that repository's committed corpora, and
every number in its report re-measured rather than copied.

## Where the work went

Twenty-four commits on `feat/gui-workbench`, `fa16550`…`47a3ef4`:

| here | there | what moved |
|---|---|---|
| — | `fa16550`, `54a100e` | the shared seam: the `models.py` / `config.py` additions everything else lands on, stopped where that branch freezes `SourceDocument` at ten fields |
| `39b5af5` (p7-01), `f32d9a9` (p7-02) | `cf5e597`, `5ef3fb1`, `b924f09`, `efcb893`, `ebfb443` | the document registry, `dsa fetch`, `staleness.py`, revision awareness, `dsa check-revisions` |
| `2d5a43b` (p7-03), `e6a6649` (p7-04) | `cfb4dd1`, `9137e2e`, `4287c1d`, `cf894d3` | `revdiff/` + `dsa diff-rev`, and errata cross-linking |
| `fed4d26` (p7-05), `9be58d5` (p7-06) | `732d2bd`, `df78104`, `e7c25d6`, `1306f9f`, `6c33e8a`, `20e969d` | `audit/` + `dsa audit`, and golden suggest/confirm |
| `3022f28` (p7-07) | `3e89c37`, `28f1a49`, `32198bd`, `78384f0`, `35fc89c`, `524257e`, `47a3ef4` | `families/` + `dsa family`, and the `key_for=` hook that lets one alignment engine serve both `dsa compare` and a family index |

An eighth wave closed the seams those four batches left — `ae5f93a`,
`b8c8dfe`, `f99ba58`, `e8c0cb8`, `6eafb8a`, `a9acb68`, `96f7379`, `89ef22a`:
the three MCP tools this branch shipped or implied (`get_audit`,
`list_families`, `get_family_index`), the family scope and `RevisionState` on
the workbench HTTP surface, the two decisions this branch left open, and the
new verbs written into `protocol.py` so `AGENT.md` and the checked-in skill
name them.

## What the port did not carry over, deliberately

The port re-measured every claim rather than trusting the reports written
here, and three did not reproduce on that tree. They are recorded in
`47a3ef4`, not silently corrected:

- "619 of 619 AFE7950 spec records carry no addressable record id" is false
  there; all 619, and all 536 of AFE7953's, carry one.
- The hand-verified family delta `IVDD1P8 / 12.6 vs 16 mA` does not exist
  there: both members print that group under different operating modes, so
  nothing pairs on the printed row.
- "83 aligned rows on the alias key vs 318 on the printed-row key" measured
  **408** and **763**.

That is the reason to read this branch's `Reports/` as history rather than as
current fact. `Reports/PHASE_7_REPORT.md` on `feat/gui-workbench` is the one
that describes a tree which exists, and it carries the integration section and
both gate readings.

## If you are here to get something

Take it from `feat/gui-workbench`. If something Phase 7 built really is
missing there, port that one thing against `derive/` the way the commits above
did — do not merge this branch to get it.
