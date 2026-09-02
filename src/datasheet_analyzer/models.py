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

from pydantic import BaseModel, Field, computed_field

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


class ParseConfidence(str, Enum):
    """How much the *parse* of a printed value can be trusted (phase 6).

    Deliberately not `Confidence`, which grades how well a record was
    **extracted**. This grades a second, later question: whether the verbatim
    string that extraction captured could be turned into a number by
    `structure/quantities.py`. A record can be extraction-`high` and
    parse-`none` — `"See Figure 7"` is printed exactly as the datasheet has
    it and is not a quantity.

    `NONE` is the honest default and covers both "tried and could not parse"
    and "never attempted" (a corpus published before the parsed layer
    existed). Nothing downstream may tell those apart *into a number*: in
    both cases there is no parsed value, `value_si is None`, and a consumer
    that sorts or compares must report the row as unparsed rather than
    guess at it.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Staleness(str, Enum):
    """Whether a corpus's document is still the current upstream revision.

    Three states, and the default is the one that protects the designer:

    - `CURRENT` — a check ran and the upstream revision identifier matched;
    - `STALE` — a check ran and upstream reports a **different** revision;
    - `UNKNOWN` — nobody has checked, or the check could not complete.

    `UNKNOWN` is the honest default for every corpus that has never run a
    revision check, and it is deliberately *not* `CURRENT`: reading "no news"
    as "still current" would let a superseded datasheet answer a design
    question with full confidence and a valid page cite.

    A **hash** difference alone never moves this field. A TI datasheet's bytes
    change on every download because the package-materials addendum is
    regenerated with the current date, while the revision identifier stays
    put; a design that read that as staleness would raise a false alarm on
    every TI part every day and train the user to ignore the one warning here
    that protects silicon. Bytes that moved under an unchanged revision are
    recorded as `RevisionState.content_drift` instead.
    """

    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


# Shape of a parsed quantity (`SpecRecord.value_kind`, `DerivedValue.value_kind`).
# `structure/quantities.py` (phase 6, ticket 02) owns the parse; these names are
# the frozen vocabulary it emits, so a consumer never string-matches a literal.
VALUE_KIND_POINT = "point"  # `105`, `1350 mA`
VALUE_KIND_RANGE = "range"  # `−40 to +85` — `value_si` low, `value_si_hi` high
VALUE_KIND_BOUND = "bound"  # `< 5`, `≥ 1.8` — `value_si` is the bound
VALUE_KIND_TOLERANCE = "tolerance"  # `±0.5` — `value_si` is the magnitude
VALUE_KINDS: tuple[str, ...] = (
    VALUE_KIND_POINT,
    VALUE_KIND_RANGE,
    VALUE_KIND_BOUND,
    VALUE_KIND_TOLERANCE,
)

# The two named derivation rules that every derived artifact needs and that no
# single ticket owns. Clause (b) of invariant 8 — a value computed by a
# documented pure function — names that function instead, chaining with `+`
# (`parse_quantity+si_normalize`); `derive/provenance.py` enforces the shape.
DERIVATION_VERBATIM = "verbatim_copy"  # clause (a): copied, unchanged
DERIVATION_LEXICON = "lexicon_label"  # clause (c): a label from a checked-in lexicon

# `PinRecord.type` (phase 6, ticket 04). A closed vocabulary drawn from a
# checked-in lexicon over the pin's name + description — clause (c) of
# invariant 8. `unknown` is a legitimate output; a guess is not.
PIN_TYPE_UNKNOWN = "unknown"
PIN_TYPES: tuple[str, ...] = (
    "power",
    "ground",
    "analog",
    "digital",
    "clock",
    "rf",
    "nc",
    "reserved",
    PIN_TYPE_UNKNOWN,
)

# The four design cards (phase 6, ticket 07). Frozen here so the CLI's
# `--card` choices, the MCP tool's enum and the builder's dispatch table are
# the same list.
CARD_POWER = "power"
CARD_THERMAL = "thermal"
CARD_INTERFACE = "interface"
CARD_LIMITS = "limits"
CARD_KINDS: tuple[str, ...] = (CARD_POWER, CARD_THERMAL, CARD_INTERFACE, CARD_LIMITS)


# How the layout engine arrived at a reconstructed grid (`TableBlock.reconstruction`).
# The header-anchored split is the table's own declaration of its columns; a
# rescue is a coarser retry-ladder split that only won because that declaration
# did not pass the gate — which is exactly what makes its rows `low`.
RECONSTRUCTION_HEADER = "header-anchored"
RECONSTRUCTION_RESCUED = "rescued"


# --- Stable record ids (phase 6, ticket 01) --------------------------------
# A derived artifact cites the record it drew from as `<artifact>#<id>`, so
# every citable record needs an id that is the *same string* after a rebuild
# of identical input. The ids below are therefore a pure function of the
# record's own coordinates inside its document — never an ordinal position in
# a list, which would shift for every record after a table that gained a row,
# silently repointing already-written cards at the wrong number.
_ID_UNSAFE = re.compile(r"[^A-Za-z0-9._+]+")


def _id_part(value: object) -> str:
    """One id component, with anything that would break the format folded out."""
    return _ID_UNSAFE.sub("_", str(value).strip())


def record_id(prefix: str, *parts: object) -> str:
    """`rec_s4.5-t2-r13` — the shape every derived record id takes."""
    return f"{prefix}_" + "-".join(_id_part(p) for p in parts)


def spec_record_id(section_key: str, table_index: int, row_index: int) -> str:
    """Id of one `SpecRecord`: its section, its table in that section, its row.

    `section_key` identifies the *section*, not its printed number, and the
    difference is the whole of phase 6.5 ticket 08. `table_index` counts
    within a section, so a document whose sections carry no numbers restarted
    it at 0 in every one of them and several records computed one id:
    **AD9081 published 549 records carrying 259 distinct ids**, with
    `rec_s-t0-r0` alone carried by 14. Every datasheet read without a numbered
    table of contents had it.

    The key is the section's published file stem, which is already unique per
    section — two sections sharing it would collide on disk before they
    collided here. Numbering tables document-globally would also have worked
    and was rejected: `table_index` is a position *within* a section, read as
    one by the CSV twin names and by every lookup back into `section.tables`.
    """
    return record_id("rec", f"s{section_key}", f"t{table_index}", f"r{row_index}")


def pin_record_id(table_index: int, row_index: int, pin: str) -> str:
    """Id of one `PinRecord`.

    The designator is part of the key because a multi-pin row expands: the
    printed row `A1, A2, B1` becomes three individually citable records that
    share one `(table_index, row_index)`.
    """
    return record_id("pin", f"t{table_index}", f"r{row_index}", pin)


#: Length of a `doc_key`: the leading hex characters of a document's content
#: hash. The same discriminator `publish.doc_dir_name_for_source` names a
#: document's directory with (`register_map-0e7de32d`), so an id and the
#: directory it lives in name the document the same way.
DOC_KEY_LEN = 8


def register_record_id(doc_key: str, table_index: int, row_index: int) -> str:
    """Id of one `RegisterRecord`: its document, its table, its row.

    `doc_key` is here for the reason ticket 08 put a section key in
    `spec_record_id` one level up: `(table_index, row_index)` is unique inside
    **one document**, and that was enough only while no part had two documents
    printing a register map. LMX1204 does — the datasheet's `Table 7-1` and the
    register map's `Table 1-1` print the same 35 registers — and the part
    published **70 records computing 35 ids**, every one carried by a record in
    each document.

    The key is the document's content-hash prefix: a pure function of the
    document's bytes rather than of a position in a list, and the same
    discriminator its published directory already carries, so two documents
    that collided here would have collided on disk first. Keying on the
    published directory itself was the other option and was rejected because a
    record must be able to compute its own id before anything is published.

    A record written before this carries no `doc_key` and keeps the old shape
    (`reg_t0-r5`), so a citation already written still resolves — the same
    fallback ticket 08 gave `section_key`.
    """
    if not doc_key:
        return record_id("reg", f"t{table_index}", f"r{row_index}")
    return record_id("reg", f"d{doc_key}", f"t{table_index}", f"r{row_index}")


def bit_field_id(register_record_id_: str, field_index: int) -> str:
    """Id of one `BitField`, hung off its register's id: `reg_t0-r5.f3`."""
    return f"{register_record_id_}.f{field_index}"


