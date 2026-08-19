---
title: Extraction fidelity — read the page correctly
labels: [ready-for-agent]
---

**Execution contract:** `Reports/PHASE_6_5_PLAN.md`. This file is the tracker
root. **Depends on Phase 6** (`.scratch/design-time-content/`): every defect
here was found by a Phase 6 gate and is recorded with a measured number in
`KNOWN_SHORTCOMINGS.md`.

## Problem Statement

Phase 6 shipped 8/8 on its acceptance gate and parked one component, and the
ten shortcomings it recorded have remarkably few root causes. Six of the ten
trace to two files; the largest four trace to `extract/pdf_layout.py` alone.

The derive layer is not what is failing. Where a table reaches it, it reads it
correctly — ticket 06 measured 100% precision on every bit field it was handed
and refused every table it could not trust. What is failing is the layer
underneath, and the honest refusals Phase 6 built are what made that visible
instead of letting wrong values through.

Concretely: a furniture detector classifies a register map's first body row as
page machinery and the whole 35-row summary disappears; row reconstruction
inherits a previous row's first cell, so HMC520A's pin table fails its
duplicate-key check and 24 real pins are lost; HTML-derived tables cite the
page their table *started* on; and spec record ids collide within a document,
so AD9081's interface card publishes 1 of the 21 rows its selectors match.

## Solution

Fix the floor, then rebuild once. Nothing here is a new capability: no new
artifact, no new CLI verb, no new MCP tool. The output is the same artifacts,
measurably more correct.

The plan's shape is forced by one constraint. `PdfLayoutBackend.output_version`
participates in the extraction cache key, and `SPECS_SCHEMA_VERSION`
invalidates every citation already written. So every cache-invalidating change
lands in **one** wave and the corpus is rebuilt **once**, at the end. The
cheap fixes that touch neither are separated into wave 0 and land immediately.

## User Stories

1. As an agent, I want `dsa <verb> --json` to emit JSON and nothing else, so I
   can pipe it without a sanitising step that silently hides real errors.
2. As a designer, I want the axis filters the plan advertised (`--near-x
   3.5GHz --y-label Gain`) to work from the CLI and not only from MCP.
3. As a designer, I want a card whose document has moved to be rebuilt rather
   than served with citations that no longer resolve.
4. As a firmware engineer, I want `dsa regs --part LMX1204` to return all 35
   registers the document prints in its own summary table.
5. As a firmware engineer, I want bit fields to be *present* as well as
   correct — Phase 6 gave me correctness at 11% recall.
6. As a designer doing schematic capture, I want HMC520A's 24 pins, and I want
   the duplicate-key refusal that currently hides them to keep protecting me
   once the upstream misread is fixed.
7. As a reader, I want a row's citation to name the page that row is printed
   on, because a citation that is nearly right is the one I will not check.
8. As a designer, I want AD9081's interface card to publish the JESD204B/C
   rates its selectors already match instead of refusing them for an id clash.

## Waves

| Wave | Tickets | Rebuild | Gate to advance |
|---|---|---|---|
| 0 | 01–04 | no | each ticket's own test green; full suite unchanged |
| 1 | 05–08 | yes, once | each unit gate green against synthetic fixtures |
| 2 | 09 | — | full re-extract + rebuild, every Phase 6 gate re-measured |

**Wave 1 must land as a single cache-invalidating change.** Splitting it costs
a full re-extraction per split and buys nothing.

## Ownership

Phase 6 shipped ten tickets with no exclusive-ownership lists and four of them
would have written `cli.py` concurrently. Every ticket here carries an
**Owns:** list. A file appears in exactly one ticket's list per wave; a ticket
that needs a change in someone else's file asks for it rather than making it.

`cli.py` is owned by ticket 01 in wave 0 and by nobody afterwards. Tickets 01
and 02 both change it, so they are the one pair in wave 0 that is **sequenced,
not parallel**: 02 starts when 01 lands.
