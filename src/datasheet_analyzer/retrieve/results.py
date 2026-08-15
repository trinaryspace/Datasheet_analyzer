"""Typed retrieval results — citation, confidence, and how the hit matched.

A hit is never a formatted string: it is the record plus a `Citation` that
knows how to render itself. Front ends print `citation.label`; they never
assemble `p.N` themselves, so the citation format can never drift between the
CLI, `query.py` and (Phase 5, ticket 07) the MCP server.

`confidence` is the record's own grade, computed at structure time by
`structure/confidence.py` (ticket 04) and read off the record here by
`record_confidence()`. A record from a corpus built before grading existed has
no grade on disk and reads `unknown` — honestly ungraded, never optimistically
`high`. Section and full-text hits carry `unknown` by construction: a grade is
a property of an extracted *record*, and a section file is verbatim text.

`matched_via` names the rung that produced the hit, so a caller can tell an
exact symbol hit from a loose substring one:

| Lookup | Values (strongest first) |
|---|---|
| specs | `symbol`, `alias:<phrase>`, `alias-prefix:<prefix>`, `symbol-substring`, `name-substring`, `fuzzy`, `section`, `all` |
| plots | `caption`, `conditions`, `section`, `tag`, `caption-terms`, `all` |
| sections | `number`, `title`, `page`, `all` |
| search | `fulltext` |

The spec ladder itself lives in `retrieve.retriever`; the alias data behind
its `alias:` rungs lives in `registry/aliases.yaml`.
"""

from __future__ import annotations

from dataclasses import dataclass

from datasheet_analyzer.models import PlotRecord, SectionFile, SpecRecord

# An ungraded record is honestly ungraded rather than optimistically "high".
CONFIDENCE_UNKNOWN = "unknown"


def record_confidence(record: object) -> str:
    """The record's own confidence grade as a plain string, or `unknown`.

    Reads the field defensively so corpora built before ticket 04 — which have
    no grade on disk — degrade to `unknown` instead of failing to load, and
    unwraps the `Confidence` enum so every hit, every `as_dict()` and every
    front end sees the same plain `"high"` / `"medium"` / `"low"` string.
    """
    value = getattr(record, "confidence", "")
    return str(getattr(value, "value", value) or "") or CONFIDENCE_UNKNOWN


@dataclass(frozen=True)
class Citation:
    """Where a hit came from: document, section, printed page or page range.

    `doc` is the corpus document directory name (`datasheet-a1b2c3d4`), which
    is also the on-disk path segment, so a caller can go from a citation to the
    files that produced it without a second lookup.

    `part` is which corpus the hit came from. It is always filled by
    `Retriever` (ticket 06), because once a question can be asked across a
    whole project the part is part of "where this came from" — an answer that
    does not say which datasheet it read is not cited. `label` deliberately
    does not print it: the citation format is what `dsa verify` measures, and
    naming the part is a front end's decision.
    """

    doc: str = ""
    doc_hash: str = ""
    section: str = ""
    page_start: int | None = None
    page_end: int | None = None
    part: str = ""

    @property
    def pages(self) -> str:
        """`p.7`, `p.29-37`, or an honest `p.?` when the page is unpinned."""
        if self.page_start is None:
            return "p.?"
        if self.page_end is not None and self.page_end != self.page_start:
            return f"p.{self.page_start}-{self.page_end}"
        return f"p.{self.page_start}"

    @property
    def label(self) -> str:
        """`§4.5, p.7` — the citation as an agent should quote it."""
        if self.section:
            return f"§{self.section}, {self.pages}"
        return self.pages

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.label

    @classmethod
    def for_spec(
        cls, record: SpecRecord, *, doc: str = "", doc_hash: str = "", part: str = ""
    ) -> Citation:
        return cls(
            doc=doc,
            doc_hash=doc_hash,
            section=record.section,
            page_start=record.page,
            page_end=record.page,
            part=part,
        )

    @classmethod
    def for_plot(
        cls, record: PlotRecord, *, doc: str = "", doc_hash: str = "", part: str = ""
    ) -> Citation:
        return cls(
            doc=doc,
            doc_hash=doc_hash,
            section=record.section,
            page_start=record.page_start,
            page_end=record.page_end,
            part=part,
        )

    @classmethod
    def for_section(cls, section: SectionFile, *, doc: str = "", part: str = "") -> Citation:
        return cls(
            doc=doc or _doc_from_file(section.file),
            doc_hash=section.doc_hash,
            section=section.number,
            page_start=section.page_start,
            page_end=section.page_end,
            part=part,
        )


