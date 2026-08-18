"""Source inventory: the Library says which documents a part is built from.

Historically a part *owned* a folder of documents and `sources.json` was the
authoritative list. ADR 0005 inverts that: a document declares the parts it
applies to (its `Applicability`), the Library holds that record keyed by
`content_hash`, and a Part is the *view* of the documents that cover it.

So `sources.json` is now a **derived, read-only** artifact — regenerated at
publish time from `store.for_part(part_number)` and stamped
`"generated": true` so a reader knows not to hand-edit it. Everything that
reads it (`dsa status`, the batch skip gate) keeps working unchanged.

Back-compat is not optional: a part directory built by the old code has a
`sources.json` and no Library entry. `resolve_documents()` detects that and
migrates each entry in on first touch, recording
`evidence="migrated from sources.json"` — and, because the Library is keyed by
content hash, doing it again is a no-op.

Vendor stays what it has always been: an evidence-pinned routing record
decided at acquire time (ADR 0002). Nothing here turns it into a runtime guess.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from datasheet_analyzer.extract.pdf_structure import compute_content_hash, make_source
from datasheet_analyzer.models import Applicability, DocType, LibraryDocument, SourceDocument
from datasheet_analyzer.vendor import detect_vendor, override_evidence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datasheet_analyzer.config import Settings
    from datasheet_analyzer.library.store import LibraryStore

log = logging.getLogger(__name__)

SOURCES_FILE = "sources.json"

# Stamped on every entry migrated out of a legacy `sources.json`. Asserted by
# tests and printed by the review UI, so it is a constant, not a f-string.
MIGRATION_EVIDENCE = "migrated from sources.json"

# The header a reader (human or agent) sees at the top of the derived file.
GENERATED_NOTE = (
    "Generated file - do not edit. The Library is the authoritative inventory; "
    "this is a derived view of the documents that apply to this part, "
    "regenerated at publish time. Hand edits are overwritten by the next build."
)

# Doc-type shared lexicon (SPEC story 24): TI prefixes (sbaa/slaa/swra)
# and ADI user-guide prefixes (ug-####) are app notes; order errata →
# register → note → datasheet means register/regmap words always beat a
# ug- prefix. The \b boundary keeps mid-word "ug" from ever counting.
_HINTS: list[tuple[re.Pattern[str], DocType]] = [
    (re.compile(r"errata", re.IGNORECASE), DocType.ERRATA),
    (re.compile(r"register|regmap|reg[-_ ]?map|programming", re.IGNORECASE), DocType.REGISTER_MAP),
    (re.compile(r"app[-_ ]?note|sbaa|slaa|swra|\bug[-_ ]?\d+", re.IGNORECASE), DocType.APP_NOTE),
    (re.compile(r"datasheet|data[-_ ]?sheet|^[a-z0-9]+\.pdf$", re.IGNORECASE), DocType.DATASHEET),
]


def detect_doc_type(path: Path) -> DocType:
    name = path.name.lower()
    for pat, dtype in _HINTS:
        if pat.search(name):
            return dtype
    return DocType.UNKNOWN


def register_source(
    path: Path,
    *,
    part_number: str = "",
    doc_type: DocType | None = None,
    nda: bool = False,
    vendor: str | None = None,
) -> SourceDocument:
    """Register one input document (identity = sha256 of its bytes).

    ``vendor`` None = evidence-pinned detection at acquire time; given =
    explicit override, recorded in ``vendor_evidence`` (never a silent
    guess on the routing path).
    """
    src = make_source(
        Path(path),
        part_number=part_number,
        doc_type=doc_type or detect_doc_type(Path(path)),
        nda=nda,
    )
    if vendor is not None:
        src.vendor = vendor
        src.vendor_evidence = override_evidence(vendor)
    else:
        src.vendor, src.vendor_evidence = detect_vendor(Path(path))
    log.info(
        "registered %s: type=%s rev=%s pages=%d hash=%s… vendor=%s (%s)",
        Path(path).name, src.doc_type.value, src.revision or "?",
        src.page_count, src.content_hash[:10], src.vendor, src.vendor_evidence,
    )
    return src


def register_into_library(
    pdf: Path,
    *,
    applicability: Applicability,
    doc_type: DocType | None = None,
    vendor: str | None = None,
    store: LibraryStore | None,
    part_number: str = "",
    nda: bool = False,
) -> LibraryDocument:
    """`register_source()` + the applicability that says which parts it is for.

    The returned `LibraryDocument` is written to ``store`` when one is
    available; a `None` store (or a store whose backing implementation is not
    present) still returns the wrapped document, so acquire degrades to the
    pre-Library behaviour instead of failing.
    """
    src = register_source(
        Path(pdf),
        part_number=part_number,
        doc_type=doc_type,
        nda=nda,
        vendor=vendor,
    )
    doc = LibraryDocument(source=src, applicability=applicability)
    if _put(store, doc):
        log.info(
            "library: registered %s (%s…) applying to %s",
            Path(src.path).name, src.content_hash[:10], applicability.label,
        )
    return doc


def pin_vendor(sources: list[SourceDocument], vendor: str) -> bool:
    """Repin every source's vendor with override evidence; True when changed."""
    evidence = override_evidence(vendor)
    changed = False
    for src in sources:
        if src.vendor != vendor or src.vendor_evidence != evidence:
            src.vendor = vendor
            src.vendor_evidence = evidence
            changed = True
    return changed


