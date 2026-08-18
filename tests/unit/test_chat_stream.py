"""Ticket 12 — the chat loop and its token stream.

Hermetic by construction: there is no network, no API key and no live model
here. A `FakeAnthropic` replays a scripted tool-use exchange through the
*real* SDK tool runner (`BetaAsyncStreamingToolRunner`), so the loop under
test is the loop that ships — only the transport is fake. Tools are a fake
registry with the frozen `(*, scope, settings, **kwargs) -> dict` shape from
ticket 11, and `app.scope_resolver.resolve` (ticket 10) is stubbed where the
router needs it.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from anthropic.lib.tools import BetaAsyncStreamingToolRunner
from anthropic.types.beta import BetaMessage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typing_extensions import Self

from datasheet_analyzer.app import chat, deps
from datasheet_analyzer.app.contracts import ChatEvent, ScopeResolution
from datasheet_analyzer.app.routers import chat as chat_router
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.models import ChatMessage, ChatSession, ScopeRef
from datasheet_analyzer.retrieve.results import Citation

DEADLINE = 10.0

PART = ScopeRef(kind="part", name="LM741")
CONFIDENT = ScopeResolution(scope=PART, confident=True, matched_via="exact")
AMBIGUOUS = ScopeResolution(
    scope=None,
    confident=False,
    candidates=[ScopeRef(kind="part", name="AFE7950"), ScopeRef(kind="part", name="AFE7952")],
    question="Did you mean AFE7950 or AFE7952?",
)

CITATION = Citation(
    doc="datasheet-a1b2c3d4",
    doc_hash="a1b2c3d4",
    section="6.5",
    page_start=7,
    page_end=7,
    part="LM741",
)


# --- fakes --------------------------------------------------------------------


def assistant_message(content: list[dict[str, Any]], stop_reason: str, **extra: Any) -> BetaMessage:
    """A real `BetaMessage` — the runner inspects it, so it must be the real type."""
    return BetaMessage.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            **extra,
        }
    )


def text_event(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_stop_event(block_id: str, name: str, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_stop",
        content_block=SimpleNamespace(type="tool_use", id=block_id, name=name, input=payload),
    )


class FakeStream:
    """One scripted turn: some stream events, then a final message."""

    def __init__(self, events: list[Any], final: BetaMessage) -> None:
        self.events = events
        self.final = final
        self.closed = False
        self.consumed = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        await self.close()
        return False

    async def __aiter__(self):
        for event in self.events:
            await asyncio.sleep(0)  # a real stream suspends between frames
            if isinstance(event, Exception):
                raise event
            self.consumed += 1
            yield event

    async def get_final_message(self) -> BetaMessage:
        return self.final

    async def close(self) -> None:
        self.closed = True


class FakeMessages:
    def __init__(self, client: FakeAnthropic, script: list[tuple[list[Any], BetaMessage]]) -> None:
        self._client = client
        self._script = list(script)
        self.requests: list[dict[str, Any]] = []
        self.streams: list[FakeStream] = []

    def tool_runner(
        self, *, tools: Any, stream: bool = False, max_iterations: int | None = None, **params: Any
    ) -> BetaAsyncStreamingToolRunner:
        assert stream is True, "the chat loop must stream"
        return BetaAsyncStreamingToolRunner(
            params=params,
            options={},
            tools=tools,
            client=self._client,  # type: ignore[arg-type]
            max_iterations=max_iterations,
        )

    def stream(self, **kwargs: Any) -> FakeStream:
        self.requests.append(kwargs)
        assert self._script, "the model was called more times than the script allows"
        events, final = self._script.pop(0)
        made = FakeStream(events, final)
        self.streams.append(made)
        return made


class FakeAnthropic:
    """Just enough of `AsyncAnthropic` for the real tool runner to drive."""

    def __init__(self, script: list[tuple[list[Any], BetaMessage]] | None = None) -> None:
        self.messages = FakeMessages(self, script or [])
        self.beta = SimpleNamespace(messages=self.messages)


class FakeSessionStore:
    """Ticket 15's store, as far as ticket 12 uses it."""

    def __init__(self, session: ChatSession | None = None) -> None:
        self.session = session
        self.appended: list[ChatMessage] = []

    def get(self, session_id: str) -> ChatSession | None:
        if self.session is not None and self.session.id == session_id:
            return self.session
        return None

    def append(self, session_id: str, message: ChatMessage) -> ChatSession:
        self.appended.append(message)
        assert self.session is not None
        self.session.messages.append(message)
        return self.session


