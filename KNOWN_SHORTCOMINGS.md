# Known shortcomings

What this tool cannot currently do, written down where a reader will find it.

An entry here is a **parked** piece of work: something a ticket set out to do,
could not do honestly, and refused to fake. Every entry names what is missing,
why it is missing, what the tool does instead, and what would close it. A
shortcoming that is recorded is a decision; a shortcoming that is silently
worked around is a bug.

---

## Pins: AFE7950 and AFE7953 publish no pin table

**Phase 6, ticket 04.** The phase plan's acceptance gate asks for
`dsa pins --part AFE7950 --type power` to return a hand-checked supply pin
set. It returns nothing, and the reason is in the document rather than in the
tool: **the AFE7950 datasheet in this corpus prints no pin table.** Its section
4 (Specifications) is followed directly by section 5 (Revision History) — there
is no *Pin Configuration and Functions* section to read. The same is true of
AFE7953.

**What the tool does instead.** No `pins.json` is published for either part,
and `dsa pins --part AFE7950` says so in as many words rather than printing an
empty result that reads as "this part has no pins". The hand-checked supply
pin set the gate asks for was produced for **AD9081** instead (22 rails, 79
balls, checked against Table 21 of its datasheet) and is asserted in
`tests/integration/test_phase6_pins.py::TestSupplyPinSet`.

**What would close it.** A TI datasheet revision that includes the pin
configuration section, added to the part with `dsa add-doc`. Nothing in
`derive/pins.py` needs to change: it reads whatever pin table the document
prints.

---

## Pins: HMC520A's pin table is rejected whole (24 pins lost)

**Phase 6, ticket 04.** HMC520A prints one pin table (`Table 4. Pin Function
Descriptions`). The layout engine reconstructs its exposed-pad row with the
previous row's designator, which makes designator `15` appear twice; the
device-table layer refuses a table with duplicate keys, so the whole table is
rejected and the part publishes no `pins.json`.

**Why it is not "fixed" by keeping the good rows.** A pin table that is missing
its last row is worse than no pin table at all: during schematic capture a
missing pin reads as "this pin does not exist". The refusal is the honest
outcome, and its cost — 24 real pins that the datasheet does print — is
recorded here and in `ExtractionStats.rejection_reasons`, where `dsa status`
prints it.

**What would close it.** A layout-engine fix for the row-continuation misread
on that page (`extract/pdf_layout.py`), not a change to `derive/pins.py`: the
duplicate key is a symptom of the grid, not of how the grid is read.

---

## Cards: AD9081's spec records are not individually addressable

**Phase 6, ticket 07 (a defect in ticket 01's contract, found by ticket 07's
gate).** A derived artifact cites a record as `<artifact>#<record id>`, and
`models.spec_record_id` computes that id as a pure function of
`(section, table_index, row_index)`. `structure/specs.build_specset` numbers
tables *within a section* (`for section in raw.sections: for i, table in
enumerate(section.tables)`), so a document whose sections carry **no numbers**
restarts `table_index` at 0 in every one of them and several records compute
one id.

**Measured, on a corpus rebuilt at the current pipeline (0.4.0, specs schema
3):** AD9081 publishes 549 spec records carrying **259 distinct ids**;
`rec_s-t0-r0` alone is carried by 14 records. This is not stale data — the
rebuild reproduces it — and it affects every datasheet the layout floor reads
without a numbered table of contents, which is every non-TI part in this
corpus.

**What the tool does instead.** `derive/provenance.resolve_source` returns the
*first* record carrying an id, so the first is addressable and the rest are
not. A card therefore cites the first and **refuses the rest**: the row is
left out, the count is named in the card's `unresolved` list, and the card
carries a warning saying how many records of the part cannot be addressed. No
card ever emits a value whose citation would land a reader on a different row.
The cost is real and visible: AD9081's `interface` card keeps 1 row of the 21
its selectors matched, and its JESD204B/JESD204C interface-rate rows — which
the datasheet does print, on p.11 — are among the refused.

**What would close it.** Making a spec record's id unique within its document,
in ticket 01's territory rather than ticket 07's: either `spec_record_id`
takes the section's *file slug* (unique per section) instead of its number, or
`build_specset` numbers tables document-globally. Either is a one-line change
plus a `SPECS_SCHEMA_VERSION` bump; both invalidate every citation already
written, which is why it is recorded here rather than done unilaterally by a
consumer of the contract.

