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

---

## Ticket 03 — `dsa diff-rev`

**Landed.** `pytest` 1809 passed / 1 skipped (1759 before this ticket + 50 new);
`ruff check src tests` clean.

### What shipped

| Piece | Where |
|---|---|
| The derivation | `src/datasheet_analyzer/revdiff/build.py` (`build_revision_diff`) |
| The report | `src/datasheet_analyzer/revdiff/render.py` (`REVISION_DIFF.md`) |
| The lookup | `src/datasheet_analyzer/retrieve/revdiff.py` (`RevisionPair`) |
| Two revisions under one part | `dsa build --rev <label>` → `pipeline._register_revision`, `SourceDocument.revision_label`, `publish.doc_dir_name_for_source` |
| The command | CLI `_cmd_diff_rev` (`dsa diff-rev --part X [--from A --to B] [--json] [--no-write]`) |
| The file writer | `publish.write_revision_diff` |
| Models | `RevisionChange`, `RevisionDiff` (additive); `REVDIFF_SCHEMA_VERSION = "1"` |
| The declared revision pair | `tests/fixtures/synthetic/revision_pair.py` |
| Tests | `tests/unit/test_revdiff.py` (39), `tests/integration/test_phase7_revdiff.py` (11) |

### Two revisions coexist because the document directory carries the label

A part corpus already keys its document directories on the content hash
(`datasheet-a1b2c3d4`), so two revisions of one datasheet **could not collide**
even before this ticket — what they could not do is be told apart by a reader,
or selected by a command. `--rev F` adds `revision_label` to the inventory entry
and a `-revf` suffix to the published directory, which buys legibility and
selection rather than uniqueness. It is strictly additive: a document with no
label is published under exactly the name it always was, so no built corpus
moves and no existing citation breaks.

Three refusals guard it:

- **A PDF already registered is never re-labelled.** The label names the
  directory every one of that document's citations points at, so re-labelling
  would rename it and orphan the built copy. `pipeline.BuildRefused` says so and
  names the fix (asserted in the gate).
- **The two sides of a diff are selected, never guessed.** A selector matches a
  label, a printed revision, a document directory or a content hash; a selector
  matching two documents is refused with both named. The no-selector default is
  taken only when exactly one document *type* has exactly two entries — a part
  holding a datasheet and a register map has two documents that are not two
  revisions of anything.
- **Diffing a document against itself is allowed and is empty.** That is the
  determinism check the ticket asks for, and the empty diff says which of the
  two empties it is (`same document` against `identical revisions`).

### One rule decides what is scored

A change carries a numeric delta **only** where the phase-6 numeric layer read
both printed values into the same SI base, and that delta is the sole number
this artifact adds (`si_delta:<column>`, `after − before`, both operands cited).
Everything else is quoted verbatim under **Review by hand** and carries no
score, no sign and no direction:

| Reported as | Scored? | Why |
|---|---|---|
| `TJ max 105 °C -> 125 °C` | yes, `+20 °C` | both sides parsed, same column, same base |
| `IDD typ 120 mA -> 135 mA` | yes, `+0.015 A` | scaled to the SI base first, as everywhere else |
| `Output noise typ See Figure 7 -> See Figure 9` | no | neither side is a quantity |
| `VDD typ 1.8 V -> 1900 mV` | yes, `+0.1 V` | a prefix is not a change; the *unit* move is its own unscored row beside it |
| `VDD typ 1.8 V -> 1.9 A` | no | different SI base — a change to review, not to subtract |
| register `R2` reset `0x0223 -> 0x0233` | **never** | a reset is a bit pattern; a signed difference between two of them means nothing |
| section retitled / page-shifted, pin renamed, anything added or removed | no | there is no second value to subtract from |

The register reset is the deliberate one. It would parse as an integer, and
scoring it would produce a number (`+16`) that looks like a measurement and is
not one.

### Alignment, per artifact

| Artifact | Aligned on | Why |
|---|---|---|
| spec | alias-resolved symbol (`registry/aliases.yaml`), else a shared printed symbol | a parameter the vendor renamed is **one changed row**, not a removal plus an addition — the ticket's second criterion |
| section | printed section number, else normalized title | a section's identity survives a rewording of its title, which is what makes `retitled` distinguishable from `added` |
| pin | printed designator | the package fixes it; a renamed pin is the same ball, and calling that "one removed, one added" would tell a designer to redraw a footprint that did not move |
| register | parsed address (`0x1A04`, `0x1a04` and `6660` are one register), else the printed string | the identity `dsa regs --addr` already uses |
| bit field | field name, inside a paired register | its own `kind`, because a field that moved from `2:0` to `3:1` compiles, runs and misconfigures silicon silently |

