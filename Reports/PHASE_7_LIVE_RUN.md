# PHASE 7 — live steps deferred to the repo owner

Phase 7 is the phase whose features are *about* the network, and it was
implemented with **no network**. Every mechanism below is built, tested against
a recorded or synthetic fixture through the existing `ReplayFetcher` /
`ReplayBinaryFetcher` seam, and honestly reported as unconfirmed until someone
with a connection runs the step listed here. Nothing was marked "met" by a
fabricated fixture: no URL was invented, no sha256 was guessed, no HTTP
response was written, and no `retrieved_at` was back-filled.

Each step below is a command the repo owner runs, plus what to record
afterwards.

---

## Ticket 01 — document registry + `dsa fetch`

### L1. Confirm the four derived TI URLs

`registry/datasheets.yaml` ships four `url_verified: false` entries. Their URLs
were **derived**, not looked up: the literature-path pattern this repo already
carries (`https://www.ti.com/lit/ds/<lit>/<lit>.pdf`, present in
`Reports/PHASE_7_PLAN.md`) applied to a literature number parsed out of a PDF
that is physically in this repo.

| Part | Literature number (parsed from) | Derived URL |
|---|---|---|
| AFE7950 | SBASA41E (`afe7950.pdf` pp.1–3) | `…/lit/ds/sbasa41e/sbasa41e.pdf` |
| AFE7953 | SBASAN1A (`afe7953.pdf` pp.1–3) | `…/lit/ds/sbasan1a/sbasan1a.pdf` |
| LM741 | SNOSC25D (`lm741.pdf` pp.1–3) | `…/lit/ds/snosc25d/snosc25d.pdf` |
| LMX1204 | SNAS800B (`tests/fixtures/pdf/lmx1204.pdf` pp.1–3) | `…/lit/ds/snas800b/snas800b.pdf` |

```bash
dsa fetch AFE7950            # then AFE7953, LM741, LMX1204
```

**Expected, and why it is not a failure.** These four will report a **sha256
mismatch and stop**. That is the designed behaviour and it is correct here:
the recorded hash carries `sha256_origin: local_file:<path>` — it is the hash
of the copy committed to this repo, not a hash recorded off the wire — and the
repo owner has already measured (ticket note, 2026-08-18) that TI regenerates
a datasheet's "PACKAGE MATERIALS INFORMATION" addendum with the current date on
every download. The bytes therefore differ from a local copy on essentially
every TI fetch while the revision identifier stays put.

The warning is written for exactly that: it decides its cause from the
**parsed revision**, not from the hash, and says *"both documents report
revision SBASA41E, so this is NOT evidence of a new revision"*. Read it, then:

```bash
dsa fetch AFE7950 --accept-new-revision
```

which records the fetched hash with `sha256_origin: fetch:<url>`,
`url_verified: true`, and a real `retrieved_at` — after which subsequent
fetches of the same revision compare hash-to-hash from the wire and the
mismatch path means something again.

**Record afterwards:** commit the updated `registry/datasheets.yaml`, and
re-run `.venv/Scripts/python.exe scripts/seed_datasheet_registry.py --check`
— it will now report stale, which is correct (the file has grown facts the
seed script cannot compute offline). Either drop the seed entries from
`SEED_DOCUMENTS` for the parts that now carry fetched hashes, or relax
`tests/unit/test_fetch.py::TestSeedRegistry::test_the_checked_in_file_is_what_the_seed_script_renders`
to cover only the entries still marked `local_file:`. That decision belongs to
whoever runs the live step, so it is recorded here rather than pre-empted.

### L2. Supply the URLs this repo cannot derive

Three vendors and one document type have **no** URL pattern encoded anywhere in
this repo, so their entries ship `url: null` with the reason recorded. Nothing
guesses them.

| Part / document | Recorded reason |
|---|---|
| AD9081 (adi) | no adi document-URL pattern is encoded in this repo |
| HMC520A (adi) | no adi document-URL pattern is encoded in this repo |
| QPA1003P (qorvo) | no qorvo document-URL pattern is encoded in this repo |
| LMX1204 register map (SNAU269A) | the only TI literature path this repo carries is the *datasheet* path (`lit/ds`); a programmer's guide's path is not encoded here |

```bash
dsa fetch --url <URL> --part AD9081
dsa fetch --url <URL> --part HMC520A
dsa fetch --url <URL> --part QPA1003P
dsa fetch --url <URL> --part LMX1204 --doc-type register_map
```

