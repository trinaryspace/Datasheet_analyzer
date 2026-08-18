# KNOWN_SHORTCOMINGS.md

What this repo does **not** do, or does only partly, recorded where a reader
will find it. An entry here is a measured limit with the reason it stands, not a
TODO list: the point of the file is that a gap in a derived artifact should be a
fact the project carries rather than something a user discovers.

Each entry says what was attempted, what it produces today, and what would have
to change. Numbers are measured, and the test that measures them is named.

---

## Register bit fields (phase 6, ticket 06)

Ticket 06 was commissioned with permission to **fail closed** — to ship nothing
and record why — because a driver written against a wrong bit range
misconfigures silicon silently. It ships: 28 of LMX1204's 35 registers publish a
validated bit-field set in each of its two documents (116 fields each), every
published field's printed quartet (bit range, name, access, reset) verified
against the text of the page it cites, and a hand-verified sample of five
registers matching field for field
(`tests/integration/test_phase6_registers.py::TestBitFieldAccuracy`).

These are the limits that came with it.

### 1. Seven of 35 registers publish no bit fields

Per document, and identically in both. They keep their summary record with
`fields: []` and a `fields_reason`, so a lookup finds the register and is told
what is missing.

| Registers | Why |
|---|---|
| R7, R8, R9, R16, R72, R86 | The layout floor's reconstruction gate rejected their field tables, so no grid reached the bit-field reader at all. Measured on `LMX1204_registermap.pdf`: 7 of 38 table candidates rejected — five as *rows do not span columns*, two as *columns not stable across rows* — and six of those seven are per-register field tables. |
| R90 | Its printed field table states `15:8` and then `15:0` (SNAU269A p.24, SNAS800B p.54). That is a typo in the document: the second range should be `7:0`. The two ranges overlap on bits 15:8, so the **whole** set is refused with a recorded reason rather than the corpus guessing which was meant. |

