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

from datasheet_analyzer.acquire.inventory import (
    default_store,
    ensure_covers,
    get_document,
    library_view,
    pin_vendor,
    register_into_library,
    relocate,
    resolve_documents,
    save_inventory,
    single_datasheet,
    sort_sources,
    sync_to_library,
)
from datasheet_analyzer.config import PIPELINE_VERSION, STRUCTURE_STAGE_VERSION, Settings
from datasheet_analyzer.derive.pins import PinBuild, build_pins, record_pin_rejections, write_pinset
from datasheet_analyzer.derive.registers import (
    RegisterBuild,
    build_registers,
    record_register_rejections,
    write_registerset,
)
from datasheet_analyzer.enrich import (
    AnthropicClient,
    DeterministicWriter,
    LLMWriter,
    SectionMeta,
    build_index_markdown,
)
from datasheet_analyzer.extract import get_backend
from datasheet_analyzer.extract.http import CachingBinaryFetcher, CachingFetcher
from datasheet_analyzer.extract.pdf_structure import compute_content_hash, page_texts, read_toc
from datasheet_analyzer.library.store import LibraryStore
from datasheet_analyzer.models import (
    Applicability,
    CorpusManifest,
    DocType,
    ExtractionStats,
    PlotSet,
    RawDocument,
    SourceDocument,
)
from datasheet_analyzer.publish import retire_cards, write_corpus
from datasheet_analyzer.publish.plots import (
    fetch_plot_images,
    render_figure_regions,
    render_plot_pages_fallback,
)
from datasheet_analyzer.publish.writer import doc_dir_name
from datasheet_analyzer.staleness import corpus_staleness, index_banner
from datasheet_analyzer.structure.corpus import SectionPlan, build_section_plans
from datasheet_analyzer.structure.pagemap import (
    pin_table_pages,
    pin_table_row_pages,
    reconcile_table_pages,
)
from datasheet_analyzer.structure.plot_axes import annotate_plot_axes
from datasheet_analyzer.structure.plots import build_plotset
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


def _stale_cache_reason(raw: RawDocument, backend_name: str, output_version: str) -> str:
    """Why a cached extraction may not be served, or "" when it may.

    Two producers write into one cached record, and both must be able to
    invalidate it: the **backend** (its embedded `output_version`) and the
    **structure stage** that runs inside `_extract_document` after the backend
    returns (page and row pinning; `STRUCTURE_STAGE_VERSION`). Only the first
    had a version until phase 6.5 measured what that costs — a per-row pinning
    fix that every `ti_html` document was served around, because bumping the
    *layout* backend's version says nothing about a document that layout
    backend never read.
    """
    if raw.extractor_version != output_version:
        return f"{backend_name} v{raw.extractor_version!r} != v{output_version!r}"
    if raw.structure_version != STRUCTURE_STAGE_VERSION:
        return f"structure stage v{raw.structure_version!r} != v{STRUCTURE_STAGE_VERSION!r}"
    return ""


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


def _annotate_axes(plotset: PlotSet, raw: RawDocument) -> None:
    """Fill the plot catalog's axis fields from the document's own PDF.

    Ticket 08. The axis catalog is geometry read off the printed page, so it
    needs the PDF rather than the extractor's output — a TI part whose figure
    catalog came from the HTML datasheet is annotated from the very same PDF,
    which is why this is keyed on the source file and not on `raw.extractor`.

    A document with no local PDF is *not attempted*, and its records keep
    `axis_confidence: unknown` rather than being graded `low`: "nobody
    looked" and "looked and found nothing" are different claims and the
    corpus makes both of them separately.
    """
    if not plotset.plots:
        return
    source = Path(raw.source.path)
    if source.suffix.lower() != ".pdf" or not source.is_file():
        return
    coverage = annotate_plot_axes(plotset, source)
    log.info(
        "plot axes: %d/%d figures read at high confidence (%.0f%%), %d log-scale",
        coverage.high,
        coverage.total,
        100 * coverage.high_fraction,
        coverage.log_axes,
    )