Each writes a well-formed entry carrying the **fetched** revision, hash,
`url_verified: true` and `retrieved_at`. That is the designed growth path, not
a gap: an agent that finds a URL calls the same command.

### L3. Record a real recorded-response fixture (optional)

`tests/fixtures/recorded_http_bin/` holds three real recorded GIFs from the
phase-3 plot work. Nothing was added to it for this ticket, because a fixture
named after a vendor URL whose bytes were never received from that URL would be
a fabricated recording — the exact defect this phase's brief warns about. The
fetch tests instead build their replay cache in-test from synthetic PDFs, under
`example.invalid` URLs, through the same `binary_cache_name` on-disk format
`ReplayBinaryFetcher` reads in production.

If a genuinely recorded vendor PDF response is wanted as a committed fixture,
record it during L1/L2 by copying the file `CachingBinaryFetcher` wrote under
`.cache/http-bin/` into `tests/fixtures/recorded_http_bin/`. Note the size cost
before doing so (a datasheet is megabytes; the current fixtures are kilobytes).

---

## Ticket 02 — revision awareness + staleness surfacing

The whole ticket is *about* asking upstream a question, and this run had no
network. Every mechanism is built and tested against synthetic PDFs served
through the existing `ReplayBinaryFetcher` seam under `example.invalid` URLs.
No vendor response was fabricated, no upstream revision was invented, and no
`revision_checked_at` was back-filled — which is why every corpus in this repo
currently reads `unknown`, and says so on all four surfaces.

### L4. Run the first real freshness check

```bash
dsa check-revisions --all --json > .scratch/tmp/first-check.json
```

Only the four parts whose registry entries carry a URL can be checked at all
(AFE7950, AFE7953, LM741, LMX1204 — the derived TI literature URLs from L1);
AD9081, HMC520A, QPA1003P and the LMX1204 register map will report
`status: no-url` and leave their recorded state untouched, which is correct.
Note that this command downloads through an **uncached** fetcher on purpose, so
it does not answer a freshness question out of `.cache/http-bin`.

**Expected from the owner's own 2026-08-18 measurement**, and worth confirming
because it is the assumption the design rests on:

| Part | Expected outcome | Why |
|---|---|---|
| LM741 | `current`, `content_drift: true` | same revision SNOSC25D, different sha256 |
| AFE7950 | `current`, `content_drift: true` | same revision SBASA41E, different sha256 |
| AFE7953 | `current`, `content_drift: true` | same revision, different sha256 |
| LMX1204 | `current`, `content_drift: false` | same revision SNAS800B, identical sha256 |

If any of the four instead reports `stale`, that is a real finding about the
part, not a bug: read the named upstream revision, then
`dsa fetch <PART> --accept-new-revision` and rebuild.

**Record afterwards:** the four `INDEX.md` banners and `dsa status` will change
from "Revision not checked" to "Revision current: … (checked <date>)". Commit
the updated `parts/*/sources.json` and `parts/*/INDEX.md` if those corpora are
tracked, and paste the `--json` output into `Reports/PHASE_7_REPORT.md` under
ticket 02 so the first live reading is on the record.

### L5. Confirm the derived-URL flag flips only on a fetch

`dsa check-revisions` deliberately does **not** rewrite
`registry/datasheets.yaml`: asking what is upstream is a different act from
putting bytes on disk, and `url_verified` records the latter. After L4 the four
TI entries will therefore still read `url_verified: false` even though the URL
demonstrably resolved. Flipping it is L1's `dsa fetch --accept-new-revision`.

If that split turns out to be unhelpful in practice, the change is a few lines
in `acquire/revisions.py` — but make it deliberately, and record it, because a
read-only command that writes a checked-in file is a surprise.

### L6. Confirm the staleness path end to end on a real new revision

Nothing in this repo has a *genuinely* superseded document, so the `stale`
path is proven only against a synthetic fixture whose revision moved
(`tests/unit/test_revisions.py::TestCheckRevisions::test_a_stale_corpus_is_detected_and_recorded`).
The first time a real TI part revises upstream (SBASA41E → SBASA41F, say),
re-run L4 and check that:

- `dsa status` shows `revision: stale` and names both revisions;
- the `INDEX.md` banner block was refreshed in place (one banner, not two);
- `dsa ask --part AFE7950 "…"` carries the warning in its footer **at every
  budget**, including one far below the pack's citation floor;
- the MCP `staleness` envelope field reads `stale` on every scoped tool.

Record the measured output in `Reports/PHASE_7_REPORT.md`; that is the one
observation this phase could not make for itself.
