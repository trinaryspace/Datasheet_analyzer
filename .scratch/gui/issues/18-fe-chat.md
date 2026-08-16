# 18 — Chat pane

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `web/src/routes/chat/**`
- `tests/web/chat.test.ts`

**What to build:** The left pane. A question box, a streaming transcript, and
the two affordances that make the design work: the scope chip and clickable
citations.

**The scope chip is not decoration.** ADR 0006 permits auto-resolution *because*
the resolved scope is visible and editable — that is the whole argument. It
renders attached to the answer, shows the Part or Project the answer came from,
and opens a picker on click. Changing it re-asks the same question under the
new scope rather than starting a fresh thread.

When resolution is ambiguous the server sends candidates and never calls the
model. Render that as a question with the candidates as choices — not as an
error, and not as a spinner that resolves into a guess.

**Citations are the handoff.** Each renders inline as `§4.5, p.7` and clicking
it drives the PDF pane (ticket 19) through the shared route state, not through
a direct import — the two panes must stay independently testable. A citation
carrying `confidence: "low"` renders its badge next to it, because low
confidence is precisely the case where the user should open the page.

Streaming: render `token` events as they arrive; show `tool` events as a
transient "searching specs…" line that clears when text starts, so a
twelve-second lookup is legible rather than blank. Stop generating on demand.
An `error` event renders in place with the message and leaves the transcript
intact.

- [ ] A question streams tokens into the transcript as they arrive
- [ ] The scope chip shows the resolved Part or Project and opens a picker on click
- [ ] Changing scope re-asks the same question under the new scope
- [ ] An ambiguous resolution renders candidates as choices and issues no model request
- [ ] Tool activity shows while running and clears when text begins
- [ ] Citations render as `§4.5, p.7` and are keyboard-activatable
- [ ] Clicking a citation updates shared route state; the chat pane does not import the PDF pane
- [ ] A `low` confidence answer renders its badge beside the citation
- [ ] Stop cancels the in-flight request and leaves partial text in place
- [ ] An `error` event renders inline and preserves the transcript
- [ ] The transcript restores from a saved session on load
- [ ] Long transcripts stay scroll-anchored to the newest token without fighting a user who scrolls up
- [ ] Tests drive a mocked SSE stream; no live backend, no live model