An **ambiguous** key — several rows on a side that share no printed identity
cell — is refused whole and listed with its printed values under *Not
comparable*, never reported as added + removed, because that would be a claim
about the device.

### Verified against a declared revision pair

There is no real revision pair in this repo (one revision of every part), so the
gate uses a **declared** one: `tests/fixtures/synthetic/revision_pair.py` writes
two PDFs whose differences are a fixed hand-written list, and both go through
the real `PdfLayoutBackend` and the real pipeline. The gate asserts the diff is
**exactly** that list:

| Declared edit | Reported as |
|---|---|
| TJ max 105 → 125 °C | `spec changed TJ max`, delta `+20 °C` |
| IDD typ 120 → 135 mA | `spec changed IDD typ`, delta `+0.015 A` |
| Output noise typ `See Figure 7` → `See Figure 9` | `spec changed Output noise typ`, review by hand |
| Turn-on time added | `spec added Turn-on time` |
| Gain error removed | `spec removed Gain Error` (keyed by the canonical symbol; the printed spelling travels as the label) |
| §5 retitled | `section retitled 5 title` |
| §5 moved p.3 → p.4 | `section page-shifted 5 page` |
| §4.2 added | `section added 4.2` |
| §4 now spans p.2-3 | `section page-shifted 4 page` |
| pin A2 VDD → VDD1P8 | `pin renamed A2 name` |
| pin B3 added | `pin added B3` |
| pin A4 removed | `pin removed A4` |

12 declared, 12 found, nothing else — and the rows that did **not** move
(including one printing `See Figure 12` on both sides, the row most likely to be
spuriously reported by a string diff) produce no changes at all. Register and
bit-field deltas are proven at corpus level on a two-revision register map
(`tests/unit/test_revdiff.py::TestTwoRevisionCorpus`) rather than inside the PDF
pair, because the layout floor routes a register summary through a register-map
document and the pair is a datasheet.

This is a *stronger* check than a real pair would give — with a real pair the
expected delta would itself have to be read off two PDFs by hand — but it is not
the same check, and the difference is recorded as **L7** in
`Reports/PHASE_7_LIVE_RUN.md`.

### Invariant 8

Every `before`/`after` cell is a `DerivedValue` carrying the printed string with
its unit, the page, the rule (`copy_cell`, or
`copy_cell+parse_quantity+si_normalize` where the numeric layer read it) and a
**part- and document-qualified** source reference
(`parts/REVPART/docs/register_map-…-reva/registers.json#reg_1`). The
qualification is not decoration: both revisions of one part publish a `rec_1`, so
an unqualified reference would resolve to a confident, wrong record. The gate
resolves every one of them through `provenance.resolve_source`.

The one exception is a **section**, which is a file rather than a record: its
reference is the corpus-relative path of its markdown file, because inventing an
`artifact#rec_n` id for it would produce a reference that looks resolvable and is
not.

### Criteria

| Criterion | Status | Evidence |
|---|---|---|
| Two revisions coexist under one part directory without colliding; both independently queryable | met | `TestTwoRevisionsCoexist` (4) — two `-rev` directories, each with `specs.json` + `pins.json`, one query returning both revisions' values with distinct citations |
| Spec deltas computed by alias-resolved symbol; a renamed-but-equivalent parameter is `changed`, not removed+added | met | `test_renamed_parameter_is_one_changed_row_not_a_removal_and_addition` |
| Numeric deltas only where both sides parsed; everything else listed verbatim under "review by hand" and never scored | met | `test_numeric_delta_appears_only_where_both_sides_parsed`, `test_unscored_change_is_quoted_verbatim_under_review_by_hand`, `test_everything_else_is_quoted_verbatim_and_never_scored` |
| Section retitles and page shifts distinguished from additions | met | `test_retitle_page_shift_and_addition_are_three_distinct_facts`, plus the gate's §4 / §4.2 / §5 rows |
| Pin and register deltas included, reset-value changes called out specifically | met | `TestPinChanges`, `TestRegisterChanges` (`reset-changed` is its own change value, beside bit-field bits/reset moves) |
| A diff against an identical revision is empty, not noise | met | `test_identical_revisions_produce_an_empty_diff_not_noise`, `test_diffing_a_revision_against_itself_is_empty`, `test_two_runs_over_the_same_input_produce_the_same_diff` |
| Verified against a hand-checked expectation on a real revision pair | **met against a declared synthetic pair; no real pair exists offline** | `TestDeclaredEditsAreFoundExactly` (12 declared edits, 12 found, nothing else); L7 in `Reports/PHASE_7_LIVE_RUN.md` |
| Output: `parts/<PART>/REVISION_DIFF.md` plus `--json` | met | `TestTheWrittenReport`, `TestCli::test_json_carries_the_schema_version_and_the_envelopes` |

