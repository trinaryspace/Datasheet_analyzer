"""Design cards — `cards/<kind>.json` + `cards/<kind>.md` (phase 6, ticket 07).

A datasheet is organised the way a datasheet is written. A design card is the
same records organised the way a designer works: *what rails does this need*,
*how hot may it get*, *what does it talk*, *how much room is there between the
recommended maximum and the rating that destroys the part*. Nothing here is
new information — every value on a card is already in `specs.json` or
`pins.json`, four sections apart, which is exactly why nobody reads them
together.

**A card derives nothing.** It selects records that already exist and computes
only what a documented pure function can compute from them. Concretely, per
invariant 8 (ADR 0007):

- **clause (a)** — every printed value is copied verbatim (`verbatim_copy`);
  the parsed number beside it comes from `structure/quantities.parse_quantity`
  and is a convenience, never a replacement for the print;
- **clause (b)** — the one thing this module *computes* is the `limits` card's
  margin (`abs_max_margin`) and the supply-pin count (`count_pins_by_name`),
  both pure functions over records, both named in the value's `derivation`;
- **clause (c)** — every selector is a phrase in `registry/cards.yaml` or a
  symbol family in `registry/aliases.yaml`, so teaching the power card a new
  rail-naming convention is a data change and nothing else.

No model call appears anywhere in this path.

Three rules are the ones a reader should test:

**The honest empty card.** A part that genuinely lacks a card's data emits a
card with no rows and an `unresolved` list saying what was looked for and why
nothing filled it. It is never padded with a plausible default, and it is
never silently omitted — "this datasheet prints no thermal table" and "nobody
ever built this card" are different answers and the card says which.

**Margin only where both sides parsed.** The `limits` card joins the
absolute-maximum table against the recommended-operating table and subtracts
one from the other only when *both* printed values became numbers in the same
unit. Every pair it could not compare — a missing counterpart, an ambiguous
join, a value like `VDDRX1P8+0.3` that is not a number — is listed on the card
by name. A parameter dropped from a margin table reads as "no margin problem
here", which is the failure this card exists to prevent. Where the
recommended maximum *equals* the absolute maximum the row is flagged
`zero-margin`: a genuine design hazard that is invisible when the two tables
are read pages apart.

**Every value carries a citation that resolves.** `audit_card` walks a card
and resolves every `source` back to the record and printed page it names,
using `derive/provenance.py`'s resolver — the same one every other derived
artifact answers to. A record this tool cannot address unambiguously is not
cited at all: the row is left out and the reason is recorded, because a
citation that resolves to a different row is worse than no row.

The CLI entry point is `cli_card`, whose flags `cli.py` froze; `build_card`
and `load_or_build_card` are the seams the MCP `get_card` tool and `dsa
compare --card` sit on.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from datasheet_analyzer.config import CARDS_SCHEMA_VERSION, get_settings
from datasheet_analyzer.corpus_ref import LIBRARY_REF_PREFIX
from datasheet_analyzer.derive.provenance import (
    CARDS_DIRNAME,
    PINS_ARTIFACT,
    SPECS_ARTIFACT,
    check_provenance,
    parse_source,
    resolve_source,
)
from datasheet_analyzer.models import (
    CARD_KINDS,
    CARD_LIMITS,
    VALUE_KIND_POINT,
    Card,
    CardRow,
    Confidence,
    DerivedValue,
    PinRecord,
    SpecRecord,
    source_ref,
)
from datasheet_analyzer.structure.aliases import AliasLexicon, load_lexicon, padded
from datasheet_analyzer.structure.quantities import Quantity, parse_record_cells, resolve_unit

log = logging.getLogger(__name__)

#: The checked-in selector lexicon. Data, not code — see the file's header.
CARD_LEXICON_PATH = Path(__file__).resolve().parent.parent / "registry" / "cards.yaml"

#: The two derivation rules this module owns (invariant 8, clause (b)). Both
#: are pure functions of published records and both are named on the value
#: they produced, so a reader can check the arithmetic instead of trusting it.
DERIVATION_MARGIN = "abs_max_margin"
DERIVATION_PIN_COUNT = "count_pins_by_name"

#: Machine-readable hazards a `limits` row may carry.
FLAG_ZERO_MARGIN = "zero-margin"
FLAG_NEGATIVE_MARGIN = "negative-margin"

#: The banner every rendered card carries. `card_version` is in it because a
#: card on someone's screen has to say which derivation rules produced it —
#: the version is the difference between two cards that look identical.
BANNER = "<!-- derived: card_version {version} -->"

#: Separates a row's group heading from the rest of its note. `CardRow` has no
#: group field — the model is frozen — so the heading rides in the note, and
#: this separator is chosen because nothing else ever emits it, which keeps
#: `render_card` able to regroup rows read back from a published `.json`.
GROUP_SEPARATOR = " · "

#: Column keys a card row may carry, in render order. A card shapes its own
#: table by which of these its rows fill; nothing else is ever a column.
COLUMN_ORDER: tuple[str, ...] = (
    "pin",
    "type",
    "count",
    "min",
    "typ",
    "max",
    "value",
    "abs_max",
    "recommended",
    "margin",
)

COLUMN_HEADINGS: dict[str, str] = {
    "pin": "Pin",
    "type": "Type",
    "count": "Pins",
    "min": "Min",
    "typ": "Typ",
    "max": "Max",
    "value": "Value",
    "abs_max": "Absolute max",
    "recommended": "Recommended",
    "margin": "Margin",
}

#: Confidence grades, strongest first. Used to grade a computed value no
#: better than the weaker of the two records it was computed from.
_CONFIDENCE_ORDER = (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW, Confidence.UNKNOWN)


# --- the selector lexicon --------------------------------------------------


@dataclass(frozen=True)
class GroupSpec:
    """One row group of a card: which records it claims, which cells it shows.

    A record joins the group when it matches at least one of `families` /
    `patterns`, passes the `units` filter and hits none of `exclude`.
    `pin_types` replaces both and draws from `pins.json` instead.
    """

    id: str
    heading: str = ""
    cells: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    unitless: bool = False
    exclude: tuple[str, ...] = ()
    pin_types: tuple[str, ...] = ()

    @property
    def from_pins(self) -> bool:
        return bool(self.pin_types)

    def describe(self) -> str:
        """What this group looked for, in words, for an `unresolved` line."""
        wanted: list[str] = []
        if self.pin_types:
            wanted.append("pins typed " + "/".join(self.pin_types))
        if self.families:
            wanted.append("symbol family " + "/".join(self.families))
        if self.patterns:
            wanted.append("any of " + ", ".join(f"{p!r}" for p in self.patterns))
        if self.units:
            wanted.append("in " + "/".join(self.units))
        elif self.unitless:
            wanted.append("with or without a unit")
        return "; ".join(wanted) or "anything"


@dataclass(frozen=True)
class SideSpec:
    """One side of the `limits` join: how its table is recognised."""

    id: str
    label: str = ""
    section_patterns: tuple[str, ...] = ()
    text_patterns: tuple[str, ...] = ()
    compare_cells: tuple[str, ...] = ("max", "value")


@dataclass(frozen=True)
class CardSpec:
    """One card's selectors, as read off `registry/cards.yaml`."""

    kind: str
    title: str = ""
    intent: str = ""
    groups: tuple[GroupSpec, ...] = ()
    sides: tuple[SideSpec, ...] = ()


