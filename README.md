# datasheet-analyzer

Turn big IC datasheets into a **token-efficient, citation-verified markdown
corpus** that AI agents navigate with an index file + grep/read — instead of
loading 46k+ tokens of raw PDF text into context.

Reference part: TI AFE7950 (SBASA41E, 146-page PDF). A built corpus for this
part answers golden-Q&A questions at **~3.7k tokens average** vs **~46k** for a
full-text dump, with every answer traceable to a printed page number.

## What it does

Pipeline: `PDF → acquire → extract → structure → enrich → publish → eval`

- **Extract** — primary backend pulls TI's document-viewer HTML (real tables,
  MathML, footnotes — no OCR, no hallucination). A degraded `pdf_text` backend
  handles register maps / errata / app notes (paragraphs only).
- **Structure** — HTML tables become atomic, span-expanded blocks with their
  conditions preamble and footnotes attached; sections get page ranges from
  the PDF's printed TOC; tables get exact pinned pages where possible.
- **Enrich** — an `INDEX.md` under a hard token budget (default 3,000). An LLM
  writes only the section descriptions (optional); all corpus content is
  verbatim-extracted. Without an API key, descriptions are deterministic.
- **Publish** — per-section markdown files with CSV twins of every table,
  `specs.json` (619 machine-queryable parametric records), `plots.json` +
  image files for all 514 cataloged figures, and a `manifest.json`.
- **Eval** — `dsa verify` runs a golden Q&A set: every answer must appear in
  the corpus section covering the cited page **and** in the cited PDF page
  itself, plus deterministic spec-query and plot-query checks.

## Install

Requires Python ≥ 3.10. Windows PowerShell, using [uv](https://docs.astral.sh/uv/):

```powershell
uv venv --python 3.10 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
```

This installs the `dsa` CLI at `.venv/Scripts/dsa.exe`.

Optional: put `ANTHROPIC_API_KEY=...` in a `.env` file to enable LLM-written
INDEX descriptions (one batched call per build; falls back safely without it).

## Quickstart

```powershell
# Build the corpus (first run fetches TI pages + plot images, cached forever)
.venv/Scripts/dsa.exe build afe7950.pdf --part AFE7950

# Verify against the golden Q&A set (citations + page truth)
.venv/Scripts/dsa.exe verify --part AFE7950 --pdf afe7950.pdf

# Also verify deterministic spec lookups
.venv/Scripts/dsa.exe verify --part AFE7950 --pdf afe7950.pdf --specs
```

Useful flags: `build --no-cache` (re-extract), `build --no-llm` (deterministic
descriptions even with a key set).

## Using the corpus

### Ask a parametric question (cheapest: ~2.5k tokens)

```powershell
.venv/Scripts/dsa.exe query --part AFE7950 --symbol DACRES
# DAC resolution (DACRES): 14 bits — §4.5, p.7 ...

.venv/Scripts/dsa.exe query --part AFE7950 --section 4.10 --name SYSREF
```

Filters (`--symbol`, `--name`, `--section`) are AND-ed, case-insensitive
substrings. Answers carry verbatim values, units, conditions, footnote
markers, and page cites.

### Find a plot

```powershell
.venv/Scripts/dsa.exe plots --part AFE7950 --q "Output Fullscale"
.venv/Scripts/dsa.exe plots --part AFE7950 --q "Gain Error" --section 4.12.1
.venv/Scripts/dsa.exe plots --part AFE7950 --tag "tx,800mhz"
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

```powershell
.venv/Scripts/dsa.exe add-doc register_map.pdf --part AFE7950 --type register_map [--nda]
.venv/Scripts/dsa.exe build afe7950.pdf --part AFE7950   # rebuild picks it up
```

Types: `register_map`, `errata`, `app_note`, `datasheet`. Companions extract
with the honest `pdf_text` backend (paragraphs only; no trusted tables, no
`specs.json`) and join the same `INDEX.md`.

### Other commands

```powershell
.venv/Scripts/dsa.exe status    # config, LLM availability, built parts
.venv/Scripts/dsa.exe version
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

```powershell
.venv/Scripts/python.exe -m pytest tests/ -q    # 213 tests, ~8 s, fully offline
.venv/Scripts/python.exe -m ruff check src tests
```

Tests are hermetic: TI pages replay from `tests/fixtures/recorded_http/`
(unrecorded URL = hard error), synthetic PDFs are built in-test with PyMuPDF,
and the LLM is a fake client. Integration tests use the real `afe7950.pdf`
(skip-guarded) plus recorded fixtures.

`tests/fixtures/golden_qa.yaml` is the objective function: 19 questions with
hand-verified answers and page cites, covering direct corpus reads, spec
queries, and plot queries. Extend it when new answer paths ship; `dsa verify`
must stay at 100% for supported paths.

## Caveats

- **Content path is TI-specific.** Other vendors need a new extraction
  backend (`ExtractionBackend` protocol in `extract/base.py`); non-datasheet
  PDFs already work via `pdf_text`.
- Table page pinning is exact where the table is locatable in PDF page text;
  otherwise the table honestly keeps its section-level page range.
- Spec values are verbatim strings — no float parsing or numeric comparison.
- **PyMuPDF is AGPL-3.0** (used for TOC/identity/verification, not content
  extraction). Fine for local research; review before commercial use.

## Repository docs

- `AGENTS.md` — architecture contract, invariants, module map
- `PHASE_1_REPORT.md` / `PHASE_2_REPORT.md` / `PHASE_3_REPORT.md` — measured
  results per phase
- `PHASE_2_PLAN.md` / `PHASE_3_PLAN.md` — execution plans
