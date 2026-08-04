# Known shortcomings — vendor-neutral layout (as of ticket 04)

Written after ticket 03 (tables + reconstruction gate) landed at `84ba05b`
and kept current through ticket 04 (best-scoring retry ladder + `dsa
status` stats). Honest ledger of things that are partial, heuristic, or
instrumented-but-thin, so they can be circled back to. Grouped by where
they likely belong; severity = impact on the multi-vendor claim, not
effort.

## Functional gaps

- **Merged-cell (rowspan/colspan) materialization is absent.** SPEC story
  12 ("merged cells inferred from overlapping spans and materialized as
  fully-expanded grids") is only partially served: wrapped multi-line cells
  merge into one row and empty cells stay honestly empty, and colspan'd
  headers fall back to `roles.py` empty-header inference — but nothing
  *replicates* a spanning cell across grid rows/columns. A table that
  depends on explicit span semantics (e.g. a parameter symbol spanning
  condition rows without indentation) loses that association. No synthetic
  test exercises real spans. Decision at the 04/06 boundary: explicitly
  deferred to ticket 06 (04's scope is the retry ladder + stats only).
  → ticket 06, high.
- **Captionless-era tables get nothing.** lm741 (old TI) and QPA1003P
  (Qorvo) have no "Table N." captions — their tables are heading-anchored —
  so they yield **0 tables / 0 specs**, honestly, but with zero
  functionality either. The phase-4 gate only proves captioned vendors
  (AD9081 29/29, HMC520A 6/6). Heading-anchored hypotheses would need
  care to not hallucinate. → ticket 06/07, high.
- **Footnote bodies are never attached to tables.** Ticket 03 only
  *detaches* footnote lines from grids (signature-based) so they stay
  paragraphs; they are not attached to `TableBlock.footnotes` with cited
  markers. `specs.json` rows therefore carry no footnote text. → ticket
  05 (explicitly owns this), medium.
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
  header never declared — a fine split that *carves* interior words of a
  multi-word header cell outvotes nobody (carved words are not advice
  edges), but only ties; chain-bridging prevented carving on every real
  PDF probed. The selection rule is a guard, not a guarantee.
- **No per-part golden Q&A for non-TI parts yet.** `golden_qa.yaml`
  covers AFE7950 only; AD9081/HMC520A have no verified question sets.
  → ticket 07, medium.

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
  Fine for honesty, weak for "how many tables" claims.
  → inspect before any public claim, low.

## Heuristics without boundary tests

- **Prose-drop threshold `_PROSE_WORDS = 8`**: a fine row confined to
  one band whose cell exceeds 8 words is dropped as prose. A legitimate
  all-in-one-column data row that long would vanish from its grid (and
  only survive as a stray paragraph). No boundary test.
- **Header anchor tau = 12 pt fixed**: a genuine multi-word header cell
  whose words sit >12 pt apart would over-split and risk rejecting a
  valid table. All *measured* cells sit within ~10 pt (AD9081 "Test
  Conditions/Comments" at 226.2/235.9/244.x).
- **Column tightness cap = 30 pt**: right-aligned cells wider than ~30 pt
  from the band's left edge would fail tightness. Not observed yet; the
  cap is justified only by the probe set.
- **Caption regex covers "Table N." / "Table N-M." / "Table N: M"**
  separators only. Exotic forms (e.g. centered captions, "TABLE III.",
  caption-below) are untested.

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
  handling still exists in two places.
- **`PIPELINE_VERSION` 0.2.0 → 0.3.0 was outside ticket 03's letter**
  (defensible under the cache-invalidation invariant; `extractor_version`
  is the real staleness guard). Keep both in lockstep when output schema
  changes.
- **Batch hash-gated skip**: verify `.scratch/batch-build/issues/02`'s
  skip gate compares `extractor_version`/`PIPELINE_VERSION`, not just
  hashes, before batch work resumes.
