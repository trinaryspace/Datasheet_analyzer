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

Gate parts (built in-tests from the ungated `tests/fixtures/pdf/` copies; measured in `PHASE_4_REPORT.md`, LMX1204 in `Reports/PHASE_6_REPORT.md`):

| Part | Vendor | Revision | Pages | Sections | Tables acc/rej | Specs | Plot files | Verify |
|---|---|---|---|---|---|---|---|---|
| AD9081 | adi | Rev. 0 | 45 | 34 | 29/0 | 549 | 100 | 4 Q @ 100% |
| LM741 | unknown* | SNOSC25D | 17 | 40 | 6/2 | 71 | 3 | 15 Q @ 100% (12 text + 3 spec) |
| QPA1003P | qorvo | Rev. I | 20 | 20 | 5/2 | 41 | 4 | 14 Q @ 100% (11 text + 2 spec + 1 plot) |
| HMC520A | adi | Rev. A | 32 | 36 | 6/1 | 85 | 107 | 13 Q @ 100% |
| LMX1204 | unknown* | SNAS800B + SNAU269A | 72 + 25 | 79 | 96/25 | 853 | 54 | 15 Q @ 100% (10 text + 3 register + 2 path) |

*LM741 carries no page-1 brand mark; the gate pins it `--vendor unknown` (recorded as cli-override evidence). LMX1204 is pinned the same way for a different reason: it *is* a TI part, so detection would prefer the network-bound `ti_html` backend and no recorded document-viewer pages exist for it — `unknown` routes it through the offline floor. It is the phase-6 ticket-05 register gate and the one gate part with two documents: the datasheet plus its programmer's guide (`LMX1204_registermap.pdf`) attached as a `register_map` companion.

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
dsa add-doc register_map.pdf --part AFE7950 --type register_map  # register maps route to pdf_layout (ticket 05)
dsa plots --part AFE7950 --q "Output Fullscale"        # + --json; every hit carries its confidence grade
dsa pins --part AD9081 --type power                    # pin lookup: --pin A1 / --name VDD / --type / --q / --json
dsa regs --part LMX1204 --addr 0x19                    # register lookup: --addr (by value) / --name / --q / --json
dsa project new rf-frontend --interfaces "AFE7950 TX -> HMC520A DSA"
dsa project add rf-frontend AFE7950 --role "quad RF transceiver"
dsa project add rf-frontend HMC520A AD9081             # unbuilt part = refused, with the build command
dsa project build rf-frontend                          # PROJECT_INDEX.md under its budget
dsa project status                                     # projects + their parts
dsa ask --project rf-frontend "does anything here need a 1.8 V rail?"
dsa search --project rf-frontend "sysref"              # --project also on query / plots; hits labelled [PART]
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
| `models.py` | **The contract.** Pydantic v2 models shared by all stages. Change deliberately. | `SourceDocument`, `TOCEntry`, `Footnote`, `TableBlock`, `FigureRef`, `SectionNode`, `RawDocument`, `SectionFile`, `CorpusManifest`, `CorpusStats`, `ExtractionStats`, `GoldenQuestion`, `Project`, `ProjectMember`, `DocType`, `Confidence`, `RECONSTRUCTION_HEADER`/`RECONSTRUCTION_RESCUED`, `SpecUnit`, `SpecRecord`, `SpecTableInfo`, `SpecSet`, `PlotRecord`, `PlotSet`, `PinRecord`, `PinSet`, `PinType`, `RegisterRecord`, `RegisterWord`, `RegisterSet`, `DerivedValue`, `ValueKind`, `ParseConfidence` |
| `provenance.py` | **The invariant-8 round trip** (phase 6, ticket 01): the id format a derived value's `source` points at, and the resolver that walks it back. `spec_record_id` mints the stable, document-scoped ids (`rec_1`, `rec_2`, …) that `structure/specs.py` stamps on every published spec record — `pin_record_id` is its twin for `pins.json` (`pin_1`, …; the differing prefix is legibility, the artifact name in the reference is what disambiguates) — the ordinal is the id because emission order is fully determined by the document, so a rebuild of identical input reproduces every id exactly. `source_ref` spells the reference (`docs/<doc>/specs.json#rec_412`), `parse_source` refuses rather than repairs a malformed one, and `resolve_source` reads the record + its printed page through `CorpusIndex` (imported at call time, so the structure stage does not drag the retrieval core in). The ADR's unqualified `specs.json#rec_412` shorthand resolves only when exactly one document of the part carries that record: an ambiguous reference warns and resolves to nothing, because a coin flip here puts an unverified number on a card. | `DerivedValue` (in `models.py`), `spec_record_id`, `source_ref`, `parse_source`, `resolve_source`, `SourceRef`, `ResolvedSource`, `SPECS_ARTIFACT`, `PLOTS_ARTIFACT`, `PINS_ARTIFACT`, `REGISTERS_ARTIFACT`, `pin_record_id`, `register_record_id` |
| `config.py` | pydantic-settings, `DSA_` prefix; `ANTHROPIC_API_KEY` plain. No filesystem side effects at import. `PIPELINE_VERSION`, `SPECS_SCHEMA_VERSION`, `PLOTS_SCHEMA_VERSION`, `SEARCH_SCHEMA_VERSION` and `CARD_VERSION` (the derivation-rule version of ADR 0005, overridable as `DSA_CARD_VERSION`, stamped into every manifest and read back by the batch skip gate) live here, as does `ask_budget` (`DSA_ASK_BUDGET`, default 4000 — the `dsa ask` pack budget when `--budget` is not given), `projects_dir` (`DSA_PROJECTS_DIR`, default `projects`), `project_index_token_budget` (`DSA_PROJECT_INDEX_TOKEN_BUDGET`, default 4000 — the hard `PROJECT_INDEX.md` budget) and `mcp_max_tokens` (`DSA_MCP_MAX_TOKENS`, default 6000 — the hard cap on every MCP response). | `Settings`, `get_settings()` (lru_cached; `reset_settings_cache()` for tests) |
| `tokens.py` | THE token counter (chars/4). Every reported token number flows through it. | `count_tokens`, `truncate_to_tokens` (budget ≤ 0 → `""`) |
| `acquire/inventory.py` | Part = folder of docs. `sources.json` per part; identity = sha256 of bytes; evidence-pinned vendor at acquire (detection or `--vendor` override). Doc-type shared lexicon in `_HINTS`: errata → register/regmap → app-note (sbaa/slaa/swra, `ug-`-prefix companions) → datasheet, so register words always beat a `ug-` prefix. | `register_source`, `save_inventory`, `load_inventory`, `detect_doc_type`, `pin_vendor` |
| `vendor.py` | **Vendor routing record, not a rulebook**: profile registry (brand lexicon + backend preference chain), evidence-pinned detection on page-1 text/filename, drift warnings. Default `ti`; no layout behavior hangs off the vendor string. `select_backend` routes by **doc type** as well: a datasheet follows the profile's chain, a `REGISTER_MAP` goes to `register_map_backend` (`pdf_layout` for every vendor — phase 6, ticket 05: a register summary read as paragraphs answers no bring-up question), and every other companion keeps `companion_backend` (`pdf_text`). | `VENDOR_PROFILES`, `detect_vendor`, `select_backend`, `warn_vendor_drift`, `is_known_vendor` |
| `extract/base.py` | Backend protocol + registry. | `ExtractionBackend`, `register`, `get_backend` |
| `extract/pdf_structure.py` | PyMuPDF: content hash, page count, **printed TOC (authoritative page numbers)**, per-page text (verification/pinning only), revision sniffing from a shared lexicon ("Rev."-token shapes — "Rev. 0"/"Rev. A"/"Rev. I", "Rev. N to Rev. M" keeps the last token — plus TI doc-ids, digit-required so bare S-words like "SUPPORT" never read as ids). Layout analysis lives in `pdf_layout`, never here. | `read_toc`, `page_texts`, `compute_content_hash`, `make_source`, `split_number`, `sniff_revision` |
| `extract/http.py` | Fetchers. `CachingFetcher` (disk cache `.cache/http`), `CachingBinaryFetcher` (`.cache/http-bin`), `ReplayFetcher`/`ReplayBinaryFetcher` (hermetic tests: miss = hard error), `MappingFetcher`. | `Fetcher` / `BinaryFetcher` protocols |
| `extract/ti_html.py` | Primary TI content backend: TI document-viewer HTML (real tables, MathML, footnotes — no OCR, no hallucination). TI keeps this path; every other vendor routes to the layout floor. | `TiHtmlBackend`, `parse_toc`, `parse_section` |
| `extract/pdf_layout.py` | **Vendor-neutral layout floor** (offline, PyMuPDF-only): furniture by slot recurrence + universal page-machinery patterns (zero vendor strings) **confined to the document's margin bands** (`_margin_bands`, ticket 05 — see the conventions), structure ladder (outline → printed-TOC dot-leader parse → per-page), page-ranged sections, honest unnumbered identity, (tickets 03–04) tables: caption-anchored hypotheses, pitch-based row grouping with wrapped-cell merging, header-anchored column clusters + a best-scoring retry ladder (every band set gated and scored; the header-declared edge share selects the winner, ties prefer the coarsest split, i.e. fewest bands — a finer tie can only carve interior words of declared columns), a reconstruction gate (rejected hypotheses recorded with reasons in `ExtractionStats`; inter-span, not start-to-start, clustering so multi-word-span note lines classify as sentences), multi-page continuation merging (the winning rung is recorded on every accepted grid as `TableBlock.reconstruction` — `header-anchored` when the table's own declared columns passed the gate first try, `rescued` when only a coarser all-word split did; the per-record confidence grade reads it), test-conditions preamble attachment, and (ticket 05) footnotes + figures: superscript citation markers from span font geometry (`_Span` carries size + glyph box; glued, raised, ≤0.82× markers land in `TableBlock.cited_markers`), trailing numbered lines attach as bare-canonical `Footnote`s with wrapped-continuation merging and positional marker-less attach; `Figure N.`-caption catalog (`FigureRef`, caption line consumed, table regions end at figure captions) plus `figure_anchor_map()`/`figure_caption_key()` clip geometry for the publisher. (Ticket 09) heading-anchored tables for the captionless era (regions under printed section headings run the same ladder + gate; header-token lines and lone section numbers split anchors sanely; side-by-side pairs split first at their mirrored header; captionless tables render "## Unnumbered table", never a fabricated number), rowspan materialization (spanning symbols replicate into child rows by indent chain / nearest-anchor fill), title-anchored figures (heading-sized line inside a drawn emphasis band with a big rect under its own x-column → `FigureRef`), and per-row page attribution of merged multi-page grids (`TableBlock.row_pages`). (Phase 6, ticket 05) three fixes the register summary needed and every table gains: furniture is margin-only, header band edges carry a float tolerance (`_BAND_EPSILON`), a title-key line ends a region only when it is alone on its baseline (`_is_section_break`), and a `(continued)` caption continues its table instead of starting a doomed second one. | `PdfLayoutBackend`, `parse_printed_toc`, `figure_anchor_map`, `figure_caption_key`, `figure_title_anchor_map` |
| `extract/pdf_text.py` | Degraded backend for errata/app notes (register maps route to `pdf_layout` since phase 6, ticket 05): paragraphs only, no trusted tables/figures, contextual page-number stripping. | `PdfTextBackend` |
| `structure/tables.py` | HTML table → atomic `TableBlock`; full rowspan/colspan expansion; markdown + CSV precomputed. The **only** mutation it performs is dropping C0 control characters from the CSV twin: a font whose ToUnicode map points a ligature at U+0001 (measured on `lmx1204.pdf`) yields a NUL that `csv.writer` cannot encode under any dialect, and one such glyph in one figure otherwise takes the whole build down. `TableBlock.grid` keeps whatever was extracted. | `html_table_to_block`, `cited_markers`, `cell_text` |
| `structure/footnotes.py` | `div.tablenote` → `Footnote`; orphan/uncited audit. | `parse_tablenote`, `attach_footnotes`, `audit_table_footnotes` |
| `structure/boilerplate.py` | Ordered regex rules. **No bare-number rule** (digits-only lines are data). | `strip_boilerplate`, `is_boilerplate` |
| `structure/pagemap.py` | Sections → PDF pages (exact number → fuzzy title → inherit, with provenance report); exact table-page pinning via PDF page text. | `assign_pages`, `pin_table_pages` |
| `structure/roles.py` | Header → semantic role (symbol/name/conditions/min/typ/max/value/unit). Deterministic regex + positional inference for empty TI headers. | `assign_roles`, `classify_table` |
| `structure/units.py` | Unit canonicalization (U+2126 → ohm, etc.) for `specs.json` only — and the lexicon the numeric layer scales from. | `canonical_unit`, `normalize_text`, `CANONICAL_UNITS` |
| `structure/quantities.py` | **The numeric layer** (phase 6, ticket 02): printed value text → a comparable SI number, pure and always allowed to fail. `parse_quantity` is an **anchored** grammar — a cell parses only when the whole of it is a quantity, so `Note 2` holds a digit and still returns `None` — over the four shapes a datasheet prints (`point` \| `range` \| `bound` \| `tolerance`), scaling through `SI_UNITS`, which covers every canonical unit of `units.py` (a unit with no scale is **refused**, because silently dropping a factor of 1000 is the confident-and-wrong failure ADR 0005 exists to prevent). Trailing footnote markers (`1350(2)`, a `Vppdiff(3)` unit column) are stripped as provenance the record already carries. `record_quantities` parses each value cell independently and is what a consumer comparing one *specific* limit must use; `record_quantity` picks the record's representative by the documented selector (`value` → `typ` → `max` → `min`, never joining two cells into a range the datasheet never printed); `annotate_records` writes it into the record's additive fields in `structure/specs.py`. `parse_population` is invariant 8's honesty half — the report a sorting or comparing consumer must print instead of dropping rows — and `parse_rate` its measurement twin, by section. | `Quantity`, `parse_quantity`, `record_quantities`, `record_quantity`, `annotate_record`, `annotate_records`, `parse_population`, `ParsePopulation`, `parse_rate`, `ParseRate`, `SI_UNITS`, `DERIVATION` |
| `structure/device_tables.py` + `registry/device_tables.yaml` | **The device-table abstraction** (phase 6, ticket 03). A pin table and a register-summary table are the same structural animal — wide, repetitive, keyed by a first column — so one pipeline serves both: **identify → map columns → validate → emit**. Identification is by checked-in lexicon (header phrases matched **whole**, so `Part Number` is not a pin column; teaching a vendor's `Ball No.` is a YAML edit): a table's headers declare it (the key column plus at least `MIN_HEADER_FIELDS` fields in all) or its caption / section title names it. Mapping is header-match first with a **positional fallback that fires only when the headers matched nothing** — a half-understood header row has told us something we did not follow, and filling the rest by position would be a guess dressed as a reading; when the fallback fires and `pdf_layout`'s first-row-is-headers rule has parked the first *pin* in `headers`, that row is read as data (`HEADER_ROW_INDEX`) rather than lost. Validation rejects the **whole** table with a recorded reason (no keyed rows, a key column of prose, a duplicate key, addresses out of order) and never emits a partial set, because a designer who greps for a pin and gets no hit concludes it does not exist. `record_rejections` puts those reasons in `ExtractionStats.rejection_reasons` beside the reconstruction gate's own, and deliberately leaves the detected/accepted/rejected **counts** alone — they measure reconstruction, and a table that reconstructed perfectly and then turned out not to be a pin table did not fail reconstruction. Multi-value key cells expand (`A1, A2, B1`, `A1-A4`), every expanded record keeping its source row's provenance and the cell as printed; a register address is never expanded (`0x00-0xFF` is one block, not 256 inventions). **A wrapped row is one row** (ticket 04): a printed entry breaks its description — and its key list, and sometimes its name — over several grid lines, and ticket 09's rowspan materialization even repeats the key cell into them, so a line printing nothing in the kind's `identity:` column (a lexicon field; `name` for pins) continues the entry above, contributing its text and any key-shaped keys. A line that *does* print an identity is a new entry even when its key cell repeats — unless the entry above left that identity **mid-list** (a trailing `,`, and only a comma — `-`, `+` and `/` end ordinary mnemonics like `VREF+`, so reading them as unfinished would fuse two pins into one record and drop a pin instead of rejecting the misread grid whole), which is how a wrapped name list looks on the page. The narrowness is the point: everything else stays a duplicate and rejects the table, and a kind that declares no `identity:` keeps the pre-ticket-04 reading exactly. A count cross-check **warns** (`cross_check_count`) per ADR 0005's decided outcome. No consumer ships with it: `pins.json` / `registers.json`, publication shape and the per-record grade belong to tickets 04–05. | `DeviceRecord`, `DeviceTable`, `DeviceTableSet`, `DeviceTableRejection`, `DeviceSpec`, `DeviceLexicon`, `ColumnMap`, `load_device_lexicon`, `identify_table`, `map_columns`, `expand_keys`, `read_device_table`, `read_device_tables`, `record_rejections`, `cross_check_count`, `PIN`, `REGISTER` |
| `structure/pins.py` + `registry/pin_types.yaml` | **`pins.json`** (phase 6, ticket 04) — the first consumer of the device-table abstraction, and the artifact a designer lives inside during schematic capture. `build_pinset` turns every *accepted* pin table of a document into one `PinRecord` per pin (a printed `A1, A2, B1` is three citable records, each still quoting its row and its page) and always returns a set, even an empty one: a document whose pin table was rejected still has a finding, and the rejection reason goes to `ExtractionStats.rejection_reasons` here. The **publisher** is what refuses to write a file for a set with no pins, which is how "no `pins.json` rather than a partial one" is enforced. `type` is the one derived field — a structural label from the checked-in lexicon over the pin's name and description, name tier first (a mnemonic identifies; a description describes), longest phrase wins inside a tier, and a tie or a miss is `UNKNOWN` with no evidence — so every classified record publishes `type_evidence`, the phrase that decided it. `stated_pin_count` reads the package cross-check's other half from a **hyphen-joined package descriptor** (`324-ball BGA`) and only when every descriptor in the document agrees; the mismatch **warns** (ADR 0005's decided outcome) into `CorpusManifest.derived_warnings`, and it runs even when nothing was published, because "24 terminals stated, none extracted" is the most useful thing a pin-less part can say. | `PinRecord`, `PinSet`, `PinType` (in `models.py`), `build_pinset`, `classify_pin_type`, `stated_pin_count`, `PinTypeLexicon`, `load_pin_lexicon` |
| `structure/registers.py` | **`registers.json`** (phase 6, ticket 05) — the second consumer of the device-table abstraction, and the artifact a firmware engineer lives inside during bring-up. `build_registerset` turns every *accepted* register-summary table into one `RegisterRecord` per printed address and always returns a set, even an empty one; the **publisher** is what refuses to write a file for a set with no registers, which is how "no `registers.json` rather than a partial one" is enforced (same rule, same reason, as `pins.json`). Two fields are derived. `address.value` is `parse_register_word`'s **anchored** reading of the printed cell — hex only by the marker the document printed (`0x…` / `…h`), decimal otherwise, so a caller's `--addr 6660` and a record's `0x1A04` mean the same number and a cell the grammar cannot read keeps its string with `value: null` rather than a guess from its leading digits. `reset` is the summary table's own reset column when it has one, else the value the register's printed declaration heading states (`R25 Register (Offset = 0x19) [Reset = 0x0211]`, the form every TI programmer's guide uses and the only place LMX1204 states a reset), joined on the **parsed offset** and refused when the heading names a different register than the row. Every reset publishes the printed line it was read from and the page that line is on — `_region_page`, not `TableBlock.page`, because `pin_table_pages` rewrites the latter by cell-text match and a field table of `R`, `R/W` and `0x0` matches half a register map (measured: LMX1204's Table 1-25 pins to p.17 and is printed on p.19). `access` is verbatim or `""`: TI states access per bit field, which is ticket 06's shape. `RegisterSet.n_reset_stated` + a warning report the gap ADR 0005 requires a consumer to say out loud. | `RegisterRecord`, `RegisterWord`, `RegisterSet` (in `models.py`), `build_registerset`, `parse_register_word`, `read_declarations`, `RegisterDeclaration` |
| `structure/aliases.py` + `registry/aliases.yaml` | **Alias lexicon — data, not code** (same philosophy as the vendor brand lexicon): a designer's phrases per canonical symbol family. YAML entry = `names` (whole-phrase matched inside the query *and* against a record's own symbol/name text, so `Junction temperature`-as-symbol layout-floor parts resolve through the same entry as TI's `TJ`), `expect_unit` (a **ranker, never a filter** — it promotes the candidate whose canonical unit matches and never suppresses a unitless record), `kind`, and `prefix_match` + `prefixes` for families (`IDD` → `IVDD1P8`, `IVDD1P2`, …). The module only answers word questions (`by_symbol`, `phrase_hits`, `prefix_hits`, `nearest_names`); the ladder over records lives in `retrieve/`. Seeded from the six built corpora by `scripts/seed_aliases.py` (procedure in its docstring; harvest recorded at `tests/fixtures/alias_seed_symbols.json`). | `AliasLexicon`, `AliasEntry`, `load_lexicon`, `normalize`, `token_overlap` |
| `structure/search.py` | **Search vocabulary — one tokenizer, index time and query time** (same "words, not records" split as `aliases.py`). Lowercase **ASCII-only** (Unicode lowercasing folds U+2126 and U+03A9 onto one ω; this corpus keeps the glyph the vendor printed), **no stemming**, stopwords are grammatical scaffolding only (no single letters, no `a`/`in` — those are units). Compound unit strings index whole *and* split (`dBc/Hz` → `dbc/hz`, `dbc`, `hz`). A token with no letter is **not** indexed: numerals rank nothing in BM25, they are what would make an index rival the size of the text, and values have an exact path through `specs.json`. | `tokenize`, `body_text`, `fold`, `STOPWORDS` |
| `structure/confidence.py` | **Per-record confidence — one rule, one place.** `ExtractionStats` grades a document; this grades a *row*, at structure time, where the evidence still exists (how the grid was reconstructed, whether the page is pinned, what the row printed). Spec rule, worst-first: `low` = grid rescued by the retry ladder **or** a value whose unit the alias lexicon expected is missing; `medium` = the page is section-range only **or** the row printed no value; `high` = pinned exact page + header-declared reconstruction + a printed value. Plots have no grid, so theirs is citation precision: exact page + caption = `high`, section range or captionless = `medium`, no page = `low`. `mix()` counts a part by grade for the manifest. | `grade_spec_record`, `grade_plot_record`, `grade_pin_record`, `grade_register_record`, `grade_of`, `mix`, `page_is_exact`, `has_value`, `unit_expected_but_missing` |
| `structure/specs.py` | `RawDocument` → `SpecSet` / `specs.json`. Pure transform over `TableBlock` grids. Skips `pdf_text` docs. A merged multi-page grid's per-row pages (`row_pages`) beat the table's caption page, so continuation rows cite their own printed page. Every record is graded here via `structure/confidence.py`, given its stable id via `provenance.spec_record_id`, and annotated with the numeric layer via `structure/quantities.py` — which writes only the SI fields and never a verbatim cell. | `table_to_records`, `build_specset` |
| `structure/plots.py` | `RawDocument` → `PlotSet` / `plots.json`. Stable IDs + section/caption tags; every record graded via `structure/confidence.py` (the pixel `file` is deliberately not part of the grade). | `build_plotset`, `figure_number`, `section_tags`, `caption_tags` |
| `structure/corpus.py` | `RawDocument` → per-section render plans (markdown + CSV twins). | `build_section_plans`, `section_stem`, `slugify` |
| `enrich/llm.py` | LLM interface + `AnthropicClient` + `FakeClient`. All LLM use goes through `LLMClient`. | — |
| `enrich/index.py` | INDEX.md builder under a hard token budget (staged degradation). `DeterministicWriter` (offline) / `LLMWriter` (one batched call, falls back safely). Its "How to use this corpus" block is a **pointer** to `AGENT.md`, never a copy of the protocol (ticket 08). | `build_index_markdown`, `SectionMeta` |
| `publish/writer.py` | Writes corpus + `manifest.json`; also writes `docs/<doc>/specs.json`, `docs/<doc>/plots.json` (when the corresponding sets are supplied), `docs/<doc>/pins.json` (only when the supplied set **has pins** — a set with none *deletes* any earlier file, so a corpus never serves a superseded pin table), `docs/<doc>/registers.json` (the same rule, for the same reason) and `docs/<doc>/search_index.json` (always, for every document). Also emits `AGENT.md` beside `INDEX.md` (the ticket-08 protocol; its measured size lands in `CorpusStats.agent_doc_tokens`). Records the index economics in `CorpusStats` (`search_index_bytes` vs `section_bytes`), each section's `search_tokens`, and the part's per-record confidence mix (`spec_confidence` / `plot_confidence` / `pin_confidence` / `register_confidence`, counts by grade). Also answers the publish-cache-key question for the artifacts it writes: `specs_current` / `plots_current` / `pins_current` / `registers_current` (schema-version checks the batch skip gate calls; an absent file reads as current, because a `pdf_text` document publishes none of them and most datasheets print no pin table). | `write_corpus`, `doc_dir_name`, `doc_dir_name_for_source`, `specs_current`, `plots_current`, `pins_current`, `registers_current` |
| `publish/search_index.py` | Builds `search_index.json` from the very markdown the writer emits, so searchable and readable can never diverge. Serialized **deterministically** (sorted keys, compact separators, `ensure_ascii=False`): identical input ⇒ byte-identical file. `search_index_current()` is the publish-cache-key check the batch skip gate calls — an absent or older-schema index rebuilds. | `build_search_index`, `dump_json`, `write_search_index`, `search_index_current`, `INDEX_FILENAME` |
| `publish/plots.py` | Downloads/render plot images into `figures/` and updates `PlotRecord.file`. `render_figure_regions` clip-renders pdf_layout figures from the region above their `Figure N.` caption (geometry via `figure_anchor_map`, drift-free); ti_html downloads + full-page fallback stay as before. | `fetch_plot_images`, `render_figure_regions`, `render_plot_pages_fallback` |
| `retrieve/` | **The retrieval core — every corpus lookup, once.** `index.py`: `CorpusIndex.load(part_dir)` reads a part's `manifest.json` + every `specs.json` / `plots.json` once and caches it on corpus identity `(part dir, manifest.json mtime + size, PIPELINE_VERSION)`, so a rebuild invalidates naturally and a part with no manifest is never cached (no identity → re-read, never stale); section bodies load lazily. `search.py`: BM25 (k1=1.2, b=0.75, non-negative IDF) over the loaded `search_index.json`s, corpus statistics merged across a part's documents, **ties broken on (doc dir, section file)** so two identical corpora rank identically, plus snippet recovery — ±240 chars around the best-scoring term, grown to a sentence boundary within 120 chars of slack, `…` marking only a genuine cut, section heading dropped (the hit carries it as a field). `retriever.py`: `Retriever.specs/plots/sections/search` return typed hits; `specs()` runs the **alias ladder**, first non-empty rung wins — exact symbol (plus its ticket-09 materialized child rows, and only when the parent row matched exactly) → alias phrase → alias prefix family → symbol/name substring (the pre-ticket-02 behaviour) → token-overlap fuzzy (≥ 2 tokens, ≥ 0.6 overlap). `suggest_specs()` is the honest no-match path: nearest corpus terms then lexicon phrases, never a rung-6 guess. `suggest_specs()` is the honest no-match path; `search_unavailable()` is search's — a corpus with no current index is told to rebuild instead of being handed an empty result that reads like "not in the datasheet". `results.py`: `Citation` (the only place `p.N` / `p.N-M` / `§N, p.N` is spelled), `SpecHit` (+ `as_dict()`, the one JSON shape the CLI and MCP both emit), `PlotHit` (+ `as_dict()`), `SectionHit`, `SearchHit` (+ `as_dict()`, `heading`, `score`, `snippet`) — each carrying doc, page range, `matched_via` (`symbol` \| `alias:<phrase>` \| `alias-prefix:<prefix>` \| `symbol-substring` \| `name-substring` \| `fuzzy` \| `section` \| `fulltext` \| … ) and `confidence` read off the record by `record_confidence()` (a corpus with no grade on disk reads `unknown`; section and full-text hits are `unknown` by construction — a grade belongs to an extracted record, not to verbatim text). Corrupt `manifest.json` / `specs.json` / `plots.json` / `search_index.json` warns and skips; it never takes the part down. `pack.py` (ticket 05) is the answer pack: `Retriever.ask()` → `build_pack()` routes deterministically (spec ladder → plot vocabulary + `plots_for_terms` → BM25 → `search_unavailable()` → explicit no-match; **no LLM in the path**), then fits the result into a token budget over a **reserved tail** (header + first answer line + verify footer) so citations are never what a budget removes. It is the one place in `retrieve/` that renders text, because a budget cannot be enforced on a payload the core did not produce. `ANSWER_PACK_SCHEMA` + `validate_pack` are the declared `--json` shape, dependency-free, reused by ticket 07's MCP tool. `project.py` (ticket 06) is the same lookups over a whole design: `ProjectRetriever.for_parts(name, dirs)` holds one `Retriever` per member and fans out in membership order (search merges by score with `(part, doc, file)` underneath, because BM25 scores from two corpora are not strictly comparable). It relabels nothing — every hit already carries `citation.part`, which `Retriever` fills — and it separates two states a single part cannot have: `search_unavailable()` (no member can be searched at all → exit 2, as for one part) from `search_gap()` (some member could not, so absence was never established). `build_project_pack` routes each member independently, orders answering members by route strength then membership, and **interleaves one row per part before any part's second**, so a tight budget cannot spend itself on one device. Ticket 07 added the lookups a second front end needed and neither front end may implement: `discover_parts()` (part directories, built or not — a half-built part is listed, not hidden), `CorpusIndex.index_markdown()` / `Retriever.index_markdown()` (`INDEX.md` through the same lazy cache as section bodies), `Retriever.resolve_section(ref)` (one section from a caller's reference: exact number → corpus file/basename → number prefix → title substring, manifest order underneath), `Retriever.plot_for_file(file)` (the record that cites an image — a loose file no record claims resolves to nothing) and `CorpusIndex.corpus_path(rel)`; phase 6, ticket 05 added `registers()` + `register_gap()` — the same shape one noun over, with `addr` resolving by **parsed value** (`0x1A04`, `0x1a04` and `6660` are one question) and falling back to the printed string for a cell that never parsed; phase 6, ticket 04 added `pins()` — exact designator, name/description substring, or lexicon type, deliberately **not** a ladder because a near-miss on a pin designator is a wiring error — and `pin_gap()`, its honest-absence half: a corpus with no pin table must never answer "no such pin", exactly as `search_unavailable()` stops an unsearchable corpus reading as "the datasheet does not say" (the only translation from a caller's string to a path; see the conventions). | `CorpusIndex`, `Retriever`, `ProjectRetriever`, `Citation`, `SpecHit`, `PlotHit`, `PinHit`, `RegisterHit`, `SectionHit`, `SearchHit`, `AnswerPack`, `PackLine`, `PackExcerpt`, `build_pack`, `build_project_pack`, `ANSWER_PACK_SCHEMA`, `validate_pack`, `PLOT_VOCABULARY`, `score_sections`, `clear_index_cache`, `discover_parts`, `INDEX_FILENAME` |
| `projects/` | **The noun above `part`.** `store.py` owns `projects/<name>/project.json` — an explicit, human-curated part list (`ProjectMember.part_number` + a free-text `role`) plus `interfaces` / `notes`. Membership is chosen, never inferred: no BOM/netlist parsing, `add_parts` refuses a part with no `manifest.json` *before mutating anything* and names the build command, and a project name is validated (not sanitized) because rewriting `../etc` would hide the mistake. `index.py` renders `PROJECT_INDEX.md` under `project_index_token_budget` with staged degradation — conventions → notes → interfaces → per-member stats → roles — leaving the part list and each member's `INDEX.md` pointer at every stage, and **saying so** when anything was dropped (`INDEX.md` degrades silently; a project index does not). Member facts are read through `CorpusIndex`, never by walking a corpus. `write_project_index` also writes the project's `AGENT.md` — building the index *is* a project's publish step, and the protocol must ship with the data. Project-scoped *retrieval* deliberately lives in `retrieve/project.py`, not here. | `Project`, `ProjectMember` (in `models.py`), `new_project`, `load_project`, `save_project`, `add_parts`, `remove_parts`, `list_projects`, `part_dirs`, `is_built`, `write_project_index`, `build_project_index_markdown`, `summarize_project`, `ProjectError` |
| `query.py` | **Back-compat shim over `retrieve/`** (deprecated as an implementation; signatures and record-list returns kept for existing callers) plus the renderers, which take their citation strings from `Citation`. `format_spec_hits` / `format_plot_hits` / `format_no_match` render typed hits (rung + confidence + nearest candidates); `format_answer` / `format_plot_answer` keep the record-list shape. | `SpecQuery`, `format_answer`, `format_spec_hits`, `format_no_match`, `find_plots`, `format_plot_answer`, `format_plot_hits` |
| `evalh/citations.py` | Golden Q&A verification: corpus-contains AND page-truth, two-tier (exact then squash-normalized). Also the four **path** pass rules, which run against `retrieve/` and never against a walk of their own: `spec_query` (page match + value substrings), `plot_query` (same, plus an on-disk image >1 KB), and (ticket 09) `ask_query` — one `dsa ask` pack whose *cited* rows carry the substrings, by the recorded route, inside its own budget (`pack_answers_question` is that rule, deliberately the spec rule applied to a pack) — and `search_query` — the **top-1** hit must be a section covering a cited page whose text holds the answer, with a corpus that has no current index failing as `search unavailable` rather than passing. | `verify_questions`, `verify_spec_queries`, `verify_plot_queries`, `verify_pin_queries`, `verify_reg_queries`, `verify_ask_queries`, `verify_search_queries`, `pack_answers_question`, `load_golden_yaml`, `contains`, `squash` |
| `evalh/golden.py` | Report rendering + token economics measurement. | `render_verification_report`, `render_spec_query_report`, `render_plot_query_report`, `render_pin_query_report`, `render_reg_query_report`, `render_ask_query_report`, `render_search_query_report`, `render_token_economics`, `estimate_lookup_tokens` |
| `pipeline.py` | Orchestration + extraction cache (`.cache/extract/<hash>__<backend>.json`, atomic write-temp + rename with a Windows rename retry). Vendor routing via the pinned vendor; `--vendor` repins the inventory; drift warnings never re-route. `build_part` takes an additive `on_progress` stage-boundary callback (extracting/structuring/enriching/publishing; no-op default — existing callers unchanged; batch's event emitter wires into it). | `build_part` |
| `batch.py` | Batch runner: flat `*.pdf` scan of a directory, one job per PDF (part = uppercase stem), failure isolation, per-job summary + `BatchReport`. Hash-gated skip (`skip_reason`: manifest + `PIPELINE_VERSION` + inventory sha256; `--force` / `--no-cache` disable it; changed PDFs re-register). Stage events: every transition (queued/extracting/structuring/enriching/publishing/done/failed/skipped) emits one prefixed terminal line AND one JSONL record (`.cache/batches/<dirstem>-<run>/batch.jsonl`; header event carries the job list) via `EventEmitter` — the JSONL is the monitoring source of truth; `build_part`'s additive `on_progress` callback (no-op default) is what fired inside jobs. Parallel dispatch: bounded `ThreadPoolExecutor` (`--workers N`, env `DSA_BATCH_WORKERS` default 4; `workers=1` is the exact serial path), job-scoped wiring (backend/fetchers/LLM client created per job — no shared mutable pipeline state), final events as jobs complete, report in run order; extraction-cache writes are atomic (write-temp + rename) so identical PDF bytes can never corrupt `.cache/extract/<hash>__<backend>.json`. | `run_batch`, `run_job`, `discover_jobs`, `skip_reason`, `EventEmitter`, `log_path_for`, `BatchReport`, `BatchError`, `STATUS_*` |
| `mcp_server/` | **The second front end** (`dsa serve --mcp`, Phase 5 ticket 07): the corpus as MCP tools over **local stdio** — no HTTP, no auth, no multi-tenancy. `server.py` registers nine tools (`list_parts`, `list_projects`, `get_index`, `search`, `find_spec`, `read_section`, `find_plots`, `get_figure`, `ask`) and two index resources (`dsa://part/<PART>/INDEX.md`, `dsa://project/<NAME>/PROJECT_INDEX.md`, registered as templates *and* as concrete resources for what is on disk at start-up). It is bound by the same seam `cli.py` is: every lookup goes through `retrieve/`, every citation comes from `Citation`, every hit shape from that hit's own `as_dict()`, and the pack from `retrieve/pack.py`. `responses.py` is deliberately **SDK-free** — the envelope (`tool`, `scope`, `error` vs `warning`, `truncated`, `over_cap`, `notice`, `citations`, `tokens`), the declared per-tool `SCHEMAS` (checked with `retrieve.pack.validate_pack`, not a second validator) and the response cap live there, because the `[mcp]` extra is optional and the rule that bounds a response must not vanish with it. `DSA_MCP_MAX_TOKENS` (default 6000) caps every tool response *and* every resource read: list bodies fill greedily in retrieval order, text bodies trim to what is left, and any drop carries a notice naming the setting. Two exceptions are stated rather than hidden: an **image block is atomic** (trimming base64 corrupts a PNG, so the cap governs the JSON that cites it), and an **answer pack shrinks by re-asking at a lower budget**, never by deleting rows from the pack it already built — below a few hundred tokens no pack fits, and the response says `over_cap` instead of shipping a mutilated answer. The `mcp` SDK is imported lazily via the package `__getattr__`, so a core install works and `dsa serve --mcp` without the extra prints an install hint. | `build_server`, `serve_stdio`, `SCHEMAS`, `validate_response`, `response_tokens`, `CAP_SETTING`, `PART_INDEX_URI`, `PROJECT_INDEX_URI` |
| `protocol.py` | **The corpus agent protocol — one rule text, three destinations** (Phase 5, ticket 08). `RULES`, `CONFIDENCE_HEADER`/`CONFIDENCE_ROWS` and `FALLBACK_RULE` are the canonical strings; `build_part_agent_markdown` (written by `publish/writer.py`), `build_project_agent_markdown` (written by `projects/index.py`) and `build_skill_markdown` (the checked-in `.claude/skills/datasheet-corpus/SKILL.md`, regenerated by `scripts/write_skill.py`) render *those exact strings* and add only their own worked examples — the CLI path and the MCP path, scoped to that part or project. `AGENT.md` is bounded like `INDEX.md` is (`AGENT_DOC_TOKEN_BUDGET` = 1700; measured 1,420 for a part and 1,496 for a three-part project, recorded per part in `CorpusStats.agent_doc_tokens`) and carries `PROTOCOL_MARKER`, its embedded version, so `agent_doc_current()` can tell the batch skip gate to republish a corpus written before the protocol existed. | `RULES`, `CONFIDENCE_HEADER`, `CONFIDENCE_ROWS`, `FALLBACK_RULE`, `AGENT_FILENAME`, `AGENT_DOC_TOKEN_BUDGET`, `PROTOCOL_VERSION`, `PROTOCOL_MARKER`, `SKILL_NAME`, `SKILL_RELPATH`, `rules_block`, `confidence_block`, `build_part_agent_markdown`, `build_project_agent_markdown`, `build_skill_markdown`, `write_agent_doc`, `agent_doc_current` |
| `cli.py` | argparse CLI, **formatting only** (`dsa pins` and `dsa regs` join `query`/`search`/`ask`/`plots` on the same `--part`/`--project` scope; `dsa status` prints the manifest's `derived_warnings`, which is where a pin-count mismatch is recorded) — it holds no retrieval logic (see the seam under Conventions). `_scope()` turns `--part` / `--project` (mutually exclusive, one required) into a `Retriever` or a `ProjectRetriever` and nothing else; project-scoped output labels each hit `[PART]` via the renderers' `show_part`. Reconfigures stdout/stderr to UTF-8 (Windows cp1252). | `main` |

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
    ├── pins.json          # one record per pin (absent when the datasheet prints no pin table)
    ├── registers.json     # one record per register (absent unless a register summary was read)
    ├── plots.json         # searchable plot catalog + file map
    └── search_index.json  # BM25 inverted index over sections/*.md (schema_version)

projects/<name>/
├── project.json           # Project: explicit parts[] (+ role), interfaces, notes, timestamps
├── PROJECT_INDEX.md       # always-loadable design index (hard budget, default 4000 tok)
└── AGENT.md               # the same retrieval protocol, scoped to the design
```

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
   `afe7950.pdf` / `afe7953.pdf` (skip-guarded) and the six committed gate
   PDFs (`tests/fixtures/pdf/` — the four phase-4 ones plus `lmx1204.pdf`
   and `LMX1204_registermap.pdf`, the phase-6 ticket-05 register gate; all
   **ungated**: a missing fixture is a hard test failure; `pdf_layout` is offline by construction; the
   repo-root copies stay the documented `dsa build` working files).
   Synthetic PDFs are built in-test via fitz.
5. **Golden Q&A is the objective function.** Per-part benchmarks at
   `tests/fixtures/golden_qa_<PART>.yaml` (the AFE7950 set — 21 questions —
   is the historical benchmark; no public one exists). `dsa verify`
   discovers a part's benchmark by name and hard-fails when it is missing
   or empty — every corpus is provably verified or provably not. Extend
    the sets whenever new answer paths ship; `dsa verify` must stay at 100%
    for supported paths (gate parts: AD9081 6 Q, LM741 17 Q, QPA1003P 16 Q,
    HMC520A 15 Q, and — phase 6, ticket 05 — LMX1204 15 Q, whose set is
    written against its **register-map companion** and therefore verifies
    with `--pdf tests/fixtures/pdf/LMX1204_registermap.pdf`). Phase 5, ticket 09 added the two paths the phase itself
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
8. **Deterministic derived artifacts** (ADR 0005). A derived artifact — one
   that is not verbatim-extracted text: a design card, a comparison row, a
   normalized number — may contain only **(a)** values copied verbatim from a
   spec, table or pin record, **(b)** values computed from those by a
   documented pure function, or **(c)** structural labels drawn from a
   checked-in lexicon. Every field carries `source` (record id + page) and
   `derivation` (the named rule that produced it); `models.DerivedValue` is
   that envelope and `provenance.py` mints and resolves the ids. **No model
   call may appear anywhere in the derivation path.** A field that cannot be
   filled stays null and says so — never interpolated, never a plausible
   default, never quietly omitted in a way that makes the artifact look
   complete. Verbatim stays authoritative: the numeric layer is additive, and
   where the two disagree the printed string is correct by definition. Any
   consumer that sorts, compares or computes margins must report its unparsed
   population explicitly rather than dropping those rows from the decision.

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
- **No retrieval logic in a front end.** `cli.py` and `mcp_server/server.py`
  may only format what `retrieve/` returns: no corpus walk, no
  `specs.json` / `plots.json` parsing, no hand-built `p.N` or `§N` string.
  Citations come from `Citation`, so the CLI and the MCP server can never drift
  apart in what they cite. `tests/unit/test_retrieve.py::TestCliIsFormatOnly`
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
- **The numeric layer is additive and allowed to fail.** `structure/quantities.py`
  parses a printed value into an SI number; it never rewrites one. No verbatim
  cell is mutated by it (asserted per field, on every record of six real
  corpora), and where the printed string and the parsed number disagree the
  printed string is correct by definition. `None` / `parse_confidence: none` is
  a **first-class outcome**, not a gap to fill: `See Figure 7` has no number,
  and the grammar is anchored so that `Note 2` does not become one either. Two
  rules follow and are load-bearing. A unit the lexicon cannot scale makes the
  whole cell unparsed rather than an unscaled number — a dropped factor of 1000
  is precisely the confident-and-wrong answer invariant 8 exists to prevent, so
  widening coverage means **adding a unit to `units.CANONICAL_UNITS` and a
  scale to `SI_UNITS`** (a test fails if one gains an entry without the other),
  never loosening the grammar. And any consumer that sorts, compares or
  computes a margin must run `parse_population` and report what it could not
  read; dropping those rows from a decision is a defect, not a tidy-up.
  Measured parse rate, six built corpora: AFE7950 95%, AFE7953 94%, QPA1003P
  83%, LM741 68%, AD9081 33%, HMC520A 27%, LMX1204 2% (`Reports/PHASE_6_REPORT.md`;
  reproduce with `scripts/measure_parse_rate.py`). The layout-floor spread is
  an *extraction* finding, not a grammar one — measured, almost all of those
  unparsed rows print no value cell at all, because a rescued grid never put
  the numbers in a value role. Improve it there, not here.
- **A device table is claimed by a lexicon and refused whole.**
  `structure/device_tables.py` reads pin tables and register summaries through
  one pipeline, and every word it matches on lives in
  `registry/device_tables.yaml` — adding a vendor's `Ball No.` or `Reg Addr` is
  a data change, exactly as adding an alias is. Three rules there are
  load-bearing. A table that fails validation is **rejected entirely, with a
  reason**, never emitted half-parsed: a partial pin table is the
  confident-but-incomplete artifact invariant 8 exists to prevent, because a
  designer who greps for a pin, gets no hit and concludes it does not exist has
  been misled. The reasons join `ExtractionStats.rejection_reasons` so device
  tables are as measurable as parametric ones, while the detected/accepted/
  rejected counts stay untouched — those measure *reconstruction*. And a table
  no route identified is **not** a rejection: a parametric spec table is simply
  not a device table, and recording it would bury the real findings. The
  positional fallback is deliberately narrow (headers matched *nothing*), and
  the count cross-check **warns** rather than rejects, which is ADR 0005's
  decided outcome — a count parsed from prose may not suppress a good table.
- **A pin table is published whole, or not at all.** `pins.json` exists only
  for a document whose pin table passed the device-table validation; a rejected
  one publishes **no file** and leaves its reason in
  `ExtractionStats.rejection_reasons`, and a datasheet that prints no pin table
  publishes no file and no reason (an absence in the document is not a finding
  about the extraction). A republish that yields no pins **deletes** any
  `pins.json` an earlier build left behind — a corpus must never serve a
  superseded pin table, and a stale file would also keep `pins_current` false
  and rebuild the part forever. Never "fix" a pin-less part by relaxing
  validation: a designer who greps for a pin, gets no hit and concludes it does
  not exist has been misled, which is the failure invariant 8 exists to
  prevent. Three more rules are load-bearing. **`type` is the only derived field on a pin**
  — a label from `registry/pin_types.yaml`, name tier before description tier,
  longest phrase first — so it always publishes `type_evidence`, and a tie or a
  miss is `unknown` with no evidence rather than a plausible category; widening
  coverage means a **longer, more specific phrase in the YAML** (`clkvdd` beats
  `clk`), never a looser match. The **package cross-check warns and is
  recorded** in `CorpusManifest.derived_warnings` (ADR 0005's decided outcome):
  it may not suppress a table, it runs even when nothing was published, and it
  reads a count only from a hyphen-joined package descriptor (`324-ball BGA`)
  on which every descriptor in the document agrees — a table of contents
  printing "21 Pin Configuration…" is not a package descriptor. And a pin
  lookup **never reads absence into a corpus with no pin table**: `pin_gap()`
  is `search_unavailable()`'s twin, and `dsa pins` exits 2 there. Measured, six
  built parts: AD9081 321 pins (324 stated — three lost to a range broken
  across two printed lines), HMC520A rejected whole, and AFE7950 / AFE7953 /
  LM741 / QPA1003P publish none (`Reports/PHASE_6_REPORT.md`).
- **A register map is published whole, or not at all — and it is read from the
  layout floor.** `DocType.REGISTER_MAP` routed to the degraded `pdf_text`
  backend until phase 6, ticket 05; that backend carries no trusted tables, so
  a register summary was unanswerable *by construction*. It now routes to
  `pdf_layout` for every vendor (`VendorProfile.register_map_backend`), which
  is why `PIPELINE_VERSION` moved to **0.5.0**: the extraction cache is keyed
  on `(content_hash, backend)` and would otherwise serve the paragraph-only
  reading forever. Errata and app notes are unchanged — their value is prose,
  and nothing downstream trusts a table from them. Four rules on the artifact
  itself are load-bearing. A summary table that fails validation is **rejected
  whole with a recorded reason** and publishes no `registers.json` (a republish
  that yields none deletes any earlier file), because a firmware engineer who
  greps for `0x1A04`, gets no hit and concludes the register does not exist has
  been misled in the most expensive way this corpus can manage. An **address
  carries both forms** and the parsed one may honestly fail: hex is recognised
  only by the marker the document printed, so a caller's bare `6660` and a
  record's `0x1A04` are the same number, and widening that would mean guessing
  a base out of the characters in a cell. A **reset is read only where the
  document prints one** — the summary's own column, else the register's printed
  declaration heading joined on the parsed offset — and the coverage gap is
  *reported* (`RegisterSet.n_reset_stated`, a manifest warning), which is
  invariant 8's honesty clause for this artifact. And **access is verbatim or
  absent**: TI's programmer's guides state access per bit field, not per
  register, so LMX1204 publishes `access: ""` rather than a plausible `R/W`;
  composing a register's access out of its fields' is ticket 06's shape.
  Measured, LMX1204's two documents: 35 registers each, all `high`, 29 of 35
  resets citing an exact printed page and 6 honestly citing none
  (`Reports/PHASE_6_REPORT.md`).
- **Furniture is page decoration, and page decoration lives in the margins.**
  Recurrence alone does not identify it. In a uniformly laid-out document the
  body's own y-slots recur on every page and its cells repeat verbatim, so a
  text-recurrence test eats the table it was meant to frame: measured on
  `LMX1204_registermap.pdf`, 252 mid-page lines were stripped as furniture,
  among them the header row of every register table and the *first data row of
  the register summary* — which ended that table's region one line under its
  own caption and threw the whole table away. `_margin_bands` therefore reads
  the margins off the **document**: a band is body when at least the recurrence
  threshold of pages print something non-decoration there, and only bands above
  the topmost such band or below the bottommost may contribute furniture. It is
  deliberately not per page (AD9081's last page prints a one-off copyright block
  *below* its page-number line, and a per-page rule would read that block as the
  body and hand the page number back as content) and deliberately not a fixed
  margin fraction (LM741's package-materials appendix prints its `www.ti.com`
  rule 12 pt lower than the datasheet's). The outermost body band is *inside*
  the margin for that last reason; only decoration lines are ever stripped, so
  including it costs nothing.
- **A band edge is only meaningful to a fraction of a character width.**
  `_header_bands` clusters column lefts from the header row **alone**, so a data
  cell the PDF lays out flush with its header can still start a float hair to
  the left of it and fall into the previous column — measured, LMX1204's `R0`
  starts 1.5e-5 pt left of `Acronym`, and every acronym in its register summary
  read as part of the address cell while the features column read as the
  acronym. `_BAND_EPSILON` (0.001 pt) is the tolerance that absorbs that; it is
  three orders of magnitude below any real geometry (columns sit tens of points
  apart, `_advice_share` compares edges at 0.75 pt) and it must stay there. A
  larger nudge is not a bigger safety margin, it is a different column split:
  0.05 pt was tried and moved four AD9081 spec values.
- **A cell is not a section heading because it says the same words.** A
  caption-anchored table region ends at a printed section heading, and a
  title-key match alone is not one: LMX1204's register summary prints `SYSREF`
  in the features column of `0x10 R16 … Go`, and the datasheet has a §6.3.6
  called `SYSREF`, so the bare test ended that table twenty rows early and
  published half a register map. `_is_section_break` adds the one distinction
  that needs no threshold — a heading occupies its own baseline, a cell shares
  one with the rest of its row.
- **A confidence grade is metadata, never a filter.** The rule lives in
  `structure/confidence.py` (its docstring is the normative version) and runs
  once, at structure time. Nothing downstream may re-derive it, and nothing may
  drop, hide or reorder a record because of it — a `low` record is still
  returned, still verbatim, still cited; `low` means "open the printed page",
  not "wrong". Measured mix (`high`/`medium`/`low`) on the built corpora:

  | Part | Backend | Specs | Plots | Measured by |
  |---|---|---|---|---|
  | AFE7950 | ti_html | 613/3/3 | 0/514/0 | fresh build (`test_afe7950_build.py`) |
  | AFE7953 | ti_html | 531/2/3 | 0/492/0 | regrade of the committed corpus (below) |
  | AD9081 | pdf_layout | 158/210/181 | 2/98/0 | phase-4 gate build |
  | LM741 | pdf_layout | 0/0/71 | 3/0/0 | phase-4 gate build |
  | QPA1003P | pdf_layout | 0/0/41 | 4/0/0 | phase-4 gate build |
  | HMC520A | pdf_layout | 0/4/81 | 34/73/0 | phase-4 gate build |
  | LMX1204 | pdf_layout | 0/89/764 | 16/38/0 | phase-6 ticket-05 gate build |

  Two facts dominate: TI's HTML tables are never reconstructed, so they grade
  almost entirely `high`, while the captionless-era layout-floor parts grade
  almost entirely `low` because their grids only ever pass the reconstruction
  gate on a rescue split. AD9081, whose ADI tables are captioned and
  header-declared, is the mixed case. Do not "improve" the mix by loosening the
  rule; improve it by making the layout floor reconstruct those grids from their
  own headers — which is exactly what phase 6, ticket 05 did, and why HMC520A
  and AD9081 moved: fixing the furniture detector's margin rule and the
  header-band float tolerance (see the two bullets below) freed grids that had
  been dropped or misread. HMC520A went from 30 spec records — most of them
  valueless — to 85 with min/typ/max, and its four non-`low` rows are its p.31
  ordering guide, whose header row really is declared. Every row on those three
  parts that carries a *printed value* is still `low`, which is the claim the
  gate asserts. Register records grade separately and are all `high` on
  LMX1204's two documents (`stats.register_confidence`). **AFE7953 has no offline build path** — it is a TI part, so it
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
  (`publish.search_index_current`), `specs.json` (`publish.specs_current`),
  `plots.json` (`publish.plots_current`), `pins.json` (`publish.pins_current`) or
  `registers.json` (`publish.registers_current`), or whose `AGENT.md` is missing or of
  an older protocol version (`protocol.agent_doc_current`), so a corpus
  published before a
  publish-time schema existed republishes once instead of skipping forever
  and answering nothing. Bump `SEARCH_SCHEMA_VERSION` /
  `SPECS_SCHEMA_VERSION` / `PLOTS_SCHEMA_VERSION` in `config.py` whenever the
  corresponding format changes; that is the invalidation, not
  `PIPELINE_VERSION`. `PINS_` is at **"1"** (phase 6, ticket 04's new `pins.json`), `REGISTERS_` at **"1"** (ticket 05's new `registers.json`), `SPECS_` is at **"4"** (phase 5, ticket 04 added
  `confidence`; phase 6, ticket 01 added the stable record `id`, ticket 02 the
  numeric layer's `value_si` / `value_low_si` / `value_high_si` / `unit_si` /
  `value_kind` / `parse_confidence`) and `PLOTS_`
  at **"2"** — the extractor-version gate cannot cover this, because
  a `ti_html` part's `output_version` never moves when the layout engine's
  does. `CARD_VERSION` joins them for *derived* artifacts and is the only gate
  that can catch a changed derivation rule: a rule is code, not input, so
  nothing about the source bytes — and therefore nothing the content hash or
  the extractor version sees — moves when it changes. It is stamped into
  `manifest.json` at publish and is at **"3"** (phase 6, ticket 04 — a wholly
  new derived artifact, `pins.json`, with a new derived field and a new derived
  warning; nothing else moves for it, so a part built at ticket 03 would skip
  forever and never gain the pin table its datasheet prints; ticket 05 moved it
  again for `registers.json`, whose derived `address.value` and `reset` are
  invisible to every other gate). A *missing*
  `specs.json`/`plots.json`/`pins.json`/`registers.json` reads as current, unlike a
  missing search index: a `pdf_text` document legitimately publishes neither,
  and demanding one would put that part in a rebuild loop — which is why the
  publisher *removes* a superseded `pins.json` instead of leaving one behind.
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