---
title: Local GUI — chat with the corpus, verify in the PDF
labels: [design-agreed]
---

## Problem Statement

The corpus is a filesystem driven by a CLI. Every answer is citation-verified and every citation resolves to a printed page, but reading that page means leaving the tool, opening the PDF by hand, and scrolling — so the verification the pipeline works hardest to guarantee is the step a user is most likely to skip. There is also no way to work a whole shelf: `dsa batch` builds a directory of datasheets, but a chip's register map, errata, and application notes each become their own part, so a question whose answer lives in the register map and whose context lives in the datasheet cannot be asked at all. Nothing renders a PDF, nothing streams a conversation, and application notes that cover a family have no honest home.

## Solution

A local web application, launched as `dsa serve`, with an LLM chat pane beside a PDF pane. The user points at a directory; every PDF in it is analyzed with live per-part progress, and each document's applicability — the set of parts it is about — is inferred from its own text and confirmed on a review screen. Questions are asked in plain language; the scope they resolve to is shown and editable. Answers carry citations, and clicking one opens the source PDF at the right page with the cited block highlighted. The application is a thin adapter over `retrieve/`, alongside the CLI and the MCP server; it adds no retrieval logic of its own.

## User Stories

### Analyze

1. As an engineer, I want to pick a directory of PDFs in the app and click Analyze, so a whole shelf becomes queryable in one action.
2. As an engineer, I want each PDF's part number inferred from the document's own title block rather than its filename, so `sbas123e.pdf` becomes `AFE7950` and not `SBAS123E`.
3. As an engineer, I want each document's applicability inferred — named part numbers, a family prefix, or all parts — so an application note covering `AFE79xx` is not forced to pick one owner.
4. As an engineer, I want a review screen showing every inferred part number and applicability before the build runs, so a wrong inference is caught in one glance rather than discovered in a wrong answer.
5. As an engineer, I want a document whose applicability cannot be determined to default to all parts, so an unclassifiable file degrades to today's behaviour rather than to a wrong owner.
6. As an engineer, I want analysis to run in the background with live per-part status, so I can leave a 40-PDF directory running and watch it progress.
7. As an engineer, I want to start asking questions about parts that have finished while others are still building, so a long batch does not block all work.
8. As an engineer, I want one failed PDF to mark its own job failed and leave the rest running, so a bad file does not cost me the batch.
9. As an engineer, I want re-analyzing an unchanged directory to be near-free, so keeping the shelf current is cheap.

### Organize

10. As an engineer, I want to correct a document's applicability by hand, so inference is a proposal and never the last word.
11. As an engineer, I want to attach my own labels to a document (`reviewed`, `thermal`, `jesd204`), so I can organize the shelf the way I actually think about it.
12. As an engineer, I want labels to be mine alone and never overwritten by a rebuild, so re-analyzing never destroys my annotations.
13. As an engineer, I want a document that applies to a part I have not built to bring that part into existence with the document as its whole corpus, so a fact correctly extracted is never discarded.

### Ask

14. As an engineer, I want to type a question without first choosing a part, so asking is as cheap as thinking of the question.
15. As an engineer, I want the scope the question resolved to shown on the answer and editable, so I always know what the answer was drawn from.
16. As an engineer, I want an ambiguous question to ask me which part I meant rather than guessing, so no answer is silently drawn from the wrong device.
17. As an engineer, I want answers streamed token by token, so a slow lookup shows progress instead of a blank pane.
18. As an engineer, I want each answer's confidence and match reason visible, so a low-confidence spec tells me to check the page before I trust it.

### Verify

19. As an engineer, I want clicking a citation to open that PDF at that page in the pane beside the answer, so verification costs one click.
20. As an engineer, I want the cited block highlighted on the page, so I am reading the row the answer came from and not hunting a 200-page document.
21. As an engineer, I want a citation whose block cannot be located to open the page with no highlight, so I am never shown a box around the wrong row.

### Keep

22. As an engineer, I want conversations saved and reloadable, so a week-old question and the pages I verified are still there.
23. As an engineer, I want to export an answer with its citations, so a verified fact can go straight into a design review.

## Implementation Decisions

