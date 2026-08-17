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

### As built (ticket 04)

`CorpusManifest.derived_warnings` is the recording place — a list, not a
pin-specific field, because the register summary and the design cards will
have the same kind of thing to say. `dsa status` prints it today; `dsa audit`
reads the same field in Phase 7.

`CARD_VERSION` moves to `2` with this ticket, which is the ADR's publish-cache-key
clause doing its job for the first time: `pins.json` is a new derived artifact
with a new derived field, and nothing else in the skip gate notices it — no
source byte changes, no extractor version bumps, and a *missing* `pins.json`
reads as current. Without the bump a part built one ticket earlier would skip
forever and keep reporting, through `pin_gap()`, that its datasheet prints no
pin table.

Two details the decision did not anticipate, both settled the same way:

- **The check runs even when nothing was published.** HMC520A states
  `24-terminal` and its printed pin table is rejected whole, so there is no
  `pins.json` for a count to disagree with — and "the package has 24 terminals
  and the corpus has none of them" is the most useful thing that part can say.
  It is recorded as a mismatch rather than as silence.
- **A stated count is read only from a hyphen-joined package descriptor**
  (`324-ball BGA`), and only when every such descriptor in the document
  agrees. A count parsed from prose may not suppress a table, and by the same
  reasoning a count parsed from *contradictory* prose may not raise a warning:
  AD9081's own table of contents prints "21 Pin Configuration and Function
  Descriptions", and LM741 prints `8-Pin CDIP` beside a revision-history
  `10-Pin CLGA`. Disagreement is treated as no evidence, not as a tie to
  break.

Measured: AD9081 states 324 balls and publishes 321 (three lost to a ball
range broken across two printed lines), which is the mismatch this section
exists for; it warns, it is in the manifest, and all 321 pins are served.

### As built (ticket 05)

`registers.json` is the second derived artifact, and it exercised three clauses
of this ADR that `pins.json` did not:

- **"A field that cannot be filled stays null and says so"**, twice over. TI's
  programmer's guides print no register-level *access* column at all — access
  is stated per bit field — so every LMX1204 register publishes `access: ""`
  rather than the `R/W` that would have been a plausible guess, and `dsa regs`
  prints `reset=?` for a register the document states no reset for. The absence
  is the reading, not a gap to close: composing a register's access out of its
  fields' is a bit-field question, which is ticket 06's shape.
- **"Any consumer that sorts or compares must report its unparsed population"**,
  applied to a non-numeric field. `RegisterSet.n_reset_stated` plus a manifest
  warning is how a caller listing reset values can say "18 of 35 registers
  state one" instead of quietly showing a shorter list.
- **`card_version` participates in the publish cache key** — moved to `3` here.
  A second new derived artifact is invisible to every other gate for the same
  reason the first was: no source byte changes and a missing `registers.json`
  reads as current.

