# Known shortcomings

What this tool cannot currently do, written down where a reader will find it.

An entry here is a **parked** piece of work: something a ticket set out to do,
could not do honestly, and refused to fake. Every entry names what is missing,
why it is missing, what the tool does instead, and what would close it. A
shortcoming that is recorded is a decision; a shortcoming that is silently
worked around is a bug.

**The first two figures below were re-measured on the fix wave of
2026-09-01** — a full offline re-extract and rebuild of all eleven parts at
pipeline 0.5.0, extractor `tables-10`, structure stage 3 — and both are facts
about documents rather than defects in this tool. Closing numbers for
everything that has been retired are in `Reports/PHASE_6_5_REPORT.md` and
`Reports/FIX_WAVE_2026-09-01.md`.

The five entries after them come from the phase 7 port and were a different
kind: each named a mechanism that was built, tested and **unexercised against
the thing it was built for** — a live upstream, a real vendor errata sheet, a
twenty-part fleet, a human confirming a generated question, a family whose
members print one parameter differently. **Two of those five were exercised on
2026-09-02** and are rewritten in place with what was measured: the registry
was fetched for real (25 requests, five vendors) and a real vendor errata
document was read for the first time. Both entries got *shorter* on the parts
that were guesses and *longer* on the parts that turned out to be wrong — the
errata lexicon was missing the word the real document actually uses, and no
test could have found that.

The corpus is **25 parts across five vendors** as of that run (ti, adi, qorvo,
minicircuits, skyworks), up from 11 across three. One entry below —
*Extraction: what the new fleet reads badly* — is new, and exists because
scaling a corpus five vendors wide is the only thing that could have produced
it.

The four entries that the fix wave closed are described in
`Reports/FIX_WAVE_2026-09-01.md` with their measured before and after: the
extraction cache that a structure-layer fix could not invalidate, the register
record id that repeated across a part's two documents, the parked bit-field
reader, and the vendor that was pinned on no evidence. All four are gone from
this file because the rebuild proved them gone, not because they were tidied
away.

---

## Pins: TI's public AFE79xx datasheet is abridged — settled, not open

**Phase 6, ticket 04; re-measured 2026-09-01; closed as a fact 2026-09-02.**
The phase plan's acceptance gate asks for `dsa pins --part AFE7950 --type
power` to return a hand-checked supply pin set. It returns nothing, and the
reason is in the document rather than in the tool: **the AFE7950 datasheet in
this corpus prints no pin table.** Its section 4 (Specifications) is followed
directly by section 5 (Revision History) — there is no *Pin Configuration and
Functions* section to read. The same is true of AFE7953.

This entry used to end "what would close it: a TI datasheet revision that
includes the pin configuration section". **It will not, and the document says
so on its own first page.** Page 1 of `afe7950.pdf`, under the heading
`1 Features`, prints as its *first bullet*:

> **Request full data sheet**

`afe7953.pdf` p.1 prints the same bullet in the same place. The public
AFE79xx datasheet is an **abridged** document; the pin-configuration section
lives in the full datasheet, which TI gates behind a request. A gated document
is out of scope for a public-documentation-only corpus, so this is not a defect
waiting on an upstream release — it is the shape of what TI publishes.

Three things were measured on 2026-09-02 to settle it:

1. TI's current public revisions are still **SBASA41E** and **SBASAN1A** —
   `dsa fetch AFE7950` and `dsa fetch AFE7953` both returned HTTP 200 from
   `ti.com/lit/ds/<lit>/<lit>.pdf` and both served the revision already
   recorded here. There is no newer revision to fetch.
2. All **146** pages of `afe7950.pdf` and all **134** of `afe7953.pdf` were
   scanned for seven cues — `pin configuration`, `pin functions`,
   `pin description`, `pin assignment`, `pinout`, `signal descriptions`,
   `terminal functions`. **Zero hits in either document.**
3. TI's AFE7950 technical-documents page lists no errata and no register map.
   The register-map-shaped material exists only as an `e2e.ti.com` forum
   attachment — a user-upload path with no literature number and no revision
   identifier — which is exactly the mirrored-source failure this corpus exists
   to prevent, so it is not cited here.

**What the tool does instead.** No `pins.json` is published for either part,
and `dsa pins --part AFE7950` says so in as many words rather than printing an
empty result that reads as "this part has no pins". The hand-checked supply
pin set the gate asks for was produced for **AD9081** instead (22 rails, 79
balls, checked against Table 21 of its datasheet) and is asserted in
`tests/integration/test_phase6_pins.py::TestSupplyPinSet`; AD9081 still
publishes **210** pins.

**What the corpus has instead, since 2026-09-02.** A pin table is no longer
something only AD9081 and HMC520A can exercise. **LMX2820** publishes 48 pins
and is the first part whose pin count and package declaration agree exactly
(48 declared, 48 read); **AWR1843** publishes 112 from a `Signal Descriptions`
table under a heading the extractor was never keyed to; **SKY65405-21** and
**SKY13351-378LF** publish 7 and 3 in a non-TI house style.

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

## Reach: the registry has been fetched — what is left is one network and one vendor

**Phase 7, tickets 01–02, ported 2026-09-01. Largely closed 2026-09-02 by the
first live run.** Both features are *about* the network and both were built
with none. That is no longer true: `dsa fetch` made **25 real HTTP requests**
across five vendors on 2026-09-02, `dsa check-revisions --all` ran against
live upstream bytes, and the registry grew from 10 parts to **25 across five
vendors (ti, adi, qorvo, minicircuits, skyworks), 30 documents, 25 URLs
verified on the wire**.

**What the live run measured.**

- **The three derived TI URLs are correct.** `AFE7950` (`SBASA41E`),
  `AFE7953` (`SBASAN1A`) and `lm741` (`SNOSC25D`) each returned HTTP 200 and a
  document reporting the exact recorded revision. The `ti_lit_ds` derivation
  rule is 3 for 3, and all three now carry `url_verified: true`.
- **All three also mismatched on sha256, and the warning was right about
  why.** "Both documents report revision X, so this is NOT evidence of a new
  revision — the bytes changed while the revision identifier did not." That is
  the TI package-addendum behaviour the registry header predicted, confirmed on
  three documents. Nothing was accepted: the recorded hashes are still
  `local_file:` hashes of the committed copies, and `retrieved_at` is still
  null on those three, because the hash that is recorded did not come off that
  download. `url_verified: true` with `retrieved_at: null` is a deliberate,
  asserted combination (`TestCheckedInRegistry`), not an inconsistency.
- **`dsa check-revisions --all` over the whole fleet: 25 checked, 0 stale,
  3 content-drift, 6 could not be checked.** Ten documents came back `current`
  with their revision confirmed on the wire — ADC12DJ5200RF, AFE7950, AFE7953,
  AWR1843 (datasheet *and* errata), LMX1204, LMX2820 (datasheet *and* register
  map), QPA2213, QPL9547, lm741 — and seven of those are byte-identical to
  what this corpus holds. Only the three TI documents with `local_file:`
  hashes drift. The `stale` path is still unexercised against a real
  superseded document: no vendor in this corpus has moved a revision under us
  yet.
- **Twelve documents read `unknown` because their publisher prints no revision
  identifier at all** — every Mini-Circuits and every Skyworks datasheet, plus
  both TI app notes. The tool says exactly that ("the upstream document prints
  no revision identifier this repo's shared lexicon can read, so the
  comparison is inconclusive") rather than guessing, and there is nothing to
  fix in the tool: those vendors do not print one. It does mean that for 12 of
  30 documents, "is this current?" cannot be answered by revision identity and
  would have to be answered by bytes.
- **A part's banner is its least fresh document, and that now bites the
  reference part.** AFE7950's datasheet is `current` and its two app notes are
  `unknown`, so `parts/AFE7950/INDEX.md` reads "Revision not checked" — which
  is the designed reduction (`staleness.corpus_staleness`) applied honestly,
  and is also strictly less useful than what the same part showed when it held
  one document. The per-document breakdown noted at the bottom of this entry
  is what would fix it.
- **`LMX1204` is in the registry now, and it is the strongest citation-fidelity
  result here.** `https://www.ti.com/lit/ds/symlink/lmx1204.pdf` returns
  `acd53c1fbc131e09…` — byte-for-byte the `content_hash` its corpus was built
  from. The bytes on ti.com today are the bytes this corpus cites. The same
  fetch parsed its revision as **SNAS800B**, correcting the `SYSREFOUT0`
  page-heading fragment recorded when it was built.
