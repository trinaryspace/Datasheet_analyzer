# 02 — Part number and applicability inference

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/acquire/applicability.py`
- `tests/unit/test_applicability.py`

**What to build:** Given a PDF, propose the part number it is about and the set
of parts it applies to. Nothing in the repo does this today — the part number
has always been supplied by the caller (`dsa build --part`) or taken from the
filename stem, which is wrong for a file named `sbas123e.pdf` where the stem is
a document ID.

`infer(pdf_path, *, first_page_text, known_parts, client) -> DocProposal`
runs in two stages, deterministic first:

1. **Sweep.** Regex the title block for part-number shapes and family shapes.
   Two patterns carry the work: a part token (letters + digits, length 4–12,
   at least two digits, e.g. `AD9081`, `AFE7950`, `LM741`) and a family token
   (the same with a trailing `xx`/`x` wildcard, e.g. `AFE79xx`). Rank hits by
   position — a datasheet names its part in the first lines — and by whether
   the token also appears in `known_parts`.
2. **Classify.** If the sweep is unambiguous (exactly one part token, no family
   token), return it with `evidence` naming the matched line and stop — **no
   model call**. Otherwise ask `client` for a single structured judgement:
   which part numbers does this document cover, or `all` if generic. When
   `client` is `None`, or the call fails, fall back to the sweep's best guess,
   and to `Applicability(kind="all")` when the sweep found nothing.

`evidence` is never blank. It records how the decision was reached — the
matched line and its page, or `llm:<model>`, or `fallback: no part token
found` — the same discipline as `SourceDocument.vendor_evidence`, which is
pinned once at acquire with recorded evidence and never silently re-guessed.

This is a *proposal*. Ticket 08 shows it on a review screen and ticket 03 only
persists what came back confirmed. Inference never writes.

- [ ] A first page naming exactly one part returns `kind="parts"` with that part and no model call (assert the fake client recorded zero calls)
- [ ] A first page naming `AFE79xx` returns `kind="family"` with `family="AFE79xx"`
- [ ] A document naming several parts routes to the classifier and returns every part it reports
- [ ] A generic document (no part token anywhere) returns `kind="all"` without a model call
- [ ] `client=None` never raises; every path falls back deterministically
- [ ] A classifier that raises falls back to the sweep result, and `evidence` says so
- [ ] A classifier returning malformed JSON is treated as a failure, not parsed loosely
- [ ] `evidence` is non-empty on every returned proposal, including fallbacks
- [ ] A part token appearing in `known_parts` outranks one that does not
- [ ] The filename stem is used only when the sweep finds nothing, and `evidence` records that it was the fallback
- [ ] `sbas123e.pdf` whose title block reads "AFE7950" proposes `AFE7950`, not `SBAS123E`
- [ ] Tests build synthetic PDFs with `fitz` and use a fake `LLMClient`; no network, no live model
