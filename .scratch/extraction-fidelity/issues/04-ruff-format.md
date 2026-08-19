# 04 — `ruff format` has never been run

**What to build:** One mechanical formatting commit, and a gate so it cannot
regress.

**Measured on the merge tree:** `ruff format --check .` reports **81 files
would be reformatted, 237 already formatted**. The repo's standing gate has
always been `ruff check` at line length 100; the formatter was never adopted.
All 27 Phase 6 modules are already format-clean, so the debt is entirely
historical.

Breakdown, because it changes what this ticket should do:

| Files | Where |
|---|---|
| 36 | `tests/unit/` |
| 35 | `src/datasheet_analyzer/` |
| 6 | `tests/integration/` |
| 2 | `tests/conftest.py`, `scripts/seed_aliases.py` |
| **2** | **`Reports/PHASE_2_PLAN.md`, `Reports/PHASE_3_PLAN.md`** |

**Those last two are the finding.** ruff 0.16 formats Python code blocks inside
Markdown, and both plan documents illustrate a model with hand-aligned comment
columns:

```
    verbatim: str          # "Ω" (U+2126), "dBc/Hz", "" when unitless
```

The formatter collapses that alignment. These are **archived records of what
was planned**, not source — `Reports/` is where a phase's history lives, and
reformatting history to satisfy a source-code gate is the wrong trade.

**Fix, in this order and as separate commits so `git blame` stays readable:**

1. Add `Reports` to `[tool.ruff] extend-exclude`, with a comment giving the
   reason above. Decide `docs/` too — it holds the ADRs; state your call.
2. `ruff format .` — **no logic change of any kind** in this commit.
3. Add `ruff format --check` to the standing gate wherever `ruff check` is
   already named (`AGENTS.md`, and CI if it exists).

Run the full suite between 2 and 3 and compare pass counts to the pre-commit
number. A formatter should change no test outcome; if one moves, that is a
finding worth more than this ticket.

**Blocked by:** **a quiet working tree.** Not by another ticket.

**Status:** blocked — partially landed

Step 1 landed with wave 0 (`Reports` excluded, reason recorded in
`pyproject.toml`). Steps 2 and 3 did **not** run, and the reason is the point:

At the moment wave 0 reached this ticket, a second agent was editing the same
working tree — `app/contracts.py`, `app/routers/projects.py`, `projects/shelf.py`,
`tests/unit/test_projects_api.py`, the whole of `web/`, and a new untracked
`app/sectiontext.py`, all touched within the preceding 40 minutes. The count
had moved from 81 files to 84 while wave 0 was running.

`ruff format .` is repo-wide. Running it then would have rewritten another
agent's half-finished work and folded a mechanical reformat into their feature
diff — destroying the one property that makes this ticket worth doing as its
own commit. **Run it when the tree has one writer**, then re-measure: the
81/84 figures above are already stale.

- [x] `Reports` excluded, with the reason written down
- [ ] `ruff format --check .` clean
- [ ] The formatting commit contains **only** formatting — verify with
      `git diff --stat` and by reading a sample of the largest hunks
- [ ] Test count before and after recorded and **identical**
- [ ] `ruff format --check` added to the documented gate
- [ ] Neither `Reports/PHASE_2_PLAN.md` nor `Reports/PHASE_3_PLAN.md` modified

**Owns:** `pyproject.toml`, `AGENTS.md`, and every file the formatter rewrites

---

Source: `.scratch/extraction-fidelity/SPEC.md`
