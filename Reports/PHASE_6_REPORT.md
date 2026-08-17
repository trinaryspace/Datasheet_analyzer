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
| HMC520A | pdf_layout | 30 | 4 | 13% |

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
