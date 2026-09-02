"""The twelve agent tools (ticket 11), mirroring the MCP tool list.

`list_parts`, `list_projects`, `list_families`, `get_index`,
`get_family_index`, `search`, `find_spec`, `find_plots`, `read_section`,
`get_figure`, `ask`, `get_audit` — because the surface an agent needs does not
change with the transport.

Phase 5 froze the first nine. Phase 7 added `list_families`,
`get_family_index` and `get_audit` to the MCP surface and this one was left
behind, so a browser turn could be *scoped* to a family (`ScopeRef.kind`
carries it, `deps.get_retriever` resolves it) and had no tool that could read
one, and no way at all to grade a corpus before answering from it. The three
that MCP takes as arguments — `get_family_index(name)`, `get_audit(part)` —
take none here, for the reason below.

The four MCP tools this surface still does not carry are `find_pin`,
`find_register`, `get_card` and `compare_parts`. That is the workbench having
panes for them rather than an oversight: `compare_parts` in particular names
its own parts and would be a scope hole exactly like a `part` argument.

Every one is a **thin adapter over `retrieve/`**: no retrieval logic, no
citation formatting, no JSON shapes of its own. Results come from each hit's
own `as_dict()` and every citation from a `Citation`. If you find yourself
computing a page range or assembling a `p.N` label, you are in the wrong
module — the same constraint `TestMcpServerIsFormatOnly` enforces on the MCP
server, and `TestAgentToolsAreFormatOnly` enforces here.

**Nothing is imported from the MCP package.** Those bodies cap responses at
`DSA_MCP_MAX_TOKENS` because their consumer is a model reading over a wire;
these have a different budget (`settings.chat_tool_max_tokens`) and a
different truncation story — the browser renders full result sets, so the cap
is larger and the image is not base64 at all. Sharing them would mean
threading a budget parameter through everything to serve two consumers with
opposed needs. The logic worth sharing already lives in `retrieve/`; that is
the seam working as designed.

**Scope is injected, never chosen.** A tool receives an already-resolved
`Retriever`, `ProjectRetriever` or `FamilyRetriever`, not a name. Resolution
happened once, before the loop started (ticket 10), and the agent must not be
able to change scope mid-answer: the scope shown to the user has to be the
scope the answer came from. No tool takes a part, project **or family** name,
so there is no argument through which the agent could widen it — which is why
`get_family_index` here maps the series this turn is scoped to rather than one
the model names, and `get_audit` grades the corpus the answer will come from.

The four part-only tools reject a `ProjectRetriever` with a structured error
rather than an `AttributeError`: an index, a section file, a figure and a
scorecard each belong to one part, and "the project has no `index_markdown`"
is a stack trace, not an answer. `get_family_index` is that rule's mirror and
refuses anything that is not a family.

`FamilyRetriever` **subclasses** `ProjectRetriever`, so every `isinstance`
check here asks about the family first. With the checks the other way round a
series reports `kind: "project"` on every payload and every refusal calls it
a design — which is what this module did before phase 7's tools reached it.

Truncation at `chat_tool_max_tokens` is **always announced** in the payload.
Silent loss is the one failure an agent cannot detect, so a payload that had
to drop rows says which setting would bring them back.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datasheet_analyzer.app.contracts import PartOut, ProjectOut, ProjectPartOut
from datasheet_analyzer.config import Settings, get_settings
from datasheet_analyzer.projects import INDEX_FILENAME as PROJECT_INDEX_FILENAME
from datasheet_analyzer.projects import (
    ProjectError,
    is_built,
    load_project,
    project_dir,
)
from datasheet_analyzer.projects import list_projects as _project_names
from datasheet_analyzer.retrieve import (
    CONFIDENCE_UNKNOWN,
    INDEX_FILENAME,
    ProjectRetriever,
    Retriever,
    discover_parts,
)
from datasheet_analyzer.retrieve.family import FamilyRetriever
from datasheet_analyzer.tokens import count_tokens, truncate_to_tokens

#: A resolved scope: one part corpus, one project's member corpora, or one
#: declared family's. `FamilyRetriever` is a `ProjectRetriever` subclass, so
#: every `isinstance` check in this module asks about the **family** first —
#: getting that order wrong is how a family answer reports itself as a project.
Scope = Retriever | ProjectRetriever | FamilyRetriever

#: The tool surface, in the order the system prompt introduces it. Ticket 12
#: builds the runner's tool list from this, so a tool that is not named here
#: is not reachable by the agent.
TOOL_NAMES: tuple[str, ...] = (
    "list_parts",
    "list_projects",
    "list_families",
    "get_index",
    "get_family_index",
    "search",
    "find_spec",
    "find_plots",
    "read_section",
    "get_figure",
    "ask",
    "get_audit",
)

#: The four tools that need one part's corpus and cannot answer for a project
#: or a family: an index, a section file, a figure and a corpus scorecard all
#: belong to one part.
PART_ONLY_TOOLS: tuple[str, ...] = ("get_index", "read_section", "get_figure", "get_audit")

#: The one tool that needs a *family* scope. Its mirror image: `get_index` is
#: refused for a series, `get_family_index` is refused for anything else.
FAMILY_ONLY_TOOLS: tuple[str, ...] = ("get_family_index",)

#: The setting every truncation notice names. A notice that does not say how
#: to see the rest is only half a notice.
CAP_SETTING = "DSA_CHAT_TOOL_MAX_TOKENS"

#: Lowest `ask` budget the cap ladder falls to before it stops halving. Below
#: this a pack is nothing but its reserved citation tail.
ASK_BUDGET_FLOOR = 200

_CAP_NOTICE = (
    "Truncated to fit the {cap}-token tool budget — raise {setting} to see "
    "the rest, or narrow the query."
)
_ARG_NOTICE = (
    "Truncated to fit max_tokens={requested} — raise it (up to the "
    "{setting}={cap} tool budget) to see the rest."
)
_FLOOR_NOTICE = (
    "A {cap}-token tool budget ({setting}) is below this response's citation "
    "floor; the answer and its citation are kept regardless."
)
_BUDGET_NOTICE = (
    "Pack budget reduced from {wanted} to {attempt} tokens to fit the "
    "{cap}-token tool budget ({setting})."
)

_PART_ONLY_NOTICE = (
    "`{tool}` needs one part, but this turn is scoped to {kind} {name!r} "
    "({parts}). An index, a section file, a figure and a corpus scorecard each "
    "belong to a single part. Use `search`, `find_spec`, `find_plots` or "
    "`ask`, which do span a {kind}, or start a new turn scoped to one of its "
    "parts — a tool cannot change the scope it was given."
)

_FAMILY_ONLY_NOTICE = (
    "`{tool}` maps a declared series, but this turn is scoped to {kind} "
    "{name!r}. Start a new turn scoped to a family — `list_families` names "
    "the ones this machine has — because a tool cannot change the scope it "
    "was given, and a family index reads pages from every member."
)

#: Image types by extension — **data, not the host's configuration**, the same
#: rule the vendor brand lexicon and the alias lexicon follow.
#: `mimetypes.guess_type` seeds itself from the Windows registry
#: (`HKCR\\.png\\Content Type`), so the type the browser is handed for the very
#: same PNG would depend on the machine `dsa serve` happens to run on. These
#: are the extensions the publisher writes or downloads; anything else is
#: honestly opaque bytes rather than a guess.
FIGURE_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

#: The body keys `read_section` still owes a caller when it cannot answer.
_EMPTY_SECTION: dict[str, Any] = {
    "section": "",
    "title": "",
    "file": "",
    "part": "",
    "doc": "",
    "doc_hash": "",
    "page_start": None,
    "page_end": None,
    "citation": "",
    "confidence": CONFIDENCE_UNKNOWN,
    "matched_via": "",
    "text": "",
}

#: The body keys `get_figure` still owes a caller when it cannot answer. The
#: image is empty bytes rather than `None` so a caller never has to branch on
#: the type of the field it is about to read.
_EMPTY_FIGURE: dict[str, Any] = {
    "image": b"",
    "media_type": "",
    "bytes": 0,
    "figure": None,
}

__all__ = [
    "ASK_BUDGET_FLOOR",
    "CAP_SETTING",
    "FAMILY_ONLY_TOOLS",
    "FIGURE_MEDIA_TYPES",
    "PART_ONLY_TOOLS",
    "TOOLS",
    "TOOL_NAMES",
    "Scope",
    "ask",
    "find_plots",
    "find_spec",
    "get_audit",
    "get_family_index",
    "get_figure",
    "get_index",
    "list_families",
    "list_parts",
    "list_projects",
    "read_section",
    "search",
]

#: The body keys `get_family_index` still owes a caller when it cannot answer.
_EMPTY_FAMILY_INDEX: dict[str, Any] = {
    "family": "",
    "title": "",
    "members": [],
    "reference": "",
    "unbuilt": [],
    "file": "",
    "n_sections": 0,
    "n_shared_sections": 0,
    "n_deltas": 0,
    "n_specs_aligned": 0,
    "n_specs_identical": 0,
    "schema_version": "",
    "text": "",
}

#: The body keys `get_audit` still owes a caller when it cannot answer. `grade`
#: is `None` rather than `"F"`: a corpus nobody could read has not earned a
#: letter, and printing one would be the defamation the `n/a` rule forbids.
_EMPTY_AUDIT: dict[str, Any] = {
    "grade": None,
    "score": None,
    "rubric_version": "",
    "schema_version": "",
    "metrics": [],
    "n_graded": 0,
    "n_unavailable": 0,
    "unavailable_policy": "",
    "banner": "",
    "headline": "",
    "notes": [],
    "count": 0,
    "total": 0,
}


# --- the twelve tools ---------------------------------------------------------


def list_parts(*, settings: Settings | None = None) -> dict[str, Any]:
    """Every part corpus: revision, vendor, counts, confidence mix.

    Unbuilt parts are listed with `built: false` rather than hidden — a
    half-built corpus is visible instead of looking like a part that was never
    acquired.
    """
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    payload = _envelope("list_parts", max_tokens=cap)
    payload["parts"] = [_part_summary(d) for d in discover_parts(settings.parts_dir)]
    return _fit_list(payload, "parts", cap)


def list_projects(*, settings: Settings | None = None) -> dict[str, Any]:
    """Every project: its member parts, their roles, and whether built."""
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    payload = _envelope("list_projects", max_tokens=cap)
    payload["projects"] = [
        _project_summary(name, settings) for name in _project_names(settings.projects_dir)
    ]
    return _fit_list(payload, "projects", cap)


def list_families(*, settings: Settings | None = None) -> dict[str, Any]:
    """Every declared part family: its members, and whether each is built.

    Membership is read from `registry/families.yaml` and nowhere else. A
    grouping nobody has confirmed lives in the candidate file and is not listed
    here — proposing one is `dsa family suggest`, a local command deliberately
    not offered to the agent: nothing a model calls may widen the set of
    families this application will answer for.

    A catalog call, like `list_parts` and `list_projects`: it names what exists
    and quotes no datasheet, so it carries no citations and takes no scope.
    """
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    payload = _envelope("list_families", max_tokens=cap)
    registry = _load_families(settings)
    payload["families"] = [
        _family_summary(registry.families[name], settings) for name in registry.names
    ]
    return _fit_list(payload, "families", cap)


def get_family_index(*, scope: Scope, settings: Settings | None = None) -> dict[str, Any]:
    """The injected family's `FAMILY_INDEX.md` — one map for a whole series.

    `get_index` one noun across, and **derived live** from the members'
    published records rather than read off `families/<NAME>/`, for the reason
    a design card is built on demand: that directory is a cache of this call,
    not its source, so a turn never depends on whether somebody ran
    `dsa family build` first.

    It takes **no family name**. The series it maps is the one this turn was
    scoped to, because a `name` argument would be a hole in the promise the
    whole module rests on: a tool that could be handed `AFE795x` while the user
    was shown `AFE7950` would answer from a second datasheet's pages under the
    first one's label. A non-family scope is refused with the sentence that
    says so.

    A member with no corpus is named in `unbuilt` and contributes nothing; it
    is never silently dropped, because a family answer quietly missing one
    device reads as an answer for all of them.
    """
    from datasheet_analyzer.families import build_family_index, render_family_index
    from datasheet_analyzer.families.store import FAMILY_INDEX_FILENAME
    from datasheet_analyzer.retrieve.family import load_members

    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    refused = _refuse_non_family("get_family_index", scope, cap, **_EMPTY_FAMILY_INDEX)
    if refused is not None:
        return refused
    entry = _load_families(settings).families.get(scope.name)
    members = load_members(list(scope.parts), settings.parts_dir)
    index = build_family_index(
        members,
        name=scope.name,
        title=entry.title if entry is not None else "",
    )
    payload = _envelope("get_family_index", max_tokens=cap, scope=scope)
    payload["family"] = index.name
    payload["title"] = index.title
    payload["members"] = list(index.members)
    payload["reference"] = index.reference
    payload["unbuilt"] = [m.part_number for m in members if not m.built]
    payload["file"] = FAMILY_INDEX_FILENAME
    payload["n_sections"] = len(index.sections)
    payload["n_shared_sections"] = len(index.shared_sections)
    payload["n_deltas"] = index.n_deltas
    payload["n_specs_aligned"] = index.n_specs_aligned
    payload["n_specs_identical"] = index.n_specs_identical
    payload["schema_version"] = index.schema_version
    payload["warning"] = _unbuilt_warning(payload["unbuilt"])
    # Rendered under the *chat* budget rather than the file's own, because
    # that is the budget this reader pays; `render_family_index` degrades in
    # the order the family index declares rather than losing its tail to a
    # blind trim.
    payload["text"] = render_family_index(index, token_budget=cap)
    return _fit_text(payload, "text", cap)


def get_index(*, scope: Scope, settings: Settings | None = None) -> dict[str, Any]:
    """The part's `INDEX.md` — the always-loadable map of its corpus."""
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    refused = _refuse_project("get_index", scope, cap, revision="", file="", text="")
    if refused is not None:
        return refused
    payload = _envelope("get_index", max_tokens=cap, scope=scope)
    payload["revision"] = _revision(scope)
    payload["file"] = INDEX_FILENAME
    payload["text"] = scope.index_markdown()
    return _fit_text(payload, "text", cap)


