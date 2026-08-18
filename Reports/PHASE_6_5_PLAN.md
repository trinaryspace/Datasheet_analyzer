# PHASE 6.5 PLAN — Extraction Fidelity

**Status: planned.** Execution contract for `.scratch/extraction-fidelity/`.
Superseded on landing by `Reports/PHASE_6_5_REPORT.md`.

**Depends on Phase 6.** Every defect below was found by Phase 6's gates and is
recorded with a measured number in `KNOWN_SHORTCOMINGS.md`. Nothing here is a
new capability; this phase makes the capabilities already shipped read the page
correctly.

**Scope decision taken before writing**: this is a *fidelity* phase, not a
features phase. It adds no new artifact, no new CLI verb and no new MCP tool.
Its output is the same artifacts, measurably more correct.

## Why

Phase 6 shipped its acceptance gate 8/8 and parked one component. Reading the
ten recorded shortcomings together, the striking thing is how few root causes
there are. **Six of the ten trace to two files**, and the largest four all
trace to one:

| Where the defect lives | Shortcomings it causes |
|---|---|
| `extract/pdf_layout.py` | register-map summary lost; bit fields parked; HMC520A pin table rejected; per-row page attribution missing |
| `structure/specs.py` (record identity) | AD9081 cards refuse most of their rows |
| everything else | four small, independent items |

The pattern is consistent and worth stating plainly: **the derive layer is not
the problem.** Where a table reaches it, it reads it correctly — ticket 06
measured 100% precision on every bit field it was handed, and refused every
table it could not trust. What is failing is the layer underneath, and the
honest refusals Phase 6 built are what made that visible instead of letting
wrong values through.

That is why this phase is worth doing before Phase 7 (Reach & Trust). Phase 7
multiplies the part count; multiplying a corpus whose extraction floor drops
two thirds of one document's tables multiplies the drop.

## The constraint that shapes the plan

`PdfLayoutBackend.output_version` (currently `tables-08`) participates in the
extraction cache key. **Any change to `extract/pdf_layout.py` that changes
output invalidates all 196 MB of cached extractions** and forces a re-extract
of every document in the corpus.

`SPECS_SCHEMA_VERSION` has the same property one layer up: bumping it
invalidates every citation already written, because a record's id is a pure
function of its coordinates and the fix changes those coordinates.

Both bumps are unavoidable here. The plan's shape follows directly:

> **Every change that invalidates the cache lands in one wave, and the corpus
> is rebuilt exactly once, at the end.**

Landing them piecemeal would mean three full re-extractions and three rounds of
re-measuring goldens. The cheap fixes that do *not* touch extraction are
therefore separated out and can land immediately, in parallel, without waiting.

## Waves

```
wave 0  (land now, no rebuild)      wave 1  (one cache bump)        wave 2
┌────────────────────────────┐      ┌──────────────────────────┐   ┌─────────┐
│ 01 json  02 plots-cli      │      │ 05 furniture  06 rows    │   │ 09      │
│ 03 card-staleness  04 fmt  │─────▶│ 07 row-pages  08 rec-id  │──▶│ rebuild │
└────────────────────────────┘      └──────────────────────────┘   │ + gate  │
                                                                    └─────────┘
```

| Wave | Tickets | Rebuild needed | Gate to advance |
|---|---|---|---|
| 0 | 01–04 | no | each ticket's own test green; full suite unchanged |
| 1 | 05–08 | yes, once | each ticket's unit gate green against synthetic fixtures |
| 2 | 09 | — | full re-extract + rebuild, every Phase 6 gate re-measured |

## Wave 0 — cheap, independent, land immediately

### 01 — `--json` is unparseable on every subcommand

**Measured:** `dsa card --part AD9081 --card power --json | jq` fails. PyMuPDF's
shim prints `warning: The 'fitz' API is deprecated…` to **stdout**, so every
`--json` payload is preceded by prose. Pre-dates Phase 6 — `dsa plots --json`
(Phase 3) breaks identically — and Phase 6's four new verbs inherited it.

**Fix:** `os.environ.setdefault("PYMUPDF_MESSAGE", "fd:2")` at the top of
`cli.py`, before any lazy import can reach `fitz`.

