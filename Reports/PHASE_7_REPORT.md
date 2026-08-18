# PHASE 7 REPORT — Reach & Trust

**Status: in progress.** Execution contract: `Reports/PHASE_7_PLAN.md`.
Network-requiring steps this phase could not run are listed, per ticket, in
`Reports/PHASE_7_LIVE_RUN.md` — read that beside this file, because several
criteria here are *implemented and tested* rather than *live-confirmed*, and
the distinction is the point of invariant 7.

---

## Ticket 01 — Document registry + `dsa fetch`

**Landed.** `pytest` 1707 passed / 1 skipped (baseline 1663 + 44 new);
`ruff check src tests` clean.

### What shipped

| Piece | Where |
|---|---|
| The registry as data | `src/datasheet_analyzer/registry/datasheets.yaml` (generated) |
| The registry as code | `src/datasheet_analyzer/acquire/registry.py` |
| `dsa fetch` | `src/datasheet_analyzer/acquire/fetch.py`, CLI `_cmd_fetch` |
| The seed generator | `scripts/seed_datasheet_registry.py` |
| `DSA_REGISTRY_DIR` | `config.Settings.registry_dir` (`None` = the packaged dir) |
| Tests | `tests/unit/test_fetch.py` (44) |

The download seam is the **existing** `BinaryFetcher` protocol in
`extract/http.py` (`CachingBinaryFetcher` in production,
`ReplayBinaryFetcher` in tests). No second replay mechanism was introduced,
and nothing in `acquire/fetch.py` opens a socket itself.

### The seeded registry, and what every field in it actually is

Seven parts, eight documents — every one of them physically in this repo, and
every `sha256` computed from those bytes by the generator rather than
remembered:

| Part | Vendor | Revision | Hashed from | URL |
|---|---|---|---|---|
| AFE7950 | ti | SBASA41E | `afe7950.pdf` | derived `ti_lit_ds(SBASA41E)`, unverified |
| AFE7953 | ti | SBASAN1A | `afe7953.pdf` | derived `ti_lit_ds(SBASAN1A)`, unverified |
| LM741 | ti | SNOSC25D | `lm741.pdf` | derived `ti_lit_ds(SNOSC25D)`, unverified |
| LMX1204 | ti | SNAS800B | `tests/fixtures/pdf/lmx1204.pdf` | derived `ti_lit_ds(SNAS800B)`, unverified |
| LMX1204 (register map) | ti | SNAU269A | `tests/fixtures/pdf/LMX1204_registermap.pdf` | **null**, reason recorded |
| AD9081 | adi | Rev. 0 | `ad9081.pdf` | **null**, reason recorded |
| HMC520A | adi | Rev. A | `hmc520a.pdf` | **null**, reason recorded |
| QPA1003P | qorvo | Rev. I | `QPA1003P.pdf` | **null**, reason recorded |

Three decisions produced that table, and all three are refusals:

- **A derived URL is a hypothesis, and says so.** The only literature-path
  pattern this repo carries is `https://www.ti.com/lit/ds/<lit>/<lit>.pdf`
  (present in `Reports/PHASE_7_PLAN.md`; the document-viewer pattern in
  `extract/ti_html.py` is the same family). It was applied *only* where a
  literature number was **parsed out of the PDF's own first pages** by an
  anchored, closed-series regex, and every result ships `url_verified: false`
  with the rule recorded in `url_derivation`. A live fetch is the only thing
  that may flip that flag.
- **A null URL with a reason is the growth path, not a gap.** No adi or qorvo
  document-URL pattern exists anywhere in this repo, and TI's *user guide*
  path is not encoded here either — so SNAU269A gets no URL rather than a
  plausible `lit/ug/…`. `dsa fetch` reads the recorded reason back and names
  `--url`.
- **A hash records where it came from.** `sha256_origin: local_file:<path>`
  says this hash is the local copy's, which is a different claim from
  `fetch:<url>`. That distinction is what lets the mismatch warning be honest
  (below).

