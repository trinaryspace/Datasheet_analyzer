# 04 — Parallel dispatch

**What to build:** Batch jobs run in a bounded thread pool: `--workers N`
(default 4, env `DSA_BATCH_WORKERS`); `--workers 1` reproduces the serial
path. Each job is one independent unit running the full pipeline, with its
backend wiring, LLM client, and fetchers created inside the job — thread
safety is by construction, no shared mutable pipeline state. Parallel
runs keep the event contract from ticket 3: every event fires exactly once
per transition and every JSONL line stays individually parseable.

**Blocked by:** 01 — Serial batch command, 03 — Stage events and the JSONL batch log

**Status:** ready-for-agent

- [ ] `--workers N` runs up to N jobs concurrently; a batch with more jobs than workers completes all of them
- [ ] `--workers 1` behaves exactly like the serial path
- [ ] `DSA_BATCH_WORKERS` env var is the default when `--workers` is not given (default 4)
- [ ] With parallel workers, every job completes and each event fires exactly once per transition
- [ ] With parallel workers, every JSONL line in the run log is individually parseable (no mid-line interleaving)
- [ ] No shared mutable pipeline state exists between concurrent jobs; job-scoped wiring (backend, fetchers, LLM client) is created per job
- [ ] Extraction-cache writes are atomic (write-temp + rename): two jobs with
      identical PDF bytes in one run must never corrupt
      `.cache/extract/<hash>__<backend>.json` (possible with pdf_layout jobs,
      which are offline) 
