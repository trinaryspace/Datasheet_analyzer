# PHASE 6.5 WAVE 1 — measured results

**Status: landed, not yet rebuilt.** Tickets `.scratch/extraction-fidelity/issues/05–08`.
Execution contract: `Reports/PHASE_6_5_PLAN.md`. Wave 2 (ticket 09) is not started.

Wave 1 is the cache-invalidating half of Phase 6.5: four fixes in the layer
under the derived artifacts, landed together so the corpus is re-extracted
once. **`PdfLayoutBackend.output_version` is deliberately unchanged**, so none
of this is visible in a built corpus yet — ticket 09 bumps it once and rebuilds.

Suite: **2356 collected**, every test passing except two that belong to another
session's in-flight work (`test_contracts.py`, `test_library_api.py`); both
reproduce with every source change in this wave stashed. `ruff check` clean.

| # | Ticket | Headline |
|---|---|---|
| 05 | furniture vs. table content | LMX1204's register summary: absent → **35 rows** |
| 06 | row reconstruction | HMC520A: **24 pins** published; **37** AD9081 values corrected |
| 07 | per-row page pinning | LMX1204 `Table 7-1`: off-by-one rows **1 → 0** |
| 08 | record id uniqueness | AD9081: **259 → 549** distinct ids over 549 records |

---

## 05 — The furniture detector ate table content

Two failures on `LMX1204_registermap.pdf`, one of which the plan had not seen:

1. `0x0` — the reset value of a field — prints in one y-band on **11 of 25
   pages** against a threshold of 10, so the register summary's first body row
   was classified as page machinery. Region cut off after the header row,
   `no viable column split`, all 35 rows lost.
2. Its field tables reprint one header row (`Bit | Field | Type | Reset |
   Description`) in the same slot on **21 pages**. Every cell of it recurs, so
   the row is entirely flagged and **97%** of its band is furniture. All 21
   tables were cut off before their first row and rejected with `no rows`.

**The second one is why the plan's approach had to change.** Its own suggestion
— compare the band's furniture share — separates case 1 cleanly (the colliding
band is 24% machinery, the running header's is 96%) and cannot separate case 2
at all: by recurrence *and* by band occupancy, a reprinted table header is
indistinguishable from a running header.

What separates them is structure, not statistics: **page machinery never prints
directly under a `Table N.` caption.** Everything below the first caption on a
page is released, bounded by the page's *body span* — what remains after
stripping the leading and trailing rows that are machinery all the way across,
which is exactly what a running header and footer are.

**A first attempt was more permissive and leaked.** It also released a flagged
line that merely shared its row with content, gated on the band share. LM741
page 15 prints `www.ti.com` beside a generated date, so the header shared its
row with content, and its band — used by few pages — read as mostly content.
The integration gate caught it (`furniture 'www.ti.com' leaked`), and the rule
was cut back to caption evidence only. The narrower rule keeps every gain:

| Document | Released lines | In a margin zone |
|---|---|---|
| `LMX1204_registermap.pdf` | 229 | **0** |
| `hmc520a.pdf` | 4 | **0** |
| the other 10 PDFs | 0 | **0** |

**Measured on the register map:** accepted tables 13 → **32** of 38 detected;
field-description tables 13 → **30**; grid rows 56 → **286**; `Table 1-1`
absent → **35 rows**. Rejection reasons went from `{no rows: 21, no viable
column split: 2, columns not stable: 2}` to `{rows do not span columns: 4,
columns not stable: 2}`.

## 06 — Row reconstruction

Four distinct misreads, each with its own class in `test_pdf_layout_rows.py`.

### A lent first cell is not a key

`_materialize_band0` lends a spanning parent's cell downward — right for
reading, wrong for keying. HMC520A's `Table 4` prints no pin number for its
exposed-pad row; the lent `15` made two rows claim one designator and the
device-table layer refused the table, losing **all 24 real pins**.

Phase 6 named this cause in a docstring and chose refusal. The fix is not to
stop lending but to **record it**: `TableBlock.lent_first_cells` lists the rows
whose first cell was lent, and a consumer that keys on that column reads them
as *unkeyed*, which is what the page says. HMC520A now publishes **24 pins**,
and the exposed-pad row becomes no record with the note `prints no key of its
own` rather than disappearing silently.

