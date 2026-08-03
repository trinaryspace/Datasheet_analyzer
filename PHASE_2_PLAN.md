# Phase 2 Plan — `specs.json`: the Verified Structured Part Model

**Status: completed — shipped. This contract is superseded by
`PHASE_2_REPORT.md` (measured results, acceptance criteria, test mapping).**

Phase 2 turned the span-expanded parametric tables into a deterministic,
machine-queryable `specs.json` per document plus a `dsa query` interface.

## What shipped

- `specs.json` in `docs/<doc>/` for every `ti_html` document (AFE7950: 619
  records across 11 `parametric` + 1 `info` tables, **0 unmapped headers**;
  AFE7953 replicated with 536 records). `pdf_text` documents emit none.
- `dsa query --part <PART> --symbol|--name|--section ...` — deterministic,
  AND-ed case-insensitive substring filters; answers carry verbatim values,
  units, conditions, footnote markers, and page cites (~2.5k tokens/question).
- Golden Q&A grew from 12 to 16 questions; `dsa verify --specs` checks the
  12 spec-query paths deterministically.
- Explicitly out of scope: float parsing/numeric comparison, LLM name
  normalization, cross-part comparison, fleet manifest, specs from `pdf_text`.

## Original contract (kept for the record)

Transform the 15 span-expanded tables (already extracted with conditions,
footnotes, and page refs) into a normalized, machine-queryable model —
a **pure transform** over `TableBlock.grid`, no new extraction risk: header
roles via `structure/roles.py`, unit canonicalization via
`structure/units.py` (U+2126 → ohm), records via `structure/specs.py`,
lookup via `query.py`, wired into `pipeline.py` and `cli.py` (`dsa query`,
`dsa verify --specs`).