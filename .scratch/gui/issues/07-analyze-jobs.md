# 07 — Analyze jobs and progress stream

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/jobs.py`
- `src/datasheet_analyzer/app/routers/analyze.py`
- `tests/unit/test_analyze_jobs.py`

**What to build:** Building 30 datasheets is minutes to hours. `POST
/api/analyze/start` returns a `run_id` immediately and does the work in the
background, one `AnalyzeJob` per PDF, while `GET /api/analyze/{run_id}/events`
streams `JobEvent`s over SSE. A part becomes askable the moment its own job
reaches `DONE` — the run does not have to finish.

`jobs.py` holds a process-wide `JobRegistry`: create a run from a list of
confirmed `DocProposal`s, dispatch jobs to a bounded pool sized by
`settings.analyze_workers`, and expose both a snapshot (`run(run_id) ->
list[AnalyzeJob]`) and an async event feed. Each job calls
`pipeline.build_part(...)` inside its own error boundary and records the
applicability the user confirmed on the review screen.

Reuse `batch.py` rather than reinventing it: it already does bounded-pool
dispatch, per-job failure isolation, hash-gated skip, and a stage callback at
`extracting / structuring / enriching / publishing`. This ticket wires that
callback to the event feed and adds the HTTP surface. If a behaviour you need
exists in `batch.py`, call it; do not copy it.

SSE specifics that matter: send an event immediately on connect carrying the
current snapshot, so a client attaching late is not blank; send a heartbeat
comment every 15 s so proxies and browsers hold the connection; and terminate
the stream when every job is in a terminal state. Two clients may watch the
same run.

- [ ] `POST /api/analyze/start` returns a `run_id` in well under a second regardless of PDF count
- [ ] Jobs run concurrently up to `settings.analyze_workers` and no further
- [ ] Each job emits `QUEUED → EXTRACTING → STRUCTURING → ENRICHING → PUBLISHING → DONE` in order
- [ ] One failing PDF marks only its own job `FAILED`, carries the error text, and leaves every other job running
- [ ] A PDF already built and unchanged is marked `SKIPPED` with a reason, not rebuilt
- [ ] A part reaching `DONE` is immediately queryable through `/api/parts` while other jobs are still running
- [ ] Connecting to the event stream mid-run first receives a snapshot of every job's current state
- [ ] Two simultaneous clients on one run both receive every subsequent event
- [ ] The stream emits a heartbeat at least every 15 s during a long-running job
- [ ] The stream closes once all jobs are terminal
- [ ] `GET /api/analyze/{run_id}/events` on an unknown run returns 404
- [ ] The confirmed applicability from the request reaches the library, not a re-inferred one
- [ ] Tests drive the registry directly with a stubbed build function and assert the event sequence; `workers=1` for determinism, plus one concurrency test asserting only that all jobs complete
- [ ] No network, no live model — the build function is faked