The literature-number regex is deliberately a **closed list of series codes**
with word boundaries. An open `[A-Z]{4}…` pattern reads LMX1204's page-1
`SYSREFOUT0` as a literature number — which is, incidentally, exactly what the
existing `sniff_revision` does for that document (see Open items).

### The mismatch warning names a cause it can support

The ticket asked the warning to name "the likely cause (a new upstream
revision)". Mid-run the repo owner measured, with network, that this is often
the *wrong* cause: TI regenerates a datasheet's "PACKAGE MATERIALS
INFORMATION" addendum with the current date on every download, so the bytes
change daily while the revision identifier does not (LM741 upstream p.15 reads
`10-Aug-2026` against `15-Jul-2025` locally; only LMX1204 hashed identically).

`mismatch_cause` therefore decides from the **parsed revision**, not the hash:

| Recorded rev | Downloaded rev | What the warning says |
|---|---|---|
| `Rev. A` | `Rev. B` | `NEW UPSTREAM REVISION` |
| `Rev. A` | `Rev. A` | `NOT evidence of a new revision` — bytes moved, identifier did not; names the regenerated-addendum case |
| `""` or unparsed | either | `nothing here says whether the revision moved` |

Both the refusal and the `--accept-new-revision` acceptance message use the
same three-way vocabulary, so accepting a regenerated document never records
it as a new revision. Ticket 02 owns staleness itself; this ticket only
refuses to overstate. Asserted by
`TestHashMismatch::test_an_unchanged_revision_is_never_reported_as_a_new_one`,
`…_accepting_an_unchanged_revision_says_the_revision_did_not_move`, and
`…_an_unknown_recorded_revision_asserts_nothing`.

### Criteria

| Criterion | Status | Evidence |
|---|---|---|
| `dsa fetch PART` resolves, downloads, verifies sha256, registers, ready for `dsa build` | met | `TestFetchHappyPath::test_fetch_verifies_registers_and_is_ready_to_build` — the test **runs `build_part` on the fetched file** and asserts `INDEX.md` exists, so "ready to build" is measured |
| A sha256 mismatch warns loudly and stops, naming the likely cause; `--accept-new-revision` records the new hash and revision | met | `TestHashMismatch` (6 tests): nothing written, nothing registered, registry byte-identical afterwards; acceptance records the hash **and** the revision the bytes report |
| A registry miss errors naming `--url`, never guesses, never searches | met | `TestRegistryMiss` (4 tests), incl. `test_miss_never_invents_a_url` asserting the message contains no URL at all |
| `--url` writes a well-formed entry with the fetched revision and hash | met | `TestUrlGrowsTheRegistry` (3 tests); a failed `--url` fetch leaves **no** half-written entry |
| `dsa fetch --project X` fetches only what is missing and reports skips | met | `TestFetchProject` (2 tests); an unknown part is reported, not fatal — the other parts still arrive |
| All tests run through `ReplayFetcher`; an unrecorded URL is a hard error | met | `TestHermeticFetchSeam::test_an_unrecorded_url_is_a_hard_error` |
| Registry entries for the six existing parts are seeded, non-empty | met | `TestSeedRegistry` (6 tests) — seven parts, and **every recorded sha256 is re-hashed against the file it names** |

Two criteria are met by *mechanism*, not by a live confirmation, and that is
recorded rather than papered over: the four derived TI URLs have never been
fetched by this tool, so they ship unverified, and `dsa fetch` reports them as
unconfirmed. `Reports/PHASE_7_LIVE_RUN.md` L1–L2 are the owner's steps.

### Two properties worth naming

- **Builds acquire nothing.** `dsa fetch` is the only command that may reach
  the network for a *document*.
  `TestBuildAcquiresNothing::test_the_pipeline_never_reaches_the_fetch_module`
  asserts `pipeline.py` does not reference the fetch module at all, and a
  second test asserts importing `datasheet_analyzer.acquire` does not pull the
  fetch seam in. Both would fail if a later ticket wired acquisition into
  `build` as a convenience.
