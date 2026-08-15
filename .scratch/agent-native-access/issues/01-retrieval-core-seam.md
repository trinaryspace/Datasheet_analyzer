# 01 — Retrieval core seam (`retrieve/`)

**What to build:** The deep module every front end will sit on. A new
`retrieve/` package with `CorpusIndex` (load a part's manifest, specs, plots,
and sections once; cache keyed on part dir + manifest mtime +
`pipeline_version`) and `Retriever` returning typed results — `SpecHit`,
`SectionHit`, `PlotHit` — each carrying citation (doc + page/range),
`confidence` (placeholder until ticket 04), and `matched_via`. `cli.py` and
`query.py` become adapters that format what the retriever returns.

Today `query.py` re-`rglob`s and re-parses every `specs.json` on every call —
fine for one CLI invocation, wrong for an MCP session making dozens.

**Blocked by:** —

**Status:** ready-for-agent

- [ ] `retrieve/index.py` + `retrieve/retriever.py` exist; `SpecQuery` and
      `find_plots` in `query.py` delegate to them and keep their signatures
      (existing callers and tests unchanged)
- [ ] A second lookup against the same part reuses the cached index (asserted
      by counting file reads, not by timing)
- [ ] Rebuilding a corpus invalidates the cache (manifest mtime change)
- [ ] Typed results carry doc, page/range, and `matched_via`; no front end
      constructs a citation string of its own
- [ ] No retrieval logic remains in `cli.py` — it formats only
- [ ] Unreadable/missing `specs.json` still degrades with a warning, not a
      crash (existing honest-degradation behaviour preserved)
- [ ] All existing tests green; `ruff` clean

---

Source: `.scratch/agent-native-access/SPEC.md`