- **Shape and delivery.** A local web application: FastAPI backend plus a React + Vite + TypeScript frontend, served as one process from a new `dsa serve` subcommand (no `--mcp` flag) in a new package under `src/datasheet_analyzer/`. Built frontend assets are served as static files by the same app. Single user, local machine, no authentication; the API key is read from the existing `ANTHROPIC_API_KEY` setting.
- **Seam.** The application is built on `feat/phase5-retrieval` and consumes `retrieve.Retriever` / `retrieve.ProjectRetriever` **in process**. It is the third thin adapter beside `cli.py` and `mcp_server/`, and holds no retrieval logic, no citation formatting, and no JSON shapes of its own — those come from `retrieve/` and the hits' own `as_dict()`. It does not shell out to the MCP server: MCP responses are capped at `DSA_MCP_MAX_TOKENS` and truncated for a model consumer, and the UI needs full result sets.
- **Agent.** An agentic tool loop over the Anthropic SDK's Tool Runner, on a new `DSA_CHAT_MODEL` setting defaulting to `claude-opus-5`; `DSA_MODEL` (`claude-haiku-4-5`) continues to serve index writing. The tool surface mirrors the nine MCP tools. Tool bodies are the GUI's own — the MCP tools are format-only wrappers whose token capping is wrong for this consumer — but `_scope` is extracted to one shared module rather than copied a third time.
- **Applicability.** `SourceDocument` gains an applicability: named part numbers, a family prefix, or all parts. It replaces single-part containment; a Part is the view of documents that apply to it. Inferred at build time from document text — part-number sweep plus a classification pass — and always confirmed on the review screen before the build. Unresolvable applicability is all parts. Architectural record: `docs/adr/0005-documents-apply-to-parts.md`.
- **Library store.** The SourceDocument record, its applicability, and its labels live once in a library store keyed by `content_hash`. Per-part `sources.json` is regenerated at publish time as a derived, read-only view so `dsa status` and existing readers are unaffected.
- **Publish once, reference many.** A document that applies to several parts is extracted once (the extraction cache is already keyed `(content_hash, backend)`) and **published** once into a shared store; each part's manifest references it. `PlotRecord.file` becomes library-relative, which bumps `PLOTS_SCHEMA_VERSION`.
- **Labels vs tags.** User-applied text is a **Label**; the existing machine-derived `PlotRecord.tags` stay **Tags**. Both are defined in `CONTEXT.md`. Labels are never written by a build and never overwritten by one.
- **Unbuilt parts.** Applicability naming an unbuilt part creates that part, with a corpus of whatever applies to it. This matches `discover_parts()` already listing half-built parts, and the resulting stub has a real manifest, so `add_parts()`' project precondition still holds.
- **Scope.** Auto-resolved to exactly one Part or Project by matching the question against built part and project names, displayed as an editable control on the answer, with ambiguity raising a question. No "all parts" scope is added. Architectural record: `docs/adr/0006-auto-resolved-scope.md`.
- **Highlighting.** Geometry is derived on demand, not persisted: a `GET /locate` endpoint takes a citation, opens the PDF with PyMuPDF, and searches for the record's own text (`SpecRecord.row_verbatim`, a table caption, a paragraph opening) on the cited page, reusing the distinctive-needle approach in `pagemap.pin_table_pages()`. Resolution happens lazily when the user clicks a citation, not in the agent loop and not in the browser. `pdf_layout.py` and `output_version` are untouched, and the extraction cache stays valid. A miss opens the page with no highlight.
- **Progress and streaming.** Analysis runs as background jobs, one per part, with per-stage status. Both job progress and chat tokens are delivered over SSE — each is one-way server-to-client, so no WebSocket is required.
- **Staleness.** Nothing new: `CorpusIndex`'s cache key is `(part_dir, manifest.json mtime_ns, size, PIPELINE_VERSION)`, so re-analysis invalidates the index by rewriting the manifest.
- **Sessions.** Conversations, their citations, and their resolved scope persist to disk and are reloadable, with an export of an answer plus citations to markdown.

## Testing Decisions

- **What makes a good test**: external behavior of the backend seam only — given a temp `parts_dir` and a synthetic corpus, assert applicability inference results, scope resolution outcomes, the shape of `/locate` responses (including the honest miss), job status transitions, and library-store round-trips. No assertions on React internals or on PyMuPDF's search algorithm.
- **Hermeticity** is unchanged and non-negotiable: synthetic PDFs built in-test via fitz, a fake LLM client for the classification pass and the chat loop, `Settings(parts_dir=tmp, cache_dir=tmp)` with the `reset_settings_cache` hook. No network, no live model, no browser.
- **Prior art**: `synthetic_env` in the pipeline tests is the fixture pattern to extend; `TestMcpServerIsFormatOnly` is the pattern for asserting that this adapter, too, holds no retrieval logic.
- **New golden material**: exported sessions with confirmed citations are the intended source of new `tests/fixtures/golden_qa_<PART>.yaml` entries, per AGENTS.md invariant 5.

## Out of Scope

- Remote hosting, multi-user access, and authentication of any kind.
- Persisting bounding boxes in `RawDocument`, or any change to `pdf_layout.py` / `output_version`.
- An "all parts" retrieval scope (ADR 0006).
- Part families and a document registry — both are proposed in `.scratch/reach-and-trust/` and unimplemented; applicability's family prefix is not a substitute for either.
- Embedding search, LLM query routing inside `retrieve/`, and any model call in a derivation path.
- Editing a corpus, a spec value, or a document from the UI. Labels are the only user-writable data.
- Curve digitization from plots — explicitly rejected in the roadmap and unchanged here.

## Further Notes

- Domain vocabulary: Part, SourceDocument, Library, Applicability, Tag, Label per `CONTEXT.md`.
- Architectural records: `docs/adr/0005-documents-apply-to-parts.md`, `docs/adr/0006-auto-resolved-scope.md`.
- Depends on `feat/phase5-retrieval` landing: `retrieve/`, `projects/`, `publish/search_index.py`, and the nine-tool MCP server all live there.
- Two pre-existing debts this work touches: `_scope` is duplicated between `cli.py` and `server.py`, and `SectionHit` is the one result type with no `as_dict()`.
- Unrelated hygiene, but adjacent: `.env` is currently tracked in git and should be `git rm --cached`'d before an application reads a key from it.
