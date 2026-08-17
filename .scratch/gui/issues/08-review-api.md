# 08 — Scan and review endpoints

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/routers/review.py`
- `tests/unit/test_review_api.py`

**What to build:** `POST /api/analyze/scan` takes a directory and returns one
`DocProposal` per PDF — the inferred part number, the inferred applicability,
and the evidence for both — without building anything. This is what the review
screen renders so a wrong inference is caught in one glance rather than
discovered later inside a wrong answer.

Scan is read-only and must stay fast: it opens each PDF only far enough to
read the first page's text and its page count, then calls
`acquire.applicability.infer(...)` (ticket 02, signature frozen in 00). It
never extracts, never publishes, and never writes to the library.

Directory handling follows `batch.discover_jobs()`: direct children only, no
recursion, `*.pdf` case-insensitive, sorted by filename. Non-PDF files are
ignored rather than reported as errors. A missing or empty directory is a 400
with a message naming the path — a typo must never silently scan nothing.

Scanning 40 PDFs is slow enough to notice, so run the per-file inference in a
bounded pool sized by `settings.analyze_workers`, and preserve sorted order in
the response regardless of completion order.

- [ ] `POST /api/analyze/scan` returns one proposal per PDF, sorted by filename
- [ ] Each proposal carries `part_number`, `applicability`, non-empty `evidence`, and `page_count`
- [ ] Nothing is written: the library, `parts_dir` and the extraction cache are byte-identical before and after
- [ ] Subdirectories are not descended into
- [ ] Non-PDF files are ignored silently
- [ ] A missing directory returns 400 naming the path; an existing directory with no PDFs returns 400 with a distinct message
- [ ] A corrupt PDF yields a proposal marked with the failure in `evidence` rather than failing the whole scan
- [ ] Results are returned in sorted order even though inference runs concurrently
- [ ] Proposals validate against `ScanOut` in `app/contracts.py`
- [ ] An edited proposal posted to `/api/analyze/start` is used verbatim — the server does not re-infer over the user's correction
- [ ] Tests build synthetic PDFs with `fitz` and stub `infer`; no network, no live model
