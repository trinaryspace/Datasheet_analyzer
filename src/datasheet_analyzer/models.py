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


class PinType(str, Enum):
    """What a pin is *for*, as a checked-in lexicon labels it (ADR 0005 (c)).

    Deliberately not the `I/O` column a datasheet prints — that is the pin's
    *direction* and travels verbatim on the record beside this. This is the
    category a designer filters on during schematic capture ("show me the
    supplies"), and it is a **classification**, so it is only ever as good as
    the lexicon: `UNKNOWN` is a legitimate output and a guess is not. A row the
    lexicon does not recognise, and a row whose evidence points at two
    categories at once, both land here as `UNKNOWN`.
    """

    POWER = "power"
    GROUND = "ground"
    ANALOG = "analog"
    DIGITAL = "digital"
    CLOCK = "clock"
    RF = "rf"
    NC = "nc"
    RESERVED = "reserved"
    UNKNOWN = "unknown"


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
    # Phase 6, ticket 04: how many individually citable pin records the part
    # published. 0 both for a part whose datasheet prints no pin table and for
    # one whose pin table was rejected — the difference is in
    # `ExtractionStats.rejection_reasons`, where a rejection is recorded and an
    # absence is honestly nothing at all.
    n_pins: int = 0
    # Phase 6, ticket 05: how many individually citable register records the
    # part published, across every document. 0 for a part with no register
    # summary anywhere — the difference between "prints none" and "was
    # rejected" lives in `ExtractionStats.rejection_reasons`, exactly as it
    # does for pins.
    n_registers: int = 0
    n_plot_files: int = 0
    # Phase 6, ticket 07: how many design cards the part publishes and how many
    # rows they hold in total. The card count is constant per lexicon (an empty
    # card is still a card); the row count is the measured one — a part whose
    # cards hold no rows at all says so in the manifest instead of only in the
    # files.
    n_cards: int = 0
    n_card_rows: int = 0
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
    # Phase 6, ticket 04: the same mix for pin records. `{}` for a part with
    # no pin table.
    pin_confidence: dict[str, int] = Field(default_factory=dict)
    # Phase 6, ticket 05: the same mix for register records. `{}` for a part
    # with no register summary.
    register_confidence: dict[str, int] = Field(default_factory=dict)
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
    # Warnings raised while *deriving* an artifact (ADR 0005) — today the
    # pin-count cross-check, tomorrow a card's. They live in the manifest
    # rather than in a build log because the ADR decided a mismatch "warns,
    # and is recorded": a warning is only weaker than a rejection when it can
    # be ignored, and a fact the corpus carries is auditable across every part
    # at once (`dsa audit`, phase 7). Additive — [] on older corpora.
    derived_warnings: list[str] = Field(default_factory=list)
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
    # The printed title of the section this row's table was printed under
    # ("Absolute Maximum Ratings"). Additive, phase 6 ticket 07: it is the only
    # identity a derived artifact can select a *table* by on the captionless era
    # of datasheets, where `section` above is honestly "" for every section
    # (ADR 0004) and a page can be covered by three sections at once. A design
    # card that cannot tell an abs-max table from a recommended-operating one
    # cannot compute a margin, so the title travels on the record. "" on a
    # corpus published before the field existed.
    section_title: str = ""
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


class PinRecord(BaseModel):
    """One pin of one package, individually citable (phase 6, ticket 04).

    The unit a designer works in during schematic capture. A printed pin row
    that names several pins (`A1, A2, B1`, `A1-A4`) becomes one record each —
    a pin search must not miss a pin that shared a row — and every one of them
    quotes the cell it came from (`pin_verbatim`) and the row it was printed on
    (`row_verbatim`), so an expansion is always traceable back to the single
    line the datasheet printed.

    Everything here except `type` is verbatim: `name`, `direction` (the printed
    `I/O` / `Type` column) and `description` are the table's own cells, and
    `page` is the page that row appears on. `type` is the one derived field —
    a structural label from `registry/pin_types.yaml` — so it carries
    `type_evidence`, the phrase that decided it, which is invariant 8's
    `derivation` for this record. An unrecognised or ambiguous row is
    `UNKNOWN` with no evidence, never a plausible guess.
    """

    # Stable, addressable id within the document's `pins.json` ("pin_12"),
    # minted by `provenance.pin_record_id`. Emission order is fully determined
    # by the document, so a rebuild of identical input reproduces every id.
    id: str = ""
    pin: str = ""  # one pin designator, e.g. "A1"
    pin_verbatim: str = ""  # the key cell as printed, e.g. "A1, A2, B1"
    name: str = ""  # the printed pin name / mnemonic
    type: PinType = PinType.UNKNOWN
    type_evidence: str = ""  # the lexicon phrase that produced `type`
    direction: str = ""  # the printed I/O column, verbatim ("" when absent)
    description: str = ""
    # identity within the document
    section: str = ""
    table_index: int = 0
    row_index: int = 0
    page: int | None = None
    row_verbatim: list[str] = Field(default_factory=list)
    # Per-record extraction confidence, same contract as `SpecRecord`.
    confidence: Confidence = Confidence.UNKNOWN


