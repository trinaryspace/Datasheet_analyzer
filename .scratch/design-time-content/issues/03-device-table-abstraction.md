# 03 — Device-table abstraction

**What to build:** `structure/device_tables.py`. Pin tables and register
summary tables are the same structural animal — wide, repetitive, keyed by a
first column — so build one abstraction with two consumers rather than two
parsers.

Pipeline: **identify → map columns → validate → emit.**

- Identify by checked-in header lexicon (no vendor rules):
  pin `pin|ball|pad|no\.?|number` × `name|signal` × `type|i/o|dir` ×
  `description|function`; register `address|offset|reg` × `name|register` ×
  `reset|default|por` × `access|r/w|type`.
- Map columns by header match with positional fallback.
- Validate: unique keys, monotonic addresses where applicable, count
  cross-checks. **A validation failure rejects the table with a recorded
  reason** — the same honesty contract `pdf_layout` already applies to
  parametric tables.
- Emit records with full provenance (table index, row index, page).

No consumer ships in this ticket; it lands with synthetic fixtures only.

**Blocked by:** 01 — Derived-artifact contract

**Status:** ready-for-agent

- [ ] Header lexicons are checked-in data; adding a header variant is a data
      change, not a code change
- [ ] Column mapping works with abbreviated headers and with no headers at all
      (positional fallback), each covered by a synthetic PyMuPDF fixture
- [ ] A table failing validation is **rejected with a reason**, never emitted
      partially — asserted with a duplicate-key fixture and a
      non-monotonic-address fixture
- [ ] Rejection reasons join `extraction_stats.rejection_reasons` so device
      tables are as measurable as parametric ones
- [ ] Multi-value key cells (`A1, A2, B1` and `A1–A4`) expand correctly, with
      each expanded record keeping the source row's provenance
- [ ] A prose table that merely looks tabular is not accepted as a device
      table (mirrors the existing no-hallucinated-tables guarantee)

---

Source: `.scratch/design-time-content/SPEC.md`
