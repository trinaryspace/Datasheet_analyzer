# ROADMAP — Phases 5–7

Cross-phase overview and decision record for the three planned phases.
Individual execution contracts: `PHASE_5_PLAN.md`, `PHASE_6_PLAN.md`,
`PHASE_7_PLAN.md`. Trackers: `.scratch/agent-native-access/`,
`.scratch/design-time-content/`, `.scratch/reach-and-trust/`.

## The goal

A hardware designer, mid-schematic-capture, asks a model a question about a
part and gets a correct, cited answer in one round trip. An agent handed a
BOM compiles every datasheet in it unattended. An agent asked about a series
of parts knows what they share and where they differ.

Phases 1–4 built the foundation for that: verbatim extraction, page-pinned
citations, a token-budgeted index, a vendor-neutral layout floor, and a golden
Q&A that gates. What remains is three different gaps.

| Phase | Gap | One-line claim |
|---|---|---|
| **5 — Agent-Native Access** | The corpus is a filesystem a human drives with a CLI | *A designer's question, in a designer's words, returns a cited answer inside a budget* |
| **6 — Design-Time Content** | The corpus is shaped like a datasheet, not like a schematic | *The corpus answers schematic-capture and bring-up questions, and every derived number traces to a printed page* |
| **7 — Reach & Trust** | Onboarding is manual and quality is invisible at scale | *Twenty parts onboard cheaply, stay honest, and a series answers as one* |

Ordering is **depth before breadth**: make six parts excellent, then scale.
Scaling a corpus shape you later want to change is the expensive mistake.

## Scope decisions taken up front

Recorded here because each one closed off work that a reasonable plan might
otherwise have included.

| Decision | Chosen | Rejected, and why |
|---|---|---|
| **Derived data** | Deterministic only — no model call in any derivation path | *LLM-assisted-verified* (non-deterministic builds, needs a verification harness) and *LLM-free-form* (breaks the traceability guarantee that makes this repo trustworthy) |
| **Project input** | Explicit part list (`project.json`) | *BOM CSV import* and *EDA netlist parsing* — an agent that can read a BOM can call `dsa project add`, which is the cheap 90% |
| **Document fetch** | Curated URL registry, grown by `--url` | *Vendor URL pattern probing* (brittle) and *web-search resolution* (non-deterministic, risks fetching a mirrored or wrong document) |
| **MCP** | Local stdio only | *HTTP/remote* — no team-sharing requirement yet; auth and multi-tenancy are real cost |
| **Pins** | Printed pin tables only | *Geometric ball-map reconstruction* (vendor-variable) and *vision fallback* (puts a model in the content path) |
| **Registers** | First-class, gated on a reference PDF | *Indefinite deferral* — bring-up questions matter; but bit fields may still park rather than ship approximate |
| **Plots** | Axis catalog so the right figure is found and handed over as a PNG | *Curve digitization now* — a confidently wrong interpolated value is the worst failure this tool could produce |
| **Priority** | Depth, then breadth | *Breadth first* — would scale a shape still being changed |

## Where each idea landed

All nineteen items from the original brainstorm, plus register maps, mapped to
tickets.

| # | Idea | Phase | Ticket |
|---|---|---|---|
| 1 | MCP server | 5 | 07 |
| 2 | Answer packs (`dsa ask`) | 5 | 05 |
| 3 | Agent protocol / skill | 5 | 08 |
| 4 | Project scope | 5 | 06 |
| 13 | Alias lexicon | 5 | 02 |
| 14 | Full-text search | 5 | 03 |
| 19 | Per-record confidence | 5 | 04 |
| — | Retrieval core seam (enabler) | 5 | 01 |
| — | Golden extension + gate | 5 | 09 |
| 7 | Design cards | 6 | 07 |
| 8 | Pinout extraction | 6 | 04 |
| 9 | Register maps | 6 | 05, 06 |
| 15 | Normalized numeric layer | 6 | 02 |
| 16 | Plot axis metadata | 6 | 08 |
| 6 | Cross-part compare | 6 | 09 |
| — | Derived-artifact ADR (enabler) | 6 | 01 |
| — | Device-table abstraction (enabler) | 6 | 03 |
| 10 | `dsa fetch` | 7 | 01 |
| 11 | Revision awareness + diff | 7 | 02, 03 |
| 12 | Errata cross-linking | 7 | 04 |
| 17 | Audit scorecard | 7 | 05 |
| 18 | Golden generation assist | 7 | 06 |
| 5 | Part families / series | 7 | 07 |

## Critical path

```
Phase 5:  01 ─→ 02 ─→ 03 ─→ 04 ─→ 05 ─┐
                                       ├─→ 07 ─→ 08 ─→ 09
          06 ───────────────────────────┘
          (06 parallel to 02–05; 07 is the join)

Phase 6:  01 ─→ 02 ─┐
          01 ─→ 03 ─→ 04 ─→ 05 ─→ 06        (05/06 blocked on reference PDF)
                     └─→ 07 ─→ 09 ─→ 10
          08 ─────────────────────────┘      (independent throughout)

Phase 7:  01 ─→ 02 ─→ 03 ─┐
          04 ──────────────┤
          05 ──────────────┼─→ 08
          06 ──────────────┤
          07 ──────────────┘
          (01 → 06 → 08 is the real critical path)
```

## Known blockers

- **Phase 6, tickets 05 and 06 are `needs-info`** pending a reference
  register-map PDF in the repo. A register parser written without a real
  document to gate against would be fiction. Ticket 08 (plot axes) is
  independent and is the right work to pick up while waiting.

## Version and invariant trail

| Phase | `PIPELINE_VERSION` | Invariant change |
|---|---|---|
| 5 | 0.2.0 → 0.3.0 | none (publish artifacts change; cache gate handles it) |
| 6 | 0.3.0 → 0.4.0 | **new invariant 8** — deterministic derived artifacts; register-map routing change invalidates those extractions |
| 7 | 0.4.0 → 0.5.0 | invariant #5 gains "generated candidates never count until confirmed" |

## Hygiene item (unrelated to these phases)

`.env` is tracked in git and contains an `API_KEY` line. It has never been
committed. `git rm --cached .env` plus a `.gitignore` entry clears it before
it lands in history.