def _derive_pins(raw: RawDocument, part_number: str) -> PinBuild:
    """Read one document's pin table and record what happened to it (ticket 04).

    Two things land here rather than in `derive/pins.py`, because both are
    about the *document* rather than about pins:

    - a rejected pin table's reason joins `ExtractionStats.rejection_reasons`,
      which `write_corpus` copies into the manifest below — so the refusal
      shows up in `dsa status` beside the parametric tables the layout engine
      refused, instead of vanishing;
    - a document that carries no stats yet (an older extractor output, or a
      backend that reports none) gets an empty set rather than losing the
      reason. Silence about a rejected pin table is the one outcome this phase
      cannot ship: a missing pin reads as "this pin does not exist".

    The `pins.json` file itself is written after publish, once the document's
    directory is known.
    """
    build = build_pins(raw, part_number)
    if build.rejection_reasons and raw.extraction_stats is None:
        raw.extraction_stats = ExtractionStats(backend=raw.extractor)
    record_pin_rejections(raw.extraction_stats, build)
    if build.pinset is not None:
        log.info(
            "pins: %d records from %s (package declares %s)",
            build.n_pins,
            raw.source.path,
            build.declared.count if build.declared.count is not None else "nothing parseable",
        )
    for warning in build.warnings:
        log.warning("pins: %s", warning)
    return build


def _derive_registers(raw: RawDocument, part_number: str) -> RegisterBuild:
    """Read one document's register summary table and record what happened.

    `_derive_pins`'s twin, for the same reasons and with the same two
    document-level jobs: a rejected register table's reason joins
    `ExtractionStats.rejection_reasons` so `dsa status` prints it, and a
    document carrying no stats yet gets an empty set rather than losing the
    reason.

    This is the artifact the routing change (ticket 05) exists to make
    possible: read as paragraphs, a register map yields no tables at all, so
    every document here would report "no candidate register table" forever
    and the silence would be indistinguishable from a part that has no
    registers. The `registers.json` file itself is written after publish, once
    the document's directory is known.
    """
    build = build_registers(raw, part_number)
    if build.rejection_reasons and raw.extraction_stats is None:
        raw.extraction_stats = ExtractionStats(backend=raw.extractor)
    record_register_rejections(raw.extraction_stats, build)
    if build.registerset is not None:
        log.info(
            "registers: %d records from %d table(s) in %s",
            build.n_registers,
            build.accepted_tables,
            raw.source.path,
        )
    for warning in build.warnings:
        log.warning("registers: %s", warning)
    return build


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


def _reconcile_named_pdf(
    inventory: list[SourceDocument],
    pdf_path: Path,
    *,
    part_number: str,
    vendor: str,
    store: LibraryStore | None,
) -> list[SourceDocument]:
    """Make sure the PDF the caller named is one of the part's documents.

    Three cases, keyed on the file's bytes because that is what identity is:

    - already resolved under this path — nothing to do;
    - already resolved under a *different* path — the document moved, so the
      record follows it rather than a second identity being invented;
    - not resolved at all — the caller named it as this part's document, so it
      is registered as applying to this part (or, if the Library already knows
      the document under a different applicability, that record is widened
      rather than replaced). A part with no datasheet yet gets one; otherwise
      the filename decides the type, the way `add-doc` does, because a
      register map named on the command line is still a register map.
    """
    current = compute_content_hash(pdf_path)
    for i, src in enumerate(inventory):
        if src.content_hash == current:
            inventory[i] = relocate(src, pdf_path, store=store)
            return inventory

    known = get_document(store, current)
    if known is not None:
        src = ensure_covers(known, part_number, store=store)
        return sort_sources([*inventory, relocate(src, pdf_path, store=store)])

    has_datasheet = any(s.doc_type == DocType.DATASHEET for s in inventory)
    doc = register_into_library(
        pdf_path,
        applicability=Applicability.for_parts(
            [part_number], evidence=f"registered at acquire for {part_number}"
        ),
        doc_type=None if has_datasheet else DocType.DATASHEET,
        vendor=vendor or None,
        store=store,
        part_number=part_number,
    )
    return sort_sources([*inventory, doc.source])


class BuildRefused(RuntimeError):
    """A build the acquire stage refused, with the reason in its message."""


