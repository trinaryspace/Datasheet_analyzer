"""Citation verification: prove the corpus can answer golden questions
WITH correct page citations — deterministically, no LLM.

For each golden question we check, per expected substring:
1. corpus_contains — the section file whose page range covers the cited
   page contains the substring (corpus completeness), and
2. page_truth — the actual PDF page text contains it (citation correctness).

Matching is two-tier: exact containment first, then an alnum-squashed
comparison that is immune to dash/space/ligature differences between the
HTML source and PDF text layer.

Golden questions carrying a `spec_query` / `plot_query` are verified here too
(`verify_spec_queries` / `verify_plot_queries`), against the retrieval core.
That work used to sit inline in `cli.py`; retrieval and its pass/fail rules
belong behind the seam, and the CLI now only renders the results.

Phase 5, ticket 09 adds the two paths the phase itself introduced —
`verify_ask_queries` (a designer's words through `dsa ask`) and
`verify_search_queries` (the same words through `dsa search`). Both are
deliberately judged against the *existing* ground truth: the question's own
cited pages and expected substrings, which were read off the printed page. A
new surface that agrees with the old objective function is proven; one judged
by a new objective function is only asserted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from datasheet_analyzer.models import GoldenQuestion, SpecRecord
from datasheet_analyzer.retrieve import AnswerPack, CorpusIndex, PlotHit, Retriever, SpecHit

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
        index = CorpusIndex.load(part_dir)
        for rel in res.matched_files:
            # Through the corpus index, not `part_dir / rel`: a document
            # published once into the shared store (ticket 04) is referenced
            # as `@library/docs/…` and joining that onto the part directory
            # would name a file that is not there — silently turning every
            # golden answer into "the corpus does not contain it".
            f = index.corpus_path(rel)
            if f is not None and f.exists():
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


@dataclass
class QueryResult:
    """Outcome of one golden `spec_query` / `plot_query` / `ask_query` /
    `search_query`.

    `n_records` is how many records the query matched at all; `n_verified` is
    how many survived the page + value check (for plots, how many also have an
    on-disk image file). The gap between them is what the report shows when a
    question fails.

    The rest is measurement the ticket-09 paths report rather than assert:
    which `route` an answer pack took, what it `tokens` cost against its
    `budget`, and a `detail` line the renderer prints verbatim — the reason
    belongs next to the rule that produced it, not in the front end.
    """

    question: GoldenQuestion
    ok: bool = False
    n_records: int = 0
    n_verified: int = 0
    route: str = ""
    tokens: int = 0
    budget: int = 0
    detail: str = ""


def _spec_fields(rec: SpecRecord) -> str:
    """Every verbatim field a golden expected-substring may match against."""
    return (
        f"{rec.symbol} {rec.name} {rec.conditions} "
        f"{rec.min} {rec.typ} {rec.max} {rec.value} "
        f"{rec.unit.verbatim} {rec.unit.canonical}"
    )


def verify_spec_queries(
    questions: list[GoldenQuestion], part_dir: Path
) -> list[QueryResult]:
    """Deterministic spec-lookup verification for every `spec_query` golden.

    Multi-row answers (e.g. DSA range + step, VCO coverage) are verified across
    the whole result set: every expected substring must appear on at least one
    record whose page is in the question's cited page list.
    """
    retriever = Retriever.for_part(part_dir)
    results: list[QueryResult] = []
    for q in questions:
        if not q.spec_query:
            continue
        hits: list[SpecHit] = retriever.specs(**q.spec_query)
        paged = [h for h in hits if h.record.page is not None and h.record.page in q.pages]
        ok = bool(paged) and all(
            any(contains(_spec_fields(h.record), sub) for h in paged)
            for sub in q.expected_substrings
        )
        results.append(
            QueryResult(question=q, ok=ok, n_records=len(hits), n_verified=len(paged))
        )
    return results


def verify_plot_queries(
    questions: list[GoldenQuestion], part_dir: Path
) -> list[QueryResult]:
    """Deterministic plot-lookup verification for every `plot_query` golden.

    A plot question passes only when a matching record is on a cited page AND
    its image file exists on disk at more than 1 KB — a catalog entry without
    pixels is not an answer.
    """
    part_dir = Path(part_dir)
    retriever = Retriever.for_part(part_dir)
    results: list[QueryResult] = []
    for q in questions:
        if not q.plot_query:
            continue
        query = q.plot_query
        hits: list[PlotHit] = retriever.plots(
            caption=query.get("caption_contains", ""),
            conditions=query.get("conditions_contain", ""),
            section=query.get("section", ""),
        )
        paged = [
            h for h in hits
            if h.record.page_start is not None and h.record.page_start in q.pages
        ]
        with_files = [h for h in paged if _plot_file_present(part_dir, h.file)]
        ok = bool(with_files)
        if ok and q.expected_substrings:
            text = " ".join(h.record.caption + " " + h.record.conditions for h in with_files)
            ok = all(contains(text, sub) for sub in q.expected_substrings)
        results.append(
            QueryResult(
                question=q, ok=ok, n_records=len(hits), n_verified=len(with_files)
            )
        )
    return results


def pack_answers_question(question: GoldenQuestion, pack: AnswerPack) -> bool:
    """The symbol path's own pass rule, applied to an answer pack's rows.

    Deliberately identical to `verify_spec_queries`: at least one answer row
    must sit on a page the question cites, and every expected substring must
    appear on one of those rows. Only *cited* rows may satisfy it — a pack that
    prints the right number beside the wrong page has not answered the
    question, and the whole claim of the phase is that the designer's wording
    reaches the same verbatim answer on the same printed page.
    """
    paged = [
        line for line in pack.answers
        if line.page_start is not None and line.page_start in question.pages
    ]
    return bool(paged) and all(
        any(contains(line.text, sub) for line in paged)
        for sub in question.expected_substrings
    )


def verify_ask_queries(
    questions: list[GoldenQuestion], part_dir: Path, *, budget: int = 0
) -> list[QueryResult]:
    """Ask-path verification for every `ask_query` golden (ticket 09).

    One `dsa ask` call must do what the symbol path does — land the same
    verbatim answer on the same cited page — **and stay inside its budget**.
    Budget compliance is part of the pass rule rather than a separate check,
    because an answer that only fits by going over is not the product this
    phase claims. When the golden names a route (`{route: spec}`), routing
    must match too: a question that used to be answered by a record and is now
    answered by a paragraph has regressed even if the text still matches.
    """
    retriever = Retriever.for_part(part_dir)
    results: list[QueryResult] = []
    for q in questions:
        if q.ask_query is None:
            continue
        pack = retriever.ask(q.question, budget=budget)
        expected_route = (q.ask_query.get("route") or "").strip()
        paged = [
            line for line in pack.answers
            if line.page_start is not None and line.page_start in q.pages
        ]
        route_ok = not expected_route or pack.route == expected_route
        answered = pack_answers_question(q, pack)
        ok = answered and route_ok and not pack.over_budget
        if ok:
            detail = f"{len(paged)} cited row(s), {pack.tokens}/{pack.budget} tok"
        elif not route_ok:
            detail = f"routed {pack.route}, expected {expected_route}"
        elif pack.over_budget:
            detail = f"over budget: {pack.tokens}/{pack.budget} tok"
        else:
            detail = f"{len(paged)}/{len(pack.answers)} row(s) on a cited page"
        results.append(
            QueryResult(
                question=q,
                ok=ok,
                n_records=len(pack.answers),
                n_verified=len(paged),
                route=pack.route,
                tokens=pack.tokens,
                budget=pack.budget,
                detail=detail,
            )
        )
    return results


def verify_search_queries(
    questions: list[GoldenQuestion], part_dir: Path
) -> list[QueryResult]:
    """Search-path verification for every `search_query` golden (ticket 09).

    The rule is the ticket's: the **top-1** hit must be the section that holds
    the hand-verified answer — it must cover a page the question cites, and its
    own text must contain every expected substring. Rank matters because a
    designer reads the first hit; a corpus that buries the answer at rank 4 has
    not made it findable. `{rank: N}` widens that to "inside the top N" for a
    question whose answer legitimately lives in one of several sections.

    A corpus with no current search index is a *failure with a reason*, never a
    silent pass: the path could not run, so nothing was established.
    """
    retriever = Retriever.for_part(part_dir)
    results: list[QueryResult] = []
    for q in questions:
        if q.search_query is None:
            continue
        query = q.search_query.get("query") or q.question
        rank = max(1, int(q.search_query.get("rank") or 1))
        hits = retriever.search(query, limit=max(rank, 5))
        covering = {
            hit.section.file
            for page in q.pages
            for hit in retriever.sections(page=page)
        }
        matched = 0
        detail = ""
        for position, hit in enumerate(hits[:rank], 1):
            if hit.section.file not in covering:
                continue
            body = retriever.section_text(hit.section)
            if all(contains(body, sub) for sub in q.expected_substrings):
                matched += 1
                detail = f"rank {position} of {rank} allowed: {hit.citation.label}"
                break
        if not matched:
            unavailable = retriever.search_unavailable()
            if unavailable:
                detail = f"search unavailable: {unavailable}"
            elif hits:
                detail = f"top hit {hits[0].citation.label} is not the cited section"
            else:
                detail = "no hit"
        results.append(
            QueryResult(
                question=q,
                ok=bool(matched),
                n_records=len(hits),
                n_verified=matched,
                detail=detail,
            )
        )
    return results


def _plot_file_present(part_dir: Path, rel_file: str) -> bool:
    """Whether a `PlotRecord.file` names real image bytes for this part.

    Resolved through the corpus index rather than joined onto `part_dir`:
    `PlotRecord.file` is anchored to the root its `plots.json` sits under, and
    ticket 04 moves that root to the shared store for a document published
    once and referenced by many parts.
    """
    if not rel_file:
        return False
    path = CorpusIndex.load(part_dir).corpus_path(rel_file)
    if path is None:
        return False
    try:
        return path.exists() and path.stat().st_size > 1024
    except OSError:
        return False


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
