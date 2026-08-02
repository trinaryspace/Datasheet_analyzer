"""Boilerplate stripping.

Pain point addressed: every printed page of a TI datasheet repeats header/
footer junk ("Product Folder Links: AFE7950", "Submit Document Feedback",
copyright lines, doc-id lines). Over 146 pages this is thousands of tokens
an agent would otherwise pay for on every read — pure noise for Q&A.

Rules are an explicit, ordered regex list so behavior is reviewable and
testable. `strip_boilerplate` reports what it removed so the pipeline can
report token savings.
"""

from __future__ import annotations

import re

BOILERPLATE_RULES: list[re.Pattern[str]] = [
    re.compile(r"^Product Folder Links?:.*$"),
    re.compile(r"^Submit Document Feedback.*$"),
    re.compile(r"^Copyright\s*©.*$", re.IGNORECASE),
    re.compile(r"^www\.ti\.com\s*$"),
    # doc-id line, e.g. "SBASA41E – FEBRUARY 2021 – REVISED MAY 2025"
    re.compile(r"^[A-Z][A-Z0-9]*\s+[–-]\s+[A-Z]+ \d{4}\s+[–-]\s+REVISED.*$"),
    re.compile(r"^PRODUCTION DATA\.?$"),
    # NOTE: no "bare page number" rule. A digits-only line is just as often a
    # real table value ("1" ms, "27" dB) as page furniture; stripping it
    # silently corrupts parametric data (caught by test_boilerplate). Page
    # numbers only get stripped where the page context is known (PDF-text
    # extraction), never by blind regex.
]


def is_boilerplate(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return any(rule.search(s) for rule in BOILERPLATE_RULES)


def strip_boilerplate(text: str) -> tuple[str, int]:
    """Remove boilerplate lines. Returns (clean_text, n_lines_removed)."""
    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        if is_boilerplate(line):
            removed += 1
        else:
            kept.append(line)
    # collapse the blank runs left behind
    clean = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return clean, removed


def strip_boilerplate_lines(lines: list[str]) -> tuple[list[str], int]:
    """List variant used by the corpus builder on paragraph blocks."""
    kept: list[str] = []
    removed = 0
    for line in lines:
        if is_boilerplate(line):
            removed += 1
        else:
            kept.append(line)
    return kept, removed
