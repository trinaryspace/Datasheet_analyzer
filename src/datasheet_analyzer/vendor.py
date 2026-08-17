"""Vendor identity + backend routing — a thin, rule-free routing record.

The vendor is *never* a rulebook: a ``VendorProfile`` carries only an
identity detector (shared brand-mark lexicon against page-1 text and the
filename), a backend preference chain, and no behavior of its own. No
layout rule hangs off the vendor string — vendor N+1 is a data change
(profile entry), not a code change.

Detection runs at acquire time; the match (vendor, evidence) is pinned into
the inventory. A later run whose detection contradicts the pinned value
warns loudly instead of re-routing (``warn_vendor_drift``). ``--vendor`` on
``dsa build`` / ``add-doc`` is the explicit override. Unmatched documents
default to ``ti`` with empty evidence (the project default — reference
parts and unknown PDFs keep today's routing).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import DocType, SourceDocument

log = logging.getLogger(__name__)

DEFAULT_VENDOR = "ti"


@dataclass(frozen=True)
class VendorProfile:
    """One vendor's routing record: detector lexicon + backend preference."""

    name: str
    brand_marks: tuple[str, ...]  # case-insensitive substrings (page-1 text / filename)
    backend_chain: tuple[str, ...]  # datasheet backends, preference order
    companion_backend: str = "pdf_text"  # non-datasheets for every vendor
    #: Register maps are the one companion whose **tables are the product**
    #: (phase 6, ticket 05): a register summary read as paragraphs answers no
    #: bring-up question at all, so they route to the layout floor instead of
    #: the degraded paragraph backend. Errata and app notes keep `pdf_text` —
    #: their value is prose, and nothing downstream trusts a table from them.
    register_map_backend: str = "pdf_layout"


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
    # Reached via --vendor unknown (or legacy data); detection never emits it.
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
    """Brand-mark detection on page-1 text, then filename.

    Returns ``(vendor, evidence)``. Nothing matched -> ``(DEFAULT_VENDOR, "")``:
    unknown PDFs keep the project default routing, recorded honestly with
    empty evidence; a brand-less PDF that needs a different chain pins
    explicitly via ``--vendor`` (the LM741 gate fixture's decision).
    """
    from datasheet_analyzer.extract.pdf_structure import first_page_text

    text = ""
    try:
        text = first_page_text(path).lower()
    except Exception as exc:  # noqa: BLE001 — detection is best-effort
        log.warning("vendor detection failed for %s: %s", Path(path).name, exc)
    name = Path(path).name.lower()
    for profile in VENDOR_PROFILES.values():
        if profile.name == "unknown":
            continue
        for mark in profile.brand_marks:
            if mark in text:
                return profile.name, f'brand:"{mark}" (p.1)'
            if mark in name:
                return profile.name, f'brand:"{mark}" (filename)'
    return DEFAULT_VENDOR, ""


def select_backend(vendor_name: str, doc_type: DocType) -> str:
    """First *registered* backend in the profile's preference chain.

    Companions (errata, app notes) use the degraded ``pdf_text`` backend for
    every vendor. **Register maps are the exception** (phase 6, ticket 05):
    their register-summary and bit-field tables are the whole reason the
    document exists, and `pdf_text` carries no trusted tables, so they route
    to the vendor-neutral layout floor. That is a deliberate reversal of the
    caveat `README.md` and `AGENTS.md` used to carry, and it is what
    `PIPELINE_VERSION` 0.5.0 invalidates cached register-map extractions for.

    A datasheet whose chain names no registered backend raises
    ``BackendUnavailableError`` — honest failure over silent degradation. A
    register map whose backend is not registered falls back to the companion
    backend rather than failing the build: a paragraph-only register map is a
    degraded reading of a companion, not a part with no datasheet.
    """
    from datasheet_analyzer.extract import BackendUnavailableError, available_backends

    profile = get_profile(vendor_name)
    if doc_type == DocType.REGISTER_MAP:
        if profile.register_map_backend in set(available_backends()):
            return profile.register_map_backend
        log.warning(
            "backend %r is not registered — register map falls back to %r",
            profile.register_map_backend, profile.companion_backend,
        )
        return profile.companion_backend
    if doc_type != DocType.DATASHEET:
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
    or missing PDFs are skipped quietly.
    """
    for src in sources:
        if src.doc_type != DocType.DATASHEET or src.vendor_evidence.startswith("cli-override"):
            continue
        detected, evidence = detect_vendor(Path(src.path))  # best-effort internally
        if detected != src.vendor:
            pinned = f" ({src.vendor_evidence})" if src.vendor_evidence else ""
            found = f" ({evidence})" if evidence else ""
            log.warning(
                "vendor drift: %s is pinned as %r%s but content matches %r%s — "
                "re-run with --vendor to override",
                Path(src.path).name, src.vendor, pinned, detected, found,
            )
