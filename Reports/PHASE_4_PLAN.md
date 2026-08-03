# PHASE 4 PLAN — Vendor-Neutral Layout Core + Multi-Vendor Gate

Supersedes the PHASE 2/3 view that extraction fidelity comes from TI's HTML
viewer alone. Phase 4 ships a **vendor-neutral offline layout engine**
(`pdf_layout`) as the guaranteed floor for every vendor, thins the
vendor concept down to evidence-pinned routing, and proves it against a
4-PDF acceptance gate spanning four layout families.

## Why

The pipeline's fidelity today comes from `ti_html` (TI's document viewer).
That does not generalize: many vendors (and older TI/ADI PDFs) have no
parseable HTML source, and `pdf_text` (paragraphs only, no tables) cannot
deliver the end-functionality — atomic tables, specs.json, plots.json,
citation-verified golden QA — for them.

Decision record from the grilling session (asked direction, not fell:
every option below was explicitly chosen):

- **Deterministic + self-verifying engine** — no ML (torch is forbidden by
  AGENTS.md; nondeterminism breaks cache-by-hash; silent cell corruption is
  the failure class this project exists to avoid).
- **Full vendor-agnostic reframe** — no per-vendor layout assumptions
  anywhere in the core; vendor conditions only inside backends that consume
  a vendor's *digital* format (today: `ti_html` alone).
- **Thin VendorProfile** (routing record, not rulebook) with evidence-pinned
  detection.
- **Gate + retry ladder + manifest stats** as the robustness mechanism.
- **Structure ladder**: bookmarks → printed-TOC parse → per-page sections.
- **Acceptance gate**: 4 genuinely different PDFs must all build with 100%
  golden verify before the engine is v1-done.
- **ti_html unchanged**, stays the only HTML backend until a future vendor's
  digital source passes its own spike + recorded-fixture gate.

## Target architecture

```
SourceDocument (vendor pinned at acquire w/ evidence)
   └─ backend selection: datasheet → VendorProfile preference chain
        ti     → [ti_html, pdf_layout]
        adi    → [pdf_layout]
        qorvo  → [pdf_layout]   (detected via brand lexicon)
        unknown→ [pdf_layout]
        companions (any vendor) → pdf_text (unchanged, v1 scope)
```

New module `extract/pdf_layout.py` → backend name `pdf_layout` (cache key
`<hash>__pdf_layout.json`; distinct from `pdf_text`). Fully offline, no new
dependencies (PyMuPDF only, already AGPL-accepted).

## Layout core spec

### Furniture (slot repetition, no strings)
- A furniture slot = y-band recurring across pages with positional + style
  (font size/style) consistency.
- Content in a slot is furniture iff constant text **or** matches universal
  page-machinery patterns: `N of M`, `Page N`, `Rev.` + token.
- Varying section-title echoes in a slot count as furniture only outside the
  body region (the page where a section starts keeps its real heading).
- No brand strings, no vendor anchors. PDFs with no consistent slots get no
  stripping (honest).

### Tables (structural inference + reconstruction gate)
- Candidate region = caption-anchored word cluster (`Table N.` caption line
  above a ruled/whitespace-structured area) — no hallucinated tables from
  prose.
- Hypothesis: rows = horizontal ruling bands (+ baseline clustering when
  unruled); columns = all-word x-clustering (proven on AD9081: values at
  stable x, e.g. 408.8 / 496.6 / 543.3); rulings are hints, never
  requirements (partial-ruling PDFs still split by whitespace).
- Rowspan/colspan: merge overlapping spans / repeated anchored sub-cells.
- **Retry ladder**: rejected hypotheses retried with coarser column splits /
  merged rows; each hypothesis scored on reconstruction fidelity.
- **Reconstruction gate**: the accepted grid must re-produce the page's own
  word stream — every word in exactly one cell, interior leftovers penalized.
  No hypothesis passes unverified.
- Failure records: tables detected / accepted / rejected + reasons, mean
  fidelity — persisted in the manifest as per-document extraction stats and
  surfaced by `dsa status`.

### Footnote support (from coordinates, not flattened text)
- Superscript markers detected via span size / raised baseline; glued-marker
  cells keep the marker text (matches the existing "glued sub/sup" rule).
- Footnote bodies = trailing numbered lines below the table region, attached
  to the TableBlock with cited markers (existing models unchanged).

### Figures
- No embedded images in any probed PDF (block diagram = 2241 vector ops).
- `Figure N.` caption → render the region above it via the existing pixmap
  machinery (`render_plot_pages_fallback` path); plots.json unchanged.

### Structure ladder
1. **Bookmarks** (fitz `get_toc`) — hierarchy from level, order from
   position; titles carry the number when printed (`lm741`: "1 Features"),
   stay `""` when not (ADI/Qorvo) — never fabricated.
2. **Printed-TOC fallback** (bookmark-less, e.g. QPA1003P) — generic
   dot-leader parse: title block + leader dots + trailing page number,
   indentation = hierarchy; numbers taken when printed else unnumbered.
3. **Neither** → one section per page, "Page N" titles (today's pdf_text
   honesty).
4. When both exist: cross-validate, report discrepancies in the manifest,
   bookmarks win.
   - Known risk: printed page numbers vs PDF offsets in old docs — mitigate
     with a small deterministic delta search (maximize title-match hits over
     delta ∈ {−2..+2}); failure → keep parsed values + flag uncertainty.

