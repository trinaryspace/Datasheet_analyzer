"""Alias lexicon — a designer's words, a datasheet's symbols.

**Data, not code.** Every synonym lives in `registry/aliases.yaml`; adding one
is a YAML edit, exactly like adding a vendor brand mark. This module only
loads that file and answers three questions about a query term:

- is there an entry for this canonical symbol (`by_symbol`)?
- does the term *contain* one of an entry's alias phrases (`phrase_hits`)?
- is the term a prefix family key (`prefix_hits`)?

The resolution ladder itself lives in `retrieve.retriever`, which is the only
place that knows about records. This module knows about words.

Two rules the data carries:

- `expect_unit` is a **disambiguator, not a filter**. It ranks candidates that
  tie at the same rung — a record whose canonical unit matches sorts first —
  and it never removes a record whose unit is missing or different. A datasheet
  that prints no unit is still an answer; hiding it would be tidier and less
  honest.
- `prefix_match` declares a family: `IDD` also covers `IVDD1P8`, `IVDD1P2`, …
  via its `prefixes` list (defaults to the canonical symbol itself), so one
  entry serves every rail a part happens to name.

Seeded from the symbols present across the six built corpora; regenerate the
coverage measurement with `scripts/seed_aliases.py` (see its docstring for the
exact procedure).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import cache
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

LEXICON_PATH = Path(__file__).resolve().parent.parent / "registry" / "aliases.yaml"

# The fuzzy rung is the last thing standing between a query and an honest
# "no match", so it is deliberately hard to reach: a single-token query can
# only ever match by substring (rung 4) or not at all, and a multi-token one
# must share most of its meaningful tokens with the record's name.
FUZZY_MIN_TOKENS = 2
FUZZY_THRESHOLD = 0.6

_NON_WORD = re.compile(r"[^\w]+")

# Question scaffolding only — never a unit, a symbol or a quantity.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
        "for", "from", "how", "in", "is", "it", "its", "many", "much", "of",
        "on", "or", "per", "that", "the", "this", "to", "what", "when",
        "which", "with",
    }
)


def normalize(text: str) -> str:
    """Lowercase, punctuation-to-space, collapsed — the phrase-match form.

    `Common-mode` and `common mode` must be the same word to a designer, and
    `RθJA` must not lose its theta, so the split is on non-word characters
    rather than on an ASCII allowlist.
    """
    return _NON_WORD.sub(" ", text.lower()).strip()


def padded(text: str) -> str:
    """Normalized and space-fenced, so `in` tests respect word boundaries."""
    return f" {normalize(text)} "


@cache
def _padded_alias(phrase: str) -> str:
    """`padded()` memoized over the lexicon's own fixed phrase vocabulary.

    Only alias phrases go through it — they are a few hundred fixed strings,
    while record text is unbounded and must not be cached. `entry_for` runs
    once per spec record at build time, so the same ~500 phrases would
    otherwise be re-normalized hundreds of thousands of times per part.
    """
    return padded(phrase)


def tokens(text: str) -> list[str]:
    """Meaningful normalized tokens, question scaffolding removed."""
    return [t for t in normalize(text).split() if t not in _STOPWORDS]


def token_overlap(query: str, candidate: str) -> float:
    """Share of the query's tokens that the candidate also uses (0.0–1.0)."""
    q = set(tokens(query))
    if not q:
        return 0.0
    return len(q & set(tokens(candidate))) / len(q)


def similarity(query: str, candidate: str) -> float:
    """Nearest-candidate score: token overlap, or character similarity.

    Deterministic (stdlib `difflib`, no model, no randomness) — suggestions
    must be the same on every machine or they are not reproducible advice.
    """
    return max(
        token_overlap(query, candidate),
        SequenceMatcher(None, normalize(query), normalize(candidate)).ratio(),
    )


@dataclass(frozen=True)
class AliasEntry:
    """One canonical symbol family and the phrases people type for it."""

    symbol: str
    names: tuple[str, ...] = ()
    expect_unit: str = ""
    kind: str = ""
    prefix_match: bool = False
    prefixes: tuple[str, ...] = ()

    @property
    def match_prefixes(self) -> tuple[str, ...]:
        """Symbol prefixes this family claims; empty unless `prefix_match`."""
        if not self.prefix_match:
            return ()
        return self.prefixes or (self.symbol,)

    def phrase_in(self, query: str) -> str:
        """The longest alias phrase contained in `query`, or `""`.

        Longest wins so `maximum junction temperature` beats `junction
        temperature` when an entry declares both — the more specific phrase is
        the one the caller actually typed.
        """
        haystack = padded(query)
        hits = [n for n in self.names if padded(n) in haystack]
        return max(hits, key=len) if hits else ""

    def describes(self, text: str) -> bool:
        """True when `text` (a record's symbol or name) uses one of the names.

        Non-TI datasheets have no symbol column, so the layout floor records
        `Junction temperature` *as* the symbol where TI records `TJ`. One entry
        has to reach both, or the lexicon would only ever work for TI.
        """
        haystack = padded(text)
        return any(padded(n) in haystack for n in self.names)