@pytest.fixture
def settings(tmp_path) -> Settings:
    reset_settings_cache()
    made = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / "cache",
        projects_dir=tmp_path / "projects",
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
        anthropic_api_key="test-key-not-used",
    ).resolve()
    yield made
    reset_settings_cache()


def drive(gen) -> list[ChatEvent]:
    """Consume a `stream_turn` generator to completion."""

    async def scenario() -> list[ChatEvent]:
        return [event async for event in gen]

    return asyncio.run(asyncio.wait_for(scenario(), DEADLINE))


def kinds(events: list[ChatEvent]) -> list[str]:
    return [event.type for event in events]


def spec_hit_payload() -> dict[str, Any]:
    """A tool result carrying a `Citation` object, the way ticket 11 returns one."""
    return {"count": 1, "hits": [{"symbol": "AVOL", "value": "200", "citation": CITATION}]}


def searching_script(answer: str, *, tool: str = "search") -> list[tuple[list[Any], BetaMessage]]:
    """Turn 1 calls a tool; turn 2 answers."""
    return [
        (
            [
                text_event("Let me look. "),
                tool_stop_event("toolu_1", tool, {"query": "open loop gain"}),
            ],
            assistant_message(
                [
                    {"type": "text", "text": "Let me look. "},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": tool,
                        "input": {"query": "open loop gain"},
                    },
                ],
                "tool_use",
            ),
        ),
        (
            [text_event(answer)],
            assistant_message([{"type": "text", "text": answer}], "end_turn"),
        ),
    ]


# --- the happy path -----------------------------------------------------------


def test_confident_scope_streams_scope_then_tokens_then_done(settings: Settings) -> None:
    client = FakeAnthropic(
        [
            (
                [text_event("Open-loop gain is "), text_event("200 V/mV.")],
                assistant_message(
                    [{"type": "text", "text": "Open-loop gain is 200 V/mV."}], "end_turn"
                ),
            )
        ]
    )
    events = drive(
        chat.stream_turn(
            question="what is the open loop gain of the LM741?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={},
        )
    )

    assert kinds(events) == ["scope", "token", "token", "done"]
    assert events[0].scope == PART
    assert events[0].resolution is not None and events[0].resolution.confident
    assert "".join(event.text for event in events if event.type == "token") == (
        "Open-loop gain is 200 V/mV."
    )
    assert events[-1].message == "Open-loop gain is 200 V/mV."


# --- ambiguity ----------------------------------------------------------------


def test_ambiguous_question_carries_candidates_and_never_calls_the_model(
    settings: Settings,
) -> None:
    client = FakeAnthropic([])  # any model call would fail the script assertion

    events = drive(
        chat.stream_turn(
            question="what is the noise figure?",
            resolution=AMBIGUOUS,
            client=client,
            retriever=None,
            settings=settings,
            registry={},
        )
    )

    assert kinds(events) == ["scope", "done"]
    scope_event = events[0]
    assert scope_event.scope is None
    assert scope_event.resolution is not None
    assert scope_event.resolution.ambiguous
    assert [candidate.name for candidate in scope_event.resolution.candidates] == [
        "AFE7950",
        "AFE7952",
    ]
    assert events[-1].message == AMBIGUOUS.question
    assert client.messages.requests == []


# --- scope is fixed -----------------------------------------------------------


def test_every_tool_call_uses_the_scope_from_the_first_event(settings: Settings) -> None:
    retriever = object()
    seen: list[Any] = []

    def fake_search(*, scope: Any, settings: Settings, query: str, limit: int = 5) -> dict:
        seen.append(scope)
        return {"hits": []}

    def fake_find_spec(
        *, scope: Any, settings: Settings, symbol: str = "", name: str = "", section: str = ""
    ) -> dict:
        seen.append(scope)
        return {"hits": []}

    script = [
        (
            [
                tool_stop_event("t1", "search", {"query": "gain"}),
                tool_stop_event("t2", "find_spec", {"symbol": "AVOL"}),
            ],
            assistant_message(
                [
                    {"type": "tool_use", "id": "t1", "name": "search", "input": {"query": "gain"}},
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "find_spec",
                        "input": {"symbol": "AVOL"},
                    },
                ],
                "tool_use",
            ),
        ),
        (
            [text_event("Done.")],
            assistant_message([{"type": "text", "text": "Done."}], "end_turn"),
        ),
    ]
    client = FakeAnthropic(script)

    events = drive(
        chat.stream_turn(
            question="gain of the LM741?",
            resolution=CONFIDENT,
            client=client,
            retriever=retriever,
            settings=settings,
            registry={"search": fake_search, "find_spec": fake_find_spec},
        )
    )

    assert events[0].scope == PART
    assert seen == [retriever, retriever], "both tools ran against the one resolved scope"


