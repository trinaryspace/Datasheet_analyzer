# 06 — Projects (the noun above `part`)

**What to build:** `projects/<name>/` holding `project.json` (name, parts[],
notes, timestamps) and a `PROJECT_INDEX.md` under a hard token budget
(default 4,000) — the single always-loadable entry point for a whole design:
each part with its one-line role, revision, and a pointer to its `INDEX.md`,
plus a free-text `interfaces` note the designer maintains.

Commands: `dsa project new|add|remove|build|status`. `--project` is accepted
by `ask`, `search`, `query`, and `plots`, fanning out across member parts and
labelling every hit with the part it came from.

Explicit part lists only — no BOM CSV or netlist parsing (recorded in the
SPEC's Out of Scope; an agent that reads a BOM can call `dsa project add`).

**Blocked by:** 01 — Retrieval core seam
(independent of 02–05; can run in parallel with them)

**Status:** ready-for-agent

- [ ] `dsa project new rf-frontend` then `add AFE7950 HMC520A AD9081` then
      `build` produces `PROJECT_INDEX.md` within budget
- [ ] The budget is hard: an oversized project truncates the least-important
      content and says so, exactly as `INDEX.md` does today
- [ ] `dsa ask --project rf-frontend "…"` returns the answer **labelled with
      the part it came from**, and a project-wide question hitting two parts
      returns both
- [ ] Adding a part that has no built corpus fails with a clear message naming
      the build command, rather than producing a half-index
- [ ] Removing a part rebuilds cleanly with no stale entries
- [ ] `dsa status` lists projects alongside parts
- [ ] A 3-part project is built in tests from the existing gate corpora and
      its index token count is recorded for the phase report

---

Source: `.scratch/agent-native-access/SPEC.md`
