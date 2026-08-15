# PHASE 5 PLAN — Agent-Native Access

**Status: planned.** Execution contract for `.scratch/agent-native-access/`.
Superseded on landing by `Reports/PHASE_5_REPORT.md` (measured numbers), per
the convention that a shipped plan closes with a report, never by assertion.

**Scope decisions taken before writing** (see `Reports/ROADMAP_5_7.md` for the
full decision record): local-stdio MCP only, projects are explicit part lists,
derived data is deterministic-only, depth before breadth.

## Why

Phases 1–4 solved retrieval *fidelity*: verbatim extraction, page-pinned
citations, a token-budgeted index, a vendor-neutral layout floor, and a golden
Q&A that gates. What they did not solve is *access*. The corpus is a
filesystem a human drives with `dsa`, and the CLI answers only the questions a
caller already knows how to phrase:

- `dsa query --symbol TJ` works. "What is the max junction temperature?"
  returns nothing — there is no alias layer between a designer's words and a
  datasheet's symbols.
- There is no full-text path at all. An agent must know to grep
  `sections/*.md` and must attribute page numbers itself, defeating the
  provenance guarantee the corpus was built for.
- Every answer costs 3–4 CLI round trips that the agent must assemble by hand,
  with no budget enforcement — a `--section 4.9` read is 9,607 tokens with no
  warning.
- Nothing above `part` exists. The stated goal is compiling datasheets *for a
  project*; the repo has no noun for that.
- The corpus is invisible to any client that is not running a shell.

Phase 5 adds no new extraction. It is surface work over data that already
exists, and it is what converts a well-built corpus into something a hardware
designer talks to while drawing a schematic.

## Target architecture

```
                 ┌──────────────┐   ┌──────────────┐
                 │ dsa CLI      │   │ MCP server   │  (stdio)
                 └──────┬───────┘   └──────┬───────┘
                        └────────┬─────────┘
                          thin adapters only
                        ┌────────▼─────────┐
                        │  retrieve/       │   NEW — the deep module
                        │  Retriever       │
                        │   .specs()       │
                        │   .sections()    │
                        │   .plots()       │
                        │   .search()      │
                        │   .ask()  ← pack │
                        └────────┬─────────┘
              ┌──────────────────┼──────────────────┐
       ┌──────▼──────┐   ┌───────▼──────┐   ┌───────▼───────┐
       │ CorpusIndex │   │ AliasLexicon │   │ SearchIndex   │
       │ (cached)    │   │ (data file)  │   │ (built at     │
       │ specs/plots │   │ symbol↔words │   │  publish)     │
       │ sections    │   └──────────────┘   └───────────────┘
       └─────────────┘
```

Today `query.py` re-`rglob`s and re-parses every `specs.json` on every call.
That is acceptable for one CLI invocation and wrong for an MCP session that
makes dozens. `retrieve/` owns loading-and-caching once, and both front ends
become adapters that format what it returns. **No retrieval logic may live in
`cli.py` or the MCP server after this phase** — that is the seam.

## Component specs

### 1. Retrieval core (`retrieve/`)

New package: `retrieve/index.py` (CorpusIndex), `retrieve/retriever.py`
(Retriever), `retrieve/pack.py` (answer packs), `retrieve/search.py` (BM25).

- `CorpusIndex.load(part_dir)` reads `manifest.json`, every `specs.json`,
  `plots.json`, and the search index once into memory. Cached in-process,
  keyed by `(part_dir, manifest mtime, pipeline_version)`; a rebuilt corpus
  invalidates naturally.
- `Retriever` returns **typed result objects**, never formatted strings:
  `SpecHit`, `SectionHit`, `PlotHit`, `AnswerPack`. Each carries
  `citation` (doc, page or page range), `confidence`, and `matched_via`
  (`symbol` | `alias:<term>` | `name-substring` | `fulltext`).
- `query.py` is retained as a thin back-compat shim delegating to `retrieve/`
  so existing tests and any external callers keep working; it gains a
  deprecation note and no new features.

### 2. Alias lexicon (`registry/aliases.yaml` + `structure/aliases.py`)

Data, not code — same philosophy as the vendor brand lexicon. Adding a
synonym must never require touching Python.

```yaml
TJ:
  names: [junction temperature, operating junction temperature, t_j, tj]
  expect_unit: "°C"
  kind: temperature
IDD:
  names: [supply current, quiescent current, operating current]
  expect_unit: A
  prefix_match: true        # IVDD1P8, IVDD1P2 … all inherit
```

Resolution ladder, first hit wins, and the winning rung is reported back to
the caller as `matched_via`:

