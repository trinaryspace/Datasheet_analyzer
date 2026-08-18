"""Building one corpus's scorecard: thirteen readings, each graded or `n/a`.

`ExtractionStats` tells the *builder* how a build went. Nothing told the
*agent* whether to trust a corpus before answering, which is what this module
computes: every number here is a count of records the corpus already published
divided by another, graded against `registry/audit_rubric.yaml`.

Invariant 8 applies to every metric even though a scorecard is never written to
disk: each one carries `source` (the artifact it was read from) and
`derivation` (the named rule that produced it), and **no model call appears
anywhere in the path**.

The rule that shapes this whole module is the ticket's:

> A metric that cannot be computed is reported as `n/a` and excluded from the
> average, never scored as zero.

So every reader below returns either a number *or* a reason, and the reason is
specific enough to act on. Three cases recur and are worth naming, because
they are the difference between a defect and a fact about the document:

- **the corpus predates the field.** `CorpusStats.tables_pinned` is `None`, the
  confidence mixes are `{}`, `manifest.card_version` is `""`. The corpus needs
  a rebuild, and the scorecard says so in `notes` rather than grading the part
  down for a statistic nobody recorded. Both reference corpora under `parts/`
  are in this state today, which is exactly the fleet-honesty case `dsa audit`
  exists to expose.
- **the backend does not compute it.** Only `pdf_layout` runs a table
  reconstruction gate, so an HTML-backed document has no accept rate and no
  fidelity. `n/a`, not 0 %.
- **the document does not have it.** A datasheet that prints no figures has no
  axis coverage; a part with no golden benchmark has no pass rate. `n/a` again.

What is *not* `n/a` is a **missing artifact**: a modern corpus that publishes no
pins, no registers or no card rows is graded down (the rubric decides how far),
because that is a fact about this corpus that changes what an agent can answer.

One metric is deliberately narrower than its `dsa verify` namesake and says so.
`golden_pass_rate` runs every corpus-side check `dsa verify` runs — the section
half of each text question and all seven query paths — but **not** the
page-truth half, which needs the printed PDF and therefore a file that is not
part of the corpus. The derivation names it (`golden_corpus_checks`) and the
metric's `detail` states it, so nobody reads this number as the benchmark's.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.audit.render import grade_order, reading
from datasheet_analyzer.audit.rubric import NO_RULE, AuditRubric, load_audit_rubric
from datasheet_analyzer.config import AUDIT_SCHEMA_VERSION
from datasheet_analyzer.models import (
    AuditMetric,
    AuditScorecard,
    Confidence,
    CorpusManifest,
    MetricKind,
)
from datasheet_analyzer.staleness import CorpusStaleness, audit_metric, one_line

log = logging.getLogger(__name__)

#: The metric keys this module can read, in the order a scorecard prints them.
#: The rubric decides what each one *earns*; this tuple decides what exists.
METRIC_KEYS: tuple[str, ...] = (
    "section_page_coverage",
    "table_pin_rate",
    "table_accept_rate",
    "mean_fidelity",
    "spec_page_rate",
    "record_confidence",
    "pins_present",
    "registers_present",
    "cards_present",
    "axis_coverage",
    "alias_hit_rate",
    "revision_freshness",
    "golden_pass_rate",
)

#: The reason every "this corpus predates the field" metric gives, once, so the
#: wording cannot drift between metrics.
REBUILD = "rebuild this corpus with `dsa build` to record it"


@dataclass(frozen=True)
class Reading:
    """One metric's raw reading before the rubric grades it.

    `value` is `None` exactly when the metric could not be computed, and
    `reason` is then non-empty. Keeping the two together is what stops a caller
    from turning an absence into a zero on the way to the rubric.
    """

    value: float | None = None
    state: str = ""
    numerator: int | None = None
    denominator: int | None = None
    detail: str = ""
    reason: str = ""
    source: str = ""
    derivation: str = ""

    @property
    def available(self) -> bool:
        return not self.reason


def _ratio(
    numerator: int,
    denominator: int,
    *,
    empty_reason: str,
    source: str,
    derivation: str,
    detail: str = "",
) -> Reading:
    """`numerator / denominator`, or the stated reason when there is nothing to divide."""
    if denominator <= 0:
        return Reading(reason=empty_reason, source=source, derivation=derivation)
    return Reading(
        value=numerator / denominator,
        numerator=numerator,
        denominator=denominator,
        detail=detail,
        source=source,
        derivation=derivation,
    )


# --- the readers -------------------------------------------------------------


def _section_page_coverage(manifest: CorpusManifest) -> Reading:
    stats = manifest.stats
    total = stats.sections_with_pages + stats.sections_without_pages
    return _ratio(
        stats.sections_with_pages,
        total,
        empty_reason="this corpus publishes no sections",
        source="manifest.json#stats",
        derivation="sections_with_pages/n_sections",
    )


def _table_pin_rate(manifest: CorpusManifest) -> Reading:
    stats = manifest.stats
    if stats.tables_pinned is None:
        return Reading(
            reason=f"this corpus records no table pinning count — {REBUILD}",
            source="manifest.json#stats",
            derivation="tables_pinned/n_tables",
        )
    return _ratio(
        stats.tables_pinned,
        stats.n_tables,
        empty_reason="this corpus publishes no tables",
        source="manifest.json#stats",
        derivation="tables_pinned/n_tables",
        detail=(
            f"{stats.n_tables - stats.tables_pinned} table(s) cite their section's "
            f"page range rather than one printed page"
        ),
    )


def _table_accept_rate(manifest: CorpusManifest) -> Reading:
    detected = sum(st.tables_detected for st in manifest.extraction_stats.values())
    accepted = sum(st.tables_accepted for st in manifest.extraction_stats.values())
    reasons = [r for st in manifest.extraction_stats.values() for r in st.rejection_reasons]
    detail = ""
    if reasons:
        shown = "; ".join(reasons[:3])
        detail = f"rejection reasons: {shown}" + ("; …" if len(reasons) > 3 else "")
    return _ratio(
        accepted,
        detected,
        empty_reason=(
            "no backend of this corpus runs a table reconstruction gate "
            "(only `pdf_layout` detects and rejects tables)"
        ),
        source="manifest.json#extraction_stats",
        derivation="tables_accepted/tables_detected",
        detail=detail,
    )


def _mean_fidelity(manifest: CorpusManifest) -> Reading:
    scored = [
        st for st in manifest.extraction_stats.values() if st.mean_fidelity > 0.0
    ]
    if not scored:
        return Reading(
            reason=(
                "no document of this corpus records a table fidelity score "
                "(only `pdf_layout` computes one)"
            ),
            source="manifest.json#extraction_stats",
            derivation="mean(mean_fidelity)",
        )
    return Reading(
        value=sum(st.mean_fidelity for st in scored) / len(scored),
        detail=f"over {len(scored)} document(s)",
        source="manifest.json#extraction_stats",
        derivation="mean(mean_fidelity)",
    )


def _spec_page_rate(index) -> Reading:
    specs = [rec for doc in index.docs for rec in doc.specs]
    with_page = sum(1 for rec in specs if rec.page is not None)
    return _ratio(
        with_page,
        len(specs),
        empty_reason="this corpus publishes no spec records",
        source="docs/*/specs.json",
        derivation="records_with_page/n_records",
    )


def _record_confidence(manifest: CorpusManifest) -> Reading:
    """Share of graded records carrying `high`, over every record kind.

    `unknown` is excluded from the denominator rather than counted as a bad
    grade: it means the record predates grading, which is a fact about the
    corpus's age and is reported as a rebuild note, not as low confidence.
    """
    stats = manifest.stats
    mixes = {
        "specs": stats.spec_confidence,
        "plots": stats.plot_confidence,
        "pins": stats.pin_confidence,
        "registers": stats.register_confidence,
    }
    counts: dict[str, int] = {}
    for mix in mixes.values():
        for grade, n in mix.items():
            counts[grade] = counts.get(grade, 0) + int(n)
    graded = sum(
        counts.get(g.value, 0) for g in (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW)
    )
    if graded <= 0:
        return Reading(
            reason=f"this corpus grades no record (published before per-record confidence) — {REBUILD}",
            source="manifest.json#stats",
            derivation="high/(high+medium+low)",
        )
    detail = "; ".join(
        f"{label} " + " / ".join(f"{n} {grade}" for grade, n in mix.items())
        for label, mix in mixes.items()
        if mix
    )
    return Reading(
        value=counts.get(Confidence.HIGH.value, 0) / graded,
        numerator=counts.get(Confidence.HIGH.value, 0),
        denominator=graded,
        detail=detail,
        source="manifest.json#stats",
        derivation="high/(high+medium+low)",
    )


def _derived_artifacts_readable(manifest: CorpusManifest) -> str:
    """`""` when the phase-6 derived counts mean anything, else the reason.

    `card_version` is the discriminator, and it is the right one: it is stamped
    by every publish that ran under ADR 0005 and is `""` on every corpus older
    than it. Without it, `n_pins == 0` on a 2025 corpus is indistinguishable
    from a datasheet that genuinely prints no pin table — and grading the first
    as if it were the second is precisely the "scored as zero" failure this
    ticket forbids.
    """
    if manifest.card_version:
        return ""
    return (
        "this corpus predates the derived artifacts (no `card_version` in its "
        f"manifest), so an absent one is not a finding — {REBUILD}"
    )


def _present(
    manifest: CorpusManifest, count: int, *, noun: str, source: str, derivation: str
) -> Reading:
    reason = _derived_artifacts_readable(manifest)
    if reason:
        return Reading(reason=reason, source=source, derivation=derivation)
    return Reading(
        value=1.0 if count > 0 else 0.0,
        state="true" if count > 0 else "false",
        numerator=count,
        detail=f"{count} {noun}",
        source=source,
        derivation=derivation,
    )


def _axis_coverage(index) -> Reading:
    """Share of *attempted* axis readings that came out `high`.

    A plot whose `axis_confidence` is `UNKNOWN` was never read — the corpus
    predates the catalog, or the document had no page geometry — so it is not
    in the denominator. A plot graded `LOW` **is**: that reading was attempted
    and the axes could not be read, which is a finding about the figure.
    """
    plots = [p for doc in index.docs for p in doc.plots]
    attempted = [p for p in plots if p.axis_confidence is not Confidence.UNKNOWN]
    if not attempted:
        reason = (
            "this corpus publishes no figures"
            if not plots
            else f"no figure of this corpus carries an axis reading — {REBUILD}"
        )
        return Reading(
            reason=reason, source="docs/*/plots.json", derivation="axis_high/axis_attempted"
        )
    high = sum(1 for p in attempted if p.axis_confidence is Confidence.HIGH)
    return _ratio(
        high,
        len(attempted),
        empty_reason="no figure of this corpus carries an axis reading",
        source="docs/*/plots.json",
        derivation="axis_high/axis_attempted",
        detail=f"{len(plots) - len(attempted)} figure(s) never had their axes read",
    )


def _revision_freshness(staleness: CorpusStaleness) -> Reading:
    metric = audit_metric(staleness)
    return Reading(
        state=metric["grade_input"],
        detail=metric["banner"],
        source="sources.json",
        derivation="corpus_staleness",
    )


# --- the golden-set readers --------------------------------------------------


def _golden_questions(golden: Path | None):
    """The part's benchmark, or `(None, reason)` when it has none."""
    if golden is None:
        return None, "no golden benchmark was supplied for this part"
    path = Path(golden)
    if not path.exists():
        return None, (
            f"this part has no golden benchmark ({path.name} is missing) — write one, "
            f"or `dsa verify` will refuse the corpus too"
        )
    from datasheet_analyzer.evalh.golden import load_golden

    questions = load_golden(path)
    if not questions:
        return None, f"the golden benchmark {path.name} holds no questions"
    return questions, ""


