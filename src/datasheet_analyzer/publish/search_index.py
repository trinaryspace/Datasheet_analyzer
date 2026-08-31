"""`search_index.json` — a document's inverted index, built at publish.

Precomputing beats shelling out to ripgrep at query time: it is deterministic,
dependency-free, and usable inside the MCP server without spawning a process.
The index is built from exactly the markdown that lands on disk, so what is
searchable and what is readable can never diverge.

Determinism is a product requirement, not a nicety: two builds of identical
input must produce byte-identical files, or every downstream cache key built
on them lies. Every mapping is emitted in sorted key order and serialized with
`sort_keys=True`, so nothing depends on dict insertion order or on the
filesystem.

The index carries `schema_version` (`SEARCH_SCHEMA_VERSION`) and participates
in the publish cache key: `search_index_current()` is what the batch skip gate
asks before it may serve an already-built corpus, so a corpus without a
current-schema index rebuilds instead of silently answering nothing.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from datasheet_analyzer.config import SEARCH_SCHEMA_VERSION
from datasheet_analyzer.models import SearchIndex, SearchSection
from datasheet_analyzer.structure.corpus import SectionPlan
from datasheet_analyzer.structure.search import body_text, tokenize

log = logging.getLogger(__name__)

INDEX_FILENAME = "search_index.json"


def build_search_index(plans: list[SectionPlan], *, part_number: str, doc_hash: str) -> SearchIndex:
    """Index one document's rendered sections.

    Sections keep plan (reading) order; every token map is sorted, so the
    result serializes identically on every machine.
    """
    sections: list[SearchSection] = []
    df: Counter[str] = Counter()
    for plan in plans:
        counts = Counter(tokenize(body_text(plan.markdown)))
        sections.append(
            SearchSection(
                file=plan.file,
                length=sum(counts.values()),
                tokens=dict(sorted(counts.items())),
            )
        )
        df.update(counts.keys())
    total = sum(s.length for s in sections)
    return SearchIndex(
        schema_version=SEARCH_SCHEMA_VERSION,
        part_number=part_number,
        doc_hash=doc_hash,
        sections=sections,
        df=dict(sorted(df.items())),
        avgdl=(total / len(sections)) if sections else 0.0,
    )


def dump_json(index: SearchIndex) -> str:
    """Serialize deterministically — sorted keys, verbatim (non-escaped) glyphs.

    Written compactly rather than indented, unlike its human-facing siblings
    `specs.json` / `plots.json`: this file is one entry per *token*, so
    pretty-printing would roughly triple a machine artifact nobody reads
    top-to-bottom, and the index must not dominate the corpus it indexes. It
    stays greppable — keys are sorted and every token is a quoted literal.

    `ensure_ascii=False` matters for the same reason: a `Ω`/`θ`/`°` escaped
    into `\\u2126` would round-trip fine but could not be grepped with the
    glyph the datasheet prints.
    """
    return json.dumps(
        index.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )


def write_search_index(doc_dir: Path, index: SearchIndex) -> int:
    """Write `search_index.json` into a document directory; return its bytes."""
    text = dump_json(index)
    (doc_dir / INDEX_FILENAME).write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def search_index_current(doc_dir: Path) -> bool:
    """Whether `doc_dir` holds a search index of the current schema.

    Anything unverifiable — missing, unreadable, older schema — reads as not
    current, which is what makes this safe to gate a rebuild on.
    """
    try:
        data = json.loads((doc_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("schema_version") == SEARCH_SCHEMA_VERSION
