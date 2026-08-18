---
title: Design-loop integration — netlist join, deterministic design checks, layout cards, expert packs, retrieval eval
labels: [ready-for-agent]
---

**Execution contract:** `Reports/PHASE_8_PLAN.md`. This file is the tracker
root. **Depends on Phases 5–7.** This phase was scoped after Phase 7; it is
not part of the original 5–7 roadmap.

## Problem Statement

Phases 1–7 make the datasheet side of the goal excellent: verbatim extraction,
page-pinned citations, alias resolution, confidence grades, pin and register
records, design cards, freshness checking and audit grades. An agent can
become an expert on a part or a series.

The tool still knows nothing about **this design**. Every question has to be
asked in the abstract, and the designer carries the join to their own
schematic in their head. The questions that actually come up mid-capture are
relational — *is this pin allowed to float? can U3 drive U5's clock directly?
which of my parts needs a thermal pad, and how many vias?* — and none of them
are answerable from a datasheet alone.

Two quieter gaps sit alongside it. The corpus is excellent and **trapped in
this repo**: an agent working in the designer's own schematic repository
cannot consume it without cloning this one, so "become an expert on a part"
is not portable. And nothing measures **retrieval** as distinct from
**answers**, so a retrieval regression the goldens happen not to cover stays
invisible until it costs someone a design decision.

## Solution

A design is imported from a KiCad netlist or a BOM CSV and its components are
bound to corpora, with unbound components reported as first-class output.
Netlist nodes join to Phase 6 pin records, producing a connections view that
states how much of the design it actually understands. Declarative,
checked-in design rules are evaluated over that view by `dsa check`, and every
finding cites the verbatim datasheet text, record id and printed page it
derives from — advisory, never a sign-off. A layout and assembly card answers
the questions asked after capture. Expert packs make a part, family or project
portable and hash-verified. Retrieval evaluation and a performance budget turn
two invisible qualities into red tests.

## User Stories

1. As a designer mid-capture, I want to import my netlist and ask "is U3 pin
   A12 allowed to float?" and get an answer citing the printed page, so I do
   not have to hold the join in my head.
2. As a designer, I want `dsa check` to flag a logic-level mismatch between two
   parts on the same net, quoting both datasheets' printed thresholds, so a
   translator I forgot becomes a finding rather than a bring-up mystery.
3. As a designer, I want every check to tell me **what it could not evaluate**,
   so a rule that assessed 3 of 400 sites never reads as "clean". This is the
   most important story in the phase.
4. As a designer, I want no check to ever claim my design is correct. Findings
   cite pages and I decide.
5. As a designer, I want components with no corpus listed explicitly with a
   reason, so I know exactly how much of my board the tool understands.
6. As a designer, I want a wrong refdes → part bind to be impossible by
   accident: binds come from the netlist's own fields or from an explicit
   override, never from fuzzy matching on a value string.
7. As a designer at layout, I want package, thermal pad, via guidance, MSL and
   reflow numbers surfaced verbatim with pages, so I stop reopening the PDF.
8. As an agent working in the designer's *own* repo, I want to drop in an
   expert pack and answer questions about those parts with no clone of this
   repo and no network.
9. As a maintainer, I want an imported pack's every file hash-verified before
   anything is written, so a corrupted or tampered pack is refused whole.
10. As a maintainer, I want recall@k and MRR measured over the goldens with a
    budget, so a retrieval regression is a red test and not a discovery.
11. As a maintainer, I want questions that returned empty or low-confidence
    answers logged, so real usage feeds Phase 7's `golden suggest` and the
    golden set grows where it is actually weak.
12. As a designer, I want answers in well under a second during capture, and I
    want that measured rather than assumed.
13. As a maintainer, I want an incremental rebuild to produce a **byte-
    identical** corpus to a full rebuild, because faster-but-different is a
    correctness bug wearing a performance costume.

## Implementation Decisions

Full detail in `Reports/PHASE_8_PLAN.md`. The load-bearing ones:

- **Design input is a KiCad netlist (documented subset: `components` and
  `nets`) plus a plain BOM CSV.** Native Altium/OrCAD/Allegro formats are out:
  proprietary, hard to test, and each is a separate parser with no shared
  shape. Anything the parser does not understand is recorded, never guessed.
- **Refdes → part binding is explicit**, from the netlist's own value/MPN
  fields or a manual override written by `dsa design bind`. No fuzzy matching
  on value strings — a wrong bind answers confidently about the wrong silicon,
  which is the worst failure this phase could produce.
- **Design rules are declarative data** (`registry/design_rules.yaml`),
  advisory only, and every finding carries verbatim text, record id and page.
  Invariant 8 holds: no model call anywhere in a check path.
- **Every rule reports its unevaluated population** and why. This is the same
  rule Phase 6 applied to `compare` and Phase 7 to `diff-rev`.
- **Rail voltages are declared** in `rails.yaml`. Inferring a rail from a net
  *name* is opt-in (`--infer-rails`) and labelled in the output, because
  `3V3_SW` may be a switching node rather than a 3.3 V rail.
- **Packs are local, self-describing directories** with a per-file sha256
  manifest and the `PIPELINE_VERSION` they were built at. Verification happens
  before any write. No hosted registry — same reasoning as the local-only MCP
  decision.
- **Retrieval eval reuses the goldens** as ground truth rather than building a
  new hand-labelled relevance corpus, with a checked-in budget file so a drop
  fails the suite.
- **Performance budgets have generous ceilings.** A tight SLA would flake on a
  loaded machine and teach people to ignore the gate.

## Testing Decisions

- The KiCad netlist parser is tested against a **checked-in synthetic
  fixture** written to the documented format, plus a fixture containing
  constructs the parser does not support, asserted to be *recorded* rather
  than silently dropped. The parser is validated against a real KiCad export
  in the live run, and that step is recorded rather than assumed.
- Every shipped rule gets a **pair** of fixtures: one designed to trip it, one
  designed not to. A rule with only a positive test is not tested.
- A test asserts that a rule which could evaluate almost nothing does **not**
  render as clean output.
- Incremental rebuild is asserted **byte-identical** to a full rebuild, not
  merely "passes the same tests".
- A pack round-trips into a clean temporary directory with no access to the
  source corpus, and a deliberately corrupted manifest is asserted to be
  refused with the failing file named.
- A seeded retrieval regression is asserted to fail the budget test.
- Performance tests assert against the budget file, not against wall-clock
  constants embedded in test code.
- All tests remain hermetic: no network, no real LLM, no subprocess.

## Out of Scope

- **Any claim of design suitability or correctness.** Checks are advisory and
  cite pages. The tool informs; the designer decides.
- **Land-pattern or footprint generation.** An EDA library problem, and a
  wrong footprint is unrecoverable.
- **Schematic or PCB file parsing** (`.kicad_sch`, `.kicad_pcb`). The netlist
  is the stable documented interface.
- **Simulation, signal/power integrity, thermal solving.** Different
  discipline.
- **Hosted pack distribution, multi-user auth.** Local files only.
- **Curve digitization.** Still rejected for Phase 6's reason.

## Further Notes

- Critical path is 01 → 02 → 03 → 08. Tickets 04–07 are parallelisable and
  each is independently valuable if the phase is cut short.
- Ticket 03 is the phase's headline. If the phase has to be cut, it is the one
  to keep — but it is worthless without 02's honest coverage reporting, so the
  two travel together.
- This phase should be almost entirely offline-testable, unlike Phase 7. The
  one live step is validating the netlist parser against a real KiCad export.
