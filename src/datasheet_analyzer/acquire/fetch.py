"""`dsa fetch` — resolve, download, hash-verify, register.

Phase 7, ticket 01. This is the only command in the repo that may reach the
network for a *document*; `dsa build` stays offline by construction and
acquires nothing as a side effect (`tests/unit/test_fetch.py` asserts the
pipeline never imports this module). Onboarding is therefore an explicit act
with an explicit result, which is what makes a corpus's provenance readable
after the fact.

The download seam is the `BinaryFetcher` protocol already in
`extract/http.py` — `CachingBinaryFetcher` in production, `ReplayBinaryFetcher`
in tests, where an unrecorded URL is a hard error (invariant 4). Nothing here
opens a socket itself.

Four rules are load-bearing, and each one is a refusal.

- **A hash mismatch stops.** When the registry records a sha256 and the bytes
  hash to something else, the document is *not* written and *not* registered:
  the staged file is deleted and the command fails, naming the likely cause. A
  silent overwrite would replace a verified corpus's input with an unreviewed
  document while every page citation kept pointing at page numbers that may no
  longer mean the same thing. `--accept-new-revision` is the reviewed path —
  it records the new hash and the revision the new bytes actually report. The
  warning decides its *cause* from the parsed revision rather than from the
  hash (`mismatch_cause`): a measured TI behaviour makes "the hash moved" and
  "the revision moved" different statements, and this command may only make the
  one it can support.
- **A registry miss names `--url`.** It never guesses a URL and never falls
  back to a search (`acquire/registry.py`).
- **A fetch records only what happened.** `retrieved_at` is stamped from the
  clock at fetch time (injectable, so tests stay hermetic), `sha256` is
  computed from the bytes that arrived, and `revision` is sniffed from the
  written document by the same shared lexicon `dsa build` uses. Nothing is
  back-filled and nothing is expected.
- **A document already present is skipped and said out loud.** `--project`
  fetches what a design is missing, and reports every part it skipped and why,
  because "did nothing" and "did nothing because everything was here" are
  different answers to a maintainer.

The destination is `parts/<PART>/documents/<file>.pdf` and the document is
registered into that part's `sources.json` exactly as `dsa add-doc` would, so
`dsa build` picks it up from the inventory with no further arguments.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from datasheet_analyzer.acquire.inventory import (
    append_to_inventory,
    load_inventory,
    register_source,
)
from datasheet_analyzer.acquire.registry import (
    DocumentRegistry,
    RegistryDocument,
    RegistryEntry,
    RegistryMiss,
    load_registry,
    no_url_message,
    resolve,
    save_registry,
)
from datasheet_analyzer.config import Settings
from datasheet_analyzer.extract.http import BinaryFetcher
from datasheet_analyzer.models import DocType, SourceDocument

log = logging.getLogger(__name__)

#: Where a fetched document lands inside its part.
DOCUMENTS_DIRNAME = "documents"

# Outcomes. They are strings rather than an enum because they are printed and
# serialized to `--json` far more often than they are compared.
FETCHED = "fetched"
SKIPPED = "skipped"
MISMATCH = "hash-mismatch"
NO_URL = "no-url"
ERROR = "error"

#: Characters a destination filename may keep. Everything else is dropped
#: rather than escaped: a URL is untrusted input and the filename it suggests
#: is a convenience, not a fact worth preserving byte for byte.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class FetchError(Exception):
    """A fetch that cannot be honoured, with the fix in the text."""


@dataclass
class FetchedDocument:
    """What happened to one document of one part."""

    part_number: str
    doc_type: DocType
    url: str
    status: str
    message: str = ""
    path: Path | None = None
    sha256: str = ""
    expected_sha256: str = ""
    revision: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {FETCHED, SKIPPED}

    def as_dict(self) -> dict:
        return {
            "part": self.part_number,
            "doc_type": self.doc_type.value,
            "url": self.url,
            "status": self.status,
            "message": self.message,
            "path": str(self.path) if self.path is not None else None,
            "sha256": self.sha256 or None,
            "expected_sha256": self.expected_sha256 or None,
            "revision": self.revision or None,
        }


@dataclass
class FetchReport:
    """Every document one `dsa fetch` invocation touched."""

    documents: list[FetchedDocument] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(d.ok for d in self.documents)

    @property
    def fetched(self) -> list[FetchedDocument]:
        return [d for d in self.documents if d.status == FETCHED]

    @property
    def skipped(self) -> list[FetchedDocument]:
        return [d for d in self.documents if d.status == SKIPPED]

    @property
    def failed(self) -> list[FetchedDocument]:
        return [d for d in self.documents if not d.ok]

    def as_dict(self) -> dict:
        return {
            "n_fetched": len(self.fetched),
            "n_skipped": len(self.skipped),
            "n_failed": len(self.failed),
            "documents": [d.as_dict() for d in self.documents],
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def documents_dir(part_number: str, settings: Settings) -> Path:
    return settings.parts_dir / part_number / DOCUMENTS_DIRNAME


def destination_name(doc: RegistryDocument, part_number: str) -> str:
    """The basename a fetched document is written under.

    The registry's own `filename` wins; otherwise the URL's last path segment,
    sanitized; otherwise `<PART>_<doc_type>.pdf`. The suffix is forced to
    `.pdf` because `detect_doc_type` and every backend in this repo read one.
    """
    if doc.filename:
        candidate = doc.filename
    else:
        candidate = Path(urlsplit(doc.url or "").path).name
    candidate = _SAFE_NAME.sub("", candidate).strip("._-")
    if not candidate:
        candidate = f"{part_number}_{doc.doc_type.value}.pdf"
    if not candidate.lower().endswith(".pdf"):
        candidate = f"{candidate}.pdf"
    return candidate


def mismatch_cause(doc: RegistryDocument, got_revision: str) -> str:
    """The likely cause of a hash mismatch, decided by the **parsed revision**.

    The naive reading — "the hash moved, so the revision moved" — is measured
    to be wrong here, and the measurement is recorded in the ticket
    (`.scratch/reach-and-trust/issues/01-document-registry-and-fetch.md`, note
    added by the repo owner with network): TI regenerates a datasheet's
    *package materials* addendum with the current date on every download, so a
    TI PDF's bytes change daily while its revision identifier stays put. A
    warning that asserted a new revision on that evidence would send a designer
    hunting for a changelog that does not exist, and — worse — would teach them
    to click past the warning that matters.

    So the revision identifier decides:

    - it moved            → a new upstream revision (the case the ticket names);
    - it did **not** move → the document was regenerated, and this is
      explicitly *not* evidence of a new revision;
    - one side is unknown → say that, and assert nothing.

    Ticket 02 owns staleness itself; this function only refuses to overstate.
    """
    recorded = doc.revision
    got = got_revision
    if got and recorded and got != recorded:
        return (
            f"the downloaded document reports revision {got} while the registry "
            f"records {recorded} — a NEW UPSTREAM REVISION"
        )
    if got and recorded and got == recorded:
        return (
            f"both documents report revision {recorded}, so this is NOT evidence of "
            f"a new revision — the bytes changed while the revision identifier did "
            f"not. A vendor that regenerates a datasheet's package-materials "
            f"addendum with the current date on every download produces exactly "
            f"this, and so does an in-place upstream edit"
        )
    if not recorded:
        return (
            f"the registry records no revision to compare against, and the "
            f"downloaded document reports {got or 'none'} — nothing here says "
            f"whether the revision moved"
        )
    return (
        f"no revision could be parsed from the downloaded document (the registry "
        f"records {recorded}), so nothing here says whether the revision moved"
    )


def mismatch_message(
    part_number: str,
    doc: RegistryDocument,
    *,
    got_sha256: str,
    got_revision: str,
) -> str:
    """The loud warning. It names the likely cause and the flag that accepts it."""
    origin = f" (recorded from {doc.sha256_origin})" if doc.sha256_origin else ""
    return (
        f"sha256 MISMATCH for {part_number} ({doc.doc_type.value}) — nothing was "
        f"written.\n"
        f"  url      {doc.url}\n"
        f"  expected {doc.sha256}{origin}\n"
        f"  got      {got_sha256}\n"
        f"  revision recorded {doc.revision or 'unknown'} — downloaded "
        f"{got_revision or 'unknown'}\n"
        f"  {mismatch_cause(doc, got_revision)}.\n"
        f"  Look at the upstream document, then re-run with "
        f"--accept-new-revision to record the hash and revision that arrived."
    )


def readable_pdf_error(payload: bytes) -> str:
    """`""` when `payload` opens as a PDF, else why it does not.

    Checked **in memory, before anything is written**. A URL that answers with
    an HTML "document not found" page is the most likely failure of a fetch by
    URL, and letting those bytes reach the part directory — even briefly, even
    under a staging name — puts a file that is not a datasheet where a
    datasheet belongs.
    """
    import pymupdf

    try:
        with pymupdf.open(stream=payload, filetype="pdf") as doc:
            if doc.page_count < 1:
                return "the document has no pages"
    except Exception as exc:  # noqa: BLE001 - any open failure is the same finding
        return str(exc)
    return ""


def _remove_quietly(path: Path) -> None:
    """Delete a staged file, retrying the Windows "still open" window.

    Same reasoning as `pipeline._atomic_write_text`'s rename retry: on Windows
    a reader that has just failed can hold the handle a moment longer, and a
    refused fetch must not leave its bytes behind because of it.
    """
    for attempt in range(10):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.01 * (attempt + 1))
    log.warning("could not remove staged download: %s", path)


def _stage_bytes(dest: Path, payload: bytes) -> Path:
    """Write `payload` beside `dest` under a unique temp name and return it.

    Staging is what makes the mismatch path a true refusal: the bytes have to
    be on disk for `sniff_revision` to read them, and a mismatch then deletes
    the staged file rather than replacing a verified document with it.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".incoming")
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    return Path(tmp)


