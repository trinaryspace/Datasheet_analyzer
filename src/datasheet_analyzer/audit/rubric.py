"""The audit rubric — what a reading has to reach to earn a letter, as data.

`registry/audit_rubric.yaml` is the data; this module only loads it and answers
three questions: what letter does this ratio earn, what letter does this state
earn, and what letter does a weighted mean of letters earn. The split is the
one `structure/aliases.py`, `cards/lexicon.py` and `errata/lexicon.py` already
make: the rubric knows *thresholds*, `audit/build.py` knows *records*.

Two rules here are load-bearing.

- **No threshold, weight or letter is written in Python.** A metric the rubric
  does not carry is not graded at all — it reports `n/a` and is excluded from
  the average — rather than falling back to a default hidden in this file. That
  is what makes the ticket's data-driven criterion testable: a test that edits
  the YAML and asserts a grade moved cannot pass against hard-coded numbers,
  and a test that *deletes* a metric proves there is no Python fallback behind
  it.
- **There is no letter for "could not measure".** `grade_ratio` and
  `grade_state` return `None` for a reading that does not exist, and
  `overall()` excludes those metrics from its mean. A missing statistic scored
  as 0 would defame a corpus for a fact nobody recorded; scored as full marks
  it would flatter one. Both are refused here rather than left to each caller.

A malformed file degrades to an **empty** rubric (invariant 7): every metric
then reports `n/a`, the scorecard reports no overall grade and says why, and
nothing crashes. A rubric that cannot be read must not be able to invent a
grade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from datasheet_analyzer.models import AuditGrade, MetricKind

log = logging.getLogger(__name__)

#: The packaged rubric, beside every other checked-in lexicon.
RUBRIC_PATH = Path(__file__).resolve().parent.parent / "registry" / "audit_rubric.yaml"

#: What an empty rubric says when it grades nothing.
NO_RULE = "the rubric grades no metric named {key!r}"
NO_RUBRIC = "the audit rubric could not be read, so nothing is graded"


@dataclass(frozen=True)
class MetricRule:
    """One metric's row of the rubric: how to grade it, and how much it counts."""

    key: str
    label: str = ""
    kind: MetricKind = MetricKind.RATIO
    weight: float = 1.0
    #: `(grade, minimum)` pairs, highest minimum first. Only for `RATIO`.
    thresholds: tuple[tuple[AuditGrade, float], ...] = ()
    #: Named readings (`{"current": A}`, `{"true": A}`). For `STATE`/`BOOLEAN`.
    values: tuple[tuple[str, AuditGrade], ...] = ()

    def grade_ratio(self, value: float) -> AuditGrade | None:
        """The letter this ratio earns; `None` when the rubric grades none.

        Thresholds are inclusive minimums walked from the top, so a value that
        clears no minimum at all earns the lowest letter the rubric declares —
        not an invented `F`, because a rubric may legitimately stop at `D`.
        """
        if not self.thresholds:
            return None
        for grade, minimum in self.thresholds:
            if value >= minimum:
                return grade
        return min(self.thresholds, key=lambda pair: pair[1])[0]

    def grade_named(self, state: str) -> AuditGrade | None:
        """The letter a named reading earns; `None` when the rubric names none."""
        for name, grade in self.values:
            if name == state:
                return grade
        return None


@dataclass(frozen=True)
class AuditRubric:
    """The loaded `audit_rubric.yaml`."""

    schema_version: str = ""
    #: Letter → points. Empty means nothing can be averaged, which is the
    #: honest reading of a rubric that declares no scale.
    points: tuple[tuple[AuditGrade, float], ...] = ()
    #: `(grade, minimum score)` pairs for the overall letter, highest first.
    overall_cuts: tuple[tuple[AuditGrade, float], ...] = ()
    rules: tuple[MetricRule, ...] = ()
    min_graded_metrics: int = 1
    unavailable_policy: str = ""

    @property
    def keys(self) -> tuple[str, ...]:
        """Every metric this rubric grades, in file order."""
        return tuple(rule.key for rule in self.rules)

    def rule(self, key: str) -> MetricRule | None:
        """The rule for one metric, or `None` when the rubric carries none."""
        for rule in self.rules:
            if rule.key == key:
                return rule
        return None

    def grade_points(self, grade: AuditGrade) -> float | None:
        for name, value in self.points:
            if name is grade:
                return value
        return None

    def overall(
        self, graded: list[tuple[AuditGrade, float]]
    ) -> tuple[AuditGrade | None, float | None, str]:
        """`(grade, score, reason)` for a list of `(grade, weight)` pairs.

        `graded` holds only the metrics that *could* be computed — the caller
        has already dropped the unavailable ones, which is the one place this
        module's "never score a missing metric" rule is enforced. The reason is
        `""` on success and a sentence naming what was missing otherwise, so a
        scorecard with no letter can always say why it has none.
        """
        if not self.rules or not self.points or not self.overall_cuts:
            return None, None, NO_RUBRIC
        if len(graded) < self.min_graded_metrics:
            return (
                None,
                None,
                (
                    f"only {len(graded)} of {len(self.rules)} metrics could be computed "
                    f"for this corpus; the rubric requires {self.min_graded_metrics} "
                    f"before an overall grade means anything"
                ),
            )
        total_weight = sum(weight for _grade, weight in graded)
        if total_weight <= 0:
            return None, None, "every computable metric carries zero weight"
        score = (
            sum((self.grade_points(grade) or 0.0) * weight for grade, weight in graded)
            / total_weight
        )
        for grade, minimum in self.overall_cuts:
            if score >= minimum:
                return grade, score, ""
        return min(self.overall_cuts, key=lambda pair: pair[1])[0], score, ""

    @classmethod
    def from_mapping(cls, data: dict | None) -> AuditRubric:
        """Build from parsed YAML; a malformed key degrades to its default."""
        data = data or {}
        points = tuple(_grade_map(data.get("points"), "points").items())
        rules = []
        raw_metrics = data.get("metrics") or {}
        if not isinstance(raw_metrics, dict):
            log.warning("audit rubric: `metrics` is not a mapping — nothing is graded")
            raw_metrics = {}
        for key, body in raw_metrics.items():
            rule = _rule(str(key), body)
            if rule is not None:
                rules.append(rule)
        return cls(
            schema_version=str(data.get("schema_version", "")),
            points=points,
            overall_cuts=_cuts(data.get("overall"), "overall"),
            rules=tuple(rules),
            min_graded_metrics=_int(data.get("min_graded_metrics"), 1),
            unavailable_policy=str(data.get("unavailable_policy", "") or "").strip(),
        )

    @classmethod
    def read(cls, path: Path | None = None) -> AuditRubric:
        """Parse a rubric file; an unreadable one degrades to an empty rubric."""
        path = Path(path) if path else RUBRIC_PATH
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            log.warning(
                "audit rubric unavailable (%s: %s) — every metric reports n/a",
                path,
                exc,
            )
            return cls()
        return cls.from_mapping(data)


