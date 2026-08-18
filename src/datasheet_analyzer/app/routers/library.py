"""Library and label endpoints (ticket 09).

`GET /api/library` reads the whole shelf; `PATCH /api/library/{content_hash}`
corrects one document by hand. This is the **only** user-writable surface in
the application — everything else under `parts/` is derived from the PDFs and
must stay reproducible — so both the validation and the non-effects here are
part of the contract:

- **Reach is derived, never stored.** A part is the *view* of the documents
  whose applicability covers it (ADR 0005), so `parts_reached` is recomputed
  from the library on every read. Widening applicability changes the reach
  immediately and changes nothing on disk under `parts/`.
- **A patch never triggers a rebuild** and never writes to `parts/` or to the
  extraction cache. Materializing a new reach into a corpus is a build's job,
  so the response carries `rebuild_needed` — the parts this document reaches
  whose built corpus does not yet reference it — and the UI offers the build.
- **A patch may name a part that does not exist yet.** That is legal and
  intended: the part comes into existence with this document as its corpus.
  Such a part is reported in `unbuilt_parts`, not rejected.
- **Applicability is validated, labels are free text.** `kind="parts"` with no
  usable part number, or `kind="family"` with a blank family, is a 400 rather
  than a silently inert write: both would store an applicability that covers
  nothing at all.

Nothing here holds retrieval logic. The store is injected through
`app.deps.get_library`, so a test overrides it with a fake and never touches a
real library directory.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from datasheet_analyzer.app.contracts import (
    API_PREFIX,
    Applicability,
    LibraryDocument,
    LibraryDocumentOut,
    LibraryOut,
    LibraryPatchIn,
)
from datasheet_analyzer.app.deps import get_library, get_settings_dep
from datasheet_analyzer.config import Settings
from datasheet_analyzer.library.store import LibraryStore
from datasheet_analyzer.retrieve.index import discover_parts

log = logging.getLogger(__name__)

__all__ = ["USER_EDIT_EVIDENCE", "list_library", "patch_library_document", "router"]

#: A part directory is *built* once it carries this file; `discover_parts()`
#: lists a directory either way, and a half-built part must read as unbuilt
#: rather than vanish.
MANIFEST_FILENAME = "manifest.json"

#: Applicability evidence stamped when a hand edit arrives without its own.
#: `Applicability.evidence` is never blank in practice — an inferred *or*
#: corrected value that cannot say where it came from is not correctable by
#: the next human to read it.
USER_EDIT_EVIDENCE = "user edit: applicability set by hand"

router = APIRouter(prefix=f"{API_PREFIX}/library", tags=["library"])

#: Injected, never constructed here: a test overrides these two providers and
#: the router never opens a real library directory.
StoreDep = Annotated[LibraryStore, Depends(get_library)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


# --- reach --------------------------------------------------------------------


@dataclass
class _Reach:
    """The part universe a document's reach is measured against.

    Built once per request. The universe is every part the application can
    name: the directories under `parts_dir` (built or not, matching
    `discover_parts()`), every part named by some document's applicability,
    and every `SourceDocument.part_number` a document was registered under.
    A `kind="all"` document reaches all of them; that is what "all parts"
    means when parts are a view rather than a container.
    """

    parts_dir: Path
    #: upper-cased part number -> the spelling to display. A built directory
    #: wins, so the corpus's own casing is what the UI shows.
    universe: dict[str, str] = field(default_factory=dict)
    _manifest_hashes: dict[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, documents: list[LibraryDocument], settings: Settings) -> _Reach:
        reach = cls(parts_dir=Path(settings.parts_dir))
        for part_dir in discover_parts(reach.parts_dir):
            reach._offer(part_dir.name, authoritative=True)
        for doc in documents:
            reach._offer(doc.source.part_number)
            for name in doc.applicability.parts:
                reach._offer(name)
        return reach

    def _offer(self, name: str, *, authoritative: bool = False) -> None:
        cleaned = (name or "").strip()
        if not cleaned:
            return
        key = cleaned.upper()
        if authoritative or key not in self.universe:
            self.universe[key] = cleaned

    def _names(self) -> list[str]:
        return sorted(self.universe.values(), key=str.upper)

    def is_built(self, part_number: str) -> bool:
        """True when the part directory carries a manifest."""
        return (self.parts_dir / part_number / MANIFEST_FILENAME).is_file()

    def manifest_hashes(self, part_number: str) -> frozenset[str]:
        """Content hashes the part's built corpus already references.

        Read straight from `manifest.json` rather than through `CorpusIndex`
        so a read of the shelf never populates the retrieval cache, and an
        unreadable manifest degrades to "references nothing" instead of
        failing the whole listing.
        """
        cached = self._manifest_hashes.get(part_number)
        if cached is not None:
            return cached
        hashes: set[str] = set()
        path = self.parts_dir / part_number / MANIFEST_FILENAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for entry in payload.get("documents") or []:
                content_hash = (entry or {}).get("content_hash") or ""
                if content_hash:
                    hashes.add(content_hash)
        except (OSError, ValueError, AttributeError) as exc:
            log.debug("no readable manifest for part %s: %s", part_number, exc)
        frozen = frozenset(hashes)
        self._manifest_hashes[part_number] = frozen
        return frozen

    def project(self, doc: LibraryDocument) -> LibraryDocumentOut:
        """One document plus the parts it reaches, and their build state."""
        reached = [name for name in self._names() if doc.covers(name)]
        unbuilt = [name for name in reached if not self.is_built(name)]
        pending = set(unbuilt)
        rebuild_needed = [
            name
            for name in reached
            if name in pending or doc.content_hash not in self.manifest_hashes(name)
        ]
        return LibraryDocumentOut.from_document(
            doc,
            parts_reached=reached,
            unbuilt_parts=unbuilt,
            rebuild_needed=rebuild_needed,
        )


# --- validation ---------------------------------------------------------------


def _clean_labels(labels: list[str]) -> list[str]:
    """Strip, drop blanks, de-duplicate — order the user gave them in.

    Labels are free text and stay free text: nothing is case-folded and
    nothing is rejected. `[]` is a real value that clears every label.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in labels:
        label = (raw or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        cleaned.append(label)
    return cleaned


def _validated(applicability: Applicability) -> Applicability:
    """The patched applicability, normalized — or `HTTPException(400)`.

    An applicability that covers nothing is refused rather than written: a
    `kind="parts"` document with no parts, or a `kind="family"` one with no
    family, would silently disappear from every part's view while looking
    like a successful edit.
    """
    evidence = (applicability.evidence or "").strip() or USER_EDIT_EVIDENCE
    if applicability.kind == "parts":
        parts: list[str] = []
        seen: set[str] = set()
        for raw in applicability.parts:
            name = (raw or "").strip()
            if not name or name.upper() in seen:
                continue
            seen.add(name.upper())
            parts.append(name)
        if not parts:
            raise HTTPException(
                status_code=400,
                detail='applicability kind="parts" needs at least one part number',
            )
        return Applicability(kind="parts", parts=parts, evidence=evidence)
    if applicability.kind == "family":
        family = (applicability.family or "").strip()
        if not family:
            raise HTTPException(
                status_code=400,
                detail='applicability kind="family" needs a family prefix, e.g. "AFE79xx"',
            )
        return Applicability(kind="family", family=family, evidence=evidence)
    return Applicability(kind="all", evidence=evidence)


# --- endpoints ----------------------------------------------------------------


@router.get("", response_model=LibraryOut, summary="Every document on the shelf")
def list_library(store: StoreDep, settings: SettingsDep) -> LibraryOut:
    """The whole library: applicability, labels, and the parts each reaches.

    An empty library is an empty list with 200 — a shelf nobody has filled
    yet is a normal state, not an error.
    """
    documents = store.all()
    reach = _Reach.build(documents, settings)
    labels = sorted({label for doc in documents for label in doc.labels})
    out = [reach.project(doc) for doc in documents]
    return LibraryOut(documents=out, count=len(out), labels=labels)


@router.patch(
    "/{content_hash}",
    response_model=LibraryDocumentOut,
    summary="Correct one document's applicability, labels, or both",
)
def patch_library_document(
    content_hash: str,
    patch: LibraryPatchIn,
    store: StoreDep,
    settings: SettingsDep,
) -> LibraryDocumentOut:
    """Write applicability, labels, or both — and rebuild nothing.

    Omission and emptiness stay distinguishable: `labels: []` clears every
    label, `labels` absent leaves them alone, and the same holds for
    `applicability`. A patch with neither field is an accepted no-op that
    reports the document's current reach.
    """
    doc = store.get(content_hash)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"no library document with content hash {content_hash!r}",
        )
    if patch.applicability is not None:
        doc = store.set_applicability(content_hash, _validated(patch.applicability))
    if patch.labels is not None:
        doc = store.set_labels(content_hash, _clean_labels(patch.labels))
    reach = _Reach.build(store.all(), settings)
    return reach.project(doc)
