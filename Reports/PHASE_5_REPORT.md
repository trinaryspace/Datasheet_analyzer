# PHASE 5 REPORT — Agent-Native Access

**Status: shipped.** Supersedes `Reports/PHASE_5_PLAN.md`, which was the
execution contract. Everything below is measured on the six built corpora by
the offline test suite; nothing here is asserted from the plan.

Phase 5 added **no new extraction**. It is surface over data phases 1–4
already produced: a retrieval core, an alias lexicon, a full-text path,
per-record confidence, answer packs, projects, an MCP front end, and the
retrieval protocol as an artifact that ships with the corpus.

## The claim, and how it is proven

> *A designer's question, in a designer's words, returns a cited answer inside
> a budget.*

Every one of the six built parts' golden sets gained two questions that test
exactly that: an **ask-path** question (natural language, no symbols) and a
**search-path** question (top-1 must be the section holding the answer). Both
are *twins* — they reuse an existing question's cited page and verbatim
substrings — so the new surface is judged by the objective function the
project already had, not by one written to fit it.

| Part | Golden Q | ask-path | search-path | `dsa verify` |
|---|---|---|---|---|
| AFE7950 | 21 | 1/1 | 1/1 | 100% |
| AFE7953 | 13 | 1/1 | 1/1 * | 100% on the paths its corpus supports |
| AD9081 | 6 | 1/1 | 1/1 | 100% |
| LM741 | 17 | 1/1 | 1/1 | 100% |
| QPA1003P | 16 | 1/1 | 1/1 | 100% |
| HMC520A | 15 | 1/1 | 1/1 | 100% |
| **Total** | **88** | **6/6** | **6/6** | |

\* AFE7953's corpus was published before `search_index.json` existed and cannot
be rebuilt in a hermetic test (no recorded TI document-viewer pages exist for
that part). Against the committed corpus its search-path golden **fails
loudly** — `search unavailable: … Rebuild to enable search` — which is the
correct answer: the path never ran, so nothing was established. The gate
verifies it against a copy whose index is rebuilt from the very markdown on
disk by the writer's own `build_search_index`
(`test_afe7950_build.py::TestGoldenPathsOnTheReferenceCorpora`), the same
"measure the committed corpus" method the ticket-04 regrade uses.

## Answer packs: one call instead of four

Measured over every golden question of every part, at `--budget 3000`.
"Multi-call" is the cost of the pre-phase path the same question took:
`INDEX.md` plus the covering section file (`estimate_lookup_tokens`).

| Part | Q | ask mean | ask max | multi-call mean | saving |
|---|---|---|---|---|---|
| AFE7950 | 21 | 288 tok | 573 tok | 3,617 tok | 12.6× |
| AFE7953 | 13 | 278 tok | 501 tok | 4,213 tok | 15.2× |
| AD9081 | 6 | 277 tok | 356 tok | 3,361 tok | 12.1× |
| LM741 | 17 | 222 tok | 291 tok | 2,906 tok | 13.1× |
| QPA1003P | 16 | 202 tok | 269 tok | 1,266 tok | 6.3× |
| HMC520A | 15 | 215 tok | 445 tok | 2,893 tok | 13.5× |

Every pack across all 88 questions is at or under budget at 3000 tokens, and
again at 400 — the largest is 573 tokens at the generous budget and, at the
tight one, what shrinks is excerpt prose and extra rows, never the first
answer row or its citation (asserted per question, both corpora sets).

Routing, over the same 88 questions, with **no LLM in the path**:

| Route | Questions |
|---|---|
| `spec` (alias ladder → record) | 58 |
| `search` (BM25 → section) | 19 |
| `plot` (figure vocabulary → catalog) | 11 |
| `none` / `unavailable` | 0 |

## Alias lexicon coverage

77 canonical families in `registry/aliases.yaml`; hit rate is measured, not
claimed (`scripts/seed_aliases.py`, printed by the test suite):

| Part | Golden questions resolved via alias | Corpus vocabulary covered |
|---|---|---|
| AFE7950 | 15/21 (71%) | 153/190 |
| AFE7953 | 11/13 (85%) | 149/185 |
| AD9081 | 5/6 (83%) | 79/216 |
| LM741 | 8/17 (47%) | 16/43 |
| QPA1003P | 12/16 (75%) | 31/35 |
| HMC520A | 8/15 (53%) | 10/16 |
| **Total** | **59/88 (67%)** | |