def _file_revision_label(
    pdf_path: Path,
    *,
    part_number: str,
    inventory: list[SourceDocument],
    store: LibraryStore | None,
    revision_label: str,
) -> None:
    """Record `dsa build --rev <label>` against the document's Library record.

    The label is the name a human filed *this copy* under. It is written to the
    Library (`LibraryDocument.revision_label`), never to `SourceDocument` — that
    shape is frozen and embedded in every cached extraction — and never to
    `sources.json`, which is regenerated from the Library at publish and would
    erase it.

    Two refusals, and one warning that names a rule this branch already had.

    **A PDF already filed under a different label is not re-labelled.** A label
    is how `dsa diff-rev` names a side, so silently overwriting it would rename
    the earlier revision in every report that quoted it. A matching label is a
    no-op, which keeps `dsa build --rev` idempotent.

    **A label on a part that already holds another datasheet warns.** On this
    branch `acquire.inventory.single_datasheet` builds one datasheet per part —
    "a part is one device, and its datasheet is one document" — so a second
    datasheet record is kept in the Library and skipped by the build. The label
    is still recorded (it is true of that document), but the caller is told, in
    the same breath, that it did not produce a second buildable side.
    """
    label = revision_label.strip()
    if not label:
        return
    content_hash = compute_content_hash(pdf_path)
    stored = get_document(store, content_hash)
    if stored is None:
        log.warning(
            "--rev %s: %s is not in the Library, so no revision label was recorded",
            label,
            pdf_path.name,
        )
        return
    existing = (stored.revision_label or "").strip()
    if existing and existing != label:
        raise BuildRefused(
            f"{pdf_path.name} is already filed for {part_number} under revision "
            f"label {existing!r}; it cannot be re-filed as {label!r} because the "
            f"label is how `dsa diff-rev` names a side and every report that "
            f"quoted the old one would silently change meaning. Clear it "
            f"deliberately, or build the other revision's own PDF"
        )
    if existing != label:
        store.set_revision_label(content_hash, label)
    built = {src.content_hash for src in inventory}
    skipped = [
        doc
        for doc in (store.for_part(part_number) if store is not None else [])
        if doc.source.doc_type == DocType.DATASHEET and doc.content_hash not in built
    ]
    if skipped:
        log.warning(
            "--rev %s was recorded on %s, but %d other datasheet record(s) for %s "
            "are not part of this build: a part builds one datasheet "
            "(acquire.inventory.single_datasheet), so labelling a second one does "
            "not make two revisions coexist under %s",
            label,
            pdf_path.name,
            len(skipped),
            part_number,
            part_number,
        )


def _acquire(
    pdf_path: Path,
    part_dir: Path,
    *,
    part_number: str,
    vendor: str,
    store: LibraryStore | None,
) -> list[SourceDocument]:
    """The document set this build runs over, and its pinned vendor records.

    The Library answers "which documents apply to this part" (ADR 0005);
    `sources.json` is not read here except by the migration inside
    `resolve_documents()`, which is what makes hand-editing the derived file
    have no effect on a build.
    """
    inventory = resolve_documents(part_dir, part_number=part_number, store=store)
    inventory = _reconcile_named_pdf(
        inventory, pdf_path, part_number=part_number, vendor=vendor, store=store
    )
    inventory = single_datasheet(inventory, keep=compute_content_hash(pdf_path))

    # Vendor is decided at acquire and pinned with evidence; a repin or a
    # legacy backfill is written straight back to the authoritative record.
    changed = bool(vendor) and pin_vendor(inventory, vendor)
    if not vendor and _backfill_vendor_evidence(inventory):
        changed = True
    if changed:
        sync_to_library(inventory, part_number=part_number, store=store)
    return inventory


