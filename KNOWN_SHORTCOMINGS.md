# Known shortcomings

What this tool cannot currently do, written down where a reader will find it.

An entry here is a **parked** piece of work: something a ticket set out to do,
could not do honestly, and refused to fake. Every entry names what is missing,
why it is missing, what the tool does instead, and what would close it. A
shortcoming that is recorded is a decision; a shortcoming that is silently
worked around is a bug.

**Every figure below was re-measured in phase 6.5, wave 2** (the full
re-extract and rebuild of all eleven parts at pipeline 0.5.0, extractor
`tables-09`). Five entries closed there and were deleted; what remains is
current, not carried forward. Closing numbers are in
`Reports/PHASE_6_5_REPORT.md`.

**One more closed since:** the register bit-field park (phase 6
ticket 06). Two region defects in `extract/pdf_layout.py` were fixed at
extractor `tables-10` — a table region that ran on past its table into the
section heading and cross-reference sentences below it, and a `Bit` column
cell refused release because the digit it printed equalled the page number.
The accuracy gate went from four of six sampled registers to **six of six**,
recall over `LMX1204_registermap.pdf` from 15 of 35 registers to **28**, and
precision stayed at **100%** over 116 fields, so `RegisterRecord.fields` now
ships. The entry is deleted rather than rewritten, which is what a closed
shortcoming is.

---

## Pins: AFE7950 and AFE7953 publish no pin table

**Phase 6, ticket 04; re-measured phase 6.5.** The phase plan's acceptance gate
asks for `dsa pins --part AFE7950 --type power` to return a hand-checked supply
pin set. It returns nothing, and the reason is in the document rather than in
the tool: **the AFE7950 datasheet in this corpus prints no pin table.** Its
section 4 (Specifications) is followed directly by section 5 (Revision
History) — there is no *Pin Configuration and Functions* section to read. The
same is true of AFE7953. **Re-measured on the 0.5.0 rebuild: 0 pins for each,
unchanged.**

**What the tool does instead.** No `pins.json` is published for either part,
and `dsa pins --part AFE7950` says so in as many words rather than printing an
empty result that reads as "this part has no pins". The hand-checked supply
pin set the gate asks for was produced for **AD9081** instead (22 rails, 79
balls, checked against Table 21 of its datasheet) and is asserted in
`tests/integration/test_phase6_pins.py::TestSupplyPinSet`; on the rebuild
AD9081 still publishes **210** pins.

**What would close it.** A TI datasheet revision that includes the pin
configuration section, added to the part with `dsa add-doc`. Nothing in
`derive/pins.py` needs to change: it reads whatever pin table the document
prints.

---

## Cards: no built part prints a zero-margin parameter

**Phase 6, ticket 07; re-measured phase 6.5.** The `limits` card flags a
parameter whose recommended maximum equals its absolute-maximum rating — a
genuine design hazard that is invisible when the two tables are read pages
apart. The phase gate asks for at least one such parameter to be flagged **if
one exists in the reference parts**. None does. **Re-measured across all
eleven rebuilt parts: 6 comparable pairs, 0 of them equal** —

| Part | Parameter | Rating | Recommended max | Margin |
|---|---|---|---|---|
| AFE7950 | `DVDD0P9, VDDT0P9` | 1.2 V | 0.95 V | 0.25 V |
| AFE7950 | Junction temperature | 150 °C | 110 °C | 40 °C |
| AFE7953 | `DVDD0P9, VDDT0P9` | 1.2 V | 0.95 V | 0.25 V |
| AFE7953 | Junction temperature | 150 °C | 110 °C | 40 °C |
| LMX1204 | Power supply voltage | 2.75 V | 2.6 V | 0.15 V |
| LMX1204 | Junction temperature | 150 °C | 125 °C | 25 °C |

No pair has zero margin, and none is negative. LMX1204's two pairs are new
here: it was not a built part when phase 6 recorded this entry.

**What the tool does instead.** The flag is proved on a synthetic corpus in
`tests/unit/test_cards.py::TestLimitsCard`, and
`tests/integration/test_phase6_cards.py::TestZeroMarginHazard` asserts the
property that actually matters over real data: *every* equal-limit pair found
in a reference part carries the flag. Today that set is empty, and the test
will start asserting the moment a part that prints one is added.

---

## Registers: one record id is carried by a record in each of a part's two documents

**Found by phase 6.5, wave 2, on the rebuild it performed.** Phase 6.5 ticket
08 made a *spec* record's id unique within its document, and the rebuild
confirms it: every part in the corpus now publishes as many distinct spec ids
as it has records (AD9081 549/549, LMX1204 543/543 and 284/284, HMC520A 85/85,
lm741 71/71, QPA1003P 41/41).

A **register** record's id is likewise a pure function of its coordinates
inside one document (`reg_t0-r15`), and that was sufficient while no part had
two documents printing a register map. LMX1204 now does: the datasheet's
`Table 7-1` and the register map's `Table 1-1` print the same 35 registers, and
recovering the second one (ticket 05) means the part publishes two
`registers.json` files whose records compute **the same 35 ids**. Measured:
70 records, 35 distinct ids, every id carried by one record in each document.

**What the tool does instead.** Nothing wrong, because the contract is
per-document: `derive/provenance.resolve_source` is given the roots to search,
and a derived value cites a record inside one document. Resolved against its
own document's root every one of the 70 records resolves to itself, which is
what `tests/integration/test_phase6_registers.py::…::
test_every_published_register_resolves_to_a_record_and_a_page` asserts. A
consumer that passes *both* roots as a list gets the first document's record.
`dsa regs --addr 0x11` therefore answers twice — once per document, each hit
citing its own page — which is honest but is two answers to one question.

**What would close it.** The same fix ticket 08 applied one layer up: fold the
document into a register record's id, or resolve a citation against the
document it was written against rather than a list of roots. Both change the
shape of every register citation already written, which is why this is recorded
rather than done in passing.

---

## Extraction cache: a fix in the structure layer is invisible to a cached extraction

**Found by phase 6.5, wave 2, while performing the rebuild it planned.** The
extraction cache is keyed `(content_hash, backend)` and invalidated by the
backend's embedded `output_version` — which is exactly what invariant 6 says.
But per-row page pinning (`structure/pagemap.pin_table_row_pages`, ticket 07)
runs **inside** `pipeline._extract_document`, after the backend returns and
before the result is cached. It has no version of its own, and it is not part
of any cache key.

**Measured, and the reason this is written down:** bumping
`PdfLayoutBackend.output_version` to `tables-09` re-extracted every
`pdf_layout` document, and left every `ti_html` document — AFE7950, AFE7953 and
LMX1204's datasheet — served from a cache written before ticket 07. The first
rebuild of LMX1204 therefore still showed the off-by-one row the ticket had
fixed (1 of 35, `0x5A`/`R90` cited on p.32 and printed on p.33). Only
`dsa build --no-cache` produced the corrected corpus (484 of 501 rows pinned,
0 rows citing a page they are not printed on).

**What the tool does instead.** Nothing detects it. The rebuild in this phase
was done with `--no-cache` for all three `ti_html` documents once the gap was
found, so the published corpus is correct.

**What would close it.** Giving the post-extraction enrichment steps a version
that participates in the cached record the same way `extractor_version` does —
a `RawDocument.pipeline_stage_version`, checked in `_load_cached_raw`. Until
then, any change to `structure/pagemap.py` must be landed with a deliberate
`--no-cache` rebuild, and saying so here is the only thing that makes that
knowable.