### Semantics (shared lexicons, positional inference)
- Roles: the existing `roles.py` positional inference generalizes; the
  conditions header accepts any `test conditions`-prefix variant
  ("Test Conditions/Comments" measured in AD9081); unit column inferred when
  a mostly-unit column sits right of numeric columns; min/typ/max identified
  by ordering of numeric columns, not per-vendor words (shared lexicon:
  min/minimum/typ/typical/nom/… max/maximum).
- Units: one universal canonicalizer maps every common glyph/spelling to the
  canonical unit (U+2126 AND U+03A9 → ohm — both measured in AD9081);
  verbatim preserved in corpus, canonicalized only in specs.json (existing
  rule).
- Revision: generic `Rev.` + token, TI doc-id (SBASA41E), "Document No."…
  shapes from a shared lexicon; used for `SourceDocument.revision`.
- Doc-type hints: shared prefixes (sbaa/slaa/swra, UG-, …) joined with
  filename word hints; order unchanged (errata → register → note → datasheet).

## Vendor routing (thin)

- `VendorProfile` registry next to the backend registry: detector (shared
  brand lexicon: "Texas Instruments", "Analog Devices", "Qorvo", … + generic
  fingerprints) + preference chain. No rules.
- Detection runs at acquire time on page-1 text + filename; **evidence
  pinned in sources.json** (`vendor`, `vendor_evidence`); a later run whose
  detection contradicts the pinned value logs a loud warning (identity
  drift detection); `--vendor` flag on `dsa build`/`add-doc` is an explicit
  override; default stays `ti` — zero behavior change on AFE7950/AFE7953.
- Manifest gains `vendor` + per-document extraction stats.

## Acceptance gate (the claim's proof)

Fixture set (`tests/fixtures/`, all ungated — the whole point is offline):

| PDF | Vendor/era | Stress exercised |
|---|---|---|
| `ad9081.pdf` (45 p, outline) | ADI new | unnumbered sections, partial rulings, Test Conditions/Comments |
| `lm741.pdf` (17 p, 40 numbered outline entries) | TI old | numbered bookmark titles, old-chrome furniture, op-amp spec tables |
| `QPA1003P.pdf` (20 p, **zero** outline) | Qorvo | printed-TOC fallback, "1 of 20" footer, modern layout |
| `hmc520a.pdf` (32 p, unnumbered outline) | ADI Hittite-era | third furniture family, S-param/mixer tables |

Acceptance = all four build to corpus, each with its own per-part golden
file (`golden_qa_ad9081.yaml`, `golden_qa_lm741.yaml`, …) and `dsa verify`
at 100% (text + `--specs` + plot lookups), plus honest failure records
(zero silent rejections). Synthetic fitz-built PDFs pin engine pathologies:
partial rulings, merged cells, header-less tables, captionless doubles,
two-column TOCs, furniture-free pages.

Golden Q&A becomes per-part files; `dsa verify` hard-fails when a part's
benchmark file is missing (a corpus with no benchmark is unverified).

## Schema / CLI / versions

- `sources.json`: additive `vendor` + `vendor_evidence` (no migration).
- `manifest.json`: additive `vendor`, `extraction_stats` per document.
- `PIPELINE_VERSION` 0.1.0 → 0.2.0. `SPECS_SCHEMA_VERSION`,
  `PLOTS_SCHEMA_VERSION` unchanged.
- CLI: `--vendor` on `build`/`add-doc`; `dsa status` shows vendor + evidence
  + per-document extraction stats.
- `_brief_and_facts` matches "General Description" (ADI) alongside
  "Description".

## Docs / invariants to update on landing

- AGENTS.md: the "layout analysis of dense parametric tables is the failure
  mode this project avoids" stance is superseded (see ADR 0003) — becomes
  "layout parsing happens only in the vendor-neutral core, every accepted
  grid is reconstruction-verified"; fixture invariant gains the ungated
  real-PDF class; U+2126 claim generalizes to "both ohm glyphs preserved
  verbatim"; architecture table gains `extract/pdf_layout.py` +
  `vendor` profiles.
- CONTEXT.md — updated in-session (Vendor, VendorProfile, Layout core,
  Furniture).
- README + this plan becomes `Reports/PHASE_4_REPORT.md` (measured token
  economics per gate part, extraction stats, verify results) once shipped.
- `Reports/PHASE_4_PLAN.md` is the completion record once superseded by the
  report (same convention as PHASE 2/3).

## Implementation order

1. VendorProfile registry + evidence-pinned detection + `--vendor` (TI
   behavior regression-locked by existing tests).
2. Layout core: furniture slots → table hypothesis + retry ladder +
   reconstruction gate → footnotes/figures → structure ladder.
3. Synthetic engine tests (fitz-built PDFs) for pathologies.
4. Gate provisioning: `tests/fixtures/` copies of the 4 PDFs + per-part
   golden files (ground truth from printed page text).
5. Dialect-free semantic layer: roles lexicons, unit canonicalizer,
   revision/doc-type genericization, brief matcher.
6. Verify 100% on all four parts + extraction-stats surfacing.
7. Docs: AGENTS.md invariants, README, PHASE_4_REPORT.md.

Out of scope (documented deferrals): HTML backends beyond TI (spike-gated),
companion-doc tables (register maps / UG-xxx stay pdf_text-degraded), ML
assistance, batch-parallelism changes.
