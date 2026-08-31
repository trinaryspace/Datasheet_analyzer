"""`PROJECT_INDEX.md` — one always-loadable file for a whole design.

The part-level `INDEX.md` answers "where in this datasheet?"; this answers
"which datasheet?". It is built under a hard token budget for the same reason
`INDEX.md` is: a file an agent loads *every* time must be cheap enough to
load every time.

Budget discipline mirrors `enrich/index.py`, with one addition the ticket asks
for: when content is dropped, the file **says so**. Staged degradation drops
the least-important block first and never touches the product —

| Stage | Dropped |
|---|---|
| 0 | nothing |
| 1 | the "How to use" conventions |
| 2 | + the designer's notes |
| 3 | + the interfaces note |
| 4 | + each member's corpus statistics |
| 5 | + each member's role |

— leaving, at every stage, the part list with each part's revision and the
pointer to its own `INDEX.md`. Those are the whole point of the file, so they
are never what a budget removes; the same rule the answer pack applies to
citations. Below the last stage the file goes over budget and says *that*,
rather than shipping a project index that lists no parts.

Member facts are read through `CorpusIndex`, never by walking a corpus here —
the retrieval seam applies to the publisher too.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import Project
from datasheet_analyzer.projects.store import INDEX_FILENAME, part_dir, project_dir
from datasheet_analyzer.protocol import (
    AGENT_FILENAME,
    build_project_agent_markdown,
    write_agent_doc,
)
from datasheet_analyzer.retrieve import CorpusIndex
from datasheet_analyzer.tokens import count_tokens

_TRUNCATION_NOTICE = (
    "_Truncated to fit a {budget}-token budget — raise it with the "
    "DSA_PROJECT_INDEX_TOKEN_BUDGET setting to see the rest._"
)
_FLOOR_NOTICE = (
    "_A {budget}-token budget is below this project's part list; every part "
    "and its index pointer are kept regardless — raise it with the "
    "DSA_PROJECT_INDEX_TOKEN_BUDGET setting._"
)


@dataclass(frozen=True)
class MemberSummary:
    """What the project index knows about one member part."""

    part_number: str
    role: str = ""
    revision: str = ""
    vendor: str = ""
    doc_type: str = ""
    n_sections: int = 0
    n_specs: int = 0
    n_plot_files: int = 0
    n_pages: int = 0
    index_path: str = ""
    built: bool = False

    @property
    def title(self) -> str:
        """`AFE7950 — datasheet SBASA41E (ti)`, every tail part optional."""
        bits = [b for b in (self.doc_type, self.revision) if b]
        head = f"**{self.part_number}**"
        if bits:
            head += " — " + " ".join(bits)
        if self.vendor:
            head += f" ({self.vendor})"
        return head

    @property
    def stats_line(self) -> str:
        counts = [
            f"{self.n_sections} sections",
            f"{self.n_specs} specs",
            f"{self.n_plot_files} figures",
        ]
        if self.n_pages:
            counts.append(f"{self.n_pages} pages")
        return ", ".join(counts)


def summarize_member(
    part_number: str, role: str, parts_dir: Path, *, relative_to: Path | None = None
) -> MemberSummary:
    """Read one member's corpus facts through `CorpusIndex`.

    A member whose corpus is gone degrades honestly: `built=False`, no
    invented counts, and the renderer says the corpus is missing rather than
    printing zeros that would read like an empty datasheet.
    """
    directory = part_dir(part_number, parts_dir)
    manifest = CorpusIndex.load(directory).manifest
    pointer = _pointer(directory / "INDEX.md", relative_to)
    if manifest is None:
        return MemberSummary(part_number=part_number, role=role, index_path=pointer)
    doc = manifest.documents[0] if manifest.documents else None
    stats = manifest.stats
    return MemberSummary(
        part_number=part_number,
        role=role,
        revision=doc.revision if doc else "",
        vendor=manifest.vendor,
        doc_type=doc.doc_type.value if doc else "",
        n_sections=stats.n_sections,
        n_specs=stats.n_specs,
        n_plot_files=stats.n_plot_files,
        n_pages=doc.page_count if doc else 0,
        index_path=pointer,
        built=True,
    )


def summarize_project(
    project: Project, parts_dir: Path, *, relative_to: Path | None = None
) -> list[MemberSummary]:
    """Member summaries in membership order — the order the index prints."""
    return [
        summarize_member(m.part_number, m.role, parts_dir, relative_to=relative_to)
        for m in project.parts
    ]


def _pointer(path: Path, relative_to: Path | None) -> str:
    """A pointer a reader can follow: relative when possible, absolute else."""
    if relative_to is None:
        return path.as_posix()
    try:
        return Path(os.path.relpath(path, relative_to)).as_posix()
    except ValueError:  # different drives on Windows — absolute still works
        return path.as_posix()


def build_project_index_markdown(
    project: Project,
    members: list[MemberSummary],
    *,
    token_budget: int,
) -> str:
    """Render `PROJECT_INDEX.md`, degrading in stages until it fits."""
    title = [f"# {project.name} — project corpus", ""]
    if members:
        names = ", ".join(m.part_number for m in members)
        title += [f"> {len(members)} parts: {names}.", ""]
    else:
        title += ["> No parts yet — add one with `dsa project add`.", ""]

    def parts_block(with_stats: bool, with_roles: bool) -> list[str]:
        lines = ["## Parts", ""]
        if not members:
            lines += ["- (none)", ""]
            return lines
        for m in members:
            head = m.title
            if with_roles and m.role:
                head += f" — {m.role}"
            lines.append(f"- {head}")
            if not m.built:
                lines.append(
                    f"  no corpus on disk — build it: `dsa build <pdf> --part {m.part_number}`"
                )
                continue
            lines.append(f"  `{m.index_path}`")
            if with_stats:
                lines.append(f"  {m.stats_line}")
        lines.append("")
        return lines

    def free_text(heading: str, body: str) -> list[str]:
        return [f"## {heading}", "", body.strip(), ""] if body.strip() else []

    # A pointer, not a copy: the retrieval protocol lives in `AGENT.md` beside
    # this file (ticket 08). Duplicating it here would make two texts that can
    # disagree, and the budget this index degrades under is better spent on
    # parts than on prose that already exists one file over.
    conventions = [
        "## How to use this project",
        "",
        (
            f"- `{AGENT_FILENAME}` beside this file is the retrieval protocol "
            "(both access paths, the confidence rule). Read it first."
        ),
        "- Then open the `INDEX.md` of the part a question points at.",
        "",
    ]

    stages = [
        # (with_conventions, with_notes, with_interfaces, with_stats, with_roles)
        (True, True, True, True, True),
        (False, True, True, True, True),
        (False, False, True, True, True),
        (False, False, False, True, True),
        (False, False, False, False, True),
        (False, False, False, False, False),
    ]
    text = ""
    for stage, (conv, notes, interfaces, stats, roles) in enumerate(stages):
        body = list(title)
        body += parts_block(stats, roles)
        if interfaces:
            body += free_text("Interfaces", project.interfaces)
        if notes:
            body += free_text("Notes", project.notes)
        if conv:
            body += conventions
        if stage:
            body += [_TRUNCATION_NOTICE.format(budget=token_budget), ""]
        text = "\n".join(body)
        if count_tokens(text) <= token_budget:
            return text
    # Below the last stage: the part list stays and the file says it went over.
    body = list(title) + parts_block(False, False)
    body += [_FLOOR_NOTICE.format(budget=token_budget), ""]
    return "\n".join(body)


def write_project_index(
    project: Project,
    *,
    parts_dir: Path,
    projects_dir: Path,
    token_budget: int,
) -> tuple[Path, str]:
    """Build and write `projects/<name>/PROJECT_INDEX.md`; return path + text.

    `AGENT.md` is written beside it, because this *is* a project's publish
    step and the protocol must ship with the data rather than with the
    command that happened to trigger the build — the same rule that puts a
    part's `AGENT.md` inside `write_corpus`. It is fixed text, so it is not
    budget-degraded and is not what the returned tuple describes.
    """
    dest = project_dir(project.name, projects_dir)
    dest.mkdir(parents=True, exist_ok=True)
    members = summarize_project(project, parts_dir, relative_to=dest)
    text = build_project_index_markdown(project, members, token_budget=token_budget)
    path = dest / INDEX_FILENAME
    path.write_text(text, encoding="utf-8")
    write_agent_doc(dest, build_project_agent_markdown(project.name, project.part_numbers))
    return path, text
