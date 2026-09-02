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
    from datasheet_analyzer.retrieve.family import FamilyRetriever
    from datasheet_analyzer.retrieve.project import ProjectRetriever
    from datasheet_analyzer.retrieve.retriever import Retriever

__all__ = [
    "FAMILY_SCOPE_ERROR",
    "PART_REQUIRED_ERROR",
    "SCOPE_ERROR",
    "SCOPE_NAMES",
    "missing_corpus_warning",
    "no_corpus_error",
    "resolve_family",
    "resolve_part",
    "resolve_scope",
    "unbuilt_family_members",
    "unbuilt_members",
]

#: Why a lookup must name its scope. ADR 0006's rationale, in the words the
#: MCP server has always used; every front end shows this string unmodified.
#: The three scopes a lookup may name, in the order they were added. A
#: family (phase 7, ticket 07) is a *declared* series and sits beside a
#: project rather than under it: a project is parts someone put on one
#: board, a family is one device published in several options.
SCOPE_NAMES: tuple[str, ...] = ("part", "project", "family")

SCOPE_ERROR = (
    "name exactly one of `part` or `project` — a lookup has to know what it "
    "is asking, and defaulting to 'everything' would make the scope of an "
    "answer implicit"
)

#: The same refusal for a call that named the third scope. `SCOPE_ERROR` is
#: ADR 0006's own wording and a test holds it character for character, so the
#: family scope widens the *list* and reuses the rationale clause verbatim
#: rather than re-wording it — one rationale, written down once.
FAMILY_SCOPE_ERROR = (
    "name exactly one of `part`, `project` or `family` — " + SCOPE_ERROR.partition("— ")[2]
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
    part: str, project: str, *, settings: Settings, family: str = ""
) -> tuple[Retriever | ProjectRetriever | FamilyRetriever | None, str]:
    """`(scope, "")` for exactly one of `part` / `project` / `family`.

    Every branch hands back an object from `retrieve/` — a `Retriever` for one
    part, a `ProjectRetriever` for a design, a `FamilyRetriever` for a declared
    series — so a caller only chooses a scope and formats what it returns.
    Naming more than one, or naming none, is refused with `SCOPE_ERROR` rather
    than resolved to a default: see ADR 0006.

    `family` is additive (phase 7, ticket 07) and defaults to `""`, so every
    existing two-argument call means exactly what it meant before. Membership
    is read from `registry/families.yaml` and nowhere else: an undeclared or
    unconfirmed family is a refusal carrying the command that fixes it, never
    a grouping guessed from a part number.
    """
    from datasheet_analyzer.projects import ProjectError, load_project, part_dirs
    from datasheet_analyzer.retrieve.project import ProjectRetriever

    part, project = (part or "").strip(), (project or "").strip()
    family = (family or "").strip()
    if [bool(part), bool(project), bool(family)].count(True) != 1:
        return None, FAMILY_SCOPE_ERROR if family else SCOPE_ERROR
    if family:
        return resolve_family(family, settings=settings)
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


def resolve_family(name: str, *, settings: Settings) -> tuple[FamilyRetriever | None, str]:
    """`(FamilyRetriever, "")` for a declared, confirmed family, else a refusal.

    The whole rule of ticket 07 lives on the other side of this call:
    `families.registry.resolve` refuses a family nobody declared and one nobody
    confirmed, with two different messages, each naming the command that fixes
    it. Nothing here infers a grouping from a part number, and nothing widens a
    family whose members are not all built — an unbuilt member is named by the
    pack it fails to answer, exactly as an unbuilt project member is.
    """
    from datasheet_analyzer.families import FamilyMiss, FamilyUnconfirmed, load_families, resolve
    from datasheet_analyzer.families.registry import families_path
    from datasheet_analyzer.retrieve.family import FamilyRetriever

    try:
        entry = resolve(load_families(families_path(settings.registry_dir)), name)
    except (FamilyMiss, FamilyUnconfirmed) as exc:
        return None, str(exc)
    return (
        FamilyRetriever.for_parts(
            entry.name, [settings.parts_dir / member for member in entry.members]
        ),
        "",
    )


def unbuilt_family_members(name: str, *, settings: Settings) -> list[str]:
    """Declared members of `name` with no corpus on disk, in declared order.

    Same shape and same reason as `unbuilt_members`: a family whose members are
    only partly built still answers, from the members that are, and what it must
    never do is answer *silently*.
    """
    from datasheet_analyzer.families import FamilyMiss, FamilyUnconfirmed, load_families, resolve
    from datasheet_analyzer.families.registry import families_path
    from datasheet_analyzer.projects import is_built

    try:
        entry = resolve(load_families(families_path(settings.registry_dir)), (name or "").strip())
    except (FamilyMiss, FamilyUnconfirmed):
        return []
    return [m for m in entry.members if not is_built(m, settings.parts_dir)]
