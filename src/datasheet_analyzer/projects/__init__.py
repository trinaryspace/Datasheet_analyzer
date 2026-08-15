"""Projects — the noun above `part`.

`projects/<name>/` holds `project.json` (an explicit, human-curated part list
plus the free text that joins the parts) and `PROJECT_INDEX.md` (the single
always-loadable entry point for a whole design, under a hard token budget).

`store.py` owns the file; `index.py` owns the rendering. Project-scoped
*retrieval* deliberately lives elsewhere — `retrieve/project.py` — so this
package stays about what a project is, and the retrieval seam keeps its
single implementation.
"""

from datasheet_analyzer.projects.index import (
    MemberSummary,
    build_project_index_markdown,
    summarize_member,
    summarize_project,
    write_project_index,
)
from datasheet_analyzer.projects.store import (
    INDEX_FILENAME,
    PROJECT_FILE,
    ProjectError,
    add_parts,
    exists,
    is_built,
    list_projects,
    load_project,
    new_project,
    part_dirs,
    project_dir,
    remove_parts,
    save_project,
    validate_name,
)

__all__ = [
    "INDEX_FILENAME",
    "PROJECT_FILE",
    "MemberSummary",
    "ProjectError",
    "add_parts",
    "build_project_index_markdown",
    "exists",
    "is_built",
    "list_projects",
    "load_project",
    "new_project",
    "part_dirs",
    "project_dir",
    "remove_parts",
    "save_project",
    "summarize_member",
    "summarize_project",
    "validate_name",
    "write_project_index",
]
