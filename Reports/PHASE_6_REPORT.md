# PHASE 6 REPORT — Design-Time Content

**Status: shipped, with two components parked and recorded.** Supersedes
`Reports/PHASE_6_PLAN.md`. Every number below was measured by a test that runs;
where a number is worse than the plan hoped for, the number is here rather than
the hope.

The claim the phase is allowed to make, from the plan's acceptance gate:

> *the corpus answers schematic-capture and bring-up questions, and every
> derived number traces to a printed page.*

Both halves hold, with the scope the measurements below define. The second half
holds without qualification: **every value on every card and every comparison
resolves back to a record and the page that printed it**, asserted
programmatically rather than asserted by hand.

---

## The contract that made the rest possible (ADR 0007, invariant 8)

Phase 6 is the first phase whose artifacts are not verbatim-extracted, which
put pressure on invariant #1 ("LLM writes indexes, never content"). The
resolution is `docs/adr/0007-deterministic-derived-artifacts.md`, recorded as
**AGENTS.md invariant 8**: a derived artifact may contain only (a) values
copied verbatim, (b) values computed from those by a documented pure function,
or (c) structural labels from a checked-in lexicon; every field carries
`source` (record id + page) and `derivation` (the named rule); **no model call
may appear anywhere in a derivation path**; a field that cannot be filled stays
null and says why.

What makes it checkable rather than aspirational is `derive/provenance.py`:
one `<artifact>#<record id>` source format, one resolver that turns a source
string back into the record and printed page it names, and one checker that
walks any derived artifact and reports every violation. Record ids are pydantic
`@computed_field` properties — pure functions of a record's coordinates — so
they cannot drift from what they describe.

The phase's own numbers for that contract: **288 filled values across eight
cards (four each for AFE7950 and AD9081) resolve to a record and a printed
page, 0 violations**, and the AFE7950/AFE7953 comparison's values resolve
likewise (`audit_comparison` returns `[]`).

---

## Acceptance gate — all eight items

Run by `tests/integration/test_phase6_gate.py` (31 tests, 35 s), which prints
every number it measures.

| # | Gate | Result | Measured |
|---|---|---|---|
| 1 | Pin tables extract or are honestly rejected; golden pin questions at 100% | **PASS** | AD9081 **210** pins, LMX1204 **41**; 9 other parts publish none, each with a recorded reason; golden pin questions **2/2** |
| 2 | Package cross-check runs on every part; a mismatch is asserted | **PASS** | ran on **2/2** parts with a pin table; **2** mismatches, both warnings: AD9081 declares 324 / table yields 210, LMX1204 declares 40 / table yields 41 |
| 3 | Register summary extracts with a golden set; bit fields pass or park | **PASS (parked half)** | **35** registers published for LMX1204, address→name verified by value (`0x11`/`0x11`/`17` are one question); bit fields **parked** with a measured reason |
| 4 | All four cards build for AFE7950 and AD9081; every value resolves | **PASS** | 8 cards, **288/288** filled values resolve to a record + page, **0** provenance violations; golden card questions **4/4** |
| 5 | `parse_quantity` covers every row of the shapes table incl. the `None` rows | **PASS** | **15** cases: 11 printed shapes → their kind, 4 unparseable → `None` |
| 6 | `dsa compare AFE7950 AFE7953` deltas, unparsed population reported | **PASS** | **742** rows, **380** with an SI delta, **334** present in one part only; coverage 415/459 compared; unparsed named per part (21/616 and 21/534) |
| 7 | Axis metadata ≥ 60% of AFE7950's 514 figures at `high` | **PASS** | **400/514 = 77.8%** (floor 60%); AFE7953 375/492 = 76.2%; 15 log axes each, marked `low` rather than guessed |
| 8 | All phase-5 goldens still at 100%; `pytest` offline, `ruff` clean | **PASS, with one recorded gap** | golden Q&A **90/90 (100%)** across six parts; spec **28/28**; plot **11/11**; ask **8/8**; search **4/4 where the index exists**, **2 blocked** on a missing index (AFE7950, AFE7953 — recorded, pre-existing) |

### Gate 8's one gap, stated plainly

