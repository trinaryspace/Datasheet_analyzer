# 17 — Analyze and review screens

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `web/src/routes/analyze/**`
- `tests/web/analyze.test.ts`

**What to build:** Three screens in sequence: point at a directory, review what
was inferred, watch it build.

**Pick.** A path input with a recent-directories list. There is no native
directory picker available to a browser that yields a server-usable path, so
this is a typed or pasted path validated by `POST /api/analyze/scan` — say so
in the UI rather than showing a file button that cannot work.

**Review.** One row per PDF: filename, inferred part number, inferred
applicability, and the evidence for both. Every inferred value is editable in
place, and the evidence is what makes editing possible — a user cannot judge
`AFE79xx` without seeing the line it came from, so show it, not a confidence
score. Applicability is edited through `ApplicabilityControl`, the shared primitive
ticket 16 owns — import it, do not write your own. Ticket 20 uses the same one
on the library screen, and it already blocks an empty parts list or a blank
family before the value can reach the 400.

Sort rows so anything needing attention floats: unresolved applicability first,
then documents matching more than one part, then the confident singles. Forty
rows where thirty-eight are obviously right should take one glance.

**Progress.** A row per job with its live state from the SSE stream. A part
reaching `DONE` gets an "Ask about this" affordance immediately — the run does
not have to finish. Failures show their error inline and do not block the rest.
Reconnect transparently after a stream drop; the server sends a snapshot on
connect, so a reconnected client re-renders rather than showing a gap.

- [ ] A valid directory scans and advances to review; an invalid one shows the server's message inline
- [ ] Every proposal renders its part number, applicability and evidence
- [ ] Part number and applicability are editable, and edits post verbatim to `/api/analyze/start`
- [ ] Applicability editing imports `ApplicabilityControl` from the shell; no local copy exists
- [ ] Rows needing attention sort above confident ones
- [ ] Progress reflects live SSE state per job
- [ ] A part reaching `DONE` offers "Ask about this" while other jobs still run
- [ ] A failed job shows its error inline and the rest keep going
- [ ] A dropped stream reconnects and re-renders from the snapshot without a gap
- [ ] Every screen has a loading, empty and error state
- [ ] All server calls go through `web/src/api/client.ts`; no hand-built fetch
- [ ] Tests mock the client and the SSE stream; no live backend