- **Two of the four Mini-Circuits parts turned out to be current too.**
  `minicircuits.com/pdfs/<PART>.pdf` served **PSA-8A+** and **ZX10R-2-183-S+**
  byte-identical; both now carry `fetch:` origins and live timestamps.

**What is still open, precisely.**

- **`www.analog.com` is unreachable from this environment.** curl over HTTP/2,
  curl `--http1.1` with a browser UA, `--tlsv1.2 -4`, PowerShell
  `Invoke-WebRequest` and WebFetch all returned connection-reset or timed out;
  `analog.com` 301s to `www.analog.com` and then resets. So **AD9081** and
  **HMC520A** still carry `url: null`, and the ADI URL pattern
  (`/media/en/technical-documentation/data-sheets/<part>.pdf`) is still
  unverified and is deliberately **not** recorded. This is a network fact, not
  a code defect. Someone on a network that can reach analog.com should record
  those two and hunt companions.
- **`qorvo.com` refuses this tool's own User-Agent.** `dsa fetch` against
  `https://www.qorvo.com/products/d/da007268` with the default
  `datasheet-analyzer/0.1 (research tooling)` returns **HTTP 429 Too Many
  Requests** on the *first* request. `DSA_USER_AGENT="Mozilla/5.0 …"` gets 200,
  and that is how QPL9547 and QPA2213 were fetched. The env override works, so
  nothing is blocked, but a fresh clone will hit the 429 with no hint that a
  User-Agent is the cause. Qorvo also serves `application/octet-stream` rather
  than `application/pdf`; that costs nothing here only because this repo checks
  whether the *bytes* open as a PDF (`readable_pdf_error`) and never reads the
  content type — a strict content-type check would have rejected two valid
  documents.
- **`QPA1003P`, `LHA-83W+` and `PMA1-14LN+` still carry `url: null`.**
  QPA1003P because no Qorvo document id is recorded for it; the two
  Mini-Circuits parts because their upstream bytes differ from the copies here
  and Mini-Circuits prints **no revision identifier at all**, so nothing can
  say whether the document was revised or only regenerated. The refusal is
  correct and the recorded reason now says exactly that.
- **`content_drift` is recorded (with `upstream_sha256`) and nothing consumes
  it yet**; `dsa diff-rev` is its natural consumer. Three parts now carry a
  true `content_drift`, so the consumer finally has data to be written against.
- ~~`RevisionState` reaches the workbench API and nothing renders it.~~
  **Closed 2026-09-02.** The workbench is the fifth surface. `describeRevision`
  in `web/src/routes/library/state.ts` mirrors `staleness.banner_text` by hand
  and `RevisionBadge.tsx` draws it in three places: the compact shelf row in
  `CategoryContents`, the part summary above it (`worstRevision` — a part is
  only as fresh as its least fresh document, the same rule
  `staleness.corpus_staleness` applies), and `DocumentRow`'s meta line, which
  is now five spans. `unknown` renders as **"not checked"** with the warning
  glyph and the warning colours — the same loudness `stale` gets — and its
  tooltip carries the whole sentence and the `dsa check-revisions` that clears
  it; `current` is the only state drawn as a confirmation, and it prints the
  date the claim was made. Verified in a real browser against a scratch shelf
  holding all three readings, not only in jsdom.
- A two-document part reports one `dsa status` line naming its least fresh
  document. A per-document breakdown would be better and is not here.

**And one thing the scale-up did not put in git.** 14 of the 25 corpora — and
the PDFs they were built from — are working files in this tree, not tracked
documents. That is the existing practice, not a new decision: 9 of the 11
corpora that predate this run are untracked too, because a corpus published to
the shared `library/` store cannot resolve in a fresh clone (ADR 0008), and
only `AFE7950` and `AFE7953` are published `--self-contained`. What *is*
tracked is the registry, which now names every one of the 25 parts with a URL
and a hash anyone can re-fetch. Making the other 23 corpora self-contained is
a real piece of work and it is not done.

---

## Errata: one real vendor errata is read now, and it taught the lexicon a word

**Phase 7, ticket 04, ported 2026-09-01. Opened for real 2026-09-02.** Until
that day no real errata PDF existed anywhere in this repo and one whole audit
metric (`errata_link_rate`) was calibrated on nothing. **AWR1843** now
registers `SWRZ089C` — *AWR1843 Device Errata, Silicon Revision 1.0*, 48 pages,
fetched from `ti.com/lit/er/swrz089/swrz089.pdf` — and publishes a real
`errata_links.json`.

**What the real document showed, and it was not what was expected.** The
acquisition proposal that brought this document in said its items are headed
`Advisory <n>`, which is the first marker word `registry/errata.yaml` lists.
**That is wrong.** SWRZ089C heads its 46 items by owning subsystem —
`MSS#44`, `ANA#08A` — and prints the word "Advisory" only as the caption of
Table 5-1, *Advisory to Silicon Variant / Revision Map*, and as that table's
column header. With no marker word matching, the lexicon fell through to
`numbered_items`, which segmented on the numbered **workaround bullets inside**
each advisory: 11 items whose text ran straight across advisory boundaries,
one of them opening mid-sentence and swallowing the next advisory's title.

