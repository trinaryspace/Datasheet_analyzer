# PHASE 6.5 REPORT — Extraction Fidelity

**Status: landed.** Supersedes `Reports/PHASE_6_5_PLAN.md`. Tickets
`.scratch/extraction-fidelity/issues/01–09`; wave 1's own write-up is
`Reports/PHASE_6_5_WAVE_1_REPORT.md`.

Every number below was measured on this tree after the wave-2 rebuild — a full
re-extract at extractor `tables-09` and a rebuild of all **eleven** parts at
pipeline **0.5.0**. Nothing is carried forward from phase 6.

## What this phase was for

Phase 6 shipped its gate 8/8 and recorded ten shortcomings, and reading them
together showed how few root causes there were: six of the ten traced to two
files and the largest four to one. This phase changed nothing about what the
tool *offers* — no new artifact, no new CLI verb, no new MCP tool — and made
the layer under the derived artifacts read the page correctly.

**Five of the ten shortcomings are closed.** Two survive with re-measured
figures, three were re-measured and closed as either fixed or not-a-defect, and
**two new ones were found by the rebuild itself** and are recorded rather than
left to be discovered.

## Acceptance gate — every item, measured

| # | Gate | Result | Measured |
|---|---|---|---|
| 1 | `--json` parses on every verb that offers it | **PASS** | **8/8** verbs parse (`query`, `search`, `ask`, `plots`, `pins`, `regs`, `card`, `compare`) |
| 2 | `dsa plots` takes `--x-label` / `--y-label` / `--near-x` / `--near-y`; the worked example returns its figure | **PASS** | all four flags present; `--near-x 3.5GHz --y-label Gain` returns **2** figures on HMC520A (Figures 77 and 78, *Conversion Gain vs. IF Frequency*, p.22). On AFE7950 the same query returns **0** — 43 figures match the label and 20 match the frequency, and no figure matches both, because AFE7950's gain figures plot against DSA setting rather than frequency. The filters work; that corpus has no such figure |
| 3 | A card whose document moved is rebuilt, not served stale; `audit_card` reports 0 problems | **PASS** | proved in `tests/unit/test_cards.py::TestCorpusKey`; **and the rebuild found the case the key cannot see** — see "What the rebuild found" below |
| 4 | `ruff format --check .` clean and part of the standing gate | **PASS** | clean — **196** files across `src`, `tests` and `scripts`, **311** over the whole tree; the gate is now written into `AGENTS.md`'s commands and definition of done, which wave 0's reformat commit had left undone |
| 5 | `LMX1204_registermap.pdf` publishes `registers.json` with all 35 registers from its own `Table 1-1` | **PASS** | **35** records, all on its page 2, first row `0x0`/`R0` — the cell the furniture detector used to eat. LMX1204 now publishes **70** registers over **2** sets |
| 6 | Table recall on that document ≥ 28/35 at 100% precision | **PASS** | **30/35** field tables handed over (was 12). Precision **100%**: all **71** emitted field cells are printed in the document, and the six registers with hand-transcribed truth match cell for cell |
| 7 | HMC520A publishes its 24 pins | **PASS** | **24** pins — ground 5, rf 4, nc 15 — every one carrying its printed page |
| 8 | Every row of LMX1204's `Table 7-1` cites the page it is printed on | **PASS** | **0** of 35 rows cite a page they are not printed on (was 1). `0x5A`/`R90` cites p.33 and prints on p.33 |
| 9 | AD9081 549/549 distinct spec record ids; its interface card publishes the rows its selectors match | **PASS** | **549/549** distinct at specs schema 4; the interface card publishes **21** rows (was 1), including `JESD204B SERIAL INTERFACE RATE` and `JESD204C SERIAL INTERFACE RATE` |
| 10 | Every phase 6 gate at or above its recorded number | **PASS** | see the table below — none dropped, four improved |
| 11 | `pytest` offline and green; `ruff check` clean | **PASS** | see "Suite" below |

## Phase 6's gates, re-measured

