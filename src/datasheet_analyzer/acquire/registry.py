"""`registry/datasheets.yaml` — the curated document registry.

**Data, not a scraper.** Phase 7, ticket 01. The registry is the checked-in
answer to "where does this part's PDF come from?", and it is deliberately the
*only* answer this repo has: there is no portal scraping and no search-API
resolution (the scope decision recorded in `.scratch/reach-and-trust/SPEC.md`).
A part the registry does not know is an error naming `--url`, never a guessed
URL — a plausible vendor URL that 404s, or worse resolves to a different
document, puts the wrong datasheet in front of a hardware designer, and the
citation would look exactly as trustworthy as a correct one.

Four rules here are load-bearing.

- **A URL is either recorded or absent, and an absent one says why.** `url`
  is `None` with a `url_reason` when nobody has supplied one; `dsa fetch` then
  tells the caller to pass `--url`, which is the designed growth path rather
  than a gap. Nothing in this module composes a URL out of a part number.
- **A URL that was never fetched is `url_verified: false`.** A seed entry's
  URL may be *derived* — the TI literature pattern already encoded in this
  repo, applied to a literature number parsed out of a PDF that is physically
  here — and a derived URL is a hypothesis until a live fetch confirms it. The
  rule that produced it is recorded in `url_derivation`, so the hypothesis is
  readable. `dsa fetch` flips the flag to `true` only after the bytes arrive.
- **A sha256 records where it came from.** `sha256_origin` is
  `local_file:<path>` for a hash computed from a document committed in this
  repo, and `fetch:<url>` for one recorded off the wire. The distinction is
  what lets a mismatch warning say something true: a hash taken from a local
  copy disagreeing with the upstream bytes is a different finding from an
  upstream document that changed under a hash we recorded from it.
- **`retrieved_at` is a fact or it is null.** It is stamped by a fetch that
  actually happened and is never back-filled with a plausible date.

The vendor field is informational — it records what `vendor.detect_vendor`
read off the document, so a fleet listing can group by vendor. It does **not**
pin routing: routing is pinned at acquire time from the document itself (or an
explicit `--vendor`), exactly as it was before this file existed.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from datasheet_analyzer.models import DocType

#: Fields the file writes as `null` to mean "not known" but the models hold as
#: `""`. YAML has one absence and pydantic has two, and reading `null` back as
#: a validation error would make the file this module *wrote* unreadable.
_NULL_AS_EMPTY = (
    "url_derivation",
    "url_reason",
    "revision",
    "sha256",
    "sha256_origin",
    "filename",
)

log = logging.getLogger(__name__)

REGISTRY_FILENAME = "datasheets.yaml"
#: The packaged registry directory — the same one the alias, card, pin-type and
#: device-table lexicons live in. `Settings.registry_dir` overrides it.
PACKAGED_REGISTRY_DIR = Path(__file__).resolve().parent.parent / "registry"

#: "1": phase 7, ticket 01 — the first shape of this file.
REGISTRY_SCHEMA_VERSION = "1"

#: The named rule that derives a TI literature URL from a literature number.
#: The pattern itself is the one this repo already carries; the literature
#: number must have been parsed out of a document, never invented.
TI_LIT_DERIVATION = "ti_lit_ds"

#: Prepended to every render so the checked-in file explains itself to whoever
#: opens it, including the one measured behaviour that makes a hash mismatch
#: ambiguous. YAML comments do not survive a load, which is exactly why this is
#: a constant here rather than something a maintainer types into the file.
FILE_HEADER = """\
# Curated document registry (phase 7, ticket 01). GENERATED — edit via
# `dsa fetch --url … --part X`, or re-run `scripts/seed_datasheet_registry.py`.
#
#   url             where the document comes from. `null` means nobody has
#                   supplied one; `url_reason` says so. Never guessed.
#   url_verified    true only once bytes have actually arrived from that URL.
#                   A `url_derivation` entry is a *derived* hypothesis until then.
#   sha256          the hash of real bytes. `sha256_origin` says whose:
#                   `local_file:<repo path>` for a document committed here,
#                   `fetch:<url>` for one recorded off the wire.
#   retrieved_at    stamped by a fetch that happened. `null` otherwise.
#
# A `local_file:` hash will not always survive a fresh download of the *same*
# revision — a vendor that regenerates a datasheet's package-materials addendum
# on every download changes the bytes without changing the revision identifier.
# `dsa fetch` therefore decides a mismatch's cause from the parsed revision, not
# from the hash, and says so.
"""


class RegistryDocument(BaseModel):
    """One document of one part as the registry records it.

    Every field is either a recorded fact or explicitly absent. Nothing here
    is interpolated: an unknown revision is `""`, an unknown hash is `""`, an
    unknown URL is `None` *with* a reason, and a document that was never
    fetched has `retrieved_at: None`.
    """

    doc_type: DocType = DocType.DATASHEET
    #: The URL to fetch from. `None` means nobody has supplied one — see
    #: `url_reason`. It is never composed from the part number.
    url: str | None = None
    #: True only once bytes have actually arrived from `url`. A *derived* URL
    #: (see `url_derivation`) ships false and stays false until then.
    url_verified: bool = False
    #: The named rule that produced a derived URL, e.g. `ti_lit_ds(SBASA41E)`.
    #: Empty when the URL was supplied by hand or by `--url`.
    url_derivation: str = ""
    #: Why there is no URL, when there is none. Read back verbatim by
    #: `dsa fetch` so the caller learns what is missing rather than "not found".
    url_reason: str = ""
    #: The document revision as the shared lexicon reads it (`SBASA41E`,
    #: `Rev. I`). `""` when unknown.
    revision: str = ""
    #: sha256 of the document bytes. `""` when unknown — a fetch then records
    #: one instead of verifying against nothing.
    sha256: str = ""
    #: Where `sha256` came from: `local_file:<repo path>` or `fetch:<url>`.
    sha256_origin: str = ""
    #: When the bytes were last fetched. `None` until a fetch happens.
    retrieved_at: datetime | None = None
    #: Destination basename under `parts/<PART>/documents/`. `""` lets the
    #: fetcher derive one from the URL.
    filename: str = ""

    @model_validator(mode="before")
    @classmethod
    def _null_reads_as_empty(cls, data):
        if isinstance(data, dict):
            data = {
                k: ("" if v is None and k in _NULL_AS_EMPTY else v)
                for k, v in data.items()
            }
        return data


class RegistryEntry(BaseModel):
    """One part: its primary document plus any companions.

    `part_number` is the key the file stores this entry under; `load_registry`
    fills it in from the mapping, so the file never carries the name twice and
    the two can never disagree.
    """

    part_number: str = ""
    #: Informational only (see the module header) — never a routing pin.
    vendor: str = ""
    document: RegistryDocument = Field(default_factory=RegistryDocument)
    companions: list[RegistryDocument] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _null_vendor_reads_as_empty(cls, data):
        if isinstance(data, dict) and data.get("vendor", "") is None:
            data = {**data, "vendor": ""}
        return data

    @property
    def documents(self) -> list[RegistryDocument]:
        """Primary document first, then companions, in recorded order."""
        return [self.document, *self.companions]


class DocumentRegistry(BaseModel):
    """The whole file: `schema_version` plus one entry per part."""

    schema_version: str = REGISTRY_SCHEMA_VERSION
    parts: dict[str, RegistryEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _entries_know_their_own_key(self) -> DocumentRegistry:
        """The mapping key *is* the part number — fill it in on load.

        Storing it twice would let a hand-edited file disagree with itself, and
        `dsa fetch` would then register a document under one name and record it
        under another.
        """
        for part_number, entry in self.parts.items():
            entry.part_number = part_number
        return self

    def get(self, part_number: str) -> RegistryEntry | None:
        return self.parts.get(part_number)

    def put(self, entry: RegistryEntry) -> None:
        self.parts[entry.part_number] = entry


class RegistryMiss(Exception):
    """A part (or a document of one) the registry cannot resolve.

    The message always names `--url`, because that flag *is* the fix and a
    "not found" that does not say how to grow the registry turns a two-second
    edit into a code-reading exercise.
    """


def registry_path(registry_dir: Path | None = None) -> Path:
    """`<registry_dir>/datasheets.yaml`, defaulting to the packaged copy."""
    return Path(registry_dir or PACKAGED_REGISTRY_DIR) / REGISTRY_FILENAME


def load_registry(path: Path | None = None) -> DocumentRegistry:
    """Read the registry; a missing file is an *empty* registry, not an error.

    `dsa fetch --url` must work on a machine whose registry file has not been
    created yet — that is the growth path — so absence reads as "knows
    nothing", which is exactly what a registry miss already says.
    """
    dest = Path(path) if path is not None else registry_path()
    if not dest.exists():
        return DocumentRegistry()
    data = yaml.safe_load(dest.read_text(encoding="utf-8")) or {}
    return DocumentRegistry.model_validate(data)


def _document_yaml(doc: RegistryDocument) -> dict:
    """One document as the file spells it.

    Fields that carry a *decision* are always emitted (`url`, `revision`,
    `sha256`, `retrieved_at`) — including as `null` — so a reader can tell
    "not known" from "not applicable". Prose fields are emitted only when they
    say something.
    """
    out: dict = {"doc_type": doc.doc_type.value, "url": doc.url}
    if doc.url is not None:
        out["url_verified"] = doc.url_verified
    if doc.url_derivation:
        out["url_derivation"] = doc.url_derivation
    if doc.url_reason:
        out["url_reason"] = doc.url_reason
    out["revision"] = doc.revision or None
    out["sha256"] = doc.sha256 or None
    if doc.sha256_origin:
        out["sha256_origin"] = doc.sha256_origin
    out["retrieved_at"] = (
        doc.retrieved_at.isoformat() if doc.retrieved_at is not None else None
    )
    if doc.filename:
        out["filename"] = doc.filename
    return out


def registry_yaml(registry: DocumentRegistry) -> str:
    """Serialize deterministically: parts sorted, block style, stable keys.

    Determinism matters because this file is checked in — a `dsa fetch --url`
    on one machine and the same one on another must produce the same diff.
    """
    payload = {
        "schema_version": registry.schema_version,
        "parts": {
            part: {
                "vendor": entry.vendor or None,
                "document": _document_yaml(entry.document),
                **(
                    {"companions": [_document_yaml(c) for c in entry.companions]}
                    if entry.companions
                    else {}
                ),
            }
            for part, entry in sorted(registry.parts.items())
        },
    }
    return FILE_HEADER + yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, width=100
    )


def save_registry(registry: DocumentRegistry, path: Path | None = None) -> Path:
    dest = Path(path) if path is not None else registry_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(registry_yaml(registry), encoding="utf-8")
    return dest


def miss_message(part_number: str, *, doc_type: DocType | None = None) -> str:
    """What a registry miss says. It names `--url`, and it never guesses."""
    kind = f" {doc_type.value}" if doc_type is not None else ""
    return (
        f"no registry entry for{kind} {part_number!r} — this tool never guesses a "
        f"datasheet URL and never falls back to a search. Supply the URL once and "
        f"it is recorded for next time:\n"
        f"  dsa fetch --url <URL> --part {part_number}"
        + (f" --doc-type {doc_type.value}" if doc_type is not None else "")
    )


def no_url_message(part_number: str, doc: RegistryDocument) -> str:
    """What an entry with no URL says — the reason it records, then the fix."""
    reason = doc.url_reason or "no URL has been supplied"
    return (
        f"registry entry for {part_number!r} ({doc.doc_type.value}) records no URL "
        f"— {reason}. Supply it and it is recorded for next time:\n"
        f"  dsa fetch --url <URL> --part {part_number} --doc-type {doc.doc_type.value}"
    )


def resolve(
    registry: DocumentRegistry,
    part_number: str,
    *,
    doc_type: DocType | None = None,
) -> list[RegistryDocument]:
    """The documents to fetch for `part_number`.

    `doc_type=None` means the whole entry (primary + companions), which is what
    `dsa fetch PART` fetches. A named type narrows to the documents of that
    type. A part the registry does not know raises `RegistryMiss` with the
    message that names `--url`.
    """
    entry = registry.get(part_number)
    if entry is None:
        raise RegistryMiss(miss_message(part_number, doc_type=doc_type))
    docs = entry.documents
    if doc_type is not None:
        docs = [d for d in docs if d.doc_type == doc_type]
        if not docs:
            raise RegistryMiss(miss_message(part_number, doc_type=doc_type))
    return docs


def ti_lit_url(literature_number: str) -> str:
    """The TI literature URL for a literature number, per the pattern this
    repo already carries (`https://www.ti.com/lit/ds/<lit>/<lit>.pdf`).

    Derivation, not knowledge: the caller must have *parsed* the literature
    number out of a document, and the resulting URL is recorded
    `url_verified: false` until a live fetch confirms it.
    """
    lit = literature_number.strip().lower()
    if not lit:
        raise ValueError("ti_lit_url needs a literature number")
    return f"https://www.ti.com/lit/ds/{lit}/{lit}.pdf"
