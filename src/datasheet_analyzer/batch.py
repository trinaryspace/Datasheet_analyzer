"""Batch runner: one invocation builds every PDF in a directory as its own part.

The batch is just a directory — its content *is* the specification. Direct
children matching ``*.pdf`` (case-insensitive) become jobs in sorted filename
order; the part number of each job is the filename stem uppercased. Each job
runs the existing single-part pipeline end to end via ``build_part`` inside
its own error boundary: a failing job records its error and every remaining
job still runs. The run prints the file -> part mapping before any work
starts and a per-job summary table at the end; ``BatchReport.ok`` is False
when any job failed (the CLI maps that to exit code 1).

Status vocabulary (part of the runner's contract):
``queued | running:<stage> | done | failed | skipped`` — this serial runner
emits the final states ``done`` / ``failed`` (``skipped`` lands with the
hash-gated skip); stage transitions belong to the event emitter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import CorpusStats
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


def run_job(
    job: BatchJob,
    *,
    settings: Settings,
    use_cache: bool,
    use_llm: bool,
) -> JobResult:
    """Build one part, isolating failures: any exception becomes a failed result."""
    try:
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
) -> BatchReport:
    """Build every PDF directly inside ``batch_dir`` as one part corpus each.

    Returns a ``BatchReport``; raises ``BatchError`` for a missing or empty
    directory (the CLI maps that to exit code 2).
    """
    batch_dir = Path(batch_dir)
    jobs = discover_jobs(batch_dir)
    if not jobs:
        raise BatchError(f"no PDF files in {batch_dir}")
    _print_mapping(batch_dir, jobs)

    results: list[JobResult] = []
    total = len(jobs)
    for idx, job in enumerate(jobs, 1):
        print(f"[{idx}/{total}] building {job.part} from {job.pdf_path.name}")
        result = run_job(job, settings=settings, use_cache=use_cache, use_llm=use_llm)
        mark = "done" if result.status == STATUS_DONE else "failed"
        print(f"[{idx}/{total}] {job.part}: {mark}")
        results.append(result)

    report = BatchReport(jobs=results)
    _print_summary(report)
    return report


# Public surface: the CLI uses run_batch/BatchError; run_job and discover_jobs
# are the seams the parallel-dispatch and hash-gate tickets extend.
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
]
