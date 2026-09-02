"""Rendering a scorecard: one part's card, and the fleet table.

The scorecard renders itself for the same reason a design card, an answer pack
and a revision diff do — `AGENTS.md`'s "no retrieval logic in a front end"
extends to no *formatting decisions about corpus facts* either. `cli.py` calls
these and prints the result; the MCP server ships the model.

Two things this rendering will not do.

- **It never hides an `n/a`.** An unavailable metric keeps its row, prints
  `n/a`, and prints the reason beside it. Dropping the row would leave a
  scorecard that looks complete, which is the failure the metric's honesty was
  built to prevent.
- **It never prints an overall grade the rubric refused.** A corpus with too
  few computable metrics prints `ungraded` and the reason, never a letter.
"""

from __future__ import annotations

from datasheet_analyzer.models import AuditMetric, AuditScorecard, MetricKind

#: What a grade-less metric prints. One spelling, used by both renderings.
NA = "n/a"

#: Worst first. Lives here rather than on `AuditGrade` because it is a
#: *presentation* order — which reading a reader is shown first — and it is what
#: both the fleet table's sort and the headline's "worst graded metric" mean by
#: worse. One definition, so a headline and a table cannot disagree about it.
GRADE_ORDER: dict[str, int] = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4}


def grade_order(grade) -> int:
    """Sort key for a grade; an unknown letter sorts last (best)."""
    return GRADE_ORDER.get(getattr(grade, "value", ""), len(GRADE_ORDER))


def reading(metric: AuditMetric) -> str:
    """A metric's value as a reader sees it: `61%`, `yes`, `unknown`, `n/a`."""
    if not metric.available:
        return NA
    if metric.kind is MetricKind.STATE:
        return metric.state or "unknown"
    if metric.kind is MetricKind.BOOLEAN:
        return "yes" if metric.value else "no"
    if metric.value is None:
        return NA
    return f"{metric.value:.0%}"


def counts(metric: AuditMetric) -> str:
    """`38/62` when the metric is a quotient, else `""`.

    Printed beside the percentage because a rate over four rows and a rate over
    four hundred are different claims and the percentage alone hides which one
    a reader is looking at.
    """
    if metric.denominator is None or metric.denominator <= 0:
        return ""
    return f"{metric.numerator}/{metric.denominator}"


def grade_of(metric: AuditMetric) -> str:
    return metric.grade.value if metric.grade is not None else NA


def render_scorecard(card: AuditScorecard) -> str:
    """The full per-part scorecard, as markdown."""
    grade = card.grade.value if card.grade is not None else "ungraded"
    lines = [
        f"# Corpus audit — {card.part}",
        "",
        f"**Grade: {grade}**"
        + (f" (score {card.score:.2f})" if card.score is not None else "")
        + f" — {card.n_graded} of {len(card.metrics)} metrics graded, "
        + f"{card.n_unavailable} n/a.",
        "",
        f"> {card.headline}",
        "",
        # `staleness.one_line` already carries its own marker — this surface
        # renders the shared sentence, it does not compose a second one.
        card.banner,
        "",
        "| Metric | Reading | Count | Grade | Weight | Notes |",
        "|---|---|---|---|---|---|",
    ]
    for metric in card.metrics:
        note = metric.unavailable_reason if not metric.available else metric.detail
        lines.append(
            f"| {metric.label} | {reading(metric)} | {counts(metric)} | "
            f"{grade_of(metric)} | {metric.weight:g} | {note} |"
        )
    lines += ["", f"*{card.unavailable_policy}*" if card.unavailable_policy else ""]
    if card.notes:
        lines += ["", "## What this corpus needs", ""]
        lines += [f"- {note}" for note in card.notes]
    lines += [
        "",
        (
            f"Rubric: `registry/audit_rubric.yaml` v{card.rubric_version or '?'}; "
            f"scorecard schema v{card.schema_version or '?'}."
        ),
        "",
    ]
    return "\n".join(line for line in lines if line is not None)


#: The fleet table's columns, in order: the metrics a reader compares across
#: parts at a glance. Everything else stays in the per-part card, because a
#: thirteen-column table is not a fleet view.
FLEET_COLUMNS: tuple[str, ...] = (
    "record_confidence",
    "mean_fidelity",
    "golden_pass_rate",
    "revision_freshness",
)


def render_fleet(cards: list[AuditScorecard]) -> str:
    """`dsa audit --all`: one row per part, worst grade first.

    Sorted by grade rather than by name, because a fleet table exists to put
    the corpus that needs attention at the top. An ungraded corpus sorts above
    every graded one: "we do not know" is the reading that most needs acting on.
    """
    rows = sorted(
        cards,
        key=lambda c: (-1 if c.grade is None else grade_order(c.grade), c.part),
    )
    header = ["Part", "Grade", "Graded", "n/a"]
    labels: list[str] = []
    for key in FLEET_COLUMNS:
        label = next((m.label for c in cards for m in c.metrics if m.key == key), key)
        labels.append(label)
    lines = [
        "# Corpus audit — fleet",
        "",
        f"{len(cards)} part(s), worst grade first.",
        "",
        "| " + " | ".join(header + labels) + " |",
        "|" + "---|" * (len(header) + len(labels)),
    ]
    for card in rows:
        by_key = {m.key: m for m in card.metrics}
        cells = [
            card.part,
            card.grade.value if card.grade is not None else "ungraded",
            str(card.n_graded),
            str(card.n_unavailable),
        ]
        for key in FLEET_COLUMNS:
            metric = by_key.get(key)
            cells.append(reading(metric) if metric is not None else NA)
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## Headlines", ""]
    lines += [f"- **{card.part}** — {card.headline}" for card in rows]
    policy = next((c.unavailable_policy for c in cards if c.unavailable_policy), "")
    if policy:
        lines += ["", f"*{policy}*"]
    lines.append("")
    return "\n".join(lines)
