# 08 — Spec record ids are not unique within a document

**What to build:** A `spec_record_id` that is unique within its document.

**Measured:** `spec_record_id` is a pure function of `(section, table_index,
row_index)`, and `build_specset` numbers tables *within a section*. A document
whose sections carry no numbers restarts `table_index` at 0 in every section, so
several records compute one id.

**AD9081 publishes 549 spec records carrying 259 distinct ids.** `rec_s-t0-r0`
alone is carried by **14** records. This affects every datasheet read without a
numbered table of contents — every non-TI part in this corpus.

The consequence is not corruption, because Phase 6 chose refusal. `CardDocument`
cites the first record carrying an id and refuses the rest, naming the count in
`uncitable`. But the cost is large and visible: **AD9081's interface card keeps
1 row of the 21 its selectors matched**, and the JESD204B/JESD204C interface-rate
rows the datasheet prints on p.11 are among the refused.

**Fix, one of two, not both:**

- `spec_record_id` takes the section's **file slug** (unique per section)
  instead of its number, or
- `build_specset` numbers tables **document-globally**.

Either is roughly one line. They differ in what the id *reads* like and in
whether an id survives a document gaining a section — think about that second
property before choosing, because ids appear in published citations and a rule
that renumbers on every ingest makes every previously-written citation wrong.
State the reasoning in the report; this is the only real decision in the ticket.

Then bump `SPECS_SCHEMA_VERSION`. Every citation already written is invalidated
by construction — a record's id is a pure function of its coordinates and this
changes those coordinates. That is why this ticket is in wave 1 and not wave 0.

**Expected gain, to be measured and not assumed:** AD9081 from 259 to **549**
distinct ids, and its interface card from 1 row to the ~21 its selectors already
match. If the second number does not follow from the first, that is a second
defect and it belongs in the report, not in a patch to this ticket.

**Blocked by:** — (wave 1)

**Status:** done (wave 1; rebuild pending in 09)

- [x] One of the two fixes, with the choice and its reasoning written down
- [x] AD9081: **549/549 distinct ids**
- [ ] AD9081 interface card publishes the rows its selectors match, JESD204B/C
      interface rates among them — named individually in the report
      **Deferred to 09.** Cards are built from a *published* corpus, and this
      one has not been rebuilt yet. What is proved now is the cause: 549/549
      distinct ids, so no record is refused for sharing one.
- [ ] `CardDocument.uncitable` is **0** for every part in the corpus, or each
      remaining refusal is explained — **deferred to 09**, same reason
- [x] Ids stable across a rebuild of identical input (the Phase 6 ticket-01
      assertion still holds)
- [x] `SPECS_SCHEMA_VERSION` bumped; every test asserting the literal updated
- [x] Any checked-in fixture or golden holding a literal record id updated —
      grep for `rec_` across the repo, do not rely on the suite to find them

**Owns:** `src/datasheet_analyzer/models.py` (`spec_record_id`) **or**
`src/datasheet_analyzer/structure/specs.py` (`build_specset`) — whichever the
chosen fix needs, not both; `src/datasheet_analyzer/config.py`
(`SPECS_SCHEMA_VERSION` only); `tests/unit/test_record_ids.py`

---

Source: `.scratch/extraction-fidelity/SPEC.md`