def test_no_tool_exposes_a_scope_argument_to_the_model(settings: Settings) -> None:
    tools = chat.build_tools(
        object(),
        settings=settings,
        registry={name: (lambda **kw: {}) for name in ("search", "find_spec", "read_section")},
    )
    assert {tool.name for tool in tools} == {"search", "find_spec", "read_section"}
    for tool in tools:
        properties = tool.to_dict()["input_schema"].get("properties") or {}
        assert not {"part", "project", "scope", "settings"} & set(properties)


# --- tool frames --------------------------------------------------------------


def test_default_registry_builds_the_nine_agent_tools(settings: Settings) -> None:
    """The tool surface is ticket 11's registry, not a list this module invents."""
    from datasheet_analyzer.app import tools as agent_tools

    built = chat.build_tools(object(), settings=settings)
    assert [tool.name for tool in built] == list(agent_tools.TOOL_NAMES)
    for tool in built:
        assert tool.to_dict()["description"], f"{tool.name} needs a description for the model"


def test_get_figure_becomes_an_image_block_plus_its_metadata(settings: Settings) -> None:
    seen: list[tuple[str, Any]] = []

    def fake_get_figure(*, scope: Any, settings: Settings, file: str) -> dict:
        return {
            "image": b"\x89PNG\r\n",
            "media_type": "image/png",
            "caption": "Open-loop gain vs frequency",
            "citation": CITATION,
        }

    tools = chat.build_tools(
        object(),
        settings=settings,
        registry={"get_figure": fake_get_figure},
        on_result=lambda name, payload: seen.append((name, payload)),
    )
    blocks = asyncio.run(asyncio.wait_for(tools[0].call({"file": "fig-1.png"}), DEADLINE))

    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[0]["source"]["type"] == "base64"
    assert "Open-loop gain" in blocks[1]["text"]
    assert "image" not in json.loads(blocks[1]["text"])
    assert chat.collect_citations(seen[0][1])[0].label == CITATION.label


def test_tool_event_is_emitted_before_the_tool_runs(settings: Settings) -> None:
    timeline: list[str] = []

    def fake_search(*, scope: Any, settings: Settings, query: str, limit: int = 5) -> dict:
        timeline.append("tool-ran")
        return spec_hit_payload()

    client = FakeAnthropic(searching_script("Gain is 200 V/mV (§6.5, p.7)."))

    async def scenario() -> None:
        async for event in chat.stream_turn(
            question="gain of the LM741?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={"search": fake_search},
        ):
            timeline.append(f"event:{event.type}")

    asyncio.run(asyncio.wait_for(scenario(), DEADLINE))

    assert "event:tool" in timeline and "tool-ran" in timeline
    assert timeline.index("event:tool") < timeline.index("tool-ran")
    tool_frames = [entry for entry in timeline if entry == "event:tool"]
    assert len(tool_frames) == 1


def test_tool_event_carries_a_name_and_a_human_summary(settings: Settings) -> None:
    def fake_search(*, scope: Any, settings: Settings, query: str, limit: int = 5) -> dict:
        return {"hits": []}

    client = FakeAnthropic(searching_script("Answered."))
    events = drive(
        chat.stream_turn(
            question="gain?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={"search": fake_search},
        )
    )
    tool_events = [event for event in events if event.type == "tool"]
    assert [event.tool for event in tool_events] == ["search"]
    assert "open loop gain" in tool_events[0].summary


# --- citations ----------------------------------------------------------------


def test_citations_come_from_tool_results_not_from_prose(settings: Settings) -> None:
    def fake_search(*, scope: Any, settings: Settings, query: str, limit: int = 5) -> dict:
        return spec_hit_payload()

    # The model's prose invents a second, unbacked citation.
    fabricated = "Gain is 200 V/mV (§6.5, p.7), and slew rate is 0.5 V/µs (§9.9, p.99)."
    client = FakeAnthropic(searching_script(fabricated))

    events = drive(
        chat.stream_turn(
            question="gain of the LM741?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={"search": fake_search},
        )
    )

    citations = [event.citation for event in events if event.type == "citation"]
    assert len(citations) == 1, "only the tool result's citation is emitted"
    only = citations[0]
    assert (only.section, only.page_start, only.doc_hash) == ("6.5", 7, "a1b2c3d4")
    assert only.label == CITATION.label
    assert "§9.9" not in only.label
    assert all(citation.section != "9.9" for citation in citations)


