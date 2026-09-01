"""Two revisions of one part -> what changed: the datasheet-update question.

Phase 7, ticket 03. A revision diff is a **view**, in exactly the sense a design
card (`cards/build.py`) and a cross-part comparison (`compare/build.py`) are: it
owns no printed value, it quotes records the two revisions already publish, and
it says of every number where it came from. ADR 0005 governs it whole —

- **(a)** every printed value is a cell copied verbatim into its envelope with
  its printed unit (`copy_cell`), from the revision's own published record;
- **(b)** the one number it adds is the **delta**, a documented pure function of
  two quoted cells (`si_delta:<role>`), computed only where the numeric layer
  read both sides into the same SI base;
- **(c)** the structural label is the alignment key — the alias-resolved symbol
  from `registry/aliases.yaml` for a spec, the printed section number, the
  printed pin designator, the parsed register address.

Five rules govern the module, and every one of them is a refusal.

**Specs align by alias-resolved symbol.** A parameter one revision prints as
`TJ` and the next prints as `Junction temperature` is one parameter that
*changed*, not one removed and one added — reporting it as the latter is how a
review misses the change that matters. Every change records what aligned it
(`alias:TJ`, `printed-symbol`), so a mis-alignment is readable rather than
invisible.

**A change either carries a delta or is listed for review by hand.** The delta
exists only where both sides parsed the same printed column into the same SI
base. Everything else — a value that reads `See Figure 7`, a retitled section, a
renamed pin, a register whose reset moved from `0x0223` to `0x0233` — is quoted
verbatim under `review_by_hand` and **never scored**. A register reset is
excluded on purpose even though it would parse as an integer: it is a bit
pattern, and a signed difference between two bit patterns is a number that means
nothing and reads like it means something.

**An ambiguous alignment is refused, not resolved.** Where a key arrives with
several rows on a side, the only pairing made is between rows that share a
printed identity cell character for character (the widening `compare.build`
allows, for the same reason). Everything left over is listed with its printed
values under `unparsed`, because "removed" is a claim about the device and a
wrong one is worse than no claim.

**A section retitle, a page shift and an addition are three different facts.**
They are three `change` values, never folded together: a reader scanning for
what moved must not have to diff two titles to find out whether the section is
new.

**Nothing is dropped.** Every change this tool refused to score is listed, and
the notes carry the population sentences invariant 8 requires of a consumer that
compares — how many of the changed values could not be compared numerically, and
what fraction of each revision's records state a readable quantity at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from datasheet_analyzer.config import REVDIFF_SCHEMA_VERSION, get_settings
from datasheet_analyzer.derive.cards import cell_value
from datasheet_analyzer.derive.compare import si_delta
from datasheet_analyzer.derive.provenance import (
    PINS_ARTIFACT,
    REGISTERS_ARTIFACT,
    SPECS_ARTIFACT,
)
from datasheet_analyzer.models import (
    Confidence,
    DerivedValue,
    PinRecord,
    RegisterRecord,
    RevisionChange,
    RevisionDiff,
    SectionFile,
    SpecRecord,
    source_ref,
)
from datasheet_analyzer.structure.aliases import AliasLexicon, load_lexicon, normalize
from datasheet_analyzer.structure.quantities import ParseCoverage, coverage

#: Confidence, weakest first — the order a joined value inherits. Duplicated
#: from `derive/compare.py` and `derive/cards.py` rather than shared, because
#: all three are two lines and a shared helper would put a lookup between a
#: reader and a rule they need to see whole.
_CONFIDENCE_ORDER = (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW, Confidence.UNKNOWN)


def _weaker(*grades: Confidence) -> Confidence:
    """The weakest grade among `grades`; `UNKNOWN` when none is known."""
    known = [g for g in grades if g in _CONFIDENCE_ORDER]
    if not known:
        return Confidence.UNKNOWN
    return max(known, key=_CONFIDENCE_ORDER.index)


#: What moved. `field` is a bit field of a register and is its own kind rather
#: than a register change, so "3 registers changed" never silently means "3 bit
#: fields inside one register did".
KIND_SPEC = "spec"
KIND_SECTION = "section"
KIND_PIN = "pin"
KIND_REGISTER = "register"
KIND_FIELD = "field"

#: How it moved. `retitled` and `page-shifted` are deliberately distinct from
#: `changed`: a section's identity is its number, and a reader scanning a diff
#: for structural moves is asking a different question from one scanning for
#: value moves.
CHANGE_ADDED = "added"
CHANGE_REMOVED = "removed"
CHANGE_CHANGED = "changed"
CHANGE_RETITLED = "retitled"
CHANGE_PAGE_SHIFTED = "page-shifted"
CHANGE_RENAMED = "renamed"
CHANGE_RESET = "reset-changed"

#: The flag on every change this module refuses to score, and the heading its
#: rendering puts them under. A reader must be able to find, in one place,
#: everything the tool did **not** measure.
FLAG_REVIEW = "review-by-hand"

#: The rules, as `DerivedValue.derivation` records them. `copy_cell` is the same
#: rule `cards.build` and `compare.build` name for the same act — one rule, three
#: artifacts — and the delta names the printed column it was computed on, because
#: "the maximums moved by 20 °C" and "the typicals did" are different claims.
DERIVATION_CELL = "copy_cell"
DERIVATION_CELL_SI = "copy_cell+parse_quantity+si_normalize"
DERIVATION_DELTA = "si_delta"
#: A pin's `type` is a lexicon classification, not a printed cell, so it is
#: enveloped under the rule that produced it. Naming it `copy_cell` would claim
#: a page printed the word `power`.
DERIVATION_PIN_TYPE = "pin_type_lexicon"

#: How a spec change aligned; mirrors `compare.build`, because a reader who has
#: learned one of these artifacts must not have to learn the other.
ALIGNED_ALIAS = "alias"
ALIGNED_PRINTED = "printed-symbol"
ALIGNED_SECTION = "section-number"
ALIGNED_SECTION_TITLE = "section-title"
ALIGNED_PIN = "pin-designator"
ALIGNED_REGISTER = "register-address"
ALIGNED_FIELD = "field-name"

#: The printed columns a spec change may be computed on, in the order a delta
#: prefers them. Every one is compared — a revision that moved `min` and left
#: `max` alone has changed, and only reporting the preferred column would hide
#: it — the order decides nothing but which column a summary line leads with.
ROLE_ORDER: tuple[str, ...] = ("max", "typ", "min", "value")

#: Printed cells of a spec row that are not values but do change its meaning. A
#: condition that moved from `TA = 25°C` to `TA = 85°C` re-bases every number in
#: the row, so it is a change; it is never scored, because it is prose.
CONTEXT_FIELDS: tuple[str, ...] = ("conditions", "unit")


@dataclass(frozen=True)
class RevisionSide:
    """One revision of one part, as the diff consumes it.

    Deliberately not a `CorpusIndex`: the corpus walk belongs to `retrieve/`, and
    taking the *records* keeps this module pure and testable from literals.

    `doc` is the document directory those records live in; `label` is what the
    caller selected the side by and `revision` what the document itself printed
    — the two are kept apart because a human's filing label is not a reading of
    the page.

    `ref_base` is the prefix a `source` reference hangs off — `docs/<doc>` for a
    document published under the part, `@library/docs/<doc>` for one published
    once into the shared store (ADR 0008). It is carried rather than composed
    from `doc` because on this branch a document's records may live outside the
    part directory, and a reference that named the wrong root would resolve to
    nothing while looking exactly like one that resolves.

    `revision_note` is what the last revision check found about this side's
    document, quoted onto the diff's notes: a diff of two documents on disk says
    nothing about what upstream now serves, and a corpus that has drifted or gone
    stale must say so in the report a designer reads.
    """

    part_number: str = ""
    label: str = ""
    doc: str = ""
    ref_base: str = ""
    revision: str = ""
    revision_note: str = ""
    specs: tuple[SpecRecord, ...] = ()
    sections: tuple[SectionFile, ...] = ()
    pins: tuple[PinRecord, ...] = ()
    registers: tuple[RegisterRecord, ...] = ()

    @property
    def reference_base(self) -> str:
        """Where this side's record references hang off; `docs/<doc>` by default."""
        return self.ref_base or (f"docs/{self.doc}" if self.doc else "")


