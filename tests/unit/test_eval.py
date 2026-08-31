"""Pain point: eval itself. The verifier must find answers in the right
sections, honor page ranges, tolerate dash/space variants, and measure the
token math that justifies the whole architecture."""

from __future__ import annotations

import json

from datasheet_analyzer.evalh.citations import (
    _sections_covering_page,
    contains,
    verify_questions,
)
from datasheet_analyzer.evalh.golden import estimate_lookup_tokens
from datasheet_analyzer.models import GoldenQuestion


def _write_part(tmp_path):
    part = tmp_path / "TEST"
    (part / "docs" / "datasheet-aaaabbbb" / "sections").mkdir(parents=True)
    (part / "INDEX.md").write_text("# TEST index\n" * 10, encoding="utf-8")
    (part / "docs" / "datasheet-aaaabbbb" / "sections" / "4-5-tx.md").write_text(
        "# 4.5 TX Electrical\n\nDAC resolution 14 bits. DSA Attenuation range 40 dB.\n",
        encoding="utf-8",
    )
    (part / "docs" / "datasheet-aaaabbbb" / "sections" / "4-10-timing.md").write_text(
        "# 4.10 Timing\n\nMinimum SCLK period: registers write 25 ns.\n",
        encoding="utf-8",
    )
    manifest = {
        "part_number": "TEST",
        "sections": [
            {
                "number": "4.5",
                "title": "TX",
                "file": "docs/datasheet-aaaabbbb/sections/4-5-tx.md",
                "page_start": 7,
                "page_end": 13,
                "token_count": 100,
            },
            {
                "number": "4.10",
                "title": "Timing",
                "file": "docs/datasheet-aaaabbbb/sections/4-10-timing.md",
                "page_start": 27,
                "page_end": 27,
                "token_count": 80,
            },
            {
                "number": "5",
                "title": "Unpaged",
                "file": "docs/x.md",
                "page_start": None,
                "page_end": None,
                "token_count": 10,
            },
        ],
    }
    (part / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return part


class TestMatching:
    def test_squash_handles_dash_space_variants(self):
        assert contains("1.75 GHz – 1.9 GHz", "1.75 GHz - 1.9 GHz")
        assert contains("1200MHz or 2TX", "1200 MHz")
        assert contains("±0.1 dB", "±0.1")
        assert not contains("resolution 12 bits", "14 bits")


class TestSectionsCoveringPage:
    def test_finds_covering_sections(self, tmp_path):
        part = _write_part(tmp_path)
        import json as j

        manifest = j.loads((part / "manifest.json").read_text())
        assert [s["number"] for s in _sections_covering_page(manifest, 9)] == ["4.5"]
        assert [s["number"] for s in _sections_covering_page(manifest, 27)] == ["4.10"]
        assert _sections_covering_page(manifest, 99) == []


class TestVerifyQuestions:
    def test_pass_when_corpus_and_page_both_contain_answer(self, tmp_path):
        part = _write_part(tmp_path)
        q = GoldenQuestion(
            id="q1",
            question="DAC resolution?",
            expected_substrings=["14", "bits"],
            pages=[7],
        )
        pages = [""] * 6 + ["DAC resolution 14 bits table"]  # page 7 text
        (res,) = verify_questions([q], part, pages)
        assert res.passed
        assert res.matched_files == ["docs/datasheet-aaaabbbb/sections/4-5-tx.md"]

    def test_fail_when_no_section_covers_page(self, tmp_path):
        part = _write_part(tmp_path)
        q = GoldenQuestion(id="q2", question="?", expected_substrings=["x"], pages=[99])
        (res,) = verify_questions([q], part, ["x"] * 100)
        assert not res.passed
        assert res.matched_files == []

    def test_fail_when_corpus_lacks_answer_even_if_page_has_it(self, tmp_path):
        part = _write_part(tmp_path)
        q = GoldenQuestion(
            id="q3", question="?", expected_substrings=["imaginary-value"], pages=[7]
        )
        pages = [""] * 6 + ["imaginary-value on the real page"]
        (res,) = verify_questions([q], part, pages)
        assert not res.passed
        assert res.page_truth and not res.corpus_contains
        assert res.missing == ["imaginary-value"]


class TestTokenEstimates:
    def test_lookup_vs_dump_math(self, tmp_path):
        from datasheet_analyzer.tokens import count_tokens

        part = _write_part(tmp_path)
        q = GoldenQuestion(id="q1", question="?", expected_substrings=["14"], pages=[7])
        (res,) = verify_questions([q], part, ["14 bits"])
        est = estimate_lookup_tokens(part, [res])

        index_tokens = count_tokens((part / "INDEX.md").read_text())
        section_tokens = count_tokens(
            (part / "docs" / "datasheet-aaaabbbb" / "sections" / "4-5-tx.md").read_text()
        )
        both_sections = section_tokens + count_tokens(
            (part / "docs" / "datasheet-aaaabbbb" / "sections" / "4-10-timing.md").read_text()
        )
        assert est["index_tokens"] == index_tokens
        assert est["per_question"][0] == index_tokens + section_tokens
        assert est["full_dump_tokens"] == both_sections
        assert est["max_per_question"] == est["avg_per_question"] == index_tokens + section_tokens
