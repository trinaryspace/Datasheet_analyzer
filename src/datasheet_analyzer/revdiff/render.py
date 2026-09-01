"""A revision diff as markdown — `REVISION_DIFF.md`, the review a designer reads.

The diff renders itself, for the same reason a design card, an answer pack and a
cross-part comparison do: what `dsa diff-rev` prints, what the file on disk says
and what any later surface describes must be one artifact, and a front end that
laid out its own table would be a second opinion about what the two revisions
say.

Three rules the format carries.

**Every value is cited in place.** A cell prints what the revision printed *and*
the page it is on, because a reader reviewing a datasheet update is deciding
whether to open the PDF, and the page number is what makes that decision cheap.

**A delta is marked as derived.** Its column names the direction (`Δ after −
before`) and the number carries `*(derived)*`: no page printed the difference
between two revisions, so nothing here may be quoted as if one had.

**"Review by hand" is a section, not a footnote.** Everything the diff refused
to score is listed under its own heading, verbatim — which is the difference
between a review that is honest and one that merely looks complete. An empty
diff gets the same treatment in reverse: it says *identical*, in words, rather
than leaving a reader to infer it from a missing table.
"""

from __future__ import annotations

from datasheet_analyzer.models import RevisionChange, RevisionDiff
from datasheet_analyzer.revdiff.build import (
    KIND_FIELD,
    KIND_PIN,
    KIND_REGISTER,
    KIND_SECTION,
    KIND_SPEC,
)

#: The banner every rendered diff opens with, naming the derivation-rule version
#: it was produced under — the same machine-readable marker a card and a
#: comparison carry, so a reader can tell which rules made the report.
BANNER_PREFIX = "<!-- derived: card_version"

#: The file a diff is written to, beside the part's `INDEX.md`.
REVISION_DIFF_FILENAME = "REVISION_DIFF.md"

#: The heading the ticket names, and the one a reader must be able to find:
#: everything this tool refused to score is under it, quoted.
REVIEW_HEADING = "## Review by hand"

#: The heading for alignments the diff refused to make at all.
NOT_COMPARABLE_HEADING = "## Not comparable"

#: What each artifact kind is called in the report, in the order a review reads
#: them: structure first (what moved), then values, then the two a designer least
#: expects to have to check.
SECTION_TITLES: tuple[tuple[str, str], ...] = (
    (KIND_SECTION, "Sections"),
    (KIND_SPEC, "Specs"),
    (KIND_PIN, "Pins"),
    (KIND_REGISTER, "Registers"),
    (KIND_FIELD, "Bit fields"),
)

#: The line every diff closes with.
FOOTER = (
    "Every value above is quoted from a record one of the two revisions "
    "publishes, under ADR 0005; every delta is the later quotation minus the "
    "earlier one, in the SI base both sides parsed to, and exists only where "
    "both parsed the same printed column. Everything else is under 'Review by "
    "hand', unscored. Open the cited pages before acting on any of it."
)


def banner(card_version: str) -> str:
    """The derived-artifact banner line for `card_version`."""
    return f"{BANNER_PREFIX} {card_version} -->"


