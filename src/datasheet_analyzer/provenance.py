"""Record provenance for derived artifacts — one id format, one resolver.

ADR 0005 (invariant 8) says every field of a derived artifact carries a
`source` naming the record it came from. That promise is only worth anything
if the string can be walked back to the record and the printed page, by a
machine, without trusting whoever wrote it. This module owns both ends of
that round trip:

- **minting** — `spec_record_id` names a spec record (`rec_412`), and
  `source_ref` spells the reference a derived value stores
  (`docs/datasheet-a1b2c3d4/specs.json#rec_412`);
- **resolving** — `resolve_source` reads a built corpus (through
  `CorpusIndex`, so nothing here walks a part directory of its own) and hands
  back the record, its document and its page.

Two rules are deliberate. A reference that names no document
(`specs.json#rec_412`, the shorthand ADR 0005 writes) resolves **only when
exactly one document of the part carries that record** — an ambiguous
reference is a finding, not a coin flip, so it warns and resolves to nothing.
And a record id is stable *evidence*, not a hash: emission order in
`structure/specs.py` is fully deterministic (section order, table order, row
order), so a rebuild of identical input reproduces every id exactly, and a
record that was never given one (a corpus published before ADR 0005) resolves
to nothing rather than to its neighbour.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from datasheet_analyzer.models import PinRecord, PlotRecord, RegisterRecord, SpecRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datasheet_analyzer.retrieve.index import CorpusIndex

log = logging.getLogger(__name__)

#: The published artifacts a `source` may point into, and the record list of
#: each on a loaded document. Nothing else is addressable: a derived value may
#: only cite a record, never a section file or a rendered card.
SPECS_ARTIFACT = "specs.json"
PLOTS_ARTIFACT = "plots.json"
PINS_ARTIFACT = "pins.json"
REGISTERS_ARTIFACT = "registers.json"
ARTIFACTS = (SPECS_ARTIFACT, PLOTS_ARTIFACT, PINS_ARTIFACT, REGISTERS_ARTIFACT)

#: Spec record ids read `rec_1`, `rec_2`, ... — 1-based, so `rec_412` is the
#: 412th record of that document, exactly as ADR 0005 writes it.
RECORD_ID_PREFIX = "rec_"

#: Pin record ids read `pin_1`, `pin_2`, ... The prefix differs from a spec
#: record's so a reference is legible on sight; the artifact name in the
#: reference is what actually disambiguates them.
PIN_ID_PREFIX = "pin_"

#: Register record ids read `reg_1`, `reg_2`, ... — the same legibility choice
#: `PIN_ID_PREFIX` makes.
REGISTER_ID_PREFIX = "reg_"

#: Corpus-relative document directories live under `docs/`; a fully qualified
#: reference is `docs/<doc>/<artifact>#<record id>`.
_DOCS_DIR = "docs"


def spec_record_id(ordinal: int) -> str:
    """Id of the `ordinal`-th (0-based) spec record of a document."""
    return f"{RECORD_ID_PREFIX}{ordinal + 1}"


def pin_record_id(ordinal: int) -> str:
    """Id of the `ordinal`-th (0-based) pin record of a document."""
    return f"{PIN_ID_PREFIX}{ordinal + 1}"


def register_record_id(ordinal: int) -> str:
    """Id of the `ordinal`-th (0-based) register record of a document."""
    return f"{REGISTER_ID_PREFIX}{ordinal + 1}"


@dataclass(frozen=True)
class SourceRef:
    """A parsed `source` string: which artifact, which record, which document.

    `doc` is the document directory name (`datasheet-a1b2c3d4`) or `""` for
    the unqualified shorthand, which resolves only when the part leaves no
    doubt about which document was meant.
    """

    artifact: str
    record_id: str
    doc: str = ""

    def __str__(self) -> str:
        return source_ref(self.record_id, artifact=self.artifact, doc=self.doc)


@dataclass(frozen=True)
class ResolvedSource:
    """A `source` walked back to the record it names and the page it cites.

    `page` is the printed page of the record itself — a spec record's pinned
    page, a plot record's section start — so a caller checking invariant 8
    compares a derived value's page against the record's own, never against a
    page the derived artifact also supplied.
    """

    source: str
    doc: str
    artifact: str
    record_id: str
    record: SpecRecord | PlotRecord | PinRecord | RegisterRecord
    page: int | None


def source_ref(record_id: str, *, artifact: str = SPECS_ARTIFACT, doc: str = "") -> str:
    """The `source` string for one record: `docs/<doc>/<artifact>#<id>`.

    `doc` is the document directory name; omitting it yields the unqualified
    `<artifact>#<id>` shorthand, which is only safe for a single-document
    part. Derivation code should always pass `doc` — it has it, and an
    unambiguous reference costs nothing.
    """
    prefix = f"{_DOCS_DIR}/{doc}/" if doc else ""
    return f"{prefix}{artifact}#{record_id}"


def parse_source(source: str) -> SourceRef | None:
    """Parse a `source` string, or `None` when it is not one.

    Refuses rather than repairs, the same stance `CorpusIndex.corpus_path`
    takes: a malformed reference is a defect in whatever wrote it, and
    guessing what it meant would put an unverified value on a card.
    """
    text = (source or "").strip().replace("\\", "/")
    if text.count("#") != 1:
        return None
    path, record_id = text.split("#", 1)
    if not record_id or any(ch.isspace() for ch in record_id):
        return None
    parts = path.split("/")
    if len(parts) == 1:
        doc, artifact = "", parts[0]
    elif len(parts) == 3 and parts[0] == _DOCS_DIR and parts[1]:
        doc, artifact = parts[1], parts[2]
    else:
        return None
    if artifact not in ARTIFACTS:
        return None
    return SourceRef(artifact=artifact, record_id=record_id, doc=doc)


def resolve_source(part: Path | str | CorpusIndex, source: str) -> ResolvedSource | None:
    """Resolve a `source` string against a built part; `None` when it cannot.

    `part` is a part directory or an already-loaded `CorpusIndex`. Returns
    `None` — with a warning naming the reason — for a reference that does not
    parse, names an unknown document, matches no record, or matches records in
    more than one document. Every one of those is "this value is not traceable",
    which is exactly what an invariant-8 check must be able to fail on.
    """
    ref = parse_source(source)
    if ref is None:
        log.warning("unparseable derived source %r", source)
        return None

    # Imported at call time: the minting half of this module runs inside the
    # structure stage, which has no business dragging the retrieval core in.
    from datasheet_analyzer.retrieve.index import CorpusIndex

    index = part if isinstance(part, CorpusIndex) else CorpusIndex.load(Path(part))

    matches: list[tuple[str, SpecRecord | PlotRecord | PinRecord | RegisterRecord]] = []
    for doc in index.docs:
        if ref.doc and doc.name != ref.doc:
            continue
        records = {
            SPECS_ARTIFACT: doc.specs,
            PLOTS_ARTIFACT: doc.plots,
            PINS_ARTIFACT: doc.pins,
            REGISTERS_ARTIFACT: doc.registers,
        }[ref.artifact]
        matches.extend(
            (doc.name, record) for record in records if record.id and record.id == ref.record_id
        )

    if not matches:
        log.warning("derived source %r resolves to no record in %s", source, index.part_number)
        return None
    if len(matches) > 1:
        # Only reachable for the unqualified shorthand across a multi-document
        # part: ids are unique within one document.
        log.warning(
            "derived source %r is ambiguous in %s (%s)",
            source, index.part_number, ", ".join(doc for doc, _ in matches),
        )
        return None

    doc_name, record = matches[0]
    page = record.page_start if isinstance(record, PlotRecord) else record.page
    return ResolvedSource(
        source=source,
        doc=doc_name,
        artifact=ref.artifact,
        record_id=ref.record_id,
        record=record,
        page=page,
    )
