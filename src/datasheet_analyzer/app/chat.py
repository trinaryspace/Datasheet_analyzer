"""The agentic chat loop and its token stream (ticket 12).

One question in, a stream of `ChatEvent`s out. The loop itself is the
Anthropic SDK's **Tool Runner** (`client.beta.messages.tool_runner(...,
stream=True)`) over `app/tools.py`'s registry — the request -> execute ->
feed-back cycle is the SDK's job, and this module's job is the two promises a
cited answer rests on:

**Scope is fixed before the first model call and cannot change.** It is
resolved once (ticket 10), emitted as the stream's first frame, and the
already-resolved retriever is *injected into the tools*, so no tool takes a
`part`, `project` or `family` argument and the agent has no way to widen or
move the scope mid-answer. An ambiguous resolution never starts a loop at all:
the candidates go out on the `scope` frame and the turn ends, so the UI can
ask. The two phase-7 tools that name their subject over MCP —
`get_family_index(name)` and `get_audit(part)` — therefore name nothing here:
they read the scope this turn was given.

**Citations are extracted structurally, never parsed out of prose.** Every
`citation` frame is built from a `Citation` living inside a tool result the
runner actually executed (see `collect_citations`). A citation the model
invented in its text has no tool result behind it and therefore produces no
frame — which is the whole point: an answer's citations are what it *read*,
not what it *wrote*.

Two smaller rules that are easy to get wrong and expensive to debug:

- **`thinking` is never disabled anywhere in this path.** On `claude-opus-5`
  thinking is on by default, and disabling it can make the model emit a tool
  call as plain text that silently never runs — a turn that looks successful
  and did nothing. The request simply omits the parameter.
- **The cache breakpoint sits after the system prompt.** Render order is
  `tools` -> `system` -> `messages`, so one `cache_control` on the last system
  block caches the tool definitions *and* the prompt; the volatile question
  lives in `messages`, after it, and never carries a breakpoint of its own.
"""

from __future__ import annotations

import base64
import functools
import inspect
import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import anyio
from anthropic import beta_async_tool

from datasheet_analyzer.app.contracts import ChatEvent, ScopeResolution
from datasheet_analyzer.config import Settings, get_settings
from datasheet_analyzer.models import ChatMessage, CitationOut, ScopeRef
from datasheet_analyzer.retrieve.results import MIN_NEEDLE_CHARS, Citation

log = logging.getLogger(__name__)

__all__ = [
    "MAX_TOOL_ITERATIONS",
    "SYSTEM_PROMPT",
    "build_client",
    "build_params",
    "build_tools",
    "collect_citations",
    "known_scopes",
    "resolve_question",
    "stream_turn",
    "system_blocks",
    "tool_summary",
]

#: Hard cap on request -> tool -> request cycles in one turn. A loop that has
#: not answered after this many rounds is stuck, and an unbounded agent loop
#: on a local machine is a runaway bill rather than an answer.
MAX_TOOL_ITERATIONS = 12

#: What the UI shows when nothing in the question named a known part.
NO_SCOPE_MESSAGE = "Pick a part or project and ask again — nothing here named one."

SYSTEM_PROMPT = """\
You answer questions about electronic component datasheets from a corpus that
has already been extracted, structured and indexed. You have tools that read
that corpus; you have no other source of truth.

Every factual claim must come from a tool result. If the tools do not contain
the answer, say so plainly and name what you looked for — an honest miss is a
useful answer and a guess is not. Never state a specification, a limit, a
pin function or a page number that you did not read from a tool result.

Quote a citation exactly as the tool result gives it. Do not renumber pages,
do not infer a section from a heading you did not read, and do not attach a
citation to a claim it does not support: the citations shown next to your
answer are collected from the tool results themselves, so a citation you
write in prose that no tool returned is simply wrong.

Cite each claim where you make it, not in a list at the end. Put the citation
in square brackets immediately after the sentence, the value or the table row
it supports — `The noise figure is 1.2 dB [§7.2, p.14].` The reader clicks a
citation to open that page, so a citation parked at the bottom of the answer
does not tell them which of five numbers it belongs to. A single claim drawn
from two places carries both. Reuse the exact label the tool gave you, because
only a label that matches one becomes a clickable link — anything else stays
dead text on the page.

When a plot bears on the quantity you were asked about, say so and cite it in
the same way, right after the number it qualifies: a measured value and the
curve it was taken from are one answer, not two. Run `find_plots` for a
quantity that is normally plotted against frequency, temperature, supply or
bias even when `find_spec` has already answered — a table value at one
condition, with no mention that the curve exists, reads as if the value held
everywhere.

Work the corpus in the order that costs least: the index and a search before
a full section read. Prefer the specific tool (`find_spec` for a parametric
value, `find_plots` for a curve) over reading whole sections.

Answer the question that was asked, at the scope you were given. Lead with the
value or the finding, then the qualifying conditions, then anything the reader
should check on the page. Keep it to what an engineer needs; do not pad.\
"""


