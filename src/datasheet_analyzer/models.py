"""Canonical data models — the contract between pipeline stages.

These are the source of truth. Extraction produces a `RawDocument`, the
structure stage refines it, enrichment produces index descriptions, and the
publisher writes the on-disk corpus + `CorpusManifest`. Keep them stable and
deliberate: every stage (and every test) depends on them.

Design rules baked into the models:
- A *part* is a folder of documents (`SourceDocument`), never a single PDF.
- Tables are atomic: a `TableBlock` always carries its header, its test
  conditions preamble, and its footnotes with it.
- Every content element carries page provenance so answers can be cited.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocType(str, Enum):
    """Kind of source document within a part's document set."""

    DATASHEET = "datasheet"
    REGISTER_MAP = "register_map"
    ERRATA = "errata"
    APP_NOTE = "app_note"
    UNKNOWN = "unknown"


class SourceDocument(BaseModel):
    """A registered input document. Identity is sha256 of the file bytes."""

    content_hash: str
    path: str
    part_number: str = ""
    doc_type: DocType = DocType.UNKNOWN
    revision: str = ""
    page_count: int = 0
    nda: bool = False
    # Vendor routing record, evidence-pinned at acquire time. The default
    # stays `ti` so pre-existing inventories keep today's routing; evidence
    # is the brand match text or "cli-override: --vendor <name>".
    vendor: str = "ti"
    vendor_evidence: str = ""
    registered_at: datetime = Field(default_factory=_utcnow)


class TOCEntry(BaseModel):
    """One table-of-contents line, reconciled across PDF and HTML views."""

    number: str = ""  # "4.5" or "" when unnumbered (e.g. "Table of Contents")
    title: str = ""  # title as printed, without the leading number
    level: int = 1
    page: int | None = None  # 1-based PDF page, None if unknown
    url: str = ""  # per-section content URL (HTML backends), "" otherwise


class Footnote(BaseModel):
    """A table footnote, keyed by its marker as printed: "(2)", "†", "*"."""

    marker: str
    text: str


class TableBlock(BaseModel):
    """An atomic table with everything an agent needs to trust it.

    `grid` is the body with all rowspan/colspan merges expanded so a given
    (row, col) lookup never depends on span bookkeeping. `headers` comes from
    the table's thead. `conditions` is the test-conditions paragraph that
    preceded the table in the source — it is part of the table's meaning and
    must never be separated from it. `footnotes` holds the table's footnotes
    (same rule). Both markdown and CSV renderings are precomputed.
    """

    caption: str = ""
    headers: list[str] = Field(default_factory=list)
    grid: list[list[str]] = Field(default_factory=list)
    conditions: str = ""
    footnotes: list[Footnote] = Field(default_factory=list)
    # markers (e.g. "(2)") cited via <sup> in the source HTML, captured while
    # structure is available; used by footnote-association audits.
    cited_markers: list[str] = Field(default_factory=list)
    markdown: str = ""
    csv: str = ""
    html: str = ""
    page: int | None = None
    # Per-row page attribution of merged multi-page grids (`pdf_layout`):
    # grid[i] was printed on row_pages[i]. Empty for HTML backends, where
    # every row shares the table's single page. Continuation rows of a
    # multi-page table cite their own printed page, so answers never cite a
    # row by a page it does not appear on.
    row_pages: list[int | None] = Field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.grid)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.grid), default=0)


class FigureRef(BaseModel):
    """A figure/plot reference. Pixels are rendered downstream (Phase 3);
    Phase 1 catalogs the reference, caption and conditions."""

    caption: str = ""
    conditions: str = ""
    image_url: str = ""
    page: int | None = None


class SectionNode(BaseModel):
    """One section of a document, flat (children expressed via `level`)."""

    number: str = ""  # "4.5" or "" when unnumbered
    title: str = ""
    level: int = 1
    page_start: int | None = None
    page_end: int | None = None
    paragraphs: list[str] = Field(default_factory=list)
    tables: list[TableBlock] = Field(default_factory=list)
    figures: list[FigureRef] = Field(default_factory=list)

    @property
    def full_title(self) -> str:
        return f"{self.number} {self.title}".strip()


class RawDocument(BaseModel):
    """Output of the extract stage: one source document, fully extracted."""

    source: SourceDocument
    toc: list[TOCEntry] = Field(default_factory=list)
    sections: list[SectionNode] = Field(default_factory=list)  # reading order
    extractor: str = ""
    # Output-schema version of the extractor that produced this document.
    # Cache invalidation: a cached raw whose version no longer matches the
    # backend's current `output_version` is stale and must be re-extracted
    # (embedded version field, per the cache-invalidation invariant).
    extractor_version: str = ""
    # Per-document extraction honesty: the layout engine records detected /
    # accepted / rejected tables with reasons and mean fidelity here; it
    # survives the extraction cache because it lives on the raw document.
    extraction_stats: ExtractionStats | None = None
    extracted_at: datetime = Field(default_factory=_utcnow)


class SectionFile(BaseModel):
    """Manifest entry for one rendered section file."""

    number: str
    title: str
    file: str  # path relative to the part corpus dir
    doc_hash: str
    page_start: int | None = None
    page_end: int | None = None
    token_count: int = 0
    description: str = ""
    n_tables: int = 0
    n_figures: int = 0