# --- the Library seam ------------------------------------------------------
#
# Every call into a `LibraryStore` goes through these two helpers, which
# tolerate a store that cannot answer. That is what lets a corpus built before
# the Library existed — and a deployment where the store is unavailable — keep
# building from its `sources.json` alone.


def default_store(settings: Settings | None = None) -> LibraryStore | None:
    """The store for ``settings``, or `None` when one cannot be constructed."""
    try:
        from datasheet_analyzer.library.store import LibraryStore

        return LibraryStore.for_settings(settings)
    except NotImplementedError:  # store implementation not present
        log.debug("library store unavailable — falling back to sources.json")
        return None


def _docs_for_part(store: LibraryStore | None, part_number: str) -> list[LibraryDocument] | None:
    """Library documents covering ``part_number``.

    `None` means *the Library could not answer* (no store); `[]` means it
    answered and no document covers this part. The caller treats those two
    differently: only the first falls back to the derived file.
    """
    if store is None or not part_number:
        return None
    try:
        return list(store.for_part(part_number))
    except NotImplementedError:
        return None


def _put(store: LibraryStore | None, doc: LibraryDocument) -> bool:
    """Write ``doc``; False when there is no store to write to."""
    if store is None:
        return False
    try:
        store.put(doc)
    except NotImplementedError:
        return False
    return True


def _get(store: LibraryStore | None, content_hash: str) -> LibraryDocument | None:
    if store is None:
        return None
    try:
        return store.get(content_hash)
    except NotImplementedError:
        return None


def get_document(store: LibraryStore | None, content_hash: str) -> LibraryDocument | None:
    """The Library's record for this hash, or `None` (no store, no record)."""
    return _get(store, content_hash)


def ensure_covers(
    doc: LibraryDocument,
    part_number: str,
    *,
    store: LibraryStore | None,
) -> SourceDocument:
    """Widen an existing record so it also applies to ``part_number``.

    Naming a document on the command line for a part it does not yet cover is
    a statement about applicability, so it is recorded as one — appended to
    the list, never replacing what is already there. A `family` record is left
    alone (a widened prefix would silently claim parts nobody asked for); it
    is used for this build and the mismatch is logged instead.
    """
    if doc.covers(part_number):
        return doc.source
    app = doc.applicability
    if app.kind != "parts":
        log.warning(
            "%s applies to %s but was named for %s — building it without "
            "changing that record",
            Path(doc.source.path).name, app.label, part_number,
        )
        return doc.source
    note = f"named for {part_number} at build"
    widened = Applicability.for_parts(
        [*app.parts, part_number],
        evidence=f"{app.evidence}; {note}" if app.evidence else note,
    )
    _put(store, doc.model_copy(update={"applicability": widened}))
    return doc.source


def sync_to_library(
    sources: list[SourceDocument],
    *,
    part_number: str,
    store: LibraryStore | None,
    evidence: str = "",
) -> int:
    """Write these sources back to the Library; return how many were written.

    An existing record keeps its applicability and its labels — only the
    `SourceDocument` is replaced. That is what makes this safe to call after a
    vendor repin or an evidence backfill: the routing record is updated
    without touching a single thing a user set.
    """
    written = 0
    for src in sources:
        existing = _get(store, src.content_hash)
        if existing is not None:
            if existing.source == src:
                continue
            doc = existing.model_copy(update={"source": src})
        else:
            doc = LibraryDocument(
                source=src,
                applicability=Applicability.for_parts([part_number], evidence=evidence),
            )
        if _put(store, doc):
            written += 1
    return written


# --- the derived view ------------------------------------------------------


