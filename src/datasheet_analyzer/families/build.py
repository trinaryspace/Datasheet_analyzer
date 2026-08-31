"""Several members of one series -> one index: the "what is different?" question.

Phase 7, ticket 07. A family index is a **view**, in exactly the sense a design
card (`cards/build.py`), a cross-part comparison (`compare/build.py`) and a
revision diff (`revdiff/build.py`) are: it owns no printed value, it quotes
records its member corpora already publish, and it says of every number where it
came from. ADR 0005 governs it whole —

- **(a)** every printed value is a cell copied verbatim into its envelope with
  its printed unit (`copy_cell`), from the member's own published record;
- **(b)** the only number it adds is the **delta**, the same documented pure
  function `dsa compare` uses (`si_delta:<column>`), computed only where the
  numeric layer read two members' values into the same SI base;
- **(c)** the structural label is the alignment key — the printed row inside the
  printed section for a spec, the printed designator for a pin, the parsed
  address for a register, the printed name for a bit field.

Five rules govern the module, and each one is a refusal.

**Membership is never inferred.** This module is handed its members; who they
are is `registry/families.yaml`'s answer and nobody else's (`families/registry.py`
carries that rule and the suggester that may only propose). A wrong grouping
would put another part's numbers in front of a designer with no visible seam.

**A section is shared only when it is identical everywhere.** Same printed title
in every member, and byte-identical body text in every member — the
`<!-- source: ... -->` provenance line excepted, because it names each member's
own revision and pages and so always differs. One value that moved makes the
section `divergent` and it is listed per member with its own page and file. That
is the ticket's second criterion, and it is the honest form of the token win: a
section listed once is one a reader may genuinely read once.

**Specs align on the row as printed, inside the section as printed.** Not on the
alias-resolved symbol, which is right for two *unrelated* parts and wrong here: a
family's members are one vendor's one document template, so `IVDD1P8` and
`IVDD1P2` are two rows a reader must see apart, and an alias key would collapse
them and then refuse them both as ambiguous. The key is therefore
`(family section, printed symbol, printed name, printed conditions)`, every part
of it compared character for character after the shared `normalize`. Everything
downstream — the identity tie-break, the per-part refusal of an ambiguous key,
the delta, the unparsed population — is `compare/build.py`'s, reached through its
`key_for` hook: one alignment engine, two artifacts.

**Only what differs is a row.** A parameter every member prints identically is
counted, not tabulated — that count *is* the family's claim, and re-printing 379
agreeing rows would cost more than reading both members' indexes. A row that one
member does not print is a row (flagged `only-in`), because during a
series-selection decision an absent parameter is the finding.

**A pin name, a register reset and a bit range are never scored.** They are
quoted verbatim on both sides and given no delta, no sign and no direction —
`revdiff` refuses a reset for the same reason, and it is worth restating: a
signed difference between two bit patterns is a number that means nothing and
looks like it means something.

Nothing is dropped. Every alignment this module refused is listed with its
printed values, and the notes carry the population sentences invariant 8 requires
of a consumer that compares.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from datasheet_analyzer.compare.build import (
    FLAG_AMBIGUOUS,
    FLAG_ONLY_IN,
    ComparePart,
    CompareRecord,
    build_spec_comparison,
)
from datasheet_analyzer.config import CARD_VERSION, FAMILY_SCHEMA_VERSION
from datasheet_analyzer.models import (
    ComparisonCell,
    ComparisonRow,
    Confidence,
    DerivedValue,
    FamilyIndex,
    FamilySection,
    PinRecord,
    RegisterRecord,
    SectionFile,
    SpecRecord,
)
from datasheet_analyzer.provenance import (
    PINS_ARTIFACT,
    REGISTERS_ARTIFACT,
    source_ref,
)
from datasheet_analyzer.retrieve.results import Citation
from datasheet_analyzer.structure.aliases import normalize
from datasheet_analyzer.tokens import count_tokens

#: What a section is to a family. `shared` is the strong claim and is the only
#: one that licenses reading the section once; `partial` is deliberately not
#: `divergent` — "some member does not print this at all" is a different fact
#: from "every member prints it and something moved".
STATE_SHARED = "shared"
STATE_DIVERGENT = "divergent"
STATE_PARTIAL = "partial"

#: How things aligned, recorded on every row and section so a mis-alignment is
#: readable rather than invisible. The spec key names the section it was scoped
#: to, because the same printed identity on two tables is two parameters.
ALIGNED_SECTION = "section-number"
ALIGNED_SECTION_TITLE = "section-title"
ALIGNED_ROW = "printed-row"
ALIGNED_PIN = "pin-designator"
ALIGNED_REGISTER = "register-address"
ALIGNED_FIELD = "field-name"

#: The rule a copied cell records — the same name `cards`, `compare` and
#: `revdiff` give the same act. One rule, four artifacts.
DERIVATION_CELL = "copy_cell"

#: Delta kinds, as a caller filters them.
KIND_SPEC = "spec"
KIND_PIN = "pin"
KIND_REGISTER = "register"
KIND_FIELD = "field"

#: The printed pin cells a family compares, in the order a reader reads them.
PIN_FIELDS: tuple[str, ...] = ("name", "type", "direction", "description")
#: The printed register cells a family compares. `reset` leads the ones that
#: matter: it configures silicon at power-up and is invisible in a section diff.
REGISTER_FIELDS: tuple[str, ...] = ("name", "reset", "access", "description")
#: The printed bit-field cells. `bits` first — a field that moved from `2:0` to
#: `3:1` compiles, runs and misconfigures silicon silently.
FIELD_FIELDS: tuple[str, ...] = ("bits", "access", "reset", "description")

#: The provenance line a section file opens with. Stripped before two members'
#: bodies are compared, because it names each member's own revision and pages
#: and would make every section divergent for a reason that is not about the
#: device.
_SOURCE_LINE = re.compile(r"^<!--\s*source:.*?-->\s*$", re.MULTILINE)


@dataclass(frozen=True)
class MemberRecord:
    """One published record on its way into a family row.

    `doc` is the corpus document directory it lives in, which is what a fully
    qualified `source` reference names.
    """

    doc: str
    record: object


@dataclass(frozen=True)
class FamilyMember:
    """One member corpus as the family index consumes it.

    Deliberately not a `CorpusIndex`: the corpus walk belongs to `retrieve/`, and
    taking the records keeps this module pure and testable from literals — the
    same split `compare.ComparePart` and `revdiff.RevisionSide` already make.

    `gap` is why this member contributed nothing, when it did: a declared member
    with no corpus on disk is **named**, never silently dropped, because a family
    index that quietly answered for two of three devices would be read as
    answering for all three.
    """

    part_number: str
    specs: tuple[CompareRecord, ...] = ()
    sections: tuple[SectionFile, ...] = ()
    bodies: Mapping[str, str] = field(default_factory=dict)
    pins: tuple[MemberRecord, ...] = ()
    registers: tuple[MemberRecord, ...] = ()
    gap: str = ""

    @property
    def built(self) -> bool:
        return not self.gap


def section_body(text: str) -> str:
    """One section file reduced to what two members can honestly be compared on.

    Two removals, both because they are facts about the *member* rather than
    about the section: the `<!-- source: ... -->` provenance line (each member's
    own revision and pages) and the `# N Title` heading, which carries the
    printed number a renumbered back-matter section changes without changing a
    word of its content. Trailing whitespace goes too — a layout floor that emits
    one extra space is not a difference a designer needs to review.
    """
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body = "\n".join(line.rstrip() for line in lines)
    return _SOURCE_LINE.sub("", body).strip()


def build_family_index(
    members: Sequence[FamilyMember],
    *,
    name: str,
    title: str = "",
) -> FamilyIndex:
    """The whole series as one artifact: shared once, differences tabulated.

    Order is fully determined by the declared membership and by each member's own
    publication order, so a rebuild of identical corpora reproduces the same index
    byte for byte.
    """
    built = [m for m in members if m.built]
    index = FamilyIndex(
        schema_version=FAMILY_SCHEMA_VERSION,
        card_version=CARD_VERSION,
        name=name,
        title=title,
        members=[m.part_number for m in members],
        reference=members[0].part_number if members else "",
    )
    for member in members:
        if member.gap:
            index.notes.append(f"{member.part_number}: {member.gap}")

    sections, section_key_of = _sections(built)
    index.sections.extend(sections)

    deltas, spec_notes, spec_unparsed, aligned, identical = _spec_deltas(
        built, section_key_of
    )
    index.deltas.extend(deltas)
    index.notes.extend(spec_notes)
    index.unparsed.extend(spec_unparsed)
    index.n_specs_aligned = aligned
    index.n_specs_identical = identical

    index.pin_deltas.extend(_pin_deltas(built))
    index.register_deltas.extend(_register_deltas(built))
    index.notes.extend(_artifact_notes(built))

    if not index.sections and not index.n_deltas:
        index.empty_reason = _empty_reason(members)
    return index


# --- sections ----------------------------------------------------------------


def _sections(
    members: Sequence[FamilyMember],
) -> tuple[list[FamilySection], dict[str, str]]:
    """Every section of the series once, plus the printed-number -> family map.

    Two exact rungs and no third. A section aligns on the **printed number**
    first; whatever is left over aligns on the **normalized printed title**, and
    only where that selects exactly one section in each member that has it —
    which is what makes a family whose members renumber their back matter (`§6.1`
    against `§5.1`, same title, same words) read as one section rather than as
    five appearing and five disappearing. Anything still unmatched is its own
    `partial` section, named to the members that print it.

    The returned map is `printed section number -> family section key`, which is
    how a spec row is scoped to the section it was printed in even when the
    members number that section differently: both `5` and `6` resolve to the one
    group their identically-titled sections folded into. A number resolves to
    exactly one group by construction — a number is placed in the group named
    after it, and the fold only ever merges groups with disjoint member sets.
    """
    parts = [m.part_number for m in members]
    groups: dict[str, dict[str, SectionFile]] = {}
    aligned_on: dict[str, str] = {}
    order: list[str] = []

    def _place(key: str, part: str, section: SectionFile, how: str) -> None:
        if key not in groups:
            groups[key] = {}
            aligned_on[key] = how
            order.append(key)
        groups[key][part] = section

    unmatched: list[tuple[str, SectionFile]] = []
    for member in members:
        for section in member.sections:
            number = section.number.strip()
            if number:
                _place(number, member.part_number, section, ALIGNED_SECTION)
            else:
                unmatched.append((member.part_number, section))

    # Rung two: the printed title, over sections no number placed. Counted per
    # member first, because a title two sections of one member share cannot tell
    # them apart and pairing on it would be the guess this rung exists to avoid.
    by_title: dict[str, list[tuple[str, SectionFile]]] = {}
    for part, section in unmatched:
        by_title.setdefault(normalize(section.title), []).append((part, section))
    for title_key, found in by_title.items():
        seen = [p for p, _ in found]
        if len(set(seen)) == len(seen):
            for part, section in found:
                _place(f"title:{title_key}", part, section, ALIGNED_SECTION_TITLE)
        else:
            for i, (part, section) in enumerate(found):
                _place(f"title:{title_key}#{i}", part, section, ALIGNED_SECTION_TITLE)

    # Rung three is not an alignment: a numbered section whose number no other
    # member prints, whose *title* another member does print under a number, is
    # still one section of the series. Fold those in, exactly-titled only.
    _fold_renumbered(groups, aligned_on)

    sections: list[FamilySection] = []
    key_of: dict[str, str] = {}
    for key in order:
        found = groups[key]
        if not found:
            continue
        present = [p for p in parts if p in found]
        missing = [p for p in parts if p not in found]
        reference = found[present[0]]
        bodies = {
            part: _body_of(members, part, found[part].file) for part in present
        }
        titles = {part: found[part].title.strip() for part in present}
        same_title = len(set(titles.values())) == 1
        same_body = len(set(bodies.values())) == 1
        state = (
            STATE_PARTIAL
            if missing
            else STATE_SHARED
            if same_title and same_body
            else STATE_DIVERGENT
        )
        sections.append(
            FamilySection(
                number=reference.number.strip(),
                title=reference.title.strip(),
                state=state,
                aligned_on=aligned_on[key],
                members=present,
                missing_from=missing,
                files={part: found[part].file for part in present},
                pages={part: _pages(found[part]) for part in present},
                titles=dict(titles),
                reason=_section_reason(
                    state, missing, parts, same_title=same_title, same_body=same_body
                ),
                tokens=count_tokens(bodies[present[0]]),
            )
        )
        for part in present:
            number = found[part].number.strip()
            if number:
                key_of[number] = key
    return sections, key_of


def _fold_renumbered(
    groups: dict[str, dict[str, SectionFile]],
    aligned_on: dict[str, str],
) -> None:
    """Merge two number-keyed groups whose members print the same title.

    The one move that makes a renumbered series legible, and it is exact: two
    groups merge only when neither has a member the other has (so nothing is
    overwritten) and every section in both prints **one** normalized title. A
    family whose members renumber §6 to §5 without changing a word then reads as
    one section; a family that reused a number for a different section does not
    merge, because the titles differ.
    """
    titles: dict[str, list[str]] = {}
    for key, found in groups.items():
        printed = {normalize(s.title) for s in found.values()}
        if len(printed) == 1:
            titles.setdefault(printed.pop(), []).append(key)
    for keys in titles.values():
        if len(keys) < 2:
            continue
        target = keys[0]
        for other in keys[1:]:
            if set(groups[target]) & set(groups[other]):
                continue
            groups[target].update(groups[other])
            groups[other] = {}
            aligned_on[target] = ALIGNED_SECTION_TITLE
    # The caller's `order` is left alone: an emptied group is skipped there, and
    # rebuilding the order here would make the output depend on dict iteration.


def _body_of(members: Sequence[FamilyMember], part: str, file: str) -> str:
    for member in members:
        if member.part_number == part:
            return member.bodies.get(file, "")
    return ""


def _pages(section: SectionFile) -> str:
    """`p.4-7` / `p.4` / `p.?` — a section's page range as a citation prints it."""
    start, end = section.page_start, section.page_end
    if start is None:
        return "p.?"
    if end is None or end == start:
        return f"p.{start}"
    return f"p.{start}-{end}"


