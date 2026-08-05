# AGENTS.md — datasheet_analyzer

Read this before writing any code in this repo. It is the architecture
contract: what exists, the invariants that must not be broken, and the
conventions every change must follow. Phases 1–3 are shipped; measured
results live in `PHASE_1_REPORT.md`, `PHASE_2_REPORT.md`, `PHASE_3_REPORT.md`
(the old `PHASE_2_PLAN.md` / `PHASE_3_PLAN.md` are superseded completion
records).

## What this is

Pipeline that turns big IC datasheets into a **token-efficient,
citation-verified markdown corpus** that agents navigate with an index file
+ grep/read instead of loading tens of thousands of raw-text tokens.

Reference parts (built corpora under `parts/`):

| Part | PDF | Revision | Pages | Sections | Specs | Figure files |
|---|---|---|---|---|---|---|
| AFE7950 | `afe7950.pdf` | SBASA41E | 146 | 39 | 619 | 514 |
| AFE7953 | `afe7953.pdf` | SBASAN1A | 134 | 39 | 536 | 492 |

Pipeline: `PDF → acquire → extract → structure → enrich → publish → eval`

## Commands (verified, Git Bash on Windows)

```bash
# setup (uv-managed venv; NO torch in this project — plain install is safe)
uv venv --python 3.10 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
source .venv/Scripts/activate       # puts `dsa` and `python` on PATH

# run
dsa build afe7950.pdf --part AFE7950                    # corpus + specs.json + plots.json
dsa build afe7953.pdf --part AFE7953                    # second reference part
dsa build ad9081.pdf --part AD9081 --vendor adi         # explicit vendor override (default: detected + pinned)
dsa batch datasheets/                                   # one part corpus per PDF in a dir (serial today)
dsa verify --part AFE7950 --pdf afe7950.pdf             # golden Q&A + token economics
dsa verify --part AFE7950 --pdf afe7950.pdf --specs     # + spec_query checks
dsa query --part AFE7950 --symbol DACRES                # deterministic spec lookup
dsa add-doc register_map.pdf --part AFE7950 --type register_map
dsa plots --part AFE7950 --q "Output Fullscale"
dsa status                                             # vendor + detection evidence + per-doc extraction stats

# test (fully offline, ~8 s)
python -m pytest tests/ -q
python -m ruff check src tests
```

Without activation, call `.venv/Scripts/dsa.exe` / `.venv/Scripts/python.exe`
directly — commands work the same in PowerShell. `uv`'s progress output goes
to stderr and shows as red text in PowerShell even on success — check exit
codes, not colors.

## Architecture

`src/datasheet_analyzer/`, src-layout, package `datasheet-analyzer`, CLI `dsa`.

