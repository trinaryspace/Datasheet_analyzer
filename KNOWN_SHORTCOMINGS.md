# Known shortcomings

What this tool cannot currently do, written down where a reader will find it.

An entry here is a **parked** piece of work: something a ticket set out to do,
could not do honestly, and refused to fake. Every entry names what is missing,
why it is missing, what the tool does instead, and what would close it. A
shortcoming that is recorded is a decision; a shortcoming that is silently
worked around is a bug.

**Every figure below was re-measured on the fix wave of 2026-09-01** — a full
offline re-extract and rebuild of all eleven parts at pipeline 0.5.0, extractor
`tables-10`, structure stage 3. Two entries remain and both are facts about
documents rather than defects in this tool. Closing numbers for everything that
has been retired are in `Reports/PHASE_6_5_REPORT.md` and
`Reports/FIX_WAVE_2026-09-01.md`.

The four entries that the fix wave closed are described in
`Reports/FIX_WAVE_2026-09-01.md` with their measured before and after: the
extraction cache that a structure-layer fix could not invalidate, the register
record id that repeated across a part's two documents, the parked bit-field
reader, and the vendor that was pinned on no evidence. All four are gone from
this file because the rebuild proved them gone, not because they were tidied
away.

---

## Pins: AFE7950 and AFE7953 publish no pin table

**Phase 6, ticket 04; re-measured on the 2026-09-01 fix wave.** The phase
plan's acceptance gate
asks for `dsa pins --part AFE7950 --type power` to return a hand-checked supply
pin set. It returns nothing, and the reason is in the document rather than in
the tool: **the AFE7950 datasheet in this corpus prints no pin table.** Its
section 4 (Specifications) is followed directly by section 5 (Revision
History) — there is no *Pin Configuration and Functions* section to read. The
same is true of AFE7953. **Re-measured on the fix-wave rebuild at extractor
`tables-10`: 0 pins for each, unchanged.**

**What the tool does instead.** No `pins.json` is published for either part,
and `dsa pins --part AFE7950` says so in as many words rather than printing an
empty result that reads as "this part has no pins". The hand-checked supply
pin set the gate asks for was produced for **AD9081** instead (22 rails, 79
balls, checked against Table 21 of its datasheet) and is asserted in
`tests/integration/test_phase6_pins.py::TestSupplyPinSet`; on the rebuild
AD9081 still publishes **210** pins.

**What would close it.** A TI datasheet revision that includes the pin
configuration section, added to the part with `dsa add-doc`. Nothing in
`derive/pins.py` needs to change: it reads whatever pin table the document
prints.

---

## Cards: no built part prints a zero-margin parameter

**Phase 6, ticket 07; re-measured on the 2026-09-01 fix wave.** The `limits`
card flags a
parameter whose recommended maximum equals its absolute-maximum rating — a
genuine design hazard that is invisible when the two tables are read pages
apart. The phase gate asks for at least one such parameter to be flagged **if
one exists in the reference parts**. None does. **Re-measured across all
eleven rebuilt parts: 6 comparable pairs, 0 of them equal** —

| Part | Parameter | Rating | Recommended max | Margin |
|---|---|---|---|---|
| AFE7950 | `DVDD0P9, VDDT0P9` | 1.2 V | 0.95 V | 0.25 V |
| AFE7950 | Junction temperature | 150 °C | 110 °C | 40 °C |
| AFE7953 | `DVDD0P9, VDDT0P9` | 1.2 V | 0.95 V | 0.25 V |
| AFE7953 | Junction temperature | 150 °C | 110 °C | 40 °C |
| LMX1204 | Power supply voltage | 2.75 V | 2.6 V | 0.15 V |
| LMX1204 | Junction temperature | 150 °C | 125 °C | 25 °C |

No pair has zero margin, and none is negative. LMX1204's two pairs are new
here: it was not a built part when phase 6 recorded this entry.

**What the tool does instead.** The flag is proved on a synthetic corpus in
`tests/unit/test_cards.py::TestLimitsCard`, and
`tests/integration/test_phase6_cards.py::TestZeroMarginHazard` asserts the
property that actually matters over real data: *every* equal-limit pair found
in a reference part carries the flag. Today that set is empty, and the test
will start asserting the moment a part that prints one is added.

---

## Reach: no URL in the registry has ever been fetched, and no corpus has ever been checked

**Phase 7, tickets 01–02, ported to this branch 2026-09-01.** Both features are
*about* the network and both were implemented with none. Everything below is
built and tested against a synthetic document served through the existing
`ReplayBinaryFetcher` seam; nothing was marked done by a fabricated fixture.
No URL was invented, no sha256 was guessed, no HTTP response was written and no
`retrieved_at` was back-filled.

**What is unconfirmed, precisely.**

- **Three derived TI URLs ship `url_verified: false`.** `AFE7950`
  (`SBASA41E`), `AFE7953` (`SBASAN1A`) and `lm741` (`SNOSC25D`) carry
  `https://www.ti.com/lit/ds/<lit>/<lit>.pdf` composed from a literature number
  parsed out of a PDF that is in this repo, through the one literature-path
  pattern this repo already carries. That is a **hypothesis**, and the flag and
  `url_derivation` say so. Only a live `dsa fetch` may flip it.