class CorpusStats(BaseModel):
    n_documents: int = 0
    n_sections: int = 0
    n_tables: int = 0
    n_figures: int = 0
    n_footnotes: int = 0
    n_specs: int = 0
    n_plot_files: int = 0
    total_tokens: int = 0
    index_tokens: int = 0
    boilerplate_tokens_removed: int = 0
    sections_with_pages: int = 0
    sections_without_pages: int = 0


class ExtractionStats(BaseModel):
    """Per-document extraction statistics recorded in the manifest.

    The detected/accepted/rejected table counts, rejection reasons and
    mean fidelity are filled by the layout engine (``pdf_layout``); other
    backends record just the backend name.

    ``extractor_version`` is the backend's ``output_version`` at build time.
    It is what lets a later run tell a current corpus from one produced by an
    older extractor output schema: the batch skip gate rebuilds when it no
    longer matches (`PIPELINE_VERSION` is the coarser guard and does not move
    on every extractor bump). Empty on corpora built before this field
    existed, which reads as stale and rebuilds once.
    """

    backend: str = ""
    extractor_version: str = ""
    tables_detected: int = 0
    tables_accepted: int = 0
    tables_rejected: int = 0
    rejection_reasons: list[str] = Field(default_factory=list)
    mean_fidelity: float = 0.0


class CorpusManifest(BaseModel):
    """Machine-readable index of a built part corpus (manifest.json)."""

    part_number: str
    pipeline_version: str = ""
    # Part-level vendor record: the datasheet's pinned vendor.
    vendor: str = ""
    # Per-document extraction stats keyed by content_hash.
    extraction_stats: dict[str, ExtractionStats] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=_utcnow)
    documents: list[SourceDocument] = Field(default_factory=list)
    sections: list[SectionFile] = Field(default_factory=list)
    stats: CorpusStats = Field(default_factory=CorpusStats)


class SpecUnit(BaseModel):
    """Verbatim unit as printed + canonical form for deterministic queries."""

    verbatim: str = ""  # e.g. "Ω" (U+2126), "dBc/Hz", "" when unitless
    canonical: str = ""  # e.g. "ohm", "dBc/Hz", ""


class SpecRecord(BaseModel):
    """One normalized row from a parametric table — deterministic lookup unit."""

    # identity within the document
    section: str = ""
    table_index: int = 0
    row_index: int = 0
    # semantic roles (empty string when the role doesn't exist for the table)
    symbol: str = ""  # e.g. "ATTstep"
    name: str = ""  # e.g. "DSA Attenuation step accuracy (DNL)"
    conditions: str = ""  # row-level test conditions
    table_conditions: str = ""  # TableBlock.conditions verbatim
    min: str = ""  # verbatim strings — NEVER parsed to float
    typ: str = ""
    max: str = ""
    value: str = ""  # single-value tables (ESD "VALUE", thermal)
    unit: SpecUnit = Field(default_factory=SpecUnit)
    # provenance
    footnotes: list[Footnote] = Field(default_factory=list)
    cited_markers: list[str] = Field(default_factory=list)
    page: int | None = None
    row_verbatim: list[str] = Field(default_factory=list)


class SpecTableInfo(BaseModel):
    """Per-table classification/reporting for coverage audits."""

    section: str = ""
    table_index: int = 0
    kind: str = ""  # "parametric" | "info" | "unmapped"
    n_records: int = 0
    unmapped_headers: list[str] = Field(default_factory=list)


class SpecSet(BaseModel):
    """A document's full set of normalized spec records."""

    schema_version: str = ""
    part_number: str = ""
    doc_hash: str = ""
    records: list[SpecRecord] = Field(default_factory=list)
    tables: list[SpecTableInfo] = Field(default_factory=list)


class PlotRecord(BaseModel):
    """One cataloged figure/plot, with optional on-disk pixel file."""

    id: str = ""  # section number + sequence, e.g. "4.12.1-f007"
    section: str = ""  # e.g. "4.12.1"
    caption: str = ""  # FigureRef.caption
    figure_number: str = ""  # "4-1" parsed from caption, "" when absent
    conditions: str = ""  # FigureRef.conditions (textnote)
    page_start: int | None = None  # owning section's page range start
    page_end: int | None = None  # owning section's page range end
    image_url: str = ""  # source URL as cataloged
    file: str = ""  # corpus-relative path, "" until pixels exist
    tags: list[str] = Field(default_factory=list)  # section + caption tags


class PlotSet(BaseModel):
    """A document's full plot catalog + pixel map."""

    schema_version: str = ""
    part_number: str = ""
    doc_hash: str = ""
    plots: list[PlotRecord] = Field(default_factory=list)


class GoldenQuestion(BaseModel):
    """One eval question with a verifiable expected answer."""

    id: str
    question: str
    expected_substrings: list[str]  # all must appear in a correct answer
    pages: list[int] = Field(default_factory=list)  # citation ground truth
    section: str = ""  # expected section number, when known
    kind: str = "direct"  # direct | derived
    spec_query: dict[str, str] | None = None  # Phase 2 deterministic lookup
    plot_query: dict[str, str] | None = None  # Phase 3 deterministic plot lookup
    notes: str = ""
