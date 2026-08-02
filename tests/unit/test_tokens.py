"""Token counter sanity — every reported number in this project flows
through tokens.count_tokens, so its behavior must be pinned."""

from __future__ import annotations

from datasheet_analyzer.tokens import CHARS_PER_TOKEN, count_tokens, truncate_to_tokens


def test_empty_is_zero():
    assert count_tokens("") == 0


def test_chars_per_token_ceiling():
    assert count_tokens("a" * CHARS_PER_TOKEN) == 1
    assert count_tokens("a" * (CHARS_PER_TOKEN + 1)) == 2
    assert count_tokens("a" * (CHARS_PER_TOKEN * 100)) == 100


def test_known_prose_estimate_in_expected_band():
    # Claude averages ~4 chars/token on English prose; ensure our estimate
    # stays within ±25% of a realistic word-count-based expectation.
    text = "The quick brown fox jumps over the lazy dog. " * 50  # 2250 chars
    tokens = count_tokens(text)
    assert 400 < tokens < 750


def test_truncate_respects_budget_and_word_boundaries():
    text = "word " * 1000
    out = truncate_to_tokens(text, budget=10)
    assert count_tokens(out) <= 11  # budget + ellipsis slack
    assert out.endswith("…")
    assert "wor" not in out[-4:]  # no mid-word cut


def test_truncate_noop_when_within_budget():
    text = "short text"
    assert truncate_to_tokens(text, budget=100) == text