def render_revision_diff(diff: RevisionDiff) -> str:
    """One revision diff as markdown, banner first, cited throughout."""
    lines: list[str] = [banner(diff.card_version), ""]
    lines.append(
        f"# {diff.part_number} — revision diff: "
        f"{_side(diff.before_label, diff.before_revision)} -> "
        f"{_side(diff.after_label, diff.after_revision)}"
    )
    lines.append("")
    # The document *directory name*, not a composed `docs/<doc>` path: on this
    # branch a document may be published once into the shared library store, so
    # a path written here would be right for a self-contained corpus and wrong
    # for a shared one. Every value's own `source` carries the resolvable
    # reference; this line only says which two directories were read.
    lines.append(
        f"- **before:** {_side(diff.before_label, diff.before_revision)} — `{diff.before_doc}`"
    )
    lines.append(
        f"- **after:** {_side(diff.after_label, diff.after_revision)} — `{diff.after_doc}`"
    )
    lines.append("")

    if diff.identical:
        lines += [f"**No differences.** {diff.empty_reason}", ""]
    else:
        for kind, title in SECTION_TITLES:
            changes = diff.of_kind(kind)
            if not changes:
                continue
            lines += [f"## {title}", ""]
            lines += _table(changes)
            lines.append("")

    if diff.review_by_hand:
        lines += [REVIEW_HEADING, ""]
        lines.append(
            f"{len(diff.review_by_hand)} changes carry no numeric delta. They are "
            f"quoted exactly as the two documents printed them and are **not** "
            f"scored — no direction is implied by their order here."
        )
        lines.append("")
        lines += [f"- {line}" for line in diff.review_by_hand]
        lines.append("")

    if diff.notes:
        lines += ["## What this diff measured", ""]
        lines += [f"- {note}" for note in diff.notes]
        lines.append("")

    if diff.unparsed:
        lines += [NOT_COMPARABLE_HEADING, ""]
        lines += [f"- {line}" for line in diff.unparsed]
        lines.append("")

    lines += [FOOTER, ""]
    return "\n".join(lines)


def _side(label: str, revision: str) -> str:
    """How one side is named: the filing label, with the printed revision beside it.

    Both, where both exist, because they answer different questions — what the
    person who filed it called it, and what the document itself says it is.
    """
    if label and revision and label != revision:
        return f"{label} ({revision})"
    return label or revision or "(unlabelled)"


def _table(changes: list[RevisionChange]) -> list[str]:
    """One markdown table for one artifact kind, a delta column and a page column."""
    header = "| What | Change | Before | After | Δ after − before | Aligned on | Pages |"
    rows = [header, "|---|---|---|---|---|---|---|"]
    for change in changes:
        rows.append(
            "| "
            + " | ".join(
                (
                    _what(change),
                    change.change,
                    _cell(change.before),
                    _cell(change.after),
                    _delta_cell(change),
                    change.aligned_on or "—",
                    _pages(change),
                )
            )
            + " |"
        )
    return rows


def _what(change: RevisionChange) -> str:
    """The row's subject: its key, the printed column that moved, its label."""
    parts = [f"`{change.key}`"]
    if change.field:
        parts.append(f"**{change.field}**")
    if change.label and change.label != change.key:
        parts.append(_escape(change.label))
    return " ".join(parts)


def _cell(value) -> str:
    """One side's printed value, escaped for a table cell; `—` when absent.

    `—` means *this revision printed nothing here*, which for an added or removed
    row is the whole finding and must not be confused with an empty cell.
    """
    if value is None or not value.verbatim:
        return "—"
    return _escape(value.verbatim)


def _delta_cell(change: RevisionChange) -> str:
    """The derived number, marked as derived; the refusal's reason where there is none."""
    if change.delta is None:
        return "review by hand"
    value = change.delta.value_si or 0.0
    unit = f" {change.delta.unit_si}" if change.delta.unit_si else ""
    return f"{value:+.6g}{unit} *(derived)*"


def _pages(change: RevisionChange) -> str:
    """`p.4 -> p.5` — where each side printed it, so both are checkable."""
    before = _page(change.before)
    after = _page(change.after)
    if before == after:
        return before
    return f"{before} -> {after}"


def _page(value) -> str:
    if value is None or value.page is None:
        return "p.?"
    return f"p.{value.page}"


def _escape(text: str) -> str:
    """Table-cell text: pipes escaped, newlines flattened, nothing else touched.

    Verbatim stays verbatim — this is a markdown escape, not a normalization, so
    the ohm glyph, the en dash and the glued subscripts a datasheet printed all
    survive exactly as extracted.
    """
    return text.replace("|", "\\|").replace("\n", " ").strip()


__all__ = [
    "BANNER_PREFIX",
    "FOOTER",
    "NOT_COMPARABLE_HEADING",
    "REVIEW_HEADING",
    "REVISION_DIFF_FILENAME",
    "banner",
    "render_revision_diff",
]