- **Bytes are validated before anything is written.** A URL that answers with
  an HTML "document not found" page is the likeliest failure of a fetch by
  URL, so `readable_pdf_error` opens the payload **in memory** first; only then
  is it staged, registered, and atomically renamed into place. A mismatch
  deletes the staging file. Net effect: a part directory never holds a file
  that is not a readable PDF, even transiently.

### Open items carried forward

- **`sniff_revision` misreads `lmx1204.pdf` as `SYSREFOUT0`.** Its
  `_TI_DOC_ID` pattern (`\bS[A-Z]{2}[A-Z0-9]*\d[A-Z0-9]*\b`) matches any
  capitalised S-word containing a digit. The seed generator side-steps it with
  a closed series list, so the registry records `SNAS800B` correctly — but a
  `dsa fetch LMX1204 --accept-new-revision` would write `SYSREFOUT0` into the
  entry, because acceptance records what `register_source` sniffed. Fixing
  `_TI_DOC_ID` touches the shared revision lexicon and every part's recorded
  revision, so it is left to ticket 02, which owns revision awareness.
- **Seed hashes vs fetched hashes.** Once L1/L2 run, the checked-in registry
  carries facts the seed script cannot recompute offline, and
  `test_the_checked_in_file_is_what_the_seed_script_renders` will fail by
  design. `PHASE_7_LIVE_RUN.md` L1 records the two ways to resolve that and
  leaves the choice to whoever runs the live step.
- **`registry/datasheets.yaml` lives inside the package**, beside the four
  existing lexicons, and is therefore written in place under an editable
  install. `DSA_REGISTRY_DIR` is the escape hatch for a non-editable install
  (and is what the tests use); no automatic fallback was added, because a
  registry that silently wrote somewhere else would be worse than one that
  fails a permission check.

---

## Ticket 02 — Revision awareness + staleness surfacing

**Landed.** `pytest` 1759 passed / 1 skipped (1707 + 52 new); `ruff check src tests` clean.

### What shipped

| Piece | Where |
|---|---|
| The three-state model | `models.Staleness` + six additive `SourceDocument` fields |
| The vocabulary, one reading rendered four ways | `src/datasheet_analyzer/staleness.py` |
| `dsa check-revisions` | `src/datasheet_analyzer/acquire/revisions.py`, CLI `_cmd_check_revisions` |
| The fixed revision parser | `extract/pdf_structure.py` (`_TI_DOC_ID`, `revision_from_texts`, `sniff_revision_bytes`) |
| An **uncached** download seam | `extract/http.DirectBinaryFetcher` |
| `INDEX.md` banner | `enrich/index.build_index_markdown(staleness_banner=…)` + `staleness.apply_index_banner` |
| `dsa status` line | `cli._part_vendor_info` → `staleness.status_lines` |
| The `dsa audit` metric | `staleness.audit_metric` (ticket 05 renders it) |
| The answer-pack footer | `retrieve/pack.py` — `AnswerPack.staleness` / `.staleness_note`, in the reserved tail |
| MCP | `staleness` enum on every response envelope; per-part state in `list_parts` |
| Tests | `tests/unit/test_revisions.py` (52) |

### The blocking prerequisite: the revision parser was wrong for LMX1204

The old shape was `\bS[A-Z]{2}[A-Z0-9]*\d[A-Z0-9]*\b` and `sniff_revision`
takes the **first** match on the page. On `lmx1204.pdf` page 1 the matches are,
in print order, `SYSREFOUT0 SYSREFOUT1 SYSREFOUT2 SYSREFOUT3 SNAS800B` — so a
pin name won and the literature number came last. A revision-first staleness
comparison built on that would have been confidently wrong for that part.

The new shape is `\bS[A-Z]{3}([A-Z0-9]{2,3})[A-Z]\b` with a **digit required in
the middle group**. Three constraints, each doing work:

| Constraint | Keeps out |
|---|---|
| four leading letters + 2–3 alphanumerics (7–8 chars total) | `SYSREFOUT0` (ten characters) |
| a digit in the tail | `SUPPORT` (the measured AD9081 p.1 trap) |
| a final **letter** — the revision letter every literature number ends in | `SYSREF1`, `SYSREF10` |

