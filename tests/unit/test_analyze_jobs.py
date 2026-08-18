"""Analyze runs: the registry, its event feed and the `/api/analyze` surface.

Hermetic by construction (AGENTS.md invariant 4): the build function is a
stub, so no PDF is parsed, no model is called and no network is touched. The
one real PDF here is three lines of `fitz` in a `tmp_path`, and it exists
only because `record_applicability` hashes the bytes it registers.

Determinism strategy, which is what makes a concurrency test readable:

- Every sequence assertion runs at `workers=1`, the serial path where one job
  fully finishes before the next is queued.
- Anything that must observe a job *while it is running* holds it on a
  `threading.Event` gate rather than on a sleep, and every wait carries a
  deadline so a broken registry fails the assertion instead of hanging.
- The concurrency test asserts only what is contractual: the pool never
  exceeds `analyze_workers`, and every job still completes.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from pathlib import Path

import fitz
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from datasheet_analyzer.app import jobs as jobs_module
from datasheet_analyzer.app.contracts import (
    ANALYZE_EVENT_END,
    ANALYZE_EVENT_JOB,
    ANALYZE_EVENT_SNAPSHOT,
    SSE_HEARTBEAT_SECONDS,
    DocProposal,
    JobEvent,
    JobRegistryLike,
    RunSnapshot,
)
from datasheet_analyzer.app.deps import get_job_registry
from datasheet_analyzer.app.jobs import (
    JobRegistry,
    RunNotFound,
    build_job,
    default_registry,
    default_skip_check,
    record_applicability,
    reset_default_registry,
)
from datasheet_analyzer.app.routers.analyze import (
    HEARTBEAT_COMMENT,
    analyze_event_stream,
)
from datasheet_analyzer.app.routers.analyze import (
    router as analyze_router,
)
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.models import AnalyzeJob, Applicability, JobState, LibraryDocument
from datasheet_analyzer.retrieve.index import discover_parts

# Every wait in this file is bounded: a registry that never finishes must fail
# a test, not hang a suite.
DEADLINE = 30.0
STAGES = ("extracting", "structuring", "enriching", "publishing")
WORKING_SEQUENCE = [
    JobState.QUEUED,
    JobState.EXTRACTING,
    JobState.STRUCTURING,
    JobState.ENRICHING,
    JobState.PUBLISHING,
]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A `Settings` rooted entirely inside `tmp_path` — nothing shared."""
    reset_settings_cache()
    reset_default_registry()
    resolved = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / "cache",
        projects_dir=tmp_path / "projects",
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
    ).resolve()
    yield resolved
    reset_settings_cache()
    reset_default_registry()


def _pdf(tmp_path: Path, name: str, text: str = "TEST9000 datasheet") -> Path:
    """A one-page PDF with real bytes, for the paths that hash a file."""
    path = tmp_path / name
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


def _touch(tmp_path: Path, name: str) -> Path:
    """A placeholder file for the paths where the build is stubbed out."""
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 stub\n")
    return path


def _proposal(path: Path, part: str, applicability: Applicability | None = None) -> DocProposal:
    return DocProposal(
        pdf_path=str(path),
        filename=path.name,
        part_number=part,
        applicability=applicability or Applicability.for_parts([part], evidence="user: confirmed"),
    )


def _never_skip(job: AnalyzeJob, *, settings: Settings) -> str:
    return ""


class StubBuild:
    """A build that emits the real stage vocabulary in milliseconds.

    `gate` holds every job at its entry until a test releases it, which is how
    a test observes a run *mid-flight*; `fail_for` raises after the first
    stage, the way a genuinely unreadable PDF fails partway through; `on_done`
    is the hook a test uses to make a job leave something real behind (a
    published part directory, say).
    """

    def __init__(
        self,
        *,
        gate: threading.Event | None = None,
        fail_for: tuple[str, ...] = (),
        on_done=None,
    ) -> None:
        self.gate = gate
        self.fail_for = fail_for
        self.on_done = on_done
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, job: AnalyzeJob, *, settings: Settings, on_progress) -> None:
        with self._lock:
            self.calls.append(job.part_number)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.gate is not None and not self.gate.wait(DEADLINE):
                raise AssertionError(f"gate never released for {job.part_number}")
            for stage in STAGES:
                on_progress(stage)
                if stage == "extracting" and job.part_number in self.fail_for:
                    raise RuntimeError("unreadable page tree")
            if self.on_done is not None:
                self.on_done(job, settings)
        finally:
            with self._lock:
                self.active -= 1


