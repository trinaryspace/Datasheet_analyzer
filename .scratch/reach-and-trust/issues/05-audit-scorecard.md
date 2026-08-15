# 05 — `dsa audit` — corpus scorecard

**What to build:** Promote builder-side statistics into a consumer-readable
trust signal. `extraction_stats` tells the *builder* how a build went; nothing
tells the *agent* whether to trust a corpus before answering.

Metrics: section page coverage, table pin rate, table accept rate, mean
fidelity, spec page rate, record confidence mix, pins/registers/cards present,
axis coverage, alias hit rate on goldens, revision freshness, golden pass
rate. Graded against a **checked-in rubric** (`registry/audit_rubric.yaml`)
into an overall A–F.

The deliverable of this ticket is that an agent can say:

> "This corpus grades C — table pin rate 61%. The value I found is `medium`
> confidence; confirm against printed p.47."

**Blocked by:** 02 — Revision awareness (freshness is a graded metric)

**Status:** ready-for-agent

- [ ] `dsa audit --part X` grades every metric above; `--all` prints the fleet
      table; `--json` feeds tooling
- [ ] The rubric is data-driven: changing `registry/audit_rubric.yaml` in a
      test changes the grade — asserted
- [ ] MCP `get_audit(part)` exposes the grade so an agent can check trust
      before answering
- [ ] Missing artifacts (no pins, no registers, no cards) reduce the grade
      rather than erroring
- [ ] A metric that cannot be computed is reported as `n/a` and excluded from
      the average, never scored as zero
- [ ] All six built parts are graded and the grades recorded for the phase
      report — including any that grade poorly, stated plainly
- [ ] The rubric's thresholds are justified in a comment block, so a grade is
      defensible rather than arbitrary

---

Source: `.scratch/reach-and-trust/SPEC.md`
