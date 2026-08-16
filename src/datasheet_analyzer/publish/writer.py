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
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from datasheet_analyzer.config import PLOTS_SCHEMA_VERSION, SPECS_SCHEMA_VERSION
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
from datasheet_analyzer.publish.search_index import build_search_index, write_search_index
from datasheet_analyzer.structure.confidence import mix as confidence_mix
from datasheet_analyzer.structure.corpus import SectionPlan
from datasheet_analyzer.tokens import count_tokens

log = logging.getLogger(__name__)


def doc_dir_name_for_source(source: SourceDocument) -> str:
    """Corpus directory name of one source document (`datasheet-a1b2c3d4`).

    Takes the `SourceDocument` rather than the `RawDocument` so a reader that
    only has a manifest — the batch skip gate, say — can name the same
    directory the publisher wrote, without re-extracting.
    """
    return f"{source.doc_type.value}-{source.content_hash[:8]}"


def doc_dir_name(raw: RawDocument) -> str:
    return doc_dir_name_for_source(raw.source)


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


def write_corpus(
    part_dir: Path,
    docs: list[tuple[RawDocument, list[SectionPlan], dict[str, str]]],
    index_md: str,
    *,
    pipeline_version: str,
    vendor: str = "",
    specsets: list[SpecSet] | None = None,
    plotsets: list[PlotSet] | None = None,
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
    """
    part_dir = Path(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)

    stats = CorpusStats(n_documents=len(docs))
    manifest = CorpusManifest(
        part_number=part_dir.name, pipeline_version=pipeline_version, vendor=vendor
    )
    specsets_by_hash = {s.doc_hash: s for s in (specsets or [])}
    plotsets_by_hash = {p.doc_hash: p for p in (plotsets or [])}
    # Per-part confidence mix, accumulated across the part's documents so the
    # manifest carries one measured number per grade (ticket 04).
    graded_specs: list[SpecRecord] = []
    graded_plots: list[PlotRecord] = []

    doc_dirs: list[str] = []

    for raw, plans, descriptions in docs:
        doc_dirs.append(doc_dir_name(raw))
        doc_rel = f"docs/{doc_dir_name(raw)}"
        doc_abs = part_dir / doc_rel
        (doc_abs / "sections").mkdir(parents=True, exist_ok=True)
        if any(p.table_files for p in plans):
            (doc_abs / "tables").mkdir(parents=True, exist_ok=True)

        specset = specsets_by_hash.get(raw.source.content_hash)
        if specset is not None:
            (doc_abs / "specs.json").write_text(
                specset.model_dump_json(indent=2), encoding="utf-8"
            )
            stats.n_specs += len(specset.records)
            graded_specs.extend(specset.records)

        plotset = plotsets_by_hash.get(raw.source.content_hash)
        if plotset is not None:
            (doc_abs / "plots.json").write_text(
                plotset.model_dump_json(indent=2), encoding="utf-8"
            )
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
            plans, part_number=part_dir.name, doc_hash=raw.source.content_hash
        )
        stats.search_index_bytes += write_search_index(doc_abs, search)
        search_tokens = {s.file: s.length for s in search.sections}

        for plan in plans:
            (doc_abs / plan.file).write_text(plan.markdown, encoding="utf-8")
            stats.section_bytes += len(plan.markdown.encode("utf-8"))
            for tf in plan.table_files:
                (doc_abs / tf.name).write_text(tf.csv, encoding="utf-8")

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

    (part_dir / "INDEX.md").write_text(index_md, encoding="utf-8")
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
    (part_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
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
