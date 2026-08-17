# PHASE 6 REPORT — Design-Time Content

**Status: in progress.** Measured results accumulate here per ticket, and this
file supersedes `Reports/PHASE_6_PLAN.md` when the phase lands.

## Ticket 02 — the numeric layer

`structure/quantities.py` turns a printed value cell into a comparable SI
number. It is pure, it is a legal step in an invariant-8 derivation path, and
it is **allowed to fail**: `parse_quantity` returns `None` for anything its
anchored grammar does not consume whole, which is recorded on the record as
`parse_confidence: none`.

### Parse rate, six built corpora

Measured with `scripts/measure_parse_rate.py` (the script's docstring is the
reproduction procedure). Records are re-parsed rather than read off stored
fields, so a corpus published before the layer existed measures identically.

| Part | Backend | Records | Parsed | Rate |
|---|---|---:|---:|---:|
| AFE7950 | ti_html | 619 | 586 | 95% |
| AFE7953 | ti_html | 536 | 504 | 94% |
| QPA1003P | pdf_layout | 41 | 34 | 83% |
| LM741 | pdf_layout | 71 | 48 | 68% |
| AD9081 | pdf_layout | 549 | 180 | 33% |
| HMC520A | pdf_layout | 85 | 23 | 27% |

> HMC520A's row moved in ticket 05 (it read 30 records / 4 parsed / 13%
> when this table was first written). Nothing in the grammar changed: the
> furniture and header-band fixes that ticket 05 needed for the register
> summary freed 55 more of its spec rows, most of them with min/typ/max
> cells that had previously been dropped. It is the "improve it in extraction,
> not here" claim below, measured.

Per section, for the two TI reference parts (the full per-section tables for
all six are printed by the tests — `test_phase6_quantities.py` for the
reference corpora, `test_phase4_layout_gate.py::TestNumericLayerParseRate` for
the gate parts, which are built there already):

| Section (AFE7950 titles) | AFE7950 | AFE7953 |
|---|---:|---:|
| 3 Description | 0/1 | 0/1 |
| 4.1 Absolute Maximum Ratings | 22/22 | 21/21 |
| 4.2 ESD Ratings | 2/2 | 2/2 |
| 4.3 Recommended Operating Conditions | 6/6 | 6/6 |
| 4.4 Thermal Information | 5/5 | 5/5 |
| 4.5 Transmitter Electrical Characteristics | 203/203 | 193/193 |
| 4.6 RF ADC Electrical Characteristics | 134/134 | 113/113 |
| 4.7 PLL/VCO/Clock Electrical Characteristics | 41/45 | 41/45 |
| 4.8 Digital Electrical Characteristics | 32/42 | 32/42 |
| 4.9 Power Supply Electrical Characteristics | 128/128 | 78/78 |
| 4.10 Timing Requirements | 10/13 | 10/13 |
| 4.11 Switching Characteristics | 3/15 | 3/15 |
| 4.12.7 TX Typical Characteristics at 9.6 GHz | 0/3 | 0/2 |

### What the numbers mean

The spread is **not** a grammar spread. Two findings, both measured:

- On the TI parts, 30 of the 33 (AFE7950) and 30 of the 32 (AFE7953) unparsed
  rows printed something the grammar deliberately refuses. §4.11 scores 3/15
  because switching characteristics are stated in `interface clock cycles(1)`
  and in named latencies (`TX Channel Latency`), neither of which is a scalable
  unit; §4.8 loses seven rows whose "unit" column holds a pin list (`LVDS
  Inputs: 0SYNCIN+/- and 1SYNCIN+/-`) and three whose value is prose. The
  honest answer in every one of those rows is the printed string.
- On the layout-floor parts the dominant cause is upstream: **335 of AD9081's
  369 unparsed rows, and all 26 of HMC520A's, print no value cell at all**. A
  rescued grid put those numbers somewhere no value role saw them, so there is
  nothing for the layer to read. That is a table-reconstruction finding and is
  where the improvement belongs; widening the grammar could not touch it.

### Lexicon growth this ticket

