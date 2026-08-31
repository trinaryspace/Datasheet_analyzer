"""Golden Q&A loader + report renderer.

Golden sets live per part in tests/fixtures/golden_qa_<PART>.yaml (the
AFE7950 benchmark doubled as the project's datasheet QA benchmark; no
public one exists). `verify` mode is deterministic; the optional `qa`
mode (needs an LLM key) simulates an agent answering from the corpus and
measures tokens consumed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from datasheet_analyzer.evalh.citations import (
    QueryResult,
    QuestionResult,
    load_golden_yaml,
    summarize,
)
from datasheet_analyzer.models import GoldenQuestion
from datasheet_analyzer.retrieve import CorpusIndex
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


def _query_report(
    title: str,
    results: list[QueryResult],
    query_field: str,
    detail: Callable[[QueryResult], str],
) -> str:
    passed = sum(1 for r in results if r.ok)
    lines = [
        f"## {title} (deterministic)",
        "",
        f"**{passed}/{len(results)} passed**",
        "",
        "| # | Question | Query | Result |",
        "|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        query = getattr(r.question, query_field) or {}
        query_str = ", ".join(f"{k}={v!r}" for k, v in query.items())
        status = "✅" if r.ok else "❌"
        lines.append(f"| {i} | {r.question.question} | {query_str} | {status} {detail(r)} |")
    return "\n".join(lines)


def render_spec_query_report(results: list[QueryResult]) -> str:
    """Spec-query verification table (the `dsa verify --specs` block)."""

    def detail(r: QueryResult) -> str:
        if r.ok:
            return f"{r.n_records} record(s)"
        return f"{r.n_records} record(s), page/value mismatch"

    return _query_report("Spec query verification", results, "spec_query", detail)


def render_plot_query_report(results: list[QueryResult]) -> str:
    """Plot-query verification table (always run when goldens carry plots)."""

    def detail(r: QueryResult) -> str:
        if r.ok:
            return f"{r.n_verified} plot file(s)"
        return f"{r.n_records} match(es), {r.n_verified} valid file(s)"

    return _query_report("Plot query verification", results, "plot_query", detail)


def render_ask_query_report(results: list[QueryResult]) -> str:
    """Ask-path verification table (ticket 09; runs whenever a golden set
    carries `ask_query` questions). The detail column is the verifier's own
    sentence — route, cited rows, and the measured tokens against the budget —
    because the reason a rule passed or failed belongs with the rule."""
    return _query_report("Ask-path verification", results, "ask_query", lambda r: r.detail)


def render_search_query_report(results: list[QueryResult]) -> str:
    """Search-path verification table (ticket 09): top-1 must be the section
    that holds the hand-verified answer."""
    return _query_report("Search-path verification", results, "search_query", lambda r: r.detail)


def render_token_economics(tokens: dict) -> str:
    """Measured per-question token cost of the corpus lookup path."""
    return "\n".join(
        [
            "## Token cost per question (measured on the built corpus)",
            "",
            f"- INDEX.md (always loaded): {tokens['index_tokens']} tokens",
            (f"- avg question total (index + section): {tokens['avg_per_question']:.0f} tokens"),
            f"- worst question total: {tokens['max_per_question']} tokens",
            f"- naive full-corpus dump: {tokens['full_dump_tokens']} tokens",
        ]
    )


def estimate_lookup_tokens(part_dir: Path, results: list[QuestionResult]) -> dict:
    """Token cost the corpus path pays per question, measured on real files:
    INDEX.md (read once) + the covering section file(s) per question.
    Compares against dumping the whole extracted text into context."""
    part_dir = Path(part_dir)
    index_tokens = count_tokens((part_dir / "INDEX.md").read_text(encoding="utf-8"))
    # Both halves of the measurement have to follow the part's documents to
    # wherever they were published: ticket 04 writes a shared document once
    # into the library and references it from the part, so an `rglob` under
    # the part would measure the "whole corpus" as zero and make the
    # comparison below trivially true.
    index = CorpusIndex.load(part_dir)

    per_question: list[int] = []
    for r in results:
        section_tokens = 0
        for rel in r.matched_files[:1]:  # agent opens the first covering section
            f = index.corpus_path(rel)
            if f is not None and f.exists():
                section_tokens += count_tokens(f.read_text(encoding="utf-8"))
        per_question.append(index_tokens + section_tokens)

    total_section_tokens = sum(
        count_tokens(f.read_text(encoding="utf-8"))
        for doc in index.docs
        if doc.directory is not None
        for f in sorted(doc.directory.glob("sections/*.md"))
    )
    return {
        "index_tokens": index_tokens,
        "per_question": per_question,
        "avg_per_question": (sum(per_question) / len(per_question) if per_question else 0),
        "max_per_question": max(per_question, default=0),
        "full_dump_tokens": total_section_tokens,
    }


def render_card_query_report(results: list[QueryResult]) -> str:
    """Card-path verification table (phase 6, ticket 10).

    Rendered like every other query table, and read the same way: the detail
    column is the verifier's own sentence about why a card question passed or
    failed, because the reason belongs with the rule that produced it.
    """
    passed = sum(1 for r in results if r.ok)
    lines = [
        "## Design-card verification (deterministic)",
        "",
        (
            f"**{passed}/{len(results)} passed** — each question checks that the "
            "named card carries a row with the expected printed values AND that "
            "the row's own citation lands on the page the question cites."
        ),
        "",
        "| # | Question | Card | Result |",
        "|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        status = "✅" if r.ok else "❌"
        lines.append(f"| {i} | {r.question.question} | {r.question.kind} | {status} {r.detail} |")
    return "\n".join(lines)
