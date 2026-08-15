"""BM25 ranking over the precomputed search indexes, plus snippet recovery.

The index is built at publish (`publish/search_index.py`); this module is the
query half. It never touches the filesystem — it scores the loaded
`SearchIndex` objects a `CorpusIndex` already holds — except through the
caller-supplied section text used to cut a snippet.

**Ranking** is textbook BM25 with the plan's constants (k1=1.2, b=0.75) and
the `log(1 + (N - df + 0.5) / (df + 0.5))` IDF, which is non-negative for
every df and so never lets a common term subtract from a score. Corpus
statistics are computed across *all* of a part's documents, so a datasheet and
its register map compete on one scale.

**Ties are broken deterministically** by (document directory, section file) —
both stable across machines and runs, unlike the dict/filesystem order they
would otherwise inherit. Two identical corpora must rank identically or a
golden search question is not a benchmark.

**Snippets** are recovered by re-reading the section file rather than by
storing positions in the index: cheaper on disk, and it guarantees the quoted
text is what the corpus actually contains today. The window is ±240 chars
around the best-scoring term's occurrence, grown outward to the nearest
sentence boundary within a bounded slack, with `…` marking either edge that
had to be cut mid-sentence.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from datasheet_analyzer.models import SearchIndex
from datasheet_analyzer.structure.search import body_text, fold, tokenize

K1 = 1.2
B = 0.75

# ±240 chars, per the phase plan; SLACK is how far the window may grow to
# reach a sentence boundary before it gives up and prints an ellipsis.
SNIPPET_RADIUS = 240
SNIPPET_SLACK = 120

_SENTENCE_END = re.compile(r"[.!?:](?=\s)")
_WHITESPACE = re.compile(r"\s+")
# A section file opens with its own `# <number> <title>` heading. It is worth
# indexing (title words are strong evidence) but not worth quoting: the hit
# already carries the heading as a field.
_LEADING_HEADING = re.compile(r"\A\s*#[^\n]*\n")


@dataclass(frozen=True)
class ScoredSection:
    """One section's BM25 score, before it is joined to its manifest entry.

    `doc` is the corpus document directory name and `file` the
    document-relative section path — together the corpus-relative
    `docs/<doc>/<file>` that the manifest also keys on. `terms` lists the
    query terms that actually contributed, strongest first, which is what the
    snippet centres on.
    """

    doc: str
    file: str
    score: float
    terms: tuple[str, ...]

    @property
    def section_file(self) -> str:
        """Corpus-relative path, as `SectionFile.file` spells it."""
        return f"docs/{self.doc}/{self.file}"


def score_sections(
    indexes: list[tuple[str, SearchIndex]], query: str, *, limit: int = 10
) -> list[ScoredSection]:
    """Rank every indexed section of a part against `query`.

    `indexes` is `(document directory name, its index)`; sections that score
    nothing are dropped rather than returned with a zero, because a search
    result a caller must filter is worse than no result.
    """
    terms = list(dict.fromkeys(tokenize(query)))
    if not terms:
        return []

    n_sections = sum(len(idx.sections) for _doc, idx in indexes)
    if n_sections == 0:
        return []
    # `avgdl` is recomputed rather than read off an index: each file records
    # its *own* document's mean, and a part with a datasheet plus a register
    # map must score on one scale. `df` is simply additive — a part's document
    # section sets are disjoint — so the stored maps sum correctly.
    total_len = sum(sec.length for _doc, idx in indexes for sec in idx.sections)
    avgdl = total_len / n_sections if n_sections else 0.0
    df = {t: sum(idx.df.get(t, 0) for _doc, idx in indexes) for t in terms}
    idf = {t: _idf(n_sections, df[t]) for t in terms if df[t] > 0}
    if not idf:
        return []

    scored: list[ScoredSection] = []
    for doc, index in indexes:
        for sec in index.sections:
            contributions: list[tuple[float, str]] = []
            for term, weight in idf.items():
                tf = sec.tokens.get(term, 0)
                if not tf:
                    continue
                norm = tf + K1 * (1 - B + B * (sec.length / avgdl if avgdl else 0.0))
                contributions.append((weight * tf * (K1 + 1) / norm, term))
            if not contributions:
                continue
            contributions.sort(key=lambda c: (-c[0], c[1]))
            scored.append(
                ScoredSection(
                    doc=doc,
                    file=sec.file,
                    score=sum(c[0] for c in contributions),
                    terms=tuple(term for _score, term in contributions),
                )
            )
    # Deterministic ordering: score first, then the corpus path — never dict
    # or filesystem order, so two identical corpora rank identically.
    scored.sort(key=lambda s: (-s.score, s.doc, s.file))
    return scored[:limit] if limit > 0 else scored


def _idf(n_sections: int, df: int) -> float:
    """Non-negative BM25 IDF: a common term contributes little, never less."""
    return math.log(1 + (n_sections - df + 0.5) / (df + 0.5))


def snippet(text: str, terms: tuple[str, ...]) -> str:
    """A ±240-char excerpt of `text` around the best-scoring term.

    `terms` is ordered by contribution, so the first one actually present in
    the body is the one worth showing. A term that only matched as a
    sub-token of a compound (`hz` inside `dBc/Hz`) still locates its
    compound, because the search is a plain substring of the folded body.
    Nothing found at all falls back to the head of the section — honest, and
    still cited.

    The section's own `# <number> <title>` heading is dropped: it is already
    on the hit as a field, and quoting it back would spend snippet budget on
    something the caller printed a line earlier.
    """
    body = _WHITESPACE.sub(" ", _LEADING_HEADING.sub("", body_text(text))).strip()
    if not body:
        return ""
    folded = fold(body)
    center = -1
    for term in terms:
        found = folded.find(term)
        if found >= 0:
            center = found + len(term) // 2
            break
    center = max(center, 0)

    start, clean_start = _expand_left(body, max(0, center - SNIPPET_RADIUS))
    end, clean_end = _expand_right(body, min(len(body), center + SNIPPET_RADIUS))
    excerpt = body[start:end].strip()
    # `…` marks a cut, and only a cut: an edge that landed on a real sentence
    # boundary reads as a quotation, not as an elision.
    if start > 0 and not clean_start:
        excerpt = f"…{excerpt}"
    if end < len(body) and not clean_end:
        excerpt = f"{excerpt}…"
    return excerpt


def _expand_left(body: str, start: int) -> tuple[int, bool]:
    """Move `start` back to just after the previous sentence end, if near.

    Returns the index and whether a boundary was actually reached.
    """
    if start <= 0:
        return 0, True
    window_start = max(0, start - SNIPPET_SLACK)
    matches = list(_SENTENCE_END.finditer(body, window_start, start))
    if not matches:
        return start, False
    return matches[-1].end(), True


def _expand_right(body: str, end: int) -> tuple[int, bool]:
    """Move `end` forward to the next sentence end, if one is near."""
    if end >= len(body):
        return len(body), True
    match = _SENTENCE_END.search(body, end, min(len(body), end + SNIPPET_SLACK))
    return (match.end(), True) if match else (end, False)