#: Prefix of an errata item's id. Not an *artifact* record id like the four
#: above: an errata item is a verbatim item of an errata document, numbered
#: within its part, and nothing cites one as a derived value's `source`.
ERRATA_ID_PREFIX = "err"


def errata_item_id(ordinal: int) -> str:
    """Id of the `ordinal`-th (0-based) errata item of a *part*: `err_1`.

    An ordinal rather than a coordinate, because an errata item has none: it
    is a run of printed lines a segmentation rule drew a line around, not a
    row of a table with an index. The sequence runs over the part, not over
    one document, so a part holding two errata documents numbers straight
    through them and no two items share an id.
    """
    return record_id(ERRATA_ID_PREFIX, ordinal + 1)


def source_ref(artifact: str, record_id_: str) -> str:
    """The `source` string a derived value carries: `specs.json#rec_s4.5-t2-r13`.

    `artifact` may be bare (`specs.json`) when the consumer already knows
    which document it is reading, a corpus-relative path
    (`docs/datasheet-1f2e3d4c/specs.json`) when it does not, or an
    `@library/…` reference into the shared document store.
    """
    return f"{artifact}#{record_id_}"


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
    | `category` | `category` | every part filed in that category |
    | `all` | — | every part in the library |

    `family` and `category` both mean "more than one part" and are not the
    same thing: a family is a *pattern over part numbers*, read off the page
    (`AFE79xx`); a category is a *slot in the user's taxonomy*, a judgement
    about what the device is (`amplifiers`). A layout-guidelines note that
    applies to every amplifier names no family and belongs to no part.

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

    kind: Literal["parts", "family", "category", "all"] = "all"
    parts: list[str] = Field(default_factory=list)  # kind == "parts"
    family: str = ""  # kind == "family", e.g. "AFE79xx"
    category: str = ""  # kind == "category", e.g. "amplifiers"
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
    def for_category(cls, category: str, *, evidence: str = "") -> Applicability:
        """Applicability covering every part filed in one category."""
        return cls(kind="category", category=category, evidence=evidence)

    @classmethod
    def for_all(cls, *, evidence: str = "") -> Applicability:
        """The honest default: a document that applies to every part."""
        return cls(kind="all", evidence=evidence)

    def covers(self, part_number: str, *, part_category: str = "") -> bool:
        """True when this document applies to `part_number`.

        Case-insensitive throughout — part numbers are printed both ways and a
        corpus keyed on `AD9081` must not miss a document that wrote `ad9081`.
        A blank part number is covered by nothing: a part is an identity, and
        "applies to the nameless part" is never a useful answer.

        `part_category` is which category the part is filed in, and only a
        `category` applicability reads it. It is a parameter rather than a
        lookup because this model must stay a pure function of its own fields:
        it is embedded in `LibraryDocument`, which the pipeline persists, and
        reaching into a store from here would put disk access inside a
        predicate that runs per document per part. A caller that does not know
        the category gets `False` for a category document — conservative, and
        the reason `LibraryStore.for_part` resolves it before asking.
        """
        wanted = (part_number or "").strip().upper()
        if not wanted:
            return False
        if self.kind == "all":
            return True
        if self.kind == "category":
            mine = (self.category or "").strip().lower()
            return bool(mine) and mine == (part_category or "").strip().lower()
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
        """Human-readable one-liner: `AD9081`, `AFE79xx`, `all amplifiers`."""
        if self.kind == "all":
            return "all parts"
        if self.kind == "category":
            return f"all {self.category}" if self.category else "unnamed category"
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
        if self.kind == "category":
            return bool(self.category.strip())
        if self.kind == "family":
            return bool(self.family.strip())
        return True


