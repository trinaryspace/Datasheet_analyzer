"""Revision diff — what changed between two revisions of one part.

Phase 7, ticket 03. `build.py` derives the diff from records the two revisions
already publish (ADR 0005: quoted cells, one documented pure function — the SI
delta — and the alias lexicon as the structural label), and `render.py` turns it
into `REVISION_DIFF.md`, the review a designer reads instead of re-reading a
datasheet. The lookups that feed it live in `retrieve/revdiff.py`, where every
other corpus lookup lives.
"""

from datasheet_analyzer.revdiff.build import (
    ALIGNED_ALIAS,
    ALIGNED_FIELD,
    ALIGNED_PIN,
    ALIGNED_PRINTED,
    ALIGNED_REGISTER,
    ALIGNED_SECTION,
    ALIGNED_SECTION_TITLE,
    CHANGE_ADDED,
    CHANGE_CHANGED,
    CHANGE_PAGE_SHIFTED,
    CHANGE_REMOVED,
    CHANGE_RENAMED,
    CHANGE_RESET,
    CHANGE_RETITLED,
    DERIVATION_CELL,
    DERIVATION_CELL_SI,
    DERIVATION_DELTA,
    DERIVATION_PIN_TYPE,
    FLAG_REVIEW,
    KIND_FIELD,
    KIND_PIN,
    KIND_REGISTER,
    KIND_SECTION,
    KIND_SPEC,
    ROLE_ORDER,
    RevisionSide,
    build_revision_diff,
)
from datasheet_analyzer.revdiff.render import (
    BANNER_PREFIX,
    NOT_COMPARABLE_HEADING,
    REVIEW_HEADING,
    REVISION_DIFF_FILENAME,
    banner,
    render_revision_diff,
)

__all__ = [
    "ALIGNED_ALIAS",
    "ALIGNED_FIELD",
    "ALIGNED_PIN",
    "ALIGNED_PRINTED",
    "ALIGNED_REGISTER",
    "ALIGNED_SECTION",
    "ALIGNED_SECTION_TITLE",
    "BANNER_PREFIX",
    "CHANGE_ADDED",
    "CHANGE_CHANGED",
    "CHANGE_PAGE_SHIFTED",
    "CHANGE_REMOVED",
    "CHANGE_RENAMED",
    "CHANGE_RESET",
    "CHANGE_RETITLED",
    "DERIVATION_CELL",
    "DERIVATION_CELL_SI",
    "DERIVATION_DELTA",
    "DERIVATION_PIN_TYPE",
    "FLAG_REVIEW",
    "KIND_FIELD",
    "KIND_PIN",
    "KIND_REGISTER",
    "KIND_SECTION",
    "KIND_SPEC",
    "NOT_COMPARABLE_HEADING",
    "REVIEW_HEADING",
    "REVISION_DIFF_FILENAME",
    "ROLE_ORDER",
    "RevisionSide",
    "banner",
    "build_revision_diff",
    "render_revision_diff",
]
