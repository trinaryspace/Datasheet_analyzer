"""Segmenting an errata document into items — the unit an erratum is.

An errata document reaches the corpus through the `pdf_text` backend, which is
honestly degraded: it publishes one paragraph per printed **line** and no
tables. That is enough, because an item's boundary is printed as a heading
(`Advisory 3`), not as a table row — so segmentation is a rule over lines, and
the words it keys on are data (`registry/errata.yaml`).

Three rules, tried in order, and the last one cannot fail:

1. **marker** — a line opening with a lexicon marker word plus an identifier
   starts an item, and every following line belongs to it until the next
   marker. Lines before the document's first marker are the document's own
   front matter and yield no item.
2. **ordinal** — the same rule over `3.` / `3)` openers, used only when the
   document declares no marker word anywhere. Numbered-only errata documents
   are common enough that refusing them would publish nothing.
3. **section** — every section with any text becomes one item. This is the
   floor: a document nothing else could segment still publishes every line it
   printed, because an erratum that disappears is the worst outcome this
   package can produce.

Whichever rule fired is recorded on each item as its `derivation`, so a reader
who disagrees with where an item starts can see which rule drew the line.

Page attribution is a **range**, never a point: `pdf_text` carries no per-line
page, so an item takes the start page of the section its first line was in and
the end page of the section its last line was in. Narrowing that to one page
would be an invented citation (invariant 3), and widening it to the document
would be useless.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from datasheet_analyzer.errata.lexicon import ErrataLexicon, load_errata_lexicon
from datasheet_analyzer.models import DocType, ErrataItem, RawDocument, SectionNode
from datasheet_analyzer.provenance import errata_item_id

log = logging.getLogger(__name__)

#: The three named segmentation rules, as they are recorded on an item.
DERIVATION_MARKER = "errata-item-marker"
DERIVATION_ORDINAL = "errata-item-ordinal"
DERIVATION_SECTION = "errata-section"


@dataclass(frozen=True)
class _Line:
    """One printed line of the errata document, with the section it sits in."""

    text: str
    section: SectionNode


def is_errata(raw: RawDocument) -> bool:
    """Whether this extracted document is one this package reads items out of."""
    return raw.source.doc_type == DocType.ERRATA


def build_items(
    docs: list[tuple[str, RawDocument]],
    *,
    lexicon: ErrataLexicon | None = None,
    start_ordinal: int = 0,
) -> list[ErrataItem]:
    """Every errata item of a part, in document-then-reading order.

    `docs` is `(document directory name, extracted document)` for each errata
    document of the part, in publication order — the ids are minted across the
    whole sequence (`provenance.errata_item_id`), so a part with two errata
    documents still has one `err_N` space and a rebuild of identical input
    reproduces every id exactly.
    """
    lexicon = lexicon or load_errata_lexicon()
    out: list[ErrataItem] = []
    for doc_name, raw in docs:
        for item in _document_items(doc_name, raw, lexicon):
            out.append(item.model_copy(update={"id": errata_item_id(start_ordinal + len(out))}))
    return out


def _document_items(
    doc_name: str, raw: RawDocument, lexicon: ErrataLexicon
) -> list[ErrataItem]:
    lines = [
        _Line(text=para.strip(), section=section)
        for section in raw.sections
        for para in section.paragraphs
        if para.strip()
    ]
    if not lines:
        log.warning(
            "errata document %s printed no readable text — no items", doc_name
        )
        return []

    starts = [(i, lexicon.marker_start(line.text)) for i, line in enumerate(lines)]
    starts = [(i, marker) for i, marker in starts if marker]
    derivation = DERIVATION_MARKER
    if not starts:
        starts = [(i, lexicon.ordinal_start(line.text)) for i, line in enumerate(lines)]
        starts = [(i, marker) for i, marker in starts if marker]
        derivation = DERIVATION_ORDINAL
    if not starts:
        return _section_items(doc_name, raw)

    items: list[ErrataItem] = []
    for n, (index, marker) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        chunk = lines[index:end]
        first, last = chunk[0].section, chunk[-1].section
        items.append(
            ErrataItem(
                doc=doc_name,
                doc_hash=raw.source.content_hash,
                marker=marker,
                text="\n".join(line.text for line in chunk),
                section=first.number,
                section_title=first.title,
                page=first.page_start,
                page_end=last.page_end if last.page_end is not None else first.page_end,
                derivation=derivation,
            )
        )
    return items


def _section_items(doc_name: str, raw: RawDocument) -> list[ErrataItem]:
    """The floor: one item per section that printed anything.

    Reached when a document declares no marker word and no ordinal opener. It
    links less well — an item this wide often names several identifiers — but
    it loses nothing, which is the property that matters.
    """
    items: list[ErrataItem] = []
    for section in raw.sections:
        paragraphs = [p.strip() for p in section.paragraphs if p.strip()]
        if not paragraphs:
            continue
        items.append(
            ErrataItem(
                doc=doc_name,
                doc_hash=raw.source.content_hash,
                marker=section.full_title,
                text="\n".join(paragraphs),
                section=section.number,
                section_title=section.title,
                page=section.page_start,
                page_end=section.page_end,
                derivation=DERIVATION_SECTION,
            )
        )
    return items
