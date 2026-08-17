# PHASE 6 AUTONOMOUS RUN REPORT — Design-Time Content

**Branch:** `feat/phase6-design-content` (worktree
`.claude/worktrees/roadmap-phases-5-7`). **Plan:** `Reports/PHASE_6_PLAN.md`.
**Measured results:** `Reports/PHASE_6_REPORT.md`.

This file covers **two runs**:

| Run | Date | Tickets | Outcome |
|---|---|---|---|
| Run 1 | 2026-08-17 | 01–07 committed, 08 left uncommitted | stopped in the tail |
| **Run 2 (tail)** | 2026-08-17 | **08, 09, 10** | **completed — phase closed** |

Run 2 is written first, below. **The run-1 record is kept verbatim further
down and parts of its "READ THIS FIRST" are now historical** — it is annotated
where it is stale, not rewritten.

---

# RUN 2 — the tail (tickets 08–10)

## ⚠ READ THIS FIRST

**1. The final verification run is GREEN.** Re-run for this report, from a
clean working tree at `daa7964`:

| Command | Result | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest tests/` | **1664 collected — 1663 passed, 1 skipped, 0 failed, 0 errors** (334 s) | **0** |
| `.venv/Scripts/python.exe -m ruff check src tests` | **All checks passed!** | **0** |

Counts come from `--junitxml`, not the terminal, for the reason run 1 recorded
in §2 below: on a full-suite run this repo prints progress dots and then
**nothing** — the summary line never reaches the terminal. That reporting
nuisance is still unfixed. The single skip is the same one every phase has
reported: `test_phase3_plots.py::TestPhase3VisionSmoke::test_vision_reads_one_golden_plot`,
auto-skipped with `no ANTHROPIC_API_KEY available`.

**2. Nothing stopped early this run, and there is no `STOPPED.md`.** The tail
ran 08 → 09 → 10 → wrap-up and finished. There is no `STOPPED.md` in the repo,
the worktree root or `.scratch/design-time-content/` — none is needed, and (as
run 1 also found) none exists for run 1 either. **Do not go looking for one.**

**3. Phase 6 is complete and its gate has been run.** All ten tickets are
committed. `Reports/PHASE_6_REPORT.md` closes with an item-by-item pass over
the plan's eight-item acceptance gate — **8 of 8 met** — and
`Reports/PHASE_6_PLAN.md` already carries `Status: superseded by
Reports/PHASE_6_REPORT.md` (ticket 10 wrote that line; this run verified it and
changed nothing).

**4. The working tree is clean and this push carries everything.** `git status
--porcelain` returns zero lines. Run 1's biggest hazard — ticket 08 living
uncommitted on one machine — is closed: it is committed as `6e180f8`.

**5. Four things shipped with known defects, and two of them I confirmed
myself rather than repeating a claim.** See [Reviewer notes carried
forward](#reviewer-notes-carried-forward-run-2). The load-bearing one:
`compare/build._qualified` converts an ADR-0005-legal doc-less reference into
one `parse_source` **rejects**, so a compared card value can carry a source
nothing can resolve. Verified in this session:

```
_qualified('specs.json#rec_412', 'AD9081') -> 'parts/AD9081/specs.json#rec_412'
parse_source('parts/AD9081/specs.json#rec_412') -> None
```

**6. The committed reference corpora are still stale, exactly as run 1 said.**
`parts/AFE7950` and `parts/AFE7953` remain at `SPECS_SCHEMA_VERSION` 1 against
a current 5, with no record ids. Nothing derived can cite them, so
`dsa compare AFE7950 AFE7953` over the committed corpora is
empty-with-a-reason, and every card/compare number in the report is measured on
a fresh hermetic build. **This is the oldest unactioned item in the phase**
(run-1 item 01-a, now also `KNOWN_SHORTCOMINGS.md` compare item 3).

## Commits this run

| Commit | Subject | Files | Diff |
|---|---|---:|---|
| `6e180f8` | `p6-08: plot axis catalog` | 30 | +3524 / −33 |
| `b64e0be` | `p6-09: cross-part compare` | 25 | +3335 / −39 |
| `daa7964` | `p6-10: mcp surface + phase gate` | 27 | +2170 / −102 |

Ticket 08's commit contains the work run 1 left uncommitted **plus** this run's
audit of it; the two are not separable in the history.

## Test count vs the 1506 baseline

| State | Collected | Passed | Skipped | Failed |
|---|---:|---:|---:|---:|
| Phase 5 final | 869 | 868 | 1 | 0 |
| Phase 6 through ticket 07 (`3572b28`) | 1421 | 1420 | 1 | 0 |
| Tail baseline as the workflow declared it (`BASELINE_TESTS = 1506`) | — | 1506 | 1 | 0 |
| **Phase 6 final (`daa7964`)** | **1664** | **1663** | **1** | **0** |

**+157 passing tests against the declared 1506 baseline.** Test *functions*
added per commit (a lower bound on collected tests, since several are
parametrized): ticket 08 **91**, ticket 09 **62**, ticket 10 **47**.

**One discrepancy worth naming rather than smoothing.** Run 1 measured the
working tree — the same tree the tail then picked up — at **1493 collected /
1492 passed**, and the tail workflow declares its verified starting state as
**1506 passed**. The 14-test gap is not explained by anything I measured. The
likely cause is that ticket 08 had a *second* implementer after run 1's report
was written (the workflow's own note says "two previous agents worked on it")
which grew `tests/unit/test_plot_axes.py` from the 533 lines / 41 tests run 1
recorded to the 615 lines / 47 test functions now committed. That is an
inference from file sizes, not a measurement, and I did not re-run the suite at
the intermediate state to confirm it.

## What landed, per ticket

### Ticket 08 — plot axis catalog (`6e180f8`)

`structure/plot_axes.py` (612 lines) reads each figure's two axes — title,
unit, printed tick range, spacing rule — off the page text inside the figure
region `extract/pdf_layout.figure_text_regions` hands back;
`PLOTS_SCHEMA_VERSION` 2 → 3; `dsa plots --x-label/--y-label/--near-x` and the
MCP `find_plots` tool expose them.

This ticket was an **audit**, not a fresh implementation: run 1 left it
implemented, green and unreviewed. The tail agent re-measured every claim
rather than trusting it, and reported doing so — reproducing 458/514 (89%) on
AFE7950, 368/492 on AFE7953, the four gate rows off the gate's own printed
table, LMX1204 23/54 off a fresh offline build, the accuracy walk outside
pytest, and both hand-read figures. It confirmed **the floor bites** by
mutating `MIN_TICKS` to 9 (coverage falls to 203/514, five gate assertions
fail) and reverting. It found and closed two real gaps: `ProjectRetriever`'s
axis filters had **zero** coverage although `dsa plots --project` and the MCP
tool both route through them, and the unclosed-bracket title case (5 of 514
figures) was untested and undocumented.

### Ticket 09 — cross-part compare (`b64e0be`)

`dsa compare` end to end: `compare/build.py` (884 lines, pure), `compare/render.py`,
`retrieve/compare.py` as the third scope beside part and project, plus a tenth
MCP tool `compare_parts`. Alignment is by alias-resolved symbol; a delta exists
only where both sides parsed the same printed column into the same SI base.
ADR 0005 gained an additive **part-qualified** reference form so a cross-corpus
delta is walkable. `COMPARE_SCHEMA_VERSION` 1 — a payload shape, deliberately
**not** a publish cache key, since a comparison is never written to disk.

### Ticket 10 — MCP surface, goldens, phase gate (`daa7964`)

`find_pin`, `find_register` and `get_card` land (the first two deferred here by
tickets 04 and 05), taking the MCP surface to **thirteen** tools; each is a
pure adapter over an existing `retrieve/` seam and the grep-shaped seam guard
still passes. `dsa ask` gains `pin` and `register` routes ahead of plot/spec,
with `pin_gap()`/`register_gap()` joining `search_unavailable()` so a path that
never ran routes `unavailable`, not `none`. A `card_query` golden marker joins
the path markers and four golden questions were added.

**Version constants as shipped:** `PIPELINE_VERSION` 0.5.0,
`SPECS_SCHEMA_VERSION` 5, `PLOTS_SCHEMA_VERSION` 3, `PINS_SCHEMA_VERSION` 1,
`REGISTERS_SCHEMA_VERSION` 2, `CARDS_SCHEMA_VERSION` 1,
`COMPARE_SCHEMA_VERSION` 1, `CARD_VERSION` 5. `PROTOCOL_VERSION` was **not**
moved — see open item 10-a.

## Measured results

All figures are `Reports/PHASE_6_REPORT.md`'s; that file is the primary record.

### Pins, and the package cross-check

| Part | Printed pin table | Published | Cross-check |
|---|---|---:|---|
| AD9081 | Table 21, 324-ball BGA | **321** | **warns**: document states 324 |
| LMX1204 | datasheet pin table | **41** | **warns**: document states 40 |
| HMC520A | Table 4, 24-terminal LCC | **0** — rejected whole | **warns**: states 24, none published |
| LM741 | printed, never reconstructed as a grid | 0 | — |
| QPA1003P / AFE7950 / AFE7953 | none printed at all | 0 | — |

**2 of 7 built parts publish pins.** All three cross-check mismatches land in
`manifest.json` under `derived_warnings` and suppress nothing. AD9081's 3-ball
gap is a range wrapped across a line break (`… M2 to` / `M5, …`); LMX1204's
+1 is a stated-vs-published mismatch the run reports rather than reconciles.
**LMX1204's 41 pins were discovered in ticket 10** — ticket 04's coverage table
predates it and still says AD9081 only (open item 10-c).

### Numeric parse rate

| Part | Backend | Records | Parsed | Rate |
|---|---|---:|---:|---:|
| AFE7950 | ti_html | 619 | 586 | **95%** |
| AFE7953 | ti_html | 536 | 504 | 94% |
| QPA1003P | pdf_layout | 41 | 34 | 83% |
| LM741 | pdf_layout | 71 | 48 | 68% |
| AD9081 | pdf_layout | 549 | 180 | 33% |
| HMC520A | pdf_layout | 85 | 23 | 27% |
| LMX1204 | pdf_layout | — | — | **2%** (report's front matter) |

The spread is an **extraction** finding, not a grammar one — 335 of AD9081's
369 and all 26 of HMC520A's unparsed rows print no value cell at all. Recorded
in `AGENTS.md` so nobody "fixes" it by loosening the grammar.

### Card coverage

| Part | power | thermal | interface | limits | values | source refs |
|---|---:|---:|---:|---:|---:|---:|
| AFE7950 | 11 | 10 | 29 | 2 | 73 | 75 |
| AD9081 | 47 | 1 | 22 | **0** | 104 | 291 |
| LM741 | 2 | 2 | 0 | 0 | 5 | 5 |
| QPA1003P | 0 | 6 | 0 | 0 | 6 | 6 |
| HMC520A | 0 | 0 | 0 | 0 | **0** | 0 |

**377 references, 0 unresolvable.** Cross-part compare adds its own walk:
**327 references over 139 values in 8 comparisons, 0 unresolvable** — including
each delta's two operands, which live in different corpora.

### Axis coverage

| Part | Backend | Figures | high | high % | medium | low |
|---|---|---:|---:|---:|---:|---:|
| AFE7950 | ti_html | 514 | **458** | **89%** | 33 | 23 |
| AFE7953 | ti_html | 492 | 368 | 75% | 44 | 80 |
| HMC520A | pdf_layout | 107 | 53 | 50% | 31 | 23 |
| LMX1204 | pdf_layout | 54 | 23 | 43% | 5 | 26 |
| AD9081 | pdf_layout | 100 | 0 | **0%** | 0 | 100 |
| LM741 | pdf_layout | 3 | 0 | **0%** | 0 | 3 |
| QPA1003P | pdf_layout | 4 | 0 | **0%** | 0 | 4 |

Ticket floor ≥60% on AFE7950: **met at 89%**. Accuracy walk: 491 of 514 records
cite an axis page and **0** published axis strings are absent from it. The
narrowing this was built for: 514 → 30 (`--y-label "Phase Noise"`) → **14**
(`+ --near-x 1MHz`). **The three 0% parts print raster figures — that zero is
honest, not a bug**, and it is reported by `plot_axis_gap` rather than passed
over in silence.

### Compare alignment

| Parts | Aligned rows | With a delta | `only in A` | Keys refused |
|---|---:|---:|---:|---:|
| four gate corpora, 6 pairs | **1** | **0** | 1,468 | 61 |
| AFE7950 vs AFE7953 (one family) | **159** | **159** | 50 | 71 |

Two unrelated parts share almost no parametric ground, and the report argues —
correctly — that this is the right outcome rather than a coverage failure. One
hand-verified delta off the printed pages: AD9081 `TJ` +120 °C (p.4) vs LM741
150 °C (p.4) = **+30 °C**.

### Registers — **shipped, not parked**

Ticket 06 held explicit permission to ship nothing and **shipped anyway**,
against a real document's accuracy gate. LMX1204, both documents: 35 registers
each, 116 fields each, field sets tiling their register exactly 28/28, and
**232 of 232 published fields verified against the page they cite**. Two honest
absences stand: register-level access is `0` because neither document prints
that column, and 6 of 35 resets per document cite `page: null`.

### Goldens and the MCP surface

**106 golden questions over seven parts, all verifying at 100%**; no existing
question's expected answer or cited page changed. Four were added (2 card, 2
ask twins). `dsa serve --mcp` registers **thirteen** tools. Ask-pack routing
over the four gate corpora: 60 questions, 60 answered, `pin: 3  plot: 7
search: 18  spec: 32`; twin agreement unchanged at **15/16** with the same one
known miss.

### The phase acceptance gate

`Reports/PHASE_6_REPORT.md` §"The phase acceptance gate, item by item" walks
the plan's eight items and reports **8 met, 0 missed, 0 parked**. Two of them
are met in a shape the plan did not predict, and the report says so: four of
seven parts print no pin table at all (a fact about datasheets, not about the
work), and the register work that the plan allowed to park did not park.

## Reviewer notes carried forward (run 2)

Reported by the ticket reviewers, **none actioned**. These are defects in
shipped code, not stylistic notes, and they are the most important content in
this file after the gate result.

**Ticket 08**

- 08-r1 — box 5 says "with caption and conditions intact"; **`conditions` is the
  one named field no test asserts survives a failed axis parse.**
- 08-r2 — an unparseable `--near-x` value returns zero hits with **no
  explanation** whenever the catalog is fully readable, and the code claims
  otherwise.
- 08-r3 — the claim that the axis region is "the same geometry
  `render_figure_regions` clips an image from" is untested and **not exact**:
  `figure_text_regions` uses `bottom = min(y of band)` for a side-by-side band,
  `figure_anchor_map` uses each caption's own y. (That claim is still printed in
  `Reports/PHASE_6_REPORT.md` §ticket 08.)

**Ticket 09**

- 09-r1 — **the invariant-8 headline population sentence can print a negative
  count.** A row that both carries a delta and is missing from a third part is
  counted twice, so `len(rows) - compared - only_in` underflows. Hits the
  advertised 3-or-more-parts case. Code unchanged at `compare/build.py:454`.
- 09-r2 — **`_qualified` can turn a resolvable reference into one provenance
  refuses.** Confirmed by me this run (see READ THIS FIRST item 5): the doc-less
  shorthand `specs.json#rec_412` becomes `parts/<PART>/specs.json#rec_412`,
  which `parse_source` returns `None` for and `resolve_source` cannot walk — a
  derived value with an unresolvable source, which is precisely what invariant 8
  exists to forbid. The 327/327 walk passes because the values it exercised were
  all doc-qualified; it does not cover this path.