### Open items carried forward

- **A part holding two revisions has part-level cards built from both.** Design
  cards join rows from every document of a part, so a two-revision part's
  `cards/power.json` can quote either revision — each row cited to its own
  document directory, so it is visible rather than silent, but it is not
  *chosen*. Recorded in `KNOWN_SHORTCOMINGS.md`; the fix (part-level derived
  artifacts read the newest labelled document) is a rule change worth making
  deliberately rather than as a side effect of this ticket.
- **`dsa diff-rev` has no MCP tool.** The phase plan lists `get_audit`,
  `list_families` and `get_family_index` as this phase's new MCP surface and not
  this one; the diff is CLI + JSON only.
- **A spec row that printed no value in any column takes no part in the
  alignment.** The layout floor emits one per neighbouring pin-table row; a dozen
  of them collapse onto one `(unnamed row)` key and bury the changes that matter.
  They are counted per side in the report's own notes rather than dropped
  silently.
- **`content_drift` is still not an input.** Ticket 02 left `upstream_sha256` on
  the record for a future "diff the drifted upstream copy against the local one";
  that needs a *fetched* second copy, so it stays a live step rather than a
  feature.

---

## Ticket 04 — Errata cross-linking

**Landed.** `pytest` 1875 passed / 1 skipped (1809 before this ticket + 66 new);
`ruff check src tests` clean.

### What shipped

| Piece | Where |
|---|---|
| The lexicon | `src/datasheet_analyzer/registry/errata.yaml` + `errata/lexicon.py` |
| Item segmentation | `errata/items.py` (`build_items`, three named rules) |
| The matching rules | `errata/link.py` (`build_errata_links`, eight rules) |
| Reading links back | `errata/link.py` (`links_by_target`, `sections_to_banner`) |
| The report, the banner, the pack warning | `errata/render.py` (`ERRATA.md`, `section_banner`, `pack_warning`) |
| Publication | `publish/writer.py` (`write_errata`, `errata_current`, `_errata_links`, `_bannered_docs`) |
| The consumer | `retrieve/index.py` (`CorpusIndex.errata`, `errata_for`, `section_file`), `retrieve/retriever.py` (`Retriever.errata_for`), `retrieve/pack.py` (`PackLine.source` / `PackLine.errata`, `_with_errata`) |
| Models | `ErrataTargetKind`, `ErrataTarget`, `ErrataItem`, `ErrataLink`, `ErrataLinkSet` (additive); `CorpusStats.n_errata_items` / `n_errata_linked`; `ERRATA_SCHEMA_VERSION = "1"`; `provenance.errata_item_id` |
| The declared errata document | `tests/fixtures/synthetic/errata_doc.py` |
| Tests | `tests/unit/test_errata.py` (52), `tests/integration/test_phase7_errata.py` (14) |

New files per part, and **only** for a part that registers an errata document:
`parts/<PART>/errata_links.json` and `parts/<PART>/ERRATA.md`.

### The honest half: the errata document is synthetic, the target is real

This repo carries **no vendor errata PDF**. `dsa add-doc --type errata` has
existed since phase 3 and `acquire/inventory.py` has detected the type since
then, but nothing has ever been filed under it — a grep over `src/`, `tests/`,
`registry/`, `scripts/` and the built corpora under `parts/` finds only the type
name, never a document. None can be fetched offline, and composing a plausible
vendor errata URL is exactly what the offline boundary forbids.

So the ticket is proven against a **split** fixture, and the split is the point:

- the document being linked *to* is real — `tests/fixtures/pdf/lm741.pdf`, the
  committed gate datasheet, pushed through the whole pipeline;
- every expected target was read off that datasheet's own published records by
  hand: `§6.1 Absolute Maximum Ratings` (printed p.4), its two
  `Junction temperature` rows (`rec_9`, `rec_10`), and `§7.3.2 Latch-up
  Prevention` (printed p.7);
- only the errata *prose* — the half a vendor writes — is declared, in
  `tests/fixtures/synthetic/errata_doc.py`.

