# 04 — Errata cross-linking

**What to build:** Errata already join the index as `pdf_text` documents.
Linking them to what they invalidate is what turns "any known issues with this
part?" into a real answer.

`errata_links.json`: `{errata_item_id, text, page, targets: [{kind:
section|spec|pin|register, id, confidence, matched_on}]}`.

Matching is deterministic — printed section numbers, alias-resolved symbols,
table captions, register names, pin names — and every link records what it
matched on.

At publish, affected section files gain a warning banner linking to the errata
item, and answer packs whose supporting record is targeted carry the warning
inline.

**Blocked by:** — (independent; parallelisable with 01–03)

**Status:** ready-for-agent

- [ ] ≥1 errata item on a real document links to its target section or spec,
      hand-verified
- [ ] **Unlinked errata items are still published** under an explicit
      "unlinked errata" heading — asserted. An errata item the matcher could
      not place must never disappear; that is the worst possible silent
      failure in this ticket.
- [ ] Every link records `matched_on`, so a wrong link is diagnosable
- [ ] Affected section files carry a warning banner at publish
- [ ] An answer pack whose supporting record is targeted by an errata item
      carries the warning inline — asserted end to end
- [ ] A part with no errata document is unaffected (no empty file, no banner)
- [ ] Matching never uses fuzzy text similarity on prose — only structured
      identifiers — so a false link cannot be produced by coincidence

---

Source: `.scratch/reach-and-trust/SPEC.md`
