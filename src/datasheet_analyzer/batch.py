"""Batch runner: one invocation builds every PDF in a directory as its own part.

The batch is just a directory — its content *is* the specification. Direct
children matching ``*.pdf`` (case-insensitive) become jobs in sorted filename
order; the part number of each job is the filename stem uppercased. Each job
runs the existing single-part pipeline end to end via ``build_part`` inside
its own error boundary: a failing job records its error and every remaining
job still runs. The run prints the file -> part mapping before any work
starts and a per-job summary table at the end; ``BatchReport.ok`` is False
when any job failed (the CLI maps that to exit code 1).

Re-running a batch over the same directory skips parts that are already
built and unchanged: a job is skipped when the part's manifest exists with
the current ``PIPELINE_VERSION``, every published document's recorded
``extractor_version`` still matches what its backend emits today, every
published document carries a current-schema ``search_index.json`` (the
publish-time artifacts are part of the key too, so a corpus that predates
full-text search republishes once), and the
PDF's sha256 matches the hash recorded for it in the part's inventory
(never mtime or size). ``--force``
disables the check; ``--no-cache`` (``use_cache=False``) also rebuilds,
matching ``dsa build --no-cache``'s full-redo semantics. A changed PDF is
re-registered under its new identity before building, so the rebuilt part is
keyed on the current bytes and later runs skip it again.

Dispatch: jobs run through a bounded ``ThreadPoolExecutor`` (``--workers N``,
env ``DSA_BATCH_WORKERS`` default 4; ``workers=1`` is the serial path with
today's exact behavior). Each job is one independent unit running the full
pipeline, with its backend wiring, LLM client and fetchers created inside the
job — thread safety is by construction, no shared mutable pipeline state.
queued/skip decisions are taken in the main thread in run order; stage
events fire from the worker that runs the job; final states are emitted as
jobs complete and the report is assembled back in run order.

Event vocabulary (part of the runner's contract): every job transition emits
one event — ``queued``, a build stage (``extracting | structuring |
enriching | publishing``, fired by ``build_part``'s additive ``on_progress``
callback), or a final state (``done | failed | skipped``) — through the
``EventEmitter``: a prefixed, line-buffered terminal line and one JSON object
appended to the run's JSONL under
``.cache/batches/<dirstem>-<run>/batch.jsonl`` (header event first, carrying
the full job list). The JSONL is the authoritative monitoring record —
tailable, greppable by part; failed and skipped jobs appear there with their
detail (failed events additionally carry a traceback summary). The emitter
lock keeps every terminal line and JSONL record whole under parallelism.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from datasheet_analyzer.acquire.inventory import load_inventory, register_source, save_inventory
from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.extract.base import get_backend
from datasheet_analyzer.extract.pdf_structure import compute_content_hash
from datasheet_analyzer.models import CorpusManifest, CorpusStats
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.protocol import agent_doc_current
from datasheet_analyzer.publish import (
    doc_dir_name_for_source,
    pins_current,
    plots_current,
    search_index_current,
    specs_current,
)
from datasheet_analyzer.vendor import select_backend

STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


class BatchError(Exception):
    """Pre-flight batch error: missing or empty source directory."""


@dataclass(frozen=True)
class BatchJob:
    """One (pdf, part) build unit derived from the source directory."""

    pdf_path: Path
    part: str


@dataclass
class JobResult:
    """Outcome of one job as recorded in the batch report."""

    part: str
    pdf_path: str
    status: str
    error: str = ""
    traceback: str = ""
    stages: list[str] = field(default_factory=list)
    stats: CorpusStats | None = None


@dataclass
class BatchReport:
    """Per-job outcomes plus derived summary — the batch's observable result."""

    jobs: list[JobResult]

    @property
    def ok(self) -> bool:
        """True when every job passed (done or skipped)."""
        return all(j.status != STATUS_FAILED for j in self.jobs)

    @property
    def counts(self) -> dict[str, int]:
        """Per-status counts keyed by the STATUS_* constants."""
        return {
            status: sum(j.status == status for j in self.jobs)
            for status in (STATUS_DONE, STATUS_FAILED, STATUS_SKIPPED)
        }


def log_path_for(batch_dir: Path, run_start: datetime, settings: Settings) -> Path:
    """Per-run JSONL path: cache/batches/<dirstem>-<run-start>/batch.jsonl.

    The directory name identifies both the source directory and the run, so
    concurrent runs of the same or different batches never collide; each run
    appends events to its own file.
    """
    stem = re.sub(r'[\\/:*?"<>|]', "_", batch_dir.stem)
    stamp = run_start.strftime("%Y%m%d-%H%M%S-%f")
    return settings.cache_dir / "batches" / f"{stem}-{stamp}" / "batch.jsonl"


