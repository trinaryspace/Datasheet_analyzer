# 20 — Library, labels and sessions screens

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `web/src/routes/library/**`
- `web/src/routes/sessions/**`
- `tests/web/library.test.ts`

**What to build:** Two screens that manage what has accumulated.

**Library.** Every document with its applicability, its labels, and the parts
it reaches. Applicability is editable through `ApplicabilityControl`, the
shared primitive ticket 16 owns — import it, do not write your own. Ticket 17
uses the same one on the review screen, and duplicating it means the two
screens validate differently within a month.

Labels are the only user-writable data in the whole application, so make them
feel it: add inline, remove with one action, autocomplete from labels already
in use. Filter the list by label and by part. A patch that widens applicability
to an unbuilt part is legal (ADR 0005) — show that part as unbuilt and surface
the `rebuild_needed` list the server returns as an offer, not a warning.

**Sessions.** Saved conversations, newest first, with title, scope and message
count. Open one to restore its transcript into the chat pane. Export offers
both formats the server emits: markdown for pasting into a design review, and
the golden-Q&A shape for dropping into `tests/fixtures/`. Label the second for
what it is — an engineer who has just verified an answer is one click from a
regression test, and will not find that unless it says so.

- [ ] The library lists every document with applicability, labels and reached parts
- [ ] Applicability edits persist through `PATCH /api/library/{hash}` and re-render
- [ ] Applicability editing imports `ApplicabilityControl` from the shell; no local copy exists
- [ ] Invalid applicability is blocked in the UI before it reaches the server
- [ ] Labels can be added and removed inline, with autocomplete from existing labels
- [ ] The list filters by label and by part
- [ ] Widening applicability to an unbuilt part succeeds and shows it as unbuilt
- [ ] `rebuild_needed` is surfaced as an offer with the affected parts named
- [ ] Sessions list newest first with title, scope and message count
- [ ] Opening a session restores its transcript into the chat pane
- [ ] Both export formats download, and the golden-Q&A option says what it is for
- [ ] Every screen has loading, empty and error states
- [ ] All calls go through `web/src/api/client.ts`
- [ ] Tests mock the client; no live backend
