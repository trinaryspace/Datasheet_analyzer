# 21 — Documentation and hygiene

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `CONTEXT.md`
- `AGENTS.md`
- `README.md`
- `.gitignore`

**What to build:** Bring the written record level with the code the other
twenty tickets are producing. This runs in wave 1 because it touches no source
file and can therefore never conflict with an implementation ticket.

**`CONTEXT.md` — the open question.** **Job** still reads "build one part from
one PDF. The part number is the PDF's filename stem, uppercased." Both clauses
are now wrong: applicability means one job builds from one PDF but may
contribute to several parts, and ticket 02 takes the part number from the
document's text with the stem only as a fallback. Redefine it. Keep the entry
to the file's house style — one or two sentences, define what it *is*, and an
`_Avoid_` line. Do not add implementation detail; this is a glossary and
nothing else. `Batch` may need a matching touch since it is defined in terms of
jobs.

**`AGENTS.md`.** Add the GUI as a third adapter alongside the CLI and the MCP
server, and state the constraint that makes it one: it holds no retrieval
logic, no citation formatting and no JSON shapes of its own. Record the two
new hard rules this work established — `SourceDocument` must not change shape
because `RawDocument` is cached, and `pdf_layout.py` / `output_version` are not
touched by GUI work. Cross-reference ADRs 0005 and 0006.

**`README.md`.** A section covering install with the `web` extra, `dsa serve`,
and the analyze → review → ask → verify path. Keep the existing CLI-first
framing — the GUI is an addition, not a replacement, and the CLI remains the
thing the tests exercise.

**Hygiene.** `.env` is currently tracked in git. Add it to `.gitignore` and
leave a one-line note in the README's setup section that a tracked `.env` must
be removed from the index with `git rm --cached .env` — the removal itself is
the user's call, not this ticket's, since it rewrites their working state.

**Numbering slip.** `docs/adr/0003-vendor-neutral-layout-core.md` has the
heading `# 0002 — …`. Fix the heading to match its filename.

- [ ] `CONTEXT.md` **Job** no longer claims one part per PDF or a filename-stem part number
- [ ] The new **Job** entry matches the file's style: one or two sentences, an `_Avoid_` line, no implementation detail
- [ ] **Batch** is consistent with the new **Job**
- [ ] No other glossary entry is silently changed
- [ ] `AGENTS.md` names the GUI as a third thin adapter and states what it must not contain
- [ ] `AGENTS.md` records the `SourceDocument`-is-cached constraint and the do-not-touch-`pdf_layout` rule
- [ ] `AGENTS.md` cross-references ADR 0005 and ADR 0006
- [ ] `README.md` documents installing the `web` extra and running `dsa serve`
- [ ] `README.md` walks analyze → review → ask → verify in the user's words
- [ ] `.gitignore` ignores `.env`, `library/`, `sessions/` and `web/dist/`
- [ ] The README notes that a tracked `.env` needs `git rm --cached .env`
- [ ] The ADR 0003 heading matches its filename
- [ ] No file outside the `Owns` list is modified
