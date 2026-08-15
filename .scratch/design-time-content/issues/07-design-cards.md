# 07 — Design cards (`cards/*.json` + `cards/*.md`)

**What to build:** Task-shaped views over records that already exist —
the datasheet reorganised around what someone needs open while drawing a
schematic. Four cards, each with a selector rule set:

| Card | Contents |
|---|---|
| `power` | rails: voltage min/typ/max, max current, total dissipation |
| `thermal` | RθJA, RθJC(top), ΨJT, ΨJB, TJ max, TA range, Tstg |
| `interface` | JESD204B/C support, lane count, max lane rate, SPI timing |
| `limits` | abs-max vs recommended-operating per parameter, with margin |

The `limits` card earns its keep alone: it joins the abs-max and
recommended-operating tables by alias-resolved symbol, computes margin only
where **both** sides parsed numerically, lists the pairs it could not compare,
and flags parameters where recommended-max equals abs-max — a genuine design
hazard that is invisible when the two tables are read pages apart.

CLI `dsa card --part X --card power`; MCP `get_card`.

**Blocked by:** 02 — Numeric layer; 04 — Pins

**Status:** ready-for-agent

- [ ] All four cards build for AFE7950 and AD9081
- [ ] **The invariant-8 test**: walking every `source` field on every card
      resolves to a real record and a printed page — no orphan values, no
      value without provenance. This is the phase's most important test.
- [ ] A part lacking a card's data emits an **honestly empty card** with a
      stated reason, never a fabricated or interpolated one — asserted with a
      part that has no interface section
- [ ] `limits` computes margin only where both sides parsed, and explicitly
      lists the uncomparable pairs
- [ ] `limits` flags at least one zero-margin parameter if one exists in the
      reference parts, hand-verified against the printed pages
- [ ] Rendered `cards/*.md` carry a `<!-- derived: card_version N -->` banner
      and a citation on every row
- [ ] Changing `DSA_CARD_VERSION` regenerates cards rather than leaving stale
      ones behind
- [ ] Selectors are lexicon-driven data, so a new rail-naming convention is a
      data change

---

Source: `.scratch/design-time-content/SPEC.md`