# --- prompt assembly ----------------------------------------------------------


def system_blocks(scope: ScopeRef) -> list[dict[str, Any]]:
    """The system prompt as cacheable text blocks, breakpoint on the last.

    Two blocks: the frozen instructions, then the resolved scope. The
    `cache_control` marker goes on the *last* one because the render order is
    `tools` -> `system` -> `messages` — one breakpoint there covers the tool
    definitions as well, and everything volatile (the question) sits after it.
    """
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {
            "type": "text",
            "text": (
                f"Scope for this conversation: {scope.label}.\n"
                "Every tool you have is already bound to this scope. You cannot "
                "read another part, and you must not answer from one."
            ),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _history_params(history: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """Earlier turns of this session as plain message params."""
    return [{"role": message.role, "content": message.text} for message in history if message.text]


def build_params(
    *,
    question: str,
    scope: ScopeRef,
    settings: Settings | None = None,
    history: Sequence[ChatMessage] = (),
) -> dict[str, Any]:
    """The request the tool runner drives, minus the tools.

    Deliberately carries **no `thinking` key**: the model's default is what we
    want, and passing `{"type": "disabled"}` here is the failure mode where a
    tool call arrives as prose and never runs.
    """
    settings = settings or get_settings()
    return {
        "model": settings.chat_model,
        "max_tokens": settings.chat_max_tokens,
        "system": system_blocks(scope),
        "messages": [
            *_history_params(history),
            {"role": "user", "content": question},
        ],
    }


# --- citations ----------------------------------------------------------------


def _is_citation(value: object) -> bool:
    """Duck-typed `retrieve.results.Citation`: the fields plus the two derived."""
    if isinstance(value, (str, bytes, Mapping)):
        return False
    return all(
        hasattr(value, name) for name in ("doc", "doc_hash", "section", "page_start", "label")
    )


def _paragraph_gap(answer: list[str]) -> str:
    """The break between one model turn's prose and the next turn's.

    Each tool round trip is its own assistant message, and the text of the
    second begins exactly where the first stopped — so a turn that opens with
    a markdown heading (`## Receiver noise figure`) lands mid-line and renders
    as literal hashes rather than a heading. Emits only the newlines that are
    actually missing, so a model that already ended its turn cleanly does not
    gain a second blank line.
    """
    so_far = "".join(answer)
    if not so_far.strip() or so_far.endswith("\n\n"):
        return ""
    return "\n" if so_far.endswith("\n") else "\n\n"


def _needle_from_row(row: Mapping[str, Any]) -> str:
    """The record's own printed text, from whichever key this hit shape uses.

    A spec row calls it `name`, a plot row `caption`, a section row `title`.
    Taking it from the row keeps `as_dict()` — and with it the MCP response
    schemas and their token budget — exactly as it was: every one of these
    keys is already on the wire.
    """
    for key in ("name", "caption", "title"):
        value = str(row.get(key) or "").strip()
        if len(value) >= MIN_NEEDLE_CHARS:
            return value
    return ""


def _citation_from_row(row: Mapping[str, Any]) -> Citation | None:
    """Rebuild the `Citation` behind a hit's `as_dict()` row.

    `SpecHit.as_dict()` and friends flatten their citation into sibling keys
    plus a rendered `citation` label. Reconstructing the dataclass — rather
    than reading the label — keeps `pages` and `label` owned by
    `retrieve.results`, which is the one place the citation format may live.
    """
    page_start = row.get("page_start", row.get("page"))
    page_end = row.get("page_end", row.get("page"))
    section = row.get("section") or ""
    citation = Citation(
        doc=str(row.get("doc") or ""),
        doc_hash=str(row.get("doc_hash") or ""),
        section=str(section),
        page_start=page_start if isinstance(page_start, int) else None,
        page_end=page_end if isinstance(page_end, int) else None,
        part=str(row.get("part") or ""),
        needle=_needle_from_row(row),
    )
    if not (citation.doc or citation.doc_hash or citation.section or citation.page_start):
        return None
    return citation


def _walk(node: object, found: list[Citation]) -> None:
    if isinstance(node, Mapping):
        cited = node.get("citation")
        if _is_citation(cited):
            found.append(cited)  # type: ignore[arg-type]
        elif isinstance(cited, str):
            rebuilt = _citation_from_row(node)
            if rebuilt is not None:
                found.append(rebuilt)
        for key, value in node.items():
            if key == "citation":
                continue
            _walk(value, found)
        return
    if isinstance(node, (list, tuple, set)):
        for item in node:
            _walk(item, found)
        return
    if _is_citation(node):
        found.append(node)  # type: ignore[arg-type]


def collect_citations(payload: object) -> list[CitationOut]:
    """Every `Citation` inside one tool result, in order, deduplicated.

    This is the *only* source of a `citation` frame. It walks the structure a
    tool returned and picks out `Citation` objects (or the rows a hit's
    `as_dict()` flattened one into) — it never reads the model's text, so a
    fabricated citation cannot reach the stream.
    """
    found: list[Citation] = []
    _walk(payload, found)
    out: list[CitationOut] = []
    seen: set[tuple[Any, ...]] = set()
    for citation in found:
        key = (
            citation.doc,
            citation.doc_hash,
            citation.section,
            citation.page_start,
            citation.page_end,
            citation.part,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(CitationOut.from_citation(citation))
    return out


# --- the tool surface handed to the runner ------------------------------------


def tool_summary(name: str, arguments: Mapping[str, Any] | None = None) -> str:
    """A short human sentence for the `tool` frame — the "searching…" text."""
    args = dict(arguments or {})

    def text(key: str) -> str:
        value = args.get(key)
        return str(value).strip() if value not in (None, "") else ""

    if name == "search":
        needle = text("query")
        return f"Searching for “{needle}”" if needle else "Searching the corpus"
    if name == "find_spec":
        needle = text("symbol") or text("name") or text("section")
        return f"Looking up the spec for {needle}" if needle else "Looking up specs"
    if name == "find_plots":
        needle = text("q") or text("section") or ", ".join(args.get("tags") or [])
        return f"Looking for plots of {needle}" if needle else "Listing plots"
    if name == "read_section":
        needle = text("ref")
        return f"Reading §{needle}" if needle else "Reading a section"
    if name == "get_figure":
        needle = text("file")
        return f"Opening figure {needle}" if needle else "Opening a figure"
    if name == "ask":
        needle = text("question")
        return (
            f"Assembling an answer pack for “{needle}”" if needle else "Assembling an answer pack"
        )
    if name == "get_index":
        return "Reading the corpus index"
    if name == "get_family_index":
        return "Reading the family index"
    if name == "get_audit":
        return "Grading this corpus"
    if name == "list_parts":
        return "Listing parts"
    if name == "list_projects":
        return "Listing projects"
    if name == "list_families":
        return "Listing families"
    return f"Running {name}"


def _payload_text(payload: object) -> str:
    """One tool result as JSON the model can read; never raises on odd types."""
    return json.dumps(payload, indent=None, default=str, ensure_ascii=False)


def _accepts(fn: Any, name: str) -> bool:
    """Whether `fn` would accept `name=` as a keyword.

    A callable that takes `**kwargs` accepts anything, and a callable whose
    signature cannot be read is given the benefit of the doubt — this decides
    what to *pass*, and refusing to pass a scope to a tool that wanted one is
    the worse of the two failures.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins, C callables
        return True
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    return name in params


def build_tools(
    scope: Any,
    *,
    settings: Settings | None = None,
    registry: Mapping[str, Any] | None = None,
    on_result: Any = None,
) -> list[Any]:
    """The twelve tools, each bound to the already-resolved `scope`.

    `scope` is the `Retriever` / `ProjectRetriever` / `FamilyRetriever` ticket
    10 resolved, and it is closed over rather than passed as an argument: the
    model never sees a `part`, `project` or `family` parameter, so it cannot
    change the scope its answer is drawn from. That is why `get_family_index`
    takes no family name and `get_audit` takes no part name here, although
    both do over MCP — an MCP client chooses its own scope per call, and this
    loop was given one before it started.

    `registry` defaults to `app.tools.TOOLS` (ticket 11) and is injectable so
    a test can drive the loop over fakes. `on_result` is called with every
    tool payload before it is serialized — how citations leave the loop.
    """
    settings = settings or get_settings()
    if registry is None:
        from datasheet_analyzer.app import tools as agent_tools

        registry = agent_tools.TOOLS

    async def call(tool_name: str, /, **kwargs: Any) -> Any:
        # Positional-only: `find_spec` takes a `name` argument of its own, and
        # a keyword collision here would be a runtime error in one tool only.
        fn = registry[tool_name]
        # The catalog tools (`list_parts`, `list_projects`, `list_families`)
        # take no scope: they name what exists on this machine and answer from
        # no corpus. Binding `scope=` to them unconditionally made every call
        # come back as an `is_error` tool result reading
        # `TypeError: list_parts() got an unexpected keyword argument 'scope'`
        # — a real defect that only a driven turn could find, because a tool
        # that is merely *declared* never gets called. Asked of the callable
        # rather than of a hard-coded name list, so an injected fake registry
        # (whose tools take `**kwargs`) still receives the scope it expects.
        extra = {"scope": scope} if _accepts(fn, "scope") else {}
        bound = functools.partial(fn, settings=settings, **extra, **kwargs)
        payload = await anyio.to_thread.run_sync(bound)
        if on_result is not None:
            on_result(tool_name, payload)
        return payload

    @beta_async_tool
    async def list_parts() -> str:
        """Every part corpus on this machine, with its counts and whether it is built."""
        return _payload_text(await call("list_parts"))

    @beta_async_tool
    async def list_projects() -> str:
        """Every project, its member parts and the role each part plays."""
        return _payload_text(await call("list_projects"))

    @beta_async_tool
    async def list_families() -> str:
        """Every declared part family on this machine, and whether each member is built."""
        return _payload_text(await call("list_families"))

    @beta_async_tool
    async def get_index() -> str:
        """The part's INDEX.md — the map of its corpus. Read this first."""
        return _payload_text(await call("get_index"))

    @beta_async_tool
    async def get_family_index() -> str:
        """This family's FAMILY_INDEX.md: what every member prints identically, and what moved.

        Only for a turn scoped to a declared family. It maps the series this
        conversation is about; there is no way to ask it about another one.
        """
        return _payload_text(await call("get_family_index"))

    @beta_async_tool
    async def search(query: str, limit: int = 5) -> str:
        """Full-text search across the scope. Every hit comes back cited.

        Args:
            query: Words to search for, as they would appear in the datasheet.
            limit: Maximum number of hits to return.
        """
        return _payload_text(await call("search", query=query, limit=limit))

    @beta_async_tool
    async def find_spec(symbol: str = "", name: str = "", section: str = "") -> str:
        """Look up a parametric specification by symbol, name or section.

        Args:
            symbol: The printed symbol, e.g. `IDD` or `t_SU`.
            name: The parameter name, e.g. `supply current`.
            section: Restrict to one section number, e.g. `6.5`.
        """
        return _payload_text(await call("find_spec", symbol=symbol, name=name, section=section))

    @beta_async_tool
    async def find_plots(q: str = "", section: str = "", tags: list[str] | None = None) -> str:
        """Filter the plot catalog before opening a figure.

        Args:
            q: Words from the caption or its measurement conditions.
            section: Restrict to one section number.
            tags: Machine-derived tags a plot must carry.
        """
        return _payload_text(await call("find_plots", q=q, section=section, tags=tags))

    @beta_async_tool
    async def read_section(ref: str, max_tokens: int = 0) -> str:
        """Read one section verbatim. Truncation, if any, is announced in the result.

        Args:
            ref: Section number or title, e.g. `6.5` or `Electrical Characteristics`.
            max_tokens: Optional smaller budget than the configured default.
        """
        return _payload_text(await call("read_section", ref=ref, max_tokens=max_tokens))

    @beta_async_tool
    async def get_figure(file: str) -> list[dict[str, Any]]:
        """Open one cataloged figure as an image, with its caption and citation.

        Args:
            file: The `file` value from a `find_plots` result.
        """
        payload = await call("get_figure", file=file)
        return _figure_blocks(payload)

    @beta_async_tool
    async def ask(question: str, budget: int = 0) -> str:
        """One cited answer pack for a question, inside its token budget.

        Args:
            question: The question, in plain language.
            budget: Optional token budget for the pack.
        """
        return _payload_text(await call("ask", question=question, budget=budget))

    @beta_async_tool
    async def get_audit() -> str:
        """Grade this corpus before quoting it: readings, a letter and one headline sentence.

        Deterministic counts over what the corpus already published — no model
        is involved. Call it when the answer will carry numbers a reader might
        act on, and put `headline` in front of the answer if the grade is low.
        """
        return _payload_text(await call("get_audit"))

    ordered = [
        list_parts,
        list_projects,
        list_families,
        get_index,
        get_family_index,
        search,
        find_spec,
        find_plots,
        read_section,
        get_figure,
        ask,
        get_audit,
    ]
    names = set(registry)
    return [tool for tool in ordered if tool.name in names]


def _figure_blocks(payload: Any) -> list[dict[str, Any]]:
    """A `get_figure` payload as content blocks: the image, then its metadata."""
    blocks: list[dict[str, Any]] = []
    image = payload.get("image") if isinstance(payload, Mapping) else None
    if isinstance(image, (bytes, bytearray)):
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": str(payload.get("media_type") or "image/png"),
                    "data": base64.standard_b64encode(bytes(image)).decode("ascii"),
                },
            }
        )
    rest = (
        {key: value for key, value in payload.items() if key != "image"}
        if isinstance(payload, Mapping)
        else payload
    )
    blocks.append({"type": "text", "text": _payload_text(rest)})
    return blocks


