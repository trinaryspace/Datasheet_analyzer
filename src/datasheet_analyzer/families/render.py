"""`FAMILY_INDEX.md` — the series as one always-loadable file.

Phase 7, ticket 07. The rendering half of `families/build.py`, and it carries
one rule the builder cannot: a **hard token budget**, with staged degradation,
because the whole claim of this artifact is that reading it costs less than
reading its members' indexes. An index that grew with the delta count would
quietly stop being cheaper than the thing it replaces, and nobody would notice —
so it is bounded, and when it drops something it says so, exactly as
`PROJECT_INDEX.md` does.

The ladder drops the least-important block first and never touches the product:

| Stage | Dropped |
|---|---|
| 0 | nothing |
| 1 | the "How to use" conventions |
| 2 | + the per-alignment refusal *listing* (its counting sentence stays) |
| 3 | + the shared-section listing (its count and its token total stay) |
| 4 | + the divergent-section listing |
| 5 | + the pin, register and bit-field delta tables |
| 6–8 | + the spec delta table, capped at 60, then 25, then 10 rows |

— leaving the members, the counts, and as much of the spec delta table as fits,
which is what someone asked the question for. The delta table is capped last and
`families/<NAME>/family.json` beside it always holds every row, so a cap costs a
reader scrolling rather than information. `build._ordered` decides *which* rows
survive a cap — the parameters every member printed differently first, then the
ones only some members print, then the alignments nobody could pair — so a
bounded index still leads with the answer to "what is different?".

Two things are **reserved tail** and are laid down before anything
discretionary: the counting sentences invariant 8 requires of a consumer that
compares (how many rows aligned, how many were refused, how many rows a cap
removed), and the note naming any declared member with no corpus. A budget may
cost a reader detail; it may never cost them the knowledge that detail is
missing.

Below the last stage the file goes over budget and says *that*, rather than
shipping a family index with no delta table at all.
"""

from __future__ import annotations

from datasheet_analyzer.compare.build import FLAG_AMBIGUOUS, FLAG_ONLY_IN
from datasheet_analyzer.families.build import STATE_PARTIAL
from datasheet_analyzer.models import ComparisonRow, FamilyIndex
from datasheet_analyzer.tokens import count_tokens

#: The file a family publishes, beside `families/<NAME>/`.
FAMILY_INDEX_FILENAME = "FAMILY_INDEX.md"
#: Its machine-readable twin, written beside it.
FAMILY_JSON_FILENAME = "family.json"

BANNER_PREFIX = "<!-- derived: family_version"

SHARED_HEADING = "## Shared sections"
DIVERGENT_HEADING = "## Sections that differ"
DELTA_HEADING = "## Spec deltas"
PIN_HEADING = "## Pin deltas"
REGISTER_HEADING = "## Register deltas"
NOT_COMPARABLE_HEADING = "## Not comparable"

_TRUNCATION_NOTICE = (
    "_Truncated to fit a {budget}-token budget — raise it with the "
    "DSA_FAMILY_INDEX_TOKEN_BUDGET setting to see the rest._"
)
_FLOOR_NOTICE = (
    "_A {budget}-token budget is below this family's delta table; the members "
    "and the deltas are kept regardless — raise it with the "
    "DSA_FAMILY_INDEX_TOKEN_BUDGET setting._"
)

#: What a cell prints when a member published nothing for a row. Never blank:
#: an empty table cell reads as "no difference" and this means the opposite.
EM_DASH = "—"


def banner(index: FamilyIndex) -> str:
    """The derived-artifact banner every derived file in this repo opens with."""
    return (
        f"{BANNER_PREFIX} {index.schema_version} card_version {index.card_version} "
        f"— every value below is quoted from a member's own published record; "
        f"nothing here is written by a model -->"
    )


def render_family_index(index: FamilyIndex, *, token_budget: int = 0) -> str:
    """`FAMILY_INDEX.md`, degrading in stages until it fits `token_budget`.

    `token_budget <= 0` renders everything — the form `--json` and a test want,
    and the form the measurement of "smaller than the sum of its members'
    indexes" must *not* use, because a bound you did not apply is not a result.
    """
    stages = [
        # (conventions, refusal listing, shared list, divergent list, artifacts,
        #  delta-table row cap; 0 = every row)
        (True, True, True, True, True, 0),
        (False, True, True, True, True, 0),
        (False, False, True, True, True, 0),
        (False, False, False, True, True, 0),
        (False, False, False, False, True, 0),
        (False, False, False, False, False, 0),
        (False, False, False, False, False, 60),
        (False, False, False, False, False, 25),
        (False, False, False, False, False, 10),
    ]
    if token_budget <= 0:
        return _render(index, *stages[0], notice="")
    for stage, flags in enumerate(stages):
        notice = _TRUNCATION_NOTICE.format(budget=token_budget) if stage else ""
        text = _render(index, *flags, notice=notice)
        if count_tokens(text) <= token_budget:
            return text
    return _render(
        index, False, False, False, False, False, 10,
        notice=_FLOOR_NOTICE.format(budget=token_budget),
    )


