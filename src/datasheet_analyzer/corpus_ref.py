"""Where a corpus artifact reference hangs off — the part, or the library.

Ticket 04 gave a document two possible homes. Its artifacts are written
either under the part that references it (`parts/<PART>/docs/<doc>/`, the
historical layout) or **once** in the shared store
(`<library>/docs/<doc>/`), with every part that the document applies to
naming that one location. A reference therefore has to say which root it
hangs off, and `SectionFile` carries no schema version of its own, so the
marker lives in the string: `@library/docs/<doc>/sections/4-1.md`.

This module is the one place that knows the marker. It is deliberately
dependency-free (`pathlib` only) so both halves of the system can use the
same rule: `publish/` writes references through it and `retrieve/` resolves
them through it, with no import edge between the two.

The **library root** a shared reference resolves against is recorded by the
writer in `CorpusManifest.library_root`, as a path relative to the part
directory. Recording it is what makes a built corpus self-describing: a
reader holding only `parts/<PART>/` can find the shared store without being
told which `Settings` built it, and two corpora built against two different
libraries (as every hermetic test does) never resolve into each other's.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Marks a manifest path as living in the shared document store rather than
#: under the part. What follows is relative to the *library* directory (the
#: parent of `shared_docs_dir`), so `@library/docs/appnote-1f2e3d4c/…`.
LIBRARY_REF_PREFIX = "@library/"


def is_library_ref(ref: str) -> bool:
    """Whether a manifest path points into the shared document store."""
    return str(ref).startswith(LIBRARY_REF_PREFIX)


def library_ref(shared_docs_dir: Path | str, doc_dir_name: str, artifact: str = "") -> str:
    """The manifest reference naming one artifact in the shared store.

    `@library/docs/<doc>/sections/4-1.md` — the prefix says which root, the
    remainder is relative to the library directory (`shared_docs_dir`'s
    parent), matching the anchoring `PlotRecord.file` uses.
    """
    ref = f"{LIBRARY_REF_PREFIX}{Path(shared_docs_dir).name}/{doc_dir_name}"
    return f"{ref}/{artifact}" if artifact else ref


def corpus_relative(ref: str) -> str:
    """A reference with its root marker removed: `docs/<doc>/sections/4-1.md`.

    Both roots hold the same `docs/<doc>/…` shape underneath, so the marker is
    the *only* difference between a shared reference and a part-local one.
    Stripping it gives the key that `search_index.json`, `plots.json` and the
    manifest all agree on, which is what lets a search hit written against a
    document join to the manifest entry that references it.
    """
    ref = str(ref).replace("\\", "/")
    return ref[len(LIBRARY_REF_PREFIX) :] if is_library_ref(ref) else ref


def resolve_artifact_ref(
    ref: str, *, part_dir: Path | str, library_dir: Path | str | None = None
) -> Path:
    """Absolute path of a manifest reference, per the root its prefix names.

    Raises `ValueError` for a shared reference with no library root to
    resolve against — refusing is the point: joining it onto the part
    directory would name a file that does not exist there, or one that does
    and is the wrong copy.
    """
    if not is_library_ref(ref):
        return Path(part_dir) / ref
    if library_dir is None:
        raise ValueError(
            f"{ref!r} references the shared document store but no library_dir "
            f"was given; it cannot be resolved against the part directory"
        )
    return Path(library_dir) / str(ref)[len(LIBRARY_REF_PREFIX) :]


def library_root_ref(part_dir: Path | str, library_dir: Path | str) -> str:
    """What `CorpusManifest.library_root` records: library root from the part.

    Relative when both live on one filesystem root, so a checkout (or a
    pytest `tmp_path`) can move without invalidating every manifest in it;
    absolute only when a relative path cannot be expressed (a different
    Windows drive). POSIX separators either way — a manifest is data, not a
    local path.
    """
    part_dir = Path(part_dir).resolve()
    library_dir = Path(library_dir).resolve()
    try:
        rel = os.path.relpath(library_dir, part_dir)
    except ValueError:
        return library_dir.as_posix()
    return Path(rel).as_posix()


def library_root_of(manifest, part_dir: Path | str) -> Path | None:
    """The library root a manifest's shared references resolve against.

    `None` when the manifest records none — either it was written before the
    shared store existed, or every document it names is published under the
    part. Both are the same answer to a reader: there is no second root.
    """
    root = getattr(manifest, "library_root", "") if manifest is not None else ""
    if not root:
        return None
    candidate = Path(root)
    if candidate.is_absolute():
        return candidate
    return (Path(part_dir) / candidate).resolve()