| Phase 6 gate | Recorded then | Measured now |
|---|---|---|
| 1 — pins published or honestly absent; golden pin questions | AD9081 210, LMX1204 41; **2/2** | AD9081 **210**, LMX1204 **41**, **HMC520A 24 (new)**; **2/2** |
| 2 — package cross-check runs, mismatches reported not resolved | ran on 2 parts, 2 mismatches | ran on **3** parts, **2** mismatches (AD9081 declares 324 / table yields 210; LMX1204 declares 40 / yields 41) |
| 3 — register summary answers by address and name; bit fields pass or park | 35 registers; parked | **70** registers over two documents; **still parked** |
| 4 — every card value resolves to a record and a page | **288/288**, 0 violations | **310/310**, **0** violations |
| 5 — `parse_quantity` shapes table | 15 cases | **15** cases |
| 6 — `dsa compare AFE7950 AFE7953` | 742 rows, 380 deltas, coverage 415/459, 21+21 unparsed | **742** rows, **380** deltas, coverage **415/459**, **21+21** unparsed, `audit_comparison` **[]** |
| 7 — AFE7950 axis coverage ≥ 60% | **400/514 = 77.8%** | **400/514 = 77.8%**; AFE7953 **375/492 = 76.2%** |
| 8 — every golden path | corpus **90/90**, spec 28/28, plot 11/11, ask 8/8, search 4/4 with **2 blocked** | corpus **90/90**, spec **28/28**, plot **11/11**, ask **8/8**, search **6/6 with 0 blocked**, card **4/4** |

Nothing dropped. Gate 8's one recorded gap — AFE7950 and AFE7953 with no
search index — is closed, which is why `PARTS_WITHOUT_SEARCH` is now empty.

## The rebuild

Eleven parts, one extractor bump, one pass.

| Part | Documents | Backend | Sections | Specs | Pins | Registers | Figures |
|---|---|---|---|---|---|---|---|
| AFE7950 | 1 | ti_html | 39 | 619 | 0 | – | 514 |
| AFE7953 | 1 | ti_html | 39 | 536 | 0 | – | 492 |
| AD9081 | 1 | pdf_layout | 34 | 549 | 210 | – | 100 |
| LMX1204 | 2 | ti_html + pdf_layout | 78 | 827 | 41 | 70 | 34 |
| HMC520A | 1 | pdf_layout | 36 | 85 | 24 | – | 107 |
| lm741 | 1 | pdf_layout | 40 | 71 | 0 | – | 3 |
| QPA1003P | 1 | pdf_layout | 20 | 41 | 0 | – | 4 |
| PMA1-14LN+ | 1 | pdf_layout | 9 | 0 | 0 | – | 2 |
| ZX10R-2-183-S+ | 1 | pdf_layout | 2 | 0 | 0 | – | 0 |
| LHA-83W+ | 1 | pdf_layout | 5 | 0 | 0 | – | 0 |
| PSA-8A+ | 1 | pdf_layout | 5 | 0 | 0 | – | 0 |

Every `pdf_layout` document carries `extractor_version: tables-09`, and all
eleven parts carry `pipeline_version: 0.5.0`. (`ti_html` records no extractor
version of its own; that is the gap the cache finding below is about.) Spec record ids are **distinct within
every document of every part** — 619/619, 536/536, 549/549, 543/543, 284/284,
85/85, 71/71, 41/41.

The four Mini-Circuits parts build only with `--vendor unknown`. Vendor
detection pins them `ti` on no evidence, which routes their datasheet to the
`ti_html` backend and 404s on `ti.com`; pinned to `unknown` they read through
the layout floor. Recorded here because it is a real command a user has to
know, not a defect this phase fixed.

## What the rebuild found

Two things that only a rebuild could show, both now in `KNOWN_SHORTCOMINGS.md`.

### A structure-layer fix is invisible to a cached extraction

The extraction cache is keyed `(content_hash, backend)` and invalidated by the
backend's embedded `output_version` — invariant 6, working as written. But
per-row page pinning (`structure/pagemap.pin_table_row_pages`, ticket 07) runs
*inside* `pipeline._extract_document`, after the backend returns and before the
result is cached. It has no version of its own.