**Why it needs a ticket rather than a one-line commit:** it changes the tool's
global stream routing, and `cli.py` is the frozen Phase 6 contract. The test is
a subprocess-free assertion that stdout parses as JSON for all five `--json`
verbs.

**Owns:** `cli.py`, `tests/unit/test_cli_json.py`

### 02 — Axis filters are unreachable from the CLI

**Measured:** the plan's own worked example, `find_plots --near-x 3.5GHz
--y-label "Gain"`, works from MCP and not from `dsa plots`. `Retriever.plots()`
and `query.find_plots()` already take `x_label`, `y_label`, `near_x`, `near_y`;
only the argument parser is missing them, because `cli.py` was frozen.

**Fix:** four flags on the `plots` parser, passed straight through. No new
logic — this is wiring a capability that already exists and is already tested.

**Owns:** `cli.py` (`plots` parser only), `tests/unit/test_plots_cli.py`

### 03 — A published card is not invalidated when its document moves

**Measured:** `load_or_build_card` treats a card as current when
`schema_version` and `card_version` match. Neither changes when the cited
document is republished to a different root, so a card built while AD9081's
records lived at `docs/datasheet-a15af6a3/…` kept citing that path after the
move to `@library/docs/…` — **87 of 87 filled values on the power card resolved
to no record.** `audit_card` caught it and the gate failed loudly, which is the
system working; serving the stale card would have been the failure.

**Fix:** fold the resolved document root (or the manifest's content hash) into
the card's cache key, so a moved document is a cache miss rather than a stale
hit.

**Owns:** `derive/cards.py`, `tests/unit/test_cards.py`

### 04 — `ruff format` has never been run

**Measured:** `ruff format --check .` fails on **78 files** (76 `.py`). The
repo's gate has always been `ruff check` at line length 100; formatting was
never adopted. All 27 Phase 6 modules are already format-clean, so the debt is
entirely historical.

**Fix:** one mechanical `ruff format .` commit, containing **no** logic change,
followed by adding `ruff format --check` to the standing gate so it cannot
regress. Kept as its own commit so it never obscures a real diff in `git blame`.

**Owns:** every unformatted file; `AGENTS.md` (the gate description)

## Wave 1 — the cache-invalidating fixes

All four land together, then the corpus is rebuilt once. Each is developed
against synthetic PyMuPDF fixtures so it is provable *before* the expensive
rebuild; the rebuild confirms on real documents.

### 05 — The furniture detector eats table content

**The single highest-value fix in this plan.** `LMX1204_registermap.pdf` prints
its whole register summary as `Table 1-1` on page 2 — 35 rows of address /
acronym / features / section. The tool reads none of it.

**Measured cause:** the furniture detector strips content recurring at the same
slot across pages. The string `0x0` prints in that same y-band on **11 of the
document's 25 pages** — it is the reset value of a field on most
field-description pages — against a recurrence threshold of **10**. The first
body row's address cell is therefore classified as page machinery, the table
region is cut off after its header row, reconstruction is rejected with
`no viable column split`, and the cell is gone from the paragraph stream too,
so nothing downstream can recover it.

**Fix:** a recurring slot that falls **inside an accepted table region** is
table content, not page machinery. The detector must run with table regions
already known, or exclude their interiors.

**Why it matters beyond one table:** this is a generic misread. Any register
map is dense in repeated short hex strings at stable positions, which is
precisely the signature the detector keys on. Expect it to affect every
register map the corpus ever ingests.

**Owns:** `extract/pdf_layout.py` (furniture detection),
`tests/unit/test_pdf_layout_furniture.py`

### 06 — Row continuation misreads produce duplicate keys

**Measured:** HMC520A prints one pin table (`Table 4. Pin Function
Descriptions`). The layout engine reconstructs its exposed-pad row with the
*previous* row's designator, so designator `15` appears twice; the device-table
layer refuses a table with duplicate keys and **24 real pins are lost**.

The refusal is correct and must stay — a pin table missing its last row reads
as "this pin does not exist" during schematic capture. The defect is upstream:
a row whose first cell is genuinely blank must be reconstructed as blank, not
inherited.

**This is also the recall problem.** The same class of misread is what limits
the register map to 12 of 35 field tables: measured damage includes a wrapped
name cell re-joined as `SYSREFREQ_DELAY_ST EPSIZE` (R13, R17), tables truncated
to their first field (R19, R21, R25), and two body lines folded into a header
(R12). Each is caught and refused, so precision stays 100% — the cost is
entirely recall.

**Gate:** table recall on `LMX1204_registermap.pdf` from **12/35 to ≥ 28/35**,
with precision held at 100% (no field may become wrong to make more appear),
and HMC520A's 24 pins published.

**Owns:** `extract/pdf_layout.py` (row reconstruction),
`tests/unit/test_pdf_layout_tables.py`, `tests/unit/test_pdf_layout_rows.py`

### 07 — HTML-derived tables cite the page the table starts on

**Measured:** `TableBlock.row_pages` is a `pdf_layout` field; the `ti_html` path
has no page geometry to fill it, so every row of an HTML-derived table cites the
page its table began on. On LMX1204's `Table 7-1`, **1 row of 35** (`0x5A` /
`R90`) prints on page 33 and cites page 32. Spec records read from the same
tables inherit it.

One row in thirty-five is small, and it is the kind of error that is worst when
small: a citation that is *nearly* right is the one a reader trusts without
checking.

**Fix:** per-row page pinning for HTML-derived tables, by locating each row's
distinctive cells in the PDF's per-page text. `structure/pagemap.pin_table_pages()`
already does exactly this at table level; this applies the same rule one level
down.

**Owns:** `structure/pagemap.py`, `structure/tables.py`,
`tests/unit/test_pagemap_rows.py`

### 08 — Spec record ids are not unique within a document

**Measured:** `spec_record_id` is a pure function of `(section, table_index,
row_index)`, and `build_specset` numbers tables *within a section*. A document
whose sections carry no numbers restarts `table_index` at 0 in every section,
so several records compute one id. **AD9081 publishes 549 spec records carrying
259 distinct ids; `rec_s-t0-r0` alone is carried by 14 records.** This affects
every datasheet read without a numbered table of contents — every non-TI part
in this corpus.

The consequence is not corruption, because Phase 6 chose refusal: a card cites
the first record carrying an id and **refuses the rest**, naming the count in
its `unresolved` list. But the cost is large and visible — **AD9081's interface
card keeps 1 row of the 21 its selectors matched**, and the JESD204B/JESD204C
interface-rate rows the datasheet prints on p.11 are among those refused.

**Fix:** make the id unique within its document — either `spec_record_id` takes
the section's file slug (unique per section) instead of its number, or
`build_specset` numbers tables document-globally. One line either way, plus a
`SPECS_SCHEMA_VERSION` bump.

**Expected gain, to be measured not assumed:** AD9081 from 259 to 549 distinct
ids, and its interface card from 1 row to the ~21 its selectors already match.

**Owns:** `models.py` (`spec_record_id`) *or* `structure/specs.py`
(`build_specset`) — one of the two, not both; `config.py`
(`SPECS_SCHEMA_VERSION`); `tests/unit/test_record_ids.py`

## Wave 2 — rebuild and re-measure

### 09 — Re-extract, rebuild, re-gate

Bump `output_version` once, re-extract every document, rebuild all eleven
parts, and re-run every Phase 6 gate. Then **update `KNOWN_SHORTCOMINGS.md`**:
each entry this phase closes is deleted with its closing number recorded in the
report, and each that survives keeps its entry with a re-measured figure.

Ticket 06 (register bit fields) is re-attempted here, not re-planned: if wave 1
lifts recall past its accuracy gate, it un-parks and ships; if it does not, its
shortcoming entry is updated with the new number and it stays parked. **The
gate decides, not the schedule.**

**Owns:** the rebuild; `Reports/PHASE_6_5_REPORT.md`; `KNOWN_SHORTCOMINGS.md`

## Acceptance gate

Each item is a number that must be measured and recorded, not a box to tick.

1. `--json` output parses as JSON for all five verbs that offer it.
2. `dsa plots` accepts `--x-label`, `--y-label`, `--near-x`, `--near-y`, and the
   plan's worked example returns the expected figure.
3. A card whose document has moved is rebuilt rather than served stale;
   `audit_card` reports 0 problems after a move.
4. `ruff format --check .` clean, and it is part of the standing gate.
5. `LMX1204_registermap.pdf` publishes a `registers.json` containing all **35**
   registers from its own `Table 1-1`.
6. Table recall on that document **≥ 28/35**, precision held at **100%** — no
   bit field becomes wrong in order to make more appear.
7. HMC520A publishes its **24** pins.
8. Every row of LMX1204's `Table 7-1` cites the page it is printed on; the
   named off-by-one row is gone and the count is 0.
9. AD9081 spec record ids **549/549 distinct**; its interface card publishes the
   rows its selectors match, with the JESD204B/C interface rates among them.
10. All Phase 6 gates still pass at or above their recorded numbers — 288/288
    card provenance, 400/514 axis coverage, 90/90 goldens. **A fidelity phase
    that improves recall while dropping a Phase 6 number has failed.**
11. `pytest` offline and green; `ruff check` clean.

## Explicitly out of scope

- **Cross-vendor `compare` alignment.** `dsa compare AD9081 AFE7950 --card power`
  aligns 0 rows of 127. That is real and worth fixing, but it is an *alias
  lexicon* problem — ADI and TI name the same rail differently — not an
  extraction problem, and lexicon work belongs with Phase 7's breadth push where
  the vocabulary evidence is. Recorded, not fixed here.
- **AFE7950/AFE7953 pin tables.** Neither datasheet in this corpus prints one;
  their section 4 is followed directly by section 5. No tool change can read a
  table that is not there. Closed by adding a revision that includes the pin
  configuration section, which is document acquisition — Phase 7.
- **The zero-margin `limits` flag.** No built part prints an equal-limit pair.
  The property is proved on a synthetic corpus and asserted over real data, so
  it will start reporting the moment such a part is added. Nothing to fix.
- **`library/` vs. the committed manifests.** A fresh clone cannot resolve
  `@library/` references because `/library/` is gitignored. Currently dormant —
  the corpora were reverted to self-contained form — but it will return the next
  time they are republished to the shared store. It is a corpus-distribution
  decision (track the library, or publish parts self-contained), not an
  extraction defect, and it deserves its own ADR.

## Found while merging Phase 6: corpus/pipeline version drift

Not a Phase 6 defect, but it belongs in this phase's territory because wave 2
rebuilds the corpus and this decides *what* it rebuilds.

Merging Phase 6 into `feat/gui-workbench` turned eight integration gates red.
Every one was corpus staleness rather than code: the branch's local
`parts/LMX1204` was built at pipeline **0.4.0** against code now at **0.5.0**,
and the derived artifacts those gates read (`pins.json`, `registers.json`) live
in the shared library, which the branch's store did not have. Refreshing the
untracked corpora and merging the library documents turned all eight green with
no code change.

The durable problem underneath: **the two tracked reference corpora,
`parts/AFE7950` and `parts/AFE7953`, are published at pipeline 0.1.0**, five
minor versions behind the code, because the "rebuild at 0.4.0" commit was
reverted. Phase 6's gates need 0.4.0 or better and currently get it from
untracked local data and the local library — neither of which a fresh clone has.

Three questions this phase should answer, in an ADR rather than in passing:

1. **What pipeline version must a tracked corpus be at?** A tracked corpus
   older than the code is a test fixture that silently stops testing what it
   claims to.
2. **Is `library/` tracked or not?** Today it is gitignored while committed
   manifests reference `@library/…`, so a corpus published to the shared store
   is unreadable on a clone. Either the library is part of the repo or corpora
   are published self-contained; both are defensible, the mixture is not.
3. **Should a corpus-reading gate fail or skip when the corpus predates the
   code?** Failing is loud but breaks clones; skipping is portable but can hide
   a genuine regression. The answer is probably "skip with the version in the
   reason, and assert elsewhere that at least one corpus is current."

## Effort and sequencing

Wave 0 is four small, genuinely independent tickets — parallel, no rebuild, and
worth landing on their own regardless of whether the rest proceeds.

Wave 1 is the real work, and 05 and 06 are the two that matter; 07 and 08 are
each roughly a one-line change plus its test and its version bump. Develop all
four against synthetic fixtures so nothing depends on the rebuild being right
the first time.

Wave 2 is mostly machine time: a full re-extract of the corpus, then re-running
gates that already exist.

The ordering is not negotiable in one respect. **Wave 1 must land as a single
cache-invalidating change.** Splitting it costs a full re-extraction per split,
and buys nothing.
