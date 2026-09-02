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

- **the corpus predates the field.** A corpus published at an older
  `pipeline_version` may predate the derived artifacts entirely. It needs a
  rebuild, and the scorecard says so in `notes` rather than grading the part
  down for a statistic nobody recorded.
- **the backend does not compute it.** Only `pdf_layout` runs a table
  reconstruction gate, so an HTML-backed document has no accept rate and no
  fidelity. `n/a`, not 0 %.
- **the document does not have it.** A datasheet that prints no figures has no
  axis coverage; a part with no golden benchmark has no pass rate; a part that
  registers no errata document has no link rate. `n/a` again.

What is *not* `n/a` is a **missing artifact**: a modern corpus that publishes no
pins, no registers or no card rows is graded down (the rubric decides how far),
because that is a fact about this corpus that changes what an agent can answer.

One metric is deliberately narrower than its `dsa verify` namesake and says so.
`golden_pass_rate` runs every corpus-side check `dsa verify` runs - the section
half of each text question and every query path this branch carries - but
**not** the page-truth half, which needs the printed PDF and therefore a file
that is not part of the corpus. The derivation names it
(`golden_corpus_checks`) and the metric's `detail` states it, so nobody reads
this number as the benchmark's.

**Two deliberate differences from the lineage this was ported from.**

- There is no `table_pin_rate` metric here. It divides `tables_pinned` by
  `n_tables`, and this branch's publisher records no pinning count on
  `CorpusStats` - a table's printed page is stamped on the `TableBlock` at
  construction and never carried into the manifest. Reading that absence as
  "0 tables pinned" is exactly the defamation the `n/a` rule forbids, and
  recording the count would mean rebuilding every corpus in the repository.
  So the metric is absent rather than permanently `n/a`: a scorecard row that
  can never say anything is noise, and the rubric grades what this branch's
  corpora actually publish.
- There **is** an `errata_link_rate` metric, which that lineage had no errata
  linker to compute. A part with known issues nobody could place against a
  record is a part an agent will answer from while silently missing them, and
  that is precisely the kind of fact this scorecard exists to put in front of
  an answer. `ErrataTarget` is not a `DerivedValue`, so `check_provenance`
  does not walk `errata_links.json` - but the audit does not walk it either.
  It reads two published counts, and it carries its own `source` and
  `derivation` like every other metric here.
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
    "table_accept_rate",
    "mean_fidelity",
    "spec_page_rate",
    "record_confidence",
    "pins_present",
    "registers_present",
    "cards_present",
    "axis_coverage",
    "errata_link_rate",
    "alias_hit_rate",
    "revision_freshness",
    "golden_pass_rate",
)

#: The backend that runs a table reconstruction gate, and therefore the only
#: one that records an accept rate and a fidelity score. Named once so the two
#: metrics that depend on it cannot state different backend facts.
GATED_BACKEND = "pdf_layout"

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
    """`numerator / denominator`, or the reason when there is nothing to divide."""
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


def _gated_docs(manifest: CorpusManifest) -> list:
    """Every document whose backend runs the table reconstruction gate.

    Selected by the recorded backend rather than by whether a number came out
    non-zero, which is the whole of one fix carried into this port: a document
    that really did score 0.0 has a *reading*, and calling that "never
    computed" is the inverse of the `n/a`-vs-zero rule this module keeps.
    """
    return [st for st in manifest.extraction_stats.values() if st.backend == GATED_BACKEND]


def _table_accept_rate(manifest: CorpusManifest) -> Reading:
    gated = _gated_docs(manifest)
    if not gated:
        return Reading(
            reason=(
                f"no document of this corpus was extracted by `{GATED_BACKEND}`, "
                "the only backend that detects and rejects tables"
            ),
            source="manifest.json#extraction_stats",
            derivation="tables_accepted/tables_detected",
        )
    detected = sum(st.tables_detected for st in gated)
    accepted = sum(st.tables_accepted for st in gated)
    reasons = [r for st in gated for r in st.rejection_reasons]
    detail = ""
    if reasons:
        shown = "; ".join(reasons[:3])
        detail = f"rejection reasons: {shown}" + ("; ..." if len(reasons) > 3 else "")
    return _ratio(
        accepted,
        detected,
        empty_reason="this corpus detected no table to accept or reject",
        source="manifest.json#extraction_stats",
        derivation="tables_accepted/tables_detected",
        detail=detail,
    )


