# 01 — Library store and labels

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/library/store.py`
- `tests/unit/test_library_store.py`

**What to build:** The one place a `LibraryDocument` lives. Keyed by
`content_hash` — the sha256 of the PDF's bytes, which is already a
`SourceDocument`'s identity — it holds the document's `SourceDocument` record,
its `Applicability`, and its user `labels`. This is the authoritative
inventory; per-part `sources.json` becomes a derived view written by ticket 03.

Storage is one JSON file per document under `settings.library_dir`, named
`<content_hash>.json`, plus nothing else — no central index file, because a
central file is a write-contention point and the directory listing already
enumerates the library. Reads are cached in memory keyed by
`(library_dir, file mtime_ns, size)`, mirroring `retrieve/index.py`'s
`_cache_key` pattern; expose a `clear_library_cache()` test hook the way
`clear_index_cache()` does.

Writes are atomic and Windows-safe: write `<name>.<pid>.<thread>.tmp` then
`.replace()`, retrying `PermissionError` up to 10 times. Copy the existing
helper shape in `pipeline.py::_store_cached_raw` — do not invent a new one.

Labels are **never written by a build**. `set_labels` is the only path that
changes them, and `put()` on an existing hash preserves the stored labels
rather than overwriting them with whatever the caller passed.

- [ ] `put()` then `get()` round-trips a `LibraryDocument` exactly, including applicability and labels
- [ ] `get()` on an unknown hash returns `None`, not an exception
- [ ] `all()` returns every document in the library, sorted deterministically by content hash
- [ ] `for_part("AD9081")` returns every document whose `applicability.covers("AD9081")` is True, including `kind="all"` documents and `family` matches
- [ ] `for_part()` on a part no document covers returns an empty list
- [ ] `set_labels` replaces the label list and leaves applicability and source untouched
- [ ] `set_applicability` replaces applicability and leaves labels and source untouched
- [ ] **`put()` on a hash that already has labels preserves those labels** — a rebuild cannot destroy user annotation
- [ ] Two `put()` calls for the same hash produce one file, not two
- [ ] A malformed or truncated JSON file in the library directory is skipped with a warning rather than failing `all()`
- [ ] The read cache is invalidated when a document file is rewritten (assert via mtime change, not by sleeping)
- [ ] Writes are atomic: no `.tmp` file survives a successful `put()`
- [ ] `LIBRARY_SCHEMA_VERSION` is recorded in each file and a file with an unknown version is skipped with a warning
- [ ] Tests use `Settings(library_dir=tmp)` with `reset_settings_cache`; no network, no LLM
