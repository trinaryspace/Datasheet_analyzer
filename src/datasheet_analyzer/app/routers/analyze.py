"""`/api/analyze`: start a run, watch it (ticket 07).

Two endpoints and one generator. `POST /api/analyze/start` hands the
confirmed proposals to the registry and returns a `run_id` — it never waits
for a build. `GET /api/analyze/{run_id}/events` is the SSE stream of that
run, shaped exactly as `app/contracts.py` documents it:

1. `event: snapshot` once on connect, so a client attaching to a run already
   half-finished renders its current state instead of a blank screen;
2. `event: job` per transition;
3. a `:` comment every `SSE_HEARTBEAT_SECONDS` of silence, because a 40-PDF
   build is genuinely idle for minutes and browsers and proxies drop an idle
   connection;
4. `event: end` with the final snapshot, once every job is terminal.

The subscription is taken *before* the snapshot is read. The reverse order
has a window in which a transition lands between the two and is never
delivered; this order can only ever repeat a transition the snapshot already
showed, which a state-assignment stream absorbs harmlessly.

The stream generator is a module-level function, separate from the endpoint,
so its heartbeat and its termination are testable in milliseconds without an
HTTP client and without waiting fifteen real seconds.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from datasheet_analyzer.app.contracts import (
    ANALYZE_EVENT_END,
    ANALYZE_EVENT_JOB,
    ANALYZE_EVENT_SNAPSHOT,
    API_PREFIX,
    SSE_HEARTBEAT_SECONDS,
    JobEvent,
    JobRegistryLike,
    StartIn,
    StartOut,
)
from datasheet_analyzer.app.deps import get_job_registry

__all__ = ["analyze_event_stream", "router", "start_analyze_run", "stream_analyze_events"]

router = APIRouter(prefix=f"{API_PREFIX}/analyze", tags=["analyze"])

#: sse-starlette has its own keep-alive; this module emits the contract's
#: heartbeat itself (so the interval is one constant, and testable), and the
#: library's ping is pushed out of the way rather than doubled up.
_LIBRARY_PING_SECONDS = 3600

#: A heartbeat comment carries no data — its only job is bytes on the wire.
HEARTBEAT_COMMENT = "keep-alive"

#: The registry both endpoints inject, overridable in a test through
#: `app.dependency_overrides[get_job_registry]`.
RegistryDep = Annotated[JobRegistryLike, Depends(get_job_registry)]


@router.post("/start", response_model=StartOut, status_code=status.HTTP_202_ACCEPTED)
def start_analyze_run(payload: StartIn, registry: RegistryDep) -> StartOut:
    """Queue a build of every confirmed proposal; return the `run_id` at once.

    202, not 200: nothing is built when this returns. An empty proposal list
    is a 400 rather than an empty run — a review screen that submitted
    nothing is a bug the user should see, not a run that finishes instantly.
    """
    if not payload.proposals:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no proposals to build",
        )
    run_id = registry.start(directory=payload.directory, proposals=list(payload.proposals))
    return StartOut(run_id=run_id, n_jobs=len(payload.proposals))


async def _next_event(feed: AsyncIterator[JobEvent]) -> JobEvent | None:
    """The next transition, or `None` once the feed has ended."""
    try:
        return await feed.__anext__()
    except StopAsyncIteration:
        return None


async def analyze_event_stream(
    registry: JobRegistryLike,
    run_id: str,
    *,
    heartbeat: float = SSE_HEARTBEAT_SECONDS,
) -> AsyncIterator[ServerSentEvent]:
    """Snapshot, then every transition, with heartbeats, then `end`."""
    feed = registry.events(run_id)
    try:
        yield ServerSentEvent(
            event=ANALYZE_EVENT_SNAPSHOT,
            data=registry.snapshot(run_id).model_dump_json(),
        )
        while True:
            try:
                event = await asyncio.wait_for(_next_event(feed), timeout=heartbeat)
            except (asyncio.TimeoutError, TimeoutError):
                yield ServerSentEvent(comment=HEARTBEAT_COMMENT)
                continue
            if event is None:
                break
            yield ServerSentEvent(event=ANALYZE_EVENT_JOB, data=event.model_dump_json())
        yield ServerSentEvent(
            event=ANALYZE_EVENT_END,
            data=registry.snapshot(run_id).model_dump_json(),
        )
    finally:
        close = getattr(feed, "close", None)
        if callable(close):
            close()


@router.get("/{run_id}/events")
async def stream_analyze_events(run_id: str, registry: RegistryDep) -> EventSourceResponse:
    """The run's SSE stream. An unknown `run_id` is a 404, never an empty one."""
    if not registry.exists(run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown analyze run: {run_id}",
        )
    return EventSourceResponse(
        analyze_event_stream(registry, run_id),
        ping=_LIBRARY_PING_SECONDS,
    )
