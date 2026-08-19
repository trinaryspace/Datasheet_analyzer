# 07 — HTML-derived tables cite the page the table starts on

**What to build:** Per-row page pinning for tables that came from the HTML
path, so a row cites the page it is printed on.

**Measured:** `TableBlock.row_pages` is filled by the `pdf_layout` backend from
real geometry. The `ti_html` path has no page geometry, so every row of an
HTML-derived table inherits the page its **table** began on. On LMX1204's
`Table 7-1`, **1 row of 35** (`0x5A` / `R90`) prints on page 33 and cites page
32. Spec records read from those tables inherit the error.

One row in thirty-five is small, and it is the kind of error that is worst when
small: a citation that is *nearly* right is the one a reader trusts without
checking. A citation that is wildly wrong gets caught the first time someone
opens the page.

**Fix:** locate each row's distinctive cells in the PDF's per-page text and pin
the row to the page it is found on. `structure/pagemap.pin_table_pages()`
already does exactly this at *table* level; this applies the same rule one level
down. Reuse it rather than writing a parallel implementation — if the row-level
case needs different behaviour, deepen that function rather than forking it.

**The failure mode to design against** is a row whose cells are not distinctive
enough to locate (an all-blank row, a row of dashes, a row whose text appears on
three pages). Those must keep the table's page and say so, not guess. A pinning
rule that is confident when it should not be turns 1 wrong row in 35 into an
unknown number of wrong rows, which is worse than what we have.

**Blocked by:** — (wave 1; independent of 05/06/08 in code)

**Status:** done (wave 1; rebuild pending in 09)

- [x] Row-level pinning implemented by extending `pin_table_pages`'s rule, not
      by duplicating it
- [x] An ambiguous or non-distinctive row falls back to the table's page and
      records that it did — no guess
- [x] LMX1204 `Table 7-1`: every row cites its printed page; the named
      off-by-one row is gone and the count is **0**
- [ ] Spec records derived from those rows carry the corrected page —
      **deferred to 09**: proved at the `TableBlock` level, and the
      published `specs.json` follows only after the rebuild
- [x] `pdf_layout`-derived tables are unaffected — they already have geometry
      and this path must not overwrite it
- [x] Synthetic fixture covering: distinctive row, ambiguous row, blank row

**Owns:** `src/datasheet_analyzer/structure/pagemap.py`,
`src/datasheet_analyzer/structure/tables.py`,
`tests/unit/test_pagemap_rows.py`

---

Source: `.scratch/extraction-fidelity/SPEC.md`