@dataclass(frozen=True)
class CardLexicon:
    """The loaded `cards.yaml`."""

    cards: tuple[CardSpec, ...] = ()

    def get(self, kind: str) -> CardSpec | None:
        for spec in self.cards:
            if spec.kind == kind:
                return spec
        return None

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(spec.kind for spec in self.cards)

    @classmethod
    def from_mapping(cls, data: dict | None) -> CardLexicon:
        """Build from parsed YAML; a malformed card is warned about and skipped.

        One bad entry must not take every card down — the same degradation
        rule `aliases.yaml` and `pin_types.yaml` already follow.
        """
        specs: list[CardSpec] = []
        for kind, body in ((data or {}).get("cards") or {}).items():
            if not isinstance(body, dict):
                log.warning("skipping malformed card entry %r: not a mapping", kind)
                continue
            groups = tuple(
                GroupSpec(
                    id=str(g.get("id") or ""),
                    heading=str(g.get("heading") or ""),
                    cells=_strings(g.get("cells")),
                    families=_strings(g.get("families")),
                    patterns=_strings(g.get("patterns")),
                    units=_strings(g.get("units")),
                    unitless=bool(g.get("unitless")),
                    exclude=_strings(g.get("exclude")),
                    pin_types=_strings(g.get("pin_types")),
                )
                for g in (body.get("groups") or [])
                if isinstance(g, dict)
            )
            sides = tuple(
                SideSpec(
                    id=str(side_id),
                    label=str(side.get("label") or side_id),
                    section_patterns=_strings(side.get("section_patterns")),
                    text_patterns=_strings(side.get("text_patterns")),
                    compare_cells=_strings(side.get("compare_cells")) or ("max", "value"),
                )
                for side_id, side in (body.get("sides") or {}).items()
                if isinstance(side, dict)
            )
            specs.append(
                CardSpec(
                    kind=str(kind),
                    title=str(body.get("title") or kind),
                    intent=" ".join(str(body.get("intent") or "").split()),
                    groups=groups,
                    sides=sides,
                )
            )
        return cls(cards=tuple(specs))

    @classmethod
    def read(cls, path: Path | None = None) -> CardLexicon:
        """Parse a lexicon file; an unreadable one degrades to an empty one.

        An empty lexicon selects nothing, so every card comes out honestly
        empty with a stated reason rather than half-populated by defaults
        compiled into the code.
        """
        path = Path(path) if path else CARD_LEXICON_PATH
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            log.warning("card lexicon unavailable (%s: %s) — cards will be empty", path, exc)
            return cls()
        return cls.from_mapping(data)


def _strings(value: object) -> tuple[str, ...]:
    """A YAML scalar or sequence, as a tuple of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


@cache
def load_card_lexicon(path: Path | None = None) -> CardLexicon:
    """The shipped card lexicon, parsed once per process (or one at `path`)."""
    return CardLexicon.read(path)


def clear_card_lexicon_cache() -> None:
    """Test hook: re-read the lexicon file on the next `load_card_lexicon`."""
    load_card_lexicon.cache_clear()


# --- the corpus a card draws on --------------------------------------------


@dataclass(frozen=True)
class CardDocument:
    """One published document a card may cite, with its citable record set.

    `citable` is not every record: a `source` is only a citation if it
    resolves back to *this* record. Where a document publishes two records
    that compute the same id — which happens when a datasheet's sections are
    unnumbered, so `(section, table_index, row_index)` collides across
    sections — only the first is addressable, and the rest are refused rather
    than cited ambiguously. `uncitable` counts what that cost.
    """

    name: str
    ref_base: str
    records: tuple[SpecRecord, ...] = ()
    pins: tuple[PinRecord, ...] = ()
    citable: frozenset[int] = frozenset()
    citable_pins: frozenset[int] = frozenset()
    uncitable: int = 0

    def spec_source(self, record: SpecRecord) -> str:
        """The `source` string citing one of this document's spec records."""
        return source_ref(f"{self.ref_base}/{SPECS_ARTIFACT}", record.id)

    def pin_source(self, record: PinRecord) -> str:
        return source_ref(f"{self.ref_base}/{PINS_ARTIFACT}", record.id)

    def can_cite(
        self, position: int, record: SpecRecord | PinRecord, *, pins: bool = False
    ) -> bool:
        """Whether citing this record produces a citation that resolves *to it*.

        Two things disqualify a record, and both are honest readings of
        invariant 8 rather than caution: it was published without a printed
        page, so the citation could not name one; or an earlier record in the
        same file computes the same id, so `resolve_source` would hand a
        reader the earlier row instead.
        """
        allowed = self.citable_pins if pins else self.citable
        return record.page is not None and position in allowed


@dataclass(frozen=True)
class CardCorpus:
    """Everything one part publishes that a card may draw from."""

    part: str
    part_dir: Path
    library_dir: Path | None = None
    documents: tuple[CardDocument, ...] = ()
    #: Section number -> printed title, from the manifest. The `limits` card
    #: recognises a side from it; a sweep row records it as its note.
    section_titles: dict[str, str] = field(default_factory=dict)

    @property
    def has_records(self) -> bool:
        return any(doc.records for doc in self.documents)

    @property
    def uncitable(self) -> int:
        return sum(doc.uncitable for doc in self.documents)

    def section_title(self, number: str) -> str:
        return self.section_titles.get((number or "").strip(), "")


