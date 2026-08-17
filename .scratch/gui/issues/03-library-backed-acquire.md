# 03 — Library-backed acquire, derived sources.json

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/acquire/inventory.py`
- `src/datasheet_analyzer/pipeline.py`
- `tests/unit/test_inventory_library.py`

**What to build:** Move the authoritative inventory into the library store and
make `parts/<PART>/sources.json` a derived, read-only view. A build for part
`P` no longer reads a per-part inventory to find its documents — it asks the
library which documents apply to `P`.

Code against ticket 01's `LibraryStore` and ticket 04's extended
`write_corpus` signature; both are frozen in `00-contracts.md`. Construct a
fake `LibraryStore` in your tests rather than importing ticket 01's
implementation, so this ticket is verifiable before 01 lands.

Changes:

- `register_source(...)` continues to build a `SourceDocument` unchanged. New:
  `register_into_library(pdf, *, applicability, doc_type, vendor, store)`
  wraps it in a `LibraryDocument` and `put()`s it.
- `load_inventory(part_dir)` keeps its signature for back-compat but is now
  fed by `store.for_part(part_number)`.
- `save_inventory(...)` writes `sources.json` as before. It is now a
  **derived** artifact regenerated at publish time; add a
  `"generated": true` marker and a header comment field so a reader knows not
  to hand-edit it.
- `pipeline.build_part(...)` gains a keyword-only `store: LibraryStore | None`.
  When `None` it constructs one from settings. It resolves its document set
  through the library and passes `shared_docs_dir=settings.library_dir /
  "docs"` to `write_corpus`.
- `warn_vendor_drift` and `_backfill_vendor_evidence` keep working against the
  resolved document list. Vendor stays pinned at acquire with evidence — this
  ticket must not turn it into a runtime guess (ADR 0002).

Backward compatibility is not optional: an existing `parts/<PART>/` built by
the old code, with a `sources.json` and no library entry, must still build.
Detect that case and migrate the entries into the library on first touch,
giving each `Applicability(kind="parts", parts=[part_number], evidence="migrated from sources.json")`.

- [ ] A build for a part resolves its documents from the library, not from `sources.json`
- [ ] A document with `kind="all"` applicability is included in every part's build
- [ ] A document with `family="AFE79xx"` is included in `AFE7950`'s build and excluded from `AD9081`'s
- [ ] `sources.json` is still written, is byte-stable across two identical builds, and carries the generated marker
- [ ] Hand-editing `sources.json` has no effect on the next build (it is derived)
- [ ] A legacy part directory with `sources.json` and no library entries builds successfully and migrates its entries, with `evidence` recording the migration
- [ ] Migration is idempotent — a second build does not duplicate library entries
- [ ] `build_part(store=...)` accepts an injected store; the default path constructs one from settings
- [ ] Vendor pinning and `vendor_evidence` behave exactly as before (assert against the existing vendor tests' expectations)
- [ ] `dsa status`, which reads `sources.json`, still reports vendor and per-document extraction stats
- [ ] The extraction cache is still hit for an unchanged PDF — this ticket must not change `content_hash` handling or force re-extraction
- [ ] Tests use a fake `LibraryStore` and `Settings(parts_dir=tmp, cache_dir=tmp, library_dir=tmp)`; no network, no LLM