def _already_present(part_dir: Path, doc: RegistryDocument, dest: Path) -> bool:
    """True when this document is already in the part's inventory.

    Identity is the sha256 of the bytes (the same identity `sources.json`
    uses), falling back to the destination path when the registry records no
    hash — a document nobody has hashed is still *present* if it is there.
    """
    inventory = load_inventory(part_dir)
    if doc.sha256:
        return any(s.content_hash == doc.sha256 for s in inventory)
    return dest.exists() and any(Path(s.path) == dest for s in inventory)


def fetch_document(
    part_number: str,
    doc: RegistryDocument,
    *,
    fetcher: BinaryFetcher,
    settings: Settings,
    vendor: str | None = None,
    accept_new_revision: bool = False,
    skip_present: bool = False,
    now: datetime | None = None,
) -> tuple[FetchedDocument, SourceDocument | None]:
    """Fetch, verify and register one document. Never raises for a bad fetch.

    Returns the outcome plus the registered `SourceDocument` (None when
    nothing was registered). The registry is *not* written here — the caller
    decides whether a run updates the checked-in file, so a failed fetch can
    never leave a half-updated entry behind.
    """
    part_dir = settings.parts_dir / part_number
    # The recorded hash, captured before this call rewrites the entry: a
    # fetched document reports what it was checked *against*, not what it
    # became, or the mismatch that was accepted would read as no mismatch.
    expected = doc.sha256
    prior_revision = doc.revision
    if not doc.url:
        return (
            FetchedDocument(
                part_number=part_number,
                doc_type=doc.doc_type,
                url="",
                status=NO_URL,
                message=no_url_message(part_number, doc),
            ),
            None,
        )

    dest = documents_dir(part_number, settings) / destination_name(doc, part_number)
    if skip_present and _already_present(part_dir, doc, dest):
        return (
            FetchedDocument(
                part_number=part_number,
                doc_type=doc.doc_type,
                url=doc.url,
                status=SKIPPED,
                message="already registered in this part's inventory",
                path=dest if dest.exists() else None,
                sha256=expected,
                expected_sha256=expected,
                revision=doc.revision,
            ),
            None,
        )

    try:
        payload = fetcher(doc.url)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not kill a project run
        return (
            FetchedDocument(
                part_number=part_number,
                doc_type=doc.doc_type,
                url=doc.url,
                status=ERROR,
                message=f"download failed: {exc}",
            ),
            None,
        )

    got = hashlib.sha256(payload).hexdigest()
    unreadable = readable_pdf_error(payload)
    if unreadable:
        return (
            FetchedDocument(
                part_number=part_number,
                doc_type=doc.doc_type,
                url=doc.url,
                status=ERROR,
                message=f"downloaded bytes are not a readable PDF: {unreadable}",
                sha256=got,
                expected_sha256=expected,
            ),
            None,
        )

    staged = _stage_bytes(dest, payload)
    try:
        source = register_source(
            staged,
            part_number=part_number,
            doc_type=doc.doc_type,
            vendor=vendor,
        )
    except Exception as exc:  # noqa: BLE001 - a document we cannot register is a finding
        _remove_quietly(staged)
        return (
            FetchedDocument(
                part_number=part_number,
                doc_type=doc.doc_type,
                url=doc.url,
                status=ERROR,
                message=f"downloaded document could not be registered: {exc}",
                sha256=got,
                expected_sha256=expected,
            ),
            None,
        )

    if expected and got != expected and not accept_new_revision:
        _remove_quietly(staged)
        return (
            FetchedDocument(
                part_number=part_number,
                doc_type=doc.doc_type,
                url=doc.url,
                status=MISMATCH,
                message=mismatch_message(
                    part_number, doc, got_sha256=got, got_revision=source.revision
                ),
                sha256=got,
                expected_sha256=expected,
                revision=source.revision,
            ),
            None,
        )

    os.replace(staged, dest)
    source.path = str(dest)
    append_to_inventory([source], part_dir)

    accepted = bool(expected) and got != expected
    stamped = now or _utcnow()
    doc.sha256 = got
    doc.sha256_origin = f"fetch:{doc.url}"
    doc.revision = source.revision
    doc.retrieved_at = stamped
    doc.url_verified = True
    doc.filename = dest.name

    # What was accepted is stated in the same terms the refusal used: a hash
    # that moved while the revision identifier did not is *not* a new revision,
    # and recording it as one would put a false revision in the registry.
    message = (
        ""
        if not accepted
        else (
            f"accepted: sha256 recorded as {got[:12]}…, revision "
            f"{source.revision or 'unknown'} — "
            + (
                "a new upstream revision"
                if prior_revision and source.revision and source.revision != prior_revision
                else "the revision identifier is unchanged (the document was regenerated)"
                if prior_revision and source.revision == prior_revision
                else "no revision comparison was possible"
            )
        )
    )
    return (
        FetchedDocument(
            part_number=part_number,
            doc_type=doc.doc_type,
            url=doc.url,
            status=FETCHED,
            message=message,
            path=dest,
            sha256=got,
            expected_sha256=expected,
            revision=source.revision,
        ),
        source,
    )


