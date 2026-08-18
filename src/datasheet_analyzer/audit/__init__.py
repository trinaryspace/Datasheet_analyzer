"""Corpus audit (phase 7, ticket 05) — the trust signal a consumer can read.

`extraction_stats` tells the *builder* how a build went. This package tells the
*agent* whether to trust the corpus before it answers, which is a different
question with a different audience: thirteen readings taken off artifacts the
corpus already published, each graded against `registry/audit_rubric.yaml` into
a letter, and the letters averaged into one.

- `rubric` — the thresholds, weights and letters, as checked-in data.
- `build`  — the readers, and the `n/a`-vs-zero rule that governs all of them.
- `render` — the per-part scorecard and the fleet table.

The invariant that governs all three: **a metric that cannot be computed is
`n/a` and is excluded from the average.** Never zero, which would defame a
corpus for a statistic nobody recorded; never full marks, which would flatter
one. The convention travels in the scorecard's own `unavailable_policy` field,
so a reader is told the rule rather than left to assume it.
"""

from datasheet_analyzer.audit.build import METRIC_KEYS, Reading, build_scorecard
from datasheet_analyzer.audit.render import (
    FLEET_COLUMNS,
    GRADE_ORDER,
    NA,
    counts,
    grade_of,
    grade_order,
    reading,
    render_fleet,
    render_scorecard,
)
from datasheet_analyzer.audit.rubric import (
    RUBRIC_PATH,
    AuditRubric,
    MetricRule,
    clear_audit_rubric_cache,
    load_audit_rubric,
)

__all__ = [
    "FLEET_COLUMNS",
    "GRADE_ORDER",
    "METRIC_KEYS",
    "NA",
    "RUBRIC_PATH",
    "AuditRubric",
    "MetricRule",
    "Reading",
    "build_scorecard",
    "clear_audit_rubric_cache",
    "counts",
    "grade_of",
    "grade_order",
    "load_audit_rubric",
    "reading",
    "render_fleet",
    "render_scorecard",
]
