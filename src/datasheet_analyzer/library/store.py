"""`LibraryStore` — the one place a `LibraryDocument` lives (ticket 01).

The Library is the authoritative document inventory, keyed by `content_hash`
(the sha256 of the PDF's bytes, already a `SourceDocument`'s identity). A
part's `sources.json` is a *derived* view of it, regenerated at publish time.

Storage is one JSON file per document, `<library_dir>/<content_hash>.json`,
and nothing else — deliberately no central index file, because a single file
every writer must touch is a write-contention point and the directory listing
already enumerates the library.

Three rules the rest of the system depends on:

- **Labels are never written by a build.** `put()` preserves whatever labels
  are already stored for a hash; `set_labels()` is the only path that changes
  them. A rebuild must not be able to destroy user annotation.
- **A bad file is skipped, never fatal.** Malformed JSON, or a
  `schema_version` this build does not know, is logged and skipped so `all()`
  still returns the readable rest of the shelf.
- **Writes are atomic and Windows-safe.** `<name>.<pid>.<thread>.tmp` then
  `os.replace()`, retrying `PermissionError` — the same helper shape as
  `pipeline.py::_store_cached_raw`, so parallel analyze jobs racing on one
  path can never leave a torn file behind.

Reads are cached in memory keyed by `(path, mtime_ns, size)`, mirroring
`retrieve/index.py`; `clear_library_cache()` is the test hook the way
`clear_index_cache()` is.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from datasheet_analyzer.config import LIBRARY_SCHEMA_VERSION, Settings, get_settings
from datasheet_analyzer.library.categories import (
    CATEGORIES_FILE,
    PARTS_FILE,
    CategoryStore,
)
from datasheet_analyzer.models import Applicability, LibraryDocument, RevisionState

log = logging.getLogger(__name__)

#: Files in `library_dir` that are the store's own, not documents.
STORE_METADATA_FILES = frozenset({CATEGORIES_FILE, PARTS_FILE})

__all__ = ["LibraryStore", "clear_library_cache"]

# Read cache: `(resolved path, mtime_ns, size) -> LibraryDocument`. The key is
# the file's identity, so a rewritten document is a cache *miss* rather than a
# stale hit — the same discipline `CorpusIndex._cache_key` carries.
_CACHE: dict[tuple, LibraryDocument] = {}

# A content hash is a filename. Anything that is not a plain token could walk
# out of `library_dir`, so it is refused rather than joined onto a path.
_SAFE_HASH = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def clear_library_cache() -> None:
    """Test hook: drop the in-memory read cache (mirrors `clear_index_cache`)."""
    _CACHE.clear()


class LibraryStore:
    """The authoritative document inventory, keyed by `content_hash`."""

    def __init__(self, library_dir: Path | str) -> None:
        """Bind the store to a directory. Nothing is read or created here.

        Importing or constructing a store has no filesystem side effects, the
        same rule `config.py` follows: directories are made by the code that
        writes to them.
        """
        self.library_dir = Path(library_dir)

    @classmethod
    def for_settings(cls, settings: Settings | None = None) -> LibraryStore:
        """The store for `settings.library_dir` (cached settings by default)."""
        return cls((settings or get_settings()).library_dir)

    # --- reads ----------------------------------------------------------------

    def get(self, content_hash: str) -> LibraryDocument | None:
        """The document with this hash, or `None` — never an exception."""
        path = self._path_for(content_hash)
        if path is None:
            return None
        return _read_document(path)

    def all(self) -> list[LibraryDocument]:
        """Every readable document, sorted deterministically by content hash.

        Unreadable files are skipped with a warning: one truncated record must
        not cost the caller the rest of the shelf.
        """
        try:
            entries = sorted(
                path
                for path in self.library_dir.glob("*.json")
                # The taxonomy and the per-part records live in this directory
                # too, and they are not documents. Excluded by name rather than
                # by failing to parse: a document store that warns about its own
                # metadata on every read has taught its user to ignore warnings.
                if path.name not in STORE_METADATA_FILES
            )
        except OSError:  # library_dir missing or unreadable: an empty shelf
            return []
        docs = [doc for doc in (_read_document(path) for path in entries) if doc is not None]
        docs.sort(key=lambda doc: doc.content_hash)
        return docs

    def for_part(self, part_number: str) -> list[LibraryDocument]:
        """Every document whose `applicability.covers(part_number)` is True.

        This is what makes a Part a *view*: `kind="all"` documents and family
        matches are included, and a part no document covers returns `[]`.
        """
        # A `category` applicability needs to know which category the part is
        # filed in, and `Applicability.covers` deliberately will not look that
        # up itself — it is embedded in a persisted model and must stay a pure
        # function. Resolved once here rather than per document.
        category = CategoryStore(self.library_dir).category_of(part_number)
        return [doc for doc in self.all() if doc.covers(part_number, part_category=category)]

    # --- writes ---------------------------------------------------------------

    def put(self, doc: LibraryDocument) -> None:
        """Write the document, **preserving any labels already stored.**

        A build calls this every time it sees a PDF. Labels are user
        annotation and the revision state is what a network check found, so
        whatever is on disk wins over whatever the caller happened to carry;
        `set_labels()` and `set_revision_state()` are the only paths that
        change them. Without the second rule a rebuild would silently reset a
        `stale` corpus to `unknown` - a warning quietly cleared by the very
        act that did nothing to address it.
        """
        path = self._require_path(doc.content_hash)
        stored = _read_document(path)
        labels = list(stored.labels) if stored is not None else list(doc.labels)
        revision_state = stored.revision_state if stored is not None else doc.revision_state
        self._write(
            path, doc.model_copy(update={"labels": labels, "revision_state": revision_state})
        )

    def set_applicability(self, content_hash: str, applicability: Applicability) -> LibraryDocument:
        """Replace applicability; leave source and labels untouched."""
        return self._update(content_hash, {"applicability": applicability})

    def set_labels(self, content_hash: str, labels: list[str]) -> LibraryDocument:
        """Replace the label list; leave source and applicability untouched."""
        return self._update(content_hash, {"labels": list(labels)})

    def set_revision_state(self, content_hash: str, state: RevisionState) -> LibraryDocument:
        """Replace what the last revision check found; leave everything else.

        The only writer is `dsa check-revisions` (phase 7, ticket 02). It is a
        separate entry point from `put()` for the reason `set_labels` is: a
        build calls `put()` on every PDF it sees, and a freshness reading is
        not something a build may compute or overwrite. `put()` therefore
        preserves whatever state is stored, exactly as it preserves labels.
        """
        return self._update(content_hash, {"revision_state": state})

    # --- internals ------------------------------------------------------------

    def _update(self, content_hash: str, changes: dict) -> LibraryDocument:
        """Read-modify-write one document. `KeyError` when it is not stored.

        The signature returns a `LibraryDocument`, not an optional, so an
        unknown hash cannot be a silent no-op; the API layer turns this into
        a 404.
        """
        doc = self.get(content_hash)
        if doc is None:
            raise KeyError(f"no library document with content_hash {content_hash!r}")
        updated = doc.model_copy(update=changes)
        self._write(self._require_path(content_hash), updated)
        return updated

    def _write(self, path: Path, doc: LibraryDocument) -> None:
        stamped = doc.model_copy(update={"schema_version": LIBRARY_SCHEMA_VERSION})
        _atomic_write_text(path, stamped.model_dump_json(indent=2))
        # Drop any cached read of this path: a coarse filesystem clock can
        # hand two writes the same mtime, and a stale hit would outlive the
        # write that replaced it.
        _invalidate(path)

    def _path_for(self, content_hash: str) -> Path | None:
        if not _SAFE_HASH.match(content_hash or ""):
            return None
        return self.library_dir / f"{content_hash}.json"

    def _require_path(self, content_hash: str) -> Path:
        path = self._path_for(content_hash)
        if path is None:
            raise ValueError(f"not a usable content_hash: {content_hash!r}")
        return path


def _cache_key(path: Path) -> tuple | None:
    """Cache identity, or None for a file that cannot be stat'ed."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path.resolve()), st.st_mtime_ns, st.st_size, LIBRARY_SCHEMA_VERSION)


