"""Vendor identity + backend routing — a thin, rule-free routing record.

Routing has two axes and neither is a vendor rulebook: the *vendor* chooses
the datasheet backend chain, and the *document type* chooses whether a
companion is read as prose (``pdf_text``) or as tables (``pdf_layout``,
``TABLE_COMPANION_TYPES``). Adding a table-shaped companion type is an entry
in that set; adding a vendor is an entry in ``VENDOR_PROFILES``.


The vendor is *never* a rulebook: a ``VendorProfile`` carries only an
identity detector (shared brand-mark lexicon against page-1 text, the
document's metadata and the filename), a backend preference chain, and no behavior of its own. No
layout rule hangs off the vendor string — vendor N+1 is a data change
(profile entry), not a code change.

Detection runs at acquire time; the match (vendor, evidence) is pinned into
the inventory. A later run whose detection contradicts the pinned value
warns loudly instead of re-routing (``warn_vendor_drift``). ``--vendor`` on
``dsa build`` / ``add-doc`` is the explicit override.

**A vendor is pinned on evidence or not at all** (ADR 0002). Detection reads
three sources in strength order — page-1 text, the document's own metadata,
the filename — and a document that matches none of them is pinned
``unknown`` with empty evidence, which routes to the vendor-neutral layout
floor. It used to default to ``ti``, which is a silent runtime guess: the
four Mini-Circuits parts in ``RadarDatasheets/`` were pinned ``ti`` on no
evidence at all and routed to ``ti_html``, which 404s against ti.com.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import DocType, SourceDocument

log = logging.getLogger(__name__)

#: A document that matches no brand mark. Not a default vendor — an honest
#: "not established", which routes to the vendor-neutral layout floor.
UNKNOWN_VENDOR = "unknown"


@dataclass(frozen=True)
class VendorProfile:
    """One vendor's routing record: detector lexicon + backend preference."""

    name: str
    brand_marks: tuple[str, ...]  # case-insensitive substrings (p.1 text / metadata / filename)
    backend_chain: tuple[str, ...]  # datasheet backends, preference order
    companion_backend: str = "pdf_text"  # prose companions, every vendor
    # Companions whose content *is* tables (`TABLE_COMPANION_TYPES`). Still
    # not the datasheet chain: that chain starts at a vendor's HTML mirror,
    # which publishes datasheets and not programmer's guides, so a register
    # map routed through it would fetch the wrong document or nothing at all.
    table_companion_backend: str = "pdf_layout"


#: Companion document types whose *tables* are the document (phase 6, ticket
#: 05). A register map read as paragraphs is a document with no answers in it:
#: every bring-up question — what is at 0x1A04, what does R5 reset to — is a
#: table lookup. These route to the layout backend for every vendor, which is
#: a doc-type fact rather than a vendor rule, so it lives beside the profiles
#: instead of inside one. Errata and app notes are prose and keep `pdf_text`.
TABLE_COMPANION_TYPES: frozenset[DocType] = frozenset({DocType.REGISTER_MAP})


VENDOR_PROFILES: dict[str, VendorProfile] = {
    "ti": VendorProfile(
        name="ti",
        brand_marks=("texas instruments",),
        backend_chain=("ti_html", "pdf_layout"),
    ),
    "adi": VendorProfile(
        name="adi",
        brand_marks=("analog devices",),
        backend_chain=("pdf_layout",),
    ),
    "qorvo": VendorProfile(
        name="qorvo",
        brand_marks=("qorvo",),
        backend_chain=("pdf_layout",),
    ),
    # What detection emits when no brand mark was found anywhere, and what
    # --vendor unknown pins explicitly. Its empty `brand_marks` is why the
    # detection loop skips it: "unknown" is never *matched*, only defaulted to.
    "unknown": VendorProfile(
        name="unknown",
        brand_marks=(),
        backend_chain=("pdf_layout",),
    ),
}


def is_known_vendor(name: str) -> bool:
    return name in VENDOR_PROFILES


def override_evidence(vendor: str) -> str:
    """vendor_evidence for an explicit ``--vendor`` override."""
    return f"cli-override: --vendor {vendor}"


def unknown_vendor_message(name: str) -> str:
    return f"unknown vendor {name!r} (known: {', '.join(sorted(VENDOR_PROFILES))})"


def get_profile(name: str) -> VendorProfile:
    if name not in VENDOR_PROFILES:
        raise KeyError(unknown_vendor_message(name))
    return VENDOR_PROFILES[name]