def _ref_base(doc_dir: Path, part_dir: Path, library_dir: Path | None) -> str:
    """The manifest-style reference naming a document's directory.

    `docs/<doc>` when the document was published under the part,
    `@library/docs/<doc>` when it lives once in the shared store — the same
    two roots `corpus_ref` resolves, so a card's `source` is resolvable by
    exactly the rule every other reference follows.
    """
    doc_dir = Path(doc_dir)
    for root, prefix in ((part_dir, ""), (library_dir, LIBRARY_REF_PREFIX)):
        if root is None:
            continue
        try:
            return prefix + doc_dir.resolve().relative_to(Path(root).resolve()).as_posix()
        except (ValueError, OSError):
            continue
    return f"docs/{doc_dir.name}"


def _citable_positions(records: Sequence) -> tuple[frozenset[int], int]:
    """Which record *positions* are addressable, and how many were refused.

    A record id is a pure function of `(section, table_index, row_index)`, and
    a document whose sections carry no numbers — every datasheet the layout
    floor reads without a numbered table of contents — restarts `table_index`
    at 0 in each of them. Several records then compute one id, and
    `resolve_source` hands back the *first* of them.

    So the first occurrence is addressable and the rest are not. Refusing the
    rest is the honest reading of invariant 8: a value whose citation lands
    on a different row is worse than a value the card leaves out and
    explains. Positions rather than ids, because the set has to tell *which
    record instance* is the addressable one.
    """
    seen: set[str] = set()
    citable: set[int] = set()
    refused = 0
    for position, record in enumerate(records):
        if record.id in seen:
            refused += 1
            continue
        seen.add(record.id)
        citable.add(position)
    return frozenset(citable), refused


def load_card_corpus(part_dir: Path | str, part: str = "") -> CardCorpus:
    """Load one built part's published records, ready to select from.

    Reads through `CorpusIndex`, which already resolves a manifest's documents
    to wherever they were published (under the part, or once in the shared
    store) — a card composes records from several documents and must cite each
    where it actually lives.
    """
    from datasheet_analyzer.derive.pins import load_part_pins
    from datasheet_analyzer.retrieve.index import CorpusIndex

    part_dir = Path(part_dir)
    index = CorpusIndex.load(part_dir)
    pins_by_doc = {doc: pinset for doc, pinset in load_part_pins(part_dir, part).sets}

    documents: list[CardDocument] = []
    for doc in index.docs:
        directory = doc.directory or (part_dir / "docs" / doc.name)
        pinset = pins_by_doc.get(doc.name)
        pins = tuple(pinset.pins) if pinset is not None else ()
        citable, refused = _citable_positions(doc.specs)
        citable_pins, _refused_pins = _citable_positions(pins)
        documents.append(
            CardDocument(
                name=doc.name,
                ref_base=_ref_base(directory, part_dir, index.library_dir),
                records=doc.specs,
                pins=pins,
                citable=citable,
                citable_pins=citable_pins,
                uncitable=refused,
            )
        )
    titles = {s.number: s.title for s in index.sections if s.number}
    return CardCorpus(
        part=part or index.part_number or part_dir.name,
        part_dir=part_dir,
        library_dir=index.library_dir,
        documents=tuple(documents),
        section_titles=titles,
    )


# --- selection -------------------------------------------------------------


def record_text(record: SpecRecord) -> str:
    """The record's own identity text, space-fenced for phrase matching.

    Symbol *and* name, because vendors disagree about which column holds
    which: TI prints `TJ` / `Junction temperature`, and the layout floor
    records `Junction temperature` as the symbol where a datasheet prints no
    symbol column at all.
    """
    return padded(f"{record.symbol} {record.name}")


def base_unit(record: SpecRecord) -> str:
    """The record's printed unit resolved to a base unit (`mA` -> `A`).

    `""` when the record printed no unit — which is a real state and not the
    same as an unrecognised one, so a group has to opt into it with
    `unitless: true` rather than getting it by accident.
    """
    resolution = resolve_unit(record.unit)
    return resolution.unit_si if resolution is not None else ""


def matches_group(record: SpecRecord, group: GroupSpec, family: str) -> bool:
    """Whether one record belongs in one group — the whole selector rule.

    Documented pure function: excludes first, then a family or phrase hit,
    then the unit filter. `family` is the alias-lexicon symbol that claims the
    record (`""` when none does), passed in because resolving it once per
    record is what keeps a 619-record corpus cheap to select over.
    """
    text = record_text(record)
    if any(padded(phrase) in text for phrase in group.exclude):
        return False
    hit = bool(family and family in group.families)
    if not hit:
        hit = any(padded(phrase) in text for phrase in group.patterns)
    if not hit:
        return False
    if group.units:
        unit = base_unit(record)
        if unit not in group.units and not (group.unitless and not unit):
            return False
    return True


def _family_of(record: SpecRecord, lexicon: AliasLexicon) -> str:
    entry = lexicon.entry_for(record.symbol, record.name)
    return entry.symbol if entry is not None else ""


# --- building one value ----------------------------------------------------


def _weaker(*grades: Confidence) -> Confidence:
    """The least trustworthy of several grades — how a computed value is graded."""
    known = [g for g in grades if g in _CONFIDENCE_ORDER]
    if not known:
        return Confidence.UNKNOWN
    return max(known, key=_CONFIDENCE_ORDER.index)