def _invalidate(path: Path) -> None:
    """Forget every cached read of `path`, whatever its mtime/size was."""
    try:
        target = str(path.resolve())
    except OSError:  # pragma: no cover - resolve() is non-strict
        return
    for key in [key for key in _CACHE if key[0] == target]:
        del _CACHE[key]


def _read_document(path: Path) -> LibraryDocument | None:
    """One library file, or None when it is absent, malformed or unknown-version."""
    key = _cache_key(path)
    if key is None:
        return None
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("skipping unreadable library document %s: %s", path, exc)
        return None
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if version != LIBRARY_SCHEMA_VERSION:
        log.warning(
            "skipping library document %s: unknown schema_version %r (expected %r)",
            path,
            version,
            LIBRARY_SCHEMA_VERSION,
        )
        return None
    try:
        doc = LibraryDocument.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - any validation failure is a skip
        log.warning("skipping malformed library document %s: %s", path, exc)
        return None
    _CACHE[key] = doc
    return doc


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically: unique temp file + rename.

    Copied in shape from ``pipeline.py::_atomic_write_text``: the temp name
    carries pid and thread id so concurrent writers never share it (Windows
    locks open files), and the rename is retried briefly on
    ``PermissionError`` because the destination is locked while another
    thread has it open for reading. A failed write removes its temp file and
    leaves the destination untouched, so no ``.tmp`` outlives a successful
    ``put()``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows: destination briefly locked
                time.sleep(0.01 * (attempt + 1))
        else:
            os.replace(tmp, path)  # last try — surface the error if still contended
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
