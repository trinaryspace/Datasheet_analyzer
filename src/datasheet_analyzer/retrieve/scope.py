"""One scope resolution, shared by every front end.

`cli.py`, `mcp_server/server.py` and (Phase 6) the web application all have to
answer the same question before they can look anything up: *what is this
lookup about — one part, or one project?* That question has exactly one right
answer, and it used to be written down twice. A third copy in the GUI would
have made it three places for the precondition of ADR 0006 to drift.

So it lives here, once. A front end chooses a scope and formats what comes
back; it never decides what "no scope" means, and it never widens a scope it
could not resolve.

The invariant this module carries, from
`docs/adr/0006-auto-resolved-scope.md`:

    Exactly one of `part` or `project`. Never both, never neither, and never
    an implicit "everything".

`SCOPE_ERROR` is that rule's own explanation, and it is the only place the
rationale is written down in code — which is why it travels verbatim to every
caller rather than being re-worded per front end.

Everything here returns `(scope, reason)`: a `Retriever` for a part, a
`ProjectRetriever` for a project, or `(None, reason)` where `reason` is text
that can be shown to a person as-is. Nothing raises, nothing prints, and
nothing exits — how a refusal reaches a user is a front end's decision (stderr
plus exit 2 for the CLI, an error envelope for MCP, a 400 for HTTP).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from datasheet_analyzer.config import Settings
    from datasheet_analyzer.retrieve.project import ProjectRetriever
    from datasheet_analyzer.retrieve.retriever import Retriever

__all__ = [
    "PART_REQUIRED_ERROR",
    "SCOPE_ERROR",
    "missing_corpus_warning",
    "no_corpus_error",
    "resolve_part",
    "resolve_scope",
    "unbuilt_members",
]

#: Why a lookup must name its scope. ADR 0006's rationale, in the words the
#: MCP server has always used; every front end shows this string unmodified.
SCOPE_ERROR = (
    "name exactly one of `part` or `project` — a lookup has to know what it "
    "is asking, and defaulting to 'everything' would make the scope of an "
    "answer implicit"
)

#: A part-only lookup (`get_index`, `read_section`, `get_figure`) with no part.
PART_REQUIRED_ERROR = "name a `part`"


def no_corpus_error(part: str, *, settings: Settings) -> str:
    """Why a named part cannot be looked up, and the command that fixes it.

    Names the directory that was searched *and* the exact build invocation:
    "no corpus" is almost always a not-built-yet, and a reader should not have
    to guess which of the two it is.
    """
    return (
        f"no corpus for part {part} under {settings.parts_dir} — run "
        f"`dsa build` first: `dsa build <pdf> --part {part}`"
    )


def resolve_part(part: str, *, settings: Settings) -> tuple[Retriever | None, str]:
    """`(Retriever, "")` for one built part, or `(None, reason)`.

    A part directory that exists but holds no `manifest.json` is *not* built:
    a half-acquired part answers nothing, and reporting it as buildable would
    turn a missing corpus into an empty result set.
    """
    from datasheet_analyzer.projects import is_built
    from datasheet_analyzer.retrieve.retriever import Retriever

    part = (part or "").strip()
    if not part:
        return None, PART_REQUIRED_ERROR
    if not is_built(part, settings.parts_dir):
        return None, no_corpus_error(part, settings=settings)
    return Retriever.for_part(settings.parts_dir / part), ""


def resolve_scope(
    part: str, project: str, *, settings: Settings
) -> tuple[Retriever | ProjectRetriever | None, str]:
    """`(scope, "")` for exactly one of `part` / `project`, else `(None, reason)`.

    Both branches hand back an object from `retrieve/` — a `Retriever` for one
    part, a `ProjectRetriever` for a design — so a caller only chooses a scope
    and formats what it returns. Naming both, or naming neither, is refused
    with `SCOPE_ERROR` rather than resolved to a default: see ADR 0006.
    """
    from datasheet_analyzer.projects import ProjectError, load_project, part_dirs
    from datasheet_analyzer.retrieve.project import ProjectRetriever

    part, project = (part or "").strip(), (project or "").strip()
    if bool(part) == bool(project):
        return None, SCOPE_ERROR
    if project:
        try:
            loaded = load_project(project, settings.projects_dir)
        except ProjectError as exc:
            return None, str(exc)
        return (
            ProjectRetriever.for_parts(loaded.name, part_dirs(loaded, settings.parts_dir)),
            "",
        )
    return resolve_part(part, settings=settings)


def unbuilt_members(project: str, *, settings: Settings) -> list[str]:
    """Member parts of `project` with no corpus on disk, in membership order.

    Separate from `resolve_scope` because it is not a refusal: a design whose
    members are only partly built still answers, from the members that are.
    What it must never do is answer *silently* — see `missing_corpus_warning`.
    An unreadable project has no members to report, and returns `[]`; the
    caller already learned that from `resolve_scope`.
    """
    from datasheet_analyzer.projects import ProjectError, is_built, load_project

    try:
        loaded = load_project((project or "").strip(), settings.projects_dir)
    except ProjectError:
        return []
    return [p for p in loaded.part_numbers if not is_built(p, settings.parts_dir)]


def missing_corpus_warning(missing: Sequence[str]) -> str:
    """The warning for members of a design that cannot answer; `""` for none.

    A member whose corpus is gone is named, never silently skipped: the answer
    would otherwise be quietly missing one device, and nothing in the result
    would say so.
    """
    names = [m for m in missing if m]
    if not names:
        return ""
    return (
        f"no corpus for {', '.join(names)} — build them "
        f"(`dsa build <pdf> --part {names[0]}`) or remove them from "
        f"the project; their answers are missing from this result"
    )
