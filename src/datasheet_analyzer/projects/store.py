"""`project.json` — the explicit part list, read and written in one place.

A project is a folder under `projects/` holding `project.json` (this module)
and `PROJECT_INDEX.md` (`projects/index.py`). Membership is *explicit* by
decision: no BOM CSV, no netlist parsing (Phase 5 plan, Out of Scope). An
agent that can read a BOM calls `add_parts` itself, which is the cheap 90%.

Two rules here are load-bearing:

- **A project never holds a part that has no corpus.** `add_parts` refuses a
  part with no `manifest.json` and says which build command would fix it, so
  a project can never be built into a half-index that cites nothing. That is
  the honest-degradation invariant at this level: report, do not force.
- **A project name is a directory name.** It is validated rather than
  sanitized, because silently rewriting `../etc` into something else would
  hide the mistake instead of refusing it.

Free text (`interfaces`, `notes`, each member's `role`) is written by humans
and only ever *read* here — the pipeline never rewrites a designer's words.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from datasheet_analyzer.models import Project, ProjectMember

PROJECT_FILE = "project.json"
INDEX_FILENAME = "PROJECT_INDEX.md"

# A project name is a directory name and a CLI argument; keep it to the
# characters that are unambiguous in both.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ProjectError(Exception):
    """A project operation that cannot be honoured, with the fix in the text."""


def validate_name(name: str) -> str:
    """Return `name` unchanged, or raise with what a legal name looks like."""
    if not _NAME.match(name or ""):
        raise ProjectError(
            f"invalid project name {name!r} — use letters, digits, '.', '_' or "
            "'-', starting with a letter or digit (e.g. rf-frontend)"
        )
    return name


def project_dir(name: str, projects_dir: Path) -> Path:
    """`projects/<name>/` — validated, never created as a side effect."""
    return Path(projects_dir) / validate_name(name)


def exists(name: str, projects_dir: Path) -> bool:
    return (project_dir(name, projects_dir) / PROJECT_FILE).exists()


def list_projects(projects_dir: Path) -> list[str]:
    """Every project name under `projects_dir`, sorted; `[]` when there are none."""
    root = Path(projects_dir)
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and (d / PROJECT_FILE).exists())


def load_project(name: str, projects_dir: Path) -> Project:
    """Read `projects/<name>/project.json`.

    A missing or unreadable project is an error rather than an empty project:
    answering "0 parts" for a typo'd name would be a silent wrong answer, and
    the caller can act on the message.
    """
    path = project_dir(name, projects_dir) / PROJECT_FILE
    if not path.exists():
        raise ProjectError(
            f"no project {name!r} at {path.parent} — create it with `dsa project new {name}`"
        )
    try:
        return Project.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectError(f"unreadable project file {path}: {exc}") from exc


def save_project(project: Project, projects_dir: Path) -> Path:
    """Write `project.json`, stamping `updated_at`."""
    dest = project_dir(project.name, projects_dir)
    dest.mkdir(parents=True, exist_ok=True)
    project.updated_at = datetime.now(timezone.utc)
    path = dest / PROJECT_FILE
    path.write_text(
        json.dumps(project.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def new_project(
    name: str,
    projects_dir: Path,
    *,
    interfaces: str = "",
    notes: str = "",
) -> Project:
    """Create an empty project; refuse to overwrite an existing one."""
    if exists(name, projects_dir):
        raise ProjectError(
            f"project {name!r} already exists at "
            f"{project_dir(name, projects_dir)} — add parts with "
            f"`dsa project add {name} <PART>`"
        )
    project = Project(name=validate_name(name), interfaces=interfaces, notes=notes)
    save_project(project, projects_dir)
    return project


def part_dir(part_number: str, parts_dir: Path) -> Path:
    return Path(parts_dir) / part_number


def is_built(part_number: str, parts_dir: Path) -> bool:
    """Whether a part has a corpus a project can point at."""
    return (part_dir(part_number, parts_dir) / "manifest.json").exists()


def part_dirs(project: Project, parts_dir: Path) -> list[Path]:
    """Member corpus directories, in membership order.

    Resolving a project's members to directories is project knowledge, not
    retrieval knowledge, which is why it lives here and `ProjectRetriever`
    takes the directories it is handed.
    """
    return [part_dir(m.part_number, parts_dir) for m in project.parts]


def add_parts(
    project: Project,
    part_numbers: list[str],
    *,
    parts_dir: Path,
    role: str = "",
) -> list[str]:
    """Add built parts to `project`; return the ones actually added.

    Raises before mutating anything when a named part has no corpus: a
    project must never be half-added, and the message names the command that
    would fix it. Re-adding a member updates its role instead of duplicating
    it — membership is a set, roles are editable.
    """
    unbuilt = [p for p in part_numbers if not is_built(p, parts_dir)]
    if unbuilt:
        listed = ", ".join(unbuilt)
        first = unbuilt[0]
        raise ProjectError(
            f"no built corpus for {listed} under {Path(parts_dir)} — build it "
            f"first: `dsa build <pdf> --part {first}` (a project only points "
            "at corpora that exist, so it can never produce a half-index)"
        )
    added: list[str] = []
    by_number = {m.part_number: m for m in project.parts}
    for number in part_numbers:
        member = by_number.get(number)
        if member is None:
            project.parts.append(ProjectMember(part_number=number, role=role))
            by_number[number] = project.parts[-1]
            added.append(number)
        elif role:
            member.role = role
    return added


def remove_parts(project: Project, part_numbers: list[str]) -> list[str]:
    """Drop members from `project`; return the ones actually removed.

    A part that is not a member is reported back as "not removed" rather than
    raised on: removing something twice is not an error worth failing a
    script over, but pretending it was there would be a lie.
    """
    wanted = set(part_numbers)
    removed = [m.part_number for m in project.parts if m.part_number in wanted]
    project.parts = [m for m in project.parts if m.part_number not in wanted]
    return removed
