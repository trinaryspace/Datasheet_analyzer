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
the current ``PIPELINE_VERSION`` and the PDF's sha256 matches the hash
recorded for it in the part's inventory (never mtime or size). ``--force``
disables the check; ``--no-cache`` (``use_cache=False``) also rebuilds,
matching ``dsa build --no-cache``'s full-redo semantics. A changed PDF is
re-registered under its new identity before building, so the rebuilt part is
keyed on the current bytes and later runs skip it again.

Status vocabulary (part of the runner's contract):
``queued | running:<stage> | done | failed | skipped`` — this serial runner
emits the final states ``done`` / ``failed`` / ``skipped``; stage
transitions belong to the event emitter (ticket 03).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from datasheet_analyzer.acquire.inventory import load_inventory, register_source, save_inventory
from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.extract.pdf_structure import compute_content_hash
from datasheet_analyzer.models import CorpusManifest, CorpusStats
from datasheet_analyzer.pipeline import build_part

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


def skip_reason(job: BatchJob, *, settings: Settings, force: bool = False) -> str:
    """Nonempty reason to skip ``job``, or "" when it must build.

    A job is skipped only when the part's corpus manifest exists, records the
    current ``PIPELINE_VERSION``, and the PDF's sha256 matches the hash of the
    document recorded for this file in the part's inventory AND the manifest's
    published documents (`content_hash` is the source document's identity —
    never mtime or size). Requiring the hash among the published documents
    means a failed rebuild can never arm the skip on a stale corpus. ``force``
    bypasses the whole check. Missing, corrupt or version-stale manifests and
    unknown hashes all mean build (a changed PDF is re-registered by the build
    path, restoring the skip condition for later runs). Never raises: any
    failure to verify means "not safe to skip".
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
        pdf_hash = compute_content_hash(job.pdf_path)
        published = {s.content_hash for s in manifest.documents}
        entries = [
            s for s in load_inventory(part_dir) if _same_path(s.path, job.pdf_path)
        ]
        if any(s.content_hash == pdf_hash for s in entries) and pdf_hash in published:
            return (f"already built: PDF sha256 and pipeline version "
                    f"{PIPELINE_VERSION} match")
        return ""
    except (OSError, ValueError):  # JSONDecodeError etc. — never raise
        return ""


def run_job(
    job: BatchJob,
    *,
    settings: Settings,
    use_cache: bool,
    use_llm: bool,
) -> JobResult:
    """Build one part, isolating failures: any exception becomes a failed result.

    Before building, the inventory is refreshed to the PDF's current bytes (a
    no-op unless the recorded hash is stale), so a rebuild triggered by the
    hash gate publishes a corpus keyed on the new identity. The refresh runs
    inside the error boundary: a failure here is an ordinary failed job.
    """
    try:
        _refresh_pdf_source(job, settings)
        result = build_part(
            job.pdf_path,
            part_number=job.part,
            settings=settings,
            use_cache=use_cache,
            use_llm=use_llm,
        )
        return JobResult(
            part=job.part,
            pdf_path=str(job.pdf_path),
            status=STATUS_DONE,
            stats=result.manifest.stats,
        )
    except Exception as exc:  # noqa: BLE001 — failure isolation is the point
        return JobResult(
            part=job.part,
            pdf_path=str(job.pdf_path),
            status=STATUS_FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )


def _print_mapping(batch_dir: Path, jobs: list[BatchJob]) -> None:
    print(f"batch: {len(jobs)} PDF(s) in {batch_dir}")
    for j in jobs:
        print(f"  {j.pdf_path.name} -> {j.part}")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _print_summary(report: BatchReport) -> None:
    counts = report.counts
    print("# Batch summary")
    print(f"{len(report.jobs)} jobs: {counts['done']} done, {counts['failed']} failed, "
          f"{counts['skipped']} skipped")
    print()
    print("| # | Part | Status | Detail |")
    print("|---|------|--------|--------|")
    for idx, job in enumerate(report.jobs, 1):
        if job.status == STATUS_DONE:
            stats = job.stats
            detail = (
                f"{_plural(stats.n_sections, 'section')}, {_plural(stats.n_tables, 'table')}"
                if stats
                else "built"
            )
        elif job.status == STATUS_SKIPPED:
            detail = job.error or "up to date"
        else:
            detail = job.error or "unknown error"
        print(f"| {idx} | {job.part} | {job.status} | {detail} |")


def run_batch(
    batch_dir: Path,
    *,
    settings: Settings,
    use_cache: bool = True,
    use_llm: bool = True,
    force: bool = False,
) -> BatchReport:
    """Build every PDF directly inside ``batch_dir`` as one part corpus each.

    Parts that are already built with the current pipeline version and whose
    PDF bytes are unchanged are skipped (``skip_reason``); ``force`` rebuilds
    everything. ``use_cache=False`` also disables skipping (full redo, like
    ``dsa build --no-cache``). Returns a ``BatchReport``; raises
    ``BatchError`` for a missing or empty directory (the CLI maps that to
    exit code 2).
    """
    batch_dir = Path(batch_dir)
    jobs = discover_jobs(batch_dir)
    if not jobs:
        raise BatchError(f"no PDF files in {batch_dir}")
    _print_mapping(batch_dir, jobs)

    results: list[JobResult] = []
    total = len(jobs)
    for idx, job in enumerate(jobs, 1):
        if use_cache:
            reason = skip_reason(job, settings=settings, force=force)
        else:
            reason = ""
        if reason:
            results.append(
                JobResult(
                    part=job.part,
                    pdf_path=str(job.pdf_path),
                    status=STATUS_SKIPPED,
                    error=reason,
                )
            )
            print(f"[{idx}/{total}] {job.part}: skipped ({reason})")
            continue
        print(f"[{idx}/{total}] building {job.part} from {job.pdf_path.name}")
        result = run_job(job, settings=settings, use_cache=use_cache, use_llm=use_llm)
        mark = "done" if result.status == STATUS_DONE else "failed"
        print(f"[{idx}/{total}] {job.part}: {mark}")
        results.append(result)

    report = BatchReport(jobs=results)
    _print_summary(report)
    return report


# Public surface: the CLI uses run_batch/BatchError; run_job, discover_jobs
# and skip_reason are the seams the parallel-dispatch and events tickets extend.
__all__ = [
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
    "BatchError",
    "BatchJob",
    "BatchReport",
    "JobResult",
    "discover_jobs",
    "run_batch",
    "run_job",
    "skip_reason",
]
