"""Chat endpoints: resolve a scope, then stream one answer (ticket 12).

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/chat/resolve-scope` | `ResolveIn` | `ScopeResolution` |
| POST | `/api/chat/{session_id}/message` | `MessageIn` | SSE of `ChatEvent` |

`resolve-scope` exists on its own so the UI can show the scope chip — and the
ambiguity question — *before* the user commits to asking. It is the same
deterministic resolver the message endpoint runs, so what the chip shows is
what the answer will be drawn from.

The message endpoint does everything that can fail **before** the response
starts: an unknown session is a 404, a missing API key or a scope that names
nothing is a 400 carrying the reason. Once the stream opens, every remaining
outcome — including a model error — is a frame on it, because a half-sent SSE
body cannot become an HTTP status. One `ChatEvent` per frame, with the SSE
event name equal to the event's own `type`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from datasheet_analyzer.app import chat, deps
from datasheet_analyzer.app.contracts import (
    API_PREFIX,
    SSE_HEARTBEAT_SECONDS,
    ChatEvent,
    MessageIn,
    ResolveIn,
    ScopeResolution,
)
from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import ChatMessage, ScopeRef

log = logging.getLogger(__name__)

__all__ = ["get_chat_client_factory", "get_retriever_factory", "router"]

router = APIRouter(prefix=f"{API_PREFIX}/chat", tags=["chat"])

#: Ticket 06's providers, injected by type so a test overrides the provider
#: itself (`app.dependency_overrides[deps.get_settings_dep] = ...`).
SettingsDep = Annotated[Settings, Depends(deps.get_settings_dep)]
SessionStoreDep = Annotated[Any, Depends(deps.get_session_store)]


def get_chat_client_factory(settings: SettingsDep) -> Callable[[], Any]:
    """A zero-arg factory for the Anthropic client, checked but not yet built.

    A factory rather than the client itself so an ambiguous question — which
    never calls the model — does not require a key to be configured.
    """

    def factory() -> Any:
        if not settings.llm_available:
            raise HTTPException(
                status_code=400,
                detail="ANTHROPIC_API_KEY is not set, so the chat agent cannot run.",
            )
        return chat.build_client(settings)

    return factory


def get_retriever_factory() -> Callable[[ScopeRef], Any]:
    """`ScopeRef -> Retriever | ProjectRetriever`, ticket 06's provider.

    Indirected through a dependency so a test can inject a fake corpus and so
    the 400 an invalid scope raises happens before the stream opens.
    """
    return deps.get_retriever


ClientFactoryDep = Annotated[Callable[[], Any], Depends(get_chat_client_factory)]
RetrieverFactoryDep = Annotated[Callable[[ScopeRef], Any], Depends(get_retriever_factory)]


@router.post("/resolve-scope", response_model=ScopeResolution)
def resolve_scope(payload: ResolveIn, settings: SettingsDep) -> ScopeResolution:
    """Which Part or Project this question resolves to — or a question back."""
    return chat.resolve_question(payload.question, settings=settings)


def _session_history(store: Any, session_id: str) -> tuple[Any, list[ChatMessage]]:
    """The session and its transcript; 404 when the id is unknown.

    A store that is not wired yet (ticket 15) is not a client error: the turn
    still runs, it simply is not persisted.
    """
    if store is None:
        return None, []
    try:
        session = store.get(session_id)
    except NotImplementedError:  # pragma: no cover - until ticket 15 lands
        log.warning("session store is not implemented; this turn will not be saved")
        return None, []
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown session: {session_id}")
    return session, list(getattr(session, "messages", []))


def _resolution_for(payload: MessageIn, settings: Settings) -> ScopeResolution:
    """The user's pick wins; otherwise resolve the question (ticket 10)."""
    if payload.scope is not None:
        return ScopeResolution(scope=payload.scope, confident=True, matched_via="user")
    return chat.resolve_question(payload.question, settings=settings)


async def _frames(events: AsyncIterator[ChatEvent]) -> AsyncIterator[dict[str, str]]:
    """One SSE frame per `ChatEvent`, named by the event's own `type`."""
    async for event in events:
        yield {"event": event.type, "data": event.model_dump_json()}


@router.post("/{session_id}/message")
def post_message(
    session_id: str,
    payload: MessageIn,
    settings: SettingsDep,
    store: SessionStoreDep,
    client_factory: ClientFactoryDep,
    retriever_factory: RetrieverFactoryDep,
) -> EventSourceResponse:
    """Ask one question and stream the answer back as `ChatEvent`s."""
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is empty")

    session, history = _session_history(store, session_id)
    resolution = _resolution_for(payload, settings)

    retriever: Any = None
    client: Any = None
    if resolution.scope is not None and resolution.confident:
        # Both may raise a 400 — deliberately here, before the stream opens.
        retriever = retriever_factory(resolution.scope)
        client = client_factory()

    events = chat.stream_turn(
        question=question,
        resolution=resolution,
        client=client,
        retriever=retriever,
        settings=settings,
        session_id=session_id,
        sessions=store if session is not None else None,
        history=history,
    )
    return EventSourceResponse(_frames(events), ping=SSE_HEARTBEAT_SECONDS)