def _registry(settings: Settings, build: StubBuild, **kwargs) -> JobRegistry:
    kwargs.setdefault("skip_check", _never_skip)
    kwargs.setdefault("workers", 1)
    return JobRegistry(settings=settings, build=build, **kwargs)


def _states(registry: JobRegistry, run_id: str, job_id: str) -> list[JobState]:
    return [e.state for e in registry.history(run_id) if e.job_id == job_id]


def _wait_until(predicate, message: str, timeout: float = DEADLINE) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {message}")


# --- start: a run_id now, the work later --------------------------------------


def test_start_returns_run_id_immediately_for_many_pdfs(settings, tmp_path):
    """Forty PDFs must not make the request that queues them slow."""
    gate = threading.Event()
    build = StubBuild(gate=gate)
    registry = _registry(settings, build)
    proposals = [_proposal(_touch(tmp_path, f"d{i}.pdf"), f"PART{i}") for i in range(40)]

    started = time.perf_counter()
    run_id = registry.start(directory=str(tmp_path), proposals=proposals)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"start() blocked for {elapsed:.3f}s"
    assert run_id
    assert registry.exists(run_id)
    assert not registry.exists("no-such-run")
    assert len(registry.run(run_id)) == 40
    assert registry.snapshot(run_id).done is False

    gate.set()
    assert registry.wait(run_id, DEADLINE)
    assert registry.snapshot(run_id).done is True


def test_start_uses_the_confirmed_part_number_and_applicability(settings, tmp_path):
    """What the review screen sent is what the job carries — verbatim."""
    build = StubBuild()
    registry = _registry(settings, build)
    confirmed = Applicability.for_family("AFE79xx", evidence="user: edited on review")
    proposal = _proposal(_touch(tmp_path, "afe7950.pdf"), "AFE7950", confirmed)
    run_id = registry.start(directory=str(tmp_path), proposals=[proposal])
    assert registry.wait(run_id, DEADLINE)

    job = registry.run(run_id)[0]
    assert job.part_number == "AFE7950"
    assert job.applicability.kind == "family"
    assert job.applicability.family == "AFE79xx"
    assert job.applicability.evidence == "user: edited on review"


def test_registry_satisfies_the_frozen_protocol(settings):
    assert isinstance(JobRegistry(settings=settings), JobRegistryLike)
    assert isinstance(default_registry(), JobRegistry)
    assert default_registry() is default_registry()


def test_unknown_run_raises_run_not_found(settings):
    registry = JobRegistry(settings=settings)
    with pytest.raises(RunNotFound):
        registry.run("nope")
    with pytest.raises(RunNotFound):
        registry.snapshot("nope")


# --- the state machine --------------------------------------------------------


def test_job_emits_every_state_in_order(settings, tmp_path):
    build = StubBuild()
    registry = _registry(settings, build)
    run_id = registry.start(
        directory=str(tmp_path),
        proposals=[_proposal(_touch(tmp_path, "lm741.pdf"), "LM741")],
    )
    assert registry.wait(run_id, DEADLINE)

    job = registry.run(run_id)[0]
    assert _states(registry, run_id, job.id) == [*WORKING_SEQUENCE, JobState.DONE]
    assert job.state is JobState.DONE
    assert job.started_at is not None and job.finished_at is not None
    assert not job.error

    event = registry.history(run_id)[-1]
    assert event.run_id == run_id
    assert event.part_number == "LM741"
    assert event.pdf_path.endswith("lm741.pdf")


