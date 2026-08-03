# Phase 1 Report — AFE7950 Corpus, Verified End-to-End

**Status: complete. Numbers below are the Phase 1 snapshot (105 tests,
golden Q&A 12/12). The current repo suite is 214 tests / 19 golden questions
— Phases 2 and 3 shipped on top (see `PHASE_2_REPORT.md`, `PHASE_3_REPORT.md`).**

Phase 1 turns the 146-page AFE7950 datasheet (SBASA41E, 16.9 MB PDF) into a
**token-efficient, citation-verified markdown corpus** that any agent can
navigate with an index file + grep/read — never a full 46k-token dump.

```
parts/AFE7950/
├── INDEX.md                 2,460 tokens — the always-loadable artifact
├── sources.json             doc inventory: sha256 identity, type, revision
├── manifest.json            machine-readable section map + stats
└── docs/datasheet-c1b4663b/
    ├── sections/*.md        39 atomic sections, page-anchored
    └── tables/*.csv         15 machine-readable table twins
```

## Reproduce (Git Bash on Windows; use `.venv/Scripts/dsa.exe` without activation)

```bash
uv venv --python 3.10 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
source .venv/Scripts/activate
dsa build afe7950.pdf --part AFE7950          # ~2 min first run (fetches TI pages, cached forever)
dsa verify --part AFE7950 --pdf afe7950.pdf   # golden Q&A + token economics
python -m pytest tests/                       # 105 tests at the time, ~8 s, fully offline
python -m ruff check src tests                # clean
```

LLM-written INDEX descriptions were already wired (`LLMWriter`, one batched
call) but this build ran **deterministic** — no `ANTHROPIC_API_KEY` on the
machine. Drop the key into `.env` and re-run `dsa build` (no flags) to upgrade.

## Results

### Corpus stats (from manifest.json)

