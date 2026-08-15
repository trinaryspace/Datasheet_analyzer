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
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import PlotRecord, SpecRecord
from datasheet_analyzer.retrieve import Citation, Retriever


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
