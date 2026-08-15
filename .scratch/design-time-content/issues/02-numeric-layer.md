# 02 — Normalized numeric layer (`parse_quantity`)

**What to build:** `structure/quantities.py` — the enabling primitive for
cards, comparison, margin checks, and revision diffs. Pure, no I/O, heavily
unit-tested.

`parse_quantity(text, unit_hint) -> Quantity | None`, with additive
`SpecRecord` fields `value_si`, `unit_si`, `value_kind`
(`point|range|bound|tolerance`), `parse_confidence`.

**Verbatim strings remain authoritative and are never mutated.** Returning
`None` is a first-class outcome, not a failure to fix.

**Blocked by:** 01 — Derived-artifact contract

**Status:** ready-for-agent

- [ ] A unit test per shape: plain (`105`), signed and unicode-minus (`−40`,
      `+85`), range (`−40 to +85`, `-40…125`), inequality (`< 5`, `≥ 1.8`),
      tolerance (`±0.5`), SI prefix (`1350 mA`, `12 GSPS`), scientific
      (`1.2e-9`)
- [ ] Unparseable inputs (`See Figure 7`, `Note 2`, `—`, empty) return `None`
      with `parse_confidence: none` — asserted per case
- [ ] Unit canonicalisation reuses `structure/units.py`, including **both ohm
      glyphs** (U+2126, U+03A9)
- [ ] No verbatim field is mutated anywhere — asserted by comparing every
      record's verbatim strings before and after the layer runs
- [ ] Parse rate across all six built corpora is measured and printed for the
      phase report, broken down by section
- [ ] A documented helper reports the unparsed population for any consumer
      that sorts or compares, so ticket 07 and 09 cannot silently drop rows

---

Source: `.scratch/design-time-content/SPEC.md`
