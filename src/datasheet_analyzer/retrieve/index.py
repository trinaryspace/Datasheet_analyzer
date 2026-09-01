"""`CorpusIndex` — read a built part off disk once, keep it in memory.

`query.py` used to re-`rglob` a part and re-parse every `specs.json` on every
call. That is fine for one CLI invocation and wrong for an MCP session making
dozens, so loading moves here and happens once per corpus state.

**Cache identity** is `(part dir, manifest.json mtime + size, PIPELINE_VERSION)`
— the same "keyed by identity" rule the extraction cache follows. A rebuild
rewrites `manifest.json`, so the key changes and the stale index is dropped
without anyone having to remember to invalidate it. A part with no
`manifest.json` (unbuilt, or a bare spec/plot fixture) has no identity to key
on and is therefore never cached: it is re-read every time, which is honest
rather than silently stale.

Degradation is honest throughout: an unreadable `manifest.json`, `specs.json`,
`plots.json` or `search_index.json` is warned about and skipped, never raised
— a corrupt document must not take the whole part down.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from datasheet_analyzer.config import PIPELINE_VERSION
from datasheet_analyzer.corpus_ref import (
    corpus_relative,
    is_library_ref,
    library_root_of,
    resolve_artifact_ref,
)
from datasheet_analyzer.models import (
    CorpusManifest,
    PlotRecord,
    PlotSet,
    SearchIndex,
    SectionFile,
    SpecRecord,
    SpecSet,
)
from datasheet_analyzer.staleness import CorpusStaleness

log = logging.getLogger(__name__)

#: The part's always-loadable index, at the root of its corpus directory.
INDEX_FILENAME = "INDEX.md"

_CACHE: dict[tuple, CorpusIndex] = {}


def clear_index_cache() -> None:
    """Test hook: drop every cached index so a rewritten corpus is re-read."""
    _CACHE.clear()


def discover_parts(parts_dir: Path | str) -> list[Path]:
    """Every part directory under `parts_dir`, sorted by name; `[]` when none.

    A *directory* counts as a part here, built or not: a front end listing
    parts must be able to show one that was only half-built, and
    `CorpusIndex.load` reads it honestly (no manifest, no facts) rather than
    hiding it. Sorted, because directory order must not decide what a caller
    sees first.
    """
    root = Path(parts_dir)
    if not root.is_dir():
        return []
    return sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)


@dataclass(frozen=True)
class IndexedDoc:
    """One document directory of a part corpus, fully loaded.

    `name` is the on-disk directory name (`datasheet-a1b2c3d4`) — the value
    every `Citation.doc` carries, so a citation always points back at real
    files.
    """

    name: str
    doc_hash: str = ""
    specs: tuple[SpecRecord, ...] = ()
    plots: tuple[PlotRecord, ...] = ()
    # Where this document's artifacts actually live — under the part, or once
    # in the shared store (ticket 04). `None` only for a document loaded from
    # a bare fixture directory with no manifest to place it.
    directory: Path | None = None
    # `search_index.json`, or None for a corpus built before full-text search
    # existed. None is what `Retriever.search_unavailable()` reports on, so an
    # older corpus is told to rebuild rather than silently answering nothing.
    search: SearchIndex | None = None


@dataclass(frozen=True)
class CorpusIndex:
    """A part's manifest, spec records, plot records and section entries."""

    part_dir: Path
    part_number: str = ""
    manifest: CorpusManifest | None = None
    docs: tuple[IndexedDoc, ...] = ()
    sections: tuple[SectionFile, ...] = ()
    # The shared document store this corpus references, read off the
    # manifest's own `library_root` (ticket 04's publish-once layout). `None`
    # for a corpus whose every document lives under the part.
    library_dir: Path | None = None
    # Lazily-read section markdown, keyed by corpus-relative path. Section
    # bodies are the expensive part of a corpus; nothing reads them unless a
    # caller asks.
    _section_text: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def load(cls, part_dir: Path | str) -> CorpusIndex:
        """Load a part, reusing the cached index when the corpus is unchanged."""
        part_dir = Path(part_dir)
        key = _cache_key(part_dir)
        if key is not None:
            cached = _CACHE.get(key)
            if cached is not None:
                return cached
        index = cls._read(part_dir)
        if key is not None:
            _CACHE[key] = index
        return index

    @classmethod
    def _read(cls, part_dir: Path) -> CorpusIndex:
        manifest = _load_manifest(part_dir / "manifest.json")
        library_dir = library_root_of(manifest, part_dir)
        docs: list[IndexedDoc] = []
        # sorted(): document order must not depend on filesystem order, or the
        # same query would rank differently on two machines.
        for name, doc_dir in sorted(_doc_dirs(manifest, part_dir, library_dir).items()):
            specset = _load_json_model(doc_dir / "specs.json", SpecSet)
            plotset = _load_json_model(doc_dir / "plots.json", PlotSet)
            search = _load_json_model(doc_dir / "search_index.json", SearchIndex)
            docs.append(
                IndexedDoc(
                    name=name,
                    doc_hash=(
                        (specset.doc_hash if specset else "")
                        or (plotset.doc_hash if plotset else "")
                        or (search.doc_hash if search else "")
                    ),
                    specs=tuple(specset.records) if specset else (),
                    plots=tuple(plotset.plots) if plotset else (),
                    directory=doc_dir,
                    search=search,
                )
            )
        return cls(
            part_dir=part_dir,
            library_dir=library_dir,
            part_number=manifest.part_number if manifest else part_dir.name,
            manifest=manifest,
            docs=tuple(docs),
            sections=tuple(manifest.sections) if manifest else (),
        )

    @property
    def staleness(self) -> CorpusStaleness:
        """This corpus's freshness reading - `unknown` until somebody checks.

        Read live off the Library rather than off the loaded manifest, and
        deliberately *not* cached with the rest of this index: `dsa
        check-revisions` writes its finding onto each document's Library record
        without rebuilding, so a reading taken from the published snapshot
        would keep saying `unknown` after a check had already found the corpus
        stale. `LibraryStore` caches its own reads by `(path, mtime, size)`, so
        re-reading here is cheap and correctly invalidated.
        """
        from datasheet_analyzer.staleness import load_corpus_staleness

        return load_corpus_staleness(self.part_dir)

    def doc_for_hash(self, doc_hash: str) -> IndexedDoc | None:
        """The loaded document whose spec/plot sets carry `doc_hash`."""
        for doc in self.docs:
            if doc.doc_hash and doc.doc_hash == doc_hash:
                return doc
        return None

    def section_text(self, section: SectionFile) -> str:
        """Markdown body of one section file; `""` when it cannot be read."""
        return self._text(section.file, "section file")

    def index_markdown(self) -> str:
        """`INDEX.md` — the part's always-loadable index; `""` when absent.

        Read through the same lazy cache as section bodies, so a session that
        pins a part's index into context repeatedly reads it once.
        """
        return self._text(INDEX_FILENAME, "index file")

    def _text(self, rel: str, kind: str) -> str:
        """One corpus-relative text file, lazily read then cached."""
        cached = self._section_text.get(rel)
        if cached is not None:
            return cached
        try:
            path = resolve_artifact_ref(rel, part_dir=self.part_dir, library_dir=self.library_dir)
        except ValueError as exc:
            log.warning("skipping unresolvable %s %s: %s", kind, rel, exc)
            self._section_text[rel] = ""
            return ""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("skipping unreadable %s %s: %s", kind, path, exc)
            text = ""
        self._section_text[rel] = text
        return text

    def doc_dir(self, name: str) -> Path | None:
        """Where document `name`'s artifacts live, shared store included."""
        for doc in self.docs:
            if doc.name == name and doc.directory is not None:
                return doc.directory
        return None

    def corpus_path(self, rel: str) -> Path | None:
        """Absolute path of a corpus-relative file, or None when it escapes.

        The one place a caller-supplied path becomes a filesystem path. A
        corpus file reference (`docs/<doc>/figures/4.12.1-f001.png`) is data
        the corpus itself produced; anything absolute, drive-qualified, null-
        byte-bearing or containing `..` is refused outright rather than
        normalized, and the resolved target is checked back against the root
        it belongs to so a symlink cannot escape either. Refusing beats
        rewriting: silently resolving `../../secrets` to *something* would
        hand a caller bytes from outside the part it asked about.

        **Which root.** A document published once into the shared store
        (ticket 04) is named by the same `docs/<doc>/…` string, because
        `plots.json` sits inside the document directory and therefore names
        its own root. The document's real directory is known from the
        manifest, so the reference is anchored there and the containment check
        runs against *that* root — a shared figure resolves, and a traversal
        out of it is refused exactly as it is under a part.

        Existence is deliberately not checked here — "outside this part" and
        "not in this corpus" are different findings and a caller should be
        able to report them differently.
        """
        rel = (rel or "").strip().replace("\\", "/")
        if not rel or "\0" in rel:
            return None
        shared = is_library_ref(rel)
        rel = corpus_relative(rel)
        candidate = Path(rel)
        if rel.startswith("/") or candidate.is_absolute() or candidate.drive:
            return None
        if any(part == ".." for part in candidate.parts):
            return None
        root = self._root_for(candidate, shared=shared)
        if root is None:
            return None
        root = root.resolve()
        target = (root / candidate).resolve()
        if target != root and root not in target.parents:
            return None
        return target

    def _root_for(self, candidate: Path, *, shared: bool) -> Path | None:
        """The directory `docs/<doc>/…` hangs off for this corpus."""
        if shared:
            return Path(self.library_dir) if self.library_dir else None
        parts = candidate.parts
        if len(parts) >= 2 and parts[0] == "docs":
            directory = self.doc_dir(parts[1])
            # `docs/<doc>` is the last two segments of the document's own
            # directory in both layouts, so the root is what sits above them.
            if directory is not None:
                return directory.parent.parent
        return self.part_dir


