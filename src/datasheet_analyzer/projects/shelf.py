"""A project's shelf: the documents sitting in its folder.

A Project's directory is where its source PDFs live, so "what is in this
project" is a question about that folder — not about the Library, which holds
every *processed* document from everywhere. The two are deliberately different
sets: a PDF you dropped in this morning is on the shelf and not in the
Library, and a document you built last year from another folder is in the
Library and not on this shelf.

The rail needs both facts at once, which is what `shelf_of` returns: every PDF
in the folder, each marked with whether the Library knows it — that is, with
whether the model can actually read it. "Not listed" would otherwise mean both
"not in the folder" and "not built", and a reader could not tell which.

Adding a document copies its PDF in, so the folder stays self-contained and a
project remains something you can hand to somebody. Copying never overwrites:
the file already in your folder is one you put there.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.extract.pdf_structure import compute_content_hash

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CopyResult:
    """What `copy_onto_shelf` did, in terms a screen can render."""

    path: Path
    #: False when the same bytes were already there and nothing was written.
    copied: bool
    #: True when the name was taken by *different* bytes, so this landed
    #: beside it under a new name. Worth flagging: the user has two files.
    renamed: bool = False
    reason: str = ""


def pdfs_on_shelf(directory: Path) -> list[Path]:
    """Every PDF in the project folder, recursively, in a stable order.

    Shares the workbench's walk rules by intent: skip what could not be a
    source document. Kept simple here — the scan endpoint owns the full rule
    set, and this is the cheap listing the rail needs.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in root.rglob("*"):
        if path.suffix.lower() != ".pdf" or not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if any(
            part in {"parts", "library", "projects", "node_modules"}
            for part in path.relative_to(root).parts[:-1]
        ):
            continue
        found.append(path)
    found.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))
    return found


def copy_onto_shelf(source: Path, directory: Path) -> CopyResult:
    """Put `source` in the project folder, without ever overwriting.

    Three outcomes:

    - the same bytes are already there — nothing is written, and the existing
      file is returned. Identity is the content hash, so a second copy under a
      second name would be pure duplication.
    - the name is free — a plain copy.
    - the name is taken by *different* bytes — copied alongside as
      `name (2).pdf` and flagged, because the user now has two files that look
      like the same document and should be told so.
    """
    source = Path(source)
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)

    wanted = compute_content_hash(source)
    for existing in pdfs_on_shelf(root):
        try:
            if compute_content_hash(existing) == wanted:
                return CopyResult(
                    path=existing,
                    copied=False,
                    reason=f"already on this shelf as {existing.name}",
                )
        except OSError:  # unreadable file on the shelf is not this one
            continue

    target = root / source.name
    renamed = False
    if target.exists():
        target = _free_name(root, source.name)
        renamed = True

    shutil.copy2(source, target)
    return CopyResult(
        path=target,
        copied=True,
        renamed=renamed,
        reason=(
            f"a different file was already called {source.name}; copied as {target.name}"
            if renamed
            else ""
        ),
    )


def _free_name(root: Path, filename: str) -> Path:
    """`report.pdf` -> `report (2).pdf`, counting up until one is free."""
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for n in range(2, 1000):
        candidate = root / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(f"no free filename for {filename} in {root}")
