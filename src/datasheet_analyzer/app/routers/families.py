"""`GET /api/families` — the families a human has declared, and only those.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/families` | — | `FamiliesOut` |

This endpoint exists so a pane can *offer* a family scope. Until it landed the
third `ScopeRef.kind` was nameable everywhere and offerable nowhere, which was
recorded rather than half-built: `deps.get_retriever` has resolved a family
since the phase 7 port, but nothing could put one in front of a user.

**Membership is declared, never inferred, and this route is where that rule
meets the UI.** Every entry is passed through `families.registry.resolve`, the
single function that refuses an undeclared name, an unconfirmed entry and a
family with no members — three refusals written once, in the module that owns
the file. Nothing here reads `families.candidate.yaml`; `load_families` refuses
that file *by name*, so a proposal cannot arrive as a declaration even if
somebody points the loader at it. A UI that only offers what this returns
therefore cannot invent a grouping, and one that lets a user type a family name
anyway gets the registry's own refusal back from
`/api/chat/{id}/message` — verbatim, through `deps.get_retriever`'s 400.

Nothing here is a 404 and nothing here is a 500. A shelf with no
`registry/families.yaml` is an empty list with 200: "nobody has declared a
family" is a real answer and a picker should say so, in the same words this
repo uses for an empty `parts_dir`.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from datasheet_analyzer.app.contracts import API_PREFIX, FamiliesOut, FamilyOut
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.config import Settings

log = logging.getLogger(__name__)

__all__ = ["declared_families", "router"]

router = APIRouter(prefix=API_PREFIX, tags=["families"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def declared_families(settings: Settings) -> list[FamilyOut]:
    """Every declared, confirmed, non-empty family, name-ordered.

    Read through `resolve` rather than off `FamilyRegistry.families` directly:
    the three ways an entry can fail to be a declaration live in that one
    function, and re-checking them here is how they would drift apart.
    """
    from datasheet_analyzer.families import (
        FamilyMiss,
        FamilyUnconfirmed,
        families_path,
        load_families,
        resolve,
    )
    from datasheet_analyzer.projects import is_built

    try:
        registry = load_families(families_path(settings.registry_dir))
    except (FamilyMiss, FamilyUnconfirmed, OSError, ValueError) as exc:
        # An unreadable or misdirected registry is "no families declared" for
        # a picker, not a broken application: the rest of the workbench is
        # unaffected, and the reason is logged rather than rendered as a
        # family that does not exist.
        log.warning("families registry could not be read: %s", exc)
        return []

    out: list[FamilyOut] = []
    for name in registry.names:
        try:
            entry = resolve(registry, name)
        except (FamilyMiss, FamilyUnconfirmed):
            # An entry that says `confirmed: false`, or declares no members.
            # Skipped, not repaired: promoting it is a person's decision.
            continue
        out.append(
            FamilyOut(
                name=entry.name,
                title=entry.title,
                members=list(entry.members),
                reference=entry.reference,
                note=entry.note,
                unbuilt_members=[m for m in entry.members if not is_built(m, settings.parts_dir)],
            )
        )
    return out


@router.get("/families", response_model=FamiliesOut)
def get_families(settings: SettingsDep) -> FamiliesOut:
    """The declared families. Never a proposal, never an inference."""
    families = declared_families(settings)
    return FamiliesOut(families=families, count=len(families))