def _section_reason(
    state: str,
    missing: Sequence[str],
    parts: Sequence[str],
    *,
    same_title: bool,
    same_body: bool,
) -> str:
    if state == STATE_SHARED:
        return ""
    if state == STATE_PARTIAL:
        return (
            f"printed by {len(parts) - len(missing)} of {len(parts)} members — "
            f"{', '.join(missing)} publishes no such section"
        )
    if not same_title and not same_body:
        return "printed under a different title, and its text differs"
    if not same_title:
        return "printed under a different title in each member"
    return "the members' text differs — read each member's own file"


# --- specs -------------------------------------------------------------------


def _spec_deltas(
    members: Sequence[FamilyMember],
    section_key_of: Mapping[str, str],
) -> tuple[list[ComparisonRow], list[str], list[str], int, int]:
    """The delta table: every spec row that differs, with each member's cell.

    The alignment is `compare.build`'s, driven through its `key_for` hook by the
    family's own printed-row key (see the module header). What this function adds
    is the family's one editorial rule — **a row that every member printed the
    same way is counted and not listed** — and the count it returns is what makes
    that rule checkable rather than a claim.
    """
    if len(members) < 2:
        return [], [], [], 0, 0

    def key_for(record: SpecRecord) -> tuple[str, str, str]:
        return _spec_key(record, section_key_of)

    parts = [
        ComparePart(part_number=m.part_number, records=tuple(m.specs)) for m in members
    ]
    comparison = build_spec_comparison(
        parts, term=_ALL_SPECS, kind=KIND_SPEC, key_for=key_for
    )
    rows = _ordered([row for row in comparison.rows if _row_differs(row)])
    identical = len(comparison.rows) - len(rows)
    notes = list(comparison.notes[1:])  # the compare-shaped headline is re-written
    notes.insert(
        0,
        (
            f"{len(comparison.rows)} spec rows align across "
            f"{', '.join(m.part_number for m in members)}: {identical} print the "
            f"same values in every member and are listed once here rather than "
            f"tabulated; {len(rows)} differ and are in the delta table below."
        ),
    )
    notes.extend(_unaddressable_notes(members))
    return rows, notes, list(comparison.unparsed), len(comparison.rows), identical