class PinSet(BaseModel):
    """A document's pin table(s) as records, plus what could not be read.

    `stated_count` is the pin count parsed from the document's own package
    descriptor (`324-ball BGA`), or `None` when the document states none or
    states several that disagree. `warnings` carries the cross-check outcome
    and anything else the read wanted to say; it is published in the part's
    manifest rather than logged and forgotten, because ADR 0005 decided a
    pin-count mismatch **warns and is recorded** — a warning is only weaker
    than a rejection when it can be ignored.

    A `PinSet` with no `pins` is still a `PinSet`: the warnings are part of the
    finding. The publisher is what refuses to write `pins.json` for it, so a
    part with no readable pin table has no pin file rather than a partial one.
    """

    schema_version: str = ""
    part_number: str = ""
    doc_hash: str = ""
    pins: list[PinRecord] = Field(default_factory=list)
    stated_count: int | None = None
    warnings: list[str] = Field(default_factory=list)


class RegisterWord(BaseModel):
    """A register-sized value as printed, plus the integer it parses to.

    Phase 6, ticket 05. The pattern ADR 0005's envelope prescribes, narrowed to
    what a register map prints: a hex (or decimal) word, an address or a reset
    value, that a machine has to be able to compare while the printed string
    stays the answer.

    - `verbatim` is the string the document printed (`0x1A04`, `1A04h`, `00`).
      It is authoritative and never mutated.
    - `value` is that string read as an integer, and is **allowed to be
      `None`**: a cell the grammar cannot read stays verbatim-only rather than
      being guessed at, which is what makes `dsa regs --addr` safe to trust.
    - `page` is the printed page the value was read off, `evidence` the printed
      text it was read from, and `derivation` the named rule that produced it —
      invariant 8's `source` + `derivation`, per field. A value copied straight
      out of the register's own row needs no evidence beyond the record, so it
      carries the rule name alone; one read from somewhere else in the document
      (a reset printed in the register's declaration heading) carries the line
      it came from and that line's page.
    """

    verbatim: str = ""
    value: int | None = None
    page: int | None = None
    evidence: str = ""
    derivation: str = ""


class BitRange(BaseModel):
    """The bits one field occupies, printed and parsed (phase 6, ticket 06).

    `RegisterWord`'s shape one level down, and the field on which this repo is
    least willing to guess: a driver written against a wrong bit range
    misconfigures silicon silently. So the printed cell is kept exactly as the
    document laid it out (`15:3`, `[3]`, `7..0`) and `hi` / `lo` are the
    parsed reading of *that cell alone* — never of a neighbouring one, never
    widened to make a field list tile a register. A cell the anchored grammar
    cannot read leaves both `None`, which makes the field unusable and is
    therefore what refuses the whole register's field set rather than
    publishing a range nobody read.

    `derivation` names which rule produced the pair: `parse_bit_range` for a
    document that prints the range as text, `bit_header_span` for one that
    prints a bit-position header row and lets a field cell span columns under
    it (invariant 8's `derivation`, per field).
    """

    verbatim: str = ""
    hi: int | None = None
    lo: int | None = None
    derivation: str = ""

    @property
    def n_bits(self) -> int:
        """How many bits this range covers; `0` when it never parsed."""
        if self.hi is None or self.lo is None:
            return 0
        return self.hi - self.lo + 1


class RegisterField(BaseModel):
    """One bit field of one register, individually citable (phase 6, ticket 06).

    The unit a driver is written against. Everything on it is verbatim from the
    register's own field table — `name` (including `RESERVED`, which is a name
    the document printed and not a gap), the printed access code, the printed
    field reset and the description as the page prints it — except `bits`,
    which carries its own derivation because a bit range is the one thing here
    that has to be read rather than copied.

    A field reset is a **string** deliberately: it is a field-width value whose
    base is only meaningful beside the field's width (`0x3` in a two-bit
    field), and a register's programmable word is what `RegisterRecord.reset`
    already publishes as a number.
    """

    name: str = ""
    bits: BitRange = Field(default_factory=BitRange)
    access: str = ""  # the printed Type / Access cell, verbatim ("" when absent)
    reset: str = ""  # the printed field reset, verbatim ("" when absent)
    description: str = ""
    # identity within the document — the field table's row, and the page it is
    # printed on, so one field is as citable as one register.
    table_index: int = 0
    row_index: int = 0
    page: int | None = None
    row_verbatim: list[str] = Field(default_factory=list)