def test_one_failing_pdf_fails_only_its_own_job(settings, tmp_path):
    build = StubBuild(fail_for=("MID",))
    registry = _registry(settings, build)
    proposals = [
        _proposal(_touch(tmp_path, "first.pdf"), "FIRST"),
        _proposal(_touch(tmp_path, "mid.pdf"), "MID"),
        _proposal(_touch(tmp_path, "last.pdf"), "LAST"),
    ]
    run_id = registry.start(directory=str(tmp_path), proposals=proposals)
    assert registry.wait(run_id, DEADLINE)

    by_part = {job.part_number: job for job in registry.run(run_id)}
    assert by_part["FIRST"].state is JobState.DONE
    assert by_part["LAST"].state is JobState.DONE
    failed = by_part["MID"]
    assert failed.state is JobState.FAILED
    assert "unreadable page tree" in failed.error
    assert "unreadable page tree" in failed.detail
    # The failure is carried on the stream too, not only on the job.
    failure = [e for e in registry.history(run_id) if e.state is JobState.FAILED]
    assert len(failure) == 1
    assert "unreadable page tree" in failure[0].detail
    # Every job was still attempted.
    assert sorted(build.calls) == ["FIRST", "LAST", "MID"]


def test_already_built_pdf_is_skipped_with_a_reason(settings, tmp_path):
    reason = "already built: PDF sha256 and pipeline version match"

    def skip_check(job: AnalyzeJob, *, settings: Settings) -> str:
        return reason if job.part_number == "OLD" else ""

    build = StubBuild()
    registry = _registry(settings, build, skip_check=skip_check)
    proposals = [
        _proposal(_touch(tmp_path, "old.pdf"), "OLD"),
        _proposal(_touch(tmp_path, "new.pdf"), "NEW"),
    ]
    run_id = registry.start(directory=str(tmp_path), proposals=proposals)
    assert registry.wait(run_id, DEADLINE)

    by_part = {job.part_number: job for job in registry.run(run_id)}
    assert by_part["OLD"].state is JobState.SKIPPED
    assert by_part["OLD"].detail == reason
    assert by_part["NEW"].state is JobState.DONE
    assert build.calls == ["NEW"], "a skipped job must not be rebuilt"
    assert _states(registry, run_id, by_part["OLD"].id) == [JobState.QUEUED, JobState.SKIPPED]


def test_default_skip_check_delegates_to_batch(settings, tmp_path, monkeypatch):
    """The hash gate is `batch.skip_reason` — reused, not re-implemented."""
    seen = {}

    def fake_skip_reason(batch_job, *, settings, force):
        seen["part"] = batch_job.part
        seen["pdf"] = Path(batch_job.pdf_path)
        seen["force"] = force
        return "already built: PDF sha256 unchanged"

    monkeypatch.setattr(jobs_module, "batch_skip_reason", fake_skip_reason)
    pdf = _touch(tmp_path, "ad9081.pdf")
    job = AnalyzeJob(id="j1", pdf_path=str(pdf), part_number="AD9081")

    assert default_skip_check(job, settings=settings) == "already built: PDF sha256 unchanged"
    assert seen == {"part": "AD9081", "pdf": pdf, "force": False}

    # And the registry's default wiring is that same function.
    registry = JobRegistry(settings=settings, build=StubBuild(), workers=1)
    run_id = registry.start(directory=str(tmp_path), proposals=[_proposal(pdf, "AD9081")])
    assert registry.wait(run_id, DEADLINE)
    assert registry.run(run_id)[0].state is JobState.SKIPPED


def test_a_finished_part_is_visible_while_other_jobs_run(settings, tmp_path):
    """`DONE` means askable now — the run does not have to finish."""
    gate = threading.Event()

    def publish(job: AnalyzeJob, settings: Settings) -> None:
        part_dir = settings.parts_dir / job.part_number
        part_dir.mkdir(parents=True, exist_ok=True)
        (part_dir / "manifest.json").write_text("{}", encoding="utf-8")

    def build(job: AnalyzeJob, *, settings: Settings, on_progress) -> None:
        if job.part_number == "SLOW":
            assert gate.wait(DEADLINE)
        for stage in STAGES:
            on_progress(stage)
        publish(job, settings)

    registry = JobRegistry(settings=settings, build=build, skip_check=_never_skip, workers=2)
    proposals = [
        _proposal(_touch(tmp_path, "fast.pdf"), "FAST"),
        _proposal(_touch(tmp_path, "slow.pdf"), "SLOW"),
    ]
    run_id = registry.start(directory=str(tmp_path), proposals=proposals)

    def fast_done() -> bool:
        return any(
            j.part_number == "FAST" and j.state is JobState.DONE for j in registry.run(run_id)
        )

    _wait_until(fast_done, "the FAST job to reach DONE")

    # The catalog `/api/parts` reads sees it already, mid-run.
    assert [d.name for d in discover_parts(settings.parts_dir)] == ["FAST"]
    slow = next(j for j in registry.run(run_id) if j.part_number == "SLOW")
    assert not slow.terminal, "the run is still going"
    assert registry.snapshot(run_id).done is False

    gate.set()
    assert registry.wait(run_id, DEADLINE)
    assert sorted(d.name for d in discover_parts(settings.parts_dir)) == ["FAST", "SLOW"]