That is weaker than a vendor errata sheet in one respect (nobody has confirmed
that a real TI/ADI errata item phrases its cross-references the way the fixture
does) and stronger in another (with a real errata PDF the expected targets would
themselves have to be read off two documents by hand and could be wrong). The
live step is **L9** in `Reports/PHASE_7_LIVE_RUN.md`.

### Matching is by structured identifier, and there is no threshold to tune

Eight rules, all of them exact comparisons against something the document
printed:

| Rule | Fires on | Grade |
|---|---|---|
| `section-number` | a **cued** number (`Section 6.1`, `§7.3.2`) equal to a published section's printed number | high |
| `table-caption` | a printed table caption (≥ 8 chars) contained in the item, normalized and space-fenced | medium |
| `spec-symbol` | a printed symbol, whole-token and case-sensitive, that *reads like a symbol* | high |
| `alias-phrase` | an `aliases.yaml` phrase in the item, resolved to a canonical symbol the record carries or prints | medium |
| `pin-name` | a printed pin name, whole-token and case-sensitive | high |
| `pin-designator` | a **cued** designator (`ball A1`) | high |
| `register-name` | a printed register acronym, whole-token and case-sensitive | high |
| `register-address` | a `0x…` word equal, **as an integer**, to a register's parsed address | high |

Three refusals are load-bearing and each has its own test:

- **A section number must be cued.** An uncued `6.1` in errata prose is a supply
  voltage far more often than a section, and this rule's output is what puts a
  warning banner on a page. `test_an_uncued_number_links_nothing`.
- **A symbol must look like a symbol.** The layout floor records `Supply`,
  `Input` and `Large` in the *symbol* column of datasheets that print no symbol
  column at all (measured: LM741 `rec_1`, `rec_17`, `rec_32`). `_is_identifier`
  requires a digit, a second capital, or a non-ASCII letter, so `TJ`, `IVDD1P8`
  and `RθJA` link and `Supply` cannot. Those prose rows stay reachable through
  the alias rule, which requires the checked-in lexicon to vouch for the phrase
  at **both** ends — which is how "the junction temperature limit" reaches a row
  whose printed symbol is `Junction temperature`.
- **An unparsed register address is unreachable.** Addresses are compared as
  integers, exactly as `dsa regs --addr` resolves one, so a register whose
  printed address the grammar could not read publishes no integer and is not
  matched by a string comparison against another notation.

There is deliberately no similarity rung anywhere, and nothing in `errata.yaml`
that could become one. `TestNoFuzzyMatching` asserts it twice: a source-level
guard over the whole package (no `difflib`, no `SequenceMatcher`, no
`similarity(`, no `get_close_matches`, no `nearest_names`, no `fuzz`), and
behaviourally, on an item whose prose paraphrases a section title closely and
names no identifier — which links nothing.

### Nothing is ever lost

The failure this ticket exists to prevent is a vanished erratum, so the design
puts the item count itself under assertion:

- segmentation has a **floor** (`errata-section`): a document declaring no
  marker word and no ordinal opener still publishes every line it printed, one
  item per section;
- `ErrataLinkSet` holds `links` and `unlinked` as two named lists and `n_items`
  is their sum — a filter cannot hide an item without breaking an arithmetic
  identity three tests check;
- `ERRATA.md` renders unplaced items under a **constant** heading
  (`errata.render.UNLINKED_HEADING`), so the renderer and the test read the same
  string, and its opening line states `N items: X linked, Y unlinked` so a reader
  can check by arithmetic;
- the manifest records `n_errata_items` / `n_errata_linked` and a
  `derived_warnings` line naming the unplaced population;
- a rule that matched more records than `max_targets_per_rule` **states how many
  it found** on the link's `notes`, rather than truncating silently.

### The banner is inserted before the corpus is written

`write_corpus` derives the links *first*, then replaces each affected
`SectionPlan` with a bannered copy (`_bannered_docs`) — before the BM25 index is
built and before a byte lands. The file on disk, the token count in the manifest
and the text the search index was built from are therefore the same string; a
banner added after publish would have quietly broken "what is searchable is
exactly what is readable". A section is bannered when an item named it **or**
when an item named a record printed in it, because an erratum correcting one row
of the absolute-maximum table has to warn whoever opens that table.

### An answer pack carries the warning on the row, not on the pack

