# 04 — Publish once, reference many

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/publish/writer.py`
- `src/datasheet_analyzer/publish/plots.py`
- `tests/unit/test_publish_shared.py`

**What to build:** A document that applies to many parts is published **once**.
Extraction is already deduplicated — the cache is keyed
`(content_hash, backend)` — but publish output is not, and figures dominate it:
AD9081 alone emits 100 image files. A vendor-wide layout note applying to 40
parts currently means 40 copies of every figure it contains.

`write_corpus(...)` gains a keyword-only `shared_docs_dir: Path | None = None`
(signature frozen in `00-contracts.md`). When set, each document's artifacts —
`sections/`, `tables/`, `figures/`, `specs.json`, `plots.json`,
`search_index.json` — are written once under
`<shared_docs_dir>/<doc_type>-<hash8>/`, and each part's manifest references
that location instead of holding a copy. When `None`, behaviour is exactly
today's: artifacts under `parts/<PART>/docs/<doc_type>-<hash8>/`.

`PlotRecord.file` becomes **library-relative** rather than part-relative. That
is the `PLOTS_SCHEMA_VERSION` bump to `"2"` which ticket 00 has already made;
this ticket makes the paths match it. `_plot_file_path()` and
`_set_record_file()` are the two functions to change. Everything that reads
`PlotRecord.file` — `retrieve/`, the MCP `get_figure` tool, `dsa plots` —
resolves it against the library root, so a `plots.json` written by the old
code and one written by the new code must be distinguishable by
`schema_version` and never silently mixed.

Writing must be idempotent and safe under concurrency: two parts published in
parallel may reference the same shared document, so a second write of an
identical artifact is a no-op rather than a truncate-and-rewrite. Reuse the
atomic temp-then-`.replace()` pattern already in `pipeline.py`.

- [ ] With `shared_docs_dir=None`, output is byte-identical to the current layout (assert against a golden directory listing)
- [ ] With `shared_docs_dir` set, one document referenced by three parts produces exactly one copy of each artifact
- [ ] Each of those three parts' manifests references the shared location and resolves to a real file on disk
- [ ] `PlotRecord.file` is library-relative and `PlotSet.schema_version == "2"`
- [ ] A `plots.json` at `schema_version == "1"` is detected and rejected with a clear message rather than resolved against the wrong root
- [ ] Publishing the same document twice is a no-op the second time — mtimes of its artifacts are unchanged
- [ ] Two concurrent publishes of the same shared document leave exactly one intact copy and no `.tmp` files
- [ ] `CorpusStats` counters are unchanged in meaning: a part's `n_plot_files` counts the figures it references, whether shared or not
- [ ] A figure file removed from the shared store is reported honestly by the manifest reader rather than crashing
- [ ] `render_figure_regions` and `fetch_plot_images` still write to the same place their records point at
- [ ] Tests use `Settings(parts_dir=tmp, library_dir=tmp)`; synthetic PDFs via `fitz`; no network