def test_pool_never_exceeds_analyze_workers(settings, tmp_path):
    """Bounded by `settings.analyze_workers`, and every job still completes."""
    bounded = settings.model_copy(update={"analyze_workers": 2})
    gate = threading.Event()
    build = StubBuild(gate=gate)
    registry = JobRegistry(settings=bounded, build=build, skip_check=_never_skip)
    assert registry.workers == 2

    proposals = [_proposal(_touch(tmp_path, f"p{i}.pdf"), f"P{i}") for i in range(6)]
    run_id = registry.start(directory=str(tmp_path), proposals=proposals)

    _wait_until(lambda: build.max_active >= 2, "two jobs to run at once")
    assert build.active <= 2
    gate.set()

    assert registry.wait(run_id, DEADLINE)
    assert build.max_active == 2, f"pool ran {build.max_active} jobs at once"
    assert len(build.calls) == 6
    assert all(job.state is JobState.DONE for job in registry.run(run_id))


# --- the event feed -----------------------------------------------------------


def _drain(feed) -> list[JobEvent]:
    async def _collect() -> list[JobEvent]:
        collected = []
        async for event in feed:
            collected.append(event)
        return collected

    return _collect()


def test_two_clients_both_receive_every_subsequent_event(settings, tmp_path):
    gate = threading.Event()
    registry = _registry(settings, StubBuild(gate=gate))
    proposals = [
        _proposal(_touch(tmp_path, "a.pdf"), "AAA"),
        _proposal(_touch(tmp_path, "b.pdf"), "BBB"),
    ]
    run_id = registry.start(directory=str(tmp_path), proposals=proposals)

    async def scenario():
        first = registry.events(run_id)
        second = registry.events(run_id)
        gate.set()
        left = await asyncio.wait_for(_drain(first), DEADLINE)
        right = await asyncio.wait_for(_drain(second), DEADLINE)
        return left, right

    left, right = asyncio.run(scenario())

    assert left, "a connected client received nothing"
    assert [(e.job_id, e.state) for e in left] == [(e.job_id, e.state) for e in right]
    assert {e.state for e in left} >= {JobState.DONE}
    assert len({e.job_id for e in left}) == 2


def test_events_for_a_finished_run_end_at_once(settings, tmp_path):
    registry = _registry(settings, StubBuild())
    run_id = registry.start(
        directory=str(tmp_path),
        proposals=[_proposal(_touch(tmp_path, "a.pdf"), "AAA")],
    )
    assert registry.wait(run_id, DEADLINE)

    assert asyncio.run(asyncio.wait_for(_drain(registry.events(run_id)), DEADLINE)) == []


# --- the SSE stream -----------------------------------------------------------


def test_stream_opens_with_a_snapshot_of_every_job(settings, tmp_path):
    """A client attaching mid-run is never blank."""
    gate = threading.Event()
    registry = _registry(settings, StubBuild(gate=gate))
    proposals = [_proposal(_touch(tmp_path, f"p{i}.pdf"), f"P{i}") for i in range(3)]
    run_id = registry.start(directory=str(tmp_path), proposals=proposals)

    async def scenario():
        stream = analyze_event_stream(registry, run_id, heartbeat=0.05)
        first = await asyncio.wait_for(stream.__anext__(), DEADLINE)
        gate.set()
        rest = [frame async for frame in stream]
        return first, rest

    first, rest = asyncio.run(scenario())

    assert first.event == ANALYZE_EVENT_SNAPSHOT
    snapshot = RunSnapshot.model_validate_json(first.data)
    assert snapshot.run_id == run_id
    assert snapshot.directory == str(tmp_path)
    assert [j.part_number for j in snapshot.jobs] == ["P0", "P1", "P2"]
    assert snapshot.done is False

    assert rest[-1].event == ANALYZE_EVENT_END
    closing = RunSnapshot.model_validate_json(rest[-1].data)
    assert closing.done is True
    assert all(job.state is JobState.DONE for job in closing.jobs)

    job_frames = [f for f in rest if f.event == ANALYZE_EVENT_JOB]
    assert job_frames, "no transitions reached the stream"
    parsed = [JobEvent.model_validate_json(f.data) for f in job_frames]
    assert [e.state for e in parsed if e.job_id == parsed[0].job_id][-1] is JobState.DONE