def format_number(value: float) -> str:
    """A computed number, rendered the way a datasheet would print it."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:g}"


def cell_value(
    record: SpecRecord,
    cell: str,
    *,
    source: str,
    parsed: dict[str, Quantity | None] | None = None,
) -> DerivedValue | None:
    """One printed cell as a provenance-carrying value; `None` when unprinted.

    Clause (a) when the print is not a quantity (`See Figure 7`,
    `VDDRX1P8+0.3`) — copied verbatim, no number, and honest about it. Clause
    (b) when `parse_quantity` reads it, which adds `value_si` beside the
    print without ever replacing it.
    """
    printed = (getattr(record, cell, "") or "").strip()
    if not printed:
        return None
    parsed = parse_record_cells(record) if parsed is None else parsed
    quantity = parsed.get(cell)
    if quantity is not None:
        return quantity.to_derived_value(
            source=source,
            page=record.page,
            confidence=record.confidence,
            verbatim=printed,
        )
    return DerivedValue.copied(
        printed, source=source, page=record.page, confidence=record.confidence
    )


# --- sweep groups ----------------------------------------------------------


@dataclass
class _Build:
    """A card under construction: rows keyed by their group, plus the honesty."""

    rows: list[tuple[str, CardRow]] = field(default_factory=list)
    headings: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)


def _sweep_group(
    build: _Build,
    corpus: CardCorpus,
    group: GroupSpec,
    kind: str,
    lexicon: AliasLexicon,
) -> None:
    """Every record this group claims becomes one row, in printed order."""
    matched = 0
    valueless = 0
    uncitable = 0
    for doc in corpus.documents:
        for position, record in enumerate(doc.records):
            family = _family_of(record, lexicon)
            if not matches_group(record, group, family):
                continue
            matched += 1
            if not doc.can_cite(position, record):
                uncitable += 1
                continue
            source = doc.spec_source(record)
            parsed = parse_record_cells(record)
            values = {}
            for cell in group.cells:
                value = cell_value(record, cell, source=source, parsed=parsed)
                if value is not None:
                    values[cell] = value
            if not values:
                valueless += 1
                continue
            build.sources.add(f"{doc.ref_base}/{SPECS_ARTIFACT}")
            build.rows.append(
                (
                    group.id,
                    CardRow(
                        label=record.name or record.symbol,
                        symbol=family or record.symbol,
                        values=values,
                        note=corpus.section_title(record.section),
                    ),
                )
            )
    _record_group_honesty(build, kind, group, matched, valueless, uncitable)


def _record_group_honesty(
    build: _Build, kind: str, group: GroupSpec, matched: int, valueless: int, uncitable: int
) -> None:
    """Say out loud what a group looked for and did not get."""
    if matched == 0:
        build.unresolved.append(
            f"{kind}/{group.id}: no published record matched {group.describe()}"
        )
        return
    if valueless:
        build.unresolved.append(
            f"{kind}/{group.id}: {valueless} matching row(s) printed nothing in "
            f"{'/'.join(group.cells) or 'any cell'} — table headings and section rows, "
            f"kept out rather than shown as blank parameters"
        )
    if uncitable:
        build.unresolved.append(
            f"{kind}/{group.id}: {uncitable} matching row(s) could not be cited so that "
            f"the citation resolves back to them (no printed page recorded, or a record id "
            f"shared with an earlier row); no value is emitted for a record this tool "
            f"cannot address"
        )


def _pin_group(build: _Build, corpus: CardCorpus, group: GroupSpec, kind: str) -> None:
    """One row per distinct supply-pin *name*, with how many pins carry it.

    A part's rails are named a handful of times and pinned out dozens of
    times; the designer's question is "which rails, and how many balls each",
    so the count is the derived value (`count_pins_by_name`, clause (b)) and
    the first pin carrying the name is the citation.
    """
    matched = 0
    uncitable = 0
    for doc in corpus.documents:
        first: dict[str, PinRecord] = {}
        counts: Counter[str] = Counter()
        for position, pin in enumerate(doc.pins):
            if pin.type not in group.pin_types:
                continue
            matched += 1
            key = pin.name or pin.pin
            counts[key] += 1
            if key not in first and doc.can_cite(position, pin, pins=True):
                first[key] = pin
        for key, count in counts.items():
            anchor = first.get(key)
            if anchor is None:
                uncitable += count
                continue
            source = doc.pin_source(anchor)
            build.sources.add(f"{doc.ref_base}/{PINS_ARTIFACT}")
            build.rows.append(
                (
                    group.id,
                    CardRow(
                        label=key,
                        symbol=key,
                        values={
                            "pin": DerivedValue.copied(
                                anchor.pin,
                                source=source,
                                page=anchor.page,
                                confidence=anchor.confidence,
                            ),
                            "type": DerivedValue.labeled(
                                anchor.type,
                                source=source,
                                page=anchor.page,
                                confidence=anchor.confidence,
                            ),
                            "count": DerivedValue(
                                verbatim=str(count),
                                value_si=float(count),
                                value_kind=VALUE_KIND_POINT,
                                source=source,
                                page=anchor.page,
                                derivation=DERIVATION_PIN_COUNT,
                                confidence=anchor.confidence,
                            ),
                        },
                    ),
                )
            )
    _record_group_honesty(build, kind, group, matched, 0, uncitable)


# --- the limits join -------------------------------------------------------


@dataclass(frozen=True)
class LimitCandidate:
    """One row of one side of the `limits` join, with the limit it printed."""

    record: SpecRecord
    doc: CardDocument
    side: SideSpec
    cell: str
    printed: str
    quantity: Quantity | None
    #: The join key: the alias family that claims the record, or its own
    #: normalized symbol when the lexicon claims nothing.
    family: str
    #: The alias family alone, `""` when the lexicon claims nothing.
    alias: str
    section_title: str

    @property
    def display_symbol(self) -> str:
        """What the card prints in its Symbol column.

        The alias family when the lexicon claims the record, otherwise the
        symbol *as printed*. `family` is a normalized join key and is not fit
        to be shown: `Pin Volatge Range` is what the datasheet printed, typo
        and all, and clause (a) says a card prints what the datasheet printed.
        """
        return self.alias or self.record.symbol

    @property
    def source(self) -> str:
        return self.doc.spec_source(self.record)

    @property
    def label(self) -> str:
        return self.record.name or self.record.symbol

    @property
    def identities(self) -> tuple[str, ...]:
        """The printed identity strings this row may be joined on.

        Both the symbol and the name, normalized: the abs-max table prints
        the rail set in its *name* column (`DVDD0P9, VDDT0P9`) where the
        recommended table prints it as the *symbol*, and the pairing a
        designer sees on the page is exactly that string appearing twice.
        """
        return tuple(
            sorted(
                {padded(text).strip() for text in (self.record.symbol, self.record.name) if text}
            )
        )

    def value(self) -> DerivedValue:
        return cell_value(self.record, self.cell, source=self.source) or DerivedValue.missing(
            f"no {self.cell} printed"
        )

    def cite(self) -> str:
        page = f"p.{self.record.page}" if self.record.page else "no page"
        return f"{self.label} ({self.side.label}, {page})"


def _side_for(record: SpecRecord, section_title: str, sides: Sequence[SideSpec]) -> SideSpec | None:
    """Which limits table this record was printed in, from text it printed.

    The section title decides when the manifest has one; otherwise the
    table's own conditions line does. Sides are tried in declaration order,
    absolute-maximum first, because an absolute-maximum table's preamble
    routinely names the operating conditions it is *not*.
    """
    title = padded(section_title)
    text = padded(f"{record.table_conditions} {record.conditions}")
    for side in sides:
        if title.strip() and any(padded(p) in title for p in side.section_patterns):
            return side
    for side in sides:
        if any(padded(p) in text for p in side.text_patterns):
            return side
    return None


def _candidates(
    corpus: CardCorpus, spec: CardSpec, lexicon: AliasLexicon
) -> tuple[list[LimitCandidate], int]:
    """Every row of both limits tables that printed the limit being compared."""
    found: list[LimitCandidate] = []
    uncitable = 0
    for doc in corpus.documents:
        for position, record in enumerate(doc.records):
            title = corpus.section_title(record.section)
            side = _side_for(record, title, spec.sides)
            if side is None:
                continue
            cell = next(
                (c for c in side.compare_cells if (getattr(record, c, "") or "").strip()), ""
            )
            if not cell:
                continue
            if not doc.can_cite(position, record):
                uncitable += 1
                continue
            printed = (getattr(record, cell) or "").strip()
            alias = _family_of(record, lexicon)
            found.append(
                LimitCandidate(
                    record=record,
                    doc=doc,
                    side=side,
                    cell=cell,
                    printed=printed,
                    quantity=parse_record_cells(record).get(cell),
                    family=alias or padded(record.symbol).strip(),
                    alias=alias,
                    section_title=title,
                )
            )
    return found, uncitable


def _pair(
    candidates: Sequence[LimitCandidate], sides: Sequence[SideSpec]
) -> tuple[list[tuple[LimitCandidate, LimitCandidate]], list[tuple[LimitCandidate, str]]]:
    """Join the two sides by printed identity, then by alias family.

    Two rungs, both exact and both refusing to guess:

    1. **Printed identity** — a string one side printed as its symbol and the
       other printed as its name (or either as either). Paired only when that
       string names exactly one row on each side.
    2. **Alias family** — the rule the plan states, applied to what rung 1
       left over, and only where the family has exactly one unpaired row on
       each side.

    Anything still unpaired is returned as such, with a reason. An ambiguous
    family is never resolved by position or by nearest value: three supply
    rails against three supply rails is a pairing the datasheet made and this
    tool did not read, and inventing one would put a margin on the wrong rail.
    """
    if len(sides) != 2:
        return [], [(c, "the card lexicon does not declare two sides to join") for c in candidates]
    left, right = sides[0].id, sides[1].id
    by_side = {
        left: [c for c in candidates if c.side.id == left],
        right: [c for c in candidates if c.side.id == right],
    }
    paired: list[tuple[LimitCandidate, LimitCandidate]] = []
    used: set[int] = set()
    ambiguous: dict[int, str] = {}

    def _free(side: str) -> list[LimitCandidate]:
        return [c for c in by_side[side] if id(c) not in used]

    identities: dict[str, dict[str, list[LimitCandidate]]] = {}
    for candidate in candidates:
        for identity in candidate.identities:
            identities.setdefault(identity, {left: [], right: []})[candidate.side.id].append(
                candidate
            )
    for identity in sorted(identities):
        both = identities[identity]
        a = [c for c in both[left] if id(c) not in used]
        b = [c for c in both[right] if id(c) not in used]
        if len(a) == 1 and len(b) == 1:
            used.update({id(a[0]), id(b[0])})
            paired.append((a[0], b[0]))

    families = sorted({c.family for c in candidates if c.family})
    for family in families:
        a = [c for c in _free(left) if c.family == family]
        b = [c for c in _free(right) if c.family == family]
        if len(a) == 1 and len(b) == 1:
            used.update({id(a[0]), id(b[0])})
            paired.append((a[0], b[0]))
        elif a and b:
            reason = (
                f"{len(a)} {sides[0].label.lower()} row(s) and {len(b)} "
                f"{sides[1].label.lower()} row(s) share the symbol family {family} and "
                f"nothing printed says which pairs with which"
            )
            for candidate in a + b:
                ambiguous[id(candidate)] = reason

    unpaired: list[tuple[LimitCandidate, str]] = []
    for candidate in candidates:
        if id(candidate) in used:
            continue
        other = sides[1] if candidate.side.id == left else sides[0]
        unpaired.append(
            (
                candidate,
                ambiguous.get(
                    id(candidate),
                    f"nothing on the {other.label.lower()} side names this parameter",
                ),
            )
        )
    return paired, unpaired


def compute_margin(high: Quantity | None, low: Quantity | None) -> tuple[float, str] | None:
    """`(margin, unit)` between two parsed limits, or `None` when it cannot be.

    The documented pure function behind `abs_max_margin`: the absolute
    maximum minus the recommended maximum, in the unit both were normalized
    to. `None` — never a guess — when either side did not parse or the two
    units are not the same thing.
    """
    if high is None or low is None:
        return None
    if high.unit_si != low.unit_si:
        return None
    return high.high - low.high, high.unit_si


def _margin_row(abs_max: LimitCandidate, recommended: LimitCandidate) -> tuple[CardRow, str | None]:
    """One compared parameter; the second element is an `unresolved` line."""
    values = {
        abs_max.side.id: abs_max.value(),
        recommended.side.id: recommended.value(),
    }
    computed = compute_margin(abs_max.quantity, recommended.quantity)
    flags: list[str] = []
    notes: list[str] = []
    unresolved: str | None = None

    if computed is None:
        reason = (
            f"{abs_max.side.label} {abs_max.printed!r} and {recommended.side.label} "
            f"{recommended.printed!r} did not both parse to a number in the same unit"
        )
        values["margin"] = DerivedValue.missing(reason, derivation=DERIVATION_MARGIN)
        unresolved = f"{abs_max.label}: {reason} — no margin computed"
    else:
        margin, unit = computed
        values["margin"] = DerivedValue(
            verbatim=f"{format_number(margin)} {unit}".strip(),
            value_si=margin,
            unit_si=unit,
            value_kind=VALUE_KIND_POINT,
            source=abs_max.source,
            page=abs_max.record.page,
            derivation=DERIVATION_MARGIN,
            confidence=_weaker(abs_max.record.confidence, recommended.record.confidence),
        )
        if math.isclose(margin, 0.0, rel_tol=0.0, abs_tol=0.0):
            flags.append(FLAG_ZERO_MARGIN)
            notes.append(
                f"zero margin — the {recommended.side.label.lower()} maximum "
                f"({recommended.printed}) equals the {abs_max.side.label.lower()} "
                f"rating ({abs_max.printed})"
            )
        elif margin < 0:
            flags.append(FLAG_NEGATIVE_MARGIN)
            notes.append(
                f"the {recommended.side.label.lower()} maximum ({recommended.printed}) is "
                f"above the {abs_max.side.label.lower()} rating ({abs_max.printed}) as printed"
            )
    if abs_max.section_title or recommended.section_title:
        notes.append(
            " / ".join(sorted({t for t in (abs_max.section_title, recommended.section_title) if t}))
        )
    return (
        CardRow(
            label=abs_max.label,
            symbol=abs_max.display_symbol,
            values=values,
            note="; ".join(notes),
            flags=flags,
        ),
        unresolved,
    )


def _limits_card(build: _Build, corpus: CardCorpus, spec: CardSpec, lexicon: AliasLexicon) -> None:
    """The `limits` card: join, compare, and list everything left over."""
    if len(spec.sides) != 2:
        build.unresolved.append(
            f"{CARD_LIMITS}: the card lexicon declares {len(spec.sides)} side(s); "
            f"the join needs exactly two"
        )
        return
    abs_side, rec_side = spec.sides
    candidates, uncitable = _candidates(corpus, spec, lexicon)
    if uncitable:
        build.unresolved.append(
            f"{CARD_LIMITS}: {uncitable} limit row(s) could not be cited so that the "
            f"citation resolves back to them; they are left out rather than compared "
            f"under another row's id"
        )
    if not candidates:
        build.unresolved.append(
            f"{CARD_LIMITS}: no {abs_side.label.lower()} or {rec_side.label.lower()} table "
            f"was identified among this part's published spec records — the join has "
            f"nothing to compare"
        )
        return
    for side in (abs_side, rec_side):
        if not any(c.side.id == side.id for c in candidates):
            build.unresolved.append(
                f"{CARD_LIMITS}: no {side.label.lower()} table was identified, so every "
                f"row below is one-sided and no margin is computed"
            )

    paired, unpaired = _pair(candidates, spec.sides)
    for candidate in candidates:
        build.sources.add(f"{candidate.doc.ref_base}/{SPECS_ARTIFACT}")

    ordered = sorted(paired, key=lambda pair: (pair[0].record.section, pair[0].record.row_index))
    for abs_max, recommended in ordered:
        row, unresolved = _margin_row(abs_max, recommended)
        build.headings.setdefault("compared", "Compared")
        build.rows.append(("compared", row))
        if unresolved:
            build.unresolved.append(f"{CARD_LIMITS}: {unresolved}")

    for candidate, reason in sorted(
        unpaired, key=lambda pair: (pair[0].record.section, pair[0].record.row_index)
    ):
        other = rec_side if candidate.side.id == abs_side.id else abs_side
        values = {
            candidate.side.id: candidate.value(),
            other.id: DerivedValue.missing(reason),
            "margin": DerivedValue.missing(f"not compared: {reason}", derivation=DERIVATION_MARGIN),
        }
        build.headings.setdefault("uncompared", "Not compared")
        build.rows.append(
            (
                "uncompared",
                CardRow(
                    label=candidate.label,
                    symbol=candidate.display_symbol,
                    values=values,
                    note=candidate.section_title,
                ),
            )
        )
        build.unresolved.append(f"{CARD_LIMITS}: {candidate.cite()} — {reason}")


# --- building a card -------------------------------------------------------


def build_card(
    corpus: CardCorpus,
    kind: str,
    *,
    lexicon: AliasLexicon | None = None,
    card_lexicon: CardLexicon | None = None,
    card_version: str = "",
) -> Card:
    """Build one design card from one part's published records.

    Never raises and never returns `None`: a part with nothing to say produces
    an honest empty card — no rows, `unresolved` naming what was looked for —
    because "this datasheet prints no thermal information" is an answer and a
    missing file is not.
    """
    aliases = lexicon or load_lexicon()
    cards = card_lexicon or load_card_lexicon()
    version = card_version or get_settings().card_version
    spec = cards.get(kind)
    build = _Build()

    if spec is None:
        build.unresolved.append(
            f"{kind}: no selectors for this card in {CARD_LEXICON_PATH.name}; nothing was "
            f"looked for, so nothing is claimed"
        )
    elif not corpus.has_records:
        build.unresolved.append(
            f"{kind}: this part publishes no spec records — either its documents were "
            f"extracted by the degraded text backend (no trusted tables) or nothing has "
            f"been built for it yet"
        )
    elif spec.sides:
        _limits_card(build, corpus, spec, aliases)
    else:
        for group in spec.groups:
            build.headings.setdefault(group.id, group.heading or group.id)
            if group.from_pins:
                _pin_group(build, corpus, group, kind)
            else:
                _sweep_group(build, corpus, group, kind, aliases)

    if corpus.uncitable:
        build.warnings.append(
            f"{corpus.uncitable} published spec record(s) in this part share a record id "
            f"with an earlier row and cannot be addressed unambiguously; a card never "
            f"cites one of them"
        )
    order = list(build.headings)
    ordered = sorted(build.rows, key=lambda pair: order.index(pair[0]) if pair[0] in order else 0)
    rows = [
        row.model_copy(
            update={
                "note": GROUP_SEPARATOR.join(
                    part for part in (build.headings.get(group_id, ""), row.note) if part
                )
            }
        )
        for group_id, row in ordered
    ]
    return Card(
        part_number=corpus.part,
        card=kind,
        schema_version=CARDS_SCHEMA_VERSION,
        card_version=version,
        rows=rows,
        unresolved=build.unresolved,
        warnings=build.warnings,
        sources=sorted(build.sources),
    )


def build_part_cards(
    part_dir: Path | str,
    part: str = "",
    kinds: Sequence[str] = CARD_KINDS,
    *,
    card_version: str = "",
) -> dict[str, Card]:
    """Every requested card for one part, built from one load of its corpus."""
    corpus = load_card_corpus(part_dir, part)
    aliases = load_lexicon()
    cards = load_card_lexicon()
    return {
        kind: build_card(
            corpus, kind, lexicon=aliases, card_lexicon=cards, card_version=card_version
        )
        for kind in kinds
    }


# --- rendering -------------------------------------------------------------


def _escape(text: str) -> str:
    """Markdown-table safe: a printed `|` must not become a column break."""
    return (text or "").replace("|", "\\|")


def _cell_text(value: DerivedValue) -> str:
    """One table cell: the print, or the honest reason there is none."""
    if not value.filled:
        return f"— *{_escape(value.null_reason)}*" if value.null_reason else "—"
    return _escape(value.verbatim)


def _citation(value: DerivedValue, *, show_doc: bool) -> str:
    parsed = parse_source(value.source)
    doc = ""
    if parsed is not None:
        artifact = parsed[0]
        parts = artifact.replace("@library/", "").split("/")
        doc = parts[1] if len(parts) > 1 and parts[0] == "docs" else parts[0]
    page = f"p.{value.page}" if value.page else ""
    if show_doc and doc:
        return f"{doc} {page}".strip()
    return page or (doc or "")


def row_citation(row: CardRow, *, show_doc: bool = False) -> str:
    """The citation printed on one rendered row — never empty for a filled row.

    Every value on a row carries its own `source`; the row's citation is the
    distinct pages those sources sit on, which is what a reader opens.
    """
    seen: list[str] = []
    for value in row.values.values():
        if not value.filled:
            continue
        label = _citation(value, show_doc=show_doc)
        if label and label not in seen:
            seen.append(label)
    return ", ".join(seen)


def render_card(card: Card, *, spec: CardSpec | None = None) -> str:
    """The rendered `cards/<kind>.md`: a banner, a citation on every row.

    The banner names `card_version` because a card on a screen has to say
    which derivation rules produced it, and the rendered file is the copy a
    human is most likely to be looking at.
    """
    cards = load_card_lexicon()
    spec = spec or cards.get(card.card)
    title = spec.title if spec else card.card.title()
    show_doc = len(card.sources) > 1
    out: list[str] = [
        BANNER.format(version=card.card_version),
        (
            f"<!-- derived: schema {card.schema_version} · deterministic, no model call "
            f"in this path (invariant 8, ADR 0007) -->"
        ),
        "",
        f"# {card.part_number} — {title}",
        "",
    ]
    if spec and spec.intent:
        out += [f"> {spec.intent}", ""]

    if not card.rows:
        out += [
            "**This card is empty.** Nothing this part publishes matched its selectors.",
            "The list below is what was looked for — an empty card is an answer, and",
            "no value here has been guessed at or interpolated.",
            "",
        ]

    groups: list[tuple[str, list[tuple[CardRow, str]]]] = []
    for row in card.rows:
        heading, separator, rest = row.note.partition(GROUP_SEPARATOR)
        if not separator:
            heading, rest = "", row.note
        if not groups or groups[-1][0] != heading:
            groups.append((heading, []))
        groups[-1][1].append((row, rest))

    for heading, entries in groups:
        if heading:
            out += [f"## {heading}", ""]
        keys = [key for row, _rest in entries for key in row.values]
        columns = [c for c in COLUMN_ORDER if c in keys]
        columns += [c for c in dict.fromkeys(keys) if c not in COLUMN_ORDER]
        header = ["Parameter", "Symbol"] + [COLUMN_HEADINGS.get(c, c.title()) for c in columns]
        header += ["Note", "Source"]
        out.append("| " + " | ".join(header) + " |")
        out.append("|" + "|".join("---" for _ in header) + "|")
        for row, rest in entries:
            cells = [_escape(row.label) or "—", _escape(row.symbol) or "—"]
            cells += [_cell_text(row.values[c]) if c in row.values else "" for c in columns]
            note = _escape(rest)
            if row.flags:
                flags = f"**{', '.join(row.flags)}**"
                note = f"{flags} — {note}" if note else flags
            cells += [note or "—", row_citation(row, show_doc=show_doc) or "—"]
            out.append("| " + " | ".join(cell.replace("\n", " ") for cell in cells) + " |")
        out.append("")

    if card.unresolved:
        out += ["## Not filled", ""]
        out += [f"- {line}" for line in card.unresolved]
        out.append("")
    if card.warnings:
        out += ["## Warnings", ""]
        out += [f"- {line}" for line in card.warnings]
        out.append("")
    out += [
        "## Sources",
        "",
    ]
    out += [f"- `{source}`" for source in card.sources] or ["- none"]
    out.append("")
    return "\n".join(out)


# --- publishing ------------------------------------------------------------


def card_paths(part_dir: Path | str, kind: str) -> tuple[Path, Path]:
    """`(cards/<kind>.json, cards/<kind>.md)` under a part directory."""
    cards_dir = Path(part_dir) / CARDS_DIRNAME
    return cards_dir / f"{kind}.json", cards_dir / f"{kind}.md"


def _write_if_changed(path: Path, text: str) -> Path:
    """Atomic, and a no-op when the bytes already match.

    The same contract every shared artifact is written under: `dsa batch
    --workers N` can have two jobs publishing one part's cards at once, and a
    half-written card would read as a corrupt one to anything holding it open.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.read_text(encoding="utf-8") == text:
            return path
    except (OSError, ValueError):
        pass
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def write_card(part_dir: Path | str, card: Card) -> tuple[Path, Path]:
    """Publish one card as JSON and as rendered markdown."""
    json_path, md_path = card_paths(part_dir, card.card)
    _write_if_changed(json_path, card.model_dump_json(indent=2))
    _write_if_changed(md_path, render_card(card))
    return json_path, md_path


