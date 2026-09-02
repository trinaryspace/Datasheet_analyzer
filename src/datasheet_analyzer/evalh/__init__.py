"""Eval harness: golden Q&A verification against corpus + ground truth.

Two halves, and the boundary between them is invariant 5:

- `citations` / `golden` **verify** a benchmark. `golden_qa_<PART>.yaml` is the
  objective function, hand-verified, and `dsa verify` fails the corpus rather
  than the question.
- `suggest` / `confirm` / `candidates` (phase 7, ticket 06) make writing one
  affordable. They produce *candidates*, which are proposals: nothing they
  write counts toward `dsa verify` until a human confirms it and it lands in
  the benchmark file. The tooling reduces typing, never judgment.
"""

from datasheet_analyzer.evalh.candidates import (
    GoldenAssistError,
    candidate_path,
    read_candidates,
    rejected_keys,
    rejected_path,
    write_candidates,
    write_rejections,
)
from datasheet_analyzer.evalh.citations import QuestionResult, verify_questions
from datasheet_analyzer.evalh.confirm import (
    Decision,
    apply_decisions,
    load_decisions,
    merge_into_golden,
    page_context,
    render_candidate,
    run_interactive,
)
from datasheet_analyzer.evalh.golden import default_golden_path, golden_dir, load_golden
from datasheet_analyzer.evalh.suggest import suggest_candidates

__all__ = [
    "Decision",
    "GoldenAssistError",
    "QuestionResult",
    "apply_decisions",
    "candidate_path",
    "default_golden_path",
    "golden_dir",
    "load_decisions",
    "load_golden",
    "merge_into_golden",
    "page_context",
    "read_candidates",
    "rejected_keys",
    "rejected_path",
    "render_candidate",
    "run_interactive",
    "suggest_candidates",
    "verify_questions",
    "write_candidates",
    "write_rejections",
]