def _golden_pass_rate(part_dir: Path, golden: Path | None) -> Reading:
    """Every corpus-side golden check this part carries, passed or not.

    Deliberately **not** the whole of `dsa verify`: the page-truth half needs
    the printed PDF, which is not part of a corpus, so it is excluded and named
    as excluded. What runs is the section half of each text question plus all
    seven query paths, which between them are what a consumer of the corpus can
    actually reach.
    """
    source = "tests/fixtures/golden_qa_<PART>.yaml + the corpus"
    derivation = "golden_corpus_checks"
    questions, reason = _golden_questions(golden)
    if questions is None:
        return Reading(reason=reason, source=source, derivation=derivation)

    from datasheet_analyzer.evalh.citations import (
        verify_ask_queries,
        verify_card_queries,
        verify_pin_queries,
        verify_plot_queries,
        verify_questions,
        verify_reg_queries,
        verify_search_queries,
        verify_spec_queries,
    )

    passed = 0
    total = 0
    failures: list[str] = []
    # The text half. `page_texts=[]` is what removes the page-truth check: with
    # no PDF, `page_truth` is False for every question by construction, so only
    # `corpus_contains` is read — and that is stated in the detail below rather
    # than left for a reader to infer from a suspiciously low number.
    for result in verify_questions(questions, part_dir, []):
        total += 1
        if result.corpus_contains:
            passed += 1
        else:
            failures.append(result.question.id)
    for verifier in (
        verify_spec_queries,
        verify_plot_queries,
        verify_pin_queries,
        verify_reg_queries,
        verify_card_queries,
        verify_ask_queries,
        verify_search_queries,
    ):
        for result in verifier(questions, part_dir):
            total += 1
            if result.ok:
                passed += 1
            else:
                failures.append(result.question.id)
    detail = (
        f"{len(questions)} question(s), {total} corpus-side check(s); the page-truth "
        f"half of `dsa verify` needs the printed PDF and is not run here"
    )
    if failures:
        shown = ", ".join(sorted(set(failures))[:4])
        detail += f"; failing: {shown}" + ("; …" if len(set(failures)) > 4 else "")
    return _ratio(
        passed,
        total,
        empty_reason="this part's golden benchmark holds no runnable check",
        source=source,
        derivation=derivation,
        detail=detail,
    )


