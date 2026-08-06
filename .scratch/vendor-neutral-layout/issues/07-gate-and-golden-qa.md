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

**Status:** shipped (commit on `feat/pdf-layout-paragraph-core`, ticket 07)

- [x] The four gate PDFs build corpora offline from fixtures (ungated, no skip guards)
- [x] A per-part golden file exists for each gate part; `dsa verify` reports 100% on text, `--specs`, and plot lookups for all four
- [x] `dsa verify` for a part without a golden file fails loudly (no silent zero-question pass)
- [x] The whole gate runs in a plain `pytest` invocation in CI-less local conditions

---

**Kickoff decisions (06/07/09 scope reconciliation + fixture mechanics,
recorded per the 04/06 and 06/07 precedent):**

1. **Scope reconciliation.** The ledger's "→ ticket 07" items — merged-cell
   materialization ("grid materialization", high), captionless-era tables
   (high), the QPA1003P zero-figures / title-anchored-figures ride-along
   (low), and continuation-row page attribution ("ticket 07
   (citations)", medium) — are **not** in this ticket's letter (gate
   provisioning + per-part golden Q&A, SPEC stories 26–27). All four
   are re-ticketed to `issues/09-layout-materialization.md` (the next
   free number — 08 is taken by shipped-docs-and-report); the ledger
   pointers and the 06 issue file's boundary text ("re-deferred to
   ticket 07") are corrected accordingly. The gate's ≥80% pin-verify
   band and lm741/QPA1003P's honest 0-table corpora stay until 09
   lands; this ticket's per-part goldens record the honest zeros.
2. **Ungated fixture mechanics.** The four gate PDFs are copied into
   `tests/fixtures/pdf/` (SPEC "Testing Decisions" letter: "the four
   gate PDFs copied into fixtures") and the gate test's skip guards are
   removed — a missing fixture is now a hard test failure, not a skip.
   The repo-root copies stay (git stores byte-identical blobs once,
   so this costs ~0 in `.git`; the root locations remain the
   documented `dsa build`/`dsa verify` working files — AGENTS.md
   command examples and the 08 docs ticket are untouched by the
   fixture home).
3. **QPA1003P honest 100%.** Its corpus has 0 tables / 0 spec records /
   0 figures (no "Table N." / "Figure N." captions at all) — its golden
   is text-questions-only: 11 questions verified at 100% on text, and
   "100% on `--specs` and plot lookups" is stated as the spec/plot
   question counts staying honestly empty (no spec_query/plot_query
   entries exist to fail or fake). The gate test asserts the honest
   zeros (0 tables, 0 specs, 0 plot files) alongside the 100% text
   verification. Same statement holds for LM741's spec count (0
   tables → no spec_query entries; its golden carries text + plot
   questions only, 12 verified at 100%).

**Ship notes.** `golden_qa.yaml` (AFE7950, 19 Q) is renamed to
`golden_qa_AFE7950.yaml` so per-part discovery (`--golden` default →
`tests/fixtures/golden_qa_<PART>.yaml`) is uniform with no special
case; `dsa verify` hard-fails (exit 2, stderr message) when a part's
benchmark is absent or a golden has zero questions. Benchmarks shipped
in this ticket (all verified 100% in the ungated gate): LM741 12 Q
(10 text + 2 plot, spec n/a), QPA1003P 11 Q (text only), HMC520A 13 Q
(10 text + 3 spec + 3 plot). AD9081's ticket-05 minimal set grows to 4 Q
at ticket 07: the CLI `--specs` check proved q2's original spec_query had
never executed and cannot pass (the row's values live on child rows, so
its parent record honestly carries empty fields) — the spec_query moved
to a new q3 (Gain Matching, complete values) and the footnote answer path
q2 guards stays text-verified (recorded in the golden file's header).
Consequence recorded in the ledger: `dsa verify --part AFE7953`
now hard-fails (no `golden_qa_AFE7953.yaml` yet) instead of silently
running the AFE7950 benchmark; README's verify example is corrected.

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