def load_card(part_dir: Path | str, kind: str, *, card_version: str = "") -> Card | None:
    """Read a published card, or `None` when it is absent or **stale**.

    Stale means built by different rules: a `schema_version` this reader does
    not speak, or a `card_version` other than the one in force. Returning
    `None` is what makes `DSA_CARD_VERSION` regenerate a card instead of
    leaving one on disk whose numbers no longer follow from the rule that is
    written down — the same publish-cache-key contract `publish.cards_current`
    enforces for the batch skip gate.
    """
    version = card_version or get_settings().card_version
    path, _md = card_paths(part_dir, kind)
    if not path.is_file():
        return None
    try:
        card = Card.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("unreadable %s: %s", path, exc)
        return None
    if card.schema_version != CARDS_SCHEMA_VERSION or card.card_version != version:
        return None
    return card


def load_or_build_card(
    part_dir: Path | str,
    part: str = "",
    kind: str = "",
    *,
    write: bool = True,
    card_version: str = "",
) -> Card:
    """The published card if it is current, otherwise a freshly built one.

    `write=True` republishes what it built, which is what makes a
    `DSA_CARD_VERSION` bump actually replace the stale file rather than
    shadow it in memory.
    """
    existing = load_card(part_dir, kind, card_version=card_version)
    if existing is not None:
        return existing
    card = build_part_cards(part_dir, part, [kind], card_version=card_version)[kind]
    if write:
        try:
            write_card(part_dir, card)
        except OSError as exc:  # a read-only corpus is still answerable
            log.warning("could not publish %s card for %s: %s", kind, part, exc)
    return card