def _render(
    index: FamilyIndex,
    conventions: bool,
    refusals: bool,
    shared_list: bool,
    divergent_list: bool,
    artifacts: bool,
    max_rows: int,
    *,
    notice: str,
) -> str:
    out: list[str] = [banner(index), ""]
    out += _header(index)
    out += _counts(index)
    if index.empty_reason:
        out += [index.empty_reason, ""]
    out += _shared(index, listing=shared_list)
    out += _divergent(index, listing=divergent_list)
    out += _delta_table(DELTA_HEADING, index.deltas, index.members, max_rows=max_rows)
    if artifacts:
        out += _delta_table(PIN_HEADING, index.pin_deltas, index.members)
        out += _delta_table(
            REGISTER_HEADING, index.register_deltas, index.members
        )
    out += _refusals(index, listing=refusals)
    if conventions:
        out += _conventions(index)
    if notice:
        out += [notice, ""]
    return "\n".join(out)


def _header(index: FamilyIndex) -> list[str]:
    title = index.title or f"{index.name} family"
    members = ", ".join(index.members) or "(none)"
    return [
        f"# {index.name} — {title}",
        "",
        (
            f"> Members: {members}. Deltas are signed against "
            f"**{index.reference}** (the first member declared in "
            f"`registry/families.yaml`)."
        ),
        "",
    ]


def _counts(index: FamilyIndex) -> list[str]:
    """The reserved tail: what aligned, what agreed, what could not be read.

    Laid down before anything discretionary, because these sentences *are* the
    honesty half invariant 8 asks for. A reader who is shown ten deltas and not
    told that four hundred rows were refused has been given a summary that is
    wrong in the direction that matters.
    """
    shared = len(index.shared_sections)
    lines = [
        "## What this family says",
        "",
        (
            f"- **{shared} of {len(index.sections)} sections are identical "
            f"across every member** and are listed once below; the other "
            f"{len(index.sections) - shared} differ and are listed per member."
        ),
        (
            f"- **{index.n_specs_aligned} spec rows align** across the members; "
            f"{index.n_specs_identical} print the same values everywhere and are "
            f"not tabulated, {len(index.deltas)} differ and are in the delta "
            f"table."
        ),
    ]
    if index.pin_deltas or index.register_deltas:
        lines.append(
            f"- **{len(index.pin_deltas)} pin** and "
            f"**{len(index.register_deltas)} register/bit-field** rows differ."
        )
    for note in index.notes:
        lines.append(f"- {note}")
    if index.unparsed:
        lines.append(
            f"- **{len(index.unparsed)} alignments were refused** rather than "
            f"guessed at; they are listed under *{NOT_COMPARABLE_HEADING.strip('# ')}* "
            f"with their printed values."
        )
    lines.append("")
    return lines


def _shared(index: FamilyIndex, *, listing: bool) -> list[str]:
    shared = index.shared_sections
    if not shared:
        return []
    total = sum(s.tokens for s in shared)
    lines = [
        SHARED_HEADING,
        "",
        (
            f"Identical in every member — read once, from "
            f"**{index.reference}** ({total} tokens, which every other member "
            f"would otherwise repeat)."
        ),
        "",
    ]
    if not listing:
        lines += [f"_{len(shared)} sections; listing dropped to fit the budget._", ""]
        return lines
    for section in shared:
        head = f"§{section.number} " if section.number else ""
        lines.append(
            f"- {head}{section.title} — `{section.files[index.reference]}` "
            f"({section.pages[index.reference]}, {section.tokens} tok)"
        )
    lines.append("")
    return lines


def _divergent(index: FamilyIndex, *, listing: bool) -> list[str]:
    divergent = index.divergent_sections
    if not divergent:
        return []
    lines = [
        DIVERGENT_HEADING,
        "",
        (
            "Follow the member's own file — these are the only sections a "
            "family reader has to open more than once."
        ),
        "",
    ]
    if not listing:
        lines += [
            f"_{len(divergent)} sections; listing dropped to fit the budget._",
            "",
        ]
        return lines
    for section in divergent:
        head = f"§{section.number} " if section.number else ""
        mark = " *(not in every member)*" if section.state == STATE_PARTIAL else ""
        lines.append(f"- {head}{section.title}{mark} — {section.reason}")
        for part in section.members:
            title = section.titles.get(part, "")
            shown = f" “{title}”" if title and title != section.title else ""
            lines.append(
                f"  - {part}:{shown} `{section.files[part]}` ({section.pages[part]})"
            )
    lines.append("")
    return lines


