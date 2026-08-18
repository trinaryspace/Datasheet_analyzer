"""Corpus writer: sections/, tables/, INDEX.md, manifest.json on disk.

Layout per part:
    parts/<PART>/
      INDEX.md
      sources.json            (written by acquire)
      manifest.json
      docs/<doc_type>-<hash8>/
        sections/*.md
        tables/*.csv
        search_index.json

## Publish once, reference many (ticket 04)

Extraction is already deduplicated — its cache is keyed
`(content_hash, backend)` — but publish output was not, and figures dominate
it: a vendor-wide layout note that applies to forty parts meant forty copies
of every figure in it. With `write_corpus(shared_docs_dir=...)` each
document's artifacts are written **once** under
`<shared_docs_dir>/<doc_type>-<hash8>/` and every part's manifest references
that one location:

    library/docs/appnote-1f2e3d4c/     <- written once
      sections/*.md  tables/*.csv  figures/**  specs.json  plots.json
      search_index.json
    parts/AD9081/manifest.json         <- references it
    parts/AD9082/manifest.json         <- and so does this one

`shared_docs_dir=None` keeps the historical per-part layout byte for byte.

**How a reference says which root it hangs off.** A shared artifact is named
in the manifest with the `@library/` prefix (`LIBRARY_REF_PREFIX`) and a
per-part one is not, so `resolve_artifact_ref()` can never join a shared path
onto a part directory. `SectionFile` carries no schema version of its own, so
the marker has to live in the string; `PlotRecord.file` deliberately does
*not* carry it, because `plots.json` sits inside the document directory and
therefore already names its own root (see `publish.plots.artifact_root`) and
`PLOTS_SCHEMA_VERSION` gates the older, part-relative form.

**A shared artifact is part-neutral.** `specs.json`, `plots.json` and
`search_index.json` are written with `part_number == ""` when shared: the
document is not owned by one part, and stamping the first part to publish it
would make the bytes depend on publish order and defeat both idempotence and
the concurrent-writer guarantee. Readers already take the part identity from
`manifest.part_number`, never from these files.

**Writes are idempotent and concurrency-safe.** Two parts publishing the same
shared document in parallel is expected, so every artifact is written
temp-then-`os.replace()` (the pattern `pipeline._atomic_write_text` uses) and
is skipped entirely when the bytes on disk already match. A second publish of
an unchanged document touches nothing — its artifacts keep their mtimes.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.config import PLOTS_SCHEMA_VERSION, SPECS_SCHEMA_VERSION
from datasheet_analyzer.corpus_ref import (
    LIBRARY_REF_PREFIX,
    is_library_ref,
    library_ref,
    library_root_of,
    library_root_ref,
    resolve_artifact_ref,
)
from datasheet_analyzer.models import (
    CorpusManifest,
    CorpusStats,
    ExtractionStats,
    PlotRecord,
    PlotSet,
    RawDocument,
    SectionFile,
    SourceDocument,
    SpecRecord,
    SpecSet,
)
from datasheet_analyzer.protocol import build_part_agent_markdown, write_agent_doc
from datasheet_analyzer.publish.plots import (
    StalePlotsSchemaError,
    load_plotset,
    resolve_plot_file,
)
from datasheet_analyzer.publish.search_index import INDEX_FILENAME, build_search_index
from datasheet_analyzer.publish.search_index import dump_json as dump_search_index
from datasheet_analyzer.structure.confidence import mix as confidence_mix
from datasheet_analyzer.structure.corpus import SectionPlan
from datasheet_analyzer.tokens import count_tokens

log = logging.getLogger(__name__)

# `LIBRARY_REF_PREFIX`, `is_library_ref()`, `library_ref()` and
# `resolve_artifact_ref()` are re-exported from `datasheet_analyzer.corpus_ref`
# (integration, ticket 22). The rule for which root a reference hangs off is
# needed by `retrieve/` as well as by this writer, and neither package may
# import the other; the marker therefore lives in one dependency-free module
# and both sides read it from there. These names stay importable from
# `publish.writer` because that is where callers already reach for them.
__all__ = [
    "LIBRARY_REF_PREFIX",
    "ArtifactRef",
    "doc_dir_name",
    "doc_dir_name_for_source",
    "document_dirs",
    "is_library_ref",
    "library_ref",
    "library_root_of",
    "library_root_ref",
    "manifest_artifacts",
    "missing_artifacts",
    "plots_current",
    "read_manifest",
    "resolve_artifact_ref",
    "specs_current",
    "write_corpus",
]


def doc_dir_name_for_source(source: SourceDocument) -> str:
    """Corpus directory name of one source document (`datasheet-a1b2c3d4`).

    Takes the `SourceDocument` rather than the `RawDocument` so a reader that
    only has a manifest — the batch skip gate, say — can name the same
    directory the publisher wrote, without re-extracting.
    """
    return f"{source.doc_type.value}-{source.content_hash[:8]}"


def doc_dir_name(raw: RawDocument) -> str:
    return doc_dir_name_for_source(raw.source)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically: unique temp file + rename.

    The same contract as `pipeline._atomic_write_text`, and for the same
    reason one level up: two parts may publish the same shared document at
    the same moment, so the visible path must flip whole or not at all, and a
    failed write must leave neither a partial file nor a stray `.tmp`. The
    rename is retried briefly on `PermissionError` because Windows locks a
    destination another thread has open for reading.

    Text mode with the platform's default newline translation is deliberate:
    it is what the historical `Path.write_text()` calls did, and
    `shared_docs_dir=None` output has to stay byte-identical to those.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
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


def _write_text_if_changed(path: Path, text: str) -> bool:
    """Publish one artifact; return whether bytes actually moved.

    Re-publishing a document that has not changed must be a no-op rather than
    a truncate-and-rewrite: with a shared store the *same* file is published
    by every part the document applies to, and rewriting it would churn
    mtimes that downstream cache keys (`CorpusIndex`'s, the batch skip gate's)
    are built on — and would briefly empty a file another part is reading.

    Comparison is on decoded text, not bytes, so a file written earlier with
    the platform's newline translation still compares equal.
    """
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, ValueError):
        pass
    _atomic_write_text(path, text)
    return True



def _artifact_schema_current(doc_dir: Path, filename: str, version: str) -> bool:
    """Whether a published JSON artifact carries the current schema version.

    A *missing* file reads as current here, unlike `search_index_current`, and
    the asymmetry is deliberate: `search_index.json` is written for every
    published document, so its absence is always staleness, while
    `specs.json` / `plots.json` are only written for documents that have
    trusted tables at all — a `pdf_text` register map legitimately has
    neither, and demanding one would put that part in a rebuild loop. What is
    checked is the version of a file that *is* there. Anything unreadable
    reads as stale, which is the safe direction: rebuild.
    """
    path = doc_dir / filename
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("schema_version") == version


def specs_current(doc_dir: Path) -> bool:
    """Whether `doc_dir`'s `specs.json` is of the current schema (or absent).

    The publish-cache-key check for spec records, called by the batch skip
    gate. `SPECS_SCHEMA_VERSION` is bumped whenever a published spec record
    gains or changes a field, so a corpus written before that field existed
    republishes once instead of serving it forever without.
    """
    return _artifact_schema_current(doc_dir, "specs.json", SPECS_SCHEMA_VERSION)


def plots_current(doc_dir: Path) -> bool:
    """`plots.json`'s twin of `specs_current`, keyed on `PLOTS_SCHEMA_VERSION`."""
    return _artifact_schema_current(doc_dir, "plots.json", PLOTS_SCHEMA_VERSION)


