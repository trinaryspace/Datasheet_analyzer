---
title: Vendor-neutral layout core + multi-vendor gate
labels: [shipped]
---

**Status: superseded by `Reports/PHASE_4_REPORT.md`** (the measured
completion record, per the batch-build convention — a shipped spec closes
as superseded by its report, never by assertion). Tickets 01–07 shipped
on `feat/pdf-layout-paragraph-core`; the open items it defers to ticket 09
(layout materialization) and the heuristics ledger continue to live in
`KNOWN_SHORTCOMINGS.md` and `issues/09-layout-materialization.md`.

## Problem Statement

The pipeline delivers token-efficient, citation-verified corpora for TI
datasheets only. TI's fidelity comes from the HTML document viewer
(`ti_html`); everything else degrades to `pdf_text` — paragraphs only, no
tables, no specs, no plots. Datasheets from other vendors (Analog Devices,
Qorvo, older TI parts) therefore cannot get the same end-functionality:
atomic tables, specs.json, plots.json, citation-verified golden Q&A. The
format of these PDFs differs per vendor and per era (numbered vs unnumbered
outlines, books with or without outlines, different headers/footers, unit
glyphs, table-header wording), so the fix cannot be one more vendor special
case — it must be an engine that survives any vendor's PDF unchanged.

## Solution

A vendor-neutral, offline layout engine (`pdf_layout` backend) becomes the
guaranteed extraction floor for every vendor: TI keeps its unchanged
`ti_html` path; ADI, Qorvo, older TI, and any vendor N+1 get full corpora —
atomic tables, specs, plots, page citations — straight from the PDF, with
zero network and zero layout assumptions keyed to any vendor. Every table
hypothesis must reconstruct the page's own word stream or it is rejected
and honestly recorded. Vendor identity is a thin routing record: detected
with recorded evidence at acquire time, overrideable with `--vendor`,
surfaced in `dsa status`, and never used to alter extraction behavior.
The claim is proven by an acceptance gate: four genuinely different PDFs
must all build with 100% golden verification.

## User Stories

1. As a builder, I want to run `dsa build ad9081.pdf --part AD9081` and get
   a full ADI corpus — INDEX.md, atomic tables, specs.json, plots.json,
   page citations — with no flags, no network, and no TI-specific behavior,
   so ADI parts get the same end-functionality as TI parts.
2. As a builder, I want the same build to work for an older TI part
   (lm741), a Qorvo part (QPA1003P, no PDF outline), and a Hittite-era ADI
   part (HMC520A), so the engine's claim is vendor- and era-agnostic, not
   fitted to one layout family.
3. As a builder, I want the vendor detected automatically at acquire time
   and pinned to the part's inventory with the evidence that matched
   (e.g. brand text on page 1), so routing is explainable and never a
   silent guess.
4. As a builder, I want to override detection explicitly with
   `--vendor adi` (default `ti`), so a misdetected or exotic document can
   always be routed by hand.
5. As a builder, I want `dsa status` to show each part's vendor, evidence,
   and extraction quality, so the provenance of a corpus is auditable.
6. As a builder, I want a re-run whose detection contradicts the pinned
   vendor to log a loud warning instead of silently re-routing, so identity
   drift is impossible to miss.
7. As a builder of TI parts, I want nothing about my workflow to change —
   no flags, no new commands, verify still 100% — so the shipped reference
   parts stay bit-for-bit the same.
8. As a builder of an unknown-vendor PDF, I want it to still build with
   honest tables via the layout engine, so an unfamiliar datasheet degrades
   gracefully instead of failing or producing paragraphs only.
9. As a builder, I want every table cell in the corpus to be traceable to
   the PDF — the engine must reconstruct the page's word stream from the
   grid it proposes — so no extractor doubt ever enters the corpus.
10. As a builder, I want word clusters that merely look tabular (no
    `Table N.` caption) to become paragraphs, never hallucinated tables,
    so prose is never mistaken for data.
11. As a builder, I want tables with partial rulings (no vertical lines
    between Min/Typ/Max) to still split their columns correctly via word
    position clustering, so every parametric table lands intact.
12. As a builder, I want merged cells (rowspan/colspan) inferred from
    overlapping spans and materialized as fully-expanded grids, so the
    corpus's atomic-table guarantee holds for any vendor.
13. As a builder, I want rejected table hypotheses retried with coarser
    splits, and only the best reconstruction-scoring grid accepted, so
    recoverable tables are rescued instead of dropped.
14. As a builder, I want every rejection recorded with its reason and the
    per-document extraction stats in the manifest, so engine honesty is
    measurable, not asserted.
15. As a builder, I want sections with no printed numbers to stay honestly
    unnumbered, keyed by slugified title files
    (`general-description.md`), so no fabricated identifiers enter the
    corpus.
16. As a builder, I want page ranges and citations to come from outline
    (bookmark) positions when they exist, from a generic printed-TOC
    dot-leader parse when they don't, and from per-page fallback only when
    neither exists, so citations are right whatever the PDF's era.
