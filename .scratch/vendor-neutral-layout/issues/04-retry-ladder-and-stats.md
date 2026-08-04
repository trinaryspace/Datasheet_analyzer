# 04 — Retry ladder + extraction stats

**What to build:** Robustness and honesty instrumentation on top of the
table engine — rejected hypotheses retried with coarser splits, the
best reconstruction-scoring grid accepted, unrecoverable tables degraded
to paragraphs and recorded, and per-document extraction stats (detected /
accepted / rejected + reasons) persisted in the manifest and surfaced by
`dsa status`.

**Blocked by:** 03 — Tables: caption-anchored hypotheses + reconstruction gate

**Status:** done (landed in `layout: best-scoring retry ladder + dsa status stats, ticket 04`)

- [x] A synthetic PDF that fails single-pass splitting but succeeds with coarser columns has its table recovered through the ladder (AD9081 Tables 17/20/21 geometry on a 2-word header over undeclared body columns; probe: every band set gated and scored)
- [x] A table the ladder cannot recover degrades to paragraphs and is recorded in extraction stats with its reason (exact gate verdict `columns not stable across rows` pinned)
- [x] `dsa status` shows per-document table detection/accept/reject counts with reasons for pdf_layout parts (per-doc lines under each part; fidelity; `rejection reasons:`)
- [x] The stats contract is additive: ti_html and pdf_text documents carry empty/zero stats without breaking existing assertions (asserted at manifest + CLI level)

**Selection rule (measured):** every band set is gated and scored; `_advice_share` —
the share of header-anchored column edges the candidate's own band edges reproduce —
selects the winner (a split that merges the header's declared columns loses the
edges it merged; the header-anchored candidate is the score maximum by construction
whenever it passes); ties keep ladder order; the winner's measured word fidelity is
reported as mean_fidelity and is never the selector (fidelity-max would select
prose-fragmenting splits: measured AD9081 Table 3 0.850 vs the declared grid 0.739).
All 35 real gate tables (AD9081 29, HMC520A 6) keep their ticket-03 grids verbatim.

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
