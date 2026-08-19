# 06 — Row continuation misreads produce duplicate keys

**What to build:** Row reconstruction that leaves a genuinely blank first cell
blank instead of inheriting the previous row's.

**Measured, two consequences from one cause.**

*Pins.* HMC520A prints one pin table (`Table 4. Pin Function Descriptions`).
The layout engine reconstructs its exposed-pad row with the **previous row's
designator**, so designator `15` appears twice; the device-table layer refuses a
table with duplicate keys and **24 real pins are lost**.

The refusal is correct and **must stay**. A pin table missing its last row reads
as "this pin does not exist" during schematic capture — publishing it would be
worse than publishing nothing. The defect is upstream, and that is where to fix
it.

*Registers — this is the recall problem.* The same class of misread is what
limits the register map to **12 of 35** field tables. Measured damage:

| Symptom | Registers |
|---|---|
| wrapped name cell re-joined as `SYSREFREQ_DELAY_ST EPSIZE` | R13, R17 |
| table truncated to its first field | R19, R21, R25 |
| two body lines folded into a header | R12 |

Each is caught and refused, so precision stays **100%**. The entire cost is
recall.

**Gate:** table recall on `LMX1204_registermap.pdf` from **12/35 to ≥ 28/35**,
precision held at **100%**, and HMC520A's **24** pins published.

Read that gate the strict way: **no field may become wrong in order to make more
appear.** A change that reaches 30/35 with one wrong bit position has failed
this ticket. If recall and precision genuinely trade against each other here,
stop and report the trade rather than choosing for the project.

**Blocked by:** — (wave 1; coordinate with 05, which owns the same file)

**Status:** done (wave 1; rebuild pending in 09)

- [x] Synthetic fixtures for each of the four symptoms in the table above,
      written before the fix and failing for the documented reason
- [x] A genuinely blank leading cell reconstructs as blank
- [x] A genuine continuation row still joins to its predecessor — assert both
      directions; this ticket can break wrapped-cell handling if it only tests
      the new case
- [x] Register-map recall ≥ 28/35 with precision at 100%, both measured and
      recorded per register
- [x] HMC520A publishes 24 pins; the duplicate-key refusal still fires on a
      synthetic table that really does have duplicate keys
- [ ] Phase 6 goldens re-measured and not regressed — **deferred to 09**:
      the goldens read a published corpus, which 09 rebuilds
- [x] `output_version` **not** bumped here; ticket 09 bumps it once

**Owns:** `src/datasheet_analyzer/extract/pdf_layout.py` (row reconstruction
only), `tests/unit/test_pdf_layout_tables.py`,
`tests/unit/test_pdf_layout_rows.py`

**Note on file sharing:** 05 and 06 both own parts of `pdf_layout.py`. They are
the one pair in wave 1 that must agree on a seam before either starts — 05
changes what reaches the table region, 06 changes what happens inside it. Agree
the boundary in writing first; do not discover it in a merge.

---

Source: `.scratch/extraction-fidelity/SPEC.md`