def _unaddressable_notes(members: Sequence[FamilyMember]) -> list[str]:
    """Name any member whose records predate ADR 0005 record ids, with the fix.

    A corpus published before every spec record carried an `id` has nothing a
    derived artifact can *cite*, so `compare.build` refuses every one of its rows
    — correctly, since an uncited value has no place here. That refusal is
    already in `unparsed`, one line per row, which on a real datasheet is six
    hundred lines saying the same thing. This is the sentence that makes it
    readable: the count, the member, and the rebuild that closes it.
    """
    notes = []
    for member in members:
        total = len(member.specs)
        if not total:
            continue
        unaddressable = sum(1 for entry in member.specs if not entry.record.id)
        if not unaddressable:
            continue
        notes.append(
            f"{member.part_number}: {unaddressable} of {total} spec records carry "
            f"no addressable record id (a corpus published before ADR 0005), so "
            f"they cannot be cited and take no part in the delta table — rebuild "
            f"it to include them: `dsa build <pdf> --part {member.part_number}`"
        )
    return notes


#: What the family's spec comparison is *about*, where `dsa compare` names a
#: query term. It is not a query: a family compares everything both members
#: publish, which is why nothing here is resolved through a lookup ladder.
_ALL_SPECS = "(every published spec row)"


def _spec_key(
    record: SpecRecord, section_key_of: Mapping[str, str]
) -> tuple[str, str, str]:
    """`(key, aligned_on, group)` for one spec row — the family's alignment.

    The **family section** scopes the key, so the same printed identity on two
    tables cannot collide and a member that renumbered the section still lines
    up (the section alignment already decided that, and this only reads its
    answer). Inside the section the identity is the row exactly as printed —
    symbol, name and conditions, each compared character for character after the
    shared `normalize`. Conditions are part of the identity rather than a cell to
    diff: a number measured at 25 °C and one measured at 85 °C are two
    parameters, and pairing them would produce a delta that means nothing.
    """
    number = record.section.strip()
    section = section_key_of.get(number, "") or number
    identity = "|".join(
        (normalize(record.symbol), normalize(record.name), normalize(record.conditions))
    )
    return identity or "(unnamed row)", f"{ALIGNED_ROW}:{section or '?'}", section


