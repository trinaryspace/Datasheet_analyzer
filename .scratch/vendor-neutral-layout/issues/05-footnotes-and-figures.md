# 05 — Footnotes + figures vertical

**What to build:** The two remaining content kinds from the layout core —
table footnotes detected from font geometry (superscript markers via span
size / raised baseline) plus trailing numbered lines attached to their
table with cited markers, and figures rendered from vector drawing regions
(`Figure N.` caption → render the region above it) into image files listed
in plots.json.

**Blocked by:** 02 — pdf_layout paragraph core (first tracer)

**Status:** ready-for-agent

- [ ] AD9081's glued superscript markers ("AC Coupling2") and trailing numbered lines attach as enumerated footnotes on the correct tables; a golden question citing footnote text verifies at 100%
- [ ] Block diagrams and vector plots on gate parts render as image files under their Figure captions; plots.json lists them and `dsa plots` finds them
- [ ] A footnote without a detectable marker still attaches positionally to the table immediately above it
- [ ] Existing TI plot/footnote tests remain green

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
