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
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.acquire import (
    append_to_inventory,
    load_inventory,
    pin_vendor,
    register_source,
    save_inventory,
)
from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.enrich import (
    AnthropicClient,
    DeterministicWriter,
    LLMWriter,
    SectionMeta,
    build_index_markdown,
)
from datasheet_analyzer.extract import get_backend
from datasheet_analyzer.extract.http import CachingBinaryFetcher, CachingFetcher
from datasheet_analyzer.extract.pdf_layout import figure_text_regions
from datasheet_analyzer.extract.pdf_structure import page_texts, read_toc
from datasheet_analyzer.models import (
    CorpusManifest,
    DocType,
    PinSet,
    PlotSet,
    RawDocument,
    RegisterSet,
    SourceDocument,
)
from datasheet_analyzer.publish import write_corpus
from datasheet_analyzer.publish.plots import (
    fetch_plot_images,
    render_figure_regions,
    render_plot_pages_fallback,
)
from datasheet_analyzer.publish.writer import doc_dir_name
from datasheet_analyzer.staleness import corpus_staleness, index_banner
from datasheet_analyzer.structure.corpus import SectionPlan, build_section_plans
from datasheet_analyzer.structure.pagemap import pin_table_pages
from datasheet_analyzer.structure.pins import build_pinset
from datasheet_analyzer.structure.plot_axes import annotate_plots
from datasheet_analyzer.structure.plots import build_plotset
from datasheet_analyzer.structure.registers import build_registerset
from datasheet_analyzer.structure.specs import build_specset
from datasheet_analyzer.vendor import select_backend, warn_vendor_drift

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

    Concurrent writers of the same path can never produce a partially
    written file: each write lands in its own temp file and the visible path
    flips only at the rename. This is what makes it safe for parallel batch
    jobs whose PDFs share the same (hash, backend) extraction-cache identity
    to race on one path; a failed write removes its temp file and leaves the
    destination untouched.

    The rename is retried briefly on ``PermissionError``: on Windows the
    destination is locked while another thread has it open for reading, so a
    parallel batch can otherwise lose a race it would win on POSIX.
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


def _store_cached_raw(settings: Settings, raw: RawDocument) -> None:
    """Atomic cache write: unique temp file + rename, so concurrent jobs
    sharing identical bytes can never leave a torn/corrupt cache entry.

    (pid + thread id keeps temp names unique even across threads of one
    process — Windows locks open files, so a shared temp name would fail;
    the replace itself races under contention and is retried briefly.)
    """
    path = _extract_cache_path(settings, raw.source.content_hash, raw.extractor)
    _atomic_write_text(path, raw.model_dump_json(indent=2))


def _brief_and_facts(raw: RawDocument) -> tuple[str, list[str]]:
    """Part brief (Description's first substantial paragraph) + Features bullets."""
    brief, facts = "", []
    for sec in raw.sections:
        title = sec.title.lower()
        # "General Description" (ADI/older parts) alongside TI's "Description"
        if not brief and title.startswith(("description", "general description")):
            for para in sec.paragraphs:
                if len(para.split()) >= 8:
                    brief = para
                    break
        if not facts and title.startswith("features"):
            facts = [p.lstrip("• ").strip() for p in sec.paragraphs if len(p) > 3]
    return brief, facts


def _backfill_vendor_evidence(sources: list[SourceDocument]) -> bool:
    """Legacy inventories (pre-0.2.0) have a vendor but no evidence: record
    the detection that agrees with the pinned value. True when anything
    changed; mismatches are left alone so the drift warning stays loud.
    """
    from datasheet_analyzer.vendor import detect_vendor

    changed = False
    for src in sources:
        if src.vendor_evidence or src.doc_type != DocType.DATASHEET:
            continue
        detected, evidence = detect_vendor(Path(src.path))
        if detected == src.vendor and evidence and not src.vendor_evidence:
            src.vendor_evidence = evidence
            changed = True
    return changed


