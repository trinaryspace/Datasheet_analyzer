"""`dsa check-revisions` — ask upstream whether a corpus is still current.

Phase 7, ticket 02. This is an **explicit, opt-in, network** command and it is
the only thing in this repo that writes a `staleness` state. `dsa build` never
calls it — `tests/unit/test_revisions.py::TestBuildChecksNothing` asserts the
pipeline does not reference this module at all — which is what keeps builds
offline by construction. Nothing on the answer path (`ask`, `query`, `search`,
`verify`) calls it either: a lookup that silently reached the network would be
a lookup whose latency and failure modes depend on a vendor's web server.

Five refusals define the behaviour.

- **Staleness is decided by the parsed revision identifier, never by a hash.**
  A TI datasheet's bytes change on every download (the package-materials
  addendum is regenerated with the current date — measured, see the ticket and
  `Reports/PHASE_7_LIVE_RUN.md`), so "the hash moved" says nothing about the
  revision. Bytes that moved under an unchanged revision are recorded as
  `content_drift` and worded as a *regenerated* document, never a revised one.
- **A check that cannot complete changes no state.** No URL, no network, an
  unreadable download: the recorded state and its date stay exactly as they
  were and the reason is recorded beside them. A failed check can therefore
  never turn `stale` into `current`, and a corpus nobody could check stays
  `unknown` rather than acquiring an optimistic reading.
- **An inconclusive comparison is `unknown`, not `current`.** If either side
  prints no revision identifier there is nothing to compare, and saying so is
  the answer.
- **Nothing is written into the part's document directory.** The upstream bytes
  are hashed and read in memory (`sniff_revision_bytes`); an unverified
  document has no business sitting where a datasheet lives, even briefly. The
  documented way to *take* a new revision is `dsa fetch --accept-new-revision`.
- **The registry is not rewritten.** A check reads `registry/datasheets.yaml`
  for the URL and leaves it alone; `url_verified` is flipped by a fetch that
  put bytes on disk, which is a different act from asking what is upstream.

The state lands on the inventory (`sources.json`) and the `INDEX.md` banner is
refreshed in place, so every surface reflects the check without a rebuild.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from datasheet_analyzer.acquire.inventory import load_inventory, save_inventory
from datasheet_analyzer.acquire.registry import (
    DocumentRegistry,
    RegistryDocument,
    RegistryEntry,
    load_registry,
)
from datasheet_analyzer.config import Settings
from datasheet_analyzer.extract.http import BinaryFetcher
from datasheet_analyzer.extract.pdf_structure import sniff_revision_bytes
from datasheet_analyzer.models import DocType, SourceDocument, Staleness
from datasheet_analyzer.retrieve.index import INDEX_FILENAME
from datasheet_analyzer.staleness import (
    apply_index_banner,
    corpus_staleness,
    index_banner,
)

log = logging.getLogger(__name__)

# Outcomes of one document's check. Strings for the same reason `fetch.py`'s
# are: they are printed and serialized far more often than compared.
CHECKED = "checked"
NO_URL = "no-url"
ERROR = "error"


@dataclass
class RevisionCheck:
    """What one check found about one document of one part."""

    part_number: str
    doc_type: DocType
    url: str = ""
    status: str = CHECKED
    state: Staleness = Staleness.UNKNOWN
    built_revision: str = ""
    upstream_revision: str = ""
    upstream_sha256: str = ""
    local_sha256: str = ""
    content_drift: bool = False
    checked_at: datetime | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        """True when the check completed *and* found the corpus current.

        A stale corpus is not an error — it is the finding this command exists
        to make — but it is not "ok" either, so a CI run can fail on it.
        """
        return self.status == CHECKED and self.state is Staleness.CURRENT

    @property
    def completed(self) -> bool:
        return self.status == CHECKED

    def as_dict(self) -> dict:
        return {
            "part": self.part_number,
            "doc_type": self.doc_type.value,
            "url": self.url or None,
            "status": self.status,
            "staleness": self.state.value,
            "built_revision": self.built_revision or None,
            "upstream_revision": self.upstream_revision or None,
            "upstream_sha256": self.upstream_sha256 or None,
            "local_sha256": self.local_sha256 or None,
            "content_drift": self.content_drift,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "message": self.message,
        }


@dataclass
class RevisionReport:
    """Every document one `dsa check-revisions` invocation looked at."""

    checks: list[RevisionCheck] = field(default_factory=list)

    @property
    def stale(self) -> list[RevisionCheck]:
        return [c for c in self.checks if c.state is Staleness.STALE]

    @property
    def failed(self) -> list[RevisionCheck]:
        return [c for c in self.checks if not c.completed]

    @property
    def drifted(self) -> list[RevisionCheck]:
        return [c for c in self.checks if c.content_drift]

    @property
    def ok(self) -> bool:
        """No stale corpus and no check that could not run."""
        return not self.stale and not self.failed

    def as_dict(self) -> dict:
        return {
            "n_checked": len([c for c in self.checks if c.completed]),
            "n_stale": len(self.stale),
            "n_failed": len(self.failed),
            "n_content_drift": len(self.drifted),
            "checks": [c.as_dict() for c in self.checks],
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def registry_document_for(
    entry: RegistryEntry | None, source: SourceDocument
) -> RegistryDocument | None:
    """The registry document that describes `source`, or None.

    Matched by recorded sha256 first (identity, the same one `sources.json`
    uses), then by the filename the registry recorded, then by document type.
    Type is last because a part may carry two documents of one type and a
    wrong pairing would compare a datasheet against an app note's revision —
    a comparison that is confidently wrong in both directions.
    """
    if entry is None:
        return None
    docs = entry.documents
    for doc in docs:
        if doc.sha256 and doc.sha256 == source.content_hash:
            return doc
    name = Path(source.path).name
    for doc in docs:
        if doc.filename and doc.filename == name:
            return doc
    same_type = [d for d in docs if d.doc_type == source.doc_type]
    return same_type[0] if len(same_type) == 1 else None


def no_url_note(part_number: str, source: SourceDocument) -> str:
    """Why a document could not be checked, and the flag that fixes it."""
    return (
        f"no registry URL for this {source.doc_type.value} — nothing to check "
        f"against. Record one with `dsa fetch --url <URL> --part {part_number} "
        f"--doc-type {source.doc_type.value}`"
    )


def compare(
    source: SourceDocument, payload: bytes, *, now: datetime
) -> RevisionCheck:
    """Decide one document's state from the upstream bytes. Pure but for `now`.

    Revision-first, and the three outcomes are all *statements*:
    identifiers equal → `current` (with `content_drift` when the bytes moved
    anyway), identifiers differ → `stale`, either identifier missing →
    `unknown` with the reason. Nothing here ever reads a hash difference as a
    revision change.
    """
    upstream_sha = hashlib.sha256(payload).hexdigest()
    upstream_rev = sniff_revision_bytes(payload)
    built_rev = source.revision
    check = RevisionCheck(
        part_number=source.part_number,
        doc_type=source.doc_type,
        status=CHECKED,
        built_revision=built_rev,
        upstream_revision=upstream_rev,
        upstream_sha256=upstream_sha,
        local_sha256=source.content_hash,
        checked_at=now,
    )
    if not upstream_rev or not built_rev:
        check.state = Staleness.UNKNOWN
        missing = (
            "the upstream document prints no revision identifier this repo's "
            "shared lexicon can read"
            if not upstream_rev
            else "this corpus's document prints no revision identifier to compare"
        )
        check.message = f"{missing}, so the comparison is inconclusive"
        return check
    if upstream_rev != built_rev:
        check.state = Staleness.STALE
        check.message = (
            f"upstream reports {upstream_rev}; this corpus is built from {built_rev}"
        )
        return check
    check.state = Staleness.CURRENT
    check.content_drift = upstream_sha != source.content_hash
    check.message = (
        f"upstream reports {upstream_rev}, unchanged"
        if not check.content_drift
        else (
            f"upstream reports {upstream_rev}, unchanged — but the bytes differ: "
            f"the document was regenerated, not revised"
        )
    )
    return check


def _record(source: SourceDocument, check: RevisionCheck) -> None:
    """Write a **completed** check onto the inventory record.

    Only completed checks land here: a check that could not run leaves the
    recorded state and date untouched and only records why, which is what makes
    a stale-to-current transition impossible on a failure.
    """
    source.staleness = check.state
    source.revision_checked_at = check.checked_at
    source.upstream_revision = check.upstream_revision
    source.upstream_sha256 = check.upstream_sha256
    source.content_drift = check.content_drift
    source.revision_check_note = check.message


def refresh_index_banner(part_dir: Path) -> bool:
    """Rewrite the `INDEX.md` staleness banner from the inventory on disk.

    True when a file was written. A part with no `INDEX.md` (never built) is
    not an error: the check still records its finding on the inventory, and the
    banner appears the moment the corpus is built.
    """
    index = Path(part_dir) / INDEX_FILENAME
    if not index.exists():
        return False
    st = corpus_staleness(load_inventory(Path(part_dir)), Path(part_dir).name)
    text = index.read_text(encoding="utf-8")
    updated = apply_index_banner(text, index_banner(st))
    if updated == text:
        return False
    index.write_text(updated, encoding="utf-8")
    return True


def check_part(
    part_number: str,
    *,
    fetcher: BinaryFetcher,
    settings: Settings,
    registry: DocumentRegistry | None = None,
    registry_file: Path | None = None,
    now: datetime | None = None,
    write: bool = True,
) -> RevisionReport:
    """Check every document of one part against its recorded upstream URL."""
    part_dir = settings.parts_dir / part_number
    sources = load_inventory(part_dir)
    report = RevisionReport()
    if not sources:
        report.checks.append(
            RevisionCheck(
                part_number=part_number,
                doc_type=DocType.UNKNOWN,
                status=ERROR,
                message=(
                    f"no documents are registered for {part_number} — nothing to "
                    f"check (build it first, or `dsa fetch {part_number}`)"
                ),
            )
        )
        return report

    reg = registry if registry is not None else load_registry(registry_file)
    entry = reg.get(part_number)
    stamped = now or _utcnow()
    changed = False

    for source in sources:
        source.part_number = source.part_number or part_number
        doc = registry_document_for(entry, source)
        if doc is None or not doc.url:
            note = no_url_note(part_number, source)
            # The reason is recorded; the state and its date are not touched.
            source.revision_check_note = note
            changed = True
            report.checks.append(
                RevisionCheck(
                    part_number=part_number,
                    doc_type=source.doc_type,
                    status=NO_URL,
                    state=source.staleness,
                    built_revision=source.revision,
                    local_sha256=source.content_hash,
                    checked_at=source.revision_checked_at,
                    message=note,
                )
            )
            continue

        try:
            payload = fetcher(doc.url)
        except Exception as exc:  # noqa: BLE001 - one bad URL must not kill the run
            note = (
                f"could not reach {doc.url}: {exc} — the recorded state "
                f"({source.staleness.value}) is unchanged"
            )
            source.revision_check_note = note
            changed = True
            report.checks.append(
                RevisionCheck(
                    part_number=part_number,
                    doc_type=source.doc_type,
                    url=doc.url,
                    status=ERROR,
                    state=source.staleness,
                    built_revision=source.revision,
                    local_sha256=source.content_hash,
                    checked_at=source.revision_checked_at,
                    message=note,
                )
            )
            continue

        check = compare(source, payload, now=stamped)
        check.part_number = part_number
        check.url = doc.url
        _record(source, check)
        changed = True
        report.checks.append(check)

    if write and changed:
        save_inventory(sources, part_dir)
        refresh_index_banner(part_dir)
    return report


def check_all(
    *,
    fetcher: BinaryFetcher,
    settings: Settings,
    registry: DocumentRegistry | None = None,
    registry_file: Path | None = None,
    now: datetime | None = None,
    write: bool = True,
) -> RevisionReport:
    """Check every part under `parts_dir`, in name order.

    One part's failure never stops the rest: the point of `--all` is a fleet
    reading, and a fleet reading with a hole in it is still worth having as
    long as the hole is reported — which it is, as an `error` check.
    """
    from datasheet_analyzer.retrieve.index import discover_parts

    reg = registry if registry is not None else load_registry(registry_file)
    report = RevisionReport()
    for part_dir in discover_parts(settings.parts_dir):
        part_report = check_part(
            part_dir.name,
            fetcher=fetcher,
            settings=settings,
            registry=reg,
            registry_file=registry_file,
            now=now,
            write=write,
        )
        report.checks.extend(part_report.checks)
    return report