class RevisionState(BaseModel):
    """What a revision check found about one document (phase 7, ticket 02).

    Written **only** by `dsa check-revisions`, which is an explicit, opt-in,
    network command; `dsa build` never fills it in, and that is what keeps a
    build offline by construction. A freshly built corpus therefore reads
    `UNKNOWN` until somebody checks, and says so everywhere it is surfaced.

    It lives on `LibraryDocument`, not on `SourceDocument`, for the two reasons
    `applicability` and `labels` do. `SourceDocument` is embedded in every
    cached `RawDocument` under `.cache/extract/` and its shape is pinned by
    `tests/unit/test_contracts.py::test_source_document_shape_is_unchanged`; and
    a part's `sources.json` is a *derived* view regenerated from the Library at
    publish time (ADR 0005), so a state written there would be erased by the
    next build and would not be read back at all. Keyed by `content_hash`, the
    reading also belongs to the *document* rather than to a part - upstream has
    one answer about a document two parts happen to share.
    """

    #: Three-state freshness of this document. See `Staleness`.
    staleness: Staleness = Staleness.UNKNOWN
    #: When the last check actually completed. `None` until one does - never
    #: back-filled with the build date or a plausible one.
    checked_at: datetime | None = None
    #: The revision identifier the upstream document reported at that check.
    #: `""` when no check has run, or when upstream printed none we could read.
    upstream_revision: str = ""
    #: sha256 of the upstream bytes at that check. Recorded because it is a
    #: fact, *not* because it decides staleness: see `content_drift`.
    upstream_sha256: str = ""
    #: Upstream's bytes differ while the revision identifier does **not**. A
    #: regenerated document, not a revised one - reported distinctly so the
    #: wording never implies a new revision exists.
    content_drift: bool = False
    #: Why the state is what it is when that needs saying: the reason a check
    #: could not run (no registry URL, network unavailable), or the drift note.
    #: Read back verbatim by every surface rather than re-derived per front end.
    note: str = ""


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
    #: What the last revision check found about this document. Additive and
    #: defaulted, so every record written before it existed still loads under
    #: the same LIBRARY_SCHEMA_VERSION - a bump would make the store skip every
    #: file on the shelf.
    revision_state: RevisionState = Field(default_factory=RevisionState)
    #: The name a human filed *this copy* under (`dsa build --rev F`, phase 7
    #: ticket 03). Recorded as given and never derived from the document:
    #: `SourceDocument.revision` is what the page printed, and conflating a
    #: filing label with a reading of the page is how a revision diff ends up
    #: naming the wrong two sides.
    #:
    #: It lives here rather than on `SourceDocument` for the reason
    #: `revision_state` does - that shape is frozen by
    #: `tests/unit/test_contracts.py::test_source_document_shape_is_unchanged`
    #: and is embedded in every cached `RawDocument` - and rather than in
    #: `sources.json`, which is a *derived* view regenerated at publish (ADR
    #: 0005) and would erase it on the next build. Written only by
    #: `LibraryStore.set_revision_label`; `put()` preserves whatever is stored,
    #: exactly as it preserves `labels`.
    #:
    #: It is deliberately **not** part of the published document directory
    #: name. The content hash already keeps two revisions from colliding, so a
    #: `-rev<label>` suffix would buy legibility at the price of renaming a
    #: directory that may be shared by several parts (ADR 0008's library store)
    #: and orphaning every citation into it.
    revision_label: str = ""
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

    def covers(self, part_number: str, *, part_category: str = "") -> bool:
        """Shorthand for `self.applicability.covers(part_number)`."""
        return self.applicability.covers(part_number, part_category=part_category)


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
    # Grid rows whose **first cell was lent by a spanning parent**, not
    # printed (`pdf_layout` rowspan materialization). The text is right for
    # reading — a spec record under a parameter that spans four condition
    # rows needs the parameter's name — and wrong for keying: HMC520A's
    # exposed-pad row prints no pin number, and lending it the row above's
    # `15` made two rows claim one designator. A consumer that keys on the
    # first column must read these rows as *unkeyed*, which is what the page
    # says. Empty for HTML backends, whose spans are declared by the source.
    lent_first_cells: list[int] = Field(default_factory=list)
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
    # Version of the *structure-stage* work embedded in this record by
    # `pipeline._extract_document` after the backend returned — table page and
    # per-row page pinning (`structure/pagemap.py`). Two producers write into
    # one cached extraction and both must be able to invalidate it; until this
    # field existed only the backend could, so a fix under `structure/` was
    # invisible behind a cached extraction (`config.STRUCTURE_STAGE_VERSION`).
    # A record written before it reads "" and is re-extracted once.
    structure_version: str = ""
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
    # Phase 7 ticket 04: how many errata items this part published, and how
    # many of them a deterministic rule could place against a record. Recorded
    # per part for the reason every other count here is - the ratio is the
    # linker's own honesty, and it belongs in the manifest as a measured number
    # rather than in a report as a claim. Both 0 for a part with no errata
    # document, which is silence rather than "no known issues".
    n_errata_items: int = 0
    n_errata_linked: int = 0


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
    section: str = ""  # the printed section number, "" when the page prints none
    # The section's published file stem — what makes this record's id unique
    # inside its document even when the printed number is absent. See
    # `spec_record_id`. Falls back to `section` when a record predates the
    # field, which keeps an older `specs.json` resolvable.
    section_key: str = ""
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
    # --- Phase 6: the parsed numeric layer (ticket 02) ---------------------
    # Strictly additive and always allowed to fail. The verbatim strings above
    # stay authoritative and are never mutated; these carry the *parse* of
    # them, produced by `structure/quantities.py`. Every one of them is absent
    # (`None` / `""` / `parse_confidence == NONE`) when the print could not be
    # parsed, and a consumer that sorts, compares or checks margins must
    # report that population explicitly rather than drop it — invariant 8.
    #
    # `value_si` is the parse of the record's *primary* cell, and
    # `value_si_cell` names which cell that was, so a number is never read as
    # a max when the datasheet printed it as a typ. The per-cell parses below
    # are what the `limits` card joins on (abs-max against recommended-max).
    value_si: float | None = None
    value_si_hi: float | None = None  # high end of a `range`; `None` otherwise
    value_si_cell: str = ""  # "min" | "typ" | "max" | "value" | ""
    unit_si: str = ""  # canonical unit of the parsed value ("A", "°C")
    value_kind: str = ""  # one of `VALUE_KINDS`, "" when nothing parsed
    parse_confidence: ParseConfidence = ParseConfidence.NONE
    min_si: float | None = None
    typ_si: float | None = None
    max_si: float | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """Stable, addressable id — what a derived artifact's `source` points at.

        Computed, never stored: it cannot drift from the coordinates it
        describes, and a rebuild of identical input necessarily reproduces it.
        Serialized into `specs.json` so a reader that never constructs the
        model can still resolve a citation.
        """
        return spec_record_id(self.section_key or self.section, self.table_index, self.row_index)


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
    # --- Phase 6: the axis catalog (ticket 08) -----------------------------
    # Geometric and deterministic: tick labels cluster along the figure
    # region's left and bottom edges and the axis title is the text run
    # parallel to that edge. Additive and independently optional — an axis
    # whose label reads but whose ticks do not still records the label and
    # leaves the range null. **Anything uncertain stays null** and says so
    # through `axis_confidence`; a plausible range is never interpolated,
    # because the point of the catalog is to spend a vision call on the right
    # figure rather than to answer "what is the gain at 3.5 GHz" without one.
    x_label: str = ""
    x_unit: str = ""
    x_min: float | None = None
    x_max: float | None = None
    y_label: str = ""
    y_unit: str = ""
    y_min: float | None = None
    y_max: float | None = None
    axis_confidence: Confidence = Confidence.UNKNOWN


class PlotSet(BaseModel):
    """A document's full plot catalog + pixel map."""

    schema_version: str = ""
    part_number: str = ""
    doc_hash: str = ""
    plots: list[PlotRecord] = Field(default_factory=list)


# --- Phase 6: derived artifacts (ADR 0007, invariant 8) --------------------
#
# Everything below this line describes data the pipeline *derives* rather than
# extracts. The contract, in full:
#
#   A derived artifact may contain only (a) values copied verbatim from a
#   spec, table or pin record; (b) values computed from those by a documented
#   pure function; (c) structural labels from a checked-in lexicon. Every
#   field carries `source` (record id + page) and `derivation` (the named
#   rule). No model call may appear in the derivation path. A field that
#   cannot be filled stays null and says so — never interpolated, never a
#   plausible default.
#
# `DerivedValue` is how a field says all of that in one place; the record
# models under it are the derived artifacts themselves.


