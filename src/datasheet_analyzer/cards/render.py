"""A design card as markdown — the file a human or an agent actually reads.

The card renders itself, for the same reason an answer pack does: the text
written to `cards/power.md` and the text `dsa card` prints must be one string,
or the corpus and the CLI are two products. Front ends choose markdown or JSON;
they never lay out a row.

Two rules the format carries.

**The banner is machine-readable.** `<!-- derived: card_version 5 -->` is the
first line of every card, so a reader — human, agent or `grep` — can tell which
derivation rules produced the file in front of it without opening
`manifest.json`. It is also what makes a stale card visible on sight.

**Every row is cited.** The `Source` column carries the `Citation` of every
record the row's values rest on, taken from `retrieve.results.Citation` rather
than composed here, so a card cites a page in exactly the format `dsa query`,
`dsa ask` and the MCP server do. A row whose values came from two pages prints
both, because a margin that cites only one of its two operands is half-traceable.
"""

from __future__ import annotations

from datasheet_analyzer.cards.build import ROLE_MARGIN
from datasheet_analyzer.models import CardRow, DerivedValue, DesignCard
from datasheet_analyzer.retrieve.results import Citation

#: The banner every rendered card opens with (ticket 07's acceptance criterion).
BANNER_PREFIX = "<!-- derived: card_version"

#: How much of a row's printed detail the markdown shows before cutting it.
DETAIL_CHARS = 72

#: The line every card closes with: what a reader may conclude from it, and the
#: one instruction the agent protocol gives about a `low` grade.
FOOTER = (
    "Every value above is derived from a published record under ADR 0005: "
    "verbatim cells, values computed from them by a named rule, and labels from "
    "`registry/cards.yaml`. Open the cited page before trusting a `low` row."
)

#: Column headings for the keys a card publishes, so a rendered card reads as
#: English rather than as field names.
_HEADINGS = {
    "min": "Min",
    "typ": "Typ",
    "max": "Max",
    "value": "Value",
    "abs_max": "Abs max",
    "recommended_max": "Recommended max",
    ROLE_MARGIN: "Margin",
    "pins": "Pins",
}


def banner(card_version: str) -> str:
    """The derived-artifact banner line for `card_version`."""
    return f"{BANNER_PREFIX} {card_version} -->"


def render_card(card: DesignCard) -> str:
    """One design card as markdown, banner first, citation on every row."""
    lines: list[str] = [banner(card.card_version), ""]
    lines.append(f"# {card.part_number} — {card.title} card")
    lines.append("")
    if card.purpose:
        lines += [card.purpose, ""]

    if card.rows:
        lines += _table(card)
    else:
        lines += [f"**No rows.** {card.empty_reason}", ""]

    if card.notes:
        lines += ["## What this card measured", ""]
        lines += [f"- {note}" for note in card.notes]
        lines.append("")
    if card.unparsed:
        lines += ["## Not on this card", ""]
        lines += [f"- {line}" for line in card.unparsed]
        lines.append("")

    lines += [FOOTER, ""]
    return "\n".join(lines)


def _table(card: DesignCard) -> list[str]:
    """The card's rows as one markdown table per group, in card order.

    A group's columns are the union of the keys its rows publish, so a rail that
    prints no typical and a rail that does still share one table, and the gap is
    an explicit `—` rather than a missing column. A group is the unit here
    because a limits row (`abs max | recommended max | margin`) and a pin row
    (`pins`) genuinely do not share a header.
    """
    lines: list[str] = []
    for title, rows in _blocks(card.rows):
        keys = _columns(rows)
        if title:
            lines += [f"## {title}", ""]
        headings = ["Parameter", *[_HEADINGS.get(k, k) for k in keys], "Grade", "Source"]
        lines.append("| " + " | ".join(headings) + " |")
        lines.append("|" + "|".join(["---"] * len(headings)) + "|")
        for row in rows:
            cells = [_label(row)]
            cells += [_value(row.values.get(key)) for key in keys]
            cells.append(_grade(row))
            cells.append(_sources(row))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def _blocks(rows: list[CardRow]) -> list[tuple[str, list[CardRow]]]:
    """Consecutive rows of one group, in card order."""
    blocks: list[tuple[str, list[CardRow]]] = []
    for row in rows:
        if blocks and blocks[-1][0] == row.group:
            blocks[-1][1].append(row)
        else:
            blocks.append((row.group, [row]))
    return blocks


def _columns(rows: list[CardRow]) -> list[str]:
    """The value keys one group publishes, in the order `_HEADINGS` declares.

    A fixed order rather than first-seen: `min | typ | max` is how a datasheet
    prints a parameter, and a card whose columns swap between two parts would be
    read wrong by someone comparing them.
    """
    seen = {key for row in rows for key in row.values}
    ordered = [key for key in _HEADINGS if key in seen]
    return ordered + sorted(seen - set(ordered))


def _label(row: CardRow) -> str:
    """The row's printed identity, plus the flags and note a reader must see.

    The detail — the parameter name and the row's printed test conditions — is
    cut to `DETAIL_CHARS` with an `…`, because a reference part states a supply
    current under a 300-character operating configuration and a card is a view,
    not the table. The cut is marked and the full text stays in the JSON card
    beside it; no *value* is ever shortened.
    """
    parts = [f"**{row.label}**" if row.flags else row.label]
    if row.detail:
        detail = row.detail
        if len(detail) > DETAIL_CHARS:
            detail = detail[:DETAIL_CHARS].rstrip() + "…"
        parts.append(f"— {detail}")
    if row.flags:
        parts.append(f"**[{', '.join(row.flags)}]**")
    if row.note:
        parts.append(f"({row.note})")
    return " ".join(parts).replace("|", "\\|")


def _value(value: DerivedValue | None) -> str:
    """One cell: the printed string, or a computed number, or an honest dash.

    A value the card does not have prints `—`, never a blank that could be read
    as zero. A *computed* value has no verbatim and prints its number with the
    unit it was computed in, marked `derived` so nobody quotes it as printed text.
    """
    if value is None:
        return "—"
    if value.verbatim:
        return value.verbatim.replace("|", "\\|")
    if value.value_si is None:
        return "—"
    number = f"{value.value_si:g}"
    return f"{number} {value.unit_si}".strip() + " *(derived)*"


def _grade(row: CardRow) -> str:
    """The weakest grade among the row's values — metadata, never a filter."""
    order = ["high", "medium", "low", "unknown"]
    grades = [str(getattr(v.confidence, "value", v.confidence)) for v in row.values.values()]
    known = [g for g in grades if g in order]
    return max(known, key=order.index) if known else "unknown"


def _sources(row: CardRow) -> str:
    """Every distinct citation the row rests on, in value order."""
    labels: list[str] = []
    for value in row.values.values():
        # The value's own section and page, never the row's: a limits row holds
        # two values from two tables, and citing both to one of them would be a
        # citation that does not survive being checked.
        label = Citation(
            section=value.section, page_start=value.page, page_end=value.page
        ).label
        if label not in labels:
            labels.append(label)
    return " / ".join(labels) if labels else "p.?"
