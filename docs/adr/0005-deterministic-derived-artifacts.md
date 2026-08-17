# ADR 0005 — Deterministic derived artifacts

**Status:** accepted (Phase 6, ticket 01)
**Date:** 2026-08-16
**Supersedes:** nothing. **Amends:** invariant 1 in `AGENTS.md` by adding a
sibling invariant that governs a category invariant 1 did not anticipate.

## Context

Invariant 1 says *"LLM writes indexes, never content. Corpus text is
verbatim-extracted."* Through Phase 5 that was sufficient, because every
artifact in the corpus was one of two things: text lifted verbatim from a
source document, or an `INDEX.md` description the LLM was explicitly licensed
to write.

Phase 6 introduces a third category that fits neither slot. A power card's
"max current for VDD1P8" is not lifted from any single place in the PDF — it
is *selected* from a spec record by a rule, and possibly *converted* from
`1350 mA` to `1.35 A`. A limits card's margin is *computed* from two records
on different pages. A pin's `type: ground` is a *classification*, not a quote.

These are useful precisely because they are not verbatim. They are also the
first place this repo could plausibly start lying: a selector that picks the
wrong record, a unit conversion that drops a factor of 1000, or a
classification that guesses `power` for a pin it does not understand would all
produce a confident, well-formatted, wrong answer with a valid-looking page
citation. That failure mode is worse than no card at all, because the citation
makes it *look* verified.

Three options were considered:

1. **Deterministic only** — derivation is pure code over existing records.
2. **LLM-assisted, verified** — a model proposes groupings and normalizations;
   every value is checked against a verbatim record before it lands.
3. **LLM-assisted, free-form** — cards may include model-written synthesis
   alongside cited values.

Option 3 was rejected outright: it breaks the traceability guarantee that is
this repo's entire value proposition. Option 2 is defensible and would cover
more edge cases sooner, but it makes builds non-deterministic (breaking the
content-hash cache invariant), requires a verification harness that is itself
substantial work, and — decisively — moves the failure mode from "a rule I can
read and fix" to "a model was confidently wrong in a way the verifier did not
anticipate."

## Decision

**A derived artifact may contain only:**

**(a)** values copied verbatim from a spec, table, or pin record;
**(b)** values computed from those by a documented pure function;
**(c)** structural labels drawn from a checked-in lexicon.

**Every derived field carries `source` (record id + page) and `derivation`
(the named rule that produced it). No model call may appear anywhere in the
derivation path.**

**A field that cannot be filled stays null and says so.** It is never
interpolated, never defaulted to a plausible value, and never quietly omitted
in a way that makes the artifact look complete.

Concretely, every derived value ships in a provenance envelope:

```json
{ "verbatim": "1350 mA", "value_si": 1.35, "unit_si": "A",
  "source": "specs.json#rec_412", "page": 21,
  "derivation": "parse_quantity+si_normalize", "confidence": "high" }
```

This becomes **invariant 8** in `AGENTS.md`.

### Consequences that follow from this, and are binding

- **Unparseable is a first-class outcome.** `parse_quantity("See Figure 7")`
  returns `None`, recorded as `parse_confidence: none`. Any consumer that
  sorts, compares, or computes margins must report its unparsed population
  explicitly ("3 of 47 rows could not be parsed, listed below") rather than
  silently excluding those rows from a decision.
- **Verbatim stays authoritative.** The numeric layer is strictly additive.
  No verbatim string is ever mutated, and where the two disagree the verbatim
  string is correct by definition.
- **An empty card is a valid card.** A part with no interface section gets an
  interface card that states it found nothing and why — not a fabricated one,
  and not a missing file that reads as "not yet built."
- **`card_version` participates in the publish cache key**, so changing a
  derivation rule regenerates cards rather than leaving stale ones behind.
- **Enforcement is a test, not a convention.** A test walks every `source`
  field on every card and asserts it resolves to a real record and a printed
  page. A card value with no resolvable provenance fails the build.

### As built (ticket 01)

The contract above lands as code before any derived artifact exists:

- `models.DerivedValue` is the envelope, field for field.
- `provenance.py` owns both ends of the round trip: `spec_record_id` mints the
  stable record ids (`rec_412`) that `structure/specs.py` stamps on every
  published spec record, `source_ref` spells the reference, and
  `resolve_source` walks it back to the record and its page through
  `CorpusIndex`. The `specs.json#rec_412` shorthand above is accepted and
  resolves whenever exactly one document of the part carries that record;
  derivation code writes the fully qualified
  `docs/<doc>/specs.json#rec_412`, because an ambiguous reference resolves to
  nothing rather than to a guess.
- `SPECS_SCHEMA_VERSION` moves to `3`, so a corpus published before record ids
  existed republishes once instead of serving unaddressable records.
- `config.CARD_VERSION` (`DSA_CARD_VERSION`) is stamped into `manifest.json`
  and read by `batch.skip_reason` — the publish-cache-key half of this ADR.

## Consequences

**Positive.** Every number a designer sees can be traced back to a printed
page by a mechanical check, not by trust. Builds stay deterministic, so the
extraction cache stays valid. When a card is wrong, the fix is a readable rule
and a regression test — not a prompt.

**Negative, accepted.** Coverage will be lower than an LLM-assisted approach
would give, especially early: parts whose tables use unusual header wording
will yield empty cards until a lexicon entry is added. This is the intended
trade — an empty card is honest, a wrong card is not. Lexicon growth is a data
change, which keeps the cost of closing those gaps low.

**Revisit if.** Lexicon maintenance becomes the dominant cost of onboarding a
new vendor, *and* a verification harness exists that can prove an LLM-proposed
derivation against verbatim records. Until both are true, this decision holds.

## Decided: a pin-count mismatch warns, and is recorded

Ticket 04 (pins) cross-checks the extracted pin count against a pin count
parsed from the package/ordering section. The question was whether a mismatch
should merely warn, or **reject** `pins.json` entirely the way a failed
reconstruction gate rejects a table.

The case for rejecting is that a partial pin table is exactly the "confident
but incomplete" failure this ADR exists to prevent: a designer who greps for a
pin, gets no hit, and concludes it does not exist has been misled. The case
for warning is that the stated pin count is itself parsed from prose and is
therefore no more reliable than the table it would suppress — rejecting on it
lets a bad count throw away a perfectly good pin table.

**Decision: warn, record the mismatch in the manifest, and surface it in
`dsa audit` (Phase 7).** A warning is only weaker than a rejection when it can
be ignored, and recording it in the manifest is what stops that: the mismatch
becomes a fact the corpus carries, auditable across every part at once,
instead of a line someone did or did not read in a build log. This keeps a
usable pin table available while making its uncertainty impossible to lose,
which is the same stance the per-record confidence grade already takes — the
`low` record is still returned, and it still says it is `low`.