So bumping `output_version` re-extracted every `pdf_layout` document and left
every `ti_html` one — AFE7950, AFE7953 and LMX1204's datasheet — served from a
cache written before ticket 07 existed. **The first rebuild of LMX1204 still
showed the off-by-one row ticket 07 had fixed.** Only `dsa build --no-cache`
produced the corrected corpus: **484 of 501 rows pinned, 0 rows citing a page
they are not printed on.** All three `ti_html` documents were rebuilt that way.

### A card survives a rebuild in place

`corpus_key` (wave 0, ticket 03) keys a card on *where* its documents resolved,
which is exactly what a move changes and exactly what a rebuild in place does
not. AFE7950's power card survived the rebuild with a matching `corpus_key`,
`card_version` and `schema_version`, and **112 of its 143 filled values then
cited p.21 for a record the rebuilt corpus prints on p.22** — per-row page
pinning had moved them. `audit_card` caught it, which is the system working.

Fixed here, because a card citing the wrong page is the exact failure this
repository exists to prevent: `publish.retire_cards` removes a part's cards and
`build_part` calls it after publishing. Missing is a documented state that
rebuilds on demand; stale-but-current-looking is not.

## Two citations that were quietly wrong

Per-row page pinning corrected two page numbers that checked-in gates had
hand-verified against the wrong page. Both were re-verified against the PDFs
here before the expectations were rewritten:

- **LMX1204 `Low-level output voltage`** was cited on p.6 and is printed on
  **p.7** — `lmx1204.pdf` prints the label, `IOL = 5 mA` and `0.45` on page 7
  and on no other page. p.6 is where its table starts.
- **The 28 `Pdiss` rows of AFE7950 and AFE7953** all cited p.21. Section 4.9's
  table runs over six printed pages on AFE7950 and four on AFE7953; the rows
  now cite pages **21–26** and **21–24**, and every one of the 28 is verified
  against the page it names.

Neither was a number anybody would have doubted, which is the point.

## Register bit fields: re-attempted, still parked

The gate is the first six registers in printed order — R0, R2, R3, R4, R5, R6 —
at 100% with no partial credit. **Four of six are now read exactly right**
(R2, R3, R5, R6); phase 6 managed two. Four is not six, so nothing ships and
`RegisterRecord.fields` stays `[]` for every published register.

| | Phase 6 | Phase 6.5 |
|---|---|---|
| field tables handed over, of 35 printed | 12 | **30** |
| registers surviving validation | 4 | **15** (11% → **43%**) |
| fields emitted | 13 | **71** |
| the six-register sample | 2 | **4** |
| precision | 100% | **100%** |

The three misreads ticket 06 named are gone: R13 and R17 no longer read
`SYSREFREQ_DELAY_ST EPSIZE`, R19/R21/R25 are no longer truncated to their
first field, R12's header no longer swallows two body lines. **Twelve of the
fifteen remaining refusals are one new cause**: the document prints two
cross-reference sentences after every field table (`R<n> is shown in … Summary
Table`, `Return to the Summary Table`), the table region now runs on into them,
and they arrive as two rows whose bit cell is prose. The other three are
genuine — R4 and R9 print incomplete field lists, R90's two fields claim the
same eight bits.

One of ticket 06's three reasons to park is closed: the reference map's own
summary table is recovered, so there is now a record in that document to hang
fields off. Recall parks it now, alone.

## ADR 0008 — the corpus/pipeline version question, settled

`docs/adr/0008-tracked-corpora-are-current-and-self-contained.md` answers the
three questions the plan raised, and this phase acted on all three.

1. **A tracked corpus is at the current `PIPELINE_VERSION`.** A fixture built
   by an older pipeline has quietly stopped testing what it claims.
2. **`/library/` stays untracked; a committed corpus is published
   self-contained.** `.gitignore` already calls the library a local shelf, and
   on this machine it holds 200+ documents from a GUI test round. The mixture
   — gitignored store, committed manifests naming `@library/…` — is what
   commit `c1d6180` shipped and `a8f93f8` reverted, at a measured cost of
   3/21 and 1/13 on the golden corpus check.
