# 08 — Scale gate + PHASE_7_REPORT

**What to build:** The proof that breadth actually works, and the report that
closes the roadmap. Breadth has to be demonstrated, not asserted.

**Blocked by:** 01–07

**Status:** ready-for-agent

- [ ] **≥20 parts** onboarded through `dsa fetch` + `dsa batch`, across
      **≥3 vendors**
- [ ] One project of **≥8 parts** builds and answers project-scoped questions
      correctly
- [ ] One family of ≥2 members builds with a correct delta table
- [ ] **Every onboarded part grades ≥ B** on `dsa audit`, or carries a
      recorded shortcoming explaining why it cannot — no part is quietly left
      ungraded
- [ ] Generated-then-confirmed goldens cover every new part; `dsa verify` at
      100% across the fleet
- [ ] All Phase 5 and Phase 6 goldens still at 100%
- [ ] `pytest` fully offline; `ruff` clean. Runtime impact of the larger
      fixture set is measured and, if the suite has grown unreasonable, the
      gate parts are sampled with the sampling recorded (per the
      no-silent-caps rule)
- [ ] `AGENTS.md`: invariant #5 gains the "generated candidates never count
      until confirmed" clause; module map gains `registry/` and `families/`
- [ ] `CONTEXT.md` gains **Family**, **Registry entry**, **Staleness**,
      **Audit grade**
- [ ] `README.md`: fetch / audit / family usage; the fleet table replaces the
      hand-maintained reference-parts table
- [ ] `Reports/PHASE_7_REPORT.md` with measured numbers: parts onboarded per
      vendor, audit grade distribution, family index tokens vs. sum of member
      indexes, answer-pack mean tokens at fleet scale, golden confirmation
      throughput
- [ ] `PHASE_7_PLAN.md` marked superseded by the report

---

Source: `.scratch/reach-and-trust/SPEC.md`
