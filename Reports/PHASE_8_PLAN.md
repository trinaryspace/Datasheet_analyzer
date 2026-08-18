# PHASE 8 PLAN — Design-Loop Integration

**Status: planned.** Execution contract for `.scratch/design-loop/`.
Superseded on landing by `Reports/PHASE_8_REPORT.md`.

**Depends on Phases 5–7.** This phase was not in the original 5–7 roadmap. It
was scoped after Phase 7 to close the last gap between what the repo does and
what the repo is *for*.

## Why this phase exists

The stated goal has always been:

> A hardware designer, mid-schematic-capture, asks a model a question about a
> part and gets a correct, cited answer in one round trip.

Phases 1–7 make the **datasheet** side of that sentence excellent. Every fact
is verbatim, page-pinned, confidence-graded, alias-resolvable, freshness-
checked and audit-graded. An agent can become an expert on a part or a series.

But the tool still knows nothing about **this design**. Every question has to
be asked in the abstract — "what is the VIH of the AFE7950?" — and the
designer carries the join to their own schematic in their head. The questions
that actually arise mid-capture are relational:

- *Is this pin allowed to be left floating?*
- *Can U3 drive U5's clock input directly, or do I need a translator?*
- *Which of my parts needs a thermal pad, and how many vias does its datasheet
  ask for?*
- *I changed the 3V3 rail to 3.0 V — what breaks?*

None of those are answerable from a datasheet alone. They need the datasheet
**joined to the design**. That join is this phase.

There is a second, quieter gap. The corpus is excellent and it is trapped in
this repo. An agent working in a *different* project — the designer's actual
schematic repo — cannot consume it without cloning this one. "Become an expert
on a part" should be portable.

And a third: nothing measures **retrieval** as distinct from **answers**.
Goldens gate end-to-end correctness; a retrieval regression that goldens happen
not to cover is invisible until it costs someone a design decision.

| Gap | One-line claim |
|---|---|
| The corpus does not know the design | *A netlist and a BOM join to pin records, and questions become design-specific* |
| Nothing checks the join | *Deterministic, page-cited, advisory checks flag what a human should look at* |
| Layout-time content is unsurfaced | *Package, thermal and layout guidance answer the questions asked at layout, not at capture* |
| The corpus is trapped in this repo | *An expert pack is portable, self-describing, and hash-verified* |
| Retrieval quality is unmeasured | *Recall@k and MRR over the golden set, with a regression budget* |
| Live use is unmeasured | *Sub-second answers during capture, measured, with a budget the suite enforces* |

## The load-bearing constraint

**Nothing in this phase signs off on a design.** Every check is advisory,
every finding cites the printed page it derives from, and every rule reports
the population it could *not* evaluate. A hardware tool that quietly says
"looks fine" when it simply failed to parse a row is worse than no tool. This
is the same rule Phase 6 applied to `compare` and Phase 7 applied to
`diff-rev`, and it is the single most important sentence in this plan.

Invariant 8 extends unchanged: **no model call anywhere in a check path.** A
design rule is a declarative, checked-in definition evaluated over records
that already carry verbatim values and pages.

## Scope decisions taken before writing

Recorded because each closed off work a reasonable plan might have included.

