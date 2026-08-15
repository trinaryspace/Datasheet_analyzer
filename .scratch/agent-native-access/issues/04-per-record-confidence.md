# 04 — Per-record confidence

**What to build:** An additive `confidence` enum (`high|medium|low`) on
`SpecRecord` and `PlotRecord`, computed at structure time and rendered in
every answer path. `extraction_stats` already grades a *document*; answers
need the grade per *record*.

The rule, documented in code and in `AGENTS.md`:

| Grade | Rule |
|---|---|
| `high` | table pinned to an exact page **and** reconstruction gate passed first try **and** the row's value cells are non-empty |
| `medium` | page is section-range only, **or** a min/typ/max cell is empty |
| `low` | grid rescued by the retry ladder, **or** unit missing where the alias lexicon expected one |

This is what lets an agent say "`low` confidence — open p.47" instead of
asserting a shaky number.

**Blocked by:** 02 — Alias lexicon (the `expect_unit` input to the `low` rule)

**Status:** ready-for-agent

- [ ] `confidence` present on every spec and plot record; schema change is
      additive and older corpora load without it (default documented)
- [ ] Each of the three grades is produced by a targeted test fixture — a
      pinned clean row, a section-range row, and a retry-ladder-rescued row
- [ ] The grade appears in `dsa query` / `dsa plots` output and in JSON
- [ ] Per-part confidence mix (counts by grade) is written to manifest stats
      and printed by `dsa status`
- [ ] The mix for all six built parts is recorded for the phase report
- [ ] No existing golden answer changes value or page as a result

---

Source: `.scratch/agent-native-access/SPEC.md`
