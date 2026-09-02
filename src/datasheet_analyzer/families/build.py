"""Several members of one series -> one index: the "what is different?" question.

Phase 7, ticket 07. A family index is a **view**, in exactly the sense a design
card (`derive/cards.py`), a cross-part comparison (`derive/compare.py`) and a
revision diff (`revdiff/`) are: it owns no printed value, it quotes records its
member corpora already publish, and it says of every number where it came from.
ADR 0005 governs it whole —

- **(a)** every printed value is a cell copied verbatim into its envelope with
  its printed unit, from the member's own published record;
- **(b)** the only number it adds is the **delta**, the same documented pure
  function `dsa compare` uses (`si_delta`), computed only where the numeric
  layer read two members' values into the same SI base;
- **(c)** the structural label is the alignment key — the printed row inside the
  printed section for a spec, the printed designator for a pin, the parsed
  address for a register, the printed name for a bit field.

Five rules govern the module, and each one is a refusal.

**Membership is never inferred.** This module is handed its members; who they
are is `registry/families.yaml`'s answer and nobody else's
(`families/registry.py` carries that rule, and the suggester that may only
propose). A wrong grouping would put another part's numbers in front of a
designer with no visible seam.

**A section is shared only when it is identical everywhere.** Same printed title
in every member, and byte-identical body text in every member — the
`<!-- source: ... -->` provenance line excepted, because it names each member's
own revision and pages and so always differs. One value that moved makes the
section `divergent` and it is listed per member with its own page and file.
That is the honest form of the token win: a section listed once is one a reader
may genuinely read once.

**Specs align on the row as printed, inside the section as printed.** Not on the
alias-resolved symbol, which is right for two *unrelated* parts and wrong here:
a family's members are one vendor's one document template, so `IVDD1P8` and
`IVDD1P2` are two rows a reader must see apart, and an alias key would collapse
them and then refuse them both as ambiguous. The key is therefore
`(family section, printed symbol, printed name, printed conditions)`, every part
of it compared character for character after the shared `normalize`. Everything
downstream — the four join rungs, the identity tie-break, the refusal of an
ambiguous key, the delta, the unparsed population — is `derive/compare.py`'s,
reached through its `key_for` hook: one alignment engine, two artifacts.

**Only what differs is a row.** A parameter every member prints identically is
counted, not tabulated — that count *is* the family's claim, and re-printing
hundreds of agreeing rows would cost more than reading both members' indexes. A
row one member does not print is a row, because during a series-selection
decision an absent parameter is the finding.

**A pin name, a register reset and a bit range are never scored.** They are
quoted verbatim on both sides and given no delta, no sign and no direction —
`revdiff` refuses a reset for the same reason, and it is worth restating: a
signed difference between two bit patterns is a number that means nothing and
looks like it means something.

Nothing is dropped. Every alignment this module refused is listed with its
printed values, and the notes carry the population sentences invariant 8
requires of a consumer that compares.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from datasheet_analyzer.config import FAMILY_SCHEMA_VERSION, get_settings
from datasheet_analyzer.derive.compare import (
    FLAG_AMBIGUOUS,
    FLAG_ONLY_IN,
    STATUS_ALIGNED,
    STATUS_AMBIGUOUS,
    STATUS_ONLY_IN,
    STATUS_PARTIAL,
    compare_specs,
)
from datasheet_analyzer.derive.provenance import PINS_ARTIFACT, REGISTERS_ARTIFACT
from datasheet_analyzer.models import (
    CompareCell,
    CompareRow,
    Confidence,
    DerivedValue,
    FamilyIndex,
    FamilySection,
    PinRecord,
    RegisterRecord,
    SectionFile,
    SpecRecord,
    source_ref,
)
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

#: Separator inside a spec row's join key, between the family section and the
#: printed identity. A unit separator, because it is the one byte a printed
#: symbol, name or conditions string cannot contain — so `section_of` can read
#: the section back off a row without a second lookup, and no printed text can
#: forge one.
KEY_SEP = "\x1f"

#: The provenance line a section file opens with. Stripped before two members'
#: bodies are compared, because it names each member's own revision and pages
#: and would make every section divergent for a reason that is not about the
#: device.
_SOURCE_LINE = re.compile(r"^<!--\s*source:.*?-->\s*$", re.MULTILINE)


@dataclass(frozen=True)
class MemberRecord:
    """One published pin or register record on its way into a family row.

    `ref_base` is the document's corpus-relative (or `@library/…`) base, which
    is what a `source` reference is built from — carried rather than recomputed
    so a document published once into the shared store is cited where it
    actually lives.
    """

    ref_base: str
    record: object


@dataclass(frozen=True)
class FamilyMember:
    """One member corpus as the family index consumes it.

    Deliberately not a `CorpusIndex`: the corpus walk belongs to `retrieve/`,
    and taking the records keeps the section, pin and register halves of this
    module pure and testable from literals — the same split
    `revdiff.RevisionSide` already makes.

    The spec half is the exception, and for a stated reason: `compare_specs`
    owns the record selection, the citability rule and the parse population on
    this branch, and it reads a **part directory**. Re-implementing that here to
    keep a symmetry would be a second comparison implementation, which is the
    thing the `key_for` hook exists to avoid. So a member carries its directory
    and the spec deltas go through `dsa compare`'s own loader.

    `gap` is why this member contributed nothing, when it did: a declared member
    with no corpus on disk is **named**, never silently dropped, because a family
    index that quietly answered for two of three devices would be read as
    answering for all three.
    """

    part_number: str
    part_dir: Path | None = None
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


def section_of(row: CompareRow) -> str:
    """The family section a delta row belongs to, or `""`.

    Read back off the join key for a spec row (the key was built to carry it)
    and off the cell's `note` for a pin, register or bit-field row, which is
    where this module puts the printed section it quoted.
    """
    if KEY_SEP in row.key:
        return row.key.split(KEY_SEP, 1)[0]
    for cell in row.cells.values():
        if cell.note:
            return cell.note
    return ""


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
        card_version=get_settings().card_version,
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

    deltas, spec_notes, spec_unparsed, aligned, identical = _spec_deltas(built, section_key_of)
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
    group their identically-titled sections folded into.
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
        bodies = {part: _body_of(members, part, found[part].file) for part in present}
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
) -> tuple[list[CompareRow], list[str], list[str], int, int]:
    """The delta table: every spec row that differs, with each member's cell.

    The alignment is `derive/compare.py`'s, driven through its `key_for` hook by
    the family's own printed-row key (see the module header). What this function
    adds is the family's one editorial rule — **a row that every member printed
    the same way is counted and not listed** — and the count it returns is what
    makes that rule checkable rather than a claim.
    """
    usable = [m for m in members if m.part_dir is not None]
    if len(usable) < 2:
        return [], [], [], 0, 0

    def key_for(record: SpecRecord) -> tuple[str, str]:
        return _spec_key(record, section_key_of)

    comparison = compare_specs([(m.part_number, Path(m.part_dir)) for m in usable], key_for=key_for)
    rows = _ordered([row for row in comparison.rows if _row_differs(row)])
    identical = len(comparison.rows) - len(rows)
    # The alignment headline is *not* a note: `n_specs_aligned` /
    # `n_specs_identical` are fields, and the renderer states them once from
    # those. A note repeating them would print the same sentence twice on the
    # page and read as two independent findings.
    notes = [f"spec value pairs: {_headline(comparison.coverage.describe())}"]
    notes.extend(_headline(cov.describe()) for cov in comparison.parse_coverage)
    notes.extend(comparison.warnings)
    notes.extend(comparison.unresolved)

    unparsed: list[str] = []
    for row in comparison.rows:
        if row.status in (STATUS_AMBIGUOUS, STATUS_ONLY_IN, STATUS_PARTIAL):
            unparsed.extend(row.not_comparable)
    unparsed.extend(comparison.coverage.reasons)
    for cov in comparison.parse_coverage:
        unparsed.extend(f"{cov.part_number}: {line}" for line in cov.unparsed)
    return rows, notes, unparsed, len(comparison.rows), identical


def _headline(described: str) -> str:
    """The counting sentence of a coverage description, without its listing.

    The listing itself goes to `unparsed`, once, where the family index prints
    it under *Not comparable*. Carrying it here as well would put the same two
    hundred lines on the page twice and call the second copy a note.
    """
    return described.split("\n")[0].rstrip(":")


def _spec_key(record: SpecRecord, section_key_of: Mapping[str, str]) -> tuple[str, str]:
    """`(key, aligned_on)` for one spec row — the family's alignment.

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
    key = f"{section}{KEY_SEP}{identity or '(unnamed row)'}"
    return key, f"{ALIGNED_ROW}:{section or '?'}"


