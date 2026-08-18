"""Why a scanned PDF will or will not be rebuilt.

The engine already skips work correctly — `app/jobs.py` calls
`batch.skip_reason`, the same gate `dsa batch` uses — but the review screen
never asked, so a directory of forty already-built PDFs looked exactly like
forty new ones. A user who cannot tell "nothing to do" from "three hours of
work" hesitates over a button that would have cost nothing.

This module answers the question and nothing else. It **never** decides
anything: `skip_reason` remains the single gate, and `classify` reports what
that gate is going to do plus enough context to say why. Two implementations
of "is this current" is precisely the drift the seam exists to prevent, so if
the two ever disagree, this one is wrong.

It inherits the gate's failure contract as well: `skip_reason` never raises
and treats whatever it cannot verify as "must build". A classification that
cannot read a manifest therefore reports `new`, which is the honest
conservative answer — it promises work rather than promising there is none.

Nothing here writes. A scan must leave `parts_dir`, `library_dir` and
`cache_dir` byte-identical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from datasheet_analyzer.acquire.inventory import load_inventory
from datasheet_analyzer.batch import BatchJob, skip_reason
from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.models import CorpusManifest

#: Four states, and there is no fifth. `current` is the only one that means
#: "this costs nothing"; the other three all end in a build.
BuildState = Literal["new", "current", "stale", "changed"]

BUILD_STATES: tuple[str, ...] = ("new", "current", "stale", "changed")


def classify(
    pdf_path: Path | str,
    part_number: str,
    content_hash: str,
    *,
    settings: Settings,
) -> tuple[BuildState, str]:
    """`(state, reason)` for one scanned PDF. Reads only; writes nothing.

    `content_hash` is the PDF's identity — never its name, never its mtime —
    so renaming a file classifies exactly as it did before.
    """
    reason = skip_reason(BatchJob(pdf_path=Path(pdf_path), part=part_number), settings=settings)
    if reason:
        return "current", reason

    manifest = _manifest(settings.parts_dir / part_number)
    if manifest is None:
        return "new", f"no corpus for {part_number} yet"

    published = {doc.content_hash for doc in manifest.documents}
    if content_hash and content_hash not in published:
        if published:
            return "changed", (
                f"this file's contents differ from the copy {part_number} was built from"
            )
        return "new", f"{part_number} has a manifest but no published document"

    if manifest.pipeline_version != PIPELINE_VERSION:
        return "stale", (
            f"built by pipeline {manifest.pipeline_version or 'unknown'}, "
            f"current is {PIPELINE_VERSION}"
        )

    # The contents are published and the pipeline is current, so the gate is
    # objecting to something else. Check the inventory before blaming the
    # extractor: `skip_reason` matches an inventory entry **by path** and only
    # then by hash, so the same bytes under a new name are not recognised as
    # already built. Saying "superseded extractor" there would send a reader
    # looking for a version problem that does not exist.
    if not _registered_at(settings.parts_dir / part_number, Path(pdf_path)):
        return "stale", (
            f"{part_number} was built from this file under a different path; "
            "it will be re-registered and rebuilt"
        )

    return "stale", "built by a superseded extractor or to an older artifact schema"


def _manifest(part_dir: Path) -> CorpusManifest | None:
    """The part's manifest, or `None` when it is absent or unreadable.

    Unreadable is deliberately indistinguishable from absent here. The gate
    has already decided this job builds; this function only explains why, and
    "the manifest will not parse" and "there is no manifest" lead a reader to
    the same action.
    """
    path = part_dir / "manifest.json"
    try:
        if not path.exists():
            return None
        return CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _registered_at(part_dir: Path, pdf_path: Path) -> bool:
    """Whether the part's inventory records a document at this exact path.

    Mirrors `batch._same_path`: both sides resolved, so a re-spelling
    (relative vs absolute, separators, case) is not treated as a move.
    """
    try:
        target = pdf_path.resolve()
        return any(Path(doc.path).resolve() == target for doc in load_inventory(part_dir))
    except (OSError, ValueError):
        return False