The fix was the data change the file's own header promises — two entries,
`ana` and `mss`, added to `item_markers`; `_MARKER_TAIL` already accepts the
`#` separator and the `08A` letter suffix. No Python changed. Other prefixes
TI uses in this family (`DSS`, `RCM`, `PCM`, `BSS`) are deliberately absent
until a document that prints one is here.

**Measured after the fix:** 98 items, **5 linked**, 93 unlinked, 20 targets,
every item `derivation: errata-item-marker`. The links land on real records at
real printed pages, hand-checked:

| Item | Links to | Page | Rule / grade |
|---|---|---|---|
| `ANA#13` — TX1 to TX3 phase mismatch | pins `B4 TX1`, `B6 TX2`, `B8 TX3` | 14 | `pin-name`, high |
| `ANA#11A` — TX/RX calibration sensitivity | spec *Transmitter Output power* | 28 | `alias-phrase`, medium |
| `ANA#12A` — HD2 in the receiver | 9 clock/phase-noise spec rows | 28, 32 | `alias-phrase`, medium |
| `ANA#18B` — spurs from digital coupling to XTAL | 3 ADC sample-rate rows | 28, 62 | `alias-phrase`, medium |

Page 14 of `awr1843.pdf` really does print `TX1 … B4` under *6.2.2 Signal
Descriptions - Analog*, checked against the PDF itself and not only against
the record.

**What is still wrong, and it is the segmentation.** 98 items for a document
with 46 advisories. Table 5-1 lists every advisory id as a row, and each of
those rows opens a line with a marker, so the map produces a near-duplicate
short item for every real one (`err_37` and `err_83` are both `ANA#13`; one is
the map row, one is the advisory). The lexicon has no way to say "not inside
this table" — segmentation runs over `pdf_text` lines, which carry no table
membership — so this is not fixable by data, and it is not fixed. A reader of
`ERRATA.md` sees each advisory twice.

**Also still unmeasured:** an errata sheet from a vendor other than TI, and an
image-only errata scan (the segmenter yields nothing and the file records
`empty_reason`, which no real document has exercised). SWRZ089C does have a
table of contents, so the page-range behaviour is now exercised: the real
advisories carry `p.7-46`, which is honest and nearly useless, because
`pdf_text` carries no per-line page and the whole advisory section is one
section.

**What is proven synthetically, and still is.** The gate
(`tests/integration/test_phase7_errata.py`) builds the real `lm741.pdf` through
the whole pipeline and links a **synthetic** errata document against it: 3
items, 2 linked, 1 unlinked; section 6.1 and both its `Junction temperature`
rows on p.4, section 7.3.2 on p.7. That test is unchanged and still passes —
it pins the linker's behaviour on prose whose intended answer is known, which
is something a real vendor document cannot do.

**One smaller parked item from the same port.** A full-text search that matches
the *banner* text still returns the banner in its snippet, cited to the
datasheet page the section prints on. That is the index being honest — the
banner really is in the section file, and the banner names its own errata page
inside the quote — but it means one surface quotes errata prose under a
datasheet citation. The answer pack's supporting excerpt does not: it strips
the banner (`errata.render.strip_banner`), because that surface exists to quote
what the datasheet page prints and the erratum is already on the answer row
above it.

---

## Extraction: what the new fleet reads badly

**Recorded 2026-09-02 when fourteen parts were onboarded; every claim in it
re-measured 2026-09-02 in a fidelity wave, and three of the four causes turned
out to be wrong.** The table below is the reading as it stands today.

| Part | The page prints | The corpus publishes |
|---|---|---|
| **LFCN-1000+**, **TCM1-83X+**, **YAT-10+**, **ZX10R-2-183-S+**, **LHA-83W+**, **PMA1-14LN+**, **PSA-8A+** | an `ELECTRICAL SPECIFICATIONS` table with a printed `Parameter / Min. / Typ. / Max. / Units` header | **0 tables detected**, 0 spec records |
| **ZFSC-2-2500+** (63 records), **ZEM-4300+** (44) | the same shape | one **whole-page** grid whose parameter column is wrong on most rows |
| **SKY67183-396LF** | `Table 1. Signal Descriptions`, eight pins, six columns side by side | 263 specs, 13 tables, **0 pins** |
| **QPA2213** | 97 titled plots over 28 pages | 57 specs, **1 figure** |

`ADC12DJ5200RF`'s 0 pins were the fifth row of this table and are **closed** —
see the commit `a row printed for the other device is not a row about this
part`; it now publishes 144 pins against a package that declares 144.

### The Mini-Circuits shape: one detection gap, and a false positive behind it

The earlier reading — *"their siblings in the same house style do work, so this
is something narrower that three of the six documents trip"* — was wrong twice
over. It is **seven** of the ten Mini-Circuits parts that detect nothing, not
three; and the two that "work" do not.

`pdf_layout` finds a table two ways: a `Table N.` caption line, or a printed
section heading (a line matching a TOC title key, or set at
`_HEADING_SIZE` = 11.0 pt or more). A Mini-Circuits datasheet offers neither.
It prints no captions and carries no TOC, so the structure ladder falls to one
`Page N` section per page and there are no title keys at all; and its only
heading-sized type is the product banner across the top, which on a multi-page
document recurs and is stripped as furniture. Where a banner line does survive,
the region under it is **the whole page**, and `_has_header_row` tests that
region's *first printed row*. On LFCN-1000+ that row is `FEATURES`. The table's
real header — `Parameter | F# | Frequency (MHz) | Min. | Typ. | Max. | Units`,
set at 7.0 pt, fifteen lines further down — is never consulted.

**The control case was not a control.** ZFSC-2-2500+'s first printed row is
`Maximum Ratings | Features`, and the single token `ratings` in it passes the
first-row gate. The whole page is then hypothesized as one table and accepted:
that is where the 63 spec records come from. They are not 63 readings of the
electrical specifications table. Their `row_verbatim` interleaves the maximum
ratings block, the features bullets and the connector list, every record grades
`confidence: low` with `parse_confidence: none` and empty min/typ/max, and
rowspan materialization carries `PORT 2` — a coaxial-connection label — down
the parameter column of twenty rows of the specifications table below it.
ZEM-4300+'s 44 records are the same shape. **LFCN-1000+'s zero is more honest
than ZFSC-2-2500+'s sixty-three**, and the INDEX.md line
`Parameters: SUM PORT, PORT 1, PORT 2, A B, 1.25 1.25, 31.75` is that fact
surfacing.

**What was built and measured, and not landed.** A third detection path that
anchors on the table's own header row: a baseline row carrying three distinct
`_HEADER_TOKENS` (`Parameter Frequency (MHz) Min. Typ. Max. Units` = 5), the
region running from it to the next caption, section title, furniture line or
larger type, and the existing ladder and gate deciding as usual. Of the six
Mini-Circuits documents scanned row by row, every one has exactly one such row
and in all six it is the specifications header. Measured by re-extracting every
PDF in the repository, before and after:

- LFCN-1000+ 0 tables → its printed grid, **exactly as printed** — 7 rows,
  `Pass Band`/`Stop Band` in the label column, `Insertion Loss | DC-F1 |
  DC-1000 | — | — | 1.0 | dB`; TCM1-83X+ 0 → 11 rows, likewise correct;
  YAT-10+, ZX10R-2-183-S+, LHA-83W+, PMA1-14LN+ and ZFDC-20-5+ each gain one.
- **No table was lost anywhere and no gate part moved**: AD9081 29/29/0,
  HMC520A 7/6/1, LM741 6 accepted, QPA1003P 5 accepted, QPA2213 4 accepted,
  SKY13351-378LF 6, SKY65405-21 5, SKY67183-396LF 13, LMX2820's register map
  139/124/15 — all identical to the reading without the path.

It was not landed because **four of the seven new tables put the parameter
column on the wrong rows.** YAT-10+ prints `Attenuation` on the first baseline
of its three-row group and `VSWR` on the *middle* baseline of the next, and
`_materialize_band0`'s nearest-anchor rule then lends each label one row too
far: the grid reads `VSWR | 15 - 18 | 10.0 | 10.81 | 11.5`, where the page
prints that line as **Attenuation, in dB**. PMA1-14LN+ and LHA-83W+ shift the
same way (Gain values labelled `Frequency Range`), and ZX10R-2-183-S+ pulls the
maximum-ratings block in from the page's other column, so
`Permanent damage may occur if any of these limits are exceeded.` becomes a
parameter. A VSWR of 10.81 is exactly the wrong value a designer acts on that
this pipeline exists to prevent, so the recall was measured and dropped rather
than shipped.

**What would close it.** Not the detection path — that part is done and
measured. Rowspan materialization that partitions rows by the table's **drawn
rules** (`_Page.boxes()` already reads them) instead of by nearest baseline, so
a label centred over its span and a label aligned to the top of its span both
land on the rows the page rules them onto. With that in place the detection
path lands as-is, and the ZFSC-2-2500+/ZEM-4300+ false positive closes with it
(their whole-page region loses the first-row gate the moment the real header
row is the anchor).

### SKY67183-396LF: a section title inside a table's header row

The recorded reason — `no viable column split` — is what `dsa status` prints,
and it is a symptom. Measured: the region under `Table 1. Signal Descriptions`
is **two lines long**. The table is six columns printed as two side-by-side
halves, `Pin | Name | Description | Pin | Name | Description`, each cell its own
line on one baseline at y=322.38; and the document has a *section* called
`Description`. The region scanner ends a region at any line whose text matches
a section title key, so the third header cell ends it, and the two lines that
survive (`Pin`, `Name`) cannot split into columns. The page prints all eight
pins; the corpus publishes none.

Matching a title key against the **whole baseline row** rather than one line of
it fixes that, and was measured to change nothing else anywhere in the corpus.
It was not landed either, because the table then reads *wrongly*. Skyworks
centres each header cell over its column while the body is left-aligned — the
`Description` header prints at x=188.3, its body text at x=115.4 — so the
header-anchored column split puts every description inside the `Name` band and
`Table 1` comes out as four rows with names like
`N/C change in performance)`, for an eight-pin part. Half a pinout with fused
names, and a `package cross-check` warning beside it, is worse than the honest
refusal: during schematic capture a missing pin reads as *this pin does not
exist*.

**What would close it.** A column model that reads a header cell's column from
the body underneath it rather than from the header word's own left edge. The
all-word rescue ladder already proposes the right bands here
(`59.8 | 84.3 | 115.4 | 188.3 | ...`) and loses the tie to the header-anchored
split by band count, which is the correct rule everywhere else — so this is a
tie-break that needs new evidence, not a threshold to move.

### QPA2213: 97 printed plot titles, one figure

The recorded cause — *"Qorvo's plot-heavy pages carry their titles inside the
plot art"* — is not what the document does. Measured over all 28 pages:

- **zero** `Figure N.` captions, anywhere. The caption-anchored path is not
  failing to parse them; there are none to parse.
- **97** printed plot-title lines, one above each plot, in ordinary text:
  `Output Power vs. Input Power vs. Temp.` (p.10, 11.16 pt),
  `IMD3, IMD5 vs. POUT/Tone vs. Vdrain` (p.20),
  `2nd Harmonic vs. POUT vs. Temp.` (p.22), four to six per page over pages
  4 to 23.

The title-anchored path misses every one of them for two reasons, both
measurable: `_TITLE_SIZE` is an **absolute** 13.0 pt and these titles are
11.16 to 11.19 pt, and a title must sit inside a drawn emphasis band, which
Qorvo's plot pages do not draw (QPA1003P's do, which is where the 13.0 pt and
the band requirement were measured). The one figure QPA2213 publishes is the
page-1 block diagram, which does have a band.

**What would close it.** A title size read relative to the page's own dominant
body type rather than as an absolute, and vector content directly below in the
title's own column as the evidence in place of the drawn band. Both are changes
to `_FigureExtraction._run_title_anchored`, and both need the same corpus-wide
before/after the detection path above got: HMC520A publishes 107 figures and
AD9081 100 off the caption path, and neither may move.

### What the tool does instead

Nothing is faked. A part with no readable pin table publishes no `pins.json`
and `dsa pins` says so; a document whose tables were never detected publishes
no spec records rather than guessed ones. The risk this entry exists to name is
that a reader takes those silences for documents that print nothing — and, now,
that a reader takes ZFSC-2-2500+'s sixty-three records for sixty-three
readings.

---

## Audit: the rubric is calibrated on eleven corpora, and one metric on none

**Phase 7, ticket 05, ported to this branch 2026-09-01.** Every threshold in
`registry/audit_rubric.yaml` is anchored to a reading measured on the corpora
under `parts/`, and the head of that file records which reading each cut point
was placed against. Eleven corpora is a small sample, seven of them RF/analog
datasheets and eight of them from one extraction backend. `A` is placed at or
just below what the best real corpus achieves, which means it moves as the
pipeline improves: `axis_coverage`'s `A` moved from 0.45 to 0.75 on this port,
because the fleet's best reading is now 78 % and leaving `A` where the source
lineage put it would have handed an `A` to a corpus reading less than the
median. That is the file being data rather than an oracle — but it is not the
same thing as a rubric validated against twenty parts.

**One metric has no measurement behind it at all.** `errata_link_rate` grades
how many of a part's published errata items a deterministic rule could place
against a record. **No part in this repository registers an errata document**
(see the errata entry below), so every corpus reports `n/a` and the cut points
are placed by argument rather than by reading — `C` at 0.50 because half the
known issues unreachable is where an agent must say so out loud. The metric is
in the scorecard because a corpus that publishes errata nobody could place is
one an agent will answer from while silently omitting them; it is not there
because anything has ever exercised it.

