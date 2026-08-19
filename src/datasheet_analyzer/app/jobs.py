"""Analyze runs: background build jobs and their live event feed (ticket 07).

Building thirty datasheets is minutes to hours, so `POST /api/analyze/start`
must not be the request that waits for it. `JobRegistry.start()` records the
run, hands back a `run_id`, and returns; a driver thread dispatches one
`AnalyzeJob` per confirmed `DocProposal` into a bounded pool sized by
`settings.analyze_workers`. A part becomes askable the moment *its own* job
reaches `DONE` — nothing waits for the run.

**`batch.py` is the runner, not a template.** Bounded-pool dispatch,
per-job failure isolation, the hash-gated skip and the
`extracting | structuring | enriching | publishing` stage callback all already
exist there and are called from here: `skip_reason()` decides a skip,
`pipeline.build_part(..., on_progress=...)` fires the stages, and this module
adds only what `batch.py` has no reason to know about — an in-memory run
registry and an async fan-out so a browser can watch.

Three things about that fan-out are load-bearing:

- **Two clients may watch one run.** `events()` hands each caller its own
  `_Feed` rather than a shared queue that one reader would drain from the
  other.
- **Producers are threads, consumers are coroutines.** A job transition is
  published from a pool worker and delivered on the consumer's event loop via
  `call_soon_threadsafe`; a feed buffers into a deque until a consumer is
  actually waiting, so an event emitted before anyone awaits is queued, never
  dropped.
- **A late client is never blank.** `snapshot()` is the frame the stream opens
  with, and `events()` is only "from here on" — which is why the router
  subscribes *before* it reads the snapshot: a duplicate transition is
  harmless, a lost one is not.

The build itself is injectable (`build=`, `skip_check=`). That is what lets
this module be tested against a stub that emits stages in milliseconds, with
no model call and no PDF parsing, while the default wiring is the real
pipeline.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from datasheet_analyzer.acquire.inventory import register_source
from datasheet_analyzer.app.contracts import (
    AnalyzeJob,
    DocProposal,
    JobEvent,
    RunSnapshot,
)
from datasheet_analyzer.batch import BatchJob
from datasheet_analyzer.batch import skip_reason as batch_skip_reason
from datasheet_analyzer.config import Settings, get_settings
from datasheet_analyzer.library.store import LibraryStore
from datasheet_analyzer.models import JobState, LibraryDocument
from datasheet_analyzer.pipeline import build_part

log = logging.getLogger(__name__)

__all__ = [
    "STAGE_STATES",
    "BuildCallable",
    "JobRegistry",
    "RunNotFound",
    "SkipCallable",
    "build_job",
    "default_registry",
    "record_applicability",
    "reset_default_registry",
]


class RunNotFound(KeyError):
    """No run with this id — the router turns it into a 404."""


#: `build_part`'s stage vocabulary, mapped onto the job states the GUI shows.
#: The mapping exists so the runner's names stay the single vocabulary: a
#: stage the pipeline does not emit cannot appear on the stream.
STAGE_STATES: dict[str, JobState] = {
    "extracting": JobState.EXTRACTING,
    "structuring": JobState.STRUCTURING,
    "enriching": JobState.ENRICHING,
    "publishing": JobState.PUBLISHING,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BuildCallable(Protocol):
    """How a job is built. Raising is how a job fails — nothing else."""

    def __call__(
        self,
        job: AnalyzeJob,
        *,
        settings: Settings,
        on_progress: Callable[[str], None],
    ) -> None: ...


class SkipCallable(Protocol):
    """Nonempty reason to skip this job, or `""` to build it."""

    def __call__(self, job: AnalyzeJob, *, settings: Settings) -> str: ...


# --- the default wiring: the real library and the real pipeline ---------------


def record_applicability(
    job: AnalyzeJob,
    *,
    settings: Settings,
    store: LibraryStore | None = None,
) -> LibraryDocument | None:
    """Put the *confirmed* applicability into the library, before building.

    The review screen's whole purpose is that a user can correct what
    inference proposed, so the job carries `applicability` and this writes
    exactly that — the build never re-infers. It runs before `build_part` so
    the document is already in the library when the build resolves the part's
    document set from it (ticket 03).

    Ticket 03 owns `acquire.inventory.register_into_library` and this calls it
    when it is there; the `register_source` + `LibraryStore.put` fallback below
    is the same record assembled from the two frozen pieces, so a build here
    never depends on which of the two tickets landed first. Neither path pins a
    vendor or a doc type by hand: both stay evidence-detected at acquire time
    (ADR 0002), and the only thing this function asserts is the applicability.
    """
    library = store if store is not None else LibraryStore.for_settings(settings)
    pdf_path = Path(job.pdf_path)
    register_into_library = _register_into_library()
    if register_into_library is not None:
        kwargs: dict[str, object] = {"applicability": job.applicability, "store": library}
        if "part_number" in inspect.signature(register_into_library).parameters:
            kwargs["part_number"] = job.part_number
        return register_into_library(pdf_path, **kwargs)
    source = register_source(pdf_path, part_number=job.part_number)
    document = LibraryDocument(source=source, applicability=job.applicability)
    library.put(document)
    return document


def _register_into_library() -> Callable[..., LibraryDocument | None] | None:
    """Ticket 03's helper if it has landed, else `None`. Never imports eagerly."""
    from datasheet_analyzer.acquire import inventory

    helper = getattr(inventory, "register_into_library", None)
    return helper if callable(helper) else None


