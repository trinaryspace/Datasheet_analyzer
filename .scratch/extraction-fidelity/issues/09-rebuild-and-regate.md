# 09 — Re-extract, rebuild, re-gate

**What to build:** The single rebuild wave 1 was shaped around, and an honest
re-measurement of every number this phase claims to have moved.

**Steps, in order:**

1. Bump `PdfLayoutBackend.output_version` **once** (`tables-08` to `tables-09`).
2. Re-extract every document in the corpus. All 196 MB of cache is invalid by
   construction; budget the machine time.
3. Rebuild all eleven parts.
4. Re-run every Phase 6 gate and every gate in this phase's acceptance list.

**Then update `KNOWN_SHORTCOMINGS.md`.** Each entry this phase closes is
deleted, with its closing number recorded in `Reports/PHASE_6_5_REPORT.md`. Each
that survives keeps its entry with a **re-measured** figure — not the Phase 6
figure carried forward. A shortcomings file whose numbers are stale is worse
than no shortcomings file, because it is read as current.

**Phase 6 ticket 06 (register bit fields) is re-attempted here, not
re-planned.** If wave 1 lifts recall past its accuracy gate, it un-parks and
ships. If it does not, its shortcoming entry is updated with the new number and
it stays parked. **The gate decides, not the schedule.**

**The regression direction matters more than the improvement direction.** All
Phase 6 gates must still pass at or above their recorded numbers — 288/288 card
provenance, 400/514 axis coverage, 90/90 goldens. A fidelity phase that improves
recall while dropping a Phase 6 number has failed, and the right response is to
find out why, not to record the new number as the new baseline.

**Also settle the corpus/pipeline version question here.** Merging Phase 6
turned eight integration gates red purely from corpus staleness, and the two
*tracked* reference corpora (`parts/AFE7950`, `parts/AFE7953`) sit at pipeline
**0.1.0** against code at 0.5.0. Wave 2 is the moment that gets decided, because
wave 2 is what rebuilds. Write an ADR answering:

1. **What pipeline version must a tracked corpus be at?** A tracked corpus older
   than the code is a fixture that has silently stopped testing what it claims.
2. **Is `library/` tracked or not?** Today it is gitignored while committed
   manifests reference `@library/...`, so a corpus published to the shared store
   is unreadable on a fresh clone. Either the library is part of the repo or
   corpora are published self-contained. Both are defensible; the mixture is
   not.
3. **Should a corpus-reading gate fail or skip when the corpus predates the
   code?** Failing is loud but breaks clones; skipping is portable but can hide
   a genuine regression. Probably: skip with the version in the skip reason, and
   assert elsewhere that at least one corpus is current.

**Blocked by:** 05, 06, 07, 08 — all of wave 1.

**Status:** done — `Reports/PHASE_6_5_REPORT.md`

- [x] `output_version` bumped once; no other cache-key change in this phase
- [x] Full re-extract and rebuild of all eleven parts completed
- [x] Every acceptance-gate item in `Reports/PHASE_6_5_PLAN.md` measured and
      recorded with its number
- [x] Every Phase 6 gate at or above its recorded number
- [x] Bit fields re-attempted; **re-parked** on the gate's verdict — four of
      the six sampled registers read exactly right (was two), recall 43% (was
      11%), precision 100%; four is not six
- [x] `KNOWN_SHORTCOMINGS.md` updated — closed entries deleted, surviving
      entries re-measured
- [x] ADR written answering the three corpus-versioning questions
- [x] `Reports/PHASE_6_5_REPORT.md` written; `Reports/PHASE_6_5_PLAN.md` marked
      superseded
- [x] `pytest` offline and green; `ruff check` and `ruff format --check` clean

**Owns:** the rebuild; `src/datasheet_analyzer/extract/pdf_layout.py`
(`output_version` only), `Reports/PHASE_6_5_REPORT.md`,
`KNOWN_SHORTCOMINGS.md`, the new ADR

---

Source: `.scratch/extraction-fidelity/SPEC.md`
