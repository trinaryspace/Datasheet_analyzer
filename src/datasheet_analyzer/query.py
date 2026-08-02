"""Deterministic spec lookup against built `specs.json` files.

No LLM, no section reads: a known parametric question becomes a sub-kilobyte
lookup with page citations attached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import PlotRecord, PlotSet, SpecRecord, SpecSet

log = logging.getLogger(__name__)


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
        part_dir = Path(self.part_dir)
        out: list[SpecRecord] = []
        for spec_path in part_dir.rglob("docs/*/specs.json"):
            try:
                specset = SpecSet.model_validate_json(
                    spec_path.read_text(encoding="utf-8")
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("skipping unreadable specs.json %s: %s", spec_path, exc)
                continue
            for rec in specset.records:
                if symbol and symbol.lower() not in rec.symbol.lower():
                    continue
                if name and name.lower() not in rec.name.lower():
                    continue
                if section and section.lower() not in rec.section.lower():
                    continue
                out.append(rec)
        return out


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
        page = f"p.{rec.page}" if rec.page is not None else "p.?"
        lines.append(
            f"{rec.name} ({rec.symbol}): {value_str}{cond} — "
            f"§{rec.section}, {page} [table {rec.table_index} row {rec.row_index}]"
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
    """Load every docs/<doc>/plots.json and AND-match caption/conditions,
    section number, and tags.

    ``q`` searches the combined caption + conditions text. ``caption`` and
    ``conditions`` restrict those fields independently.
    """
    part_dir = Path(part_dir)
    tags = tags or []
    out: list[PlotRecord] = []
    for plot_path in part_dir.rglob("docs/*/plots.json"):
        try:
            plotset = PlotSet.model_validate_json(
                plot_path.read_text(encoding="utf-8")
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("skipping unreadable plots.json %s: %s", plot_path, exc)
            continue
        for rec in plotset.plots:
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
            out.append(rec)
    return out


def _pages_label(rec: PlotRecord) -> str:
    if rec.page_start is None:
        return "?"
    if rec.page_end is not None and rec.page_end != rec.page_start:
        return f"p.{rec.page_start}-{rec.page_end}"
    return f"p.{rec.page_start}"


def format_plot_answer(records: list[PlotRecord], limit: int = 8) -> str:
    """Render matching plot records for a human/agent reader."""
    if not records:
        return "No matching plots."
    lines: list[str] = []
    for rec in records[:limit]:
        cond = f" — {rec.conditions}" if rec.conditions else ""
        file_str = f" — file: {rec.file}" if rec.file else ""
        lines.append(
            f"{rec.caption} — §{rec.section} ({_pages_label(rec)}){cond}{file_str}"
        )
    if len(records) > limit:
        lines.append(f"... and {len(records) - limit} more matches")
    return "\n".join(lines)