1. exact symbol match (case-insensitive)
2. alias name match (whole phrase in the query)
3. alias prefix families (`IDD` → `IVDD1P8`)
4. name substring (today's behaviour)
5. token-overlap fuzzy match over `name`, only above a fixed threshold

`expect_unit` is a **disambiguator, not a filter**: when two rungs tie, the
candidate whose canonical unit matches wins. It never suppresses a record
whose unit is missing — honesty over tidiness.

Seeded from the symbols already present across the six built corpora, so
coverage is measurable on day one rather than aspirational.

### 3. Full-text search (`search_index.json`, built at publish)

A precomputed inverted index per document beats shelling out to ripgrep: it is
deterministic, dependency-free, and usable inside the MCP server without
spawning processes.

- Built in `publish/` alongside the section files. Tokens are lowercased,
  stopword-stripped; **no stemming** (technical terms and symbols must survive
  intact — "SYSREF", "θJA", "dBc/Hz").
- Schema: `{schema_version, docs: {section_id: {tokens: {tok: tf}, len: N}},
  df: {tok: n}, avgdl: float}`. Positions are not stored; snippets are
  recovered by re-reading the matched section file, which is cheap and keeps
  the index small.
- Ranked with BM25 (k1=1.2, b=0.75). Results carry the section's page range
  from its `<!-- source: ... -->` header, so **every search hit is cited by
  construction** — the agent never attributes pages itself.
- Snippet = ±240 chars around the highest-scoring term occurrence, expanded to
  sentence boundaries, with the section header prepended.
- `dsa search --part X "sysref setup" [--limit N] [--json]`.

### 4. Per-record confidence

`extraction_stats` is per-document today; answers need it per-record. Additive
`confidence` enum on `SpecRecord` and `PlotRecord`, computed at structure time
by a documented rule:

| Grade | Rule |
|---|---|
| `high` | table pinned to an exact page **and** reconstruction gate passed first try **and** the row's value cells are non-empty |
| `medium` | page is section-range only, **or** the row has an empty min/typ/max cell |
| `low` | grid rescued by the retry ladder, **or** unit missing where the alias lexicon expected one |

Rendered in CLI output and returned in every MCP response. This is what lets
an agent say "this value is `low` confidence — open p.47 to confirm" instead
of asserting it. Pairs with `dsa audit` in Phase 7.

### 5. Answer packs (`dsa ask`)

One call, one context payload, a hard budget.

```
dsa ask --part AFE7950 "max junction temperature" --budget 3000 [--json]
```

Routing is **deterministic — no LLM in the path**. The question is classified
by feature hits, in order:

1. alias/symbol hit → spec lookup (cheapest, ~300 tok)
2. plot vocabulary hit (`plot|curve|vs\.|versus|graph|figure`) → plot lookup
3. otherwise → full-text search + section excerpt

The pack is assembled greedily by score against the budget, with a reserved
tail so citations can never be truncated away:

```
## AFE7950 — SBASA41E (datasheet-c1b4663b)
### Answer
TJ  Operating junction temperature: 105 °C (max) — §4.3, p.6  [high]
### Supporting excerpt  (§4.3 Recommended Operating Conditions, p.6)
...240 chars...
### Verify
Printed page 6 of afe7950.pdf.  Confidence: high.
```

On no match the pack says so explicitly and suggests the nearest alias
candidates. **It never falls back to a guess** — that is the whole point.

### 6. Projects

```
projects/<name>/
├── project.json        # name, parts[], notes, created/updated
└── PROJECT_INDEX.md    # always-loadable, hard budget (default 4000 tok)
```

`project.json` holds an explicit part list; no BOM or netlist parsing in this
phase (deferred deliberately — see Out of Scope). `PROJECT_INDEX.md` is the
single entry point for a whole design: each part with its one-line role, its
revision, a pointer to its `INDEX.md`, and a free-text `interfaces` note the
designer maintains by hand.

Commands: `dsa project new|add|remove|build|status`. Project-scoped retrieval
(`--project` on `ask`, `search`, `query`, `plots`) fans out across member
parts and labels every hit with its part, which is what makes "does anything
in this design need a 1.8 V rail?" answerable.

### 7. MCP server (`dsa serve --mcp`)

Local stdio only. No auth, no HTTP, no multi-tenancy.

| Tool | Returns |
|---|---|
| `list_parts` / `list_projects` | names + revision + section/spec counts |
| `get_index(part)` | `INDEX.md` text |
| `search(scope, query, limit)` | ranked hits with page cites + snippets |
| `find_spec(part, symbol?, name?, section?)` | spec records + cites + confidence |
| `read_section(part, ref, max_tokens)` | section text, truncated with notice |
| `find_plots(part, q?, section?, tags?)` | plot records + file paths |
| `get_figure(part, file)` | **the PNG as an image content block** |
| `ask(scope, question, budget)` | an answer pack |

`get_figure` is the tool that makes the plot catalog pay off: the agent
narrows with `find_plots`, then receives the one image it needs and can
present it to the designer — or, later, analyse it.

Every response carries citations and confidence. A global response cap
(`DSA_MCP_MAX_TOKENS`, default 6000) truncates with an explicit notice naming
the flag; **truncation is always visible, never silent**.

Resources: `dsa://part/<PART>/INDEX.md` and `dsa://project/<NAME>/PROJECT_INDEX.md`
so a client can pin the index into context without a tool call.

Dependency: the official `mcp` Python SDK, added as an optional extra
(`pip install -e ".[mcp]"`) so the core install stays lean. Tests drive the
server **in-process over the SDK's memory transport** — no subprocess, no
port, hermetic per invariant #4.

### 8. Corpus agent protocol

The retrieval discipline currently lives as prose inside `INDEX.md` and,
in practice, inside your prompts. Promote it:

- `parts/<PART>/AGENT.md` and `projects/<NAME>/AGENT.md`, emitted at publish:
  index first, never bulk-read, always quote units, always cite `p.N`, check
  confidence, fall back to the printed page when `low`.
- `.claude/skills/datasheet-corpus/SKILL.md` in-repo, so any Claude Code agent
  in this workspace adopts the protocol without being told.

## Schema / CLI / versions

- **Additive only.** `SpecRecord.confidence`, `PlotRecord.confidence`,
  `SectionFile.search_tokens` (count, for budgeting). New files:
  `search_index.json` per doc, `AGENT.md` per part/project.
- `PIPELINE_VERSION` 0.2.0 → **0.3.0**. Extraction cache is keyed on
  `(content_hash, backend)` and is untouched by this phase; the *publish*
  artifacts change, so a version bump forces republish via the batch skip
  gate (which already gates on `pipeline_version`).
- New CLI: `search`, `ask`, `project`, `serve`. Existing commands unchanged in
  behaviour; `query` and `plots` gain `--project` and `--json`.
- New config: `DSA_PROJECTS_DIR` (default `projects`), `DSA_ASK_BUDGET`
  (default 4000), `DSA_MCP_MAX_TOKENS` (default 6000).

## Acceptance gate

The claim of this phase is *"a designer's question, in a designer's words,
returns a cited answer inside a budget."* Proof:

1. Every existing golden question for all six parts still passes `dsa verify`
   at 100%.
2. Each part's golden set gains **ask-path** questions phrased in natural
   language (no symbols), which must resolve through the alias lexicon to the
   same verbatim answer and the same page as the existing symbol-path
   question.
3. Each part's golden set gains **search-path** questions whose top-1 hit must
   be the section containing the hand-verified answer.
4. A 3-part project builds, and a project-scoped `ask` returns the right part.
5. Every `ask` response across the golden set is **at or under budget**,
   asserted numerically.
6. MCP: every tool exercised in-process; responses validate against their
   declared schemas; the truncation notice is asserted on an over-budget read.
7. `pytest` fully offline, `ruff` clean.

## Implementation order

| # | Ticket | Rationale |
|---|---|---|
| 01 | Retrieval core seam | Everything else is an adapter over it |
| 02 | Alias lexicon | Cheapest hit-rate win; `ask` depends on it |
| 03 | Full-text search index | Second retrieval path; publish-time change |
| 04 | Per-record confidence | Needed before answers can be graded |
| 05 | Answer packs (`dsa ask`) | Composes 01–04 |
| 06 | Projects | Independent of 02–05; can run in parallel with them |
| 07 | MCP server | Needs 01–06 stable to expose |
| 08 | Agent protocol files + skill | Documents the finished surface |
| 09 | Golden extension + phase gate | Proves the claim; closes the phase |

Tickets 01→05 are a chain; 06 is parallelisable; 07 is the join.

## Docs / invariants to update on landing

- `AGENTS.md`: module map gains `retrieve/`, `registry/aliases.yaml`, the MCP
  entry point; conventions gain the "no retrieval logic in front ends" seam.
- `CONTEXT.md`: new nouns — **Project**, **Answer pack**, **Alias**,
  **Confidence**.
- `README.md`: MCP setup snippet, `ask`/`search`/`project` usage.
- `Reports/PHASE_5_REPORT.md`: measured alias hit rate, mean answer-pack
  tokens vs today's multi-call cost, search top-1 accuracy on the goldens.

## Out of scope (kept out, recorded)

- **HTTP/remote MCP transport, auth, multi-tenancy** — local stdio only.
  Revisit if the corpus is ever shared across a team.
- **BOM CSV and EDA netlist import** — projects take explicit part lists. An
  agent that can read a BOM can call `dsa project add` itself, which is the
  cheap 90% of the value.
- **LLM query routing.** `ask` classification is deterministic. An LLM caller
  is welcome to *use* `ask`; it is not allowed *inside* it.
- **Semantic/embedding search.** BM25 plus the alias lexicon first; measure
  the miss rate in the Phase 5 report before considering vectors, which would
  add a model dependency and break determinism.
- All new extraction (pins, registers, cards, axis metadata) — Phase 6.

## Further notes

- `.env` is currently tracked in git and contains an `API_KEY` line. It has
  never been committed; `git rm --cached .env` plus a `.gitignore` entry
  clears it before it lands in history. Unrelated to this phase, but it
  should be fixed before the next commit.
