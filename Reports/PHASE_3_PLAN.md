# Phase 3 Plan — Plot Pixels + Vision Reads + Multi-Doc Parts

> Execution contract for the implementing agent. Read `AGENTS.md` first.
> Independent of Phase 2 (either order works); must keep Phase 1 integration
> green. Deterministic everywhere; the only optional LLM use is a smoke test
> proving the vision-read workflow, and it must skip cleanly without a key.

## Objective

Phase 1 cataloged 514 figures (caption + conditions + image URL) but no
pixels. Phase 3 makes plots answerable:

1. **Pixels:** every cataloged figure gets an image file in the corpus
   (`figures/`), downloaded from TI or rendered from the PDF.
2. **Catalog:** `plots.json` — a machine-readable, searchable plot index
   (the plot twin of Phase 2's `specs.json`).
3. **Lookup:** `dsa plots --q ...` finds the right plot in ≤2k tokens; an
   agent then vision-reads ONE image (~1.5–3k tokens) instead of guessing.
4. **Multi-doc:** a part builds from a *folder* of documents (datasheet +
   register map + errata + app notes), via a new honest `pdf_text` backend
   for documents TI's HTML viewer doesn't cover.

Success on the real AFE7950: **≥514 figure files present and referenced,
3 golden plot lookups verified, a 2-document synthetic part builds with a
single INDEX.md, and plot-question token cost ≤ ~4k measured.**

## Deliverables (file-by-file)

### 0. Probe task (do FIRST, 15 minutes, document the answer in the report)

FigureRef.image_url looks like `/ods/images/SBASA41E/GUID-…-low.gif`.
With curl/requests probe: (a) fetch one `-low.gif`, record dimensions;
(b) try `-high.gif` and the bare GUID (no suffix); (c) pick the rule:
prefer the largest variant that returns 200; if all fail → PDF-render
fallback. Record findings in `PHASE_3_REPORT.md`. All production fetches go
through the binary fetcher below (cached); tests use replay only.

### 1. `src/datasheet_analyzer/models.py` — additions

```python
class PlotRecord(BaseModel):
    id: str                  # "4.12.1-f007" — section number + seq in section
    section: str             # "4.12.1"
    caption: str             # FigureRef.caption ("Figure 4-1 TX Output Fullscale vs …")
    figure_number: str       # "4-1" parsed from caption, "" when absent
    conditions: str          # FigureRef.conditions (textnote)
    page_start: int | None   # owning section's range (figures are NOT page-pinned —
    page_end: int | None     #   honest range, never a guessed single page)
    image_url: str           # source URL as cataloged
    file: str                # corpus-relative path, "" until pixels exist
    tags: list[str]          # derived — see tag rules below

class PlotSet(BaseModel):
    schema_version: str      # PLOTS_SCHEMA_VERSION "1"
    part_number: str
    doc_hash: str
    plots: list[PlotRecord]
```

`config.py`: add `PLOTS_SCHEMA_VERSION = "1"`, `plot_image_dpi: int = 150`.
`CorpusStats`: add `n_plot_files: int = 0`.

### 2. `src/datasheet_analyzer/extract/http.py` — binary fetching (append)

```python
class CachingBinaryFetcher:
    """Bytes variant of CachingFetcher: .cache/http-bin/<sha1(url)>.<ext>,
    ext taken from the URL path (.gif/.png/.jpg, default .bin)."""
    def __init__(self, cache_dir: Path, *, timeout_s=60, delay_s=0.25,
                 user_agent="datasheet-analyzer/0.1"): ...
    def __call__(self, url: str) -> bytes: ...

class ReplayBinaryFetcher:
    """Hermetic tests: serves recorded bytes; miss = AssertionError.
    May be constructed with a `default: bytes` stand-in returned for any
    unrecorded URL (used so 511 of 514 real plot files exist in tests
    without 20 MB of fixtures — the 3 golden plots use real recordings)."""
```

### 3. `src/datasheet_analyzer/structure/plots.py` — the transform (NEW)

```python
MEASURE_KEYWORDS: list[str]   # caption tag vocabulary:
  # ["acpr","nsd","output power","fullscale","gain error","phase error",
  #  "phase noise","imd","hd2","hd3","harmonic","return loss","s11","nf",
  #  "noise figure","image rejection","spurious","sfdr","snr","eye diagram",
  #  "jitter","settling","bandwidth","flatness","dsa"]

def figure_number(caption: str) -> str
    """"Figure 4-1 TX Output …" -> "4-1"; no match -> ""."""

def section_tags(section: SectionNode) -> list[str]
    """From the section title: path tag ("tx"|"rx"|"fb"|"pll-clock") and
    frequency tag ("800mhz"…"9.6ghz") when present in the title."""

def caption_tags(caption: str) -> list[str]
    """MEASURE_KEYWORDS found (lowercased substring) in the caption."""

def build_plotset(raw: RawDocument, part_number: str) -> PlotSet
    """Every FigureRef in every section -> PlotRecord with stable ids
    (section order, then figure order), tags = section_tags + caption_tags,
    file="" (pixels are a separate stage)."""
```

### 4. `src/datasheet_analyzer/publish/plots.py` — pixels (NEW)

```python
def fetch_plot_images(plotset: PlotSet, *, fetcher) -> int
    """Fill PlotRecord.file by downloading image_url (apply the hi-res rule
    from task 0) into docs/<doc>/figures/<section-stem>/<id>.<ext>.
    Returns count of files written. Never raises on a single failure:
    log + leave file="" (honest degradation)."""

def render_plot_pages_fallback(plotset: PlotSet, pdf_path: Path, *,
                               dpi: int) -> int
    """For plots with file=="": render the figure's section page(s) to PNG
    via fitz (page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72))) —
    full-page render, no bbox cropping (vector plots make bboxes unreliable).
    Used when a download 404s and for --offline builds."""
```

### 5. `src/datasheet_analyzer/query.py` — extend (or `plots_query.py`)

```python
def find_plots(part_dir: Path, *, q: str = "", section: str = "",
               tags: list[str] | None = None) -> list[PlotRecord]
    """Load every docs/<doc>/plots.json; match: q = case-insensitive
    substring over caption+conditions; tags = all must be present;
    section = exact number. ANDed."""

def format_plot_answer(records: list[PlotRecord], limit: int = 8) -> str
    """'<caption> — §4.12.1 (p.29-37) — <conditions> — file: docs/…/f007.gif'"""
```

### 6. `src/datasheet_analyzer/extract/pdf_text.py` — multi-doc backend (NEW)

For register maps / errata / app notes that TI's HTML viewer doesn't serve.
**Explicitly degraded and honest:** paragraphs only, no trusted tables.

```python
class PdfTextBackend:
    name = "pdf_text"
    def extract(self, source, *, pdf_toc=None) -> RawDocument:
        """sections from the printed TOC; paragraphs = page_texts slice of
        each section's page range, with CONTEXTUAL boilerplate stripping:
        a digits-only line is stripped ONLY when it equals that page's own
        printed number (the rule Phase 1 deferred — page context makes it
        safe); tables=[] (pdf_text tables are NOT trusted in v1 and get no
        specs.json); figures=[]; extractor='pdf_text'.
        No TOC -> one section per page (level 1, page = itself)."""
```

Register it in `extract/__init__.py`. If Phase 2 has already landed,
`build_specset` must skip documents whose `extractor == "pdf_text"` (add a
one-line guard with a comment); if Phase 3 lands first, leave a TODO at that
call site instead.

### 7. `pipeline.py` + `cli.py` — multi-doc wire-in

- `dsa add-doc <pdf> --part AFE7950 --type register_map|errata|app_note [--nda]`
  → `register_source` with explicit type/nda, append to `sources.json`
  (dedupe by content_hash: re-adding is a no-op with a log line).
- `dsa build` loops over `load_inventory(part_dir)` (or the single CLI pdf
  when building fresh): main datasheet → `ti_html`; everything else →
  `pdf_text`. All RawDocuments flow through structure/publish as today.
- `enrich/index.py`: render one `## Section map — <doc_type> <revision>`
  block per document (the existing function already accepts a docs list;
  extend `build_index_markdown` to group sections by doc and keep the staged
  budget degradation over the TOTAL). Budget accounting unchanged.
- `dsa plots --part AFE7950 [--q "output fullscale"] [--section 4.12.1]
  [--tag acpr]` → `format_plot_answer`; exit 0 if hits else 1.
- INDEX.md "How to use" block gains one line (replace the Phase-3 placeholder):
  `- Plot lookup: dsa plots / docs/<doc>/plots.json -> open the image file (vision).`

### 8. `tests/fixtures/golden_qa.yaml` — plot entries (append, don't touch existing)

3 new questions with `plot_query` blocks (exact captions/conditions to be
read from the built `plots.json` during implementation — candidates seen in
the real corpus: "TX Output Fullscale vs Output Frequency" §4.12.1 with
"DSA = 0" conditions; "TX Calibrated Differential Gain Error vs DSA Setting"
§4.12.1; one RX plot from §4.12.8):

```yaml
  - id: p01-tx-fullscale-800m
    question: Which figure shows TX output fullscale vs frequency at 800 MHz?
    kind: plot
    plot_query: {caption_contains: "Output Fullscale vs Output Frequency", section: "4.12.1", conditions_contain: "DSA = 0"}
```

`GoldenQuestion`: add `plot_query: dict[str, str] | None = None`.
`dsa verify` gains plot checks: each `plot_query` must match ≥1 PlotRecord
whose `file` exists on disk and is >1 KB. Table 3 in the verify report.

## Test plan (all hermetic)

### `tests/unit/test_plots.py`
- `test_figure_number_parse` — "Figure 4-1 …" → "4-1"; no caption number → "".
- `test_section_and_caption_tags` — "TX Typical Characteristics at 1.8 GHz"
  → {tx, 1.8ghz}; "…ACPR vs Output Power…" → contains acpr + output power.
- `test_build_plotset_real_counts` — recorded RawDocument → 514 records,
  ids stable across re-runs, every figure referenced exactly once.
- `test_records_carry_section_page_range_not_guessed_pages`.

### `tests/unit/test_http_binary.py`
- `CachingBinaryFetcher` roundtrip (tmp dir; second call no network via
  requests-mock style monkeypatched requests); extension preserved.
- `ReplayBinaryFetcher` miss raises; `default` stand-in mode returns bytes.

### `tests/unit/test_pdf_text.py`
- synthetic fitz PDF (TOC + footers incl. the page's own number + a digits-only
  DATA line) → sections with pages; page-number footer stripped, data line kept.
- no-TOC PDF → one section per page.
- `extractor == "pdf_text"`; tables empty.

### `tests/unit/test_plots_query.py`
- substring/tag/section matching, AND semantics, format includes file + pages.

### `tests/integration/test_phase3_plots.py` (marker `integration`)
- Real build with `ReplayBinaryFetcher(recorded_dir, default=TINY_GIF)`:
  ≥514 `figures/` files; 3 golden plots are the REAL recorded GIFs (>5 KB);
  `plots.json` validates; every PlotRecord.file exists; 3/3 golden plot
  queries pass; report's token estimate for a plot question
  (INDEX + plots slice + one image's token cost at ~1.5k/image) ≤ ~4k.
- Vision smoke test, marker `llm`, `pytest.mark.skipif(not key)`: send one
  golden PNG/GIF to Claude, assert expected substring (e.g. "dBm" in answer).

### `tests/integration/test_phase3_multidoc.py` (marker `integration`)
- Synthetic part: ti_html-replayed datasheet (Phase 1 synthetic fixtures)
  + fitz-built `register_map.pdf` → one INDEX.md lists both docs, manifest
  `n_documents == 2`, both section trees on disk under separate
  `docs/<type>-<hash>/` dirs, register-map sections carry `extractor`
  provenance and emit NO specs.json.
- `dsa add-doc` idempotence (same bytes twice → single inventory entry).

### Fixtures to record during implementation
- 3 golden plot GIFs → `tests/fixtures/recorded_http_bin/` (+ expected sha
  or size in the test so the right file is asserted).
- Everything else uses existing fixtures.

## Execution order (9 tasks)

0. hi-res image probe (record decision) 
1. models + PLOTS_SCHEMA_VERSION (+GoldenQuestion.plot_query)
2. `extract/http.py` binary fetchers + tests
3. `structure/plots.py` + tests
4. `publish/plots.py` + query extension + `dsa plots` CLI
5. golden plot yaml + verify plot table
6. `extract/pdf_text.py` + tests; register backend; specs guard
7. `dsa add-doc` + multi-doc pipeline loop + INDEX.md grouping
8. integration suites green (plots + multi-doc + Phase 1 regression)
9. `PHASE_3_REPORT.md` (probe findings, counts, token economics, multi-doc
   proof) + AGENTS.md module-table update

## Acceptance criteria (copy into the report)

- [ ] ≥514 figure files on disk, all referenced from `plots.json`
- [ ] `dsa plots --q "Output Fullscale"` → §4.12.1 record with existing file
- [ ] 3/3 golden plot queries pass in `dsa verify` (table 3)
- [ ] Plot question token cost measured (expect ≤ ~4k incl. one image)
- [ ] 2-document part builds with unified INDEX.md; register map emits no specs
- [ ] pdf_text strips page furniture using page context; data lines survive
- [ ] `pytest` + `ruff` green incl. Phase 1 + (if done) Phase 2 integration

## Explicitly out of scope

- Vector curve digitization (PyMuPDF path→CSV): a later phase; needs its own
  research spike (no OSS prior art).
- Bbox cropping of plots from PDF renders (full-page fallback is fine).
- specs.json from pdf_text documents.
- Fleet manifest / MCP / hybrid search (Phase 4).