---

## Cards: no built part prints a zero-margin parameter

**Phase 6, ticket 07.** The `limits` card flags a parameter whose recommended
maximum equals its absolute-maximum rating — a genuine design hazard that is
invisible when the two tables are read pages apart. The phase gate asks for at
least one such parameter to be flagged **if one exists in the reference
parts**. None does: across all eleven built parts, the only two comparable
pairs are AFE7950/AFE7953's `TJ` (150 °C rating against a 110 °C recommended
maximum, margin 40 °C) and their `DVDD0P9` rail (1.2 V against 0.95 V, margin
0.25 V), both hand-verified against the printed pages.

**What the tool does instead.** The flag is proved on a synthetic corpus in
`tests/unit/test_cards.py::TestLimitsCard`, and
`tests/integration/test_phase6_cards.py::TestZeroMarginHazard` asserts the
property that actually matters over real data: *every* equal-limit pair found
in a reference part carries the flag. Today that set is empty, and the test
will start asserting the moment a part that prints one is added.

---

## Registers: the LMX1204 register map's own summary table is not read

**Phase 6, ticket 05.** `LMX1204_registermap.pdf` prints its whole register
summary as `Table 1-1. LMX1204 Registers` on page 2 — 35 rows of address /
acronym / features / section. The tool does not read that table, and the
reason is in the layout engine rather than in `derive/registers.py`: the
furniture detector, which strips content that recurs at the same slot across
pages, classifies the first body row's `0x0` address cell as page furniture
(measured: the string `0x0` prints in that same y-band window on 11 of the
document's 25 pages — it is the reset value of a field on most of the
field-description pages — against a recurrence threshold of 10). The table's region is therefore cut off after its
header row, the reconstruction is rejected with `no viable column split`, and
the table survives only as paragraphs — with the `0x0` cell already gone from
them, so nothing downstream can recover it either.

**What the tool does instead.** The register map publishes **no**
`registers.json` at all rather than a map missing its first register, and the
rejection is recorded in `ExtractionStats.rejection_reasons`, where
`dsa status` prints it. LMX1204's registers are still answerable end to end:
the *datasheet* prints the same 35-register summary as `Table 7-1` on page 32,
that table extracts cleanly, and `dsa regs --part LMX1204 --addr 0x11` cites
it. The re-route this ticket made is still what pays for itself on the
register map — read as paragraphs it had zero tables; read as `pdf_layout` it
yields 13, which is what ticket 06's bit-field work reads.

**Why it is not worked around here.** Rebuilding the table from the paragraph
stream would invent the address the furniture filter deleted, or drop register
R0 silently — and a register missing from a map reads as "this register does
not exist" during bring-up.

**What would close it.** A furniture-detector fix in `extract/pdf_layout.py`
(a recurring slot inside an accepted table region is table content, not page
machinery). That file's `output_version` gates the whole extraction cache, so
the change belongs to a deliberate re-extraction pass, not to this ticket.
`tests/integration/test_phase6_registers.py::TestTheReferenceMapsOwnSummaryTable`
asserts the current behaviour and is what has to change when it lands.

---

## Citations: an HTML-derived table gives every row the page it starts on

**Phase 6, ticket 05** (pre-existing, measured here for the first time).
`TableBlock.row_pages` — per-row page attribution for a grid merged across a
page break — is a `pdf_layout` field; the `ti_html` path has no page geometry
to fill it, so every row of an HTML-derived table cites the page the table
starts on. Measured on LMX1204's `Table 7-1`: **1 row of 35** (`0x5A` / `R90`)
is printed on page 33 and cited on page 32. Spec records read from the same
tables share the limitation.

**What the tool does instead.** Nothing hides it: the off-by-one row is named
and asserted in
`tests/integration/test_phase6_registers.py::TestGoldenRegisterQuestions::test_the_one_row_whose_cite_is_a_page_early_is_named`,
so the count cannot grow unnoticed.

**What would close it.** Per-row page pinning for HTML-derived tables, by
locating each row's distinctive cells in the PDF's per-page text — the rule
`structure/pagemap.pin_table_pages()` already applies at table level, applied
one level down. That is a change to the extract/structure layers and to every
artifact read off them, not to `derive/registers.py`.