def build_revision_diff(
    before: RevisionSide,
    after: RevisionSide,
    *,
    lexicon: AliasLexicon | None = None,
) -> RevisionDiff:
    """Everything that moved between two revisions of one part.

    Order is fully determined by the two record sets — the `after` side's own
    publication order, then whatever only `before` printed — so a rebuild of
    identical input reproduces the same diff byte for byte, and diffing a
    revision against itself produces no changes at all rather than noise.
    """
    lexicon = load_lexicon() if lexicon is None else lexicon
    diff = RevisionDiff(
        schema_version=REVDIFF_SCHEMA_VERSION,
        card_version=get_settings().card_version,
        part_number=after.part_number or before.part_number,
        before_label=before.label,
        before_doc=before.doc,
        before_revision=before.revision,
        after_label=after.label,
        after_doc=after.doc,
        after_revision=after.revision,
    )

    diff.changes.extend(_section_changes(before, after))
    spec_changes, refused = _spec_changes(before, after, lexicon=lexicon)
    diff.changes.extend(spec_changes)
    diff.unparsed.extend(refused)
    diff.changes.extend(_pin_changes(before, after))
    register_changes, register_refused = _register_changes(before, after)
    diff.changes.extend(register_changes)
    diff.unparsed.extend(register_refused)

    diff.review_by_hand.extend(
        _review_line(change) for change in diff.changes if FLAG_REVIEW in change.flags
    )
    diff.identical = not diff.changes
    diff.notes.extend(_notes(diff, before, after))
    if not diff.changes:
        diff.empty_reason = _empty_reason(before, after)
    return diff


# --- sections ----------------------------------------------------------------


def _section_changes(before: RevisionSide, after: RevisionSide) -> list[RevisionChange]:
    """Sections added, removed, retitled and page-shifted — four facts, kept apart.

    A section's identity is the number the document printed (`4.1`), because that
    is what survives a rewording of its title; a section the document numbers not
    at all is identified by its normalized title, which is the only handle it
    has. So a retitle is a *paired* section whose title moved, and it is reported
    as such rather than as one section vanishing and another appearing.
    """
    old = _by_key(before.sections, _section_key)
    new = _by_key(after.sections, _section_key)
    changes: list[RevisionChange] = []
    for key, section in new.items():
        previous = old.get(key)
        if previous is None:
            changes.append(
                _change(
                    KIND_SECTION,
                    CHANGE_ADDED,
                    key,
                    label=_section_label(section),
                    aligned_on=_section_aligned(section),
                    after=_section_value(after, section, "title"),
                    summary=f"§{key} {section.title} — added",
                )
            )
            continue
        if previous.title.strip() != section.title.strip():
            changes.append(
                _change(
                    KIND_SECTION,
                    CHANGE_RETITLED,
                    key,
                    label=_section_label(section),
                    aligned_on=_section_aligned(section),
                    field="title",
                    before=_section_value(before, previous, "title"),
                    after=_section_value(after, section, "title"),
                    summary=(f"§{key} retitled: {previous.title!r} -> {section.title!r}"),
                )
            )
        if (previous.page_start, previous.page_end) != (section.page_start, section.page_end):
            changes.append(
                _change(
                    KIND_SECTION,
                    CHANGE_PAGE_SHIFTED,
                    key,
                    label=_section_label(section),
                    aligned_on=_section_aligned(section),
                    field="page",
                    before=_section_value(before, previous, "page"),
                    after=_section_value(after, section, "page"),
                    summary=(
                        f"§{key} {section.title} moved: {_pages(previous)} -> {_pages(section)}"
                    ),
                )
            )
    for key, section in old.items():
        if key in new:
            continue
        changes.append(
            _change(
                KIND_SECTION,
                CHANGE_REMOVED,
                key,
                label=_section_label(section),
                aligned_on=_section_aligned(section),
                before=_section_value(before, section, "title"),
                summary=f"§{key} {section.title} — removed",
            )
        )
    return changes


