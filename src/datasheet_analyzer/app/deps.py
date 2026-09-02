"""FastAPI dependency providers (ticket 06).

**Signatures frozen by ticket 00; bodies are ticket 06's.**

Every router injects through these, and every one is overridable in a test
via `app.dependency_overrides` — that overridability is what lets tickets
07–15 test their routers against fakes without importing each other's
implementations.

Every provider is a **zero-argument** callable on purpose. A provider that
took `settings: Settings = Depends(get_settings_dep)` would read better as
FastAPI, and would stop being callable as a plain function from a background
job, a CLI path or a test — so settings are read from the process-wide cache
here and pointed somewhere else with `reset_settings_cache()` (tests) or
`app.dependency_overrides` (routers).

`get_retriever` deliberately delegates to `retrieve.scope.resolve_scope`
(ticket 05) rather than resolving a scope itself: the XOR precondition and
its refusal text are the invariant from ADR 0006, and an adapter that
re-implemented them would be the place they drift. An invalid scope is a 400
carrying that refusal text verbatim — never a 500, and never a silent widen.
The import is deferred to call time for one more reason: `retrieve/scope.py`
is optional at import time, so a half-installed tree surfaces as one failing
request rather than as an application that will not start.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import HTTPException

from datasheet_analyzer.app.contracts import (
    AnalyzeJob,
    DocProposal,
    JobEvent,
    JobRegistryLike,
    RunSnapshot,
    ScopeRef,
)
from datasheet_analyzer.app.sessions import SessionStore
from datasheet_analyzer.config import Settings, get_settings
from datasheet_analyzer.library.store import LibraryStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datasheet_analyzer.retrieve.family import FamilyRetriever
    from datasheet_analyzer.retrieve.project import ProjectRetriever
    from datasheet_analyzer.retrieve.retriever import Retriever

__all__ = [
    "get_job_registry",
    "get_library",
    "get_retriever",
    "get_session_store",
    "get_settings_dep",
    "reset_job_registry",
]

#: What `get_job_registry` says when `app/jobs.py` (ticket 07) is not
#: installed. 503 rather than 500: the endpoint is fine, the capability is
#: absent, and the sentence names what is missing.
JOBS_UNAVAILABLE = (
    "analyze jobs are unavailable: `datasheet_analyzer.app.jobs` exposes no "
    "job registry in this install — the rest of the API is unaffected"
)

_registry_lock = threading.Lock()
_registry: JobRegistryLike | None = None


def get_settings_dep() -> Settings:
    """The cached, resolved `Settings` for this process."""
    return get_settings()


def get_library() -> LibraryStore:
    """The `LibraryStore` over `settings.library_dir`."""
    return LibraryStore(get_settings_dep().library_dir)


def get_retriever(scope: ScopeRef) -> Retriever | ProjectRetriever | FamilyRetriever:
    """A `Retriever` for a part, a `ProjectRetriever` for a design, a
    `FamilyRetriever` for a declared series.

    Raises `HTTPException(400)` carrying `resolve_scope`'s refusal text when
    the scope names nothing that exists.

    The three-way split is `ScopeRef.kind`'s, not this function's: exactly one
    of the three names is ever non-empty, so ADR 0006's precondition is
    satisfied structurally rather than re-checked here.
    """
    from datasheet_analyzer.retrieve.scope import resolve_scope

    settings = get_settings_dep()
    name = (scope.name or "").strip() if scope is not None else ""
    kind = scope.kind if scope is not None else "part"
    part = name if kind == "part" else ""
    project = name if kind == "project" else ""
    family = name if kind == "family" else ""
    retriever, reason = resolve_scope(part, project, settings=settings, family=family)
    if retriever is None:
        # The refusal text travels verbatim: it is the only place ADR 0006's
        # rationale is written down, and a UI is meant to render it as-is.
        raise HTTPException(status_code=400, detail=reason)
    return retriever


def get_job_registry() -> JobRegistryLike:
    """The process-wide analyze registry (ticket 07 fills it in).

    Process-wide on purpose: a run outlives the request that started it, and
    a second client must be able to attach to the same stream.
    """
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = _build_job_registry()
        return _registry


def reset_job_registry() -> None:
    """Test hook: drop the process-wide registry (mirrors the cache hooks)."""
    global _registry
    with _registry_lock:
        _registry = None


def get_session_store() -> SessionStore:
    """The `SessionStore` over `settings.sessions_dir` (ticket 15)."""
    return SessionStore(get_settings_dep().sessions_dir)


def _build_job_registry() -> JobRegistryLike:
    """Ticket 07's registry, or an honest placeholder that 503s on use.

    Resolved by name rather than imported at module scope so `deps.py` stays
    importable — and every other provider stays usable — in a tree where
    `app/jobs.py` has not landed.
    """
    try:
        from datasheet_analyzer.app import jobs as jobs_module
    except ImportError:
        return _UnavailableJobRegistry()
    factory = getattr(jobs_module, "get_registry", None)
    if callable(factory):
        return factory()
    registry_cls = getattr(jobs_module, "JobRegistry", None)
    if registry_cls is not None:
        return registry_cls()
    return _UnavailableJobRegistry()


class _UnavailableJobRegistry:
    """A `JobRegistryLike` that refuses, in the shape callers expect.

    Returning this rather than raising at import time keeps one missing
    module from taking down `/api/parts`, `/api/library` and the chat loop —
    the same honest-degradation rule the corpus readers follow.
    """

    def start(self, *, directory: str, proposals: list[DocProposal]) -> str:
        raise HTTPException(status_code=503, detail=JOBS_UNAVAILABLE)

    def exists(self, run_id: str) -> bool:
        return False

    def run(self, run_id: str) -> list[AnalyzeJob]:
        raise HTTPException(status_code=503, detail=JOBS_UNAVAILABLE)

    def snapshot(self, run_id: str) -> RunSnapshot:
        raise HTTPException(status_code=503, detail=JOBS_UNAVAILABLE)

    def events(self, run_id: str) -> AsyncIterator[JobEvent]:
        raise HTTPException(status_code=503, detail=JOBS_UNAVAILABLE)