class EventEmitter:
    """Dual-sink stage-event emitter: terminal line + JSONL append.

    One ``emit`` per transition; the event is a single JSON object carrying
    job id, part, stage, ISO timestamp and detail (further fields via
    ``extra``). The terminal line is prefixed ``[<job>/<total>] <part>:
    <stage>`` (or ``batch: <stage>`` for run-level events), and the JSONL
    append happens under the same lock, so a line or record is never
    interleaved with another event's — even under the parallelism of later
    tickets. A log sink that cannot be opened degrades to a one-time warning:
    monitoring must never take a build down.
    """

    def __init__(self, log_path: Path, total: int) -> None:
        self._log_path = log_path
        self._total = total
        self._lock = threading.Lock()
        self._log_warned = False

    def _sink(
        self,
        job_id: int | None,
        part: str | None,
        stage: str,
        detail: str = "",
        extra: dict | None = None,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "job": job_id,
            "part": part,
            "stage": stage,
            "detail": detail,
        }
        if extra:
            event.update(extra)
        if job_id is None:
            text = f"batch: {stage}"
        else:
            text = f"[{job_id}/{self._total}] {part}: {stage}"
        if detail:
            text += f" ({detail.replace(chr(10), ' ')})"
        with self._lock:
            print(text, flush=True)
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=True) + "\n")
            except OSError:
                if not self._log_warned:
                    self._log_warned = True
                    print(f"batch log unavailable: {self._log_path}", file=sys.stderr)

    def emit(
        self,
        job_id: int,
        part: str,
        stage: str,
        detail: str = "",
        extra: dict | None = None,
    ) -> None:
        """Emit one job transition to both sinks."""
        self._sink(job_id, part, stage, detail, extra=extra)

    def header(self, batch_dir: Path, jobs: list[BatchJob]) -> None:
        """Run-level header event carrying the full job list in run order."""
        job_list = [
            {"job": idx, "part": j.part, "pdf": j.pdf_path.name}
            for idx, j in enumerate(jobs, 1)
        ]
        self._sink(None, None, "header", str(batch_dir), {"jobs": job_list})