class RegisterRecord(BaseModel):
    """One register of one device, individually citable (phase 6, ticket 05).

    The unit a firmware engineer works in during bring-up. Everything here is
    verbatim from the register-summary table except what `RegisterWord` marks
    as parsed or as read from elsewhere in the document:

    - `address` is the row's key, verbatim and parsed, so `0x1A04`, `0x1a04`
      and `6660` are one register.
    - `name` / `access` / `description` are the printed cells; `access` is `""`
      when the table prints no access column, which is an absence in the
      document and never a default.
    - `reset` is `None` unless the document states one — either in the summary
      table's own reset column or in the register's printed declaration
      heading (`R0 Register (Offset = 0x0) [Reset = 0x0000]`), which is the
      form every TI programmer's guide uses and where the value actually lives.

    Phase 6, ticket 06 adds the register's **bit fields**, and every one of its
    fields exists so that an incomplete or unread field set cannot read as a
    complete one:

    - `fields` is empty unless the register's own field table was read *and*
      validated; `fields_reason` then says why, per criterion — a register is
      never dropped for having no readable fields.
    - `width` is the register's width in bits and `width_evidence` the printed
      word it was read from. No width, no fields: a field list that cannot be
      checked against the register's width is exactly the artifact this ticket
      refuses to ship.
    - `unaccounted_bits` names the bits of that width no field claims, so the
      coverage of a field list is checkable by anyone reading the file rather
      than assumed to be total.
    - `fields_route` is the derivation (`bit-column` / `bit-diagram`) and
      `fields_evidence` the caption of the table the fields were read from.
    """

    # Stable, addressable id within the document's `registers.json`
    # ("reg_12"), minted by `provenance.register_record_id`.
    id: str = ""
    address: RegisterWord = Field(default_factory=RegisterWord)
    name: str = ""  # the printed acronym / register name
    access: str = ""  # the printed access column, verbatim ("" when absent)
    description: str = ""
    reset: RegisterWord | None = None
    # identity within the document
    section: str = ""
    table_index: int = 0
    row_index: int = 0
    page: int | None = None
    row_verbatim: list[str] = Field(default_factory=list)
    # Per-record extraction confidence, same contract as `SpecRecord`.
    confidence: Confidence = Confidence.UNKNOWN
    # --- bit fields (phase 6, ticket 06) --------------------------------
    fields: list[RegisterField] = Field(default_factory=list)
    width: int | None = None
    width_evidence: str = ""  # the printed word `width` was read from
    width_derivation: str = ""  # the named rule that read it
    unaccounted_bits: list[str] = Field(default_factory=list)
    fields_route: str = ""  # the named rule that produced `fields`
    fields_evidence: str = ""  # the field table's printed caption
    fields_reason: str = ""  # why `fields` is empty, when it is
    # How far the field set can be trusted without opening the printed page.
    # Same contract as every other grade: metadata, never a filter.
    fields_confidence: Confidence = Confidence.UNKNOWN


