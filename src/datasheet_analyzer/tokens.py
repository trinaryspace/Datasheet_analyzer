"""Token estimation.

We deliberately avoid a tokenizer dependency. Claude tokens average ~4
chars/token for English prose; dense technical tables skew slightly heavier
(~3.5). We use chars/4 everywhere and treat the result as an *estimate* good
enough for budgets and before/after comparisons. All token numbers reported
by this project come from this one function so comparisons are consistent.
"""

from __future__ import annotations

CHARS_PER_TOKEN = 4


def count_tokens(text: str) -> int:
    """Estimate token count of `text` (chars/4, rounded up)."""
    if not text:
        return 0
    return -(-len(text) // CHARS_PER_TOKEN)  # ceil division


def truncate_to_tokens(text: str, budget: int, ellipsis: str = " …") -> str:
    """Truncate `text` to roughly `budget` tokens without splitting words.
    A non-positive budget means "drop the text entirely"."""
    if budget <= 0:
        return ""
    if count_tokens(text) <= budget:
        return text
    max_chars = budget * CHARS_PER_TOKEN
    if max_chars <= len(ellipsis):
        return ""
    cut = text[: max_chars - len(ellipsis)]
    # don't split mid-word
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut + ellipsis
