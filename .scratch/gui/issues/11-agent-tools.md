# 11 — Agent tool functions

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/tools.py`
- `tests/unit/test_app_tools.py`

**What to build:** The nine callables the chat loop hands to the Anthropic
SDK's Tool Runner, mirroring the MCP tool list: `list_parts`, `list_projects`,
`get_index`, `search`, `find_spec`, `find_plots`, `read_section`, `get_figure`,
`ask`.

Every one is a **thin adapter over `retrieve/`** and holds no retrieval logic,
no citation formatting, and no JSON shapes of its own — results come from each
hit's own `as_dict()` and every citation from `Citation`. This is the same
constraint `mcp_server/server.py` enforces on itself with
`TestMcpServerIsFormatOnly`; write the equivalent test here. If you find
yourself computing a page range or building a label, you are in the wrong
module.

Do **not** import from `mcp_server/`. Its tool bodies cap responses at
`DSA_MCP_MAX_TOKENS` because their consumer is a model reading over a wire;
these have a different budget (`settings.chat_tool_max_tokens`) and a different
truncation story. Sharing them would mean threading a budget parameter through
everything to serve two consumers with opposed needs. The shared logic already
lives in `retrieve/` — that is the seam working as designed.

Scope handling: tools that take a scope receive an already-resolved
`Retriever` or `ProjectRetriever` injected by the caller, not a `part`/`project`
string pair. Resolution happened once, before the loop started (ticket 10), and
the agent must not be able to change scope mid-answer — the scope shown to the
user has to be the scope the answer came from.

`get_figure` returns the PNG bytes plus its media type so ticket 12 can build
an image content block. `read_section` and `ask` respect
`settings.chat_tool_max_tokens` and **always announce truncation** rather than
silently cutting.

- [ ] All nine tools exist with the signatures frozen in `00-contracts.md`
- [ ] Each returns data built from `retrieve/` result objects' own `as_dict()` — asserted by a format-only test mirroring `TestMcpServerIsFormatOnly`
- [ ] `app/tools.py` imports nothing from `mcp_server/`
- [ ] Part-only tools (`get_index`, `read_section`, `get_figure`) reject a `ProjectRetriever` with a clear error rather than an `AttributeError`
- [ ] A tool given a `ProjectRetriever` that supports it (`search`, `find_spec`, `find_plots`, `ask`) returns results spanning its member parts
- [ ] Truncation at `chat_tool_max_tokens` is announced in the payload, never silent
- [ ] `get_figure` returns bytes and a media type, and 404-equivalents return a structured error rather than raising
- [ ] `find_spec` results carry `confidence` and `matched_via` through unchanged
- [ ] Every citation in every payload comes from a `Citation` object
- [ ] No tool can change the scope it was given
- [ ] Tests build a synthetic corpus on disk and construct a real `Retriever` over it; no network, no live model
