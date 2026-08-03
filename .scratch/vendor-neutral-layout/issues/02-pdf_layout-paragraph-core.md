# 02 — pdf_layout paragraph core (first tracer)

**What to build:** The vendor-neutral layout core's skeleton — generic
furniture slot detection (recurrence + universal page-machinery patterns,
no vendor strings), the structure ladder (outline → printed-TOC
dot-leader parse → per-page sections), sections with page ranges feeding a
normal corpus build. Non-TI datasheets route to the engine, so an ADI,
Qorvo, or old-TI PDF builds offline: sections, pages, paragraphs, INDEX —
tables come later.

**Blocked by:** 01 — Vendor routing seam + additive schema

**Status:** ready-for-agent

- [ ] `dsa build` of AD9081, lm741, and QPA1003P produces corpora fully offline: sections, page ranges, INDEX, inventory with vendor evidence
- [ ] QPA1003P (no PDF outline) sections come from a generic printed-TOC parse; a synthetic bookmark-less PDF with no printed TOC degrades to per-page sections
- [ ] Furniture bands (ADI "Rev. 0 | N of 45", old-TI web-chrome, Qorvo "1 of 20") are absent from section paragraphs on every gate part, confirmed against golden strings
- [ ] A synthetic furniture-free PDF keeps all its text (no false stripping)
- [ ] Sections stay honestly unnumbered where the source has no numbers (slug-keyed files, correct page citations); lm741's numbered outline titles produce numbered sections
- [ ] Existing TI-path tests remain green

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
