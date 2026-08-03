# 0001: batch build command

Status: accepted

`dsa batch <dir>` builds every PDF directly in `<dir>` as its own part corpus
in one invocation. A batch is just a directory — no spec file, no inline
pairs, no name inference from PDFs beyond the stem. Each job (PDF → part,
part = uppercase filename stem) runs its full build (acquire → extract →
structure → enrich → publish) as one isolated unit inside a bounded thread
pool (`--workers`, default 4); jobs whose part corpus exists and whose PDF
sha256 matches the recorded inventory hash are skipped as up-to-date. Every
stage transition emits one event, printed to the terminal and appended to
`.cache/batches/<dirstem>-<run>/batch.jsonl`: the JSONL is the monitoring
source of truth. A failed job records its error and the batch continues;
exit code 0 = all passed, 1 = any failed.

Addendum (vendor-neutral layout core, ADR 0003): the "workload is network-
and LLM-bound, PyMuPDF releases the GIL" rationale predates the offline
`pdf_layout` engine. Batches now mix network-bound HTML jobs (ti_html, LLM
enrichment) with CPU-bound offline jobs (layout inference — pure Python
clustering under the GIL). The thread-pool decision is retained for now —
`--workers` remains a capacity knob, not a wall-clock promise — but worker
placement (threads vs processes) must be revisited with measured scaling
when pdf_layout lands. Vendor is detected and evidence-pinned per job, never
per directory, so a mixed-vendor batch stays vendor-free by construction.

Considered and rejected:

- Descriptor file (YAML listing pdf/part pairs) — stable identity and resume
  story, but the user's worked patterns always ran the whole directory;
  cache + hash-gating makes reruns cheap enough that resume was unnecessary.
- Inline `--part A a.pdf --part B b.pdf` pairs — unreadable at batch scale.
- Glob + filename inference (`dsa build "*.pdf"`) — fragile naming rules that
  silently build wrong part names.
- Process pool — Windows `multiprocessing.spawn` re-import cost and pydantic
  pickling trouble for no measurable gain: the workload is network- and
  LLM-bound, and PyMuPDF releases the GIL.
- In-run retry on failure — cache makes a rerun of the batch the retry
  mechanism; retrying inside the run only hides transient state.