**`revision_freshness` is `unknown` on all eleven**, correctly: no corpus here
has been checked against a live upstream. `unknown` grades `C`, weight 3, so
every part in this repository carries that `C` today and the fleet's grades are
lower than they will be once `dsa check-revisions` has run. The grade therefore
depends on run order, which is a fact about the corpus rather than about the
rubric, and the scorecard says so in its own notes.

**`alias_hit_rate`'s top rungs are uncalibrated.** Only two benchmarks here ask
a spec question keyed by a designer's words: AFE7953 resolves 2 of 5 off the
lexicon and AFE7950 0 of 11. Nothing has ever read above 40 %, so `A` at 0.90
and `B` at 0.70 are aspirations rather than measurements. The metric is
weighted 1 for exactly that reason: it measures the lexicon and the benchmark,
not the extraction.

**What would close it.** Onboard twenty parts and re-read the fleet table; file
a real errata document and re-read `errata_link_rate`; run `dsa check-revisions
--all` against a connection and re-read `revision_freshness`. Every one of
those is a YAML edit away from moving a threshold, which is the design.

**One metric the port dropped rather than published.** `table_pin_rate`
(tables cited to one printed page, over all tables) is in the phase-7 plan and
is **not** in this branch's scorecard: the publisher here stamps a table's page
on the `TableBlock` at construction and never carries the count into
`CorpusStats`, so the metric could only ever report `n/a`. Reading its absence
as "0 tables pinned" is the defamation the `n/a` rule exists to forbid, and
recording the count would mean rebuilding every corpus in the repository.
Closing it means adding `CorpusStats.tables_pinned: int | None` — the `None`
being the whole design — and a rebuild.

---

## Golden generation: no generated question has ever been confirmed by a human

**Phase 7, ticket 06, ported to this branch 2026-09-01.** `dsa golden suggest`
and `dsa golden confirm` are built, tested and measured, and **not one
generated question has been committed to `tests/fixtures/`**. That is not an
oversight: accepting one *is* the human verification invariant 5 rests on, and
a maintainer has to do it. Every measurement below ran against a scratch golden
directory under `.scratch/`; the committed benchmarks are byte-identical, and
`tests/unit/test_golden_assist.py::TestNothingHereCanReachTheRealBenchmarks`
asserts that by shelling out to `git status --porcelain -- tests/fixtures`.

**How good the proposals are, measured.** Twenty candidates per part, all
accepted unread, then verified — the corpus half of every check, plus the
page-truth half against the printed PDF:

| Part | corpus-side | page-truth-inclusive |
|---|---|---|
| AD9081 | 20/20 text, 7/7 spec, 6/6 plot, 7/7 ask | 20/20 |
| AFE7950 | 20/20 text, 10/10 spec, 10/10 plot | 20/20 |
| AFE7953 | 20/20 text, 10/10 spec, 10/10 plot | 20/20 |
| HMC520A | 20/20 text, 7/7 spec, 6/6 plot | 20/20 |
| LMX1204 | 20/20 text, 5/5 spec, 5/5 plot, 4/5 ask | 19/20 |
| lm741 | 20/20 text, 17/17 spec, 3/3 plot | 19/20 |
| QPA1003P | 20/20 text, 16/16 spec, 4/4 plot | 18/20 |

The six page-truth failures are all one shape and all the reviewer's job: a
printed identity composed from cells that never appear contiguously on the page
(`Input adjustment range` on lm741 p.5; `Input Power (P VD = +28 V, I` on
QPA1003P, where the name cell wrapped mid-print). The corpus holds the row and
the query path finds it; the page never printed that exact run. A candidate to
edit or reject, which is what `confirm` is for — and a useful measurement of
how often a table's identity cell is a join rather than a quote.

**A finding about the tool, not about the documents.** LMX1204's one ask-path
failure is a register named `R1` whose answer pack lands on pages the question
does not cite. Its *pin* candidates surfaced something larger and are the
reason the templates changed: the ask router names a pin by an upper-case
designator lifted from the question text (`retrieve.pack.PIN_DESIGNATOR_RE`),
so **a datasheet that numbers its pins `1..40` cannot reach the pin route by
asking about a pin at all** — all five LMX1204 pin candidates routed `search`.
The generator now withholds `ask_query: {route: pin}` for such a designator and
says why on the candidate, because a path marker is a claim about the tool and
this one would be false. The router gap itself is untouched and is real: `dsa
ask --part LMX1204 "Which signal is on pin 20?"` answers from full-text search
rather than from `pins.json`.

**Question wording is a format string over printed cells, and it shows.** A
record whose name cell wrapped mid-print produces a question that reads exactly
that badly. It is verbatim and it is correct about the record; it is also the
first thing a reviewer edits, which is why `edit` takes the question text. No
model call may fix it (invariant 8) and no heuristic should: rewriting a
printed identity would break the substring it exists to match.

**Not generated at all:** `ask_query` / `search_query` *twins* of an existing
question (minting a twin means choosing which question deserves one — judgment,
not a template), and card goldens (they live in the file's own `cards:` block
and name which of the four cards must answer).

**What would close it.** Run `dsa golden suggest --part AD9081`, then `dsa
golden confirm --part AD9081 --pdf ad9081.pdf`, read each candidate against the
printed page, and commit what survives. Until someone does, this repository's
benchmarks are exactly the hand-written ones they always were.

---

## Part families: the reference family computes no delta at all

**Phase 7, ticket 07, ported to this branch 2026-09-01.** `dsa family build
AFE795x` produces a real index over the corpora committed here — 39 sections,
14 of them identical in both members and listed once, 763 spec rows aligned on
the printed row, 379 printing the same values everywhere, 384 in the delta
table. What it does **not** produce is a single `si_delta`: **0 of 763 aligned
rows carry a computed difference.**

That is not a bug in the delta and it is worth reading precisely, because the
zero has three separate causes and only one of them is about the devices.

- **379 rows agree.** Both members print the same value, so there is nothing to
  subtract. This is the family working: those rows are counted and not
  tabulated, which is the whole token argument.
- **360 rows are printed by one member and not the other**, and 16 more are
  printed several times under one identity by one member. AFE7950 is the quad
  TX/RX device and AFE7953 the dual, so their §4.9 supply-current tables sweep
  *different operating modes* — `Mode 10: 4T4R2F` exists on one document and on
  no page of the other. Nothing printed says which of AFE7950's modes pairs
  with which of AFE7953's, so nothing is paired. Inventing a pairing would put
  a delta between two unrelated measurements, which is the worst thing this
  artifact could do: it would look exactly like an answer.
