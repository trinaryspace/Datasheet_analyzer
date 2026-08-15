# datasheet-analyzer

Turn big IC datasheets into a **token-efficient, citation-verified markdown
corpus** that AI agents navigate with an index file + grep/read — instead of
loading tens of thousands of raw-PDF tokens into context.

Two reference parts are built and verified in this repo:

| | AFE7950 (SBASA41E) | AFE7953 (SBASAN1A) |
|---|---|---|
| PDF | 146 pages | 134 pages |
| Sections | 39 | 39 |
| Tables (atomic) | 15 | 14 |
| Figures → image files | 514 | 492 |
| `specs.json` records | 619 | 536 |
| Corpus tokens | 46,073 | 39,033 |
| INDEX.md tokens | 2,469 / 3,000 | 2,522 / 3,000 |

A golden Q&A set (19 questions, answers hand-verified against the printed
PDF) passes at ~2.5k tokens for parametric lookups, ~4.3k average for direct
section reads, and ~4k for plot lookups — vs ~46k for a full-text dump —
with every answer traceable to a printed page number.

## What it does

Pipeline: `PDF → acquire → extract → structure → enrich → publish → eval`

- **Extract** — TI datasheets use TI's document-viewer HTML (real tables,
  MathML, footnotes — no OCR, no hallucination); every other vendor and
  era routes to a vendor-neutral offline layout engine (`pdf_layout`,
  PyMuPDF-only, zero vendor assumptions — tables, specs, plots, page
  citations straight from the PDF). A degraded `pdf_text` backend handles
  register maps / errata / app notes (paragraphs only).
- **Structure** — HTML tables become atomic, span-expanded blocks with their
  conditions preamble + footnotes attached; sections get page ranges from the
  PDF's printed TOC; tables get exact pinned pages where possible.
- **Enrich** — an `INDEX.md` under a hard token budget (default 3,000). An
  LLM writes only the section descriptions (optional); all corpus content is
  verbatim-extracted. Without an API key, descriptions are deterministic.
- **Publish** — per-section markdown with CSV twins of every table,
  `specs.json`, `plots.json` + `figures/` image files, a `search_index.json`
  BM25 index per document, and `manifest.json`.
- **Eval** — `dsa verify` runs the golden Q&A: every answer must appear in the
  corpus section covering the cited page **and** in the cited PDF page itself,
  plus deterministic spec-query and plot-query checks.

## Install

Requires Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/). Commands below
are for Git Bash on Windows:

```bash
uv venv --python 3.10 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
source .venv/Scripts/activate   # puts `dsa` and `python` on PATH
```

If you skip the activation line, call `.venv/Scripts/dsa.exe` and
`.venv/Scripts/python.exe` directly — all commands below work either way.

Optional: put `ANTHROPIC_API_KEY=...` in a `.env` file to enable LLM-written
INDEX descriptions (one batched call per build; falls back safely without it).

## Quickstart

```bash
# Build the corpus (first run fetches TI pages + plot images, cached forever)
dsa build afe7950.pdf --part AFE7950

# Verify against the golden Q&A set (citations + page truth)
dsa verify --part AFE7950 --pdf afe7950.pdf

# Also verify deterministic spec lookups
dsa verify --part AFE7950 --pdf afe7950.pdf --specs

# Second reference part, same build path
dsa build afe7953.pdf --part AFE7953
dsa verify --part AFE7953 --pdf afe7953.pdf --specs
# (per-part goldens live in tests/fixtures/golden_qa_<PART>.yaml; `dsa verify`
# resolves a part's own benchmark and fails loudly when it is missing, rather
# than running another part's)

# Non-TI part: vendor detected and pinned from page-1 brand text, built
# and verified fully offline through the pdf_layout floor
dsa build ad9081.pdf --part AD9081 --vendor adi         # ADI part, explicit pin
dsa verify --part AD9081 --pdf tests/fixtures/pdf/ad9081.pdf --specs
# (A brand-less PDF pins --vendor unknown instead — see the LM741 gate fixture)

# One invocation builds every PDF in a directory as its own part corpus
# (part = uppercase filename stem; flat scan; failing jobs are isolated;
#  unchanged parts skipped; parallel with --workers N, default 4)
dsa batch datasheets/
```

Useful flags: `build --no-cache` (re-extract), `build --no-llm` (deterministic
descriptions even with a key set); `batch` accepts the same `--no-cache` /
`--no-llm` options plus `--force` (rebuild even when up to date) and
`--workers N` (parallel jobs; `DSA_BATCH_WORKERS` env default, 1 = serial).

