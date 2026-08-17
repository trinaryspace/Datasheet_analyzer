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
    RegisterHit,
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


def format_register_hits(
    hits: list[RegisterHit],
    limit: int = 40,
    *,
    show_part: bool = False,
    show_fields: bool = False,
) -> str:
    """Render register hits: address, acronym, reset, access, citation.

    The reset prints as the document printed it and never as a number the
    corpus computed: `reset=0x0223` is what the page says, and a register the
    document states no reset for prints `reset=?` rather than a plausible zero
    — ADR 0005's "null and says so" at the surface a human reads. The limit is
    the pin renderer's, and for the same reason: a register map is long, and a
    truncated list that does not admit it is worse than a long one.

    `show_fields` prints each register's bit fields underneath it (ticket 06),
    and prints the *reason* there are none when there are none — a register
    whose field table was refused must not look like a register with nothing to
    configure. Bits nobody claimed are printed too, for the same reason.
    """
    if not hits:
        return "No matching registers."
    lines: list[str] = []
    for hit in hits[:limit]:
        rec = hit.record
        reset = rec.reset.verbatim if rec.reset is not None else "?"
        access = f" [{rec.access}]" if rec.access else ""
        description = f" — {rec.description}" if rec.description else ""
        lines.append(
            f"{_part_prefix(hit.citation, show_part)}"
            f"{rec.address.verbatim}: {rec.name or '(unnamed)'} "
            f"(reset={reset}){access} — {hit.citation.pages}{description} "
            f"[via {hit.matched_via} · {hit.confidence}]"
        )
        if show_fields:
            lines.extend(_register_field_lines(hit))
    if len(hits) > limit:
        lines.append(f"... and {len(hits) - limit} more registers")
    return "\n".join(lines)


def _register_field_lines(hit: RegisterHit) -> list[str]:
    """The indented bit-field block under one rendered register."""
    rec = hit.record
    if not rec.fields:
        return [f"    (no bit fields published: {rec.fields_reason})"]
    width = f"{rec.width}-bit" if rec.width is not None else "unknown width"
    lines = [f"    {width} · fields {rec.fields_confidence.value}"]
    for record in rec.fields:
        access = f" [{record.access}]" if record.access else ""
        reset = f" reset={record.reset}" if record.reset else ""
        lines.append(
            f"    [{record.bits.verbatim}] {record.name or '(unnamed)'}"
            f"{access}{reset} — p.{record.page if record.page is not None else '?'}"
        )
    if rec.unaccounted_bits:
        lines.append(
            f"    bits claimed by no field: {', '.join(rec.unaccounted_bits)}"
        )
    return lines


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


def format_axes(rec: PlotRecord) -> str:
    """The figure's axis catalog as one line, or `""` when it has none.

    `x: Output Frequency 600–1500 MHz (linear) · y: Output Full Scale −2–7 dBm`
    — the printed titles, the printed tick range and the printed unit, so a
    reader can tell from the listing whether this is the figure to open. An axis
    that was not read prints nothing at all rather than a placeholder range.
    """
    parts: list[str] = []
    for name in ("x", "y"):
        label = getattr(rec, f"{name}_label")
        lo, hi = getattr(rec, f"{name}_min"), getattr(rec, f"{name}_max")
        if not label and lo is None:
            continue
        span = f" {_num(lo)}–{_num(hi)}" if lo is not None and hi is not None else ""
        unit = f" {getattr(rec, f'{name}_unit')}" if getattr(rec, f"{name}_unit") else ""
        scale = getattr(rec, f"{name}_scale")
        tail = f" ({scale.value})" if scale is not None else ""
        parts.append(f"{name}: {label or '?'}{span}{unit}{tail}")
    return " · ".join(parts)


def _num(value: float | None) -> str:
    """A tick value the way the axis printed it — no trailing `.0`."""
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else str(value)


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
        axes = format_axes(rec)
        if axes:
            lines.append(f"    axes — {axes} [{rec.axis_confidence.value}]")
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
