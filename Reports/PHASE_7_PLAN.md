# PHASE 7 PLAN — Reach & Trust

**Status: planned.** Execution contract for `.scratch/reach-and-trust/`.
Superseded on landing by `Reports/PHASE_7_REPORT.md`.

**Depends on Phases 5–6.** This is the breadth phase: after depth is proven on
a handful of parts, Phase 7 makes onboarding cheap, keeps corpora honest as
they multiply, and adds the family view that makes an agent an expert on a
*series* rather than a part.

**Scope decisions taken before writing**: document acquisition is a curated
URL registry (no scraping, no search API); depth-before-breadth means the
audit and golden-generation tooling lands here, when part count actually
grows.

## Why

Phases 5–6 produce an excellent corpus for parts you have already onboarded by
hand. Three things break as the count grows from six to sixty:

- **Onboarding is manual.** Every corpus begins with a human finding and
  downloading a PDF. The BOM → corpora path an agent should walk unattended
  stops at the first step.
- **Nothing knows whether a datasheet is current.** Revisions are parsed
  (`SBASA41E`, `Rev. I`) and then never questioned. Designing against a
  superseded datasheet is a real hardware failure mode, and right now the tool
  would answer such a question with full confidence and a valid page cite.
- **Quality is invisible to the consumer.** `extraction_stats` tells the
  *builder* how a corpus went. Nothing tells the *agent* whether to trust it
  before answering, and hand-verified goldens do not scale to sixty parts.

And one capability that only makes sense once several related parts exist:
a **family view**. AFE7950 and AFE7953 share 39 identically-named sections.
Loading both to answer "what is different between these?" is the wrong shape
for the question and for the token budget.

## Component specs

### 1. Document registry + `dsa fetch`

A checked-in registry, not a scraper. Deterministic, hermetically testable,
and legally uncomplicated.

```yaml
# registry/datasheets.yaml
AFE7950:
  vendor: ti
  doc_type: datasheet
  url: https://www.ti.com/lit/ds/sbasa41e/sbasa41e.pdf
  revision: SBASA41E
  sha256: 9f2c…            # recorded on first successful fetch
  retrieved_at: 2026-08-15
  companions:
    - {doc_type: register_map, url: "…", revision: "…"}
```

- `dsa fetch AFE7950` → resolve → download → **verify sha256 when known**.
  A mismatch is a loud warning naming the likely cause (a new revision
  upstream), not a silent overwrite. `--accept-new-revision` records the new
  hash and revision after the user looks.
- `dsa fetch --url <u> --part X [--doc-type …]` adds an entry for a part not
  yet in the registry, so the registry grows by use. An agent that finds a URL
  can call this itself — that is the intended growth path.
- A registry miss is an error that names the flag to fix it. No guessing, no
  fallback search.
- `dsa fetch --project rf-frontend` fetches everything a project needs that is
  not already present, which is the BOM → corpora path end to end.
- Tests reuse the existing `ReplayFetcher`; unrecorded URL remains a hard
  error per invariant #4.

### 2. Revision awareness

- Additive inventory fields: `revision_checked_at`, `upstream_revision`,
  `staleness` (`current | stale | unknown`).
- `dsa check-revisions [--part X | --all]` is an **explicit, opt-in, network**
  command — never part of `build`, so builds stay offline by construction. It
  re-fetches the registry URL's headers/document, parses the revision with the
  existing shared lexicon, and compares.
- Staleness is surfaced where it can actually change a decision:
  `dsa status`, a banner at the top of `INDEX.md`, the `dsa audit` scorecard,
  and — most importantly — **a footer line on every answer pack**:

  ```
  ⚠ This corpus is built from SBASA41E; SBASA41F is available upstream
    (checked 2026-08-15). Verify before committing to silicon.
  ```

  An agent that answers from a stale corpus without saying so is the single
  most dangerous behaviour this tool can have. This is the mitigation.

### 3. `dsa diff-rev`

Build two revisions of the same part side by side (`--rev` suffixes the
document directory so both coexist under one part), then diff:

- **Specs**: added / removed / changed, by alias-resolved symbol, showing both
  verbatim values, both pages, and — via the Phase 6 numeric layer — a
  human-readable delta ("TJ max 105 → 125 °C").