---

## Register bit fields: not extracted (ticket 06 parked)

**Phase 6, ticket 06.** The phase plan asks for per-register bit fields —
`{"name": "NCO_EN", "bits": {"verbatim": "[3]", "hi": 3, "lo": 3}, ...}` — and
gives the ticket leave to park rather than ship approximate ones, because a
wrong bit range is acted on: a driver written against it misconfigures silicon
and fails silently. **The gate failed and the ticket parked.**
`RegisterRecord.fields` is `[]` for every published register, and nothing in
the shipping code path can fill it.

**What was attempted.** `src/datasheet_analyzer/derive/bitfields.py` reads
both printed shapes — the field-description table (`Bit | Field | Type |
Reset | Description`) and the bit-position diagram (`7 6 5 4 3 2 1 0` over
field-name cells that span columns, where a field's range comes from the
header row's *column boundaries* and never from the name cell's text). It
accepts a register's field set whole or refuses it whole, on rules that reject
an unparsed bit cell, a field name that is not an identifier, a blank access
or reset where the table declares that column, an overlap, an overflow, and a
gap in the register's coverage.

**What broke, measured against `LMX1204_registermap.pdf`** by
`tests/integration/test_phase6_bitfields.py`, which asserts every number here:

- The document prints **35** register field tables. The layout engine hands
  over **12**. Of those, **4** survive validation (R2, R5, R33, R67) — **13
  fields, and all 13 are exactly right**. The failure is recall (11%), not
  precision.
- Over a sample fixed by document order before measuring — R0, R2, R3, R4,
  R5, R6 — **two of six** registers yield fields. R0, R3, R4 and R6 print a
  table the layout engine drops entirely. 100% with no partial credit is not
  met.
- Where a table does arrive it is often damaged: a wrapped name cell re-joined
  as `SYSREFREQ_DELAY_ST EPSIZE` (R13, R17), a table truncated to its first
  field (R19, R21, R25), two body lines folded into the header (R12). Each is
  caught and refuses that register, so nothing wrong is emitted.
- **There is nowhere to put them even if they were perfect.** The reference
  map's own summary table is not recovered (the shortcoming above), so that
  document publishes no `registers.json` and has no summary record to hang
  fields off. The 35 published LMX1204 registers come from `Table 7-1` of the
  *datasheet*, a different document, and a derived value cites a record inside
  one document.

**What the tool does instead.** Nothing. No bit-field record is published, no
CLI or MCP surface answers a bit-field question with data, and `dsa regs
--field` already says out loud that no bit breakdown exists for the part
(`derive/registers.no_bit_fields_message`) rather than returning an empty
result that reads as "this register has no fields". `derive/bitfields.py` is
imported by no shipping module; the gate asserts that too.

**Also honest:** the reference document prints **no bit-position diagram at
all**, so the geometric column-span reader — the shape the ticket names — is
exercised only by the synthetic fixtures in `tests/unit/test_bitfields.py`.
No real document in this repository gates it.

**What would close it.** A layout-engine fix (`extract/pdf_layout.py`) for the
three misreads above, plus recovery of the reference map's summary table. Both
belong to a deliberate re-extraction pass — that file's `output_version` gates
the whole extraction cache — and neither is a change to `derive/bitfields.py`,
which reads whatever grid it is handed. When they land,
`tests/integration/test_phase6_bitfields.py` is what has to change with them,
and this entry is deleted with it.

---

## Corpus: AFE7950 and AFE7953 reference a library that holds only their figures

**Found by phase 6, ticket 10's gate; the defect predates the phase** (commit
`c1d6180`, "data: rebuild AFE7950 and AFE7953 at pipeline 0.4.0"). Both parts'
tracked `manifest.json` cites every section as
`@library/docs/datasheet-<hash8>/sections/…`, but `/library/` is **gitignored**
and the section markdown, `specs.json` and `plots.json` are the *tracked* files
under `parts/<PART>/docs/`. `CorpusIndex.corpus_path()` resolves an `@library/`
reference strictly against the library root, so every section read for those
two parts resolved to a path that was not there.

