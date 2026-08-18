# 04 — Layout & assembly card

**What to build:** A Phase 6-style design card for the questions asked *after*
schematic capture, when the board is being laid out and built: package type
and pin count, thermal pad presence and dimensions, the datasheet's stated
via and thermal guidance, moisture sensitivity level, peak reflow temperature,
ESD ratings.

Verbatim strings, page citations, `null` where the datasheet is silent. This
is a surfacing ticket, not an inference ticket.

**Blocked by:** — (independent; feeds rule `missing-decoupling` in 03)

**Status:** ready-for-agent

- [ ] `dsa card <PART> --layout` emits the layout/assembly card; the field
      group is **additive** to the existing card schema
- [ ] Every populated field carries `source` (record id + page) and
      `derivation`, exactly as invariant 8 requires
- [ ] A field the datasheet does not state is `null` **and says why** — never
      interpolated, never defaulted, never omitted
- [ ] The card populates from at least two real corpora in this repo and each
      populated value is spot-checked against the printed page in the ticket's
      test or its report notes
- [ ] Decoupling requirements, where the datasheet states them, are extracted
      in a form rule `missing-decoupling` can consume
- [ ] MCP `get_layout_card(part)` exposes it
- [ ] Card definitions stay in the existing checked-in `registry/cards.yaml`
      idiom rather than a new mechanism
- [ ] No model call in the derivation path (invariant 8)

---

Source: `.scratch/design-loop/SPEC.md`