The misses are not failures: a question the lexicon does not resolve routes to
the figure catalog or the full-text index instead, which is why the route
table above has no `none`.

## Full-text search

The six search-path goldens — a designer's keywords, the way `dsa search` is
actually used — rank the answering section **first, 6/6**.

Asked the harder way, by feeding each golden's whole question sentence to
BM25, top-1 accuracy over all 88 questions is **64%** and top-3 is **82%**:

| Part | top-1 | top-3 |
|---|---|---|
| AFE7950 | 15/21 (71%) | 18/21 (86%) |
| AFE7953 | 8/13 (62%) | 10/13 (77%) |
| AD9081 | 5/6 (83%) | 6/6 (100%) |
| LM741 | 11/17 (65%) | 14/17 (82%) |
| QPA1003P | 12/16 (75%) | 14/16 (88%) |
| HMC520A | 5/15 (33%) | 10/15 (67%) |
| **Total** | **56/88 (64%)** | **72/88 (82%)** |

HMC520A is the floor and the reason is structural, not statistical: its
Hittite-era outline is unnumbered and its plot gallery is 107 near-identically
worded figure sections, so a question's words are spread thin across many
sections that legitimately contain them. This is the miss rate the plan said
should be measured *before* anyone reaches for embeddings; it is recorded here
rather than acted on.

### Index economics

`search_index.json` is written per document at publish, from the very markdown
the writer emits:

| Part | index | section markdown | index/markdown | index/corpus on disk |
|---|---|---|---|---|
| AFE7950 | 54,289 B | 186,147 B | 29.2% | 3.2% * |
| AFE7953 | 49,413 B | 159,121 B | 31.1% | 0.05% |
| AD9081 | 69,489 B | 88,712 B | 78.3% | 0.9% |
| LM741 | 48,650 B | 55,180 B | 88.2% | 7.3% |
| QPA1003P | 18,876 B | 24,553 B | 76.9% | 5.2% |
| HMC520A | 37,054 B | 60,814 B | 60.9% | 0.6% |

\* measured on the in-test build, whose plot images are hermetic stand-ins;
the committed AFE7950 corpus carries real figures and lands in the same
0.6–7.3% band as the rest.

## Per-record confidence

The mix each corpus reports in its own manifest (`structure/confidence.py`
grades once, at structure time; the grade is metadata and never filters):

| Part | Backend | Specs (high/med/low) | Plots (high/med/low) |
|---|---|---|---|
| AFE7950 | ti_html | 613 / 3 / 3 | 0 / 514 / 0 |
| AFE7953 | ti_html | 531 / 2 / 3 | 0 / 492 / 0 |
| AD9081 | pdf_layout | 151 / 207 / 191 | 2 / 98 / 0 |
| LM741 | pdf_layout | 0 / 0 / 71 | 3 / 0 / 0 |
| QPA1003P | pdf_layout | 0 / 0 / 41 | 4 / 0 / 0 |
| HMC520A | pdf_layout | 0 / 0 / 30 | 34 / 73 / 0 |

TI's HTML tables are never reconstructed, so they grade almost entirely
`high`; the captionless-era layout-floor parts grade entirely `low` because
their grids only ever pass the reconstruction gate on a rescue split. That is
the rule reporting the truth about the extraction, and the way to move it is
to make the layout floor reconstruct those grids from their own headers — not
to loosen the rule.

## Projects

A three-part project (AD9081 + LM741 + HMC520A) builds in the gate:
`PROJECT_INDEX.md` is **190 tokens** against a 4,000-token budget, names every
member and points at each member's own `INDEX.md`. A project-scoped `ask`
answers from the right part, twice over: once on hand-picked probes (a phrase
each part prints and the others do not) and once on **each member's own
ask-path golden**, where the answering row must be that member's, on the page
its benchmark cites, with every row labelled by part.

## MCP server

Nine tools (`list_parts`, `list_projects`, `get_index`, `search`, `find_spec`,
`read_section`, `find_plots`, `get_figure`, `ask`) plus two index resources,
over local stdio. Exercised in-process over the SDK's memory transport in two
places: the whole surface against a synthetic corpus
(`tests/unit/test_mcp_server.py`) and, since ticket 09, **the gate corpora**
(`test_phase4_layout_gate.py::TestMcpOverTheGateCorpora`) — every tool against
four real datasheets, each response validated against its declared schema,
`ask` landing the golden's cited page, `get_figure` returning a real image
block, a traversal attempt refused for that reason, and a 120-token cap
producing a truncated `get_index` that names `DSA_MCP_MAX_TOKENS`.