`PackLine` gains `source` (the ADR 0005 reference of the record the row was read
from) and `errata` (the warnings naming it). They ride on the **line** for the
same reason the citation does: they must be dropped only if the row they qualify
is dropped. `_with_errata` runs after routing and before the budget, so the
fitting arithmetic measures each row *with* its warning and cannot keep a value
while dropping the notice that an erratum names it. Three references can reach an
item — the row's record, a file the row already names, and the section file it
was printed in — deduplicated by the rendered warning.

Measured, on the gate corpus: `dsa ask --part LM741 "maximum junction
temperature"` routes `spec`, answers from `specs.json#rec_9`, and renders
`⚠ errata err_1 (p.1): Advisory 1 Section 6.1 Absolute Maximum Ratings: the
junction temperature limit printed for this device is incorrect…` under the
value. A part with no errata document produces the pack it produced before this
ticket, unchanged: `CorpusIndex.errata is None` returns the rows untouched.

### Invariant 8

No model call is anywhere in this path. Every field of an `ErrataTarget` is a
reference to a published record, a verbatim identifier the errata document
printed (`matched_on`), or a structural label from a checked-in lexicon (`rule`,
`confidence`). Record targets are referenced with `provenance.source_ref` so the
round trip resolves; a **section** target is referenced by its corpus-relative
markdown file, for the same reason the revision diff does it — inventing an
`artifact#rec_n` id for a file would produce a reference that looks resolvable
and is not. A record published without an id yields an honestly empty reference
rather than one pointed at a neighbouring row.

Only records the publisher **actually writes** are targetable: `pins.json` and
`registers.json` exist only when they hold rows, so a link into a rejected pin
table — which would read as a placed erratum while resolving to nothing — cannot
be minted. An errata document is never its own target.

### Criteria

| Criterion | Status | Evidence |
|---|---|---|
| ≥1 errata item on a real document links to its target section or spec, hand-verified | **met against a real datasheet with a declared errata document** | `TestPublishedLinks` — §6.1 by `section-number`, `rec_9`/`rec_10` by `alias-phrase`, §7.3.2 by the `§` cue, all read off `lm741.pdf` by hand; L9 in `Reports/PHASE_7_LIVE_RUN.md` |
| Unlinked errata items are still published under an explicit "unlinked errata" heading — asserted | met | `TestUnlinkedItemsSurvive` (3), `TestNothingIsLost` (4) — the count identity, the heading constant, the verbatim text under it, and the manifest warning |
| Every link records `matched_on` | met | `test_every_link_records_what_it_matched_on`; every rule test asserts the exact `matched_on` string |
| Affected section files carry a warning banner at publish | met | `TestSectionBanners` — banner in both targeted files, under the source comment, naming the item and what it matched on; absent from every other section |
| An answer pack whose supporting record is targeted carries the warning inline — asserted end to end | met | `TestAnswerPackCarriesTheWarning` (3) — in `pack.markdown`, in the declared JSON shape, and absent for an untargeted record |
| A part with no errata document is unaffected (no empty file, no banner) | met | `TestPartWithoutErrataIsUnaffected` (2) |
| Matching never uses fuzzy text similarity on prose — only structured identifiers | met | `TestNoFuzzyMatching` (2: source guard + behavioural), plus the three refusal tests above |

### Open items carried forward

- **No real vendor errata document exists in this repo.** The linker is proven
  against a real datasheet and a declared errata document; L9 in
  `Reports/PHASE_7_LIVE_RUN.md` is the step that closes it, and it is the one
  criterion above that is not live-confirmed.
- **There is no `dsa errata` command.** The ticket's surfaces are the published
  files, the section banners and the answer pack; the phase plan's new-CLI list
  does not include one, and adding a lookup command is a separate decision.
  `ERRATA.md` is readable and `errata_links.json` is greppable in the meantime.
- **`INDEX.md` does not mention errata.** The staleness banner (ticket 02) earned
  its place at the top of the index by being about the whole corpus; a per-part
  "this device has N known errata items" line is the natural twin and was left
  out rather than added unmeasured.
- **An errata document with no marker word falls to the section floor.** Every
  line is still published, but an item read that way is often a whole page and
  links more broadly than it should. The fix is a marker word in `errata.yaml`,
  a data edit — and the condition is visible in the item's own `derivation`
  field (`errata-section` rather than `errata-item-marker`).
- **Page attribution is a range.** `pdf_text` carries no per-line page, so an
  item takes the page range of the section it was read from. For a one-page
  errata sheet that is exact; for a TOC'd multi-page one it can read `p.3-5`.
  Narrowing it means re-reading the PDF at structure time, which is what
  `pin_table_pages` and the axis catalog already do and is the shape a future
  ticket would follow.
