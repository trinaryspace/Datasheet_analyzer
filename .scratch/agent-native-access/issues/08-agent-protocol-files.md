# 08 — Corpus agent protocol (`AGENT.md` + skill)

**What to build:** Promote the retrieval discipline from prose inside
`INDEX.md` (and, in practice, from someone's prompt) into artifacts that ship
with the data.

- `parts/<PART>/AGENT.md` and `projects/<NAME>/AGENT.md`, emitted at publish:
  index first, never bulk-read, prefer `ask`, always quote units, always cite
  `p.N`, check the confidence grade, fall back to the printed page when `low`.
- `.claude/skills/datasheet-corpus/SKILL.md` in-repo, so any Claude Code agent
  in this workspace adopts the protocol without being told.

**Blocked by:** 07 — MCP server (the protocol should describe the finished
surface, including the MCP tools)

**Status:** ready-for-agent

- [ ] `AGENT.md` is emitted for every part and project at publish, and is
      itself small enough to load freely (budget recorded)
- [ ] It documents both access paths — CLI and MCP — with a worked example of
      each
- [ ] It states the confidence-and-fallback rule explicitly, including when to
      tell the designer to open the printed page
- [ ] The in-repo skill is discoverable by name and its instructions match
      `AGENT.md` (a test asserts the shared rule text does not drift)
- [ ] `INDEX.md`'s "How to use this corpus" section is reduced to a pointer,
      not duplicated prose

---

Source: `.scratch/agent-native-access/SPEC.md`
