# 09 — Layout materialization + continuation-page attribution (deferred from 07)

**What to build:** The four layout items the 07 ledger pointed at but that
are **not** in ticket 07's letter (07 is gate provisioning + per-part
golden Q&A). Re-ticketed at the 06/07/09 kickoff from the ledger entries
they were labeled "→ ticket 07"; the 06 issue file's boundary text that
referred to "ticket 07" is corrected to this ticket here.

1. **Merged-cell (rowspan/colspan) materialization** — SPEC story 12:
   nothing currently *replicates* a spanning cell across grid rows/columns
   (wrapped multi-line cells merge into one row; colspan'd headers fall
   back to `roles.py` empty-header inference). A table that depends on
   explicit span semantics loses the association. Needs its own
   probe-backed synthetic fixture set (span shapes + materialized grids),
   not a lexicon change. Ledger: "grid materialization", high.
2. **Captionless-era tables** — lm741 / QPA1003P have heading-anchored,
   captionless tables and honestly yield 0 tables / 0 specs. Heading-
   anchored hypotheses must not hallucinate (SPEC story 10: captionless
   doubles stay paragraphs is the rejection-gate guard). Ledger: high.
3. **Title-anchored figures** — QPA1003P has zero "Figure N." captions
   (its block diagram and performance plots are title-anchored), so its
   plots.json is honestly empty. Rides along with item 2 (same
   anchor/rejection design). Ledger: low.
4. **Continuation-row page attribution** — merged multi-page tables cite
   only the caption page; measured 20/21 AD9081 pin "misses" are
   continuation rows found on later pages. Per-row page attribution inside
   merged grids is the fix; the corpus-verify gate keeps its ≥80% band
   until this lands. Ledger: "ticket 07 (citations)", medium.

**Blocked by:** 07 — Gate provisioning + per-part golden Q&A (this
ticket's per-part goldens must record the honest zeros for lm741 /
QPA1003P so the materialized outcomes are later provable against a
benchmark).

**Status:** ready-for-agent

- [ ] Merged cells materialize as fully-expanded grids (SPEC story 12), pinned by synthetic span fixtures
- [ ] Heading-anchored table hypotheses ship with the captionless-doubles rejection guard (SPEC story 10), proving lm741/QPA1003P tables + specs
- [ ] Title-anchored figures render for QPA1003P (its plots.json stops being honestly-empty)
- [ ] Continuation rows carry per-row page attribution; the gate's ≥80% pin band tightens

---

Source: `.scratch/vendor-neutral-layout/SPEC.md` (post-07 scope
reconciliation: ledger entries + 06 boundary text, corrected at the
06/07/09 kickoff)
