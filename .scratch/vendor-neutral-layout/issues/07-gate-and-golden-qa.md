# 07 — Gate provisioning + per-part golden Q&A

**What to build:** The acceptance gate that licenses the multi-vendor
claim — the four real PDFs (AD9081, lm741, QPA1003P, hmc520a) as ungated,
offline fixtures; per-part golden benchmark files whose ground truth comes
from printed page text; `dsa verify` hard-failing when a part's benchmark
is missing; 100% verification (text, spec-query, plot-query) across all
four in a plain offline `pytest` run.

**Blocked by:** 03 — Tables: caption-anchored hypotheses + reconstruction gate,
04 — Retry ladder + extraction stats,
05 — Footnotes + figures vertical,
06 — Semantics genericization

**Status:** ready-for-agent

- [ ] The four gate PDFs build corpora offline from fixtures (ungated, no skip guards)
- [ ] A per-part golden file exists for each gate part; `dsa verify` reports 100% on text, `--specs`, and plot lookups for all four
- [ ] `dsa verify` for a part without a golden file fails loudly (no silent zero-question pass)
- [ ] The whole gate runs in a plain `pytest` invocation in CI-less local conditions

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
