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

---

## Ticket 03 — `dsa diff-rev`

The command itself needs no network: it reads two documents a part already
holds. What needed network is *getting* a second revision, and this repo carries
exactly one revision of every part it has. So the whole feature is implemented
and tested, and the one thing it could not be shown on is a vendor's actual
revision.

### L7. Diff a real revision pair

The gate proves the command against a **declared** pair —
`tests/fixtures/synthetic/revision_pair.py` writes two PDFs whose differences
are a fixed hand-written list, both go through the real extraction pipeline, and
`tests/integration/test_phase7_revdiff.py` asserts the diff is exactly that list
(12 declared edits, 12 found, nothing else). That is a stronger *expectation*
than a real pair gives, because a real pair's expected delta would itself have
to be read off two PDFs by hand. It is not, however, evidence that a **vendor's**
revision moves things the way the fixture does.

When a part in `registry/datasheets.yaml` revises upstream — `dsa
check-revisions --all` reports `stale`, naming the new revision — do this:

```bash
# 1. keep the built revision where it is, and fetch the new one
dsa fetch AFE7950 --accept-new-revision     # writes parts/AFE7950/documents/<new>.pdf

# 2. build the new one beside the old, each under its own label
dsa build parts/AFE7950/documents/afe7950.pdf --part AFE7950 --rev SBASA41F

# (the already-built revision needs no label: --from also accepts its printed
#  revision identifier or its document directory name)

# 3. the review
dsa diff-rev --part AFE7950 --from SBASA41E --to SBASA41F
dsa diff-rev --part AFE7950 --from SBASA41E --to SBASA41F --json > revdiff.json
```

**What to check, and record in `Reports/PHASE_7_REPORT.md` under ticket 03:**

- how many changes the diff reports, and how many of them carried a numeric
  delta — the ratio is the honest measure of how much of a real revision this
  tool can *score* rather than merely surface;
- whether any change is one the vendor's own revision-history section does
  **not** mention (that is the value of the feature: the deltas nobody lists);
- whether any change in the vendor's revision-history section is **missing**
  from the diff (that is the feature's real failure mode, and the number worth
  publishing);
- whether the alias lexicon aligned a genuinely renamed parameter, or reported
  it as removed + added. If the latter, the fix is a YAML edit to
  `registry/aliases.yaml`, not code — and it is the first real evidence of what
  that lexicon needs to cover.

**Expect noise from the page shifts.** A vendor who adds one page to a datasheet
shifts every section after it, and each of those is a real `page-shifted` row.
The gate's four-page fixture shows two; a 146-page revision may show dozens.
Whether that wants collapsing ("§7–§39 all shifted by 1") is a judgement to make
against real output rather than in advance — record the raw count first.

### L8. Confirm a two-revision part's cards

Design cards are part-level and join rows from **every** document of a part, so
a part holding two revisions can produce a card quoting either one. Every row is
cited to its own document directory, so it is visible rather than silent, but it
is not *chosen*. After L7, run:

```bash
dsa card --part AFE7950 --card power --json
```

and check how many rows now come from the superseded revision. If the answer is
"enough to mislead", the rule to add is that part-level derived artifacts read
the newest labelled document — a deliberate change, recorded in
`KNOWN_SHORTCOMINGS.md` rather than made as a side effect of this ticket.

---

## Ticket 04 — errata cross-linking

### L9. Link a real vendor errata document

This repo carries **no errata PDF**. `dsa add-doc --type errata` has existed
since phase 3 and `acquire/inventory.py` has detected the type since then, but
nothing has ever been filed under it, and no errata URL may be composed offline
— a plausible vendor URL that resolves to the wrong document is exactly what
this phase's boundary forbids.

So the linker was built and proven against a **split** fixture: the datasheet it
links *into* is real (`tests/fixtures/pdf/lm741.pdf`, through the whole
pipeline, with every expected target read off its printed pages by hand), and
only the errata prose is declared, in `tests/fixtures/synthetic/errata_doc.py`.
What that cannot establish is whether a vendor's errata sheet phrases its
cross-references the way the fixture does — whether it writes "Section 6.1",
"§6.1", "Table 6-1" or nothing at all.

