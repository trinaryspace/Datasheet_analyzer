"""Cross-part comparison — the part-selection question, answered in one call.

Phase 6, ticket 09. `build.py` derives a comparison from records several parts
already publish (ADR 0005: quoted cells, one documented pure function — the SI
delta — and the alias lexicon as the structural label), and `render.py` turns it
into the table a choice is made on. The lookups that feed it live in
`retrieve/compare.py`, where every other corpus lookup lives.
"""

from datasheet_analyzer.compare.build import (
    ALIGNED_ALIAS,
    ALIGNED_CARD,
    ALIGNED_IDENTITY,
    ALIGNED_PRINTED,
    DERIVATION_CELL,
    DERIVATION_CELL_SI,
    DERIVATION_DELTA,
    FLAG_ONLY_IN,
    KIND_CARD,
    KIND_NAME,
    KIND_SYMBOL,
    ROLE_ORDER,
    ComparePart,
    CompareRecord,
    SpecKeyFn,
    build_card_comparison,
    build_spec_comparison,
)
from datasheet_analyzer.compare.render import (
    BANNER_PREFIX,
    NOT_COMPARABLE_HEADING,
    banner,
    render_comparison,
)

__all__ = [
    "ALIGNED_ALIAS",
    "ALIGNED_CARD",
    "ALIGNED_IDENTITY",
    "ALIGNED_PRINTED",
    "BANNER_PREFIX",
    "DERIVATION_CELL",
    "DERIVATION_CELL_SI",
    "DERIVATION_DELTA",
    "FLAG_ONLY_IN",
    "KIND_CARD",
    "KIND_NAME",
    "KIND_SYMBOL",
    "NOT_COMPARABLE_HEADING",
    "ROLE_ORDER",
    "ComparePart",
    "CompareRecord",
    "SpecKeyFn",
    "banner",
    "build_card_comparison",
    "build_spec_comparison",
    "render_comparison",
]
