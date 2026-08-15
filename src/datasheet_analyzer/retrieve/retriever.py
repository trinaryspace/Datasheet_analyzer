"""`Retriever` — every corpus lookup, returning typed hits.

One instance wraps one `CorpusIndex`, so a session that asks a part twenty
questions parses its JSON once. Each hit says *how* it matched
(`matched_via`) and carries a `Citation` instead of leaving the caller to
build one.

Spec lookups run the **alias ladder** (ticket 02), first non-empty rung wins:

| # | Rung | `matched_via` |
|---|---|---|
| 1 | exact symbol (plus its materialized child rows) | `symbol` |
| 2 | alias phrase from `registry/aliases.yaml` | `alias:<phrase>` |
| 3 | alias prefix family (`IDD` → `IVDD1P8`, …) | `alias-prefix:<prefix>` |
| 4 | symbol / name substring (the pre-ticket-02 behaviour) | `symbol-substring`, `name-substring` |
| 5 | token-overlap fuzzy over the record name | `fuzzy` |

`expect_unit` never removes a candidate — it only sorts the ones a rung
already returned, so a record whose unit is missing still answers. Nothing
matches at all → an empty list plus `suggest_specs()` for the nearest
candidates, never a rung-6 guess.

`search()` (ticket 03) is the second retrieval path: BM25 over the
`search_index.json` built at publish, returning section hits cited from the
manifest. A corpus built before the index existed does not crash and does not
silently answer nothing — `search_unavailable()` says to rebuild.

`ask()` (ticket 05) composes all of it: one question in, one cited,
budget-bounded `AnswerPack` out. The routing and the budget arithmetic live in
`retrieve/pack.py`; this class stays the place lookups happen.

Every spec and plot hit also carries the record's own `confidence` (ticket 04),
read off the record — never recomputed here, and never used to drop, hide or
reorder a hit. Grading is metadata; retrieval order stays the ladder's.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from datasheet_analyzer.config import SEARCH_SCHEMA_VERSION
from datasheet_analyzer.models import PlotRecord, SearchIndex, SectionFile, SpecRecord
from datasheet_analyzer.retrieve.index import CorpusIndex, IndexedDoc
from datasheet_analyzer.retrieve.results import (
    Citation,
    PlotHit,
    SearchHit,
    SectionHit,
    SpecHit,
    record_confidence,
)
from datasheet_analyzer.retrieve.search import ScoredSection, score_sections, snippet
from datasheet_analyzer.structure.aliases import (
    FUZZY_MIN_TOKENS,
    FUZZY_THRESHOLD,
    AliasEntry,
    AliasLexicon,
    load_lexicon,
    padded,
    similarity,
    token_overlap,
    tokens,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from datasheet_analyzer.retrieve.pack import AnswerPack

# The words a designer uses to say "I want a picture". `retrieve.pack` routes
# on this constant and `plots_for_terms` ranks with it, so the router and the
# ranker cannot disagree about what plot vocabulary is. `diagram` is the
# plan's list plus one measured addition: "where is the functional block
# diagram?" is a figure question by any reading, and QPA1003P's golden asks it
# in exactly those words.
PLOT_VOCABULARY = re.compile(
    r"\b(plots?|curves?|vs\.?|versus|graphs?|figures?|diagrams?)\b", re.IGNORECASE
)
# The subset that is *dead weight when ranking*: every caption in a plot
# gallery says "vs." and every AFE7950 caption starts "Figure N", so scoring
# on them ranks nothing and would let every figure match. `diagram` is
# deliberately not here — it names a figure rather than describing all of them.
_PLOT_WORDS = frozenset(
    {"plot", "plots", "curve", "curves", "vs", "versus", "graph", "graphs",
     "figure", "figures", "show", "shows", "showing"}
)

# One candidate record on its way to becoming a hit: the document it came
# from, the record, the alias entry (if any) that vouched for it — the entry
# is what carries `expect_unit` into the tie-break — and the rung label this
# candidate earned. The label is per candidate, not per rung, because two
# alias entries can tie on one rung and each hit should still name the phrase
# that found it.
_Candidate = tuple[IndexedDoc, SpecRecord, AliasEntry | None, str]


@dataclass(frozen=True)
class Retriever:
    """Lookups over one loaded part corpus."""

    index: CorpusIndex

    @classmethod
    def for_part(cls, part_dir: Path | str) -> Retriever:
        """Retriever over `part_dir`, reusing its cached index when current."""
        return cls(CorpusIndex.load(part_dir))

    @property
    def part_dir(self) -> Path:
        return self.index.part_dir

    @property
    def lexicon(self) -> AliasLexicon:
        return load_lexicon()

    def specs(
        self,
        *,
        symbol: str = "",
        name: str = "",
        section: str = "",
    ) -> list[SpecHit]:
        """Resolve a spec query through the alias ladder (see module docs).

        `symbol` and `name` are both just a designer's term; whichever is given
        drives the ladder. When both are given they still AND, as they always
        did — the unused one stays a filter on every rung.
        """
        pool = [
            (doc, rec)
            for doc in self.index.docs
            for rec in doc.specs
            if _passes(rec, section=section, also_name=name if (symbol and name) else "")
        ]
        term = (symbol or name).strip()
        if not term:
            label = "section" if section else "all"
            return _build_hits([(d, r, None, label) for d, r in pool])

        for candidates in self._spec_ladder(term, from_symbol=bool(symbol), pool=pool):
            if candidates:
                return _build_hits(candidates)
        return []

    def suggest_specs(self, term: str, limit: int = 5) -> list[str]:
        """Nearest candidate terms for a query that matched nothing.

        Drawn from the part's own symbols and names first — advice a caller can
        act on in this corpus — then topped up from the alias lexicon. An
        honest "no match, did you mean…" beats a fuzzy guess presented as an
        answer.
        """
        if not term.strip():
            return []
        pool: dict[str, str] = {}
        for doc in self.index.docs:
            for rec in doc.specs:
                for text in (rec.symbol, rec.name):
                    if text:
                        pool.setdefault(text.lower(), text)
        scored = [(similarity(term, label), label) for label in pool.values()]
        scored = [s for s in scored if s[0] > 0.0]
        scored.sort(key=lambda s: (-s[0], s[1]))
        out = [label for _score, label in scored[:limit]]
        for label in self.lexicon.nearest_names(term, limit):
            if len(out) >= limit:
                break
            if label not in out:
                out.append(label)
        return out[:limit]

    def _spec_ladder(
        self, term: str, *, from_symbol: bool, pool: list[tuple[IndexedDoc, SpecRecord]]
    ) -> Iterator[list[_Candidate]]:
        """Yield one candidate list per rung, strongest rung first."""
        lex = self.lexicon
        own = lex.by_symbol(term)

        # 1 — exact symbol, plus its materialized children. A rowspan child
        # (ticket 09) carries its parent's symbol with its own label appended,
        # so `Full-Scale Output Current Range` must still reach `… AC
        # Coupling`. The children only come along when the parent row itself
        # matched exactly; without that guard this rung would quietly become a
        # prefix search and shadow the alias rungs below it.
        low = term.lower()
        exact = [(doc, rec) for doc, rec in pool if rec.symbol.lower() == low]
        if exact:
            children = [
                (doc, rec) for doc, rec in pool if rec.symbol.lower().startswith(low + " ")
            ]
            # pool order, not exact-then-children order: the parent row still
            # prints before its children as the table printed them.
            keep = {id(rec) for _doc, rec in exact} | {id(rec) for _doc, rec in children}
            yield [(doc, rec, own, "symbol") for doc, rec in pool if id(rec) in keep]
        else:
            yield []

        # 2 — alias phrase. Candidates are the entry's canonical symbol *and*
        # any record whose own printed identity uses one of its phrases (see
        # `_printed_as`), because the layout floor records `Junction
        # temperature` as the symbol where TI records `TJ`. Entries whose
        # matched phrase is the same length tie on this rung and are offered
        # together, for `expect_unit` to separate.
        for group in _by_phrase_length(lex.phrase_hits(term)):
            candidates: list[_Candidate] = []
            claimed: set[tuple[int, int]] = set()
            for entry, phrase in group:
                entry_low = entry.symbol.lower()
                for doc, rec in pool:
                    if not (
                        rec.symbol.lower() == entry_low
                        or _in_family(rec, entry)
                        or entry.describes(_printed_as(rec))
                    ):
                        continue
                    key = (id(doc), id(rec))
                    if key in claimed:
                        continue
                    claimed.add(key)
                    candidates.append((doc, rec, entry, f"alias:{phrase}"))
            yield candidates

        # 3 — alias prefix family. Naming any one prefix (`IDD`) opens the
        # whole family (`IVDD1P8`, `IVDD1P2`, …); every family the term names
        # ties on this rung.
        prefix_hits = lex.prefix_hits(term)
        if prefix_hits:
            candidates = []
            claimed = set()
            for entry, prefix in prefix_hits:
                for doc, rec in pool:
                    if not _in_family(rec, entry):
                        continue
                    key = (id(doc), id(rec))
                    if key in claimed:
                        continue
                    claimed.add(key)
                    candidates.append((doc, rec, entry, f"alias-prefix:{prefix}"))
            yield candidates

        # 4 — substring, exactly as it behaved before the ladder existed.
        if from_symbol:
            yield [
                (doc, rec, own, "symbol-substring")
                for doc, rec in pool
                if low in rec.symbol.lower()
            ]
        else:
            yield [
                (doc, rec, own, "name-substring") for doc, rec in pool if low in rec.name.lower()
            ]

        # 5 — fuzzy, and only then. A single-token term never gets here.
        if len(tokens(term)) >= FUZZY_MIN_TOKENS:
            yield [
                (doc, rec, own, "fuzzy")
                for doc, rec in pool
                if token_overlap(term, rec.name) >= FUZZY_THRESHOLD
            ]

    def plots(
        self,
        *,
        q: str = "",
        caption: str = "",
        conditions: str = "",
        section: str = "",
        tags: list[str] | None = None,
    ) -> list[PlotHit]:
        """AND-match caption/conditions text, exact section number, and tags.

        `q` searches the combined caption + conditions text; `caption` and
        `conditions` restrict those fields independently.
        """
        tags = tags or []
        hits: list[PlotHit] = []
        for doc in self.index.docs:
            for rec in doc.plots:
                haystack = (rec.caption + " " + rec.conditions).lower()
                if q and q.lower() not in haystack:
                    continue
                if caption and caption.lower() not in rec.caption.lower():
                    continue
                if conditions and conditions.lower() not in rec.conditions.lower():
                    continue
                if section and section != rec.section:
                    continue
                if tags and not all(t.lower() in (rec.tags or []) for t in tags):
                    continue
                hits.append(
                    PlotHit(
                        record=rec,
                        citation=Citation.for_plot(rec, doc=doc.name, doc_hash=doc.doc_hash),
                        matched_via=_plot_matched_via(rec, q, caption, conditions, section, tags),
                        confidence=record_confidence(rec),
                    )
                )
        return hits

    def plots_for_terms(self, text: str, *, limit: int = 5) -> list[PlotHit]:
        """Rank the plot catalog by how much of `text`'s vocabulary it uses.

        `plots()` is exact — a caller must already know a caption substring.
        A designer asking "which figure shows TX output fullscale vs
        frequency?" knows no such thing, so the terms are matched
        individually against caption + conditions and the figures using most
        of them lead. Plot vocabulary itself is dropped first: every caption
        in a gallery says "vs.", so scoring on it ranks nothing and would let
        every figure match.

        Deterministic throughout — score, then the record's own id — so the
        same catalog answers the same question identically on any machine.
        """
        terms = [t for t in tokens(text) if t not in _PLOT_WORDS]
        if not terms:
            return []
        scored: list[tuple[int, str, PlotHit]] = []
        for hit in self.plots():
            rec = hit.record
            haystack = padded(f"{rec.caption} {rec.conditions} {' '.join(rec.tags or [])}")
            matched = sum(1 for t in terms if f" {t} " in haystack)
            if matched:
                scored.append((matched, rec.id, hit))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [
            replace(hit, matched_via="caption-terms")
            for _matched, _id, hit in (scored[:limit] if limit > 0 else scored)
        ]

    def ask(self, question: str, *, budget: int = 0) -> AnswerPack:
        """One cited, budget-bounded answer pack (ticket 05; see `pack.py`).

        Imported at call time only: `retrieve.pack` composes this class, so a
        module-level import here would be a cycle.
        """
        from datasheet_analyzer.retrieve.pack import build_pack

        return build_pack(self, question, budget=budget)

    def sections(
        self,
        *,
        number: str = "",
        title: str = "",
        page: int | None = None,
    ) -> list[SectionHit]:
        """Manifest section entries by number, title substring, or covered page.

        `page` is the provenance path an agent needs most: "which section do I
        open to check the printed page this answer cites?".
        """
        hits: list[SectionHit] = []
        for sec in self.index.sections:
            if number and number.lower() not in sec.number.lower():
                continue
            if title and title.lower() not in sec.title.lower():
                continue
            if page is not None and not _covers_page(sec, page):
                continue
            hits.append(
                SectionHit(
                    section=sec,
                    citation=Citation.for_section(sec),
                    matched_via=_section_matched_via(sec, number, title, page),
                )
            )
        return hits

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        """Rank the part's sections against `query` with BM25 (see `search.py`).

        Every hit is cited from the manifest entry of the section it names, so
        the caller never attributes a page. A part with no usable index
        returns `[]`; ask `search_unavailable()` for the reason rather than
        reading an empty list as "nothing matched".
        """
        indexes = self._search_indexes()
        if not indexes:
            return []
        sections_by_file = {sec.file: sec for sec in self.index.sections}
        hits: list[SearchHit] = []
        for scored in score_sections(indexes, query, limit=limit):
            section = sections_by_file.get(scored.section_file) or _orphan_section(
                scored, self.index
            )
            hits.append(
                SearchHit(
                    section=section,
                    citation=Citation.for_section(section),
                    score=scored.score,
                    snippet=snippet(self.index.section_text(section), scored.terms),
                    terms=scored.terms,
                )
            )
        return hits

    def search_unavailable(self) -> str:
        """`""` when the part is searchable, else why it is not.

        An older corpus predates `search_index.json` entirely, and one built
        against a superseded schema cannot be scored honestly either. Both say
        so, naming the fix, instead of returning zero hits that read like "the
        datasheet does not mention that".
        """
        if self._search_indexes():
            return ""
        part = self.index.part_number or self.index.part_dir.name
        return (
            f"no full-text index for part {part} — this corpus predates search "
            f"(or was built against an older index schema). Rebuild to enable "
            f"search: dsa build <pdf> --part {part}"
        )

    def _search_indexes(self) -> list[tuple[str, SearchIndex]]:
        """`(doc dir name, index)` for every document with a current index."""
        return [
            (doc.name, doc.search)
            for doc in self.index.docs
            if doc.search is not None
            and doc.search.schema_version == SEARCH_SCHEMA_VERSION
        ]

    def section_text(self, section: SectionFile) -> str:
        """Markdown body of a section file (lazily read, then cached)."""
        return self.index.section_text(section)


def _orphan_section(scored: ScoredSection, index: CorpusIndex) -> SectionFile:
    """A stand-in entry for an indexed section the manifest does not list.

    Only reachable when `manifest.json` is unreadable or out of step with the
    documents on disk. The hit still points at a real file and still cites —
    honestly as `p.?`, because no page range survives to quote.
    """
    doc = next((d for d in index.docs if d.name == scored.doc), None)
    return SectionFile(
        number="",
        title=Path(scored.file).stem,
        file=scored.section_file,
        doc_hash=doc.doc_hash if doc else "",
    )


def _passes(rec: SpecRecord, *, section: str, also_name: str) -> bool:
    """Filters that apply on every rung, not just the one that matched."""
    if section and section.lower() not in rec.section.lower():
        return False
    return not (also_name and also_name.lower() not in rec.name.lower())


def _printed_as(rec: SpecRecord) -> str:
    """The record's identity as the table printed it — symbol *then* name.

    An alias phrase is a designer's phrase, and a datasheet does not promise
    to keep one inside a single cell: LM741 prints `Supply` in the symbol
    column and `voltage` in the parameter column, so `supply voltage` exists
    only across the boundary. Matching each cell alone would make that record
    unreachable by the words that describe it, which is why the ladder asks
    the joined text — the same join `pack._head` renders back to the caller.

    `AliasLexicon.entry_for` deliberately keeps its per-cell test: it answers
    a different question ("does the lexicon know this record at all?"), and it
    is what `structure/confidence.py` grades by — a grade already frozen into
    every published corpus. Retrieval may widen; the rule a corpus was graded
    under may not, not without a rebuild. Keeping the widening on this side of
    the seam is what makes it provably grade-neutral.
    """
    return f"{rec.symbol} {rec.name}"


def _in_family(rec: SpecRecord, entry: AliasEntry) -> bool:
    """True when the record's symbol starts with one of the family prefixes."""
    symbol = rec.symbol.lower()
    return any(symbol.startswith(p.lower()) for p in entry.match_prefixes)


