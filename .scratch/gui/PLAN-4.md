---
title: GUI round 4 — a structured library
labels: [ready-for-agent]
---

# Why

The Library is a flat set. That is fine as a record and useless as a place to
*find* something: pulling a part you used two years ago into a new project
means reading every row. An RF/embedded shelf has obvious structure —
amplifiers, mixers, passives, transformers, op-amps, data converters — and the
Library should have it too.

Three things follow, and each has a decision behind it (grilled, recorded):

- **Category is a fourth Applicability kind.** ADR 0005 says three and no
  fourth; a document that covers every amplifier is exactly a fourth, and
  modelling it any other way would give retrieval two mechanisms for one idea.
- **A part's category is a human answer, not a build output.** The manifest is
  rewritten by every build, so a category stored there dies at the next
  rebuild — the trap Labels were designed around. The machine's guess lives in
  the manifest; the person's answer lives beside the Library and wins.
- **Part numbers are corroborated, not chosen from one source.** Mini-Circuits
  names files after the part (`PMA1-14LN+.pdf`); TI names them after the
  document (`sbas123e.pdf`). Reading only the text produced `LHA-83W+ →
  DQ1225`; reading only the filename would undo SPEC user story #2. Taking
  both and preferring the corroborated one gets both vendors right.

| # | Ticket | Owns (primary) |
|---|---|---|
| 38 | Category taxonomy + per-part record | `library/categories.py`, `library/parts.py` |
| 39 | Applicability gains `category` | `models.py`, `docs/adr/0005` |
| 40 | Corroborated part numbers | `acquire/applicability.py` |
| 41 | Category inference over a built corpus | `acquire/categorize.py` |
| 42 | Category + taxonomy endpoints | `app/routers/categories.py` |
| 43 | Document-only build (supporting documents) | `pipeline.py`, `app/jobs.py` |
| 44 | The compact review row | `web/src/routes/analyze/**` |
| 45 | Post-build categorise step | `web/src/routes/analyze/CategorizeStep.tsx` |
| 46 | The two-pane Library | `web/src/routes/library/**` |
| 47 | Clear the user's built data | (operational, not code) |

## Rules

1. Never edit `extract/pdf_layout.py`; never bump `output_version`.
2. Never clear `parts/AFE7950`, `parts/AFE7953`, `.cache/extract` or
   `.cache/http-bin` — committed fixtures the suite asserts against, and the
   recordings that keep it off the network.
3. A build may propose a category; only a person may set one.
4. One category per part, plus `uncategorized`. Multi-membership is a Label.
5. Tests hermetic; `ruff check` and `npm run typecheck` clean.