`SI_UNITS` must cover every canonical unit (a test fails otherwise), and the
gaps the six corpora exposed were closed as *data*: `dBc`, `dBFS/Hz` and `%`
(together 341 rows of the TI parts), plus the SI-prefix members already missing
from families the lexicon carried — `nA`, `pA`, `µV`, `kV`, `µs`, `nF`, `µF`,
`µW`. All are identity canonicalizations, so no published `unit.canonical`
string moved. Prefixed ohms (`kΩ`, `MΩ`, 3 rows) were deliberately **not**
added: giving them a canonical form would rename a unit string the committed
corpora already publish, which is not worth three rows.

### Contract points asserted by test

- Every shape of the plan's table, one case each, plus the unparseable cases
  returning `None` (`tests/unit/test_quantities.py`).
- Both ohm glyphs (U+2126, U+03A9) reach the same SI unit, from the value cell
  and from the unit column alike.
- No verbatim field is mutated: every printed cell of every record of all six
  corpora is snapshotted before and after the layer runs.
- `parse_population` accounts for every record — `total == parsed + unparsed`,
  one listing line per unparsed row — so ticket 07 and ticket 09 cannot drop a
  row from a comparison without saying so.

## Ticket 03 — the device-table abstraction

`structure/device_tables.py` + `registry/device_tables.yaml` read a pin table
and a register-summary table through one pipeline — **identify → map columns →
validate → emit** — because they are the same structural animal: wide,
repetitive, keyed by a first column of designators rather than prose.

**No consumer ships with it, deliberately.** `pins.json` (ticket 04) and
`registers.json` (ticket 05) own the published shape and the per-record grade;
nothing here is a pydantic model, because a schema is a promise to a reader on
disk and no reader exists yet. Coverage over the six built corpora is therefore
not measurable in this ticket — it is measured in ticket 04, where the first
consumer runs the abstraction over real pin tables.

### What is data and what is code