def _doc_dirs(
    manifest: CorpusManifest | None, part_dir: Path, library_dir: Path | None
) -> dict[str, Path]:
    """`<doc dir name>` -> the directory holding that document's artifacts.

    Two sources, in that order of authority:

    1. every directory under `parts/<PART>/docs/` — the historical layout, and
       still what a bare spec/plot fixture with no manifest at all looks like;
    2. every document the manifest references, which under ticket 04's
       publish-once layout resolves into the shared store instead.

    A corpus of mixed provenance (some documents shared, some published under
    the part before the shared store existed) therefore loads completely, and
    a part-local copy wins over a shared one of the same name — it is the more
    specific answer to "where is *this part's* copy".
    """
    dirs: dict[str, Path] = {}
    docs_dir = part_dir / "docs"
    if docs_dir.is_dir():
        for doc_dir in docs_dir.iterdir():
            if doc_dir.is_dir():
                dirs[doc_dir.name] = doc_dir
    if manifest is None:
        return dirs
    for section in manifest.sections:
        rel = corpus_relative(section.file)
        if "/sections/" not in rel:
            continue
        base = rel.split("/sections/", 1)[0]
        name = base.rsplit("/", 1)[-1]
        if name in dirs:
            continue
        try:
            dirs[name] = resolve_artifact_ref(
                section.file.split("/sections/", 1)[0],
                part_dir=part_dir,
                library_dir=library_dir,
            )
        except ValueError as exc:
            log.warning("skipping unresolvable document reference: %s", exc)
    return dirs


def _cache_key(part_dir: Path) -> tuple | None:
    """Cache identity, or None for a part that has no manifest to key on."""
    try:
        st = (part_dir / "manifest.json").stat()
    except OSError:
        return None
    return (str(part_dir.resolve()), st.st_mtime_ns, st.st_size, PIPELINE_VERSION)


def _load_manifest(path: Path) -> CorpusManifest | None:
    if not path.exists():
        return None
    try:
        return CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("skipping unreadable manifest.json %s: %s", path, exc)
        return None


def _load_json_model(path: Path, model: type):
    """Parse one corpus JSON artifact; warn and skip when it will not load."""
    if not path.exists():
        return None
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("skipping unreadable %s %s: %s", path.name, path, exc)
        return None