def _ordered(rows: list[ComparisonRow]) -> list[ComparisonRow]:
    """Rows most worth reading first, stably.

    Three tiers, and the order is a statement about what a series reader is
    asking: a parameter **every member printed and printed differently** is the
    answer to "what is different between these?"; a parameter only some members
    print is the next most useful (an absence is a finding); a key nobody could
    pair is last, because it is a fact about the extraction rather than about the
    devices. The rendering caps the table under a token budget, so this ordering
    decides what a bounded reader sees — which makes it part of the answer, not
    a presentation detail. Ties keep the derivation order, so the output stays
    byte-identical across rebuilds.
    """

    def tier(row: ComparisonRow) -> int:
        if FLAG_AMBIGUOUS in row.flags:
            return 2
        if FLAG_ONLY_IN in row.flags:
            return 1
        return 0

    return sorted(rows, key=tier)


def _row_differs(row: ComparisonRow) -> bool:
    """True when this aligned row is not the same in every member.

    Three ways a row differs, and all three belong in the delta table: a member
    that publishes no record under it (`only-in` — during series selection an
    absent parameter is the finding), a member that publishes several rows the
    tie-break refused (`ambiguous` — it said something, just not one thing), and
    a printed column whose verbatim string is not identical across the cells.
    Comparison is on the **printed string**, never on the parsed number: `1.35 A`
    and `1350 mA` are the same magnitude and are not the same printed answer, and
    the string is what this repo treats as authoritative.
    """
    if FLAG_ONLY_IN in row.flags or FLAG_AMBIGUOUS in row.flags:
        return True
    roles = {role for cell in row.cells for role in cell.values}
    for role in roles:
        printed = {
            cell.values[role].verbatim if role in cell.values else _NOT_PRINTED
            for cell in row.cells
        }
        if len(printed) > 1:
            return True
    return False