class DerivedValue(BaseModel):
    """One value on a derived artifact, carrying the provenance invariant 8 demands.

    ```json
    { "verbatim": "1350 mA", "value_si": 1.35, "unit_si": "A",
      "source": "specs.json#rec_s4.9-t0-r12", "page": 21,
      "derivation": "parse_quantity+si_normalize", "confidence": "high" }
    ```

    Three rules make this envelope worth its bytes:

    - **`verbatim` is the answer; `value_si` is a convenience.** The printed
      string is what a designer checks against the page, so it is never
      rewritten to look tidier. `value_si` exists so a machine can sort and
      compare, and it is allowed to be absent for every value that is real
      but not numeric (`"See Figure 7"`, `"—"`).
    - **`source` + `page` are not optional for a filled value.** A number
      nobody can trace to a printed page is exactly the failure mode this
      whole phase exists to prevent, so `derive/provenance.py` checks the
      pair and a card that cannot supply it must leave the field null.
    - **A null value says why.** `null_reason` is the "and says so" half of
      the invariant: `"no recommended-max printed"` is an answer, a silently
      absent key is not, and a plausible default is a lie.
    """

    verbatim: str = ""
    value_si: float | None = None
    value_si_hi: float | None = None  # high end of a `range`; `None` otherwise
    unit_si: str = ""
    value_kind: str = ""  # one of `VALUE_KINDS`, "" when nothing parsed
    source: str = ""  # `<artifact>#<record id>`, e.g. "specs.json#rec_s4.9-t0-r12"
    page: int | None = None  # the printed page the source record sits on
    derivation: str = ""  # the named rule: `verbatim_copy`, `abs_max_margin`, …
    confidence: Confidence = Confidence.UNKNOWN
    null_reason: str = ""  # why an unfilled field is unfilled; never blank when null
    #: The *other* records that entered a value computed from more than one.
    #: A margin is one number over two rows on two pages, and citing one of
    #: them and dropping the other would make the value untraceable by
    #: exactly half. `source` stays the primary record; every entry here is a
    #: reference of the same form. Additive: `[]` on every single-source
    #: value, which is almost all of them.
    sources: list[str] = Field(default_factory=list)
    #: The printed section number the source record sits in, so a derived
    #: artifact can cite it as `§4.1, p.4` without re-reading the record. Two
    #: values of one row can come from sections pages apart, which is why the
    #: citation belongs to the value and not to the row that gathered it.
    section: str = ""

    @property
    def refs(self) -> list[str]:
        """Every record reference this value rests on, primary first.

        What an invariant-8 check must walk: a value is traceable only if
        *all* of its references resolve, not just the one that happened to be
        first.
        """
        return [ref for ref in [self.source, *self.sources] if ref]

    @property
    def filled(self) -> bool:
        """Whether this envelope actually carries a value."""
        return bool(self.verbatim) or self.value_si is not None

    @classmethod
    def missing(
        cls,
        reason: str,
        *,
        derivation: str = "",
        source: str = "",
        page: int | None = None,
    ) -> DerivedValue:
        """The honest empty value: null, with the reason it is null.

        Preferred over omitting the field entirely, because a consumer cannot
        tell an omission from an oversight, and both read as "the datasheet
        does not say" when only one of them is true.
        """
        return cls(
            source=source,
            page=page,
            derivation=derivation,
            confidence=Confidence.UNKNOWN,
            null_reason=reason or "not stated",
        )

    @classmethod
    def copied(
        cls,
        verbatim: str,
        *,
        source: str,
        page: int | None,
        unit_si: str = "",
        confidence: Confidence = Confidence.UNKNOWN,
    ) -> DerivedValue:
        """Clause (a): a value copied verbatim, derivation `verbatim_copy`."""
        return cls(
            verbatim=verbatim,
            unit_si=unit_si,
            source=source,
            page=page,
            derivation=DERIVATION_VERBATIM,
            confidence=confidence,
        )

    @classmethod
    def labeled(
        cls,
        label: str,
        *,
        source: str,
        page: int | None,
        confidence: Confidence = Confidence.UNKNOWN,
    ) -> DerivedValue:
        """Clause (c): a structural label from a checked-in lexicon."""
        return cls(
            verbatim=label,
            source=source,
            page=page,
            derivation=DERIVATION_LEXICON,
            confidence=confidence,
        )


class PinRecord(BaseModel):
    """One pin of one package, from a printed pin table (phase 6, ticket 04).

    During schematic capture the pin table *is* the datasheet, so this is a
    first-class record with the same provenance contract a `SpecRecord`
    carries: table, row, page, and a confidence grade.

    Two fields exist because of honesty rules rather than data:

    - `expanded_from` records the printed first cell when one row became
      several — `"A1, A2, B1"` and `"A1–A4"` expand so every pin is
      individually citable, and the reader can still see the row as printed.
    - `type_evidence` names the lexicon entry that produced `type`. A label
      nobody can trace back to the checked-in lexicon is indistinguishable
      from a guess, and clause (c) of invariant 8 forbids guesses.
    """

    pin: str = ""  # designator as printed: "A1", "12"
    name: str = ""  # signal name: "VSSA"
    type: str = PIN_TYPE_UNKNOWN  # one of `PIN_TYPES` — `unknown` is legitimate
    direction: str = ""  # as printed: "I", "O", "I/O", "—"
    description: str = ""
    # identity within the document, exactly as `SpecRecord` carries it
    section: str = ""
    table_index: int = 0
    row_index: int = 0
    page: int | None = None
    row_verbatim: list[str] = Field(default_factory=list)
    expanded_from: str = ""  # printed cell when this row expanded, "" otherwise
    type_evidence: str = ""  # the lexicon entry behind `type`
    confidence: Confidence = Confidence.UNKNOWN

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """Stable, addressable id: `pin_t2-r0-A1`."""
        return pin_record_id(self.table_index, self.row_index, self.pin)


class PinSet(BaseModel):
    """A document's full pin table (`pins.json`).

    `rejection_reasons` is why this file may be *short* — a pin table that
    failed validation is rejected whole and named here, never emitted
    half-parsed, the same contract `pdf_layout` already applies to parametric
    tables. A part with no parseable pin table produces no `pins.json` at all
    rather than a partial one.

    `declared_pin_count` is whatever the package or ordering-information
    section printed, when that is parseable; comparing it against `len(pins)`
    is the package cross-check, and a mismatch is a `warning`, never fatal —
    the pin table is still the best record available.
    """

    schema_version: str = ""
    part_number: str = ""
    doc_hash: str = ""
    pins: list[PinRecord] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    declared_pin_count: int | None = None  # None when nothing parseable was printed


class RegisterValue(BaseModel):
    """A printed register number and its integer value: `0x1A04` -> 6660.

    `value` stays `None` when the print could not be parsed — a register
    address the tool guessed at is worse than one it admits it cannot read.
    """

    verbatim: str = ""
    value: int | None = None


class BitRange(BaseModel):
    """The bit positions a field occupies: `[7:4]` -> hi 7, lo 4.

    `hi` / `lo` are `None` together when the printed range could not be
    parsed. Wrong bit positions are worse than absent ones: a driver written
    against them fails silently in hardware.
    """

    verbatim: str = ""
    hi: int | None = None
    lo: int | None = None

    @property
    def width(self) -> int | None:
        """Number of bits, or `None` when the range did not parse."""
        if self.hi is None or self.lo is None:
            return None
        return abs(self.hi - self.lo) + 1


class BitField(BaseModel):
    """One named field inside a register (phase 6, ticket 06)."""

    name: str = ""
    bits: BitRange = Field(default_factory=BitRange)
    access: str = ""  # as printed: "R/W", "RO", "W1C"
    reset: str = ""  # as printed
    description: str = ""
    page: int | None = None
    confidence: Confidence = Confidence.UNKNOWN


class RegisterRecord(BaseModel):
    """One register from a register-summary table (phase 6, ticket 05).

    `fields` is filled by ticket 06 from the register's own field-description
    table when that table reads whole, and is legitimately empty otherwise: a
    register summary that lists address, name, reset and access is already the
    answer to most bring-up questions, and an empty `fields` list says "the bit
    breakdown was not extracted" rather than implying the register has none.
    Which it is, for a given register, is in the register set's warnings.
    """

    block: str = ""  # register block / peripheral, "" when the map has none
    name: str = ""
    address: RegisterValue = Field(default_factory=RegisterValue)
    width: int | None = None  # register width in bits, None when not printed
    reset: RegisterValue = Field(default_factory=RegisterValue)
    access: str = ""  # as printed: "R/W", "RO"
    fields: list[BitField] = Field(default_factory=list)
    # identity within the document, exactly as `SpecRecord` carries it
    section: str = ""
    table_index: int = 0
    row_index: int = 0
    # The document this row was printed in — its content-hash prefix, which is
    # what makes this record's id unique inside its *part* and not merely
    # inside its document. See `register_record_id`. A record written before
    # the field falls back to the old id shape, which keeps citations already
    # written resolvable.
    doc_key: str = ""
    page: int | None = None
    row_verbatim: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """Stable, addressable id: `reg_d0e7de32-t0-r5`."""
        return register_record_id(self.doc_key, self.table_index, self.row_index)


