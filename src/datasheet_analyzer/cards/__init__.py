"""Design cards — task-shaped views over records the corpus already publishes.

Phase 6, ticket 07. `build.py` derives them (ADR 0005: quoted cells, documented
pure functions, lexicon labels — no model call anywhere in the path),
`lexicon.py` holds the selectors as data (`registry/cards.yaml`) and `render.py`
turns one into the markdown a reader sees.
"""

from datasheet_analyzer.cards.build import (
    DERIVATION_CELL,
    DERIVATION_CELL_SI,
    DERIVATION_MARGIN,
    DERIVATION_PIN_COUNT,
    DERIVATION_REDUCE_MAX,
    FLAG_OVER_ABS_MAX,
    FLAG_ZERO_MARGIN,
    ROLE_ABS_MAX,
    ROLE_MARGIN,
    ROLE_RECOMMENDED_MAX,
    CardDoc,
    build_card,
    build_cards,
    card_docs,
)
from datasheet_analyzer.cards.lexicon import (
    CardGroup,
    CardLexicon,
    CardSpec,
    LimitsJoin,
    clear_card_lexicon_cache,
    load_card_lexicon,
)
from datasheet_analyzer.cards.render import (
    BANNER_PREFIX,
    banner,
    render_card,
    row_citations,
)

__all__ = [
    "BANNER_PREFIX",
    "DERIVATION_CELL",
    "DERIVATION_CELL_SI",
    "DERIVATION_MARGIN",
    "DERIVATION_PIN_COUNT",
    "DERIVATION_REDUCE_MAX",
    "FLAG_OVER_ABS_MAX",
    "FLAG_ZERO_MARGIN",
    "ROLE_ABS_MAX",
    "ROLE_MARGIN",
    "ROLE_RECOMMENDED_MAX",
    "CardDoc",
    "CardGroup",
    "CardLexicon",
    "CardSpec",
    "LimitsJoin",
    "banner",
    "build_card",
    "build_cards",
    "card_docs",
    "clear_card_lexicon_cache",
    "load_card_lexicon",
    "render_card",
    "row_citations",
]