@dataclass(frozen=True)
class AliasLexicon:
    """The loaded `aliases.yaml`, in ladder order."""

    entries: tuple[AliasEntry, ...] = ()

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(e.symbol for e in self.entries)

    def by_symbol(self, symbol: str) -> AliasEntry | None:
        """Entry whose canonical symbol is `symbol` (case-insensitive)."""
        key = symbol.strip().lower()
        for entry in self.entries:
            if entry.symbol.lower() == key:
                return entry
        return None

    def entry_for(self, symbol: str, name: str = "") -> AliasEntry | None:
        """The entry that claims a *record*, or None — the coverage rule.

        A record is claimed when the lexicon knows its symbol as a canonical
        symbol, as a member of a prefix family, or by one of its alias phrases
        appearing in the record's own symbol or name text (the layout floor
        prints `Junction temperature` where TI prints `TJ`).

        This is the one place that rule lives: `scripts/seed_aliases.py`
        measures coverage with it and `structure/confidence.py` asks it whether
        a unit was expected, so the measured coverage and the grade can never
        disagree about what the lexicon covers.
        """
        entry = self.by_symbol(symbol)
        if entry is not None:
            return entry
        low = symbol.strip().lower()
        haystacks = [padded(text) for text in (symbol, name) if text]
        for candidate in self.entries:
            if low and any(low.startswith(p.lower()) for p in candidate.match_prefixes):
                return candidate
            for alias in candidate.names:
                phrase = _padded_alias(alias)
                if any(phrase in haystack for haystack in haystacks):
                    return candidate
        return None

    def phrase_hits(self, query: str) -> list[tuple[AliasEntry, str]]:
        """`(entry, phrase)` for every entry whose alias phrase is in `query`.

        Ordered by phrase length, longest first: a query that hits two entries
        is a tie the caller breaks with `expect_unit`, but a longer phrase is
        simply more of the query and leads.
        """
        hits = [(e, e.phrase_in(query)) for e in self.entries]
        hits = [(e, p) for e, p in hits if p]
        return sorted(hits, key=lambda ep: (-len(ep[1]), ep[0].symbol))

    def prefix_hits(self, query: str) -> list[tuple[AliasEntry, str]]:
        """`(entry, prefix)` for families the whole query names.

        The query must *be* the family key (`IDD`, or a declared prefix like
        `IVDD`) — a prefix family is a deliberate widening, never something a
        longer phrase falls into by accident.
        """
        key = normalize(query)
        hits: list[tuple[AliasEntry, str]] = []
        for entry in self.entries:
            for prefix in entry.match_prefixes:
                if normalize(prefix) == key:
                    hits.append((entry, prefix))
                    break
        return hits

    def nearest_names(self, query: str, limit: int = 5) -> list[str]:
        """`SYMBOL (phrase)` labels closest to `query` — no-match advice."""
        scored: list[tuple[float, str]] = []
        for entry in self.entries:
            for name in entry.names:
                score = similarity(query, name)
                if score > 0.0:
                    scored.append((score, f"{entry.symbol} ({name})"))
        scored.sort(key=lambda s: (-s[0], s[1]))
        seen: list[str] = []
        for _score, label in scored:
            if label not in seen:
                seen.append(label)
            if len(seen) >= limit:
                break
        return seen

    @classmethod
    def from_mapping(cls, data: dict | None) -> AliasLexicon:
        """Build from parsed YAML: `{SYMBOL: {names, expect_unit, …}}`.

        A malformed entry is warned about and skipped — one bad synonym must
        not take the whole lexicon (and with it every alias query) down.
        """
        entries: list[AliasEntry] = []
        for symbol, body in (data or {}).items():
            if not isinstance(body, dict):
                log.warning("skipping malformed alias entry %r: not a mapping", symbol)
                continue
            names = body.get("names") or []
            if isinstance(names, str):
                names = [names]
            prefixes = body.get("prefixes") or []
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            entries.append(
                AliasEntry(
                    symbol=str(symbol),
                    names=tuple(str(n) for n in names),
                    expect_unit=str(body.get("expect_unit") or ""),
                    kind=str(body.get("kind") or ""),
                    prefix_match=bool(body.get("prefix_match")),
                    prefixes=tuple(str(p) for p in prefixes),
                )
            )
        return cls(entries=tuple(entries))

    @classmethod
    def read(cls, path: Path | None = None) -> AliasLexicon:
        """Parse a lexicon file; an unreadable one degrades to an empty one."""
        path = Path(path) if path else LEXICON_PATH
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            log.warning("alias lexicon unavailable (%s: %s) — symbol lookups only", path, exc)
            return cls()
        return cls.from_mapping(data)


@cache
def load_lexicon(path: Path | None = None) -> AliasLexicon:
    """The shipped lexicon, parsed once per process (or one at `path`)."""
    return AliasLexicon.read(path)


def clear_lexicon_cache() -> None:
    """Test hook: re-read the lexicon file on the next `load_lexicon`."""
    load_lexicon.cache_clear()
