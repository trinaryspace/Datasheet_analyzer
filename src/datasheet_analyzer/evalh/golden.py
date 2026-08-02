"""Golden Q&A loader + report renderer.

The golden set lives in tests/fixtures/golden_qa.yaml and doubles as the
project's datasheet QA benchmark (no public one exists). `verify` mode is
deterministic; the optional `qa` mode (needs an LLM key) simulates an agent
answering from the corpus and measures tokens consumed.
"""

from __future__ import annotations

from pathlib import Path

from datasheet_analyzer.evalh.citations import (
    QuestionResult,
    load_golden_yaml,
    summarize,
)
from datasheet_analyzer.models import GoldenQuestion
from datasheet_analyzer.tokens import count_tokens


def load_golden(path: Path) -> list[GoldenQuestion]:
    return load_golden_yaml(path)


def render_verification_report(results: list[QuestionResult]) -> str:
    summary = summarize(results)
    lines = [
        "## Golden Q&A verification (deterministic)",
        "",
        (
            f"**{summary['passed']}/{summary['total']} passed "
            f"({summary['accuracy']:.0%})** — each question checks that the corpus "
            "section covering the cited page contains the expected answer values "
            "AND that the cited PDF page itself contains them."
        ),
        "",
        "| # | Question | Pages | Corpus has answer | Page cite correct |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        q = r.question
        pages = ", ".join(f"p.{p}" for p in q.pages)
        lines.append(
            f"| {i} | {q.question} | {pages} | "
            f"{'✅' if r.corpus_contains else '❌'} | "
            f"{'✅' if r.page_truth else '❌'} |"
        )
    failures = [r for r in results if not r.passed]
    if failures:
        lines += ["", "### Failures", ""]
        for r in failures:
            lines.append(
                f"- **{r.question.id}** missing: {r.missing} "
                f"(sections checked: {r.matched_files or 'NONE — no section covers cited page'})"
            )
    lines.append("")
    return "\n".join(lines)


def estimate_lookup_tokens(part_dir: Path, results: list[QuestionResult]) -> dict:
    """Token cost the corpus path pays per question, measured on real files:
    INDEX.md (read once) + the covering section file(s) per question.
    Compares against dumping the whole extracted text into context."""
    part_dir = Path(part_dir)
    index_tokens = count_tokens((part_dir / "INDEX.md").read_text(encoding="utf-8"))

    per_question: list[int] = []
    for r in results:
        section_tokens = 0
        for rel in r.matched_files[:1]:  # agent opens the first covering section
            f = part_dir / rel
            if f.exists():
                section_tokens += count_tokens(f.read_text(encoding="utf-8"))
        per_question.append(index_tokens + section_tokens)

    total_section_tokens = sum(
        count_tokens(f.read_text(encoding="utf-8"))
        for f in part_dir.rglob("sections/*.md")
    )
    return {
        "index_tokens": index_tokens,
        "per_question": per_question,
        "avg_per_question": (
            sum(per_question) / len(per_question) if per_question else 0
        ),
        "max_per_question": max(per_question, default=0),
        "full_dump_tokens": total_section_tokens,
    }