def discover_jobs(batch_dir: Path) -> list[BatchJob]:
    """Flat, case-insensitive ``*.pdf`` scan of direct children, sorted.

    Raises ``BatchError`` when the directory is missing — the same failure
    vocabulary the rest of the runner uses.
    """
    batch_dir = Path(batch_dir)
    if not batch_dir.is_dir():
        raise BatchError(f"batch directory not found: {batch_dir}")
    pdfs = sorted(p for p in batch_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    return [BatchJob(pdf_path=p, part=p.stem.upper()) for p in pdfs]


def _same_path(recorded: str, pdf_path: Path) -> bool:
    """Whether a recorded source path names ``pdf_path``'s file.

    The inventory stores the path as spelled at registration time; CLI
    re-spellings (relative vs absolute, separators, case) must not defeat the
    match, so both sides are resolved before comparing.
    """
    return Path(recorded).resolve() == pdf_path.resolve()


def _refresh_pdf_source(job: BatchJob, settings: Settings) -> None:
    """Re-register ``job.pdf_path`` under its current bytes in the inventory.

    A changed PDF keeps its old hash in the inventory until this runs; without
    the refresh the part would rebuild on every subsequent run (its recorded
    identity never matches) and the corpus would stay keyed on stale bytes.
    Only entries naming this file are touched, so companions added via
    ``add-doc`` are untouched. No-op when the path is not in the inventory or
    the recorded hash already matches.
    """
    part_dir = settings.parts_dir / job.part
    inventory = load_inventory(part_dir)
    current = compute_content_hash(job.pdf_path)
    stale = [
        s for s in inventory
        if _same_path(s.path, job.pdf_path) and s.content_hash != current
    ]
    if not stale:
        return
    fresh = register_source(job.pdf_path, part_number=job.part, doc_type="datasheet")
    kept = [s for s in inventory if not _same_path(s.path, job.pdf_path)]
    kept.append(fresh)
    save_inventory(kept, part_dir)


def _extractor_stale(manifest: CorpusManifest) -> bool:
    """True when any published document was built by a superseded extractor.

    Compares each document's recorded ``extractor_version`` against the
    ``output_version`` the backend its vendor routes to emits today. A missing
    stats entry or an unknown backend counts as stale: the gate's contract is
    that whatever it cannot verify must rebuild.
    """
    for doc in manifest.documents:
        recorded = manifest.extraction_stats.get(doc.content_hash)
        if recorded is None:
            return True
        try:
            backend = get_backend(select_backend(doc.vendor, doc.doc_type))
        except KeyError:
            return True
        if recorded.extractor_version != getattr(backend, "output_version", ""):
            return True
    return False


def _publish_artifacts_stale(
    part_dir: Path, manifest: CorpusManifest, card_version: str
) -> bool:
    """True when a published document is missing a current publish artifact.

    Extraction is not the only thing that can go out of date: the publish
    stage writes derived artifacts too, and a corpus published before
    `search_index.json` existed (or against an older `SEARCH_SCHEMA_VERSION`)
    would answer `dsa search` with nothing at all. Making the search index
    part of the skip gate is what "caching keyed by identity" means for a
    publish-time schema — the corpus republishes once and then skips again.

    `specs.json`, `plots.json` and `pins.json` are the same kind of artifact
    and are gated the same way, on `SPECS_SCHEMA_VERSION` /
    `PLOTS_SCHEMA_VERSION` / `PINS_SCHEMA_VERSION`. Without
    that, a part whose extractor version did not move — every `ti_html` part,
    since the layout engine's `output_version` bumps say nothing about TI's
    HTML path — would keep pre-`confidence` records forever and answer every
    query ungraded. Nothing here re-derives a grade: the gate only decides
    whether to republish, and grading stays where it belongs, at structure
    time.

    `AGENT.md` (ticket 08) is gated the same way, on its own embedded
    protocol marker: a corpus published before the protocol existed would
    otherwise skip forever and ship no protocol beside its index.

    `card_version` (ADR 0005) is the same rule for *derived* artifacts, and it
    is the only gate that can catch them: a derivation rule is code, not
    input, so changing one moves no source byte and neither the content hash
    nor the extractor version notices. A corpus derived under a different rule
    set therefore republishes once rather than serving stale cards forever.
    """
    if manifest.card_version != card_version:
        return True
    if not agent_doc_current(part_dir):
        return True
    for doc in manifest.documents:
        doc_dir = part_dir / "docs" / doc_dir_name_for_source(doc)
        if not search_index_current(doc_dir):
            return True
        if not specs_current(doc_dir) or not plots_current(doc_dir):
            return True
        if not pins_current(doc_dir):
            return True
    return False


def skip_reason(job: BatchJob, *, settings: Settings, force: bool = False) -> str:
    """Nonempty reason to skip ``job``, or "" when it must build.

    A job is skipped only when the part's corpus manifest exists, records the
    current ``PIPELINE_VERSION``, every published document's recorded
    ``extractor_version`` still matches what its backend produces today,
    every published document carries current-schema publish artifacts —
    ``search_index.json``, a ``specs.json`` / ``plots.json`` of the
    current schema wherever one was written, the part's ``AGENT.md`` at
    the current protocol version, and a manifest stamped with the current
    ``card_version`` (``_publish_artifacts_stale``) —
    and
    the PDF's sha256 matches the hash of the document recorded for this file
    in the part's inventory AND the manifest's published documents
    (`content_hash` is the source document's identity — never mtime or size).
    Requiring the hash among the published documents means a failed rebuild
    can never arm the skip on a stale corpus. ``force`` bypasses the whole
    check. Missing, corrupt or version-stale manifests and unknown hashes all
    mean build (a changed PDF is re-registered by the build path, restoring
    the skip condition for later runs). Never raises: any failure to verify
    means "not safe to skip".

    The extractor check is separate from ``PIPELINE_VERSION`` on purpose. The
    layout engine bumps its own ``output_version`` (tables-05 -> 06 -> 07 -> 08)
    without necessarily moving ``PIPELINE_VERSION``; ``build_part`` already
    invalidates a stale *extraction cache* that way, but a batch run that
    skips the job never reaches that code, so without this the gate would
    serve corpora built by a superseded extractor.
    """
    if force:
        return ""
    part_dir = settings.parts_dir / job.part
    try:
        manifest_path = part_dir / "manifest.json"
        if not manifest_path.exists():
            return ""
        manifest = CorpusManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if manifest.pipeline_version != PIPELINE_VERSION:
            return ""
        if _extractor_stale(manifest):
            return ""
        if _publish_artifacts_stale(part_dir, manifest, settings.card_version):
            return ""
        pdf_hash = compute_content_hash(job.pdf_path)
        published = {s.content_hash for s in manifest.documents}
        entries = [
            s for s in load_inventory(part_dir) if _same_path(s.path, job.pdf_path)
        ]
        if any(s.content_hash == pdf_hash for s in entries) and pdf_hash in published:
            return (f"already built: PDF sha256, pipeline version "
                    f"{PIPELINE_VERSION} and extractor versions match")
        return ""
    except (OSError, ValueError):  # JSONDecodeError etc. — never raise
        return ""


def run_job(
    job: BatchJob,
    *,
    settings: Settings,
    use_cache: bool,
    use_llm: bool,
    on_progress: Callable[[str], None] | None = None,
) -> JobResult:
    """Build one part, isolating failures: any exception becomes a failed result.

    Before building, the inventory is refreshed to the PDF's current bytes (a
    no-op unless the recorded hash is stale), so a rebuild triggered by the
    hash gate publishes a corpus keyed on the new identity. The refresh runs
    inside the error boundary: a failure here is an ordinary failed job.
    ``on_progress`` receives every stage transition as it fires (see
    ``build_part``); the observed stages land in ``JobResult.stages``.
    """
    stages: list[str] = []

    def _forward(stage: str) -> None:
        stages.append(stage)
        if on_progress is not None:
            on_progress(stage)

    try:
        _refresh_pdf_source(job, settings)
        result = build_part(
            job.pdf_path,
            part_number=job.part,
            settings=settings,
            use_cache=use_cache,
            use_llm=use_llm,
            on_progress=_forward,
        )
        return JobResult(
            part=job.part,
            pdf_path=str(job.pdf_path),
            status=STATUS_DONE,
            stages=stages,
            stats=result.manifest.stats,
        )
    except Exception as exc:  # noqa: BLE001 — failure isolation is the point
        return JobResult(
            part=job.part,
            pdf_path=str(job.pdf_path),
            status=STATUS_FAILED,
            stages=stages,
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
        )


def _print_mapping(batch_dir: Path, jobs: list[BatchJob]) -> None:
    print(f"batch: {len(jobs)} PDF(s) in {batch_dir}")
    for j in jobs:
        print(f"  {j.pdf_path.name} -> {j.part}")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _details(job: JobResult) -> str:
    """One-line detail for a job outcome: stats for done, reason/error else."""
    if job.status == STATUS_DONE:
        stats = job.stats
        return (
            f"{_plural(stats.n_sections, 'section')}, {_plural(stats.n_tables, 'table')}"
            if stats
            else "built"
        )
    if job.status == STATUS_SKIPPED:
        return job.error or "up to date"
    return job.error or "unknown error"


def _emit_final(emitter: EventEmitter, idx: int, result: JobResult) -> None:
    """Emit a job's final state (terminal + JSONL) with its traceback extra."""
    extra = {"traceback": result.traceback} if result.traceback else None
    emitter.emit(idx, result.part, result.status, _details(result), extra=extra)


def _dispatch_job(
    idx: int,
    job: BatchJob,
    *,
    emitter: EventEmitter,
    settings: Settings,
    use_cache: bool,
    use_llm: bool,
    force: bool,
    completed: dict[int, JobResult],
    executor: ThreadPoolExecutor | None = None,
    pending: dict[Future, int] | None = None,
) -> None:
    """Run one job at its dispatch point: queue, skip, then either run inline
    (serial path, ``executor=None``) or submit to the pool.

    With ``executor`` the build's stage events fire from the worker thread;
    the final event is emitted by the collector, not here. Without it the
    whole job — stages and final — completes before this call returns, which
    is what makes ``workers=1`` byte-for-byte the serial path.
    """
    emitter.emit(idx, job.part, "queued")
    reason = skip_reason(job, settings=settings, force=force) if use_cache else ""
    if reason:
        completed[idx] = JobResult(
            part=job.part,
            pdf_path=str(job.pdf_path),
            status=STATUS_SKIPPED,
            error=reason,
        )
        emitter.emit(idx, job.part, STATUS_SKIPPED, reason)
        return

    def _progress(stage: str) -> None:
        emitter.emit(idx, job.part, stage)

    if executor is None:
        result = run_job(
            job,
            settings=settings,
            use_cache=use_cache,
            use_llm=use_llm,
            on_progress=_progress,
        )
        completed[idx] = result
        _emit_final(emitter, idx, result)
    else:
        future = executor.submit(
            run_job,
            job,
            settings=settings,
            use_cache=use_cache,
            use_llm=use_llm,
            on_progress=_progress,
        )
        pending[future] = idx


def _print_summary(report: BatchReport) -> None:
    counts = report.counts
    print("# Batch summary")
    print(f"{len(report.jobs)} jobs: {counts['done']} done, {counts['failed']} failed, "
          f"{counts['skipped']} skipped")
    print()
    print("| # | Part | Status | Detail |")
    print("|---|------|--------|--------|")
    for idx, job in enumerate(report.jobs, 1):
        print(f"| {idx} | {job.part} | {job.status} | {_details(job)} |")


def run_batch(
    batch_dir: Path,
    *,
    settings: Settings,
    use_cache: bool = True,
    use_llm: bool = True,
    force: bool = False,
    workers: int = 1,
) -> BatchReport:
    """Build every PDF directly inside ``batch_dir`` as one part corpus each.

    Parts that are already built with the current pipeline version and whose
    PDF bytes are unchanged are skipped (``skip_reason``); ``force`` rebuilds
    everything. ``use_cache=False`` also disables skipping (full redo, like
    ``dsa build --no-cache``).

    Dispatch: ``workers`` controls a bounded thread pool (default 1 = the
    serial path). Each job runs the full pipeline inside its own error
    boundary with job-scoped wiring, so a failing or slow job never disturbs
    another. Every job transition is emitted through an ``EventEmitter`` —
    one prefixed terminal line and one JSONL record under
    ``.cache/batches/`` (see ``log_path_for``); the JSONL is the monitoring
    source of truth. The report is assembled in run (sorted) order no matter
    which order jobs complete. Returns a ``BatchReport``; raises
    ``BatchError`` for a missing or empty directory (the CLI maps that to
    exit code 2).
    """
    batch_dir = Path(batch_dir)
    jobs = discover_jobs(batch_dir)
    if not jobs:
        raise BatchError(f"no PDF files in {batch_dir}")
    _print_mapping(batch_dir, jobs)

    run_start = datetime.now(timezone.utc)
    log_path = log_path_for(batch_dir, run_start, settings)
    emitter = EventEmitter(log_path, total=len(jobs))
    emitter.header(batch_dir, jobs)
    print(f"batch log: {log_path}")

    # Dispatch. workers=1 is the serial path: one job fully runs (and its
    # events fully flush) before the next is even queued — byte-for-byte the
    # behavior of earlier releases. workers>1 runs jobs in a bounded thread
    # pool: queued + skip decisions are taken here in run order, builds run
    # in workers with job-scoped wiring, and final states are emitted as jobs
    # complete (live terminal/JSONL). run_job never raises — failure
    # isolation turns every exception into a failed result. (Settings
    # validation rejects ``batch_workers < 1``; a direct zero/negative
    # ``workers`` argument raises in the pool boundary instead of silently
    # clamping.)
    completed: dict[int, JobResult] = {}
    if workers == 1:
        for idx, job in enumerate(jobs, 1):
            _dispatch_job(
                idx, job, emitter=emitter, settings=settings,
                use_cache=use_cache, use_llm=use_llm, force=force,
                completed=completed,
            )
    else:
        pending: dict[Future, int] = {}
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="dsa-batch"
        ) as executor:
            for idx, job in enumerate(jobs, 1):
                _dispatch_job(
                    idx, job, emitter=emitter, settings=settings,
                    use_cache=use_cache, use_llm=use_llm, force=force,
                    completed=completed, executor=executor, pending=pending,
                )

            for future in as_completed(pending):
                idx = pending[future]
                result = future.result()
                completed[idx] = result
                _emit_final(emitter, idx, result)

    results = [completed[idx] for idx in range(1, len(jobs) + 1)]
    report = BatchReport(jobs=results)
    _print_summary(report)
    return report


# Public surface: the CLI uses run_batch/BatchError; run_job, discover_jobs,
# skip_reason, EventEmitter and log_path_for are the seams the
# parallel-dispatch ticket extends.
__all__ = [
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
    "BatchError",
    "BatchJob",
    "BatchReport",
    "EventEmitter",
    "JobResult",
    "discover_jobs",
    "log_path_for",
    "run_batch",
    "run_job",
    "skip_reason",
]
