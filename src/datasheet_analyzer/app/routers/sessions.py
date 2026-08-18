"""`/api/sessions` — saved conversations, and the way an answer leaves (ticket 15).

Four endpoints over `app/sessions.py`, and no logic of its own beyond turning
"no such session" into a 404 and choosing a media type. The store is injected
through `get_session_store`, so a test points this router at a temp directory
without touching the environment.

Two decisions are worth naming:

- **The id is generated server-side, always.** `SessionCreateIn` carries no
  id field, and a body that smuggles one is ignored by the model: session
  files are written by id, so a caller-chosen id would be a caller-chosen
  path under `sessions_dir`.
- **Export is a download, not a JSON envelope.** `GET .../export` returns the
  document itself — `text/markdown` for the design-review paste,
  `text/yaml` for the golden-Q&A draft — with a `Content-Disposition`
  filename that already matches the fixture the YAML is destined to become
  (`golden_qa_<PART>.yaml`). Wrapping either in JSON would make the client
  unwrap a document it is about to hand to a file save.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from datasheet_analyzer.app.contracts import (
    API_PREFIX,
    SessionCreateIn,
    SessionExportFormat,
    SessionOut,
    SessionsOut,
)
from datasheet_analyzer.app.deps import get_session_store
from datasheet_analyzer.app.sessions import SessionStore
from datasheet_analyzer.models import ChatSession

router = APIRouter(prefix=API_PREFIX, tags=["sessions"])

#: Injected rather than constructed: `app.dependency_overrides[get_session_store]`
#: points a whole app at a temporary `sessions_dir` without touching the
#: environment.
StoreDep = Annotated[SessionStore, Depends(get_session_store)]

#: Media types the two exports are served as, per the contract table.
MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"
GOLDEN_MEDIA_TYPE = "text/yaml; charset=utf-8"

# Anything else in a suggested filename is dropped rather than escaped: the
# header is advisory, and a quote or a path separator in it is not.
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@router.get("/sessions", response_model=SessionsOut)
def list_sessions(store: StoreDep) -> SessionsOut:
    """Every saved conversation, newest first. A malformed file is skipped."""
    summaries = [SessionOut.from_session(session).summary for session in store.list()]
    return SessionsOut(sessions=summaries, count=len(summaries))


@router.post("/sessions", response_model=SessionOut)
def create_session(body: SessionCreateIn, store: StoreDep) -> SessionOut:
    """Create a session and return it — its id included, generated here."""
    session = store.create(title=body.title, scope=body.scope)
    return SessionOut.from_session(session)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, store: StoreDep) -> SessionOut:
    """The full transcript, with every citation intact; 404 for an unknown id."""
    return SessionOut.from_session(_require(store, session_id))


@router.get("/sessions/{session_id}/export")
def export_session(
    session_id: str,
    store: StoreDep,
    export_format: Annotated[
        SessionExportFormat,
        Query(alias="format", description="`markdown` for a design review, `golden` for a fixture"),
    ] = "markdown",
) -> Response:
    """The session as markdown, or as a golden-Q&A fixture draft.

    A session with no assistant messages exports an empty *document* rather
    than an error: "there is nothing in here yet" is an answer.
    """
    session = _require(store, session_id)
    if export_format == "golden":
        content = store.export_golden(session_id)
        media_type = GOLDEN_MEDIA_TYPE
        filename = f"golden_qa_{_safe(session.scope.name or 'PART')}.yaml"
    else:
        content = store.export_markdown(session_id)
        media_type = MARKDOWN_MEDIA_TYPE
        filename = f"session-{_safe(session.id)}.md"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _require(store: SessionStore, session_id: str) -> ChatSession:
    """The session, or a 404 naming the id that was asked for."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"no session with id {session_id!r}")
    return session


def _safe(name: str) -> str:
    """A filename suggestion with everything path-shaped removed."""
    return _UNSAFE_FILENAME.sub("-", name).strip("-") or "session"
