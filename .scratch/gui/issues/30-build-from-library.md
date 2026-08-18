# 30 — Build an unbuilt part where you meet it

**Owns:** `web/src/routes/library/PartGroupRow.tsx`,
`web/src/routes/library/route.tsx`, `tests/web/library.test.ts`

**Problem.** The Library says "QPA1003P — unbuilt" and refuses to add it to a
project, then offers no way to fix it. The user goes back to Analyze and
retypes a path to build a part the Library is already pointing at.

**Build.** An unbuilt part row offers **Build this part**. Its documents carry
`path`, `part_number` and `applicability`, which is a `DocProposal` — so this
starts an ordinary run through `POST /api/analyze/start`. No new endpoint.

Progress belongs where progress already lives: hand off to the Analyze
screen's run view rather than growing a second progress UI here.

- [ ] An unbuilt part offers to build; a built one does not
- [ ] Building sends one proposal per document reaching that part, applicability intact
- [ ] The user lands on the run view, and the run id is in the URL
- [ ] A document whose file has moved reports the recorded path rather than failing silently