The refusal itself is untouched — a row that really prints `15` twice still
rejects the table, and there is now a test for each direction.

### A column edge crossed by float noise

The largest single correction in this wave, and it was invisible.

LMX1204's body cell `R0` starts at x = 100.24398803710938; the header cell
`Acronym` that declares its column starts at 100.24400329589844 — **1.5×10⁻⁵ pt**
further right. A strict half-open interval put `R0` in the *previous* column,
so every row of the register summary read `0x0 R0 | Powerdown… | | Go` and the
address column stopped being addresses: **0 of 35 rows keyed**. With a 0.1 pt
tolerance the table parses as a register map with all **35** addresses.

The same noise was corrupting values on parts nobody suspected:

| Part | Was | Is | The page says |
|---|---|---|---|
| AD9081 `Full-Scale Output Current Range, AC Coupling` | `min='6.43 26.5'`, `typ='37.75'`, `max=''` | `min='6.43'`, `typ='26.5'`, `max='37.75'` | header Min 438.8 / Typ 465.9 / Max 521.5; row prints at 439.07 / 465.89 / 521.47 |
| AD9081 phase noise, **37 records** | `min='−118'` | `typ='−118'` | `−118` prints at 487.56, `Typ` declares 487.60 |
| HMC520A `Table 1.` | 5 rows, all `low` | **28 rows**, high 25 / medium 19 / low 41 | the header's own 6 columns now pass the gate |

Thirty-seven phase-noise figures were filed as guaranteed **minimums** when the
datasheet prints them as **typicals**. That is the kind of wrong number a
designer acts on.

### A data row folded into the header