def _shared_neutral(artifact: SpecSet | PlotSet, shared: bool):
    """A shared artifact carries no part number; a per-part one is unchanged.

    Which part published a shared document first is an accident of ordering,
    and stamping it into the bytes would make two parts disagree about the
    file's contents and rewrite it forever. Readers take the part from
    `manifest.part_number`, so nothing loses information.
    """
    return artifact.model_copy(update={"part_number": ""}) if shared else artifact


def write_corpus(
    part_dir: Path,
    docs: list[tuple[RawDocument, list[SectionPlan], dict[str, str]]],
    index_md: str,
    *,
    pipeline_version: str,
    vendor: str = "",
    specsets: list[SpecSet] | None = None,
    plotsets: list[PlotSet] | None = None,
    shared_docs_dir: Path | None = None,
) -> CorpusManifest:
    """Write all corpus artifacts; return the manifest.

    `docs` = list of (RawDocument, its section plans, section descriptions).
    `vendor` is the part's evidence-pinned vendor routing record. Per-document
    extraction stats are recorded (backend always; table counts by the layout
    engine). Optional `specsets` are written as `docs/<doc>/specs.json`.
    Optional `plotsets` are written as `docs/<doc>/plots.json`.
    Every document also gets `docs/<doc>/search_index.json` — the BM25 index
    over the section markdown written here, so what is searchable is exactly
    what is readable.

    `shared_docs_dir` (ticket 04, signature frozen by ticket 00): publish
    once, reference many. Extraction is already deduplicated — its cache is
    keyed `(content_hash, backend)` — but publish output is not, and figures
    dominate it, so a vendor-wide note applying to 40 parts currently means
    40 copies of every figure. When set, each document's artifacts are
    written once under `<shared_docs_dir>/<doc_type>-<hash8>/` and each
    part's manifest references that location. `None` keeps today's layout
    under `parts/<PART>/docs/<doc_type>-<hash8>/`, byte for byte.
    """
    part_dir = Path(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)
    shared = shared_docs_dir is not None
    if shared:
        shared_docs_dir = Path(shared_docs_dir)
        shared_docs_dir.mkdir(parents=True, exist_ok=True)

    stats = CorpusStats(n_documents=len(docs))
    manifest = CorpusManifest(
        part_number=part_dir.name,
        pipeline_version=pipeline_version,
        vendor=vendor,
        # Self-describing corpus (integration, ticket 22): a reader holding
        # only this part directory has to be able to follow an `@library/`
        # reference, and nothing else on disk says which library wrote it.
        # Recorded relative to the part, so the pair moves together.
        library_root=(
            library_root_ref(part_dir, shared_docs_dir.parent) if shared else ""
        ),
    )
    specsets_by_hash = {s.doc_hash: s for s in (specsets or [])}
    plotsets_by_hash = {p.doc_hash: p for p in (plotsets or [])}
    # Per-part confidence mix, accumulated across the part's documents so the
    # manifest carries one measured number per grade (ticket 04).
    graded_specs: list[SpecRecord] = []
    graded_plots: list[PlotRecord] = []

    doc_dirs: list[str] = []

    for raw, plans, descriptions in docs:
        name = doc_dir_name(raw)
        doc_dirs.append(name)
        if shared:
            # The document's artifacts live once in the shared store; the
            # manifest below carries `@library/...` references to them.
            doc_abs = shared_docs_dir / name
            doc_rel = library_ref(shared_docs_dir, name)
        else:
            doc_rel = f"docs/{name}"
            doc_abs = part_dir / doc_rel
        (doc_abs / "sections").mkdir(parents=True, exist_ok=True)
        if any(p.table_files for p in plans):
            (doc_abs / "tables").mkdir(parents=True, exist_ok=True)

        specset = specsets_by_hash.get(raw.source.content_hash)
        if specset is not None:
            _write_text_if_changed(
                doc_abs / "specs.json",
                _shared_neutral(specset, shared).model_dump_json(indent=2),
            )
            stats.n_specs += len(specset.records)
            graded_specs.extend(specset.records)

        plotset = plotsets_by_hash.get(raw.source.content_hash)
        if plotset is not None:
            _write_text_if_changed(
                doc_abs / "plots.json",
                _shared_neutral(plotset, shared).model_dump_json(indent=2),
            )
            # Unchanged in meaning by the shared store: this counts the
            # figures *this part references*, whether it owns the bytes or
            # shares them with forty other parts.
            stats.n_plot_files += sum(1 for p in plotset.plots if p.file)
            graded_plots.extend(plotset.plots)

        manifest.documents.append(raw.source)
        extraction = raw.extraction_stats
        if extraction is None:
            extraction = ExtractionStats(backend=raw.extractor)
        # Stamp the extractor identity on every document, whatever produced
        # the stats: the batch skip gate reads it to detect a corpus built by
        # an older extractor output schema.
        extraction = extraction.model_copy(
            update={
                "backend": extraction.backend or raw.extractor,
                "extractor_version": raw.extractor_version,
            }
        )
        manifest.extraction_stats[raw.source.content_hash] = extraction
        stats.n_sections += len(plans)

        # Full-text index for this document, built from the very markdown the
        # loop below writes. Section token lengths come back out of it so the
        # manifest can budget a search hit without loading the index.
        search = build_search_index(
            plans,
            part_number="" if shared else part_dir.name,
            doc_hash=raw.source.content_hash,
        )
        search_text = dump_search_index(search)
        _write_text_if_changed(doc_abs / INDEX_FILENAME, search_text)
        stats.search_index_bytes += len(search_text.encode("utf-8"))
        search_tokens = {s.file: s.length for s in search.sections}

        for plan in plans:
            _write_text_if_changed(doc_abs / plan.file, plan.markdown)
            stats.section_bytes += len(plan.markdown.encode("utf-8"))
            for tf in plan.table_files:
                _write_text_if_changed(doc_abs / tf.name, tf.csv)

            sec = plan.section
            stats.n_tables += len(sec.tables)
            stats.n_figures += len(sec.figures)
            stats.n_footnotes += sum(len(t.footnotes) for t in sec.tables)
            stats.total_tokens += plan.token_count
            stats.boilerplate_tokens_removed += plan.boilerplate_removed
            if sec.page_start is not None:
                stats.sections_with_pages += 1
            else:
                stats.sections_without_pages += 1

            manifest.sections.append(
                SectionFile(
                    number=sec.number,
                    title=sec.title,
                    file=f"{doc_rel}/{plan.file}",
                    doc_hash=raw.source.content_hash,
                    page_start=sec.page_start,
                    page_end=sec.page_end,
                    token_count=plan.token_count,
                    description=descriptions.get(sec.number or sec.title, ""),
                    n_tables=len(sec.tables),
                    n_figures=len(sec.figures),
                    search_tokens=search_tokens.get(plan.file, 0),
                )
            )

    _write_text_if_changed(part_dir / "INDEX.md", index_md)
    stats.index_tokens = count_tokens(index_md)

    # The retrieval protocol ships *with* the corpus (ticket 08): INDEX.md is
    # the map, AGENT.md is how to read it. Written here rather than by the
    # enrich stage because it is not enriched — it is fixed text plus the
    # facts this function already has.
    agent_md = build_part_agent_markdown(
        part_dir.name,
        revision=manifest.documents[0].revision if manifest.documents else "",
        doc_dirs=doc_dirs,
        n_sections=stats.n_sections,
        n_specs=stats.n_specs,
        n_plot_files=stats.n_plot_files,
    )
    write_agent_doc(part_dir, agent_md)
    stats.agent_doc_tokens = count_tokens(agent_md)

    if graded_specs:
        stats.spec_confidence = confidence_mix(graded_specs)
    if graded_plots:
        stats.plot_confidence = confidence_mix(graded_plots)

    manifest.stats = stats
    _atomic_write_text(
        part_dir / "manifest.json",
        json.dumps(manifest.model_dump(mode="json"), indent=2),
    )
    log.info(
        "corpus written: %s (%d sections, %d tables, %d spec records, %d tokens, "
        "index %d tokens, agent protocol %d tokens)",
        part_dir, stats.n_sections, stats.n_tables, stats.n_specs,
        stats.total_tokens, stats.index_tokens, stats.agent_doc_tokens,
    )
    log.info(
        "confidence mix: specs %s; plots %s",
        stats.spec_confidence or "(none)", stats.plot_confidence or "(none)",
    )
    log.info(
        "search index: %d bytes over %d bytes of section markdown (%.0f%%)",
        stats.search_index_bytes, stats.section_bytes,
        100.0 * stats.search_index_bytes / stats.section_bytes if stats.section_bytes else 0.0,
    )
    return manifest


