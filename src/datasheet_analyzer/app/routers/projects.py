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

import hashlib
import logging
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from datasheet_analyzer.app.contracts import (
    API_PREFIX,
    ProjectCreateIn,
    ProjectExcludeIn,
    ProjectOpenIn,
    ProjectOut,
    ProjectPartOut,
    ProjectPartsIn,
    ProjectPatchIn,
    ShelfAddIn,
    ShelfAddOut,
    ShelfDocument,
    ShelfOut,
)
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.config import Settings
from datasheet_analyzer.extract.pdf_structure import compute_content_hash
from datasheet_analyzer.library.store import LibraryStore
from datasheet_analyzer.projects import (
    INDEX_FILENAME as PROJECT_INDEX_FILENAME,
)
from datasheet_analyzer.projects import (
    ProjectError,
    add_parts,
    exists,
    is_built,
    list_projects,
    load_project,
    new_project,
    project_dir,
    remove_parts,
    save_project,
    validate_name,
)
from datasheet_analyzer.projects.shelf import copy_onto_shelf, pdfs_on_shelf
from datasheet_analyzer.retrieve import discover_parts

log = logging.getLogger(__name__)

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


@router.post("/projects/open", response_model=ProjectOut)
def open_project(body: ProjectOpenIn, settings: SettingsDep) -> ProjectOut:
    """Adopt a directory as a working set, creating the project if needed.

    Idempotent by directory: opening the same folder twice resolves to the
    same project, never a second one pointing at the same shelf. That is what
    makes "swap projects by swapping folders" safe to do repeatedly.

    The folder's name is slugified because project names are constrained
    (`[A-Za-z0-9._-]`, starting alphanumeric) and real folders are not —
    `Radar 7-8G` is an ordinary thing to call a directory. On a name collision
    with a project pointing somewhere *else*, a short digest of the path is
    appended rather than adopting a stranger's project, which would silently
    repoint their working set at your files.
    """
    raw = (body.directory or "").strip()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no directory given")
    directory = Path(raw).expanduser()
    if not directory.is_dir():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"directory not found: {raw}"
        )
    resolved = str(directory)

    for existing in list_projects(settings.projects_dir):
        try:
            candidate = load_project(existing, settings.projects_dir)
        except ProjectError:
            continue
        if candidate.directory and _same_directory(candidate.directory, resolved):
            return _row(candidate.name, settings)

    name = _available_name(directory, resolved, settings)
    try:
        project = new_project(name, settings.projects_dir)
        project.directory = resolved
        save_project(project, settings.projects_dir)
    except ProjectError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _row(project.name, settings)


@router.put("/projects/{name}/exclusions", response_model=ProjectOut)
def set_exclusions(name: str, body: ProjectExcludeIn, settings: SettingsDep) -> ProjectOut:
    """Replace the set of documents this project will never build.

    The whole set, not a delta: the review screen already holds the complete
    tick state, and a delta API would turn "untick two, tick one back" into
    three round trips that can disagree if one fails.
    """
    project = _load(name, settings)
    project.excluded = sorted({h.strip() for h in body.excluded if h.strip()})
    try:
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


def _same_directory(a: str, b: str) -> bool:
    """Whether two recorded paths name one folder, re-spellings included."""
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, ValueError):
        return a.strip().rstrip("/\\").lower() == b.strip().rstrip("/\\").lower()


def _slugify(folder_name: str) -> str:
    """A folder name as a legal project name, or `project` when nothing survives."""
    kept = [ch if (ch.isalnum() or ch in "._-") else "-" for ch in folder_name.strip()]
    slug = re.sub(r"-{2,}", "-", "".join(kept)).strip("-.")
    while slug and not slug[0].isalnum():
        slug = slug[1:]
    return slug.lower() or "project"


def _available_name(directory: Path, resolved: str, settings: Settings) -> str:
    """The slug, or the slug plus a path digest when the slug is taken."""
    slug = _slugify(directory.name or resolved)
    if not exists(slug, settings.projects_dir):
        return slug
    digest = hashlib.sha256(resolved.encode("utf-8", "replace")).hexdigest()[:6]
    return f"{slug}-{digest}"


