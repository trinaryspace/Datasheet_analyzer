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
