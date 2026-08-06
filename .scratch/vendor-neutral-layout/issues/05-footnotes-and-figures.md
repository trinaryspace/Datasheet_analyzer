# 05 — Footnotes + figures vertical

**What to build:** The two remaining content kinds from the layout core —
table footnotes detected from font geometry (superscript markers via span
size / raised baseline) plus trailing numbered lines attached to their
table with cited markers, and figures rendered from vector drawing regions
(`Figure N.` caption → render the region above it) into image files listed
in plots.json.

**Blocked by:** 02 — pdf_layout paragraph core (first tracer)

**Status:** shipped (commit on `feat/pdf-layout-paragraph-core`, ticket 04
pattern: TDD at `build_part`, gate-PDF measured proof, ledger updated)

- [x] AD9081's glued superscript markers ("AC Coupling2") and trailing numbered lines attach as enumerated footnotes on the correct tables; a golden question citing footnote text verifies at 100% — measured: Table 3 cites real footnotes 1+2 ("201" = 20 + citation 1), footnote 1's wrapped continuation merges into the body, corpus carries each body exactly once; `golden_qa_AD9081.yaml` (minimal, boundary decision recorded in the ledger — full per-part rollout is ticket 07) verifies 3/3 offline. The golden proves corpus-contains + page-truth on the footnote text; the attach seam itself (once-only rendering, per-marker citations) is pinned by the dedicated gate assertions
- [x] Block diagrams and vector plots on gate parts render as image files under their Figure captions; plots.json lists them and `dsa plots` finds them — measured: AD9081 101/101 images (23-111 KB), HMC520A 110/110, LM741 5/5; `find_plots` resolves the vector figures; plot ids for unnumbered sections key by title slug ("dac-f001") so multi-section figure pages never collide (corrected at ticket 08: those figure counts were probe-time estimates — the measured numbers are AD9081 100/100, HMC520A 107/107, LM741 3/3, recorded in `PHASE_4_REPORT.md` and the AGENTS.md gate table)
- [x] A footnote without a detectable marker still attaches positionally to the table immediately above it — synthetic test 05 pins the positional attach, the after-marked-block stop, and the all-caps-heading guard (hmc520a p3 shape)
- [x] Existing TI plot/footnote tests remain green — full suite green, gate tables unchanged (AD9081 29/29, HMC520A 6/6, fidelity 0.90/0.88)

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
