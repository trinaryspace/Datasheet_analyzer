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

import re
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from datasheet_analyzer.retrieve.results import Citation


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


# `Applicability.family` wildcards: a trailing (or embedded) run of `x`/`X`
# stands for one character each, the way vendors print a family — `AFE79xx`
# covers AFE7950 and AFE7952, `AD90x1` covers AD9081 and AD9091.
_FAMILY_WILDCARD = re.compile(r"[xX]")
# What may follow a matched family stem: a package/temperature suffix
# (`AFE7950A`, `LM741-N`) is still the same family.
_FAMILY_SUFFIX = r"[A-Z0-9\-]*"


class Applicability(BaseModel):
    """The set of parts a document is *about* (ADR 0005).

    Containment ("a part owns its documents") cannot express an application
    note titled "AFE79xx JESD204C Interface Guide", so a document instead
    carries the set of parts it applies to and a Part becomes the *view* of
    the documents that cover it. Three kinds, and no fourth:

    | kind | field read | means |
    |---|---|---|
    | `parts` | `parts` | exactly these part numbers |
    | `family` | `family` | every part matching the prefix (`AFE79xx`) |
    | `all` | — | every part in the library |

    `all` is the default *and* the honest fallback: a document whose
    applicability cannot be determined degrades to the previous flat
    behaviour rather than to a wrong owner.

    `evidence` records how the decision was reached — the matched title-block
    line, `llm:<model>`, `fallback: no part token found`, or
    `migrated from sources.json`. It is never blank in practice, the same
    discipline `SourceDocument.vendor_evidence` carries on the routing path:
    an inferred value that cannot say why is not correctable by a human.

    This model lives on `LibraryDocument`, never on `SourceDocument`:
    `SourceDocument` is embedded in every cached `RawDocument` under
    `.cache/extract/`, and a new required field there would invalidate every
    cached extraction.
    """

    kind: Literal["parts", "family", "all"] = "all"
    parts: list[str] = Field(default_factory=list)  # kind == "parts"
    family: str = ""  # kind == "family", e.g. "AFE79xx"
    evidence: str = ""  # how it was decided; never blank in practice

    @classmethod
    def for_parts(cls, parts: list[str] | tuple[str, ...], *, evidence: str = "") -> Applicability:
        """Applicability naming exactly these part numbers."""
        return cls(kind="parts", parts=list(parts), evidence=evidence)

    @classmethod
    def for_family(cls, family: str, *, evidence: str = "") -> Applicability:
        """Applicability covering a family prefix such as `AFE79xx`."""
        return cls(kind="family", family=family, evidence=evidence)

    @classmethod
    def for_all(cls, *, evidence: str = "") -> Applicability:
        """The honest default: a document that applies to every part."""
        return cls(kind="all", evidence=evidence)

    def covers(self, part_number: str) -> bool:
        """True when this document applies to `part_number`.

        Case-insensitive throughout — part numbers are printed both ways and a
        corpus keyed on `AD9081` must not miss a document that wrote `ad9081`.
        A blank part number is covered by nothing: a part is an identity, and
        "applies to the nameless part" is never a useful answer.
        """
        wanted = (part_number or "").strip().upper()
        if not wanted:
            return False
        if self.kind == "all":
            return True
        if self.kind == "parts":
            return any(wanted == p.strip().upper() for p in self.parts)
        stem = (self.family or "").strip().upper()
        if not stem:
            return False
        if not _FAMILY_WILDCARD.search(stem):
            return wanted.startswith(stem)
        pattern = "".join("." if ch in "xX" else re.escape(ch) for ch in stem)
        return re.fullmatch(pattern + _FAMILY_SUFFIX, wanted) is not None

    @property
    def label(self) -> str:
        """Human-readable one-liner: `AD9081`, `AFE79xx`, `all parts`."""
        if self.kind == "all":
            return "all parts"
        if self.kind == "family":
            return self.family or "unnamed family"
        return ", ".join(self.parts) if self.parts else "no parts"

    @property
    def is_valid(self) -> bool:
        """False for the two shapes the API refuses (ticket 09).

        `kind="parts"` with an empty list and `kind="family"` with a blank
        family are inert writes that would silently narrow a document to
        nothing; they are a 400, never a stored value.
        """
        if self.kind == "parts":
            return bool([p for p in self.parts if p.strip()])
        if self.kind == "family":
            return bool(self.family.strip())
        return True


class LibraryDocument(BaseModel):
    """A `SourceDocument` in the flat Library, plus what a user may change.

    The Library is the authoritative inventory keyed by `content_hash` (the
    sha256 of the PDF's bytes, already a `SourceDocument`'s identity); a
    part's `sources.json` becomes a derived view of it.

    Only two fields here are user-writable: `applicability` (inference is a
    proposal, never the last word) and `labels`. A **Label** is user text
    (`reviewed`, `thermal`); the machine-derived `PlotRecord.tags` are
    **Tags**. A build never writes labels and never overwrites them.

    `schema_version` is stamped by the store with `LIBRARY_SCHEMA_VERSION`;
    a file carrying an unknown version is skipped rather than guessed at.
    """

    source: SourceDocument
    applicability: Applicability = Field(default_factory=Applicability)
    labels: list[str] = Field(default_factory=list)
    added_at: datetime = Field(default_factory=_utcnow)
    schema_version: str = ""

    @property
    def content_hash(self) -> str:
        """The document's identity — the store's key."""
        return self.source.content_hash

    @property
    def filename(self) -> str:
        """The recorded path's basename, for display."""
        return self.source.path.replace("\\", "/").rsplit("/", 1)[-1]

    def covers(self, part_number: str) -> bool:
        """Shorthand for `self.applicability.covers(part_number)`."""
        return self.applicability.covers(part_number)