# --- reading a published manifest back ------------------------------------


@dataclass(frozen=True)
class ArtifactRef:
    """One artifact a manifest points at, and whether it is really there.

    Sharing makes absence a normal condition rather than a corruption: a
    figure removed from the shared store is missing from every part that
    references it at once, and a reader that crashes on the first one is
    useless for diagnosing exactly that. So this is a *report* — `exists`
    says what is on disk and `detail` says why not, and nothing raises.
    """

    ref: str  # as written in the manifest / plots.json
    path: Path  # where it resolves to
    kind: str  # "section" | "figure" | "specs" | "plots" | "search_index"
    doc: str  # document directory name
    shared: bool
    exists: bool
    detail: str = ""


def read_manifest(part_dir: Path) -> CorpusManifest | None:
    """Load `manifest.json`; `None` when it is absent or unreadable."""
    path = Path(part_dir) / "manifest.json"
    try:
        return CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("unreadable manifest %s: %s", path, exc)
        return None


def document_dirs(
    manifest: CorpusManifest, *, part_dir: Path, library_dir: Path | None = None
) -> dict[str, Path]:
    """`content_hash` -> the directory holding that document's artifacts.

    Derived from the manifest's own section references, so a corpus of mixed
    provenance — some documents shared, some published under the part before
    the shared store existed — resolves each document where it actually is.

    `library_dir` defaults to the root the manifest itself records
    (`CorpusManifest.library_root`), so a caller that has only read a part off
    disk does not have to know which `Settings` built it.
    """
    part_dir = Path(part_dir)
    if library_dir is None:
        library_dir = library_root_of(manifest, part_dir)
    by_hash: dict[str, Path] = {}
    for section in manifest.sections:
        if section.doc_hash in by_hash or "/sections/" not in section.file:
            continue
        base = section.file.split("/sections/", 1)[0]
        try:
            by_hash[section.doc_hash] = resolve_artifact_ref(
                base, part_dir=part_dir, library_dir=library_dir
            )
        except ValueError as exc:
            log.warning("%s", exc)
    for source in manifest.documents:
        if source.content_hash in by_hash:
            continue
        # A document with no sections still has a directory; fall back to the
        # convention rather than dropping it from the report.
        name = doc_dir_name_for_source(source)
        local = part_dir / "docs" / name
        shared = Path(library_dir) / "docs" / name if library_dir else None
        by_hash[source.content_hash] = (
            shared if shared is not None and shared.is_dir() and not local.is_dir() else local
        )
    return by_hash