def _section_key(section: SectionFile) -> str:
    """A section's identity: its printed number, else its normalized title."""
    number = section.number.strip()
    return number or f"title:{normalize(section.title)}"


def _section_aligned(section: SectionFile) -> str:
    return ALIGNED_SECTION if section.number.strip() else ALIGNED_SECTION_TITLE


def _section_label(section: SectionFile) -> str:
    return section.title.strip() or section.number.strip()


def _pages(section: SectionFile) -> str:
    """`p.4-7` / `p.4` / `p.?` — a section's page range as a citation prints it."""
    start, end = section.page_start, section.page_end
    if start is None:
        return "p.?"
    if end is None or end == start:
        return f"p.{start}"
    return f"p.{start}-{end}"


def _section_value(side: RevisionSide, section: SectionFile, what: str) -> DerivedValue:
    """One section's title or page range, quoted with the file it is written in.

    A section is a **file**, not a record, so its reference is the corpus-relative
    path of that file rather than an `artifact#rec_n` id: there is no record to
    resolve, and inventing an id shape for one would be a reference that looks
    resolvable and is not.
    """
    return DerivedValue(
        verbatim=section.title.strip() if what == "title" else _pages(section),
        source=section.file,
        page=section.page_start,
        section=section.number,
        derivation=DERIVATION_CELL,
        confidence=Confidence.UNKNOWN,
    )


# --- specs -------------------------------------------------------------------


def _spec_changes(
    before: RevisionSide, after: RevisionSide, *, lexicon: AliasLexicon
) -> tuple[list[RevisionChange], list[str]]:
    """Spec records added, removed and changed, aligned by alias-resolved symbol.

    The alignment is the whole point of the ticket's second criterion: a
    parameter the vendor renamed between revisions is *one* parameter, and the
    lexicon is what says so. What the lexicon does not claim still aligns on a
    printed symbol the two revisions share, and the change says which happened.
    """
    # A record that printed no value in any column has nothing to compare and no
    # name a reader could act on — the layout floor emits one for every row of a
    # neighbouring pin table. They are not dropped: they are counted, per side, in
    # the population sentence `_notes` writes. What they must not do is enter the
    # alignment, where a dozen of them collapse onto one `(unnamed row)` key and
    # bury the parameters that did move under a wall of refusals.
    old = _bucket(
        [r for r in before.specs if _has_printed_value(r)],
        lambda r: _spec_key(r, lexicon=lexicon),
    )
    new = _bucket(
        [r for r in after.specs if _has_printed_value(r)],
        lambda r: _spec_key(r, lexicon=lexicon),
    )
    changes: list[RevisionChange] = []
    refused: list[str] = []

    for key in list(new) + [k for k in old if k not in new]:
        olds, news = old.get(key, []), new.get(key, [])
        pairs, only_old, only_new, ambiguous = _pair(olds, news, _spec_identity)
        if ambiguous:
            refused.extend(_ambiguous_specs(key, before, after, ambiguous))
        for previous, record in pairs:
            changes.extend(
                _spec_pair_changes(key, before, after, previous, record, lexicon=lexicon)
            )
        for record in only_new:
            changes.append(
                _change(
                    KIND_SPEC,
                    CHANGE_ADDED,
                    _spec_display(key, record, _spec_aligned(record, lexicon=lexicon)),
                    label=_spec_label(record),
                    aligned_on=_spec_aligned(record, lexicon=lexicon),
                    after=_spec_value(after, record, _lead_role(record)),
                    summary=f"{_spec_label(record)} — added: {_spec_printed(record)}",
                )
            )
        for record in only_old:
            changes.append(
                _change(
                    KIND_SPEC,
                    CHANGE_REMOVED,
                    _spec_display(key, record, _spec_aligned(record, lexicon=lexicon)),
                    label=_spec_label(record),
                    aligned_on=_spec_aligned(record, lexicon=lexicon),
                    before=_spec_value(before, record, _lead_role(record)),
                    summary=f"{_spec_label(record)} — removed: {_spec_printed(record)}",
                )
            )
    return changes, refused


def _spec_pair_changes(
    key: str,
    before: RevisionSide,
    after: RevisionSide,
    previous: SpecRecord,
    record: SpecRecord,
    *,
    lexicon: AliasLexicon,
) -> list[RevisionChange]:
    """Every printed cell of one aligned parameter that moved, one change each.

    Per column, never per row: "TJ changed" is not actionable, and a row whose
    `min` moved while its `max` held still has to say so, or the reader has to
    open both datasheets to find out which number they are being warned about.
    """
    changes: list[RevisionChange] = []
    aligned = _spec_aligned(record, lexicon=lexicon)
    display = _spec_display(key, record, aligned)
    for role in ROLE_ORDER:
        old_cell = getattr(previous, role, "").strip()
        new_cell = getattr(record, role, "").strip()
        if old_cell == new_cell:
            continue
        old_value = _spec_value(before, previous, role) if old_cell else None
        new_value = _spec_value(after, record, role) if new_cell else None
        delta, reason = _delta(role, old_value, new_value)
        changes.append(
            _change(
                KIND_SPEC,
                CHANGE_CHANGED,
                display,
                label=_spec_label(record),
                aligned_on=aligned,
                field=role,
                before=old_value,
                after=new_value,
                delta=delta,
                note=reason,
                summary=_value_summary(
                    f"{_spec_label(record)} {role}", old_value, new_value, delta
                ),
            )
        )
    for what in CONTEXT_FIELDS:
        old_cell = _context_cell(previous, what)
        new_cell = _context_cell(record, what)
        if old_cell == new_cell:
            continue
        changes.append(
            _change(
                KIND_SPEC,
                CHANGE_CHANGED,
                display,
                label=_spec_label(record),
                aligned_on=aligned,
                field=what,
                before=_spec_context_value(before, previous, what),
                after=_spec_context_value(after, record, what),
                note=(
                    f"the printed {what} moved — every number in this row is "
                    f"stated under it, so the row is re-based rather than merely "
                    f"re-worded"
                ),
                summary=(
                    f"{_spec_label(record)} {what}: {old_cell or '(none)'} -> "
                    f"{new_cell or '(none)'}"
                ),
            )
        )
    return changes


