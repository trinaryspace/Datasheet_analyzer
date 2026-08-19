---
title: GUI round 3 — the project as the working surface, and honest highlights
labels: [ready-for-agent]
---

# Why

Two complaints, both correct, and the causes are unrelated.

**The Library shows every part ever scanned.** Two bugs compound: nothing adds
a built part to the open project, and `filterGroupsToProject` returns
*everything* when the part list is empty. But the fix is not "scope the
Library" — the Library is the whole bookshelf and that is its job. What was
missing is a surface that is about *this* project, which is what the shelf
rail becomes.

**Highlights land on the footer.** Not a geometry bug — the overlay was
verified correct at 1x, at fit-width and at 1.5x device pixel ratio. The cause
is that documents with no detected headings get sections titled `Page N`, and
the citation needle is the section title. `"Page 3"` appears exactly once on
the page: in the running footer.

Measured: PMA1-14LN+ 9/9 sections titled `Page N`, ZX10R-2-183-S+ 2/2,
CA1389 5/5, DQ1225 5/5 — and AD9081 0/34, lm741 0/40. 100% of the radar
corpus affected, 0% of the reference corpora, which is why it looked total to
the user and worked in every demo.

| # | Ticket | Owns (primary) |
|---|---|---|
| 31 | Hash-first skip gate | `batch.py` |
| 32 | Honest highlights | `app/locate.py`, `retrieve/results.py` |
| 33 | The project shelf endpoint | `app/routers/projects.py`, `app/contracts.py` |
| 34 | Add a document to a project (copies the PDF) | `app/routers/projects.py`, `projects/shelf.py` |
| 35 | The shelf rail | `web/src/shell/ShelfRail.tsx` |
| 36 | Library as the bookshelf, geared to the project | `web/src/routes/library/**` |
| 37 | Land on the project picker every launch | `web/src/routes/analyze/**` |

## Decisions this round rests on (grilled, recorded)

- A Project's folder is a **shelf**: it holds copies of the sources it was
  built from. It is still a view over parts — removing never deletes.
- The **Library is every *processed* document**. A PDF enters it when it is
  built, never before. A processed document may sit in one project or many.
- Therefore the rail is *not* one Library query: it is the folder's files,
  with the Library saying which of them are processed.
- Labels are for processed documents only. Build first, then label.
- Identity is the content hash. Path is a tiebreak, never a precondition.

## Rules

1. Never edit `extract/pdf_layout.py`; never bump `output_version`.
2. Tests hermetic: no network, no live model, no subprocess, no browser.
3. Copying never overwrites. A clash is copied alongside and flagged.
4. `ruff check` and `npm run typecheck` clean; every acceptance box a real test.
