# 06 — Golden Q&A generation assist

**What to build:** Invariant #5 is the right objective function and it does
not survive sixty parts of hand-verification. Keep the human judgment, remove
the typing.

- `dsa golden suggest --part X --n 20` templates candidate questions from
  records that **already carry verbatim answers and pages** — spec rows, pin
  rows, register rows, plot captions — **stratified** across sections,
  backends, and confidence grades so the set is not all easy lookups. Written
  to `tests/fixtures/golden_qa_<PART>.candidate.yaml` with `confirmed: false`.
- `dsa golden confirm --part X` walks candidates in bulk (accept / edit /
  reject), showing the printed page text beside each so confirmation is a
  glance, then merges accepted items into the real golden file.

**Blocked by:** — (independent, but on the critical path: onboarding twenty
parts is unaffordable without it)

**Status:** ready-for-agent

- [ ] Candidates are stratified across sections, backends, and confidence
      grades — asserted, so the generator cannot degenerate into twenty
      variations of the easiest lookup
- [ ] Each candidate carries its answer verbatim, its page, and the record it
      came from
- [ ] **An unconfirmed candidate is asserted not to affect `dsa verify`** —
      invariant #5 survives intact; the tooling reduces typing, never judgment
- [ ] `confirm` shows the printed page text alongside each candidate
- [ ] Accepted candidates merge into `golden_qa_<PART>.yaml` without
      disturbing existing hand-written questions
- [ ] Rejected candidates are recorded so the same bad candidate is not
      re-suggested on the next run
- [ ] A part with no built corpus errors clearly rather than generating
      questions with no answers

---

Source: `.scratch/reach-and-trust/SPEC.md`
