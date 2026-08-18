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

from datasheet_analyzer.acquire.inventory import SOURCES_FILE, load_inventory
from datasheet_analyzer.config import PIPELINE_VERSION
from datasheet_analyzer.models import (
    CorpusManifest,
    PinRecord,
    PinSet,
    PlotRecord,
    PlotSet,
    RegisterRecord,
    RegisterSet,
    SearchIndex,
    SectionFile,
    SourceDocument,
    SpecRecord,
    SpecSet,
)
from datasheet_analyzer.staleness import CorpusStaleness, corpus_staleness

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
    # `pins.json` (phase 6, ticket 04). Empty both for a document that prints
    # no pin table and for one whose pin table was rejected — the publisher
    # writes no file for either, and the rejection reason lives in the
    # manifest's extraction stats.
    pins: tuple[PinRecord, ...] = ()
    # The pin count the document's package descriptor stated, when it stated
    # one that every descriptor agreed on. Carried so a caller can report the
    # cross-check without re-parsing the datasheet.
    stated_pin_count: int | None = None
    # `registers.json` (phase 6, ticket 05). Empty both for a document that
    # prints no register summary and for one whose summary was rejected — the
    # publisher writes no file for either, and the rejection reason lives in
    # the manifest's extraction stats.
    registers: tuple[RegisterRecord, ...] = ()
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
    # The acquire-time inventory (`sources.json`), read here because it is the
    # *live* record: `dsa check-revisions` writes staleness onto it after the
    # build, and the manifest's copy of a `SourceDocument` is a snapshot of
    # what was true when the corpus was published. A retrieval surface that
    # read the snapshot would keep reporting `unknown` after a check had
    # already found the corpus stale (phase 7, ticket 02).
    sources: tuple[SourceDocument, ...] = ()
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
        docs: list[IndexedDoc] = []
        docs_dir = part_dir / "docs"
        if docs_dir.is_dir():
            # sorted(): document order must not depend on filesystem order, or
            # the same query would rank differently on two machines.
            for doc_dir in sorted(d for d in docs_dir.iterdir() if d.is_dir()):
                specset = _load_json_model(doc_dir / "specs.json", SpecSet)
                plotset = _load_json_model(doc_dir / "plots.json", PlotSet)
                pinset = _load_json_model(doc_dir / "pins.json", PinSet)
                registerset = _load_json_model(doc_dir / "registers.json", RegisterSet)
                search = _load_json_model(doc_dir / "search_index.json", SearchIndex)
                docs.append(
                    IndexedDoc(
                        name=doc_dir.name,
                        doc_hash=(
                            (specset.doc_hash if specset else "")
                            or (plotset.doc_hash if plotset else "")
                            or (pinset.doc_hash if pinset else "")
                            or (registerset.doc_hash if registerset else "")
                            or (search.doc_hash if search else "")
                        ),
                        specs=tuple(specset.records) if specset else (),
                        plots=tuple(plotset.plots) if plotset else (),
                        pins=tuple(pinset.pins) if pinset else (),
                        stated_pin_count=pinset.stated_count if pinset else None,
                        registers=tuple(registerset.registers) if registerset else (),
                        search=search,
                    )
                )
        return cls(
            part_dir=part_dir,
            part_number=manifest.part_number if manifest else part_dir.name,
            manifest=manifest,
            docs=tuple(docs),
            sections=tuple(manifest.sections) if manifest else (),
            sources=tuple(load_inventory(part_dir)),
        )

    @property
    def staleness(self) -> CorpusStaleness:
        """This corpus's freshness reading — `unknown` until somebody checks.

        Read off the inventory by `staleness.corpus_staleness`, so the CLI, the
        MCP server and the answer pack all report the same reading of the same
        record instead of each deciding what "current" means.
        """
        return corpus_staleness(self.sources, self.part_number or self.part_dir.name)

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
        path = self.part_dir / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("skipping unreadable %s %s: %s", kind, path, exc)
            text = ""
        self._section_text[rel] = text
        return text

    def corpus_path(self, rel: str) -> Path | None:
        """Absolute path of a corpus-relative file, or None when it escapes.

        The one place a caller-supplied path becomes a filesystem path. A
        corpus file reference (`docs/<doc>/figures/4.12.1-f001.png`) is data
        the corpus itself produced; anything absolute, drive-qualified, null-
        byte-bearing or containing `..` is refused outright rather than
        normalized, and the resolved target is checked back against the part
        directory so a symlink cannot escape either. Refusing beats rewriting:
        silently resolving `../../secrets` to *something* would hand a caller
        bytes from outside the part it asked about.

        Existence is deliberately not checked here — "outside this part" and
        "not in this corpus" are different findings and a caller should be
        able to report them differently.
        """
        rel = (rel or "").strip().replace("\\", "/")
        if not rel or "\0" in rel:
            return None
        candidate = Path(rel)
        if rel.startswith("/") or candidate.is_absolute() or candidate.drive:
            return None
        if any(part == ".." for part in candidate.parts):
            return None
        root = self.part_dir.resolve()
        target = (root / candidate).resolve()
        if target != root and root not in target.parents:
            return None
        return target


def _stamp(path: Path) -> tuple:
    """`(mtime_ns, size)` of a file, or `(0, 0)` when it is not there."""
    try:
        st = path.stat()
    except OSError:
        return (0, 0)
    return (st.st_mtime_ns, st.st_size)


def _cache_key(part_dir: Path) -> tuple | None:
    """Cache identity, or None for a part that has no manifest to key on.

    `sources.json` is part of the identity as well as `manifest.json` (phase 7,
    ticket 02): `dsa check-revisions` rewrites the inventory *without*
    rebuilding, so a key that watched only the manifest would keep serving a
    cached index whose staleness reading predates the check that just ran.
    """
    manifest = _stamp(part_dir / "manifest.json")
    if manifest == (0, 0):
        return None
    return (
        str(part_dir.resolve()),
        manifest,
        _stamp(part_dir / SOURCES_FILE),
        PIPELINE_VERSION,
    )


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