AFE7950 and AFE7953 have no `search_index.json` anywhere in this tree, so the
full-text path **cannot run** for them: `dsa verify` reports
`search unavailable`, which is "could not look", never "nothing found". The
cause predates this phase (commit `c1d6180`): both parts' committed manifests
cite every section as `@library/docs/…` while `/library/` is gitignored and
the section files are the tracked copies under `parts/<PART>/docs/`. Before
that was repaired locally the corpus check scored **3/21** and **1/13** for
those two parts — every failure "corpus has answer ❌ / page cite ✅", i.e. the
corpus could not be read at all. Copying the part-local artifacts into the
library (which is what the manifest already claimed) restored **21/21** and
**13/13**. Republishing, which would also write the missing search index,
needs network access for the TI figure path and could not be done here.
Full write-up, including the shadowing rule that hid a *complete* library copy
behind a stale part-local one, is in `KNOWN_SHORTCOMINGS.md`.

The gate pins the blocked set to exactly `{AFE7950, AFE7953}` and fails if it
grows **or** shrinks without the record being updated.

---

## What shipped, component by component

### 1. Normalized numeric layer (`structure/quantities.py`)

Strictly additive over the verbatim strings, which are never mutated. Parses
point / range / bound / tolerance shapes, SI prefixes, scientific notation and
both unicode minus signs; `See Figure 7` returns `None`, recorded as
`parse_confidence: none`.

**Measured parse rate across the corpora that carry parsed specs: 1108/1150 =
96.3%** (AFE7950 96.6%, AFE7953 96.1%). The 42 unparsed rows are listed
individually by `tests/integration/test_phase6_parse_rate.py` — they are cells
like `1, 2, 3, 4, 6 or 8` and `AC Coupling Only`, which are not quantities.
Every consumer that sorts or compares reports its own unparsed population.

### 2. Device-table abstraction (`structure/device_tables.py`)

One identify → map → validate → emit pipeline with the header vocabulary in
`registry/device_tables.yaml`, and two consumers. A validation failure rejects
the table **whole** with a recorded reason.

### 3. Pins (`pins.json`, `dsa pins`, MCP `find_pin`)

| Part | Pins | By lexicon label |
|---|---|---|
| AD9081 | 210 | power 79, ground 15, analog 24, digital 69, clock 7, nc 6, unknown 10 |
| LMX1204 | 41 | power 4, ground 7, analog 2, digital 4, clock 24 |
| AFE7950, AFE7953 | 0 | the datasheets print no pin table (recorded) |
| HMC520A | 0 | its one pin table is rejected whole — duplicate designator (recorded) |
| lm741, QPA1003P, CA1389, DQ1225, PMA1-14LN+, ZX10R-2-183-S+ | 0 | no readable pin table |

