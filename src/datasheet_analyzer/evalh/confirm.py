"""Turning candidates into benchmark questions - the human decision, as code.

Phase 7, ticket 06, and the half of it invariant 5 actually rests on. Nothing
here generates a question; everything here *applies a decision* a person made
about one. The split is deliberate and load-bearing:

- `apply_decisions` is a **pure core**: a candidate set plus a list of
  accept / edit / reject decisions in, an outcome out. It touches no terminal
  and no file, which is why it can be tested directly and why the same code
  path drives a scripted twenty-part fleet run (`--decisions <file>` /
  `--accept-ids`) as drives one person at a prompt.
- `run_interactive` is a **thin shell** over it: it prints a candidate beside
  the printed page text and reads one keystroke per candidate. Its input and
  output are injected, so even the shell is testable without a TTY.
- `merge_into_golden` is the write, and it **appends**. The golden files are
  hand-written and their comments are documentation; a merge that re-dumped the
  YAML would reformat a reviewer's file to land two questions.

Two defects in the lineage this was ported from are fixed here rather than
reproduced, and both are about the file this command writes being the
repository's own objective function.

**The merge is validated before it is written, not after.** The original wrote
the merged text and *then* re-parsed it to decide whether to roll back - so a
merge producing unparsable YAML raised inside `yaml.safe_load` before the
rollback guard was ever reached, and left the golden file corrupted on disk.
Here the candidate text is parsed and compared **in memory**; the file is
touched only once everything has already been checked, and a post-write
re-read is kept as a second line of defence with its own rollback.

**A newly created golden file states how it was confirmed, truthfully.** The
original stamped "Every answer below was checked against the printed page
before it landed here" unconditionally - including on a bulk `--accept-ids`
run where no page was ever displayed, which is a forged provenance claim in the
one file invariant 5 rests on. `merge_into_golden` now takes the provenance of
the decisions and writes *that*; the default is the bulk sentence, because the
safe default for a claim about human verification is the one that does not make
it.

The page text is the other half of "confirmation is a glance". `page_context`
prefers the **printed PDF page**, because that is the ground truth
`dsa verify`'s page-truth check reads; when no PDF is supplied it falls back to
the corpus section covering the page and says so in as many words, because a
corpus that agrees with itself proves nothing about a page citation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from datasheet_analyzer.evalh.candidates import (
    GoldenAssistError,
    candidate_by_id,
    dump_yaml,
    existing_question_ids,
    question_to_dict,
)
from datasheet_analyzer.models import (
    GoldenCandidate,
    GoldenCandidateSet,
    GoldenQuestion,
    GoldenRejection,
)

log = logging.getLogger(__name__)

ACCEPT = "accept"
EDIT = "edit"
REJECT = "reject"
ACTIONS: tuple[str, ...] = (ACCEPT, EDIT, REJECT)

#: The golden-question fields a decision may edit. Deliberately short: a
#: reviewer fixes the wording, the substrings or the page - the three things
#: reading the printed page tells you. Everything else (the path marker, the
#: notes) belongs to the record the candidate was templated from, and editing
#: it by hand in a decisions file would decouple the question from its
#: provenance.
EDITABLE: tuple[str, ...] = ("question", "expected_substrings", "pages")

#: How much page text `page_context` shows around the answer.
DEFAULT_WINDOW = 900

#: How a set of decisions was arrived at, in the words the golden file records.
#: These are provenance claims about *human verification*, so there is one for
#: each thing that can actually have happened and no default that flatters.
PROVENANCE_PAGE = (
    "walked by hand with `dsa golden confirm --pdf`; every question below was "
    "shown beside the printed PDF page it cites before it was accepted"
)
PROVENANCE_CORPUS = (
    "walked by hand with `dsa golden confirm`, but with NO --pdf: each question "
    "was shown beside the corpus's own section text, which cannot confirm a "
    "page citation. Open the printed page before trusting the pages below"
)
PROVENANCE_BULK = (
    "accepted in a bulk `dsa golden confirm --accept-ids/--decisions` run. NO "
    "page was displayed, so nothing below has been checked against the printed "
    "page. Treat these as unverified until someone opens the pages"
)

#: What the merge writes above the questions it appends, so a later reader can
#: tell a confirmed-generated question from a hand-written one - and can tell
#: how it was confirmed.
MERGE_HEADER = "# --- confirmed from generated candidates (`dsa golden confirm`) ---"


@dataclass(frozen=True)
class Decision:
    """One human decision about one candidate.

    `id` is the candidate's question id. `edits` is only read for `EDIT`, and
    an `EDIT` with no edits is an error rather than an accept: "I meant to
    change something" is not a decision the tooling may guess at.
    """

    id: str
    action: str
    reason: str = ""
    edits: dict = field(default_factory=dict)


@dataclass
class ConfirmOutcome:
    """What a set of decisions did, before anything is written.

    `deferred` is the candidates nobody decided on - a legitimate outcome of a
    session that was interrupted, and the reason the candidate file is
    rewritten with them rather than deleted.
    """

    accepted: list[GoldenQuestion] = field(default_factory=list)
    rejected: list[GoldenRejection] = field(default_factory=list)
    deferred: list[GoldenCandidate] = field(default_factory=list)
    edited_ids: list[str] = field(default_factory=list)


@dataclass
class MergeResult:
    """What `merge_into_golden` wrote."""

    path: Path
    added: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    created: bool = False
    provenance: str = ""


def load_decisions(path: Path) -> list[Decision]:
    """Read a decisions file - the non-interactive entry point to the core.

    ```yaml
    decisions:
      - {id: g-a1b2c3d4-rec_1, action: accept}
      - {id: g-a1b2c3d4-pin_3, action: edit, pages: [7]}
      - {id: g-a1b2c3d4-reg_2, action: reject, reason: the address is a range}
    ```

    Anything the file gets wrong is refused rather than interpreted: an unknown
    action, a row with no id, a file with no `decisions:` key. A decisions file
    is a record of human judgment, and guessing at one would forge it.
    """
    path = Path(path)
    if not path.exists():
        raise GoldenAssistError(f"no decisions file at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        raise GoldenAssistError(
            f"{path} is not a decisions file (expected a top-level `decisions:` list)"
        )
    decisions: list[Decision] = []
    for row in data["decisions"]:
        if not isinstance(row, dict):
            raise GoldenAssistError(f"{path}: every decision must be a mapping, got {row!r}")
        question_id = str(row.get("id") or "").strip()
        action = str(row.get("action") or "").strip().lower()
        if not question_id:
            raise GoldenAssistError(f"{path}: a decision has no `id`")
        if action not in ACTIONS:
            raise GoldenAssistError(
                f"{path}: decision {question_id} has action {action!r}; "
                f"expected one of {', '.join(ACTIONS)}"
            )
        edits = {name: row[name] for name in EDITABLE if name in row}
        decisions.append(
            Decision(
                id=question_id,
                action=action,
                reason=str(row.get("reason") or ""),
                edits=edits,
            )
        )
    return decisions


def decisions_from_ids(
    accept_ids: list[str] | None = None,
    reject_ids: list[str] | None = None,
    *,
    reason: str = "",
) -> list[Decision]:
    """`--accept-ids` / `--reject-ids` as decisions - the scriptable shorthand."""
    out = [Decision(id=i, action=ACCEPT) for i in (accept_ids or []) if i]
    out += [Decision(id=i, action=REJECT, reason=reason) for i in (reject_ids or []) if i]
    return out


def _edited(question: GoldenQuestion, edits: dict) -> GoldenQuestion:
    """`question` with the reviewer's edits applied, validated as a question."""
    payload = question.model_dump(mode="json")
    for name, value in edits.items():
        if name not in EDITABLE:
            raise GoldenAssistError(
                f"{question.id}: {name!r} is not editable here (editable: {', '.join(EDITABLE)})"
            )
        payload[name] = value
    return GoldenQuestion.model_validate(payload)


