# 03 — `dsa diff-rev`

**What to build:** Two revisions of one part built side by side (`--rev`
suffixes the document directory so both coexist under one part), then
diffed — so a datasheet update becomes a review rather than a re-read.

- **Specs**: added / removed / changed by alias-resolved symbol, with both
  verbatim values, both pages, and a human-readable delta via the Phase 6
  numeric layer ("TJ max 105 → 125 °C").
- **Sections**: added / removed / retitled / page-shifted.
- **Pins and registers**: added / removed / renamed / reset-value changed —
  the deltas designers most need and least expect to have to check.

Output: `parts/<PART>/REVISION_DIFF.md` plus `--json`.

**Blocked by:** 02 — Revision awareness; Phase 6 ticket 02 (numeric layer)

**Status:** ready-for-agent

- [ ] Two revisions of one part coexist under one part directory without
      colliding, and both remain independently queryable
- [ ] Spec deltas are computed by alias-resolved symbol, so a renamed-but-
      equivalent parameter is reported as changed rather than as
      removed+added
- [ ] Numeric deltas appear only where both sides parsed; everything else is
      listed verbatim under "review by hand" and is **never scored**
- [ ] Section retitles and page shifts are distinguished from additions
- [ ] Pin and register deltas included, with reset-value changes called out
      specifically
- [ ] A diff against an identical revision produces an empty diff, not noise
      (determinism check)
- [ ] Verified against a hand-checked expectation on a real revision pair

---

Source: `.scratch/reach-and-trust/SPEC.md`