**Measured, before repair:** the golden Q&A corpus check scored **3/21** for
AFE7950 and **1/13** for AFE7953 — every failure "corpus has answer ❌, page
cite correct ✅", i.e. the corpus could not be *read*, not that it was wrong.
The record paths were unaffected (spec 12/12 and 7/7, plot 3/3 and 1/1, ask
1/1 and 1/1), because those resolve through `publish.document_dirs`, which
prefers the part-local copy. Two resolvers disagreeing about where one
document lives is the root cause.

**What was done here.** The part-local artifacts were copied into
`library/docs/<doc>/`, which is what the manifest already claimed, restoring
**21/21** and **13/13**. That repair is *local, ignored data*: it fixes this
machine's corpus and does nothing for a fresh clone, where `parts/AFE7950`
still points at a library that will not exist.

**What is still broken, and is asserted rather than hidden.** Neither document
has a `search_index.json` anywhere in the tree, so `dsa search` and the pack's
full-text route cannot run for them: `dsa verify` reports the search-path
golden as `search unavailable` (0/1 for each), which is "could not look", never
"nothing found". `tests/integration/test_phase6_gate.py::…::
test_the_search_path_is_at_full_marks_wherever_it_can_run` pins the blocked set
to exactly `{AFE7950, AFE7953}` and fails if it grows *or* shrinks silently.

**What would close it.** Republishing both parts (`dsa build afe7950.pdf --part
AFE7950`) writes the sections, the specs, the plots **and** the search index
into the shared store in one pass. It could not be done in this worktree: the
`ti_html` path re-fetches every figure through `publish/plots.py`, which needs
network access this environment does not have (measured: 14 minutes of image
probes with no corpus written before the run was stopped). The second half of
the fix is a decision, not a build: either the shared store stops being
gitignored, or a part published into it stops being committed as if it were
self-contained.

**Related, same root.** After a rebuild republishes a document into the shared
store, the *old* `parts/<PART>/docs/<doc>/` copy still shadows it —
`retrieve.index._doc_dirs` prefers a part-local directory of the same name, by
design ("the more specific answer to where *this part's* copy is"). A stale
local copy therefore hides a complete shared one: AD9081 and lm741 were rebuilt
here at pipeline 0.5.0 and kept answering out of their pre-library directories,
with no search index and no `pins.json`, until those directories were removed.
A rebuild that publishes into the store should retire the copy it supersedes.

---

## Cards: a published card is not invalidated when its document moves

**Phase 6, ticket 10 (observed while running the gate).** `load_or_build_card`
treats a card on disk as current when its `schema_version` and `card_version`
match. Neither changes when the *document* a card cites is republished to a
different root, so a card built while AD9081's records lived at
`docs/datasheet-a15af6a3/…` kept citing that path after the document moved to
`@library/docs/datasheet-a15af6a3/…`: **87 of 87 filled values on the power
card resolved to no record on disk.**

**What the tool does instead.** Nothing silently: `derive.cards.audit_card`
catches it — that is exactly the walk it exists for — and the phase gate fails
loudly rather than serving a card whose citations lead nowhere. The card is
correct again as soon as it is rebuilt (deleting `parts/<PART>/cards/` is
enough).

**What would close it.** Adding the document roots a card drew on to its
cache key, beside `card_version`, so a republished document invalidates the
cards that cite it — one line in `derive/cards.load_card`, plus the same check
in `publish.cards_current`.

---

## Plots: the axis filters are reachable from MCP but not from the CLI

**Phase 6, ticket 08's gap, confirmed by ticket 10.** The plan's worked example
is `find_plots --near-x 3.5GHz --y-label "Gain"`. The filters exist and are
tested — `Retriever.plots()` and `query.find_plots()` take `x_label`,
`y_label`, `near_x` and `near_y`, and the MCP `find_plots` tool exposes all
four — but `dsa plots` does not, because `cli.py` was frozen by ticket 01 and
its `plots` parser predates the catalog.

**What the tool does instead.** An agent gets the filters through MCP; a human
at the CLI narrows by caption, section or tag and reads the axis fields out of
`plots.json`.

**What would close it.** Four `add_argument` lines in `cli.py`'s `plots` parser
and four keyword arguments at the `scope.plots(...)` call — a deliberate edit
to the frozen contract file, which is why it was not made unilaterally by a
consumer of it.
