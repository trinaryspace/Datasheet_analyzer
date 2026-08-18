"""Writing to a project — create it, and move parts in and out of it.

`catalog.py` reads projects; this module is the write half, kept separate so
the read path stays a pure catalog. Together they make a project the thing a
user curates while they work: the shelf for *this* design, rather than every
datasheet on disk.

Why a project and not a new kind of collection: a project is already the noun
above `part` (`projects/store.py`), already carries an explicit human-curated
member list, and — the reason that settles it — is already one of the two
things a question may be scoped to under ADR 0006. A parallel "collection"
concept would organize the shelf without being answerable, so the set a user
assembles and the set their question reads would be two different sets.

Documents are not members. Under ADR 0005 a document applies to parts and a
part is the *view* of the documents that apply to it, so a project that names
its parts already names its documents transitively. Putting a document into
a project therefore means widening that document's applicability to reach a
part the project holds — which is `PATCH /api/library/{hash}`, and stays
there rather than being duplicated here.

Every write is last-writer-wins on one small JSON file, which is what a
single-user local application can afford; there is no locking and no revision
check.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from datasheet_analyzer.app.contracts import (
    API_PREFIX,
    ProjectCreateIn,
    ProjectOut,
    ProjectPartOut,
    ProjectPartsIn,
    ProjectPatchIn,
)
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.config import Settings
from datasheet_analyzer.projects import (
    INDEX_FILENAME as PROJECT_INDEX_FILENAME,
)
from datasheet_analyzer.projects import (
    ProjectError,
    add_parts,
    exists,
    is_built,
    load_project,
    new_project,
    project_dir,
    remove_parts,
    save_project,
    validate_name,
)

router = APIRouter(prefix=API_PREFIX, tags=["projects"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreateIn, settings: SettingsDep) -> ProjectOut:
    """Create an empty project. 409 when the name is taken, 400 when invalid."""
    name = body.name.strip()
    try:
        # `exists()` validates the name too, so it belongs inside the guard:
        # left outside it, an illegal name escaped as a 500 instead of as the
        # 400 whose message says what a legal name looks like.
        validate_name(name)
        if exists(name, settings.projects_dir):
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"project {name!r} already exists")
        project = new_project(
            name, settings.projects_dir, interfaces=body.interfaces, notes=body.notes
        )
        save_project(project, settings.projects_dir)
    except ProjectError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _row(project.name, settings)


@router.post("/projects/{name}/parts", response_model=ProjectOut)
def add_project_parts(name: str, body: ProjectPartsIn, settings: SettingsDep) -> ProjectOut:
    """Add parts to a project.

    `add_parts` enforces the precondition that a member is a real part
    directory, so naming a part that was never analyzed is a 400 carrying that
    reason rather than a project quietly holding a member that resolves to
    nothing.
    """
    project = _load(name, settings)
    try:
        add_parts(project, body.parts, parts_dir=settings.parts_dir, role=body.role)
        save_project(project, settings.projects_dir)
    except ProjectError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _row(project.name, settings)


@router.patch("/projects/{name}", response_model=ProjectOut)
def patch_project(name: str, body: ProjectPatchIn, settings: SettingsDep) -> ProjectOut:
    """Change the fields a user maintains: the directory, interfaces, notes.

    `None` means "leave it alone" for every field, so a screen editing one of
    them cannot blank the other two by omitting them. Parts are deliberately
    not patchable here — they move through their own endpoints, where adding
    an unbuilt part can be refused with a reason instead of silently stored.
    """
    project = _load(name, settings)
    if body.directory is not None:
        # Recorded verbatim, exactly as `ScanIn.directory` is given. It is a
        # path on the machine running the server, and normalising it here
        # would stop it matching what the user typed on the Analyze screen.
        project.directory = body.directory.strip()
    if body.interfaces is not None:
        project.interfaces = body.interfaces
    if body.notes is not None:
        project.notes = body.notes
    try:
        save_project(project, settings.projects_dir)
    except ProjectError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _row(project.name, settings)


@router.delete("/projects/{name}/parts/{part_number}", response_model=ProjectOut)
def remove_project_part(name: str, part_number: str, settings: SettingsDep) -> ProjectOut:
    """Remove one part from a project.

    Removing a part it does not hold is not an error: the caller asked for a
    project without that part, and that is the state they get. Nothing on disk
    under `parts/` is touched — a project is a view, and leaving it must never
    delete a corpus.
    """
    project = _load(name, settings)
    try:
        remove_parts(project, [part_number])
        save_project(project, settings.projects_dir)
    except ProjectError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _row(project.name, settings)


def _load(name: str, settings: Settings):
    """The project, or a 404 naming it."""
    try:
        return load_project(name, settings.projects_dir)
    except ProjectError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _row(name: str, settings: Settings) -> ProjectOut:
    """The same shape `GET /api/projects` returns, so a write refreshes a list.

    Deliberately re-read from disk rather than rendered from the in-memory
    object: the response is then the state a subsequent GET would show, which
    is what the screen replaces its row with.
    """
    project = load_project(name, settings.projects_dir)
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
        directory=project.directory,
        built=(project_dir(project.name, settings.projects_dir) / PROJECT_INDEX_FILENAME).exists(),
    )
