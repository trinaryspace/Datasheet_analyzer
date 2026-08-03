# Phase 3 Plan — Plot Pixels + Vision Reads + Multi-Doc Parts

**Status: completed — shipped. This contract is superseded by
`PHASE_3_REPORT.md` (probe findings, measured numbers, acceptance criteria).**

Phase 3 closed the catalog→pixels gap (514 AFE7950 / 492 AFE7953 figure
files on disk) and made parts multi-document.

## What shipped

- **Pixels:** every cataloged figure has an image file in `figures/`
  (TI `-low.gif` is the only live variant — probe table in the report);
  largest-success rule with `[-high.gif, .gif, .png, ""]` variants plus a
  PDF-render fallback at `DSA_PLOT_IMAGE_DPI` (default 150).
- **Catalog:** `plots.json` (`PLOTS_SCHEMA_VERSION = "1"`), stable IDs
  (`4.12.1-f001`), section + caption tags; `CorpusStats.n_plot_files`.
- **Lookup:** `dsa plots --part <PART> --q ... --section ... --tag ...`;
  plot-question token cost measured at ~4,053 (INDEX + plots slice + one image).
- **Multi-doc parts:** `dsa add-doc <pdf> --part ... --type register_map|errata|app_note [--nda]`
  + honest `pdf_text` backend (paragraphs only, contextual page-number
  stripping); one `INDEX.md` per part; no `specs.json` for `pdf_text` docs.
- Golden Q&A grew from 16 to 19 questions (3 plot queries); a regression
  test pins that `dsa verify` summary counts only passing rows.
- Explicitly out of scope: vector curve digitization, bbox cropping of PDF
  renders, specs from `pdf_text`, fleet manifest / MCP / hybrid search.

## Original contract (kept for the record)

Phase 1 cataloged 514 figures (caption + conditions + image URL) but no
pixels. Phase 3 made plots answerable: pixels in the corpus, a searchable
`plots.json`, a deterministic `dsa plots` lookup (~2k tokens) after which an
agent vision-reads ONE image (~1.5–3k tokens) instead of guessing, and a
part built from a **folder** of documents via the `pdf_text` backend for
documents TI's HTML viewer does not cover.