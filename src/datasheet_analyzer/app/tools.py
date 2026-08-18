"""The nine agent tools (ticket 11), mirroring the MCP tool list.

`list_parts`, `list_projects`, `get_index`, `search`, `find_spec`,
`find_plots`, `read_section`, `get_figure`, `ask` — the same nine the MCP
server exposes, because the surface an agent needs does not change with the
transport.

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
`Retriever` or `ProjectRetriever`, not a `part`/`project` string pair.
Resolution happened once, before the loop started (ticket 10), and the agent
must not be able to change scope mid-answer: the scope shown to the user has
to be the scope the answer came from. No tool takes a part or project name,
so there is no argument through which the agent could widen it.

The three part-only tools reject a `ProjectRetriever` with a structured error
rather than an `AttributeError`: an index, a section file and a figure each
belong to one part, and "the project has no `index_markdown`" is a stack
trace, not an answer.

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
from datasheet_analyzer.tokens import count_tokens, truncate_to_tokens

#: A resolved scope: one part corpus, or one project's member corpora.
Scope = Retriever | ProjectRetriever

#: The tool surface, in the order the system prompt introduces it. Ticket 12
#: builds the runner's tool list from this, so a tool that is not named here
#: is not reachable by the agent.
TOOL_NAMES: tuple[str, ...] = (
    "list_parts",
    "list_projects",
    "get_index",
    "search",
    "find_spec",
    "find_plots",
    "read_section",
    "get_figure",
    "ask",
)

#: The three tools that need one part's corpus and cannot answer for a
#: project: an index, a section file and a figure all belong to one part.
PART_ONLY_TOOLS: tuple[str, ...] = ("get_index", "read_section", "get_figure")

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
    "`{tool}` needs one part, but this turn is scoped to project {name!r} "
    "({parts}). An index, a section file and a figure each belong to a single "
    "part. Use `search`, `find_spec`, `find_plots` or `ask`, which do span a "
    "project, or start a new turn scoped to one of its parts — a tool cannot "
    "change the scope it was given."
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
    "FIGURE_MEDIA_TYPES",
    "PART_ONLY_TOOLS",
    "TOOLS",
    "TOOL_NAMES",
    "Scope",
    "ask",
    "find_plots",
    "find_spec",
    "get_figure",
    "get_index",
    "list_parts",
    "list_projects",
    "read_section",
    "search",
]


# --- the nine tools -----------------------------------------------------------


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


#: Name -> callable, in `TOOL_NAMES` order. The registry ticket 12 iterates.
TOOLS: dict[str, Any] = {
    "list_parts": list_parts,
    "list_projects": list_projects,
    "get_index": get_index,
    "search": search,
    "find_spec": find_spec,
    "find_plots": find_plots,
    "read_section": read_section,
    "get_figure": get_figure,
    "ask": ask,
}


# --- scope -------------------------------------------------------------------


def _settings(settings: Settings | None) -> Settings:
    return settings or get_settings()


def _scope_ref(scope: Scope | None) -> dict[str, Any]:
    """The scope, as the payload reports it back — never as an argument in."""
    if scope is None:
        return {"kind": "", "name": "", "parts": []}
    if isinstance(scope, ProjectRetriever):
        return {"kind": "project", "name": scope.name, "parts": list(scope.parts)}
    return {"kind": "part", "name": scope.part, "parts": [scope.part]}


def _refuse_project(tool: str, scope: Scope, cap: int, **body: Any) -> dict[str, Any] | None:
    """`None` for a part scope; a structured refusal for a project scope.

    Asked before anything touches the scope object, so a project never reaches
    a `Retriever`-only attribute and the caller reads a sentence instead of an
    `AttributeError`.
    """
    if not isinstance(scope, ProjectRetriever):
        return None
    return _error(
        tool,
        _PART_ONLY_NOTICE.format(
            tool=tool,
            name=scope.name,
            parts=", ".join(scope.parts) or "no member parts",
        ),
        max_tokens=cap,
        scope=scope,
        **body,
    )


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
