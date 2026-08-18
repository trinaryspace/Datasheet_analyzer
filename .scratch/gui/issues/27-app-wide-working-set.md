# 27 — The working set is app-wide, not a Library filter

**Owns:** `web/src/shell/workingSet.tsx`, `web/src/shell/index.ts`,
`web/src/routes/chat/ChatPane.tsx`, `web/src/routes/library/route.tsx`
(consume only), `tests/web/workingset.test.ts`

**Problem.** The project is chosen inside Library and known only to Library.
It should be the context every screen inherits.

**Build.** A `WorkingSetProvider` in the shell holding `{project, setProject}`,
persisted to `localStorage` and mirrored to the `?project=` search param so a
link carries it. Every screen reads it through `useWorkingSet()`.

**Chat, and ADR 0006.** The working set is a *fallback*, never an override:

1. Resolve the question as today.
2. Confident → use it. The project does not silently redirect a question that
   plainly names a part.
3. Not confident (ambiguous, or no match) **and** a working set is active →
   scope to the project instead of interrupting. This is not a guess: it is
   the context the user declared, and the chip shows it.
4. Not confident and no working set → ask, exactly as today.

The chip must render the project scope identically to a resolved one, and stay
editable. An answer whose scope is invisible is the thing ADR 0006 forbids.

- [ ] Choosing a project on one screen is visible on the others without a reload
- [ ] It survives a reload, and `?project=` in a pasted URL selects it
- [ ] A confident resolution wins over the active project
- [ ] An ambiguous question under an active project scopes to the project and asks nothing
- [ ] An ambiguous question with no project still asks, and issues no model request
- [ ] The chip shows the project scope and can be changed back to a part