def _by_phrase_length(
    hits: list[tuple[AliasEntry, str]],
) -> Iterator[list[tuple[AliasEntry, str]]]:
    """Group `(entry, phrase)` hits into ties — same phrase length, one rung."""
    group: list[tuple[AliasEntry, str]] = []
    for entry, phrase in hits:  # already sorted longest phrase first
        if group and len(phrase) != len(group[0][1]):
            yield group
            group = []
        group.append((entry, phrase))
    if group:
        yield group


def _build_hits(candidates: list[_Candidate]) -> list[SpecHit]:
    """Order by the `expect_unit` tie-break, then wrap in typed hits.

    The sort is stable and the key is binary, so document order survives and a
    record whose unit is missing keeps its place in the list — `expect_unit`
    promotes, it never suppresses.
    """
    ordered = sorted(candidates, key=lambda c: _unit_rank(c[1], c[2]))
    return [
        SpecHit(
            record=rec,
            citation=Citation.for_spec(rec, doc=doc.name, doc_hash=doc.doc_hash),
            matched_via=matched_via,
            confidence=record_confidence(rec),
        )
        for doc, rec, _entry, matched_via in ordered
    ]


def _unit_rank(rec: SpecRecord, entry: AliasEntry | None) -> int:
    """0 for a record whose canonical unit is the one the alias expected."""
    if entry is None or not entry.expect_unit:
        return 0
    return 0 if rec.unit.canonical == entry.expect_unit else 1


def _covers_page(sec: SectionFile, page: int) -> bool:
    if sec.page_start is None:
        return False
    return sec.page_start <= page <= (sec.page_end or sec.page_start)


def _plot_matched_via(
    rec: PlotRecord,
    q: str,
    caption: str,
    conditions: str,
    section: str,
    tags: list[str],
) -> str:
    if caption or (q and q.lower() in rec.caption.lower()):
        return "caption"
    if conditions or q:
        return "conditions"
    if section:
        return "section"
    if tags:
        return "tag"
    return "all"


def _section_matched_via(sec: SectionFile, number: str, title: str, page: int | None) -> str:
    if number:
        return "number"
    if title:
        return "title"
    if page is not None:
        return "page"
    return "all"
