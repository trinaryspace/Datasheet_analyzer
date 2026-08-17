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


class Confidence(str, Enum):
    """How much a single extracted record can be trusted on its own.

    `ExtractionStats` grades a whole *document*; an answer needs the grade per
    *record*, so an agent can say "this one is `low` — open p.47" instead of
    asserting a shaky number. Graded at structure time by
    `structure/confidence.py`, which documents the rule.

    `UNKNOWN` is the honest default: a corpus built before the field existed
    carries no grade on disk and loads as ungraded rather than as an
    optimistic `HIGH`.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ValueKind(str, Enum):
    """The shape of a printed value the numeric layer recognised.

    A datasheet cell states one of exactly four things, and which one it states
    changes what may be computed from it: a `POINT` is a number, a `RANGE` is an
    interval, a `BOUND` constrains one side only, and a `TOLERANCE` is a spread
    with no nominal of its own. `structure/quantities.py` owns the grammar; a
    cell that states none of these has no kind at all (`None` on the record),
    which is the honest outcome and never a fifth guess.
    """

    POINT = "point"
    RANGE = "range"
    BOUND = "bound"
    TOLERANCE = "tolerance"


class ParseConfidence(str, Enum):
    """Whether the numeric layer could read a record's printed value.

    Deliberately *not* `Confidence`: that grade is about the extraction (how far
    a row can be trusted), this one is about the parse (whether a number exists
    at all). `NONE` is a first-class outcome, not a failure to fix — `See
    Figure 7` has no number, and inventing one is precisely what invariant 8
    forbids.
    """

    EXACT = "exact"
    NONE = "none"


# How the layout engine arrived at a reconstructed grid (`TableBlock.reconstruction`).
# The header-anchored split is the table's own declaration of its columns; a
# rescue is a coarser retry-ladder split that only won because that declaration
# did not pass the gate — which is exactly what makes its rows `low`.
RECONSTRUCTION_HEADER = "header-anchored"
RECONSTRUCTION_RESCUED = "rescued"


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
    # How this grid was reconstructed, when it had to be (`pdf_layout`):
    # `RECONSTRUCTION_HEADER` — the table's own header-declared column edges
    # passed the gate on the first try; `RECONSTRUCTION_RESCUED` — only a
    # coarser retry-ladder split did. `""` means the question does not apply
    # (an HTML backend's table is structurally declared by its source) or the
    # document predates the field. Read by the per-record confidence grade.
    reconstruction: str = ""

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
    # Indexed search-token count (Phase 5): the section's length as BM25 sees
    # it. Additive — 0 on corpora built before the search index existed.
    search_tokens: int = 0


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
    # Phase 5 search index economics, recorded per part so the ratio is a
    # measured number in every manifest rather than a claim in a report:
    # the bytes every `search_index.json` occupies, against the bytes of the
    # section markdown they index. Additive — 0 on older corpora.
    section_bytes: int = 0
    search_index_bytes: int = 0
    # Phase 5 per-record confidence mix: how many spec / plot records of this
    # part carry each grade (`{"high": 412, "medium": 190, "low": 17}`, and
    # `"unknown"` only when something really is ungraded). Recorded per part
    # so the mix is a measured number in every manifest — `dsa status` prints
    # it — rather than a claim in a report. Additive: `{}` on older corpora.
    spec_confidence: dict[str, int] = Field(default_factory=dict)
    plot_confidence: dict[str, int] = Field(default_factory=dict)
    # Phase 5 ticket 08: the measured size of the `AGENT.md` published beside
    # `INDEX.md`. Recorded for the same reason `index_tokens` is — a file an
    # agent loads every time has a cost, and the cost belongs in the manifest
    # as a number rather than in a report as a claim. Additive: 0 on corpora
    # published before the protocol existed.
    agent_doc_tokens: int = 0


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
    # Derivation-rule version this corpus's derived artifacts were produced
    # under (`config.CARD_VERSION`, overridable as `DSA_CARD_VERSION`). Part of
    # the publish cache key: `batch.skip_reason` refuses to skip a corpus
    # derived under a different rule set, so changing a rule regenerates rather
    # than leaving stale cards behind. Additive — "" on corpora published
    # before ADR 0005, which reads as stale and republishes once.
    card_version: str = ""
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

    # Stable, addressable id within the document's `specs.json` ("rec_412"),
    # minted by `provenance.spec_record_id` at structure time. It is what a
    # derived value's `source` points at (ADR 0005 / invariant 8), so it must
    # be reproduced exactly by a rebuild of identical input. Additive: a corpus
    # published before ids existed carries "" and resolves to nothing —
    # honestly unaddressable rather than pointing at the wrong row.
    id: str = ""
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
    # Per-record extraction confidence (`structure/confidence.py` owns the
    # rule). Additive: a corpus built before it existed has no value on disk
    # and loads as `UNKNOWN` — honestly ungraded, never optimistically high.
    confidence: Confidence = Confidence.UNKNOWN
    # The additive numeric layer (`structure/quantities.py`, phase 6 ticket 02).
    # It describes the record's *representative* quantity — the one that module
    # documents and selects — and is always allowed to fail: nothing here is a
    # substitute for the verbatim cells above, which stay authoritative and are
    # never mutated by it.
    #
    # `value_si` is the point value of a `point`, and the magnitude of a
    # `tolerance` (±0.5 has no interval without a nominal); it is `None` for a
    # `range` and a `bound`, whose interval lives in the two fields below —
    # a bound fills the side it states and leaves the other `None`. Everything
    # is expressed in `unit_si`, the SI base unit the layer scaled to.
    value_si: float | None = None
    value_low_si: float | None = None
    value_high_si: float | None = None
    unit_si: str = ""
    value_kind: ValueKind | None = None
    parse_confidence: ParseConfidence = ParseConfidence.NONE


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
    # Per-record extraction confidence, same contract as `SpecRecord`: a plot
    # is graded on how precisely it can be cited and identified.
    confidence: Confidence = Confidence.UNKNOWN


class PlotSet(BaseModel):
    """A document's full plot catalog + pixel map."""

    schema_version: str = ""
    part_number: str = ""
    doc_hash: str = ""
    plots: list[PlotRecord] = Field(default_factory=list)