def _sort_key(src: SourceDocument) -> tuple[int, str, str]:
    """Datasheet first, then a stable order by type and identity.

    Order has to be a function of the documents alone: `sources.json` is
    rewritten on every build and must be byte-identical when nothing changed,
    and the datasheet leads because it is the document whose vendor pins the
    part's routing.
    """
    return (0 if src.doc_type == DocType.DATASHEET else 1, src.doc_type.value, src.content_hash)


def sort_sources(sources: list[SourceDocument]) -> list[SourceDocument]:
    """The canonical order a document set is written and built in."""
    return sorted(sources, key=_sort_key)


def same_path(recorded: str, path: Path) -> bool:
    """Whether a recorded path names the same file as ``path``.

    Spelling is not identity: `plain.PDF` and `plain.pdf`, or a relative and
    an absolute spelling of one file, are the same document. (The same
    comparison `batch._same_path` makes, on the same reasoning.)
    """
    try:
        return Path(recorded).resolve() == Path(path).resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return str(recorded) == str(path)


def save_inventory(sources: list[SourceDocument], part_dir: Path) -> Path:
    """Regenerate `sources.json` as the derived view of this part's documents.

    The file carries `"generated": true` and a note saying where the
    authoritative record lives. Entries are written in a deterministic order,
    so two identical builds produce identical bytes.
    """
    part_dir = Path(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)
    dest = part_dir / SOURCES_FILE
    payload = {
        "generated": True,
        "note": GENERATED_NOTE,
        "part_number": part_dir.name,
        "sources": [s.model_dump(mode="json") for s in sort_sources(sources)],
    }
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def _parse_sources(data: Any) -> list[SourceDocument]:
    """Both shapes: the legacy bare list and the generated wrapper object."""
    if isinstance(data, dict):
        data = data.get("sources", [])
    if not isinstance(data, list):
        return []
    return [SourceDocument.model_validate(d) for d in data]


