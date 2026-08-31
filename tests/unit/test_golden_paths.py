"""The two golden paths phase 5 added: `ask_query` and `search_query`.

Phase 5, ticket 09. The gate proves these against six real datasheets; what is
proven *here* is the rule itself — that each verifier passes only for the right
reason and fails, with a stated reason, for every wrong one:

- an ask-path question passes only when the pack's **cited** rows carry the
  expected substrings, on a page the question cites, by the route the golden
  recorded, and inside the pack's own budget;
- a search-path question passes only when the **top-1** hit is a section that
  covers a cited page *and* whose text holds the answer — a corpus that buries
  the answer at rank 4 has not made it findable;
- a corpus with no current search index fails with "search unavailable", never
  passes quietly and never reads as "the datasheet does not say".

The last class checks the shipped benchmarks themselves: every one of the six
built parts carries both new paths, and every path marker is attached to a
question with the ground truth (pages + substrings) those rules judge against.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from mcp_corpus import DOC, build_part

from datasheet_analyzer.evalh.citations import verify_ask_queries, verify_search_queries
from datasheet_analyzer.evalh.golden import (
    load_golden,
    render_ask_query_report,
    render_search_query_report,
)
from datasheet_analyzer.models import GoldenQuestion

FIXTURES = Path(__file__).parent.parent / "fixtures"
#: The six built corpora of AGENTS.md invariant 5 — every one carries a
#: benchmark, and after ticket 09 every benchmark carries both new paths.
BUILT_PARTS = ["AFE7950", "AFE7953", "AD9081", "LM741", "QPA1003P", "HMC520A"]


@pytest.fixture
def part(tmp_path) -> Path:
    """The shared synthetic corpus: TJ 105 °C on p.6, DACRES on p.7,
    sections 4.3/4.5 and a real search index over their markdown."""
    return build_part(tmp_path / "parts" / "TEST")


def _ask(qid: str = "a1", **kwargs) -> GoldenQuestion:
    payload = {
        "id": qid,
        "question": "What is the maximum junction temperature?",
        "expected_substrings": ["Operating junction temperature", "105"],
        "pages": [6],
        "kind": "ask",
        "ask_query": {"route": "spec"},
    }
    payload.update(kwargs)
    return GoldenQuestion.model_validate(payload)


def _search(qid: str = "k1", **kwargs) -> GoldenQuestion:
    payload = {
        "id": qid,
        "question": "Where is the SYSREF setup requirement?",
        "expected_substrings": ["SYSREF setup time"],
        "pages": [7],
        "kind": "search",
        "search_query": {"query": "sysref setup"},
    }
    payload.update(kwargs)
    return GoldenQuestion.model_validate(payload)


class TestAskPathRule:
    def test_a_designers_words_reach_the_cited_page(self, part):
        (res,) = verify_ask_queries([_ask()], part)
        assert res.ok
        assert res.route == "spec"
        assert res.n_verified == 1
        assert 0 < res.tokens <= res.budget
        assert "tok" in res.detail

    def test_questions_without_the_marker_are_not_ask_questions(self, part):
        plain = GoldenQuestion(
            id="q1",
            question="What is the maximum junction temperature?",
            expected_substrings=["105"],
            pages=[6],
        )
        assert verify_ask_queries([plain], part) == []

    def test_the_answer_must_be_on_a_page_the_question_cites(self, part):
        """The pack answers — but from page 6, and the golden cites page 99.
        A right number beside a wrong page is exactly what this project
        exists not to emit."""
        (res,) = verify_ask_queries([_ask(pages=[99])], part)
        assert not res.ok
        assert res.n_records and res.n_verified == 0
        assert "on a cited page" in res.detail

    def test_a_substring_the_cited_rows_lack_fails(self, part):
        (res,) = verify_ask_queries(
            [_ask(expected_substrings=["Operating junction temperature", "999"])], part
        )
        assert not res.ok

    def test_a_moved_route_fails_even_when_the_text_still_matches(self, part):
        """A question a record used to answer and a paragraph now answers has
        regressed, whatever the text says."""
        (res,) = verify_ask_queries([_ask(ask_query={"route": "search"})], part)
        assert not res.ok
        assert res.detail == "routed spec, expected search"

    def test_an_unrouted_golden_accepts_whichever_route_answers(self, part):
        (res,) = verify_ask_queries([_ask(ask_query={})], part)
        assert res.ok

    def test_a_budget_below_the_citation_floor_fails_the_question(self, part):
        """`over_budget` is the pack's own honest report that a budget sat
        below its citation floor. Budget compliance is part of the pass rule,
        not a separate check — an answer that only fits by going over is not
        the product this phase claims."""
        (res,) = verify_ask_queries([_ask()], part, budget=20)
        assert not res.ok
        assert res.detail.startswith("over budget:")
        assert res.tokens > res.budget == 20

    def test_the_report_names_every_question_and_counts_only_passes(self, part):
        results = verify_ask_queries([_ask(), _ask("a2", pages=[99])], part)
        text = render_ask_query_report(results)
        assert "**1/2 passed**" in text
        assert "Ask-path verification" in text
        assert text.count("✅") == 1 and text.count("❌") == 1


class TestSearchPathRule:
    def test_top_1_is_the_section_holding_the_answer(self, part):
        (res,) = verify_search_queries([_search()], part)
        assert res.ok
        assert res.n_verified == 1
        assert "§4.5, p.7-8" in res.detail

    def test_questions_without_the_marker_are_not_search_questions(self, part):
        plain = GoldenQuestion(
            id="q1",
            question="Where is SYSREF?",
            expected_substrings=["SYSREF"],
            pages=[7],
        )
        assert verify_search_queries([plain], part) == []

    def test_the_query_defaults_to_the_question_itself(self, part):
        (res,) = verify_search_queries([_search(search_query={})], part)
        assert res.ok

    def test_a_hit_that_does_not_cover_the_cited_page_fails(self, part):
        (res,) = verify_search_queries([_search(pages=[6])], part)
        assert not res.ok
        assert "not the cited section" in res.detail

    def test_a_section_that_does_not_hold_the_answer_fails(self, part):
        (res,) = verify_search_queries(
            [_search(expected_substrings=["a phrase this corpus never prints"])], part
        )
        assert not res.ok

    def test_rank_widens_the_window_it_never_removes_it(self, part):
        """`dac resolution junction temperature` ranks §4.3 first and §4.5
        second. A page-7 question fails at the default top-1 and passes with
        an explicit `rank: 2` — the widening is recorded in the golden, so a
        corpus that quietly slid from rank 1 to rank 2 still fails."""
        query = {"query": "dac resolution junction temperature"}
        (strict,) = verify_search_queries(
            [_search(expected_substrings=["14 bits"], search_query=query)], part
        )
        assert not strict.ok
        (widened,) = verify_search_queries(
            [
                _search(
                    expected_substrings=["14 bits"],
                    search_query={**query, "rank": "2"},
                )
            ],
            part,
        )
        assert widened.ok

    def test_a_corpus_without_an_index_says_rebuild_not_no_match(self, part):
        """The distinction the answer pack draws between `none` and
        `unavailable`, applied to the benchmark: a path that never ran
        establishes nothing, so it must fail loudly rather than pass."""
        (part / "docs" / DOC / "search_index.json").unlink()
        from datasheet_analyzer.retrieve import clear_index_cache

        clear_index_cache()
        (res,) = verify_search_queries([_search()], part)
        assert not res.ok
        assert "search unavailable" in res.detail
        assert "Rebuild" in res.detail

    def test_the_report_names_every_question_and_counts_only_passes(self, part):
        results = verify_search_queries([_search(), _search("k2", pages=[6])], part)
        text = render_search_query_report(results)
        assert "**1/2 passed**" in text
        assert "Search-path verification" in text


class TestShippedBenchmarks:
    """The benchmarks themselves, as data. Ticket 09 requires the two new
    paths on *every* built part; a set that ships without them would leave
    the phase's claim unproven for that datasheet."""

    @pytest.mark.parametrize("name", BUILT_PARTS)
    def test_every_built_part_carries_both_new_paths(self, name):
        questions = load_golden(FIXTURES / f"golden_qa_{name}.yaml")
        assert [q.id for q in questions if q.ask_query is not None], (
            f"{name}: no ask-path question — the designer's-words claim is unproven for this part"
        )
        assert [q.id for q in questions if q.search_query is not None], (
            f"{name}: no search-path question"
        )

    @pytest.mark.parametrize("name", BUILT_PARTS)
    def test_every_path_question_carries_the_ground_truth_it_is_judged_by(self, name):
        for q in load_golden(FIXTURES / f"golden_qa_{name}.yaml"):
            if q.ask_query is None and q.search_query is None:
                continue
            assert q.pages, f"{name}/{q.id}: a path question needs a cited page"
            assert q.expected_substrings, f"{name}/{q.id}: nothing to verify"
            if q.ask_query is not None:
                assert set(q.ask_query) <= {"route"}, f"{name}/{q.id}"
            if q.search_query is not None:
                assert set(q.search_query) <= {"query", "rank"}, f"{name}/{q.id}"

    @pytest.mark.parametrize("name", BUILT_PARTS)
    def test_the_yaml_on_disk_is_what_the_loader_sees(self, name):
        """The markers are additive fields on a model that already existed;
        a typo (`ask-query`, `searchquery`) would silently drop the question
        from both new tables instead of failing, so the raw keys are checked
        against the model's own field names."""
        raw = yaml.safe_load((FIXTURES / f"golden_qa_{name}.yaml").read_text(encoding="utf-8"))
        allowed = set(GoldenQuestion.model_fields)
        for item in raw["questions"]:
            unknown = set(item) - allowed
            assert not unknown, f"{name}/{item.get('id')}: unknown key(s) {unknown}"