**What would change it.** The six rejections are an *extraction* finding, not a
bit-field one — the fix belongs in `extract/pdf_layout.py`, where those grids
fail the gate, and it would benefit every table of every part (which is what
ticket 05's three layout fixes did). R90 cannot be fixed here at all: the
document is wrong, and inventing `7:0` for it would be exactly the confident,
plausible, unverifiable value ADR 0005 forbids.

### 2. The bit-diagram route has no real-document gate

Two printed shapes carry bit fields. The **bit column** (`Bit | Field | Type |
Reset | Description`, the range printed as text) is what both reference
documents use, and it is what the accuracy gate measures. The **bit diagram** (a
bit-position header row `7 6 5 4 3 2 1 0` with field names spanning columns
under it) is implemented — the ticket requires the range to be derived
geometrically from the header row's cell boundaries — but **no document in this
repo prints one**, so it is gated on synthetic PDFs read by the real layout
floor plus hand-built grids
(`tests/unit/test_bitfields.py::TestTheDiagramRouteIsGeometric`), never on a
vendor's own page.

Two properties keep that honest until a real one arrives: the route only fires
for a table whose caption or preamble names the register it describes, and its
output still has to tile that register's width with no overlap and no overflow
or it is refused whole. It also publishes **no per-field access or reset**,
because a diagram prints neither in the header run it was read from.

One reading is an assumption rather than a measurement: an empty bit column
continues the field to its left, which is what a cell spanning four columns
looks like once the layout floor has reduced it to text in the band its words
start in. Columns before the *first* named cell continue nothing and are
reported as unaccounted rather than folded backwards.

**What would change it.** A register map that prints bit diagrams, committed to
`tests/fixtures/pdf/`, with a hand-verified sample held to the same 100% bar.

### 3. A field description can carry the line printed under its table

The layout floor's table region sometimes extends past the last field row and
picks up the navigation line TI prints beneath it (`R12 is shown in Table 1-13.
Return to the Summary Table.`). Where that line prints no field name it is read
as the continuation of the last field's description, so a handful of
descriptions end with text that is not part of the field's description.

Bit ranges, names, access and resets are unaffected — those come from a row's
own cells, and a line with no readable bit range never becomes a field (the
count of such lines is reported in the register set's warnings). Filtering the
line by its wording would put a vendor's phrasing in the code, which this repo
does not do; the fix is a tighter region end in `extract/pdf_layout.py`.

### 4. A register with no printed hex reset word publishes no fields

The register width is read from the reset word the document prints
(`[Reset = 0x0000]` → four hex digits → 16 bits), because it is the only width
statement a TI programmer's guide makes and it is *printed*. A document that
states a reset in decimal, or states none, therefore publishes no fields for
that register even when its field table read cleanly — a field list that cannot
be checked against a register width is unverifiable, and this ticket's whole
stance is that unverifiable bit ranges do not ship. A document printing
`[Reset = 0x0]` for a 16-bit register reads as 4 bits wide, its top fields
overflow, and the set is refused with a reason.

**What would change it.** A width stated somewhere else printed — a summary
column, or a bit-position header row (already used when a diagram provides one).
Deriving it from the fields themselves is deliberately not done: a width taken
from the ranges it is supposed to validate makes the validation vacuous.

---

## Design cards (phase 6, ticket 07)

The four cards ship, and every value on them resolves to a record and a printed
page (377 references, 0 unresolvable — `Reports/PHASE_6_REPORT.md`). These are
the limits of what they cover.

### 1. The limits card compares the `max` column only

`registry/cards.yaml`'s join declares `role: max`, so the card answers "how much
headroom does the recommended maximum leave under the absolute maximum?" and says
nothing about the `min` side. A recommended *minimum* below an absolute-maximum
minimum is a real hazard too, and it needs the opposite subtraction
(`recommended_min - abs_min`); a card showing both under one "Margin" column
would be read wrong by exactly the reader it is for.

**What would change it.** A second declared join role with its own column and its
own flag, plus a printed pair to gate it on. Neither reference part prints a
comparable min pair — AFE7950's abs-max minima are pin-voltage ratings stated
relative to another rail (`VDDRX1P8+0.3`), which do not parse — so it would ship
untested against a real page, and this phase's stance on that is ticket 06's.

### 2. No zero-margin parameter exists in the built parts

The flag the card exists for is exercised by unit test only, including its
across-a-unit-prefix twin (1850 mV against 1.85 V must read as zero, which exact
float equality would miss). Measured: only **two** parameter pairs compare at all
across the five built corpora, both on AFE7950, both with headroom — because
joining two tables requires both of them to extract with values, and only one
part manages that (see 3).

**What would change it.** A part whose recommended maximum really is its absolute
maximum. It cannot be manufactured honestly: a golden fixture with an invented
zero-margin row would assert the flag against a datasheet nobody printed.

### 3. AD9081's limits and thermal cards are empty for an extraction reason

Its absolute-maximum and thermal-resistance tables (both on p.21) reconstruct as
rows with a symbol and **no value cells at all**, so there is nothing to compare
and nothing to publish: the limits card refuses all 12 candidate parameters by
name and the thermal card carries only the junction-temperature range from p.4.
Both tables are also attributed to the *following* section heading (`Thermal
Resistance`), which is why the limits join finds no abs-max side at all.

**What would change it.** Work in `extract/pdf_layout.py`, not in `cards/`: the
card reports what the corpus holds, and the fix is to make those two grids
reconstruct their value columns and anchor under their own heading. Loosening the
card's selectors would only move the silence.

### 4. A card's coverage is only as wide as its lexicon

HMC520A publishes no card rows at all: its 85 spec records carry no rail, no
thermal resistance and no interface parameter under wording
`registry/cards.yaml` knows. QPA1003P publishes a thermal card and nothing else,
for the same kind of reason. This is the trade ADR 0005 accepted in writing —
"parts whose tables use unusual header wording will yield empty cards until a
lexicon entry is added" — and closing a gap is a YAML edit measured against that
part's printed pages, never a looser match.

---

## Plot axis catalog (phase 6, ticket 08)

The catalog reads a figure's axes off the text the page prints inside the
figure's own region. AFE7950 publishes 458 of 514 figures at
`axis_confidence: high` (89%, against the ticket's 60% floor) and every published
axis string appears on the page its record cites. What follows is what it does
**not** read, and why each one is null rather than approximate.

### 1. A figure drawn as a raster image publishes no axes at all

Measured: **all 100 of AD9081's plots**, all 3 of LM741's, all 4 of QPA1003P's
(`Reports/PHASE_6_REPORT.md`). There is no text inside those regions — the axis
titles and tick labels are pixels in a bitmap — so every field is null and the
figure grades `low`. The figure itself is untouched: caption, conditions, page and
rendered PNG all still publish, and `dsa plots --near-x` reports the population it
could not consider rather than answering "no such figure".

**What would change it.** Reading pixels, which is image analysis of the rendered
PNG — deliberately out of ticket 08's scope, and under ADR 0005 a digitized number
needs an accuracy gate of its own before it may be published beside a printed one.
The schema is shaped so that pass lands additively.

### 2. A captionless-era figure gets no region, so no axes

QPA1003P's and LM741's cataloged figures come from ticket 09's *title-anchored*
route, and regions here are **caption-anchored only**. That is a refusal, not an
oversight: a title band may hold several plots, and one axis pair could not be
attributed to one of them honestly. A wrong axis pair looks exactly like a right
one, which is the failure invariant 8 exists to prevent.

### 3. 33 of AFE7950's figures read one axis and not the other

All 33 are y-only (458 figures publish a readable x axis, 491 a readable y axis).
They grade `medium` and are still findable by `--y-label`; what they cannot do is
answer `--near-x`. Three measured causes, one per figure inspected:

| Figure | What the region holds | Why the x axis is null |
|---|---|---|
| 4-117 | the y column (70…80) and no numeric row at all | the x tick labels are not text on that page — nothing to read |
| 4-175 | an x row `-32 -29 -26 -23 -20 -17 -14 -12` | the truncated last step is 2 against 3, a spacing ratio of 1.50 over the 1.35 bar, so the sequence has **no** scale and is refused whole |
| 4-192 | an x row `0 4 8 … 40`, uniform | no title run is printed under it, and "no title, no axis" refuses a range nobody named |

**What would change it.** Only case 4-175 is a threshold, and raising
`_SPACING_TOLERANCE` past 1.5 is not a bigger safety margin — it is a wider
definition of "linear" that starts admitting legends and mis-clustered columns
(1, 2, 4, 8 is 2.0 today and stays unread). Case 4-192 would need a title-run
search that reaches outside the region, which is how a neighbouring figure's title
becomes this figure's axis. Case 4-117 is not readable from text at all.

### 4. A second y axis on the right is not read

A figure printing two y scales publishes the **left** one only; the right-hand
column is deliberately not read rather than read as the first. Nothing in the
record says a second axis existed, which is the honest gap here: a consumer
filtering on `y_label` sees the left axis and no claim about the right.

### 5. `x_min`/`x_max` are the first and last **tick label**, not the axis line

No text states where the drawn axis line ends, so the published range is the
printed tick span — usually a hair narrower than the plotted extent. A `--near-x`
value between the last tick and the end of the line is therefore excluded. That is
the conservative direction: the range published is one the page actually prints.

### 6. A merged tick row's scale is trusted from its values alone

The spacing rule is normally cross-checked against **where** the ticks are
printed, which is what stops a log axis labelled at its minor ticks
(`10 20 30 … 100`, uniform differences, logarithmic positions) from reading as
linear. That check needs one position per tick, and PyMuPDF sometimes lays a whole
tick row out as a single text run (`"1200 1350 1500 1650"`): measured, **15 of the
458** AFE7950 figures that publish an x axis got theirs that way. Those 15 keep the
value-derived rule; a minor-tick-labelled log axis that happened to arrive merged
would be published as `linear`.

No such axis exists in the seven built corpora: all 446 of AFE7950's individually
laid-out x tick rows agree with their own geometry, and every log axis in it
is printed as decades (`1E+3 … 1E+8`). **What would change it** is splitting a
merged run back into its tokens' own boxes, which PyMuPDF can do at span level —
worth doing when a document that needs it turns up, and not before, because a
split guessed from character widths would put the check on invented geometry.

### 7. A unit the SI lexicon cannot scale is unmatchable by range

AFE7950's temperature axes print `Cq` — a degree glyph its font mangled — and
`SI_UNITS` cannot scale it, so those figures answer `--x-label Temperature` and
never `--near-x`. Comparing at face value would be the dropped-factor-of-1000
failure the numeric layer refuses; closing the gap means an entry in
`units.CANONICAL_UNITS` **and** `SI_UNITS`, never a looser comparison.

### 8. A title whose bracket the page never closes publishes no unit

Measured: **5 of AFE7950's 514 figures** (4-187, 4-189, 4-192, 4-236, 4-238).
PyMuPDF hands their rotated y title back as
`Uncalibrated Amplitude Differential Nonlinearity (dB` — the closing bracket is
not in the page's text stream at all. The label is published exactly as the page
printed it, fragment included, and the unit stays `""`: inferring `dB` from an
unclosed bracket is a guess, and a guessed unit is what `--near-x` would then
scale a comparison by. So those figures answer `--y-label` and honestly never a
range filter, which is the same split as item 7 for the same reason.

**What would change it** is joining a title run to the continuation line that
holds the rest of it, which is a second axis-title rule (and a way for a
neighbouring figure's line to become this figure's unit). At 1% of the part, the
verbatim fragment plus a null unit is the better trade.

---

## Cross-part comparison (phase 6, ticket 09)

`dsa compare` aligns two or more parts by alias-resolved symbol and subtracts
where both sides parsed the same printed column. It is gated on the four
layout-floor corpora, where the invariant-8 walk resolves 327 references over 139
values in 8 comparisons. These are its measured limits.

### 1. Two unrelated parts align on almost nothing, and that is correct

Measured over the four gate corpora, every pair, and all 213 alias phrases the
lexicon knows: the spec path produces **1 aligned row and 1,468 `only in A`
rows**, and the one aligned row (`Pdiss`, AD9081 against QPA1003P) carries no
delta because the two parts state it in different columns. The same walk over two
parts of one family (AFE7950 against AFE7953) produces **159 aligned rows, all
159 with a delta** (`Reports/PHASE_6_REPORT.md`; reproduce with
`scripts/measure_compare_alignment.py`).

Most of the gate number is a fact about the parts — a data converter, an op-amp, a
mixer and a power amplifier share very little parametric ground. The rest is the
ambiguity refusal doing its job: AD9081 prints 8 supply-rail rows where LM741
prints 2 absolute-maximum ones, and pairing 8 rails against 2 ratings is a guess,
so all 10 are listed instead. The **card** path aligns better because the card
lexicon has already selected one row per parameter, which is why `--card` is the
shape to reach for when two parts are not siblings.

**What would change it** is more alias coverage (a YAML edit) and better
extraction — never a looser pairing rule. A margin between the wrong two rows is
worse than no margin, and during part selection it is worse still.

### 2. A parameter a part prints many times cannot be paired at all

The pairing rung inside an ambiguous key needs a **printed** cell the two rows
share. Where a datasheet states one parameter once per operating configuration
and the layout floor recovers no name and no test-conditions cell for those rows,
nothing printed distinguishes them. Measured on offline builds of the two
reference PDFs: `--symbol Pdiss` finds 15 rows on AFE7950 and 20 on AFE7953, all
of them labelled `Pdiss` with an empty name and empty conditions, so the key is
refused whole and all 35 are listed with their values and pages.

**What would change it** is *extraction* — recovering the configuration cell
those rows are printed against — or a new pairing rung on something else the page
prints, such as the section title both rows sit under. The second is a real
option and is deliberately not taken here: it is weaker than character-for-
character identity (it pairs on the *table* rather than on the row), and this
phase's stance is that a widening ships with a hand-verified pair to gate it,
not ahead of one.

### 3. The reference parts cannot be compared until they are rebuilt

`dsa compare AFE7950 AFE7953 --symbol Pdiss` is the ticket's own example and it
produces **no rows** against the corpora committed under `parts/`: both were
published at `SPECS_SCHEMA_VERSION 1`, before ADR 0005 minted record ids, so
every row of them is honestly unaddressable. The comparison says so — one line
per row, naming the build command — rather than quietly comparing values it
cannot cite, because an uncited value has no place on a derived artifact.

**What would change it** is `dsa build afe7950.pdf --part AFE7950` (and the same
for AFE7953). The gate exercises the identical code path on corpora built inside
the test suite.

### 4. `only in A` is a statement about the corpus, not about the datasheet

A row flagged `only-in` says the other part *publishes* no record under that
parameter — which can mean its datasheet does not print one, or that the
extraction did not reach it. Measured: `dsa compare AD9081 LM741 QPA1003P --card
thermal` shows `RθJA` as "only in QPA1003P", although AD9081 prints a
thermal-resistance table on p.21 (whose rows reconstruct with no value cells —
Design cards, item 3) and LM741 prints a junction-to-ambient resistance on p.4
that its corpus publishes no spec record for at all (`Retriever.specs(name=
"Junction-to-ambient")` returns nothing).

The wording is deliberate — "publishes no record", never "does not state" — and
every comparison prints each part's unparsed population beside the table. **What
would change it** is extraction, in the same place the design-card gap lives.

### 5. One delta per row, on one column

A row states its delta on the first column both parts printed and parsed
(`max` → `typ` → `min` → `value`, then the card roles). Two parts that print both
a typical and a maximum get one delta, not two, because a table with two
difference columns per part invites reading across the wrong pair — and the
per-column numbers are all published verbatim beside it, so the second
subtraction is a subtraction the reader can do knowing which columns it used.

---

## MCP surface (phase 6, ticket 10)

### 1. A pin-type lookup reports no unconsidered population

`find_register --field NCO_EN` and `find_plots --near-x 3.5GHz` both select on a
**derived** value, and both say how much of the corpus they could not consider
(`register_field_gap()`, `plot_axis_gap()`). `find_pin --type power` selects on
a derived value too — the lexicon label — and says nothing of the kind.

The reason it is a smaller gap than its two siblings is that the unconsidered
population is *queryable*: `unknown` is a first-class pin type, so
`find_pin --type unknown` (or `dsa pins --type unknown`) returns exactly the
pins the lexicon could not label, each publishing an empty `type_evidence`.
Measured: AD9081 has **10** of 321 (`TDP`/`TDN` and eight `ADCx_FDy` fast-detect
outputs); LMX1204 leaves `BIAS01`, `BIAS23`, `MUXOUT` and `SCK` unlabelled for
the same reason. Nothing is hidden — it is just not volunteered beside a
filtered answer.

**What would change it** is a `pin_type_gap()` beside `register_field_gap()`,
returned as a body key on `find_pin` and printed as a `note:` line by
`dsa pins --type`. It is a small change and was left out of the phase gate
deliberately rather than rushed into it.

### 2. `AGENT.md` does not list the tools this phase added

`protocol.py` is the one place the retrieval protocol is written, and its
"Access path 2 — MCP tools" block still names the phase-5 nine
(`list_parts` … `ask`). `compare_parts` (ticket 09) and `find_pin` /
`find_register` / `get_card` (ticket 10) are absent from it, so an agent working
only from a part's `AGENT.md` or from the `datasheet-corpus` skill will not
learn that the device tables and the design cards have tools at all. Every other
surface — `README.md`, `AGENTS.md`, each tool's own description and its declared
`_meta.response_schema` — does list them.

**What would change it** is four names in `_mcp_block()` plus
`scripts/write_skill.py` to regenerate the checked-in `SKILL.md`. It was held
back because the emitted file carries `PROTOCOL_MARKER` (`v1`) as a
publish-cache key: editing the rule text without bumping the version leaves the
staleness undetectable, and bumping it republishes the `AGENT.md` of every
corpus on the next build — a behaviour change to the skip gate that belongs in
its own ticket rather than in a phase gate.

## Document registry + `dsa fetch` (phase 7, ticket 01)

### 1. Four of the eight seeded URLs are derived, and none of them is confirmed

`registry/datasheets.yaml` ships with URLs for AFE7950, AFE7953, LM741 and
LMX1204 that this repo has **never fetched**. They were derived by applying the
one literature-path pattern the repo carries
(`https://www.ti.com/lit/ds/<lit>/<lit>.pdf`) to a literature number parsed out
of each PDF's own first pages. That is a hypothesis, not a lookup, and it ships
as one: `url_verified: false`, with the rule in `url_derivation`, and `dsa
fetch` reports it as unconfirmed until bytes arrive. The other four documents
(AD9081, HMC520A, QPA1003P, and LMX1204's programmer's guide) carry `url: null`
plus the reason, because no URL pattern for those vendors — or for TI's *user
guide* path — is encoded anywhere in this repo, and guessing one would put a
wrong document in front of a designer under a citation that looks exactly as
trustworthy as a right one.

**What would change it** is `Reports/PHASE_7_LIVE_RUN.md` L1–L2: one
`dsa fetch` per part on a machine with a connection, which flips the flag,
records `sha256_origin: fetch:<url>` and stamps a real `retrieved_at`.

### 2. A seeded sha256 will mismatch a fresh fetch of the *same* revision

Every seeded hash carries `sha256_origin: local_file:<repo path>` — it is the
hash of the copy committed here, not one recorded off the wire. Measured by the
repo owner with network (2026-08-18): TI regenerates a datasheet's "PACKAGE
MATERIALS INFORMATION" addendum with the current date on every download, so a TI
PDF's bytes change daily while its revision identifier stays put (LM741's
upstream p.15 reads `10-Aug-2026` against `15-Jul-2025` locally; of the four,
only LMX1204 hashed identically). A first `dsa fetch` of a TI part will
therefore stop with a mismatch.

The stop is the designed behaviour rather than a bug, and the warning is written
not to overstate it: `mismatch_cause` decides from the **parsed revision**, so
an unchanged identifier is reported as *"NOT evidence of a new revision"* and
`NEW UPSTREAM REVISION` is reserved for one that actually moved. What remains a
shortcoming is that a seeded hash is not yet a wire hash, so the first fetch of
each TI part costs a human read of the warning.

**What would change it** is the same live run: after `--accept-new-revision` the
entry holds a wire hash, and a later mismatch means something sharper.

### 3. `sniff_revision` reads LMX1204's datasheet as `SYSREFOUT0`

`extract/pdf_structure._TI_DOC_ID` matches any capitalised S-word containing a
digit (`\bS[A-Z]{2}[A-Z0-9]*\d[A-Z0-9]*\b`), and LMX1204's page 1 prints
`SYSREFOUT0` before it prints `SNAS800B`. The seed generator side-steps this
with a closed list of TI series codes, so the registry records `SNAS800B`
correctly — but `dsa fetch LMX1204 --accept-new-revision` would overwrite it
with `SYSREFOUT0`, because acceptance records what `register_source` sniffed
from the bytes that arrived. The same pattern is why a fresh `dsa build` of that
part records a revision AGENTS.md's table does not.

**What would change it** is a closed series list in `_TI_DOC_ID` itself. It was
not done here because that pattern is the shared revision lexicon every part's
recorded revision flows through, and ticket 02 (revision awareness) owns it.

## Revision diff (phase 7, ticket 03)

### 1. No real revision pair exists in this repo, so the gate uses a declared one

Every part here carries exactly one revision, and this run had no network, so
`dsa diff-rev` has never been run on two revisions a vendor actually published.
The gate instead builds a **declared** pair
(`tests/fixtures/synthetic/revision_pair.py`): two PDFs whose differences are a
fixed hand-written list, both pushed through the real `PdfLayoutBackend` and the
real pipeline, with the diff asserted to be exactly that list — 12 declared
edits, 12 found, nothing else.

That makes the *expectation* exact in a way a real pair could not (a real pair's
expected delta would have to be read off two PDFs by hand and could be wrong).
What it cannot show is that a vendor's revision moves things the way the fixture
does — in particular how much page-shift noise a 146-page revision produces, and
whether the alias lexicon aligns parameters a vendor genuinely renamed.

**What would change it** is `Reports/PHASE_7_LIVE_RUN.md` L7: the first time a
registered part reports `stale`, fetch the new revision, build it under `--rev`,
and record the measured change counts.

### 2. A part holding two revisions has part-level cards built from both

Design cards are a *part*-level artifact — a card joins rows from every document
of a part, which is what makes a limits margin work across two tables in two
documents. A part holding two revisions therefore gets cards that can quote
either one. Nothing is fabricated and nothing is hidden: every card row cites the
document directory it came from, and those now carry the revision label
(`datasheet-a1b2c3d4-reve`), so a reader can see which revision a row is from.
But the card does not *choose*, and a reader who does not look at the citation
could take a superseded value.

The same is true of any other part-level view over all documents (`dsa ask`,
`dsa query` without a document filter): they answer from both revisions, each hit
cited to its own.

**What would change it** is a rule that part-level derived artifacts read only
the newest labelled document of each type. That is a real behaviour change for
multi-document parts and it was not made as a side effect of this ticket; L8 in
`Reports/PHASE_7_LIVE_RUN.md` is the measurement that should decide it.

### 3. A spec row that printed no value in any column takes no part in the diff

The layout floor emits a spec record for rows of neighbouring tables that carry
no value in `min`/`typ`/`max`/`value` — six of them per side in the gate's own
fixture. They are excluded from the alignment, because a dozen valueless rows
collapse onto one `(unnamed row)` key and bury every real change under a wall of
"uncomparable" refusals.

They are **not** dropped from the report: each side's count is stated in the
diff's own notes ("6 of those spec records print no value in any column and take
no part in the alignment"), beside the parse-population sentence invariant 8
requires. But a valueless row that a revision genuinely *added* or *removed* is
not reported as such.

**What would change it** is a distinction between a row with no value and a row
with no name — the first is a real (if uninformative) parameter, the second is
extraction residue. The device-table abstraction has the evidence to tell them
apart; the diff does not.
