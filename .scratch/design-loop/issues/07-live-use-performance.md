# 07 — Live-use performance

**What to build:** Mid-capture means seconds matter. Make rebuilds incremental,
keep the retrieval index warm, and measure query latency against a checked-in
budget with a generous ceiling.

The correctness half of this ticket matters more than the speed half: an
incremental rebuild that is faster but *different* is a correctness bug
wearing a performance costume.

**Blocked by:** — (independent; touches build and the retrieval core)

**Status:** ready-for-agent

- [ ] `dsa build` re-does only documents whose source hash or extractor
      version changed; everything else is reused from the published corpus
- [ ] An incremental rebuild produces a **byte-identical** corpus to a full
      rebuild — asserted, not assumed
- [ ] A changed source PDF, a bumped `PIPELINE_VERSION`, and a changed
      extractor version each correctly force a rebuild — all three asserted
- [ ] The retrieval core loads its BM25 index and record tables **once per
      process**; the MCP server keeps them resident across calls
- [ ] p50/p95 measured for `ask`, `search`, `query`, `pins`, `regs` across the
      fleet and recorded in the phase report
- [ ] `registry/perf_budget.yaml` holds the ceilings; performance tests assert
      against the file, never against constants embedded in test code
- [ ] Ceilings are generous enough not to flake on a loaded machine, and the
      justification for each is written down
- [ ] Cache and reuse keying follows the existing identity rules — do not
      introduce a second caching scheme

---

Source: `.scratch/design-loop/SPEC.md`
