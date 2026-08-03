---
title: Batch build command
labels: [ready-for-agent]
---

## Problem Statement

Running the pipeline over a library of datasheets means one `dsa build <pdf>` call per PDF, each with a hand-typed `--part`. A batch of many PDFs requires babysitting: builders run serially, nothing is paralleled, failures in the middle kill the whole sequence of attention, and there is no record of what ran, what finished, and what broke. Large batches make this worse — hours of wall time with no visibility.

## Solution

A single invocation builds every PDF directly inside one directory as its own part corpus. Jobs run in parallel with a bounded worker pool; parts whose PDF bytes are unchanged since their last successful build are skipped rather than rebuilt; every job reports its stage transitions live to the terminal and to a durable JSONL batch log; a failed job is isolated, its error captured, and the remaining jobs proceed. The command summarizes the whole batch at the end and exits nonzero if any job failed.

## User Stories

1. As a builder running the pipeline, I want to point one command at a directory of datasheets, so that every PDF directly inside it becomes one part corpus in a single invocation.
2. As a builder, I want the part number for each PDF derived deterministically as the uppercase filename stem, so I never hand-type part names and `afe7950.pdf` always maps to part `AFE7950`.
3. As a builder, I want the directory scanned flat (direct children only), so a mixed tree with subfolders never turns app notes and stray documents into misnamed parts.
4. As a builder, I want jobs processed in sorted filename order, so the same directory always produces the same job sequence.
5. As a builder, I want non-PDF files in the directory ignored, so READMEs and notes in the folder don't fail the batch.
6. As a builder, I want the full (file → part) mapping printed before any work starts, so a rogue filename (e.g. `notes.pdf` → part `NOTES`) is visible before anything is built.
7. As a builder of large batches, I want jobs to run in parallel with a bounded worker pool (`--workers`, env `DSA_BATCH_WORKERS`, default 4), so total wall time shrinks with machine capacity.
8. As a builder, I want `--workers 1` to reproduce today's serial single-part behavior exactly, so the batch option can never surprise a cautious run.
9. As a builder re-running a batch, I want parts that are already built and whose PDF sha256 matches the hash recorded in their inventory to be skipped, so re-runs of a finished library are near-free and never burn fresh LLM calls on unchanged parts.
10. As a builder, I want `--force` to rebuild a part even when it is up to date, so deliberately changing data or pipeline versions is always possible.
11. As a builder, I want a changed or new PDF in the directory to trigger a full rebuild of that part, so a stale corpus is impossible-by-construction (hash is identity).
12. As a builder, I want one failing job (bad PDF, transient network error) to record its error and let every other job continue, so one bad file doesn't kill hours of work.
13. As a builder, I want the batch to exit 0 when all jobs passed and 1 when any job failed, so CI and scripts can depend on the exit code (matching `verify`'s convention).
14. As a builder monitoring a long batch, I want each job's stage transitions (`queued → extracting → structuring → enriching → publishing → done/failed/skipped`) visible live on the terminal as single prefixed lines, so I can see progress without guesswork.
15. As a builder monitoring a long batch, I want the same events appended to a per-run JSONL file under the cache directory, so I can tail it, grep it by part name, and hand it to tooling later.
16. As a builder, I want the JSONL event stream to be the source of truth for monitoring, so human terminal text never corrupts the machine-readable record.
17. As a builder, I want a final summary table at the end of the batch (per-part status, reasons for failure or skip), so the outcome of N jobs is one glance away.
18. As a builder of many parts, I want `--no-cache`, `--no-llm`, and `--workers` to behave identically to their `build` equivalents, so batch is a strict superset of single-part invocations.
19. As a builder, I want an empty or missing source directory reported clearly as an error, so a typo'd path never silently builds nothing.
20. As a builder, I want each job's extracted data to reuse the existing extraction cache, so partial re-runs after failures only redo the work that failed.
21. As a builder, I want per-job status and error detail recorded in the JSONL even for skipped and failed jobs, so the log alone explains what happened after the terminal scrolled.
22. As a builder, I want the JSONL events from concurrent jobs to never interleave mid-line, so each event is one parseable JSON object.

## Implementation Decisions

- **New `batch` subcommand** taking a directory positional: `dsa batch <dir>` with `--workers N` (default 4, env `DSA_BATCH_WORKERS`), `--force`, `--no-cache`, `--no-llm`. `build`, `add-doc`, `verify`, `query`, `status` are untouched.
- **New batch runner module** exporting a `run_batch(...) -> BatchReport` function as the single seam between CLI and batch machinery. The CLI command is a thin wrapper in the same style as the existing command handlers.
- **Job derivation**: direct children of the directory matching `*.pdf` case-insensitively, sorted by filename; part number = uppercase stem; each job is its own part build. The derivation result (file → part) is emitted before dispatch.
- **Concurrency**: bounded `ThreadPoolExecutor` with one job per worker; each job runs the existing single-part pipeline end to end, wrapped in its own error boundary. Thread-safety is by construction: any state a job needs (backend wiring, LLM client, fetchers) is created inside the job, as the single-part path already does. `workers=1` is the serial path.
- **Skip-if-up-to-date**: a job is skipped when the part corpus manifest exists and the PDF's sha256 equals the hash of that document recorded in the part's inventory. `--force` disables the check. Skips produce a `skipped` event and a summary row with reason.
- **Stage events**: the single-part build gains an optional, additive progress callback invoked at stage boundaries (extracting, structuring, enriching, publishing; default no-op so existing callers are unaffected). The batch runner wires it to the event emitter.
- **Event emitter**: one emit call per transition, structured as (job id, part, stage, timestamp, detail); dual sink — one prefixed, line-buffered line to stdout and one JSON line appended to the batch run's JSONL. JSONL is the authoritative record.
- **Batch log**: a per-run JSONL file keyed by source directory stem plus run start timestamp, inside the cache directory (`.cache/batches/`), with a stable header event carrying the full job list. No pruning/rotation in this change.
- **Failure isolation**: any exception inside a job is captured (message plus, in the JSONL, traceback summary), recorded as a `failed` event, and the batch continues with the remaining jobs. BatchReport carries a per-job status with error text and final summary counts.
- **Exit code**: 0 when every job is done or skipped; 1 when any job failed.
- **No in-run retries**: per ADR 0001, rerunning the batch is the retry mechanism — extraction cache plus hash-gating make repeat runs cheap.
- **Report shape**: `BatchReport` with one entry per job (part name, PDF path, status, stages observed, error, token counts/artifact stats when done) plus derived summary counts. Defined in the runner module as a plain result type; the corpus product (manifest, specs, plots) is unchanged.
- Terminal output uses the existing UTF-8 output reconfiguration; status vocabulary is part of the runner's contract (`queued | running:<stage> | done | failed | skipped`).

## Testing Decisions

- **What makes a good test**: external behavior of the runner only — given a directory of synthetic PDFs and temp-dir settings, assert the observable outcomes (which parts exist, which jobs are done/skipped/failed, the event stream, the report, exit semantics). No assertions on thread scheduling or internals; deterministic runs use `workers=1`, and one parallel test (small worker count) asserts only that all jobs complete, events fire once per transition, and JSONL lines are individually parseable.
- **Modules tested**: the new batch runner tests; one additive test on the single-part build confirming the progress callback fires at the expected stage boundaries without altering behavior.
- **Hermeticity**: the existing fixtures are the whole toolkit — synthetic PDFs built in-test via fitz, `MappingFetcher`-replayed TI HTML, `UseLLM=False` or a fake LLM client, `Settings(parts_dir=tmp, cache_dir=tmp)` with the `reset_settings_cache` hook. No network, no real LLM.
- **Prior art**: `synthetic_env` in the pipeline tests (temporary settings + mapping fetcher + backend-registry monkeypatch, calling the seam function directly) is the pattern the batch tests extend to N PDFs in one directory; JSONL/log assertions follow the style of the extraction-cache tests, and the multiple-document fixtures in the integration tests show the multi-doc shape.

## Out of Scope

- Companion documents (`add-doc`) inside a batch — a batch is datasheet-only; companions keep their existing command.
- Recursive directory walks, glob patterns, or any part-naming rule beyond the uppercase stem.
- Resume bookkeeping beyond what extraction cache + hash-gated skip already provide, and any in-run retry logic (ADR 0001).
- Log pruning, rotation, or dashboards/tail tooling for batch logs.
- Live progress-bar rendering or interactive terminal UI.
- Surfacing batch state in `dsa status`.

## Further Notes

- Architectural record: `docs/adr/0001-batch-build-command.md`.
- Domain vocabulary: Batch, Job, Part, Build per `CONTEXT.md`.
- The skip-if-up-to-date rule leans on the model invariant that `content_hash` (sha256 of PDF bytes) is a `SourceDocument`'s identity.
- After implementation, measured batch behavior (worker scalings, log shapes) belongs in the next phase report and this spec should be closed as superseded by that record.
