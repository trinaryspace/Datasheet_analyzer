"""`GET /api/parts` and `GET /api/projects` — the catalog (ticket 06).

The two endpoints the shell loads before anything else: what is on this
machine, and how much of it is built. Both are adapters over the same
functions the MCP server's `list_parts` / `list_projects` call
(`retrieve.index.discover_parts`, `projects.store.list_projects`), so the
three front ends cannot disagree about what a part *is*.

Two behaviours here are deliberate rather than incidental:

- **Half-built parts are listed**, flagged `built: false`. `discover_parts()`
  lists a directory whether or not it has a manifest, and a UI that hid them
  would hide the part a running job is about to finish.
- **Nothing here is a 404.** An empty `parts_dir` (or a `projects_dir` that
  does not exist yet) is an empty list with 200: "you have not built anything
  yet" is a real answer, and a fresh machine must render as empty rather than
  as broken.

A project whose `project.json` will not load is reported as a row carrying
`error` instead of being dropped — the same honest-degradation rule the
corpus readers follow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from datasheet_analyzer.app.contracts import (
    API_PREFIX,
    PartOut,
    PartsOut,
    ProjectOut,
    ProjectPartOut,
    ProjectsOut,
)
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.config import Settings
from datasheet_analyzer.projects import (
    INDEX_FILENAME as PROJECT_INDEX_FILENAME,
)
from datasheet_analyzer.projects import (
    ProjectError,
    is_built,
    list_projects,
    load_project,
    project_dir,
)
from datasheet_analyzer.retrieve import Retriever, discover_parts

router = APIRouter(prefix=API_PREFIX, tags=["catalog"])

#: Injected rather than read: `app.dependency_overrides[get_settings_dep]`
#: points a whole app at a temporary corpus without touching the environment.
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


@router.get("/parts", response_model=PartsOut)
def get_parts(settings: SettingsDep) -> PartsOut:
    """Every part directory under `parts_dir`, built or not, sorted by name."""
    parts = [_part_row(part_dir) for part_dir in discover_parts(settings.parts_dir)]
    return PartsOut(parts=parts, count=len(parts))


@router.get("/projects", response_model=ProjectsOut)
def get_projects(settings: SettingsDep) -> ProjectsOut:
    """Every project under `projects_dir`; `[]` when the directory is absent."""
    projects = [_project_row(name, settings) for name in list_projects(settings.projects_dir)]
    return ProjectsOut(projects=projects, count=len(projects))


def _part_row(part_dir: Path) -> PartOut:
    """One catalog row, read off the manifest the publisher wrote.

    A part with no manifest is not built: it is reported with its directory
    name and zeroes rather than with invented counts, because a half-built
    corpus that looked complete is worse than one that says so.
    """
    scope = Retriever.for_part(part_dir)
    manifest = scope.index.manifest
    if manifest is None:
        return PartOut(part_number=part_dir.name, built=False)
    stats = manifest.stats
    return PartOut(
        part_number=manifest.part_number or part_dir.name,
        built=True,
        revision=_revision(manifest),
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
    )


def _project_row(name: str, settings: Settings) -> ProjectOut:
    """One project row: its members, their roles, and whether it is indexed."""
    try:
        project = load_project(name, settings.projects_dir)
    except ProjectError as exc:
        return ProjectOut(name=name, error=str(exc))
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
    )


def _revision(manifest) -> str:
    """The datasheet revision this corpus was built from; `""` when unknown."""
    if not manifest.documents:
        return ""
    return manifest.documents[0].revision