## Using the corpus

### Ask one question, get one cited answer (`dsa ask`)

```bash
dsa ask --part AFE7950 "max junction temperature" --budget 3000
## AFE7950 — SBASA41E (datasheet-c1b4663b)
### Answer
TJ  Junction temperature: 150 °C (max) — §4.1, p.4  [high]
TJ  Operating Junction Temperature: 110(1) °C (max) — §4.3, p.6  [high]
TJ  Maximum Operating Junction Temperature: 125 °C (min) — §4.3, p.6  [high]
TJ  Total Jitter Tolerance: 0.42 UI (max) — §4.8, p.20  [high]
### Supporting excerpt  (§4.1 Absolute Maximum Ratings, p.4)
## Unnumbered table > **Test conditions:** over operating free-air temperature
range (unless otherwise noted)(1) | | | MIN | MAX | UNIT | … | Supply Voltage
Range | DVDD0P9, VDDT0P9 | –0.3 | 1.2 | V | …
### Verify
Printed page 4 of afe7950.pdf.  Confidence: high.

dsa ask --part QPA1003P "where is the functional block diagram?" --json
```

That transcript is the command's own output on a freshly built AFE7950 corpus
(190 tokens), wrapped for this page with the middle of the excerpt row elided
at `…`. It is worth reading against the plan, which illustrated this question
with `105 °C — §4.3, p.6`: the AFE7950 prints its junction-temperature limit
in §4.1 Absolute Maximum Ratings on page 4, and the pack cites what the
datasheet prints, never what the example said. (A corpus built before
per-record grading landed answers the same rows graded `unknown` until it is
rebuilt.)

One call instead of three or four. Routing is **deterministic — no LLM is in
the path** — classified by feature hits in order:

| Feature in the question | Route |
|---|---|
| the alias ladder resolves it to spec records | `spec` |
| plot vocabulary (`plot`, `curve`, `vs`, `versus`, `graph`, `figure`, `diagram`) **and** a figure whose caption uses the question's words | `plot` |
| anything the full-text index ranks | `search` |
| nothing, and this corpus has no current full-text index | `unavailable` — rebuild to enable search (exit 2, as `dsa search` does) |
| nothing | `none` — an explicit no-match plus nearest candidates, never a guess |

The `unavailable` route is why an empty full-text result is never reported as
an answer: `search()` returns nothing both when nothing matched and when there
was no index to match against, and only the first of those is a statement
about the datasheet.

The pack is filled greedily against `--budget` (default `DSA_ASK_BUDGET`,
4000 tokens) over a **reserved tail** — the header, the first answer line and
the verify footer — so a budget can only ever cost extra rows and excerpt
prose. **Citations are never the truncated part**, and any truncation prints a
notice naming `--budget`. `--json` emits a shape with a declared schema
(`retrieve.pack.ANSWER_PACK_SCHEMA`).

### Ask a parametric question (cheapest: ~2.5k tokens)

```bash
dsa query --part AFE7950 --symbol DACRES
# DAC resolution (DACRES): 14 bits — §4.5, p.7 [table 0 row 0] [via symbol · high]

dsa query --part AFE7953 --symbol DACRES
dsa query --part AFE7950 --section 4.10 --name SYSREF
```

You do not have to know the datasheet's symbol. `--symbol` / `--name` take a
designer's words and run a resolution ladder — exact symbol, then alias phrase,
then alias prefix family, then substring, then a token-overlap fuzzy match —
and every answer reports the rung that found it:

```bash
dsa query --part AFE7950 --name "junction temperature"
# Junction temperature (TJ): 150 °C — §4.1, p.4 … [via alias:junction temperature · high]

dsa query --part AFE7950 --symbol IDD        # the whole IVDD* supply-current family
dsa query --part AFE7950 --name "junction temperature" --json
```

The synonyms live in `src/datasheet_analyzer/registry/aliases.yaml`; adding one
is a YAML edit, never a code change. `--section` still AND-s with the term.
A query that matches nothing says so and lists the nearest candidates in the
corpus — it never guesses. Answers carry verbatim values, units, conditions,
footnote markers, and page cites.

### Trust an answer: the confidence grade

Every spec and plot record is graded when the corpus is built, and the grade is
printed after the rung (`[via symbol · high]`) and returned in `--json`:

| Grade | What it means |
|---|---|
| `high` | pinned to an exact printed page, reconstructed from the table's own declared columns, and the row prints a value |
| `medium` | the page is a section range, or the row printed no value at all |
| `low` | the grid was rescued by the layout engine's retry ladder, or a value's unit is missing where its alias family expects one |
| `unknown` | ungraded — a corpus built before grading existed; rebuild it |

`low` is not "wrong": it is "open the printed page before you quote this". The
mix per part is recorded in `manifest.json` and printed by `dsa status`.

### Search the text (every hit already cited)

```bash
dsa search --part AFE7950 "sysref setup"
# 1. §4.10 SYSREF Timing — §4.10, p.31-33 [score 8.41 · via fulltext]
#    SYSREF setup time must be met for deterministic latency. …

dsa search --part AFE7950 "thermal pad" --limit 3
dsa search --part AFE7950 "dBc/Hz" --json
```

Ranked with BM25 over a `search_index.json` built at publish — no ripgrep, no
subprocess, no network. Every hit carries the section's page range **from the
manifest**, so a caller never attributes a page itself, plus a ±240-char
snippet grown to sentence boundaries.

The tokenizer is built for datasheets: no stemming, ASCII-only lowercasing (so
`Ω` U+2126 and `Ω` U+03A9 stay distinct, as does `RθJA`), and compound unit
strings index whole and split (`dBc/Hz` finds `dbc/hz`, `dbc` or `hz`). Bare
numbers are deliberately *not* indexed — `dsa query` is the exact-value path,
and a bare `105` ranks nothing. A corpus built before search existed says
"rebuild to enable search" instead of returning an empty result.

### Find a plot

```bash
dsa plots --part AFE7950 --q "Output Fullscale"
dsa plots --part AFE7950 --q "Gain Error" --section 4.12.1
dsa plots --part AFE7950 --tag "tx,800mhz"
dsa plots --part AFE7950 --q "Output Fullscale" --json
```

Returns matching `plots.json` records (caption, conditions, section, page,
confidence, and the image file path under `figures/`) for an agent to open.

### Read content by section

Load `parts/AFE7950/INDEX.md` first — it maps every section to its file and
page range within its token budget. Then grep/read the section files:

```
parts/AFE7950/
├── INDEX.md               # always-loadable index (hard budget, 3000 tok)
├── sources.json           # doc inventory: sha256, type, revision, nda flag
├── manifest.json          # machine-readable section map + stats
└── docs/datasheet-<hash8>/
    ├── sections/*.md      # atomic; `<!-- source: <doc> p.N[-M] -->` header
    ├── tables/*.csv       # machine-readable twins of each section table
    ├── figures/           # plot image files referenced by plots.json
    ├── specs.json         # parametric spec records (symbol/name/conditions/min/typ/max/unit/page)
    ├── plots.json         # searchable plot catalog + file map
    └── search_index.json  # BM25 index over sections/*.md (what `dsa search` ranks)
```

Every answer should quote values **with units** and cite `p.N` from the
section header.

### Group parts into a design (`dsa project`)

A **project** is the noun above `part`: an explicit list of parts plus the
free text that joins them, with one always-loadable `PROJECT_INDEX.md` for
the whole board.

```bash
dsa project new rf-frontend --interfaces "AFE7950 TX -> HMC520A DSA -> board edge"
dsa project add rf-frontend AFE7950 --role "quad RF transceiver"
dsa project add rf-frontend HMC520A AD9081
dsa project build rf-frontend        # writes PROJECT_INDEX.md under its budget
dsa project status                   # every project and its parts
```

```
projects/rf-frontend/
├── project.json        # name, parts[] (+ role), interfaces, notes, timestamps
└── PROJECT_INDEX.md    # always-loadable, hard budget (4000 tok)
```

Membership is explicit — no BOM or netlist parsing. A part with no built
corpus is refused with the build command that would fix it, so a project
never points at nothing. `project.json` is meant to be hand-edited: the
`interfaces` note and each part's `role` are yours, and a rebuild never
rewrites them.

Then ask the whole design one question. Every hit is labelled with the part
it came from, and a question two parts answer returns both:

```bash
dsa ask --project rf-frontend "does anything here need a 1.8 V rail?"
dsa search --project rf-frontend "sysref"
dsa query  --project rf-frontend --name "junction temperature"
dsa plots  --project rf-frontend --q "gain"
```

```
## rf-frontend — project (AFE7950, HMC520A, AD9081)
### Answer
[AFE7950] VDD1P8  1.8V supply: 1.75 V (min) — §4.3, p.6  [high]
[AD9081] VDD1P8  1.8 V supply: 1.75 V (min) — §Power Supply, p.9  [medium]
### Verify
AFE7950 — Printed page 6 of afe7950.pdf.  Confidence: high.
```