def _context_cell(record: SpecRecord, what: str) -> str:
    if what == "unit":
        return (record.unit.verbatim or record.unit.canonical).strip()
    return getattr(record, what, "").strip()


def _spec_key(record: SpecRecord, *, lexicon: AliasLexicon) -> str:
    entry = lexicon.entry_for(record.symbol, record.name)
    if entry is not None:
        return entry.symbol
    printed = normalize(record.symbol) or normalize(record.name)
    return printed or "(unnamed row)"


def _spec_aligned(record: SpecRecord, *, lexicon: AliasLexicon) -> str:
    entry = lexicon.entry_for(record.symbol, record.name)
    return f"{ALIGNED_ALIAS}:{entry.symbol}" if entry is not None else ALIGNED_PRINTED


def _spec_label(record: SpecRecord) -> str:
    return record.symbol.strip() or record.name.strip() or "(unnamed row)"


def _spec_display(key: str, record: SpecRecord, aligned_on: str) -> str:
    """The key a reader sees: the canonical symbol, else the printed label.

    A normalized printed string is a lowercased echo of the row's own name and
    reads like a typo in a report; the lexicon's symbol is a word a designer
    already knows. (`compare.build._display_key` decides the same thing, from
    the same fact — whether the lexicon claimed the row.)
    """
    return key if aligned_on.startswith(ALIGNED_ALIAS) else _spec_label(record)


def _spec_identity(record: SpecRecord) -> frozenset[str]:
    """The printed cells that name a spec row, normalized for pairing.

    Symbol, name and conditions as separate cells, never joined: one revision's
    *name* cell can be the next one's *symbol* cell, and the conditions are what
    tell two rows of one parameter apart (`industrial` against `commercial`).
    """
    return frozenset(
        text
        for text in (
            normalize(record.symbol),
            normalize(record.name),
            normalize(record.conditions),
        )
        if text
    )


def _has_printed_value(record: SpecRecord) -> bool:
    """Whether a spec record printed anything in any value column."""
    return any(getattr(record, role, "").strip() for role in ROLE_ORDER)


def _lead_role(record: SpecRecord) -> str:
    """The printed column an added/removed row is quoted by; `""` when it has none."""
    for role in ROLE_ORDER:
        if getattr(record, role, "").strip():
            return role
    return ""


def _spec_printed(record: SpecRecord) -> str:
    """What one row printed, quoted — never summarized away."""
    unit = (record.unit.verbatim or record.unit.canonical).strip()
    printed = [
        f"{role} {getattr(record, role).strip()} {unit}".strip()
        for role in ROLE_ORDER
        if getattr(record, role, "").strip()
    ]
    return "; ".join(printed) if printed else "no printed value"


def _spec_value(side: RevisionSide, record: SpecRecord, role: str) -> DerivedValue | None:
    """One printed cell in its provenance envelope, or `None` when it is empty.

    `verbatim` carries the row's printed unit (`"150 °C"`), the same rule
    `cards.build._cell` and `compare.build._cell` follow: a value quoted without
    its unit is the one way this artifact could mislead the person reading it to
    decide whether a design still holds.
    """
    if not role:
        return None
    cell = (getattr(record, role, "") or "").strip()
    if not cell:
        return None
    value = cell_value(record, role, source=_ref(side, record.id, SPECS_ARTIFACT))
    if value is None:  # pragma: no cover - `cell` is non-empty, so this cannot fire
        return None
    unit = (record.unit.verbatim or record.unit.canonical).strip()
    return value.model_copy(
        update={
            "verbatim": f"{cell} {unit}".strip(),
            "section": record.section,
            "derivation": (DERIVATION_CELL_SI if value.value_si is not None else DERIVATION_CELL),
        }
    )


def _spec_context_value(side: RevisionSide, record: SpecRecord, what: str) -> DerivedValue:
    """A spec row's conditions or unit, quoted — prose, so never a number."""
    return DerivedValue(
        verbatim=_context_cell(record, what),
        source=_ref(side, record.id, SPECS_ARTIFACT),
        page=record.page,
        section=record.section,
        derivation=DERIVATION_CELL,
        confidence=record.confidence,
    )


def _ambiguous_specs(
    key: str, before: RevisionSide, after: RevisionSide, rows: Sequence[SpecRecord]
) -> list[str]:
    """The refusal for a parameter whose rows could not be paired, plus its values.

    Never reported as added + removed: that is a claim about the device, and a
    wrong one here reads as "the vendor deleted a parameter" when the vendor
    merely reworded a condition. The rows are listed instead, so a reader can do
    by eye what this module refuses to do by guess.
    """
    lines = [
        (
            f"uncomparable: {key} — this parameter prints several rows that share "
            f"no printed name across {before.label or 'the earlier revision'} and "
            f"{after.label or 'the later revision'}; pairing them would be a "
            f"guess, so every row is listed here instead"
        )
    ]
    lines.extend(
        f"uncomparable: {key} / {_spec_label(row)} — {_spec_printed(row)} ({_page(row.page)})"
        for row in rows
    )
    return lines


# --- pins --------------------------------------------------------------------


