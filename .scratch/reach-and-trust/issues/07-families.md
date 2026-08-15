# 07 — Part families / series

**What to build:** The direct answer to "become an expert on a *series* of
parts". AFE7950 and AFE7953 share 39 identically-named sections; loading both
to ask "what is different?" is the wrong shape for the question and for the
token budget.

- `registry/families.yaml` declares members **explicitly**. An auto-suggest
  helper proposes groupings by title and section-structure similarity, but a
  human confirms — silent family membership would be a correctness hazard.
- `dsa family build AFE795x` → `families/AFE795x/FAMILY_INDEX.md`:
  sections whose text is identical across members listed **once**; a delta
  table of every spec that differs with each member's verbatim value and page;
  pin and register deltas; links into per-part sections only where they
  diverge.
- `dsa ask --family AFE795x "…"` answers from shared content once and flags
  per-member differences when the answer is not common.

**Blocked by:** — (independent; parallelisable)

**Status:** ready-for-agent

- [ ] A family of AFE7950 + AFE7953 builds with a correct delta table,
      hand-verified against both printed datasheets
- [ ] Shared sections are listed once; a section that differs by even one
      value appears in the delta table rather than the shared list
- [ ] `FAMILY_INDEX.md` is **measurably smaller** than the sum of its members'
      indexes; the ratio is recorded for the phase report
- [ ] Membership is explicit; the auto-suggest helper only proposes and its
      output requires confirmation — asserted that an unconfirmed suggestion
      builds nothing
- [ ] `dsa ask --family` returns a shared answer once, and flags per-member
      divergence when the answer is not common — both paths asserted
- [ ] Pin and register deltas included where those artifacts exist
- [ ] A family whose members have differing section structures degrades
      honestly (more deltas, fewer shared) rather than mis-aligning sections

---

Source: `.scratch/reach-and-trust/SPEC.md`
