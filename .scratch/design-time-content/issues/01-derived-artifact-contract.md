# 01 — Derived-artifact contract (ADR 0005 + provenance envelope)

**What to build:** The contract every later ticket in this phase conforms to,
written before any derived artifact exists.

`docs/adr/0005-deterministic-derived-artifacts.md` and a new **invariant 8**
in `AGENTS.md`:

> A derived artifact may contain only (a) values copied verbatim from a spec,
> table, or pin record; (b) values computed from those by a documented pure
> function; (c) structural labels from a checked-in lexicon. Every field
> carries `source` (record id + page) and `derivation` (the named rule). No
> model call may appear in the derivation path. A field that cannot be filled
> stays null and says so — never interpolated, never a plausible default.

Plus the shared `DerivedValue` model (the provenance envelope) and stable
record ids that `source` can point at.

**Blocked by:** —

**Status:** ready-for-agent

- [ ] ADR written, with the rejected alternatives (LLM-assisted-verified,
      LLM-free-form) recorded and the reason for rejecting them
- [ ] Invariant 8 added to `AGENTS.md`
- [ ] `DerivedValue` model: `verbatim`, `value_si`, `unit_si`, `source`,
      `page`, `derivation`, `confidence`
- [ ] Stable, addressable record ids exist on spec records (`specs.json#rec_412`
      style) and are asserted stable across a rebuild of identical input
- [ ] A reusable test helper resolves any `source` string back to its record
      and page — later tickets use it for the invariant-8 test
- [ ] `DSA_CARD_VERSION` defined and wired into the publish cache key

---

Source: `.scratch/design-time-content/SPEC.md`
