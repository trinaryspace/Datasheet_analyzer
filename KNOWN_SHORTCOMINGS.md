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

The five entries after them come from the phase 7 port and are a different
kind: each names a mechanism that is built, tested and **unexercised against
the thing it was built for** — a live upstream, a real vendor errata sheet, a
twenty-part fleet, a human confirming a generated question, a family whose
members print one parameter differently. They are recorded here rather than
reported as met.

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
- `RevisionState` **reaches the workbench API and nothing renders it.** The
  integration wave put the whole reading on `LibraryDocumentOut` (and its
  TypeScript twin) rather than a flattened `staleness` string, so
  `GET /api/library` now carries `staleness`, `checked_at`,
  `upstream_revision`, `content_drift` and the verbatim `note` for every
  document. No pane reads them: `DocumentRow`'s meta line is a fixed four-span
  list and its three sections are applicability, labels and parts-reached.
  Surfacing it needs a badge component and a place to put it — real frontend
  work, deliberately not started here. The CLI, the corpus files and MCP
  carried it already.
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

**Still parked, and now the only thing standing between a browser user and a
family: the family scope is nameable everywhere and offered nowhere.**
`ScopeRef.kind` is `part | project | family`, `deps.get_retriever` resolves a
family, `POST /api/chat/{id}/message` answers a whole series with the
common-once collapse, and — since 2026-09-02 — the chat agent has a
`get_family_index` tool that maps the series its turn was scoped to. All of
that is reachable **only by a client that posts
`ScopeRef(kind="family", name=...)` itself.** Nothing in the running UI does.

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
