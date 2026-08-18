# 08 — Phase gate + PHASE_8_REPORT

**What to build:** The end-to-end proof that the design loop closes, and the
report that documents it.

**Blocked by:** 01–07

**Status:** ready-for-agent

- [ ] A complete design walkthrough runs **in the test suite** against a
      checked-in synthetic design: import → bind → connections → check →
      `DESIGN_REVIEW.md` → `dsa ask --design`
- [ ] At least one **real** finding is produced against a real corpus in this
      repo and hand-verified against the printed page
- [ ] At least one **deliberately injected fault** is caught by the rules, and
      one deliberately clean design produces no findings
- [ ] Every rule's unevaluated population is reported and visible in the
      walkthrough output — no rule reads as clean without saying what it
      skipped
- [ ] A pack round-trips and answers in a clean directory
- [ ] Retrieval and performance budgets are recorded and enforced
- [ ] `PIPELINE_VERSION` bumped (confirm the entering value in
      `src/datasheet_analyzer/config.py` first — earlier phases moved it ahead
      of plan)
- [ ] `AGENTS.md` invariant 8 restated to cover design checks; module map
      updated with `designs/`, the rules engine and the pack format
- [ ] `CONTEXT.md` gains the nouns: Design, Refdes, Net, Rail, Design rule,
      Finding, Expert pack
- [ ] `README.md` leads with the design-loop walkthrough
- [ ] `Reports/PHASE_8_REPORT.md` carries the measured numbers: fleet size,
      coverage percentages, findings produced, pack sizes, retrieval metrics,
      latency p50/p95, and every open item stated plainly
- [ ] `Reports/PHASE_8_LIVE_RUN.md` consolidates any step that needs network
      or a real EDA export, as an ordered runbook the owner can execute cold
- [ ] `pytest` fully offline; `ruff` clean

---

Source: `.scratch/design-loop/SPEC.md`
