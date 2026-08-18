# 26 — The scan says what it already knows

**Owns:** `src/datasheet_analyzer/app/buildstate.py`,
`src/datasheet_analyzer/app/routers/review.py`,
`src/datasheet_analyzer/app/contracts.py` (DocProposal only),
`web/src/routes/analyze/ReviewStep.tsx`, `tests/unit/test_buildstate.py`

**Problem.** `POST /api/analyze/scan` returns a proposal per PDF with no
indication that a document is already built and current. `DocProposal` already
carries `content_hash`, so the answer is one manifest read away.

**Build.** A pure classifier, `app/buildstate.py`:

```python
BuildState = Literal["new", "current", "stale", "changed"]
def classify(pdf_path, part_number, content_hash, *, settings) -> tuple[BuildState, str]
```

- `current` — `batch.skip_reason` returns a reason. Carry that reason verbatim.
- `new` — no manifest for the part.
- `changed` — manifest exists, this `content_hash` is not among its documents.
- `stale` — manifest exists and the hash matches, but the gate still says
  build: the pipeline or extractor version moved. Say which.

Reuse `batch.skip_reason`, never a second gate. It never raises; a failure to
verify means build, and this must inherit that.

`DocProposal` gains `build_state: BuildState = "new"` and `build_reason: str`.

- [ ] A PDF built at the current pipeline classifies `current` with the gate's own reason
- [ ] A PDF never seen classifies `new`
- [ ] A corpus at an older `PIPELINE_VERSION` classifies `stale`, and the reason names the version move
- [ ] Editing the PDF (new hash, same part) classifies `changed`
- [ ] Renaming the file changes nothing — identity is the content hash
- [ ] Classification writes nothing: `parts_dir`, `library_dir`, `cache_dir` byte-identical after a scan
- [ ] `ScanOut` carries counts so a caller need not tally rows itself
