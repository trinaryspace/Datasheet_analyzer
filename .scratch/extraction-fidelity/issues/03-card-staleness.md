# 03 — A published card is not invalidated when its document moves

**What to build:** A card cache key that notices the corpus underneath it
changed shape.

**Measured:** `load_card` calls a card current when `schema_version` matches
`CARDS_SCHEMA_VERSION` and `card_version` matches `DSA_CARD_VERSION`. Neither
changes when a document is republished to a different root. A card's `source`
strings are built from `_ref_base(...)`, which returns `docs/<doc>` for a
part-local document and `@library/docs/<doc>` for one in the shared store — so
republishing flips every citation the card holds while both version fields stay
equal. A card built before AD9081's move kept citing `docs/datasheet-a15af6a3/…`
afterwards: **87 of 87 filled values on the power card resolved to no record.**

`audit_card` caught it and the gate failed loudly. That is the system working —
serving the stale card silently would have been the failure. What is missing is
the *invalidation*, so the failure is a cache miss instead of a red gate.

**Fix:** fold the resolved document set into the card. Add a `corpus_key` to
`Card` — a short digest over the `(doc name, ref_base)` pairs `load_card_corpus`
resolved, computed by a documented pure function — and have `load_card` return
`None` when the recomputed key differs. Bump `CARDS_SCHEMA_VERSION` so existing
cards regenerate rather than failing to validate.

Two things to get right, and they are the whole ticket:

- **Recomputing the key must be much cheaper than building the card**, or this
  trades a stale card for a slow one. `CorpusIndex.load` reads a manifest;
  building a card reads every `specs.json`. Measure both and put the numbers in
  the report.
- **The key must be stable across a rebuild of identical input** — same
  ordering, no absolute paths, no timestamps — or every card is permanently
  stale and `load_or_build_card` rebuilds on every call.

**Blocked by:** —

**Status:** done

- [x] `Card.corpus_key` populated at build; documented as a cache key, not as
      data a reader should interpret
- [x] `load_card` returns `None` when the key differs, alongside the existing
      schema/version checks
- [x] `publish.cards_current` agrees with `load_card` — one staleness rule, not
      two that can disagree (the batch skip gate reads that function)
- [x] Test: build a card, move its document part-local <-> `@library`, reload —
      it rebuilds, and `audit_card` reports **0 problems** afterwards
- [x] Test: rebuild with identical input twice — the key is byte-identical
- [x] `CARDS_SCHEMA_VERSION` bumped; the constant's test updated
- [x] Recompute cost measured against build cost and recorded

**Owns:** `src/datasheet_analyzer/derive/cards.py`,
`src/datasheet_analyzer/publish/writer.py` (`cards_current` only),
`src/datasheet_analyzer/models.py` (the `Card` model only),
`src/datasheet_analyzer/config.py` (`CARDS_SCHEMA_VERSION` only),
`tests/unit/test_cards.py`

---

Source: `.scratch/extraction-fidelity/SPEC.md`
