"""Remember what inference decided about a document, keyed on its bytes.

Scanning runs a model call per PDF. That was affordable when a scan read one
directory's direct children; it is not once the walk is recursive, because a
shelf of two hundred documents then costs two hundred calls *every time the
folder is opened* — and reopening a project is supposed to be the cheap
operation. A document's identity is the sha256 of its bytes, so a proposal
computed once is valid for as long as those bytes and the inference that
produced them are unchanged.

The key is `(content_hash, INFERENCE_VERSION)`, the same discipline
`PdfLayoutBackend.output_version` already applies to the extraction cache:
change how inference decides and every stored proposal becomes unreachable
rather than quietly stale. Bumping the version is therefore mandatory when
`acquire/applicability.py` changes in a way that could produce a different
answer — a cache that outlives its producer is worse than no cache.

Nothing here is load-bearing. Every read that fails for any reason returns a
miss, and every write that fails is dropped: a broken cache must cost time,
never correctness.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from datasheet_analyzer.app.contracts import DocProposal
from datasheet_analyzer.config import Settings

log = logging.getLogger(__name__)

#: Bump when `acquire/applicability.py` could decide differently: a changed
#: prompt, a changed sweep, a new fallback. Stored proposals keyed on an older
#: version are never read again.
INFERENCE_VERSION = "1"

#: The fields the cache owns. Everything else on a `DocProposal` is measured
#: per scan (the path it was found at, its build state) and must not be
#: restored from a previous run — the same bytes can live at a new path, under
#: a part that has since been built.
_CACHED_FIELDS = (
    "part_number",
    "applicability",
    "evidence",
    "doc_type",
    "content_hash",
    "page_count",
    "is_datasheet",
)


def _path_for(content_hash: str, settings: Settings) -> Path:
    return Path(settings.cache_dir) / "proposals" / f"{content_hash}__{INFERENCE_VERSION}.json"


def get(content_hash: str, *, settings: Settings) -> DocProposal | None:
    """The stored proposal for these bytes, or `None` on any kind of miss."""
    if not content_hash:
        return None
    try:
        path = _path_for(content_hash, settings)
        if not path.exists():
            return None
        stored = json.loads(path.read_text(encoding="utf-8"))
        # `pdf_path` is required on the model and deliberately *not* stored —
        # the same bytes can be found at a new path next scan. It is supplied
        # empty here and filled by `merge`, which every caller must use.
        return DocProposal(pdf_path="", **stored)
    except (OSError, ValueError) as exc:
        log.debug("proposal cache: unreadable entry for %s: %s", content_hash, exc)
        return None


def put(proposal: DocProposal, *, settings: Settings) -> None:
    """Store the reusable half of a proposal. Failure is not an error."""
    if not proposal.content_hash:
        # Nothing to key on — an unreadable PDF, or one inference could not
        # hash. Caching it under a blank key would collide every such file.
        return
    try:
        path = _path_for(proposal.content_hash, settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        keep = proposal.model_dump(mode="json", include=set(_CACHED_FIELDS))
        path.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError) as exc:
        log.debug("proposal cache: could not store %s: %s", proposal.content_hash, exc)


def merge(cached: DocProposal, *, pdf_path: Path, page_count: int) -> DocProposal:
    """A cached proposal re-attached to where the file was found *this* scan."""
    return cached.model_copy(
        update={
            "pdf_path": str(pdf_path),
            "filename": pdf_path.name,
            "page_count": cached.page_count or page_count,
        }
    )