def test_stream_heartbeats_while_a_job_is_slow(settings, tmp_path):
    """A silent stream still writes bytes, or a proxy drops the connection."""
    assert SSE_HEARTBEAT_SECONDS == 15
    default = inspect.signature(analyze_event_stream).parameters["heartbeat"].default
    assert default == SSE_HEARTBEAT_SECONDS

    gate = threading.Event()
    registry = _registry(settings, StubBuild(gate=gate))
    run_id = registry.start(
        directory=str(tmp_path),
        proposals=[_proposal(_touch(tmp_path, "slow.pdf"), "SLOW")],
    )

    async def scenario():
        stream = analyze_event_stream(registry, run_id, heartbeat=0.05)
        await asyncio.wait_for(stream.__anext__(), DEADLINE)  # snapshot
        beats = []
        for _ in range(2):
            frame = await asyncio.wait_for(stream.__anext__(), DEADLINE)
            beats.append(frame)
        gate.set()
        rest = [frame async for frame in stream]
        return beats, rest

    beats, rest = asyncio.run(scenario())

    assert [b.comment for b in beats] == [HEARTBEAT_COMMENT, HEARTBEAT_COMMENT]
    assert all(b.event is None and not b.data for b in beats)
    # The heartbeat is a keep-alive, not a substitute for the transitions.
    assert [f.event for f in rest].count(ANALYZE_EVENT_JOB) >= len(WORKING_SEQUENCE) - 1
    assert rest[-1].event == ANALYZE_EVENT_END


def test_stream_closes_once_every_job_is_terminal(settings, tmp_path):
    gate = threading.Event()
    registry = _registry(settings, StubBuild(gate=gate, fail_for=("BBB",)))
    proposals = [
        _proposal(_touch(tmp_path, "a.pdf"), "AAA"),
        _proposal(_touch(tmp_path, "b.pdf"), "BBB"),
    ]
    run_id = registry.start(directory=str(tmp_path), proposals=proposals)
    gate.set()

    async def scenario():
        stream = analyze_event_stream(registry, run_id, heartbeat=0.05)
        frames = []
        async for frame in stream:  # terminates on its own or the test hangs
            frames.append(frame)
        return frames

    frames = asyncio.run(asyncio.wait_for(scenario(), DEADLINE))

    assert frames[0].event == ANALYZE_EVENT_SNAPSHOT
    assert frames[-1].event == ANALYZE_EVENT_END
    closing = RunSnapshot.model_validate_json(frames[-1].data)
    assert closing.done is True
    assert {j.state for j in closing.jobs} == {JobState.DONE, JobState.FAILED}
    # A closed stream detached its feed: the run keeps none behind.
    assert asyncio.run(asyncio.wait_for(_drain(registry.events(run_id)), DEADLINE)) == []


# --- the HTTP surface ---------------------------------------------------------


def _client(registry: JobRegistry) -> TestClient:
    """Just this ticket's router, so no other in-flight module can break it."""
    app = FastAPI()
    app.include_router(analyze_router)
    app.dependency_overrides[get_job_registry] = lambda: registry
    return TestClient(app)


def test_post_start_returns_a_run_id(settings, tmp_path):
    gate = threading.Event()
    registry = _registry(settings, StubBuild(gate=gate))
    payload = {
        "directory": str(tmp_path),
        "proposals": [
            _proposal(_touch(tmp_path, "a.pdf"), "AAA").model_dump(mode="json"),
            _proposal(_touch(tmp_path, "b.pdf"), "BBB").model_dump(mode="json"),
        ],
    }
    with _client(registry) as client:
        response = client.post("/api/analyze/start", json=payload)

    assert response.status_code == 202
    body = response.json()
    assert body["n_jobs"] == 2
    assert registry.exists(body["run_id"])
    gate.set()
    assert registry.wait(body["run_id"], DEADLINE)


