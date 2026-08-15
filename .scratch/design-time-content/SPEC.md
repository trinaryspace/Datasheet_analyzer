---
title: Design-time content — pins, registers, design cards, quantities, plot axes
labels: [ready-for-agent]
---

**Execution contract:** `Reports/PHASE_6_PLAN.md`. This file is the tracker
root. **Depends on Phase 5** (`.scratch/agent-native-access/`) for the
retrieval core, confidence grades, alias lexicon, and MCP surface — every new
artifact here is exposed through seams that phase builds.

## Problem Statement

After Phase 5 the corpus answers datasheet questions well, but it is still
organised the way a datasheet is organised, and it is missing the two tables a
hardware designer and a firmware engineer actually live inside. The pin table
— which *is* the datasheet during schematic capture — exists in no queryable
form. Register maps route to the degraded `pdf_text` backend for every vendor,
so bring-up questions are unanswerable by construction. "What rails does this
need and how much current?" is a five-section scavenger hunt. Spec values are
verbatim strings that are never parsed, so "which of these tolerates 105 °C"
cannot be answered although every number is present and cited. And 514
figures catalogued by caption alone means an agent burns vision calls
discovering it opened the wrong one.

## Solution

A deterministic derived-artifact contract (ADR 0005) makes it safe to build
task-shaped views without weakening the traceability guarantee: every derived
field carries its source record, page, and the named rule that produced it,
and no model call may appear in the derivation path. On that contract: an
additive numeric layer that is always allowed to fail; one device-table
abstraction serving two consumers (`pins.json`, `registers.json`); four
design cards keyed to design tasks rather than datasheet structure; a
geometric plot-axis catalog so figures can be targeted before a vision call;
and `dsa compare` for part selection.

## User Stories

1. As a designer doing schematic capture, I want `dsa pins --part X --q VDD`
   to list every matching pin with number, name, type, and page, so I stop
   scrolling a 200-row table in a PDF viewer.
2. As a designer, I want multi-pin rows (`A1, A2, B1`, `A1–A4`) expanded into
   individually citable records, so a pin search cannot miss a pin that shared
   a row.
3. As a designer, I want a pin whose type cannot be determined to be labelled
   `unknown`, so the corpus never guesses whether something is a supply.
4. As a designer, I want a warning when the extracted pin count disagrees with
   the package's stated pin count, so a partially-parsed pin table announces
   itself instead of quietly under-reporting.
5. As a firmware engineer, I want `dsa regs --part X --addr 0x1A04` to return
   the register's name, reset value, access, and page, so bring-up questions
   are answerable from the corpus.
6. As a firmware engineer, I want bit-field extraction to be **absent rather
   than approximate** if it cannot be verified, because wrong bit positions
   are worse than missing ones.
7. As a designer, I want a power card listing every rail with its voltage
   range, max current, and page, so the supply design is one lookup.
8. As a designer, I want a limits card showing abs-max against
   recommended-operating per parameter, flagging zero-margin parameters, so a
   hazard that is invisible across two distant tables becomes visible.
9. As a designer, I want a card with no available data to be honestly empty,
   so an absent interface section never becomes an invented one.
10. As an auditor of this tool, I want every value on every card to resolve to
    a spec or pin record and a printed page, checkable programmatically, so
    the derived layer is provably traceable rather than asserted to be.
11. As a designer comparing candidates, I want `dsa compare AFE7950 AFE7953
    --symbol Pdiss` to show both verbatim values, both pages, and a delta, so
    part selection is one call.
12. As a designer, I want comparisons to report the rows they could **not**
    compare, so an unparseable value is never silently excluded from a
    decision.
13. As an agent, I want to filter 514 figures by axis label and range before
    opening one, so I spend a vision call on the right figure and can present
    that PNG to the designer.
14. As a maintainer, I want unparseable values to stay unparsed and be
    reported as such, so the verbatim-is-authoritative invariant survives the
    arrival of numbers.
15. As a maintainer, I want pins and registers to share one table abstraction
    with recorded rejection reasons, so device tables are as measurable as
    parametric ones already are.

## Implementation Decisions

Full detail in `Reports/PHASE_6_PLAN.md`. The load-bearing ones:

- **ADR 0005 / invariant 8 — deterministic derived artifacts.** A derived
  artifact may contain only verbatim values, values computed from them by a
  documented pure function, or labels from a checked-in lexicon. Every field
  carries `source` (record id + page) and `derivation` (rule name). No model
  call in the path. Unfillable fields stay null. `card_version` participates
  in the publish cache key.
- **The numeric layer is additive and allowed to fail.** `parse_quantity`
  returns `None` for `See Figure 7` / `Note 2` / `—`, recorded as
  `parse_confidence: none`. Verbatim strings are never mutated. Every
  consumer that sorts or compares must report its unparsed population.
- **One device-table abstraction, two consumers.** Identify by header lexicon
  → map columns (header match, positional fallback) → validate (unique keys,
  monotonic addresses, count cross-checks) → emit with provenance. A
  validation failure rejects the table with a recorded reason rather than
  emitting half a record set.
- **Register maps re-route from `pdf_text` to `pdf_layout`.** This is a
  deliberate behaviour change to a documented caveat and invalidates cached
  extractions for those documents; hence the `PIPELINE_VERSION` bump.
- **Pin tables only.** Package drawings stay figure images, retrievable via
  `get_figure`. No geometric ball-map reconstruction, no vision fallback.
- **Plot axes are geometric.** Tick clusters along region edges, axis title
  from the parallel text run (rotated for y). Uncertain stays null.

## Testing Decisions

- `parse_quantity` gets a unit test per row of the shapes table in the plan,
  **including** the unparseable cases asserting `None`.
- The invariant-8 test walks every card's `source` fields and asserts each
  resolves to a real record and a printed page. This is the phase's most
  important test: it is what makes the derived layer trustworthy.
- Pin extraction must either succeed or reject with a recorded reason on all
  six parts; a part with no parseable pin table produces **no** `pins.json`,
  asserted.
- Register work is gated against the reference register-map PDF; bit-field
  extraction may park with a `KNOWN_SHORTCOMINGS.md` entry rather than ship
  approximate bits.
- Synthetic PyMuPDF fixtures cover device-table shapes at the unit level so
  work is not blocked on the reference document arriving.
- All Phase 5 goldens stay at 100%; new golden questions cover pins,
  registers, and cards.

## Out of Scope

- Geometric ball-map reconstruction from package drawings.
- Vision fallback for unparseable pin tables (would put a model in the content
  path, contradicting invariant 8).
- Curve digitization from plot images. The axis catalog is the groundwork; a
  confidently wrong interpolated value is the worst failure this tool could
  produce, so digitization needs its own accuracy gate first.
- Cross-part interface validation (needs connectivity, which needs netlists).

## Further Notes

- **Ticket 05 is blocked on the reference register-map PDF** being dropped
  into the repo, and stays `needs-info` until it lands. A register parser
  written without a real document to gate against would be fiction.
- Ticket 08 (plot axes) is independent of everything else in the phase and is
  the right work to pick up while waiting on that PDF.
- Ticket 04 (pins) must land before 05 so the shared device-table abstraction
  is proven on the easier table shape first.
