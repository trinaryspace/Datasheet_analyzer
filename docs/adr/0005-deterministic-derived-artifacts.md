# ADR 0005 — Deterministic derived artifacts

**Status:** proposed (drafted for review before Phase 6 ticket 01 lands)
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

## Open question for the repo owner

Ticket 04 (pins) proposes a package cross-check: compare the extracted pin
count against a pin count parsed from the package/ordering section, and warn
on mismatch. That warning is honest, but a *warning* is weaker than this ADR's
usual stance. Should a pin-count mismatch instead **reject** `pins.json`
entirely, the way a failed reconstruction gate rejects a table?

Argument for rejecting: a partial pin table is exactly the "confident but
incomplete" failure this ADR exists to prevent, and a designer who greps for a
pin and gets no hit may conclude it does not exist.

Argument for warning: pin counts are parsed from prose and are themselves
unreliable, so a bad count could suppress a perfectly good pin table.

**Recommendation: warn, but record the mismatch in the manifest and surface it
in `dsa audit` (Phase 7), so it cannot be ignored at scale.** Flagged here
rather than decided unilaterally, because it trades completeness against
caution and that is the repo owner's call.