| Metric | Value |
|---|---|
| Sections | 39 (100% of content sections; cover page correctly excluded) |
| Parametric tables | 15 atomic, span-expanded, each with conditions + footnotes inline |
| Figures cataloged | 514 plots with captions + conditions (pixels came in Phase 3) |
| Footnotes | 20, **0 orphan citations** (every marker in every table resolves) |
| Sections with page ranges | **39/39** (reconciled from the PDF's printed TOC) |
| Tables with exact page pinned | 12/15 (located in PDF page text; rest stay honestly at section range) |
| Corpus tokens | 46,073 (vs ~66k raw PDF text) |
| INDEX.md tokens | **2,460** (budget 3,000, enforced by staged degradation) |

### Golden Q&A verification — 12/12 (100%)

Each of the 12 questions (`tests/fixtures/golden_qa.yaml`, answers verified
against the printed PDF by hand) is checked twice, deterministically:
the corpus section covering the cited page must contain the answer values,
**and** the cited PDF page itself must contain them. (The set has grown to
19 questions across Phases 2–3.)

| # | Question | Cite | Result |
|---|---|---|---|
| 1 | DAC resolution? (14 bits) | p.7 | pass |
| 2 | TX DSA range + analog step? (40 dB, 1.0 dB) | p.7 | pass |
| 3 | DSA step accuracy after calibration? (±0.1 dB, footnote-conditioned) | p.7 | pass |
| 4 | SerDes standards + max rate? (JESD204B/C, 29.5 Gbps) | p.1 | pass |
| 5 | Min SCLK period, register write? (25 ns) | p.27 | pass |
| 6 | Junction-to-ambient thermal resistance? (16.2 °C/W) | p.6 | pass |
| 7 | VCO count + coverage? (4 VCOs, 7.2–12.08 GHz) | p.18 | pass |
| 8 | Abs-max peak RF input @830 MHz? (16.7 dBm) | p.4 | pass |
| 9 | SYSREF setup/hold? (50 ps) | p.27 | pass |
| 10 | Package? (17×17 mm FCBGA, 0.8 mm pitch) | p.1 | pass |
| 11 | Max RX bandwidth? (1200/600 MHz, FB-conditional) | p.1 | pass |
| 12 | TX/RX RF range? (600 MHz–12 GHz) | p.1 | pass |

### Token economics (measured on the built corpus)

| Strategy | Tokens/question |
|---|---|
| Naive full-corpus dump | 46,081 |
| **This corpus (INDEX.md + one section)** | **4,256 avg / 8,402 worst** |

**10.8× cheaper on average, 5.5× in the worst case** — before the
`specs.json` lookup path (Phase 2, ~2.5k for known parametric questions).

### What a section file looks like (4.5, p.7–13)

Every parametric row keeps its parameter (rowspan-expanded), its per-row
test conditions, and its footnote markers glued to values; the conditions
preamble and footnotes travel with the table:

```
| ATTstep | DSA Attenuation step accuracy (DNL) | 0 < Atten < 40dB, after calibration |  | ±0.1 |  | dB |
| ATTphase-err | DSA Gain Steps Phase accuracy, any 8dB range | fout = 850MHz(2) |  | ±1 |  | deg |

**Footnotes:**
- (2) After DSA calibration procedure
```

## Test infrastructure — 105 tests, mapped to pain points

Fully offline: TI pages replayed from `tests/fixtures/recorded_http/`
(41 files, `ReplayFetcher` hard-fails on any unrecorded URL); synthetic PDFs
are manufactured in-test with PyMuPDF; LLM is injected as `FakeClient`.

| Pain point | Tests | Proof |
|---|---|---|
| Merged cells corrupt param/value association | 14 (`test_tables.py`) incl. real 204-row/73-rowspan TI table | exact golden values asserted |
| Footnote → value association lost | 9 (`test_footnotes.py`) + whole-corpus orphan audit | 0 orphans on real build |
| Table split from conditions/header | 6 (`test_corpus.py`) | atomicity contract pinned |
| Boilerplate inflates tokens | 6 (`test_boilerplate.py`) | real TI footer block |
| Wrong page citations | 9 (`test_pagemap.py`) + 12 golden page-truth checks | 39/39 sections mapped |
| Reading order scrambled | corpus + TOC tests | source order pinned |
| INDEX.md bloats / descriptions uninformative | 7 (`test_index.py`) | staged budget degradation; description content asserted |
| Stale cache | 4 (`test_cache.py`) | hash/backend keying pinned |
| Multi-doc part model | `test_manifest.py::test_multi_doc_part` | datasheet + register_map layout |
| Manifest integrity | 5 (`test_manifest.py`) | every referenced file exists |
| Units/unicode mangled | table + corpus tests | Ω(U+2126), °C, µA, ±, – preserved |
| End-to-end on real datasheet | 9 (`tests/integration/`) | full build + 12/12 golden |

### Bugs the tests caught during development (why this infrastructure matters)

1. **Data loss via "bare page number" boilerplate rule** — would have deleted
   real spec values (`1` ms RESETZ timing). Caught by `test_boilerplate`;
   rule removed, regression pinned.
2. **Negative-budget truncation** (`text[:-3]` ≈ no truncation) — INDEX.md
   budget silently unenforced. Caught by `test_index`.
3. **List-aliasing mutation** — INDEX.md rendered the same blocks 8× over.
   Caught by `test_index` budget assertion.
4. **TI cover page parsed as a content section** (phantom `1.md`, one
   unmatched page anchor). Caught by TOC/page-coverage assertions.
5. **Empty layout tables** (`frame-none` furniture) parsed as parametric
   tables in plot sections. Caught by build-shape assertions.
6. **Revision-history pages use `h1` + id-less containers** — section
   silently dropped. Caught by 39/40 page-coverage check; last-resort
   container fallback added and pinned.
7. **Nested feature bullets flattened** (bandwidth conditions merged into
   one unreadable line). Caught by INDEX.md review; per-`li` splitting +
   indentation pinned by test.
8. **Ohm sign is U+2126, not U+03A9** — verbatim preservation locked in by
   test (unit canonicalization shipped in Phase 2 `specs.json`).

## Known limitations (deliberate Phase 1 scope, later phases closed these)

- **Plots were cataloged, not rendered.** 514 figures had captions +
  conditions + image URLs; pixels and vision reads shipped in Phase 3.
- **Table page pinning is 12/15**; unpinned tables honestly keep
  section-level ranges rather than guess.
- **TI-only content path.** Other vendors fall back to a PDF backend
  (MinerU/docling) — extraction interface is already pluggable; `pdf_text`
  shipped in Phase 3.
- **Descriptions were deterministic** until an Anthropic key is provided;
  `LLMWriter` is implemented, tested with `FakeClient`, and falls back
  safely on any failure.
- PyMuPDF is AGPL-3.0 (used for TOC/identity/verification, not content
  extraction) — fine for local research, review before commercial use.

## Phase 2 hooks (all landed)

- `specs.json`: parametric tables are span-expanded grids with
  conditions/footnotes/page refs — normalization was a pure transform.
- Golden Q&A harness (`dsa verify`) is the objective function for every
  change; no public datasheet benchmark exists, so the set keeps growing.
- `docs/<type>-<hash>/` layout accepts register maps/errata with zero
  redesign (multi-doc manifest test green since Phase 1).