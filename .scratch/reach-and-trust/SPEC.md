---
title: Reach & trust — fetch, revisions, errata links, audit, golden assist, families
labels: [ready-for-agent]
---

**Execution contract:** `Reports/PHASE_7_PLAN.md`. This file is the tracker
root. **Depends on Phases 5–6.** This is the breadth phase: depth is proven
first, then onboarding becomes cheap, corpora stay honest as they multiply,
and the family view makes an agent an expert on a *series*.

## Problem Statement

Phases 5–6 produce an excellent corpus for parts already onboarded by hand.
Three things break as the count grows from six to sixty. Onboarding is
manual — every corpus starts with a human finding and downloading a PDF, so
the BOM → corpora path an agent should walk unattended stops at step one.
Nothing knows whether a datasheet is current: revisions are parsed and then
never questioned, so the tool would answer from a superseded document with
full confidence and a valid page cite. And quality is invisible to the
consumer — `extraction_stats` tells the *builder* how a build went, while
nothing tells the *agent* whether to trust a corpus before answering, and
hand-verified goldens do not scale to sixty parts.

Separately, one capability only becomes meaningful once several related parts
exist: AFE7950 and AFE7953 share 39 identically-named sections, and loading
both to ask "what is different?" is the wrong shape for the question and for
the budget.

## Solution

A checked-in document registry makes `dsa fetch` deterministic and hermetic
without scraping. Revision awareness turns a parsed string into an active
staleness warning that reaches the designer inside the answer itself.
`dsa diff-rev` shows what changed between revisions, down to pins and register
reset values. Errata get cross-linked to what they invalidate. `dsa audit`
promotes builder statistics into a consumer-readable grade an agent checks
before answering. Golden generation keeps the human judgment and removes the
typing. And family indexes answer series-level questions once instead of per
member.

## User Stories

1. As an agent handed a BOM, I want `dsa fetch --project rf-frontend` to
   download every missing datasheet and build every corpus, so BOM → corpora
   needs no human.
2. As a maintainer, I want a fetch whose sha256 disagrees with the registry to
   warn loudly and stop, so a silently-changed upstream document can never
   overwrite a verified corpus.
3. As a maintainer, I want a registry miss to name the flag that fixes it, so
   coverage grows by use rather than by guesswork.
4. As a designer, I want an answer drawn from a superseded datasheet to **say
   so in the answer**, so I never commit to silicon on a stale number. This is
   the most important story in the phase.
5. As a designer, I want `dsa diff-rev` to tell me what changed between two
   revisions — specs, sections, pins, register reset values — so a datasheet
   update is a review, not a re-read.
6. As a designer, I want "any known issues with this part?" answered from
   errata linked to the specific section or spec they affect.
7. As a maintainer, I want an errata item the matcher could not place to still
   appear under "unlinked errata", so nothing is ever silently dropped.
8. As an agent, I want `get_audit(part)` before I answer, so I can downgrade
   my own language when a corpus grades poorly instead of asserting a shaky
   number confidently.
9. As a maintainer onboarding twenty parts, I want candidate goldens generated
   from records that already carry verbatim answers and pages, stratified
   across sections and confidence grades, so confirmation is a glance.
10. As a maintainer, I want unconfirmed candidates to never count toward
    `dsa verify`, so invariant #5 survives the tooling that makes it
    affordable.
11. As a designer working with a series, I want a family index that lists
    shared sections once and tabulates only the differences, so "what is
    different between the AFE7950 and AFE7953?" is one small read.
12. As a maintainer, I want family membership declared explicitly (suggested,
    never assumed), so a wrong grouping cannot silently mix two parts' data.
13. As a maintainer, I want the breadth claim proven by a gate — twenty parts,
    three vendors, an eight-part project, every part graded — so scale is
    measured rather than asserted.

## Implementation Decisions

Full detail in `Reports/PHASE_7_PLAN.md`. The load-bearing ones:

- **A curated registry, not a scraper.** `registry/datasheets.yaml` holds
  part → vendor, url, revision, sha256, retrieved_at, plus companions.
  `dsa fetch --url` grows it by use; a miss errors and names the flag. No
  search API, no portal scraping, no guessing.
- **Revision checking is an explicit, opt-in, network command.** Never part of
  `build` — builds stay offline by construction. Staleness surfaces in
  `dsa status`, the `INDEX.md` banner, the audit scorecard, and **the answer
  pack footer**, which is the one that actually protects a design decision.
- **Errata matching is deterministic** (section numbers, alias-resolved
  symbols, table captions, register and pin names), each link recording what
  it matched on. Unlinked items are published, never dropped.
- **The audit rubric is checked-in data** (`registry/audit_rubric.yaml`), so
  grading thresholds are reviewable and changing them is a data change.
- **Golden generation templates questions from records that already carry
  verbatim answers and pages**, stratified across sections, backends, and
  confidence grades so the set is not all easy lookups. Human confirmation is
  mandatory and unconfirmed candidates are inert.
- **Family membership is explicit**, with an auto-suggest helper that proposes
  groupings by title and section-structure similarity for a human to confirm.

## Testing Decisions

- Fetch and revision checks are tested through the existing `ReplayFetcher`;
  an unrecorded URL remains a hard error per invariant #4. The hash-mismatch
  path is asserted against a recorded fixture.
- The staleness banner is asserted in **all four** surfaces (`INDEX.md`,
  `dsa status`, `dsa audit`, answer-pack footer) — a warning that appears in
  only three of them is the failure mode worth testing for.
- An unconfirmed golden candidate is asserted **not** to affect `dsa verify`.
- The audit rubric's data-driven nature is asserted by changing the YAML in a
  test and observing the grade change.
- The scale gate is a real integration run: ≥20 parts, ≥3 vendors, an ≥8-part
  project, a family, all graded ≥ B or carrying a recorded shortcoming.

## Out of Scope

- Scraping vendor portals or resolving datasheets through a search API. The
  registry grows by explicit `--url` entries; revisit only if curation becomes
  the bottleneck, and then as its own spec with a legal review.
- Automatic family detection without human confirmation.
- Hosted or shared corpora, HTTP MCP transport, multi-user auth — still local.
- Any claim of design *suitability*. `diff-rev` and `audit` report deltas and
  grades; neither signs off on a part for a design.

## Further Notes

- Critical path is 01 → 06 → 08: fetching makes onboarding possible, golden
  generation makes it affordable, the gate proves it happened.
- Tickets 04 (errata) and 07 (families) are independent and parallelisable.
- Ticket 02 is the phase's safety feature. If the phase has to be cut short,
  it is the one to keep.