def _ordered(rows: list[CompareRow]) -> list[CompareRow]:
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

    def tier(row: CompareRow) -> int:
        if FLAG_AMBIGUOUS in row.flags or row.status == STATUS_AMBIGUOUS:
            return 2
        if FLAG_ONLY_IN in row.flags or row.missing_from:
            return 1
        return 0

    return sorted(rows, key=tier)


#: The sentinel for "this member printed nothing in this column". A distinct
#: string rather than `""`, because a member that printed an empty cell and one
#: that printed no cell at all are the same to a reader and must both differ from
#: a member that printed a value.
_NOT_PRINTED = "\x00not-printed"


def _row_differs(row: CompareRow) -> bool:
    """True when this aligned row is not the same in every member.

    Three ways a row differs, and all three belong in the delta table: a member
    that publishes no record under it (an absent parameter *is* the finding
    during series selection), a member that publishes several rows the tie-break
    refused (it said something, just not one thing), and a printed column whose
    verbatim string is not identical across the cells. Comparison is on the
    **printed string**, never on the parsed number: `1.35 A` and `1350 mA` are
    the same magnitude and are not the same printed answer, and the string is
    what this repo treats as authoritative.
    """
    if row.status != STATUS_ALIGNED or row.missing_from:
        return True
    roles = {role for cell in row.cells.values() for role in cell.values}
    for role in roles:
        printed = {
            cell.values[role].verbatim if role in cell.values else _NOT_PRINTED
            for cell in row.cells.values()
        }
        if len(printed) > 1:
            return True
    return False


