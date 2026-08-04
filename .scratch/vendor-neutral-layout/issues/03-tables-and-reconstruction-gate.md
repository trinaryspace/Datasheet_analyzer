# 03 — Tables: caption-anchored hypotheses + reconstruction gate

**What to build:** Tables from the layout core — caption-anchored
hypotheses, row bands from rulings/baselines, columns from word-position
clustering with rulings as hints, merged-cell inference with expanded
grids, conditions/caption attachment, table-page pinning, and specs.json
for non-TI parts. Every accepted grid must reconstruct the page's own word
stream: captionless tabular clusters stay paragraphs, garbage layouts
yield nothing.

**Blocked by:** 02 — pdf_layout paragraph core (first tracer)

**Status:** done (landed in `layout: pdf_layout tables + reconstruction gate, ticket 03`)

- [x] AD9081 spec tables (partial-ruling Min/Typ/Max, "Test Conditions/Comments" columns) build as atomic tables with correct expanded grids; `dsa query` resolves ADI spec records from specs.json (29/29 tables accepted, 547 spec records, `SpecQuery` resolves role-mapped rows incl. ohm canonicalization)
- [x] Table pages are pinned and verified against the PDF's own page text (≥80% of value cells verify on the exact cited page; continuation rows of merged multi-page blocks cite the block's first page)
- [x] A synthetic captionless tabular cluster comes out as paragraphs, never a table
- [x] A synthetic garbage-spacing layout yields no table at all (gate rejects; reasons recorded in manifest extraction stats)
- [x] `Table N.` captions and test-conditions preambles attach to the correct tables
- [x] TI-path golden verify remains 100% (full suite green, offline)

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