@router.get("/projects/{name}/shelf", response_model=ShelfOut)
def get_shelf(name: str, settings: SettingsDep) -> ShelfOut:
    """Every PDF in the project's folder, marked with what the Library knows.

    Two sets joined on the content hash: the files that are *there*, and the
    documents that have been *processed*. The rail needs both — "the model can
    read this" and "this is on your shelf but unbuilt" are different answers
    and a reader must be able to tell them apart.
    """
    project = _load(name, settings)
    directory = Path(project.directory) if project.directory else None
    if directory is None or not directory.is_dir():
        return ShelfOut(project=project.name, directory=project.directory)

    store = LibraryStore.for_settings(settings)
    known = {doc.content_hash: doc for doc in store.all()}
    excluded = set(project.excluded)

    documents: list[ShelfDocument] = []
    for pdf in pdfs_on_shelf(directory):
        try:
            content_hash = compute_content_hash(pdf)
        except OSError:  # a file that vanished mid-listing is simply not shown
            continue
        entry = known.get(content_hash)
        documents.append(
            ShelfDocument(
                filename=pdf.name,
                path=str(pdf),
                relative_dir=_relative_dir(pdf, directory),
                content_hash=content_hash,
                processed=entry is not None,
                part_number=entry.source.part_number if entry else "",
                parts_reached=_parts_reached(entry, settings) if entry else [],
                labels=list(entry.labels) if entry else [],
                page_count=entry.source.page_count if entry else 0,
                excluded=content_hash in excluded,
            )
        )

    return ShelfOut(
        project=project.name,
        directory=str(directory),
        documents=documents,
        count=len(documents),
        processed_count=sum(1 for d in documents if d.processed),
    )


@router.post("/projects/{name}/shelf", response_model=ShelfAddOut)
def add_to_shelf(name: str, body: ShelfAddIn, settings: SettingsDep) -> ShelfAddOut:
    """Copy a processed document's PDF onto this project's shelf.

    The copy is what makes a project portable: its folder ends up holding the
    sources it was built from. Nothing is ever overwritten — same bytes means
    no copy at all, and a name taken by different bytes lands beside it.

    Built parts the document reaches join the project, because otherwise you
    would add a document and the project still could not answer questions
    about it. Unbuilt reached parts are left out: `add_parts` refuses them, and
    the shelf shows the document with a build offer instead.
    """
    project = _load(name, settings)
    if not project.directory:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"project {name!r} has no folder to copy into",
        )

    store = LibraryStore.for_settings(settings)
    entry = store.get(body.content_hash)
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"no processed document with hash {body.content_hash}",
        )

    source = Path(entry.source.path)
    if not source.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"the PDF recorded for this document is not on disk: {source}",
        )

    try:
        result = copy_onto_shelf(source, Path(project.directory))
    except OSError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"could not copy onto the shelf: {exc}"
        ) from exc

    reached = _parts_reached(entry, settings)
    added: list[str] = []
    if reached:
        try:
            added = add_parts(project, reached, parts_dir=settings.parts_dir)
            save_project(project, settings.projects_dir)
        except ProjectError as exc:
            # The copy already happened and is the useful half. A part that
            # cannot join is reported, not rolled back into a failed request.
            log.info("shelf: parts not added for %s: %s", name, exc)

    return ShelfAddOut(
        document=ShelfDocument(
            filename=result.path.name,
            path=str(result.path),
            relative_dir=_relative_dir(result.path, Path(project.directory)),
            content_hash=entry.content_hash,
            processed=True,
            part_number=entry.source.part_number,
            parts_reached=reached,
            labels=list(entry.labels),
            page_count=entry.source.page_count,
        ),
        copied=result.copied,
        renamed=result.renamed,
        reason=result.reason,
        parts_added=added,
    )


def _relative_dir(path: Path, root: Path) -> str:
    """Where the file sits under the shelf; `""` at the top."""
    try:
        rel = path.parent.relative_to(root).as_posix()
    except ValueError:
        return ""
    return "" if rel == "." else rel


def _parts_reached(entry, settings: Settings) -> list[str]:
    """Built parts this document applies to, sorted."""
    return sorted(
        part.name
        for part in discover_parts(settings.parts_dir)
        if entry.applicability.covers(part.name)
    )


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
        excluded=list(project.excluded),
        built=(project_dir(project.name, settings.projects_dir) / PROJECT_INDEX_FILENAME).exists(),
    )
