"""Part families — a series answered once instead of per member.

Phase 7, ticket 07. `registry.py` owns membership (declared in
`registry/families.yaml`, proposed by `suggest.py`, never assumed), `build.py`
derives the index from records the members already publish (ADR 0005: quoted
cells, one pure function — the SI delta — and the printed row as the structural
label), and `render.py` writes `families/<NAME>/FAMILY_INDEX.md` under a hard
token budget. The corpus walk that feeds it lives in `retrieve/family.py`, where
every other corpus lookup lives.
"""

from datasheet_analyzer.families.registry import (
    CANDIDATES_FILENAME,
    FAMILIES_FILENAME,
    FAMILIES_SCHEMA_VERSION,
    FamilyEntry,
    FamilyMiss,
    FamilyRegistry,
    FamilyUnconfirmed,
    candidates_path,
    candidates_yaml,
    families_path,
    families_yaml,
    is_candidate_path,
    load_candidates,
    load_families,
    miss_message,
    resolve,
    save_candidates,
    save_families,
    unconfirmed_message,
)
from datasheet_analyzer.families.suggest import (
    MIN_SECTION_OVERLAP,
    MIN_STEM,
    PROPOSED_BY,
    CandidatePart,
    overlap,
    section_signature,
    stem,
    suggest_families,
)

__all__ = [
    "CANDIDATES_FILENAME",
    "FAMILIES_FILENAME",
    "FAMILIES_SCHEMA_VERSION",
    "MIN_SECTION_OVERLAP",
    "MIN_STEM",
    "PROPOSED_BY",
    "CandidatePart",
    "FamilyEntry",
    "FamilyMiss",
    "FamilyRegistry",
    "FamilyUnconfirmed",
    "candidates_path",
    "candidates_yaml",
    "families_path",
    "families_yaml",
    "is_candidate_path",
    "load_candidates",
    "load_families",
    "miss_message",
    "overlap",
    "resolve",
    "save_candidates",
    "save_families",
    "section_signature",
    "stem",
    "suggest_families",
    "unconfirmed_message",
]
