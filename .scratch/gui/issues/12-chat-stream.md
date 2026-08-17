# 12 — Chat loop and token stream

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/chat.py`
- `src/datasheet_analyzer/app/routers/chat.py`
- `tests/unit/test_chat_stream.py`

**What to build:** The agentic loop. `POST /api/chat/{session_id}/message`
takes a question, resolves its scope, runs an Anthropic tool-use loop over
ticket 11's tools, and streams `ChatEvent`s back over SSE.
`POST /api/chat/resolve-scope` exposes ticket 10's resolver on its own so the
UI can show the scope chip before the user commits.

Use the SDK's **Tool Runner** (`client.beta.messages.tool_runner` with
`@beta_tool`), not a hand-written loop — the runner already handles the
request → execute → feed-back cycle, and its per-turn hook is where tool calls
are surfaced as events. Model is `settings.chat_model` (`claude-opus-5`),
`max_tokens` is `settings.chat_max_tokens`, and thinking is left at the
model's default — do not pass `thinking: {type: "disabled"}`, which on this
model can emit a tool call as plain text that silently never runs.

Two things must be true of every answer:

- **Scope is fixed before the first model call and cannot change.** Resolve
  once, emit a `scope` event, inject the resolved retriever into the tools, and
  keep it for the whole turn. An ambiguous resolution does not start a loop at
  all — emit the candidates and stop, so the UI can ask.
- **Citations are extracted structurally, not parsed out of prose.** They come
  from the `Citation` objects inside the tool results the runner executed, not
  from a regex over the model's text. A cited claim the model invented has no
  matching tool result and therefore no citation.

Event types: `scope` once at the start, `tool` when a tool is invoked (name and
a short human summary — this drives the "searching…" affordance), `token` for
each text delta, `citation` as each is collected, then `done` or `error`.
Prompt-cache the system prompt and the tool definitions; keep the volatile
question after the last breakpoint.

- [ ] A question with a confident scope emits `scope`, then `token`s, then `done`
- [ ] An ambiguous question emits `scope` carrying candidates and never calls the model
- [ ] The scope in the first event is the scope every tool call used
- [ ] Tool invocations emit a `tool` event before their results are fed back
- [ ] Citations come from tool-result `Citation` objects; a fabricated citation in the model's prose produces no `citation` event
- [ ] The completed exchange is appended to the session (both messages, with citations)
- [ ] A model error mid-stream emits `error` with a readable message and closes the stream cleanly
- [ ] A client disconnecting mid-stream cancels the loop rather than leaking a running request
- [ ] `stop_reason == "refusal"` is handled before reading content and surfaces as `error`, not a crash
- [ ] `thinking` is not disabled anywhere in the request path
- [ ] The system prompt and tool definitions sit before the last cache breakpoint; the question sits after it
- [ ] Tests use a fake Anthropic client that replays a scripted tool-use exchange; no network, no live model, no API key required
