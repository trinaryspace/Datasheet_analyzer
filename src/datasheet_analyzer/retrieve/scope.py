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

`resolve_scope` returns `(scope, reason)`: a `Retriever` for a part, a
`ProjectRetriever` for a project, a `FamilyRetriever` for a family, or
`(None, reason)` where `reason` is text that can be shown to a person as-is.

`resolve_scope_dirs` answers the *same* question in the shape the derived
lookups need — `dsa pins`, `dsa regs` and `dsa card` read published artifacts
off disk and never ask a `Retriever` anything — and returns a `ScopeDirs`.
Two shapes, one decision: both call `chosen_scope`, so the XOR and its
wording exist once whatever a caller does with the answer. (Until 2026-09-02
the three derived lookups each carried a private copy that knew only two
scopes, which is how `--family` came to be advertised by the parser and
refused by the command.)

Nothing raises, nothing prints, and nothing exits — how a refusal reaches a
user is a front end's decision (stderr plus exit 2 for the CLI, an error
envelope for MCP, a 400 for HTTP).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
    "ScopeDirs",
    "chosen_scope",
    "family_part_dirs",
    "missing_corpus_warning",
    "no_corpus_error",
    "resolve_family",
    "resolve_part",
    "resolve_scope",
    "resolve_scope_dirs",
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


def chosen_scope(part: str, project: str, family: str = "") -> tuple[str, str, str]:
    """`(kind, name, "")` for exactly one named scope, else `("", "", reason)`.

    ADR 0006's XOR, decided before anything is loaded and written down once:
    `resolve_scope` and `resolve_scope_dirs` both ask this rather than each
    counting the arguments themselves. `kind` is one of `SCOPE_NAMES`.

    Whitespace is not a scope — `--part "  "` is naming nothing, not naming a
    part called space — and a call that named the *third* scope alongside
    another gets the three-scope wording, because a refusal that lists two
    options when the caller passed a third does not name what they passed.
    """
    named = [
        (kind, (value or "").strip())
        for kind, value in zip(SCOPE_NAMES, (part, project, family), strict=True)
    ]
    chosen = [(kind, name) for kind, name in named if name]
    if len(chosen) != 1:
        return "", "", (FAMILY_SCOPE_ERROR if (family or "").strip() else SCOPE_ERROR)
    return chosen[0][0], chosen[0][1], ""


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

    kind, name, reason = chosen_scope(part, project, family)
    if reason:
        return None, reason
    if kind == "family":
        return resolve_family(name, settings=settings)
    if kind == "project":
        try:
            loaded = load_project(name, settings.projects_dir)
        except ProjectError as exc:
            return None, str(exc)
        return (
            ProjectRetriever.for_parts(loaded.name, part_dirs(loaded, settings.parts_dir)),
            "",
        )
    return resolve_part(name, settings=settings)


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
    from datasheet_analyzer.retrieve.family import FamilyRetriever

    declared, dirs, reason = family_part_dirs(name, settings=settings)
    if reason:
        return None, reason
    return FamilyRetriever.for_parts(declared, dirs), ""


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


@dataclass(frozen=True)
class ScopeDirs:
    """The corpus directories one named scope resolves to, or why it did not.

    The second shape a front end needs from ADR 0006's one rule. `dsa pins`,
    `dsa regs` and `dsa card` read *published artifacts* off disk rather than
    asking a `Retriever` anything, so resolving them to retrievers would load
    every member's specs, plots and search index to answer a question about
    `pins.json`. They get directories instead — decided by the same
    `chosen_scope`, in this module, so there is still exactly one place that
    knows what naming a scope means.

    `kind` and `name` travel with the directories because a scope-level
    message has to name the scope it is about: "no member publishes a pin
    table" is a sentence about a family, and it needs the family's name.
    """

    kind: str = ""
    name: str = ""
    parts: tuple[tuple[str, Path], ...] = ()
    reason: str = ""

    @property
    def is_multi(self) -> bool:
        """Does this scope cover several parts *by construction*?

        True for a project and a family — including a one-member one, because
        a hit from a scope that can hold several parts is labelled with the
        part it came from whether or not this particular scope holds two.
        """
        return self.kind in ("project", "family")

    @property
    def part_numbers(self) -> list[str]:
        """The parts in scope, in membership order."""
        return [part for part, _ in self.parts]


def family_part_dirs(name: str, *, settings: Settings) -> tuple[str, list[Path], str]:
    """`(declared name, member dirs, "")` for a declared, confirmed family.

    The registry read that `resolve_family` and `resolve_scope_dirs` share, so
    a family means the same list of directories to a retriever and to a pin
    lookup. Refusals come straight from `families.registry.resolve`: an
    undeclared family and an unconfirmed one get different messages, each
    naming the command that fixes it, and neither is ever a grouping guessed
    from a part number.
    """
    from datasheet_analyzer.families import FamilyMiss, FamilyUnconfirmed, load_families, resolve
    from datasheet_analyzer.families.registry import families_path

    try:
        entry = resolve(load_families(families_path(settings.registry_dir)), (name or "").strip())
    except (FamilyMiss, FamilyUnconfirmed) as exc:
        return "", [], str(exc)
    return entry.name, [settings.parts_dir / member for member in entry.members], ""


def resolve_scope_dirs(
    part: str, project: str, *, settings: Settings, family: str = ""
) -> ScopeDirs:
    """`ScopeDirs` for exactly one of `part` / `project` / `family`.

    The directory-shaped sibling of `resolve_scope`, for the lookups that read
    published artifacts rather than the retrieval index. Same XOR, same
    refusals, same wording — a caller chooses a scope and formats what comes
    back, and nothing here prints, raises or exits.

    A *project* or *family* member with no corpus on disk is still returned:
    a design or a series whose members are only partly built still answers
    from the members that are, and `unbuilt_members` / `unbuilt_family_members`
    are what name the gap. A named **part** with no corpus is a refusal,
    because there is then nothing left to answer from.
    """
    from datasheet_analyzer.projects import ProjectError, is_built, load_project, part_dirs

    kind, name, reason = chosen_scope(part, project, family)
    if reason:
        return ScopeDirs(reason=reason)
    if kind == "family":
        declared, dirs, refusal = family_part_dirs(name, settings=settings)
        if refusal:
            return ScopeDirs(reason=refusal)
        return ScopeDirs(kind="family", name=declared, parts=tuple((d.name, d) for d in dirs))
    if kind == "project":
        try:
            loaded = load_project(name, settings.projects_dir)
        except ProjectError as exc:
            return ScopeDirs(reason=str(exc))
        return ScopeDirs(
            kind="project",
            name=loaded.name,
            parts=tuple((d.name, d) for d in part_dirs(loaded, settings.parts_dir)),
        )
    if not is_built(name, settings.parts_dir):
        return ScopeDirs(reason=no_corpus_error(name, settings=settings))
    return ScopeDirs(kind="part", name=name, parts=((name, settings.parts_dir / name),))