- **The other seven entries carry no URL at all**, each with a recorded reason:
  no adi pattern (`AD9081`, `HMC520A`), no qorvo pattern (`QPA1003P`), and no
  vendor pinned from the document's own pages at all for the four
  Mini-Circuits parts. `dsa fetch --url <URL> --part X` is the growth path.
- **`LMX1204` is not in the registry**, although its corpus is built. Its two
  PDFs are working files in this tree rather than tracked documents, so a
  `sha256_origin: local_file:` hash for them would name a path a fresh clone
  does not have — the one claim that field exists to make checkable.
- **Every seeded hash is a `local_file:` hash**, so the first `dsa fetch` of
  each TI part will report a sha256 mismatch essentially always: TI regenerates
  a datasheet's package-materials addendum with the current date on every
  download, so the bytes of an unchanged revision differ. The warning is
  written for exactly that — it decides its cause from the parsed revision and
  says the revision did *not* move — but it still costs a human read before
  `--accept-new-revision` records a wire hash.
- **All eleven corpora read `staleness: unknown`.** That is the designed and
  honest state, and it is loud on all four surfaces. But it means the `stale`
  path has only ever been exercised against a synthetic fixture whose revision
  moved (`tests/unit/test_revisions.py::TestCheckRevisions`), never against a
  vendor document that was really superseded.

**What would close it.** A connection, and the steps in
`Reports/PHASE_7_LIVE_RUN.md` (L1–L6 on the source lineage): fetch the four
derivable parts, read the mismatch warnings, re-run with
`--accept-new-revision`, supply the URLs this repo cannot derive, then
`dsa check-revisions --all --json` for the first real freshness reading.

**Two smaller parked items from the same port.**

- `content_drift` is recorded (with `upstream_sha256`) and nothing consumes it
  yet; `dsa diff-rev` is its natural consumer.
- `RevisionState` is not exposed on the workbench HTTP surface — the browser
  panes show a document's applicability and labels but not its freshness. The
  CLI, the corpus files and MCP all carry it.
- A two-document part reports one `dsa status` line naming its least fresh
  document. A per-document breakdown would be better and is not here.

---

## Errata: no vendor errata document has ever been read

**Phase 7, ticket 04, ported to this branch 2026-09-01.** Errata cross-linking
is built, tested and gated, and **no real errata PDF exists in this repo to
point it at**. `dsa add-doc --type errata` and `dsa fetch --doc-type errata`
have both existed for some time; nothing has ever been filed under either, and
none of the eleven built parts registers an errata document. Every corpus in
`parts/` therefore publishes no `errata_links.json`, which is the designed
silence — a part with no errata document gets *no file*, because an empty one
would read as "no known issues", a claim this corpus has no evidence for.

**What is proven, precisely.** The gate
(`tests/integration/test_phase7_errata.py`) builds the real `lm741.pdf` through
the whole pipeline and links a **synthetic** errata document against it. The
split is deliberate and is the honest half: the section numbers, the spec rows,
the record ids and the printed pages the links land on are all real and
hand-read off that datasheet, while the errata *prose* — the part a vendor
writes — is declared in `tests/fixtures/synthetic/errata_doc.py`. Measured
there: 3 items, 2 linked, 1 unlinked; section 6.1 and both its `Junction
temperature` rows on p.4, section 7.3.2 on p.7.

**What that cannot tell us.** Whether a real vendor's errata sheet segments
into the items its author intended. The lexicon's marker words (`advisory`,
`anomaly`, `bug`, `errata item`, `erratum`, `issue`, `item`) are a reasonable
guess at a vendor's vocabulary and **nothing has confirmed them against a
document written by one**. A vendor heading its items some other way falls to
the ordinal rule, and failing that to the per-section floor: every line is
still published, but under one item per section, which links less well. That
degradation is by design and is visible in `ERRATA.md` as an item's
`derivation` — but it has never been observed on real vendor prose.

**Also not measured on a real document:** an errata sheet with a table of
contents (an item's page then becomes a range like `p.3-5`, because `pdf_text`
carries no per-line page), and an image-only errata scan (the segmenter yields
nothing and the file records `empty_reason`, which no real document has
exercised).

**What would close it.** A connection and a vendor: file a real errata PDF
(`dsa fetch --url … --doc-type errata --part X`), rebuild, then read
`ERRATA.md`'s unlinked list and every `matched_on` in `errata_links.json` and
record the linked/unlinked split. Then confirm the banner and the inline pack
warning on that part — `dsa ask --part X … --json` must carry a non-empty
`errata` array on the answer row.

**One smaller parked item from the same port.** A full-text search that matches
the *banner* text still returns the banner in its snippet, cited to the
datasheet page the section prints on. That is the index being honest — the
banner really is in the section file, and the banner names its own errata page
inside the quote — but it means one surface quotes errata prose under a
datasheet citation. The answer pack's supporting excerpt does not: it strips
the banner (`errata.render.strip_banner`), because that surface exists to quote
what the datasheet page prints and the erratum is already on the answer row
above it.