- **8 rows align and differ, and every one of them differs by *column*, not by
  value.** The §4.10 SPI timing rows read `t(SCLK)_R = 50` under `typ` in
  AFE7950's corpus and `50` under `max` in AFE7953's — the same printed number,
  read into different columns by two extraction runs. `si_delta` refuses to
  subtract a `max` from a `typ` (ADR 0007), so these are listed under
  "not comparable" with both verbatim values, correctly. They are a finding
  about the *extraction*, not about the silicon, and the family index says so
  by quoting both sides rather than scoring them.

**What the delta path is proven on instead.** The synthetic family in
`tests/unit/family_corpus.py`, where the two members differ by exactly one
printed value (`TJ` max 105 against 125 °C) and the index computes `+20`
against the reference with both pages cited. Every branch of the arithmetic is
covered there; what is *not* covered is a real vendor publishing two members
that print the same parameter, under the same printed conditions, in the same
column, with different numbers.

**What would close it.** A family whose members are closer than AFE795x —
device options rather than channel counts — or the same two devices rebuilt
through one extraction backend so the §4.10 column labels agree. The second is
cheap and was measured: a `--vendor unknown` layout-floor build of afe7950.pdf
takes 181 s, so rebuilding both members costs about six minutes and is a
reasonable one-off, but it changes what `parts/` holds and every other measured
reading in this repository with it. Recorded rather than done.

**Also unexercised: pins and registers.** Neither AFE795x member publishes a
readable pin table or register map (the standing shortcoming above), so the pin,
register and bit-field delta paths are proven on synthetic corpora only. The
family index states that absence in words — *"no member publishes pins … this
family states nothing about pins, which is not the same as stating they
agree"* — rather than printing an empty table a reader could mistake for
agreement.

**~~Also parked: the family scope is nameable everywhere and offered
nowhere.~~ Closed 2026-09-02, in the workbench only.** `GET /api/families`
lists what `registry/families.yaml` declares — every entry read through
`families.registry.resolve`, so a proposal, an unconfirmed entry and an empty
family are absent rather than quietly present — and `ScopeChip` offers that
list beside the parts and projects. `known_scopes` returns a third name list
and `scope_resolver.resolve` takes `families=`, matching a declared family
**only** on an exact whole-token hit of its declared name and returning it as
a *candidate*: no path through the resolver makes a family the confident
scope, so a family becomes a scope because a person chose it. The picker
cannot invent one either — the filter narrows the declared list and never adds
to it, and typing `AFE79xx` (the wildcard the part tier matches on) offers
nothing. An undeclared family named anyway comes back as `deps.get_retriever`'s
400 carrying the registry's own refusal, rendered verbatim in the turn.
Verified in a real browser, both with the repo's declared `AFE795x` and
against an empty registry. On MCP the same boundary still holds for a
different reason — see below.

Two things are missing, both in code this wave did not own:

- **`app/scope_resolver.py` proposes only parts and projects.** A question
  naming `AFE79xx` produces *part* candidates through `_family_matches`, which
  is a string pattern over part numbers and not this noun. Closing it means
  `chat.known_scopes` reading the family registry (it returns
  `(parts, projects)` today) and a third tier in the resolver with its own
  tests — Python, and this wave's to do had it not needed the picker too.
- **`ScopeChip` lists `getParts()` and `getProjects()` and has no family
  section** — real frontend work in `web/`, which another agent owns. It is
  **recorded here and deliberately not made**: nothing in `web/` was touched
  by this wave.

Until the picker lands, `get_family_index` and the family fan-out are proven
end to end through the API and the chat loop (`tests/unit/test_chat_stream.py::
test_the_new_tools_run_through_the_real_runner_over_a_real_corpus`) and are
unreachable from a mouse. `dsa ask --family` and MCP have had the scope since
this port; the browser has the plumbing and not the door.

**Closed 2026-09-01: `search` / `find_spec` / `find_plots` / `ask` now take a
`family` over MCP.** The envelope's `scope` object carries all three names, so
a response says which scope answered it; the measured cost of the third key is
4 tokens on a 65-token envelope (0.067 % of the 6000-token cap), and with the
fan-out in, 7 of the 16 tools can fill it rather than 2. The reasoning is in
`mcp_server/server.py`'s module docstring and the argument that replaced the
deferral is `Reports/PHASE_7_REPORT.md`.

**Closed 2026-09-02: `dsa pins` / `dsa regs` / `dsa card` accepted `--family`
and refused it.** `cli._add_scope` put `--family` on all seven scoped commands,
but `pins`, `regs` and `card` did not go through `retrieve.scope` — each of
`derive/pins.py`, `derive/registers.py` and `derive/cards.py` carried its own
`_part_dirs` that resolved *directories* rather than a retriever, and each
re-implemented the **two**-scope XOR as `bool(part) == bool(project)`. A
`--family` therefore fell out of that test as "you named neither" and printed
the two-scope `SCOPE_ERROR`, which is why the refusal never named the argument
the caller passed: the code had no branch for it to fall into.

The three copies are gone. `retrieve/scope.py` now answers the same question in
two shapes — `resolve_scope` for the lookups that need a retriever,
`resolve_scope_dirs` for the three that read published artifacts off disk — and
both call one `chosen_scope`, so ADR 0006's XOR and its wording exist once. The
directory shape is kept rather than routing the three through `resolve_scope`
on purpose: a `Retriever` loads a member's specs, plots and search index, which
is a lot of reading to answer a question about `pins.json`. Every exit-code
contract is unchanged — 2 for a scope that will not resolve (an unbuilt part, an
unknown project, an undeclared or unconfirmed family), 1 for an honest empty
result, 0 for hits — and `tests/unit/test_scope_seam.py` now carries the
grep-shaped assertion that no `derive/` module counts scopes of its own.

**What a family `dsa pins` says, given that neither AFE795x member publishes a
pin table.** Each member still gets its own `no pin table was published` line,
and the scope gets one more: `AFE795x: no member publishes a pin table
(AFE7950, AFE7953) — this family states nothing about pins, which is not the
same as stating its members have none.` That is the family index's own wording
for the same fact, one noun across, so the two surfaces cannot drift; the exit
code stays 1, and `--json` carries it as `no_member_publishes_pins`. `dsa regs`
says the same about a register map, `dsa card` about a card no member fills. A
single `--part` scope does not get the extra line: `no_pins_message` has
already said it about the one part.

**Still open: `find_pin` and `find_register` over MCP take no `family`.** They
were deliberately left without one so the two surfaces would keep the same scope
set, and that argument has now inverted — the CLI resolves a family on all seven
scoped verbs and MCP on five of seven. The mechanism they need is in place
(`_pins_for` and `_registers_for` already fan out over a `ProjectRetriever`, and
`FamilyRetriever` is one), so what is left is the tool signature, the two
docstrings, the scope table in the module docstring and the envelope tests.
Recorded rather than done, because it is a change to a declared tool surface and
this session's remit was the CLI.