class RegisterSet(BaseModel):
    """A document's register-summary table(s) as records, plus what was odd.

    Same contract as `PinSet`: a set with no `registers` is still a set — the
    warnings and the recorded rejection reasons are the finding — and the
    publisher is what declines to write `registers.json` for it, so a document
    whose register table was rejected serves no half-parsed register map.

    `n_reset_stated` is how many of these registers the document actually
    states a reset value for. It is recorded rather than inferred because the
    gap is the honest half of invariant 8: a caller that lists reset values
    must be able to say "18 of 35 registers state one" instead of quietly
    showing 18 rows. `warnings` carries that sentence for the manifest.

    `n_field_sets` is the same clause for bit fields (phase 6, ticket 06): how
    many of these registers publish a validated field list, so "bit fields for
    28 of 35 registers" is a fact the corpus carries rather than a shape a
    caller has to notice.
    """

    schema_version: str = ""
    part_number: str = ""
    doc_hash: str = ""
    registers: list[RegisterRecord] = Field(default_factory=list)
    n_reset_stated: int = 0
    n_field_sets: int = 0
    warnings: list[str] = Field(default_factory=list)


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
      parses and resolves it), `page` is the printed page it was read off and
      `section` the printed section number it sits in, so a derived artifact can
      cite it as `§4.1, p.4` — the one citation format this repo has. Two values
      of one row can come from two sections pages apart, which is the whole
      point of a limits card, so the citation belongs to the value and not to
      the row that gathered it.
    - `sources` (additive, phase 6 ticket 07) names the *other* records that
      entered a value computed from more than one — a limits card's margin is
      one number over two rows on two pages, and citing one of them and
      dropping the other would make the value untraceable by exactly half.
      `source` stays the primary record, every entry here is a reference of the
      same form, and the invariant-8 walk resolves all of them.
    - `derivation` names the rule that produced the value
      (`parse_quantity+si_normalize`). A field with no named rule has no
      business being on a derived artifact.
    - `confidence` is carried over from the source record; it is metadata about
      the extraction and never a filter.

    A field that cannot be filled stays null and says so — it is never
    interpolated and never defaulted to a plausible value. A **computed** value
    has no `verbatim` at all: no page printed it, and putting a rendered number
    there would claim a datasheet said something it did not.
    """

    verbatim: str = ""
    value_si: float | None = None
    unit_si: str = ""
    source: str = ""
    sources: list[str] = Field(default_factory=list)
    page: int | None = None
    section: str = ""
    derivation: str = ""
    confidence: Confidence = Confidence.UNKNOWN

    @property
    def refs(self) -> list[str]:
        """Every record reference this value rests on, primary first.

        What an invariant-8 check walks: a value is traceable only if *all* of
        its references resolve, not just the one that happened to be first.
        """
        return [ref for ref in [self.source, *self.sources] if ref]


class CardRow(BaseModel):
    """One row of a design card: what it is about, and its cited values.

    A card row is a *view* of records that already exist, so it owns no value
    of its own — every entry of `values` is a `DerivedValue` carrying its own
    source, page and rule (ADR 0005). The keys of `values` are the printed
    columns the card publishes (`min`, `typ`, `max`, `value`) or, on the limits
    card, the two sides and their margin (`abs_max`, `recommended_max`,
    `margin`).

    - `group` is the card table this row belongs to, as the lexicon titles it
      ("Supply rails"); rows of one group are rendered together.
    - `label` / `detail` are the row's identity as the datasheet printed it —
      the symbol and the parameter name, never a rewritten one.
    - `section` / `section_title` are where it was printed, which is what makes
      two rows carrying the same symbol on two tables distinguishable.
    - `selector` is the lexicon rule that put this row on this card — the
      structural-label evidence ADR 0005 (c) requires, exactly as a pin
      publishes the phrase that decided its type.
    - `flags` are the findings a reader must not miss (`zero-margin`).
    - `note` says what a reader would otherwise have to guess: that this row is
      the largest of several printed values, or why a margin is absent.
    """

    group: str = ""
    label: str = ""
    detail: str = ""
    section: str = ""
    section_title: str = ""
    selector: str = ""
    values: dict[str, DerivedValue] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    note: str = ""


class DesignCard(BaseModel):
    """One task-shaped view over a part's records (phase 6, ticket 07).

    The datasheet reorganised around what a designer needs open while drawing a
    schematic, and the first artifact in this repo that exists only because a
    rule selected it. Everything on it is therefore derived under ADR 0005: no
    value is written here that is not a quote of a record, a documented pure
    function of records, or a lexicon label, and each one says which.

    - `card_version` is the derivation-rule version the card was produced under
      (`config.CARD_VERSION`), which is what makes a stale card detectable.
    - `rows` may be empty, and an empty card is a **valid** card: `empty_reason`
      then states what was looked for and not found. A part with no interface
      section gets an interface card that says so, never a fabricated one and
      never a missing file that reads as "not built yet".
    - `notes` carries the population sentences invariant 8 requires of any
      consumer that sorts or compares (`2 of 14 parameters could not be
      compared`), and `unparsed` the one line per excluded item that makes
      "listed below" literally true.
    """

    schema_version: str = ""
    card: str = ""  # "power" | "thermal" | "interface" | "limits"
    title: str = ""
    purpose: str = ""
    part_number: str = ""
    card_version: str = ""
    rows: list[CardRow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    unparsed: list[str] = Field(default_factory=list)
    empty_reason: str = ""

    @property
    def n_rows(self) -> int:
        return len(self.rows)


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
    | `pin_query` | `dsa pins` | pin records on a cited page carry them; `count` must match exactly |
    | `reg_query` | `dsa regs` | register records on a cited page carry them; `count` must match exactly |
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
    # Phase 6 pin lookup ({pin} | {name} | {type} | {q}, plus an optional
    # `count` the result set must match exactly — "how many supply pins" is a
    # pin question a designer really asks, and a count that drifts is a pin
    # table that quietly gained or lost rows).
    pin_query: dict[str, str] | None = None
    # Phase 6, ticket 05 register lookup ({addr} | {name} | {q}, plus an
    # optional `count` the result set must match exactly). `addr` is the shape
    # that matters most: it is checked by *parsed* value, so `0x1A04`,
    # `0x1a04` and `6660` are the same question.
    reg_query: dict[str, str] | None = None
    ask_query: dict[str, str] | None = None  # Phase 5 answer pack ({route})
    search_query: dict[str, str] | None = None  # Phase 5 full text ({query, rank})
    notes: str = ""
