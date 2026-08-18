"""Templating golden *candidates* from records the corpus already published.

Phase 7, ticket 06. Invariant 5 is the right objective function and it does not
survive sixty parts of hand-verification; this module removes the typing and
leaves the judgment where it belongs. It produces proposals — never benchmark
questions — and `evalh/confirm.py` is the only path by which one becomes a
question.

Two rules shape everything here.

**Invariant 8 applies, even though a candidate is not a corpus artifact.** A
candidate is derived: its question text is a format string over cells a record
already carries, and the record itself supplies the answer and the page. So
every candidate names its `source` (a `provenance.source_ref`), its `page`
(the page that record was printed on), its `verbatim` (the cells the answer was
taken from) and its `template` (the named rule). **No model call is anywhere in
this path.** A record that carries no page, or no printed answer, is not
templatable at all and is counted rather than filled in with a plausible guess.

**Stratification is the point, not the count.** Twenty questions off one
easy spec table technically satisfy `--n 20` and prove nothing: the benchmark
would confirm the extraction path that was already working. So candidates are
selected by round-robin over a composite stratum — `(artifact, backend,
confidence, section)` — which spreads the set across all three dimensions the
ticket names at once, and the resulting mix is published in the file's `strata`
block so a reviewer can see it without re-deriving it. The round-robin is also
why the file is written in selection order: consecutive candidates come from
different strata, so a degenerate set is visible on sight.

Nothing here filters candidates by whether they would *pass* `dsa verify`. That
would be fitting the proposals to the checker rather than to the document, and
it would hide exactly the rows a maintainer most needs to look at. A candidate
is a question about a printed page; the human answers it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.config import GOLDEN_CANDIDATE_SCHEMA_VERSION
from datasheet_analyzer.evalh.candidates import GoldenAssistError, candidate_key
from datasheet_analyzer.models import (
    Confidence,
    GoldenCandidate,
    GoldenCandidateSet,
    GoldenQuestion,
    PinRecord,
    PlotRecord,
    RegisterRecord,
    SpecRecord,
)
from datasheet_analyzer.provenance import (
    PINS_ARTIFACT,
    PLOTS_ARTIFACT,
    REGISTERS_ARTIFACT,
    SPECS_ARTIFACT,
    source_ref,
)

log = logging.getLogger(__name__)

#: How many candidates a run proposes when the caller names no number.
DEFAULT_N = 20

#: The named rules this module templates with — invariant 8's `derivation` for
#: a candidate. One rule per artifact: a second phrasing of the same record
#: would double the count without widening the coverage, which is the failure
#: mode the whole module is built against.
TEMPLATE_SPEC = "spec_row_value"
TEMPLATE_PIN = "pin_row_name"
TEMPLATE_REGISTER = "register_row_address"
TEMPLATE_PLOT = "plot_caption"
TEMPLATES: tuple[str, ...] = (
    TEMPLATE_SPEC,
    TEMPLATE_PIN,
    TEMPLATE_REGISTER,
    TEMPLATE_PLOT,
)

#: The artifacts a candidate may be templated from, in the order the pool is
#: walked. Fixed here rather than read off the filesystem so two machines
#: propose the same set.
ARTIFACT_ORDER: tuple[str, ...] = (
    SPECS_ARTIFACT,
    PINS_ARTIFACT,
    REGISTERS_ARTIFACT,
    PLOTS_ARTIFACT,
)

#: Confidence grades in the order they sort into strata keys. `unknown` last:
#: a corpus that predates grading should not lead the file.
_CONFIDENCE_ORDER: dict[str, int] = {
    Confidence.HIGH.value: 0,
    Confidence.MEDIUM.value: 1,
    Confidence.LOW.value: 2,
    Confidence.UNKNOWN.value: 3,
}

#: The dimensions the file reports its mix over.
STRATA_DIMENSIONS: tuple[str, ...] = ("artifact", "backend", "confidence", "section")

#: What the generator says when a corpus has no templatable record of a kind.
_EMPTY_POOL = "{artifact}: no record carries both a printed answer and a page"


@dataclass(frozen=True)
class _Proposal:
    """One templatable record, before stratified selection picks it or not."""

    candidate: GoldenCandidate
    stratum: tuple


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def _spec_answer(record: SpecRecord) -> tuple[str, str, str]:
    """`(qualifier, value cell, cell name)` for a spec row, or `("", "", "")`.

    The qualifier is the word the *printed column* justifies — a row that states
    a maximum is a question about a maximum — so the generated question can
    never claim a limit the table did not print. A cell with no digit in it is
    refused: `See Figure 7` and `—` are legitimate printed cells and legitimate
    non-answers, and a golden question whose expected substring is an em dash
    would pass against half the document.
    """
    for cell, qualifier in (
        (record.max, "maximum"),
        (record.min, "minimum"),
        (record.typ, "typical"),
        (record.value, ""),
    ):
        text = (cell or "").strip()
        if text and _has_digit(text):
            return qualifier, text, ""
    return "", "", ""


def _spec_candidate(record: SpecRecord, doc: str) -> tuple[GoldenQuestion, str, str] | None:
    """`(question, verbatim, answer)` for one spec row, or None when untemplatable."""
    identity = (record.name or record.symbol).strip()
    if not identity or record.page is None:
        return None
    qualifier, value, _ = _spec_answer(record)
    if not value:
        return None
    unit = (record.unit.verbatim or "").strip()
    expected = [identity, value]
    if unit:
        expected.append(unit)
    lead = f"the {qualifier} " if qualifier else "the "
    question = GoldenQuestion(
        id="",
        question=f"What is {lead}{identity}?",
        expected_substrings=expected,
        pages=[record.page],
        section=record.section,
        kind="direct",
        spec_query=(
            {"symbol": record.symbol} if record.symbol else {"name": record.name}
        ),
        notes=(
            f"generated from {SPECS_ARTIFACT} row {record.id} of {doc} "
            f"({record.section_title or 'untitled table'}); confirm against the printed page"
        ),
    )
    verbatim = " | ".join(record.row_verbatim) or f"{identity} {value} {unit}".strip()
    return question, verbatim, value


def _pin_candidate(record: PinRecord, doc: str) -> tuple[GoldenQuestion, str, str] | None:
    if not record.pin.strip() or not record.name.strip() or record.page is None:
        return None
    question = GoldenQuestion(
        id="",
        question=f"Which signal is on pin {record.pin}?",
        expected_substrings=[record.pin, record.name],
        pages=[record.page],
        section=record.section,
        kind="direct",
        pin_query={"pin": record.pin},
        notes=(
            f"generated from {PINS_ARTIFACT} row {record.id} of {doc}; "
            "confirm the designator and the printed name against the page"
        ),
    )
    verbatim = " | ".join(record.row_verbatim) or f"{record.pin} {record.name}"
    return question, verbatim, record.name


def _register_candidate(
    record: RegisterRecord, doc: str
) -> tuple[GoldenQuestion, str, str] | None:
    address = (record.address.verbatim or "").strip()
    if not record.name.strip() or not address or record.page is None:
        return None
    question = GoldenQuestion(
        id="",
        question=f"At what address is register {record.name}?",
        expected_substrings=[record.name, address],
        pages=[record.page],
        section=record.section,
        kind="direct",
        reg_query={"addr": address},
        notes=(
            f"generated from {REGISTERS_ARTIFACT} row {record.id} of {doc}; "
            "confirm the printed address against the page"
        ),
    )
    verbatim = " | ".join(record.row_verbatim) or f"{address} {record.name}"
    return question, verbatim, address


#: A caption that is only a figure label (`Figure 1.`) — nothing to ask about.
_BARE_FIGURE = re.compile(r"^figure\s+[\w.\-]+\.?$", re.IGNORECASE)


def _figure_subject(caption: str) -> str:
    """A caption with its printed `Figure N-M` prefix removed, when it has one.

    Verbatim in the sense that matters: nothing is added or reworded, only the
    numbering the question does not need is left off the *question text*. The
    caption itself still travels whole as the expected substring.
    """
    words = caption.split()
    if len(words) > 2 and words[0].lower().rstrip(".") == "figure":
        rest = " ".join(words[2:]).strip()
        if rest:
            return rest
    return caption


def _plot_candidate(
    record: PlotRecord, doc: str, part_dir: Path
) -> tuple[GoldenQuestion, str, str] | None:
    caption = record.caption.strip()
    if not caption or record.page_start is None or not record.file:
        return None
    if _BARE_FIGURE.match(caption):
        # `Figure 1.` names no subject, so there is nothing to ask about it and
        # nothing verbatim for an answer to contain. Refused rather than turned
        # into "Which figure shows Figure 1.?", which is a question about the
        # caption rather than about the device.
        return None
    if not (part_dir / record.file).exists():
        # A catalog entry with no pixels on disk is not an answer to "which
        # figure shows this" — the point of a plot question is the image.
        return None
    subject = _figure_subject(caption)
    expected = [caption]
    if record.conditions.strip():
        expected.append(record.conditions.strip())
    question = GoldenQuestion(
        id="",
        question=f"Which figure shows {subject}?",
        expected_substrings=expected,
        pages=[record.page_start],
        section=record.section,
        kind="plot",
        plot_query={"caption_contains": subject},
        notes=(
            f"generated from {PLOTS_ARTIFACT} entry {record.id} of {doc}; "
            "confirm the figure number and the page against the printed page"
        ),
    )
    verbatim = caption if not record.conditions.strip() else f"{caption} | {record.conditions}"
    return question, verbatim, caption


def _backend_of(manifest, doc_hash: str) -> str:
    """The extraction backend that produced one document; `""` when unrecorded.

    Unrecorded is left empty rather than defaulted to `pdf_layout`: a corpus
    published before extraction stats existed has no backend, and pretending it
    does would make the backend stratum a fiction.
    """
    if manifest is None or not doc_hash:
        return ""
    stats = (manifest.extraction_stats or {}).get(doc_hash)
    return stats.backend if stats else ""


def _mint_id(template: str, doc_hash: str, record_id: str) -> str:
    """The candidate's question id: `g-<doc8>-<record id>`.

    Prefixed `g-` so a generated question is legible as one in the merged
    benchmark, and scoped by the document hash because record ids are
    per document — a two-document part would otherwise mint `rec_1` twice.
    """
    del template  # one template per artifact, so the record id already decides
    return f"g-{(doc_hash or 'nodoc')[:8]}-{record_id}"


def _proposals(part_dir: Path, index) -> tuple[list[_Proposal], dict[str, int]]:
    """Every templatable record of the corpus, in document then record order."""
    proposals: list[_Proposal] = []
    pool: dict[str, int] = {artifact: 0 for artifact in ARTIFACT_ORDER}
    for doc in index.docs:
        backend = _backend_of(index.manifest, doc.doc_hash)
        builders = (
            (SPECS_ARTIFACT, TEMPLATE_SPEC, doc.specs, _spec_candidate),
            (PINS_ARTIFACT, TEMPLATE_PIN, doc.pins, _pin_candidate),
            (REGISTERS_ARTIFACT, TEMPLATE_REGISTER, doc.registers, _register_candidate),
            (PLOTS_ARTIFACT, TEMPLATE_PLOT, doc.plots, _plot_candidate),
        )
        for artifact, template, records, build in builders:
            for record in records:
                if not record.id:
                    # An unaddressable record cannot carry a `source`, so it
                    # cannot be a candidate: invariant 8 has no exception for
                    # a proposal.
                    continue
                built = (
                    build(record, doc.name, part_dir)
                    if artifact == PLOTS_ARTIFACT
                    else build(record, doc.name)
                )
                if built is None:
                    continue
                question, verbatim, _answer = built
                source = source_ref(record.id, artifact=artifact, doc=doc.name)
                page = (
                    record.page_start
                    if artifact == PLOTS_ARTIFACT
                    else record.page
                )
                confidence = record.confidence
                section = record.section
                title = getattr(record, "section_title", "")
                question.id = _mint_id(template, doc.doc_hash, record.id)
                candidate = GoldenCandidate(
                    question=question,
                    confirmed=False,
                    key=candidate_key(source, template),
                    template=template,
                    source=source,
                    page=page,
                    verbatim=verbatim,
                    artifact=artifact,
                    doc=doc.name,
                    backend=backend,
                    section=section,
                    section_title=title,
                    confidence=confidence,
                )
                pool[artifact] += 1
                proposals.append(
                    _Proposal(
                        candidate=candidate,
                        stratum=(
                            ARTIFACT_ORDER.index(artifact),
                            backend,
                            _CONFIDENCE_ORDER.get(confidence.value, 9),
                            _section_stratum(candidate),
                        ),
                    )
                )
    return proposals, pool


def _round_robin(sequences: list[list]) -> list:
    """One item from each sequence in turn, in the order the sequences are given.

    The whole stratification is this function applied at every level of the
    stratum tuple. Deterministic: no set iteration, no sorting by anything but
    the stratum key, and each sequence keeps the order the document printed its
    records in.
    """
    out: list = []
    index = 0
    while True:
        drawn = False
        for sequence in sequences:
            if index < len(sequence):
                out.append(sequence[index])
                drawn = True
        if not drawn:
            return out
        index += 1


def _stratified_order(proposals: list[_Proposal], depth: int = 0) -> list[_Proposal]:
    """Every templatable record, ordered so a prefix of it is a stratified set.

    A *flat* round-robin over the whole composite stratum would hand each
    dimension's stratum **count** the deciding vote, and the counts are wildly
    uneven: AD9081 prints its specs under twelve table titles and its 321 pins
    under none, so one flat pass draws twelve spec rows per pin row and a set of
    twenty holds a single pin. That benchmark barely exercises the pin path.

    So the round-robin is applied at each level of the stratum tuple in turn —
    artifact, then backend, then confidence grade, then section — with each
    group ordered by the same rule recursively. One spec row, one pin row, one
    register row, one figure; and *within* the spec rows, one `high`, one
    `medium`, one `low`, each from a different table. The property that falls
    out is the testable one, and it holds at every level: nothing is drawn twice
    until everything beside it has been drawn once.
    """
    if depth >= len(STRATA_DIMENSIONS) or len(proposals) <= 1:
        return list(proposals)
    groups: dict = {}
    for proposal in proposals:
        groups.setdefault(proposal.stratum[depth], []).append(proposal)
    return _round_robin(
        [_stratified_order(group, depth + 1) for _, group in sorted(groups.items())]
    )


def _select(proposals: list[_Proposal], n: int) -> list[GoldenCandidate]:
    """The first `n` of the stratified order — fewer when the pool is smaller."""
    return [p.candidate for p in _stratified_order(proposals)[:n]]


def _section_stratum(candidate: GoldenCandidate) -> str:
    """Which "section" a candidate counts toward, on documents that number none.

    ADR 0004's captionless era prints no section number at all — every AD9081
    record honestly carries `section: ""` — so numbering alone would collapse a
    whole datasheet into one stratum and the generator would spread across
    nothing. The printed **table title** is the identity a derived artifact may
    select a table by there (phase 6, ticket 07), so it stands in, and only when
    neither exists is the stratum explicitly unnumbered. The candidate's own
    `section` field is untouched: it stays the number the page printed, which
    is `""` when the page printed none.
    """
    return candidate.section or candidate.section_title or "(unnumbered)"


def strata_of(candidates: list[GoldenCandidate]) -> dict[str, dict[str, int]]:
    """The selected set's mix, one mapping per dimension the ticket names.

    An empty value is reported under its own explicit label rather than as `""`
    — "the captionless era prints no section number" is a reading of the
    document, and a blank key in a report reads as a bug.
    """
    labels = {
        "artifact": lambda c: c.artifact,
        "backend": lambda c: c.backend or "(unrecorded)",
        "confidence": lambda c: c.confidence.value,
        "section": _section_stratum,
    }
    out: dict[str, dict[str, int]] = {}
    for dimension in STRATA_DIMENSIONS:
        counts: dict[str, int] = {}
        for candidate in candidates:
            key = labels[dimension](candidate)
            counts[key] = counts.get(key, 0) + 1
        out[dimension] = {key: counts[key] for key in sorted(counts)}
    return out


def suggest_candidates(
    part_dir: Path,
    *,
    n: int = DEFAULT_N,
    rejected: set[str] | None = None,
    existing_ids: set[str] | None = None,
) -> GoldenCandidateSet:
    """Template up to `n` stratified candidates from a built corpus.

    `rejected` is the rejection ledger's key set and `existing_ids` the golden
    file's question ids. Both are *exclusions counted rather than applied
    silently*: a run that proposed nothing because everything was already
    rejected must say so, or it reads as a corpus with no records.

    Raises `GoldenAssistError` for a part with no built corpus — the ticket's
    own criterion, and the only honest outcome: a question generated from no
    records would carry an answer nothing printed.
    """
    from datasheet_analyzer.retrieve import CorpusIndex

    part_dir = Path(part_dir)
    if not (part_dir / "manifest.json").exists():
        raise GoldenAssistError(
            f"no corpus at {part_dir} — build it first: "
            f"`dsa build <pdf> --part {part_dir.name}`. Candidates are templated "
            "from published records, so a part with no corpus has no answers to "
            "template from."
        )
    index = CorpusIndex.load(part_dir)
    part = index.part_number or part_dir.name
    if n < 1:
        raise GoldenAssistError(f"--n must be at least 1, got {n}")

    rejected = rejected or set()
    existing_ids = existing_ids or set()
    proposals, pool = _proposals(part_dir, index)

    kept: list[_Proposal] = []
    skipped_rejected = 0
    skipped_existing = 0
    for proposal in proposals:
        if proposal.candidate.key in rejected:
            skipped_rejected += 1
            continue
        if proposal.candidate.question.id in existing_ids:
            skipped_existing += 1
            continue
        kept.append(proposal)

    selected = _select(kept, n)

    notes: list[str] = []
    for artifact in ARTIFACT_ORDER:
        if not pool.get(artifact):
            notes.append(_EMPTY_POOL.format(artifact=artifact))
    if len(selected) < n:
        notes.append(
            f"{len(selected)} candidate(s) proposed of the {n} asked for: "
            f"{len(kept)} templatable record(s) remained after exclusions "
            f"({skipped_rejected} previously rejected, "
            f"{skipped_existing} already in the golden set)."
        )
    if not selected:
        notes.append(
            "nothing to confirm — every templatable record is either already a "
            "golden question or has been rejected by hand."
        )

    return GoldenCandidateSet(
        schema_version=GOLDEN_CANDIDATE_SCHEMA_VERSION,
        part=part,
        candidates=selected,
        strata=strata_of(selected),
        pool=pool,
        skipped_rejected=skipped_rejected,
        skipped_existing=skipped_existing,
        notes=notes,
    )


def render_suggestion_report(candidates: GoldenCandidateSet, path: Path) -> str:
    """What `dsa golden suggest` prints: the mix, then where the file went."""
    lines = [
        f"# Golden candidates - {candidates.part}",
        "",
        (
            f"**{len(candidates.candidates)} candidate(s)**, none confirmed. "
            "They are proposals: nothing here counts toward `dsa verify` until "
            "`dsa golden confirm` merges it by hand."
        ),
        "",
        "| Dimension | Mix |",
        "|---|---|",
    ]
    for dimension in STRATA_DIMENSIONS:
        counts = candidates.strata.get(dimension) or {}
        mix = ", ".join(f"{key} {value}" for key, value in counts.items()) or "-"
        lines.append(f"| {dimension} | {mix} |")
    lines += [
        "",
        "| # | Id | Question | Page | Grade | Source |",
        "|---|---|---|---|---|---|",
    ]
    for i, candidate in enumerate(candidates.candidates, 1):
        page = f"p.{candidate.page}" if candidate.page is not None else "-"
        lines.append(
            f"| {i} | {candidate.question.id} | {candidate.question.question} | "
            f"{page} | {candidate.confidence.value} | {candidate.source} |"
        )
    pool = ", ".join(f"{key} {value}" for key, value in candidates.pool.items())
    lines += ["", f"Templatable records by artifact: {pool}."]
    if candidates.skipped_rejected or candidates.skipped_existing:
        lines.append(
            f"Excluded: {candidates.skipped_rejected} previously rejected, "
            f"{candidates.skipped_existing} already in the golden set."
        )
    for note in candidates.notes:
        lines.append(f"- {note}")
    lines += ["", f"Written to {path}", ""]
    return "\n".join(lines)