def detect_vendor(path: Path) -> tuple[str, str]:
    """Brand-mark detection: page-1 text, then document metadata, then filename.

    Returns ``(vendor, evidence)``. The three sources are tried in that order
    — strongest first — and every profile is offered each source before the
    next one is read, so what the document *prints* beats what its metadata
    or its filename claims.

    Nothing matched -> ``(UNKNOWN_VENDOR, "")``. That is the whole point: a
    vendor is pinned only where a brand mark was actually found, and the
    absence of one is recorded as an absence rather than filled in with the
    project's most common vendor. ``unknown`` routes to ``pdf_layout``, the
    vendor-neutral floor, which is the correct reading of a document whose
    publisher we cannot name. A brand-less PDF that needs a *different* chain
    still pins explicitly via ``--vendor``.
    """
    from datasheet_analyzer.extract.pdf_structure import (
        document_metadata_text,
        first_page_text,
    )

    page_one = ""
    try:
        page_one = first_page_text(path).lower()
    except Exception as exc:  # noqa: BLE001 — detection is best-effort
        log.warning("vendor detection failed for %s: %s", Path(path).name, exc)
    sources = (
        ("p.1", page_one),
        ("metadata", document_metadata_text(path).lower()),
        ("filename", Path(path).name.lower()),
    )
    for label, text in sources:
        if not text:
            continue
        for profile in VENDOR_PROFILES.values():
            if profile.name == UNKNOWN_VENDOR:
                continue
            for mark in profile.brand_marks:
                if mark in text:
                    return profile.name, f'brand:"{mark}" ({label})'
    return UNKNOWN_VENDOR, ""


def select_backend(vendor_name: str, doc_type: DocType) -> str:
    """First *registered* backend in the profile's preference chain.

    Prose companions (errata, app notes) use the degraded ``pdf_text``
    backend for every vendor. **Table companions — register maps — use
    ``pdf_layout``** (phase 6, ticket 05): they were paragraphs-only until
    that change, which made every bring-up question unanswerable by
    construction. The change invalidates cached ``(content_hash, backend)``
    extractions for those documents, which is what the ``PIPELINE_VERSION``
    bump to 0.5.0 exists for.

    A datasheet whose chain names no registered backend raises
    ``BackendUnavailableError`` — honest failure over silent degradation. A
    companion falls back to ``pdf_text`` when its preferred backend is not
    registered, because a degraded reading of a companion is still better
    than failing a build over one.
    """
    from datasheet_analyzer.extract import BackendUnavailableError, available_backends

    profile = get_profile(vendor_name)
    if doc_type != DocType.DATASHEET:
        if doc_type not in TABLE_COMPANION_TYPES:
            return profile.companion_backend
        preferred = profile.table_companion_backend
        if preferred in set(available_backends()):
            return preferred
        log.warning(
            "backend %r is not registered — reading %s documents as paragraphs (%s)",
            preferred,
            doc_type.value,
            profile.companion_backend,
        )
        return profile.companion_backend
    registered = set(available_backends())
    for name in profile.backend_chain:
        if name in registered:
            return name
    raise BackendUnavailableError(
        f"vendor {vendor_name!r} prefers backend(s) {list(profile.backend_chain)!r}, "
        f"none registered (registered: {sorted(registered)})"
    )


def warn_vendor_drift(sources: list[SourceDocument]) -> None:
    """Loud warning when re-detection contradicts a pinned vendor.

    Runs on datasheets only (their vendor drives backend routing). Explicit
    overrides never warn — they are deliberate contradictions. Unreadable
    or missing PDFs are skipped quietly, and so is a document detection can
    find **no** brand mark in: drift is one brand contradicting another, and
    an absence of evidence contradicts nothing. (That distinction only became
    reachable when detection stopped answering the evidence-free case with
    ``ti`` — before, a missing file "matched" the project default.)
    """
    for src in sources:
        if src.doc_type != DocType.DATASHEET or src.vendor_evidence.startswith("cli-override"):
            continue
        detected, evidence = detect_vendor(Path(src.path))  # best-effort internally
        if detected == UNKNOWN_VENDOR:
            continue
        if detected != src.vendor:
            pinned = f" ({src.vendor_evidence})" if src.vendor_evidence else ""
            found = f" ({evidence})" if evidence else ""
            log.warning(
                "vendor drift: %s is pinned as %r%s but content matches %r%s — "
                "re-run with --vendor to override",
                Path(src.path).name,
                src.vendor,
                pinned,
                detected,
                found,
            )
