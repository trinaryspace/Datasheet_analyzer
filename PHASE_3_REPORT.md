# Phase 3 Report — Plot Pixels + Vision Reads + Multi-Doc Parts

**Status: complete. Phase 3 closes the catalog→pixels gap and makes parts
multi-document; results below are the final measured numbers. Replicated on
AFE7953 (SBASAN1A): 492 figure files + 492 `plots.json` records, same code
path, zero changes.**

Phase 3 makes the 514 cataloged AFE7950 figures answerable by agents:
every figure has an image file in the corpus, a searchable `plots.json`
catalog, and a deterministic `dsa plots` lookup. Companion documents
(register maps, errata, app notes) can now be added to a part and built
with a single `INDEX.md` via the honest `pdf_text` backend.

## Reproduce (Git Bash on Windows; use `.venv/Scripts/dsa.exe` without activation)

```bash
uv venv --python 3.10 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
source .venv/Scripts/activate
dsa build afe7950.pdf --part AFE7950                  # + plots.json + figures/
dsa verify --part AFE7950 --pdf afe7950.pdf --specs   # 19 golden incl. 3 plot queries
dsa plots --part AFE7950 --q "Output Fullscale"       # plot lookup
python -m pytest tests/ -q                            # 214 tests, ~8 s, fully offline
python -m ruff check src tests
```

## Task 0 — Hi-res image probe

TI AFE7950 image URLs are of the form
`/ods/images/SBASA41E/GUID-...-low.gif`. We probed four representative
GUIDs and tried the variants `-low.gif`, `-high.gif`, `.gif`, bare GUID,
and `.png`.

**Findings:** only `-low.gif` returned HTTP 200.

| GUID | -low.gif | -high.gif | .gif | bare | .png | kept |
|---|---|---|---|---|---|---|
| GUID-CE747DA5-... | 200 (407×298, 9869 B) | 404 | 404 | 404 | 404 | `-low.gif` |
| GUID-260BEA07-... | 200 (397×298, 6603 B) | 404 | 404 | 404 | 404 | `-low.gif` |
| GUID-09A019EB-... | 200 (404×298, 6996 B) | 404 | 404 | 404 | 404 | `-low.gif` |
| GUID-6BA67C9D-... | 200 (400×298, 8875 B) | 404 | 404 | 404 | 404 | `-low.gif` |

**Decision rule implemented:** try the original URL plus the variant
suffixes `[-high.gif, .gif, .png, ""]` and keep the largest successful
response. For this document family the original `-low.gif` is the only
available variant, but the rule is general.

## Deliverables

### Models & config

- `PlotRecord` / `PlotSet` models added to `models.py`.
- `PLOTS_SCHEMA_VERSION = "1"` and `plot_image_dpi = 150` added to
  `config.py`.
- `CorpusStats.n_plot_files` added.
- `GoldenQuestion.plot_query` added.

### Binary fetchers

- `CachingBinaryFetcher` caches bytes under `.cache/http-bin/<sha1(url)>.<ext>`.
- `ReplayBinaryFetcher` serves recorded bytes in tests; supports a
  `default` stand-in for unrecorded URLs.

### Plot transform & pixels

- `structure/plots.py`: stable IDs (`4.12.1-f001`), section + caption tags,
  figure-number parsing.
- `publish/plots.py`: `fetch_plot_images` (network/replay) +
  `render_plot_pages_fallback` (PDF full-page render).
- `query.py`: `find_plots` / `format_plot_answer`.
- `dsa plots --part AFE7950 --q "..." --section ... --tag ...` wired in.

### Multi-doc / pdf_text backend

- `extract/pdf_text.py`: honest PDF-text backend; paragraphs only,
  contextual page-number stripping, `tables=[]`, `figures=[]`,
  `extractor="pdf_text"`.
- `dsa add-doc <pdf> --part ... --type register_map|errata|app_note [--nda]`.
- Pipeline loops over `sources.json`; datasheet -> `ti_html`, companions ->
  `pdf_text`.
- `build_specset` skips `pdf_text` documents (no `specs.json`).
- `INDEX.md` now renders one section-map block per document.

### Golden Q&A

- 3 plot questions added to `golden_qa.yaml`:
  - `p01-tx-fullscale-800m`
  - `p02-tx-gain-error-800m`
  - `p03-rx-fullscale-800m`
- `dsa verify` prints a third table: **Plot query verification**.
- A regression test (`tests/unit/test_cli_verify.py`) pins the summary
  counts: spec/plot rows must count only passing questions (a generator
  bug once claimed N/N on failing rows).

## Measured numbers (real AFE7950, hermetic fixtures)

Build output:

```text
n_documents: 1
n_sections: 39
n_tables: 15
n_figures: 514
n_specs: 619
n_plot_files: 514
total_tokens: 46073
index_tokens: 2469
plots.json records: 514
plot question tokens: 4053
```

Second reference part (AFE7953, same build path, no code changes):

```text
n_sections: 39
n_tables: 14
n_figures: 492
n_specs: 536
n_plot_files: 492
total_tokens: 39033
index_tokens: 2522
plots.json records: 492
```

Golden plot file sizes (real recorded GIFs):

- `4.12.1-f001` (TX Output Fullscale): 9869 B
- `4.12.1-f003` (TX Calibrated Differential Gain Error): 11209 B
- `4.12.8-f017` (RX Input Fullscale): 7312 B

## Acceptance criteria

- [x] ≥514 figure files on disk, all referenced from `plots.json`
- [x] `dsa plots --q "Output Fullscale"` returns §4.12.1 records with existing files
- [x] 3/3 golden plot queries pass in `dsa verify` (Table 3)
- [x] Plot question token cost measured: 4053 tokens (INDEX + plots slice + one image ~1.5k)
- [x] 2-document part builds with unified `INDEX.md`; register map emits no `specs.json`
- [x] `pdf_text` strips page furniture using page context; data lines survive
- [x] `pytest` (214 tests) + `ruff` green incl. Phase 1 + Phase 2 integration

## Out of scope (kept out)

- Vector curve digitization.
- Bbox cropping of PDF plot renders.
- `specs.json` from `pdf_text` documents.
- Fleet manifest / MCP / hybrid search.