class RegisterSet(BaseModel):
    """A document's register map (`registers.json`).

    Same honesty contract as `PinSet`: a summary table that fails validation
    (duplicate addresses, non-monotonic addresses where the map declares
    them, an unmappable header set) is rejected whole and named in
    `rejection_reasons`.
    """

    schema_version: str = ""
    part_number: str = ""
    doc_hash: str = ""
    registers: list[RegisterRecord] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CardRow(BaseModel):
    """One line of a design card: a parameter and its provenance-carrying values.

    `values` is keyed by column name (`min`, `typ`, `max`, `value`,
    `margin`, …) so a card can shape its own table without a new model per
    card. Every value in it is a `DerivedValue`, which is what makes the
    invariant-8 walk possible: a test resolves every `source` on the card
    back to a record and a printed page without knowing what card it is
    looking at.
    """

    label: str = ""  # what this row is, as the card names it
    symbol: str = ""  # alias-resolved symbol, "" when the row is not symbol-keyed
    values: dict[str, DerivedValue] = Field(default_factory=dict)
    note: str = ""  # honest per-row note: "zero margin", "typ only"
    flags: list[str] = Field(default_factory=list)  # machine-readable hazards


class Card(BaseModel):
    """A task-shaped view over records that already exist (`cards/<kind>.json`).

    A card derives nothing new: it *selects* records a designer would
    otherwise hunt for across five sections, and computes only what a
    documented pure function can compute from them (the `limits` card's
    margin). An **honest empty card** — no rows, `unresolved` naming what was
    looked for — is the correct output for a part that genuinely lacks the
    data, and is never padded with plausible values.

    `card_version` is `DSA_CARD_VERSION` at build time and participates in the
    publish cache key, so changing a selector or a derivation rule forces
    regeneration instead of silently leaving stale cards on disk.

    `corpus_key` is the other half of that key: the rules can be unchanged
    while the *documents* move between the part and the shared store, which
    rewrites every `source` the card holds. See `derive.cards.corpus_key`.
    """

    part_number: str = ""
    card: str = ""  # one of `CARD_KINDS`
    schema_version: str = ""
    card_version: str = ""  # `DSA_CARD_VERSION` at build; publish cache key
    # Digest of the documents this card was built against, and where they
    # resolved to. A cache key, not data: nothing should read meaning out of it.
    corpus_key: str = ""
    rows: list[CardRow] = Field(default_factory=list)
    # What the card looked for and could not fill, named out loud. The
    # `limits` card's "could not compare" population lives here.
    unresolved: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Every artifact this card drew from, so a reader can find the inputs
    # without re-deriving the selector rules.
    sources: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_utcnow)

    @property
    def is_empty(self) -> bool:
        """True for an honest empty card — no rows at all."""
        return not self.rows


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
    #: SourceDocuments this project will never build, by content hash. A
    #: recursive walk re-proposes every rejected file on every rescan, so an
    #: exclusion that did not persist would have to be re-made forever.
    #: Scoped here rather than globally on purpose: the same document is noise
    #: in one design and the subject of another. Excluding is not deleting —
    #: the file is untouched and any other project may still build it.
    excluded: list[str] = Field(default_factory=list)
    #: The directory this project's documents were scanned from, recorded
    #: verbatim as the user gave it. A shelf of PDFs *is* the project, but
    #: until this existed the association lived only in browser local storage
    #: — it died with the cache and the server never learned it, so reopening
    #: meant retyping a path. Additive and optional: a `project.json` written
    #: before this field reads `""`, which honestly means "not recorded".
    directory: str = ""
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


# ---------------------------------------------------------------------------
# Phase 7 — reach and trust
#
# Everything below is additive: new derived artifacts (a revision diff, a
# family index, an errata link set, an audit scorecard) and the generated-
# golden proposal types. None of them is written by a stage that already
# exists, so a corpus published before them loads unchanged and no schema
# version above moves.
# ---------------------------------------------------------------------------