3. **A corpus-reading gate skips when its corpus is absent or stale**, and one
   test that cannot skip asserts the tracked pair is current and readable from
   the part directory alone.

`dsa build --self-contained` is the mode that makes (2) executable, and
`tests/integration/test_corpus_currency.py` is (1) and (3).

**The tracked corpora were rebuilt and committed** (`6837524`). That is the
decision with history: the same act was reverted once, and it is being done
differently — self-contained rather than into the shared store, so a fresh
clone can read every section, spec, plot and search index of both parts
without a library it does not have. The diff is 40 files; 514 figures and most
section markdown came back byte for byte.

`/parts/*/cards/` is now gitignored: a card is a derived cache the build
retires and the reader rebuilds, not something a citation lands on.

## Shortcomings: what closed, what survives

**Closed and deleted** (closing number in brackets):

| Entry | Closed by | Closing number |
|---|---|---|
| HMC520A's pin table is rejected whole | wave 1, ticket 06 | **24** pins published |
| AD9081's spec records are not individually addressable | wave 1, ticket 08 | **549/549** distinct ids; interface card 1 → **21** rows |
| The LMX1204 register map's own summary table is not read | wave 1, ticket 05 | **35** registers from `Table 1-1` |
| An HTML-derived table gives every row the page it starts on | wave 1, ticket 07 | **0** of 35 rows mis-cited; 484/501 rows pinned document-wide |
| A published card is not invalidated when its document moves | wave 0, ticket 03 | `corpus_key`; `audit_card` 0 problems after a move |
| The axis filters are reachable from MCP but not from the CLI | wave 0, ticket 02 | four flags on `dsa plots`; worked example returns 2 figures |
| AFE7950/AFE7953 reference a library that holds only their figures | wave 2, ADR 0008 | both self-contained at 0.5.0; search goldens 4/4+2 blocked → **6/6** |

**Survives, with a re-measured figure:**

- **AFE7950 and AFE7953 publish no pin table** — the datasheets print none.
  Re-measured: **0** pins each, unchanged. Closed only by a document revision.
- **No built part prints a zero-margin parameter** — re-measured across all
  eleven parts: **6 comparable rating/recommended pairs, 0 of them equal**
  (AFE7950 and AFE7953's `TJ` at 40 °C margin and `DVDD0P9` at 0.25 V, plus
  LMX1204's supply voltage at 0.15 V and its `TJ` at 25 °C, which are new
  because LMX1204 was not built when phase 6 recorded the entry). The
  assertion over real data holds vacuously and starts reporting the moment
  such a part is added.
- **Register bit fields** — re-measured at 43% recall / 100% precision, four of
  six on the sample. Parked.

**New, found by the rebuild:**

- **A register record id repeats across a part's two documents.** LMX1204's
  datasheet and register map both print the same 35-register summary, so the
  part publishes 70 records carrying **35** ids, each carried by one record in
  each document. Resolution is per-document and correct; a consumer passing
  both roots as a list gets the first. `dsa regs --addr 0x11` answers twice,
  each hit citing its own document and page.
- **A structure-layer fix is invisible to a cached extraction** — see above.

## Suite

- `python -m pytest tests/ -q` — **2408 tests, 0 failures, 0 errors, 34
  skipped**, 557 s, fully offline (integration alone: 279 tests, 0 failures,
  2 skipped).
- `python -m ruff check src tests` — clean.
- `python -m ruff format --check .` — clean: **196** files across `src`,
  `tests` and `scripts`, **311** over the whole tree.

## What a reader should not conclude

- **Recall is not correctness everywhere.** The bit-field reader is at 43%
  recall precisely because it refuses everything it cannot prove. The number to
  watch is precision, and it is 100% over 71 fields.
- **`dsa regs` answering twice for LMX1204 is not a bug being hidden.** Both
  answers are true and each cites its own printed page; it is recorded as a
  shortcoming because two answers to one question is worse than one.
- **The tracked corpora being current is a standing cost, not a one-off.**
  Every future change that alters published output owns their rebuild, which
  is roughly twenty minutes of figure fetching per reference part. That is
  written into `AGENTS.md`'s definition of done.