def _pin_changes(before: RevisionSide, after: RevisionSide) -> list[RevisionChange]:
    """Pins added, removed, renamed and re-typed, aligned by printed designator.

    The designator is the identity because it is what the package fixes: a pin
    whose *name* changed is the same physical ball, and calling that "one pin
    removed, one added" would tell a designer to redraw a footprint that did not
    move. A renamed pin is therefore its own `change` value.
    """
    old = _by_key(before.pins, lambda p: normalize(p.pin) or normalize(p.name))
    new = _by_key(after.pins, lambda p: normalize(p.pin) or normalize(p.name))
    changes: list[RevisionChange] = []
    for key, pin in new.items():
        previous = old.get(key)
        if previous is None:
            changes.append(
                _change(
                    KIND_PIN,
                    CHANGE_ADDED,
                    pin.pin or key,
                    label=pin.name,
                    aligned_on=ALIGNED_PIN,
                    after=_pin_value(after, pin, "name"),
                    summary=f"pin {pin.pin} {pin.name} — added",
                )
            )
            continue
        if previous.name.strip() != pin.name.strip():
            changes.append(
                _change(
                    KIND_PIN,
                    CHANGE_RENAMED,
                    pin.pin or key,
                    label=pin.name,
                    aligned_on=ALIGNED_PIN,
                    field="name",
                    before=_pin_value(before, previous, "name"),
                    after=_pin_value(after, pin, "name"),
                    summary=(f"pin {pin.pin} renamed: {previous.name!r} -> {pin.name!r}"),
                )
            )
        for what in ("type", "direction", "description"):
            old_cell = _pin_cell(previous, what)
            new_cell = _pin_cell(pin, what)
            if old_cell == new_cell:
                continue
            changes.append(
                _change(
                    KIND_PIN,
                    CHANGE_CHANGED,
                    pin.pin or key,
                    label=pin.name,
                    aligned_on=ALIGNED_PIN,
                    field=what,
                    before=_pin_value(before, previous, what),
                    after=_pin_value(after, pin, what),
                    summary=(
                        f"pin {pin.pin} {what}: {old_cell or '(none)'} -> {new_cell or '(none)'}"
                    ),
                )
            )
    for key, pin in old.items():
        if key in new:
            continue
        changes.append(
            _change(
                KIND_PIN,
                CHANGE_REMOVED,
                pin.pin or key,
                label=pin.name,
                aligned_on=ALIGNED_PIN,
                before=_pin_value(before, pin, "name"),
                summary=f"pin {pin.pin} {pin.name} — removed",
            )
        )
    return changes


def _pin_cell(pin: PinRecord, what: str) -> str:
    return (getattr(pin, what, "") or "").strip()


def _pin_value(side: RevisionSide, pin: PinRecord, what: str) -> DerivedValue:
    """One printed pin cell, quoted and cited to the pin record it came from.

    A pin's `type` is the one cell here that is **not** a verbatim copy: it is a
    label `registry/pin_types.yaml` assigned, and the phrase that assigned it is
    on the record as `type_evidence`. Its envelope therefore names the rule that
    produced it rather than claiming the page printed it — the source branch
    enveloped it as `copy_cell`, which its own reviewer flagged, and the fix is
    cheap enough to take on the way past.
    """
    derivation = DERIVATION_PIN_TYPE if what == "type" else DERIVATION_CELL
    return DerivedValue(
        verbatim=_pin_cell(pin, what),
        source=_ref(side, pin.id, PINS_ARTIFACT),
        page=pin.page,
        section=pin.section,
        derivation=derivation,
        confidence=pin.confidence,
    )


# --- registers ---------------------------------------------------------------


def _register_changes(
    before: RevisionSide, after: RevisionSide
) -> tuple[list[RevisionChange], list[str]]:
    """Registers and their bit fields, aligned by parsed address and field name.

    The address is the identity, in its parsed form where the grammar read one,
    because `0x1A04`, `0x1a04` and `6660` are one register and a diff that
    reported three would be worse than useless during bring-up. A register whose
    address never parsed keeps the string the document printed as its identity —
    the same rule `dsa regs --addr` follows.

    A **reset value change is its own `change`** because it is the delta this
    ticket exists for: it configures silicon at power-up, it is invisible in a
    section diff, and nobody expects to have to check it.
    """
    old = _bucket(before.registers, _register_key)
    new = _bucket(after.registers, _register_key)
    changes: list[RevisionChange] = []
    refused: list[str] = []
    for key in list(new) + [k for k in old if k not in new]:
        olds, news = old.get(key, []), new.get(key, [])
        pairs, only_old, only_new, ambiguous = _pair(olds, news, _register_identity)
        if ambiguous:
            refused.append(
                f"uncomparable: register {key} — {len(ambiguous)} rows print this "
                f"address under names that do not pair across the two revisions; "
                f"they are listed rather than guessed at"
            )
            refused.extend(
                f"uncomparable: register {key} / {row.name or '(unnamed)'} — "
                f"reset {row.reset.verbatim if row.reset else '(none stated)'} "
                f"({_page(row.page)})"
                for row in ambiguous
            )
        for previous, record in pairs:
            changes.extend(_register_pair_changes(key, before, after, previous, record))
        for record in only_new:
            changes.append(
                _change(
                    KIND_REGISTER,
                    CHANGE_ADDED,
                    _register_display(record),
                    label=record.name,
                    aligned_on=ALIGNED_REGISTER,
                    after=_register_value(after, record, "name"),
                    summary=(
                        f"register {_register_display(record)} {record.name} — added "
                        f"(reset {_reset_text(record)})"
                    ),
                )
            )
        for record in only_old:
            changes.append(
                _change(
                    KIND_REGISTER,
                    CHANGE_REMOVED,
                    _register_display(record),
                    label=record.name,
                    aligned_on=ALIGNED_REGISTER,
                    before=_register_value(before, record, "name"),
                    summary=(
                        f"register {_register_display(record)} {record.name} — removed "
                        f"(was reset {_reset_text(record)})"
                    ),
                )
            )
    return changes, refused


