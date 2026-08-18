"""The Library: one flat store of every registered document (ADR 0005).

A part does not own its documents — a document says which parts it applies
to, and a Part is the view of the documents that cover it. The authoritative
record of that relation lives here, keyed by `content_hash`, and
`parts/<PART>/sources.json` becomes a derived, read-only view regenerated at
publish time.

One file per document under `settings.library_dir`, and no central index:
a single index file is a write-contention point under a parallel build, and
the directory listing already enumerates the shelf.
"""

from __future__ import annotations

from datasheet_analyzer.library.store import LibraryStore, clear_library_cache

__all__ = ["LibraryStore", "clear_library_cache"]
