---
title: Agent-native access — retrieval core, search, answer packs, projects, MCP
labels: [ready-for-agent]
---

**Execution contract:** `Reports/PHASE_5_PLAN.md` (architecture, schemas,
CLI surface, acceptance gate, implementation order). This file is the tracker
root: problem, solution, user stories, decisions, scope boundary.

## Problem Statement

The pipeline delivers token-efficient, citation-verified corpora, but only to
a caller who already knows how to phrase a datasheet's own vocabulary and is
willing to spend several shell round trips assembling an answer. A designer
asks "what is the max junction temperature?"; `dsa query` only answers
`--symbol TJ`. There is no full-text path, so an agent greps `sections/*.md`
and attributes pages by hand — defeating the provenance guarantee the corpus
exists for. There is no budget enforcement, so a section read can silently
cost 9,607 tokens. There is no noun above `part`, though the goal is compiling
datasheets *for a project*. And the whole corpus is invisible to any client
that is not running a shell.

## Solution

A retrieval core (`retrieve/`) becomes the single implementation of every
lookup, with the CLI and a local stdio MCP server as thin adapters over it.
An alias lexicon maps designers' words to datasheets' symbols; a precomputed
BM25 index adds a cited full-text path; per-record confidence grades every
answer; `dsa ask` returns one budget-bounded, fully-cited pack instead of four
round trips; `projects/` groups parts into a design; and the retrieval
discipline ships as `AGENT.md` with each corpus. No new extraction: this phase
is surface over data that already exists.

## User Stories

1. As a designer, I want to ask "max junction temperature" in plain words and
   get `TJ 105 °C — §4.3, p.6`, so I do not have to know the datasheet's
   symbol before I can look something up.
2. As a designer, I want `dsa search --part X "sysref setup"` to return ranked
   sections **with page citations already attached**, so I never attribute a
   page by hand.
3. As an agent, I want one `dsa ask` call to return a complete, cited,
   budget-bounded answer pack, so a question costs one round trip instead of
   four and can never blow my context.
4. As an agent, I want a stated budget to be honoured exactly, and any
   truncation to be announced in the response, so silent loss is impossible.
5. As an agent, I want every returned value to carry a confidence grade, so I
   can tell the designer to check the printed page when the extraction was
   weak instead of asserting a shaky number.
6. As an agent, I want a question with no match to say so and suggest nearer
   terms, so I never present a guess as an answer.
7. As a designer, I want `projects/rf-frontend/` to hold the parts of one
   design with a single always-loadable `PROJECT_INDEX.md`, so an agent can
   orient on the whole board from one file.
8. As a designer, I want to ask a question across a whole project and see
   which part each answer came from, so "does anything here need a 1.8 V
   rail?" is one question.
9. As an agent in Claude Code, Claude Desktop, or Cursor, I want the corpus as
   MCP tools rather than a CLI I must shell out to, so I can use it without a
   terminal and with typed arguments.
10. As an agent narrowing 514 figures, I want to filter the catalog and then
    receive **the one PNG** as an image, so I can present it to the designer
    without burning vision calls on wrong figures.
11. As a corpus consumer, I want the retrieval protocol shipped inside the
    corpus as `AGENT.md`, so the discipline travels with the data instead of
    living in someone's prompt.
12. As a maintainer, I want retrieval logic to exist in exactly one module, so
    the CLI and the MCP server can never drift apart in behaviour.
13. As a maintainer, I want adding a synonym to be a YAML edit, so extending
    coverage is a data change and not a code change — consistent with the
    vendor brand lexicon.
14. As a maintainer, I want the goldens extended with natural-language and
    search-path questions that must resolve to the same verbatim answer and
    page as the existing symbol-path questions, so the new surface is proven
    against the existing objective function rather than a new one.

## Implementation Decisions

Full detail in `Reports/PHASE_5_PLAN.md`. The load-bearing ones:

- **`retrieve/` is a deep module.** `CorpusIndex` loads and caches a part
  once; `Retriever` returns typed results (`SpecHit`, `SectionHit`, `PlotHit`,
  `AnswerPack`) carrying citation, confidence, and `matched_via`. Front ends
  format, they do not query. `query.py` stays as a back-compat shim.
- **Aliases are data** (`registry/aliases.yaml`), resolved by a five-rung
  ladder (exact symbol → alias phrase → alias prefix family → name substring →
  token-overlap fuzzy) with the winning rung reported. `expect_unit`
  disambiguates ties; it never filters out a unitless record.
- **Search is a precomputed BM25 index** built at publish, not a ripgrep
  shell-out: deterministic, dependency-free, usable inside MCP without
  spawning processes. No stemming — symbols and unit strings must survive.
- **Confidence is computed at structure time** from page pinning, the
  reconstruction gate, and cell completeness; it is additive and rendered
  everywhere.
- **`ask` routing is deterministic.** Alias hit → spec; plot vocabulary →
  plots; otherwise search. No LLM inside `ask`; an LLM caller may use it.
- **Projects are explicit part lists.** No BOM or netlist parsing.
- **MCP is local stdio only**, via the official `mcp` SDK as an optional
  extra, tested in-process over the memory transport.

## Testing Decisions

- Hermetic per invariant #4: no network, no LLM, no subprocess. The MCP server
  is exercised in-process; unrecorded HTTP remains a hard error.
- Every part's golden set gains an **ask-path** question (natural language, no
  symbols) and a **search-path** question (top-1 must be the section holding
  the hand-verified answer). Both must land on the same verbatim answer and
  page as the existing symbol-path question — the new surface is proven
  against the existing objective function.
- Budget compliance is asserted **numerically** over the whole golden set, not
  spot-checked.
- Truncation notices are asserted on a deliberately over-budget read.
- Alias hit rate over the six built corpora is measured and recorded in the
  phase report, so coverage is a number rather than a claim.

## Out of Scope

- HTTP/remote MCP transport, auth, multi-tenancy.
- BOM CSV import and EDA netlist integration.
- LLM query routing or embedding/semantic search — BM25 plus aliases first;
  the report records the miss rate that would justify revisiting.
- All new extraction (pins, registers, cards, plot axes) — Phase 6.

## Further Notes

- `.env` is tracked in git and contains an `API_KEY` line. Never committed;
  `git rm --cached .env` + a `.gitignore` entry clears it. Unrelated to this
  work, but it should be fixed before the next commit.
- Ticket 06 (projects) is independent of 02–05 and can run in parallel;
  01→05 is a chain, and 07 is the join.
