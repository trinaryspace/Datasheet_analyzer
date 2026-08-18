# 0007 — Derived artifacts are deterministic, and every field traces to a page

Until phase 6 every byte in a part corpus was verbatim extraction output, and
invariant 1 could be stated in one line: *the LLM writes indexes, never
content*. Phase 6 breaks that symmetry deliberately. A pin table, a register
map, a power card and a cross-part comparison are all things the tool
**computes** — a multi-pin row expands into four records, a printed `1350 mA`
becomes `1.35 A`, an abs-max and a recommended-max printed nine pages apart
become one margin. None of that is verbatim, and all of it is exactly what a
designer needs. Leaving invariant 1 as written would forbid the phase; loosening
it to "derived data is fine" would license precisely the failure this tool
exists to avoid — a confident number nobody can check.

The resolution is to permit derivation and constrain it, as **invariant 8**:

> A derived artifact may contain only **(a)** values copied verbatim from a
> spec, table or pin record; **(b)** values computed from those by a documented
> pure function; **(c)** structural labels drawn from a checked-in lexicon.
> Every field carries `source` (record id + page) and `derivation` (the named
> rule that produced it). No model call may appear anywhere in the derivation
> path. A derived artifact that cannot fill a field leaves it null and says
> so — it never interpolates, and it never emits a plausible default.

Three mechanisms make that a property of the code rather than a promise in a
document. Every derived value ships in one envelope, `DerivedValue`, carrying
`verbatim`, `value_si`, `unit_si`, `source`, `page`, `derivation`, `confidence`
and — for the null case — `null_reason`. Every citable record carries a stable
id (`specs.json#rec_s4.5-t2-r13`) that is a pure function of its coordinates
inside its document, so a rebuild of identical input reproduces the same string
and a card written last week still points at the row it was written against.
And `derive/provenance.py` resolves any `source` back to its record and printed
page, so "every value on this card traces to a page" is asserted by walking the
card, not by reading it.

The clauses are drawn tightly on purpose. Clause (b)'s *pure* excludes I/O and
excludes wall-clock and random state, which is what makes a derived artifact
reproducible; its *documented* means the function has a name, and `derivation`
records that name, so a number that looks wrong leads to the rule that produced
it rather than to a search. Clause (c) exists because pin-type classification
and device-table header matching genuinely need world knowledge — `VSSA` is a
ground, `RθJA` is thermal — and the honest way to hold world knowledge is a
YAML file under `registry/` that a human can read, diff and correct, not a
model that produces a different answer each time it is asked. `unknown` is a
first-class output of every lexicon lookup.

The null rule is the clause that will be under the most pressure, because a
card with gaps looks unfinished and a card with plausible defaults looks
complete. A `—` in a printed table means the vendor did not characterize the
parameter; a card that renders `0` there has invented a specification. Nulls
therefore carry `null_reason`, which is the difference between "the datasheet
does not state a recommended maximum" and a field somebody forgot to fill.

**`card_version` participates in the publish cache key** for the same reason
schema versions already do. A derivation rule change alters a card's contents
without altering its shape, so nothing else on disk would notice; without the
key, a corpus would keep serving numbers that no longer follow from the rule
that is written down. `DSA_CARD_VERSION` is bumped in the commit that changes a
rule, and the batch skip gate regenerates.

## Alternatives rejected

**LLM-assisted, verified** — let a model propose a pin type or a bit range and
accept it only when a deterministic check agrees. Rejected because the check is
the hard part, not the proposal: a verifier strong enough to catch a wrong bit
range is strong enough to extract the bit range, at which point the model is
doing nothing the parser could not, non-reproducibly and at a cost per row.
Where verification is genuinely weak — is `VSSA` a ground? — the model's output
is unverifiable, so what would ship is a guess wearing a checkmark. It also
makes the corpus a function of a model version: two builds of the same PDF stop
being byte-identical, and every cache key in the system is quietly wrong.

**LLM free-form** — hand the model the section and let it write the card.
Rejected as the failure mode this whole tool is a reaction to. It produces
fluent, well-formatted, uncheckable output; its errors are indistinguishable
from its successes at a glance; and it fills gaps by construction, because a
plausible completion is what a language model is for. A power card that quietly
invents a rail current is worse than no power card, because the designer
believes it. It also cannot be run offline, cannot be regenerated identically,
and puts a model call in the path of every number a schematic gets built from.

**A vision fallback for pin tables that fail to parse** — kept out of scope for
the same reason: it is (a) and (b) replaced by a model on exactly the rows where
the deterministic path already admitted it could not read the page. An honest
rejection with a recorded reason is the better artifact, because it is
actionable — a rejection reason names a table shape somebody can teach the
parser.

## Consequences

Coverage is bounded by what a deterministic parser can read, and some parts
will produce no `pins.json` at all. That is a measured, reportable number
(`rejection_reasons` joins `extraction_stats`, and `dsa audit` in phase 7 reads
it) rather than a silent quality gradient, which is the trade this project has
made everywhere else. Cards for a sparse part come out mostly empty, and the
`unresolved` list makes that legible instead of embarrassing.

Hard to reverse: `source` and `derivation` are on every derived field on disk,
so relaxing the rule later means deciding what those strings mean on values
that no longer have them. Surprising without context: a reader who has seen the
GUI's chat agent will assume a model wrote the cards too, and this file is what
says it did not — the chat agent *reads* derived artifacts and cites them; it
never produces one.