def test_a_turn_with_no_tool_results_emits_no_citations(settings: Settings) -> None:
    prose = "It is 200 V/mV (§6.5, p.7)."
    client = FakeAnthropic(
        [([text_event(prose)], assistant_message([{"type": "text", "text": prose}], "end_turn"))]
    )
    events = drive(
        chat.stream_turn(
            question="gain of the LM741?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={},
        )
    )
    assert [event.type for event in events if event.type == "citation"] == []


def test_collect_citations_reads_flattened_hit_rows() -> None:
    row = {
        "symbol": "AVOL",
        "section": "6.5",
        "page": 7,
        "part": "LM741",
        "doc": "datasheet-a1b2c3d4",
        "doc_hash": "a1b2c3d4",
        "citation": CITATION.label,
    }
    found = chat.collect_citations({"hits": [row, dict(row)]})
    assert len(found) == 1, "identical citations are emitted once"
    assert found[0].label == CITATION.label
    assert found[0].pages == "p.7"
    assert chat.collect_citations({"answer": "no citations here"}) == []


# --- persistence --------------------------------------------------------------


def test_completed_exchange_is_appended_to_the_session(settings: Settings) -> None:
    session = ChatSession(id="s-1", title="", scope=PART)
    store = FakeSessionStore(session)

    def fake_search(*, scope: Any, settings: Settings, query: str, limit: int = 5) -> dict:
        return spec_hit_payload()

    client = FakeAnthropic(searching_script("Gain is 200 V/mV."))
    drive(
        chat.stream_turn(
            question="gain of the LM741?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={"search": fake_search},
            session_id="s-1",
            sessions=store,
        )
    )

    assert [message.role for message in store.appended] == ["user", "assistant"]
    assert store.appended[0].text == "gain of the LM741?"
    # The pre-tool preamble and the answer are two assistant turns, so they are
    # separated by a blank line rather than run together: a second turn opening
    # with a markdown heading must start at the beginning of a line.
    assert store.appended[1].text == "Let me look. \n\nGain is 200 V/mV."
    assert [citation.label for citation in store.appended[1].citations] == [CITATION.label]
    assert store.appended[0].citations == []


def test_a_failed_turn_is_not_appended_to_the_session(settings: Settings) -> None:
    session = ChatSession(id="s-1", title="", scope=PART)
    store = FakeSessionStore(session)
    client = FakeAnthropic(
        [([text_event("hm"), RuntimeError("upstream exploded")], assistant_message([], "end_turn"))]
    )

    events = drive(
        chat.stream_turn(
            question="gain?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={},
            session_id="s-1",
            sessions=store,
        )
    )

    assert events[-1].type == "error"
    assert store.appended == []


# --- failure modes ------------------------------------------------------------


def test_model_error_midstream_emits_error_and_closes_cleanly(settings: Settings) -> None:
    client = FakeAnthropic(
        [
            (
                [text_event("Reading"), RuntimeError("connection reset by peer")],
                assistant_message([], "end_turn"),
            )
        ]
    )

    events = drive(
        chat.stream_turn(
            question="gain?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={},
        )
    )

    assert kinds(events) == ["scope", "token", "error"]
    assert "connection reset by peer" in events[-1].message
    assert "done" not in kinds(events)
    assert client.messages.streams[0].closed is True


def test_refusal_is_handled_before_content_and_surfaces_as_error(settings: Settings) -> None:
    refusal = assistant_message(
        [],
        "refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "declined"},
    )
    client = FakeAnthropic([([], refusal)])

    events = drive(
        chat.stream_turn(
            question="gain?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={},
        )
    )

    assert kinds(events) == ["scope", "error"]
    assert "declined" in events[-1].message
    assert client.messages.streams[0].closed is True


def test_refusal_without_details_still_reads_as_a_sentence(settings: Settings) -> None:
    client = FakeAnthropic([([], assistant_message([], "refusal"))])
    events = drive(
        chat.stream_turn(
            question="gain?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={},
        )
    )
    assert kinds(events) == ["scope", "error"]
    assert events[-1].message.strip().endswith(".")


