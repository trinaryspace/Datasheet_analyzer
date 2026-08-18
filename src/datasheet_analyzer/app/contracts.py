"""The HTTP surface, frozen: one request and one response model per endpoint.

This module docstring is the single source of truth for the endpoint table.
A router may not invent a shape, and a front end may not read one that is not
here — that is what lets the backend and the five frontend tickets be written
in parallel against the same contract.

| Method | Path | Request | Response | Ticket |
|---|---|---|---|---|
| GET | `/api/parts` | — | `PartsOut` | 06 |
| GET | `/api/projects` | — | `ProjectsOut` | 06 |
| POST | `/api/projects` | `ProjectCreateIn` | `ProjectOut` | — |
| POST | `/api/projects/{name}/parts` | `ProjectPartsIn` | `ProjectOut` | — |
| DELETE | `/api/projects/{name}/parts/{part}` | — | `ProjectOut` | — |
| PATCH | `/api/projects/{name}` | `ProjectPatchIn` | `ProjectOut` | — |
| POST | `/api/projects/open` | `ProjectOpenIn` | `ProjectOut` | — |
| PUT | `/api/projects/{name}/exclusions` | `ProjectExcludeIn` | `ProjectOut` | — |
| POST | `/api/browse/dialog` | — | `BrowsePickOut` | — |
| GET | `/api/browse/list` | query `path` | `BrowseListOut` | — |
| POST | `/api/analyze/scan` | `ScanIn` | `ScanOut` | 08 |
| POST | `/api/analyze/start` | `StartIn` | `StartOut` | 07 |
| GET | `/api/analyze/{run_id}/events` | — | SSE of `JobEvent` | 07 |
| GET | `/api/library` | — | `LibraryOut` | 09 |
| PATCH | `/api/library/{content_hash}` | `LibraryPatchIn` | `LibraryDocumentOut` | 09 |
| POST | `/api/chat/resolve-scope` | `ResolveIn` | `ScopeResolution` | 12 |
| POST | `/api/chat/{session_id}/message` | `MessageIn` | SSE of `ChatEvent` | 12 |
| GET | `/api/sessions` | — | `SessionsOut` | 15 |
| POST | `/api/sessions` | `SessionCreateIn` | `SessionOut` | 15 |
| GET | `/api/sessions/{id}` | — | `SessionOut` | 15 |
| GET | `/api/sessions/{id}/export` | query `format` | `text/markdown` or `text/yaml` | 15 |
| GET | `/api/locate` | query `LocateQuery` | `LocateOut` | 13 |
| GET | `/api/pdf/{content_hash}` | Range header | `application/pdf` | 14 |

Errors are FastAPI's own `{"detail": ...}` body, modelled as `ErrorOut`.

**Two SSE streams**, both one-way server-to-client (no WebSocket is needed):

- `/api/analyze/{run_id}/events` sends `event: snapshot` (a `RunSnapshot`,
  once on connect so a client attaching late is never blank), then
  `event: job` (a `JobEvent`) per transition, `:` heartbeat comments every
  `SSE_HEARTBEAT_SECONDS`, and `event: end` when every job is terminal.
- `/api/chat/{session_id}/message` sends one `ChatEvent` per frame, with the
  SSE event name equal to the event's own `type`
  (`scope | tool | token | citation | done | error`).

Nothing here imports FastAPI. `acquire/applicability.py` returns a
`DocProposal` and must stay importable in a plain (non-`web`) install, so
these are pure pydantic models; the routers are where HTTP appears.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from datasheet_analyzer.app.buildstate import BUILD_STATES, BuildState
from datasheet_analyzer.models import (
    AnalyzeJob,
    Applicability,
    ChatMessage,
    ChatSession,
    CitationOut,
    JobState,
    LibraryDocument,
    ScopeRef,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Re-exported so a caller has one import for "the contract": the four models
# that must live in `models.py` (they are embedded in `ChatSession` and in
# `LibraryDocument`, which the pipeline persists) are part of this surface
# too.
__all__ = [
    "ANALYZE_EVENT_END",
    "ANALYZE_EVENT_JOB",
    "ANALYZE_EVENT_SNAPSHOT",
    "API_PREFIX",
    "BUILD_STATES",
    "CHAT_EVENT_TYPES",
    "EXPORT_FORMATS",
    "SSE_HEARTBEAT_SECONDS",
    "AnalyzeJob",
    "Applicability",
    "BrowseEntry",
    "BrowseListOut",
    "BrowsePickOut",
    "BuildState",
    "ChatEvent",
    "ChatEventType",
    "ChatMessage",
    "ChatSession",
    "CitationOut",
    "DocProposal",
    "ErrorOut",
    "JobEvent",
    "JobRegistryLike",
    "JobState",
    "LibraryDocument",
    "LibraryDocumentOut",
    "LibraryOut",
    "LibraryPatchIn",
    "LocateOut",
    "LocateQuery",
    "MessageIn",
    "PartOut",
    "PartsOut",
    "ProjectCreateIn",
    "ProjectExcludeIn",
    "ProjectOpenIn",
    "ProjectOut",
    "ProjectPartOut",
    "ProjectPartsIn",
    "ProjectPatchIn",
    "ProjectsOut",
    "RectOut",
    "ResolveIn",
    "RunSnapshot",
    "ScanIn",
    "ScanOut",
    "ScopeRef",
    "ScopeResolution",
    "SessionCreateIn",
    "SessionExportFormat",
    "SessionOut",
    "SessionSummary",
    "SessionsOut",
    "StartIn",
    "StartOut",
]

#: Every route in this application lives under this prefix; `/` and anything
#: that is not `/api/*` belongs to the built frontend (`app/static.py`).
API_PREFIX = "/api"

#: SSE keep-alive period. Browsers and intervening proxies drop an idle
#: connection, and a 40-PDF build is idle for minutes at a time.
SSE_HEARTBEAT_SECONDS = 15

#: The three SSE event names of the analyze stream.
ANALYZE_EVENT_SNAPSHOT = "snapshot"
ANALYZE_EVENT_JOB = "job"
ANALYZE_EVENT_END = "end"

ChatEventType = Literal["token", "tool", "citation", "scope", "done", "error"]
#: The chat stream's SSE event names — identical to `ChatEvent.type`.
CHAT_EVENT_TYPES: tuple[str, ...] = ("token", "tool", "citation", "scope", "done", "error")

SessionExportFormat = Literal["markdown", "golden"]
#: `markdown` pastes into a design review; `golden` drops into
#: `tests/fixtures/golden_qa_<PART>.yaml` as a regression test.
EXPORT_FORMATS: tuple[str, ...] = ("markdown", "golden")


# --- errors ------------------------------------------------------------------


class ErrorOut(BaseModel):
    """FastAPI's error body, modelled so the frontend can type it.

    `detail` is the human-readable reason and is always safe to render — the
    scope refusal text, the directory that does not exist, the recorded path
    a PDF has moved from. `kind` is an optional machine tag for the few cases
    a UI branches on.
    """

    detail: str = ""
    kind: str = ""


# --- catalog (ticket 06) ------------------------------------------------------


class PartOut(BaseModel):
    """One part corpus as the catalog sees it.

    Mirrors the MCP `list_parts` row key for key, including the deliberate
    listing of *unbuilt* parts: `discover_parts()` lists a directory whether
    or not it has a manifest, and a UI that hid half-built parts would hide
    the part a running job is about to finish.
    """

    part_number: str
    built: bool = False
    revision: str = ""
    vendor: str = ""
    backends: list[str] = Field(default_factory=list)
    sections: int = 0
    specs: int = 0
    plots: int = 0
    tokens: int = 0
    searchable: bool = False
    spec_confidence: dict[str, int] = Field(default_factory=dict)
    plot_confidence: dict[str, int] = Field(default_factory=dict)


class PartsOut(BaseModel):
    """`GET /api/parts` — every part directory, built or not, sorted by name."""

    parts: list[PartOut] = Field(default_factory=list)
    count: int = 0


class ProjectPartOut(BaseModel):
    """One member of a project, with the role its designer gave it."""

    part_number: str
    role: str = ""
    built: bool = False


class ProjectOut(BaseModel):
    """One project: its explicit member list and whether its index is built."""

    name: str
    parts: list[ProjectPartOut] = Field(default_factory=list)
    interfaces: str = ""
    notes: str = ""
    #: The directory this project was scanned from; `""` when not recorded.
    directory: str = ""
    #: Content hashes this project will never build. See `Exclusion` in
    #: CONTEXT.md — excluding is not deleting, and not removing a part.
    excluded: list[str] = Field(default_factory=list)
    built: bool = False
    error: str = ""


class ProjectOpenIn(BaseModel):
    """`POST /api/projects/open` — adopt a directory as a working set.

    The folder is the Batch; the project is named after it. Opening is
    idempotent: the same directory always resolves to the same project, so
    reopening is a load and never a second project pointing at one shelf.
    """

    directory: str


class ProjectExcludeIn(BaseModel):
    """`PUT /api/projects/{name}/exclusions` — the full set, not a delta.

    Sent whole because the review screen already holds the complete tick
    state; a delta API would make "untick two, tick one back" three round
    trips and leave the two out of step if one failed.
    """

    excluded: list[str] = Field(default_factory=list)


class ProjectPatchIn(BaseModel):
    """`PATCH /api/projects/{name}` — change the fields a user maintains.

    Every field is optional and `None` means "leave it alone", so a screen
    that edits one of them cannot blank the other two by omission. Parts are
    not here: they move through their own endpoints, where adding an unbuilt
    part can be refused with a reason.
    """

    directory: str | None = None
    interfaces: str | None = None
    notes: str | None = None


class ProjectCreateIn(BaseModel):
    """`POST /api/projects` — a new, empty working set.

    Parts are added afterwards rather than here: creating and populating in
    one call would make a half-valid member list fail the whole creation, and
    the screen adds parts one at a time anyway.
    """

    name: str
    interfaces: str = ""
    notes: str = ""


class ProjectPartsIn(BaseModel):
    """`POST /api/projects/{name}/parts` — parts to bring into the project."""

    parts: list[str] = Field(default_factory=list)
    role: str = ""


class ProjectsOut(BaseModel):
    """`GET /api/projects` — empty list (200) when `projects_dir` is absent."""

    projects: list[ProjectOut] = Field(default_factory=list)
    count: int = 0


# --- browsing for a folder ----------------------------------------------------


class BrowsePickOut(BaseModel):
    """`POST /api/browse/dialog` — the result of a native folder picker.

    Three outcomes, deliberately distinct: a folder was chosen, the user
    cancelled, or no dialog could be opened at all. Only the third is a reason
    for the client to fall back to the in-app listing; cancelling means the
    user changed their mind and should be left alone.
    """

    available: bool = True
    picked: bool = False
    directory: str = ""
    reason: str = ""


class BrowseEntry(BaseModel):
    """One selectable directory in the in-app browser."""

    name: str
    path: str


class BrowseListOut(BaseModel):
    """`GET /api/browse/list` — sub-directories of one path.

    `parent` is `""` at a filesystem root, which is how the UI knows not to
    offer "up".
    """

    path: str = ""
    parent: str = ""
    entries: list[BrowseEntry] = Field(default_factory=list)


# --- scan and review (tickets 02, 08) ----------------------------------------


class DocProposal(BaseModel):
    """What inference *proposes* for one PDF, before anything is built.

    Returned by `acquire.applicability.infer()` and rendered one per row on
    the review screen. `evidence` is the part-number evidence (the matched
    title-block line, `llm:<model>`, or the fallback that was used);
    `applicability.evidence` is the separate record of how the *applicability*
    was decided. Both are shown, because a user cannot judge `AFE79xx`
    without seeing the line it came from.

    A proposal is never authoritative: ticket 08 shows it, the user edits it,
    and `/api/analyze/start` uses what came back verbatim.
    """

    pdf_path: str
    filename: str = ""
    part_number: str = ""
    applicability: Applicability = Field(default_factory=Applicability)
    evidence: str = ""
    page_count: int = 0
    # Optional extras a scan may fill without a second pass over the file.
    doc_type: str = ""
    content_hash: str = ""
    #: Whether analyzing this PDF will actually do any work, and why. Reported
    #: by `app/buildstate.classify`, which asks `batch.skip_reason` rather than
    #: deciding anything itself. `current` is the only state that costs
    #: nothing. Defaults to `new` so a caller that never classified promises
    #: work rather than promising there is none.
    build_state: BuildState = "new"
    build_reason: str = ""
    #: Where this PDF sits under the scanned directory (`""` at the top), so
    #: the review can group by folder — a recursive walk makes folder
    #: structure meaningful, and two `datasheet.pdf` files in different
    #: subdirectories are otherwise indistinguishable.
    relative_dir: str = ""
    #: False when the classifier judged this is not a source document at all.
    #: A recursive walk finds purchase orders and mechanical drawings; those
    #: start unticked rather than hidden, so the user confirms rather than
    #: hunts.
    is_datasheet: bool = True


class ScanIn(BaseModel):
    """`POST /api/analyze/scan` — a server-side directory path.

    A browser cannot hand a server a usable directory path, so this is typed
    or pasted by the user and validated here. A missing or empty directory is
    a 400 naming the path: a typo must never silently scan nothing.
    """

    directory: str


class ScanOut(BaseModel):
    """One proposal per direct-child `*.pdf`, sorted by filename.

    `states` tallies `DocProposal.build_state` so a caller can say "38 current,
    2 will rebuild" without walking the rows — the screen needs the summary
    before it decides whether to show a review table at all.
    """

    directory: str = ""
    proposals: list[DocProposal] = Field(default_factory=list)
    count: int = 0
    states: dict[str, int] = Field(default_factory=dict)
    #: Directories the walk deliberately did not descend into, each with its
    #: reason. Reported rather than swallowed: a scan that silently ignored
    #: half a shelf is indistinguishable from one that found everything.
    skipped: list[str] = Field(default_factory=list)

    @property
    def rebuild_count(self) -> int:
        """How many of these will actually do work."""
        return sum(n for state, n in self.states.items() if state != "current")


class StartIn(BaseModel):
    """`POST /api/analyze/start` — the proposals the user confirmed.

    The server does not re-infer: an edited `part_number` or `applicability`
    is used exactly as posted, which is the whole point of the review screen.
    """

    directory: str = ""
    proposals: list[DocProposal] = Field(default_factory=list)


class StartOut(BaseModel):
    """Returned immediately — the build runs in the background."""

    run_id: str
    n_jobs: int = 0


class JobEvent(BaseModel):
    """One job transition on the analyze stream.

    `detail` carries the human sentence for the state: the skip reason for
    `SKIPPED`, the error text for `FAILED`, the stage note otherwise.
    """

    run_id: str
    job_id: str
    part_number: str = ""
    pdf_path: str = ""
    state: JobState = JobState.QUEUED
    detail: str = ""
    at: datetime = Field(default_factory=_utcnow)


class RunSnapshot(BaseModel):
    """Every job's current state — sent on connect, and again on reconnect.

    A client attaching mid-run (or after a dropped stream) re-renders from
    this rather than showing a gap, which is why the stream leads with it
    instead of with the next transition.
    """

    run_id: str
    directory: str = ""
    jobs: list[AnalyzeJob] = Field(default_factory=list)
    done: bool = False


@runtime_checkable
class JobRegistryLike(Protocol):
    """The process-wide analyze registry, as its callers may rely on it.

    Frozen here rather than in `app/jobs.py` (ticket 07) because
    `app/deps.py` (ticket 06) returns one and must be writable before ticket
    07 lands. The implementation may add to this; it may not narrow it.
    """

    def start(self, *, directory: str, proposals: list[DocProposal]) -> str:
        """Create a run, dispatch its jobs, and return the `run_id` at once."""
        ...

    def exists(self, run_id: str) -> bool:
        """False for an unknown run — the router turns that into a 404."""
        ...

    def run(self, run_id: str) -> list[AnalyzeJob]:
        """Snapshot of every job in the run, in dispatch order."""
        ...

    def snapshot(self, run_id: str) -> RunSnapshot:
        """The snapshot frame the stream opens with."""
        ...

    def events(self, run_id: str) -> AsyncIterator[JobEvent]:
        """Every transition from now on, one feed per connected client.

        Two clients may watch the same run, so this hands out an independent
        feed rather than a shared queue one reader would drain from the other.
        """
        ...


# --- library (tickets 01, 09) -------------------------------------------------


class LibraryDocumentOut(BaseModel):
    """One library document plus the parts it currently *reaches*.

    "Reaches" is derived, never stored: a part is the view of the documents
    whose applicability covers it, so widening applicability changes the
    reach immediately and changes nothing on disk under `parts/`.
    `rebuild_needed` is the offer the UI makes afterwards — materializing a
    new reach into a corpus is a build's job, not a patch's.
    """

    content_hash: str
    path: str = ""
    filename: str = ""
    part_number: str = ""
    doc_type: str = ""
    vendor: str = ""
    page_count: int = 0
    applicability: Applicability = Field(default_factory=Applicability)
    labels: list[str] = Field(default_factory=list)
    added_at: datetime | None = None
    parts_reached: list[str] = Field(default_factory=list)
    unbuilt_parts: list[str] = Field(default_factory=list)
    rebuild_needed: list[str] = Field(default_factory=list)

    @classmethod
    def from_document(
        cls,
        doc: LibraryDocument,
        *,
        parts_reached: list[str] | tuple[str, ...] = (),
        unbuilt_parts: list[str] | tuple[str, ...] = (),
        rebuild_needed: list[str] | tuple[str, ...] = (),
    ) -> LibraryDocumentOut:
        """Project a stored `LibraryDocument` into its wire shape."""
        source = doc.source
        return cls(
            content_hash=source.content_hash,
            path=source.path,
            filename=doc.filename,
            part_number=source.part_number,
            doc_type=source.doc_type.value,
            vendor=source.vendor,
            page_count=source.page_count,
            applicability=doc.applicability,
            labels=list(doc.labels),
            added_at=doc.added_at,
            parts_reached=list(parts_reached),
            unbuilt_parts=list(unbuilt_parts),
            rebuild_needed=list(rebuild_needed),
        )


class LibraryOut(BaseModel):
    """`GET /api/library` — the whole shelf, plus every label in use.

    `labels` is the union across the library, so the label editor can
    autocomplete without a second request.
    """

    documents: list[LibraryDocumentOut] = Field(default_factory=list)
    count: int = 0
    labels: list[str] = Field(default_factory=list)


class LibraryPatchIn(BaseModel):
    """`PATCH /api/library/{content_hash}` — applicability, labels, or both.

    Both fields are `None`-by-omission rather than defaulted, so "leave this
    alone" and "set this to empty" stay distinguishable: `labels: []` clears
    every label, `labels` absent keeps them.
    """

    applicability: Applicability | None = None
    labels: list[str] | None = None


# --- chat (tickets 10, 12) ----------------------------------------------------


class ResolveIn(BaseModel):
    """`POST /api/chat/resolve-scope` — the question, before it is asked."""

    question: str


class ScopeResolution(BaseModel):
    """Which Part or Project a question resolved to — or a question back.

    Three states, and the model can represent exactly these three:

    | state | `scope` | `confident` | `candidates` | `question` |
    |---|---|---|---|---|
    | confident | the scope | `True` | empty | empty |
    | ambiguous | `None` | `False` | the options | what to ask |
    | no match | `None` | `False` | empty | what to ask |

    `scope is None` with candidates means **ask the user** — never guess, and
    never widen to everything (ADR 0006). A single built part is not a safe
    default either: answering from the only part that happens to exist is
    exactly the implicit scope the invariant forbids.
    """

    scope: ScopeRef | None = None
    confident: bool = False
    candidates: list[ScopeRef] = Field(default_factory=list)
    question: str = ""
    matched_via: str = ""

    @property
    def ambiguous(self) -> bool:
        """True when the user must choose before a model call is made."""
        return self.scope is None and bool(self.candidates)


class MessageIn(BaseModel):
    """`POST /api/chat/{session_id}/message`.

    `scope` present means the user picked it (from the chip or from the
    ambiguity prompt) and resolution is skipped; absent means resolve first.
    """

    question: str
    scope: ScopeRef | None = None


class ChatEvent(BaseModel):
    """One frame of the chat stream. `type` is also the SSE event name.

    | `type` | carries | when |
    |---|---|---|
    | `scope` | `scope`, `resolution` | once, before any model call |
    | `tool` | `tool`, `summary` | a tool is about to run |
    | `token` | `text` | each text delta |
    | `citation` | `citation` | a `Citation` from a tool result |
    | `done` | `message` (optional) | the turn finished |
    | `error` | `message` | the turn failed; the stream then closes |

    A `citation` frame is only ever built from a `Citation` object inside a
    tool result the runner executed. A citation the model wrote into its
    prose has no tool result behind it and therefore produces no frame.
    """

    type: ChatEventType
    text: str = ""
    tool: str = ""
    summary: str = ""
    citation: CitationOut | None = None
    scope: ScopeRef | None = None
    resolution: ScopeResolution | None = None
    confidence: str = ""
    message: str = ""
    at: datetime = Field(default_factory=_utcnow)

    @classmethod
    def for_token(cls, text: str) -> ChatEvent:
        return cls(type="token", text=text)

    @classmethod
    def for_tool(cls, tool: str, summary: str = "") -> ChatEvent:
        return cls(type="tool", tool=tool, summary=summary)

    @classmethod
    def for_citation(cls, citation: CitationOut, *, confidence: str = "") -> ChatEvent:
        return cls(type="citation", citation=citation, confidence=confidence)

    @classmethod
    def for_scope(cls, resolution: ScopeResolution) -> ChatEvent:
        return cls(type="scope", scope=resolution.scope, resolution=resolution)

    @classmethod
    def for_done(cls, message: str = "") -> ChatEvent:
        return cls(type="done", message=message)

    @classmethod
    def for_error(cls, message: str) -> ChatEvent:
        return cls(type="error", message=message)


# --- sessions (ticket 15) -----------------------------------------------------


class SessionCreateIn(BaseModel):
    """`POST /api/sessions`. The id is generated server-side, always.

    A client-supplied id is never used as a filename — session files are
    written by id, and a caller-chosen name is a path the caller controls.
    """

    title: str = ""
    scope: ScopeRef | None = None


class SessionSummary(BaseModel):
    """One row of the sessions list: enough to choose, nothing more."""

    id: str
    title: str = ""
    scope: ScopeRef = Field(default_factory=ScopeRef)
    n_messages: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionsOut(BaseModel):
    """`GET /api/sessions` — newest first. A malformed file is skipped."""

    sessions: list[SessionSummary] = Field(default_factory=list)
    count: int = 0


class SessionOut(BaseModel):
    """One full transcript, with every citation intact."""

    id: str
    title: str = ""
    scope: ScopeRef = Field(default_factory=ScopeRef)
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    n_messages: int = 0

    @classmethod
    def from_session(cls, session: ChatSession) -> SessionOut:
        return cls(
            id=session.id,
            title=session.title,
            scope=session.scope,
            messages=list(session.messages),
            created_at=session.created_at,
            updated_at=session.updated_at,
            n_messages=len(session.messages),
        )

    @property
    def summary(self) -> SessionSummary:
        return SessionSummary(
            id=self.id,
            title=self.title,
            scope=self.scope,
            n_messages=self.n_messages,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


# --- locate (ticket 13) -------------------------------------------------------


class LocateQuery(BaseModel):
    """`GET /api/locate` query parameters.

    `doc_hash` is a `SourceDocument.content_hash`; the PDF is resolved
    through the manifest join (`doc_hash` -> `documents[*].content_hash` ->
    `path`), never from a caller-supplied path. `needle` is the record's own
    text — a spec row's most distinctive cell, a table caption, the opening
    of a paragraph — chosen by the caller that owns the record.
    """

    part: str = ""
    doc_hash: str = ""
    page: int = 1
    needle: str = ""


class RectOut(BaseModel):
    """One highlight rectangle in **PDF points**, PyMuPDF's coordinate space.

    Origin is the page's **top-left**, x grows right and y grows *down*, and
    the values are unrotated page coordinates at zoom 1.0 — exactly what
    `fitz.Page.search_for()` returns. A viewer converts by applying its own
    zoom and the page's rotation; it must never assume PDF-native bottom-left
    origin, because these are already flipped.
    """

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


class LocateOut(BaseModel):
    """Where to draw the highlight — or an honest miss.

    `found=False` carries an empty `rects` and a human-readable `reason`, and
    the viewer opens the page with no highlight. A box around the wrong row
    is worse than no box: it turns the verification step this application
    exists for into a lie. Leaving it unpinned rather than guessing is the
    same rule `structure/pagemap.pin_table_pages()` follows.

    `page_width` / `page_height` / `rotation` describe the page the rects are
    measured against, so a viewer can validate its own scaling instead of
    assuming it.
    """

    found: bool = False
    page: int = 0
    rects: list[RectOut] = Field(default_factory=list)
    reason: str = ""
    needle: str = ""
    page_width: float = 0.0
    page_height: float = 0.0
    rotation: int = 0

    @classmethod
    def miss(cls, reason: str, *, page: int = 0, needle: str = "") -> LocateOut:
        """The honest miss: no rects, and a reason a human can act on."""
        return cls(found=False, page=page, rects=[], reason=reason, needle=needle)
