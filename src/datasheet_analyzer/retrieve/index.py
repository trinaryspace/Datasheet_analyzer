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
from datasheet_analyzer.models import (
    CorpusManifest,
    PlotRecord,
    PlotSet,
    SearchIndex,
    SectionFile,
    SpecRecord,
    SpecSet,
)

log = logging.getLogger(__name__)

_CACHE: dict[tuple, CorpusIndex] = {}


def clear_index_cache() -> None:
    """Test hook: drop every cached index so a rewritten corpus is re-read."""
    _CACHE.clear()


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
                search = _load_json_model(doc_dir / "search_index.json", SearchIndex)
                docs.append(
                    IndexedDoc(
                        name=doc_dir.name,
                        doc_hash=(
                            (specset.doc_hash if specset else "")
                            or (plotset.doc_hash if plotset else "")
                            or (search.doc_hash if search else "")
                        ),
                        specs=tuple(specset.records) if specset else (),
                        plots=tuple(plotset.plots) if plotset else (),
                        search=search,
                    )
                )
        return cls(
            part_dir=part_dir,
            part_number=manifest.part_number if manifest else part_dir.name,
            manifest=manifest,
            docs=tuple(docs),
            sections=tuple(manifest.sections) if manifest else (),
        )

    def doc_for_hash(self, doc_hash: str) -> IndexedDoc | None:
        """The loaded document whose spec/plot sets carry `doc_hash`."""
        for doc in self.docs:
            if doc.doc_hash and doc.doc_hash == doc_hash:
                return doc
        return None

    def section_text(self, section: SectionFile) -> str:
        """Markdown body of one section file; `""` when it cannot be read."""
        cached = self._section_text.get(section.file)
        if cached is not None:
            return cached
        path = self.part_dir / section.file
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("skipping unreadable section file %s: %s", path, exc)
            text = ""
        self._section_text[section.file] = text
        return text


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