def _register_pair_changes(
    key: str,
    before: RevisionSide,
    after: RevisionSide,
    previous: RegisterRecord,
    record: RegisterRecord,
) -> list[RevisionChange]:
    """One aligned register's moved cells, its reset first, then its bit fields."""
    changes: list[RevisionChange] = []
    display = _register_display(record)
    old_reset, new_reset = _reset_text(previous), _reset_text(record)
    if old_reset != new_reset:
        changes.append(
            _change(
                KIND_REGISTER,
                CHANGE_RESET,
                display,
                label=record.name,
                aligned_on=ALIGNED_REGISTER,
                field="reset",
                before=_register_value(before, previous, "reset"),
                after=_register_value(after, record, "reset"),
                note=(
                    "a reset value is a bit pattern, not a magnitude: it is "
                    "reported verbatim and never subtracted, because a signed "
                    "difference between two reset words means nothing"
                ),
                summary=(f"register {display} {record.name} reset: {old_reset} -> {new_reset}"),
            )
        )
    if previous.name.strip() != record.name.strip():
        changes.append(
            _change(
                KIND_REGISTER,
                CHANGE_RENAMED,
                display,
                label=record.name,
                aligned_on=ALIGNED_REGISTER,
                field="name",
                before=_register_value(before, previous, "name"),
                after=_register_value(after, record, "name"),
                summary=(f"register {display} renamed: {previous.name!r} -> {record.name!r}"),
            )
        )
    for what in ("access", "description"):
        old_cell = getattr(previous, what, "").strip()
        new_cell = getattr(record, what, "").strip()
        if old_cell == new_cell:
            continue
        changes.append(
            _change(
                KIND_REGISTER,
                CHANGE_CHANGED,
                display,
                label=record.name,
                aligned_on=ALIGNED_REGISTER,
                field=what,
                before=_register_value(before, previous, what),
                after=_register_value(after, record, what),
                summary=(
                    f"register {display} {what}: {old_cell or '(none)'} -> {new_cell or '(none)'}"
                ),
            )
        )
    changes.extend(_field_changes(display, before, after, previous, record))
    return changes


def _field_changes(
    display: str,
    before: RevisionSide,
    after: RevisionSide,
    previous: RegisterRecord,
    record: RegisterRecord,
) -> list[RevisionChange]:
    """Bit fields added, removed, moved and re-reset inside one aligned register.

    A bit field is its own `kind` because it is its own risk: a field that moved
    from `2:0` to `3:1` compiles, runs and misconfigures silicon silently, and a
    diff that folded it into "register R25 changed" would have said nothing a
    driver author could act on.
    """
    old = _by_key(previous.fields, lambda f: normalize(f.name))
    new = _by_key(record.fields, lambda f: normalize(f.name))
    changes: list[RevisionChange] = []
    for key, field_record in new.items():
        earlier = old.get(key)
        label = f"{display}.{field_record.name}"
        if earlier is None:
            changes.append(
                _change(
                    KIND_FIELD,
                    CHANGE_ADDED,
                    label,
                    label=field_record.name,
                    aligned_on=ALIGNED_FIELD,
                    after=_field_value(after, record, field_record, "bits"),
                    summary=(
                        f"field {label} — added at bits "
                        f"{field_record.bits.verbatim or '(unstated)'}"
                    ),
                )
            )
            continue
        if earlier.bits.verbatim.strip() != field_record.bits.verbatim.strip():
            changes.append(
                _change(
                    KIND_FIELD,
                    CHANGE_CHANGED,
                    label,
                    label=field_record.name,
                    aligned_on=ALIGNED_FIELD,
                    field="bits",
                    before=_field_value(before, previous, earlier, "bits"),
                    after=_field_value(after, record, field_record, "bits"),
                    summary=(
                        f"field {label} bits: {earlier.bits.verbatim or '(unstated)'}"
                        f" -> {field_record.bits.verbatim or '(unstated)'}"
                    ),
                )
            )
        if earlier.reset.strip() != field_record.reset.strip():
            changes.append(
                _change(
                    KIND_FIELD,
                    CHANGE_RESET,
                    label,
                    label=field_record.name,
                    aligned_on=ALIGNED_FIELD,
                    field="reset",
                    before=_field_value(before, previous, earlier, "reset"),
                    after=_field_value(after, record, field_record, "reset"),
                    summary=(
                        f"field {label} reset: {earlier.reset or '(none stated)'} -> "
                        f"{field_record.reset or '(none stated)'}"
                    ),
                )
            )
    for key, field_record in old.items():
        if key in new:
            continue
        label = f"{display}.{field_record.name}"
        changes.append(
            _change(
                KIND_FIELD,
                CHANGE_REMOVED,
                label,
                label=field_record.name,
                aligned_on=ALIGNED_FIELD,
                before=_field_value(before, previous, field_record, "bits"),
                summary=(
                    f"field {label} — removed (was bits "
                    f"{field_record.bits.verbatim or '(unstated)'})"
                ),
            )
        )
    return changes


def _register_key(record: RegisterRecord) -> str:
    """A register's identity: its parsed address, else exactly what was printed."""
    if record.address.value is not None:
        return f"0x{record.address.value:X}"
    return normalize(record.address.verbatim) or normalize(record.name) or "(unnamed)"


def _register_display(record: RegisterRecord) -> str:
    return record.address.verbatim.strip() or _register_key(record)


def _register_identity(record: RegisterRecord) -> frozenset[str]:
    return frozenset(
        text for text in (normalize(record.name), normalize(record.address.verbatim)) if text
    )


def _reset_text(record: RegisterRecord) -> str:
    """A register's printed reset, or the honest absence of one.

    `(none stated)` rather than `0x0`: a register the document states no reset
    for has none, and a zero here would be a value nobody printed.
    """
    if record.reset is None or not record.reset.verbatim.strip():
        return "(none stated)"
    return record.reset.verbatim.strip()


def _register_value(side: RevisionSide, record: RegisterRecord, what: str) -> DerivedValue:
    """One printed register cell, quoted and cited to its record.

    `value_si` stays `None` for every one of them, the reset included: an address
    and a reset word are bit patterns, and putting them on the numeric layer
    would invite exactly the subtraction this module refuses to do.
    """
    verbatim = _reset_text(record) if what == "reset" else getattr(record, what, "").strip()
    return DerivedValue(
        verbatim=verbatim,
        source=_ref(side, record.id, REGISTERS_ARTIFACT),
        page=record.page,
        section=record.section,
        derivation=DERIVATION_CELL,
        confidence=record.confidence,
    )


