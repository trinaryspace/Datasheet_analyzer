# 03 — Stage events and the JSONL batch log

**What to build:** Every job stage transition (`queued → extracting →
structuring → enriching → publishing → done/failed/skipped`) is emitted
twice: as one prefixed, line-buffered terminal line per event, and as one
JSON object appended to a per-run JSONL log under the cache directory
(keyed by source directory stem plus run-start timestamp, with a header
event carrying the full job list). The JSONL is the authoritative monitoring
record — tailable, greppable by part. Concurrency safety is by construction
(single line per event; no mid-line interleaving). The single-part build
gains an additive progress callback invoked at stage boundaries with a
no-op default, so existing callers and tests are unaffected. Failed and
skipped jobs still appear in the log with their detail.

**Blocked by:** 01 — Serial batch command

**Status:** ready-for-agent

- [ ] Terminal shows one prefixed stage line per job transition (no interleaving, even later under parallelism)
- [ ] A per-run JSONL file is written under the cache directory with a header event listing the jobs
- [ ] Every event is a single parseable JSON object carrying job id, part, stage, timestamp, detail
- [ ] Done, failed, and skipped jobs all appear in the log with their detail (error text for failures, reason for skips — skip states arriving via ticket 2)
- [ ] Existing calls to the single-part build without the callback behave exactly as before (additive change)
- [ ] The log file path clearly identifies the source directory and the run
