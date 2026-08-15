"""`Retriever` — every corpus lookup, returning typed hits.

One instance wraps one `CorpusIndex`, so a session that asks a part twenty
questions parses its JSON once. Matching semantics are exactly the ones
`query.py` shipped (case-insensitive substrings, ANDed across fields); what is
new is that each hit says *how* it matched (`matched_via`) and carries a
`Citation` instead of leaving the caller to build one.

Ticket 02 extends `specs()` with the alias ladder, ticket 03 adds the
BM25 `search()` path, ticket 04 fills in `confidence`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import PlotRecord, SectionFile, SpecRecord
from datasheet_analyzer.retrieve.index import CorpusIndex
from datasheet_analyzer.retrieve.results import (
    Citation,
    PlotHit,
    SectionHit,
    SpecHit,
    record_confidence,
)


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

    def specs(
        self,
        *,
        symbol: str = "",
        name: str = "",
        section: str = "",
    ) -> list[SpecHit]:
        """Case-insensitive substring match on symbol/name/section (ANDed)."""
        hits: list[SpecHit] = []
        for doc in self.index.docs:
            for rec in doc.specs:
                if symbol and symbol.lower() not in rec.symbol.lower():
                    continue
                if name and name.lower() not in rec.name.lower():
                    continue
                if section and section.lower() not in rec.section.lower():
                    continue
                hits.append(
                    SpecHit(
                        record=rec,
                        citation=Citation.for_spec(rec, doc=doc.name, doc_hash=doc.doc_hash),
                        matched_via=_spec_matched_via(rec, symbol, name, section),
                        confidence=record_confidence(rec),
                    )
                )
        return hits

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

    def section_text(self, section: SectionFile) -> str:
        """Markdown body of a section file (lazily read, then cached)."""
        return self.index.section_text(section)


def _covers_page(sec: SectionFile, page: int) -> bool:
    if sec.page_start is None:
        return False
    return sec.page_start <= page <= (sec.page_end or sec.page_start)


def _spec_matched_via(rec: SpecRecord, symbol: str, name: str, section: str) -> str:
    """Strongest rung that produced this hit — see `results` for the ladder."""
    if symbol:
        return "symbol" if symbol.lower() == rec.symbol.lower() else "symbol-substring"
    if name:
        return "name-substring"
    if section:
        return "section"
    return "all"


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