---

## Scale gate: eleven of twenty-five parts cannot reach `B`, measured part by part

**Phase 7, ticket 08, measured 2026-09-02** against the full 25-part fleet.
The checklist asks that every onboarded part grade `>= B` on `dsa audit` **or
carry a recorded shortcoming explaining why it cannot**. Fourteen reach `B` or
better; eleven do not, and this is the record for those eleven. **No threshold
in `registry/audit_rubric.yaml` was touched to produce this table** - the
rubric was calibrated on eleven corpora before the fleet grew and it is left
exactly where it was, because a scorecard tuned until the corpus passes is
worth less than no scorecard.

Two readings were taken, and the difference between them is itself the finding:

| | A | B | C |
|---|---:|---:|---:|
| As the fleet stood (cards never built, upstream never checked) | 2 | 10 | 13 |
| After `dsa card` on all 25 and `dsa check-revisions --all` | 2 | 12 | 11 |

Both of those are real work rather than tuning - building the derived artifact
a metric asks about, and asking upstream the question `revision_freshness`
exists to answer - and both together moved exactly two parts (lm741 and
QPA2213). It is also the shortcoming: **two of the thirteen metrics are not
reproducible from a clone.** `cards_present` reads `parts/<PART>/cards/*.json`,
a gitignored on-demand cache, so a fresh checkout grades every part `D` on it
until someone runs `dsa card`; `revision_freshness` reads a state only an
opt-in network command can set. A grade that depends on run order is a fact
about the corpus rather than the rubric, and the audit entry above already says
so - what ticket 08 adds is the size of it: **two whole grade steps across the
fleet.**

Building the cards was a measurement rather than a favour. Four cards were
written for every part, and **twelve parts hold zero card rows** even so
(LFCN-1000+, LHA-83W+, PMA1-14LN+, PSA-8A+, QPL9547, SKY13351-378LF, TCM1-83X+,
YAT-10+, ZEM-4300+, ZFDC-20-5+, ZFSC-2-2500+, ZX10R-2-183-S+ - including
QPL9547, which publishes real specs and still fills nothing). Those keep the
`D` honestly: the selectors matched nothing, which is the reading the rubric
wants.

**The eleven, and why each cannot reach `B`.**

| Part | Grade | The reading that holds it down |
|---|:---:|---|
| ZFDC-20-5+ | C 2.00 | `table accept rate` **F 0.00** - no table survives the gate |
| SKY67183-396LF | C 2.42 | `records graded high` **F 0.00**; pin table refused |
| LFCN-1000+ | C 2.44 | no specs, no pins, no registers, no card rows, no plots |
| LHA-83W+ | C 2.44 | same |
| PSA-8A+ | C 2.44 | same |
| TCM1-83X+ | C 2.44 | same |
| YAT-10+ | C 2.44 | same |
| ZFSC-2-2500+ | C 2.44 | 63 spec rows, **0 graded high**, no pins/registers/card rows |
| ZX10R-2-183-S+ | C 2.44 | no specs, no pins, no registers, no card rows |
| ZEM-4300+ | C 2.56 | 44 spec rows, **0 graded high** |
| SKY13351-378LF | C 2.58 | `records graded high` C 0.24; `figure axes read` F 0.00 |

Ten of the eleven are Mini-Circuits or Skyworks, and both causes are already
recorded above - *the Mini-Circuits shape: one detection gap, and a false
positive behind it* (a fix was built and **reverted**, because it produced
wrong values) and *SKY67183-396LF: a section title inside a table's header
row*. Nothing new is claimed here; what is new is that the fleet is now large
enough for those two entries to account for **40 % of it**.

**The one lever left, and why it was not pulled.** `golden_pass_rate` is
weight 4, the heaviest in the rubric, and it reports `n/a` for the nineteen
parts with no confirmed benchmark. A benchmark at 100 % would move nearly every
`C` here to `B` - LFCN-1000+ computes to 2.92 with one. That lever is exactly
the human confirmation invariant 5 rests on, and pulling it by marking
generated candidates `confirmed: true` would be the single most dishonest thing
available in this repository. It stays unpulled, and the eleven `C`s stand.

---

## Scale gate: no golden candidate can be generated at all for nine parts

**Phase 7, ticket 08, measured 2026-09-02.** `dsa golden suggest --n 20` was
run against all 25 fleet parts. It proposed **301 candidates**, and for nine
parts it proposed **zero** - every one of them Mini-Circuits, and a tenth
(PMA1-14LN+) managed two.

| Parts | Candidates | The generator's own recorded refusal |
|---|---:|---|
| LFCN-1000+, LHA-83W+, PSA-8A+, TCM1-83X+, YAT-10+, ZX10R-2-183-S+ | 0 | "this corpus publishes no record of this kind" - no specs, pins, registers or plots to template from |
| ZFSC-2-2500+ | 0 | 63 spec records, all refused: "the record prints no name or symbol to ask about" |
| ZEM-4300+ | 0 | 44 spec records, same refusal |
| ZFDC-20-5+ | 0 | no templatable record survived |
| PMA1-14LN+ | 2 | 2 of a very small population |

The second row is the interesting one and it is **not** a generator defect. A
Mini-Circuits spec table is a frequency matrix - the row key is `2000` and the
columns are the measured quantities - so a row carries no symbol and no name,
and a template over it would mint the question *"What is the maximum ?"*. The
generator refuses it and says which rule dropped how many, which is ADR 0005's
unparsed-population clause working. The consequence is real all the same:
**ticket 08's "goldens cover every new part" cannot be met for nine parts by
any amount of human confirmation, because there is nothing to confirm.**

