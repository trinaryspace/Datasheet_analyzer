"""Retrieval core: the single implementation of every corpus lookup.

Front ends (`cli.py`, `query.py`, and later the MCP server) are adapters that
*format* what this package returns. No retrieval logic — no `rglob`, no
`specs.json` parsing, no hand-built `p.N` citation string — may live outside
here; that is the seam this package exists to enforce.
"""

from datasheet_analyzer.retrieve.index import CorpusIndex, IndexedDoc, clear_index_cache
from datasheet_analyzer.retrieve.results import (
    CONFIDENCE_UNKNOWN,
    Citation,
    PlotHit,
    SectionHit,
    SpecHit,
)
from datasheet_analyzer.retrieve.retriever import Retriever

__all__ = [
    "CONFIDENCE_UNKNOWN",
    "Citation",
    "CorpusIndex",
    "IndexedDoc",
    "PlotHit",
    "Retriever",
    "SectionHit",
    "SpecHit",
    "clear_index_cache",
]