| Part | search hits | spec hits | ask | figure returned |
|---|---|---|---|---|
| AD9081 | 5 | 4 | `spec`, 206 tok | `functional-block-diagram-f001.png` |
| LM741 | 5 | 2 | `spec`, 216 tok | `8.2.1-f001.png` |
| QPA1003P | 5 | 4 | `spec`, 269 tok | `1-f001.png` |
| HMC520A | 5 | 1 | `spec`, 190 tok | `features-f001.png` |

### MCP hand-verification — **OUTSTANDING**

Ticket 07 left one acceptance box that no test can close: registering the
server in a real client per the README `mcp.json` snippet and confirming the
tools appear. The memory transport proves the *server*; it does not prove the
*registration*. Ticket 09 carries the box rather than leaving it unowned, and
it is still open:

| Client | Date | Tools called | Result |
|---|---|---|---|
| — | — | — | **not yet run by a human** |

**The phase does not close on this box.** Whoever runs it should fill the row
in with the client, the date and the calls made, and nothing should be written
here that a human has not actually done.

## Agent protocol

`protocol.py` holds the rules once and renders them into three destinations:
`parts/<PART>/AGENT.md` (1,420 tokens measured, ceiling 1,700),
`projects/<NAME>/AGENT.md` (1,496 tokens for a three-part design) and the
checked-in `.claude/skills/datasheet-corpus/SKILL.md`. `INDEX.md` and
`PROJECT_INDEX.md` point at it instead of repeating it, and `AGENT.md` carries
a version marker so the batch skip gate republishes a corpus written before
the protocol existed.

## Acceptance gate

| # | Gate (from the plan) | Result |
|---|---|---|
| 1 | Every existing golden question for all six parts passes `dsa verify` at 100% | ✅ 88 questions, six parts |
| 2 | Ask-path questions per part, resolving to the same answer and page as the symbol path | ✅ 6/6 |
| 3 | Search-path questions per part, top-1 = the answering section | ✅ 6/6 |
| 4 | A 3-part project builds; a project-scoped `ask` returns the right part | ✅ 190-token index; per-member golden answered by that member |
| 5 | Every `ask` response at or under budget, asserted numerically | ✅ 88 questions at 3000 and at 400 |
| 6 | MCP: every tool in-process, schemas validated, truncation notice asserted | ✅ synthetic corpus + four real ones |
| 7 | `pytest` fully offline, `ruff` clean | ✅ |

## Known residuals

Recorded per question in the tests, so a regression fails *and* an unrecorded
fix fails:

- **LM741 `s1-spec-supply-absmax`** — the ask path reaches the named
  absolute-maximum supply rows and cites p.4, but the `±18` the question also
  expects lives on a nameless device-variant sub-row whose only text is the
  symbol `Supply`. Closing it means materializing an inherited *parameter
  name* into continuation rows at extraction time (ticket 09 of phase 4
  materializes the symbol only) — a corpus change, not a retrieval one.
- **AFE7950 `q07-vco-coverage`** — the question names `VCOs`, which is a
  symbol *prefix* here (`fVCO1`…`fVCO4`), not a phrase a whole-phrase lexicon
  can match, and its expected extremes are the first and last of eight sibling
  rows, so the per-route row cap would drop one even if the rung existed. The
  symbol-path twin only reaches it by filtering to §4.7 — a scope the
  natural-language question never states.
- **The two corpora committed under `parts/` have no search index.** They were
  published before ticket 03 wrote one, so `dsa verify --part AFE7950` and
  `--part AFE7953` report their search-path golden as `search unavailable`
  until the part is rebuilt. For AFE7950 the fix is one `dsa build` (the gate
  verifies it against exactly that build); for AFE7953 a rebuild needs TI
  document-viewer pages this repo does not record, so the gate verifies it
  against a copy whose index is rebuilt from the published markdown. The batch
  skip gate already refuses to skip such a corpus, so a rebuild is one command
  and never a silent stale answer.
- **Search top-1 at 64% over whole-sentence questions** (above). Keyword
  queries, which is how `dsa search` is used, rank 6/6.

## Out of scope, kept out

HTTP/remote MCP transport, auth and multi-tenancy; BOM/netlist import; LLM
query routing; embedding/semantic search; all new extraction (pins, registers,
cards, plot axes — phase 6).