Multi-pin rows expand and keep the printed cell in `expanded_from`; every label
names the lexicon entry behind it in `type_evidence`; `unknown` is a legitimate
output (10 of AD9081's 210).

### 4. Registers (`registers.json`, `dsa regs`, MCP `find_register`)

`DocType.REGISTER_MAP` now routes to `pdf_layout` for every vendor — a
documented behaviour change that invalidated cached extractions and carried
**PIPELINE_VERSION 0.4.0 → 0.5.0**. Read as paragraphs the reference register
map yielded zero tables; read through the layout floor it yields 13.

**35 registers published for LMX1204**, from `Table 7-1` of its datasheet,
each cited to the page that printed it. That table prints no reset or access
column, and the tool says so instead of filling them — a blank reset read as
`0x00` is what breaks a bring-up sequence. Two honest failures are recorded in
`KNOWN_SHORTCOMINGS.md`: the reference register map's *own* summary table is
lost to a furniture-detector misread in the layout engine, and one row of 35
cites a page one early because HTML-derived tables have no per-row page
geometry.

**Bit fields are parked** (ticket 06). The document prints 35 register field
tables; the layout engine hands over 12, of which 4 survive validation — 13
fields, all 13 correct. Recall 11%, not precision. Nothing is published,
nothing imports `derive/bitfields.py`, and `dsa regs --field` says out loud
that no bit breakdown exists rather than returning an empty result. A wrong bit
range is acted on by a driver and fails silently; that is why this parked.

### 5. Design cards (`cards/*.json` + `.md`, `dsa card`, MCP `get_card`)

| Part | power | thermal | interface | limits |
|---|---|---|---|---|
| AFE7950 | 134 rows / 143 values | 10 / 12 | 11 / 14 | 25 / 29 |
| AD9081 | 30 / 87 | 1 / 2 | 1 / 1 | 0 / 0 |

Every one of those 288 values resolves. AD9081's thin thermal and interface
cards are not a card bug: its spec record ids are not unique within the
document (549 records, 259 distinct ids), so a card refuses to cite a record it
cannot address, names the count in `unresolved`, and carries a warning. The
cost is written down in `KNOWN_SHORTCOMINGS.md` with the one-line fix and the
schema bump it needs. AD9081's `limits` card is empty — an honest answer: no
abs-max/recommended pair in that document parsed on both sides.

`DSA_CARD_VERSION` participates in the publish cache key, proven end to end.

### 6. Plot axis catalog

Geometric and deterministic: tick clusters along the figure region's edges,
rotated y titles via span direction, log axes marked rather than guessed.

| Part | Figures | `high` | Log axes |
|---|---|---|---|
| AFE7950 | 514 | 400 (77.8%) | 15 |
| AFE7953 | 492 | 375 (76.2%) | 15 |

The catalog is what makes `find_plots` narrow hundreds of figures before a
vision token is spent. A figure whose axes could not be read matches **no**
axis filter — nulls stay null.

### 7. Cross-part compare (`dsa compare`, MCP `compare_parts`)

AFE7950 vs AFE7953: **742 rows, 380 with an SI delta, 334 present in one part
only** (reported, never dropped), coverage 415/459 compared, and the unparsed
population named per part. Every value resolves back to its own corpus.

### 8. MCP surface (this ticket)

Nine tools became **thirteen**: `find_pin`, `find_register`, `get_card` and
`compare_parts`, plus axis filters (`x_label`, `y_label`, `near_x`, `near_y`)
on `find_plots`. Each new tool declares its response schema, ships it to
clients in `_meta`, carries citations and a confidence grade, and is bounded by
the same `DSA_MCP_MAX_TOKENS` cap with the same "truncation is never silent"
rule. `PlotHit.as_dict()` gained an `axes` block, so the catalog is visible to
every front end at once.

The JSON-Schema subset in `retrieve/pack.py` gained schema-valued
`additionalProperties` for exactly one reason: a card's `values` is keyed by
column name, and a declared contract that stops describing the payload at the
node where the provenance envelope lives is not worth shipping.

### 9. `dsa ask` routes pin and register questions

Two new deterministic routes, tried **before** the spec ladder, each guarded
the way the plot route already was: vocabulary alone routes nothing — the
artifact must exist *and* return a record.

```
which pins are ground?                    -> route=pin       DAP  DAP  [ground] — §4, p.4
what is the reset value of R17?           -> route=register  0x11  R17 — §7.1, p.32
max junction temperature                  -> route=spec      TJ 150 °C (max) — §5.1, p.5
```

`tests/unit/test_ask_derived_routes.py` (17 tests) asserts both halves, and the
half that matters for phase 5 is the declining half: a corpus with no pin table
routes exactly as it did before.

---

## Goldens

Golden sets gained **pin** questions (AD9081: "which pins are ground?", "what
is pin A1 on this device?" — both `ask_query: {route: pin}`, so they run inside
`dsa verify` with no new machinery) and **card** questions (AD9081 power +
interface, AFE7950 thermal + limits).

`dsa verify` across all six benchmarked parts:

| Part | Golden Q&A | spec | plot | ask | search | cards |
|---|---|---|---|---|---|---|
| AD9081 | 8/8 | 1/1 | 1/1 | 3/3 | 1/1 | 2/2 |
| AFE7950 | 21/21 | 12/12 | 3/3 | 1/1 | 0/1 (no index) | 2/2 |
| AFE7953 | 13/13 | 7/7 | 1/1 | 1/1 | 0/1 (no index) | — |
| HMC520A | 15/15 | 3/3 | 3/3 | 1/1 | 1/1 | — |
| LM741 | 17/17 | 3/3 | 2/2 | 1/1 | 1/1 | — |
| QPA1003P | 16/16 | 2/2 | 1/1 | 1/1 | 1/1 | — |
| **total** | **90/90** | **28/28** | **11/11** | **8/8** | **4/4 runnable** | **4/4** |

A **card** golden could not be expressed as a `GoldenQuestion`: the model
(frozen by ticket 01) carries no `card_query` marker and `cli.py` was frozen
too. Rather than bend an existing marker into meaning something else, card
questions live in a `cards:` block of the same per-part YAML, ignored by
`load_golden_yaml` and verified by `evalh.citations.verify_card_queries` — the
rule is the phase's: the named card must carry a row with the expected printed
values, that row's own citation must land on a page the question cites, and the
cited PDF page must really print them. They run in the phase gate rather than
in `dsa verify`; wiring them into the command is four lines in the frozen file.

---

## Schema, version and CLI changes

- `PIPELINE_VERSION` **0.4.0 → 0.5.0** (register-map routing invalidates cached
  extractions for those documents).
- `SPECS_SCHEMA_VERSION` **2 → 3** (serialized record ids + the parsed numeric
  layer). `PINS_SCHEMA_VERSION`, `REGISTERS_SCHEMA_VERSION`,
  `CARDS_SCHEMA_VERSION` = 1. `PLOTS_SCHEMA_VERSION` deliberately unchanged:
  the axis fields are additive and an old file loads as `unknown`.
- New setting `DSA_CARD_VERSION` (default 1) — the version of the *derivation
  rules*, in the publish cache key.
- New commands `dsa pins`, `dsa regs`, `dsa card`, `dsa compare`; exit 3
  (`EXIT_NOT_IMPLEMENTED`) is retained and still tested, distinct from 1 (no
  match) and 2 (bad scope).
- New MCP tools `find_pin`, `find_register`, `get_card`, `compare_parts`; axis
  filters on `find_plots`.
- New files per document: `pins.json`, `registers.json`. New per part:
  `cards/<kind>.json` + `.md`.

## Docs updated on landing

`AGENTS.md` (invariant 8; module map gains `structure/quantities.py`,
`structure/device_tables.py`, `structure/plot_axes.py`, `derive/pins.py`,
`derive/registers.py`, `derive/bitfields.py`, `derive/cards.py`,
`derive/compare.py`; the register-map caveat, the MCP row and the answer-pack
routing sentence rewritten) · `README.md` (both stale caveats amended — the
register-map one and "spec values are never parsed", which becomes "verbatim
values are authoritative; the parsed layer is additive and may be absent" —
plus worked sections for the four new commands and the new corpus layout) ·
`CONTEXT.md` (**Quantity**, **Device table**, **Design card**) ·
`docs/adr/0007-deterministic-derived-artifacts.md` · `KNOWN_SHORTCOMINGS.md`
(ten entries) · `protocol.py` / `AGENT.md` / the checked-in skill (the four
derived tools are named; the worst-case project doc now measures 1696 of its
1700-token ceiling, which is why they are named rather than explained there).

## Parked, with reasons

Every entry is in `KNOWN_SHORTCOMINGS.md` with what is missing, why, what the
tool does instead, and what would close it.

1. **Register bit fields** — recall 11% against the reference map; wrong bit
   ranges are worse than absent ones.
2. **The reference register map's own summary table** — a furniture-detector
   misread in the layout engine deletes register R0's address cell.
3. **AFE7950/AFE7953 publish no pin table** — the datasheets print none.
4. **HMC520A's pin table is rejected whole** — 24 real pins lost to a
   row-continuation misread; a partial pin table is worse than none.
5. **AD9081's spec ids are not unique within its document** — 549 records, 259
   ids; cards refuse the un-addressable rest and say how many.
6. **No built part prints a zero-margin parameter** — the `limits` flag is
   proven synthetically and asserted as a property over real data.
7. **HTML-derived tables give every row the page the table starts on** — 1 row
   of 35 measured on LMX1204.
8. **AFE7950/AFE7953 reference a library that holds only their figures** —
   pre-existing; no search index for either; repaired locally, not in the repo.
9. **A published card is not invalidated when its document moves** — caught by
   `audit_card` rather than served.
10. **`dsa plots` has no axis flags** — the filters exist one layer down and in
    MCP; wiring them to the CLI is four lines in the frozen `cli.py`.

## Out of scope, kept out

Geometric ball-map reconstruction; vision fallback for unparseable pin tables
(it would put a model in the content path, contradicting invariant 8); curve
digitization; cross-part interface validation. All four remain recorded in the
plan and unbuilt.