- 09-r3 — `compare_parts` is exempted from the tight-cap parametrized test **on
  a justification that is measurably false**, and the comment's claim that it is
  "asserted separately" has no backing test.
- 09-r4 — a **vacuous assertion**: both disjuncts are false in practice, so the
  line is always true and would survive any regression.

**Ticket 10**

- 10-r1 — **the `card_query` verifier has no gate on a real corpus and no
  CLI-wiring test.** The phase's headline derived-artifact benchmark is
  unprotected against regression.
- 10-r2 — the seam-guard token list was not extended for ticket 10's artifacts.

## Open items carried forward (run 2)

Every item the ticket implementers reported, verbatim in substance.

**Ticket 08**

- 08-a — **raster-plot parts publish no axes at all** (AD9081 100/100, LM741
  3/3, QPA1003P 4/4). Honest 0%, gap reported by `plot_axis_gap`; closing it is
  PNG digitization, which ADR 0005 says needs its own accuracy gate.
- 08-b — title-anchored (captionless-era) figures get no region **by design**,
  so QPA1003P/LM741 catalog no axes even where text exists. Widening it risks
  attributing one axis pair to a band holding several plots.
- 08-c — a **merged tick run states no per-tick positions**, so its scale is
  trusted from values alone (15 of AFE7950's 458). A minor-tick-labelled log
  axis arriving merged would publish as **linear**; none exists in the seven
  corpora.
- 08-d — 5 of 514 AFE7950 figures print a title whose closing bracket is absent
  from the page's text stream: label keeps the fragment, unit stays null, so
  those answer `--y-label` and never `--near-x`
  (`KNOWN_SHORTCOMINGS.md` axis item 8).
- 08-e — `gap_axis()` treats a **whitespace-only** `--near-x` as an axis filter
  and prints a gap although `plots()` does not filter on it. Over-reports rather
  than under-reports; left as-is deliberately.

**Ticket 09**

- 09-a — `protocol.py` / `AGENT.md` / `SKILL.md` do not mention `dsa compare` or
  `compare_parts`; the agent protocol's access-path examples still list
  ask/search/query/plots. Ticket 10's surface work — **and ticket 10 did not do
  it** (see 10-a).
- 09-b — `parts/AFE7950` and `parts/AFE7953` are published at
  `SPECS_SCHEMA_VERSION` 1 (no record ids), so **any comparison over the
  committed reference corpora is empty-with-a-reason**. A rebuild fixes it;
  `KNOWN_SHORTCOMINGS.md` compare item 3.
- 09-c — a section-title pairing rung would let a family pair's repeated-symbol
  parameters (`Pdiss`, `TJ`) align; deliberately not taken without a
  hand-verified pair to gate it (`KNOWN_SHORTCOMINGS.md` compare item 2).
- 09-d — no golden question exercises the compare path (no `compare_query`
  marker). Ticket 10 owned goldens and **added a `card_query` marker, not a
  compare one**, so this is still open.

**Ticket 10**

- 10-a — **`AGENT.md` and `.claude/skills/datasheet-corpus/SKILL.md` still list
  the phase-5 nine MCP tools.** `compare_parts`, `find_pin`, `find_register` and
  `get_card` are missing. Needs four names in `protocol._mcp_block()` +
  `scripts/write_skill.py`, and a `PROTOCOL_VERSION` decision — bumping it
  republishes every corpus's `AGENT.md`, which is why it was left to its own
  ticket. **Net effect today: the agent-facing protocol does not know that four
  of the thirteen tools, or `dsa card`, `dsa compare`, `dsa pins` and
  `dsa regs`, exist.**
- 10-b — `find_pin --type` reports no unconsidered population, unlike
  `find_register --field` and `find_plots --near-x`. A `pin_type_gap()` beside
  `register_field_gap()` would close it; the population is currently reachable
  via `--type unknown`.
- 10-c — measured in ticket 10 and worth recording elsewhere: **LMX1204
  publishes 41 pins**, so it is the second built part with pins; ticket 04's
  coverage table predates it and still says AD9081 only.
- 10-d — `PHASE_6_REPORT`'s ticket-04 section, `dsa verify --part AD9081 reports
  9/9 text…`, is now **historical**; it is annotated rather than rewritten.

## Status of run 1's carried items

| Run-1 item | Status after run 2 |
|---|---|
| Ticket 08 uncommitted on one machine | **closed** — committed as `6e180f8` after an audit |
| 01-a stale reference corpora | **open, unchanged** — still schema 1; blocks compare and cards on those parts |
| 01-b `resolve_source` findings are log lines | open — Phase 7 `dsa audit` |
| 01-c `card_version` granularity | open |
| 02-a prefixed ohms unparsed | open |
| 02-b layout-floor parse rate bounded by extraction | open (recorded in `AGENTS.md`) |
| 02-c nothing reads `value_si` | **closed** — tickets 07 and 09 are the consumers |
| 04-a MCP `find_pin` missing | **closed** — ticket 10 |
| 05-b / 06-d MCP `find_register` missing | **closed** — ticket 10 |
| 04-b HMC520A pin table rejected (rowspan fill) | open — would recover 24 pins |
| 04-c AD9081 loses 3 balls to a wrapped range | open |
| 04-d LM741 pin table never reconstructed | open |
| 04-e `SCLK` types as `clock` | open |
| 05-a register access absent on the reference document | open by document, not by code |
| 05-c 6 of 35 resets cite `page: null` | open |
| 06-a/b/c bit-field extraction limits | open (`KNOWN_SHORTCOMINGS.md`) |
| 07-a zero-margin criterion never triggered | open |
| 07-b AD9081 limits/thermal cards empty | open (extraction) |
| 07-c protocol does not mention `dsa card` | **open and widened** — see 10-a |
| 07-d no golden covers the card path | **closed** — `card_query` + 2 questions |
| 07-e cards built against stale corpora | open — same root cause as 01-a |
| pytest prints no summary line | **open** — still true this run |

## What a resumer should do first

1. **Fix 09-r2 before anything else builds on compare.** A derived value with an
   unresolvable `source` is an invariant-8 violation that ships today; it is
   three lines in `compare/build._qualified` (drop the shorthand case, or teach
   `parse_source` the four-segment form) plus a test that walks a doc-less
   reference.
2. **Rebuild `parts/AFE7950` and `parts/AFE7953`** (01-a / 09-b). It is the
   oldest open item in the phase and it silently empties the compare and card
   paths on the two reference parts. AFE7953 still needs an offline build path.
3. **Do the protocol/skill surface work** (10-a) and take the
   `PROTOCOL_VERSION` decision deliberately — four tools and four commands are
   invisible to agents until it lands.
4. **Fix 09-r1** (the negative population count) before anyone runs a
   three-part comparison in front of a customer.
5. **Fix the missing pytest summary line.** Two run reports in a row have had to
   reconstruct the count from junit XML.

---

# RUN 1 — the original run (tickets 01–07), kept as written

> **Historical.** Items 1, 3 and 4 of the section below were true when written
> and are now superseded: the run did stop early, but tickets 08–10 have since
> landed in run 2; ticket 08 is committed; and the phase gate has been run.
> Items 2 and 5 still stand — the suite was green then as now, and the committed
> reference corpora are still stale. Nothing below has been rewritten.

**Run date:** 2026-08-17. **Branch:** `feat/phase6-design-content`.

## ⚠ READ THIS FIRST (run 1)

**1. The run stopped early. 7 of 10 tickets landed.** Tickets 01–07 are
implemented, reviewed and committed. **Ticket 08 (plot axis catalog) is
implemented but NOT committed and NOT reviewed.** Tickets 09 (compare) and 10
(MCP surface + goldens + phase gate) were never started. **Phase 6 is not
complete and its phase gate has never been run.**

**2. The test suite is green — in both states.** Full suite, exit 0, zero
failures, zero errors, one skip (the vision smoke test, which needs an API key):

| State | Tests | Passed | Skipped | Failed | Ruff | Exit |
|---|---:|---:|---:|---:|---|---|
| Committed `HEAD` (`3572b28`, through ticket 07) | **1421** | 1420 | 1 | **0** | All checks passed | 0 |
| Working tree (`HEAD` + uncommitted ticket 08) | **1493** | 1492 | 1 | **0** | All checks passed | 0 |

**3. There is uncommitted work in the working tree and this push does not carry
it.** Ticket 08's implementation is sitting in the worktree as three untracked
files and fourteen modified tracked files — 918 changed lines plus 1173 new
ones. It passes the whole suite and ruff. It was never reviewed and was never
committed, so `git push` sends `HEAD` (ticket 07) plus this report and **leaves
ticket 08 behind on this machine only**. Anyone resuming must either commit it
or deliberately discard it. Details in [Ticket 08 forensics](#ticket-08-forensics).

**4. There is no `STOPPED.md`.** The orchestrator did not write one — I checked
the repo, the worktree root and `.scratch/design-time-content/`. This file is
therefore the only record of where the run stopped. Do not go looking for
`STOPPED.md`; it does not exist.

**5. The committed `parts/` corpora are stale and were stale before this phase
began.** Verified on disk for this report:
`parts/AFE7950/docs/datasheet-c1b4663b/specs.json` and AFE7953's equivalent are
at **`schema_version: "1"`** — the current `SPECS_SCHEMA_VERSION` is **5** — with
no record ids anywhere and a `manifest.json` carrying no `card_version`. Neither
part has a top-level `specs.json`, a `pins.json`, a `registers.json` or a
`cards/` directory. Nothing derived can cite them until they are rebuilt. Every
measured number in this report that concerns pins, registers, cards or confidence
comes from a **fresh hermetic build**, not from the committed corpora. See open
item 01-a. (The implementers reported this as "schema 2"; the on-disk value is 1.
Either way it is four or five versions behind.)

---

## 1. Commits this run

`git log --oneline`, newest first. The run's own commits are the eight from
`863081e` up:

| Commit | Subject |
|---|---|
| `3572b28` | `p6-07: design cards` |
| `215a913` | `p6-06: register bit fields` |
| `d853c0d` | `p6-05: register summary tables` |
| `dda3fd7` | `p6-04: pins` |
| `1365bcc` | `p6-03: device-table abstraction` |
| `969237d` | `p6-02: numeric layer` |
| `2eb6515` | `p6-01: derived-artifact contract` |
| `863081e` | `chore: phase 6 setup — ADR 0005 draft, LMX1204 fixtures, workflow` |

Below that, `4d413ee docs: phase 5 autonomous run report` is where Phase 5
ended. **No commit exists for ticket 08, 09 or 10.**

## 2. Verification, re-run for this report

Both commands were run fresh, twice — once against the working tree and once
against a detached worktree at `3572b28` — because the working tree contains
uncommitted code and a single number would have been ambiguous.

```
# working tree
.venv/Scripts/python.exe -m pytest tests/ -q          → exit 0
.venv/Scripts/python.exe -m ruff check src tests      → All checks passed!
```

Counts were taken from `--junitxml` rather than from the terminal, because on a
full-suite run the summary line does not reach the terminal at all — something
in the suite (very likely the MCP stdio-server tests, which take over
`sys.stdout`) swallows it. **The exit code is still trustworthy and is 0**, but
be aware that `pytest tests/ -q` on this repo prints progress dots and then
nothing. That is a reporting nuisance worth fixing; it is not a failure, and it
is not new to this phase.

| Run | tests | failures | errors | skipped | wall |
|---|---:|---:|---:|---:|---:|
| working tree | 1493 | 0 | 0 | 1 | 153 s |
| `HEAD` = `3572b28` | 1421 | 0 | 0 | 1 | 129 s |

The single skip is
`tests/integration/test_phase3_plots.py::TestPhase3VisionSmoke::test_vision_reads_one_golden_plot`
(auto-skips without `ANTHROPIC_API_KEY`) — the same skip Phase 5 reported.

## 3. Test count vs the 868 baseline

| | Tests | Passed | Skipped |
|---|---:|---:|---:|
| Phase 5 final (baseline) | 868 | 867 | 1 |
| **Phase 6 committed (through ticket 07)** | **1421** | **1420** | **1** |
| Working tree (incl. uncommitted ticket 08) | 1493 | 1492 | 1 |

**+553 committed tests, +72 uncommitted.** The bulk of the growth is in the six
new rule-test files and the two new integration gates: `test_quantities.py` 70,
`test_bitfields.py` 82, `test_cards.py` 74, `test_pins.py` 67, `test_registers.py`
66, `test_device_tables.py` 57, `test_provenance.py` 33,
`test_phase6_registers.py` 35, `test_phase6_quantities.py` 8, plus 41 in the
uncommitted `test_plot_axes.py` and 31 more spread across three modified test
files. `test_phase4_layout_gate.py` grew from the phase-4 gate to 73.

## 4. What landed, per ticket

### Ticket 01 — derived-artifact contract (committed, `2eb6515`)

ADR 0005 promoted from draft to decided and added to `AGENTS.md` as **invariant
8**: a derived artifact may contain only a verbatim cell, a value computed from
such cells by a named pure function, or a label from a checked-in lexicon; every
field carries `source` + `derivation`; no model call in the derivation path; an
unfillable field stays null and says so. Ships `provenance.py` (184 lines) with
`resolve_source`, addressable record ids on `SpecRecord`, and `card_version` as
a participant in the publish cache key. 419 new tests.

### Ticket 02 — numeric layer (committed, `969237d`)

`structure/quantities.py`: `parse_quantity` / `si_normalize` /
`parse_population`. Strictly additive, always allowed to fail, verbatim never
mutated (snapshot-asserted over every printed cell of all six corpora). Lexicon
grew as data only — all identity canonicalizations, so no published
`unit.canonical` string moved.

### Ticket 03 — device-table abstraction (committed, `1365bcc`)

`structure/device_tables.py` + `registry/device_tables.yaml`: identify → map
columns → validate → emit, one pipeline for pin tables and register summaries.
Every matched word lives in YAML; an invented "widget schedule" kind drives it
end to end in test. No consumer shipped with it, deliberately.

### Ticket 04 — pins (committed, `dda3fd7`)

`structure/pins.py` + `registry/pin_types.yaml` → `pins.json`, `dsa pins`,
`Retriever.pins()`, package cross-check, `pin_query` golden marker. Added the
wrapped-row rule to the ticket-03 abstraction (opt-in per kind via `identity:`).
`CARD_VERSION` → 2.

### Ticket 05 — register summary (committed, `d853c0d`)

`DocType.REGISTER_MAP` now routes to `pdf_layout` instead of the paragraph-only
`pdf_text`; `structure/registers.py` → `registers.json`, `dsa regs`.
`PIPELINE_VERSION` **0.4.0 → 0.5.0** so pre-existing parts do not keep serving
the paragraph-only reading. Three layout-floor defects were fixed to make the
real document readable (`_margin_bands`, `_BAND_EPSILON`, `_is_section_break`)
and those fixes improved unrelated parts — **HMC520A went from 30 spec records,
mostly valueless, to 85 with min/typ/max**, and AD9081's confidence mix moved
151/207/191 → 158/210/181 with every recorded value and page unchanged.
`tests/fixtures/alias_seed_symbols.json` was regenerated by the documented
procedure; only HMC520A's rows moved.

### Ticket 06 — register bit fields (committed, `215a913`)

The ticket that was permitted to ship nothing. **It shipped.** `registers.json`
schema 1 → 2 with per-field records; both the `bit-column` and `bit-diagram`
routes implemented; four refusals (no width → no fields; overlap/overflow
refuses the whole set; a gap is published not refused; a register is never
dropped). `dsa regs --field` is the phase's first filter selecting on a derived
value and carries the population it could not consider.

### Ticket 07 — design cards (committed, `3572b28`)

`cards/build.py` + `cards/lexicon.py` + `cards/render.py` +
`registry/cards.yaml` → `parts/<PART>/cards/*.json` and `*.md`, `dsa card`,
`Retriever.card()`. Four task-shaped views (power, thermal, interface, limits).
`SPECS_SCHEMA_VERSION` 4 → 5 to add `SpecRecord.section_title`; `CARD_VERSION`
→ 5.

### Ticket 08 — plot axis catalog (**implemented, uncommitted, unreviewed**)

See §6. Not part of this push.

### Tickets 09, 10 — not started

Ticket 09 (`compare`) and ticket 10 (`MCP surface + goldens + phase gate`) have
no code, no tests and no commits. **Ticket 10 is where the phase gate lives**,
so Phase 6 has no gate result at all. It is also where three deferred MCP tools
were parked: `find_pin` (ticket 04), `find_register` (tickets 05 and 06) and
`get_card` (ticket 07). All three still have their retrieval seams in place and
are a `server.py` registration plus a `SCHEMAS` entry each.

**Version constants as committed:** `PIPELINE_VERSION` 0.5.0,
`SPECS_SCHEMA_VERSION` 5, `PINS_SCHEMA_VERSION` 1, `REGISTERS_SCHEMA_VERSION` 2,
`PLOTS_SCHEMA_VERSION` 2, `CARD_VERSION` 5. (Uncommitted ticket 08 bumps
`PLOTS_SCHEMA_VERSION` → 3.)

## 5. Measured results

All figures below are from `Reports/PHASE_6_REPORT.md` unless marked otherwise;
that file is the primary record and carries the per-section breakdowns.

### 5.1 Pins, per part, with package cross-check

| Part | Printed pin table | Outcome | Cross-check |
|---|---|---|---|
| AD9081 | Table 21, 324-ball BGA | **321 pins published** | **warns**: document states 324, 321 published |
| HMC520A | Table 4, 24-terminal LCC | identified, **rejected whole** | records `document states 24, no pin table was published` |
| LM741 | printed, never reconstructed as a grid | no pin table, no file | — |
| QPA1003P | none printed | no pin table, no file | — |
| AFE7950 | **none printed — no pin section at all** | no file | — |
| AFE7953 | **none printed — same** | no file | — |

**No part publishes a partial `pins.json`.** Two of the ticket's own acceptance
criteria could not be met and the reason is one fact: *four of six built parts
print no machine-readable pin table*, and the two TI reference parts print no
pin section whatsoever (asserted in
`test_afe7950_build.py::TestTheReferencePartsPrintNoPinTable`).

AD9081's 321 balls: **321 high / 0 medium / 0 low** confidence. Type mix — power
85, ground 126, digital 61, analog 26, clock 7, nc 6, **unknown 10**. The 10
unknowns are labelled unknown with no evidence rather than guessed.
`dsa pins --part AD9081 --type power` returns **85 balls across 23 rails**,
hand-checked against the printed Table 21, every one cited to p.22 or p.23, with
no ground/signal/no-connect leakage. `pin_query` goldens verify **3/3 with page
cites**.

The 3-ball gap is exact and understood: the `GND` entry's ball list wraps
mid-range across two printed lines (`… M2 to` / `M5, …`), so `M2 to` is not a
key and M2/M3/M4 are dropped. Per ADR 0005 the mismatch warns, lands in
`manifest.json` under `derived_warnings`, is printed by `dsa status`, and
suppresses nothing.

### 5.2 Numeric parse rate, six built corpora

Measured by `scripts/measure_parse_rate.py`, re-parsing records rather than
reading stored fields:

| Part | Backend | Records | Parsed | Rate |
|---|---|---:|---:|---:|
| AFE7950 | ti_html | 619 | 586 | **95%** |
| AFE7953 | ti_html | 536 | 504 | **94%** |
| QPA1003P | pdf_layout | 41 | 34 | 83% |
| LM741 | pdf_layout | 71 | 48 | 68% |
| AD9081 | pdf_layout | 549 | 180 | **33%** |
| HMC520A | pdf_layout | 85 | 23 | **27%** |

**The spread is not a grammar spread, and this is measured, not asserted.** On
the TI parts, 30 of 33 and 30 of 32 unparsed rows print something the grammar
deliberately refuses (clock cycles, named latencies, a pin list in the unit
column, prose). On the layout-floor parts the cause is upstream: **335 of
AD9081's 369 unparsed rows and all 26 of HMC520A's print no value cell at all**
— a rescued grid put the numbers where no value role saw them. That is a
table-reconstruction finding, recorded in `AGENTS.md` specifically so nobody
"fixes" it by loosening the grammar.

### 5.3 Registers — **shipped, not parked**

Both halves shipped. Measured on LMX1204, built hermetically from
`tests/fixtures/pdf/lmx1204.pdf` + `LMX1204_registermap.pdf`:

| | datasheet (SNAS800B) | register map (SNAU269A) |
|---|---:|---:|
| Registers published | 35 | 35 |
| Address parsed | 35 | 35 |
| Register confidence | 35 high | 35 high |
| Reset stated | 35 | 35 |
| Reset citing an exact page | **29** | **29** |
| Register-level access published | **0** | **0** |
| Registers with a validated field set | 28 | 28 |
| Fields published | 116 | 116 |
| Field sets tiling their register exactly | 28 / 28 | 28 / 28 |
| Registers with `fields: []` + a recorded reason | 7 | 7 |
| Field-set grades | 28 medium | 28 medium |
| Fields whose printed quartet is on the page they cite | **116 / 116** | **116 / 116** |

Ticket 06's accuracy gate: a hand-verified sample at **100% with no partial
credit** (R0, R2, R3, R24, R25 — 28 fields read cell by cell off pp. 4, 5, 19 and
checked as an exact ordered list), plus a page-truth walk over **every**
published field of both documents — 232 fields, 232 hits. LMX1204's golden set
verifies **10/10 text, 4/4 register, 1/1 ask, 1/1 search**.

Two honest absences, both reported rather than smoothed: **register-level access
is 0 because neither document prints a register-level access column** (TI states
access per bit field, and composing one would be a value no page states), and
**6 of 35 resets cite `page: null`** because their declaration heading survived
extraction as a bare paragraph. A page borrowed from a neighbouring table was
implemented, measured to produce one wrong citation per document, and removed.

### 5.4 Design cards

Rows published per card, and the invariant-8 provenance walk:

| Part | power | thermal | interface | limits | values | source refs |
|---|---:|---:|---:|---:|---:|---:|
| AFE7950 | 11 | 10 | 29 | 2 | 73 | 75 |
| AD9081 | 47 | 1 | 22 | **0** | 104 | 291 |
| LM741 | 2 | 2 | 0 | 0 | 5 | 5 |
| QPA1003P | 0 | 6 | 0 | 0 | 6 | 6 |
| HMC520A | 0 | 0 | 0 | 0 | **0** | 0 |

**377 references, 0 unresolvable** — every `source` and `sources` entry of every
value of every card resolves to a real record with a printed page, and the
primary reference's record page *is* the page the card cites. That is the
phase's most important test.

AFE7950's limits card is hand-verified against pp. 4/6: `TJ` 150 °C vs 110 °C =
40 °C margin, `VDD` 1.2 V vs 0.95 V = 0.25 V margin. Six more parameters are
listed as uncomparable **by name and with the reason**, including two supply
pairs refused as an ambiguous join. Empty cards are written, not omitted, and
state what they looked for — HMC520A's four are all empty.

### 5.5 Axis coverage (ticket 08 — **measured from uncommitted code**)

Ticket 08 wrote `scripts/measure_axis_coverage.py` but never recorded its output
anywhere, because the ticket never reached its report step. **I ran it for this
report.** These numbers come from code that is in the working tree, passes the
suite, and has not been reviewed — treat them as indicative, not as a landed
result:

| Part | Figures | high | high % | medium | low | axes read |
|---|---:|---:|---:|---:|---:|---|
| AFE7950 | 514 | 458 | **89%** | 33 | 23 | 934 linear / 15 log |
| AFE7953 | 492 | 368 | 75% | 44 | 80 | 766 linear / 14 log |
| HMC520A | 107 | 53 | 50% | 31 | 23 | 137 linear / 0 log |
| AD9081 | 100 | 0 | **0%** | 0 | 100 | 0 / 0 |
| LM741 | 3 | 0 | **0%** | 0 | 3 | 0 / 0 |
| QPA1003P | 4 | 0 | **0%** | 0 | 4 | 0 / 0 |

The ticket's floor is **≥60% `axis_confidence: high` on AFE7950's 514 figures**;
89% clears it. The three 0% parts print their figures as raster images, so there
is no axis text to read and the honest number is zero — which is what the script
returns. AFE7950/AFE7953 were measured against the committed (stale) corpora;
the four gate parts were built fresh into a scratch parts dir per the script's
documented procedure.

**None of this has been reviewed, gated or committed.**

## 6. Ticket 08 forensics

> **Historical.** This section describes the uncommitted state as of run 1. Run
> 2 audited that work, extended it, and committed it as `6e180f8`; the file
> sizes below are smaller than what shipped.

Untracked (new):

- `src/datasheet_analyzer/structure/plot_axes.py` — 540 lines
- `tests/unit/test_plot_axes.py` — 533 lines, **41 tests, all passing**
- `scripts/measure_axis_coverage.py` — 100 lines, with a reproduction procedure
  in its docstring

Modified (tracked, 918 changed lines): `cli.py`, `config.py`,
`extract/pdf_layout.py` (+132), `mcp_server/responses.py`, `models.py` (+68),
`pipeline.py`, `query.py`, `retrieve/project.py`, `retrieve/results.py`,
`retrieve/retriever.py` (+89), `structure/confidence.py`,
`tests/integration/test_phase3_plots.py` (+136),
`tests/integration/test_phase4_layout_gate.py` (+88),
`tests/unit/test_plots_query.py` (+206). `PLOTS_SCHEMA_VERSION` 2 → 3.

**Not** modified: `Reports/PHASE_6_REPORT.md`, `KNOWN_SHORTCOMINGS.md`,
`AGENTS.md`, `README.md` — so ticket 08 has no report section, no recorded
shortcomings and no docs. Its scratch prototypes (`.scratch/tmp/proto*.py`) are
timestamped 08:44–08:51 and its own green junit run is timestamped 09:37. The
agent finished implementation and testing and then stopped before review,
documentation and commit.

**Judgement, offered plainly:** the code is there and it is green, but "green
suite" is not this phase's bar. Every other ticket in this run shipped a
measured report section, named its refusals, and recorded what it could not do.
Ticket 08 has none of that, and its 60% criterion, its rotated-y-axis criterion,
its log-scale criterion and its "no plot is lost to a failed axis parse"
criterion have not been checked by anyone. I did not commit it, per
instructions. **Do not merge it without a review pass.**

## 7. Open items and reviewer notes carried forward

Every item reported by the ticket implementers, verbatim in substance and
attributed. Nothing here has been actioned.

### From ticket 01 (contract)

**01-a — the committed corpora are stale and cannot be cited.** `parts/AFE7950`
and `parts/AFE7953` still carry `specs.json` at schema 1 (reported as 2; measured
as 1, against a current `SPECS_SCHEMA_VERSION` of 5) with no record ids and a
manifest with no `card_version`, so nothing derived can cite them until they are
rebuilt. That is the intended one-shot republish the skip gate now forces;
it could not be done in-run because **AFE7953 has no offline build path** (no
recorded TI document-viewer pages) and rebuilding AFE7950 needs the same replay
corpus the tests use. It was flagged as "worth a rebuild before ticket 07 builds
cards against those parts" — **ticket 07 then landed without it** (see 07-d).
This is the highest-priority carried item.

**01-b — `resolve_source` findings are log lines, not findings.** Its
ambiguity/absence results are reported only through `log.warning`. When
`dsa audit` lands (Phase 7) it should surface them as structured findings.
Noted, not built, because this ticket had no consumer.

**01-c — `card_version` granularity.** It currently gates the whole corpus
republish, which was the only correct granularity when no `cards/` directory
existed. Ticket 07 now writes `cards/*.json`, so a card-only regeneration path
may be worth having instead of a full republish.

### From ticket 02 (numeric layer)

**02-a — prefixed ohms stay unparsed on purpose.** `kΩ`, `MΩ` (3 rows). Giving
them a canonical form (`kohm`/`Mohm`) would rename a unit string the committed
corpora already publish and which `tests/fixtures/alias_seed_symbols.json`
records as ground truth — a fixture regeneration for 3 rows. Recorded in
`units.py` as honest lexicon growth for a later ticket.

**02-b — the layout-floor parse rates are bounded by extraction, not grammar.**
AD9081 33%, HMC520A 27%. Measured: 335 of AD9081's 369 and all 26 of HMC520A's
unparsed rows print no value cell at all, because a rescued grid never put the
numbers in a value role. This is a table-reconstruction finding, recorded in the
report **and in `AGENTS.md`** so nobody "fixes" it by loosening the grammar.

**02-c — nothing user-facing reads `value_si` yet.** By design: tickets 07 and
09 are the consumers, and `parse_population` exists so they cannot drop a row
from a decision without saying so. Ticket 09 never ran, so half that consumer
set is still missing.

**02-d — `DERIVATION` is exported and unused.** `"parse_quantity+si_normalize"`
was exported for ticket 07 to stamp on `DerivedValue.derivation`. (Ticket 07 has
since landed and does stamp derivations; the note is left here as reported.)

### From ticket 03 (device-table abstraction)

**03-a — coverage not measured in this ticket.** No consumer, and `RawDocument`s
are not published. It belongs to ticket 04, where the first consumer runs it
over real pin tables. The phase report says so explicitly rather than leaving a
blank.

**03-b — the synthetic fixtures draw column rules, and that is not cosmetic.**
`pdf_layout`'s occupancy check rejects a fully-packed unruled grid, and a pin
table fills every cell — real pin tables print rules for the same reason. **A
device table in an unruled PDF will not reach this module at all.** That is an
extraction finding for ticket 04 to measure, not something to fix by loosening a
gate here.

**03-c — two judgement constants are calibrated against synthetic fixtures
only.** `KEY_SHAPE_MIN = 0.6` and `MAX_EXPANSION = 256`. Ticket 04 was asked to
re-check them against the six real corpora and move them with a measurement if a
real pin table trips either. (Ticket 06 subsequently lowered the bar to
`key_shape_min: 0.25` for the `bitfield` kind only, as data, with its reason
recorded.)

### From ticket 04 (pins)

**04-a — MCP `find_pin` is not implemented.** The ticket's prose names it but no
checkbox requires it, and the plan assigns "MCP surface + goldens + phase gate"
to ticket 10. The seam is in place (`Retriever.pins`, `PinHit.as_dict`,
`pin_gap`), so it is a `server.py` registration plus a `SCHEMAS` entry.
**Ticket 10 never ran**, so this is still missing.

**04-b — HMC520A's pin table is rejected for a defect one layer up.** Ticket
09's (phase-4) rowspan materialization fills `15` into the EPAD row, whose
printed pin cell is blank. The fix belongs in `pdf_layout`'s materialization —
an exposed-pad row has no pin number — **not** in the pin reader; patching it
downstream would merge two distinct printed entries and tell a designer pin 15
is named `LO EPAD`. **Would recover 24 pins for that part.**

**04-c — AD9081 loses 3 of 324 balls to a range wrapped across a line break.**
The `GND` entry's ball list wraps (`… M2 to` / `M5, …`), so `M2 to` is not a key
and M2/M3/M4 are dropped. Recovering them means joining a range across a line
break in the layout floor or in `expand_keys`; left alone because the cross-check
reports the loss exactly and a speculative join could invent balls. **Note the
coupling: this is the mismatch the ADR-0005 warning path is currently
demonstrated on, so closing it needs a different (or synthetic) mismatch fixture
in the gate.**

**04-d — LM741's real "Pin Functions" table is never reconstructed as a grid.**
It lands as paragraphs, so the part publishes no pins. An extraction finding for
`pdf_layout`, recorded as such.

**04-e — `SCLK` classifies as `clock`, not `digital`** (evidence
`name:"sclk"`). It is the SPI serial clock, so both readings are defensible and
the lexicon currently prefers the clock reading. Flagged rather than silently
tuned; changing it is a one-line YAML edit if a designer disagrees.

### From ticket 05 (register summary)

**05-a — the `name → access` golden register question is genuinely impossible on
the reference document and is absent.** Neither `LMX1204_registermap.pdf` nor
`lmx1204.pdf` prints a register-level access column anywhere: TI states access
per **bit field**, in the per-register field tables (`Type`: R, R/W), and Table
1-2 "Device Access Type Codes" is only the legend for those codes.
`registers.json` publishes `access: ""` for all 70 LMX1204 records — the honest
reading — and there is no printed value a golden question could be held to. Two
alternatives were considered and rejected: parsing access out of the summary's
prose ("(read-only, optional, lock detect)") is guessing, and composing a
register's access from the unanimous `Type` of its bit-field rows requires
reading those tables and would be fragile against their measured reconstruction
quality (all 30 come back `rescued`, several with the header row swallowed).
The **code path is real and gated** — a synthetic summary that does print
`Access` publishes it verbatim (`TestAccessIsVerbatimOrAbsent`) and `dsa regs`
renders it. The two register golden questions the document does support
(address → name, twice: hex and decimal; and name → reset) verify 3/3 with page
cites.

**05-b — MCP `find_register` deferred to ticket 10**, following ticket 04's
precedent: the MCP server registers nine tools and neither device-table
consumer, and adding one of the two in isolation would split that surface across
two tickets. **Ticket 10 never ran.**

**05-c — 6 of 35 resets per document cite `page: null`.** Their declaration
heading survived extraction as a bare paragraph with nothing to pin it to. The
value and the printed line it was read from are still published. Closing this
needs the layout floor to keep a page on paragraph lines — a separate change. A
page borrowed from a neighbouring table was implemented, measured to produce one
wrong citation per document, and removed.

### From ticket 06 (register bit fields)

**06-a — 6 registers per document publish no fields because the layout floor's
reconstruction gate rejected their field tables.** R7, R8, R9, R16, R72, R86 —
7 of 38 candidates rejected: 5 × "rows do not span columns", 2 × "columns not
stable across rows". An extraction finding fixable only in
`extract/pdf_layout.py`, and it would benefit every table of every part.
`KNOWN_SHORTCOMINGS.md` entry #1.

**06-b — R90 publishes no fields because the document itself prints overlapping
ranges** (`15:8` then `15:0`, SNAU269A p.24 / SNAS800B p.54 — the second should
be `7:0`). Not fixable here: inventing `7:0` is exactly the plausible-but-
unstated value ADR 0005 forbids.

**06-c — some field descriptions end with a swept-up navigation line** ("Return
to the Summary Table."). Bit ranges, names, access and resets are unaffected.
Filtering by wording would put a vendor's phrasing in code, so the fix is a
tighter region end in `pdf_layout`. `KNOWN_SHORTCOMINGS.md` entry #3.

**06-d — MCP `find_register` (now also carrying bit fields) stays deferred to
ticket 10**, where ticket 04's `find_pin` also went.

**06-e — the bit-diagram route publishes no per-field access or reset**, because
a diagram prints neither in the header run it is read from. Honest absence, but
worth revisiting if a real diagram-printing document is added and prints an
access row. (Also: that whole route has **no real-document gate** —
`KNOWN_SHORTCOMINGS.md` entry #2.)

### From ticket 07 (design cards)

**07-a — the zero-margin criterion is conditional and did not trigger.** No
zero-margin parameter exists in the built parts. Only two parameter pairs
compare at all (both AFE7950, both with headroom, both hand-verified against
pp. 4/6), because a join needs both tables to extract with values and only
AFE7950 manages that. The flag — and its across-a-unit-prefix twin, 1850 mV vs
1.85 V, which exact float equality would miss — is pinned by unit test, and the
absence is recorded in `KNOWN_SHORTCOMINGS.md` and the phase report rather than
papered over.

**07-b — AD9081's limits card has no rows and its thermal card has one, for an
extraction reason.** Its absolute-maximum and thermal-resistance tables (both
p.21) reconstruct as rows with a symbol and no value cells, and both are
attributed to the following section heading. The cards report that honestly
(population sentences, every candidate pair refused by name); the fix belongs in
`extract/pdf_layout.py`. Recorded in `KNOWN_SHORTCOMINGS.md`.

**07-c — `protocol.py` / `AGENT.md` / the checked-in skill do not mention
`dsa card`.** Adding it would bump `PROTOCOL_VERSION` and require regenerating
`SKILL.md`, which is ticket 10's surface work. The cards are discoverable today
via `dsa card`, `dsa status` and the `cards/` directory. **Ticket 10 never ran,
so the agent-facing protocol still does not know cards exist.**

**07-d — no golden question covers the card path.** Ticket 10 owns the phase's
goldens, and the phase-5 rule is that a new path proves itself against an
existing question's ground truth (a `card_query` marker plus a verifier would be
that ticket's shape). **Ticket 10 never ran.**

**07-e — cards were built against stale corpora.** `parts/AFE7950` and
`parts/AFE7953` were already stale before this ticket (`specs.json`
schema_version 1) and are untouched; card behaviour on the reference part is
measured on a fresh hermetic build, as the confidence and pin work already is.
Same root cause as 01-a.

### Cross-cutting: what ticket 10's absence costs

Three MCP tools (`find_pin`, `find_register`, `get_card`) are unregistered, the
protocol/skill files do not know about `dsa pins`, `dsa regs --field` or
`dsa card`, no golden question covers pins-beyond-AD9081 or cards at all, and
**the Phase 6 phase gate has never been run**. Four separate tickets deferred
work to ticket 10 on the reasonable assumption that it would follow. It did not.

## 8. What a resumer should do first

> **Superseded** by run 2's list above. Items 1 and 3 are done (ticket 08 was
> audited and committed; tickets 09 and 10 ran). Items 2 and 4 are still open.

1. **Decide about ticket 08.** Review the working-tree diff, then either commit
   it with a report section and shortcomings entries, or discard it. It is
   currently unpushed and exists on one machine.
2. **Rebuild `parts/AFE7950` and `parts/AFE7953`** (item 01-a). Everything
   derived — pins, registers, cards, confidence — is measured on hermetic builds
   because the committed corpora cannot be cited. AFE7953 needs an offline build
   path before this is possible.
3. **Run ticket 09, then ticket 10**, and expect ticket 10 to be larger than
   planned: it has accumulated four tickets' worth of deferred surface work.
4. **Fix the missing pytest summary line** (§2) before the next autonomous run.
   A run that cannot print "N passed" makes every report in this series harder
   to trust than it needs to be.