#: The sentinel for "this member printed nothing in this column". A distinct
#: object rather than `""`, because a member that printed an empty cell and one
#: that printed no cell at all are the same to a reader and must both differ from
#: a member that printed a value.
_NOT_PRINTED = "\x00not-printed"


# --- pins and registers ------------------------------------------------------


def _pin_deltas(members: Sequence[FamilyMember]) -> list[ComparisonRow]:
    """Pins that differ across the members, aligned by printed designator.

    The designator is the identity because it is what the package fixes — a pin
    whose *name* changed is the same physical ball, and reporting that as one pin
    missing and one appearing would tell a designer to redraw a footprint that
    did not move (`revdiff._pin_changes` decides the same thing for the same
    reason). Nothing here is scored: a pin name has no SI base.
    """
    return _record_deltas(
        members,
        records=lambda m: m.pins,
        key=lambda pin: normalize(pin.pin) or normalize(pin.name),
        label=lambda pin: pin.pin or pin.name,
        detail=lambda pin: pin.name,
        cells=PIN_FIELDS,
        cell=_pin_cell,
        artifact=PINS_ARTIFACT,
        aligned_on=ALIGNED_PIN,
    )


def _pin_cell(pin: PinRecord, what: str) -> str:
    if what == "type":
        return pin.type.value
    return str(getattr(pin, what, "")).strip()