class AuditGrade(str, Enum):
    """The letter one metric — or one whole corpus — earns.

    Five grades, because a scorecard exists to be *acted on*: `A` needs no
    action, `F` means do not answer from this corpus without opening the PDF,
    and the three in between are the gradations a designer actually uses when
    deciding how much to double-check. What each letter *means* for each
    metric is not here — it is `registry/audit_rubric.yaml`, checked-in data,
    so a threshold argument is a YAML edit rather than a code change.

    **There is no grade for "could not measure".** A metric the corpus cannot
    answer carries `None`, is reported as `n/a`, and is excluded from the
    overall average — never scored `F` (which would defame a corpus for a
    statistic nobody recorded) and never scored `A` (which would flatter one).
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class MetricKind(str, Enum):
    """What shape of reading one audit metric produces.

    The kind decides how the rubric grades it, which is why it travels on the
    metric rather than being inferred from the value: a `RATIO` is graded
    against ordered thresholds, a `BOOLEAN` and a `STATE` against a
    named-value map. Nothing here interpolates between them.
    """

    RATIO = "ratio"
    BOOLEAN = "boolean"
    STATE = "state"


class AuditMetric(BaseModel):
    """One graded reading about one corpus.

    It is a derived value in the sense of invariant 8 and carries the same two
    fields every derived value does: `source` (the artifact it was read from)
    and `derivation` (the named rule that produced it). No model call appears
    anywhere in that path — every number here is a count of records the corpus
    already published, divided by another.

    **`available: false` is a first-class outcome**, and the one thing this
    model exists to keep honest. `value` is then `None`, `grade` is `None`,
    and `unavailable_reason` says which fact the corpus does not carry. A
    metric in that state is excluded from the overall grade; it is never read
    as `0` (which would defame a good corpus for a statistic nobody recorded)
    and never as full marks (which would flatter a bad one).
    """

    key: str
    label: str
    kind: MetricKind = MetricKind.RATIO
    #: The reading, `0.0`–`1.0` for a ratio, `1.0`/`0.0` for a boolean, `None`
    #: for a state metric and for anything unavailable.
    value: float | None = None
    #: The reading of a `STATE` metric (`current` / `stale` / `unknown`), and
    #: the word a boolean reads as. `""` for a ratio.
    state: str = ""
    #: The counts a ratio was computed from, so a reader can see 61% as 38/62
    #: and tell a small denominator from a large one. `None` when the metric
    #: is not a quotient.
    numerator: int | None = None
    denominator: int | None = None
    grade: AuditGrade | None = None
    weight: float = 1.0
    available: bool = True
    unavailable_reason: str = ""
    #: Anything a reader needs beside the number — the full confidence mix,
    #: the rejection reasons, the golden set that produced a pass rate.
    detail: str = ""
    source: str = ""
    derivation: str = ""


class AuditScorecard(BaseModel):
    """Every metric of one corpus, graded, plus the overall letter.

    `grade` is `None` when too few metrics could be computed for an average to
    mean anything (`min_graded_metrics` in the rubric) — an ungraded corpus
    says so rather than reporting a letter earned by three readings out of
    thirteen.

    `headline` is the sentence this artifact exists to produce: the one line
    an agent can put in front of an answer to downgrade its own confidence
    language before it speaks.
    """

    schema_version: str = ""
    rubric_version: str = ""
    part: str = ""
    grade: AuditGrade | None = None
    #: The weighted mean of the graded metrics' grade points, on the rubric's
    #: own scale. `None` whenever `grade` is.
    score: float | None = None
    metrics: list[AuditMetric] = Field(default_factory=list)
    n_graded: int = 0
    n_unavailable: int = 0
    #: The convention this scorecard applied to metrics it could not compute,
    #: stated in the output rather than assumed by the reader.
    unavailable_policy: str = ""
    #: The staleness banner, so the scorecard is one of the surfaces that
    #: cannot disagree about a corpus's freshness.
    staleness: str = ""
    banner: str = ""
    headline: str = ""
    #: What this corpus needs doing to it — a rebuild, a revision check, a
    #: golden set. Each one names the command.
    notes: list[str] = Field(default_factory=list)


class ComparisonCell(BaseModel):
    """What one part printed for one aligned parameter.

    One column of a comparison row. It quotes that part's row and nothing
    else: `values` are the printed cells in their provenance envelopes (`min`,
    `typ`, `max`, `value` for a spec comparison; whatever a design card
    publishes for a card comparison), each carrying its own `source`, `page`
    and rule.

    - `label` / `detail` are the row's identity **as that part printed it**,
      which is the whole point of a cross-part row: two parts name one
      parameter differently and the comparison must show both names rather
      than pick one.
    - `matched_via` is the rung this part's record answered the query on
      (`symbol`, `alias:junction temperature`, …). A comparison that aligned
      two rows must be able to say how each of them was found, or a
      mis-alignment is invisible.
    - `citation` is the rendered citation of the record this cell quotes.
    - `delta` is this cell's value **minus the reference part's**, in the SI
      base both parsed to, and exists only where both sides parsed the same
      printed column. It is a computed value, so it carries no `verbatim`: no
      page printed a difference between two datasheets.
    """

    part_number: str = ""
    label: str = ""
    detail: str = ""
    section: str = ""
    section_title: str = ""
    matched_via: str = ""
    citation: str = ""
    values: dict[str, DerivedValue] = Field(default_factory=dict)
    delta: DerivedValue | None = None


class ComparisonRow(BaseModel):
    """One parameter, across the parts being compared.

    - `key` is what the row aligned **on** — the alias-resolved symbol where
      the lexicon claims the parameter, otherwise the printed identity the
      parts share — and `aligned_on` says which of those it was, so an
      alignment can never be silently wrong: a reader can check the rule that
      produced it.
    - `role` is the printed column the deltas were computed on (`max`), `""`
      when no two cells stated a comparable number in the same column.
    - `reference` is the part every delta on this row is measured against —
      the first part named that printed the parameter.
    - `missing_from` lists the compared parts that publish **no** record for
      this parameter. It is a finding, not a gap to hide: during part
      selection an absent parameter is information.
    - `ambiguous_in` lists the parts that publish **several** rows here which
      no shared printed name could pair, so they hold no column of this row.
      It is deliberately not the same list as `missing_from`: one part said
      nothing, the other said several things at once, and only the first is a
      fact about the device.
    """

    key: str = ""
    aligned_on: str = ""
    group: str = ""
    role: str = ""
    reference: str = ""
    cells: list[ComparisonCell] = Field(default_factory=list)
    missing_from: list[str] = Field(default_factory=list)
    ambiguous_in: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    note: str = ""
    citation: str = ""

    @property
    def n_deltas(self) -> int:
        return sum(1 for cell in self.cells if cell.delta is not None)


class PartComparison(BaseModel):
    """The part-selection question, answered once.

    A derived artifact under ADR 0005 like a design card, and derived from the
    very same records: every value is a quoted cell in its envelope or a
    number computed from two of them by a named rule, and nothing here is
    written that the parts' own corpora do not already hold.

    Unlike a card it is **never written to disk** — it exists for the length
    of one question — so it carries `card_version` as the derivation-rule
    version it was produced under rather than as a cache key.

    - `rows` may be empty, and an empty comparison is a valid one:
      `empty_reason` then states what was looked for in which parts.
    - `notes` carries the population sentences invariant 8 requires of any
      consumer that compares, and `unparsed` one line per pair it could not
      compare — including every value of an ambiguous alignment it refused,
      quoted verbatim, so nothing is ever dropped from a decision in silence.
    """

    schema_version: str = ""
    card_version: str = ""
    kind: str = ""  # "symbol" | "name" | "card"
    query: str = ""
    parts: list[str] = Field(default_factory=list)
    reference: str = ""
    rows: list[ComparisonRow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    unparsed: list[str] = Field(default_factory=list)
    empty_reason: str = ""

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_deltas(self) -> int:
        return sum(row.n_deltas for row in self.rows)


class RevisionChange(BaseModel):
    """One difference between two revisions of one part.

    A derived artifact row under ADR 0005: `before` and `after` are cells
    copied verbatim out of the two revisions' own published records, each
    carrying the record it came from and the page it was printed on, and
    `delta` is the one number this artifact adds — a documented pure function
    of those two cells, present **only** where both parsed into the same SI
    base.

    A change that carries no `delta` is not a weaker change; it is one this
    tool refuses to score. It is flagged `review-by-hand` and quoted verbatim,
    because a direction guessed at between two printed strings ("Rev. B is
    better") is the one thing a revision review must never be handed.

    `kind` says which artifact moved (`spec` | `section` | `pin` | `register`
    | `field`), `change` says how (`added` | `removed` | `changed` |
    `retitled` | `page-shifted` | `renamed` | `reset-changed`), and `field`
    names the printed column that moved, so `changed` is never a claim a
    reader has to open two documents to interpret.
    """

    kind: str = ""
    change: str = ""
    key: str = ""
    label: str = ""
    field: str = ""
    aligned_on: str = ""
    before: DerivedValue | None = None
    after: DerivedValue | None = None
    delta: DerivedValue | None = None
    #: The one-line reading, composed only from the two verbatim cells and the
    #: delta where one exists ("TJ max 105 °C -> 125 °C (+20 °C)").
    summary: str = ""
    flags: list[str] = Field(default_factory=list)
    note: str = ""


class RevisionDiff(BaseModel):
    """What changed between two revisions of one part — `REVISION_DIFF.md`.

    Derived like a comparison and governed by the same ADR: it owns no printed
    value, quotes both revisions' records with their pages, and adds exactly
    one number per row where the numeric layer read both sides.

    - `changes` may be empty, and an empty diff is the **correct** answer for
      two identical revisions — `identical` says so explicitly rather than
      leaving a reader to infer it from a missing table.
    - `review_by_hand` is every change this tool refused to score, quoted
      verbatim, one line each. It is the artifact's honesty half: a revision
      review that silently dropped what it could not measure would be worse
      than no review at all.
    - `notes` carries the population sentences invariant 8 requires of a
      consumer that compares, and `unparsed` the alignments it refused (a
      parameter whose rows could not be paired without a guess), with their
      printed values.
    """

    schema_version: str = ""
    card_version: str = ""
    part_number: str = ""
    #: How the caller named each side, and what each one actually is on disk.
    before_label: str = ""
    before_doc: str = ""
    before_revision: str = ""
    after_label: str = ""
    after_doc: str = ""
    after_revision: str = ""
    changes: list[RevisionChange] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    review_by_hand: list[str] = Field(default_factory=list)
    unparsed: list[str] = Field(default_factory=list)
    identical: bool = False
    empty_reason: str = ""

    @property
    def n_changes(self) -> int:
        return len(self.changes)

    @property
    def n_deltas(self) -> int:
        return sum(1 for change in self.changes if change.delta is not None)

    def of_kind(self, kind: str) -> list[RevisionChange]:
        """Every change of one artifact kind, in the order they were derived."""
        return [change for change in self.changes if change.kind == kind]


class FamilySection(BaseModel):
    """One section of a family: shared once, or divergent per member.

    The token win a family index exists for is exactly this distinction, so it
    is a recorded fact per section rather than a rendering decision:

    - `state` is `shared` only when **every** member prints this section under
      the same printed title and its body text is byte-identical across all of
      them (the provenance line excepted, which names each member's own
      revision and pages and therefore always differs). One differing value
      makes the section `divergent`.
    - `divergent` means every member prints it and something in it moved;
      `partial` means some member does not print it at all, which is a finding
      about the series and never folded into `divergent`.
    - `aligned_on` says how the members' sections were matched — the printed
      section number, else the printed title — because a family whose members
      renumber their back matter must be readable as such rather than as ten
      sections appearing and ten disappearing.
    - `files` / `pages` / `titles` are per member and are what a reader
      follows **only where the members diverge**: a shared section is read
      once, from the reference member, and the family index says so instead of
      linking N copies.
    - `tokens` is the size of the body the comparison was made on, measured
      with the project's one token counter — the number that makes "listed
      once" a measurement rather than a claim.
    """

    number: str = ""
    title: str = ""
    state: str = ""  # "shared" | "divergent" | "partial"
    aligned_on: str = ""
    members: list[str] = Field(default_factory=list)
    missing_from: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    pages: dict[str, str] = Field(default_factory=dict)
    titles: dict[str, str] = Field(default_factory=dict)
    #: Why this section is not shared, in words. Empty for a shared section.
    reason: str = ""
    tokens: int = 0


class FamilyIndex(BaseModel):
    """A series answered once — `families/<NAME>/FAMILY_INDEX.md`.

    A derived artifact under ADR 0005 in exactly the sense a design card, a
    cross-part comparison and a revision diff are: it owns no printed value,
    it quotes records its member corpora already publish, and the only numbers
    it adds are the per-member deltas — each a documented pure function of two
    quoted cells, each citing both operands.

    - `members` is the **declared** membership, in the order
      `registry/families.yaml` lists it; `reference` is the first of them,
      which every delta is signed against. Nothing here is inferred from a
      part number: a family is confirmed by a human or it does not exist.
    - `sections` carries every section of the series once, each saying whether
      it is shared or divergent (`FamilySection`).
    - `deltas` / `pin_deltas` / `register_deltas` are the rows that **differ**,
      as `ComparisonRow`s — the same row type a cross-part comparison
      publishes, because a family delta is a cross-part comparison restricted
      to what moved. Rows that align and agree are counted
      (`n_specs_identical`) and not listed: listing them is the cost the
      family index exists to avoid.
    - `notes` carries the population sentences invariant 8 requires of a
      consumer that compares, and `unparsed` one line per alignment it
      refused, with the printed values, so nothing leaves a decision in
      silence.
    - `empty_reason` states what was looked for when there is nothing to show;
      an empty family index is a valid one.
    """

    schema_version: str = ""
    card_version: str = ""
    name: str = ""
    title: str = ""
    members: list[str] = Field(default_factory=list)
    reference: str = ""
    sections: list[FamilySection] = Field(default_factory=list)
    deltas: list[ComparisonRow] = Field(default_factory=list)
    pin_deltas: list[ComparisonRow] = Field(default_factory=list)
    register_deltas: list[ComparisonRow] = Field(default_factory=list)
    #: Spec rows that aligned across at least two members, and how many of
    #: those printed the same values everywhere. The second number is the
    #: measured half of "list the shared once".
    n_specs_aligned: int = 0
    n_specs_identical: int = 0
    notes: list[str] = Field(default_factory=list)
    unparsed: list[str] = Field(default_factory=list)
    empty_reason: str = ""

    @property
    def shared_sections(self) -> list[FamilySection]:
        return [s for s in self.sections if s.state == "shared"]

    @property
    def divergent_sections(self) -> list[FamilySection]:
        return [s for s in self.sections if s.state != "shared"]

    @property
    def n_deltas(self) -> int:
        return len(self.deltas) + len(self.pin_deltas) + len(self.register_deltas)


class ErrataTargetKind(str, Enum):
    """What one errata link points at.

    Exactly the four things a corpus publishes that an erratum can invalidate:
    a section of prose, a parametric row, a pin, or a register. A figure is
    deliberately absent — an erratum that corrects a curve corrects the
    section it was printed in, and pointing at an image nobody can re-read
    would be a link with nothing behind it.
    """

    SECTION = "section"
    SPEC = "spec"
    PIN = "pin"
    REGISTER = "register"


class ErrataTarget(BaseModel):
    """One thing an errata item was matched to, and what matched it.

    A derived artifact row under ADR 0005, and the strictest kind: it owns no
    printed value at all. `id` is the reference that walks back to the thing
    itself — a `models.source_ref` for a record
    (`docs/<doc>/specs.json#rec_s4.5-t2-r13`), the corpus-relative section
    file for a section — and `matched_on` is invariant 8's `derivation`
    spelled for a reader: the identifier the errata item printed, and where it
    was found.

    `rule` is the named rule that produced the link (`section-number`,
    `alias-phrase`, …) and `confidence` is that rule's grade from
    `registry/errata.yaml`. Both are structural labels from a checked-in
    lexicon (ADR 0005 (c)) — no model call is anywhere in this path, and no
    similarity score exists to be tuned.
    """

    kind: ErrataTargetKind = ErrataTargetKind.SECTION
    #: The reference that resolves back to the target.
    id: str = ""
    #: The document directory the target lives in (`datasheet-e0d1e5a2`).
    doc: str = ""
    #: A human-readable name for the target — the section's full title, the
    #: record's symbol/name. Never what a caller resolves by; `id` is.
    label: str = ""
    #: The printed section number the target sits under, when it has one. It
    #: is what the publisher banners on, so a spec-record target banners the
    #: section that printed it.
    section: str = ""
    #: The printed page of the target itself, so a link can be cited without
    #: re-opening the record it names.
    page: int | None = None
    confidence: Confidence = Confidence.UNKNOWN
    #: The named rule (`registry/errata.yaml`'s `rules` keys).
    rule: str = ""
    #: What the match was made on, verbatim: `section number "6.1" (cued by
    #: "Section")`, `alias phrase "junction temperature" -> TJ`.
    matched_on: str = ""


class ErrataItem(BaseModel):
    """One item of an errata document, verbatim.

    `text` is the printed lines of the item joined with newlines and is never
    rewritten — an erratum is a legal statement about silicon, and a
    summarized one is a different statement. `marker` is the printed line that
    started it (`Advisory 3`), `derivation` the named rule that segmented it,
    so a reader who disagrees with where an item starts can see which rule
    drew the line.

    `page` / `page_end` are the printed page range of the errata document
    section the item was read from, so the item cites as `p.3` or `p.3-4`. A
    paragraph-only extraction carries no per-line page, so a range is the
    honest reading and a narrower one would be invented.
    """

    #: Stable id within the part's `errata_links.json` (`err_1`), minted by
    #: `models.errata_item_id` in document-then-reading order.
    id: str = ""
    doc: str = ""  # the errata document's corpus directory name
    doc_hash: str = ""
    marker: str = ""
    text: str = ""
    section: str = ""  # the errata document's own section number
    section_title: str = ""
    page: int | None = None
    page_end: int | None = None
    derivation: str = ""

    @property
    def pages(self) -> str:
        """`p.3`, `p.3-4`, or `p.?` when the errata document pinned no page."""
        if self.page is None:
            return "p.?"
        if self.page_end is not None and self.page_end != self.page:
            return f"p.{self.page}-{self.page_end}"
        return f"p.{self.page}"


class ErrataLink(BaseModel):
    """One errata item and everything the linker could place it against.

    `targets` may be **empty**, and an empty one is not a lesser link: it is
    an item the matcher could not place, which is published under its own
    heading rather than dropped. Losing an erratum is the worst failure this
    artifact can produce, so the set holds linked and unlinked items in two
    named lists and `ErrataLinkSet.n_items` is asserted against their sum.

    `notes` carries anything the matcher had to say about its own limits — a
    rule that matched more records than the lexicon's cap states how many it
    found, because a truncated list that does not say it was truncated reads
    as a complete one.
    """

    errata_item_id: str = ""
    item: ErrataItem = Field(default_factory=ErrataItem)
    targets: list[ErrataTarget] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def text(self) -> str:
        """The item's verbatim text."""
        return self.item.text

    @property
    def page(self) -> int | None:
        return self.item.page

    def targets_of_kind(self, kind: ErrataTargetKind) -> list[ErrataTarget]:
        return [t for t in self.targets if t.kind == kind]


class ErrataLinkSet(BaseModel):
    """A part's `errata_links.json` — every errata item, placed or not.

    Written only for a part that actually holds an errata document. A part
    with no errata document gets **no file**, because an empty one would read
    as "no known issues", which is a claim this corpus has no evidence for.

    A part that holds an errata document the segmenter could read nothing out
    of still gets a file, with `empty_reason` saying so: "there is an errata
    document and it yielded no items" and "there is no errata document" are
    different findings and a designer must be able to tell them apart.
    """

    schema_version: str = ""
    part_number: str = ""
    #: The errata documents this set was built from, by corpus directory name.
    errata_docs: list[str] = Field(default_factory=list)
    #: Items with at least one target.
    links: list[ErrataLink] = Field(default_factory=list)
    #: Items with none — published, never dropped.
    unlinked: list[ErrataLink] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    empty_reason: str = ""

    @property
    def n_items(self) -> int:
        return len(self.links) + len(self.unlinked)

    @property
    def n_targets(self) -> int:
        return sum(len(link.targets) for link in self.links)

    def all_items(self) -> list[ErrataLink]:
        """Every item, linked first then unlinked — nothing filtered out."""
        return list(self.links) + list(self.unlinked)


class GoldenCandidate(BaseModel):
    """One *generated* golden question — a proposal, inert until confirmed.

    `GoldenQuestion` above is the objective function (invariant 5); this is
    the thing that is **not** it yet. A candidate is templated from a record
    that already carries a verbatim answer and a printed page, so it is a
    derived artifact under invariant 8 and carries the whole envelope:
    `source` (the record it was read from, a `models.source_ref`), `page` (the
    page that record was printed on), `verbatim` (the cells the answer was
    taken from) and `template` (the named rule that produced it). No model
    call is in that path — the question text is a format string over printed
    cells.

    `confirmed` is the field the invariant turns on, and it is written
    `false`. Nothing reads a candidate file into the verification run: the
    file is named `golden_qa_<PART>.candidate.yaml`, its top-level key is
    `candidates` rather than `questions`, and the golden loader refuses it by
    name. A candidate becomes part of the benchmark only by a human decision
    that copies its `question` into `golden_qa_<PART>.yaml`.

    The strata fields (`doc`, `backend`, `section`, `section_title`,
    `confidence`, `artifact`) are what the generator spreads the set across.
    They are recorded per candidate rather than only in aggregate so a
    reviewer can see *why* a candidate is in the set — "this is the corpus's
    only `low` register row" is the reason to look hardest at it.
    """

    question: GoldenQuestion
    confirmed: bool = False
    #: Stable identity of this candidate across runs: `<source>|<template>`.
    #: It is what the rejection ledger records, so the same bad candidate is
    #: not re-suggested next run; record ids are reproduced exactly by a
    #: rebuild of identical input, which is what makes the key stable.
    key: str = ""
    #: The named rule that produced the question (invariant 8's `derivation`).
    template: str = ""
    #: The record this was templated from
    #: (`docs/<doc>/specs.json#rec_s4.5-t2-r13`).
    source: str = ""
    #: The page that record was printed on. Never `None` on a published
    #: candidate — a record with no page is not templatable at all, because a
    #: golden question with no citable page cannot be verified.
    page: int | None = None
    #: The printed cells the answer was taken from, joined for a reviewer's
    #: glance. Verbatim: never rewritten, never shortened to fit.
    verbatim: str = ""
    #: Which published artifact the record lives in (`specs.json`,
    #: `pins.json`, `registers.json`, `plots.json`).
    artifact: str = ""
    doc: str = ""  # the document directory name
    backend: str = ""  # the extraction backend that produced that document
    section: str = ""  # printed section number ("" on the captionless era)
    section_title: str = ""
    confidence: Confidence = Confidence.UNKNOWN


class GoldenCandidateSet(BaseModel):
    """A part's generated candidates, plus what the generator refused and why.

    `strata` is the stratification, measured on the **selected** set: one
    mapping per dimension (`artifact`, `backend`, `confidence`, `section`)
    from value to count. It is published rather than left for the reader to
    compute because it is the criterion — a set that is twenty variations of
    the easiest lookup is a defect, and the file has to make that visible
    without re-deriving it.

    `pool` is how many templatable records existed per artifact before
    selection, so "only three candidates" is legible as a fact about the
    corpus rather than as a broken generator. `skipped_rejected` /
    `skipped_existing` are the two exclusions, counted rather than silently
    applied.
    """

    schema_version: str = ""
    part: str = ""
    candidates: list[GoldenCandidate] = Field(default_factory=list)
    strata: dict[str, dict[str, int]] = Field(default_factory=dict)
    pool: dict[str, int] = Field(default_factory=dict)
    #: The population the generator *refused*, per artifact and per reason
    #: (`{"specs.json": {"the record carries no printed page": 41}}`). ADR
    #: 0005's unparsed-population clause applies to a selector as much as to a
    #: derivation: a corpus that yields three candidates out of six hundred
    #: records has to be able to say which rule dropped the other five hundred
    #: and ninety-seven, or "the generator is broken" and "these records are
    #: unaddressable" read identically. Additive; `{}` on a file written before
    #: it existed.
    refused: dict[str, dict[str, int]] = Field(default_factory=dict)
    skipped_rejected: int = 0
    skipped_existing: int = 0
    notes: list[str] = Field(default_factory=list)

    @property
    def n_refused(self) -> int:
        """How many records were refused, over every artifact and reason."""
        return sum(n for reasons in self.refused.values() for n in reasons.values())


class GoldenRejection(BaseModel):
    """One candidate a human rejected, recorded so it is not re-suggested.

    Keyed by the candidate's `key` (record reference + template), which the
    next generation run over the same corpus reproduces exactly. The question
    text and the reason travel with it because a ledger nobody can read is a
    ledger nobody will correct: "the value cell is a footnote marker" is the
    note that stops a maintainer re-deriving the same wrong candidate by hand.
    """

    key: str
    id: str = ""
    question: str = ""
    reason: str = ""


class GoldenRejectionLedger(BaseModel):
    """`tests/fixtures/golden_qa_<PART>.rejected.yaml` — the rejected set."""

    schema_version: str = ""
    part: str = ""
    rejected: list[GoldenRejection] = Field(default_factory=list)