def apply_decisions(candidates: GoldenCandidateSet, decisions: list[Decision]) -> ConfirmOutcome:
    """The pure core: decisions in, an outcome out. Nothing is read or written.

    Every decision must name a candidate that is in the set, and no candidate
    may be decided on twice - both are refused rather than resolved, because a
    decisions file that names a candidate the generator no longer proposes is
    stale, and applying the half of it that still matches would confirm
    questions the reviewer never saw.
    """
    seen: set[str] = set()
    outcome = ConfirmOutcome()
    decided: dict[str, Decision] = {}
    for decision in decisions:
        if decision.id in seen:
            raise GoldenAssistError(f"candidate {decision.id} is decided twice in one run")
        seen.add(decision.id)
        candidate = candidate_by_id(candidates, decision.id)
        if candidate is None:
            raise GoldenAssistError(
                f"no candidate {decision.id} in this set "
                f"({len(candidates.candidates)} candidate(s) available) - "
                "regenerate with `dsa golden suggest` or fix the decisions file"
            )
        decided[decision.id] = decision

    for candidate in candidates.candidates:
        decision = decided.get(candidate.question.id)
        if decision is None:
            outcome.deferred.append(candidate)
            continue
        if decision.action == REJECT:
            outcome.rejected.append(
                GoldenRejection(
                    key=candidate.key,
                    id=candidate.question.id,
                    question=candidate.question.question,
                    reason=decision.reason,
                )
            )
            continue
        question = candidate.question
        if decision.action == EDIT:
            if not decision.edits:
                raise GoldenAssistError(
                    f"candidate {candidate.question.id}: an `edit` decision with "
                    "no edits - accept it or say what changes"
                )
            question = _edited(question, decision.edits)
            outcome.edited_ids.append(question.id)
        outcome.accepted.append(question)
    return outcome


