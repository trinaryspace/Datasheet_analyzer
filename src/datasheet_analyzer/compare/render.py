"""A cross-part comparison as markdown — the table a part selection is made on.

The comparison renders itself, for the same reason a design card and an answer
pack do: what `dsa compare` prints and what the MCP `compare_parts` tool
describes must be one artifact, and a front end that laid out its own table
would be a second opinion about what the corpora say.

Three rules the format carries.

**Every value is cited in place.** A cell prints the value as the datasheet
printed it *and* the page it is on (`150 °C (§6.1, p.4)`), rather than pushing
citations into a trailing column, because a reader comparing two parts is
reading across a row and the page is what makes each half checkable.

**A delta is marked as derived.** Its column names both operands and its
direction (`Δ LM741 − AD9081 (max)`), and the number carries `*(derived)*`: no
page printed the difference between two datasheets, so nothing here may be
quoted as if one had.

**What could not be compared has its own heading.** "Not comparable" is a
section of this document, not a footnote — every pair the rules refused is
listed there with its verbatim values, which is the difference between a
comparison that is honest and one that merely looks complete.
"""

from __future__ import annotations

from datasheet_analyzer.models import ComparisonCell, ComparisonRow, DerivedValue, PartComparison

#: The banner every rendered comparison opens with, naming the derivation-rule
#: version it was produced under — the same machine-readable marker a card
#: carries, so a reader can tell which rules made the table in front of them.
BANNER_PREFIX = "<!-- derived: card_version"

#: The heading the ticket names, and the one a reader must be able to find:
#: everything the comparison refused to compare is under it.
NOT_COMPARABLE_HEADING = "## Not comparable"

#: The line every comparison closes with.
FOOTER = (
    "Every value above is quoted from a published record under ADR 0005; every "
    "delta is that quotation subtracted from another, in the SI base both sides "
    "parsed to, and exists only where both parsed the same printed column. Open "
    "the cited pages before choosing a part."
)

#: How much of a row's printed detail the markdown shows before cutting it.
DETAIL_CHARS = 48


def banner(card_version: str) -> str:
    """The derived-artifact banner line for `card_version`."""
    return f"{BANNER_PREFIX} {card_version} -->"


def render_comparison(comparison: PartComparison) -> str:
    """One cross-part comparison as markdown, banner first, cited throughout."""
    lines: list[str] = [banner(comparison.card_version), ""]
    lines.append(f"# {' vs '.join(comparison.parts)} — {_subject(comparison)}")
    lines.append("")

    if comparison.rows:
        lines += _table(comparison)
    else:
        lines += [f"**No rows.** {comparison.empty_reason}", ""]

    if comparison.notes:
        lines += ["## What this comparison measured", ""]
        lines += [f"- {note}" for note in comparison.notes]
        lines.append("")
    if comparison.unparsed:
        lines += [NOT_COMPARABLE_HEADING, ""]
        lines += [f"- {line}" for line in comparison.unparsed]
        lines.append("")

    lines += [FOOTER, ""]
    return "\n".join(lines)


def _subject(comparison: PartComparison) -> str:
    """What was asked, in the caller's own words."""
    return f"--{comparison.kind} {comparison.query}".strip()


def _table(comparison: PartComparison) -> list[str]:
    """One markdown table per group, a column per part plus a delta per part.

    A group is the unit for the same reason it is on a card: a `--card limits`
    comparison prints `abs max / recommended max / margin` rows that do not
    share a header with a supply rail. A spec comparison has one unnamed group
    and therefore one table.
    """
    lines: list[str] = []
    others = comparison.parts[1:]
    for title, rows in _blocks(comparison.rows):
        if title:
            lines += [f"## {title}", ""]
        headings = [
            "Parameter",
            *comparison.parts,
            *[f"Δ {part} − {comparison.reference}" for part in others],
            "Grade",
        ]
        lines.append("| " + " | ".join(headings) + " |")
        lines.append("|" + "|".join(["---"] * len(headings)) + "|")
        for row in rows:
            by_part = {cell.part_number: cell for cell in row.cells}
            cells = [_label(row)]
            cells += [_cell(by_part.get(part), row.role) for part in comparison.parts]
            cells += [_delta(by_part.get(part)) for part in others]
            cells.append(_grade(row))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return lines


def _blocks(rows: list[ComparisonRow]) -> list[tuple[str, list[ComparisonRow]]]:
    """Consecutive rows of one group, in comparison order."""
    blocks: list[tuple[str, list[ComparisonRow]]] = []
    for row in rows:
        if blocks and blocks[-1][0] == row.group:
            blocks[-1][1].append(row)
        else:
            blocks.append((row.group, [row]))
    return blocks


def _label(row: ComparisonRow) -> str:
    """The parameter, the column compared, how it aligned, and any finding.

    `aligned_on` is printed rather than kept in the JSON alone: a reader must be
    able to see *why* two differently-named rows are on one line, because a
    silent mis-alignment is the failure this artifact could most easily hide.
    """
    parts = [f"**{row.key}**" if row.flags else row.key]
    if row.role:
        parts.append(f"({row.role})")
    parts.append(f"— {row.aligned_on}")
    if row.flags:
        parts.append(f"**[{', '.join(row.flags)}]**")
    if row.note:
        parts.append(f"({row.note})")
    return " ".join(parts).replace("|", "\\|")


def _cell(cell: ComparisonCell | None, role: str) -> str:
    """One part's column: what it printed, and the page it printed it on.

    A part that publishes no record for the parameter prints `—`, never a blank
    that could be read as a zero or as an unstated agreement.
    """
    if cell is None:
        return "—"
    value = cell.values.get(role) if role else None
    printed = _value(value) if value is not None else _summary(cell)
    label = cell.label.strip()
    detail = f"{label}: " if label else ""
    if len(detail) > DETAIL_CHARS:
        detail = detail[:DETAIL_CHARS].rstrip() + "…: "
    return f"{detail}{printed} ({cell.citation})".replace("|", "\\|")


def _summary(cell: ComparisonCell) -> str:
    """Every column this part printed, when no one column could be compared.

    A row with no shared role still shows both sides — that is what makes a
    refusal readable — so the cell quotes what the part actually printed instead
    of collapsing to a dash.
    """
    printed = [
        f"{role} {_value(value)}" for role, value in cell.values.items() if value.verbatim
    ]
    return "; ".join(printed) if printed else "—"


def _value(value: DerivedValue | None) -> str:
    """A printed value, or a computed number, or an honest dash."""
    if value is None:
        return "—"
    if value.verbatim:
        return value.verbatim
    if value.value_si is None:
        return "—"
    return f"{value.value_si:g} {value.unit_si}".strip() + " *(derived)*"


def _delta(cell: ComparisonCell | None) -> str:
    """The delta column: a derived number, or an honest dash."""
    if cell is None or cell.delta is None:
        return "—"
    number = f"{cell.delta.value_si:+g}" if cell.delta.value_si is not None else "—"
    return f"{number} {cell.delta.unit_si}".strip() + " *(derived)*"


def _grade(row: ComparisonRow) -> str:
    """The weakest grade among the row's values — metadata, never a filter."""
    order = ["high", "medium", "low", "unknown"]
    grades = [
        str(getattr(v.confidence, "value", v.confidence))
        for cell in row.cells
        for v in cell.values.values()
    ]
    known = [g for g in grades if g in order]
    return max(known, key=order.index) if known else "unknown"