Every word the abstraction matches on lives in the YAML: each column's header
phrases (matched **whole**, so `Part Number` is not a pin column), the caption
phrases that name a table its headers do not, the key shape, and the three
per-kind switches — `expand_key`, `monotonic_key`, `key_numeric`. The module
holds the rules and none of the words: a lexicon of invented kinds (a "widget
schedule" keyed on `Slot ID`) drives it end to end in test, which is what "no
vendor rules" means operationally.

### Contract points asserted by test (`tests/unit/test_device_tables.py`, 50 at this ticket; 57 after ticket 04's wrapped-row rule)

Synthetic fitz-built PDFs through the real layout floor, plus hand-built
`TableBlock`s where the point of a case is a shape a PDF cannot be made to
produce reliably. The fixtures draw column rules, because a pin table fills
every cell and the layout floor's occupancy check rejects a fully-packed
unruled grid — which is the same reason real pin tables print rules.

- Abbreviated headers (`NO.`, `I/O`) map by lexicon; a header the lexicon does
  not know is **said** to be unmapped (`ColumnMap.missing`) rather than filled
  in by position, and teaching it is one line of YAML — asserted by editing the
  shipped file in-test and watching the same code map the column.
- A table with **no header row at all** maps positionally. `pdf_layout` puts
  the first row of every region in `headers`, so such a table parks its first
  *pin* there; reading it as data (`HEADER_ROW_INDEX = -1`) is what keeps that
  pin in the corpus instead of losing it to a header that never existed.
- A duplicate-key pin table and an out-of-order register summary are each
  **rejected whole, with a reason**, and emit zero records — including the
  collision that only key *expansion* makes visible (`A1-A3` then `A2`).
- Rejection reasons join `ExtractionStats.rejection_reasons` beside the
  reconstruction gate's, capped and deduplicated, while the
  detected/accepted/rejected counts stay exactly as the layout engine left
  them.
- `A1, A2, B1`, `A1-A4`, `A1–A4` (en dash), `12 to 14` and `A01-A03` (printed
  width preserved) expand; `RXA-CLK` and `A1-B4` do not, and a register address
  never does. Every expanded record carries its row's section, table index, row
  index and printed page, and quotes the cell it came from.
- Prose laid out in columns under a pin caption is rejected as prose; a
  parametric spec table is neither accepted nor recorded as a rejection, since
  "not a device table" is not a finding and recording it would bury the real
  ones.
- A count mismatch **warns and keeps every record** (ADR 0005's decided
  outcome); a `pdf_text` document yields no device tables at all, the same rule
  `build_specset` applies to a backend with no trusted tables.
- Reading is pure and reproducible: the `TableBlock` is byte-identical
  afterwards, and two reads of one document return the same records in the same
  order — a derived artifact built on this has to be rebuildable.

## Ticket 04 — pins

`structure/pins.py` + `registry/pin_types.yaml` publish the pin table as
`pins.json`: one individually citable record per pin, a lexicon label for what
the pin is *for*, and the package cross-check that says when the table and the
package disagree. `dsa pins --part X [--pin A1] [--name VDD] [--type power]
[--q clock] [--json]` is the lookup; `Retriever.pins()` is the seam behind it.

### The one thing the abstraction had to survive first

The device-table abstraction rejects a table with a duplicate key, and a real
ADI pin table is **full** of them: a printed entry breaks its description —
and its ball list, and sometimes its name — over several lines, and ticket 09's
rowspan materialization repeats the key cell into each of those lines. Read
literally, AD9081's 167-row `Table 21. Pin Function Descriptions` is a
duplicate-key table and is thrown away entirely, because its descriptions are
long.

So ticket 04 added one rule to `device_tables.py`, opt-in per kind through a
new `identity:` field in the lexicon (`name`, for pins): **a wrapped row is one
row.** A grid line printing nothing in the identity column continues the entry
above — its text appends, its key-shaped keys join that entry — and a line that
*does* print an identity is a new entry even when its key cell repeats, unless
the entry above left its identity mid-list (a trailing `,`), which is
what a wrapped name list looks like on the page. A comma is the only marker,
and deliberately so: `-`, `+` and `/` end ordinary mnemonics (`RESET-`,
`VREF+`), so reading one as "unfinished" would merge two complete entries into
a fused record — one pin lost — instead of rejecting the misread grid whole.

The narrowness is the product. Measured on the two real pin tables in the gate:

- **AD9081** folds 167 grid rows into 80 printed entries and 321 unique balls,
  every one of them key-shaped, with zero duplicates — the table is accepted.
- **HMC520A** does *not* fold: its `LO` and `EPAD` rows both print pin `15`
  (the layout floor materialized `15` into the exposed-pad row, whose printed
  pin cell is blank) and both print a complete name, so they stay two entries,
  the duplicate stands, and the table is **rejected whole with a recorded
  reason**. That is the intended outcome, not a gap: merging them would have
  told a designer that pin 15 is named `LO EPAD`.

### Coverage over the six built parts

| Part | Printed pin table | Outcome |
|---|---|---|
| AD9081 | Table 21, 324-ball BGA | **321 pins published**; cross-check warns (324 stated) |
| HMC520A | Table 4, 24-terminal LCC | identified, **rejected whole**: `duplicate pin "15" (rows 4 and 5)` |
| LM741 | printed, but the layout floor never reconstructs it as a grid | no pin table, no file |
| QPA1003P | none printed | no pin table, no file |
| AFE7950 | none printed — the datasheet has no pin section at all | no pin table, no file |
| AFE7953 | none printed — same | no pin table, no file |

Every one of those six is the criterion's honest state: extracted, or rejected
with a recorded reason, or a document that prints nothing to extract. **No part
publishes a partial `pins.json`.** The distinction is visible on disk: a
rejection leaves a line in `ExtractionStats.rejection_reasons`; an absent pin
section leaves nothing, because an absence in the *document* is not a finding
about the extraction.

Two criteria could not be met as the ticket wrote them, and the reason is the
same fact:

- *"Pin tables extract for all six built parts"* — four of the six print no
  machine-readable pin table. AFE7950 and AFE7953 are the surprise: both are
  146/134-page TI specification documents whose printed TOC runs 1 Features →
  4 Specifications → 5/6 Revision History with **no pin section**, asserted in
  `test_afe7950_build.py::TestTheReferencePartsPrintNoPinTable`.
- *"`dsa pins --type power` on AFE7950 returns a plausible, hand-checked supply
  pin set"* — impossible for the same reason. The hand-checked set below is
  AD9081's, the one built part that has a pin table at all.

### `dsa pins --part AD9081 --type power` — hand-checked

**85 balls across 23 rails**, every one cited to p.22 or p.23, checked against
the printed Table 21:

```
AVDD1, AVDD1_ADC, AVDD2, AVDD2_PLL, BVDD2, BVDD3, BVNN2, CLKVDD1, DAVDD1,
DCLKVDD1, DVDD1, DVDD1P8, DVDD1_RT, FVDD1, NVG1_OUT, PLLCLKVDD1, RVDD2,
SVDD1, SVDD1_PLL, SVDD2_PLL, VCO_VREG, VDD1_NVG, VNN1
```

No ground, signal or no-connect ball leaks in. Three of those rails only
classify correctly because of a longer, more specific lexicon phrase, which is
the intended way to close an ambiguity: `PLLCLKVDD1`, `CLKVDD1` and `DCLKVDD1`
all carry `clk` *and* `clkvdd`, and `clkvdd` (6 characters) beats `clk` (3), so
a clock-domain supply reads as a supply. `NVG1_OUT` has no lexicon phrase in
its name at all and is caught by its description (`Supply Outputs`).

Full type mix for AD9081's 321 balls:

| type | power | ground | digital | analog | clock | nc | unknown |
|---|---|---|---|---|---|---|---|
| balls | 85 | 126 | 61 | 26 | 7 | 6 | **10** |

The 10 `unknown` balls are the honest half and are the reason the lexicon can
be trusted: `TDP`/`TDN` ("Anode and Cathode of Temperature Diodes") and the
eight `ADCx_FDy` fast-detect outputs match nothing the lexicon knows, so they
are labelled `unknown` with no evidence rather than guessed. Every classified
ball publishes the phrase that decided it (`type_evidence`, e.g.
`name:"clkvdd"`, `description:"differential input"`) — invariant 8's
`derivation`, per record.

### The package cross-check, on a real mismatch

AD9081 states `324-ball BGA` and 321 balls survive extraction. The cause is
exact and worth recording: the `GND` entry's ball list wraps mid-range across
two printed lines (`… M2 to` / `M5, M10, …`), so `M2 to` is not a key and
`M2`, `M3`, `M4` are lost — three balls, three missing. Per ADR 0005 the
mismatch **warns**: it is recorded in `manifest.json` under `derived_warnings`,
printed by `dsa status`, and it suppresses nothing. HMC520A's cross-check runs
too, even though it published no pins, and records `document states 24, no pin
table was published` — which is the most useful thing a pin-less part can say
and is invisible from a `pins.json` that does not exist.

A stated count is read only from a **hyphen-joined package descriptor**
(`324-ball BGA`, `24-terminal ceramic LCC`) and only when every descriptor in
the document agrees. Both halves are load-bearing: AD9081's own table of
contents prints `21 Pin Configuration and Function Descriptions` and LM741's
thermal table prints `8 PINS`, neither of which is a package descriptor; and
LM741 prints `8-Pin CDIP` beside a revision-history `10-Pin CLGA`, which
disagree and are therefore treated as no evidence at all rather than as a tie
to break.

### Golden pin questions

`pin_query` joins `spec_query` / `plot_query` / `ask_query` / `search_query` as
a path marker, verified by `evalh.citations.verify_pin_queries` and rendered in
`dsa verify`. The pass rule is the spec rule applied to pins — the expected
substrings must appear on records sitting on a page the question cites — plus
`count`, checked against the whole result set because a count is a claim about
the table rather than about one page.

AD9081's benchmark carries the ticket's three shapes and verifies **3/3 with
page cites** (`dsa verify --part AD9081` now reports 9/9 text, 1/1 spec, 1/1
plot, 3/3 pin, 1/1 ask, 1/1 search):

| id | shape | query | cited |
|---|---|---|---|
| `n1-pin-a2-name` | pin → name | `{pin: A2}` | p.22 → `AVDD2` |
| `n2-clkin-balls` | name → pins | `{name: CLKIN, count: 2}` | p.24 → `J1`, `K1` |
| `n3-no-connect-count` | count by type | `{type: nc, count: 6}` | p.25-26 → 2 `NC` + 4 `DNC` |

The other five parts carry no pin questions, because a benchmark for a pin
table that does not exist would be fiction.

### Confidence

Pins are graded by the same module and at the same time as specs
(`structure/confidence.py`): a rescued grid is `low`, a row that printed no
name is `low`, a section-range page is `medium`, everything else is `high`.
AD9081's 321 balls come back **321 high / 0 medium / 0 low** — its pin table is
caption-anchored, header-declared and page-pinned per row. The mix is recorded
per part in `CorpusStats.pin_confidence` and printed by `dsa status`.

### Contract points asserted by test

`tests/unit/test_pins.py` (67) is the rule test; `tests/unit/test_device_tables.py`
gained 9 for the wrapped-row reading; `TestPinsOnTheGateCorpora` (10) measures
the four gate corpora and `TestTheReferencePartsPrintNoPinTable` (4) the two TI
reference ones; `tests/unit/test_batch.py` gained the publish-cache-key cases
and `tests/unit/test_cli_verify.py` the `dsa verify` pin table.

- Rejected table → **no `pins.json`**, reason recorded; no pin table at all →
  no file *and* no reason; a stale `pins.json` republishes once and an absent
  one never does. A republish that now yields no pins **removes** the old file,
  so the corpus never serves a superseded pin table and the part settles
  instead of rebuilding forever.
- `CARD_VERSION` is at **"2"**: `pins.json` is a new derived artifact and
  nothing else in the skip gate moves for it, so a part built at ticket 03
  republishes once rather than skipping forever without a pin table.
- Multi-pin rows expand and every expanded pin cites its own printed page, even
  across a page break, quoting the printed cell (`pin_verbatim`) and row.
- Classification: an invented lexicon this repo never ships classifies pins
  with no Python change; the name tier outranks the description tier; the
  longest phrase wins; a two-letter phrase matches only a whole token (so the
  `nc` inside `SYNC0OUTB` is not a no-connect); a tie in either tier and a
  total miss both yield `unknown` **with no evidence**; and an `unknown` pin is
  still published, still verbatim, still cited.
- Cross-check: warns and keeps every pin, agrees silently, runs with no pins
  published, refuses a count from disagreeing descriptors, and lands in
  `manifest.json` — asserted through `dsa status`, not only through the object.
- `pin_gap()` on a corpus with no pin table; `dsa pins` exits 2 there and 1 on
  an ordinary no-match.
- `pins.json#pin_N` resolves through `provenance.resolve_source` to the record
  and its printed page, so a ticket-07 card can cite a pin the same way it
  cites a spec.

## Ticket 05 — register summary (`registers.json`, `dsa regs`)

The register map stops being a document the corpus cannot read. Two changes
land together, because either alone is useless: `DocType.REGISTER_MAP` now
routes to the vendor-neutral layout floor instead of the paragraph-only
`pdf_text` backend, and `structure/registers.py` publishes the summary table it
finds there as `registers.json`.

### The routing change, and its cost

`select_backend` gained a doc-type branch: a datasheet follows its vendor's
chain, a `REGISTER_MAP` goes to `VendorProfile.register_map_backend`
(`pdf_layout`, for every vendor), every other companion keeps `pdf_text`.
`PIPELINE_VERSION` moves **0.4.0 → 0.5.0** — the extraction cache is keyed on
`(content_hash, backend)`, so without the bump a part built before this ticket
would keep serving the paragraph-only reading of its register map forever. (The
0.4.0 the phase plan reserved for this change was spent earlier in the phase on
the layout engine's own output schema.) The caveats that said otherwise are
rewritten in `README.md` (three places) and `AGENTS.md` (the `pdf_text` module
row, the `vendor.py` row, and a new conventions bullet).

### Three layout-floor defects the real document exposed

Routing the register map to `pdf_layout` produced, at first, garbage: 252
mid-page lines of `LMX1204_registermap.pdf` were being stripped as *furniture*,
including the header row of every register field table and the **first data row
of the register summary** — which ended that table's region one line under its
own caption and threw all 35 registers away. Three fixes were needed, all of
them corrections to rules that were wrong in general and merely invisible until
a document this uniform arrived:

| Fix | What was wrong | Measured effect |
|---|---|---|
| `_margin_bands` | Furniture was any recurring y-slot with recurring text. In a 25-page document that prints the same table shape on every page, that *is* the body. | Furniture is now confined to the document's margin bands. Mid-page furniture over the register map / HMC520A / QPA1003P / LM741: **252 / 149 / 304 / 3 → 0**. |
| `_BAND_EPSILON` | Header-anchored column edges are clustered from the header row alone, so a data cell laid out flush with its header but 1.5e-5 pt to the left of it fell into the previous column. | Every acronym in LMX1204's summary moved back into the acronym column. Tolerance 0.001 pt — 0.05 pt was tried and moved four AD9081 spec values. |
| `_is_section_break` | A table region ended at any line whose text matched a section title. The summary prints `SYSREF` in a features cell; the datasheet has a §6.3.6 called `SYSREF`. | Table 7-1 went from 15 rows to 35. A heading is now told from a cell by having its baseline to itself. |

Two smaller ones travelled with them: a `(continued)` caption now continues its
table instead of starting a second candidate the gate rejects (LMX1204's R90 is
on p.33 alone), with the continuation page held to the same
words-inside-the-bands and non-empty-row rules the table's first page obeys;
and `structure/tables.py` drops C0 control characters from the **CSV twin
only**, because `lmx1204.pdf` prints ligatures through a font whose ToUnicode
map points at U+0001 and `csv.writer` cannot encode a NUL under any dialect —
one such glyph took the whole build down with `need to escape, but no
escapechar set`.

Those fixes improved parts that have nothing to do with registers, which is
what makes them fixes rather than special cases: **HMC520A goes from 30 spec
records (most of them valueless) to 85 with min/typ/max**, and AD9081's
confidence mix moves 151/207/191 → 158/210/181 with every recorded value and
page unchanged. `tests/fixtures/alias_seed_symbols.json` was regenerated by the
documented `scripts/seed_aliases.py` procedure; only HMC520A's rows changed
(16 → 30 distinct `(symbol, name, unit)` triples), and none of the other five
parts moved a single field.

### The artifact

One `RegisterRecord` per printed address, published only for a document whose
summary table passed the device-table validation. Everything is verbatim except
two derived fields, each carrying the rule that produced it:

| Field | Source |
|---|---|
| `address.verbatim` | the printed cell |
| `address.value` | `parse_register_word` — hex only by the marker the document printed (`0x…` / `…h`), decimal otherwise, anchored so `0x00-0xFF` and `See Table 7-1` parse to nothing |
| `name` / `access` / `description` | printed cells; `access` is `""` when the table prints no access column |
| `reset` | the summary's own reset column, else the register's printed declaration heading (`R25 Register (Offset = 0x19) [Reset = 0x0211]`), joined on the **parsed offset** and refused when the heading names a different register |

`--addr` resolves by value, which is the point of publishing both forms:
`0x19`, `0x19` in lower case, `19h` and `25` are one question. A cell the
grammar cannot read publishes `value: null`, grades `medium`, and is still
reachable by typing exactly what the page shows — never by an integer some
other base would have given it.

### Measured, LMX1204 (both documents)

Built as the honest fixture the ticket asks for: `dsa build
tests/fixtures/pdf/lmx1204.pdf --part LMX1204 --vendor unknown`, then `dsa
add-doc tests/fixtures/pdf/LMX1204_registermap.pdf --part LMX1204 --type
register_map`, then rebuild. The `--vendor unknown` pin is the LM741 precedent
(recorded as cli-override evidence): LMX1204 is a TI part, detection would
prefer the network-bound `ti_html` backend, and this repo holds no recorded
document-viewer pages for it. The companion needs no pin — a `register_map`
routes to the layout floor whatever its vendor.

| | datasheet (SNAS800B) | register map (SNAU269A) |
|---|---:|---:|
| Registers published | 35 | 35 |
| Address parsed | 35 | 35 |
| Confidence | 35 high | 35 high |
| Reset stated | 35 | 35 |
| Reset citing an exact page | 29 | 29 |
| Access published | 0 | 0 |

The two gaps are the honest ones. **Access is 0 because neither document prints
a register-level access column**: TI states access per bit field, in the
per-register field tables (`Type`: R, R/W), which is ticket 06's shape. Nothing
is guessed — `dsa regs` prints no access and `registers.json` carries `""`.
**Six of 35 resets cite no page** because their declaration heading survived
extraction as a bare paragraph with nothing to pin it to; the value is still
published with the printed line it was read from, and the page is `null` rather
than the section's 22-page range or a neighbouring table's. The reset coverage
is recorded (`RegisterSet.n_reset_stated` plus a manifest warning) precisely so
a caller can say what it could not read.

A note on that page, because it was nearly wrong: `pagemap.pin_table_pages`
rewrites `TableBlock.page` by matching cell text, and a field table whose cells
are `R`, `R/W`, `0x0` and `RESERVED` matches half a register map — LMX1204's
Table 1-25 pins to p.17 and is printed on p.19. The reset therefore cites the
table *region*'s page (`row_pages`, which pinning does not rewrite). Before that
fix one reset in each document cited a page its value was not printed on;
`TestResetTracesToAPrintedPage` is the walk that caught it, and it now asserts
that every pinned reset's evidence really is on the page it cites.

### Golden set

`tests/fixtures/golden_qa_LMX1204.yaml` — 15 questions written against the
**register-map companion**, so the whole set verifies with `dsa verify --part
LMX1204 --pdf tests/fixtures/pdf/LMX1204_registermap.pdf`: **10/10 text, 3/3
register, 1/1 ask, 1/1 search**. LMX1204 joins `BUILT_PARTS` in
`tests/unit/test_golden_paths.py`, so it carries the two phase-5 paths like
every other benchmarked part.

| id | shape | query | cited |
|---|---|---|---|
| `r1-address-to-name` | address → name | `{addr: 0x17}` | p.2 → `R23`, `Temperature Sensor` |
| `r2-decimal-address-finds-the-same-register` | decimal address → name | `{addr: 24}` | p.2 → `0x18`, `R24` |
| `r3-name-to-reset` | name → reset | `{name: R12}` | p.2 + p.11 → `0xFFFF` |

**A `name → access` question is absent, and that is a reported shortcoming
rather than an oversight.** Neither reference document prints a register-level
access column, so there is nothing to hold a question to; the golden file's
header says so. The code path is real and gated on a synthetic register summary
that *does* print one (`TestAccessIsVerbatimOrAbsent`).

### Contract points asserted by test

`tests/unit/test_registers.py` (66) is the rule test;
`tests/integration/test_phase6_registers.py` (13) is the gate over the two real
documents; `tests/unit/test_vendor.py` carries the routing change and
`tests/integration/test_phase3_multidoc.py` the provenance it moved.

- Rejected table (duplicate address, addresses out of order) → **no
  `registers.json`**, reason recorded with the `device-table (register)` prefix;
  no register table at all → no file *and* no reason; a republish that yields
  none **removes** the old file.
- `parse_register_word` on every printed form, and on eight strings it must
  refuse — including bare hex (`AB`, `0A`), whose base is the document's and not
  ours.
- `--addr` by value in four notations; the printed-string fallback for a cell
  that never parsed, and that it is *not* reachable by the integer another base
  would have given it.
- Reset: from a heading, from a reset column (which wins), from a table's
  test-conditions preamble; refused when the heading contradicts the row's
  name; `None` when the document declares nothing; the page taken from the
  region rather than from the pin, and `None` when there is nothing to pin it
  to.
- `access` published verbatim from a document that prints one, `""` from
  LMX1204 which does not.
- `register_gap()` on a corpus with no summary; `dsa regs` exits 2 there and 1
  on an ordinary no-match; `reset=?` in the rendered output.
- `registers.json#reg_N` resolves through `provenance.resolve_source` to the
  record and its printed page.
- `REGISTERS_SCHEMA_VERSION` and `CARD_VERSION` "3" in the skip gate; a missing
  file reads as current.

### Not built here

The `find_register` MCP tool named in the ticket's prose is deferred to ticket
10 (`MCP surface + goldens + phase gate`), which is where ticket 04's
`find_pin` also went: the MCP server today registers nine tools and neither
device-table consumer among them, so adding one of the two in isolation would
split that surface across two tickets for no gain.
