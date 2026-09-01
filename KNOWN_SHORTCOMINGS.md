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

**Two entries closed after wave 2 and deleted here.**

*"Extraction cache: a fix in the structure layer is invisible to a cached
extraction"* — the structure stage now has a version of its own
(`config.STRUCTURE_STAGE_VERSION`, embedded in
`RawDocument.structure_version`) that invalidates the cache the way an
extractor change does, so `--no-cache` is no longer the only way to land a
`structure/` fix. Measured on the document that showed the defect: LMX1204's
datasheet re-extracted on the version mismatch alone and pinned 484 of 501
row pages, the number the phase-6.5 rebuild could only reach with
`--no-cache`.

*"Registers: one record id is carried by a record in each of a part's two
documents"* — `register_record_id` folds in the document
(`reg_d0e7de32d-t0-r5`), the shape ticket 08 used one level up, and
`REGISTERS_SCHEMA_VERSION` is 2. Measured from both cached extractions:
LMX1204's 70 register records now compute **70 distinct ids**, none shared
between its two documents. The published `registers.json` files still carry
the old ids until the next rebuild — a record with no `doc_key` computes the
old shape on purpose, so citations already written keep resolving — and
`test_the_published_ids_are_distinct_once_the_part_is_rebuilt` says so when
it skips.

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

## Register bit fields: not extracted (ticket 06 stays parked)

**Phase 6, ticket 06; re-attempted and re-measured in phase 6.5, wave 2.** The
phase plan asks for per-register bit fields — `{"name": "NCO_EN", "bits":
{"verbatim": "[3]", "hi": 3, "lo": 3}, ...}` — and gives the ticket leave to
park rather than ship approximate ones, because a wrong bit range is acted on:
a driver written against it misconfigures silicon and fails silently. **The
gate is 100% over a sample fixed by document order, with no partial credit. It
was met for two of six registers in phase 6; it is now met for four of six.
Four is not six, so `RegisterRecord.fields` stays `[]` for every published
register.**

**The numbers moved a long way, and are recorded because the direction matters
even when the verdict does not change.** Measured against
`LMX1204_registermap.pdf` at extractor `tables-09` by
`tests/integration/test_phase6_bitfields.py`:

| | Phase 6 | Phase 6.5 |
|---|---|---|
| field tables the layout engine hands over (of 35 printed) | 12 | **30** |
| registers that survive validation | 4 | **15** (43%, from 11%) |
| fields emitted | 13 | **71** |
| the six-register sample (R0, R2, R3, R4, R5, R6) | 2 | **4** |
| precision over everything emitted | 100% | **100%** |

**What refuses now, and why.** The three misreads ticket 06 named are gone:
R13 and R17 no longer read `SYSREFREQ_DELAY_ST EPSIZE`, R19/R21/R25 are no
longer truncated to their first field, and R12's header no longer swallows two
body lines. **Twelve of the fifteen remaining refusals are one new cause**: the
document prints two cross-reference sentences after every field table (`R<n>
is shown in … Summary Table`, `Return to the Summary Table`), the table region
now runs on into them, and they arrive as two more rows whose bit cell is
prose. The other three are genuine: R4 and R9 print field lists that cover only
part of the register, and R90's two fields claim the same eight bits.

**What the tool does instead.** Nothing. No bit-field record is published, no
CLI or MCP surface answers a bit-field question with data, and `dsa regs
--field` says out loud that no bit breakdown exists for the part
(`derive/registers.no_bit_fields_message`) rather than returning an empty
result that reads as "this register has no fields". `derive/bitfields.py` is
imported by no shipping module; the gate asserts that too.

**One of ticket 06's three reasons to park is now closed.** The reference map's
own summary table is recovered (35 records on its page 2), so there *is* a
summary record in that document to hang fields off. Recall is what parks it
now, alone.

**Also honest:** the reference document prints **no bit-position diagram at
all**, so the geometric column-span reader — the shape the ticket names — is
exercised only by the synthetic fixtures in `tests/unit/test_bitfields.py`. No
real document in this repository gates it.

**What would close it.** Ending the table region at the last row rather than at
the trailing cross-reference prose (`extract/pdf_layout.py`), which would put
twelve more registers in front of the validators, plus whatever the three
genuine refusals then need. That is another cache-invalidating change to the
layout floor, so it belongs to a deliberate re-extraction pass.