def _list_indent(text: str) -> str:
    """The indentation the file's `questions:` sequence already uses.

    Read off the first item rather than assumed, because both shapes are valid
    YAML and the repo's hand-written sets use two spaces while a machine dump
    uses none. `""` when the file declares an empty list - nothing to match.
    """
    seen_key = False
    for line in text.splitlines():
        if not seen_key:
            if line.rstrip().startswith("questions:"):
                seen_key = True
            continue
        stripped = line.lstrip(" ")
        if stripped.startswith("- "):
            return " " * (len(line) - len(stripped))
        if stripped and not stripped.startswith("#"):
            break
    return ""


def _reindent(block: str, indent: str) -> str:
    """`block` with `indent` in front of every non-empty line."""
    if not indent:
        return block
    return "\n".join(f"{indent}{line}" if line.strip() else line for line in block.split("\n"))


def _created_header(part: str, provenance: str) -> str:
    """The header a *newly created* golden file carries.

    It states how the questions below were confirmed, in the words of the run
    that confirmed them. It does not claim they were checked against a printed
    page unless they were: the file this writes is invariant 5's objective
    function, and a false provenance claim in it is worse than no header.
    """
    return (
        f"# Golden Q&A set{f' for {part}' if part else ''}, merged from generated\n"
        "# candidates (`dsa golden suggest` -> `dsa golden confirm`).\n"
        "#\n"
        f"# How these were confirmed: {provenance}.\n"
    )


def _questions_of(parsed: object) -> list:
    """The `questions:` list of a parsed golden file; `[]` when it declares none."""
    if not isinstance(parsed, dict):
        return []
    return parsed.get("questions") or []


