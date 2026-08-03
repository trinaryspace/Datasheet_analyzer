# 04 — Retry ladder + extraction stats

**What to build:** Robustness and honesty instrumentation on top of the
table engine — rejected hypotheses retried with coarser splits, the
best reconstruction-scoring grid accepted, unrecoverable tables degraded
to paragraphs and recorded, and per-document extraction stats (detected /
accepted / rejected + reasons) persisted in the manifest and surfaced by
`dsa status`.

**Blocked by:** 03 — Tables: caption-anchored hypotheses + reconstruction gate

**Status:** ready-for-agent

- [ ] A synthetic PDF that fails single-pass splitting but succeeds with coarser columns has its table recovered through the ladder
- [ ] A table the ladder cannot recover degrades to paragraphs and is recorded in extraction stats with its reason
- [ ] `dsa status` shows per-document table detection/accept/reject counts with reasons for pdf_layout parts
- [ ] The stats contract is additive: ti_html and pdf_text documents carry empty/zero stats without breaking existing assertions

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
