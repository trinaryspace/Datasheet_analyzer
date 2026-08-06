# 08 — Shipped docs and measured report

**What to build:** The architecture contract catching up with reality —
AGENTS.md invariant wording (vendor-neutral layout core supersedes the
no-layout-analysis stance; ungated real-PDF fixtures; both ohm glyphs;
`--vendor`; pdf_layout backend in the architecture table), README updates,
and the measured phase report with token economics, extraction stats, and
verify results across the four gate parts; the spec is superseded by the
report as the completion record.

**Blocked by:** 07 — Gate provisioning + per-part golden Q&A

**Status:** shipped (commit on `feat/pdf-layout-paragraph-core`, ticket 08)

- [x] No stale "layout analysis avoided" doctrine remains in AGENTS.md or module docstrings
- [x] AGENTS.md documents: pdf_layout backend, thin VendorProfile routing, ungated real-PDF fixture class, both-ohm glyph rule, `--vendor` usage
- [x] README covers building non-TI parts and the multi-vendor verification workflow
- [x] The phase report records measured numbers: corpus token economics, extraction stats (detected/accepted/rejected), verify accuracy per gate part
- [x] `.scratch/vendor-neutral-layout/SPEC.md` is marked superseded by the report (matching the batch-build convention)

---

**Ship notes (what had already landed vs what this ticket changed):**

1. **Shipped-in-earlier-tickets items** (recorded, not re-done): the
   AGENTS.md module table already carried `extract/pdf_layout.py`,
   `vendor.py` ("routing record, not a rulebook"), invariant #4's ungated
   real-PDF fixture class and invariant #5's per-part goldens, the
   `--vendor` build example, and the "342 tests, ~85 s" suite line were
   all landed by tickets 01–07. This ticket verified each letter item
   against the files and filled only the real gaps: a gate-parts table +
   `--vendor unknown` build example + non-TI verify example in AGENTS.md;
   gate-parts rows for LM741's pin; and the phase-4 plan in the
   superseded-records lists.
2. **Doctrine removed**: README's `## Caveats` "Content path is
   TI-specific — other vendors need a new extraction backend" (dead since
   ticket 02/03) became the vendor-neutral statement; the `detect_vendor`
   docstring's "backend does not exist yet" line is rewritten; the
   PyMuPDF "structure/verification only" lines in README/AGENTS.md now
   name it as the `pdf_layout` extraction floor; the AGENTS.md ohm gotcha
   generalized to the both-glyph rule (PHASE_4_PLAN's documented landing
   requirement). Historical records (ADRs, PHASE_1_REPORT, the plan) were
   left as written.
3. **Measured report**: `Reports/PHASE_4_REPORT.md` supersedes
   `PHASE_4_PLAN.md` (and this SPEC). Every number was re-measured on this
   commit from repo state (fresh `build_part(use_llm=False)` per part from
   the ungated fixtures + `dsa verify` per part + the gate test's pin
   check). Deliberate honest deltas vs earlier session estimates:
   HMC520A figures 107 (not 110) and LM741 figures 3 (not 5) — the 05
   issue file's numbers were estimates; the report and the AGENTS.md gate
   table carry the measured ones. AD9081's exact numbers (previously only
   test bounds): 34 sections, 29/29/0 tables, fidelity 0.902, 547 specs,
   **100** figures/plot files (the ledger's "101/101" from ticket 05 was
   already stale), 19 footnotes, 21,238 corpus tokens / 2,904 INDEX.
4. **Honesty boundaries kept**: the report claims 88.9% (168/189) exact-
   page pinning and states the ≥80% band + continuation-row cause per the
   ledger; the lm741/QPA1003P 0-table corpora are recorded as OPEN
   (ticket 09) with the gate test asserting the honest zeros — the report
   does not overstate either.
5. **Also in this commit**: unused `GOLDEN_QA` constant removed from
   `tests/conftest.py` (07 review note); ledger header bumped to "as of
   ticket 08" with the docs catch-up recorded.

---

Source: `.scratch/vendor-neutral-layout/SPEC.md`
