"""Pipeline orchestration: PDF(s) (+ vendor HTML) -> corpus on disk.

Stages: acquire -> extract -> structure -> enrich -> publish.
Extraction is cached by (content_hash, backend): the RawDocument is
serialized to .cache/extract/<hash>__<backend>.json so re-runs skip
parsing entirely (the HTTP layer has its own cache too).
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.acquire import append_to_inventory, load_inventory, register_source
from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.enrich import (
    AnthropicClient,
    DeterministicWriter,
    LLMWriter,
    SectionMeta,
    build_index_markdown,
)
from datasheet_analyzer.extract import DEFAULT_BACKEND, get_backend
from datasheet_analyzer.extract.http import CachingBinaryFetcher, CachingFetcher
from datasheet_analyzer.extract.pdf_structure import page_texts, read_toc
from datasheet_analyzer.models import CorpusManifest, PlotSet, RawDocument, SourceDocument
from datasheet_analyzer.publish import write_corpus
from datasheet_analyzer.publish.plots import (
    fetch_plot_images,
    render_plot_pages_fallback,
)
from datasheet_analyzer.publish.writer import doc_dir_name
from datasheet_analyzer.structure.corpus import SectionPlan, build_section_plans
from datasheet_analyzer.structure.pagemap import pin_table_pages
from datasheet_analyzer.structure.plots import build_plotset
from datasheet_analyzer.structure.specs import build_specset

log = logging.getLogger(__name__)

BUILD_STAGES: tuple[str, ...] = (
    "extracting",
    "structuring",
    "enriching",
    "publishing",
)


@dataclass
class BuildResult:
    part_dir: Path
    manifest: CorpusManifest
    index_md: str
    used_llm: bool
    cached_extraction: bool


def _extract_cache_path(settings: Settings, content_hash: str, backend: str) -> Path:
    return settings.cache_dir / "extract" / f"{content_hash}__{backend}.json"


def _load_cached_raw(settings: Settings, content_hash: str, backend: str) -> RawDocument | None:
    path = _extract_cache_path(settings, content_hash, backend)
    if path.exists():
        log.info("extraction cache hit: %s", path.name)
        return RawDocument.model_validate_json(path.read_text(encoding="utf-8"))
    return None


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically: unique temp file + rename.

    A concurrent reader or writer always observes either the old file or the
    complete new one — never a partially written file. This is what makes it
    safe for parallel batch jobs whose PDFs share the same (hash, backend)
    extraction-cache identity to race on one path; a failed write removes its
    temp file and leaves the destination untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _store_cached_raw(settings: Settings, raw: RawDocument) -> None:
    path = _extract_cache_path(settings, raw.source.content_hash, raw.extractor)
    _atomic_write_text(path, raw.model_dump_json(indent=2))


def _brief_and_facts(raw: RawDocument) -> tuple[str, list[str]]:
    """Part brief (Description's first substantial paragraph) + Features bullets."""
    brief, facts = "", []
    for sec in raw.sections:
        title = sec.title.lower()
        if not brief and title.startswith("description"):
            for para in sec.paragraphs:
                if len(para.split()) >= 8:
                    brief = para
                    break
        if not facts and title.startswith("features"):
            facts = [p.lstrip("• ").strip() for p in sec.paragraphs if len(p) > 3]
    return brief, facts


def _select_backend_name(source: SourceDocument, datasheet_backend: str) -> str:
    """Primary datasheet -> HTML backend; companions -> degraded pdf_text."""
    if source.doc_type.value == "datasheet":
        return datasheet_backend
    return "pdf_text"


def _extract_document(
    source: SourceDocument,
    pdf_path: Path,
    settings: Settings,
    datasheet_backend: str,
    use_cache: bool,
) -> tuple[RawDocument, bool]:
    """Extract one document, using cache if enabled. Returns (raw, cached)."""
    backend_name = _select_backend_name(source, datasheet_backend)
    cached = False
    raw: RawDocument | None = None
    if use_cache:
        raw = _load_cached_raw(settings, source.content_hash, backend_name)
    cached = raw is not None
    if raw is None:
        pdf_toc = read_toc(pdf_path)
        backend = get_backend(backend_name)
        # Tests pre-wire a replaying fetcher on the backend instance; do not
        # override an explicit fetcher.
        if (
            backend_name != "pdf_text"
            and getattr(backend, "fetcher", None) is None
            and hasattr(backend, "fetcher")
        ):
            backend.fetcher = CachingFetcher(
                settings.cache_dir / "http",
                timeout_s=settings.http_timeout_s,
                delay_s=settings.http_delay_s,
                user_agent=settings.user_agent,
            )
        raw = backend.extract(source, pdf_toc=pdf_toc)
        if backend_name != "pdf_text":
            pinned = pin_table_pages(raw.sections, page_texts(pdf_path))
            log.info("table pages pinned: %d/%d", pinned,
                     sum(len(s.tables) for s in raw.sections))
        _store_cached_raw(settings, raw)
    return raw, cached


def build_part(
    pdf_path: Path,
    *,
    part_number: str,
    settings: Settings,
    backend_name: str = DEFAULT_BACKEND,
    use_cache: bool = True,
    use_llm: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> BuildResult:
    """Build one part corpus end to end.

    ``on_progress`` is an additive hook: when supplied it is called at each
    stage boundary (``extracting``, ``structuring``, ``enriching``,
    ``publishing``) before that stage's work starts. Callers that omit it get
    the exact behavior they always had.
    """
    pdf_path = Path(pdf_path)
    part_dir = settings.parts_dir / part_number

    def _progress(stage: str) -> None:
        if on_progress is not None:
            on_progress(stage)

    # acquire: load inventory or bootstrap from the CLI pdf
    inventory = load_inventory(part_dir)
    if not inventory:
        source = register_source(
            pdf_path, part_number=part_number, doc_type="datasheet"
        )
        inventory = append_to_inventory([source], part_dir)

    # extract each document (datasheet via ti_html, companions via pdf_text)
    _progress("extracting")
    docs: list[RawDocument] = []
    any_cached = True
    for source in inventory:
        raw, cached = _extract_document(
            source, Path(source.path), settings, backend_name, use_cache
        )
        any_cached = any_cached and cached
        docs.append(raw)

    # structure + enrich per document
    writer = DeterministicWriter()
    used_llm = False
    if use_llm and settings.llm_available and settings.llm_descriptions:
        writer = LLMWriter(
            AnthropicClient(settings.anthropic_api_key, settings.model),
            fallback=DeterministicWriter(),
            max_tokens=settings.max_output_tokens,
        )
        used_llm = True
    elif use_llm and not settings.llm_available:
        log.warning("no ANTHROPIC_API_KEY — using deterministic descriptions")

    all_plans: list[tuple[RawDocument, list[SectionPlan], dict[str, str]]] = []
    _progress("structuring")
    specsets: list[PlotSet] = []
    plotsets: list[PlotSet] = []
    doc_summaries: list[tuple[str, str, int, str]] = []
    brief, facts = "", []
    for raw in docs:
        # specs and plots are deterministic transforms over the raw doc
        specset = build_specset(raw, part_number)
        if specset is not None:
            specsets.append(specset)
        plotset = build_plotset(raw, part_number)
        plotsets.append(plotset)

        # pixel fetch only for html-derived docs
        if raw.extractor != "pdf_text":
            doc_abs = part_dir / f"docs/{doc_dir_name(raw)}"
            plot_fetcher = CachingBinaryFetcher(
                settings.cache_dir / "http-bin",
                timeout_s=settings.http_timeout_s,
                delay_s=settings.http_delay_s,
                user_agent=settings.user_agent,
            )
            fetched = fetch_plot_images(plotset, doc_abs, fetcher=plot_fetcher)
            rendered = render_plot_pages_fallback(
                plotset, doc_abs, Path(raw.source.path), dpi=settings.plot_image_dpi
            )
            log.info("plot pixels: %d fetched, %d rendered fallback", fetched, rendered)

        plans = build_section_plans(raw)
        descriptions = writer.describe(raw, plans)
        all_plans.append((raw, plans, descriptions))

        if not brief:
            brief, facts = _brief_and_facts(raw)
        doc_summaries.append(
            (
                raw.source.doc_type.value,
                raw.source.revision,
                raw.source.page_count,
                raw.source.content_hash[:8],
            )
        )

    # enrich: one INDEX.md grouping sections by document
    _progress("enriching")
    metas: list[SectionMeta] = []
    for raw, plans, descriptions in all_plans:
        doc_dir = f"docs/{doc_dir_name(raw)}"
        for p in plans:
            sec = p.section
            metas.append(
                SectionMeta(
                    number=sec.number,
                    title=sec.title,
                    file=f"{doc_dir}/{p.file}",
                    page_start=sec.page_start,
                    page_end=sec.page_end,
                    token_count=p.token_count,
                    n_tables=len(sec.tables),
                    n_figures=len(sec.figures),
                    description=descriptions.get(sec.number or sec.title, ""),
                )
            )
    index_md = build_index_markdown(
        part_number,
        brief,
        facts,
        doc_summaries,
        metas,
        token_budget=settings.index_token_budget,
    )

    # publish
    _progress("publishing")
    manifest = write_corpus(
        part_dir, all_plans, index_md,
        pipeline_version=PIPELINE_VERSION,
        specsets=specsets,
        plotsets=plotsets,
    )
    return BuildResult(
        part_dir=part_dir, manifest=manifest, index_md=index_md,
        used_llm=used_llm, cached_extraction=any_cached,
    )