| Module | Role | Key exports |
|---|---|---|
| `models.py` | **The contract.** Pydantic v2 models shared by all stages. Change deliberately. | `SourceDocument`, `TOCEntry`, `Footnote`, `TableBlock`, `FigureRef`, `SectionNode`, `RawDocument`, `SectionFile`, `CorpusManifest`, `CorpusStats`, `ExtractionStats`, `GoldenQuestion`, `DocType`, `SpecUnit`, `SpecRecord`, `SpecTableInfo`, `SpecSet`, `PlotRecord`, `PlotSet` |
| `config.py` | pydantic-settings, `DSA_` prefix; `ANTHROPIC_API_KEY` plain. No filesystem side effects at import. `PIPELINE_VERSION`, `SPECS_SCHEMA_VERSION`, `PLOTS_SCHEMA_VERSION` live here. | `Settings`, `get_settings()` (lru_cached; `reset_settings_cache()` for tests) |
| `tokens.py` | THE token counter (chars/4). Every reported token number flows through it. | `count_tokens`, `truncate_to_tokens` (budget ≤ 0 → `""`) |
| `acquire/inventory.py` | Part = folder of docs. `sources.json` per part; identity = sha256 of bytes; evidence-pinned vendor at acquire (detection or `--vendor` override). | `register_source`, `save_inventory`, `load_inventory`, `detect_doc_type`, `pin_vendor` |
| `vendor.py` | **Vendor routing record, not a rulebook**: profile registry (brand lexicon + backend preference chain), evidence-pinned detection on page-1 text/filename, drift warnings. Default `ti`; no layout behavior hangs off the vendor string. | `VENDOR_PROFILES`, `detect_vendor`, `select_backend`, `warn_vendor_drift`, `is_known_vendor` |
| `extract/base.py` | Backend protocol + registry. | `ExtractionBackend`, `register`, `get_backend` |
| `extract/pdf_structure.py` | PyMuPDF: content hash, page count, **printed TOC (authoritative page numbers)**, per-page text (verification/pinning only). Layout analysis lives in `pdf_layout`, never here. | `read_toc`, `page_texts`, `compute_content_hash`, `make_source`, `split_number` |
| `extract/http.py` | Fetchers. `CachingFetcher` (disk cache `.cache/http`), `CachingBinaryFetcher` (`.cache/http-bin`), `ReplayFetcher`/`ReplayBinaryFetcher` (hermetic tests: miss = hard error), `MappingFetcher`. | `Fetcher` / `BinaryFetcher` protocols |
| `extract/ti_html.py` | Primary TI content backend: TI document-viewer HTML (real tables, MathML, footnotes — no OCR, no hallucination). TI keeps this path; every other vendor routes to the layout floor. | `TiHtmlBackend`, `parse_toc`, `parse_section` |
| `extract/pdf_layout.py` | **Vendor-neutral layout floor** (offline, PyMuPDF-only): furniture by slot recurrence + universal page-machinery patterns (zero vendor strings), structure ladder (outline → printed-TOC dot-leader parse → per-page), page-ranged sections, honest unnumbered identity, (tickets 03–04) tables: caption-anchored hypotheses, pitch-based row grouping with wrapped-cell merging, header-anchored column clusters + a best-scoring retry ladder (every band set gated and scored; the header-declared edge share selects the winner, ties keep ladder order), a reconstruction gate (rejected hypotheses recorded with reasons in `ExtractionStats`), multi-page continuation merging, test-conditions preamble attachment, and (ticket 05) footnotes + figures: superscript citation markers from span font geometry (`_Span` carries size + glyph box; glued, raised, ≤0.82× markers land in `TableBlock.cited_markers`), trailing numbered lines attach as bare-canonical `Footnote`s with wrapped-continuation merging and positional marker-less attach; `Figure N.`-caption catalog (`FigureRef`, caption line consumed, table regions end at figure captions) plus `figure_anchor_map()`/`figure_caption_key()` clip geometry for the publisher. | `PdfLayoutBackend`, `parse_printed_toc`, `figure_anchor_map`, `figure_caption_key` |
| `extract/pdf_text.py` | Degraded backend for register maps/errata/app notes: paragraphs only, no trusted tables/figures, contextual page-number stripping. | `PdfTextBackend` |
| `structure/tables.py` | HTML table → atomic `TableBlock`; full rowspan/colspan expansion; markdown + CSV precomputed. | `html_table_to_block`, `cited_markers`, `cell_text` |
| `structure/footnotes.py` | `div.tablenote` → `Footnote`; orphan/uncited audit. | `parse_tablenote`, `attach_footnotes`, `audit_table_footnotes` |
| `structure/boilerplate.py` | Ordered regex rules. **No bare-number rule** (digits-only lines are data). | `strip_boilerplate`, `is_boilerplate` |
| `structure/pagemap.py` | Sections → PDF pages (exact number → fuzzy title → inherit, with provenance report); exact table-page pinning via PDF page text. | `assign_pages`, `pin_table_pages` |
| `structure/roles.py` | Header → semantic role (symbol/name/conditions/min/typ/max/value/unit). Deterministic regex + positional inference for empty TI headers. | `assign_roles`, `classify_table` |
| `structure/units.py` | Unit canonicalization (U+2126 → ohm, etc.) for `specs.json` only. | `canonical_unit`, `normalize_text`, `CANONICAL_UNITS` |
| `structure/specs.py` | `RawDocument` → `SpecSet` / `specs.json`. Pure transform over `TableBlock` grids. Skips `pdf_text` docs. | `table_to_records`, `build_specset` |
| `structure/plots.py` | `RawDocument` → `PlotSet` / `plots.json`. Stable IDs + section/caption tags. | `build_plotset`, `figure_number`, `section_tags`, `caption_tags` |
| `structure/corpus.py` | `RawDocument` → per-section render plans (markdown + CSV twins). | `build_section_plans`, `section_stem`, `slugify` |
| `enrich/llm.py` | LLM interface + `AnthropicClient` + `FakeClient`. All LLM use goes through `LLMClient`. | — |
| `enrich/index.py` | INDEX.md builder under a hard token budget (staged degradation). `DeterministicWriter` (offline) / `LLMWriter` (one batched call, falls back safely). | `build_index_markdown`, `SectionMeta` |
| `publish/writer.py` | Writes corpus + `manifest.json`; also writes `docs/<doc>/specs.json` and `docs/<doc>/plots.json` when the corresponding sets are supplied. | `write_corpus`, `doc_dir_name` |
| `publish/plots.py` | Downloads/render plot images into `figures/` and updates `PlotRecord.file`. `render_figure_regions` clip-renders pdf_layout figures from the region above their `Figure N.` caption (geometry via `figure_anchor_map`, drift-free); ti_html downloads + full-page fallback stay as before. | `fetch_plot_images`, `render_figure_regions`, `render_plot_pages_fallback` |
| `query.py` | Deterministic spec lookup against built `specs.json` files; plot lookup against `plots.json`. | `SpecQuery`, `format_answer`, `find_plots`, `format_plot_answer` |
| `evalh/citations.py` | Golden Q&A verification: corpus-contains AND page-truth, two-tier (exact then squash-normalized). | `verify_questions`, `load_golden_yaml`, `contains`, `squash` |
| `evalh/golden.py` | Report rendering + token economics measurement. | `render_verification_report`, `estimate_lookup_tokens` |
| `pipeline.py` | Orchestration + extraction cache (`.cache/extract/<hash>__<backend>.json`, atomic write-temp + rename). Vendor routing via the pinned vendor; `--vendor` repins the inventory; drift warnings never re-route. | `build_part` |
| `batch.py` | Batch runner: flat `*.pdf` scan of a directory, one job per PDF (part = uppercase stem), failure isolation, per-job summary + `BatchReport`. Serial today (workers/hash-gate/events land in later tickets). | `run_batch`, `run_job`, `discover_jobs`, `BatchReport`, `BatchError`, `STATUS_*` |
| `cli.py` | argparse CLI. Reconfigures stdout/stderr to UTF-8 (Windows cp1252). | `main` |