def _alias_hit_rate(part_dir: Path, golden: Path | None) -> Reading:
    """Of the goldens asked in a designer's words, how many the lexicon resolved.

    The population is the `spec_query` entries keyed by `name` — a question that
    names a `symbol` already knows the answer's identity and tests nothing about
    `registry/aliases.yaml`. A part whose benchmark asks no such question has no
    alias hit rate, which is `n/a` rather than 0 %.
    """
    source = "tests/fixtures/golden_qa_<PART>.yaml + registry/aliases.yaml"
    derivation = "alias_rung_hits/name_lookups"
    questions, reason = _golden_questions(golden)
    if questions is None:
        return Reading(reason=reason, source=source, derivation=derivation)

    from datasheet_analyzer.retrieve import Retriever

    retriever = Retriever.for_part(part_dir)
    hits = 0
    asked = 0
    missed: list[str] = []
    for question in questions:
        query = question.spec_query or {}
        if not query.get("name"):
            continue
        asked += 1
        found = retriever.specs(**query)
        via = found[0].matched_via if found else ""
        if via.startswith(("alias:", "alias-prefix:")):
            hits += 1
        else:
            missed.append(f"{question.id} ({via or 'no match'})")
    detail = ""
    if missed:
        detail = "resolved off the lexicon: " + ", ".join(missed[:4])
        if len(missed) > 4:
            detail += "; …"
    return _ratio(
        hits,
        asked,
        empty_reason=(
            "this part's golden benchmark asks no spec question in a designer's "
            "words (`spec_query: {name: …}`), so nothing exercises the alias lexicon"
        ),
        source=source,
        derivation=derivation,
        detail=detail,
    )


