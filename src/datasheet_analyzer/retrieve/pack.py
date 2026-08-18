"""Answer packs — one call, one cited payload, a hard budget.

`dsa ask` composes tickets 01–04 into a single round trip: the alias ladder
(02), the BM25 full-text path (03) and the per-record grade (04), assembled
over the loaded corpus (01) into one payload an agent can drop straight into
its context.

**Routing is deterministic — no LLM is in this path.** The question is
classified by feature hits, in the plan's order:

| # | Feature | Route |
|---|---|---|
| 1 | pin vocabulary (`pin`, `ball`, `pad`) **and** a published `pins.json` that answers | `pin` |
| 2 | register vocabulary (`register`, `reset value`, `bit field`) **and** a published `registers.json` that answers | `register` |
| 3 | the spec ladder resolves the question (symbol / alias / prefix / fuzzy) | `spec` |
| 4 | plot vocabulary (`plot`, `curve`, `vs`, `versus`, `graph`, `figure`) **and** a figure whose caption uses the question's words | `plot` |
| 5 | anything the full-text index ranks | `search` |
| 6 | nothing, and the corpus has no current full-text index | `unavailable` — rebuild to enable search |
| 7 | nothing at all | `none` — an explicit no-match plus nearest candidates |

Routes 1 and 2 are phase 6's, and they go first for the reason the phase
exists: "which pins are ground?" has a *table* for an answer, and a corpus
that publishes that table should never answer it with a paragraph that happens
to contain the word "ground". They are guarded exactly as the plot route is —
vocabulary alone never routes anything; the derived artifact has to exist and
has to return a record — so a part that published no pin table (most of them
do not) routes as it always did, and no phase-5 answer moves.

Route 6 exists because an empty full-text result means "nothing matched" only
when there was an index to match against. A corpus published before
`search_index.json` existed (or against an older schema) hands back the same
empty list, and reading that as absence would put a claim in the pack that the
retrieval never earned — `Retriever.search_unavailable()` is asked before
`none` is ever reported, exactly as `dsa search` asks it.

One refinement of that order is load-bearing and deliberate: a question that
*names a figure* and finds one is a plot question even when the quantity it
names also has an alias entry ("which figure shows the **gain error** vs DSA
setting?"). Plot vocabulary therefore disqualifies the spec route — but only
when the plot lookup actually found something, so a routing technicality can
never cost an answer that exists.

**The budget is enforced here, not in a front end.** A front end cannot honour
a token budget on text it did not produce, so the pack renders itself
(`markdown`) and reports what that cost (`tokens`). Assembly is greedy in
retrieval order against `budget`, with a **reserved tail** — the header, the
first answer line, and the verify footer — that is laid down *first* and never
competes with the fill. That is what makes citations un-truncatable: the parts
that carry `§N, p.N` are reserved before anything discretionary is added, and
what gets dropped is extra rows and excerpt prose. Any drop emits an explicit
notice naming `--budget`; truncation is never silent.

`build_project_pack` (ticket 06) is the same pack over a whole design. Each
member part is routed independently — its own records, its own figures, its
own index — and every answer line carries the part it came from, because
"1.8 V min" is not an answer until you know which device printed it. The rows
are interleaved one per part before any part's second row, so a question two
parts answer returns both even under a tight budget. A member with no
full-text index is a *gap*, not an absence: the project reports which part
could not be searched rather than claiming the design is silent.

`ANSWER_PACK_SCHEMA` is the declared JSON shape of `as_dict()`. It lives here
rather than in a front end for the same reason `SpecHit.as_dict()` does — the
CLI's `--json` and (ticket 07) the MCP tool must emit one shape and cannot be
allowed to drift. `validate_pack(payload)` checks a payload against it and is
dependency-free, so the check is available wherever the schema is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from datasheet_analyzer.config import get_settings
from datasheet_analyzer.models import PlotRecord, SectionFile, SpecRecord
from datasheet_analyzer.retrieve.project import ProjectRetriever
from datasheet_analyzer.retrieve.results import (
    CONFIDENCE_UNKNOWN,
    Citation,
    PlotHit,
    SearchHit,
    SpecHit,
)
from datasheet_analyzer.retrieve.retriever import PLOT_VOCABULARY, Retriever
from datasheet_analyzer.retrieve.search import snippet
from datasheet_analyzer.structure.aliases import padded, tokens
from datasheet_analyzer.structure.search import tokenize
from datasheet_analyzer.tokens import count_tokens, truncate_to_tokens

ROUTE_SPEC = "spec"
#: Phase 6: the derived device tables. A pin or register question asked of a
#: corpus that published one is answered from that artifact rather than from a
#: paragraph that happens to contain the word — see `_route`.
ROUTE_PIN = "pin"
ROUTE_REGISTER = "register"
ROUTE_PLOT = "plot"
ROUTE_SEARCH = "search"
ROUTE_NONE = "none"
#: No route could run: the spec and figure paths found nothing and this corpus
#: has no current full-text index, so absence was never established.
ROUTE_UNAVAILABLE = "unavailable"
ROUTES = (
    ROUTE_SPEC,
    ROUTE_PIN,
    ROUTE_REGISTER,
    ROUTE_PLOT,
    ROUTE_SEARCH,
    ROUTE_NONE,
    ROUTE_UNAVAILABLE,
)

#: What makes a question a *pin* question, and a *register* question. Both are
#: printed-word lexicons, like `PLOT_VOCABULARY` — matching one is necessary
#: and never sufficient: the derived artifact must also exist and must
#: actually answer, so a routing technicality can never cost an answer that
#: exists (the rule the plot route already follows).
PIN_VOCABULARY = re.compile(r"\b(pin|pins|pinout|pin-?out|ball|balls|pad|pads)\b", re.IGNORECASE)
REGISTER_VOCABULARY = re.compile(
    r"\b(register|registers|regmap|register map|reset value|default value|"
    r"bit ?field|bit ?fields)\b",
    re.IGNORECASE,
)
#: A printed pin designator (`A1`, `B12`, `E7`) or a signal/register name
#: (`VDD18`, `TXDIG_CTRL0`). Case is significant: a datasheet prints both in
#: upper case, and lower-casing the question first would make "the" a name.
_DESIGNATOR = re.compile(r"\b[A-Z]{1,2}\d{1,3}\b")
_IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*[A-Z0-9]\b")
_HEX_LITERAL = re.compile(r"\b0x[0-9a-fA-F]+\b")

# How many candidates each route offers the budget. The budget is the real
# limit; these caps only stop a prefix-family query from rendering two hundred
# lines just to trim them again.
MAX_SPEC_ANSWERS = 6
MAX_PIN_ANSWERS = 8
MAX_REGISTER_ANSWERS = 6
MAX_PLOT_ANSWERS = 5
MAX_SEARCH_ANSWERS = 3
MAX_SUGGESTIONS = 5
# A project pack answers from several parts at once; the cap is on the union,
# and the rows are interleaved so it can never spend itself on one member.
MAX_PROJECT_ANSWERS = 8
# How many member names the project header spells out before it counts them.
_HEADER_PARTS = 6
# Which route leads a project pack when two parts answer by different paths:
# a parametric row is a stronger answer than a quoted paragraph.
_ROUTE_STRENGTH = {
    ROUTE_SPEC: 0,
    ROUTE_PIN: 1,
    ROUTE_REGISTER: 2,
    ROUTE_PLOT: 3,
    ROUTE_SEARCH: 4,
}

_TRUNCATION_NOTICE = (
    "_Truncated to fit a {budget}-token budget — raise it with `--budget N` "
    "(or the DSA_ASK_BUDGET setting) to see the rest._"
)
# Below the reserved tail there is nothing left to give back: the answer and
# its citation stay, and the pack says outright that it went over.
_FLOOR_NOTICE = (
    "_A {budget}-token budget is below this pack's citation floor; the answer "
    "and its citation are kept regardless — raise it with `--budget N` "
    "(or the DSA_ASK_BUDGET setting)._"
)


@dataclass(frozen=True)
class PackLine:
    """One answer row: the finding and the citation that proves it.

    They are one object because they must survive or be dropped together — a
    value without its page is exactly the assertion this project exists to
    avoid emitting.
    """

    text: str
    citation: str
    confidence: str = CONFIDENCE_UNKNOWN
    matched_via: str = ""
    # Which part answered. Empty for a single-part pack, where the header
    # already says it; filled for a project pack, where it is the thing that
    # makes the answer usable — "1.8 V min" is not an answer until you know
    # which device on the board printed it.
    part: str = ""
    doc: str = ""
    section: str = ""
    page_start: int | None = None
    page_end: int | None = None
    file: str = ""

    @property
    def rendered(self) -> str:
        head = f"[{self.part}] " if self.part else ""
        tail = f"  file: {self.file}" if self.file else ""
        return f"{head}{self.text} — {self.citation}  [{self.confidence}]{tail}"

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "citation": self.citation,
            "confidence": self.confidence,
            "matched_via": self.matched_via,
            "part": self.part,
            "doc": self.doc,
            "section": self.section,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "file": self.file,
        }


@dataclass(frozen=True)
class PackExcerpt:
    """The supporting quote: verbatim corpus text, with its own citation."""

    heading: str
    citation: str
    text: str
    #: Which part the quote came from — empty unless the pack spans a project.
    part: str = ""

    @property
    def label(self) -> str:
        """`§4.3 Recommended Operating Conditions, p.6` — never § twice.

        The heading already opens with the section number when there is one,
        so the citation contributes only its pages there; a section-less
        corpus (ADI's unnumbered outlines) keeps the citation whole. A project
        pack prefixes the part, because across a design "§4.3" alone names
        nothing.
        """
        tail = self.citation
        if self.heading.startswith("§") and tail.startswith("§"):
            tail = tail.split(", ", 1)[-1]
        base = f"{self.heading}, {tail}" if tail else self.heading
        return f"{self.part} — {base}" if self.part else base

    def as_dict(self) -> dict:
        return {
            "heading": self.heading,
            "citation": self.citation,
            "text": self.text,
            "part": self.part,
        }


@dataclass(frozen=True)
class AnswerPack:
    """One question's complete, cited, budget-bounded payload."""

    part: str
    question: str
    route: str
    budget: int
    revision: str = ""
    doc: str = ""
    # Project scope (ticket 06): `project` names the design and `parts` its
    # members. Both empty for a single-part pack — `project` being set is what
    # tells a caller that every answer line names its own part.
    project: str = ""
    parts: tuple[str, ...] = ()
    answers: tuple[PackLine, ...] = ()
    excerpt: PackExcerpt | None = None
    verify: str = ""
    suggestions: tuple[str, ...] = ()
    notice: str = ""
    truncated: bool = False

    @property
    def header(self) -> str:
        """`## AFE7950 — SBASA41E (datasheet-c1b4663b)`, parts optional.

        A project pack names the design and its members instead:
        `## rf-frontend — project (AFE7950, HMC520A, AD9081)`. The member list
        is capped, because the header is reserved tail and a fifty-part design
        must not spend the budget introducing itself.
        """
        if self.project:
            head = self.project
            if self.parts:
                shown = ", ".join(self.parts[:_HEADER_PARTS])
                if len(self.parts) > _HEADER_PARTS:
                    shown += f", … ({len(self.parts)} parts)"
                head += f" — project ({shown})"
            else:
                head += " — project (no parts)"
            return f"## {head}"
        bits = self.part or "(unknown part)"
        if self.revision:
            bits += f" — {self.revision}"
        if self.doc:
            bits += f" ({self.doc})"
        return f"## {bits}"

    @property
    def markdown(self) -> str:
        """The payload itself — what the budget is measured against."""
        blocks = [self.header]
        if self.route in (ROUTE_NONE, ROUTE_UNAVAILABLE):
            title = "No match" if self.route == ROUTE_NONE else "Search unavailable"
            blocks.append(
                f"### {title}\n" + (self.answers[0].text if self.answers else "")
            )
        else:
            blocks.append(
                "### Answer\n" + "\n".join(line.rendered for line in self.answers)
            )
        if self.suggestions:
            blocks.append(
                "### Nearest candidates\n"
                + "\n".join(f"- {s}" for s in self.suggestions)
            )
        if self.excerpt is not None:
            blocks.append(
                f"### Supporting excerpt  ({self.excerpt.label})\n{self.excerpt.text}"
            )
        blocks.append(f"### Verify\n{self.verify}")
        if self.notice:
            blocks.append(self.notice)
        return "\n".join(blocks)

    @property
    def tokens(self) -> int:
        """Estimated size of `markdown` — the number the budget bounds."""
        return count_tokens(self.markdown)

    @property
    def over_budget(self) -> bool:
        """True only when the budget was below the un-droppable citation core."""
        return self.tokens > self.budget

    @property
    def citations(self) -> tuple[str, ...]:
        """Every citation the pack carries, answers first then the excerpt."""
        out = [line.citation for line in self.answers if line.citation]
        if self.excerpt is not None and self.excerpt.citation:
            out.append(self.excerpt.citation)
        return tuple(out)

    def as_dict(self) -> dict:
        """The declared JSON shape (`ANSWER_PACK_SCHEMA`)."""
        return {
            "part": self.part,
            "question": self.question,
            "route": self.route,
            "budget": self.budget,
            "tokens": self.tokens,
            "over_budget": self.over_budget,
            "truncated": self.truncated,
            "notice": self.notice,
            "revision": self.revision,
            "doc": self.doc,
            "project": self.project,
            "parts": list(self.parts),
            "answers": [line.as_dict() for line in self.answers],
            "excerpt": None if self.excerpt is None else self.excerpt.as_dict(),
            "verify": self.verify,
            "suggestions": list(self.suggestions),
            "citations": list(self.citations),
            "markdown": self.markdown,
        }


def build_pack(retriever: Retriever, question: str, *, budget: int = 0) -> AnswerPack:
    """Route `question`, gather the evidence, and fit it into `budget` tokens.

    `budget <= 0` means "use the configured default" (`DSA_ASK_BUDGET`), so a
    caller that does not care never has to name a number.
    """
    question = question.strip()
    if budget <= 0:
        budget = get_settings().ask_budget

    route, lines, excerpt, verify, suggestions, more = _route(retriever, question)
    frame = _draft(retriever, question, route, budget)
    return _assemble(frame, lines, excerpt, verify, suggestions, more)


def build_project_pack(
    scope: ProjectRetriever, question: str, *, budget: int = 0
) -> AnswerPack:
    """One pack for a whole design: every answering part, each labelled.

    Every member is routed **independently** — a part answers from its own
    records, its own figures and its own index — and the answering members are
    then ordered by route strength (a spec row beats a quoted paragraph), with
    membership order underneath. The rows are interleaved one per part before
    any part's second row, so a question two parts answer returns both even
    under a tight budget: dropping the second device's only answer to make
    room for the first device's fifth would defeat the point of asking a
    project.

    Ordering is the only liberty taken. Nothing is dropped, re-graded or
    re-cited here, and the budget arithmetic is the single-part one.
    """
    question = question.strip()
    if budget <= 0:
        budget = get_settings().ask_budget

    answering: list[_MemberAnswer] = []
    suggestions: list[str] = []
    for order, member in enumerate(scope.members):
        route, lines, excerpt, verify, hints, more = _route(member, question)
        if route in _ROUTE_STRENGTH:
            answering.append(
                _MemberAnswer(
                    part=member.part,
                    order=order,
                    route=route,
                    lines=[replace(line, part=member.part) for line in lines],
                    excerpt=(
                        None if excerpt is None else replace(excerpt, part=member.part)
                    ),
                    verify=verify,
                    more=more,
                )
            )
        else:
            for hint in hints:
                if hint not in suggestions:
                    suggestions.append(hint)

    if not answering:
        return _project_no_match(scope, question, budget, suggestions)

    answering.sort(key=lambda m: (_ROUTE_STRENGTH[m.route], m.order))
    lead = answering[0]
    lines = _interleave([m.lines for m in answering])
    more = any(m.more for m in answering) or len(lines) > MAX_PROJECT_ANSWERS
    frame = _project_draft(scope, question, lead.route, budget)
    return _assemble(
        frame,
        lines[:MAX_PROJECT_ANSWERS],
        lead.excerpt,
        f"{lead.part} — {lead.verify}",
        [],
        more,
    )


def _assemble(
    frame: AnswerPack,
    lines: list[PackLine],
    excerpt: PackExcerpt | None,
    verify: str,
    suggestions: list[str],
    more: bool,
) -> AnswerPack:
    """Fit the gathered evidence into the frame's budget and say what it cost."""
    budget = frame.budget
    kept, kept_excerpt, truncated = _fit(frame, lines, excerpt, verify, suggestions, "")
    truncated = truncated or more
    notice = ""
    if truncated:
        # One re-fit, not a loop: the notice text depends only on the budget,
        # so adding it can shrink the fill but can never change its own text.
        notice = _TRUNCATION_NOTICE.format(budget=budget)
        kept, kept_excerpt, _again = _fit(
            frame, lines, excerpt, verify, suggestions, notice
        )
    pack = replace(
        frame,
        answers=tuple(kept),
        excerpt=kept_excerpt,
        verify=verify,
        suggestions=tuple(suggestions),
        notice=notice,
        truncated=truncated,
    )
    if pack.over_budget:
        # Even with everything discretionary gone, the reserved tail does not
        # fit: the budget is below this pack's citation floor. The answer and
        # its citation stay — they are the point — and the notice says so
        # outright rather than quietly shipping an over-budget pack.
        pack = replace(pack, notice=_FLOOR_NOTICE.format(budget=budget))
    return pack


@dataclass(frozen=True)
class _MemberAnswer:
    """What one member part contributed to a project pack."""

    part: str
    order: int
    route: str
    lines: list[PackLine]
    excerpt: PackExcerpt | None
    verify: str
    more: bool


def _interleave(groups: list[list[PackLine]]) -> list[PackLine]:
    """Round-robin: every group's first row before any group's second."""
    out: list[PackLine] = []
    for rank in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if rank < len(group):
                out.append(group[rank])
    return out


def _project_no_match(
    scope: ProjectRetriever, question: str, budget: int, suggestions: list[str]
) -> AnswerPack:
    """No member answered — an explicit no-match, or an admitted gap.

    A member with no full-text index never ran that path, so the project
    cannot say the design is silent on the question; it says which part could
    not be searched instead. Same rule as the single-part `unavailable` route,
    applied to a set of corpora.
    """
    gap = scope.search_gap()
    if gap:
        route, line, verify = (
            ROUTE_UNAVAILABLE,
            _unavailable_line(question, gap),
            _verify_unavailable(),
        )
    else:
        route, line, verify = ROUTE_NONE, _no_match_line(question), _verify_none()
    frame = _project_draft(scope, question, route, budget)
    return _assemble(frame, [line], None, verify, suggestions[:MAX_SUGGESTIONS], False)


def _draft(retriever: Retriever, question: str, route: str, budget: int) -> AnswerPack:
    """An empty pack carrying only the part's identity — the render frame."""
    manifest = retriever.index.manifest
    doc = manifest.documents[0] if (manifest and manifest.documents) else None
    return AnswerPack(
        part=retriever.part,
        question=question,
        route=route,
        budget=budget,
        revision=doc.revision if doc else "",
        doc=retriever.index.docs[0].name if retriever.index.docs else "",
    )


def _project_draft(
    scope: ProjectRetriever, question: str, route: str, budget: int
) -> AnswerPack:
    """The render frame for a project pack: the design and its members."""
    return AnswerPack(
        part="",
        question=question,
        route=route,
        budget=budget,
        project=scope.name,
        parts=tuple(scope.parts),
    )


# --- routing -----------------------------------------------------------------


def _route(
    retriever: Retriever, question: str
) -> tuple[str, list[PackLine], PackExcerpt | None, str, list[str], bool]:
    """Classify, gather, and return `(route, lines, excerpt, verify, suggestions, more)`.

    `more` reports that candidates were dropped before the budget ever saw
    them (the per-route caps), so the notice tells the truth either way.
    """
    if not question:
        return ROUTE_NONE, [_no_match_line(question)], None, _verify_none(), [], False

    # The derived device tables answer first when they can — see module docs.
    # Each returns `None` unless its artifact exists *and* held a record, so
    # neither can shadow an answer the older routes would have found.
    derived = _pin_route(retriever, question) or _register_route(retriever, question)
    if derived is not None:
        return derived

    spec_hits = retriever.specs(name=question)
    # The plot lookup runs only when the question actually names a figure, and
    # its result is what allows it to override the spec route (module docs).
    plot_hits = (
        retriever.plots_for_terms(question, limit=MAX_PLOT_ANSWERS)
        if PLOT_VOCABULARY.search(question)
        else []
    )

    if spec_hits and not plot_hits:
        return _spec_route(retriever, question, spec_hits)
    if plot_hits:
        return _plot_route(retriever, question, plot_hits)

    search_hits = retriever.search(question, limit=MAX_SEARCH_ANSWERS)
    if search_hits:
        return _search_route(retriever, search_hits)

    # `search()` returns `[]` both for "nothing matched" and for "there was
    # nothing to match against". Only the first of those licenses a no-match,
    # so the reason is asked for before absence is ever asserted.
    unavailable = retriever.search_unavailable()
    if unavailable:
        return (
            ROUTE_UNAVAILABLE,
            [_unavailable_line(question, unavailable)],
            None,
            _verify_unavailable(),
            retriever.suggest_specs(question, limit=MAX_SUGGESTIONS),
            False,
        )

    return (
        ROUTE_NONE,
        [_no_match_line(question)],
        None,
        _verify_none(),
        retriever.suggest_specs(question, limit=MAX_SUGGESTIONS),
        False,
    )


def _pin_type_named(question: str) -> str:
    """The pin-type label a question names, from the checked-in lexicon.

    Invariant 8 clause (c): the label is not inferred from the shape of the
    question, it is a phrase somebody wrote down in `registry/pin_types.yaml`.
    Only the literal phrases are used — a glob (`*vdd*`) describes a printed
    *name*, not a word a designer types — and lexicon order decides, exactly
    as it does when the same file labels a record.
    """
    from datasheet_analyzer.derive.pins import load_pin_lexicon, normalize

    asked = normalize(question)
    for spec in load_pin_lexicon().types:
        for phrase in (*spec.printed, *spec.keywords):
            if "*" in phrase:
                continue
            # Whole words, not substrings: "ground?" ends a printed question
            # and "background" is not one. The boundary is alphanumeric-only
            # because the lexicon's own phrases carry punctuation (`n/c`).
            pattern = rf"(?<![a-z0-9]){re.escape(normalize(phrase))}(?![a-z0-9])"
            if phrase and re.search(pattern, asked):
                return spec.type
    return ""


def _named_records(question: str) -> list[str]:
    """Printed designators and identifiers the question names, longest first.

    `A1`, `VDD18`, `TXDIG_CTRL0` — the strings a datasheet prints in a device
    table's key column. Longest first because a question that names both
    `TXDIG_CTRL0` and `TX` is asking about the former, and the lookup takes
    the first term that matches a record.
    """
    found = [*_DESIGNATOR.findall(question), *_IDENTIFIER.findall(question)]
    unique = list(dict.fromkeys(found))
    return sorted(unique, key=lambda t: (-len(t), t))


def _pin_route(retriever: Retriever, question: str):
    """The pin table's answer, or `None` to leave the question to another route.

    `None` — not an empty pack — for every way this route can decline: the
    question names no pin, the part published no `pins.json`, or the table has
    no matching record. Declining is what keeps the guarantee that adding this
    route cannot move an answer another route already gave.
    """
    if not PIN_VOCABULARY.search(question):
        return None
    label = _pin_type_named(question)
    terms = _named_records(question)
    if not label and not terms:
        return None
    from datasheet_analyzer.derive.pins import find_pins, load_part_pins

    part_pins = load_part_pins(retriever.part_dir, retriever.part)
    if not part_pins.sets:
        return None
    hits: list = []
    # A named designator is the sharper question, so it is asked first; a type
    # that was also named is the fallback, which is what makes "which pins are
    # ground on the AD9081?" answer despite naming the part in passing.
    for term in [*terms, ""] if label else terms:
        hits = find_pins(part_pins, q=term, pin_type=label)
        if hits:
            break
    if not hits:
        return None
    lines = [_pin_line(h) for h in hits[:MAX_PIN_ANSWERS]]
    top = hits[0]
    excerpt = _excerpt_for(retriever, question, top.citation)
    verify = _verify_record(retriever, top.citation, top.confidence)
    return ROUTE_PIN, lines, excerpt, verify, [], len(hits) > MAX_PIN_ANSWERS


def _register_route(retriever: Retriever, question: str):
    """The register map's answer, or `None` to leave the question alone.

    Same decline contract as `_pin_route`. An address is asked first and by
    *value* (`derive.registers` resolves `0x1A04`, `0x1a04` and `6660` to one
    question), because a firmware engineer who typed an address knows exactly
    which register they mean.
    """
    if not REGISTER_VOCABULARY.search(question):
        return None
    addresses = _HEX_LITERAL.findall(question)
    names = _named_records(question)
    if not addresses and not names:
        return None
    from datasheet_analyzer.derive.registers import find_registers, load_part_registers

    part_registers = load_part_registers(retriever.part_dir, retriever.part)
    if not part_registers.sets:
        return None
    hits: list = []
    for address in addresses:
        hits = find_registers(part_registers, addr=address)
        if hits:
            break
    if not hits:
        for name in names:
            hits = find_registers(part_registers, name=name)
            if hits:
                break
    if not hits:
        return None
    lines = [_register_line(h) for h in hits[:MAX_REGISTER_ANSWERS]]
    top = hits[0]
    excerpt = _excerpt_for(retriever, question, top.citation)
    verify = _verify_record(retriever, top.citation, top.confidence)
    return ROUTE_REGISTER, lines, excerpt, verify, [], len(hits) > MAX_REGISTER_ANSWERS


def _spec_route(retriever: Retriever, question: str, hits: list[SpecHit]):
    hits = _by_relevance(question, hits)
    lines = [_spec_line(h) for h in hits[:MAX_SPEC_ANSWERS]]
    top = hits[0]
    excerpt = _excerpt_for(retriever, question, top.citation)
    verify = _verify_record(retriever, top.citation, top.confidence)
    return ROUTE_SPEC, lines, excerpt, verify, [], len(hits) > MAX_SPEC_ANSWERS


def _plot_route(retriever: Retriever, question: str, hits: list[PlotHit]):
    lines = [_plot_line(h) for h in hits[:MAX_PLOT_ANSWERS]]
    top = hits[0]
    excerpt = _excerpt_for(retriever, question, top.citation)
    verify = _verify_record(retriever, top.citation, top.confidence)
    return ROUTE_PLOT, lines, excerpt, verify, [], len(hits) > MAX_PLOT_ANSWERS


def _search_route(retriever: Retriever, hits: list[SearchHit]):
    lines = [_search_line(h) for h in hits[:MAX_SEARCH_ANSWERS]]
    top = hits[0]
    # A section with no quotable body (a bare heading) still cites honestly;
    # it just has no excerpt to offer, rather than an empty block.
    excerpt = (
        PackExcerpt(heading=top.heading, citation=top.citation.label, text=top.snippet)
        if top.snippet
        else None
    )
    verify = _verify_text(retriever, top.citation)
    return ROUTE_SEARCH, lines, excerpt, verify, [], False


def _by_relevance(question: str, hits: list[SpecHit]) -> list[SpecHit]:
    """Order one rung's rows by how much of the question each row uses.

    The ladder's order is *retrieval* order: which rung matched, then the
    table's own row order (with `expect_unit` promoting inside it). A rung
    that legitimately returns twenty rows of one family still has to decide
    which row the designer asked about, and the question's own words are the
    only deterministic signal available without an LLM — this is the "greedy
    by score" the plan calls for, and it is a *presentation* order: no row is
    dropped, hidden or re-graded by it.

    The sort is stable, so rows the question does not distinguish keep the
    ladder's order exactly.
    """
    terms = tokens(question)
    if not terms:
        return hits

    def overlap(hit: SpecHit) -> int:
        rec = hit.record
        haystack = padded(f"{rec.symbol} {rec.name} {rec.conditions}")
        return -sum(1 for term in terms if f" {term} " in haystack)

    return sorted(hits, key=overlap)


# --- answer lines ------------------------------------------------------------


def _spec_line(hit: SpecHit) -> PackLine:
    rec = hit.record
    text = _head(rec)
    value = _spec_value(rec)
    if value:
        text = f"{text}: {value}" if text else value
    if rec.conditions:
        text = f"{text}; {rec.conditions}" if text else rec.conditions
    return PackLine(
        text=text or rec.section,
        citation=hit.citation.label,
        confidence=hit.confidence,
        matched_via=hit.matched_via,
        doc=hit.citation.doc,
        section=hit.citation.section,
        page_start=hit.citation.page_start,
        page_end=hit.citation.page_end,
    )


def _head(rec: SpecRecord) -> str:
    """`TJ  Operating junction temperature` — either half may be missing."""
    if rec.symbol and rec.name and rec.symbol != rec.name:
        return f"{rec.symbol}  {rec.name}"
    return rec.symbol or rec.name


def _spec_value(rec: SpecRecord) -> str:
    """`105 °C (max)`, `1.15 V (min), 1.2 V (typ)`, or `""` when none printed."""
    unit = rec.unit.verbatim or rec.unit.canonical
    if rec.value:
        return f"{rec.value} {unit}".strip()
    parts = [
        (f"{val} {unit}".strip() + f" ({label})")
        for label, val in (("min", rec.min), ("typ", rec.typ), ("max", rec.max))
        if val
    ]
    return ", ".join(parts)


def _pin_line(hit) -> PackLine:
    """`A1  VSSA  [ground] — Analog ground`, every half optional but the key.

    The type is printed in brackets because it is a *derived* label and a
    reader must be able to tell it from the two cells the datasheet printed;
    `dsa pins` prints it the same way for the same reason.
    """
    rec = hit.record
    head = f"{rec.pin}  {rec.name}".strip()
    direction = f" {rec.direction}" if rec.direction else ""
    text = f"{head}  [{rec.type}{direction}]"
    if rec.description:
        text = f"{text} — {rec.description}"
    return PackLine(
        text=text,
        citation=hit.citation.label,
        confidence=hit.confidence,
        matched_via=hit.matched_via,
        doc=hit.citation.doc,
        section=hit.citation.section,
        page_start=hit.citation.page_start,
        page_end=hit.citation.page_end,
    )


def _register_line(hit) -> PackLine:
    """`0x1A04  TXDIG_CTRL0: reset 0x00, access R/W` — printed cells only.

    A column the map never printed contributes nothing rather than a
    placeholder: the line says what the page says.
    """
    rec = hit.record
    head = f"{rec.address.verbatim}  {rec.name}".strip() or rec.id
    detail = [
        f"{label} {value}"
        for label, value in (("reset", rec.reset.verbatim), ("access", rec.access))
        if value
    ]
    for field in hit.fields:
        bits = field.bits.verbatim or "?"
        detail.append(f"{bits} {field.name}".strip())
    text = f"{head}: {', '.join(detail)}" if detail else head
    return PackLine(
        text=text,
        citation=hit.citation.label,
        confidence=hit.confidence,
        matched_via=hit.matched_via,
        doc=hit.citation.doc,
        section=hit.citation.section,
        page_start=hit.citation.page_start,
        page_end=hit.citation.page_end,
    )


def _plot_line(hit: PlotHit) -> PackLine:
    rec: PlotRecord = hit.record
    text = rec.caption or rec.id
    if rec.conditions:
        text = f"{text}; {rec.conditions}"
    return PackLine(
        text=text,
        citation=hit.citation.label,
        confidence=hit.confidence,
        matched_via=hit.matched_via,
        doc=hit.citation.doc,
        section=hit.citation.section,
        page_start=hit.citation.page_start,
        page_end=hit.citation.page_end,
        file=rec.file,
    )


def _search_line(hit: SearchHit) -> PackLine:
    return PackLine(
        text=hit.section.title or hit.section.file,
        citation=hit.citation.label,
        confidence=hit.confidence,
        matched_via=hit.matched_via,
        doc=hit.citation.doc,
        section=hit.citation.section,
        page_start=hit.citation.page_start,
        page_end=hit.citation.page_end,
    )


def _unavailable_line(question: str, reason: str) -> PackLine:
    """Degraded, not absent — and the difference is the un-droppable line.

    The record and figure paths ran and found nothing; the full-text path
    could not run at all. Reporting that as "no section answers this" would
    turn a missing index into a claim about the datasheet, which is the exact
    misreading `Retriever.search()` warns about.
    """
    asked = f" {question!r}" if question else ""
    return PackLine(
        text=(
            f"No spec record or figure answers{asked}, and the full-text path "
            f"could not run: {reason}. Whether the section text answers it is "
            "unknown — this corpus was not asked, and nothing was guessed."
        ),
        citation="",
        confidence=CONFIDENCE_UNKNOWN,
    )


def _no_match_line(question: str) -> PackLine:
    """The no-match statement is an answer line so it can never be dropped."""
    asked = f" {question!r}" if question else ""
    return PackLine(
        text=(
            f"No spec record, figure or section in this corpus answers{asked}. "
            "Nothing was guessed."
        ),
        citation="",
        confidence=CONFIDENCE_UNKNOWN,
    )


# --- excerpt and verify footer ----------------------------------------------


def _excerpt_for(
    retriever: Retriever, question: str, citation: Citation
) -> PackExcerpt | None:
    """The section covering the answer's page, quoted around the question."""
    section = _section_for(retriever, citation)
    if section is None:
        return None
    body = retriever.section_text(section)
    if not body:
        return None
    # `snippet` centres on the first term it finds, so hand it the question's
    # longest words first: "temperature" locates the row a designer asked
    # about, while "max" matches a MIN/MAX column header at the top of every
    # spec table. Length is a crude specificity proxy, but it is free and
    # deterministic — no corpus statistics, no per-part tuning.
    terms = sorted(set(tokenize(question)), key=lambda t: (-len(t), t))
    text = snippet(body, tuple(terms))
    if not text:
        return None
    return PackExcerpt(
        heading=_heading(section),
        citation=Citation.for_section(section).label,
        text=text,
    )


def _section_for(retriever: Retriever, citation: Citation) -> SectionFile | None:
    """The tightest section that covers the answer, preferring its own number.

    A printed page is covered by a whole chain of sections — `4
    Specifications` spans pages 4-133 and is usually an empty parent stub,
    while `4.1 Absolute Maximum Ratings` is the one that prints the answer. So
    the record's own section number wins when the manifest has it, and
    otherwise the narrowest page span does.
    """
    covering = (
        [h.section for h in retriever.sections(page=citation.page_start)]
        if citation.page_start is not None
        else []
    )
    if citation.section:
        exact = [s for s in covering if s.number == citation.section] or [
            h.section
            for h in retriever.sections(number=citation.section)
            if h.section.number == citation.section
        ]
        if exact:
            return _narrowest(exact)
    return _narrowest(covering) if covering else None


def _narrowest(sections: list[SectionFile]) -> SectionFile:
    """Tightest page span, then the corpus path — deterministic either way."""
    return min(
        sections,
        key=lambda s: (
            (s.page_end or s.page_start or 0) - (s.page_start or 0),
            s.file,
        ),
    )


def _heading(section: SectionFile) -> str:
    if section.number:
        return f"§{section.number} {section.title}".strip()
    return section.title or section.file


def _verify_record(retriever: Retriever, citation: Citation, confidence: str) -> str:
    """`Printed page 6 of afe7950.pdf.  Confidence: high.`"""
    source = _source_name(retriever, citation)
    if citation.page_start is None:
        where = f"No printed page is pinned for this answer — open {source}"
        if citation.section:
            where += f" at §{citation.section}"
        where += "."
    else:
        where = f"Printed {_pages(citation)} of {source}."
    line = f"{where}  Confidence: {confidence}."
    if confidence in ("low", CONFIDENCE_UNKNOWN):
        line += "  Open the printed page before relying on this value."
    return line


def _verify_text(retriever: Retriever, citation: Citation) -> str:
    source = _source_name(retriever, citation)
    if citation.page_start is None:
        return f"No printed page is pinned for this section — open {source}."
    return (
        f"Printed {_pages(citation)} of {source}.  Verbatim section text: a "
        "confidence grade belongs to an extracted record, not to quoted text."
    )


def _verify_unavailable() -> str:
    return (
        "One retrieval path never ran, so nothing here rules the answer out. "
        "Rebuild this part to enable full-text search, then ask again."
    )


def _verify_none() -> str:
    return (
        "Nothing was returned. This is an explicit no-match, not an empty "
        "answer — the corpus was not made to guess."
    )


def _pages(citation: Citation) -> str:
    if citation.page_end is not None and citation.page_end != citation.page_start:
        return f"pages {citation.page_start}-{citation.page_end}"
    return f"page {citation.page_start}"


def _source_name(retriever: Retriever, citation: Citation) -> str:
    """The printed document a page number refers to, as a filename.

    Falls back to the corpus document directory: a citation must always name
    *something* openable, and the directory is on disk even when the manifest
    is damaged.
    """
    manifest = retriever.index.manifest
    doc = None
    if manifest:
        doc = next(
            (d for d in manifest.documents if d.content_hash == citation.doc_hash), None
        )
        if doc is None and manifest.documents:
            doc = manifest.documents[0]
    if doc is not None and doc.path:
        return doc.path.replace("\\", "/").rsplit("/", 1)[-1]
    return citation.doc or "the source document"


# --- budget fitting ----------------------------------------------------------


def _fit(
    frame: AnswerPack,
    lines: list[PackLine],
    excerpt: PackExcerpt | None,
    verify: str,
    suggestions: list[str],
    notice: str,
) -> tuple[list[PackLine], PackExcerpt | None, bool]:
    """Greedy fill against the budget over a reserved tail.

    The reserved tail is `frame` + the **first** answer line + the verify
    footer + the notice: laid down before anything discretionary, so the
    citation-bearing parts are never what a budget removes. Extra answer rows
    are added in retrieval order while they fit, then the excerpt, trimmed to
    whatever remains and dropped entirely if its own frame does not fit.
    """

    def render(kept: list[PackLine], ex: PackExcerpt | None) -> int:
        return count_tokens(
            replace(
                frame,
                answers=tuple(kept),
                excerpt=ex,
                verify=verify,
                suggestions=tuple(suggestions),
                notice=notice,
            ).markdown
        )

    kept = lines[:1]
    for extra in lines[1:]:
        if render([*kept, extra], None) <= frame.budget:
            kept = [*kept, extra]
        else:
            break  # retrieval order is score order: after the first miss, stop

    kept_excerpt: PackExcerpt | None = None
    if excerpt is not None:
        if render(kept, excerpt) <= frame.budget:
            kept_excerpt = excerpt
        else:
            room = frame.budget - render(kept, replace(excerpt, text=""))
            trimmed = truncate_to_tokens(excerpt.text, room)
            if trimmed:
                kept_excerpt = replace(excerpt, text=trimmed)

    truncated = len(kept) < len(lines) or kept_excerpt != excerpt
    return kept, kept_excerpt, truncated


# --- declared JSON shape -----------------------------------------------------

_LINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "text", "citation", "confidence", "matched_via", "part", "doc", "section",
        "page_start", "page_end", "file",
    ],
    "properties": {
        "text": {"type": "string"},
        "citation": {"type": "string"},
        "confidence": {"enum": ["high", "medium", "low", CONFIDENCE_UNKNOWN]},
        "matched_via": {"type": "string"},
        "part": {"type": "string"},
        "doc": {"type": "string"},
        "section": {"type": "string"},
        "page_start": {"type": ["integer", "null"]},
        "page_end": {"type": ["integer", "null"]},
        "file": {"type": "string"},
    },
}