def _int(raw: object, default: int) -> int:
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _float(raw: object, default: float) -> float:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _grade(raw: object, where: str) -> AuditGrade | None:
    """One letter from the file, or `None` with a warning."""
    try:
        return AuditGrade(str(raw).strip())
    except ValueError:
        log.warning("audit rubric: %s names %r, which is not a grade — ignoring", where, raw)
        return None


def _grade_map(raw: object, where: str) -> dict[AuditGrade, float]:
    if not isinstance(raw, dict):
        if raw is not None:
            log.warning("audit rubric: %s is not a mapping — ignoring it", where)
        return {}
    out: dict[AuditGrade, float] = {}
    for key, value in raw.items():
        grade = _grade(key, where)
        if grade is None:
            continue
        try:
            out[grade] = float(value)
        except (TypeError, ValueError):
            log.warning("audit rubric: %s[%s] is not a number (%r)", where, key, value)
    return out


def _cuts(raw: object, where: str) -> tuple[tuple[AuditGrade, float], ...]:
    """`[{grade: A, min: 3.6}, …]` as descending `(grade, minimum)` pairs.

    Sorted here rather than trusted from the file: a rubric whose rows a
    maintainer reordered must not silently start grading everything `F`.
    """
    if not isinstance(raw, list):
        if raw is not None:
            log.warning("audit rubric: %s is not a list — ignoring it", where)
        return ()
    pairs: list[tuple[AuditGrade, float]] = []
    for row in raw:
        if not isinstance(row, dict):
            log.warning("audit rubric: %s holds %r, which is not a row", where, row)
            continue
        grade = _grade(row.get("grade"), where)
        if grade is None:
            continue
        try:
            pairs.append((grade, float(row.get("min"))))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            log.warning("audit rubric: %s[%s] has no numeric `min`", where, grade.value)
    return tuple(sorted(pairs, key=lambda pair: pair[1], reverse=True))


def _rule(key: str, body: object) -> MetricRule | None:
    if not isinstance(body, dict):
        log.warning("audit rubric: metric %r is not a mapping — not graded", key)
        return None
    try:
        kind = MetricKind(str(body.get("kind", "ratio")).strip())
    except ValueError:
        log.warning(
            "audit rubric: metric %r declares kind %r, which is not a metric kind — not graded",
            key,
            body.get("kind"),
        )
        return None
    values: list[tuple[str, AuditGrade]] = []
    raw_values = body.get("values")
    if isinstance(raw_values, dict):
        for name, letter in raw_values.items():
            grade = _grade(letter, f"metrics.{key}.values")
            if grade is not None:
                # `true` / `false` come back from YAML as booleans; the reading
                # a metric carries is a string, so normalize at the boundary.
                values.append((str(name).lower() if isinstance(name, bool) else str(name), grade))
    elif raw_values is not None:
        log.warning("audit rubric: metrics.%s.values is not a mapping", key)
    return MetricRule(
        key=key,
        label=str(body.get("label", "") or key),
        kind=kind,
        weight=_float(body.get("weight"), 1.0),
        thresholds=_cuts(body.get("thresholds"), f"metrics.{key}.thresholds"),
        values=tuple(values),
    )


@cache
def load_audit_rubric(path: Path | None = None) -> AuditRubric:
    """The shipped rubric, parsed once per process (or one at `path`)."""
    return AuditRubric.read(path)


def clear_audit_rubric_cache() -> None:
    """Test hook: re-read the rubric file on the next `load_audit_rubric`."""
    load_audit_rubric.cache_clear()
