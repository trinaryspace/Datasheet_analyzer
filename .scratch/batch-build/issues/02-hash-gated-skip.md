# 02 — Hash-gated skip and --force

**What to build:** Re-running a batch over the same directory skips parts
that are already built. A job is skipped when the part corpus manifest exists
and the PDF's sha256 matches the hash recorded for that document in the
part's inventory (`content_hash` — the source document's identity). A PDF
that is new or whose bytes changed triggers a full rebuild of that part;
skipped jobs are reported with their reason in the run summary and, when
ticket 3 has landed, in the event stream. `--force` disables the check and
rebuilds every part.

**Blocked by:** 01 — Serial batch command

**Status:** ready-for-agent

- [ ] The skip gate compares the recorded inventory hash AND the manifest's
      `pipeline_version` (+ pinned vendor where present): an unchanged PDF
      built by an older pipeline version rebuilds instead of skipping
      (`PIPELINE_VERSION` bumps, e.g. 0.1.0 → 0.2.0 for the vendor-neutral
      layout core, must never leave stale corpora silently in place)
- [ ] Second run over an unchanged directory marks every already-built part as skipped (not rebuilt)
- [ ] A changed or newly added PDF rebuilds exactly that part; unchanged parts are skipped
- [ ] A part without a completed corpus (e.g. a prior failed publish with no manifest) is rebuilt, not skipped
- [ ] Skip state appears in the run summary with its reason; skips count toward success for exit code purposes
- [ ] `--force` rebuilds parts even when up to date
- [ ] The check uses the recorded inventory hash, not file mtime or size