def _mean_fidelity(manifest: CorpusManifest) -> Reading:
    """Mean self-verification score over the documents that computed one.

    Availability is decided by the recorded backend and by whether that backend
    accepted a table to score - never by the score itself. A corpus whose
    accepted tables really do reconstruct at 0.0 fidelity reads `0 %` and
    grades `F`, which is the finding; reporting it as "no document records a
    fidelity score" would hide the worst corpus behind the sentence written for
    a backend that computes no fidelity at all.
    """
    gated = _gated_docs(manifest)
    if not gated:
        return Reading(
            reason=(
                f"no document of this corpus was extracted by `{GATED_BACKEND}`, "
                "the only backend that computes a table fidelity score"
            ),
            source="manifest.json#extraction_stats",
            derivation="mean(mean_fidelity)",
        )
    scored = [st for st in gated if st.tables_accepted > 0]
    if not scored:
        return Reading(
            reason=(
                "this corpus accepted no table, so there is nothing whose "
                "reconstruction could be scored"
            ),
            source="manifest.json#extraction_stats",
            derivation="mean(mean_fidelity)",
        )
    return Reading(
        value=sum(st.mean_fidelity for st in scored) / len(scored),
        detail=f"over {len(scored)} document(s) that accepted at least one table",
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


def _confidence_mix(records) -> dict[str, int]:
    """`{grade: count}` over any records that carry a `confidence`."""
    mix: dict[str, int] = {}
    for record in records:
        grade = getattr(record, "confidence", None)
        if grade is None:
            continue
        key = getattr(grade, "value", str(grade))
        mix[key] = mix.get(key, 0) + 1
    return mix


def _record_confidence(manifest: CorpusManifest, derived: _Derived, index) -> Reading:
    """Share of graded records carrying `high`, over every record kind.

    `unknown` is excluded from the denominator rather than counted as a bad
    grade: it means the record predates grading, which is a fact about the
    corpus's age and is reported as a rebuild note, not as low confidence.

    Specs and plots are read off the manifest's recorded mix; pins and
    registers off the published records themselves, because this branch's
    `CorpusStats` carries no mix for them. Both are counts of what is on disk.
    """
    stats = manifest.stats
    mixes = {
        "specs": dict(stats.spec_confidence),
        "plots": dict(stats.plot_confidence),
        "pins": _confidence_mix(derived.pins),
        "registers": _confidence_mix(derived.registers),
    }
    if not mixes["specs"]:
        mixes["specs"] = _confidence_mix([rec for doc in index.docs for rec in doc.specs])
    if not mixes["plots"]:
        mixes["plots"] = _confidence_mix([rec for doc in index.docs for rec in doc.plots])
    counts: dict[str, int] = {}
    for mix in mixes.values():
        for grade, n in mix.items():
            counts[grade] = counts.get(grade, 0) + int(n)
    graded = sum(
        counts.get(g.value, 0) for g in (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW)
    )
    if graded <= 0:
        return Reading(
            reason=(
                "this corpus grades no record (it publishes none, or it predates "
                f"per-record confidence) - {REBUILD}"
            ),
            source="manifest.json#stats + docs/*/pins.json + docs/*/registers.json",
            derivation="high/(high+medium+low)",
        )
    detail = "; ".join(
        f"{label} " + " / ".join(f"{n} {grade}" for grade, n in sorted(mix.items()))
        for label, mix in mixes.items()
        if mix
    )
    return Reading(
        value=counts.get(Confidence.HIGH.value, 0) / graded,
        numerator=counts.get(Confidence.HIGH.value, 0),
        denominator=graded,
        detail=detail,
        source="manifest.json#stats + docs/*/pins.json + docs/*/registers.json",
        derivation="high/(high+medium+low)",
    )


def _derived_artifacts_readable(manifest: CorpusManifest) -> str:
    """`""` when the derived counts mean anything, else the reason.

    `pipeline_version` is this branch's discriminator. It is stamped by every
    publish, and it is what separates "this corpus predates pins, registers and
    cards" from "this datasheet prints none of them" - and grading the first as
    if it were the second is precisely the "scored as zero" failure this ticket
    forbids. (The lineage this was ported from used
    `CorpusManifest.card_version`; there is no such field here, because on this
    branch a card carries its own version per card.)
    """
    from datasheet_analyzer.config import PIPELINE_VERSION

    if manifest.pipeline_version == PIPELINE_VERSION:
        return ""
    return (
        f"this corpus was published at pipeline "
        f"{manifest.pipeline_version or '(unrecorded)'} rather than "
        f"{PIPELINE_VERSION}, so it may predate the derived artifacts entirely "
        f"and an absent one is not a finding - {REBUILD}"
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

    A plot whose `axis_confidence` is `UNKNOWN` was never read - the corpus
    predates the catalog, or the document had no page geometry - so it is not
    in the denominator. A plot graded `LOW` **is**: that reading was attempted
    and the axes could not be read, which is a finding about the figure.
    """
    plots = [p for doc in index.docs for p in doc.plots]
    attempted = [p for p in plots if p.axis_confidence is not Confidence.UNKNOWN]
    if not attempted:
        reason = (
            "this corpus publishes no figures"
            if not plots
            else f"no figure of this corpus carries an axis reading - {REBUILD}"
        )
        return Reading(
            reason=reason,
            source="docs/*/plots.json",
            derivation="axis_high/axis_attempted",
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


def _errata_link_rate(index) -> Reading:
    """Of this part's published errata items, how many name a record.

    A part that registers **no** errata document reports `n/a`, and that
    distinction is the point: silence is not "no known issues". A part that
    publishes items none of which could be placed reads `0 %` and grades down,
    because an agent answering from that corpus will miss every one of them
    without ever being told.
    """
    source = "errata_links.json"
    derivation = "errata_linked/errata_items"
    links = index.errata
    if links is None:
        return Reading(
            reason=(
                "this part registers no errata document, so nothing is known to "
                "be wrong with it - which is silence, not a clean bill of health"
            ),
            source=source,
            derivation=derivation,
        )
    detail = f"{len(links.unlinked)} item(s) named no record this corpus publishes"
    return _ratio(
        len(links.links),
        links.n_items,
        empty_reason="this part's errata document publishes no item",
        source=source,
        derivation=derivation,
        detail=detail,
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
            f"this part has no golden benchmark ({path.name} is missing) - write one, "
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
    as excluded. What runs is the section half of each text question plus every
    query path this branch verifies, which between them are what a consumer of
    the corpus can actually reach.
    """
    source = "tests/fixtures/golden_qa_<PART>.yaml + the corpus"
    derivation = "golden_corpus_checks"
    questions, reason = _golden_questions(golden)
    if questions is None:
        return Reading(reason=reason, source=source, derivation=derivation)

    from datasheet_analyzer.evalh.citations import (
        load_card_golden,
        verify_ask_queries,
        verify_card_queries,
        verify_plot_queries,
        verify_questions,
        verify_search_queries,
        verify_spec_queries,
    )

    passed = 0
    total = 0
    failures: list[str] = []
    # The text half. `page_texts=[]` is what removes the page-truth check: with
    # no PDF, `page_truth` is False for every question by construction, so only
    # `corpus_contains` is read - and that is stated in the detail below rather
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
        verify_ask_queries,
        verify_search_queries,
    ):
        for result in verifier(questions, part_dir):
            total += 1
            if result.ok:
                passed += 1
            else:
                failures.append(result.question.id)
    # Card goldens live in the same file under their own `cards:` key, and
    # `dsa verify` does not run them today. They are corpus-side checks of a
    # published artifact, so the audit does: a scorecard that skipped the
    # derived half would over-report a corpus whose cards answer nothing.
    card_questions = load_card_golden(Path(golden))
    for result in verify_card_queries(card_questions, part_dir):
        total += 1
        if result.ok:
            passed += 1
        else:
            failures.append(result.question.id)
    detail = (
        f"{len(questions)} question(s) + {len(card_questions)} card question(s), "
        f"{total} corpus-side check(s); the page-truth half of `dsa verify` needs "
        f"the printed PDF and is not run here"
    )
    if failures:
        shown = ", ".join(sorted(set(failures))[:4])
        detail += f"; failing: {shown}" + ("; ..." if len(set(failures)) > 4 else "")
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

    The population is the `spec_query` entries keyed by `name` - a question that
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
            detail += "; ..."
    return _ratio(
        hits,
        asked,
        empty_reason=(
            "this part's golden benchmark asks no spec question in a designer's "
            "words (a `spec_query` keyed by name), so nothing exercises the "
            "alias lexicon"
        ),
        source=source,
        derivation=derivation,
        detail=detail,
    )


# --- the derived artifacts, read once ----------------------------------------


@dataclass(frozen=True)
class _Derived:
    """This branch's derived artifacts, loaded once for the whole scorecard.

    They are not on `CorpusStats` here - there is no `n_pins`, `n_registers` or
    `n_card_rows` - so the counts are read off the published files themselves.
    That is strictly better evidence than a manifest number would be: it is
    what a consumer of the corpus would find.
    """

    pins: tuple = ()
    registers: tuple = ()
    card_rows: int = 0
    n_cards: int = 0
    warnings: tuple[str, ...] = ()


def _load_derived(part_dir: Path) -> _Derived:
    from datasheet_analyzer.derive.cards import CARDS_DIRNAME
    from datasheet_analyzer.derive.pins import load_part_pins
    from datasheet_analyzer.derive.registers import load_part_registers
    from datasheet_analyzer.models import Card

    pins = load_part_pins(part_dir)
    registers = load_part_registers(part_dir)
    rows = 0
    n_cards = 0
    card_warnings: list[str] = []
    for path in sorted((part_dir / CARDS_DIRNAME).glob("*.json")):
        try:
            card = Card.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            card_warnings.append(f"unreadable card {path.name}: {exc}")
            continue
        n_cards += 1
        rows += len(card.rows)
        card_warnings.extend(f"{card.card} card: {w}" for w in card.warnings)
    return _Derived(
        pins=pins.pins,
        registers=registers.registers,
        card_rows=rows,
        n_cards=n_cards,
        warnings=tuple(
            [f"pins: {w}" for w in pins.warnings]
            + [f"registers: {w}" for w in registers.warnings]
            + card_warnings
        ),
    )


# --- assembly ----------------------------------------------------------------


def _withdraw(metric: AuditMetric, why: str) -> AuditMetric:
    """Report a metric as `n/a` for a reason that is *not* a missing reading.

    A reading the rubric cannot grade - because the rubric carries no rule for
    the metric, or none for the state it read - is still a real measurement, so
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
        # The rubric grades no metric of this key - deleted from the YAML, or
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
        # The rubric carries the metric but grades nothing it read - a `values`
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
    qualify its answer with - and names the unavailable count when there is
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
        sentence += f" - {worst.label} {reading(worst)}"
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
            f"{part} has no manifest.json - it is not built, so there is nothing to "
            f"grade: `dsa build <pdf> --part {part}`"
        )
        card.headline = f"{part} is ungraded: {card.notes[0]}"
        return card

    derived = _load_derived(part_dir)
    readings: dict[str, Reading] = {
        "section_page_coverage": _section_page_coverage(manifest),
        "table_accept_rate": _table_accept_rate(manifest),
        "mean_fidelity": _mean_fidelity(manifest),
        "spec_page_rate": _spec_page_rate(index),
        "record_confidence": _record_confidence(manifest, derived, index),
        "pins_present": _present(
            manifest,
            len(derived.pins),
            noun="pin record(s)",
            source="docs/*/pins.json",
            derivation="n_pins>0",
        ),
        "registers_present": _present(
            manifest,
            len(derived.registers),
            noun="register record(s)",
            source="docs/*/registers.json",
            derivation="n_registers>0",
        ),
        "cards_present": _present(
            manifest,
            derived.card_rows,
            noun=f"design-card row(s) over {derived.n_cards} card(s)",
            source="cards/*.json",
            derivation="n_card_rows>0",
        ),
        "axis_coverage": _axis_coverage(index),
        "errata_link_rate": _errata_link_rate(index),
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
    card.notes.extend(_notes(manifest, card, staleness, derived, index))
    card.headline = _headline(part, card)
    return card


def _notes(
    manifest: CorpusManifest,
    card: AuditScorecard,
    staleness,
    derived: _Derived,
    index,
) -> list[str]:
    """What this corpus needs doing to it, each note naming its command."""
    from datasheet_analyzer.config import PIPELINE_VERSION
    from datasheet_analyzer.staleness import CHECK_COMMAND

    notes: list[str] = []
    part = card.part
    if manifest.pipeline_version != PIPELINE_VERSION:
        notes.append(
            f"this corpus was published at pipeline version "
            f"{manifest.pipeline_version or 'unrecorded'} rather than "
            f"{PIPELINE_VERSION}: it needs a rebuild "
            f"(`dsa build <pdf> --part {part}`) before several metrics can be "
            f"measured at all"
        )
    if staleness.state.value == "unknown":
        notes.append(f"revision never checked - run `{CHECK_COMMAND} --part {part}`")
    if index.errata is not None and index.errata.unlinked:
        notes.append(
            f"{len(index.errata.unlinked)} errata item(s) name no record this corpus "
            f"publishes - an answer from it will not carry them"
        )
    # This branch keeps a derived artifact's warnings on the artifact rather
    # than on the manifest, so they are gathered from the artifacts themselves.
    notes.extend(f"derived warning: {warning}" for warning in derived.warnings)
    return notes