Wrap-merging uses the region's row pitch, and the pitch is wrong when the
region caught text that is not the table's: LMX1204's field tables are followed
by the next section's prose at 18 pt, which lifted the wrap threshold above the
table's own 14 pt row gap. **5 tables** read `Bit 15:0 | Field
rb_CLKPOS[31:16] | …`, with the header's declaration destroyed and a rescue
split winning the ladder.

The two shapes separate on how much the later baseline fills: a wrapped header
continues *some* cells (2 of 8 on AFE7950's ordering table), a folded data row
fills **every** column the header filled. Sub-baseline skew (AD9081's 0.9 pt,
HMC520A's 0.4 pt) is one printed line and never splits.

### An identifier split across two lines

LMX1204 R13 and R17 print `SYSREFREQ_DELAY_STEPSIZE` across two lines; the grid
read `SYSREFREQ_DELAY_ST EPSIZE`, a field name that does not exist. Geometry
does not decide it — the line had 5.6 pt of room against a 4.7 pt character, so
the break was not width-forced at that glyph. The rule is lexical and narrow:
both fragments identifier-shaped, and the head must contain an underscore, so
`POWER` over `SUPPLIES` keeps its space. `SYSREFOUT0_DELAY_PHASE` and
`SYSREFOUT2_DELAY_PHASE` came back with it.

### What this exposed downstream, and what was *not* changed

Making HMC520A's `Table 1.` reconstruct from its own header put its footnote
superscript inside the Parameter cell, where the corpus glues markers on
purpose — `test_pdf_layout_footnotes.py` fixes that contract so a reader of an
answer can see which footnote applies. The symbol became `RF RANGE1`, no alias
matched it, and "Over what RF frequency range does this mixer work?" started
answering with `LO INPUT FREQUENCY RANGE` and `IF FREQUENCY RANGE` — both real
records, neither the answer.

**A first fix dropped the marker at extraction and was wrong**: it overturned a
deliberate, tested contract as a side effect. It was reverted. The hole is in
matching, not in extraction — AD9081 has printed `Maximum Aperture Jitter2` all
along — so the ladder now tries the marker-stripped form *alongside* the printed
one. Offering both can only add a match, which is what makes it safe: stripping
alone is wrong in both directions (`AVDD2`), and the record's own
`cited_markers` cannot referee — it carries `1` for a row reading `VCO Output
Divide by 1` too.

## 07 — Per-row page pinning for HTML-derived tables

`TableBlock.row_pages` is real geometry on the `pdf_layout` path and the HTML
path has none, so every row cited the page its *table* began on. Measured on
LMX1204's `Table 7-1`: row 34 (`0x5A` / `R90`) prints on page 33 and cited 32.

The rule is `pin_table_pages`'s, applied one level down, plus the structural
fact that makes it safe: **a printed table advances one page at a time.** Rows
are walked in order and each is only asked whether it stayed or moved to the
next page. Searching the whole section instead — the obvious first
implementation — fails on exactly this row: `0x5A` and `R90` both appear again
on page 54, twenty-two pages past a 35-row table, and the tie left it unpinned.

| Measure | Before | After |
|---|---|---|
| `Table 7-1` rows citing a page they are not printed on | 1 of 35 | **0** |
| rows pinned document-wide | 0 of 501 | **458** |
| rows whose cited page really prints them | 397 | **416** |
| rows citing a page that does not print them, while another does | 12 | **1** |

The surviving one is a two-page jump the one-page-at-a-time walk will not make.
It refuses rather than leaps, which is the intended direction.

Two bounds had to widen, both because the section range is a *heading*
boundary and not a content one. AFE7950's section 4.8 is recorded as pages
20–20, and its last four rows (`VOCOM`, `VOD`, `ZT` and their LVDS band header)
print on page **21** — checked against the PDF's own page text, they appear on
21 and **not** on 20. `test_phase2_specs` was relaxed to allow exactly one page
of spill, and a new test was added beside it that checks every spilled record
against the page it cites, so the widened bound is evidence and not slack.

## 08 — Spec record ids are unique within a document

`spec_record_id` was a pure function of `(section, table_index, row_index)`, and
tables are numbered *within* a section — so a document whose sections carry no
printed number restarted at 0 in every one of them.

| Part | Records | Distinct ids before | After |
|---|---|---|---|
| AD9081 | 549 | 259 | **549** |
| HMC520A | 85 | — | **85** |
| LM741 | 71 | — | **71** |
| QPA1003P | 41 | — | **41** |

`rec_s-t0-r0` alone had been carried by 14 records.

The id now keys on the section's **published file stem**, which is already
unique per section — two sections sharing it would collide on disk first.
Numbering tables document-globally was the plan's other option and was
rejected for a reason now asserted in the tests: `table_index` is a position
*within* a section, read as one by the CSV twin names and by every lookup back
into `section.tables`. The stem also leaves neighbours alone when a document
gains a section, which matters because ids appear in citations already written.

`SPECS_SCHEMA_VERSION` 3 → 4. A record written before this stays addressable
through a documented fallback to its section number.

**Not yet measured, and deferred to ticket 09:** AD9081's interface card
publishing the ~21 rows its selectors match, and `CardDocument.uncitable`
reaching 0. Cards are built from a *published* corpus, and this one has not been
rebuilt. What is proved now is the cause — no record is refused for sharing an
id, because none shares one.

## Gates that were changed, and why

Six checked-in expectations moved. Each recorded a defect rather than a
guarantee, and each was verified against the PDF before the expectation was
rewritten:

| Gate | Was | Now |
|---|---|---|
| `test_ad9081_spec_records_resolve_via_query` | `min == "6.43 26.5"` — its comment called the fused cell "honest" | the printed `6.43 / 26.5 / 37.75` |
| `test_a_rescued_grid_is_why_the_captionless_corpora_are_low` | HMC520A in the all-`low` group | HMC520A produces all three grades |
| `test_every_record_page_in_section_range` | records confined to the section's TOC range | one page of spill, each instance proved |
| `test_a_repeat_that_prints_every_column_is_a_duplicate` | HMC520A's pin table must be refused | its 24 pins publish; a *printed* duplicate still refuses |
| `alias_seed_symbols.json` | 16 HMC520A symbols; 37 AD9081 values as minimums | 30 symbols; the values as typicals |
| `SPECS_SCHEMA_VERSION == "3"` | — | `"4"` |

## What wave 1 did not do

`output_version` is unchanged, so the extraction cache still serves the old
results and **no built corpus carries any of this yet**. That is the plan's
shape: one cache bump, one rebuild, at the end. Ticket 09 does it and re-measures
every Phase 6 gate — including whether register bit fields now clear their
accuracy gate and un-park.