_EXCERPT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["heading", "citation", "text", "part"],
    "properties": {
        "heading": {"type": "string"},
        "citation": {"type": "string"},
        "text": {"type": "string"},
        "part": {"type": "string"},
    },
}

#: The one declared shape of `AnswerPack.as_dict()` — `dsa ask --json` and
#: (ticket 07) the MCP `ask` tool both emit exactly this.
ANSWER_PACK_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "dsa answer pack",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "part", "question", "route", "budget", "tokens", "over_budget",
        "truncated", "notice", "revision", "doc", "project", "parts",
        "answers", "excerpt", "verify", "suggestions", "citations", "markdown",
    ],
    "properties": {
        "part": {"type": "string"},
        "project": {"type": "string"},
        "parts": {"type": "array", "items": {"type": "string"}},
        "question": {"type": "string"},
        "route": {"enum": list(ROUTES)},
        "budget": {"type": "integer"},
        "tokens": {"type": "integer"},
        "over_budget": {"type": "boolean"},
        "truncated": {"type": "boolean"},
        "notice": {"type": "string"},
        "revision": {"type": "string"},
        "doc": {"type": "string"},
        "answers": {"type": "array", "items": _LINE_SCHEMA},
        "excerpt": {"anyOf": [_EXCERPT_SCHEMA, {"type": "null"}]},
        "verify": {"type": "string"},
        "suggestions": {"type": "array", "items": {"type": "string"}},
        "citations": {"type": "array", "items": {"type": "string"}},
        "markdown": {"type": "string"},
    },
}

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def validate_pack(payload: object, schema: dict | None = None, path: str = "$") -> list[str]:
    """Check `payload` against `ANSWER_PACK_SCHEMA`; `[]` means it validates.

    A deliberately small JSON-Schema subset (type, enum, anyOf, properties,
    required, items, and `additionalProperties` as either `false` or a schema)
    implemented here rather than pulled in as a dependency: the declared shape
    is part of the contract between this core and its front ends, and checking
    it must never depend on an optional package being installed.

    Schema-valued `additionalProperties` is phase 6's addition, and it exists
    for one shape: a derived card's `values` is keyed by *column name*, so the
    only way to declare what a card's cells are is to declare the schema every
    unlisted key must satisfy. Without it that node would have to be declared
    as "some object" — and a contract that stops describing the payload at the
    exact place the provenance envelope lives is not worth shipping to a
    client.
    """
    schema = ANSWER_PACK_SCHEMA if schema is None else schema
    errors: list[str] = []

    if "anyOf" in schema:
        if any(not validate_pack(payload, alt, path) for alt in schema["anyOf"]):
            return []
        return [f"{path}: matches none of the allowed shapes"]

    if "enum" in schema and payload not in schema["enum"]:
        errors.append(f"{path}: {payload!r} is not one of {schema['enum']}")

    expected = schema.get("type")
    if expected is not None:
        names = [expected] if isinstance(expected, str) else list(expected)
        allowed = tuple(_TYPES[n] for n in names)
        # bool is an int in Python; an integer field must not accept True.
        ok = isinstance(payload, allowed) and not (
            isinstance(payload, bool) and "boolean" not in names
        )
        if not ok:
            return [*errors, f"{path}: expected {'/'.join(names)}, got {type(payload).__name__}"]

    if isinstance(payload, dict) and ("properties" in schema or "additionalProperties" in schema):
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties")
        for key in schema.get("required", []):
            if key not in payload:
                errors.append(f"{path}.{key}: required key missing")
        for key in payload:
            if key in properties:
                continue
            if extra is False:
                errors.append(f"{path}.{key}: unexpected key")
            elif isinstance(extra, dict):
                errors.extend(validate_pack(payload[key], extra, f"{path}.{key}"))
        for key, sub in properties.items():
            if key in payload:
                errors.extend(validate_pack(payload[key], sub, f"{path}.{key}"))

    if isinstance(payload, list) and "items" in schema:
        for i, item in enumerate(payload):
            errors.extend(validate_pack(item, schema["items"], f"{path}[{i}]"))

    return errors