| Decision | Chosen | Rejected, and why |
|---|---|---|
| **Design input format** | KiCad netlist (documented subset) + plain BOM CSV | *Altium / OrCAD / Allegro native formats* — proprietary, less available for testing, and each is a separate parser with no shared shape. *Full KiCad s-expression fidelity* — the netlist's `components` and `nets` blocks are all this phase needs; parsing the rest invites drift |
| **Refdes → part binding** | Explicit, from the netlist's own value/MPN fields, with a manual override file | *Fuzzy matching on component value strings* — a wrong bind silently answers about the wrong silicon, which is the worst failure this phase could produce |
| **Design checks** | Declarative rules in `registry/design_rules.yaml`, advisory only | *Hardcoded Python rules* (not reviewable, not extensible) and *pass/fail sign-off* (a liability and a lie) |
| **Layout content** | Verbatim surfacing of package/thermal/layout sections as a card | *Land-pattern geometry generation* — that is an EDA library problem, and a wrong footprint is unrecoverable |
| **Expert packs** | A local, self-describing, hash-manifested directory/archive | *A hosted pack registry* — still no multi-user requirement; auth and distribution are real cost |
| **Retrieval eval** | Recall@k / MRR over existing goldens + an unanswered-question log | *A new hand-labelled relevance corpus* — expensive, and the goldens already encode the ground truth |
| **Performance** | Measured budgets with generous ceilings, asserted in-suite | *A hard latency SLA* — would flake on a loaded machine and teach people to ignore the gate |

## Component specs

### 1. Design ingest — `dsa design import`

```
dsa design import my-board.net --name rf-frontend
dsa design import bom.csv --name rf-frontend --format bom
```

Produces `designs/<NAME>/design.json`:

```json
{
  "name": "rf-frontend",
  "source": {"path": "my-board.net", "format": "kicad_netlist", "sha256": "…"},
  "components": [
    {"refdes": "U3", "value": "AFE7950IAAV", "part": "AFE7950",
     "bound_by": "registry/part_aliases", "footprint": "…"}
  ],
  "unbound": [
    {"refdes": "U7", "value": "XYZ-999", "reason": "no corpus for this part"}
  ],
  "nets": [{"name": "3V3", "nodes": [{"refdes": "U3", "pin": "A12"}, …]}]
}
```

- The parser handles a **documented subset** of the KiCad netlist
  s-expression: `(components …)` and `(nets …)`. Anything it does not
  understand is recorded, never guessed.
- **`unbound` is a first-class output, not an error.** A design will always
  contain passives and parts with no corpus. Those must be visible and must
  never be silently dropped — the count appears in every downstream report.
- `dsa design bind <NAME> U7=LMX1204` writes a manual override, so the join
  improves by use exactly as the Phase 7 registry does.

### 2. Pin-level join — `designs/<NAME>/connections.json`

The join of netlist nodes to Phase 6 pin records:

```json
{"refdes": "U3", "part": "AFE7950", "pin": "A12",
 "net": "3V3",
 "pin_record": {"id": "pin:AFE7950:A12", "name": "VDDA", "type": "power",
                "page": 14},
 "matched_on": "designator"}
```

- Matching is by pin designator first, pin name second, and each row records
  which. A node whose pin cannot be found in the corpus is reported under
  `unmatched_nodes` with the reason.
- **Coverage is reported, always**: "U3: 41 of 41 pins matched; U5: 12 of 64
  matched — corpus has no pin table". A consumer that reads this file must be
  able to tell how much of the design it actually understands.

### 3. Deterministic design checks — `dsa check`

Rules live in `registry/design_rules.yaml` and are evaluated over the joined
view. Ship these:

| Rule | What it flags | Needs |
|---|---|---|
| `floating-power-pin` | a pin typed `power`/`ground` on a net with one node | pin types (P6) |
| `unconnected-required-pin` | a pin the datasheet marks must-connect, on no net | pin records |
| `supply-out-of-range` | a net's stated rail voltage outside the pin's recommended-operating range | numeric layer (P6) |
| `logic-level-mismatch` | a driver's VOH/VOL against a receiver's VIH/VIL on the same net | numeric layer + alias lexicon |
| `abs-max-margin` | a net voltage within a configured margin of an absolute-maximum | numeric layer |
| `missing-decoupling` | fewer decoupling caps on a supply net than the datasheet's stated requirement | layout card (ticket 04) |

Every finding carries: rule id, severity, the refdes/pin/net involved, the
**verbatim datasheet text** it derives from, the record id, and the printed
page. Output `designs/<NAME>/DESIGN_REVIEW.md` plus `--json`.