def publish_part_cards(
    part_dir: Path | str, part: str = "", kinds: Sequence[str] = CARD_KINDS
) -> dict[str, Card]:
    """Build and write every card for one part; returns what was written."""
    cards = build_part_cards(part_dir, part, kinds)
    for card in cards.values():
        write_card(part_dir, card)
    return cards


# --- the invariant-8 walk --------------------------------------------------


@dataclass(frozen=True)
class CardAudit:
    """The result of walking every `source` on a card back to a record.

    `problems` empty is the pass condition of the phase's most important
    test: no orphan values, no value without provenance, no citation that
    lands on a page the record is not printed on.
    """

    card: str = ""
    checked: int = 0
    resolved: int = 0
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

    def describe(self) -> str:
        if self.ok:
            return (
                f"{self.card}: {self.resolved}/{self.checked} filled value(s) resolve to a "
                f"record and a printed page"
            )
        lines = "\n".join(f"  - {p}" for p in self.problems)
        return f"{self.card}: {len(self.problems)} provenance violation(s)\n{lines}"


def audit_card(
    card: Card, *, part_dir: Path | str, library_dir: Path | str | None = None
) -> CardAudit:
    """Resolve every value on a card back to the record and page it cites.

    The structural half is `derive/provenance.check_provenance` — one
    implementation of the rule, shared with every other derived artifact. The
    resolution half memoizes by `source` string, because a row's four cells
    cite one record and re-reading `specs.json` once per *cell* turns a
    one-second walk into a minute of JSON parsing.
    """
    problems = list(check_provenance(card))
    cache: dict[str, object] = {}
    checked = resolved = 0
    for path, value in _iter_values(card):
        if not value.filled:
            continue
        checked += 1
        if value.source not in cache:
            cache[value.source] = resolve_source(
                value.source, roots=[Path(part_dir)], library_dir=library_dir
            )
        found = cache[value.source]
        if found is None:
            problems.append(f"{path}: source {value.source!r} resolves to no record on disk")
            continue
        resolved += 1
        page = getattr(found, "page", None)
        if page is not None and value.page is not None and page != value.page:
            problems.append(
                f"{path}: cites p.{value.page} but {value.source} is printed on p.{page}"
            )
    return CardAudit(card=card.card, checked=checked, resolved=resolved, problems=tuple(problems))