def test_client_disconnect_cancels_the_loop(settings: Settings) -> None:
    """Closing the generator (what an SSE disconnect does) stops the run."""
    ran: list[str] = []

    def fake_search(*, scope: Any, settings: Settings, query: str, limit: int = 5) -> dict:
        ran.append("search")
        return {"hits": []}

    client = FakeAnthropic(searching_script("never reached"))

    async def scenario() -> list[str]:
        events = chat.stream_turn(
            question="gain?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={"search": fake_search},
        )
        seen: list[str] = []
        async for event in events:
            seen.append(event.type)
            if event.type == "token":
                break  # the browser went away mid-stream
        await events.aclose()
        return seen

    seen = asyncio.run(asyncio.wait_for(scenario(), DEADLINE))

    assert seen == ["scope", "token"]
    assert client.messages.streams[0].closed is True, "the in-flight request was released"
    assert len(client.messages.requests) == 1, "no second turn was started"
    assert ran == [], "no tool ran after the client left"


# --- request shape ------------------------------------------------------------


def test_thinking_is_never_disabled_in_the_request_path(settings: Settings) -> None:
    params = chat.build_params(question="gain?", scope=PART, settings=settings)
    assert "thinking" not in params

    client = FakeAnthropic(searching_script("Done."))
    drive(
        chat.stream_turn(
            question="gain?",
            resolution=CONFIDENT,
            client=client,
            retriever=object(),
            settings=settings,
            registry={"search": lambda **kw: {"hits": []}},
        )
    )
    for request in client.messages.requests:
        assert "thinking" not in request
    for path in (chat.__file__, chat_router.__file__):
        with open(path, encoding="utf-8") as handle:
            body = handle.read()
        assert "thinking=" not in body, "the request path must not set `thinking`"
        assert '"thinking":' not in body


def test_system_and_tools_sit_before_the_last_cache_breakpoint(settings: Settings) -> None:
    question = "what is the open loop gain?"
    params = chat.build_params(question=question, scope=PART, settings=settings)

    blocks = params["system"]
    assert [block.get("cache_control") for block in blocks[:-1]] == [None] * (len(blocks) - 1)
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}

    # The volatile question lives after the breakpoint and carries none of its own.
    assert params["messages"][-1] == {"role": "user", "content": question}
    assert json.dumps(params["messages"]).count("cache_control") == 0
    assert question not in json.dumps(params["system"])
    assert params["model"] == settings.chat_model
    assert params["max_tokens"] == settings.chat_max_tokens


def test_history_precedes_the_question(settings: Settings) -> None:
    history = [
        ChatMessage(role="user", text="earlier question"),
        ChatMessage(role="assistant", text="earlier answer"),
    ]
    params = chat.build_params(question="new one", scope=PART, settings=settings, history=history)
    assert [message["content"] for message in params["messages"]] == [
        "earlier question",
        "earlier answer",
        "new one",
    ]


# --- the HTTP surface ---------------------------------------------------------


def make_app(
    settings: Settings,
    *,
    client: FakeAnthropic,
    store: Any,
    retriever: Any = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router.router)
    app.dependency_overrides[deps.get_settings_dep] = lambda: settings
    app.dependency_overrides[deps.get_session_store] = lambda: store
    app.dependency_overrides[chat_router.get_chat_client_factory] = lambda: lambda: client
    app.dependency_overrides[chat_router.get_retriever_factory] = lambda: (
        lambda scope: retriever or object()
    )
    return app


def sse_frames(body: str) -> list[tuple[str, dict]]:
    """`event:`/`data:` pairs out of an SSE body, ignoring `:` heartbeats."""
    frames: list[tuple[str, dict]] = []
    name = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            frames.append((name, json.loads(line.split(":", 1)[1].strip())))
    return frames


def test_resolve_scope_endpoint_returns_the_resolution(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datasheet_analyzer.app import scope_resolver

    monkeypatch.setattr(scope_resolver, "resolve", lambda question, **kw: AMBIGUOUS)
    app = make_app(settings, client=FakeAnthropic([]), store=FakeSessionStore())

    with TestClient(app) as http:
        response = http.post("/api/chat/resolve-scope", json={"question": "noise figure?"})

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] is None
    assert body["confident"] is False
    assert [candidate["name"] for candidate in body["candidates"]] == ["AFE7950", "AFE7952"]