### Corpus layout (the product)

```
parts/<PART>/
├── INDEX.md               # always-loadable index (hard budget, default 3000 tok)
├── sources.json           # doc inventory: sha256, DocType, revision, nda flag, pinned vendor + evidence
├── manifest.json          # CorpusManifest: sections, files, page ranges, stats, vendor, extraction stats
└── docs/<doc_type>-<hash8>/
    ├── sections/*.md      # atomic; `<!-- source: <doc> p.N[-M] -->` header
    ├── tables/*.csv       # machine-readable twins of each section table
    ├── figures/           # plot/pixel image files referenced by plots.json
    ├── specs.json         # machine-queryable parametric spec records
    └── plots.json         # searchable plot catalog + file map
```

## Invariants — do not break these

1. **LLM writes indexes, never content.** Corpus text is verbatim-extracted.
   LLM output lives only in INDEX.md descriptions (and clearly-marked
   derived artifacts). Every table row must remain traceable to source HTML.
2. **Tables are atomic.** A table is never split, and its test-conditions
   preamble + footnotes travel with it (inside `TableBlock`).
3. **Provenance everywhere.** Every section has page range from the PDF's
   printed TOC; every table aims for an exact pinned page; citation format
   `p.N` / `p.N-M`. Unpinned/unmatched stays honestly `None`, never guessed.
4. **Tests are hermetic.** No network (ReplayFetcher/MappingFetcher), no LLM
   (FakeClient), no reliance on machine state. Real-input coverage comes from
   recorded fixtures (`tests/fixtures/recorded_http/`, 41 files) + the real
   `afe7950.pdf` / `afe7953.pdf` and the four Phase-4 gate PDFs
   (`ad9081.pdf`/`lm741.pdf`/`QPA1003P.pdf`/`hmc520a.pdf`, skip-guarded;
   `pdf_layout` is offline by construction). Synthetic PDFs are built
   in-test via fitz.
5. **Golden Q&A is the objective function.** `tests/fixtures/golden_qa.yaml`
   (19 questions) is the benchmark (no public one exists). Extend it whenever
   new answer paths ship; `dsa verify` must stay at 100% for supported paths.
6. **Caching keyed by identity.** Extraction cache = (content_hash, backend).
   Schema/version changes that alter output must invalidate via filename or
   embedded version fields.
7. **Honest degradation.** Missing container → empty section + warning, not a
   crash. Missing key → deterministic descriptions. Unmappable → reported,
   not forced.

## Conventions & gotchas

- Python ≥ 3.10. pydantic v2 (models are mutable; attribute assignment OK).
- Sub/superscripts are glued to base text (`T_A`, `1st`, `850MHz(2)`) — this
  is deliberate; do not "fix" the spacing.
- TI emits **U+2126 OHM SIGN**, not U+03A9. Preserve verbatim in extraction;
  canonicalization belongs to derived artifacts (`specs.json`).
- Footnote citation markers are read from `<sup>` elements while HTML
  structure is available — after flattening they're ambiguous. Stored in
  `TableBlock.cited_markers`.
- `div.graph` bundles = figures (img + div.textnote conditions + span.caption).
  `table.frame-none` outside div.graph = empty furniture, skip.
- TI cover page appears in the viewer TOC (empty id, numeric navtitle) — it
  is filtered; both AFE79xx reference parts have **39** content sections.
- Revision-history-style pages: `h1` headings, id-less containers —
  `parse_section` has a last-resort "first substantial subsection" fallback.
- Windows: console encoding must be UTF-8 (cli.py does it; tests print unicode
  freely). PyMuPDF is AGPL-3.0 — used for structure/verification only.
- Ruff runs on `src` and `tests`; line length 100; keep it clean.

## Definition of done (every change)

1. New code lands with its tests in the same change; `pytest` and `ruff` green.
2. Pain-point tests exist for anything that can silently corrupt data
   (span/footnote/provenance class bugs).
3. Integration proof on the real AFE7950 (hermetic fixtures) still passes.
4. Shipped capabilities update the docs: measured numbers in the relevant
   `PHASE_<N>_REPORT.md` or README, and this file if architecture/conventions
   changed.