# --- assembly ----------------------------------------------------------------


def _withdraw(metric: AuditMetric, why: str) -> AuditMetric:
    """Report a metric as `n/a` for a reason that is *not* a missing reading.

    A reading the rubric cannot grade — because the rubric carries no rule for
    the metric, or none for the state it read — is still a real measurement, so
    it is preserved in `detail` rather than discarded. What it may not do is
    keep occupying `value`: `available: false` promises a `null` reading, and a
    payload that says "not measured" while carrying a number is a contract a
    client cannot act on. Two facts, kept distinct.
    """
    if metric.available:
        measured = reading(metric)
        metric.detail = f"read {measured}; {metric.detail}" if metric.detail else f"read {measured}"
    metric.available = False
    metric.grade = None
    metric.value = None
    metric.state = ""
    metric.numerator = None
    metric.denominator = None
    metric.unavailable_reason = why
    return metric


def _grade(rubric: AuditRubric, key: str, raw: Reading) -> AuditMetric:
    """One reading plus the rubric's verdict on it, as a published metric."""
    rule = rubric.rule(key)
    label = rule.label if rule is not None else key
    kind = rule.kind if rule is not None else MetricKind.RATIO
    weight = rule.weight if rule is not None else 0.0
    metric = AuditMetric(
        key=key,
        label=label,
        kind=kind,
        weight=weight,
        value=raw.value,
        state=raw.state,
        numerator=raw.numerator,
        denominator=raw.denominator,
        detail=raw.detail,
        source=raw.source,
        derivation=raw.derivation,
        available=raw.available,
        unavailable_reason=raw.reason,
    )
    if rule is None:
        # The rubric grades no metric of this key — deleted from the YAML, or
        # never added. There is deliberately no default rule to fall back to,
        # so the metric reports `n/a` and keeps its reading in `detail`.
        return _withdraw(metric, raw.reason or NO_RULE.format(key=key))
    if not raw.available:
        return metric
    if kind is MetricKind.RATIO:
        metric.grade = rule.grade_ratio(raw.value if raw.value is not None else 0.0)
    else:
        metric.grade = rule.grade_named(raw.state)
    if metric.grade is None:
        # The rubric carries the metric but grades nothing it read — a `values`
        # map with no entry for this state, say. That is a gap in the data, and
        # it reports as `n/a` for the same reason a missing statistic does.
        return _withdraw(
            metric,
            f"the rubric grades no reading {raw.state or raw.value!r} for {key!r}",
        )
    return metric