Deliberately *not* "take the last match", which the ticket warned against: that
fixes LMX1204 by accident of print order and breaks the first document whose
page 1 cites another literature number after its own.

Measured against all eight documents committed to this repo — the regression
guard is `TestRevisionParser::test_every_committed_document_still_reads_its_revision`,
parametrized over every one of them:

| Document | Before | After |
|---|---|---|
| `tests/fixtures/pdf/lmx1204.pdf` | **`SYSREFOUT0`** | **`SNAS800B`** |
| `tests/fixtures/pdf/LMX1204_registermap.pdf` | `SNAU269A` | `SNAU269A` |
| `tests/fixtures/pdf/lm741.pdf` | `SNOSC25D` | `SNOSC25D` |
| `tests/fixtures/pdf/ad9081.pdf` | `Rev. 0` | `Rev. 0` |
| `tests/fixtures/pdf/hmc520a.pdf` | `Rev. A` | `Rev. A` |
| `tests/fixtures/pdf/QPA1003P.pdf` | `Rev. I` | `Rev. I` |
| `afe7950.pdf` | `SBASA41E` | `SBASA41E` |
| `afe7953.pdf` | `SBASAN1A` | `SBASAN1A` |

`registry/datasheets.yaml` is byte-identical afterwards (the seed script reads
its own closed series list and only falls back to `sniff_revision` for the
non-TI parts, whose readings did not move), so
`TestSeedRegistry::test_the_checked_in_file_is_what_the_seed_script_renders`
still passes unchanged. Ticket 01's open item is closed.

Note `SBASAN1A` carries only **one** digit, which is why the rule is "a digit"
rather than the more tempting "at least two digits" — a stricter numeric rule
would have silently cost AFE7953 its revision.

### Staleness is decided by the revision identifier, never by a hash

`compare()` is the whole decision, and it is four statements:

| Upstream vs built revision | State | Extra |
|---|---|---|
| different | `stale` | both revisions and the check date recorded |
| same, bytes differ | `current` | `content_drift: true`, worded *regenerated, not revised* |
| same, bytes identical | `current` | — |
| either side unreadable | `unknown` | the reason, verbatim |

The middle row is the one the ticket's measurement demanded: TI regenerates a
datasheet's package-materials addendum with the current date on every download,
so an unchanged revision's bytes differ daily.
`TestComparisonIsRevisionFirst::test_a_hash_difference_under_one_revision_is_not_stale`
asserts the state, and
`…_content_drift_is_worded_so_it_cannot_read_as_a_new_revision` asserts the
message contains none of `new revision`, `available upstream`, `superseded` —
a wording test, because the failure mode here is a true state with a sentence
that reads like a different one.

### `unknown` is the default, and it is not `current`

Every corpus in this repo currently reads `unknown`, because nothing has been
checked — this run had no network. That is the honest state and it is loud:
`INDEX.md`, `dsa status`, the audit metric and every answer pack all say
"Revision not checked" and name `dsa check-revisions`.
`TestUnknownIsNotCurrent::test_the_footer_says_not_checked_rather_than_implying_currency`
asserts the footer contains "not checked" and does **not** contain "current".

### The four surfaces

| Surface | Rendering | Test |
|---|---|---|
| `INDEX.md` | marker-delimited blockquote **above the title** | `TestTheFourSurfaces::test_index_md_carries_the_banner` |
| `dsa status` | `revision: stale — ⚠ …` per part | `…::test_dsa_status_reports_it` |
| `dsa audit` | `staleness.audit_metric()` — `state`, `grade_input`, `banner` | `…::test_the_audit_metric_carries_it` |
| answer pack | footer in the **reserved tail** | `…::test_the_answer_pack_footer_carries_it` |

Plus `…::test_all_four_surfaces_at_once`, which builds one stale corpus and
asserts the upstream revision appears in all four texts, reporting *which* ones
are missing it — the "present in only three" catcher the plan asked for. And
`…::test_an_unchecked_corpus_says_so_on_every_surface`, its `unknown` twin.

