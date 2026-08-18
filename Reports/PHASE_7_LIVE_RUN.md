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
