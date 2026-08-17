"""Deterministic spec/plot lookup — back-compat shim over `retrieve/`.

No LLM, no section reads: a known parametric question becomes a sub-kilobyte
lookup with page citations attached.

**Deprecated as an implementation.** Since Phase 5 ticket 01 the lookups live
in `datasheet_analyzer.retrieve` (`CorpusIndex` + `Retriever`), which loads a
part once instead of re-parsing every `specs.json` per call and returns typed
hits carrying citation, confidence and `matched_via`. `SpecQuery` and
`find_plots` keep their signatures and their record-list return types for
existing callers; new code should use `Retriever` directly and gets no new
features here. The renderers below stay — formatting is a front-end job — but
they take their citation strings from `Citation`, never build their own.
`format_spec_hits` / `format_plot_hits` / `format_no_match` render typed hits
(rung and confidence included); `format_search_hits` renders the BM25
full-text hits of ticket 03; `format_answer` / `format_plot_answer` keep the
record-list shape for callers that predate them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import PlotRecord, SpecRecord
from datasheet_analyzer.retrieve import (
    Citation,
    PinHit,
    PlotHit,
    Retriever,
    SearchHit,
    SpecHit,
)


@dataclass
class SpecQuery:
    part_dir: Path

    def find(
        self,
        *,
        symbol: str = "",
        name: str = "",
        section: str = "",
    ) -> list[SpecRecord]:
        """Case-insensitive substring match on symbol/name/section (ANDed)."""
        hits = Retriever.for_part(self.part_dir).specs(
            symbol=symbol, name=name, section=section
        )
        return [h.record for h in hits]


def _value_field(rec: SpecRecord) -> str:
    if rec.value:
        return rec.value
    parts = [p for p in (rec.min, rec.typ, rec.max) if p]
    return "/".join(parts) if parts else ""


def format_answer(records: list[SpecRecord], limit: int = 5) -> str:
    """Render matching spec records for a human/agent reader."""
    if not records:
        return "No matching spec records."
    lines: list[str] = []
    for rec in records[:limit]:
        val = _value_field(rec)
        unit = rec.unit.verbatim
        value_str = f"{val} {unit}".strip()
        cond = f", {rec.conditions}" if rec.conditions else ""
        lines.append(
            f"{rec.name} ({rec.symbol}): {value_str}{cond} — "
            f"{Citation.for_spec(rec).label} "
            f"[table {rec.table_index} row {rec.row_index}]"
        )
        if rec.cited_markers:
            for fn in rec.footnotes:
                if fn.marker in rec.cited_markers:
                    lines.append(f"  {fn.marker} {fn.text}")
    if len(records) > limit:
        lines.append(f"... and {len(records) - limit} more matches")
    return "\n".join(lines)


def _part_prefix(citation: Citation, show_part: bool) -> str:
    """`[AFE7950] ` when the caller asked for part labels, else `""`.

    Every hit carries `citation.part` (the retrieval core fills it), but a
    single-part query already said which part it asked; printing it on every
    line there would be noise. Project-scoped output turns it on, because
    across a design the part is the first thing the reader needs.
    """
    return f"[{citation.part}] " if (show_part and citation.part) else ""


def format_spec_hits(hits: list[SpecHit], limit: int = 5, *, show_part: bool = False) -> str:
    """Render typed spec hits, each naming the ladder rung that found it.

    Same line shape as `format_answer` plus a `[via <rung> · <confidence>]`
    tail, so an agent can tell an exact symbol hit from an alias or a fuzzy
    one without a second call.
    """
    if not hits:
        return "No matching spec records."
    lines: list[str] = []
    for hit in hits[:limit]:
        rec = hit.record
        val = _value_field(rec)
        value_str = f"{val} {rec.unit.verbatim}".strip()
        cond = f", {rec.conditions}" if rec.conditions else ""
        lines.append(
            f"{_part_prefix(hit.citation, show_part)}"
            f"{rec.name} ({rec.symbol}): {value_str}{cond} — "
            f"{hit.citation.label} "
            f"[table {rec.table_index} row {rec.row_index}] "
            f"[via {hit.matched_via} · {hit.confidence}]"
        )
        if rec.cited_markers:
            for fn in rec.footnotes:
                if fn.marker in rec.cited_markers:
                    lines.append(f"  {fn.marker} {fn.text}")
    if len(hits) > limit:
        lines.append(f"... and {len(hits) - limit} more matches")
    return "\n".join(lines)


def format_no_match(term: str, suggestions: list[str]) -> str:
    """Explicit no-match plus the nearest candidates — never a guess.

    A query that resolves to nothing has to say so: the ladder stops at the
    fuzzy rung, and what it offers instead is a list of terms the caller can
    re-ask with, clearly labelled as suggestions rather than an answer.
    """
    head = f"No spec record matches {term!r}." if term else "No matching spec records."
    if not suggestions:
        return f"{head} No near candidates in this corpus either."
    listed = "\n".join(f"  - {s}" for s in suggestions)
    return f"{head} Nearest candidates:\n{listed}"


def format_search_hits(hits: list[SearchHit], *, show_part: bool = False) -> str:
    """Render BM25 hits: rank, heading, citation, score, then the snippet.

    The section header is printed here rather than baked into `hit.snippet` —
    the hit carries the heading and the citation as fields, and deciding how
    they read on a terminal is a front end's job.
    """
    if not hits:
        return "No matching sections."
    lines: list[str] = []
    for rank, hit in enumerate(hits, 1):
        lines.append(
            f"{rank}. {_part_prefix(hit.citation, show_part)}{hit.heading} — "
            f"{hit.citation.label} "
            f"[score {hit.score:.2f} · via {hit.matched_via}]"
        )
        if hit.snippet:
            lines.append(f"   {hit.snippet}")
    return "\n".join(lines)


def format_pin_hits(hits: list[PinHit], limit: int = 40, *, show_part: bool = False) -> str:
    """Render pin hits: designator, name, lexicon type, direction, citation.

    The limit is high on purpose — a pin lookup's whole point is that a
    designer stops scrolling a 200-row table, and `--type power` on a large
    BGA legitimately returns dozens of balls. The tail line still says how
    many were held back, because a truncated list that does not admit it is
    the one failure mode worse than a long one.
    """
    if not hits:
        return "No matching pins."
    lines: list[str] = []
    for hit in hits[:limit]:
        rec = hit.record
        direction = f" [{rec.direction}]" if rec.direction else ""
        description = f" — {rec.description}" if rec.description else ""
        lines.append(
            f"{_part_prefix(hit.citation, show_part)}"
            f"{rec.pin}: {rec.name or '(unnamed)'} ({rec.type.value}){direction} — "
            f"{hit.citation.pages}{description} "
            f"[via {hit.matched_via} · {hit.confidence}]"
        )
    if len(hits) > limit:
        lines.append(f"... and {len(hits) - limit} more pins")
    return "\n".join(lines)


def find_plots(
    part_dir: Path,
    *,
    q: str = "",
    caption: str = "",
    conditions: str = "",
    section: str = "",
    tags: list[str] | None = None,
) -> list[PlotRecord]:
    """AND-match plot caption/conditions, section number, and tags.

    ``q`` searches the combined caption + conditions text. ``caption`` and
    ``conditions`` restrict those fields independently.
    """
    hits = Retriever.for_part(part_dir).plots(
        q=q, caption=caption, conditions=conditions, section=section, tags=tags
    )
    return [h.record for h in hits]


def format_plot_hits(hits: list[PlotHit], limit: int = 8, *, show_part: bool = False) -> str:
    """Render typed plot hits — same line as `format_plot_answer` plus the
    `[via <rung> · <confidence>]` tail every graded answer path carries."""
    if not hits:
        return "No matching plots."
    lines: list[str] = []
    for hit in hits[:limit]:
        rec = hit.record
        cond = f" — {rec.conditions}" if rec.conditions else ""
        file_str = f" — file: {rec.file}" if rec.file else ""
        lines.append(
            f"{_part_prefix(hit.citation, show_part)}"
            f"{rec.caption} — §{rec.section} ({hit.citation.pages})"
            f"{cond}{file_str} [via {hit.matched_via} · {hit.confidence}]"
        )
    if len(hits) > limit:
        lines.append(f"... and {len(hits) - limit} more matches")
    return "\n".join(lines)


def format_plot_answer(records: list[PlotRecord], limit: int = 8) -> str:
    """Render matching plot records for a human/agent reader."""
    if not records:
        return "No matching plots."
    lines: list[str] = []
    for rec in records[:limit]:
        cond = f" — {rec.conditions}" if rec.conditions else ""
        file_str = f" — file: {rec.file}" if rec.file else ""
        pages = Citation.for_plot(rec).pages
        lines.append(f"{rec.caption} — §{rec.section} ({pages}){cond}{file_str}")
    if len(records) > limit:
        lines.append(f"... and {len(records) - limit} more matches")
    return "\n".join(lines)