# --- scope --------------------------------------------------------------------


def known_scopes(settings: Settings | None = None) -> tuple[list[str], list[str]]:
    """`(part names, project names)` as they exist on disk right now."""
    settings = settings or get_settings()
    from datasheet_analyzer.projects.store import list_projects as _list_projects
    from datasheet_analyzer.retrieve.index import discover_parts

    try:
        parts = [path.name for path in discover_parts(settings.parts_dir)]
    except OSError:  # pragma: no cover - unreadable parts_dir
        parts = []
    try:
        projects = list(_list_projects(settings.projects_dir))
    except OSError:  # pragma: no cover - unreadable projects_dir
        projects = []
    return parts, projects


def resolve_question(question: str, *, settings: Settings | None = None) -> ScopeResolution:
    """Resolve a question against the parts and projects that exist (ticket 10)."""
    from datasheet_analyzer.app.scope_resolver import resolve

    parts, projects = known_scopes(settings)
    return resolve(question, parts=parts, projects=projects)


def build_client(settings: Settings | None = None) -> Any:
    """The async Anthropic client this loop drives, from the configured key."""
    from anthropic import AsyncAnthropic

    settings = settings or get_settings()
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


# --- the turn -----------------------------------------------------------------


def _refusal_message(message: Any) -> str:
    """A readable sentence for `stop_reason == "refusal"`, without reading content."""
    details = getattr(message, "stop_details", None)
    category = str(getattr(details, "category", "") or "")
    explanation = str(getattr(details, "explanation", "") or "")
    if explanation:
        return f"The model declined to answer: {explanation}"
    if category:
        return f"The model declined to answer (category: {category})."
    return "The model declined to answer this question."