Every rule additionally reports its **unevaluated population** — how many
candidate sites it could not assess and why (no pin table, unparsed value, no
rail voltage declared). A rule that evaluated 3 of 400 sites and found nothing
must not read as "clean".

Net rail voltages come from `designs/<NAME>/rails.yaml`, declared by the
designer. Inferring a rail voltage from a net *name* (`3V3` → 3.3 V) is a
convenience that must be opt-in (`--infer-rails`) and labelled in the output,
because `3V3_SW` might be a switching node.

### 4. Layout & assembly card

A Phase 6-style design card for the questions asked *after* capture:
package type and pin count, thermal pad presence and dimensions, the
datasheet's stated via/thermal guidance, moisture sensitivity level, peak
reflow temperature, ESD ratings. Verbatim strings, page cites, `null` where
the datasheet does not say. Surfaced as `dsa card <PART> --layout` and in the
MCP tool set.

### 5. Expert packs — `dsa pack` / `dsa unpack`

```
dsa pack --part AFE7950 --out AFE7950.dsapack
dsa pack --family AFE795x --out AFE795x.dsapack
dsa pack --project rf-frontend --out rf-frontend.dsapack
```

A pack is a self-describing directory (and optional archive) containing the
index, records, cards, pins, registers, plot catalog, the agent protocol
document from Phase 5, the audit grade from Phase 7, and a `MANIFEST.json`
with a sha256 per file plus the `PIPELINE_VERSION` it was built at.

`dsa unpack` verifies every hash before writing anything. A pack that fails
verification is refused with the failing file named — never partially
imported.

The point: an agent working in the designer's *own* schematic repo drops in a
pack and is immediately an expert on those parts, with no clone of this repo
and no network.

### 6. Retrieval evaluation — `dsa eval retrieval`

Goldens gate answers. This gates the layer beneath them.

- For each golden question, the ground-truth record is already known. Measure
  **recall@1/@5/@10** and **MRR** for the retrieval core across the fleet,
  broken down by query kind (spec lookup, pin, register, free text) and by
  backend.
- A **budget file** (`registry/retrieval_budget.yaml`) records the current
  numbers; the suite fails if a metric drops more than a stated tolerance.
  That converts "retrieval got worse" from a thing someone notices later into
  a red test.
- An **unanswered-question log**: `dsa ask` records questions that returned
  empty or low-confidence answers to `designs/…/unanswered.jsonl`, which feeds
  Phase 7's `golden suggest`. The loop closes: real questions become goldens.

### 7. Live-use performance

Mid-capture means seconds matter.

- **Incremental rebuild**: `dsa build` re-does only documents whose source
  hash or extractor version changed; everything else is reused from the
  published corpus. Measured on a real rebuild.
- **Warm index**: the retrieval core loads its BM25 index and record tables
  once per process; the MCP server keeps them resident across calls.
- Measured **p50/p95** for `ask`, `search`, `query`, `pins`, and `regs` across
  the fleet, recorded in the report and budgeted in
  `registry/perf_budget.yaml` with a generous ceiling so the gate means
  something without flaking.

### 8. Phase gate + walkthrough

- A complete design walkthrough runs end to end in the test suite against a
  checked-in synthetic design: import → bind → connections → check →
  `DESIGN_REVIEW.md` → `dsa ask --design`.
- At least one **real** finding is produced on a real corpus and hand-verified
  against the printed page, and at least one deliberately-injected fault is
  caught.
- Every rule's unevaluated population is reported and non-hidden.
- A pack round-trips: pack → unpack into a clean directory → `dsa ask` answers
  correctly there with no access to the source repo.
- Retrieval and performance budgets are recorded and enforced.
- `pytest` offline, `ruff` clean.

## Schema / CLI / versions

- New directories `designs/<NAME>/`, new checked-in data
  `registry/design_rules.yaml`, `registry/retrieval_budget.yaml`,
  `registry/perf_budget.yaml`.
