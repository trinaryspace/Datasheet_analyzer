# 13 — Locate a citation on the page

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/locate.py`
- `src/datasheet_analyzer/app/routers/locate.py`
- `tests/unit/test_locate.py`

**What to build:** Given a citation, return the rectangles to highlight on the
PDF page. No bounding box is persisted anywhere in the repo — geometry lives in
transient `_Span` / `_Line` slots inside `pdf_layout.py` and is discarded when
extraction returns — so this derives geometry on demand instead, by opening the
PDF and searching for the record's own text.

`locate(pdf_path, page, needle) -> LocateOut` opens the page with PyMuPDF and
runs `page.search_for(needle)`. Needle selection is the hard part, not the
search:

- **A spec row** → the most distinctive cell in `SpecRecord.row_verbatim`,
  preferring the symbol or name over a bare number. `−40` appears fifty times
  on a page; `OPERATING JUNCTION TEMPERATURE` appears once.
- **A table** → the caption.
- **A section or search hit** → the opening of its first paragraph, truncated
  to a length that stays on one line.

Reuse the discipline already in `structure/pagemap.py::pin_table_pages` —
squashed "distinctive needles", require enough evidence, and **leave it
unpinned rather than guess**. That is invariant 3, and here it means a miss
returns `found=False` with a human-readable reason and an empty `rects`, so the
UI opens the page with no highlight. A box around the wrong row is worse than
no box: it makes a verification step actively lie.

Row rectangles want to span the table, not just the matched cell. Take the
matched rect's vertical band and widen it horizontally to the text block's
extent on that page, so the highlight reads as a row.

This ticket must not touch `pdf_layout.py` and must not bump
`output_version` — leaving the extraction cache valid is the whole reason this
approach was chosen over persisting geometry.

- [ ] A needle appearing exactly once on the page returns `found=True` with one rect
- [ ] A needle appearing several times returns every hit, ordered top to bottom
- [ ] A needle that does not appear returns `found=False`, empty `rects`, and a non-empty `reason`
- [ ] A page number outside the document returns `found=False` with a reason, not an exception
- [ ] An unreadable or missing PDF returns `found=False` with a reason
- [ ] Row rects are widened horizontally to the text extent and keep the matched vertical band
- [ ] Coordinates are PDF points with the origin the frontend expects, documented in the response model
- [ ] Ligatures, soft hyphens and non-breaking spaces in the needle are normalized before searching
- [ ] A needle chosen from `row_verbatim` prefers a symbol or name over a bare numeric cell
- [ ] `pdf_layout.py` is not modified and `output_version` is unchanged
- [ ] The endpoint resolves the PDF path from the manifest join (`doc_hash` → `documents[*].content_hash` → `path`) and 404s cleanly when the file has moved
- [ ] Tests build synthetic PDFs with known text at known coordinates via `fitz` and assert rects within a tolerance; no network
