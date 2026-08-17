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

### Contract points asserted by test (`tests/unit/test_device_tables.py`, 50)

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