`--part` and `--project` are mutually exclusive, and one of them is required.

### Add companion documents

```bash
dsa add-doc register_map.pdf --part AFE7950 --type register_map [--nda]
dsa build afe7950.pdf --part AFE7950   # rebuild picks it up
```

Types: `register_map`, `errata`, `app_note`, `datasheet`. Companions extract
with the honest `pdf_text` backend (paragraphs only; no trusted tables, no
`specs.json`) and join the same `INDEX.md`.

### Other commands

```bash
dsa status    # config, LLM availability, built parts, per-part confidence mix
              # + per-doc extraction stats + projects
dsa version
```

## Configuration

Environment variables (prefix `DSA_`, or `.env` file):

| Variable | Default | Purpose |
|---|---|---|
| `DSA_PARTS_DIR` | `parts` | where corpora are written |
| `DSA_PROJECTS_DIR` | `projects` | where projects are written |
| `DSA_CACHE_DIR` | `.cache` | HTTP + extraction caches |
| `DSA_INDEX_TOKEN_BUDGET` | `3000` | hard INDEX.md budget |
| `DSA_ASK_BUDGET` | `4000` | default `dsa ask` pack budget (`--budget` overrides) |
| `DSA_PROJECT_INDEX_TOKEN_BUDGET` | `4000` | hard PROJECT_INDEX.md budget |
| `DSA_LLM_DESCRIPTIONS` | `true` | use LLM for INDEX descriptions |
| `DSA_MODEL` | `claude-haiku-4-5` | Anthropic model for descriptions |
| `ANTHROPIC_API_KEY` | — | enables LLM enrichment |
| `DSA_PLOT_IMAGE_DPI` | `150` | DPI for PDF-rendered plot fallback |

Token counts everywhere are `chars/4` (see `tokens.py`).

## Development

```bash
python -m pytest tests/ -q    # 600 tests, ~90 s, fully offline (the
                              # phase-4 gate builds four real PDFs)
python -m ruff check src tests
```

Tests are hermetic: TI pages replay from `tests/fixtures/recorded_http/`
(unrecorded URL = hard error), synthetic PDFs are built in-test with PyMuPDF,
and the LLM is a fake client. Integration tests use the real `afe7950.pdf` /
`afe7953.pdf` (skip-guarded) plus recorded fixtures.

Per-part goldens in `tests/fixtures/golden_qa_<PART>.yaml` are the
objective function: hand-verified answers and page cites covering direct
corpus reads, spec queries, and plot queries (AFE7950 carries the 19-Q
historical benchmark; the four gate parts AD9081/LM741/QPA1003P/HMC520A
each have their own, all verified 100% offline; AFE7953 has an 11-Q set
verified against the committed corpus + the skip-guarded PDF, because that
part has no offline build path). `dsa verify --part X`
discovers the part's golden by name and fails loudly when it is missing —
extend a set when new answer paths ship; `dsa verify` must stay at 100%
for supported paths.

## Caveats

- **Content path is vendor-neutral.** TI keeps its HTML viewer path;
  ADI / Qorvo / older TI / vendor N+1 datasheets route to the offline
  `pdf_layout` floor (PyMuPDF-only, no per-vendor layout rules — adding
  a vendor is a brand-lexicon data change, not engine code). Non-datasheet
  PDFs (register maps / errata / app notes) use `pdf_text` for any vendor.
- Table page pinning is exact where the table is locatable in PDF page text;
  otherwise the table honestly keeps its section-level page range.
- Spec values are verbatim strings — no float parsing or numeric comparison.
- **PyMuPDF is AGPL-3.0** — it is the engine behind the offline
  `pdf_layout` extraction floor, and TI's HTML path uses it for
  TOC/identity/verification. Fine for local research; review before
  commercial use.

## Repository docs

- `AGENTS.md` — architecture contract, invariants, module map
- `PHASE_1_REPORT.md` / `PHASE_2_REPORT.md` / `PHASE_3_REPORT.md` /
  `PHASE_4_REPORT.md` — measured results per phase (all four phases are
  shipped; PHASE 4 covers the vendor-neutral layout core + four-part gate)
- `PHASE_2_PLAN.md` / `PHASE_3_PLAN.md` / `PHASE_4_PLAN.md` — completed
  execution contracts, superseded by their reports