def test_post_start_rejects_an_empty_proposal_list(settings, tmp_path):
    registry = _registry(settings, StubBuild())
    with _client(registry) as client:
        response = client.post("/api/analyze/start", json={"directory": str(tmp_path)})
    assert response.status_code == 400
    assert "no proposals" in response.json()["detail"]


def test_get_events_on_an_unknown_run_is_404(settings):
    registry = _registry(settings, StubBuild())
    with _client(registry) as client:
        response = client.get("/api/analyze/nope/events")
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


def test_get_events_streams_snapshot_then_end(settings, tmp_path):
    registry = _registry(settings, StubBuild())
    run_id = registry.start(
        directory=str(tmp_path),
        proposals=[_proposal(_touch(tmp_path, "a.pdf"), "AAA")],
    )
    assert registry.wait(run_id, DEADLINE)

    with _client(registry) as client:
        response = client.get(f"/api/analyze/{run_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert f"event: {ANALYZE_EVENT_SNAPSHOT}" in body
    assert f"event: {ANALYZE_EVENT_END}" in body
    assert body.index(f"event: {ANALYZE_EVENT_SNAPSHOT}") < body.index(
        f"event: {ANALYZE_EVENT_END}"
    )


# --- the confirmed applicability reaches the library --------------------------


class FakeStore:
    """Ticket 01's `LibraryStore` surface, as much of it as this ticket uses."""

    def __init__(self) -> None:
        self.documents: dict[str, LibraryDocument] = {}

    def put(self, doc: LibraryDocument) -> None:
        self.documents[doc.content_hash] = doc

    def get(self, content_hash: str) -> LibraryDocument | None:
        return self.documents.get(content_hash)


def test_confirmed_applicability_is_what_reaches_the_library(settings, tmp_path, monkeypatch):
    """The user's edit is stored — inference is never consulted at build time."""

    def _never(*args, **kwargs):
        raise AssertionError("build-time inference must not run")

    monkeypatch.setattr("datasheet_analyzer.acquire.applicability.infer", _never, raising=False)

    pdf = _pdf(tmp_path, "afe7950.pdf")
    confirmed = Applicability.for_family("AFE79xx", evidence="user: edited on review")
    job = AnalyzeJob(
        id="j1",
        pdf_path=str(pdf),
        part_number="AFE7950",
        applicability=confirmed,
    )
    store = FakeStore()

    document = record_applicability(job, settings=settings, store=store)

    assert isinstance(document, LibraryDocument)
    assert list(store.documents) == [document.content_hash]
    stored = store.documents[document.content_hash]
    assert stored.applicability.kind == "family"
    assert stored.applicability.family == "AFE79xx"
    assert stored.applicability.evidence == "user: edited on review"
    assert stored.covers("AFE7950") and not stored.covers("AD9081")
    assert stored.source.path == str(pdf)


def test_build_job_records_applicability_before_building(settings, tmp_path, monkeypatch):
    """Order matters: the library must already know the document at build time."""
    order: list[str] = []
    seen: dict[str, object] = {}

    def fake_record(job, *, settings, store=None):
        order.append("record")
        seen["part"] = job.part_number

    def fake_build_part(pdf_path, *, part_number, settings, on_progress=None, **kwargs):
        order.append("build")
        seen["pdf"] = Path(pdf_path)
        seen["build_part"] = part_number
        if on_progress is not None:
            on_progress("extracting")

    monkeypatch.setattr(jobs_module, "record_applicability", fake_record)
    monkeypatch.setattr(jobs_module, "build_part", fake_build_part)

    pdf = _touch(tmp_path, "lm741.pdf")
    job = AnalyzeJob(id="j1", pdf_path=str(pdf), part_number="LM741")
    stages: list[str] = []
    build_job(job, settings=settings, on_progress=stages.append)

    assert order == ["record", "build"]
    assert seen == {"part": "LM741", "pdf": pdf, "build_part": "LM741"}
    assert stages == ["extracting"], "the pipeline's stage callback is passed through"
