"""Where a family index lives on disk: `families/<NAME>/`.

Phase 7, ticket 07. Beside `parts/` and `projects/`, never inside a member — a
family is a view *over* parts, and writing it into one of them would make one
member's corpus quietly authoritative for the others.

Two files, the pair every derived artifact in this repo publishes: the markdown a
reader loads (`FAMILY_INDEX.md`, under its token budget) and the machine-readable
twin (`family.json`, complete, so a `--json` consumer is never handed the
budget-degraded reading by accident). The JSON is serialized deterministically
for the reason `search_index.json` is: identical corpora must produce an
identical file, or a diff of two runs says something that is not true.
"""

from __future__ import annotations

import json
from pathlib import Path

from datasheet_analyzer.families.render import (
    FAMILY_INDEX_FILENAME,
    FAMILY_JSON_FILENAME,
    render_family_index,
)
from datasheet_analyzer.models import FamilyIndex


def family_dir(name: str, families_dir: Path) -> Path:
    return Path(families_dir) / name


def index_path(name: str, families_dir: Path) -> Path:
    return family_dir(name, families_dir) / FAMILY_INDEX_FILENAME


def json_path(name: str, families_dir: Path) -> Path:
    return family_dir(name, families_dir) / FAMILY_JSON_FILENAME


def write_family_index(
    index: FamilyIndex, *, families_dir: Path, token_budget: int
) -> tuple[Path, str]:
    """Write both files; return the markdown path and the text that was written.

    The markdown is rendered **under the budget** — the number the ticket's
    third criterion is measured against is the file that ships, not the file that
    would have shipped without a bound.
    """
    directory = family_dir(index.name, families_dir)
    directory.mkdir(parents=True, exist_ok=True)
    text = render_family_index(index, token_budget=token_budget)
    markdown = directory / FAMILY_INDEX_FILENAME
    markdown.write_text(text, encoding="utf-8")
    (directory / FAMILY_JSON_FILENAME).write_text(
        json.dumps(
            index.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return markdown, text