def _doc_from_file(rel_path: str) -> str:
    """`docs/datasheet-a1b2c3d4/sections/4-5.md` -> `datasheet-a1b2c3d4`."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == "docs":
        return parts[1]
    return ""


@dataclass(frozen=True)
class SpecHit:
    """One parametric spec record with its citation and match provenance."""

    record: SpecRecord
    citation: Citation
    matched_via: str = ""
    confidence: str = CONFIDENCE_UNKNOWN

    def as_dict(self) -> dict:
        """JSON-ready view: values, citation, rung, grade.

        Lives here rather than in a front end so the CLI's `--json` and (ticket
        07) the MCP server emit the *same* shape — the drift the retrieval seam
        exists to prevent applies to serialization too.
        """
        rec = self.record
        return {
            "symbol": rec.symbol,
            "name": rec.name,
            "conditions": rec.conditions,
            "min": rec.min,
            "typ": rec.typ,
            "max": rec.max,
            "value": rec.value,
            "unit": rec.unit.verbatim,
            "unit_canonical": rec.unit.canonical,
            "section": self.citation.section,
            "page": self.citation.page_start,
            "part": self.citation.part,
            "doc": self.citation.doc,
            "citation": self.citation.label,
            "matched_via": self.matched_via,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class PlotHit:
    """One cataloged plot with its citation and match provenance."""

    record: PlotRecord
    citation: Citation
    matched_via: str = ""
    confidence: str = CONFIDENCE_UNKNOWN

    @property
    def file(self) -> str:
        """Corpus-relative image path, `""` until pixels exist."""
        return self.record.file

    def as_dict(self) -> dict:
        """JSON-ready view: the figure, its citation, rung and grade.

        Same rule as `SpecHit.as_dict` — the shape lives in the retrieval core
        so `dsa plots --json` and (ticket 07) the MCP server cannot drift.
        """
        rec = self.record
        return {
            "id": rec.id,
            "caption": rec.caption,
            "figure_number": rec.figure_number,
            "conditions": rec.conditions,
            "section": self.citation.section,
            "page_start": self.citation.page_start,
            "page_end": self.citation.page_end,
            "part": self.citation.part,
            "doc": self.citation.doc,
            "citation": self.citation.label,
            "file": rec.file,
            "tags": list(rec.tags),
            "matched_via": self.matched_via,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SectionHit:
    """One corpus section file with its citation and match provenance."""

    section: SectionFile
    citation: Citation
    matched_via: str = ""
    confidence: str = CONFIDENCE_UNKNOWN


@dataclass(frozen=True)
class SearchHit:
    """One BM25 full-text hit: the section, its citation, score and snippet.

    The citation is built from the manifest entry, not from the snippet, so a
    search result is **cited by construction** — a caller never attributes a
    page itself, which is the whole reason the corpus records page ranges.

    The section's heading travels as structured fields (`section.number` /
    `section.title`, exposed together as `heading`) rather than glued onto the
    front of `snippet`: formatting is a front end's job, and a caller that
    wants only the excerpt should not have to unpick a header from it.
    """

    section: SectionFile
    citation: Citation
    score: float = 0.0
    snippet: str = ""
    terms: tuple[str, ...] = ()
    matched_via: str = "fulltext"
    confidence: str = CONFIDENCE_UNKNOWN

    @property
    def heading(self) -> str:
        """`§4.5 Transmitter Electrical Characteristics`, number optional."""
        if self.section.number:
            return f"§{self.section.number} {self.section.title}".strip()
        return self.section.title

    def as_dict(self) -> dict:
        """JSON-ready view — the one shape the CLI and the MCP server share."""
        return {
            "section": self.section.number,
            "title": self.section.title,
            "file": self.section.file,
            "part": self.citation.part,
            "doc": self.citation.doc,
            "page_start": self.citation.page_start,
            "page_end": self.citation.page_end,
            "citation": self.citation.label,
            "score": round(self.score, 6),
            "snippet": self.snippet,
            "terms": list(self.terms),
            "matched_via": self.matched_via,
            "confidence": self.confidence,
        }