def _field_value(
    side: RevisionSide, record: RegisterRecord, field_record, what: str
) -> DerivedValue:
    """One printed bit-field cell, cited to the **register** record that holds it.

    A bit field has no id of its own — it is published inside its register — so
    its reference names that register, which is the record a reader resolves and
    the page they open.
    """
    if what == "bits":
        verbatim = field_record.bits.verbatim.strip() or "(unstated)"
    else:
        verbatim = getattr(field_record, what, "").strip() or "(none stated)"
    return DerivedValue(
        verbatim=verbatim,
        source=_ref(side, record.id, REGISTERS_ARTIFACT),
        page=field_record.page if field_record.page is not None else record.page,
        section=record.section,
        derivation=DERIVATION_CELL,
        confidence=field_record.confidence,
    )


# --- shared machinery --------------------------------------------------------


def _change(
    kind: str,
    change: str,
    key: str,
    *,
    label: str = "",
    aligned_on: str = "",
    field: str = "",
    before: DerivedValue | None = None,
    after: DerivedValue | None = None,
    delta: DerivedValue | None = None,
    summary: str = "",
    note: str = "",
) -> RevisionChange:
    """One change, flagged for review by hand unless it carries a delta.

    The flag is set **here**, in one place, so the rule cannot be true of specs
    and quietly false of registers: a change this tool did not measure says so on
    the record itself, and every rendering of it inherits that.
    """
    return RevisionChange(
        kind=kind,
        change=change,
        key=key,
        label=label,
        field=field,
        aligned_on=aligned_on,
        before=before,
        after=after,
        delta=delta,
        summary=summary,
        flags=[] if delta is not None else [FLAG_REVIEW],
        note=note,
    )


def _delta(
    role: str, before: DerivedValue | None, after: DerivedValue | None
) -> tuple[DerivedValue | None, str]:
    """The later value minus the earlier one, or `None` and the reason why.

    Sign convention, stated once: the delta is `after − before`, so a positive
    number means the newer revision states the larger value. It carries no
    `verbatim` — no page printed a difference between two revisions — and it
    cites **both** operands, because a delta that cited one of them would be
    traceable by exactly half.

    The arithmetic itself is `derive.compare.si_delta`, this branch's one
    documented pure function for subtracting two printed cells, rather than a
    second implementation here: `dsa compare` and `dsa diff-rev` ask the same
    question of the same two envelopes, and two rules for "what is a delta"
    is exactly the divergence a reader could never see. One consequence worth
    naming: a `max` cell that printed a **range** asserts its top on this
    branch, so it scores rather than dropping to review by hand.
    """
    if before is None or after is None:
        return None, (
            "one revision prints no value in this column — added and removed "
            "values are reviewed by hand, never scored as a difference"
        )
    computed = si_delta(before, after, role)
    if computed is None and (before.value_si is None or after.value_si is None):
        unreadable = [
            f"{side} {value.verbatim!r}"
            for side, value in (("before", before), ("after", after))
            if value.value_si is None
        ]
        return None, (
            f"no delta: the numeric layer read no comparable number from "
            f"{', '.join(unreadable)} — both are quoted above, verbatim"
        )
    if computed is None:
        return None, (
            f"no delta: the two revisions state this {role} in different bases "
            f"({after.unit_si or 'unitless'} against {before.unit_si or 'unitless'})"
            f" — a change of unit is a change to review, not to subtract"
        )
    difference, unit = computed
    return (
        DerivedValue(
            value_si=difference,
            unit_si=unit,
            source=after.source,
            sources=[before.source],
            page=after.page,
            section=after.section,
            derivation=f"{DERIVATION_DELTA}:{role}",
            confidence=_weaker(after.confidence, before.confidence),
        ),
        "",
    )


def _value_summary(
    label: str,
    before: DerivedValue | None,
    after: DerivedValue | None,
    delta: DerivedValue | None,
) -> str:
    """`TJ max 105 °C -> 125 °C (+20 °C)` — verbatim on both sides.

    The arrow half is always the two printed strings, so a value the numeric
    layer could not read still reads correctly; the parenthesized delta is
    appended only where one exists, which is the ticket's third criterion made
    visible in the one line most readers will actually read.
    """
    left = before.verbatim if before is not None else "(not printed)"
    right = after.verbatim if after is not None else "(not printed)"
    line = f"{label} {left} -> {right}"
    if delta is None:
        return line
    return f"{line} ({_signed(delta)})"


def _signed(delta: DerivedValue) -> str:
    """A delta as a signed number in its SI base — the only number added here."""
    value = delta.value_si or 0.0
    number = f"{value:+.6g}"
    return f"{number} {delta.unit_si}".strip()


def _review_line(change: RevisionChange) -> str:
    """One line under "review by hand": what moved, quoted, with its pages.

    Quoted from the two envelopes rather than re-read from the records, so this
    listing and the table above it can never disagree about what the document
    printed.
    """
    where = " ".join(
        part
        for part in (
            f"was {_page(change.before.page)}" if change.before is not None else "",
            f"now {_page(change.after.page)}" if change.after is not None else "",
        )
        if part
    )
    detail = change.summary or f"{change.kind} {change.key} {change.change}"
    line = f"{change.kind} {change.change}: {detail}"
    return f"{line} ({where})" if where else line


def _page(page: int | None) -> str:
    return f"p.{page}" if page is not None else "p.?"


def _ref(side: RevisionSide, record_id: str, artifact: str) -> str:
    """A record's document-qualified `source`, or `""` when it has no id.

    Qualified by the document directory, the way `derive/cards.py` qualifies
    one, and for one extra reason here: **both** revisions of a part publish a
    `rec_1`, so a bare `specs.json#rec_1` would resolve to a confident, wrong
    record — the earlier revision's row read as the later one's. A record with
    no id gets no reference rather than a fabricated one; the diff still reports
    the change.

    The base is the side's own `reference_base`, not a composed `docs/<doc>`,
    because a document published once into the shared library store is
    referenced `@library/docs/<doc>/…` and resolving it against the part
    directory would find nothing.
    """
    if not record_id:
        return ""
    base = side.reference_base
    return source_ref(f"{base}/{artifact}" if base else artifact, record_id)


