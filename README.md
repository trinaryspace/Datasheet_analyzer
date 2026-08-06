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
  `specs.json`, `plots.json` + `figures/` image files, and `manifest.json`.
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
# (no golden_qa_AFE7953.yaml exists — `dsa verify --part AFE7953` fails
# loudly instead of running another part's benchmark; per-part goldens
# live in tests/fixtures/golden_qa_<PART>.yaml)

# Non-TI part: vendor detected and pinned from page-1 brand text, built
# and verified fully offline through the pdf_layout floor
dsa build ad9081.pdf --part AD9081 --vendor adi         # ADI part, explicit pin
dsa verify --part AD9081 --pdf tests/fixtures/pdf/ad9081.pdf --specs
# (A brand-less PDF pins --vendor unknown instead — see the LM741 gate fixture)

# One invocation builds every PDF in a directory as its own part corpus
# (part = uppercase filename stem; flat scan; failing jobs are isolated)
dsa batch datasheets/
```

Useful flags: `build --no-cache` (re-extract), `build --no-llm` (deterministic
descriptions even with a key set); `batch` accepts the same `--no-cache` /
`--no-llm` options.

## Using the corpus

### Ask a parametric question (cheapest: ~2.5k tokens)

```bash
dsa query --part AFE7950 --symbol DACRES
# DAC resolution (DACRES): 14 bits — §4.5, p.7 [table 0 row 0]

dsa query --part AFE7953 --symbol DACRES
dsa query --part AFE7950 --section 4.10 --name SYSREF
```

Filters (`--symbol`, `--name`, `--section`) are AND-ed, case-insensitive
substrings. Answers carry verbatim values, units, conditions, footnote
markers, and page cites.

### Find a plot

```bash
dsa plots --part AFE7950 --q "Output Fullscale"
dsa plots --part AFE7950 --q "Gain Error" --section 4.12.1
dsa plots --part AFE7950 --tag "tx,800mhz"
```

Returns matching `plots.json` records (caption, conditions, section, page,
and the image file path under `figures/`) for an agent to open.

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
    └── plots.json         # searchable plot catalog + file map
```

Every answer should quote values **with units** and cite `p.N` from the
section header.

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
dsa status    # config, LLM availability, built parts + per-doc extraction stats
dsa version
```

## Configuration

Environment variables (prefix `DSA_`, or `.env` file):

| Variable | Default | Purpose |
|---|---|---|
| `DSA_PARTS_DIR` | `parts` | where corpora are written |
| `DSA_CACHE_DIR` | `.cache` | HTTP + extraction caches |
| `DSA_INDEX_TOKEN_BUDGET` | `3000` | hard INDEX.md budget |
| `DSA_LLM_DESCRIPTIONS` | `true` | use LLM for INDEX descriptions |
| `DSA_MODEL` | `claude-haiku-4-5` | Anthropic model for descriptions |
| `ANTHROPIC_API_KEY` | — | enables LLM enrichment |
| `DSA_PLOT_IMAGE_DPI` | `150` | DPI for PDF-rendered plot fallback |

Token counts everywhere are `chars/4` (see `tokens.py`).

## Development

```bash
python -m pytest tests/ -q    # 342 tests, ~85 s, fully offline (the
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
each have their own, all verified 100% offline). `dsa verify --part X`
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