def fetch_part(
    part_number: str,
    *,
    fetcher: BinaryFetcher,
    settings: Settings,
    registry: DocumentRegistry | None = None,
    registry_file: Path | None = None,
    url: str | None = None,
    doc_type: DocType | None = None,
    vendor: str | None = None,
    accept_new_revision: bool = False,
    skip_present: bool = False,
    now: datetime | None = None,
    write_registry: bool = True,
) -> FetchReport:
    """Fetch one part's documents, growing the registry by use.

    `url` given: the part is added to (or updated in) the registry with the URL
    supplied, which is the documented growth path — an agent that finds a URL
    calls this itself. `url` omitted: the registry must already know the part,
    and a miss raises `RegistryMiss` with the message naming `--url`.
    """
    reg = registry if registry is not None else load_registry(registry_file)
    if url:
        entry = reg.get(part_number) or RegistryEntry(part_number=part_number)
        wanted = doc_type or DocType.DATASHEET
        docs = [d for d in entry.documents if d.url == url]
        if not docs:
            docs = [d for d in entry.documents if d.doc_type == wanted and not d.url]
        if docs:
            doc = docs[0]
            doc.url = url
            doc.doc_type = wanted
            doc.url_derivation = ""
            doc.url_reason = ""
        else:
            doc = RegistryDocument(doc_type=wanted, url=url)
            if entry.document.url is None and not entry.companions:
                entry.document = doc
            else:
                entry.companions.append(doc)
        if vendor:
            entry.vendor = vendor
        reg.put(entry)
        targets = [doc]
    else:
        targets = resolve(reg, part_number, doc_type=doc_type)

    report = FetchReport()
    registered_vendor = vendor
    for doc in targets:
        outcome, source = fetch_document(
            part_number,
            doc,
            fetcher=fetcher,
            settings=settings,
            vendor=registered_vendor,
            accept_new_revision=accept_new_revision,
            skip_present=skip_present,
            now=now,
        )
        report.documents.append(outcome)
        entry = reg.get(part_number)
        if source is not None and entry is not None and not entry.vendor:
            entry.vendor = source.vendor

    if write_registry and report.fetched:
        save_registry(reg, registry_file)
    return report


