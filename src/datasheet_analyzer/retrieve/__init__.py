"""Retrieval core: the single implementation of every corpus lookup.

Front ends (`cli.py`, `query.py`, and later the MCP server) are adapters that
*format* what this package returns. No retrieval logic — no `rglob`, no
`specs.json` parsing, no hand-built `p.N` citation string — may live outside
here; that is the seam this package exists to enforce.

The one thing this package does render is the answer pack (`pack.py`): a token
budget cannot be enforced on text the core did not produce, so the pack renders
itself and reports what it cost.
"""

from datasheet_analyzer.retrieve.index import (
    INDEX_FILENAME,
    CorpusIndex,
    IndexedDoc,
    clear_index_cache,
    discover_parts,
)
from datasheet_analyzer.retrieve.project import ProjectRetriever
from datasheet_analyzer.retrieve.results import (
    CONFIDENCE_UNKNOWN,
    Citation,
    PlotHit,
    SearchHit,
    SectionHit,
    SpecHit,
)
from datasheet_analyzer.retrieve.retriever import PLOT_VOCABULARY, Retriever
from datasheet_analyzer.retrieve.search import ScoredSection, score_sections

# Imported after `retriever`: `pack` composes `Retriever`, which reaches back
# for `build_pack` only at call time.
from datasheet_analyzer.retrieve.pack import (  # isort: skip
    ANSWER_PACK_SCHEMA,
    ROUTE_NONE,
    ROUTE_PIN,
    ROUTE_PLOT,
    ROUTE_REGISTER,
    ROUTE_SEARCH,
    ROUTE_SPEC,
    ROUTE_UNAVAILABLE,
    ROUTES,
    AnswerPack,
    PackExcerpt,
    PackLine,
    build_pack,
    build_project_pack,
    validate_pack,
)

__all__ = [
    "ANSWER_PACK_SCHEMA",
    "CONFIDENCE_UNKNOWN",
    "INDEX_FILENAME",
    "PLOT_VOCABULARY",
    "ROUTES",
    "ROUTE_NONE",
    "ROUTE_PIN",
    "ROUTE_PLOT",
    "ROUTE_REGISTER",
    "ROUTE_SEARCH",
    "ROUTE_SPEC",
    "ROUTE_UNAVAILABLE",
    "AnswerPack",
    "Citation",
    "CorpusIndex",
    "IndexedDoc",
    "PackExcerpt",
    "PackLine",
    "PlotHit",
    "ProjectRetriever",
    "Retriever",
    "ScoredSection",
    "SearchHit",
    "SectionHit",
    "SpecHit",
    "build_pack",
    "build_project_pack",
    "clear_index_cache",
    "discover_parts",
    "score_sections",
    "validate_pack",
]