With network, pick a part this repo already builds and that has a published
errata or advisory document — a TI "Silicon Errata" (`SPRZ…`) or an ADI
anomaly sheet — and file it:

```bash
dsa fetch --url <the errata PDF URL> --part <PART> --doc-type errata
dsa build <part>.pdf --part <PART>
```

**Then read three things, in this order:**

1. `parts/<PART>/ERRATA.md` — how many items were segmented, and under which
   rule. Every item carries its `derivation`: `errata-item-marker` means the
   document's own heading words were recognised, `errata-section` means they
   were not and the floor rule fired. If it is the floor rule, the fix is one
   line in `src/datasheet_analyzer/registry/errata.yaml` under `item_markers`
   — a data edit, not a code change.
2. The **"Unlinked errata"** section of that same file. This is the measurement
   that matters: what fraction of a real vendor's items name an identifier this
   corpus publishes. A high unlinked count is not a bug — it is the honest
   reading, and it is the number to record — but read the items themselves and
   check *why*. If they cite tables by a caption the datasheet prints and the
   caption rule missed it, that is a real gap worth a ticket.
3. Every link's `matched_on` in `parts/<PART>/errata_links.json`. Each one must
   name an identifier that really is in the erratum's text. **A wrong link is
   worse than a missing one**, so check the `high`-graded ones first
   (`section-number`, `spec-symbol`, `register-address`) and confirm the section
   or row they landed on is what the erratum was about.

**Record afterwards:** the item count, the linked/unlinked split, and any
`matched_on` that pointed at the wrong thing, in
`Reports/PHASE_7_REPORT.md` under ticket 04 — and, if a rule mislinked, in
`KNOWN_SHORTCOMINGS.md` before changing the rule.

### L10. Confirm the banner and the pack warning on that real part

After L9, open a section file the links name and confirm the banner reads
sensibly beside real datasheet prose:

```bash
dsa ask --part <PART> "<a question the erratum is about>" --json
```

The answering row must carry a non-empty `errata` array, and the rendered
markdown must show the warning under the value. If a whole section was named by
several items, check the banner is still readable at the top of the file rather
than a wall of quoted errata — the display cap is
`errata.render.BANNER_QUOTE_CHARS`, and lowering it is a one-constant change.


---

## Ticket 05 — `dsa audit` corpus scorecard

### L11. Grade the fleet with `revision_freshness` actually checked

`dsa audit` is fully offline by construction — every metric is a count of
records the corpus already published, divided by another — with **one
exception**: `revision_freshness` reads whatever `dsa check-revisions` last
wrote onto `sources.json`, and nothing in this repo has ever run that against a
live upstream. So every corpus in the measured fleet table
(`Reports/PHASE_7_REPORT.md`, ticket 05) grades that metric `unknown`, which the
rubric scores `C` on weight 3.

That is the honest reading and it is not a gap in the audit — `unknown` is
correct until somebody checks. But it means **no corpus here has yet been graded
with freshness `current` or `stale`**, and the two states the metric exists for
have therefore only been exercised against synthetic fixtures
(`tests/unit/test_revisions.py`, `tests/unit/test_audit.py`).

With network, after running L2–L5 of ticket 02:

```bash
dsa check-revisions --all          # writes staleness onto every sources.json
dsa audit --all                    # the fleet table, now with freshness graded
dsa audit --part AFE7950           # the full scorecard for one part
dsa audit --all --json > fleet.json
```

**What to check:**

1. The `revision freshness` row of each scorecard now reads `current` or
   `stale` rather than `unknown`, and the grade moves accordingly (`A` for
   `current`, `D` for `stale` — `registry/audit_rubric.yaml`).
2. The **overall grade moves with it.** A corpus whose only `C` was freshness
   should gain roughly 0.23 of a score point when it turns `current` (weight 3
   of a 26-weight rubric, `C`→`A`). If a grade does *not* move, the metric is
   not reaching the average and that is a defect worth a ticket.
3. The scorecard's staleness **banner** — the block under the headline — says
   the same thing as `dsa status` and as the top of `INDEX.md`. All three render
   `staleness.one_line`; three surfaces disagreeing is the failure mode ticket
   02's tests exist to catch, and this is the first run where the state is
   something other than `unknown` on a real corpus.

