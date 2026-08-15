# AGENTS.md — datasheet_analyzer

Read this before writing any code in this repo. It is the architecture
contract: what exists, the invariants that must not be broken, and the
conventions every change must follow. Phases 1–4 are shipped; measured
results live in `PHASE_1_REPORT.md`, `PHASE_2_REPORT.md`, `PHASE_3_REPORT.md`,
`PHASE_4_REPORT.md` (the old `PHASE_2_PLAN.md` / `PHASE_3_PLAN.md` /
`PHASE_4_PLAN.md` are superseded completion
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

Gate parts (built in-tests from the ungated `tests/fixtures/pdf/` copies; measured in `PHASE_4_REPORT.md`):

| Part | Vendor | Revision | Pages | Sections | Tables acc/rej | Specs | Plot files | Verify |
|---|---|---|---|---|---|---|---|---|
| AD9081 | adi | Rev. 0 | 45 | 34 | 29/0 | 549 | 100 | 4 Q @ 100% |
| LM741 | unknown* | SNOSC25D | 17 | 40 | 6/2 | 71 | 3 | 15 Q @ 100% (12 text + 3 spec) |
| QPA1003P | qorvo | Rev. I | 20 | 20 | 5/2 | 41 | 4 | 14 Q @ 100% (11 text + 2 spec + 1 plot) |
| HMC520A | adi | Rev. A | 32 | 36 | 6/1 | 30 | 107 | 13 Q @ 100% |

*LM741 carries no page-1 brand mark; the gate pins it `--vendor unknown` (recorded as cli-override evidence).

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
dsa build lm741.pdf --part LM741                         # brand-less: pin --vendor unknown for the layout floor
dsa verify --part AD9081 --pdf tests/fixtures/pdf/ad9081.pdf --specs  # non-TI golden (per-part yaml)
dsa batch datasheets/                                   # one part corpus per PDF in a dir (unchanged parts skipped; --workers N parallel, default 4)
dsa verify --part AFE7950 --pdf afe7950.pdf             # golden Q&A + token economics
dsa verify --part AFE7950 --pdf afe7950.pdf --specs     # + spec_query checks
# verify resolves golden_qa_<PART>.yaml per part (tests/fixtures) and
# hard-fails (exit 2) when a part has no benchmark — no silent zero-question pass
dsa query --part AFE7950 --symbol DACRES                # deterministic spec lookup
dsa query --part AFE7950 --name "junction temperature"  # alias ladder: designers' words -> TJ
dsa query --part AFE7950 --symbol IDD --json            # prefix family + machine-readable hits
dsa search --part AFE7950 "sysref setup"                # BM25 full text; every hit carries §/p.N
dsa search --part AFE7950 "thermal pad" --limit 3 --json
dsa ask --part AFE7950 "max junction temperature" --budget 3000   # one cited pack, hard budget
dsa ask --part QPA1003P "where is the functional block diagram?" --json
dsa add-doc register_map.pdf --part AFE7950 --type register_map
dsa plots --part AFE7950 --q "Output Fullscale"        # + --json; every hit carries its confidence grade
dsa status                                             # vendor + evidence + confidence mix + per-doc extraction stats

# test (fully offline, ~85 s — the ungated phase-4 gate builds four real PDFs)
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
| `models.py` | **The contract.** Pydantic v2 models shared by all stages. Change deliberately. | `SourceDocument`, `TOCEntry`, `Footnote`, `TableBlock`, `FigureRef`, `SectionNode`, `RawDocument`, `SectionFile`, `CorpusManifest`, `CorpusStats`, `ExtractionStats`, `GoldenQuestion`, `DocType`, `Confidence`, `RECONSTRUCTION_HEADER`/`RECONSTRUCTION_RESCUED`, `SpecUnit`, `SpecRecord`, `SpecTableInfo`, `SpecSet`, `PlotRecord`, `PlotSet` |
| `config.py` | pydantic-settings, `DSA_` prefix; `ANTHROPIC_API_KEY` plain. No filesystem side effects at import. `PIPELINE_VERSION`, `SPECS_SCHEMA_VERSION`, `PLOTS_SCHEMA_VERSION`, `SEARCH_SCHEMA_VERSION` live here, as does `ask_budget` (`DSA_ASK_BUDGET`, default 4000 — the `dsa ask` pack budget when `--budget` is not given). | `Settings`, `get_settings()` (lru_cached; `reset_settings_cache()` for tests) |
| `tokens.py` | THE token counter (chars/4). Every reported token number flows through it. | `count_tokens`, `truncate_to_tokens` (budget ≤ 0 → `""`) |
| `acquire/inventory.py` | Part = folder of docs. `sources.json` per part; identity = sha256 of bytes; evidence-pinned vendor at acquire (detection or `--vendor` override). Doc-type shared lexicon in `_HINTS`: errata → register/regmap → app-note (sbaa/slaa/swra, `ug-`-prefix companions) → datasheet, so register words always beat a `ug-` prefix. | `register_source`, `save_inventory`, `load_inventory`, `detect_doc_type`, `pin_vendor` |
| `vendor.py` | **Vendor routing record, not a rulebook**: profile registry (brand lexicon + backend preference chain), evidence-pinned detection on page-1 text/filename, drift warnings. Default `ti`; no layout behavior hangs off the vendor string. | `VENDOR_PROFILES`, `detect_vendor`, `select_backend`, `warn_vendor_drift`, `is_known_vendor` |
| `extract/base.py` | Backend protocol + registry. | `ExtractionBackend`, `register`, `get_backend` |
| `extract/pdf_structure.py` | PyMuPDF: content hash, page count, **printed TOC (authoritative page numbers)**, per-page text (verification/pinning only), revision sniffing from a shared lexicon ("Rev."-token shapes — "Rev. 0"/"Rev. A"/"Rev. I", "Rev. N to Rev. M" keeps the last token — plus TI doc-ids, digit-required so bare S-words like "SUPPORT" never read as ids). Layout analysis lives in `pdf_layout`, never here. | `read_toc`, `page_texts`, `compute_content_hash`, `make_source`, `split_number`, `sniff_revision` |
| `extract/http.py` | Fetchers. `CachingFetcher` (disk cache `.cache/http`), `CachingBinaryFetcher` (`.cache/http-bin`), `ReplayFetcher`/`ReplayBinaryFetcher` (hermetic tests: miss = hard error), `MappingFetcher`. | `Fetcher` / `BinaryFetcher` protocols |
| `extract/ti_html.py` | Primary TI content backend: TI document-viewer HTML (real tables, MathML, footnotes — no OCR, no hallucination). TI keeps this path; every other vendor routes to the layout floor. | `TiHtmlBackend`, `parse_toc`, `parse_section` |
| `extract/pdf_layout.py` | **Vendor-neutral layout floor** (offline, PyMuPDF-only): furniture by slot recurrence + universal page-machinery patterns (zero vendor strings), structure ladder (outline → printed-TOC dot-leader parse → per-page), page-ranged sections, honest unnumbered identity, (tickets 03–04) tables: caption-anchored hypotheses, pitch-based row grouping with wrapped-cell merging, header-anchored column clusters + a best-scoring retry ladder (every band set gated and scored; the header-declared edge share selects the winner, ties prefer the coarsest split, i.e. fewest bands — a finer tie can only carve interior words of declared columns), a reconstruction gate (rejected hypotheses recorded with reasons in `ExtractionStats`; inter-span, not start-to-start, clustering so multi-word-span note lines classify as sentences), multi-page continuation merging (the winning rung is recorded on every accepted grid as `TableBlock.reconstruction` — `header-anchored` when the table's own declared columns passed the gate first try, `rescued` when only a coarser all-word split did; the per-record confidence grade reads it), test-conditions preamble attachment, and (ticket 05) footnotes + figures: superscript citation markers from span font geometry (`_Span` carries size + glyph box; glued, raised, ≤0.82× markers land in `TableBlock.cited_markers`), trailing numbered lines attach as bare-canonical `Footnote`s with wrapped-continuation merging and positional marker-less attach; `Figure N.`-caption catalog (`FigureRef`, caption line consumed, table regions end at figure captions) plus `figure_anchor_map()`/`figure_caption_key()` clip geometry for the publisher. (Ticket 09) heading-anchored tables for the captionless era (regions under printed section headings run the same ladder + gate; header-token lines and lone section numbers split anchors sanely; side-by-side pairs split first at their mirrored header; captionless tables render "## Unnumbered table", never a fabricated number), rowspan materialization (spanning symbols replicate into child rows by indent chain / nearest-anchor fill), title-anchored figures (heading-sized line inside a drawn emphasis band with a big rect under its own x-column → `FigureRef`), and per-row page attribution of merged multi-page grids (`TableBlock.row_pages`). | `PdfLayoutBackend`, `parse_printed_toc`, `figure_anchor_map`, `figure_caption_key`, `figure_title_anchor_map` |
| `extract/pdf_text.py` | Degraded backend for register maps/errata/app notes: paragraphs only, no trusted tables/figures, contextual page-number stripping. | `PdfTextBackend` |
| `structure/tables.py` | HTML table → atomic `TableBlock`; full rowspan/colspan expansion; markdown + CSV precomputed. | `html_table_to_block`, `cited_markers`, `cell_text` |
| `structure/footnotes.py` | `div.tablenote` → `Footnote`; orphan/uncited audit. | `parse_tablenote`, `attach_footnotes`, `audit_table_footnotes` |
| `structure/boilerplate.py` | Ordered regex rules. **No bare-number rule** (digits-only lines are data). | `strip_boilerplate`, `is_boilerplate` |
| `structure/pagemap.py` | Sections → PDF pages (exact number → fuzzy title → inherit, with provenance report); exact table-page pinning via PDF page text. | `assign_pages`, `pin_table_pages` |
| `structure/roles.py` | Header → semantic role (symbol/name/conditions/min/typ/max/value/unit). Deterministic regex + positional inference for empty TI headers. | `assign_roles`, `classify_table` |
| `structure/units.py` | Unit canonicalization (U+2126 → ohm, etc.) for `specs.json` only. | `canonical_unit`, `normalize_text`, `CANONICAL_UNITS` |
| `structure/aliases.py` + `registry/aliases.yaml` | **Alias lexicon — data, not code** (same philosophy as the vendor brand lexicon): a designer's phrases per canonical symbol family. YAML entry = `names` (whole-phrase matched inside the query *and* against a record's own symbol/name text, so `Junction temperature`-as-symbol layout-floor parts resolve through the same entry as TI's `TJ`), `expect_unit` (a **ranker, never a filter** — it promotes the candidate whose canonical unit matches and never suppresses a unitless record), `kind`, and `prefix_match` + `prefixes` for families (`IDD` → `IVDD1P8`, `IVDD1P2`, …). The module only answers word questions (`by_symbol`, `phrase_hits`, `prefix_hits`, `nearest_names`); the ladder over records lives in `retrieve/`. Seeded from the six built corpora by `scripts/seed_aliases.py` (procedure in its docstring; harvest recorded at `tests/fixtures/alias_seed_symbols.json`). | `AliasLexicon`, `AliasEntry`, `load_lexicon`, `normalize`, `token_overlap` |
| `structure/search.py` | **Search vocabulary — one tokenizer, index time and query time** (same "words, not records" split as `aliases.py`). Lowercase **ASCII-only** (Unicode lowercasing folds U+2126 and U+03A9 onto one ω; this corpus keeps the glyph the vendor printed), **no stemming**, stopwords are grammatical scaffolding only (no single letters, no `a`/`in` — those are units). Compound unit strings index whole *and* split (`dBc/Hz` → `dbc/hz`, `dbc`, `hz`). A token with no letter is **not** indexed: numerals rank nothing in BM25, they are what would make an index rival the size of the text, and values have an exact path through `specs.json`. | `tokenize`, `body_text`, `fold`, `STOPWORDS` |
| `structure/confidence.py` | **Per-record confidence — one rule, one place.** `ExtractionStats` grades a document; this grades a *row*, at structure time, where the evidence still exists (how the grid was reconstructed, whether the page is pinned, what the row printed). Spec rule, worst-first: `low` = grid rescued by the retry ladder **or** a value whose unit the alias lexicon expected is missing; `medium` = the page is section-range only **or** the row printed no value; `high` = pinned exact page + header-declared reconstruction + a printed value. Plots have no grid, so theirs is citation precision: exact page + caption = `high`, section range or captionless = `medium`, no page = `low`. `mix()` counts a part by grade for the manifest. | `grade_spec_record`, `grade_plot_record`, `grade_of`, `mix`, `page_is_exact`, `has_value`, `unit_expected_but_missing` |
| `structure/specs.py` | `RawDocument` → `SpecSet` / `specs.json`. Pure transform over `TableBlock` grids. Skips `pdf_text` docs. A merged multi-page grid's per-row pages (`row_pages`) beat the table's caption page, so continuation rows cite their own printed page. Every record is graded here via `structure/confidence.py`. | `table_to_records`, `build_specset` |
| `structure/plots.py` | `RawDocument` → `PlotSet` / `plots.json`. Stable IDs + section/caption tags; every record graded via `structure/confidence.py` (the pixel `file` is deliberately not part of the grade). | `build_plotset`, `figure_number`, `section_tags`, `caption_tags` |
| `structure/corpus.py` | `RawDocument` → per-section render plans (markdown + CSV twins). | `build_section_plans`, `section_stem`, `slugify` |
| `enrich/llm.py` | LLM interface + `AnthropicClient` + `FakeClient`. All LLM use goes through `LLMClient`. | — |
| `enrich/index.py` | INDEX.md builder under a hard token budget (staged degradation). `DeterministicWriter` (offline) / `LLMWriter` (one batched call, falls back safely). | `build_index_markdown`, `SectionMeta` |
| `publish/writer.py` | Writes corpus + `manifest.json`; also writes `docs/<doc>/specs.json`, `docs/<doc>/plots.json` (when the corresponding sets are supplied) and `docs/<doc>/search_index.json` (always, for every document). Records the index economics in `CorpusStats` (`search_index_bytes` vs `section_bytes`), each section's `search_tokens`, and the part's per-record confidence mix (`spec_confidence` / `plot_confidence`, counts by grade). Also answers the publish-cache-key question for the two artifacts it writes: `specs_current` / `plots_current` (schema-version checks the batch skip gate calls; an absent file reads as current, because a `pdf_text` document publishes neither). | `write_corpus`, `doc_dir_name`, `doc_dir_name_for_source`, `specs_current`, `plots_current` |
| `publish/search_index.py` | Builds `search_index.json` from the very markdown the writer emits, so searchable and readable can never diverge. Serialized **deterministically** (sorted keys, compact separators, `ensure_ascii=False`): identical input ⇒ byte-identical file. `search_index_current()` is the publish-cache-key check the batch skip gate calls — an absent or older-schema index rebuilds. | `build_search_index`, `dump_json`, `write_search_index`, `search_index_current`, `INDEX_FILENAME` |
| `publish/plots.py` | Downloads/render plot images into `figures/` and updates `PlotRecord.file`. `render_figure_regions` clip-renders pdf_layout figures from the region above their `Figure N.` caption (geometry via `figure_anchor_map`, drift-free); ti_html downloads + full-page fallback stay as before. | `fetch_plot_images`, `render_figure_regions`, `render_plot_pages_fallback` |
| `retrieve/` | **The retrieval core — every corpus lookup, once.** `index.py`: `CorpusIndex.load(part_dir)` reads a part's `manifest.json` + every `specs.json` / `plots.json` once and caches it on corpus identity `(part dir, manifest.json mtime + size, PIPELINE_VERSION)`, so a rebuild invalidates naturally and a part with no manifest is never cached (no identity → re-read, never stale); section bodies load lazily. `search.py`: BM25 (k1=1.2, b=0.75, non-negative IDF) over the loaded `search_index.json`s, corpus statistics merged across a part's documents, **ties broken on (doc dir, section file)** so two identical corpora rank identically, plus snippet recovery — ±240 chars around the best-scoring term, grown to a sentence boundary within 120 chars of slack, `…` marking only a genuine cut, section heading dropped (the hit carries it as a field). `retriever.py`: `Retriever.specs/plots/sections/search` return typed hits; `specs()` runs the **alias ladder**, first non-empty rung wins — exact symbol (plus its ticket-09 materialized child rows, and only when the parent row matched exactly) → alias phrase → alias prefix family → symbol/name substring (the pre-ticket-02 behaviour) → token-overlap fuzzy (≥ 2 tokens, ≥ 0.6 overlap). `suggest_specs()` is the honest no-match path: nearest corpus terms then lexicon phrases, never a rung-6 guess. `suggest_specs()` is the honest no-match path; `search_unavailable()` is search's — a corpus with no current index is told to rebuild instead of being handed an empty result that reads like "not in the datasheet". `results.py`: `Citation` (the only place `p.N` / `p.N-M` / `§N, p.N` is spelled), `SpecHit` (+ `as_dict()`, the one JSON shape the CLI and MCP both emit), `PlotHit` (+ `as_dict()`), `SectionHit`, `SearchHit` (+ `as_dict()`, `heading`, `score`, `snippet`) — each carrying doc, page range, `matched_via` (`symbol` \| `alias:<phrase>` \| `alias-prefix:<prefix>` \| `symbol-substring` \| `name-substring` \| `fuzzy` \| `section` \| `fulltext` \| … ) and `confidence` read off the record by `record_confidence()` (a corpus with no grade on disk reads `unknown`; section and full-text hits are `unknown` by construction — a grade belongs to an extracted record, not to verbatim text). Corrupt `manifest.json` / `specs.json` / `plots.json` / `search_index.json` warns and skips; it never takes the part down. `pack.py` (ticket 05) is the answer pack: `Retriever.ask()` → `build_pack()` routes deterministically (spec ladder → plot vocabulary + `plots_for_terms` → BM25 → `search_unavailable()` → explicit no-match; **no LLM in the path**), then fits the result into a token budget over a **reserved tail** (header + first answer line + verify footer) so citations are never what a budget removes. It is the one place in `retrieve/` that renders text, because a budget cannot be enforced on a payload the core did not produce. `ANSWER_PACK_SCHEMA` + `validate_pack` are the declared `--json` shape, dependency-free, reused by ticket 07's MCP tool. | `CorpusIndex`, `Retriever`, `Citation`, `SpecHit`, `PlotHit`, `SectionHit`, `SearchHit`, `AnswerPack`, `PackLine`, `PackExcerpt`, `build_pack`, `ANSWER_PACK_SCHEMA`, `validate_pack`, `PLOT_VOCABULARY`, `score_sections`, `clear_index_cache` |
| `query.py` | **Back-compat shim over `retrieve/`** (deprecated as an implementation; signatures and record-list returns kept for existing callers) plus the renderers, which take their citation strings from `Citation`. `format_spec_hits` / `format_plot_hits` / `format_no_match` render typed hits (rung + confidence + nearest candidates); `format_answer` / `format_plot_answer` keep the record-list shape. | `SpecQuery`, `format_answer`, `format_spec_hits`, `format_no_match`, `find_plots`, `format_plot_answer`, `format_plot_hits` |
| `evalh/citations.py` | Golden Q&A verification: corpus-contains AND page-truth, two-tier (exact then squash-normalized). Also the `spec_query` / `plot_query` pass rules (page match + value substrings; plots additionally need an on-disk image >1 KB) — they run against `retrieve/`, not against a walk of their own. | `verify_questions`, `verify_spec_queries`, `verify_plot_queries`, `load_golden_yaml`, `contains`, `squash` |
| `evalh/golden.py` | Report rendering + token economics measurement. | `render_verification_report`, `render_spec_query_report`, `render_plot_query_report`, `render_token_economics`, `estimate_lookup_tokens` |
| `pipeline.py` | Orchestration + extraction cache (`.cache/extract/<hash>__<backend>.json`, atomic write-temp + rename with a Windows rename retry). Vendor routing via the pinned vendor; `--vendor` repins the inventory; drift warnings never re-route. `build_part` takes an additive `on_progress` stage-boundary callback (extracting/structuring/enriching/publishing; no-op default — existing callers unchanged; batch's event emitter wires into it). | `build_part` |
| `batch.py` | Batch runner: flat `*.pdf` scan of a directory, one job per PDF (part = uppercase stem), failure isolation, per-job summary + `BatchReport`. Hash-gated skip (`skip_reason`: manifest + `PIPELINE_VERSION` + inventory sha256; `--force` / `--no-cache` disable it; changed PDFs re-register). Stage events: every transition (queued/extracting/structuring/enriching/publishing/done/failed/skipped) emits one prefixed terminal line AND one JSONL record (`.cache/batches/<dirstem>-<run>/batch.jsonl`; header event carries the job list) via `EventEmitter` — the JSONL is the monitoring source of truth; `build_part`'s additive `on_progress` callback (no-op default) is what fired inside jobs. Parallel dispatch: bounded `ThreadPoolExecutor` (`--workers N`, env `DSA_BATCH_WORKERS` default 4; `workers=1` is the exact serial path), job-scoped wiring (backend/fetchers/LLM client created per job — no shared mutable pipeline state), final events as jobs complete, report in run order; extraction-cache writes are atomic (write-temp + rename) so identical PDF bytes can never corrupt `.cache/extract/<hash>__<backend>.json`. | `run_batch`, `run_job`, `discover_jobs`, `skip_reason`, `EventEmitter`, `log_path_for`, `BatchReport`, `BatchError`, `STATUS_*` |
| `cli.py` | argparse CLI, **formatting only** — it holds no retrieval logic (see the seam under Conventions). Reconfigures stdout/stderr to UTF-8 (Windows cp1252). | `main` |

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
    ├── plots.json         # searchable plot catalog + file map
    └── search_index.json  # BM25 inverted index over sections/*.md (schema_version)
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
   `afe7950.pdf` / `afe7953.pdf` (skip-guarded) and the four Phase-4 gate
   PDFs (`tests/fixtures/pdf/` — committed, **ungated**: a missing fixture
   is a hard test failure; `pdf_layout` is offline by construction; the
   repo-root copies stay the documented `dsa build` working files).
   Synthetic PDFs are built in-test via fitz.
5. **Golden Q&A is the objective function.** Per-part benchmarks at
   `tests/fixtures/golden_qa_<PART>.yaml` (the AFE7950 set — 19 questions —
   is the historical benchmark; no public one exists). `dsa verify`
   discovers a part's benchmark by name and hard-fails when it is missing
   or empty — every corpus is provably verified or provably not. Extend
    the sets whenever new answer paths ship; `dsa verify` must stay at 100%
    for supported paths (gate parts: AD9081 4 Q, LM741 15 Q (12 text + 3
    spec), QPA1003P 14 Q (11 text + 2 spec + 1 plot), HMC520A 13 Q).
    **AFE7953 carries one too** — 11 Q (3 text + 7 spec + 1 plot), added in
    the ticket-05 repair so that "every golden question across all six parts"
    is measured over six. It is the one set whose ground truth cannot be
    checked against a fresh build: no recorded TI document-viewer pages exist
    for that part, so its questions were read off `afe7953.pdf`'s printed
    pages and checked against the corpus committed under `parts/` — the same
    substrate the ticket-04 regrade uses
    (`test_afe7950_build.py::TestAnswerPacksOnAfe7953`).
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
- Both ohm glyphs — **U+2126 OHM SIGN** (TI) and **U+03A9** (ADI, both measured in AD9081) — are preserved verbatim in extraction (do not "fix" the glyph); canonicalization belongs to derived artifacts (`specs.json`).
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
  freely). PyMuPDF is AGPL-3.0 — it *is* the offline `pdf_layout` extraction floor
  (fonts, spans, rulings, vector figure regions); TI's HTML path uses it for
  structure/verification only.
- **No retrieval logic in a front end.** `cli.py` (and, from ticket 07, the MCP
  server) may only format what `retrieve/` returns: no corpus walk, no
  `specs.json` / `plots.json` parsing, no hand-built `p.N` or `§N` string.
  Citations come from `Citation`, so the CLI and the MCP server can never drift
  apart in what they cite. `tests/unit/test_retrieve.py::TestCliIsFormatOnly`
  fails the moment that creeps back in.
- **Adding a synonym is a YAML edit.** `registry/aliases.yaml` is data; no
  resolution rule may be hard-coded in Python. Keep alias phrases ≥ 2
  characters and specific (a bare "gain" or "supply" hijacks half a corpus);
  short symbols need no alias at all, because exact symbol is rung 1.
  `expect_unit` ranks and must never filter — a printed value with no unit is
  still an answer. Re-measure coverage with `scripts/seed_aliases.py` and
  refresh `tests/fixtures/alias_seed_symbols.json` whenever extraction changes;
  the phase-4 gate fails if that seed goes stale.
- **An answer pack is assembled, never generated.** `retrieve/pack.py` routes
  by feature hits alone — no LLM may enter the `ask` path, and an LLM caller
  is welcome to *use* `ask` but never to sit inside it. Two rules there are
  load-bearing: the **reserved tail** (header + first answer line + verify
  footer) is laid down before anything discretionary, so a budget can only
  ever cost extra rows and excerpt prose and never a `§N, p.N`; and any drop
  emits a notice naming `--budget`, because silent truncation is the one
  failure an agent cannot detect. When a budget is below that reserved tail
  the pack goes over and *says so* (`over_budget` + the floor notice) rather
  than shipping an answer with its citation removed. `pack.py` is also the
  only module in `retrieve/` allowed to render text: enforcing a token budget
  on a payload a front end formats is impossible, so the pack renders itself
  and the CLI only chooses markdown or JSON. A third rule joined them in
  repair: `search()` returns `[]` both for "nothing matched" and for "there
  was no index to match against", so the pack asks `search_unavailable()`
  *before* it may report `none` and routes an unsearchable corpus to
  `unavailable` (rebuild to enable search; `dsa ask` exits 2, exactly as `dsa
  search` does). Reading that empty list as absence would put a claim about
  the datasheet in a pack that never ran the path. Question-relevance ordering
  inside a rung (`_by_relevance`) is *presentation* — it drops nothing,
  hides nothing, and never re-grades.
- **A confidence grade is metadata, never a filter.** The rule lives in
  `structure/confidence.py` (its docstring is the normative version) and runs
  once, at structure time. Nothing downstream may re-derive it, and nothing may
  drop, hide or reorder a record because of it — a `low` record is still
  returned, still verbatim, still cited; `low` means "open the printed page",
  not "wrong". Measured mix (`high`/`medium`/`low`) on all six built corpora:

  | Part | Backend | Specs | Plots | Measured by |
  |---|---|---|---|---|
  | AFE7950 | ti_html | 613/3/3 | 0/514/0 | fresh build (`test_afe7950_build.py`) |
  | AFE7953 | ti_html | 531/2/3 | 0/492/0 | regrade of the committed corpus (below) |
  | AD9081 | pdf_layout | 151/207/191 | 2/98/0 | phase-4 gate build |
  | LM741 | pdf_layout | 0/0/71 | 3/0/0 | phase-4 gate build |
  | QPA1003P | pdf_layout | 0/0/41 | 4/0/0 | phase-4 gate build |
  | HMC520A | pdf_layout | 0/0/30 | 34/73/0 | phase-4 gate build |

  Two facts dominate: TI's HTML tables are never reconstructed, so they grade
  almost entirely `high`, while the captionless-era layout-floor parts grade
  entirely `low` because their grids only ever pass the reconstruction gate on
  a rescue split. AD9081, whose ADI tables are captioned and header-declared,
  is the mixed case. Do not "improve" the mix by loosening the rule; improve
  it by making the layout floor reconstruct those grids from their own
  headers. **AFE7953 has no offline build path** — it is a TI part, so it
  routes to `ti_html`, and the only recorded document-viewer pages in the repo
  are AFE7950's — so its mix is measured off the corpus committed under
  `parts/` by regrading published artifacts: `specs.json` rows, `manifest.json`
  section ranges, and the `tables/*.csv` twins re-pinned through the pipeline's
  own `pin_table_pages` against `afe7953.pdf`. That reconstruction is trusted
  only because the same code reproduces the freshly built AFE7950 mix exactly;
  `TestCommittedReferenceCorpora` asserts that before it reports AFE7953.
- The retrieval index is an in-process cache. Tests get a fresh one from the
  autouse `fresh_retrieval_cache` fixture; production code invalidates by
  rebuilding the corpus (which rewrites `manifest.json`).
- **Publish artifacts are part of the skip gate.** `batch.skip_reason` refuses
  to skip a part whose documents lack a current-schema `search_index.json`
  (`publish.search_index_current`), `specs.json` (`publish.specs_current`) or
  `plots.json` (`publish.plots_current`), so a corpus published before a
  publish-time schema existed republishes once instead of skipping forever
  and answering nothing. Bump `SEARCH_SCHEMA_VERSION` /
  `SPECS_SCHEMA_VERSION` / `PLOTS_SCHEMA_VERSION` in `config.py` whenever the
  corresponding format changes; that is the invalidation, not
  `PIPELINE_VERSION`. `SPECS_`/`PLOTS_` are at **"2"** (phase 5, ticket 04
  added `confidence`) — the extractor-version gate cannot cover this, because
  a `ti_html` part's `output_version` never moves when the layout engine's
  does. A *missing* `specs.json`/`plots.json` reads as current, unlike a
  missing search index: a `pdf_text` document legitimately publishes neither,
  and demanding one would put that part in a rebuild loop.
- **The search tokenizer is shared, and deliberately lossy in one direction.**
  Index time and query time both call `structure.search.tokenize`, so they
  cannot drift. Two rules there are load-bearing and must not be "fixed":
  ASCII-only casefolding (keeps both ohm glyphs apart) and dropping tokens
  with no letter (a bare `105` ranks nothing; `dsa query` is the value path).
- `search_index.json` is written compactly (not indented like its `specs.json`
  siblings) and with sorted keys: it holds one entry per *token*, so
  pretty-printing would triple a machine artifact, and sorted keys are what
  make rebuilds byte-identical.
- Ruff runs on `src` and `tests`; line length 100; keep it clean.

## Definition of done (every change)

1. New code lands with its tests in the same change; `pytest` and `ruff` green.
2. Pain-point tests exist for anything that can silently corrupt data
   (span/footnote/provenance class bugs).
3. Integration proof on the real AFE7950 (hermetic fixtures) still passes.
4. Shipped capabilities update the docs: measured numbers in the relevant
   `PHASE_<N>_REPORT.md` or README, and this file if architecture/conventions
   changed.