The `INDEX.md` banner is written at build time from the inventory (no network)
and refreshed **in place** by the check via `apply_index_banner`, which is why
it is marker-delimited: applying a new reading replaces the block rather than
stacking warnings, asserted by `TestTheBannerBlock`.

**On `dsa audit`.** The command itself is ticket 05. What landed here is the
field it consumes and the metric function that renders it — published in
`staleness.py` beside the other three renderings so the audit command will
format a reading it did not compute, the same rule the CLI follows for every
number it prints. The criterion is therefore met as *the field exists,
carries the banner, and is asserted*; it is not met as *a `dsa audit` command
exists*, and that distinction is recorded here rather than glossed.

### The footer is reserved tail, and its length scales with the danger

`AnswerPack.staleness_note` is set on the **frame** in `_draft` /
`_project_draft`, so `_fit` pays for it before it considers the first
discretionary row: a budget can cost extra rows and excerpt prose, never the
warning. `TestTheFooterIsReservedTail` asserts the stale wording survives at
budgets of 20, 60, 200 and 3000 tokens.

That makes the footer's *cost* a real design constraint, because every pack
pays it on every call. Measured on the `test_ask` fixture, the pack's citation
floor (header + first answer row + verify footer + notice) is 74 tokens; the
first draft of the footer added **67** — nearly doubling it, and pushing the
floor above the 100-token budget an existing test exercises. `pack_footer` is
therefore terser than the other three renderings, and terser the less dangerous
the finding is:

| State | Footer | Tokens |
|---|---|---|
| `stale` | `⚠ Built from SBASA41E; SBASA41F is available upstream (checked …). Verify before committing to silicon.` | ~27 |
| `unknown` | `⚠ Revision not checked — run \`dsa check-revisions\`.` | 13 |
| `current` | `✓ Revision current: SBASA41E, checked 2026-08-15.` | ~12 |

`unknown` is the state of every unchecked corpus, so it is the one paid for on
essentially every call; `stale` is rare and is the one that changes a decision,
so it carries the plan's full sentence. The full reasoning for every state is
still one `dsa status` away, and the other three surfaces are not budgeted.

The same reasoning shrank the MCP envelope field. It began as the full
seven-key reading, which cost ~114 tokens on **every** response and pushed two
existing cap tests (`read_section` at a 170-token cap, `find_plots` at 300) over
their limits — the response cap is a product promise, so the field had to fit
inside it rather than the other way round. It is now a **bare enum**: a remote
agent needs the *state* on whatever call it makes, and the sentence is already
where it is looking — `get_index` returns an `INDEX.md` whose first block is the
banner, `ask` returns a pack whose reserved tail is the footer, `list_parts`
shows the state per corpus. The server's `instructions` string explains the
enum once, including that `unknown` does not mean current.

### Honest degradation with no network

`check_part` never raises for a bad fetch, and a check that cannot complete
**writes no state**: the recorded `staleness`, `revision_checked_at` and
`upstream_revision` are left exactly as they were, and only
`revision_check_note` is updated with the reason. Two tests hold that line:

- `test_no_network_degrades_honestly_and_never_upgrades_a_stale_corpus` —
  a corpus pinned `stale`, then a fetcher that raises `OSError`: the state is
  still `stale`, the upstream revision is still recorded, the note says the
  recorded state is unchanged, and `report.ok` is `False`;
- `test_an_unknown_corpus_stays_unknown_when_the_check_fails`.

`test_an_unrecorded_url_is_a_hard_error_in_tests` keeps invariant 4 visible in
this module too: the replay seam refuses rather than reaching the network.

The download seam is `DirectBinaryFetcher`, added for this ticket and
deliberately **uncached**. `CachingBinaryFetcher` would have answered "what does
upstream say now" out of `.cache/http-bin`, reporting a previous run's bytes as
today's upstream — a freshness check served from a cache is not a freshness
check.

### Builds stay offline

