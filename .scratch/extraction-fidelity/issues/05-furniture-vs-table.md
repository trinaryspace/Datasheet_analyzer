# 05 — The furniture detector eats table content

**The single highest-value fix in this phase.**

**What to build:** A furniture detector that cannot classify the interior of an
accepted table region as page machinery.

**Measured:** `LMX1204_registermap.pdf` prints its whole register summary as
`Table 1-1` on page 2 — 35 rows of address / acronym / features / section. The
tool reads **none** of it.

The chain, end to end:

1. The furniture detector strips content that recurs at the same slot across
   pages — the correct rule for headers, footers, and page numbers.
2. The string `0x0` prints in that same y-band on **11 of the document's 25
   pages**: it is the reset value of a field on most field-description pages.
   The recurrence threshold is **10**.
3. The first body row's address cell is therefore classified as page machinery
   and removed.
4. The table region is cut off after its header row, reconstruction is rejected
   with `no viable column split`, and the cell is gone from the paragraph
   stream too — so nothing downstream can recover it.

**Fix:** a recurring slot that falls **inside an accepted table region** is
table content, not page machinery. Either run the detector with table regions
already known, or exclude their interiors from it. Pick one and say why in the
report — the ordering constraint between region detection and furniture
detection is the interesting part of this ticket, not the predicate.

**Why it matters beyond one table:** this is a generic misread, not a one-part
quirk. Any register map is dense in repeated short hex strings at stable
positions, which is *precisely* the signature the detector keys on. Expect it
to affect every register map the corpus ever ingests.

**Guard against the obvious wrong fix.** Raising the threshold from 10 would
make this document pass and quietly break header stripping on any document with
more than 10 pages. The predicate must be about *where* the text is, not how
often it appears.

**Blocked by:** — (wave 1; lands with 06–08 as one cache-invalidating change)

**Status:** ready-for-agent

- [ ] Develop against **synthetic PyMuPDF fixtures** first: a document whose
      genuine running header recurs, and one whose table cell recurs at the
      same slot. The first must still be stripped; the second must survive.
- [ ] `LMX1204_registermap.pdf` yields `Table 1-1` with all **35** rows
- [ ] Every document already extracting correctly is byte-identical afterwards
      *except* where this fix is the reason — diff the corpus and account for
      every change, do not assume
- [ ] Real running headers/footers/page numbers still stripped — assert on a
      document that has them
- [ ] The threshold constant is unchanged (see the guard above)
- [ ] `output_version` **not** bumped here; ticket 09 bumps it once for the wave

**Owns:** `src/datasheet_analyzer/extract/pdf_layout.py` (furniture detection
only), `tests/unit/test_pdf_layout_furniture.py`

---

Source: `.scratch/extraction-fidelity/SPEC.md`