def _extract_document(
    source: SourceDocument,
    pdf_path: Path,
    settings: Settings,
    use_cache: bool,
) -> tuple[RawDocument, bool]:
    """Extract one document, using cache if enabled. Returns (raw, cached).

    Backend follows the source's evidence-pinned vendor routing record:
    datasheet -> the profile's preference chain, register maps -> the layout
    floor (phase 6, ticket 05 — their tables are the product), other
    companions -> pdf_text.
    """
    backend_name = select_backend(source.vendor, source.doc_type)
    cached = False
    raw: RawDocument | None = None
    if use_cache:
        raw = _load_cached_raw(settings, source.content_hash, backend_name)
    backend = get_backend(backend_name)
    output_version = getattr(backend, "output_version", "")
    if raw is not None and raw.extractor_version != output_version:
        # The cached raw was produced by an older extractor output schema;
        # re-extract rather than serve a stale corpus (embedded version
        # field invalidation).
        log.info(
            "stale extraction cache (%s v%r != v%r) — re-extracting",
            backend_name, raw.extractor_version, output_version,
        )
        raw = None
    cached = raw is not None
    if raw is None:
        pdf_toc = read_toc(pdf_path)
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


class BuildRefused(RuntimeError):
    """A build the acquire stage refused, with the reason in its message."""


def _register_revision(
    pdf_path: Path,
    *,
    part_number: str,
    part_dir: Path,
    inventory: list[SourceDocument],
    vendor: str,
    revision_label: str,
) -> list[SourceDocument]:
    """File one PDF as a named revision of a part that already holds documents.

    The one place `--rev` widens acquire, and it is deliberately narrow: a PDF
    whose bytes are already registered is *not* re-labelled. The label is part of
    the published document directory name, so re-labelling would rename a
    directory every existing citation points at and leave the old one orphaned on
    disk — a corpus with two copies of one revision, one of them unreachable. A
    contradicting label is therefore refused with the reason, and a matching one
    is a no-op, which keeps `dsa build --rev` idempotent.
    """
    source = register_source(
        pdf_path, part_number=part_number, doc_type="datasheet",
        vendor=vendor or None, revision_label=revision_label,
    )
    existing = next(
        (s for s in inventory if s.content_hash == source.content_hash), None
    )
    if existing is None:
        return append_to_inventory([source], part_dir)
    if (existing.revision_label or "") == source.revision_label:
        return inventory
    raise BuildRefused(
        f"{Path(pdf_path).name} is already registered for {part_number} under "
        f"revision label {existing.revision_label or '(none)'!r}; it cannot be "
        f"re-filed as {source.revision_label!r} because the label names the "
        f"published document directory and every citation in it. Build the other "
        f"revision's own PDF with --rev instead"
    )


