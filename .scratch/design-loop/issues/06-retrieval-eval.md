# 06 — Retrieval evaluation + unanswered-question log

**What to build:** Goldens gate *answers*. This gates the layer beneath them.
`dsa eval retrieval` measures recall@1/@5/@10 and MRR for the retrieval core
across the fleet, using the existing goldens as ground truth, with a
checked-in budget file so a regression is a red test rather than a discovery.

Plus the loop that makes the golden set grow where it is actually weak: an
unanswered-question log fed by real `dsa ask` usage into Phase 7's
`golden suggest`.

**Blocked by:** — (independent)

**Status:** ready-for-agent

- [ ] `dsa eval retrieval` reports recall@1/@5/@10 and MRR, broken down by
      query kind (spec, pin, register, free text) and by extraction backend
- [ ] `registry/retrieval_budget.yaml` records the current numbers; the suite
      fails when a metric drops beyond the stated tolerance
- [ ] A **seeded retrieval regression** is asserted to fail the budget test —
      a budget nothing can trip is not a budget
- [ ] Ground truth comes from the existing goldens; no new hand-labelled
      relevance corpus is introduced
- [ ] `dsa ask` appends questions that returned empty or low-confidence
      answers to an `unanswered.jsonl` log, with the question, the timestamp
      source, and why it was judged weak
- [ ] The log is consumable by Phase 7's `golden suggest` — asserted by a test
      that feeds one through
- [ ] Logging is **off by default or clearly opt-in**, and never records
      anything beyond the question and the retrieval outcome
- [ ] Tests remain hermetic and free of wall-clock dependence

---

Source: `.scratch/design-loop/SPEC.md`
