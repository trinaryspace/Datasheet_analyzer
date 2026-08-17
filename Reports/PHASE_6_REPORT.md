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