17. As a builder, I want header/footer furniture identified by slot
    recurrence and universal page-machinery patterns — never by vendor
    strings — so an ADI header strip and an old-TI web-chrome header strip
    both vanish without the engine knowing any vendor's name.
18. As a builder, I want a PDF with no consistent furniture bands to keep
    all its text (no stripping), so the honesty default is preservation.
19. As a builder, I want table footnotes and their citation markers
    detected from font geometry (superscript size/raised baseline) and the
    trailing numbered lines attached to the table, so spec answers citing
    footnotes stay correct.
20. As a builder, I want figures (block diagrams, plots — all vector
    drawings, no embedded images) rendered as image files with their
    `Figure N.` captions and listed in plots.json, so the plot-lookup
    functionality works for every vendor.
21. As a builder, I want `dsa query --part AD9081 --symbol <sym>` to
    resolve ADI spec records (e.g. full-scale output current range) from
    specs.json, so deterministic spec lookup is vendor-neutral.
22. As a builder, I want unit canonicalization to handle both ohm glyphs
    (U+2126 and U+03A9 — both measured in AD9081) plus the existing
    convention of verbatim preservation in the corpus and canonicalization
    only in specs.json, so downstream comparisons never misfire on glyph
    variants.
23. As a builder, I want revision detection to understand "Rev. A"-style
    captions and "SBASA41E"-style document ids from a shared lexicon, so
    inventory metadata is right for every vendor without per-vendor code.
24. As a builder, I want doc-type hints to recognize ADI-style prefixes
    (UG-xxx user guides) alongside TI's (sbaa/slaa/swra), so companion
    documents classify correctly for any vendor.
25. As a builder, I want the INDEX.md brief to find "General Description"
    as well as "Description", so ADI parts get a proper brief and facts
    list.
26. As a builder running `dsa verify --part AD9081`, I want a per-part
    golden benchmark, and a hard failure when a part's benchmark file is
    missing, so every corpus is provably verified or provably not.
27. As a builder, I want the four gate parts to verify at 100% (text,
    spec-query, and plot-query checks) in an ordinary offline `pytest`
    run, so the multi-vendor claim is continuously proven, not
    demonstrated once.
28. As a builder of mixed-vendor batches, I want `dsa batch` on a directory
    of TI, ADI, and Qorvo PDFs to detect and route each job independently,
    so a batch needs no per-vendor configuration.
29. As a builder re-running batches after pipeline upgrades, I want the
    hash-gated skip to also gate on `pipeline_version` and vendor, so a
    version bump rebuilds instead of silently skipping into staleness.
30. As a builder running parallel jobs, I want extraction-cache writes to
    be atomic (write-temp + rename), so concurrent jobs with identical
    bytes can never corrupt the cache.
31. As a builder evaluating the engine, I want a full offline run of the
    four gate PDFs with no HTTP traffic at all, so the fidelity path never
    depends on network availability.
32. As a builder extending to vendor N+1 (e.g. Renesas), I want it to
    require only a profile entry in a shared brand lexicon plus backend
    preference — no engine changes — so adding a vendor is a data change,
    not a code change.

## Implementation Decisions

- **Thin VendorProfile registry** (route, not rules): each entry carries an
  identity detector (shared brand-mark lexicon + generic doc fingerprints),
  a backend preference chain (`ti → [ti_html, pdf_layout]`,
  `adi/qorvo/unknown → [pdf_layout]`), and pinned evidence. No layout rule
  hangs off the vendor string. Default vendor remains `ti`.
- **Evidence pinning at acquire**: detection runs on page-1 text +
  filename; the match (vendor, evidence text) is stored additively in
  sources.json; contradiction on later runs warns loudly; `--vendor` is an
  explicit override on `build`/`add-doc`. Manifest gains `vendor` +
  per-document `extraction_stats`.
- **`pdf_layout` backend** (from prototype probing on the real AD9081 PDF:
  stable value-column x positions, e.g. `−40`@408.8 / `+120`@496.6 /
  `°C`@543.3): furniture by slot recurrence + universal patterns; tables
  are caption-anchored hypotheses; rows from ruling bands + baseline
  clustering; columns from all-word x-clustering with rulings as hints;
  rowspan/colspan from overlapping spans; retry ladder with coarser
  splits; **reconstruction gate**: an accepted grid must re-produce the
  page's own word stream (every word in exactly one cell, interior
  leftovers penalized). No ML (torch is forbidden; determinism required by
  the content-hash cache).
- **Structure ladder**: PDF outline (bookmarks) first — titles keep printed
  numbers when present, stay `""` otherwise (never fabricated);
  generic printed-TOC dot-leader parser fallback (indentation = hierarchy);
  per-page sections last. When both exist, cross-validate and report
  discrepancies in the manifest; outline wins. Printed page numbers in old
  PDFs carry a delta-search offset correction (small deterministic search;
  failure → keep parsed values, flag uncertainty).