# --- pins and registers ------------------------------------------------------


def _pin_deltas(members: Sequence[FamilyMember]) -> list[CompareRow]:
    """Pins that differ across the members, aligned by printed designator.

    The designator is the identity because it is what the package fixes: a pin
    whose *name* changed is the same physical ball, and reporting that as one pin
    missing and one appearing would tell a designer to redraw a footprint that
    did not move (`revdiff` decides the same thing for the same reason). Nothing
    here is scored, because a pin name has no SI base.
    """
    return _record_deltas(
        members,
        records=lambda m: m.pins,
        key=lambda pin: normalize(pin.pin) or normalize(pin.name),
        label=lambda pin: pin.pin or pin.name,
        cells=PIN_FIELDS,
        cell=_pin_cell,
        artifact=PINS_ARTIFACT,
        aligned_on=ALIGNED_PIN,
    )


def _pin_cell(pin: PinRecord, what: str) -> str:
    """One printed pin cell as a string.

    `type` is the one field that is not already text: it may arrive as a
    `PinType` or, from a corpus read back with `use_enum_values`, as the bare
    string it serializes to. Both are the same printed word, and a family row
    must not depend on which of the two a caller happened to hand it.
    """
    if what == "type":
        return str(getattr(pin.type, "value", pin.type)).strip()
    return str(getattr(pin, what, "")).strip()