def _headline(part: str, card: AuditScorecard) -> str:
    """The sentence the ticket exists to produce.

    Names the *worst graded* metric, because that is the one an agent has to
    qualify its answer with — and names the unavailable count when there is
    one, because a `B` earned on six of thirteen metrics is a different claim
    from a `B` earned on all thirteen.
    """
    if card.grade is None:
        why = card.notes[0] if card.notes else "too few metrics could be computed"
        return f"{part} is ungraded: {why}"
    graded = [m for m in card.metrics if m.grade is not None]
    worst = min(graded, key=lambda m: (grade_order(m.grade), -m.weight)) if graded else None
    sentence = f"This corpus grades {card.grade.value}"
    if worst is not None:
        sentence += f" — {worst.label} {reading(worst)}"
    sentence += "."
    if card.n_unavailable:
        sentence += (
            f" {card.n_unavailable} of {len(card.metrics)} metrics could not be "
            f"computed and are excluded, not scored."
        )
    return sentence


def build_scorecard(
    part_dir: Path | str,
    *,
    rubric: AuditRubric | None = None,
    golden: Path | None = None,
) -> AuditScorecard:
    """Grade one built corpus. An unbuilt one grades nothing and says so."""
    from datasheet_analyzer.retrieve import CorpusIndex

    part_dir = Path(part_dir)
    rubric = rubric if rubric is not None else load_audit_rubric()
    index = CorpusIndex.load(part_dir)
    part = index.part_number or part_dir.name
    staleness = index.staleness
    manifest = index.manifest

    card = AuditScorecard(
        schema_version=AUDIT_SCHEMA_VERSION,
        rubric_version=rubric.schema_version,
        part=part,
        unavailable_policy=rubric.unavailable_policy,
        staleness=staleness.state.value,
        banner=one_line(staleness),
    )
    if manifest is None:
        card.notes.append(
            f"{part} has no manifest.json — it is not built, so there is nothing to "
            f"grade: `dsa build <pdf> --part {part}`"
        )
        card.headline = f"{part} is ungraded: {card.notes[0]}"
        return card

    stats = manifest.stats
    readings: dict[str, Reading] = {
        "section_page_coverage": _section_page_coverage(manifest),
        "table_pin_rate": _table_pin_rate(manifest),
        "table_accept_rate": _table_accept_rate(manifest),
        "mean_fidelity": _mean_fidelity(manifest),
        "spec_page_rate": _spec_page_rate(index),
        "record_confidence": _record_confidence(manifest),
        "pins_present": _present(
            manifest, stats.n_pins, noun="pin record(s)",
            source="manifest.json#stats", derivation="n_pins>0",
        ),
        "registers_present": _present(
            manifest, stats.n_registers, noun="register record(s)",
            source="manifest.json#stats", derivation="n_registers>0",
        ),
        "cards_present": _present(
            manifest, stats.n_card_rows, noun="design-card row(s)",
            source="manifest.json#stats", derivation="n_card_rows>0",
        ),
        "axis_coverage": _axis_coverage(index),
        "alias_hit_rate": _alias_hit_rate(part_dir, golden),
        "revision_freshness": _revision_freshness(staleness),
        "golden_pass_rate": _golden_pass_rate(part_dir, golden),
    }
    card.metrics = [_grade(rubric, key, readings[key]) for key in METRIC_KEYS]
    graded = [(m.grade, m.weight) for m in card.metrics if m.grade is not None]
    card.n_graded = len(graded)
    card.n_unavailable = len(card.metrics) - len(graded)
    grade, score, reason = rubric.overall(graded)
    card.grade, card.score = grade, score
    if reason:
        card.notes.append(reason)
    card.notes.extend(_notes(manifest, card, staleness))
    card.headline = _headline(part, card)
    return card


def _notes(manifest: CorpusManifest, card: AuditScorecard, staleness) -> list[str]:
    """What this corpus needs doing to it, each note naming its command."""
    from datasheet_analyzer.config import CARD_VERSION, PIPELINE_VERSION
    from datasheet_analyzer.staleness import CHECK_COMMAND

    notes: list[str] = []
    part = card.part
    behind = [
        name
        for name, built, current in (
            ("pipeline", manifest.pipeline_version, PIPELINE_VERSION),
            ("derivation-rule", manifest.card_version, CARD_VERSION),
        )
        if built != current
    ]
    if behind:
        notes.append(
            f"this corpus was published at {' and '.join(behind)} version(s) "
            f"({manifest.pipeline_version or 'unrecorded'} / "
            f"{manifest.card_version or 'unrecorded'}) rather than "
            f"{PIPELINE_VERSION} / {CARD_VERSION}: it needs a rebuild "
            f"(`dsa build <pdf> --part {part}`) before several metrics can be "
            f"measured at all"
        )
    if staleness.state.value == "unknown":
        notes.append(f"revision never checked — run `{CHECK_COMMAND} --part {part}`")
    for warning in manifest.derived_warnings:
        notes.append(f"derived warning: {warning}")
    return notes