def search(
    *, scope: Scope, query: str, limit: int = 5, settings: Settings | None = None
) -> dict[str, Any]:
    """BM25 full-text search over the scope. Every hit is cited by construction.

    A corpus with no current index is an error, not an empty result: "could
    not look" and "not in the datasheet" are different answers, and only the
    second one is a claim about the device.
    """
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    unavailable = scope.search_unavailable()
    if unavailable:
        return _error("search", unavailable, max_tokens=cap, scope=scope, hits=[], count=0, total=0)
    payload = _envelope("search", max_tokens=cap, scope=scope)
    # A design where only *some* members are searchable can still answer; what
    # it must not do is let the result read as the whole design. That is a
    # warning, not an error: the call succeeded, the coverage did not.
    payload["warning"] = getattr(scope, "search_gap", lambda: "")()
    payload["hits"] = [hit.as_dict() for hit in scope.search(query, limit=limit)]
    return _fit_list(payload, "hits", cap)


def find_spec(
    *,
    scope: Scope,
    symbol: str = "",
    name: str = "",
    section: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """The alias ladder over parametric records; `matched_via` names the rung.

    Each hit carries its own `confidence` and `matched_via` through unchanged:
    the grade is the record's, computed at structure time, and the rung is the
    retriever's. Neither is recomputed, and neither is used to drop or reorder
    a hit. No match returns an empty list plus nearest candidates, never a
    guess.
    """
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    hits = scope.specs(symbol=symbol, name=name, section=section)
    payload = _envelope("find_spec", max_tokens=cap, scope=scope)
    payload["hits"] = [hit.as_dict() for hit in hits]
    payload["suggestions"] = [] if hits else scope.suggest_specs((symbol or name).strip())
    return _fit_list(payload, "hits", cap)


def find_plots(
    *,
    scope: Scope,
    q: str = "",
    section: str = "",
    tags: list[str] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Filter the plot catalog — the narrowing step before `get_figure`."""
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    payload = _envelope("find_plots", max_tokens=cap, scope=scope)
    payload["hits"] = [
        hit.as_dict() for hit in scope.plots(q=q, section=section, tags=list(tags or []))
    ]
    return _fit_list(payload, "hits", cap)


def read_section(
    *, scope: Scope, ref: str, max_tokens: int = 0, settings: Settings | None = None
) -> dict[str, Any]:
    """One section verbatim, bounded by `chat_tool_max_tokens`.

    `ref` is a section number, a corpus-relative file path, or a title
    substring — whichever the caller has. Two limits can bind and they bind
    different things: the caller's own `max_tokens` bounds the text it asked
    to read, and `chat_tool_max_tokens` bounds the whole payload. Whichever
    bit, the notice names it; neither ever cuts silently.
    """
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    refused = _refuse_project("read_section", scope, cap, **_EMPTY_SECTION)
    if refused is not None:
        return refused
    hit = scope.resolve_section(ref)
    if hit is None:
        return _error(
            "read_section",
            f"no section matching {ref!r} in part {scope.part} — list them with `get_index`",
            max_tokens=cap,
            scope=scope,
            **_EMPTY_SECTION,
        )
    payload = _envelope("read_section", max_tokens=cap, scope=scope)
    body = _section_body(hit)
    payload.update(body)
    payload["citations"] = _citations_of([body])
    payload["text"] = scope.section_text(hit.section)
    return _fit_text(payload, "text", cap, requested=max_tokens)


def get_figure(*, scope: Scope, file: str, settings: Settings | None = None) -> dict[str, Any]:
    """One cataloged figure's bytes plus its media type, caption and citation.

    Returns `{"image": bytes, "media_type": str, "figure": {...}}` so ticket 12
    can build an image content block without deciding anything about the file
    itself. A path outside the part directory, or a file no plot record
    claims, is a structured error rather than an exception — an uncited image
    is not an answer, and a refusal an agent can read beats a traceback it
    cannot.

    The image is **atomic**: the token budget governs the JSON beside it, not
    the pixels. Trimming an image produces a corrupt file, not a smaller one.
    """
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    refused = _refuse_project("get_figure", scope, cap, **_EMPTY_FIGURE)
    if refused is not None:
        return refused

    # Path safety is checked first and on the *caller's* string, so an attempt
    # to leave the part directory is refused for that reason and told so — not
    # silently re-labelled "no such figure".
    if scope.corpus_path(file) is None:
        return _figure_error(
            f"refused {file!r}: a figure path must stay inside the part "
            "directory (relative, no '..', no absolute paths)",
            scope=scope,
            cap=cap,
        )
    hit = scope.plot_for_file(file)
    if hit is None:
        return _figure_error(
            f"no cataloged figure {file!r} in part {scope.part} — narrow the "
            "catalog with `find_plots` and pass a hit's `file`",
            scope=scope,
            cap=cap,
        )
    # Read what the *catalog* recorded, not what the caller typed: the bytes
    # returned must be the ones the citation below refers to.
    path = scope.corpus_path(hit.file)
    if path is None:
        return _figure_error(
            f"the catalog records an unusable path for {hit.record.id} "
            f"({hit.file!r}) — rebuild the part",
            scope=scope,
            cap=cap,
        )
    try:
        blob = path.read_bytes()
    except OSError as exc:
        return _figure_error(
            f"figure {hit.file} is cataloged but not on disk ({exc}) — rebuild "
            "the part to render its images",
            scope=scope,
            cap=cap,
        )

    payload = _envelope("get_figure", max_tokens=cap, scope=scope)
    payload["image"] = blob
    payload["media_type"] = _media_type(path)
    payload["bytes"] = len(blob)
    payload["figure"] = hit.as_dict()
    payload["citations"] = _citations_of([payload["figure"]])
    return _finalize(payload, cap)


def ask(
    *, scope: Scope, question: str, budget: int = 0, settings: Settings | None = None
) -> dict[str, Any]:
    """One cited answer pack for the question, inside its token budget.

    A pack protects its own citations against its own budget, so the way to
    make one smaller is to *ask for a smaller pack* — never to delete rows
    from the pack it returned, which would strip citations it had deliberately
    reserved. The budget therefore halves until the payload fits, and the
    reduction is announced.
    """
    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    wanted = max(budget if budget > 0 else settings.ask_budget, 1)
    attempt = min(wanted, cap)
    while True:
        pack = scope.ask(question, budget=attempt)
        payload = _envelope("ask", max_tokens=cap, scope=scope)
        payload["pack"] = pack.as_dict()
        payload["citations"] = list(pack.citations)
        # `truncated` is the pack's own answer: a budget lowered to fit the cap
        # that still dropped nothing has truncated nothing, and saying
        # otherwise would train a caller to ignore the flag.
        payload["truncated"] = pack.truncated
        notes = []
        if attempt < wanted:
            notes.append(
                _BUDGET_NOTICE.format(wanted=wanted, attempt=attempt, cap=cap, setting=CAP_SETTING)
            )
        if pack.notice:
            notes.append(pack.notice)
        payload["notice"] = " ".join(notes)
        if _payload_tokens(payload) <= cap or attempt <= ASK_BUDGET_FLOOR:
            return _finalize(payload, cap)
        attempt = max(ASK_BUDGET_FLOOR, attempt // 2)


def get_audit(*, scope: Scope, settings: Settings | None = None) -> dict[str, Any]:
    """Grade the scoped corpus before answering from it: readings and a letter.

    `dsa audit` on the chat surface. Every reading is a count of records the
    corpus already published divided by another — no model is called anywhere
    on this path — and the thresholds are checked-in data
    (`registry/audit_rubric.yaml`), so a disagreement about a grade is a YAML
    edit rather than an argument with this tool.

    `headline` is the sentence the whole artifact exists to produce: one line
    to put in front of an answer to downgrade its own confidence language
    before speaking. A metric that could not be measured is `available: false`
    with a reason, is excluded from the overall letter, and is never reported
    as `0`; `grade` is null when too few metrics could be computed for an
    average to mean anything.

    Part-scoped, and it takes no part name: a scorecard is a statement about
    one published corpus, and the corpus it grades has to be the one the answer
    will come from.
    """
    from datasheet_analyzer.audit import build_scorecard
    from datasheet_analyzer.evalh.golden import default_golden_path

    settings = _settings(settings)
    cap = settings.chat_tool_max_tokens
    refused = _refuse_project("get_audit", scope, cap, **_EMPTY_AUDIT)
    if refused is not None:
        return refused
    card = build_scorecard(scope.part_dir, golden=default_golden_path(scope.part))
    payload = _envelope("get_audit", max_tokens=cap, scope=scope)
    payload["grade"] = card.grade.value if card.grade else None
    payload["score"] = card.score
    payload["rubric_version"] = card.rubric_version
    payload["schema_version"] = card.schema_version
    payload["metrics"] = [m.model_dump(mode="json") for m in card.metrics]
    payload["n_graded"] = card.n_graded
    payload["n_unavailable"] = card.n_unavailable
    payload["unavailable_policy"] = card.unavailable_policy
    payload["banner"] = card.banner
    payload["headline"] = card.headline
    payload["notes"] = list(card.notes)
    return _fit_list(payload, "metrics", cap)


#: Name -> callable, in `TOOL_NAMES` order. The registry ticket 12 iterates.
TOOLS: dict[str, Any] = {
    "list_parts": list_parts,
    "list_projects": list_projects,
    "list_families": list_families,
    "get_index": get_index,
    "get_family_index": get_family_index,
    "search": search,
    "find_spec": find_spec,
    "find_plots": find_plots,
    "read_section": read_section,
    "get_figure": get_figure,
    "ask": ask,
    "get_audit": get_audit,
}


# --- scope -------------------------------------------------------------------


def _settings(settings: Settings | None) -> Settings:
    return settings or get_settings()


def _scope_ref(scope: Scope | None) -> dict[str, Any]:
    """The scope, as the payload reports it back — never as an argument in.

    `kind` is `ScopeRef.kind`'s vocabulary (`part | project | family`), so what
    a tool result says answered the turn is the same noun the `scope` frame
    showed the user before the loop started. The family branch comes **first**
    because `FamilyRetriever` subclasses `ProjectRetriever`: with the checks
    the other way round a series reports itself as a design, and every refusal
    below calls it one.
    """
    if scope is None:
        return {"kind": "", "name": "", "parts": []}
    if isinstance(scope, FamilyRetriever):
        return {"kind": "family", "name": scope.name, "parts": list(scope.parts)}
    if isinstance(scope, ProjectRetriever):
        return {"kind": "project", "name": scope.name, "parts": list(scope.parts)}
    return {"kind": "part", "name": scope.part, "parts": [scope.part]}


def _refuse_project(tool: str, scope: Scope, cap: int, **body: Any) -> dict[str, Any] | None:
    """`None` for a part scope; a structured refusal for a multi-part scope.

    Asked before anything touches the scope object, so a project never reaches
    a `Retriever`-only attribute and the caller reads a sentence instead of an
    `AttributeError`. The refusal names the scope by the kind it actually is:
    telling a user their family is a project is a small lie, and it is the
    same lie `_scope_ref` used to tell.
    """
    if not isinstance(scope, ProjectRetriever):
        return None
    return _error(
        tool,
        _PART_ONLY_NOTICE.format(
            tool=tool,
            kind=_scope_ref(scope)["kind"],
            name=scope.name,
            parts=", ".join(scope.parts) or "no member parts",
        ),
        max_tokens=cap,
        scope=scope,
        **body,
    )


def _refuse_non_family(tool: str, scope: Scope, cap: int, **body: Any) -> dict[str, Any] | None:
    """`None` for a family scope; a structured refusal for anything else.

    `_refuse_project` one noun across, and the mirror of the same rule: a tool
    answers at the scope it was handed or says why it cannot, and never widens
    one part into the series it happens to belong to.
    """
    if isinstance(scope, FamilyRetriever):
        return None
    ref = _scope_ref(scope)
    return _error(
        tool,
        _FAMILY_ONLY_NOTICE.format(tool=tool, kind=ref["kind"] or "nothing", name=ref["name"]),
        max_tokens=cap,
        scope=scope,
        **body,
    )


def _load_families(settings: Settings):
    """The declared family registry, read from `registry/families.yaml`.

    A read, not a decision: `families.registry` owns what a family *is*, and
    this application only reports what it finds there. Imported at call time
    like every other optional reach, so `app/tools.py` stays importable.
    """
    from datasheet_analyzer.families import load_families
    from datasheet_analyzer.families.registry import families_path

    return load_families(families_path(settings.registry_dir))


def _family_summary(entry: Any, settings: Settings) -> dict[str, Any]:
    """One `list_families` row, with each member's built state.

    No `error` key, unlike `_project_summary`: a project is a file that can
    fail to load, while a family is one entry in a registry this call has
    already loaded whole. There is nothing left to go wrong per row.
    """
    from datasheet_analyzer.families.store import FAMILY_INDEX_FILENAME

    return {
        "name": entry.name,
        "title": entry.title,
        "members": [
            {"part": member, "built": is_built(member, settings.parts_dir)}
            for member in entry.members
        ],
        "reference": entry.reference,
        "confirmed": entry.confirmed,
        "note": entry.note,
        "built": (settings.families_dir / entry.name / FAMILY_INDEX_FILENAME).exists(),
    }


def _unbuilt_warning(parts: list[str]) -> str:
    """The warning a family answer carries when a member has no corpus.

    `retrieve.scope.missing_corpus_warning` is that wording, written once; a
    second phrasing here would be a second promise about what is missing.
    """
    from datasheet_analyzer.retrieve.scope import missing_corpus_warning

    return missing_corpus_warning(parts)


def _revision(scope: Retriever) -> str:
    """The datasheet revision this corpus was built from; `""` when unknown."""
    manifest = scope.index.manifest
    if manifest is None or not manifest.documents:
        return ""
    return manifest.documents[0].revision


# --- catalog rows -------------------------------------------------------------


def _part_summary(part_dir: Path) -> dict[str, Any]:
    """One `list_parts` row, in the frozen `PartOut` shape."""
    scope = Retriever.for_part(part_dir)
    manifest = scope.index.manifest
    if manifest is None:
        return PartOut(part_number=part_dir.name).model_dump(mode="json")
    stats = manifest.stats
    return PartOut(
        part_number=manifest.part_number or part_dir.name,
        built=True,
        revision=_revision(scope),
        vendor=manifest.vendor,
        backends=list(
            dict.fromkeys(st.backend for st in manifest.extraction_stats.values() if st.backend)
        ),
        sections=stats.n_sections,
        specs=stats.n_specs,
        plots=stats.n_plot_files,
        tokens=stats.total_tokens,
        searchable=not scope.search_unavailable(),
        spec_confidence=dict(stats.spec_confidence),
        plot_confidence=dict(stats.plot_confidence),
    ).model_dump(mode="json")


def _project_summary(name: str, settings: Settings) -> dict[str, Any]:
    """One `list_projects` row, in the frozen `ProjectOut` shape."""
    try:
        project = load_project(name, settings.projects_dir)
    except ProjectError as exc:
        return ProjectOut(name=name, error=str(exc)).model_dump(mode="json")
    return ProjectOut(
        name=project.name,
        parts=[
            ProjectPartOut(
                part_number=member.part_number,
                role=member.role,
                built=is_built(member.part_number, settings.parts_dir),
            )
            for member in project.parts
        ],
        interfaces=project.interfaces,
        notes=project.notes,
        built=(project_dir(project.name, settings.projects_dir) / PROJECT_INDEX_FILENAME).exists(),
    ).model_dump(mode="json")


def _section_body(hit: Any) -> dict[str, Any]:
    """A resolved section as JSON, from the hit's own view of itself.

    `SectionHit.as_dict()` is ticket 05's addition to `retrieve/results.py`.
    Until it lands the same fields are read straight off the hit and its
    `Citation` — field access, not formatting: the citation string is still
    the `Citation`'s own `label`, exactly as it is everywhere else.
    """
    as_dict = getattr(hit, "as_dict", None)
    if callable(as_dict):
        return dict(as_dict())
    citation = hit.citation
    return {
        "section": hit.section.number,
        "title": hit.section.title,
        "file": hit.section.file,
        "part": citation.part,
        "doc": citation.doc,
        "doc_hash": citation.doc_hash,
        "page_start": citation.page_start,
        "page_end": citation.page_end,
        "citation": citation.label,
        "matched_via": hit.matched_via,
        "confidence": hit.confidence,
    }


def _media_type(path: Path) -> str:
    """The image type of a cataloged figure, read from its own extension."""
    return FIGURE_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


# --- payload shape and the tool budget ---------------------------------------


def _envelope(tool: str, *, max_tokens: int, scope: Scope | None = None) -> dict[str, Any]:
    """The keys every tool response carries, whatever the tool.

    `tokens` starts at `max_tokens` as a placeholder and stays that way while
    the payload is fitted, because the field's own width must not change the
    fit. The final value can only be smaller, which makes the reported
    `tokens` an honest upper bound rather than a figure measured on a payload
    that no longer exists.
    """
    return {
        "tool": tool,
        "scope": _scope_ref(scope),
        "error": "",
        # `error` means the call could not be answered; `warning` means it was
        # answered but something about the result is incomplete (a project
        # member with no search index, say). Conflating the two is how an
        # agent ends up reporting a gap as an absence.
        "warning": "",
        "max_tokens": max_tokens,
        "tokens": max_tokens,
        "truncated": False,
        "over_cap": False,
        "notice": "",
        "citations": [],
    }


def _error(
    tool: str, message: str, *, max_tokens: int, scope: Scope | None = None, **body: Any
) -> dict[str, Any]:
    """A refused call in the declared shape, with the reason in `error`.

    Refusals are payloads, not exceptions, so an agent reads *why* in the same
    structure it reads an answer from — and the empty body says plainly that
    nothing was found, rather than a traceback implying something broke.
    """
    payload = _envelope(tool, max_tokens=max_tokens, scope=scope)
    payload["error"] = message
    payload.update(body)
    return _finalize(payload, max_tokens)


def _figure_error(message: str, *, scope: Scope, cap: int) -> dict[str, Any]:
    return _error("get_figure", message, max_tokens=cap, scope=scope, **_EMPTY_FIGURE)


def _citations_of(items: list) -> list[str]:
    """Every citation the returned items carry, in order, de-duplicated.

    Hoisted to the envelope so a caller can check "is this response cited?"
    without walking a body whose shape differs per tool. Items that are not
    corpus findings (a part listing, a project listing) contribute none, and
    the empty list is the honest answer there rather than a fabricated one.
    """
    out: list[str] = []
    for item in items:
        cite = item.get("citation", "") if isinstance(item, dict) else ""
        if cite and cite not in out:
            out.append(cite)
    return out


def _jsonable(payload: dict) -> dict:
    """The payload as JSON sees it — the image counted, not serialized."""
    image = payload.get("image")
    if isinstance(image, (bytes, bytearray)):
        return {**payload, "image": f"<{len(image)} bytes>"}
    return payload


def _payload_tokens(payload: dict) -> int:
    """Size of a payload as the chat loop will spend it."""
    return count_tokens(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2))


def _finalize(payload: dict, cap: int) -> dict[str, Any]:
    """Stamp the measured size and whether the payload still exceeds the cap."""
    measured = _payload_tokens(payload)
    payload["over_cap"] = measured > cap
    if payload["over_cap"] and not payload["notice"]:
        payload["notice"] = _FLOOR_NOTICE.format(cap=cap, setting=CAP_SETTING)
        measured = _payload_tokens(payload)
    payload["tokens"] = measured
    return payload


def _fit_list(payload: dict, key: str, cap: int) -> dict[str, Any]:
    """Fill `payload[key]` greedily in retrieval order until the cap bites.

    Retrieval order *is* score order everywhere in this project, so filling
    from the front and stopping at the first item that does not fit keeps the
    best hits and drops the weakest — and each surviving hit keeps its own
    citation, because a hit is dropped whole or not at all. `total` against
    `count` is how the caller sees that something was dropped even before it
    reads the notice.
    """
    items = list(payload.get(key) or [])

    def shaped(kept: list, notice: str) -> dict:
        out = dict(payload)
        out[key] = kept
        out["total"] = len(items)
        out["count"] = len(kept)
        out["citations"] = _citations_of(kept)
        out["notice"] = notice
        out["truncated"] = bool(notice)
        return out

    def fill(notice: str) -> list:
        kept: list = []
        for item in items:
            if _payload_tokens(shaped([*kept, item], notice)) <= cap:
                kept.append(item)
            else:
                break  # retrieval order is score order: after a miss, stop
        return kept

    kept = fill("")
    notice = ""
    if len(kept) < len(items):
        # One re-fit, not a loop: the notice text depends only on the cap, so
        # adding it can shrink the fill but can never change its own text.
        notice = _CAP_NOTICE.format(cap=cap, setting=CAP_SETTING)
        kept = fill(notice)
    return _finalize(shaped(kept, notice), cap)


def _fit_text(payload: dict, key: str, cap: int, *, requested: int = 0) -> dict[str, Any]:
    """Trim `payload[key]` to the binding limit and announce it if trimmed.

    The caller's `max_tokens` is a *reading* budget and the cap is a *payload*
    budget; the citation, the page range and the section heading are the
    reserved tail in both cases, because a budget must never be paid for by
    deleting the provenance of the thing it bounded.
    """
    text = payload.get(key) or ""

    def shaped(body: str, notice: str) -> dict:
        out = dict(payload)
        out[key] = body
        out["notice"] = notice
        out["truncated"] = bool(notice)
        return out

    notice = ""
    if requested > 0 and count_tokens(text) > requested:
        text = truncate_to_tokens(text, requested)
        notice = _ARG_NOTICE.format(requested=requested, cap=cap, setting=CAP_SETTING)

    if _payload_tokens(shaped(text, notice)) > cap:
        notice = _CAP_NOTICE.format(cap=cap, setting=CAP_SETTING)
        room = cap - _payload_tokens(shaped("", notice))
        text = truncate_to_tokens(text, room)
        # JSON escaping (a newline is two characters on the wire, a quote is
        # two) makes an encoded body longer than the text it holds, so the
        # estimate is corrected against the real payload rather than trusted.
        while text and _payload_tokens(shaped(text, notice)) > cap:
            room -= 1
            text = truncate_to_tokens(text, room)

    return _finalize(shaped(text, notice), cap)