def merge_into_golden(
    golden: Path,
    questions: list[GoldenQuestion],
    *,
    provenance: str = PROVENANCE_BULK,
    part: str = "",
) -> MergeResult:
    """Append confirmed questions to `golden_qa_<PART>.yaml`, disturbing nothing.

    The existing file's bytes are the prefix of the new file's bytes. That is
    the whole guarantee, and it is *checked before the file is touched*: the
    merged text is parsed in memory, every question that was there before must
    still parse to exactly the dict it parsed to before, and a failure raises
    with nothing written. Unparsable output is one of those failures - the
    lineage this was ported from wrote first and parsed second, so a bad merge
    left the benchmark corrupted on disk.

    A duplicate id is refused outright - two questions with one id make the
    benchmark ambiguous about which one failed.
    """
    golden = Path(golden)
    if not questions:
        return MergeResult(
            path=golden,
            added=[],
            preserved=sorted(existing_question_ids(golden)),
            provenance=provenance,
        )

    before_text = golden.read_text(encoding="utf-8") if golden.exists() else ""
    try:
        before = yaml.safe_load(before_text) if before_text.strip() else None
    except yaml.YAMLError as exc:
        raise GoldenAssistError(
            f"refusing the merge: {golden} does not parse as YAML ({exc}). Fix it "
            "by hand first - appending to a broken benchmark would hide the break."
        ) from exc
    declares_questions = isinstance(before, dict) and "questions" in before
    before_questions = _questions_of(before) if declares_questions else []
    before_ids = [str(item.get("id", "")) for item in before_questions if isinstance(item, dict)]

    clashes = sorted({q.id for q in questions} & set(before_ids))
    if clashes:
        raise GoldenAssistError(
            f"{golden} already holds question id(s) {', '.join(clashes)} - "
            "rename the candidate or remove the existing question by hand"
        )

    body = dump_yaml({"questions": [question_to_dict(q) for q in questions]})
    # The dumped mapping starts with its own `questions:` key; appending to a
    # file that already has one would declare it twice.
    if declares_questions:
        # A block sequence must keep one indentation throughout, and the
        # hand-written sets indent their items two spaces under `questions:`
        # while `yaml.safe_dump` emits them at column 0. Matching the file
        # rather than reformatting it is the whole point of appending.
        appended = _reindent(body.split("\n", 1)[1], _list_indent(before_text))
    else:
        appended = body
    if before_text:
        prefix = before_text if before_text.endswith("\n") else before_text + "\n"
        text = f"{prefix}\n{MERGE_HEADER}\n# {provenance}.\n{appended}"
    else:
        text = _created_header(part, provenance) + body

    # --- everything below happens before the file is touched -----------------
    _check_merge(golden, text, before_questions, len(questions))

    golden.parent.mkdir(parents=True, exist_ok=True)
    golden.write_text(text, encoding="utf-8")

    # Second line of defence: what landed on disk is what was checked. A
    # filesystem that wrote something else, or an encoding that mangled a
    # character, is caught here and rolled back rather than reported later.
    try:
        _check_merge(golden, golden.read_text(encoding="utf-8"), before_questions, len(questions))
    except GoldenAssistError:
        if before_text:
            golden.write_text(before_text, encoding="utf-8")
        else:
            golden.unlink(missing_ok=True)
        raise

    return MergeResult(
        path=golden,
        added=[q.id for q in questions],
        preserved=before_ids,
        created=not before_text,
        provenance=provenance,
    )


def _check_merge(golden: Path, text: str, before_questions: list, n_added: int) -> None:
    """Raise unless `text` is the old file's questions plus exactly `n_added`.

    Parsing is inside the guard rather than in front of it: unparsable YAML is
    the *first* thing a merge can get wrong, and treating it as anything other
    than a refusal is how a benchmark ends up corrupted.
    """
    try:
        reloaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GoldenAssistError(
            f"refusing the merge: appending to {golden} would produce YAML that "
            f"does not parse ({exc}) - nothing was written"
        ) from exc
    after = _questions_of(reloaded)
    if len(after) != len(before_questions) + n_added:
        raise GoldenAssistError(
            f"refusing the merge: appending to {golden} would leave "
            f"{len(after)} question(s) where {len(before_questions) + n_added} "
            "were expected - nothing was written"
        )
    if after[: len(before_questions)] != before_questions:
        raise GoldenAssistError(
            f"refusing the merge: appending to {golden} would have changed the "
            "questions already in it - nothing was written"
        )