def fetch_project(
    project_name: str,
    *,
    fetcher: BinaryFetcher,
    settings: Settings,
    registry: DocumentRegistry | None = None,
    registry_file: Path | None = None,
    accept_new_revision: bool = False,
    now: datetime | None = None,
    write_registry: bool = True,
) -> FetchReport:
    """Fetch everything a project needs that is not already present.

    The BOM → corpora path end to end: a project is an explicit part list, and
    this walks it, skipping documents whose bytes are already in that part's
    inventory and *saying so*. A part the registry does not know is reported
    as a failure naming `--url` — it never aborts the run, because one unknown
    part must not stop the other seven from arriving.
    """
    from datasheet_analyzer.projects import load_project

    reg = registry if registry is not None else load_registry(registry_file)
    project = load_project(project_name, settings.projects_dir)

    report = FetchReport()
    for part_number in project.part_numbers:
        try:
            part_report = fetch_part(
                part_number,
                fetcher=fetcher,
                settings=settings,
                registry=reg,
                registry_file=registry_file,
                accept_new_revision=accept_new_revision,
                skip_present=True,
                now=now,
                write_registry=False,
            )
        except RegistryMiss as exc:
            report.documents.append(
                FetchedDocument(
                    part_number=part_number,
                    doc_type=DocType.DATASHEET,
                    url="",
                    status=NO_URL,
                    message=str(exc),
                )
            )
            continue
        report.documents.extend(part_report.documents)

    if write_registry and report.fetched:
        save_registry(reg, registry_file)
    return report