Two guards, both shaped like ticket 01's:
`TestBuildChecksNothing::test_the_pipeline_never_reaches_the_revision_check`
asserts `pipeline.py` does not reference `acquire.revisions`, `check_part` or
`check_all`; `test_importing_the_acquire_package_does_not_pull_in_the_check`
asserts the import graph. And
`test_a_build_leaves_the_corpus_unknown_even_with_a_registry_url` measures the
behaviour rather than the source: a build over a registry that *does* carry a
URL still leaves `staleness: unknown`, `revision_checked_at: None`.

One consequence worth stating: `CorpusIndex`'s cache identity gained
`sources.json`'s mtime and size. `dsa check-revisions` rewrites the inventory
*without* rebuilding, and a key that watched only `manifest.json` would keep
serving a staleness reading that predates the check that had just run.

### Criteria

| Criterion | Status | Evidence |
|---|---|---|
| `sniff_revision` returns `SNAS800B` for `lmx1204.pdf`, other six documents unchanged | met | `TestRevisionParser` (all eight committed documents, parametrized) |
| Staleness decided by the parsed revision, never by a hash alone | met | `TestComparisonIsRevisionFirst::test_a_hash_difference_under_one_revision_is_not_stale` |
| A hash difference under an unchanged revision is reported distinctly | met | `…_content_drift_is_worded_so_it_cannot_read_as_a_new_revision`; `content_drift` field + `n_content_drift` in the report |
| `dsa check-revisions` detects a stale corpus against a recorded fixture and records `upstream_revision` + `revision_checked_at` | met | `TestCheckRevisions::test_a_stale_corpus_is_detected_and_recorded` |
| `build` performs no network revision check | met | `TestBuildChecksNothing` (3 tests: source, import graph, behaviour) |
| The banner appears in all four surfaces, each asserted separately | met for three, **mechanism only for `dsa audit`** | `TestTheFourSurfaces` (6 tests) — the audit *command* is ticket 05; the field and its metric function landed here and are asserted |
| A never-checked corpus reads `unknown`, distinct from `current`; the footer says "revision not checked" | met | `TestUnknownIsNotCurrent` (4 tests) + `test_an_unchecked_corpus_says_so_on_every_surface` |
| MCP responses carry the staleness state | met | `TestMcpCarriesStaleness` (2 tests: the declared schema of every tool, and a live session over `get_index` / `find_spec` / `list_parts`) |
| The check degrades honestly with no network: `unknown`, a warning, no crash, no stale-to-current transition | met | `TestCheckRevisions` (2 offline tests) |

One criterion is met by *mechanism* rather than by a live confirmation, and it
is the big one: **no corpus in this repo has ever been checked against a real
upstream document**, because this run had no network. Every part reads
`unknown`, which is the designed and honest state. `Reports/PHASE_7_LIVE_RUN.md`
L4–L6 are the owner's steps, including the one observation this phase cannot
make for itself — the `stale` path against a document that really was
superseded.

### Open items carried forward

- **`dsa audit` does not exist yet** (ticket 05). `staleness.audit_metric()` is
  its `revision freshness` row, tested, and documented as its input. If ticket
  05 renders freshness some other way, that is a divergence to catch there.
- **`check-revisions` does not flip `url_verified`.** A successful check proves
  the URL resolves, which is exactly what that flag records — but the flag also
  implies bytes were kept, and a read-only command silently rewriting a
  checked-in registry file would be a surprise. Recorded as L5 for the owner to
  decide with the evidence in front of them.
- **`content_drift` is recorded but nothing acts on it.** It is a maintainer's
  signal today (a `current` corpus whose upstream bytes moved). If `dsa
  diff-rev` (ticket 03) wants to diff a drifted document against its local
  copy, `upstream_sha256` is already on the record.
- **A part with two documents reads as its least fresh one.** That is the safe
  direction, but a corpus whose *register map* is stale and whose datasheet is
  current currently reports one line naming the worse document; a per-document
  breakdown in `dsa status` would be an improvement and is not here.