One detail the decision did not anticipate. A derived value's `page` must be
the page the value was *printed* on, and the obvious source for it was wrong:
`pagemap.pin_table_pages` rewrites `TableBlock.page` by matching cell text, and
a register field table whose cells are `R`, `R/W`, `0x0` and `RESERVED` matches
half a register map (LMX1204's Table 1-25 pins to p.17 and is printed on p.19).
The reset value therefore cites the table *region*'s page, which pinning does
not rewrite, and cites nothing at all when the declaration was left in a bare
paragraph — 29 of 35 with an exact page, 6 with `page: null`. Invariant 3
already decided that trade: a citation is right, or it is absent.

### As built (ticket 06)

Register **bit fields** are the derived artifact this ADR was written for: a bit
range is not a quote, a driver is written against it, and a wrong one
misconfigures silicon without complaining. The ticket therefore carried explicit
permission to ship nothing. It shipped, and three clauses of this decision are
what made that defensible.

- **"A field that cannot be filled stays null and says so"**, taken all the way
  up to the artifact. A register whose field table cannot be read keeps its
  record with `fields: []` and a `fields_reason`; a register with no *printed*
  width to check its ranges against publishes no fields at all, because a field
  list nobody can check against a width is unverifiable. And the register-level
  `access` that ticket 05 left as `""` **stays** `""`: having read the fields,
  composing one out of `R`, `R/W` and `R` would be a derived value no page
  states.
- **"Any consumer that sorts or compares must report its unparsed population"**,
  as *coverage*. `unaccounted_bits` lists the bits of the register width that no
  field claims, and `RegisterSet.n_field_sets` plus a manifest warning says how
  many registers publish a set at all (measured: 28 of 35, in each of LMX1204's
  two documents). A field list that covers 12 of 16 bits says which four it does
  not.
- **"Enforcement is a test, not a convention"**, at its strongest form yet. The
  gate hand-verifies five registers field by field off the printed pages and then
  walks **every** published field of both documents, requiring the quartet the
  page prints — bit range, name, access, reset, in that order — to appear in that
  page's text. 232 fields, 232 hits. A range read off the wrong row cannot appear
  as a run of the printed page, so "no wrong bit ranges" is measured rather than
  asserted.

Two decisions the ADR implied and this ticket had to make explicit:

- **A refusal is per artifact, not per field.** A field set that overlaps or
  overflows is refused *whole*, including the fields that look fine. Measured:
  LMX1204's own R90 table prints `15:8` and then `15:0` — a typo in the
  document — and publishing either range would be a guess about which was meant.
- **A gap is not a refusal.** Bits no field claims are reported rather than
  refused, because the document may genuinely not name them and throwing away the
  fields it *does* name would remove verifiable information to punish an
  unverifiable absence.

`CARD_VERSION` moves to `4` (and `REGISTERS_SCHEMA_VERSION` to `2`), for the
third time and the same reason: two new derived values per register that no other
gate can see. The limits that came with the ship are recorded in
`KNOWN_SHORTCOMINGS.md`, including the one this ADR would otherwise hide — the
geometric bit-diagram route has no real document to gate it, because neither
reference document prints that shape.

### As built (ticket 07)

The **design cards** are the artifact this decision was written for: the "power
card's max current for VDD1P8" of the Context section, now a file. `cards/`
derives four of them (`power`, `thermal`, `interface`, `limits`) from published
records, and each clause above turned into a rule with a test.

- **(a), (b) and (c), named per field.** A copied cell records
  `copy_cell` — with `+parse_quantity+si_normalize` when the numeric layer could
  read it — and carries the printed unit inside `verbatim` (`"1350 mA"`, exactly
  the envelope this ADR sketched). A computed value records the function that
  produced it: `max_over_rows` (the largest current a rail is stated to draw, out
  of 16 printed operating configurations), `abs_max-recommended_max`, and
  `pins_by_name+count`. The lexicon label is the group a row is in, recorded as
  the row's `selector`, exactly as a pin publishes the phrase that typed it.
- **A computed value has no `verbatim`.** The envelope above shows a `verbatim`
  because it describes a *copied* value; a margin was printed on no page, so its
  `verbatim` stays empty and its number lives in `value_si` / `unit_si`,
  rendered `*(derived)*`. Filling that field with a rendered number would be a
  quotation of something no datasheet says.
- **One value, two operands.** A margin joins two records on two pages, so
  `DerivedValue` gains an additive `sources` beside `source`: the primary
  reference stays the row whose headroom it is, the rating it was measured
  against is cited beside it, and the invariant-8 walk resolves both. Citing one
  and dropping the other would make the value untraceable by exactly half.
- **"An empty card is a valid card"**, taken literally. A part with no interface
  section gets an interface card that names what it looked for and did not find,
  written like any other and recorded in `CorpusManifest.derived_warnings`
  (measured: LM741, an op-amp). Nothing about that file reads as "not yet built".
- **"Enforcement is a test, not a convention."** The invariant-8 walk runs on
  five real corpora: every `source` and every `sources` entry of every value of
  every card is resolved back through `provenance.resolve_source` to a record and
  a printed page, and the primary reference's page must be the page the card
  cites. 377 references, 0 unresolvable
  (`test_afe7950_build.py::TestDesignCardsOnTheReferenceCorpus`,
  `test_phase4_layout_gate.py::TestDesignCardsOnTheGateCorpora`).
- **"Any consumer that sorts or compares must report its unparsed population."**
  The two places a card does arithmetic — the `reduce: max` groups and the limits
  join — run `quantities.parse_population` and publish its sentence plus one line
  per row they could not read.

Two decisions this ticket had to make explicit, both refusals:

- **An ambiguous join is refused, not resolved.** AFE7950 prints three supply
  ratings on its absolute-maximum table and three rails on its recommended
  table, and the alias lexicon resolves all six to `VDD`. The only pairing the
  card will make is between two rows that share a printed identity cell
  *character for character* — a fact about the page, not an inference about it —
  and everything left over is listed as uncomparable with the counts. A margin
  computed between a 0.9 V rail and a 1.8 V rating would be worse than no margin,
  because it would look exactly like a good one.
- **A card selects by data, and one predicate had to be physical.** AD9081 prints
  its rails and its rail *currents* on two tables inside one section, and every
  row of both names `AVDD2`; no printed word separates them. `unit_bases` does:
  a rail is stated in volts and a current in amps, and `SI_UNITS` already knows
  which base a printed unit scales to. The same rule keeps AFE7950's *other*
  `TJ` — Total Jitter, in UI — off the thermal card.

`CARD_VERSION` moves to `5` and `SPECS_SCHEMA_VERSION` to `5`. The second bump is
the ticket's one schema change: a card selects rows by the *table* they were
printed on, and on the captionless era of datasheets every section number is
honestly `""`, so `SpecRecord` gains the printed `section_title`. Without it the
limits and power cards would be empty on exactly the parts that need them most.

### As built (ticket 09)

The **cross-part comparison** is the first derived artifact whose values come
from more than one corpus, and it forced this decision's one extension so far.

- **A reference must name everything needed to resolve it.** A comparison's
  delta cites one record in each of two parts, and `rec_1` exists in nearly every
  corpus — so `docs/<doc>/specs.json#rec_1` is walkable only by a caller who
  already knows which part it came from, which is not a round trip.
  `provenance.source_ref` therefore gained an **additive** part-qualified form,
  `parts/<PART>/docs/<doc>/specs.json#rec_412`; `parse_source` reads it, and
  `resolve_source` *refuses* a reference resolved against a different part rather
  than matching a same-numbered record there. A design card's references are
  unchanged — inside one corpus naming the part is noise — and a card comparison
  re-qualifies the values it inherits.
- **"A field that cannot be filled stays null and says so"**, applied to the one
  number this artifact adds. A delta exists only where both sides parsed the
  *same printed column* into the same SI base: a `typ` against a `max`, two
  different bases, and a printed range reduced to an endpoint are all refused
  with the reason, and both printed values are still published, still cited.
- **"Any consumer that compares must report its unparsed population."** Every
  comparison prints `quantities.parse_population`'s sentence per part, one line
  per row it could not read, and one line per pair it could not compare —
  under a heading a reader can find (`## Not comparable`).
- **An ambiguous join is refused, and here it is refused *per part*.** Ticket 07
  refuses a whole key; a comparison refuses only the part whose rows no shared
  printed name can pair, names it in `ambiguous_in`, quotes all of its rows, and
  lets the parts that *are* unambiguous compare. A third device's messy table may
  not erase a clean comparison between two others.
- **`only in A` is a row, not a silence** — during part selection an absent
  parameter is the answer — and its note says the other part "publishes no
  record", never "does not state": the artifact reports the corpus, and the
  difference is recorded in `KNOWN_SHORTCOMINGS.md`.

`CARD_VERSION` does **not** move for this ticket, and that is the point: a
comparison is never written to disk. It is a question about a *set* of parts,
and a corpus belongs to one, so there is no file for a cache key to invalidate —
`COMPARE_SCHEMA_VERSION` describes a payload shape instead. Enforcement is the
same test as ever, one noun wider: 327 references over 139 values in 8
comparisons, each resolved in the corpus its own reference names
(`test_phase4_layout_gate.py::TestCrossPartCompareOnTheGateCorpora`).
