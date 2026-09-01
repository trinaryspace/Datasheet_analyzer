"""Errata cross-linking (phase 7, ticket 04).

An errata document joins a part's corpus as a `pdf_text` document; this package
is what connects each of its items to the section, spec row, pin or register it
invalidates, so "any known issues with this part?" has an answer with a page
number on it.

- `lexicon` — the words an errata document uses, as checked-in data.
- `items` — segmenting a document into items; the floor rule loses nothing.
- `link` — the deterministic matching rules, and reading the links back.
- `render` — `ERRATA.md`, the section banner, and the answer-pack warning.

The invariant that governs all four: an item the matcher could not place is
**published**, under `render.UNLINKED_HEADING`. Losing an erratum is the worst
failure available here, so nothing in this package filters items — only the
`links` / `unlinked` split, whose sum is asserted, decides where one is printed.
"""

from datasheet_analyzer.errata.items import build_items, is_errata
from datasheet_analyzer.errata.lexicon import (
    RULES,
    ErrataLexicon,
    clear_errata_lexicon_cache,
    load_errata_lexicon,
)
from datasheet_analyzer.errata.link import (
    SectionBanner,
    TargetDoc,
    build_errata_links,
    links_by_target,
    sections_to_banner,
)
from datasheet_analyzer.errata.render import (
    ERRATA_LINKS_FILENAME,
    ERRATA_MARKDOWN_FILENAME,
    UNLINKED_HEADING,
    insert_banner,
    pack_warning,
    render_errata,
    section_banner,
)

__all__ = [
    "ERRATA_LINKS_FILENAME",
    "ERRATA_MARKDOWN_FILENAME",
    "RULES",
    "UNLINKED_HEADING",
    "ErrataLexicon",
    "SectionBanner",
    "TargetDoc",
    "build_errata_links",
    "build_items",
    "clear_errata_lexicon_cache",
    "insert_banner",
    "is_errata",
    "links_by_target",
    "load_errata_lexicon",
    "pack_warning",
    "render_errata",
    "section_banner",
    "sections_to_banner",
]