**Record afterwards:** the re-measured fleet table in
`Reports/PHASE_7_REPORT.md` under ticket 05, replacing the all-`unknown`
freshness column, and note whether any part's overall letter changed.

### L12. Re-grade the two reference corpora after a rebuild

Eight of thirteen metrics report `n/a` for `parts/AFE7950` and `parts/AFE7953`
because those corpora predate record ids, per-record confidence, `card_version`
and the table-pinning count. `AFE7950` can be rebuilt offline from the
repo-root PDF; `AFE7953` **cannot be rebuilt hermetically** (no recorded TI
document-viewer pages exist for it), which is why this step is here rather than
done.

```bash
dsa build afe7950.pdf --part AFE7950     # offline; TI HTML backend needs network for AFE7953
dsa build afe7953.pdf --part AFE7953     # needs the TI document viewer
dsa audit --all
```

**What to check:** that `table_pin_rate` reports a real number for a TI HTML
corpus for the first time. It is 100 % on every `pdf_layout` corpus by
construction (the layout engine stamps a table's page at construction), so the
HTML path is the only place this metric can discriminate — and
`pagemap.pin_table_pages` genuinely can fail there, leaving `page: None`.
A rate materially below 100 % is the finding this metric was put in the rubric
for; record it, and re-check the `A`/`C` cut points against it.

---

## Ticket 06 — golden suggest/confirm

**Nothing in this ticket needs the network.** `dsa golden suggest` reads records
a corpus already published and `dsa golden confirm` reads the corpus and,
optionally, a local PDF. Both are fully offline by construction and both are
measured in `Reports/PHASE_7_REPORT.md` under ticket 06 against real corpora
built offline from `tests/fixtures/pdf/`. The steps below are deferred for a
different reason: they need a **human**, which is the whole point of the
ticket — invariant 5's judgment is not something this run may perform on the
repo owner's behalf.

### L13. Confirm a real generated set into a real golden file

No generated question was committed to `tests/fixtures/` by this ticket. The
19-of-20 pass rates in the report were measured against scratch corpora under
`.scratch/tmp/` and thrown away, and the seven hand-written golden sets are
untouched — because accepting a candidate *is* the human verification invariant
5 rests on, and a candidate accepted by the agent that generated it would be a
benchmark verified by nothing.

```bash
dsa golden suggest --part AD9081 --n 20
dsa golden confirm --part AD9081 --pdf tests/fixtures/pdf/ad9081.pdf
```

`confirm` shows each candidate beside the **printed PDF page**; accept, edit the
wording or the page, or reject with a reason. Accepted questions append to
`tests/fixtures/golden_qa_AD9081.yaml` (the hand-written questions above stay
byte-identical); rejections land in `golden_qa_AD9081.rejected.yaml` and are
never proposed again.

**What to record afterwards**, in `Reports/PHASE_7_REPORT.md` under ticket 06:

- the accept / edit / reject split for the first real set. The report's
  measured 19/20 says how many candidates *pass the checker*; only a human can
  say how many are **good questions**, and the gap between those two numbers is
  the one figure that tells whether this tooling is worth using at scale;
- how many rejections were the composed-identity shape the report names
  (`Differential Input Power Minimum`), because if that dominates, the fix is a
  templating rule and not a reviewer's time;
- the new per-part question count in `AGENTS.md` invariant 5 and the README
  testing section, and a `dsa verify --part <PART> --pdf …` run at 100 %.

### L14. Regenerate for the two reference corpora *after* they are rebuilt

`parts/AFE7950` and `parts/AFE7953` predate record ids, so their spec, pin and
register records carry `id: ""` and are **unaddressable**. Invariant 8 has no
exception for a proposal — a candidate must name the record it came from — so
those two parts yield 0 spec/pin/register candidates today (514 and 492 plot
candidates respectively; plot ids predate the scheme). That is the same finding
`dsa audit` already reports for them.

Rebuilding AFE7950 is offline (`dsa build afe7950.pdf --part AFE7950`);
**AFE7953 cannot be rebuilt hermetically** — no recorded TI document-viewer
pages exist for it — which is why this sits here rather than done. It is the
same rebuild as ticket 05's L12; do them together:

```bash
dsa build afe7950.pdf --part AFE7950     # offline
dsa build afe7953.pdf --part AFE7953     # needs the TI document viewer
dsa golden suggest --part AFE7950 --n 20 # now proposes spec rows too
```

**What to check:** that the pool line changes from `specs.json 0` to a real
count. If it does not, the rebuild did not stamp record ids and that is a
defect, not a corpus fact.

---

## Ticket 07 — part families + delta index

### L15. Record the AFE7953 TI document-viewer pages

**What is missing, exactly.** `tests/fixtures/recorded_http/` holds 41 recorded
pages and **all 41 are AFE7950's** (`grep -l -i afe7953 tests/fixtures/recorded_http/*.html`
returns nothing). The `CachingFetcher` cache layout is `sha1(url)[:16].html`, so
the missing entry point is nameable exactly, from the URL rule already encoded in
`src/datasheet_analyzer/extract/ti_html.py::TiHtmlBackend.main_url` — nothing here
is a guessed URL:

| Document | URL (from `TiHtmlBackend.main_url`) | Cache filename | Present? |
|---|---|---|---|
| AFE7950 TOC | `https://www.ti.com/document-viewer/AFE7950/datasheet` | `184beea0eaf165c0.html` | **yes** |
| AFE7953 TOC | `https://www.ti.com/document-viewer/AFE7953/datasheet` | `490ed36fb2d28cf4.html` | **no** |

The per-section URLs cannot be listed here at all, and that is the honest
statement rather than a gap in this note: `ti_html.parse_toc` reads them out of
the TOC page's own `<a href>` GUIDs, so until the TOC above is fetched, nobody —
this repo included — knows what they are. AFE7950's 40 section pages are
recorded; AFE7953's are not, and there is no pattern to compose them from.

```bash
# with a connection, from the repo root
dsa build afe7953.pdf --part AFE7953        # routes to ti_html, fills .cache/http
cp .cache/http/*.html tests/fixtures/recorded_http/   # only the new AFE7953 ones
```

**Why it matters for this ticket.** The family view itself does **not** need the
network: `dsa family build AFE795x` works today, and
`tests/integration/test_phase7_families.py` builds both members offline through
the vendor-neutral layout floor (`--vendor unknown`) and asserts a hand-verified
delta table against both printed PDFs. What the recorded pages would change is
*quality*, and the difference is measured, not estimated:

| Substrate | Sections | Shared | Spec rows aligned | Identical | Delta rows |
|---|---|---|---|---|---|
| `pdf_layout`, both members (this test, offline) | 40 | 5 | 318 | 86 | 232 |
| `ti_html`, both members (the corpora committed under `parts/`) | 39 | 14 | — | — | — |

The ti_html reading aligns far better — measured on the committed corpora,
387 spec rows pair on `(section, printed symbol, printed name, printed
conditions)` against 88 on the layout-floor rebuild — because the document
viewer's real table markup keeps the symbol, name and conditions columns apart
that the layout floor has to infer. It produces **no delta table today** for a
different reason, recorded in L12/L14 above: both committed corpora predate ADR
0005 record ids, so every row is unaddressable and `dsa family build AFE795x`
says so per member with the rebuild command. Once L14's rebuild has happened,
re-run:

```bash
dsa family build AFE795x
```

**Record afterwards:** the new `sections / shared / aligned / identical / delta`
row for the ti_html substrate, and the `FAMILY_INDEX.md` vs sum-of-member-indexes
ratio, into the ticket-07 section of `Reports/PHASE_7_REPORT.md` beside the
offline numbers already there. Do **not** delete the offline row — the point of
the pair is that the family view degrades honestly on the weaker substrate rather
than silently producing a thinner truth.

### L16. Nothing else in this ticket needs a network

Stated explicitly so nobody goes looking: `registry/families.yaml` is checked-in
data, `dsa family suggest` reads only built corpora, `dsa family confirm` writes
only YAML, and `dsa ask --family` is the existing offline retrieval core fanned
out over declared members. There is no fetch, no URL and no hash anywhere in this
ticket's code.