# --- the printed page beside the candidate -----------------------------------


@dataclass(frozen=True)
class PageContext:
    """The text a reviewer glances at, and where it came from.

    `origin` is never empty and never vague: "printed PDF p.7" and "corpus
    section docs/.../4.3-....md" are different evidence, and only the first can
    confirm a page citation. `warning` says so when the second is all there is.
    """

    page: int | None
    origin: str
    text: str
    warning: str = ""
    hits: dict[str, bool] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.text)

    @property
    def from_pdf(self) -> bool:
        """Whether this text is the printed page rather than the corpus's own."""
        return self.origin.startswith("printed PDF")


def _window(text: str, needles: list[str], size: int) -> str:
    """`size` characters of `text` centred on the first needle that occurs."""
    if len(text) <= size:
        return text
    start = 0
    for needle in needles:
        found = text.find(needle) if needle else -1
        if found >= 0:
            start = max(0, found - size // 3)
            break
    return text[start : start + size]


def page_context(
    part_dir: Path,
    candidate: GoldenCandidate,
    *,
    page_texts: list[str] | None = None,
    window: int = DEFAULT_WINDOW,
) -> PageContext:
    """The printed page text for one candidate - PDF first, corpus second.

    The PDF page is preferred because it is what `dsa verify`'s page-truth check
    reads: a candidate confirmed against corpus text alone has had its citation
    checked against the same extraction that produced it, which is not a check.
    Without a PDF the corpus section covering the page is shown *and labelled*,
    so the reviewer knows what they are looking at.
    """
    from datasheet_analyzer.retrieve import CorpusIndex

    part_dir = Path(part_dir)
    page = candidate.page
    expected = list(candidate.question.expected_substrings)
    if page is None:
        return PageContext(
            page=None,
            origin="(no page)",
            text="",
            warning="this candidate cites no page and cannot be confirmed",
        )

    if page_texts and 0 < page <= len(page_texts):
        text = page_texts[page - 1]
        return PageContext(
            page=page,
            origin=f"printed PDF p.{page}",
            text=_window(text, expected, window),
            hits={sub: sub in text for sub in expected},
        )

    index = CorpusIndex.load(part_dir)
    covering = [
        section
        for section in index.sections
        if section.page_start is not None
        and section.page_start <= page <= (section.page_end or section.page_start)
    ]
    if not covering:
        return PageContext(
            page=page,
            origin="(nothing covers this page)",
            text="",
            warning=(
                f"no PDF given and no corpus section covers p.{page} - "
                "open the printed page before accepting"
            ),
        )
    section = covering[0]
    text = index.section_text(section)
    return PageContext(
        page=page,
        origin=f"corpus section {section.file}",
        text=_window(text, expected, window),
        warning=(
            "no --pdf given: this is the corpus's own text, not the printed "
            "page, so it cannot confirm the page citation"
        ),
        hits={sub: sub in text for sub in expected},
    )


def render_candidate(
    candidate: GoldenCandidate,
    context: PageContext,
    *,
    position: str = "",
) -> str:
    """One candidate as a reviewer sees it: the question, then the page."""
    question = candidate.question
    head = f"[{position}] " if position else ""
    lines = [
        f"{head}{question.id}  ({candidate.template}, {candidate.confidence.value})",
        f"  Q: {question.question}",
        f"  expects: {question.expected_substrings}",
        f"  page: p.{candidate.page}   source: {candidate.source}",
        f"  printed cells: {candidate.verbatim}",
        f"  --- {context.origin} ---",
    ]
    if context.warning:
        lines.append(f"  ! {context.warning}")
    for line in (context.text or "(no text available)").splitlines():
        lines.append(f"  | {line}")
    if context.hits:
        missing = [sub for sub, hit in context.hits.items() if not hit]
        lines.append(
            "  substrings on this page: all of them"
            if not missing
            else f"  substrings NOT on this page: {missing}"
        )
    return "\n".join(lines)


#: The prompt the interactive shell shows, and the keys it accepts.
PROMPT = "  [a]ccept / [e]dit / [r]eject / [s]kip / [q]uit > "
_KEYS = {"a": ACCEPT, "e": EDIT, "r": REJECT}


def run_interactive(
    candidates: GoldenCandidateSet,
    *,
    part_dir: Path,
    page_texts: list[str] | None = None,
    read: object = input,
    write: object = print,
) -> list[Decision]:
    """The thin shell: show a candidate, read one decision, move on.

    `read` and `write` are injected so the loop is exercised in tests without a
    TTY - the shell is thin, but "thin" is not "unowned". It contains no rule
    the core does not already own: it collects `Decision`s and hands them to
    `apply_decisions`, which is where every rule about them lives.
    """
    decisions: list[Decision] = []
    total = len(candidates.candidates)
    for i, candidate in enumerate(candidates.candidates, 1):
        context = page_context(part_dir, candidate, page_texts=page_texts)
        write(render_candidate(candidate, context, position=f"{i}/{total}"))
        answer = str(read(PROMPT) or "").strip().lower()
        if answer.startswith("q"):
            write(f"  stopped after {i - 1} decision(s); the rest stay unconfirmed")
            break
        if answer.startswith("s") or not answer:
            continue
        action = _KEYS.get(answer[0])
        if action is None:
            write(f"  '{answer}' is not a decision - skipping {candidate.question.id}")
            continue
        if action == REJECT:
            decisions.append(
                Decision(
                    id=candidate.question.id,
                    action=REJECT,
                    reason=str(read("  why? ") or "").strip(),
                )
            )
            continue
        if action == EDIT:
            edited = str(read("  question text: ") or "").strip()
            if not edited:
                write("  no new wording given - skipping")
                continue
            decisions.append(
                Decision(id=candidate.question.id, action=EDIT, edits={"question": edited})
            )
            continue
        decisions.append(Decision(id=candidate.question.id, action=ACCEPT))
    return decisions


def render_confirm_report(
    outcome: ConfirmOutcome, merge: MergeResult, *, rejected_file: Path | None
) -> str:
    """What `dsa golden confirm` prints after the write."""
    lines = [
        "# Golden confirm",
        "",
        (
            f"**{len(outcome.accepted)} accepted** "
            f"({len(outcome.edited_ids)} edited), "
            f"{len(outcome.rejected)} rejected, "
            f"{len(outcome.deferred)} left unconfirmed."
        ),
        "",
    ]
    if merge.added:
        lines.append(f"Merged into {merge.path}:")
        lines += [f"- {qid}" for qid in merge.added]
        lines.append(
            f"({len(merge.preserved)} hand-written question(s) untouched)"
            if merge.preserved
            else "(new golden file)"
        )
        # The provenance the file was stamped with is printed here too, so a
        # bulk run is told what it just wrote rather than having to open it.
        lines += ["", f"Recorded provenance: {merge.provenance}.", ""]
    if outcome.rejected and rejected_file is not None:
        lines.append(f"Recorded in {rejected_file} so they are not suggested again:")
        lines += [
            f"- {entry.id}: {entry.reason or 'no reason given'}" for entry in outcome.rejected
        ]
        lines.append("")
    if outcome.deferred:
        lines.append(
            f"{len(outcome.deferred)} candidate(s) still await a decision and stay "
            "in the candidate file. They count toward nothing until they do."
        )
        lines.append("")
    return "\n".join(lines)