def _register_deltas(members: Sequence[FamilyMember]) -> list[ComparisonRow]:
    """Registers that differ, plus the bit fields inside them that differ.

    A register aligns on its **parsed** address, so `0x1A04`, `0x1a04` and `6660`
    are one register (`dsa regs --addr` resolves the same way); one whose address
    the grammar never read keeps the string the document printed as its identity.
    A bit field aligns on its printed name inside its aligned register, and it is
    its own row rather than a cell of the register's, because "3 registers differ"
    must never silently mean "3 bit fields inside one register do".

    Neither carries a delta. A reset value is a bit pattern and a signed
    difference between two of them is a number that means nothing and looks like
    it means something; a bit range is the artifact a driver is written against
    and is quoted, never arithmetic.
    """
    rows = _record_deltas(
        members,
        records=lambda m: m.registers,
        key=_register_key,
        label=lambda reg: reg.address.verbatim or reg.name,
        detail=lambda reg: reg.name,
        cells=REGISTER_FIELDS,
        cell=_register_cell,
        artifact=REGISTERS_ARTIFACT,
        aligned_on=ALIGNED_REGISTER,
    )
    return rows + _field_deltas(members)


def _register_key(register: RegisterRecord) -> str:
    value = register.address.value
    if value is not None:
        return f"addr:{value}"
    return f"printed:{normalize(register.address.verbatim) or normalize(register.name)}"


def _register_cell(register: RegisterRecord, what: str) -> str:
    if what == "reset":
        return register.reset.verbatim.strip()
    return str(getattr(register, what, "")).strip()