def build_part(
    pdf_path: Path,
    *,
    part_number: str,
    settings: Settings,
    vendor: str = "",
    use_cache: bool = True,
    use_llm: bool = True,
    revision_label: str = "",
    on_progress: Callable[[str], None] | None = None,
) -> BuildResult:
    """Build one part corpus end to end.

    ``vendor`` = explicit override of detection (recorded as cli-override
    evidence); "" = detection/pinned value.

    ``revision_label`` (`dsa build --rev F`, phase 7 ticket 03) files this PDF as
    a *named revision* of the part: it is registered into the inventory even when
    the part already holds documents, and the publisher gives it its own
    `-rev<label>` document directory, so two revisions coexist under one part and
    both stay independently queryable. Without a label the behaviour is exactly
    what it always was — the inventory is bootstrapped only when it is empty.

    ``on_progress`` is an additive hook: when supplied it is called at each
    stage boundary (``extracting``, ``structuring``, ``enriching``,
    ``publishing``) before that stage's work starts. Callers that omit it get
    the exact behavior they always had.

    Raises ``BuildRefused`` when a revision label contradicts one already
    recorded for the same bytes.
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
            pdf_path, part_number=part_number, doc_type="datasheet",
            vendor=vendor or None, revision_label=revision_label,
        )
        inventory = append_to_inventory([source], part_dir)
    elif revision_label:
        inventory = _register_revision(
            pdf_path, part_number=part_number, part_dir=part_dir,
            inventory=inventory, vendor=vendor, revision_label=revision_label,
        )
    if vendor and pin_vendor(inventory, vendor):
        save_inventory(inventory, part_dir)

    if not vendor and _backfill_vendor_evidence(inventory):
        save_inventory(inventory, part_dir)

    # identity drift: a detection contradicting a pin warns loudly but never
    # re-routes (the pinned value stays authoritative).
    warn_vendor_drift(inventory)

    part_vendor = next(
        (s.vendor for s in inventory if s.doc_type == DocType.DATASHEET),
        inventory[0].vendor if inventory else "",
    )

    # extract each document (datasheet via the vendor's preferred backend,
    # register maps via the layout floor, other companions via pdf_text)
    _progress("extracting")
    docs: list[RawDocument] = []
    any_cached = True
    for source in inventory:
        raw, cached = _extract_document(
            source, Path(source.path), settings, use_cache
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
    pinsets: list[PinSet] = []
    registersets: list[RegisterSet] = []
    doc_summaries: list[tuple[str, str, int, str]] = []
    brief, facts = "", []
    for raw in docs:
        # specs, plots and pins are deterministic transforms over the raw doc
        specset = build_specset(raw, part_number)
        if specset is not None:
            specsets.append(specset)
        plotset = build_plotset(raw, part_number)
        # The axis catalog (phase 6, ticket 08) is read from the PDF's own text
        # geometry, so it lives here rather than in `build_plotset`: it needs the
        # printed page, which a RawDocument does not carry, and it is the same
        # need `pin_table_pages` and `render_figure_regions` already have. It
        # runs for *both* content paths — a TI part's figures are downloaded
        # images, but the axes beside them are printed in the same PDF — and not
        # at all for `pdf_text`, which catalogs no figures.
        if raw.extractor != "pdf_text" and plotset.plots:
            graded_high = annotate_plots(
                plotset, figure_text_regions(Path(raw.source.path))
            )
            log.info("plot axes: %d/%d figures graded high",
                     graded_high, len(plotset.plots))
        plotsets.append(plotset)
        # Always appended, even when it holds no pins: a set with none still
        # carries the package cross-check and the rejection reasons, and the
        # publisher is what declines to write a file for it.
        pinsets.append(build_pinset(raw, part_number))
        # Same contract as pins: always appended, even when it holds no
        # registers, because the reset-coverage warning and the recorded
        # rejection reasons are part of the finding.
        registersets.append(build_registerset(raw, part_number))

        # pixel fetch only for html-derived docs; pdf_layout figures are
        # clip-rendered from their vector regions (never fetched)
        if raw.extractor == "pdf_layout":
            doc_abs = part_dir / f"docs/{doc_dir_name(raw)}"
            rendered = render_figure_regions(
                plotset, doc_abs, Path(raw.source.path),
                dpi=settings.plot_image_dpi,
            )
            log.info("plot pixels: %d clip-rendered (pdf_layout)", rendered)
        elif raw.extractor != "pdf_text":
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
    # The staleness banner is read off the inventory this build already
    # loaded — never fetched. A build performs no revision check (phase 7,
    # ticket 02), so a freshly built corpus banners `unknown` and says which
    # command clears it; `dsa check-revisions` refreshes the block in place.
    index_md = build_index_markdown(
        part_number,
        brief,
        facts,
        doc_summaries,
        metas,
        token_budget=settings.index_token_budget,
        staleness_banner=index_banner(corpus_staleness(inventory, part_number)),
    )

    # publish
    _progress("publishing")
    manifest = write_corpus(
        part_dir, all_plans, index_md,
        pipeline_version=PIPELINE_VERSION,
        vendor=part_vendor,
        specsets=specsets,
        plotsets=plotsets,
        pinsets=pinsets,
        registersets=registersets,
        card_version=settings.card_version,
    )
    return BuildResult(
        part_dir=part_dir, manifest=manifest, index_md=index_md,
        used_llm=used_llm, cached_extraction=any_cached,
    )