What would close it is not in the generator. It is a template keyed on the
*column* rather than the row for a matrix-shaped table ("what is the insertion
loss at 2000 MHz?"), which is a new template with its own refusal rules, or the
Mini-Circuits detection gap above being closed so those corpora publish named
records in the first place.

**And the 301 that were generated: 296 machine-verified, 0 human-confirmed.**
Each candidate's expected substrings were checked against (a) the corpus
section covering the page it cites and (b) the printed PDF page text itself,
through `evalh/citations.py` - the same two checks `dsa verify` runs. 301/301
passed the corpus half; **296/301 (98.3 %) passed the page-truth half**, and
277/282 of the query-side checks passed. The five page-truth failures are the
shape the ticket-06 entry above already named - a printed identity composed
from cells that never appear contiguously (lm741 `Input adjustment range`;
QPA1003P `Input Power (P VD = +28 V, I`; SKY65405-21 `PIN, LNA TA`) - and the
five query failures are register candidates on ADC12DJ5200RF and LMX1204 whose
`regs` lookup does not return the row the question was templated from.

Machine-verified is not confirmed, and the gap between them is the whole point
of invariant 5. A page-truth check proves the substring is printed where the
candidate says. It proves nothing about whether the *question* is worth asking,
whether the row it names is the one a designer would mean, or whether the
question reads as English at all. Those are the three things `dsa golden
confirm` puts in front of a human, and no run of this ticket did any of them.

**None of the 301 is in `tests/fixtures/`.** They were written to
`.scratch/gate08/candidates/` instead, and the reason is worth recording: the
first run wrote them to the default golden directory, and
`tests/unit/test_golden_assist.py::TestNothingHereCanReachTheRealBenchmarks`
**caught it** - two failures in a 3,046-test suite, one of them a `git status
--porcelain -- tests/fixtures` shell-out. The defence worked on an agent that
was actively trying to be careful, which is the only real test of a defence
like that.

---

## Family: the reference family's zero delta is a fact about the two documents

**Phase 7, ticket 08, re-measured 2026-09-02.** The entry above - *Part
families: the reference family computes no delta at all* - records three causes
for AFE795x's `0 of 763`, and re-measurement **confirms all three counts**
(8 aligned, 360 only-in, 16 ambiguous, 379 identical). What it adds is the one
piece of evidence that entry could not have: whether a *looser* join would find
anything to subtract.

It would not. `dsa compare AFE7950 AFE7953` aligns on the alias-resolved symbol
rather than the printed row, pairs **408 rows** where the family pairs 8, and
computes **415 SI delta cells - every single one of them zero.** Not one
non-zero difference exists between these two devices in any row either engine
can pair. The family's zero is therefore not an artifact of its stricter key:
AFE7950 and AFE7953 print the same numbers wherever they both print a number,
and no join, however loose, will produce a delta table from them. The "what
would close it" line in that entry - *the same two devices rebuilt through one
extraction backend so the column labels agree* - would resolve the 8 typ-vs-max
rows and still yield zero, because those 8 rows print the same number too. It
is recorded here rather than edited in above, because the earlier reading was
correct and this one only goes further.

**Three closer families were probed, in an isolated scratch registry, and none
was declared.** `DSA_REGISTRY_DIR` and `DSA_FAMILIES_DIR` were pointed at
`.scratch/gate08/`, so nothing was written to `registry/families.yaml` and no
membership was declared by an agent - membership is DECLARED, never inferred,
and an agent is not a human.

| Probe | Members | Rows aligned | Non-zero SI deltas |
|---|---|---:|---:|
| AFE795x (declared) | AFE7950, AFE7953 | 8 of 763 | **0** |
| LMXclk | LMX2820, LMX1204 | 2 of 261 | **2** |
| QorvoPA | QPA1003P, QPA2213 | 1 of 90 | 0 - one delta, and it is wrong (below) |
| SkyLNA | SKY65405-21, SKY67183-396LF | 0 of 105 | 0 |

The LMXclk probe is the only pairing in this fleet that produces a real
computed delta table, and it produces two rows:

```
IIL  Low-level input current   LMX1204 -25 uA (p.7)   LMX2820 -1 uA  (p.9)   delta -24 uA
VIL  Low-level input voltage   LMX1204 0.4 V  (p.7)   LMX2820 0.6 V  (p.9)   delta -0.2 V
```

Both are correct against the printed pages. Two rows of 261 is not a delta
table anyone would design against, and LMX1204 (a clock buffer) and LMX2820 (a
wideband synthesizer) are not one series in any sense a hardware engineer would
accept - they are two products that happen to share TI's document template.
Declaring them would satisfy a checklist and mislead a reader, so the probe is
recorded and the registry is unchanged.

**What would close it is unchanged**: a vendor family whose members are device
*options* - same parameter, same printed conditions, same column, different
number. This fleet contains no such pair. That is a fact about which 25 parts
were onboarded rather than about the family builder, and it is the honest
reason ticket 08's third checklist item does not fully pass.

---

## Cards: a `limits` margin compares the two tops and says nothing about the two bottoms

**Re-measured 2026-09-02, narrowed from an entry that is now closed.** The
entry that stood here — "`si_delta` reads a range as its low end, and prints
`0` for a real difference" — is **fixed**, not parked. `dsa compare
QPA1003P QPA2213` published `0 degC` for Storage Temperature (`-55 to 150 degC`
against `-55 to +125 degC`) *and* flagged the row `identical`; the second of
those was not recorded here and was the worse claim. `derive/compare.py`
now subtracts a range only where the difference is the same at both ends, and
refuses with a sentence otherwise. Blast radius before and after, all 300 pairs
of the 25-part fleet: 67,920 aligned rows, 589 published deltas, 335 (row,
column) cells carrying a `value_si_hi`, **one** delta computed from a collapsed
range — this one, and it was wrong. After: 588 deltas, zero from a collapsed
range. `dsa compare` publishes one fewer number fleet-wide, which is the
better number. `dsa diff-rev` shares the same function and inherits it.

**What survives is narrower and is a different rule.** `derive/cards.py`'s
`compute_margin` — the `limits` card's `abs_max_margin` — subtracts
`Quantity.high` from `Quantity.high`: the *top* of the absolute-maximum side
minus the *top* of the recommended side. That is the right reading of "how
much headroom is there before the absolute maximum", and it is what the
column's name says it computes. But when **both** sides print a span in one
unnamed column, the cold end has a margin too and the card does not carry it:
an absolute-maximum `-55 to 150 degC` against a recommended `-40 to 85 degC`
prints `65 degC` and never mentions that the low-end headroom is `15 degC`.
That is incomplete, not wrong, and it is why this is an entry rather than a
second fix.

**Measured, 2026-09-02.** Across all 25 parts, the `limits` cards publish
**9** margin rows in total, and **0** of them have a range on either side.
The residue is currently inert; it is recorded because the population that
would exercise it — a vendor printing both its absolute-maximum and its
recommended tables one column wide, with spans in both — is exactly the shape
Qorvo prints, and the fleet gains Qorvo parts.

**What would close it.** A second derived cell (`margin_low`) beside `margin`
on the rows where both sides parsed as ranges, named in the column header so
it cannot be read as the same quantity, plus the `DSA_CARD_VERSION` bump ADR
0007 requires for a derivation-rule change and a rebuild of the 9 rows. It was
not done in the same commit as the `si_delta` fix because it changes a card
that is on disk and this one does not: `si_delta` is computed at compare time
and written to no artifact.

**Two related collapses were checked and are not defects.**
`structure/quantities.annotate_record` reads a range in a `typ` cell as its
low end for `typ_si` (96 such cells fleet-wide, almost all of them misparses
of things like `10-18` for 10^-18 and `0.5*P - 3`); nothing in the tree
computes with `typ_si`, so it is published beside the verbatim print and read
by a human. The family index (`families/build.py`) goes through
`compare_specs` and inherits the fix; the reference family `AFE795x` carries
384 delta rows, **0** delta cells and **0** range-carrying cells, so its
`family.json` is unchanged by this fix and was not rebuilt.