def read_sources_file(part_dir: Path) -> list[SourceDocument]:
    """The documents recorded in `sources.json`, ignoring the Library.

    Only two callers should want this: the migration path (which reads the
    file precisely because the Library has nothing yet) and a test asserting
    what was written.
    """
    dest = Path(part_dir) / SOURCES_FILE
    if not dest.exists():
        return []
    try:
        return _parse_sources(json.loads(dest.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:  # unreadable/corrupt — never fatal
        log.warning("unreadable %s: %s", dest, exc)
        return []


def load_inventory(part_dir: Path, *, store: LibraryStore | None = None) -> list[SourceDocument]:
    """This part's documents — from the Library, falling back to the file.

    The signature is unchanged for the readers that already call it
    (`dsa status`, the batch skip gate), but the answer now comes from
    `store.for_part(<part>)`; `sources.json` is consulted only when the
    Library has no record of this part, which is exactly the legacy corpus.
    """
    part_dir = Path(part_dir)
    docs = _docs_for_part(
        store if store is not None else default_store(),
        part_dir.name,
    )
    if docs:
        # The same view a build would run over, so what `dsa status` lists and
        # what the batch skip gate compares against is what would be built.
        return _view([d.source for d in docs])
    return read_sources_file(part_dir)


def resolve_documents(
    part_dir: Path,
    *,
    part_number: str,
    store: LibraryStore | None,
) -> list[SourceDocument]:
    """The document set a build for ``part_number`` runs over.

    Library first; any `sources.json` entry the Library does not know about is
    migrated in (idempotently — the key is the content hash) so a corpus built
    before the Library existed keeps building. Documents whose file has since
    disappeared are dropped with a warning rather than failing the build: the
    Library is a shelf shared by every part, and one deleted PDF must not
    break every build that a `kind="all"` document touches.
    """
    part_dir = Path(part_dir)
    library_docs = _docs_for_part(store, part_number)
    legacy = read_sources_file(part_dir)

    if library_docs is None:
        resolved = legacy
    else:
        known = {d.content_hash for d in library_docs}
        resolved = [d.source for d in library_docs]
        migrated = 0
        for src in legacy:
            if src.content_hash in known:
                continue
            doc = LibraryDocument(
                source=src,
                applicability=Applicability.for_parts(
                    [part_number], evidence=MIGRATION_EVIDENCE
                ),
            )
            if _put(store, doc):
                migrated += 1
            known.add(src.content_hash)
            resolved.append(src)
        if migrated:
            log.info(
                "library: migrated %d source(s) from %s/%s", migrated, part_dir.name, SOURCES_FILE
            )

    return _view(resolved)


def _view(sources: list[SourceDocument]) -> list[SourceDocument]:
    """The Library's records reduced to one buildable document set.

    Three reductions, all of them about the difference between *a shelf of
    records* and *this part's documents*: a record whose file is gone is not
    buildable, two records naming one file are one document, and a part has
    one datasheet.
    """
    return sort_sources(single_datasheet(_dedupe_by_path(_existing_only(sources))))


def relocate(
    source: SourceDocument,
    pdf_path: Path,
    *,
    store: LibraryStore | None,
) -> SourceDocument:
    """Point a record at the file the caller just named, keeping its identity.

    Identity is the content hash, so the same bytes under a new path are the
    same document that moved — not a second one. Recording the move keeps the
    inventory's `path` resolvable, which is what every reader downstream
    (extraction, `/api/pdf`, the batch skip gate) needs it for.
    """
    if same_path(source.path, pdf_path):
        return source
    log.info(
        "library: %s… moved %s -> %s", source.content_hash[:10], source.path, pdf_path
    )
    moved = source.model_copy(update={"path": str(pdf_path)})
    existing = _get(store, source.content_hash)
    if existing is not None:
        _put(store, existing.model_copy(update={"source": moved}))
    return moved


def single_datasheet(
    sources: list[SourceDocument], *, keep: str = ""
) -> list[SourceDocument]:
    """One datasheet per part: the named one, else the newest registration.

    A part is one device, and its datasheet is one document. Several
    datasheet records covering the same part means the file was replaced — a
    new revision, new bytes, therefore a new identity — and building both
    would publish two contradictory copies of the same specifications under
    one part. The superseded records stay in the Library (they are still real
    documents, and another part may name them); they are simply not part of
    *this* build. Companions are untouched: a part may hold any number of
    register maps, errata and notes.
    """
    datasheets = [s for s in sources if s.doc_type == DocType.DATASHEET]
    if len(datasheets) < 2:
        return sources
    winner = next(
        (s for s in datasheets if s.content_hash == keep),
        max(datasheets, key=lambda s: s.registered_at),
    )
    superseded = {s.content_hash for s in datasheets if s.content_hash != winner.content_hash}
    log.warning(
        "%d datasheet records apply to this part — building %s (%s…) and "
        "skipping %d superseded record(s)",
        len(datasheets), Path(winner.path).name, winner.content_hash[:10], len(superseded),
    )
    return [s for s in sources if s.content_hash not in superseded]


def _existing_only(sources: list[SourceDocument]) -> list[SourceDocument]:
    kept = []
    for src in sources:
        if Path(src.path).exists():
            kept.append(src)
        else:
            log.warning("skipping %s: file is gone (%s)", Path(src.path).name, src.path)
    return kept


def _dedupe_by_path(sources: list[SourceDocument]) -> list[SourceDocument]:
    """One record per file: the one whose hash matches the file's bytes today.

    A PDF replaced in place leaves its old record behind (that is what
    `batch._refresh_pdf_source` re-registers around). Both records name the
    same path, so building both would extract the same file twice under two
    identities; the current bytes win, and with no match the last registration
    does.
    """
    by_path: dict[str, list[SourceDocument]] = {}
    for src in sources:
        by_path.setdefault(str(Path(src.path).resolve()).lower(), []).append(src)
    kept: list[SourceDocument] = []
    for path, group in by_path.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        current = compute_content_hash(Path(path))
        match = next((s for s in group if s.content_hash == current), None)
        winner = match or max(group, key=lambda s: s.registered_at)
        log.warning(
            "%d records name %s — building the one matching its bytes (%s…)",
            len(group), Path(path).name, winner.content_hash[:10],
        )
        kept.append(winner)
    return kept


def append_to_inventory(
    new_sources: list[SourceDocument], part_dir: Path
) -> list[SourceDocument]:
    """Append new sources to an existing inventory, deduping by content_hash.

    Returns the merged inventory. Re-adding an existing source is a no-op
    (logged) so `dsa add-doc` is idempotent. The written file is the derived
    view; the next build migrates any entry the Library does not yet hold.
    """
    existing = load_inventory(part_dir)
    by_hash = {s.content_hash: s for s in existing}
    added = 0
    for src in new_sources:
        if src.content_hash in by_hash:
            log.info(
                "source already registered: %s (hash %s…)",
                Path(src.path).name, src.content_hash[:10],
            )
            continue
        by_hash[src.content_hash] = src
        added += 1
    merged = list(by_hash.values())
    if added:
        log.info("added %d new source(s) to inventory for %s", added, part_dir.name)
    save_inventory(merged, part_dir)
    return merged