def _field_deltas(members: Sequence[FamilyMember]) -> list[ComparisonRow]:
    """Bit fields that differ, aligned by printed name inside an aligned register."""
    parts = [m.part_number for m in members]
    buckets: dict[str, dict[str, tuple[str, RegisterRecord, object]]] = {}
    order: list[str] = []
    for member in members:
        for entry in member.registers:
            register = entry.record
            for bit_field in register.fields:
                key = f"{_register_key(register)}/{normalize(bit_field.name)}"
                if key not in buckets:
                    buckets[key] = {}
                    order.append(key)
                if member.part_number in buckets[key]:
                    # Two fields of one register printing one name: a duplicate
                    # this module refuses to choose between, exactly as an
                    # ambiguous spec key is refused. Dropping the second would
                    # publish the first as if it were the only one.
                    buckets[key][member.part_number] = _AMBIGUOUS
                    continue
                buckets[key][member.part_number] = (entry.doc, register, bit_field)
    rows: list[ComparisonRow] = []
    for key in order:
        found = buckets[key]
        present = [p for p in parts if p in found and found[p] is not _AMBIGUOUS]
        ambiguous = [p for p in parts if found.get(p) is _AMBIGUOUS]
        missing = [p for p in parts if p not in found]
        if not present:
            continue
        cells = []
        for part in present:
            doc, register, bit_field = found[part]
            cells.append(
                _cell(
                    part=part,
                    label=bit_field.name,
                    detail=f"{register.name} {register.address.verbatim}".strip(),
                    section=register.section,
                    page=bit_field.page,
                    values={
                        what: _value(
                            verbatim=_field_cell(bit_field, what),
                            ref=source_ref(
                                register.id,
                                artifact=REGISTERS_ARTIFACT,
                                doc=doc,
                                part=part,
                            ),
                            page=bit_field.page,
                            section=register.section,
                            confidence=register.fields_confidence,
                        )
                        for what in FIELD_FIELDS
                        if _field_cell(bit_field, what)
                    },
                )
            )
        row = _row(
            key=cells[0].label or key,
            aligned_on=ALIGNED_FIELD,
            group=cells[0].detail,
            cells=cells,
            missing_from=missing,
            ambiguous_in=ambiguous,
        )
        if _row_differs(row):
            rows.append(row)
    return rows


def _field_cell(bit_field, what: str) -> str:
    """One printed bit-field cell as the document printed it.

    `bits` is a `BitRange`, not a string, and its `verbatim` is the run the page
    actually carries (`2:0`) — the parsed `hi`/`lo` pair beside it is derived.
    Quoting the object's repr instead would put a Python data structure on a
    derived artifact and call it verbatim.
    """
    if what == "bits":
        return bit_field.bits.verbatim.strip()
    return str(getattr(bit_field, what, "")).strip()


#: The marker a duplicate key leaves in a member's slot, so the row can name that
#: member under `ambiguous_in` instead of publishing one of two answers.
_AMBIGUOUS = object()


def _record_deltas(
    members: Sequence[FamilyMember],
    *,
    records,
    key,
    label,
    detail,
    cells: Sequence[str],
    cell,
    artifact: str,
    aligned_on: str,
) -> list[ComparisonRow]:
    """One N-way alignment over a keyed artifact, keeping only what differs.

    Shared by pins and registers because they are the same shape — a printed key
    and a handful of printed cells — exactly as `structure/device_tables.py` reads
    them through one abstraction rather than one parser each.
    """
    parts = [m.part_number for m in members]
    if len(members) < 2:
        return []
    buckets: dict[str, dict[str, tuple[str, object]]] = {}
    order: list[str] = []
    for member in members:
        for entry in records(member):
            bucket_key = key(entry.record)
            if bucket_key not in buckets:
                buckets[bucket_key] = {}
                order.append(bucket_key)
            if member.part_number in buckets[bucket_key]:
                buckets[bucket_key][member.part_number] = _AMBIGUOUS
                continue
            buckets[bucket_key][member.part_number] = (entry.doc, entry.record)

    rows: list[ComparisonRow] = []
    for bucket_key in order:
        found = buckets[bucket_key]
        present = [p for p in parts if p in found and found[p] is not _AMBIGUOUS]
        ambiguous = [p for p in parts if found.get(p) is _AMBIGUOUS]
        missing = [p for p in parts if p not in found]
        if not present:
            continue
        built = []
        for part in present:
            doc, record = found[part]
            built.append(
                _cell(
                    part=part,
                    label=label(record),
                    detail=detail(record),
                    section=record.section,
                    page=record.page,
                    values={
                        what: _value(
                            verbatim=cell(record, what),
                            ref=source_ref(
                                record.id, artifact=artifact, doc=doc, part=part
                            ),
                            page=record.page,
                            section=record.section,
                            confidence=record.confidence,
                        )
                        for what in cells
                        if cell(record, what)
                    },
                )
            )
        row = _row(
            key=built[0].label or bucket_key,
            aligned_on=aligned_on,
            group="",
            cells=built,
            missing_from=missing,
            ambiguous_in=ambiguous,
        )
        if _row_differs(row):
            rows.append(row)
    return rows