class ScopeRef(BaseModel):
    """Exactly one Part or one Project — the only scopes retrieval accepts.

    ADR 0006: there is no "all parts" scope. A question is resolved to one of
    these, and the resolved scope is *shown* on the answer so the scope of an
    answer is never implicit.
    """

    kind: Literal["part", "project"] = "part"
    name: str = ""

    @property
    def label(self) -> str:
        """`AD9081` or `project: rx-frontend`."""
        return self.name if self.kind == "part" else f"project: {self.name}"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.label


class CitationOut(BaseModel):
    """`retrieve.results.Citation` as JSON, plus its two derived strings.

    Mirrors the dataclass field for field so a citation crossing the HTTP
    boundary is the same thing the retrieval core built, and carries `pages`
    and `label` as *fields* because a browser cannot call a Python property.
    Front ends print `label` (`§4.5, p.7`) and never assemble `p.N`
    themselves — that is what keeps the citation format from drifting between
    the CLI, the MCP server and this application.
    """

    doc: str = ""
    doc_hash: str = ""
    section: str = ""
    page_start: int | None = None
    page_end: int | None = None
    part: str = ""
    pages: str = "p.?"
    label: str = ""
    needle: str = ""

    @classmethod
    def from_citation(cls, citation: Citation) -> CitationOut:
        """Build from a `retrieve.results.Citation` without importing it.

        Duck-typed on purpose: `retrieve.results` imports this module, so a
        runtime import back the other way would be a cycle. `needle` is read
        defensively for the same reason a corpus built before it existed must
        still load: a citation without one opens the page unhighlighted.
        """
        return cls(
            doc=citation.doc,
            doc_hash=citation.doc_hash,
            section=citation.section,
            page_start=citation.page_start,
            page_end=citation.page_end,
            part=citation.part,
            pages=citation.pages,
            label=citation.label,
            needle=getattr(citation, "needle", "") or "",
        )


class JobState(str, Enum):
    """Where one analyze job is, in the order it passes through.

    The five working states mirror `batch.py`'s event vocabulary
    (`extracting | structuring | enriching | publishing`) so the GUI reports
    the stages the runner already emits rather than inventing a second
    vocabulary. `DONE`, `FAILED` and `SKIPPED` are terminal.
    """

    QUEUED = "queued"
    EXTRACTING = "extracting"
    STRUCTURING = "structuring"
    ENRICHING = "enriching"
    PUBLISHING = "publishing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def terminal(self) -> bool:
        """True once the job will emit no further state."""
        return self in (JobState.DONE, JobState.FAILED, JobState.SKIPPED)


# The working stages in the order a job passes through them, exported so a
# progress UI and a test can assert the sequence without hardcoding it twice.
JOB_STAGE_ORDER: tuple[JobState, ...] = (
    JobState.QUEUED,
    JobState.EXTRACTING,
    JobState.STRUCTURING,
    JobState.ENRICHING,
    JobState.PUBLISHING,
)
JOB_TERMINAL_STATES: tuple[JobState, ...] = (
    JobState.DONE,
    JobState.FAILED,
    JobState.SKIPPED,
)


class AnalyzeJob(BaseModel):
    """One PDF being built into a part, with the applicability the user confirmed.

    `applicability` is what came back from the review screen, not what
    inference proposed: a correction the user made must reach the library, so
    the job carries it rather than re-inferring it at build time.
    """

    id: str
    pdf_path: str
    part_number: str
    applicability: Applicability = Field(default_factory=Applicability)
    state: JobState = JobState.QUEUED
    error: str = ""
    detail: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def terminal(self) -> bool:
        return self.state.terminal


class ChatMessage(BaseModel):
    """One turn of a conversation, with the citations that back it.

    Citations are collected from the `Citation` objects inside the tool
    results the agent actually executed — never parsed out of the model's
    prose — so a claim the model invented carries no citation.
    """

    role: Literal["user", "assistant"]
    text: str
    citations: list[CitationOut] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class ChatSession(BaseModel):
    """A saved conversation: its messages, their citations, and its scope.

    Persisted as one JSON file per session so a week-old question and the
    pages it cited are still there after a restart. The scope is stored
    because an answer without the scope it was drawn from is not verifiable.
    """

    id: str
    title: str
    scope: ScopeRef
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @property
    def n_messages(self) -> int:
        return len(self.messages)


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
    # Part-level vendor record: the datasheet's pinned vendor.
    vendor: str = ""
    # Where this corpus's `@library/…` references hang off, as a path
    # *relative to the part directory* (POSIX separators). Empty — and so for
    # every corpus written before the shared document store existed — means
    # every document is published under the part and there is no second root.
    # Recorded here because a reader is often handed a part directory and
    # nothing else; without it, following a shared reference would mean
    # guessing at the `Settings` that produced the build. See
    # `datasheet_analyzer.corpus_ref`.
    library_root: str = ""
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
    # Per-record extraction confidence (`structure/confidence.py` owns the
    # rule). Additive: a corpus built before it existed has no value on disk
    # and loads as `UNKNOWN` — honestly ungraded, never optimistically high.
    confidence: Confidence = Confidence.UNKNOWN


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
