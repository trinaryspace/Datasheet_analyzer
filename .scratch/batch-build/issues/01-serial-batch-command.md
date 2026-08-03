# 01 — Serial batch command

**What to build:** `dsa batch <dir>` builds every PDF directly inside the
directory as its own part corpus in one invocation. The directory is scanned
flat (direct children only) for `.pdf` files case-insensitively, processed in
sorted filename order; the part number for each job is the filename stem,
uppercased. The full file→part mapping prints before any work starts, then
each job runs end to end (acquire → extract → structure → enrich → publish)
serially, reusing the existing single-part pipeline. A failing job records its
error and the remaining jobs continue. The run ends with a per-job summary
table; non-PDF files are ignored; an empty or missing directory is a clear
error. New `batch` runner module with a thin CLI wrapper; `--no-cache` and
`--no-llm` behave as in `build`.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [x] `dsa batch <dir>` builds one part corpus per PDF directly in `<dir>`, with part number = uppercase filename stem
- [x] Scan is flat and case-insensitive; non-PDF files are ignored; jobs run in sorted filename order
- [x] The file→part mapping is printed before any build work starts
- [x] A failing job (bad/corrupt PDF, extraction error) is isolated: its error is captured, remaining jobs complete
- [x] Final summary table lists every job with its outcome (done/failed)
- [x] Process exit code is 0 when all jobs passed, 1 when any failed; empty or missing directory is a clear error path (exit 2)
- [x] `--no-cache` / `--no-llm` behave identically to `build`
- [x] `build`, `add-doc`, `verify`, `query`, `status` are unchanged