- **Section identity**: honest unnumbered (`number == ""`) + slug-keyed
  files; INDEX/plots/spec keying generalized to slug where numbers are
  absent; the layout engine assigns page ranges from the structure ladder
  directly and never routes through the TI-HTML pagemap machinery.
- **Semantics via shared lexicons + positional inference**: conditions
  headers accept suffix variants ("Test Conditions/Comments" measured in
  AD9081); min/typ/max/unit from numeric-column ordering and a universal
  units canonicalizer covering both ohm glyphs; revision shapes and
  doc-type prefixes (`sbaa|slaa|swra`, `ug-`, …) from shared lists.
- **Companion documents stay `pdf_text`-degraded** for every vendor in this
  change (register maps / user guides included) — parity with today.
- **Footnotes from geometry**: superscript markers via span size/raised
  baseline; trailing numbered lines attached with cited markers; models
  unchanged.
- **Figures from vector rendering**: `Figure N.` caption → render the
  region above it via the existing pixmap machinery; plots.json unchanged.
- **Schema**: additive fields only (sources.json: `vendor`,
  `vendor_evidence`; manifest: `vendor`, `extraction_stats`);
  `PIPELINE_VERSION` 0.1.0 → 0.2.0; spec/plot schema versions unchanged.
- **CLI**: `--vendor` on `build`/`add-doc`; `dsa status` surfaces vendor,
  evidence, and extraction stats; `verify` hard-fails without a per-part
  golden file.
- **Batch consistency** (parallelization work in progress): skip gate
  gains `pipeline_version`/vendor comparison; extraction-cache writes
  become atomic; worker-model rationale superseded in the batch ADR
  (offline CPU-bound jobs vs network-bound HTML jobs — threads retained,
  revisit with measured scaling).

## Testing Decisions

- **What makes a good test**: external corpus behavior only — given a PDF
  (real or synthetic) and temp-dir settings, assert what lands in the
  corpus: which sections exist and their page ranges, which tables became
  TableBlocks with correct grids, footnote attachment, what stayed
  paragraphs, specs.json records, plots.json entries, manifest
  extraction_stats, and not (ever) engine internals — no direct calls into
  clustering, the retry ladder, or the gate.
- **Single seam**: `build_part()` with settings from the existing
  `synthetic_env` pattern; the engine's accept/reject behavior is proven by
  crafting PDFs that must or must not produce tables (captionless doubles
  must stay paragraphs) and asserting on the corpus product.
- **Fixtures** (all ungated — offline by construction): the four gate PDFs
  copied into fixtures (`ad9081.pdf` 45p outline; `lm741.pdf` 17p numbered
  outline; `QPA1003P.pdf` 20p with **no** outline — forces the printed-TOC
  path; `hmc520a.pdf` 32p unnumbered outline), each with its own per-part
  golden file (`golden_qa_<part>.yaml`) whose ground truth comes from
  printed page text; `dsa verify` at 100% (text + `--specs` + plot
  lookups) in plain `pytest`.
- **Synthetic PDFs** (fitz-built in-test) pin engine pathologies: partial
  rulings, merged cells, header-less tables, captionless doubles,
  furniture-free pages, two-column printed TOCs, revised "Rev." furniture,
  bookmarks with and without embedded numbers.
- **Prior art**: the `synthetic_env` pipeline-test pattern (temp settings +
  injected fetcher, calling the seam function directly); extraction-cache
  tests (write-temp/rename style they already assert against); the
  multi-document integration fixtures; the golden-verify suite which this
  change extends per-part without altering its mechanics.

## Out of Scope

- HTML backends beyond TI (future vendor HTML sources must pass their own
  spike + recorded-fixture gate before any code lands).
- ML-assisted extraction of any kind.
- Tables for companion documents (register maps / user guides stay
  `pdf_text`-degraded).
- Changing the batch worker model itself (addendum only: measure, then
  revisit in the parallelization work).
- Pagemap rework for the TI HTML path; changes to INDEX token budget,
  plots/DPIs, or LLM enrichment beyond the description matcher.
- Anything resembling per-vendor layout rules anywhere in the engine.

## Further Notes

- Architectural record: ADR 0002 (evidence-pinned vendor routing),
  ADR 0003 (layout core supersedes the no-layout-analysis stance),
  ADR 0004 (honest unnumbered section identity); batch ADR 0001 carries the
  consistency addendum. Full working plan: `Reports/PHASE_4_PLAN.md`
  (superseded by `Reports/PHASE_4_REPORT.md`, this spec's completion
  record — measured token economics and extraction stats per gate part).
- Domain vocabulary refreshed in CONTEXT.md: Vendor, VendorProfile, Layout
  core, Furniture.
- Probe facts underpinning the design: AD9081 tables carry vertical rulings
  only at parameter/value/unit boundaries (Min/Typ/Max split by whitespace
  alone — verified as stable x-clusters); all four gate PDFs contain zero
  embedded images (pure vector figures); both ohm glyphs appear in AD9081;
  `QPA1003P` has no PDF outline at all.
