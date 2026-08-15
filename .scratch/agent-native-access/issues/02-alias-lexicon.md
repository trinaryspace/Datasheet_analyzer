# 02 — Alias lexicon (designers' words → datasheets' symbols)

**What to build:** `registry/aliases.yaml` plus `structure/aliases.py`. A
checked-in data file mapping canonical symbol families to the phrases people
actually type, with an optional `expect_unit` disambiguator and
`prefix_match` for families (`IDD` → `IVDD1P8`, `IVDD1P2`, …). Adding a
synonym must be a YAML edit, never a code change — same philosophy as the
vendor brand lexicon.

Resolution ladder, first hit wins, winning rung reported to the caller as
`matched_via`: exact symbol → alias phrase → alias prefix family → name
substring (today's behaviour) → token-overlap fuzzy above a fixed threshold.

**Blocked by:** 01 — Retrieval core seam

**Status:** ready-for-agent

- [ ] `dsa query --part AFE7950 --name "junction temperature"` resolves to
      `TJ` and returns the same verbatim value and page as `--symbol TJ`
- [ ] Every hit reports which rung matched; `matched_via` appears in CLI and
      JSON output
- [ ] `expect_unit` breaks ties between equal-rung candidates and **never**
      suppresses a record whose unit is missing (asserted)
- [ ] Prefix families expand: an `IDD` query returns every `IVDD*` supply
      current record
- [ ] The lexicon is seeded from symbols present across the six built corpora;
      the seeding script or procedure is checked in so coverage is reproducible
- [ ] Alias hit rate across all six corpora's golden questions is measured and
      printed by the test, for the phase report
- [ ] A query matching nothing returns an explicit no-match with the nearest
      candidates, never a guess

---

Source: `.scratch/agent-native-access/SPEC.md`
