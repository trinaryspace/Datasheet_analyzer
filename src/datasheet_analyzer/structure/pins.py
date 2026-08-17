"""RawDocument -> pins.json: the pin table as individually citable records.

Phase 6, ticket 04 — the first consumer of the device-table abstraction, and
the artifact a designer lives inside during schematic capture. Nothing here
reads a PDF or a drawing: `structure/device_tables.py` has already done
identify → map → validate → emit, and this module is the *publication* of that
result as pins: one record per pin, a lexicon label for what the pin is for,
and the cross-check that says when the table disagrees with the package.

Three rules are load-bearing.

- **A pin table is published whole or not at all.** The device-table
  abstraction rejects a table it cannot validate, and this module never
  back-fills the gap: a document whose pin table was rejected publishes **no**
  `pins.json`, and the reason lands in `ExtractionStats.rejection_reasons`
  beside the reconstruction gate's own. A designer who greps for a pin, gets
  no hit and concludes the pin does not exist has been misled, which is
  precisely the "confident but incomplete" artifact ADR 0005 exists to
  prevent. So `build_pinset` still returns a `PinSet` when nothing was
  accepted — the warnings are part of the finding — and the publisher writes
  no file for it.
- **`type` is a lexicon label, and `unknown` is an answer.** `registry/
  pin_types.yaml` is the only place a pin word lives (see its header for the
  matching rule). A row the lexicon does not recognise, and a row whose
  evidence points at two categories at once, are both `unknown`; a pin the
  corpus is not sure about must never read as a supply. Every classified
  record carries `type_evidence`, the phrase that decided it — invariant 8's
  `derivation`, per record.
- **The package cross-check warns; it never suppresses.** ADR 0005 decided
  this explicitly: the stated count is itself parsed from prose, so letting it
  reject a good pin table would trade a real artifact for a bad sentence. The
  warning is *recorded* in the manifest (`CorpusManifest.derived_warnings`)
  rather than logged, because a warning that can be ignored is weaker than a
  rejection and a fact the corpus carries cannot be.

A stated pin count is read only from a **hyphen-joined package descriptor**
(`324-ball BGA`, `24-terminal ceramic LCC`, `8-Pin CDIP`), and only when every
such descriptor in the document agrees. A datasheet's table of contents prints
"21 Pin Configuration and Function Descriptions" and its thermal table prints
"8 PINS"; neither is a package descriptor, and the hyphen is what tells them
apart. Two descriptors that disagree are no evidence at all, so the document
states nothing and no cross-check runs.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from datasheet_analyzer.config import PINS_SCHEMA_VERSION
from datasheet_analyzer.models import PinRecord, PinSet, PinType, RawDocument, SectionNode
from datasheet_analyzer.provenance import pin_record_id
from datasheet_analyzer.structure.confidence import grade_pin_record
from datasheet_analyzer.structure.device_tables import (
    PIN,
    DeviceTable,
    count_mismatch,
    read_device_tables,
    record_rejections,
)

log = logging.getLogger(__name__)

LEXICON_PATH = Path(__file__).resolve().parent.parent / "registry" / "pin_types.yaml"

#: The shortest lexicon phrase allowed to match *inside* a pin name. Below it a
#: phrase is matched only as a whole token: `NC` is a no-connect pin, but the
#: `nc` in `SYNC0OUTB` is two letters of a JESD204B synchronization output.
MIN_SUBSTRING = 3

#: The unit words a package descriptor prints, hyphen-joined to its count.
_PACKAGE_UNITS = "ball|balls|lead|leads|pin|pins|terminal|terminals|bump|bumps|contact|contacts"
#: `324-ball`, `24‑terminal`, `8-Pin` — any of the dashes a datasheet prints.
_PACKAGE_COUNT_RE = re.compile(
    rf"\b(\d{{1,4}})\s*[-‐‑‒–—−]\s*({_PACKAGE_UNITS})\b",
    re.IGNORECASE,
)

#: Split a pin name into the tokens a lexicon phrase may match whole:
#: `DVDD1P8` -> dvdd, 1, p, 8; `VDD1_NVG` -> vdd, 1, nvg.
_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+")


@dataclass(frozen=True)
class TypeMatch:
    """One lexicon phrase that claimed a pin, and where it was found."""

    type: PinType
    phrase: str
    field: str  # "name" | "description"

    @property
    def evidence(self) -> str:
        """The `derivation` string a classified record publishes."""
        return f'{self.field}:"{self.phrase}"'


@dataclass(frozen=True)
class PinTypeLexicon:
    """The loaded `pin_types.yaml`: phrases per type, per matched field."""

    names: dict[PinType, tuple[str, ...]] = field(default_factory=dict)
    descriptions: dict[PinType, tuple[str, ...]] = field(default_factory=dict)

    @property
    def types(self) -> tuple[PinType, ...]:
        return tuple(self.names)

    @classmethod
    def from_mapping(cls, data: dict | None) -> PinTypeLexicon:
        """Build from parsed YAML; a malformed entry warns and is skipped.

        One bad type must not take the whole lexicon — and with it every pin of
        every other type — down, the same stance `aliases.py` and
        `device_tables.py` take.
        """
        names: dict[PinType, tuple[str, ...]] = {}
        descriptions: dict[PinType, tuple[str, ...]] = {}
        for label, body in (data or {}).items():
            try:
                pin_type = PinType(str(label).strip().lower())
            except ValueError:
                log.warning("skipping unknown pin type %r in the pin-type lexicon", label)
                continue
            if pin_type is PinType.UNKNOWN:
                log.warning("skipping pin-type entry 'unknown': it is the absence of a label")
                continue
            if not isinstance(body, dict):
                log.warning("skipping malformed pin-type entry %r: not a mapping", label)
                continue
            names[pin_type] = _phrases(body.get("names"))
            descriptions[pin_type] = _phrases(body.get("descriptions"))
        return cls(names=names, descriptions=descriptions)

    @classmethod
    def read(cls, path: Path | None = None) -> PinTypeLexicon:
        """Parse a lexicon file; an unreadable one degrades to an empty one.

        An empty lexicon classifies every pin `unknown`, which is the honest
        degradation: no labels rather than labels produced by a rule nobody can
        see.
        """
        path = Path(path) if path else LEXICON_PATH
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            log.warning("pin-type lexicon unavailable (%s: %s) — every pin is unknown", path, exc)
            return cls()
        return cls.from_mapping(data)

    def name_matches(self, name: str) -> list[TypeMatch]:
        """Every phrase this name carries (see the lexicon header's rule 1)."""
        text = (name or "").lower()
        if not text:
            return []
        tokens = set(_TOKEN_RE.findall(text))
        out: list[TypeMatch] = []
        for pin_type, phrases in self.names.items():
            for phrase in phrases:
                if phrase in tokens or (len(phrase) >= MIN_SUBSTRING and phrase in text):
                    out.append(TypeMatch(type=pin_type, phrase=phrase, field="name"))
        return out

    def description_matches(self, description: str) -> list[TypeMatch]:
        """Every phrase this description carries (plain substrings)."""
        text = (description or "").lower()
        if not text:
            return []
        return [
            TypeMatch(type=pin_type, phrase=phrase, field="description")
            for pin_type, phrases in self.descriptions.items()
            for phrase in phrases
            if phrase in text
        ]


def _phrases(value) -> tuple[str, ...]:
    """A lexicon phrase list, lowercased and de-duplicated in file order."""
    if isinstance(value, str):
        value = [value]
    cleaned = [str(p).strip().lower() for p in (value or [])]
    return tuple(dict.fromkeys(p for p in cleaned if p))


@cache
def load_pin_lexicon(path: Path | None = None) -> PinTypeLexicon:
    """The shipped pin-type lexicon, parsed once per process (or one at `path`)."""
    return PinTypeLexicon.read(path)


def clear_pin_lexicon_cache() -> None:
    """Test hook: re-read the lexicon file on the next `load_pin_lexicon`."""
    load_pin_lexicon.cache_clear()


def classify_pin_type(
    name: str, description: str = "", *, lexicon: PinTypeLexicon | None = None
) -> tuple[PinType, str]:
    """`(type, evidence)` for one pin — `(UNKNOWN, "")` when it cannot be said.

    The rule, in full (the lexicon header states it as data):

    1. the pin's **name** is asked first, because a mnemonic is chosen to
       identify the pin while a description is a sentence about it;
    2. the **description** is asked only when the name matched nothing;
    3. inside a tier the **longest matched phrase wins** — it explains more of
       the text — and two types tied at that length yield `UNKNOWN`, because
       the lexicon has just said it cannot tell them apart. Guessing between
       them is what invariant 8 forbids; a longer, more specific phrase in the
       YAML is how the gap closes.
    """
    lexicon = load_pin_lexicon() if lexicon is None else lexicon
    for matches in (lexicon.name_matches(name), lexicon.description_matches(description)):
        if not matches:
            continue
        longest = max(len(m.phrase) for m in matches)
        best = [m for m in matches if len(m.phrase) == longest]
        if len({m.type for m in best}) != 1:
            return PinType.UNKNOWN, ""
        return best[0].type, best[0].evidence
    return PinType.UNKNOWN, ""


def stated_pin_count(raw: RawDocument) -> int | None:
    """The pin count the document's package descriptors state, or `None`.

    Read only from a hyphen-joined descriptor (`324-ball BGA`) and only when
    every descriptor in the document agrees — see the module docstring for why
    both halves matter. Disagreement is not a tie to break: two package
    descriptors that contradict each other are no evidence, and a cross-check
    run against a coin flip would produce warnings nobody can act on.
    """
    counts = Counter(
        int(match.group(1))
        for text in _document_text(raw)
        for match in _PACKAGE_COUNT_RE.finditer(text)
        if int(match.group(1)) > 1
    )
    if len(counts) != 1:
        if counts:
            log.info(
                "package pin count is stated inconsistently (%s) — no cross-check",
                ", ".join(str(n) for n in sorted(counts)),
            )
        return None
    return next(iter(counts))


def _document_text(raw: RawDocument) -> list[str]:
    """Every printed string of a document a package descriptor could sit in."""
    out: list[str] = []
    for section in raw.sections:
        out.append(section.full_title)
        out.extend(section.paragraphs)
        for table in section.tables:
            out.append(table.caption)
            out.extend(table.headers)
            for row in table.grid:
                out.extend(row)
        out.extend(figure.caption for figure in section.figures)
    return out


def build_pinset(raw: RawDocument, part_number: str) -> PinSet:
    """Build a `PinSet` from every pin table of a `RawDocument`.

    Always returns a set, even an empty one: a document whose pin table was
    rejected has a *finding* (the reason, recorded in the document's extraction
    stats) and possibly a warning, and both would be lost by returning `None`.
    What must not exist is a half-published pin file, and that is the
    publisher's rule — it writes `pins.json` only for a set that has pins.

    Rejection reasons are recorded here rather than by the caller because this
    is where the read happens; `record_rejections` puts them in the same list
    the reconstruction gate writes to, so a device-table rejection is as
    measurable as a parametric one.
    """
    result = read_device_tables(raw, kind=PIN)
    if raw.extraction_stats is not None:
        record_rejections(raw.extraction_stats, result.rejections)

    lexicon = load_pin_lexicon()
    pins: list[PinRecord] = []
    for table in result.tables:
        pins.extend(_table_to_pins(table, raw, lexicon))

    # Stable, addressable ids (ADR 0005): emission order is fully determined by
    # the document — section order, table order, row order, printed key order —
    # so a rebuild of identical input reproduces every id exactly.
    for ordinal, record in enumerate(pins):
        record.id = pin_record_id(ordinal)

    warnings = list(result.warnings)
    stated = stated_pin_count(raw)
    if stated is not None:
        # The cross-check runs whenever the document states a count, including
        # when nothing was published: "this package has 24 terminals and the
        # corpus has none of them" is the single most useful thing a pin-less
        # part can say, and it is invisible from a `pins.json` that does not
        # exist.
        mismatch = (
            count_mismatch(len(pins), stated, kind=PIN)
            if pins
            else (
                f"{PIN} count mismatch: document states {stated}, no pin table "
                "was published (see the recorded rejection reasons)"
            )
        )
        if mismatch:
            log.warning("%s: %s", part_number, mismatch)
            warnings.append(mismatch)

    return PinSet(
        schema_version=PINS_SCHEMA_VERSION,
        part_number=part_number,
        doc_hash=raw.source.content_hash,
        pins=pins,
        stated_count=stated,
        warnings=warnings,
    )


def _table_to_pins(
    table: DeviceTable, raw: RawDocument, lexicon: PinTypeLexicon
) -> list[PinRecord]:
    """One accepted device table as pin records, graded where they were read."""
    section = _section_for(raw, table.section_index)
    block = _block_for(section, table.table_index)
    out: list[PinRecord] = []
    for device in table.records:
        pin_type, evidence = classify_pin_type(
            device.field("name"), device.field("description"), lexicon=lexicon
        )
        record = PinRecord(
            pin=device.key,
            pin_verbatim=device.key_verbatim,
            name=device.field("name"),
            type=pin_type,
            type_evidence=evidence,
            direction=device.field("type"),
            description=device.field("description"),
            section=device.section,
            table_index=device.table_index,
            row_index=device.row_index,
            page=device.page,
            row_verbatim=list(device.row_verbatim),
        )
        # Graded here, where the evidence still exists: how the grid was
        # reconstructed and whether the page was pinned are both gone by the
        # time a record reaches `retrieve/`.
        if block is not None and section is not None:
            record.confidence = grade_pin_record(record, block, section)
        out.append(record)
    return out


def _section_for(raw: RawDocument, section_index: int) -> SectionNode | None:
    """The section an accepted device table came from, by position.

    By position rather than by printed number, because a whole era of
    datasheets numbers no section at all (ADR 0004) and every one of those
    would otherwise resolve to the same entry.
    """
    if not (0 <= section_index < len(raw.sections)):
        return None
    return raw.sections[section_index]


def _block_for(section: SectionNode | None, table_index: int):
    """The `TableBlock` an accepted device table came from, or `None`."""
    if section is None or not (0 <= table_index < len(section.tables)):
        return None
    return section.tables[table_index]