def _value(
    *, verbatim: str, ref: str, page: int | None, section: str, confidence: Confidence
) -> DerivedValue:
    """One printed cell in its provenance envelope — copied, never rewritten."""
    return DerivedValue(
        verbatim=verbatim,
        source=ref,
        page=page,
        section=section,
        derivation=DERIVATION_CELL,
        confidence=confidence,
    )


def _cell(
    *,
    part: str,
    label: str,
    detail: str,
    section: str,
    page: int | None,
    values: Mapping[str, DerivedValue],
) -> ComparisonCell:
    return ComparisonCell(
        part_number=part,
        label=label,
        detail=detail,
        section=section,
        citation=Citation(section=section, page_start=page, page_end=page).label,
        values=dict(values),
    )


def _row(
    *,
    key: str,
    aligned_on: str,
    group: str,
    cells: Sequence[ComparisonCell],
    missing_from: Sequence[str],
    ambiguous_in: Sequence[str],
) -> ComparisonRow:
    row = ComparisonRow(
        key=key,
        aligned_on=aligned_on,
        group=group,
        role="",
        reference=cells[0].part_number if cells else "",
        cells=list(cells),
        missing_from=list(missing_from),
        ambiguous_in=list(ambiguous_in),
    )
    notes = []
    if row.missing_from:
        row.flags.append(FLAG_ONLY_IN)
        notes.append(
            f"only in {', '.join(c.part_number for c in row.cells)} — "
            f"{', '.join(row.missing_from)} publishes no such record"
        )
    if row.ambiguous_in:
        row.flags.append(FLAG_AMBIGUOUS)
        notes.append(
            f"{', '.join(row.ambiguous_in)} publishes several records under this "
            f"identity — choosing between them would be a guess, so this member "
            f"holds no column here"
        )
    notes.append("quoted verbatim on both sides; no delta is computed for this kind")
    row.note = "; ".join(notes)
    row.citation = "; ".join(
        dict.fromkeys(f"{c.part_number} {c.citation}" for c in row.cells if c.citation)
    )
    return row


# --- notes -------------------------------------------------------------------


def _artifact_notes(members: Sequence[FamilyMember]) -> list[str]:
    """What each member publishes of the artifacts a family can compare.

    A pin delta table with no rows means one of two very different things — the
    members print identical pinouts, or nobody published a pin table at all — and
    a reader must never have to guess which. So the counts are stated whether or
    not any row came out of them.
    """
    notes = []
    for what, get in (("pins", lambda m: m.pins), ("registers", lambda m: m.registers)):
        counts = ", ".join(f"{m.part_number} {len(get(m))}" for m in members)
        published = [m.part_number for m in members if get(m)]
        if not published:
            notes.append(
                f"no member publishes {what} ({counts}) — this family states "
                f"nothing about {what}, which is not the same as stating they agree"
            )
        elif len(published) < len(members):
            notes.append(
                f"{what} published by {', '.join(published)} only ({counts}) — a "
                f"member that publishes none contributes no column"
            )
        else:
            notes.append(f"{what} published by every member ({counts})")
    return notes


def _empty_reason(members: Sequence[FamilyMember]) -> str:
    built = [m.part_number for m in members if m.built]
    if len(built) < 2:
        return (
            f"no family index: {len(built)} of {len(members)} declared members "
            f"({', '.join(m.part_number for m in members)}) has a built corpus, and "
            f"a family of one has nothing to share and nothing to compare — build "
            f"the rest (`dsa build <pdf> --part <PART>`)"
        )
    return (
        f"no family index: {', '.join(built)} are built but publish no section and "
        f"no comparable record between them"
    )


def deltas_of(index: FamilyIndex, kind: str) -> Iterable[ComparisonRow]:
    """Every delta row of one artifact kind, in the order it was derived."""
    return {
        KIND_SPEC: index.deltas,
        KIND_PIN: index.pin_deltas,
        KIND_REGISTER: index.register_deltas,
    }.get(kind, [])
