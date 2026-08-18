# AGENTS.md — datasheet_analyzer

Read this before writing any code in this repo. It is the architecture
contract: what exists, the invariants that must not be broken, and the
conventions every change must follow. Phases 1–5 are shipped; measured
results live in `PHASE_1_REPORT.md`, `PHASE_2_REPORT.md`, `PHASE_3_REPORT.md`,
`PHASE_4_REPORT.md`, `PHASE_5_REPORT.md` (the old `PHASE_2_PLAN.md` /
`PHASE_3_PLAN.md` / `PHASE_4_PLAN.md` / `PHASE_5_PLAN.md` are superseded
completion records).

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
# plot_query, ask_query and search_query tables run whenever the golden set
# carries them (no --pdf needed for the last two) and fail the command
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
dsa project new rf-frontend --interfaces "AFE7950 TX -> HMC520A DSA"
dsa project add rf-frontend AFE7950 --role "quad RF transceiver"
dsa project add rf-frontend HMC520A AD9081             # unbuilt part = refused, with the build command
dsa project build rf-frontend                          # PROJECT_INDEX.md under its budget
dsa project status                                     # projects + their parts
dsa ask --project rf-frontend "does anything here need a 1.8 V rail?"
dsa search --project rf-frontend "sysref"              # --project also on query / plots; hits labelled [PART]
dsa serve                                              # the local workbench in a browser on 127.0.0.1:8765 (needs the [web] extra)
dsa serve --mcp                                        # the corpus as MCP tools over local stdio (needs the [mcp] extra)
dsa status                                             # vendor + evidence + confidence mix + per-doc extraction stats + projects

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
| `models.py` | **The contract.** Pydantic v2 models shared by all stages. Change deliberately. | `SourceDocument`, `TOCEntry`, `Footnote`, `TableBlock`, `FigureRef`, `SectionNode`, `RawDocument`, `SectionFile`, `CorpusManifest`, `CorpusStats`, `ExtractionStats`, `GoldenQuestion`, `Project`, `ProjectMember`, `DocType`, `Confidence`, `RECONSTRUCTION_HEADER`/`RECONSTRUCTION_RESCUED`, `SpecUnit`, `SpecRecord`, `SpecTableInfo`, `SpecSet`, `PlotRecord`, `PlotSet` |
| `config.py` | pydantic-settings, `DSA_` prefix; `ANTHROPIC_API_KEY` plain. No filesystem side effects at import. `PIPELINE_VERSION`, `SPECS_SCHEMA_VERSION`, `PLOTS_SCHEMA_VERSION`, `SEARCH_SCHEMA_VERSION` live here, as does `ask_budget` (`DSA_ASK_BUDGET`, default 4000 — the `dsa ask` pack budget when `--budget` is not given), `projects_dir` (`DSA_PROJECTS_DIR`, default `projects`), `project_index_token_budget` (`DSA_PROJECT_INDEX_TOKEN_BUDGET`, default 4000 — the hard `PROJECT_INDEX.md` budget) and `mcp_max_tokens` (`DSA_MCP_MAX_TOKENS`, default 6000 — the hard cap on every MCP response). | `Settings`, `get_settings()` (lru_cached; `reset_settings_cache()` for tests) |
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
| `enrich/index.py` | INDEX.md builder under a hard token budget (staged degradation). `DeterministicWriter` (offline) / `LLMWriter` (one batched call, falls back safely). Its "How to use this corpus" block is a **pointer** to `AGENT.md`, never a copy of the protocol (ticket 08). | `build_index_markdown`, `SectionMeta` |
| `publish/writer.py` | Writes corpus + `manifest.json`; also writes `docs/<doc>/specs.json`, `docs/<doc>/plots.json` (when the corresponding sets are supplied) and `docs/<doc>/search_index.json` (always, for every document). Also emits `AGENT.md` beside `INDEX.md` (the ticket-08 protocol; its measured size lands in `CorpusStats.agent_doc_tokens`). Records the index economics in `CorpusStats` (`search_index_bytes` vs `section_bytes`), each section's `search_tokens`, and the part's per-record confidence mix (`spec_confidence` / `plot_confidence`, counts by grade). Also answers the publish-cache-key question for the two artifacts it writes: `specs_current` / `plots_current` (schema-version checks the batch skip gate calls; an absent file reads as current, because a `pdf_text` document publishes neither). | `write_corpus`, `doc_dir_name`, `doc_dir_name_for_source`, `specs_current`, `plots_current` |
| `publish/search_index.py` | Builds `search_index.json` from the very markdown the writer emits, so searchable and readable can never diverge. Serialized **deterministically** (sorted keys, compact separators, `ensure_ascii=False`): identical input ⇒ byte-identical file. `search_index_current()` is the publish-cache-key check the batch skip gate calls — an absent or older-schema index rebuilds. | `build_search_index`, `dump_json`, `write_search_index`, `search_index_current`, `INDEX_FILENAME` |
| `publish/plots.py` | Downloads/render plot images into `figures/` and updates `PlotRecord.file`. `render_figure_regions` clip-renders pdf_layout figures from the region above their `Figure N.` caption (geometry via `figure_anchor_map`, drift-free); ti_html downloads + full-page fallback stay as before. | `fetch_plot_images`, `render_figure_regions`, `render_plot_pages_fallback` |
| `retrieve/` | **The retrieval core — every corpus lookup, once.** `index.py`: `CorpusIndex.load(part_dir)` reads a part's `manifest.json` + every `specs.json` / `plots.json` once and caches it on corpus identity `(part dir, manifest.json mtime + size, PIPELINE_VERSION)`, so a rebuild invalidates naturally and a part with no manifest is never cached (no identity → re-read, never stale); section bodies load lazily. `search.py`: BM25 (k1=1.2, b=0.75, non-negative IDF) over the loaded `search_index.json`s, corpus statistics merged across a part's documents, **ties broken on (doc dir, section file)** so two identical corpora rank identically, plus snippet recovery — ±240 chars around the best-scoring term, grown to a sentence boundary within 120 chars of slack, `…` marking only a genuine cut, section heading dropped (the hit carries it as a field). `retriever.py`: `Retriever.specs/plots/sections/search` return typed hits; `specs()` runs the **alias ladder**, first non-empty rung wins — exact symbol (plus its ticket-09 materialized child rows, and only when the parent row matched exactly) → alias phrase → alias prefix family → symbol/name substring (the pre-ticket-02 behaviour) → token-overlap fuzzy (≥ 2 tokens, ≥ 0.6 overlap). `suggest_specs()` is the honest no-match path: nearest corpus terms then lexicon phrases, never a rung-6 guess. `suggest_specs()` is the honest no-match path; `search_unavailable()` is search's — a corpus with no current index is told to rebuild instead of being handed an empty result that reads like "not in the datasheet". `results.py`: `Citation` (the only place `p.N` / `p.N-M` / `§N, p.N` is spelled), `SpecHit` (+ `as_dict()`, the one JSON shape the CLI and MCP both emit), `PlotHit` (+ `as_dict()`), `SectionHit`, `SearchHit` (+ `as_dict()`, `heading`, `score`, `snippet`) — each carrying doc, page range, `matched_via` (`symbol` \| `alias:<phrase>` \| `alias-prefix:<prefix>` \| `symbol-substring` \| `name-substring` \| `fuzzy` \| `section` \| `fulltext` \| … ) and `confidence` read off the record by `record_confidence()` (a corpus with no grade on disk reads `unknown`; section and full-text hits are `unknown` by construction — a grade belongs to an extracted record, not to verbatim text). Corrupt `manifest.json` / `specs.json` / `plots.json` / `search_index.json` warns and skips; it never takes the part down. `pack.py` (ticket 05) is the answer pack: `Retriever.ask()` → `build_pack()` routes deterministically (spec ladder → plot vocabulary + `plots_for_terms` → BM25 → `search_unavailable()` → explicit no-match; **no LLM in the path**), then fits the result into a token budget over a **reserved tail** (header + first answer line + verify footer) so citations are never what a budget removes. It is the one place in `retrieve/` that renders text, because a budget cannot be enforced on a payload the core did not produce. `ANSWER_PACK_SCHEMA` + `validate_pack` are the declared `--json` shape, dependency-free, reused by ticket 07's MCP tool. `project.py` (ticket 06) is the same lookups over a whole design: `ProjectRetriever.for_parts(name, dirs)` holds one `Retriever` per member and fans out in membership order (search merges by score with `(part, doc, file)` underneath, because BM25 scores from two corpora are not strictly comparable). It relabels nothing — every hit already carries `citation.part`, which `Retriever` fills — and it separates two states a single part cannot have: `search_unavailable()` (no member can be searched at all → exit 2, as for one part) from `search_gap()` (some member could not, so absence was never established). `build_project_pack` routes each member independently, orders answering members by route strength then membership, and **interleaves one row per part before any part's second**, so a tight budget cannot spend itself on one device. Ticket 07 added the lookups a second front end needed and neither front end may implement: `discover_parts()` (part directories, built or not — a half-built part is listed, not hidden), `CorpusIndex.index_markdown()` / `Retriever.index_markdown()` (`INDEX.md` through the same lazy cache as section bodies), `Retriever.resolve_section(ref)` (one section from a caller's reference: exact number → corpus file/basename → number prefix → title substring, manifest order underneath), `Retriever.plot_for_file(file)` (the record that cites an image — a loose file no record claims resolves to nothing) and `CorpusIndex.corpus_path(rel)` (the only translation from a caller's string to a path; see the conventions). | `CorpusIndex`, `Retriever`, `ProjectRetriever`, `Citation`, `SpecHit`, `PlotHit`, `SectionHit`, `SearchHit`, `AnswerPack`, `PackLine`, `PackExcerpt`, `build_pack`, `build_project_pack`, `ANSWER_PACK_SCHEMA`, `validate_pack`, `PLOT_VOCABULARY`, `score_sections`, `clear_index_cache`, `discover_parts`, `INDEX_FILENAME` |
| `projects/` | **The noun above `part`.** `store.py` owns `projects/<name>/project.json` — an explicit, human-curated part list (`ProjectMember.part_number` + a free-text `role`) plus `interfaces` / `notes`. Membership is chosen, never inferred: no BOM/netlist parsing, `add_parts` refuses a part with no `manifest.json` *before mutating anything* and names the build command, and a project name is validated (not sanitized) because rewriting `../etc` would hide the mistake. `index.py` renders `PROJECT_INDEX.md` under `project_index_token_budget` with staged degradation — conventions → notes → interfaces → per-member stats → roles — leaving the part list and each member's `INDEX.md` pointer at every stage, and **saying so** when anything was dropped (`INDEX.md` degrades silently; a project index does not). Member facts are read through `CorpusIndex`, never by walking a corpus. `write_project_index` also writes the project's `AGENT.md` — building the index *is* a project's publish step, and the protocol must ship with the data. Project-scoped *retrieval* deliberately lives in `retrieve/project.py`, not here. | `Project`, `ProjectMember` (in `models.py`), `new_project`, `load_project`, `save_project`, `add_parts`, `remove_parts`, `list_projects`, `part_dirs`, `is_built`, `write_project_index`, `build_project_index_markdown`, `summarize_project`, `ProjectError` |
| `query.py` | **Back-compat shim over `retrieve/`** (deprecated as an implementation; signatures and record-list returns kept for existing callers) plus the renderers, which take their citation strings from `Citation`. `format_spec_hits` / `format_plot_hits` / `format_no_match` render typed hits (rung + confidence + nearest candidates); `format_answer` / `format_plot_answer` keep the record-list shape. | `SpecQuery`, `format_answer`, `format_spec_hits`, `format_no_match`, `find_plots`, `format_plot_answer`, `format_plot_hits` |
| `evalh/citations.py` | Golden Q&A verification: corpus-contains AND page-truth, two-tier (exact then squash-normalized). Also the four **path** pass rules, which run against `retrieve/` and never against a walk of their own: `spec_query` (page match + value substrings), `plot_query` (same, plus an on-disk image >1 KB), and (ticket 09) `ask_query` — one `dsa ask` pack whose *cited* rows carry the substrings, by the recorded route, inside its own budget (`pack_answers_question` is that rule, deliberately the spec rule applied to a pack) — and `search_query` — the **top-1** hit must be a section covering a cited page whose text holds the answer, with a corpus that has no current index failing as `search unavailable` rather than passing. | `verify_questions`, `verify_spec_queries`, `verify_plot_queries`, `verify_ask_queries`, `verify_search_queries`, `pack_answers_question`, `load_golden_yaml`, `contains`, `squash` |
| `evalh/golden.py` | Report rendering + token economics measurement. | `render_verification_report`, `render_spec_query_report`, `render_plot_query_report`, `render_ask_query_report`, `render_search_query_report`, `render_token_economics`, `estimate_lookup_tokens` |
| `pipeline.py` | Orchestration + extraction cache (`.cache/extract/<hash>__<backend>.json`, atomic write-temp + rename with a Windows rename retry). Vendor routing via the pinned vendor; `--vendor` repins the inventory; drift warnings never re-route. `build_part` takes an additive `on_progress` stage-boundary callback (extracting/structuring/enriching/publishing; no-op default — existing callers unchanged; batch's event emitter wires into it). | `build_part` |
| `batch.py` | Batch runner: flat `*.pdf` scan of a directory, one job per PDF (part = uppercase stem), failure isolation, per-job summary + `BatchReport`. Hash-gated skip (`skip_reason`: manifest + `PIPELINE_VERSION` + inventory sha256; `--force` / `--no-cache` disable it; changed PDFs re-register). Stage events: every transition (queued/extracting/structuring/enriching/publishing/done/failed/skipped) emits one prefixed terminal line AND one JSONL record (`.cache/batches/<dirstem>-<run>/batch.jsonl`; header event carries the job list) via `EventEmitter` — the JSONL is the monitoring source of truth; `build_part`'s additive `on_progress` callback (no-op default) is what fired inside jobs. Parallel dispatch: bounded `ThreadPoolExecutor` (`--workers N`, env `DSA_BATCH_WORKERS` default 4; `workers=1` is the exact serial path), job-scoped wiring (backend/fetchers/LLM client created per job — no shared mutable pipeline state), final events as jobs complete, report in run order; extraction-cache writes are atomic (write-temp + rename) so identical PDF bytes can never corrupt `.cache/extract/<hash>__<backend>.json`. | `run_batch`, `run_job`, `discover_jobs`, `skip_reason`, `EventEmitter`, `log_path_for`, `BatchReport`, `BatchError`, `STATUS_*` |
| `mcp_server/` | **The second front end** (`dsa serve --mcp`, Phase 5 ticket 07): the corpus as MCP tools over **local stdio** — no HTTP, no auth, no multi-tenancy. `server.py` registers nine tools (`list_parts`, `list_projects`, `get_index`, `search`, `find_spec`, `read_section`, `find_plots`, `get_figure`, `ask`) and two index resources (`dsa://part/<PART>/INDEX.md`, `dsa://project/<NAME>/PROJECT_INDEX.md`, registered as templates *and* as concrete resources for what is on disk at start-up). It is bound by the same seam `cli.py` is: every lookup goes through `retrieve/`, every citation comes from `Citation`, every hit shape from that hit's own `as_dict()`, and the pack from `retrieve/pack.py`. `responses.py` is deliberately **SDK-free** — the envelope (`tool`, `scope`, `error` vs `warning`, `truncated`, `over_cap`, `notice`, `citations`, `tokens`), the declared per-tool `SCHEMAS` (checked with `retrieve.pack.validate_pack`, not a second validator) and the response cap live there, because the `[mcp]` extra is optional and the rule that bounds a response must not vanish with it. `DSA_MCP_MAX_TOKENS` (default 6000) caps every tool response *and* every resource read: list bodies fill greedily in retrieval order, text bodies trim to what is left, and any drop carries a notice naming the setting. Two exceptions are stated rather than hidden: an **image block is atomic** (trimming base64 corrupts a PNG, so the cap governs the JSON that cites it), and an **answer pack shrinks by re-asking at a lower budget**, never by deleting rows from the pack it already built — below a few hundred tokens no pack fits, and the response says `over_cap` instead of shipping a mutilated answer. The `mcp` SDK is imported lazily via the package `__getattr__`, so a core install works and `dsa serve --mcp` without the extra prints an install hint. | `build_server`, `serve_stdio`, `SCHEMAS`, `validate_response`, `response_tokens`, `CAP_SETTING`, `PART_INDEX_URI`, `PROJECT_INDEX_URI` |
| `app/` + `web/` | **The third front end** (`dsa serve`, the local workbench): a FastAPI application plus a React + Vite + TypeScript UI, one process, loopback only (`serve_host` defaults to `127.0.0.1` — there is no authentication, so binding `0.0.0.0` would publish an unauthenticated corpus browser and every NDA document in it). Bound by the **same seam** `cli.py` and `mcp_server/` are, and for the same reason: no retrieval logic, no citation formatting, no JSON shapes of its own. It consumes `retrieve.Retriever` / `ProjectRetriever` **in process** — it does not shell out to the MCP server, whose `DSA_MCP_MAX_TOKENS` cap is correct for a model reading over a wire and wrong for a UI rendering full result sets. `contracts.py` is the frozen HTTP surface: its docstring holds the endpoint table and every request/response model, it imports no FastAPI (so `acquire/applicability.py` stays importable in a plain install), and a router may not invent a shape that is not in it. `main.py` auto-discovers `routers/*.py`; `static.py` serves `web/dist` when it exists and says how to build it when it does not. Two one-way SSE streams (analyze progress, chat tokens) — server-to-client only, so no WebSocket. `app/tools.py` mirrors the nine MCP tools as the chat agent's tool surface; `_scope` is shared from `retrieve/scope.py` rather than copied a third time. `locate.py` derives highlight geometry **on demand** from the PDF and never persists it (see the `SourceDocument` rule below). The `web` extra is optional exactly as `mcp` is — `dsa serve` without it prints an install hint. | `create_app`, `contracts` (the endpoint table), `JobRegistry`, `resolve_scope`, `locate_citation`, `SessionStore` |
| `protocol.py` | **The corpus agent protocol — one rule text, three destinations** (Phase 5, ticket 08). `RULES`, `CONFIDENCE_HEADER`/`CONFIDENCE_ROWS` and `FALLBACK_RULE` are the canonical strings; `build_part_agent_markdown` (written by `publish/writer.py`), `build_project_agent_markdown` (written by `projects/index.py`) and `build_skill_markdown` (the checked-in `.claude/skills/datasheet-corpus/SKILL.md`, regenerated by `scripts/write_skill.py`) render *those exact strings* and add only their own worked examples — the CLI path and the MCP path, scoped to that part or project. `AGENT.md` is bounded like `INDEX.md` is (`AGENT_DOC_TOKEN_BUDGET` = 1700; measured 1,420 for a part and 1,496 for a three-part project, recorded per part in `CorpusStats.agent_doc_tokens`) and carries `PROTOCOL_MARKER`, its embedded version, so `agent_doc_current()` can tell the batch skip gate to republish a corpus written before the protocol existed. | `RULES`, `CONFIDENCE_HEADER`, `CONFIDENCE_ROWS`, `FALLBACK_RULE`, `AGENT_FILENAME`, `AGENT_DOC_TOKEN_BUDGET`, `PROTOCOL_VERSION`, `PROTOCOL_MARKER`, `SKILL_NAME`, `SKILL_RELPATH`, `rules_block`, `confidence_block`, `build_part_agent_markdown`, `build_project_agent_markdown`, `build_skill_markdown`, `write_agent_doc`, `agent_doc_current` |
| `cli.py` | argparse CLI, **formatting only** — it holds no retrieval logic (see the seam under Conventions). `_scope()` turns `--part` / `--project` (mutually exclusive, one required) into a `Retriever` or a `ProjectRetriever` and nothing else; project-scoped output labels each hit `[PART]` via the renderers' `show_part`. Reconfigures stdout/stderr to UTF-8 (Windows cp1252). | `main` |

### Corpus layout (the product)

```
parts/<PART>/
├── INDEX.md               # always-loadable index (hard budget, default 3000 tok)
├── AGENT.md               # the retrieval protocol (~1.4k tok, ceiling 1700; carries its version marker)
├── sources.json           # doc inventory: sha256, DocType, revision, nda flag, pinned vendor + evidence
├── manifest.json          # CorpusManifest: sections, files, page ranges, stats, vendor, extraction stats
└── docs/<doc_type>-<hash8>/
    ├── sections/*.md      # atomic; `<!-- source: <doc> p.N[-M] -->` header
    ├── tables/*.csv       # machine-readable twins of each section table
    ├── figures/           # plot/pixel image files referenced by plots.json
    ├── specs.json         # machine-queryable parametric spec records
    ├── plots.json         # searchable plot catalog + file map
    └── search_index.json  # BM25 inverted index over sections/*.md (schema_version)

projects/<name>/
├── project.json           # Project: explicit parts[] (+ role), interfaces, notes, timestamps
├── PROJECT_INDEX.md       # always-loadable design index (hard budget, default 4000 tok)
└── AGENT.md               # the same retrieval protocol, scoped to the design

library/                   # DSA_LIBRARY_DIR — the authoritative document inventory
└── <content_hash>.json    # LibraryDocument: SourceDocument + applicability + user labels

sessions/                  # DSA_SESSIONS_DIR — saved conversations
└── <session_id>.json      # ChatSession: messages, citations, resolved scope
```

`library/` and `sessions/` are gitignored: the first is a local shelf and the
second is personal working state, and both can describe NDA material. Neither
is part of the product a corpus ships — `parts/` and `projects/` are.

The protocol also ships in-repo as the Claude Code skill
`.claude/skills/datasheet-corpus/SKILL.md` — rendered, not written by hand
(`scripts/write_skill.py`).

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
   Synthetic PDFs are built in-test via fitz. The workbench inherits this
   unchanged: **no browser** either. Its backend seam is tested in-process
   against a temp `parts_dir` / `library_dir` / `sessions_dir` (the
   `reset_settings_cache` hook), and the frontend against jsdom — never a
   live server, a real model, or a real driver.
5. **Golden Q&A is the objective function.** Per-part benchmarks at
   `tests/fixtures/golden_qa_<PART>.yaml` (the AFE7950 set — 21 questions —
   is the historical benchmark; no public one exists). `dsa verify`
   discovers a part's benchmark by name and hard-fails when it is missing
   or empty — every corpus is provably verified or provably not. Extend
    the sets whenever new answer paths ship; `dsa verify` must stay at 100%
    for supported paths (gate parts: AD9081 6 Q, LM741 17 Q, QPA1003P 16 Q,
    HMC520A 15 Q). Phase 5, ticket 09 added the two paths the phase itself
    introduced to **all six** sets: one `ask_query` question (a designer's
    words, no symbols) and one `search_query` question (top-1 must be the
    section holding the answer). Both are *twins* — they reuse an existing
    question's cited pages and verbatim substrings, so a new surface is
    proven against the existing objective function instead of a new one.
    **AFE7953 carries one too** — 13 Q (3 text + 7 spec + 1 plot + 2 path), added in
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
- **No retrieval logic in a front end.** There are now **three** front ends —
  `cli.py`, `mcp_server/server.py` and `app/` (the `dsa serve` workbench) — and
  the rule is the same for all three: they may only format what `retrieve/`
  returns. No corpus walk, no
  `specs.json` / `plots.json` parsing, no hand-built `p.N` or `§N` string.
  Citations come from `Citation`, so the CLI, the MCP server and the GUI can
  never drift apart in what they cite. The GUI is the easiest of the three to
  break this in, because a browser wants a JSON shape and it is one line to
  hand-roll one: it must not. Response bodies are built from the hits' own
  `as_dict()` and declared in `app/contracts.py`, which is why `SectionHit`
  gained an `as_dict()` rather than the GUI gaining a serializer.
  `tests/unit/test_retrieve.py::TestCliIsFormatOnly`
  and `tests/unit/test_mcp_responses.py::TestMcpServerIsFormatOnly` fail the
  moment that creeps back in — the same grep-shaped guard over both sources.
  The MCP half of that guard deliberately lives in the **SDK-free** test
  module and reads `server.py` through `find_spec` instead of importing it, so
  the seam is still checked on a core install where the `[mcp]` extra is
  absent (see the testing note below).
  Serialization is part of the seam too: `SpecHit`/`PlotHit`/`SearchHit`
  `as_dict()` and `AnswerPack.as_dict()` own the JSON shapes, and the MCP
  server's declared `SCHEMAS` are asserted *against those very dicts* so a
  declared contract cannot drift from the data it describes.
- **`SourceDocument`'s shape is frozen by the extraction cache.**
  `SourceDocument` is embedded in `RawDocument`, and `RawDocument` is exactly
  what `.cache/extract/<hash>__<backend>.json` serializes. Adding a required
  field to it therefore fails validation on every cache file already on disk,
  and that cache is the most expensive artifact in the repo to rebuild. This is
  why applicability and labels are **not** fields on `SourceDocument`: they
  live on a `LibraryDocument` that wraps it (`source` + `applicability` +
  `labels`), stored once per `content_hash` under `library_dir`, with per-part
  `sources.json` regenerated at publish as a derived read-only view.
  `SourceDocument.part_number` keeps its meaning — the part a document was
  registered under — and becomes advisory rather than authoritative. See
  `docs/adr/0005-documents-apply-to-parts.md`.
- **GUI work does not touch the extraction layer.**
  `extract/pdf_layout.py` is not edited and `PdfLayoutBackend.output_version`
  is not bumped by anything in the workbench, for the reason above: an
  `output_version` bump is a cache invalidation, and re-extracting the shelf is
  not a side effect a UI feature gets to have. Citation highlighting is what
  makes this tempting and what proves it unnecessary — geometry is **derived on
  demand** by `app/locate.py` (open the cited page with PyMuPDF, search for the
  record's own text using the distinctive-needle approach already in
  `structure/pagemap.pin_table_pages`), never persisted into `RawDocument`. A
  miss opens the page with **no** highlight; a box around the wrong row is the
  one outcome worse than no box, and it is the same honesty rule as an unpinned
  page staying `None`.
- **The GUI's scope is resolved and shown, never widened.** There is still no
  "all parts" scope: a question resolves to exactly one Part or Project by
  matching it against built part and project names, the resolution is rendered
  as an editable control attached to the answer, and ambiguity raises a
  question to the user instead of a guess. The invariant that a lookup must
  know what it is asking is satisfied because the scope is on screen, not
  because a picker was forced on the user. See
  `docs/adr/0006-auto-resolved-scope.md`.
- **A caller's string becomes a path in exactly one place.**
  `CorpusIndex.corpus_path` (via `Retriever.corpus_path`) is the only
  translation from a corpus-relative reference to a file, and it *refuses*
  rather than normalizes: absolute paths, drive letters, null bytes and any
  `..` component are rejected, and the resolved target is checked back against
  the part directory so a symlink cannot escape either. `get_figure` checks it
  on the caller's string first (so a traversal attempt is refused *for that
  reason*), then requires the file to be one a plot record claims, then reads
  the path the **catalog** recorded — the bytes returned are the ones the
  citation beside them refers to.
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
- **A project is a curated list, and it never points at nothing.**
  `projects/<name>/project.json` is written by a human or an agent that
  decided; nothing infers membership (no BOM, no netlist — recorded in the
  Phase 5 plan's Out of Scope). `add_parts` therefore refuses a part with no
  `manifest.json` *before* mutating the project and names the build command,
  because a half-added project builds a half-index that cites nothing. The
  free text — each member's `role`, `interfaces`, `notes` — is read and never
  rewritten by the pipeline, so a rebuild cannot edit a designer's words; the
  index is rewritten whole, which is what makes "remove a part, rebuild"
  leave no stale entry. `PROJECT_INDEX.md` degrades in stages and **announces
  the drop** (unlike `INDEX.md`, which degrades silently), and the part list
  plus each member's `INDEX.md` pointer are never what a budget removes —
  the same rule the answer pack applies to citations.
- **A project-scoped answer names its part.** Every hit carries
  `citation.part`, filled by `Retriever` itself, so fan-out is composition and
  never a second retrieval implementation; `ProjectRetriever` relabels
  nothing. Two states must stay distinct across a design, exactly as they do
  for one part: no member searchable at all (`search_unavailable()`, exit 2)
  versus *some* member unsearchable (`search_gap()`), which forbids a
  project-wide "nothing in this design answers that" — absence was never
  established for the part that never ran the path. Project packs interleave
  one answer row per part before any part's second, so a tight budget cannot
  quietly drop the second device.
- **The protocol is written once and ships with the data.** The retrieval
  discipline used to be prose inside `INDEX.md` and, in practice, inside
  someone's prompt. It now lives in `protocol.py` as canonical strings, and
  the three places that carry it — `parts/<PART>/AGENT.md`,
  `projects/<NAME>/AGENT.md`, `.claude/skills/datasheet-corpus/SKILL.md` —
  render those very strings; only the worked examples differ, because they
  name the scope. Do not restate a rule anywhere else: `INDEX.md` and
  `PROJECT_INDEX.md` **point** at `AGENT.md` rather than repeating it, since a
  second copy is a second protocol the moment one is edited.
  `tests/unit/test_protocol.py` fails on any of it — each canonical line must
  appear verbatim in all three, and `SKILL.md` must be byte-for-byte what
  `build_skill_markdown()` renders (regenerate with `scripts/write_skill.py`).
  `AGENT.md` carries `PROTOCOL_MARKER`, its own version, so the batch skip
  gate republishes a corpus written before the protocol existed instead of
  skipping it forever with no protocol beside its index.
- **A new answer path proves itself against the old objective function.**
  A golden question may carry a *path marker* — `spec_query`, `plot_query`,
  `ask_query`, `search_query` — and every marker is judged by that question's
  **existing** ground truth: the printed page it cites and the verbatim
  substrings read off that page. The ask-path question is the designer's-words
  twin of a symbol-path question and must land the same answer on the same
  page; the search-path question must put the section that holds it at rank 1.
  Two rules there are load-bearing. A pack passes only on its *cited* rows
  (a right value beside a wrong page is the assertion this project exists not
  to emit) and only inside its own budget, so budget compliance is part of the
  pass rule rather than a separate check. And a corpus with no current search
  index **fails** the search path with `search unavailable` — the path never
  ran, so nothing was established; passing it would read as "the datasheet does
  not say". Adding a marker is a YAML edit;
  `tests/unit/test_golden_paths.py` fails if any of the six built parts ships
  without both new paths, or if a marker carries a key the verifier does not
  know.
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
- **An optional dependency may never take the test suite down.** The `mcp`
  SDK is in the `dev` extra (so the documented dev install runs the phase-5
  MCP gate) *and* in the standalone `[mcp]` extra (so a core install stays
  lean). A top-level `from mcp import ...` in a test module would turn a lean
  install into a **collection error** that disables every other test, so the
  MCP surface is tested from two sides: `tests/unit/test_mcp_responses.py` is
  SDK-free and always runs (the seam guard, the declared `SCHEMAS` against the
  hits' own `as_dict()`, `corpus_path` path safety, the install hint), while
  `tests/unit/test_mcp_server.py` holds only the session-driven half behind
  `pytest.importorskip("mcp")`. The corpus both halves run against is built
  once in `tests/unit/mcp_corpus.py` so they cannot drift. Same pattern as
  `tests/unit/test_ask.py`'s `pytest.importorskip("jsonschema")`.
- The retrieval index is an in-process cache. Tests get a fresh one from the
  autouse `fresh_retrieval_cache` fixture; production code invalidates by
  rebuilding the corpus (which rewrites `manifest.json`).
- **Publish artifacts are part of the skip gate.** `batch.skip_reason` refuses
  to skip a part whose documents lack a current-schema `search_index.json`
  (`publish.search_index_current`), `specs.json` (`publish.specs_current`) or
  `plots.json` (`publish.plots_current`), or whose `AGENT.md` is missing or of
  an older protocol version (`protocol.agent_doc_current`), so a corpus
  published before a
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