- **Sections**: added / removed / retitled / page-shifted.
- **Pins and registers**: added / removed / renamed / reset-value changed.
  This is the one designers most need and least expect to have to check.

Output: `parts/<PART>/REVISION_DIFF.md` plus `--json`. Changes that cannot be
compared numerically are listed verbatim under "review by hand" rather than
being scored.

### 4. Errata cross-linking

Errata already join the index as `pdf_text` documents. Linking them to what
they invalidate is what makes "any known issues with this part?" a real
answer.

- `errata_links.json`: `{errata_item_id, text, page, targets: [{kind:
  section|spec|pin|register, id, confidence, matched_on}]}`.
- Matching is **deterministic**: printed section numbers, symbol strings
  resolved through the alias lexicon, table captions, register names, pin
  names. Each link records what it matched on.
- **Unlinked errata items are still published**, under an explicit
  "unlinked errata" heading. An errata item that the matcher could not place
  must never disappear — that would be the worst possible silent failure.
- At publish, affected section files gain a warning banner linking to the
  errata item; answer packs whose supporting record is targeted by an errata
  item carry the warning inline.

### 5. `dsa audit` — corpus scorecard

Promotes builder-side statistics into a consumer-readable trust signal.

| Metric | Source |
|---|---|
| section page coverage | `sections_with_pages / n_sections` |
| table pin rate | tables with an exact page / total |
| table accept rate + mean fidelity | `extraction_stats` |
| spec page rate | specs with a page / total |
| record confidence mix | Phase 5 confidence enum |
| pins / registers / cards present | Phase 6 artifacts |
| axis coverage | plots with `axis_confidence: high` |
| alias hit rate | goldens resolving via the lexicon |
| revision freshness | Phase 7 staleness |
| golden pass rate | `dsa verify` |

Each metric is graded against a **checked-in rubric** (`registry/audit_rubric.yaml`)
into an overall A–F. `dsa audit --all` prints the fleet table; `--json` feeds
tooling; an MCP `get_audit(part)` tool lets an agent check trust *before*
answering and downgrade its own language accordingly:

> "This corpus grades C — table pin rate 61%. The value I found is `medium`
> confidence; confirm against printed p.47."

That sentence is the deliverable of this ticket.

### 6. Golden Q&A generation assist

Invariant #5 is the right objective function and it does not survive sixty
parts of hand-verification. The fix keeps the human in the loop but makes the
loop cheap.

- `dsa golden suggest --part X --n 20` templates candidate questions from
  records that already carry verbatim answers and pages — spec rows, pin rows,
  register rows, plot captions — **stratified** across sections, backends, and
  confidence grades so the set is not all easy lookups. Written to
  `tests/fixtures/golden_qa_<PART>.candidate.yaml` with `confirmed: false`.
- `dsa golden confirm --part X` walks candidates in bulk (accept / edit /
  reject), showing the printed page text alongside each so confirmation is a
  glance, then merges accepted items into the real golden file.
- **Unconfirmed candidates never count toward `dsa verify`.** The invariant is
  preserved exactly: a corpus is provably verified only against
  human-confirmed answers. The tooling reduces typing, never judgment.

### 7. Part families / series

- `registry/families.yaml` declares members **explicitly** (an auto-suggest
  helper proposes groupings by title and section-structure similarity, but a
  human confirms — silent family membership would be a correctness hazard).
- `dsa family build AFE795x` produces `families/AFE795x/FAMILY_INDEX.md`:
  - sections whose text is identical across members, listed **once**;
  - a **delta table** of every spec that differs, with each member's verbatim
    value and page;
  - pin and register deltas;
  - links into per-part sections only where they diverge.
- `dsa ask --family AFE795x "…"` answers from shared content once and flags
  per-member differences when the answer is not common.

This is the direct answer to "become an expert on a series of parts", and it
is a large token win: the shared 39 sections stop being loaded twice.

### 8. Scale gate

Breadth has to be demonstrated, not asserted:

- onboard **≥20 parts** through `dsa fetch` + `dsa batch`, across ≥3 vendors;
- one project of **≥8 parts** builds and answers project-scoped questions;
- one family of ≥2 members builds with a correct delta table;
- **every onboarded part grades ≥ B** on `dsa audit`, or carries a recorded
  shortcoming explaining why it cannot;
- generated-then-confirmed goldens cover every new part; `dsa verify` at 100%
  across the fleet;
- measured token numbers — per-part corpus, family index vs. two part indexes,
  answer-pack mean — recorded in `PHASE_7_REPORT.md`.

## Schema / CLI / versions

- Additive inventory fields (`revision_checked_at`, `upstream_revision`,
  `staleness`); new files `errata_links.json`, `REVISION_DIFF.md`,
  `families/<NAME>/FAMILY_INDEX.md`; new checked-in data
  `registry/datasheets.yaml`, `registry/families.yaml`,
  `registry/audit_rubric.yaml`.
- `PIPELINE_VERSION` 0.4.0 → **0.5.0**.
- New CLI: `fetch`, `check-revisions`, `diff-rev`, `audit`, `golden
  suggest|confirm`, `family`. New MCP tools: `get_audit`, `list_families`,
  `get_family_index`.
- New config: `DSA_REGISTRY_DIR` (default `registry`),
  `DSA_FAMILIES_DIR` (default `families`).

## Acceptance gate

1. `dsa fetch` resolves, downloads, hash-verifies, and registers a part from
   the registry; a hash mismatch produces the loud warning path, asserted in
   test against a recorded fixture.
2. A registry miss errors with a message naming `--url`.
3. `dsa check-revisions` detects a stale corpus against a recorded fixture,
   and the staleness banner appears in `INDEX.md`, `dsa status`, `dsa audit`,
   and the answer-pack footer — all four asserted.
4. `dsa diff-rev` between two revisions of one part reports spec, section,
   pin, and register deltas, verified against a hand-checked expectation.
5. Errata linking connects ≥1 errata item to its target section/spec on a real
   document, and an unlinked item is asserted to still appear in the output.
6. `dsa audit` grades all fleet parts; the rubric is data-driven (changing the
   YAML changes grades, asserted).
7. `dsa golden suggest` produces stratified candidates; an unconfirmed
   candidate is asserted **not** to affect `dsa verify`.
8. A family index builds with a correct delta table, and is measurably smaller
   than the sum of its members' indexes.
9. The scale gate above passes; `pytest` offline, `ruff` clean.

## Implementation order

| # | Ticket | Notes |
|---|---|---|
| 01 | Document registry + `dsa fetch` | Unblocks bulk onboarding |
| 02 | Revision awareness + staleness surfacing | The safety feature |
| 03 | `dsa diff-rev` | Needs 02 + the Phase 6 numeric layer |
| 04 | Errata cross-linking | Independent; parallelisable |
| 05 | `dsa audit` scorecard + rubric | Needs the fleet to be meaningful |
| 06 | Golden suggest/confirm | Needed before onboarding 20 parts is affordable |
| 07 | Families + delta index | Independent; the series capability |
| 08 | Scale gate + PHASE_7_REPORT | Closes the phase and the roadmap |

01 → 06 → 08 is the critical path: fetching makes onboarding possible, golden
generation makes it affordable, and the gate proves it happened.

## Docs / invariants to update on landing

- `AGENTS.md`: invariant #5 gains the "generated candidates never count until
  confirmed" clause; module map gains `registry/`, `families/`.
- `CONTEXT.md`: new nouns — **Family**, **Registry entry**, **Staleness**,
  **Audit grade**.
- `README.md`: fetch/audit/family usage; the fleet table replaces the
  hand-maintained reference-parts table.

## Out of scope (kept out, recorded)

- **Scraping vendor portals or search-API resolution.** The registry grows by
  explicit `--url` entries. Revisit only if curation becomes the bottleneck,
  and then as a separate spec with its own legal review.
- **Automatic family detection without confirmation.** Suggested, never
  assumed.
- **Hosted/shared corpora, HTTP MCP, multi-user auth.** Still local-only.
- **Numeric comparison as a correctness claim.** `diff-rev` and `audit`
  report deltas and grades; neither asserts a part is *suitable* for a design.
  The tool informs the designer; it does not sign off.