def build_job(
    job: AnalyzeJob,
    *,
    settings: Settings,
    on_progress: Callable[[str], None],
) -> None:
    """The real build: record the confirmed applicability, then `build_part`."""
    record_applicability(job, settings=settings)
    build_part(
        Path(job.pdf_path),
        part_number=job.part_number,
        settings=settings,
        on_progress=on_progress,
    )


def default_skip_check(job: AnalyzeJob, *, settings: Settings) -> str:
    """`batch.skip_reason` verbatim — one hash gate, not two implementations."""
    return batch_skip_reason(
        BatchJob(pdf_path=Path(job.pdf_path), part=job.part_number),
        settings=settings,
        force=False,
    )


# --- the async fan-out --------------------------------------------------------


class _Feed:
    """One client's independent view of a run's transitions.

    Events are pushed from pool worker threads and consumed on an event loop.
    Both sides go through one `threading.Lock`: a push with no consumer
    waiting buffers into `_pending`, a push with one waiting resolves that
    consumer's future on *its* loop. `None` is the end marker and ends the
    iteration, which is how "the stream closes once all jobs are terminal"
    reaches the router.
    """

    def __init__(self, on_close: Callable[[_Feed], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._pending: deque[JobEvent | None] = deque()
        self._waiter: asyncio.Future[JobEvent | None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_close = on_close
        self._ended = False
        self._detached = False

    # -- producer side (any thread) --
    def push(self, event: JobEvent | None) -> None:
        """Publish one event, or `None` to end the feed. Never blocks."""
        with self._lock:
            if self._ended:
                return
            if event is None:
                self._ended = True
            waiter = self._waiter
            loop = self._loop
            if waiter is None or loop is None:
                self._pending.append(event)
                return
            self._waiter = None
        loop.call_soon_threadsafe(self._deliver, waiter, event)

    def _deliver(self, waiter: asyncio.Future[JobEvent | None], event: JobEvent | None) -> None:
        """Hand an event to a waiting consumer, on that consumer's loop.

        A consumer whose wait was cancelled between the push and this callback
        (the heartbeat timeout does exactly that) has not seen the event, so it
        goes back to the head of the queue rather than into a dead future.
        """
        if waiter.done():
            with self._lock:
                self._pending.appendleft(event)
            return
        waiter.set_result(event)

    # -- consumer side (one event loop) --
    def __aiter__(self) -> _Feed:
        return self

    async def __anext__(self) -> JobEvent:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._pending:
                item = self._pending.popleft()
                waiter = None
            else:
                self._loop = loop
                waiter = loop.create_future()
                self._waiter = waiter
        if waiter is not None:
            try:
                item = await waiter
            except asyncio.CancelledError:
                with self._lock:
                    if self._waiter is waiter:
                        self._waiter = None
                raise
        if item is None:
            raise StopAsyncIteration
        return item

    def close(self) -> None:
        """Detach from the run and end the iteration. Idempotent."""
        with self._lock:
            already = self._detached
            self._detached = True
            on_close = self._on_close
        if not already and on_close is not None:
            on_close(self)
        self.push(None)


@dataclass
class _Run:
    """One analyze run: its jobs, its history and its connected clients."""

    run_id: str
    directory: str
    jobs: list[AnalyzeJob]
    lock: threading.Lock = field(default_factory=threading.Lock)
    history: list[JobEvent] = field(default_factory=list)
    feeds: list[_Feed] = field(default_factory=list)
    done: bool = False
    finished: threading.Event = field(default_factory=threading.Event)


class JobRegistry:
    """The process-wide analyze registry (`JobRegistryLike`).

    Process-wide on purpose: a run outlives the request that started it, and a
    second client must be able to attach to the stream of a run someone else
    started.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        build: BuildCallable | None = None,
        skip_check: SkipCallable | None = None,
        workers: int | None = None,
        use_cache: bool = True,
    ) -> None:
        self._settings = settings
        self._build: BuildCallable = build or build_job
        self._skip_check: SkipCallable = skip_check or default_skip_check
        self._workers = workers
        self._use_cache = use_cache
        self._runs: dict[str, _Run] = {}
        self._lock = threading.Lock()

    # -- configuration --
    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    @property
    def workers(self) -> int:
        """The pool bound: the explicit override, else `analyze_workers`."""
        return max(1, self._workers or self.settings.analyze_workers)

    # -- the frozen surface (`contracts.JobRegistryLike`) --
    def start(self, *, directory: str, proposals: Sequence[DocProposal]) -> str:
        """Create a run, dispatch it on a background thread, return at once.

        Nothing here touches a PDF: the return is a dict insert and a thread
        start, so the response time does not depend on the number of PDFs.
        """
        run_id = uuid.uuid4().hex[:12]
        jobs = [self._job_for(run_id, index, p) for index, p in enumerate(proposals, 1)]
        run = _Run(run_id=run_id, directory=directory, jobs=jobs)
        with self._lock:
            self._runs[run_id] = run
        threading.Thread(
            target=self._drive,
            args=(run,),
            name=f"dsa-analyze-{run_id}",
            daemon=True,
        ).start()
        return run_id

    def exists(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._runs

    def run(self, run_id: str) -> list[AnalyzeJob]:
        """Snapshot of every job, in dispatch order — copies, not live models."""
        run = self._get(run_id)
        with run.lock:
            return [job.model_copy(deep=True) for job in run.jobs]

    def snapshot(self, run_id: str) -> RunSnapshot:
        """The frame the stream opens with: every job's current state."""
        run = self._get(run_id)
        with run.lock:
            jobs = [job.model_copy(deep=True) for job in run.jobs]
            done = run.done
        return RunSnapshot(run_id=run.run_id, directory=run.directory, jobs=jobs, done=done)

    def events(self, run_id: str) -> AsyncIterator[JobEvent]:
        """An independent feed of every transition from now on.

        Registration happens *here*, not on the first `__anext__`, so a caller
        that subscribes and then reads the snapshot cannot lose a transition
        in between. A run that is already finished hands back a feed that ends
        immediately — the snapshot already told that client everything.
        """
        run = self._get(run_id)
        feed = _Feed(on_close=lambda f: self._detach(run, f))
        with run.lock:
            finished = run.done
            if not finished:
                run.feeds.append(feed)
        if finished:
            feed.push(None)
        return feed

    # -- additions (a `Protocol` may be widened, not narrowed) --
    def history(self, run_id: str) -> list[JobEvent]:
        """Every transition so far, in emission order."""
        run = self._get(run_id)
        with run.lock:
            return list(run.history)

    def wait(self, run_id: str, timeout: float = 60.0) -> bool:
        """Block until every job is terminal; False on timeout."""
        return self._get(run_id).finished.wait(timeout)

    def runs(self) -> list[str]:
        with self._lock:
            return list(self._runs)

    # -- internals --
    def _get(self, run_id: str) -> _Run:
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    def _job_for(self, run_id: str, index: int, proposal: DocProposal) -> AnalyzeJob:
        """One job per proposal, using the *confirmed* values verbatim.

        The part number falls back to the filename stem the way `batch.py`
        derives one, so a proposal whose part number a user cleared still
        builds something named after its file rather than an empty part.
        """
        part_number = (proposal.part_number or "").strip().upper()
        if not part_number:
            part_number = Path(proposal.pdf_path).stem.upper()
        return AnalyzeJob(
            id=f"{run_id}-{index}",
            pdf_path=proposal.pdf_path,
            part_number=part_number,
            applicability=proposal.applicability.model_copy(deep=True),
            state=JobState.QUEUED,
        )

    def _drive(self, run: _Run) -> None:
        """Dispatch every job, bounded by `workers`, then close the run.

        `workers == 1` is the serial path (one job fully finishes before the
        next is queued), which is what makes an event sequence assertable.
        Above that, queue decisions are taken here in run order and builds run
        in the pool; `_execute` never raises, so one failure never stops
        dispatch.
        """
        try:
            workers = self.workers
            if not run.jobs:
                return
            if workers == 1:
                for job in run.jobs:
                    self._emit(run, job, JobState.QUEUED)
                    self._execute(run, job)
                return
            pending: list[Future[None]] = []
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dsa-analyze") as pool:
                for job in run.jobs:
                    self._emit(run, job, JobState.QUEUED)
                    pending.append(pool.submit(self._execute, run, job))
                for future in as_completed(pending):
                    future.result()
        finally:
            self._finish(run)

    def _execute(self, run: _Run, job: AnalyzeJob) -> None:
        """Run one job inside its own error boundary. Never raises.

        Failure isolation is the point: an exception becomes this job's
        `FAILED` state with the error text attached, and every other job keeps
        running.
        """
        settings = self.settings
        reason = ""
        if self._use_cache:
            try:
                reason = self._skip_check(job, settings=settings)
            except Exception:  # noqa: BLE001 - an unverifiable gate means build
                reason = ""
        if reason:
            self._emit(run, job, JobState.SKIPPED, detail=reason)
            return
        with run.lock:
            job.started_at = _utcnow()
        try:
            self._build(
                job,
                settings=settings,
                on_progress=lambda stage: self._on_stage(run, job, stage),
            )
        except Exception as exc:  # noqa: BLE001 - failure isolation is the point
            self._emit(
                run,
                job,
                JobState.FAILED,
                detail=f"{type(exc).__name__}: {exc}",
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        self._emit(run, job, JobState.DONE, detail="built")

    def _on_stage(self, run: _Run, job: AnalyzeJob, stage: str) -> None:
        """`build_part`'s stage callback, translated into one job transition."""
        state = STAGE_STATES.get(stage)
        if state is None:
            return
        self._emit(run, job, state)

    def _emit(
        self,
        run: _Run,
        job: AnalyzeJob,
        state: JobState,
        *,
        detail: str = "",
        error: str = "",
    ) -> None:
        """Record a transition on the job, the history and every feed."""
        with run.lock:
            job.state = state
            job.detail = detail
            if error:
                job.error = error
            if state.terminal:
                job.finished_at = _utcnow()
            event = JobEvent(
                run_id=run.run_id,
                job_id=job.id,
                part_number=job.part_number,
                pdf_path=job.pdf_path,
                state=state,
                detail=detail,
            )
            run.history.append(event)
            feeds = list(run.feeds)
        for feed in feeds:
            feed.push(event)

    def _finish(self, run: _Run) -> None:
        """Mark the run done and end every connected stream."""
        with run.lock:
            run.done = True
            feeds = list(run.feeds)
            run.feeds.clear()
        for feed in feeds:
            feed.push(None)
        run.finished.set()

    def _detach(self, run: _Run, feed: _Feed) -> None:
        with run.lock:
            if feed in run.feeds:
                run.feeds.remove(feed)


_DEFAULT_REGISTRY: JobRegistry | None = None
_DEFAULT_LOCK = threading.Lock()


def default_registry() -> JobRegistry:
    """The one registry `app.deps.get_job_registry` hands out (ticket 06)."""
    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        if _DEFAULT_REGISTRY is None:
            _DEFAULT_REGISTRY = JobRegistry()
        return _DEFAULT_REGISTRY


def reset_default_registry() -> None:
    """Test hook: drop the process-wide registry (mirrors the cache hooks)."""
    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        _DEFAULT_REGISTRY = None

