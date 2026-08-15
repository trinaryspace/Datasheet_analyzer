# 02 — Revision awareness + staleness surfacing

**What to build:** The phase's safety feature. Revisions are parsed today
(`SBASA41E`, `Rev. I`) and then never questioned — so the tool would answer
from a superseded datasheet with full confidence and a valid page cite.

Additive inventory fields: `revision_checked_at`, `upstream_revision`,
`staleness` (`current | stale | unknown`).

`dsa check-revisions [--part X | --all]` is an **explicit, opt-in, network**
command — never part of `build`, so builds stay offline by construction.

Staleness surfaces in four places, and the fourth is the one that protects a
design decision:

```
⚠ This corpus is built from SBASA41E; SBASA41F is available upstream
  (checked 2026-08-15). Verify before committing to silicon.
```

**Blocked by:** 01 — Document registry + fetch

**Status:** ready-for-agent

- [ ] `dsa check-revisions` detects a stale corpus against a recorded fixture
      and records `upstream_revision` + `revision_checked_at`
- [ ] `build` performs **no** network revision check — asserted, so offline
      builds stay offline
- [ ] The staleness banner appears in **all four** surfaces — `INDEX.md`,
      `dsa status`, `dsa audit`, and the answer-pack footer — each asserted
      separately. A warning present in only three is the failure mode this
      test exists to catch.
- [ ] A never-checked corpus reads `unknown`, distinct from `current`, and the
      answer footer says "revision not checked" rather than implying currency
- [ ] MCP responses carry the staleness state so a remote agent sees it too
- [ ] The check degrades honestly when the network is unavailable: `unknown`,
      a warning, no crash, no stale-to-current transition

---

Source: `.scratch/reach-and-trust/SPEC.md`
