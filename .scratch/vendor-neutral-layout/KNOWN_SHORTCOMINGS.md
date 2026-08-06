# Known shortcomings — vendor-neutral layout (as of ticket 06)

Written after ticket 03 (tables + reconstruction gate) landed at `84ba05b`
and kept current through ticket 04 (best-scoring retry ladder + `dsa
status` stats), ticket 05 (footnotes + figures vertical) and ticket 06
(semantics genericization). Honest ledger
of things that are partial, heuristic, or instrumented-but-thin, so they
can be circled back to. Grouped by where they likely belong; severity =
impact on the multi-vendor claim, not effort.

## Functional gaps

- **Merged-cell (rowspan/colspan) materialization is absent.** SPEC story
  12 ("merged cells inferred from overlapping spans and materialized as
  fully-expanded grids") is only partially served: wrapped multi-line cells
  merge into one row and empty cells stay honestly empty, and colspan'd
  headers fall back to `roles.py` empty-header inference — but nothing
  *replicates* a spanning cell across grid rows/columns. A table that
  depends on explicit span semantics (e.g. a parameter symbol spanning
  condition rows without indentation) loses that association. No synthetic
  test exercises real spans. Boundary notes: deferred at 04/06 to ticket
  06, then re-deferred at the 06/07 kickoff — 06 shipped semantics only
  (lexicons + positional inference, SPEC stories 22–25) and grid
  materialization is a reconstruction design that needs its own
  probe-backed synthetic fixture set, not a lexicon change (recorded in
  the 06 issue file). → ticket 07 (grid materialization), high.
- **Captionless-era tables get nothing.** lm741 (old TI) and QPA1003P
  (Qorvo) have no "Table N." captions — their tables are heading-anchored —
  so they yield **0 tables / 0 specs**, honestly, but with zero
  functionality either. The phase-4 gate only proves captioned vendors
  (AD9081 29/29, HMC520A 6/6). Heading-anchored hypotheses would need
  care to not hallucinate (SPEC story 10: captionless doubles must stay
  paragraphs — that guard is a rejection-gate design, bigger than a
  lexicon change). → ticket 07, high (06/07 boundary decision recorded
  in the 06 issue file).
- **Fixed in ticket 05: footnote bodies attach to their table with cited
  markers.** Superscript citation markers are detected from span geometry
  (size ≤ 0.82× the row's max span, glyph-box center above the row's
  vertical middle, glued to the previous span — measured 0.61-0.75× on
  AD9081/HMC520A) and land in `TableBlock.cited_markers`; the trailing
  numbered lines below the grid attach as `Footnote(marker, body)` with
  bare-canonical markers ("1.", "(1)", "1Reference" → "1"), wrapped
  continuations merge into the open footnote (AD9081 p5's footnote 1 is two
  lines), and marker-less bodies attach positionally to the table directly
  above them (ticket item 3). Measured on the gate: AD9081 Table 3 cites
  footnotes 1+2 ("201" = value 20 + citation 1 is a real second citation),
  its body text lands in the corpus exactly once, and a golden question
  citing footnote text verifies at 100%. Residuals (below, "Footnote
  geometry" heuristics).
- **Ladder fixed in ticket 04: every band set is gated and scored, and
  only the best-scoring grid wins** (SPEC story 13). The selector is
  `_advice_share`: the share of header-anchored column edges the candidate
  band set reproduces — a split that merges the header's declared columns
  loses the edges it merged, and the header-anchored candidate is the
  score maximum by construction whenever it passes; ties keep ladder
  order. Measured word fidelity is *reported* (mean_fidelity), never a
  selector, because fidelity-max demonstrably prefers prose-fragmenting
  splits (AD9081 Table 3: 0.850 for an over-fine grid vs 0.739 for the
  header-declared one). Measured: all 35 real gate tables keep their
  ticket-03 grids verbatim. Residual: the score is blind to bands the
  header never declared — a fine split that *carves* the interior words
  of a multi-word header cell (words <12 pt apart, so the header-anchored
  clustering keeps them in one cell) neither adds nor removes advice
  edges: it ties, and ladder order keeps the primary split. Only words
  ≥12 pt apart are advice edges at all — a genuinely wide cell is then
  *declared* as separate columns by the engine's own rule (see the header
  anchor tau item below). The selection rule is a guard, not a guarantee.
- **No per-part golden Q&A for non-TI parts yet.** `golden_qa.yaml`
  covers AFE7950 only. Ticket 05 shipped a *minimal* `golden_qa_AD9081.yaml`
  (footnote-citing + spec + plot questions, verified 100% offline in the
  gate test) as the boundary decision — the full per-part benchmark
  rollout (all parts, `dsa verify` hard-fail wiring, SPEC story 26) is
  ticket 07, medium.
- **Interleaved footnotes stay paragraphs.** A footnote line that sits
  *between* grid rows (HMC520A p4's "1 See JEDEC ..." thermal note inside
  the Table-3 region) is dropped from the grid but never becomes a
  `Footnote` — only rows *after* the last multi-band grid row attach.
  Honest (nothing lost; it renders as a paragraph) but the citation link
  is missed. Mid-grid footnotes are rare; a position-insensitive attach
  would risk swallowing real grid rows. → revisit with real cases,
  medium.
- **Figure clips are region estimates, not art bounds.** The clip is the
  rectangle above the caption (prev caption or page top → caption line):
  single-figure pages may include the page header, and two-column figure
  pairs share one band image (each caption gets its own record, both
  pointing at the same rendered band). No embedded-image PDFs exist in
  the gate set; a PDF with raster figures under captions would render
  them the same way (clip includes the image), unverified. → revisit
  with real raster figures, low.
- **QPA1003P yields zero figures** — it has no "Figure N." captions at
  all (its block diagram is captionless), so the honest result is an
  empty plots.json. Same class as the captionless-tables gap: title-
  anchored figures would need the same care. → ticket 07, low (rides
  along with the heading-anchored-hypotheses work).

## Citation and verification nuances

- **Merged multi-page tables cite only the first page.** Continuation
  rows merged into a block (AD9081 Tables 16/17/21 spanning 2-5 pages)
  all carry the caption page. Measured: 20 of the 21 AD9081 pin
  "misses" (11% of 189 checked value rows) are continuation rows living
  on later pages — every one is found within ±2 pages (the block's
  span). The corpus-verify gate therefore asserts ≥80% rather than
  100%. Per-row page attribution inside merged grids is the fix.
  → ticket 07 (citations), medium.
- **Pin verification has a text-rendering blind spot.** Glued
  superscript markers render differently in page text than in cells
  (e.g. 'Maximum Aperture Jitter2' on p9 verifies neither way). 1/189
  observed. → verify lower bound includes honest slack, low.
- **Stats count caption *occurrences*, not distinct tables.**
  `tables_detected`/`accepted` increment per caption line, so
  multi-page tables count once per page (HMC520A reports "6 accepted"
  for 6 captions — correct; AD9081 reports 29 for 21 distinct tables).
  Fine for honesty, weak for "how many tables" claims. `dsa status` now
  surfaces these counts per document, so any public claim built on
  status output inherits the occurrence semantics; it also truncates
  rejection reasons to the first 3 (trailing "…") to stay one line.
  → inspect before any public claim, low.

## Heuristics without boundary tests

- **Prose-drop threshold `_PROSE_WORDS = 8`**: a fine row confined to
  one band whose cell exceeds 8 words is dropped as prose. A legitimate
  all-in-one-column data row that long would vanish from its grid (and
  only survive as a stray paragraph). No boundary test.
- **Header anchor tau = 12 pt fixed**: a genuine multi-word header cell
  whose words sit >12 pt apart would over-split and risk rejecting a
  valid table. All *measured* cells sit within ~10.9 pt (AD9081 "Test
  Conditions/Comments" at 226.2/235.9/244.x). Ticket 04 extends the
  consequence: words ≥12 pt apart become *declared columns* — the
  header-anchored edge list carries one edge per word, so a fine split
  that reproduces those edges wins the retry ladder on `_advice_share`
  and a genuinely wide cell is read as several columns. No boundary
  test exercises a >12 pt multi-word cell; the probe set has none.
- **Column tightness cap = 30 pt**: right-aligned cells wider than ~30 pt
  from the band's left edge would fail tightness. Not observed yet; the
  cap is justified only by the probe set.
- **Band-edge tolerance = 0.75 pt fixed** in `_advice_share`: an advice
  edge counts as reproduced when a candidate band edge sits within
  0.75 pt. Absorbs float noise between clustering runs (measured
  adjacency 0.1 pt: AD9081 header "Max" at 450.0 vs the all-word band at
  449.9) — but two true columns whose starts sit between 0.75 pt and
  tau apart would false-credit each other's edge. No boundary test.
- **Caption regex covers "Table N." / "Table N-M." / "Table N: M"**
  separators only. Exotic forms (e.g. centered captions, "TABLE III.",
  caption-below) are untested.
- **Marker size ratio = 0.82 fixed** in `_row_markers`: a superscript
  citation must be ≤0.82× the row's max span size with ≥1 pt difference.
  AD9081/HMC520A markers measure 0.61-0.75× — the threshold absorbs the
  spread, but a legit marker at 0.85× or a chemical subscript smaller
  than 0.82× with a raised box would misread. No boundary test.
- **A "10^6"-style exponent is geometrically identical to a glued
  superscript marker** (measured: HMC520A's ">1 × 106 Hours" '6' has the
  same size/rise as its real markers) — it lands in `cited_markers` as an
  orphan (the footnote-marker audit flags it; nothing in the product
  prints it). Rejecting it would also reject real after-digit markers
  (AD9081's "29001", "× 0.8142" — both measure identically). Pinned by a
  synthetic test; the trade-off is recorded, not "fixed".
- **`_FOOTNOTE_GAP = 28 pt` and the continuation threshold (pitch×0.92)**
  bound the trailing-block scan: a marker-less sentence within 28 pt of
  the grid's last multi-band row attaches positionally — a real
  paragraph sitting directly under a table in that window would be
  swallowed (no geometric signal separates them; AD9081/HMC520A trailing
  notes measure 12-26 pt). The all-caps heading guard ("6 GHZ TO 10
  GHZ ...") and the post-marked-block stop pin the observed shapes only.
- **Multi-band grid-end rule**: the footnote scan starts after the last
  row that spans column bands (both the first-page and continuation
  branches share the rule); a table whose *final* rows are single-band
  sub-headers (none observed) would read them as footnote continuations
  within the window. The hmc520a p3 shape (all-caps sub-table headings
  between grid rows) is pinned by test. Every trailing row — marker
  rows included — must sit within 28 pt of the grid end (or of the last
  attached row) to belong to the block; a numbered line far below a
  table is never claimed by it.
- **Same-band caption rule (`≤ _FIGURE_MARGIN` = 12 pt)**: side-by-side
  captions measured 0.07-7.9 pt apart; a stacked caption pair closer
  than 12 pt (figure rows are ≥180 pt apart on every real page) would
  share a clip. No boundary test.
- **Prose-drop threshold `_PROSE_WORDS = 8`** (see above) doubles as the
  footnote-continuation fence: a wrapped footnote fragment of ≤8 words
  that sits >cont_th below its marker line would become a grid row
  again. Pinned at the 8-word boundary in the positional-attach test.

- **Revision sniffing is lexicon-literal, not prose-aware.** Ticket 06
  `sniff_revision` matches the shared shapes only: capitalized "Rev."
  + token (`[A-Z][A-Z0-9]?` or 1-3 digits — "Rev. 0", "Rev. A",
  "Rev. I"), "Rev. N to Rev. M" shapes keep the last token (the current
  revision), and TI document ids must contain at least one digit
  (SBASA41E/SNOSC25D pass; the old regex read bare all-letter S-words
  like "SUPPORT" as document ids — measured false positive on AD9081
  page 1, now pinned dead). Lowercase "rev. a", all-caps "REV. 0",
  dotted tokens ("Rev. 1.2") and "Document No."-style ids (a PHASE_4_PLAN
  design seed, unmeasured so far) fall through to the honest "" — the
  shape list is what it is, deliberately not prose-aware, and a "Rev."
  mention in title-page prose (rare) wins over the title block. Also:
  the first page carrying *either* shape is the answer — a page-1 TI
  doc-id short-circuits a "Rev." token on page 2/3 within the window — so
  the "Rev-token wins within a page" rule never re-opens an earlier page.
  Cache note: cached raws embed the acquire-time revision, so ticket 06
  bumped `pdf_layout` extractor_version tables-05 → tables-06
  (invariant #6) — resume the lockstep discipline from the Engineering
  debt section.
  Deterministic, boundary-pinned by synthetic tests in `test_acquire.py`,
  recorded here for the record.

## Engineering debt

- **`_Page.v_rulings()` reopens the PDF per page** (lazy drawing scan).
  Builds are still fast (AD9081 ~1.5 s), but the reopen is avoidable
  (e.g. pass the open doc through).
- **`attached` set keyed by `id(block)`** in `_sections_from_entries`:
  pydantic models aren't hashable; identity-based dedup is fragile if
  blocks were ever rebuilt/re-serialized mid-run. An explicit monotonic
  block index would be sturdier.
- **Continuation vs first-page row filtering share logic**: partially
  deduped post-review (`_is_repeated_header`), but footnote/prose
  handling still exists in two places (first-page `run()` vs the
  continuation branch).
- **`figure_anchor_map()` re-opens the PDF** at render time (publish
  stage) — deterministic, drift-free, and ~0.3-0.5 s per doc, but the
  same two-phase scan as extraction. A cached geometry side-channel
  would avoid the reopen on repeat builds.
- **`PIPELINE_VERSION` 0.2.0 → 0.3.0 was outside ticket 03's letter**
  (defensible under the cache-invalidation invariant; `extractor_version`
  is the real staleness guard). Keep both in lockstep when output schema
  changes.
- **Batch hash-gated skip**: verify `.scratch/batch-build/issues/02`'s
  skip gate compares `extractor_version`/`PIPELINE_VERSION`, not just
  hashes, before batch work resumes.