- New files `design.json`, `connections.json`, `rails.yaml`,
  `DESIGN_REVIEW.md`, `unanswered.jsonl`, `MANIFEST.json`.
- Additive card field group for layout/assembly.
- `PIPELINE_VERSION` 0.6.0 → **0.7.0** (confirm the entering value; Phase 6
  moved it to 0.5.0 ahead of plan and Phase 7 takes it to 0.6.0).
- New CLI: `design import|bind|status`, `check`, `pack`, `unpack`,
  `eval retrieval`. New MCP tools: `get_design`, `check_design`,
  `get_layout_card`.
- New config: `DSA_DESIGNS_DIR` (default `designs`).

## Acceptance gate

1. A KiCad netlist fixture imports; components bind to corpora; unbound
   components appear explicitly with reasons — asserted.
2. A BOM CSV imports and produces the same `design.json` shape.
3. `connections.json` joins nodes to pin records, records `matched_on`, and
   reports per-part match coverage including a part with no pin table.
4. Each shipped rule fires on a fixture designed to trip it, and does **not**
   fire on a fixture designed not to — both asserted.
5. Every rule reports its unevaluated population; a test asserts a rule that
   could evaluate almost nothing does not read as clean.
6. Rail inference is off by default and labelled when on — asserted.
7. `DESIGN_REVIEW.md` findings each carry verbatim text, record id, and page.
8. The layout card populates from a real datasheet with page cites, and leaves
   `null` where the document is silent.
9. A pack round-trips into a clean directory and answers there; a corrupted
   pack is refused with the failing file named.
10. `dsa eval retrieval` reports recall@k and MRR; a seeded retrieval
    regression makes the budget test fail.
11. Incremental rebuild is measurably faster and produces a byte-identical
    corpus to a full rebuild — asserted, because "faster but different" is a
    correctness bug.
12. Performance budgets recorded and enforced; `pytest` offline, `ruff` clean.

## Implementation order

| # | Ticket | Notes |
|---|---|---|
| 01 | Design ingest (`dsa design import`) | The foundation; everything joins to it |
| 02 | Pin-level join + coverage | Needs 01 and Phase 6 pin records |
| 03 | Design rules + `dsa check` | The headline capability. Needs 02 |
| 04 | Layout & assembly card | Independent; also feeds rule `missing-decoupling` |
| 05 | Expert packs | Independent; needs Phase 7 audit + families to be complete |
| 06 | Retrieval eval + unanswered log | Independent |
| 07 | Live-use performance | Independent; touches build and the retrieval core |
| 08 | Phase gate + report | Closes the phase |

01 → 02 → 03 → 08 is the critical path. 04–07 are parallelisable against it
and each is independently valuable if the phase is cut short.

## Docs / invariants to update on landing

- `AGENTS.md`: invariant 8 restated to cover design checks explicitly; module
  map gains `designs/`, the rules engine, and the pack format.
- `CONTEXT.md`: new nouns — **Design**, **Refdes**, **Net**, **Rail**,
  **Design rule**, **Finding**, **Expert pack**.
- `README.md`: the design-loop walkthrough as the headline usage example.

## Out of scope (kept out, recorded)

- **Signing off on a design.** Checks are advisory and cite pages. The tool
  informs the designer; the designer decides.
- **Land-pattern or footprint generation.** A wrong footprint is unrecoverable
  and this is an EDA library problem, not a datasheet problem.
- **Schematic or PCB file parsing** (`.kicad_sch`, `.kicad_pcb`). The netlist
  is the stable, documented interface between capture and everything else.
- **Simulation, SI/PI analysis, or thermal solving.** Different discipline,
  different tool.
- **Hosted pack distribution.** Local files only, same as the MCP decision.
- **Curve digitization.** Still rejected, for the reason Phase 6 gave: a
  confidently wrong interpolated value is the worst output this tool could
  produce.
