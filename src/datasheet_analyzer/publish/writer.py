"""Corpus writer: sections/, tables/, INDEX.md, manifest.json on disk.

Layout per part:
    parts/<PART>/
      INDEX.md
      sources.json            (written by acquire)
      manifest.json
      docs/<doc_type>-<hash8>/
        sections/*.md
        tables/*.csv
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from datasheet_analyzer.models import (
    CorpusManifest,
    CorpusStats,
    ExtractionStats,
    PlotSet,
    RawDocument,
    SectionFile,
    SpecSet,
)
from datasheet_analyzer.structure.corpus import SectionPlan
from datasheet_analyzer.tokens import count_tokens

log = logging.getLogger(__name__)


def doc_dir_name(raw: RawDocument) -> str:
    return f"{raw.source.doc_type.value}-{raw.source.content_hash[:8]}"


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
    """
    part_dir = Path(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)

    stats = CorpusStats(n_documents=len(docs))
    manifest = CorpusManifest(
        part_number=part_dir.name, pipeline_version=pipeline_version, vendor=vendor
    )
    specsets_by_hash = {s.doc_hash: s for s in (specsets or [])}
    plotsets_by_hash = {p.doc_hash: p for p in (plotsets or [])}

    for raw, plans, descriptions in docs:
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

        plotset = plotsets_by_hash.get(raw.source.content_hash)
        if plotset is not None:
            (doc_abs / "plots.json").write_text(
                plotset.model_dump_json(indent=2), encoding="utf-8"
            )
            stats.n_plot_files += sum(1 for p in plotset.plots if p.file)

        manifest.documents.append(raw.source)
        extraction = raw.extraction_stats
        if extraction is None:
            extraction = ExtractionStats(backend=raw.extractor)
        manifest.extraction_stats[raw.source.content_hash] = extraction
        stats.n_sections += len(plans)

        for plan in plans:
            (doc_abs / plan.file).write_text(plan.markdown, encoding="utf-8")
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
                )
            )

    (part_dir / "INDEX.md").write_text(index_md, encoding="utf-8")
    stats.index_tokens = count_tokens(index_md)

    manifest.stats = stats
    (part_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    log.info(
        "corpus written: %s (%d sections, %d tables, %d spec records, %d tokens, index %d tokens)",
        part_dir, stats.n_sections, stats.n_tables, stats.n_specs,
        stats.total_tokens, stats.index_tokens,
    )
    return manifest