def _by_key(records: Iterable, key) -> dict:
    """Records by identity, first occurrence winning, in publication order.

    First wins rather than last, so a duplicate key never silently replaces the
    row a reader already saw; duplicates are what `_pair` refuses on the spec and
    register paths, and the artifacts that use this one (`sections`, `pins`,
    bit fields) are validated as unique before they are published at all.
    """
    out: dict = {}
    for record in records:
        identity = key(record)
        if identity not in out:
            out[identity] = record
    return out


def _bucket(records: Iterable, key) -> dict:
    """Records grouped by identity, in publication order."""
    out: dict = {}
    for record in records:
        out.setdefault(key(record), []).append(record)
    return out


def _pair(olds: Sequence, news: Sequence, identity):
    """`(pairs, only_old, only_new, ambiguous)` for one alignment key.

    One row on each side pairs. One side empty is an addition or a removal.
    Several on a side pair **only** on a printed identity cell shared character
    for character — the one widening `compare.build._pair_by_identity` allows,
    and for the same reason: a cell matching two rows on one side proves nothing
    about which was meant. What is left over is `ambiguous`, which the caller
    lists verbatim rather than reporting as added + removed.
    """
    if len(olds) <= 1 and len(news) <= 1:
        if olds and news:
            return [(olds[0], news[0])], [], [], []
        return [], list(olds), list(news), []

    pairs = []
    used_old: set[int] = set()
    used_new: set[int] = set()
    for new_row in news:
        cells = identity(new_row)
        matches = [
            old_row
            for old_row in olds
            if id(old_row) not in used_old and identity(old_row) == cells
        ]
        if len(matches) != 1:
            continue
        pairs.append((matches[0], new_row))
        used_old.add(id(matches[0]))
        used_new.add(id(new_row))
    left_old = [row for row in olds if id(row) not in used_old]
    left_new = [row for row in news if id(row) not in used_new]
    if not left_old:
        return pairs, [], left_new, []
    if not left_new:
        return pairs, left_old, [], []
    return pairs, [], [], left_old + left_new


def _notes(diff: RevisionDiff, before: RevisionSide, after: RevisionSide) -> list[str]:
    """The sentences invariant 8 requires of a consumer that compares.

    Two populations, and they answer different questions. The **changed** values
    it could not score are the population of this artifact — every one of them is
    listed under review by hand — and the **records** each revision publishes that
    state no readable quantity at all are the substrate that population came out
    of. Only the first is listed row by row here: listing the second would repeat
    hundreds of `See Figure 7` rows that did not change between the revisions and
    bury the ones that did.
    """
    unscored = sum(1 for change in diff.changes if change.delta is None)
    lines = [
        (
            f"{diff.n_changes} changes between {before.label or before.doc} and "
            f"{after.label or after.doc}: {diff.n_deltas} carry a numeric delta; "
            f"{unscored} state no comparable number in one printed column and are "
            f"listed verbatim under 'review by hand', unscored."
        ),
    ]
    for side in (before, after):
        valueless = sum(1 for record in side.specs if not _has_printed_value(record))
        lines.append(
            f"{side.label or side.doc}: {_population(coverage(side.specs))} "
            f"({len(side.specs)} spec records, {len(side.sections)} sections, "
            f"{len(side.pins)} pins, {len(side.registers)} registers); "
            f"{valueless} of those spec records print no value in any column and "
            f"take no part in the alignment."
        )
    for side in (before, after):
        if side.revision_note:
            lines.append(f"{side.label or side.doc}: {side.revision_note}")
    if diff.unparsed:
        lines.append(
            f"{len(diff.unparsed)} lines under 'not comparable': parameters whose "
            f"rows could not be paired across the revisions without a guess."
        )
    return lines


def _population(parsed: ParseCoverage) -> str:
    """The one-line population sentence, without the listing `describe()` adds.

    `ParseCoverage.describe()` is multi-line by design — it lists every unparsed
    cell — and these notes are read as bullet points beside a table, so the
    count is quoted here and the listing stays where it already is: every
    unscored change is under *Review by hand*, verbatim, with its pages.
    """
    if parsed.considered == 0:
        return "no spec row printed a value to parse"
    return (
        f"{parsed.parsed} of {parsed.considered} spec rows that printed a value "
        f"parsed into a number ({parsed.unparsed_count} did not)"
    )


def _empty_reason(before: RevisionSide, after: RevisionSide) -> str:
    """Why a diff has no changes — the honestly empty artifact.

    Two absences a reader must not confuse: two revisions that really are
    identical in every published record, and a "diff" of one document against
    itself, which proves determinism and nothing about any datasheet.
    """
    if before.doc and before.doc == after.doc:
        return (
            f"no differences: both sides name the same document ({before.doc}), so "
            f"this is a determinism check rather than a revision comparison"
        )
    return (
        f"no differences: every spec record, section, pin, register and bit field "
        f"{before.label or before.doc} publishes is published identically by "
        f"{after.label or after.doc}. Nothing was suppressed — a change this tool "
        f"could not score would still be listed under 'review by hand'"
    )


__all__ = [
    "ALIGNED_ALIAS",
    "ALIGNED_FIELD",
    "ALIGNED_PIN",
    "ALIGNED_PRINTED",
    "ALIGNED_REGISTER",
    "ALIGNED_SECTION",
    "ALIGNED_SECTION_TITLE",
    "CHANGE_ADDED",
    "CHANGE_CHANGED",
    "CHANGE_PAGE_SHIFTED",
    "CHANGE_REMOVED",
    "CHANGE_RENAMED",
    "CHANGE_RESET",
    "CHANGE_RETITLED",
    "DERIVATION_CELL",
    "DERIVATION_CELL_SI",
    "DERIVATION_DELTA",
    "DERIVATION_PIN_TYPE",
    "FLAG_REVIEW",
    "KIND_FIELD",
    "KIND_PIN",
    "KIND_REGISTER",
    "KIND_SECTION",
    "KIND_SPEC",
    "ROLE_ORDER",
    "RevisionSide",
    "build_revision_diff",
]
