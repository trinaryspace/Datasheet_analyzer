# 07 — MCP server (`dsa serve --mcp`, local stdio)

**What to build:** A local stdio MCP server over the retrieval core, so the
corpus is usable from Claude Code, Claude Desktop, or Cursor without a
terminal. No HTTP, no auth, no multi-tenancy — scope decision recorded in the
SPEC.

Tools: `list_parts`, `list_projects`, `get_index`, `search`, `find_spec`,
`read_section`, `find_plots`, `get_figure`, `ask`.
Resources: `dsa://part/<PART>/INDEX.md`, `dsa://project/<NAME>/PROJECT_INDEX.md`.

`get_figure` returns the PNG as an **image content block** — that is what
makes the plot catalog pay off: narrow with `find_plots`, receive the one
image, present it to the designer.

Dependency: the official `mcp` Python SDK as an optional extra
(`pip install -e ".[mcp]"`) so the core install stays lean.

**Blocked by:** 05 — Answer packs; 06 — Projects

**Status:** ready-for-agent

- [ ] Every tool is exercised **in-process over the SDK's memory transport** —
      no subprocess, no port, hermetic per invariant #4
- [ ] Every tool response carries citations and confidence; responses validate
      against their declared schemas
- [ ] `DSA_MCP_MAX_TOKENS` (default 6000) caps every response; exceeding it
      truncates **with a visible notice naming the flag** — asserted
- [ ] `get_figure` returns a valid image content block for a real figure from
      a built corpus, and a clear error for a path outside the part directory
      (no path traversal)
- [ ] Both resources resolve and return the index text
- [ ] The server starts with zero built parts and reports an empty list rather
      than failing
- [ ] A README snippet shows the `mcp.json` registration and is verified by
      hand once against a real client (recorded in the phase report)
- [ ] Core install without the `[mcp]` extra still works; `dsa serve --mcp`
      without it errors with an install hint

---

Source: `.scratch/agent-native-access/SPEC.md`