def _extract_document(
    source: SourceDocument,
    pdf_path: Path,
    settings: Settings,
    use_cache: bool,
) -> tuple[RawDocument, bool]:
    """Extract one document, using cache if enabled. Returns (raw, cached).

    Backend follows the source's evidence-pinned vendor routing record:
    datasheet -> the profile's preference chain, register maps -> pdf_layout
    (phase 6, ticket 05), other companions -> pdf_text.
    """
    backend_name = select_backend(source.vendor, source.doc_type)
    cached = False
    raw: RawDocument | None = None
    if use_cache:
        raw = _load_cached_raw(settings, source.content_hash, backend_name)
    backend = get_backend(backend_name)
    output_version = getattr(backend, "output_version", "")
    if raw is not None:
        # The cached raw was produced by an older extractor output schema, or
        # by an older structure stage; re-extract rather than serve a stale
        # corpus (embedded version field invalidation).
        stale = _stale_cache_reason(raw, backend_name, output_version)
        if stale:
            log.info("stale extraction cache (%s) — re-extracting", stale)
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
            texts = page_texts(pdf_path)
            pinned = pin_table_pages(raw.sections, texts)
            log.info("table pages pinned: %d/%d", pinned, sum(len(s.tables) for s in raw.sections))
            # Rows next, at the same bar. `pdf_layout` already measured its
            # own; this is the HTML path, which has no geometry to measure.
            rows_pinned, rows_total = pin_table_row_pages(raw.sections, texts)
            if rows_total:
                log.info("table row pages pinned: %d/%d", rows_pinned, rows_total)
            # Last, because it reads what both of the above wrote: where the
            # two disagree about a table's page, the rows are the stronger
            # evidence and the table follows them.
            for caption, was, now in reconcile_table_pages(raw.sections):
                log.info("table page corrected by its rows: %s p.%d -> p.%d", caption, was, now)
        # Stamped after the structure stage ran, not before: the version
        # describes what is *in* this record.
        raw.structure_version = STRUCTURE_STAGE_VERSION
        _store_cached_raw(settings, raw)
    return raw, cached


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
    store: LibraryStore | None = None,
    self_contained: bool = False,
) -> BuildResult:
    """Build one part corpus end to end.

    ``vendor`` = explicit override of detection (recorded as cli-override
    evidence); "" = detection/pinned value.

    ``revision_label`` (`dsa build --rev F`, phase 7 ticket 03) records the name
    a human filed *this copy* under, on the document's Library record, so
    `dsa diff-rev` can name a side by it. It changes nothing about which
    documents are built: a part still builds one datasheet
    (`acquire.inventory.single_datasheet`), and a label on a second one is
    recorded and warned about rather than silently widening the build set.
    Raises ``BuildRefused`` when it contradicts a label already recorded for the
    same bytes.

    ``on_progress`` is an additive hook: when supplied it is called at each
    stage boundary (``extracting``, ``structuring``, ``enriching``,
    ``publishing``) before that stage's work starts. Callers that omit it get
    the exact behavior they always had.

    ``store`` is the Library this build resolves its documents through (ADR
    0005): the part is the *view* of the documents whose applicability covers
    it, not the contents of a folder. `None` constructs the store named by
    ``settings``. `parts/<PART>/sources.json` is regenerated from the resolved
    set at publish time and is never read back as the source of truth.

    ``self_contained`` (ADR 0008) publishes every artifact under
    ``parts/<PART>/docs/`` instead of the shared library store, so the part
    directory alone is a complete, readable corpus. That is what a *tracked*
    reference corpus must be: `/library/` is gitignored local shelf state, so
    a committed corpus carrying `@library/…` references is unreadable on a
    fresh clone. Default `False` keeps publish-once/reference-many for the
    working shelf.
    """
    pdf_path = Path(pdf_path)
    part_dir = settings.parts_dir / part_number
    if store is None:
        store = default_store(settings)

    def _progress(stage: str) -> None:
        if on_progress is not None:
            on_progress(stage)

    # acquire: ask the Library which documents apply to this part, migrating a
    # legacy sources.json in on first touch; bootstrap from the CLI pdf when
    # nothing applies yet.
    inventory = _acquire(pdf_path, part_dir, part_number=part_number, vendor=vendor, store=store)

    # identity drift: a detection contradicting a pin warns loudly but never
    # re-routes (the pinned value stays authoritative).
    warn_vendor_drift(inventory)

    # `--rev` is filing metadata, written after the document is in the Library
    # and before anything is extracted: a refused label must cost nothing.
    _file_revision_label(
        pdf_path,
        part_number=part_number,
        inventory=inventory,
        store=store,
        revision_label=revision_label,
    )

    part_vendor = next(
        (s.vendor for s in inventory if s.doc_type == DocType.DATASHEET),
        inventory[0].vendor if inventory else "",
    )

    # extract each document (datasheet via the vendor's preferred backend,
    # register maps via pdf_layout, other companions via pdf_text)
    _progress("extracting")
    docs: list[RawDocument] = []
    any_cached = True
    for source in inventory:
        raw, cached = _extract_document(source, Path(source.path), settings, use_cache)
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

    # publish once, reference many: a document that applies to several parts
    # is extracted once (the cache is keyed by content hash) and published
    # once, under the library's shared document store; each part's manifest
    # references it. Plot pixels are rendered into the root the publisher will
    # use, so a figure is never orphaned from the record that names it.
    shared_docs_dir = None if self_contained else settings.library_dir / "docs"

    def _doc_out_dir(raw: RawDocument) -> Path:
        root = (part_dir / "docs") if shared_docs_dir is None else shared_docs_dir
        return root / doc_dir_name(raw)

    all_plans: list[tuple[RawDocument, list[SectionPlan], dict[str, str]]] = []
    _progress("structuring")
    specsets: list[PlotSet] = []
    plotsets: list[PlotSet] = []
    # Derived artifacts, keyed by document (phase 6). Held until publish, when
    # the document's directory is known — shared store or under the part.
    pinbuilds: dict[str, PinBuild] = {}
    registerbuilds: dict[str, RegisterBuild] = {}
    doc_summaries: list[tuple[str, str, int, str]] = []
    brief, facts = "", []
    for raw in docs:
        # specs and plots are deterministic transforms over the raw doc
        specset = build_specset(raw, part_number)
        if specset is not None:
            specsets.append(specset)
        plotset = build_plotset(raw, part_number)
        plotsets.append(plotset)
        _annotate_axes(plotset, raw)
        pinbuilds[raw.source.content_hash] = _derive_pins(raw, part_number)
        registerbuilds[raw.source.content_hash] = _derive_registers(raw, part_number)

        # pixel fetch only for html-derived docs; pdf_layout figures are
        # clip-rendered from their vector regions (never fetched)
        if raw.extractor == "pdf_layout":
            doc_abs = _doc_out_dir(raw)
            rendered = render_figure_regions(
                plotset,
                doc_abs,
                Path(raw.source.path),
                dpi=settings.plot_image_dpi,
            )
            log.info("plot pixels: %d clip-rendered (pdf_layout)", rendered)
        elif raw.extractor != "pdf_text":
            doc_abs = _doc_out_dir(raw)
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
    # The staleness banner is read off the Library records this build already
    # wrote - never fetched. A build performs no revision check (phase 7,
    # ticket 02), so a freshly built corpus banners `unknown` and says which
    # command clears it; `dsa check-revisions` refreshes the block in place.
    index_md = build_index_markdown(
        part_number,
        brief,
        facts,
        doc_summaries,
        metas,
        token_budget=settings.index_token_budget,
        staleness_banner=index_banner(
            corpus_staleness(
                library_view(part_dir, part_number=part_number, store=store), part_number
            )
        ),
    )

    # publish
    _progress("publishing")
    manifest = write_corpus(
        part_dir,
        all_plans,
        index_md,
        pipeline_version=PIPELINE_VERSION,
        vendor=part_vendor,
        specsets=specsets,
        plotsets=plotsets,
        shared_docs_dir=shared_docs_dir,
    )
    # Every design card on disk was computed from the corpus this build just
    # replaced, so it is retired here rather than left looking current
    # (`publish.retire_cards`). `load_or_build_card` rebuilds on demand.
    retired = retire_cards(part_dir)
    if retired:
        log.info("retired %d stale design-card file(s) after republish", retired)

    # `pins.json` lands beside the document's other artifacts, wherever they
    # were published. Written only for a document that actually yielded a pin
    # table: a part with none publishes no file at all rather than an empty
    # one, which would read as "this part has no pins" (ticket 04).
    # `registers.json` follows the same rule (ticket 05): written only for a
    # document that actually yielded a register summary table, so a part with
    # none publishes no file rather than an empty map.
    for raw in docs:
        build = pinbuilds.get(raw.source.content_hash)
        if build is not None and build.pinset is not None:
            write_pinset(_doc_out_dir(raw), build.pinset, shared=not self_contained)
        regbuild = registerbuilds.get(raw.source.content_hash)
        if regbuild is not None and regbuild.registerset is not None:
            write_registerset(_doc_out_dir(raw), regbuild.registerset, shared=not self_contained)

    # sources.json is derived: regenerated here from the resolved document
    # set so `dsa status` and the batch skip gate keep reading what they
    # always read, and a hand edit never survives a build.
    save_inventory(inventory, part_dir)
    return BuildResult(
        part_dir=part_dir,
        manifest=manifest,
        index_md=index_md,
        used_llm=used_llm,
        cached_extraction=any_cached,
    )