def test_message_endpoint_streams_chat_events(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datasheet_analyzer.app import scope_resolver

    monkeypatch.setattr(scope_resolver, "resolve", lambda question, **kw: CONFIDENT)
    monkeypatch.setattr(
        chat, "build_tools", lambda scope, **kw: [], raising=True
    )  # ticket 11's bodies are not this ticket's concern

    client = FakeAnthropic(
        [
            (
                [text_event("200 V/mV.")],
                assistant_message([{"type": "text", "text": "200 V/mV."}], "end_turn"),
            )
        ]
    )
    session = ChatSession(id="s-1", title="", scope=PART)
    store = FakeSessionStore(session)
    app = make_app(settings, client=client, store=store)

    with TestClient(app) as http:
        response = http.post("/api/chat/s-1/message", json={"question": "gain of the LM741?"})
        frames = sse_frames(response.text)

    assert response.status_code == 200
    assert [name for name, _ in frames] == ["scope", "token", "done"]
    assert all(name == payload["type"] for name, payload in frames)
    assert frames[0][1]["scope"]["name"] == "LM741"
    assert frames[1][1]["text"] == "200 V/mV."
    assert [message.role for message in store.appended] == ["user", "assistant"]


def test_message_endpoint_404s_on_an_unknown_session(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datasheet_analyzer.app import scope_resolver

    monkeypatch.setattr(scope_resolver, "resolve", lambda question, **kw: CONFIDENT)
    app = make_app(settings, client=FakeAnthropic([]), store=FakeSessionStore())

    with TestClient(app) as http:
        response = http.post("/api/chat/nope/message", json={"question": "gain?"})

    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


def test_message_endpoint_asks_instead_of_guessing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datasheet_analyzer.app import scope_resolver

    monkeypatch.setattr(scope_resolver, "resolve", lambda question, **kw: AMBIGUOUS)
    called: list[Any] = []

    client = FakeAnthropic([])
    session = ChatSession(id="s-1", title="", scope=PART)
    app = make_app(settings, client=client, store=FakeSessionStore(session))
    app.dependency_overrides[chat_router.get_retriever_factory] = lambda: (
        lambda scope: called.append(scope)
    )

    with TestClient(app) as http:
        response = http.post("/api/chat/s-1/message", json={"question": "noise figure?"})
        frames = sse_frames(response.text)

    assert [name for name, _ in frames] == ["scope", "done"]
    assert frames[0][1]["resolution"]["question"] == AMBIGUOUS.question
    assert called == [], "no scope was resolved, so no retriever was built"
    assert client.messages.requests == []


def test_message_endpoint_honours_a_user_supplied_scope(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datasheet_analyzer.app import scope_resolver

    def explode(*args: Any, **kwargs: Any) -> ScopeResolution:  # pragma: no cover - must not run
        raise AssertionError("a user-picked scope must not be re-resolved")

    monkeypatch.setattr(scope_resolver, "resolve", explode)
    monkeypatch.setattr(chat, "build_tools", lambda scope, **kw: [])

    client = FakeAnthropic(
        [([text_event("ok")], assistant_message([{"type": "text", "text": "ok"}], "end_turn"))]
    )
    session = ChatSession(id="s-1", title="", scope=PART)
    app = make_app(settings, client=client, store=FakeSessionStore(session))

    with TestClient(app) as http:
        response = http.post(
            "/api/chat/s-1/message",
            json={"question": "gain?", "scope": {"kind": "part", "name": "AD9081"}},
        )
        frames = sse_frames(response.text)

    assert frames[0][1]["scope"] == {"kind": "part", "name": "AD9081"}
    assert frames[0][1]["resolution"]["matched_via"] == "user"


def test_a_second_turn_opening_with_a_heading_starts_on_its_own_line() -> None:
    """Only the missing newlines are added, never a blank line onto a blank line.

    The gap exists so `## Receiver noise figure` at the start of a post-tool
    turn parses as a heading instead of rendering as literal hashes. A model
    that already closed its turn with a newline must not gain a second one.
    """
    assert chat._paragraph_gap([]) == ""
    assert chat._paragraph_gap(["   "]) == ""
    assert chat._paragraph_gap(["I'll look this up."]) == "\n\n"
    assert chat._paragraph_gap(["I'll look this up.\n"]) == "\n"
    assert chat._paragraph_gap(["I'll look this up.\n\n"]) == ""
