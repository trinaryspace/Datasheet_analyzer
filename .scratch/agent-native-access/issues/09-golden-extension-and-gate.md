# 09 — Golden extension + phase-5 gate

**What to build:** The proof of the phase's claim — *"a designer's question,
in a designer's words, returns a cited answer inside a budget"* — plus the
docs that close it.

Each of the six parts' golden sets gains an **ask-path** question (natural
language, no symbols) and a **search-path** question (top-1 hit must be the
section holding the hand-verified answer). Both must land on the same verbatim
answer and the same page as the existing symbol-path question, so the new
surface is proven against the *existing* objective function rather than a new
one.

**Blocked by:** 07 — MCP server; 08 — Agent protocol files

**Status:** ready-for-agent

- [ ] Every existing golden question for all six parts still passes at 100%
- [ ] Ask-path and search-path questions added per part; `dsa verify` runs
      them and hard-fails on a missing set, as it does today
- [ ] A 3-part project builds and a project-scoped `ask` returns the right
      part, in the gate
- [ ] Budget compliance asserted numerically across the whole golden set
- [ ] MCP tools exercised in the gate, in-process
- [ ] `pytest` fully offline; `ruff` clean on `src` and `tests`
- [ ] `AGENTS.md` updated: `retrieve/` and `registry/aliases.yaml` in the
      module map, the "no retrieval logic in front ends" seam in conventions
- [ ] `CONTEXT.md` gains **Project**, **Answer pack**, **Alias**,
      **Confidence**
- [ ] `README.md` gains MCP setup plus `ask` / `search` / `project` usage
- [ ] `Reports/PHASE_5_REPORT.md` written with measured numbers: alias hit
      rate, search top-1 accuracy, mean answer-pack tokens vs. today's
      multi-call cost, per-part confidence mix, search-index size ratio
- [ ] `PHASE_5_PLAN.md` marked superseded by the report

---

Source: `.scratch/agent-native-access/SPEC.md`