def _iter_values(card: Card) -> Iterable[tuple[str, DerivedValue]]:
    """Every `DerivedValue` on a card, with a readable path to each."""
    for index, row in enumerate(card.rows):
        for key, value in row.values.items():
            yield f"rows[{index}]({row.label}).values[{key}]", value


# --- CLI -------------------------------------------------------------------


def scoped_part_dirs(args: argparse.Namespace) -> tuple[list[tuple[str, Path]], str]:
    """`([(part, dir)], "")` for the requested scope, or `([], reason)`.

    ADR 0006's rule — exactly one of `--part` / `--project` — reused rather
    than re-decided. Cards are read off published artifacts, so this resolves
    to directories rather than to a `Retriever`.
    """
    from datasheet_analyzer.projects import ProjectError, is_built, load_project, part_dirs
    from datasheet_analyzer.retrieve.scope import SCOPE_ERROR, no_corpus_error

    settings = get_settings()
    part = (getattr(args, "part", "") or "").strip()
    project = (getattr(args, "project", "") or "").strip()
    if bool(part) == bool(project):
        return [], SCOPE_ERROR
    if part:
        if not is_built(part, settings.parts_dir):
            return [], no_corpus_error(part, settings=settings)
        return [(part, settings.parts_dir / part)], ""
    try:
        loaded = load_project(project, settings.projects_dir)
    except ProjectError as exc:
        return [], str(exc)
    return [(d.name, d) for d in part_dirs(loaded, settings.parts_dir)], ""


def cli_card(args: argparse.Namespace) -> int:
    """`dsa card --part X --card power [--json]`.

    Exit codes match the other deterministic lookups: 0 when the card has
    rows, 1 for an honest empty card — a real answer, and the reason is
    printed with it — and 2 for a scope that could not be resolved.
    """
    parts, reason = scoped_part_dirs(args)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    kind = (getattr(args, "card", "") or "").strip()
    if kind not in CARD_KINDS:
        print(
            f"dsa card: unknown card {kind!r}; expected one of {', '.join(CARD_KINDS)}",
            file=sys.stderr,
        )
        return 2

    cards = [load_or_build_card(part_dir, part, kind) for part, part_dir in parts]
    if getattr(args, "json", False):
        payload = {
            "part": getattr(args, "part", ""),
            "project": getattr(args, "project", ""),
            "card": kind,
            "cards": [json.loads(card.model_dump_json()) for card in cards],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(render_card(card) for card in cards))
    return 0 if any(card.rows for card in cards) else 1