def _delta_table(
    heading: str,
    rows: list[ComparisonRow],
    members: list[str],
    *,
    max_rows: int = 0,
) -> list[str]:
    """One delta table: a row per parameter, a column per member, plus the delta.

    Every cell carries the printed value **and** its citation, exactly as
    `compare/render.py` prints one: a value quoted without the page it came from
    is the one thing this repo must never emit.

    `max_rows` (0 = every row) is the budget's last resort, and it **says what it
    removed** — a table silently showing the first ten of two hundred rows would
    read as a two-hundredth of the truth with no seam.
    """
    if not rows:
        return []
    shown = rows if max_rows <= 0 else rows[:max_rows]
    header = ["Parameter", "Column", *members, "Δ vs " + (members[0] if members else "")]
    lines = [
        heading,
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in shown:
        by_part = {cell.part_number: cell for cell in row.cells}
        role = row.role or _first_role(row)
        cells = [_row_label(row), role or EM_DASH]
        for part in members:
            cell = by_part.get(part)
            cells.append(_cell_text(cell, role) if cell is not None else EM_DASH)
        cells.append(_delta_text(row))
        lines.append("| " + " | ".join(cells) + " |")
        if row.note:
            lines.append(f"| | | {row.note} " + "| " * len(members) + "|")
    if len(shown) < len(rows):
        lines.append("")
        lines.append(
            f"_{len(shown)} of {len(rows)} rows shown — the rest were cut to fit "
            f"the token budget, most-different first. Every row is in "
            f"`{FAMILY_JSON_FILENAME}` beside this file._"
        )
    lines.append("")
    return lines


def _row_label(row: ComparisonRow) -> str:
    label = row.key or "(unnamed row)"
    if row.group:
        label = f"{label} <br>_{row.group}_"
    flags = [f for f in (FLAG_ONLY_IN, FLAG_AMBIGUOUS) if f in row.flags]
    return f"**{label}**" + ("".join(f" `{f}`" for f in flags))


def _first_role(row: ComparisonRow) -> str:
    for cell in row.cells:
        for role in cell.values:
            return role
    return ""


def _cell_text(cell, role: str) -> str:
    value = cell.values.get(role)
    if value is None:
        # The member holds a column of this row but printed nothing in *this*
        # one. Say which columns it did print rather than an em dash that reads
        # as "this part does not state it".
        printed = ", ".join(sorted(cell.values)) or "nothing"
        return f"{EM_DASH} _(prints {printed})_"
    body = value.verbatim or EM_DASH
    return f"{body} <br>`{cell.citation}`" if cell.citation else body


def _delta_text(row: ComparisonRow) -> str:
    """Every member's delta against the reference, or an em dash.

    A delta carries `*(derived)*` for the reason a card's margin does: no page
    printed a difference between two datasheets, so nothing here may read as a
    quotation.
    """
    parts = []
    for cell in row.cells:
        if cell.delta is None or cell.delta.value_si is None:
            continue
        sign = "+" if cell.delta.value_si > 0 else ""
        parts.append(
            f"{cell.part_number} {sign}{_num(cell.delta.value_si)} "
            f"{cell.delta.unit_si} *(derived)*"
        )
    return "; ".join(parts) if parts else EM_DASH


def _num(value: float) -> str:
    """A delta printed without float noise; never rounded into a false precision."""
    return f"{value:.6g}"


def _refusals(index: FamilyIndex, *, listing: bool) -> list[str]:
    if not index.unparsed:
        return []
    lines = [
        NOT_COMPARABLE_HEADING,
        "",
        (
            f"{len(index.unparsed)} alignments this tool refused rather than "
            f"guessed at, with what each member actually printed."
        ),
        "",
    ]
    if not listing:
        lines += ["_Listing dropped to fit the budget; the count above stands._", ""]
        return lines
    lines += [f"- {line}" for line in index.unparsed]
    lines.append("")
    return lines


def _conventions(index: FamilyIndex) -> list[str]:
    return [
        "## How to use this family index",
        "",
        (
            f"- A section under *{SHARED_HEADING.strip('# ')}* is identical in "
            f"every member: read {index.reference}'s copy and it holds for all "
            f"of them."
        ),
        (
            f"- A section under *{DIVERGENT_HEADING.strip('# ')}* is not: open "
            f"the member you are designing with."
        ),
        (
            "- A spec row that is **not** in a delta table printed the same "
            "value in every member. The counts above say how many that is."
        ),
        (
            f"- Ask the whole family at once: "
            f"`dsa ask --family {index.name} \"<question>\"`."
        ),
        "",
    ]