def _register_deltas(members: Sequence[FamilyMember]) -> list[CompareRow]:
    """Registers that differ, plus the bit fields inside them that differ.

    A register aligns on its **parsed** address, so 0x1A04, 0x1a04 and 6660 are
    one register (`dsa regs --addr` resolves the same way); one whose address the
    grammar never read keeps the string the document printed as its identity.
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


def _field_cell(bit_field, what: str) -> str:
    """One printed bit-field cell as the document printed it.

    `bits` is a `BitRange`, not a string, and its `verbatim` is the run the page
    actually carries (2:0); the parsed hi/lo pair beside it is derived. Quoting
    the object's repr instead would put a Python data structure on a derived
    artifact and call it verbatim.
    """
    if what == "bits":
        return bit_field.bits.verbatim.strip()
    return str(getattr(bit_field, what, "")).strip()


#: The marker a duplicate key leaves in a member slot, so the row can name that
#: member as ambiguous instead of publishing one of two answers.
_AMBIGUOUS = object()


def _field_deltas(members: Sequence[FamilyMember]) -> list[CompareRow]:
    """Bit fields that differ, aligned by printed name inside an aligned register."""
    parts = [m.part_number for m in members]
    if len(members) < 2:
        return []
    buckets: dict[str, dict[str, object]] = {}
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
                buckets[key][member.part_number] = (entry.ref_base, register, bit_field)
    rows: list[CompareRow] = []
    for key in order:
        found = buckets[key]
        present = [p for p in parts if p in found and found[p] is not _AMBIGUOUS]
        ambiguous = [p for p in parts if found.get(p) is _AMBIGUOUS]
        missing = [p for p in parts if p not in found]
        if not present:
            continue
        cells: dict[str, CompareCell] = {}
        label = ""
        for part in present:
            ref_base, register, bit_field = found[part]
            label = label or bit_field.name
            cells[part] = _cell(
                part=part,
                label=bit_field.name,
                note=register.section,
                conditions=f"{register.name} {register.address.verbatim}".strip(),
                page=bit_field.page,
                values={
                    what: _value(
                        verbatim=_field_cell(bit_field, what),
                        ref=source_ref(f"{ref_base}/{REGISTERS_ARTIFACT}", register.id),
                        page=bit_field.page,
                        section=register.section,
                        confidence=register.fields_confidence,
                    )
                    for what in FIELD_FIELDS
                    if _field_cell(bit_field, what)
                },
            )
        row = _row(
            key=label or key,
            aligned_on=ALIGNED_FIELD,
            parts=parts,
            cells=cells,
            present=present,
            missing_from=missing,
            ambiguous_in=ambiguous,
        )
        if _row_differs(row):
            rows.append(row)
    return rows


def _record_deltas(
    members: Sequence[FamilyMember],
    *,
    records,
    key,
    label,
    cells: Sequence[str],
    cell,
    artifact: str,
    aligned_on: str,
) -> list[CompareRow]:
    """One N-way alignment over a keyed artifact, keeping only what differs.

    Shared by pins and registers because they are the same shape (a printed key
    and a handful of printed cells), exactly as `structure/device_tables.py`
    reads them through one abstraction rather than one parser each.
    """
    parts = [m.part_number for m in members]
    if len(members) < 2:
        return []
    buckets: dict[str, dict[str, object]] = {}
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
            buckets[bucket_key][member.part_number] = (entry.ref_base, entry.record)

    rows: list[CompareRow] = []
    for bucket_key in order:
        found = buckets[bucket_key]
        present = [p for p in parts if p in found and found[p] is not _AMBIGUOUS]
        ambiguous = [p for p in parts if found.get(p) is _AMBIGUOUS]
        missing = [p for p in parts if p not in found]
        if not present:
            continue
        built: dict[str, CompareCell] = {}
        printed = ""
        for part in present:
            ref_base, record = found[part]
            printed = printed or label(record)
            built[part] = _cell(
                part=part,
                label=label(record),
                note=record.section,
                conditions="",
                page=record.page,
                values={
                    what: _value(
                        verbatim=cell(record, what),
                        ref=source_ref(f"{ref_base}/{artifact}", record.id),
                        page=record.page,
                        section=record.section,
                        confidence=record.confidence,
                    )
                    for what in cells
                    if cell(record, what)
                },
            )
        row = _row(
            key=printed or bucket_key,
            aligned_on=aligned_on,
            parts=parts,
            cells=built,
            present=present,
            missing_from=missing,
            ambiguous_in=ambiguous,
        )
        if _row_differs(row):
            rows.append(row)
    return rows


def _value(
    *, verbatim: str, ref: str, page: int | None, section: str, confidence: Confidence
) -> DerivedValue:
    """One printed cell in its provenance envelope: copied, never rewritten."""
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
    note: str,
    conditions: str,
    page: int | None,
    values: Mapping[str, DerivedValue],
) -> CompareCell:
    return CompareCell(
        part_number=part,
        label=label,
        symbol=label,
        note=note,
        conditions=conditions,
        page=page,
        values=dict(values),
    )


def _row(
    *,
    key: str,
    aligned_on: str,
    parts: Sequence[str],
    cells: Mapping[str, CompareCell],
    present: Sequence[str],
    missing_from: Sequence[str],
    ambiguous_in: Sequence[str],
) -> CompareRow:
    """One family delta row, in the row shape `dsa compare` publishes.

    `not_comparable` is where the two refusals a family can make are written
    down (a member that publishes nothing under this key, and a member that
    publishes several things), plus the standing statement that this kind of row
    is never scored. It is the same field `dsa compare` puts its own refusals in,
    which is why a reader of either artifact reads one convention.
    """
    reasons: list[str] = []
    flags: list[str] = []
    if missing_from:
        flags.append(FLAG_ONLY_IN)
        reasons.append(
            f"only in {', '.join(present)}: {', '.join(missing_from)} publishes no such record"
        )
    if ambiguous_in:
        flags.append(FLAG_AMBIGUOUS)
        reasons.append(
            f"{', '.join(ambiguous_in)} publishes several records under this identity, "
            f"and choosing between them would be a guess, so that member holds no "
            f"column here"
        )
    reasons.append("quoted verbatim on both sides; no delta is computed for this kind")
    status = STATUS_ALIGNED
    if ambiguous_in:
        status = STATUS_AMBIGUOUS
    elif len(present) == 1 and len(parts) > 1:
        status = STATUS_ONLY_IN
    elif missing_from:
        status = STATUS_PARTIAL
    return CompareRow(
        key=key,
        label=key,
        symbol=key,
        matched_on=aligned_on,
        status=status,
        cells=dict(cells),
        deltas=[],
        present_in=list(present),
        missing_from=list(missing_from),
        not_comparable=reasons,
        flags=flags,
    )


# --- notes -------------------------------------------------------------------


def _artifact_notes(members: Sequence[FamilyMember]) -> list[str]:
    """What each member publishes of the artifacts a family can compare.

    A pin delta table with no rows means one of two very different things (the
    members print identical pinouts, or nobody published a pin table at all) and
    a reader must never have to guess which. So the counts are stated whether or
    not any row came out of them.
    """
    notes = []
    for what, get in (("pins", lambda m: m.pins), ("registers", lambda m: m.registers)):
        counts = ", ".join(f"{m.part_number} {len(get(m))}" for m in members)
        published = [m.part_number for m in members if get(m)]
        if not published:
            notes.append(
                f"no member publishes {what} ({counts}) - this family states "
                f"nothing about {what}, which is not the same as stating they agree"
            )
        elif len(published) < len(members):
            notes.append(
                f"{what} published by {', '.join(published)} only ({counts}) - a "
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
            f"a family of one has nothing to share and nothing to compare - build "
            f"the rest (`dsa build <pdf> --part <PART>`)"
        )
    return (
        f"no family index: {', '.join(built)} are built but publish no section and "
        f"no comparable record between them"
    )


def deltas_of(index: FamilyIndex, kind: str) -> Iterable[CompareRow]:
    """Every delta row of one artifact kind, in the order it was derived."""
    return {
        KIND_SPEC: index.deltas,
        KIND_PIN: index.pin_deltas,
        KIND_REGISTER: index.register_deltas,
    }.get(kind, [])
