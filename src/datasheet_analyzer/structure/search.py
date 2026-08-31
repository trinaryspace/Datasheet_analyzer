"""Search vocabulary — one tokenizer, index time and query time.

Same philosophy as `structure/aliases.py`: this module knows about *words*.
`publish/search_index.py` uses it to build a document's inverted index and
`retrieve/search.py` uses it to tokenize the query, so the two can never
disagree about what a token is — a drift that would silently make indexed
terms unfindable.

Three rules the tokenizer carries, all of them about not destroying a
datasheet's own vocabulary:

- **No stemming.** `SYSREF` must not become `sysref`+`s`, and `Ratings` must
  stay `ratings`. Technical corpora punish stemmers: the terms a designer
  types are already the terms the page prints.
- **Casefolding is ASCII-only.** Unicode lowercasing maps *both* ohm glyphs
  (U+2126 OHM SIGN, TI, and U+03A9 GREEK CAPITAL OMEGA, ADI) onto the same
  U+03C9, which would merge two glyphs this repo preserves verbatim
  everywhere else. Lowercasing only `A-Z` keeps `Ω` and `Ω` — and `θJA`, `µ`,
  `°C` — exactly as printed.
- **Compound unit strings stay whole *and* split.** `dBc/Hz` indexes as
  `dbc/hz` so the printed string is searchable verbatim, and additionally as
  `dbc` and `hz` so a caller who types one half still lands on it.

One thing is deliberately *not* indexed: a token that carries no letter at
all. See `_indexable` — numerals are the least discriminating tokens a
datasheet contains, they are what makes an index rival the size of the text,
and values already have an exact path through `specs.json` (`dsa query`).

Stopwords are grammatical scaffolding only. Nothing that is (or could be) a
printed unit symbol is in the list — notably `a` (amperes) and `in` (inches)
are deliberately absent, and no single-letter word is ever a stopword. BM25's
IDF already flattens genuinely common terms; a stopword list that eats a unit
would lose an answer, which is the more expensive mistake.
"""

from __future__ import annotations

import re
import string

# `str.lower()` would fold U+2126 and U+03A9 together; this does not.
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)

# Non-alphanumeric characters that may live *inside* a token. `/` keeps
# `dBc/Hz` whole, `.` and `-` keep `1.2` and `4-1`, `_` keeps the glued
# subscripts (`T_A`) the extraction stage deliberately produces, and `°`/`%`/
# `±` keep printed unit strings intact.
_INNER = "_/.+-°%±"
# Punctuation that is sentence noise when it lands on a token's edge.
_EDGE_TRIM = "/.+-"

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ALNUM_RUN = re.compile(r"[^\W_]+", re.UNICODE)

# Grammatical scaffolding only — never a unit, a symbol or a quantity. See
# the module docstring for why `a`, `in` and every single letter are absent.
STOPWORDS = frozenset(
    {
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "if",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "were",
        "which",
        "while",
        "will",
        "with",
    }
)


def fold(text: str) -> str:
    """ASCII-only lowercase — the one casefolding rule for search."""
    return text.translate(_ASCII_LOWER)


def body_text(markdown: str) -> str:
    """A section file's searchable body: HTML comments removed.

    The `<!-- source: <doc> p.N -->` provenance header is metadata, not
    content. It is already carried structurally by the manifest, so indexing
    it would only pollute the vocabulary and let it surface inside snippets.
    """
    return _HTML_COMMENT.sub(" ", markdown)


def _split(text: str) -> list[str]:
    """Raw tokens: maximal runs of alphanumerics plus the inner punctuation."""
    out: list[str] = []
    buf: list[str] = []
    for ch in text:
        if ch.isalnum() or ch in _INNER:
            buf.append(ch)
        elif buf:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out


def _subtokens(token: str) -> list[str]:
    """The halves of a genuinely compound token (`dbc/hz` -> `dbc`, `hz`).

    Only compounds split, and only parts that carry a letter and are at least
    two characters survive: `1.2` must not litter the index with `1` and `2`,
    and `t_a` must not add a bare `t`.
    """
    runs = _ALNUM_RUN.findall(token)
    if len(runs) < 2:
        return []
    return [r for r in runs if len(r) >= 2 and not r.isdigit()]


def _indexable(token: str) -> bool:
    """A token earns a place in the index only if it carries a letter.

    Datasheets are mostly numbers, and a bare `105` or `1.2` is the least
    discriminating thing BM25 could hold: it appears on nearly every page and
    ranks nothing. Values have an exact, cheaper path already — `dsa query`
    reads them out of `specs.json` with their units and their page. So the
    index keeps the words and drops the numerals, which is most of the reason
    it stays a fraction of the text it indexes.

    "Letter" is unicode-wide, so `Ω` (both glyphs), `θ` and `µ` stay: a symbol
    is a word here, not a number.
    """
    return any(ch.isalpha() for ch in token)


def tokenize(text: str) -> list[str]:
    """Search tokens for `text`, in order of appearance.

    Lowercased (ASCII only), stopword-stripped, never stemmed, numerals
    dropped (see `_indexable`). Compound unit strings contribute both the
    whole token and its lettered parts, so `dBc/Hz` is findable as itself, as
    `dbc`, and as `hz`.
    """
    out: list[str] = []
    for raw in _split(fold(text)):
        token = raw.strip(_EDGE_TRIM)
        if not token or not _indexable(token):
            continue
        for candidate in (token, *_subtokens(token)):
            if candidate not in STOPWORDS:
                out.append(candidate)
    return out