async def _aclose(obj: Any) -> None:
    """Close a stream or iterator without letting cleanup mask the real exit."""
    for name in ("aclose", "close"):
        closer = getattr(obj, name, None)
        if closer is None:
            continue
        try:
            result = closer()
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:  # noqa: BLE001 - cleanup must not raise
            log.debug("closing %s failed: %s", type(obj).__name__, exc)
        return


async def stream_turn(
    *,
    question: str,
    resolution: ScopeResolution,
    client: Any = None,
    retriever: Any = None,
    settings: Settings | None = None,
    registry: Mapping[str, Any] | None = None,
    session_id: str = "",
    sessions: Any = None,
    history: Sequence[ChatMessage] = (),
) -> AsyncIterator[ChatEvent]:
    """One question -> `scope`, then `tool`/`token`/`citation`, then `done` | `error`.

    The generator owns the loop's lifetime: closing it (which is what an SSE
    client disconnect does) unwinds into the `finally` below and closes the
    in-flight model request rather than leaving it running.
    """
    settings = settings or get_settings()

    yield ChatEvent.for_scope(resolution)
    if resolution.scope is None or not resolution.confident:
        # Ambiguous or unmatched: the candidates are already on the `scope`
        # frame and no model call is made. The UI asks; the user picks.
        yield ChatEvent.for_done(message=resolution.question or NO_SCOPE_MESSAGE)
        return

    pending: list[CitationOut] = []
    emitted: set[tuple[Any, ...]] = set()

    def on_result(name: str, payload: object) -> None:
        for citation in collect_citations(payload):
            key = (citation.doc_hash, citation.doc, citation.section, citation.pages, citation.part)
            if key in emitted:
                continue
            emitted.add(key)
            pending.append(citation)

    def drain() -> list[ChatEvent]:
        frames = [ChatEvent.for_citation(citation) for citation in pending]
        pending.clear()
        return frames

    tools = build_tools(retriever, settings=settings, registry=registry, on_result=on_result)
    params = build_params(
        question=question, scope=resolution.scope, settings=settings, history=history
    )

    answer: list[str] = []
    citations: list[CitationOut] = []
    failure = ""
    stream: Any = None
    iterator: Any = None

    try:
        if client is None:
            client = build_client(settings)
        runner = client.beta.messages.tool_runner(
            stream=True,
            tools=tools,
            max_iterations=MAX_TOOL_ITERATIONS,
            **params,
        )
        iterator = runner.__aiter__()
        while True:
            try:
                stream = await iterator.__anext__()
            except StopAsyncIteration:
                break
            for frame in drain():
                citations.append(frame.citation)  # type: ignore[arg-type]
                yield frame
            opened_text = False
            async for event in stream:
                kind = getattr(event, "type", "")
                if kind == "text":
                    text = getattr(event, "text", "")
                    if text:
                        if not opened_text:
                            opened_text = True
                            gap = _paragraph_gap(answer)
                            if gap:
                                answer.append(gap)
                                yield ChatEvent.for_token(gap)
                        answer.append(text)
                        yield ChatEvent.for_token(text)
                elif kind == "content_block_stop":
                    block = getattr(event, "content_block", None)
                    if getattr(block, "type", "") == "tool_use":
                        name = getattr(block, "name", "")
                        yield ChatEvent.for_tool(
                            name, summary=tool_summary(name, getattr(block, "input", None) or {})
                        )
            message = await stream.get_final_message()
            # Checked before anything reads `content`: a refusal can carry an
            # empty content list, and indexing it is the crash this avoids.
            if getattr(message, "stop_reason", "") == "refusal":
                failure = _refusal_message(message)
                break
            stream = None
    except Exception as exc:
        # Every failure becomes one `error` frame: once the stream is open an
        # exception cannot become an HTTP status, only a readable last frame.
        log.exception("chat turn failed", exc_info=exc)
        failure = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    finally:
        if stream is not None:
            await _aclose(stream)
        if iterator is not None:
            await _aclose(iterator)

    for frame in drain():
        citations.append(frame.citation)  # type: ignore[arg-type]
        yield frame

    if failure:
        yield ChatEvent.for_error(failure)
        return

    text = "".join(answer)
    _append_exchange(
        sessions, session_id, question=question, answer=text, citations=list(citations)
    )
    yield ChatEvent.for_done(message=text)


def _append_exchange(
    sessions: Any,
    session_id: str,
    *,
    question: str,
    answer: str,
    citations: list[CitationOut],
) -> None:
    """Persist both halves of a completed exchange; never break the stream."""
    if sessions is None or not session_id:
        return
    try:
        sessions.append(session_id, ChatMessage(role="user", text=question))
        sessions.append(session_id, ChatMessage(role="assistant", text=answer, citations=citations))
    except Exception as exc:  # noqa: BLE001 - a full answer is worth more than a save
        log.warning("could not append exchange to session %s: %s", session_id, exc)