class DerivedValue(BaseModel):
    """One value on a derived artifact, in its provenance envelope (ADR 0005).

    Invariant 8's unit of currency. A derived artifact (a design card, a
    comparison row) is not verbatim corpus text, so it may only exist as a
    quote of a record, a documented pure function of records, or a label from
    a checked-in lexicon — and it must say which, for every single field:

    - `verbatim` is the string as the datasheet printed it. It is authoritative
      and is never mutated; where it and the parsed number disagree, it wins.
    - `value_si` / `unit_si` are the additive numeric layer and are allowed to
      fail: `None` / `""` means "this could not be parsed", which is a
      first-class outcome and never a zero.
    - `source` is the record this value came from
      (`docs/<doc>/specs.json#rec_412`; see `provenance.py`, which mints,
      parses and resolves it) and `page` is the printed page it was read off.
    - `derivation` names the rule that produced the value
      (`parse_quantity+si_normalize`). A field with no named rule has no
      business being on a derived artifact.
    - `confidence` is carried over from the source record; it is metadata about
      the extraction and never a filter.

    A field that cannot be filled stays null and says so — it is never
    interpolated and never defaulted to a plausible value.
    """

    verbatim: str = ""
    value_si: float | None = None
    unit_si: str = ""
    source: str = ""
    page: int | None = None
    derivation: str = ""
    confidence: Confidence = Confidence.UNKNOWN


class SearchSection(BaseModel):
    """One indexed section file: its term frequencies and its token length.

    `file` is the *document*-relative path (`sections/4-5.md`), so a document
    directory carries a self-contained index that survives being moved with
    the part. Positions are deliberately not stored: snippets are recovered by
    re-reading the section file, which is cheap and keeps the index small.
    """

    file: str = ""
    length: int = 0
    tokens: dict[str, int] = Field(default_factory=dict)


class SearchIndex(BaseModel):
    """A document's inverted index (search_index.json), built at publish.

    `df` is the per-token document frequency across this document's sections
    and `avgdl` their mean length — the two corpus statistics BM25 needs. A
    part with several documents merges them at query time.
    """

    schema_version: str = ""
    part_number: str = ""
    doc_hash: str = ""
    sections: list[SearchSection] = Field(default_factory=list)
    df: dict[str, int] = Field(default_factory=dict)
    avgdl: float = 0.0


class ProjectMember(BaseModel):
    """One part inside a project, with the role the designer gave it.

    `role` is free text a human maintains (`dsa project add --role`, or by
    editing `project.json`): the corpus cannot know that AFE7950 is "the
    transceiver" of *this* board. It is never derived and never guessed —
    an unset role simply prints nothing.
    """

    part_number: str
    role: str = ""


class Project(BaseModel):
    """A design: an explicit list of parts plus the notes that join them.

    The noun above `part`. Membership is explicit by decision (no BOM or
    netlist parsing — see the Phase 5 plan's Out of Scope): a project is a
    list a human or an agent curates, so it can never silently acquire a part
    nobody chose. `interfaces` and `notes` are the free text the designer
    maintains; the pipeline reads them and never rewrites them.
    """

    name: str
    parts: list[ProjectMember] = Field(default_factory=list)
    interfaces: str = ""
    notes: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @property
    def part_numbers(self) -> list[str]:
        return [m.part_number for m in self.parts]


class GoldenQuestion(BaseModel):
    """One eval question with a verifiable expected answer.

    A question may carry a *path marker* saying which retrieval path must
    answer it. They are additive and independent — a set written before a path
    existed still loads, and a question may be verified by more than one path:

    | Marker | Path | Pass rule (in `evalh.citations`) |
    |---|---|---|
    | `spec_query` | `dsa query` | a record on a cited page carries every expected substring |
    | `plot_query` | `dsa plots` | a cataloged figure on a cited page has real pixels |
    | `ask_query` | `dsa ask` | the pack's rows on a cited page carry them, inside its budget |
    | `search_query` | `dsa search` | the **top-1** hit is a section covering a cited page, and that section holds them |

    `ask_query` / `search_query` (phase 5, ticket 09) both take the question's
    own `pages` and `expected_substrings` as ground truth — the point of them
    is that a designer's words reach *the same verbatim answer on the same
    printed page* as the symbol path already reaches, so they are twins of an
    existing question rather than a second objective function. `ask_query` may
    name the route it must take (`{route: spec}`); `search_query` may carry the
    words a designer would type (`{query: sysref setup}`), defaulting to the
    question itself.
    """

    id: str
    question: str
    expected_substrings: list[str]  # all must appear in a correct answer
    pages: list[int] = Field(default_factory=list)  # citation ground truth
    section: str = ""  # expected section number, when known
    kind: str = "direct"  # direct | derived | plot | ask | search
    spec_query: dict[str, str] | None = None  # Phase 2 deterministic lookup
    plot_query: dict[str, str] | None = None  # Phase 3 deterministic plot lookup
    ask_query: dict[str, str] | None = None  # Phase 5 answer pack ({route})
    search_query: dict[str, str] | None = None  # Phase 5 full text ({query, rank})
    notes: str = ""
