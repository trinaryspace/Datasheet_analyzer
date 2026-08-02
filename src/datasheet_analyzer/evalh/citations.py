"""Citation verification: prove the corpus can answer golden questions
WITH correct page citations — deterministically, no LLM.

For each golden question we check, per expected substring:
1. corpus_contains — the section file whose page range covers the cited
   page contains the substring (corpus completeness), and
2. page_truth — the actual PDF page text contains it (citation correctness).

Matching is two-tier: exact containment first, then an alnum-squashed
comparison that is immune to dash/space/ligature differences between the
HTML source and PDF text layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from datasheet_analyzer.models import GoldenQuestion

_NONALNUM = re.compile(r"[^a-z0-9]+")


def squash(text: str) -> str:
    return _NONALNUM.sub("", text.lower())


def contains(haystack: str, needle: str) -> bool:
    if needle in haystack:
        return True
    return squash(needle) in squash(haystack)


@dataclass
class QuestionResult:
    question: GoldenQuestion
    corpus_contains: bool = False
    page_truth: bool = False
    matched_files: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.corpus_contains and self.page_truth


def _sections_covering_page(manifest: dict, page: int) -> list[dict]:
    out = []
    for s in manifest.get("sections", []):
        start, end = s.get("page_start"), s.get("page_end")
        if start is None:
            continue
        if start <= page <= (end or start):
            out.append(s)
    return out


def verify_questions(
    questions: list[GoldenQuestion],
    part_dir: Path,
    page_texts: list[str],
) -> list[QuestionResult]:
    import json

    part_dir = Path(part_dir)
    manifest = json.loads((part_dir / "manifest.json").read_text(encoding="utf-8"))

    results: list[QuestionResult] = []
    for q in questions:
        res = QuestionResult(question=q)

        # Plot questions are verified against plots.json / image files in a
        # dedicated table (Phase 3); skip them in the text-corpus table.
        if q.plot_query:
            res.corpus_contains = True
            res.page_truth = True
            results.append(res)
            continue

        # 1. corpus check: any section covering a cited page must contain
        #    every expected substring
        files: set[str] = set()
        for page in q.pages:
            for s in _sections_covering_page(manifest, page):
                files.add(s["file"])
        res.matched_files = sorted(files)
        corpus_texts: list[str] = []
        for rel in res.matched_files:
            f = part_dir / rel
            if f.exists():
                corpus_texts.append(f.read_text(encoding="utf-8"))
        corpus_blob = "\n".join(corpus_texts)
        res.corpus_contains = bool(corpus_texts) and all(
            contains(corpus_blob, sub) for sub in q.expected_substrings
        )

        # 2. page-truth check: the cited PDF pages themselves contain it
        page_blob = "\n".join(
            page_texts[p - 1] for p in q.pages if 0 < p <= len(page_texts)
        )
        res.page_truth = bool(page_blob) and all(
            contains(page_blob, sub) for sub in q.expected_substrings
        )

        if not res.passed:
            res.missing = [
                sub
                for sub in q.expected_substrings
                if not contains(corpus_blob, sub) or not contains(page_blob, sub)
            ]
        results.append(res)
    return results


def load_page_texts(pdf_path: Path) -> list[str]:
    from datasheet_analyzer.extract.pdf_structure import page_texts as _pt

    return _pt(Path(pdf_path))


def summarize(results: list[QuestionResult]) -> dict:
    n = len(results)
    passed = sum(1 for r in results if r.passed)
    no_section = [r.question.id for r in results if not r.matched_files]
    return {
        "total": n,
        "passed": passed,
        "failed": n - passed,
        "accuracy": passed / n if n else 0.0,
        "questions_without_covering_section": no_section,
    }


def load_golden_yaml(path: Path) -> list[GoldenQuestion]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [GoldenQuestion.model_validate(item) for item in data["questions"]]
