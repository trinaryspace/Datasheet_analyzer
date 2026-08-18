# 02 — Pin-level join + coverage reporting

**What to build:** Join every netlist node to the Phase 6 pin record it refers
to, producing `designs/<NAME>/connections.json`. This is the view every design
check runs over, and its most important property is **honesty about its own
coverage**.

A consumer reading this file must be able to tell exactly how much of the
design the tool actually understands: which parts have pin tables, which
nodes matched, which did not and why.

**Blocked by:** 01 — Design ingest

**Status:** ready-for-agent

- [ ] `connections.json` maps `(refdes, pin) → net` and attaches the pin
      record: id, name, type, and printed page
- [ ] Each row records `matched_on` — `designator` or `name` — so a match is
      auditable rather than asserted
- [ ] Nodes whose pin cannot be found in the corpus appear under
      `unmatched_nodes` with a reason, never dropped
- [ ] Per-part **match coverage** is reported ("U3: 41 of 41; U5: 12 of 64 —
      corpus has no pin table") and is asserted by a test that includes at
      least one part with no pin table
- [ ] A component bound to a part with **no** pin records produces a clear,
      non-fatal coverage entry rather than an error or an empty success
- [ ] `dsa design status X` surfaces the coverage summary
- [ ] Pin type comes from the checked-in `registry/pin_types.yaml` lexicon
      already in the repo — do not introduce a second type vocabulary
- [ ] No model call anywhere in the join (invariant 8); every attached field
      resolves to a record id and a printed page

---

Source: `.scratch/design-loop/SPEC.md`