def manifest_artifacts(
    manifest: CorpusManifest, *, part_dir: Path, library_dir: Path | None = None
) -> list[ArtifactRef]:
    """Every artifact this manifest references, resolved and checked.

    Covers the sections named in the manifest and, per document, its
    `specs.json` / `plots.json` / `search_index.json` and every figure its
    plot catalog points at. A stale `plots.json` is reported as one missing
    artifact carrying the schema error's own message — the figures behind it
    are deliberately *not* guessed at, because their paths are anchored to a
    root this version cannot know.

    `library_dir` defaults to `CorpusManifest.library_root`, as in
    `document_dirs()`.
    """
    part_dir = Path(part_dir)
    if library_dir is None:
        library_dir = library_root_of(manifest, part_dir)
    dirs = document_dirs(manifest, part_dir=part_dir, library_dir=library_dir)
    out: list[ArtifactRef] = []

    for section in manifest.sections:
        doc = section.file.split("/sections/", 1)[0].rsplit("/", 1)[-1]
        try:
            path = resolve_artifact_ref(
                section.file, part_dir=part_dir, library_dir=library_dir
            )
        except ValueError as exc:
            out.append(
                ArtifactRef(section.file, part_dir, "section", doc, True, False, str(exc))
            )
            continue
        out.append(
            ArtifactRef(
                section.file, path, "section", doc, is_library_ref(section.file),
                path.is_file(),
            )
        )

    for source in manifest.documents:
        doc_dir = dirs.get(source.content_hash)
        if doc_dir is None:
            continue
        name = doc_dir.name
        is_shared = library_dir is not None and _is_under(doc_dir, Path(library_dir))
        for filename, kind in (
            ("specs.json", "specs"),
            ("plots.json", "plots"),
            (INDEX_FILENAME, "search_index"),
        ):
            path = doc_dir / filename
            if path.exists() or kind == "search_index":
                out.append(
                    ArtifactRef(
                        f"{name}/{filename}", path, kind, name, is_shared, path.is_file()
                    )
                )
        try:
            plotset = load_plotset(doc_dir)
        except (StalePlotsSchemaError, OSError, ValueError) as exc:
            out.append(
                ArtifactRef(
                    f"{name}/plots.json", doc_dir / "plots.json", "plots", name,
                    is_shared, False, str(exc),
                )
            )
            continue
        if plotset is None:
            continue
        for record in plotset.plots:
            if not record.file:
                continue
            resolved = resolve_plot_file(
                record, doc_dir=doc_dir, schema_version=plotset.schema_version
            )
            out.append(
                ArtifactRef(
                    record.file,
                    resolved if resolved is not None else doc_dir.parent.parent / record.file,
                    "figure",
                    name,
                    is_shared,
                    resolved is not None,
                    "" if resolved is not None else "figure file is not on disk",
                )
            )
    return out


def missing_artifacts(
    manifest: CorpusManifest, *, part_dir: Path, library_dir: Path | None = None
) -> list[ArtifactRef]:
    """The subset of `manifest_artifacts` that is not on disk."""
    return [
        a
        for a in manifest_artifacts(manifest, part_dir=part_dir, library_dir=library_dir)
        if not a.exists
    ]


def _is_under(path: Path, root: Path) -> bool:
    try:
        Path(os.path.normpath(str(path))).relative_to(Path(os.path.normpath(str(root))))
    except ValueError:
        return False
    return True
