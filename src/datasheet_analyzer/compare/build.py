"""Records from several parts -> one comparison: the part-selection question.

Phase 6, ticket 09. A comparison is a **view** in exactly the sense a design
card is (`cards/build.py`), one noun wider: it owns no value, it quotes rows
that each part's `specs.json` — or each part's own design card — already
publishes, and it says of every number where it came from. ADR 0005 governs it
whole:

- **(a)** every printed value is a cell copied verbatim into its envelope, with
  its printed unit, exactly as a card copies one (`copy_cell`, plus the additive
  `+parse_quantity+si_normalize` when the numeric layer could read it);
- **(b)** the one number a comparison adds is the **delta**, a documented pure
  function of two quoted cells (`si_delta:<role>`), computed only where both
  sides parsed the *same printed column* into the same SI base;
- **(c)** the structural label is the alignment key — the alias-resolved symbol
  from `registry/aliases.yaml`, recorded on the row as `aligned_on`.

Four rules govern the module, and each of them is a refusal.

**Rows align by alias-resolved symbol, and the row says so.** Two parts name one
parameter differently (`OPERATING JUNCTION TEMPERATURE (T` against `Junction
temperature`), which is the whole reason the alias lexicon exists; a row that
aligned them records `alias:TJ`, and a row that aligned two identical printed
symbols records `printed-symbol`. A mis-alignment must be readable, not
invisible.

**An ambiguous alignment is refused, not resolved.** Where a key arrives with
several rows from one part, the only pairing this module will make is between
rows that share a printed identity cell character for character — a fact about
the page, the same widening `cards.build._pair_by_identity` allows and for the
same reason. Everything left over is published as a listing of the actual
printed values, one line each, because a delta between the wrong two rows during
part selection is worse than no delta at all.

**A delta compares one printed column.** A datasheet's `typ` and another's `max`
are not comparable numbers, so the role is chosen once per row (the first of
`ROLE_ORDER` the reference part and at least one other part both parsed) and
named in the derivation (`si_delta:max`). Two sides in different SI bases are
refused with the reason.

**Every reference names its part.** This is the first derived artifact whose
values come from *two corpora*, and `rec_1` exists in nearly every one of them,
so a reference that leaves its part implicit resolves to a confident, wrong
record. Every value here therefore carries the part-qualified form
`provenance.source_ref(..., part=...)` mints — including a card comparison's,
whose values arrive from a card that (correctly) left the part out.

**Nothing is dropped.** A parameter one part prints and another does not is a
`missing_from` row flagged `only-in` — during part selection an absent parameter
is itself a finding — and every pair that could not be compared is listed with
its verbatim values under the comparison's `unparsed`, beside
`quantities.parse_population`'s sentence per part (invariant 8's honesty half).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from datasheet_analyzer.config import CARD_VERSION, COMPARE_SCHEMA_VERSION
from datasheet_analyzer.models import (
    ComparisonCell,
    ComparisonRow,
    DerivedValue,
    DesignCard,
    PartComparison,
    SpecRecord,
)
from datasheet_analyzer.provenance import SPECS_ARTIFACT, parse_source, source_ref
from datasheet_analyzer.retrieve.results import Citation
from datasheet_analyzer.structure.aliases import AliasLexicon, load_lexicon, normalize
from datasheet_analyzer.structure.confidence import weakest
from datasheet_analyzer.structure.quantities import parse_population, parse_quantity

#: The rule name a delta records (invariant 8's `derivation`); the printed
#: column it was computed on is appended, because "the maximums differ by 30 °C"
#: and "the typicals do" are different claims.
DERIVATION_DELTA = "si_delta"
#: What a copied cell records, mirroring `cards.build` — one rule, two artifacts.
DERIVATION_CELL = "copy_cell"
DERIVATION_CELL_SI = "copy_cell+parse_quantity+si_normalize"

#: How a row aligned. `alias:<symbol>` names the lexicon entry that claimed both
#: sides; `printed-symbol` means the parts printed the same identity themselves;
#: `printed-identity:<cell>` is the tie-break rung inside an ambiguous key.
ALIGNED_ALIAS = "alias"
ALIGNED_PRINTED = "printed-symbol"
ALIGNED_IDENTITY = "printed-identity"
#: A card comparison aligns on the card's own group *and* row identity, because
#: two cards can print one name under two groups (a rail and its current).
ALIGNED_CARD = "card-row"

#: How a caller that holds a **stronger** identity than the alias lexicon
#: overrides the alignment (phase 7, ticket 07). Called once per record; returns
#: `(key, aligned_on, group)`, where `group` scopes the key so two identical
#: identities printed on two different tables cannot collide.
#:
#: It exists for the family index, whose members are one vendor's one document
#: template published for several devices: there, the identity that survives is
#: the row as printed inside the section it was printed in, and resolving it
#: through the alias lexicon would collapse `IVDD1P8` and `IVDD1P2` onto one key
#: and refuse them both as ambiguous. Everything downstream of the key — the
#: pairing, the refusals, the delta, the unparsed population — is unchanged,
#: which is the point: one alignment engine, two artifacts.
SpecKeyFn = Callable[[SpecRecord], tuple[str, str, str]]

#: Rows a reader must not misread. `only-in` means a compared part publishes no
#: record under this parameter at all; `ambiguous` means one publishes several
#: that could not be paired, which is a different fact and is listed separately.
FLAG_ONLY_IN = "only-in"
FLAG_AMBIGUOUS = "ambiguous"

#: The printed columns a delta may be computed on, in the order it prefers them.
#: `max` leads because a design is bounded by a maximum, then `typ` (what a
#: datasheet quotes back), then `min`, then the single-value column; the card
#: roles follow, so a `--card limits` comparison can compare two margins. Order
#: only decides between columns *both* parts printed, so a pair that states one
#: number each still compares whatever that number is.
ROLE_ORDER: tuple[str, ...] = (
    "max", "typ", "min", "value", "margin", "abs_max", "recommended_max", "pins",
)

#: Comparison kinds, as `PartComparison.kind` records them.
KIND_SYMBOL = "symbol"
KIND_NAME = "name"
KIND_CARD = "card"


@dataclass(frozen=True)
class CompareRecord:
    """One part's spec record on its way into a comparison.

    `doc` is the corpus document directory the record lives in, which is what a
    fully qualified `source` reference names; `matched_via` is the ladder rung
    that produced it, carried through so an aligned row can say how each side
    was found.
    """

    doc: str
    record: SpecRecord
    matched_via: str = ""


@dataclass(frozen=True)
class ComparePart:
    """One part as the comparison consumes it: its number and its records.

    Deliberately not a `Retriever`: the lookups belong to `retrieve/`, and taking
    the *result* of one keeps this module pure and testable from literals.
    """

    part_number: str
    records: tuple[CompareRecord, ...] = ()


@dataclass(frozen=True)
class _Candidate:
    """One part's row, normalized into what alignment needs."""

    part: str
    key: str
    label_key: str
    aligned_on: str
    group: str = ""
    label: str = ""
    detail: str = ""
    section: str = ""
    section_title: str = ""
    matched_via: str = ""
    page: int | None = None
    identity: frozenset[str] = field(default_factory=frozenset)
    values: dict[str, DerivedValue] = field(default_factory=dict)


def build_spec_comparison(
    parts: Sequence[ComparePart],
    *,
    term: str,
    kind: str = KIND_SYMBOL,
    lexicon: AliasLexicon | None = None,
    key_for: SpecKeyFn | None = None,
) -> PartComparison:
    """Compare the records each part resolved for one query term.

    The records are whatever each part's own resolution ladder returned — a
    rung is a statement about one corpus's vocabulary, so each part answers for
    itself and the alignment happens afterwards, on the alias-resolved symbol.

    `key_for` (additive, phase 7 ticket 07) replaces *only* that last step, for a
    caller holding a stronger identity than the lexicon — see `SpecKeyFn`. It is
    never a widening: a key function that pairs two rows the lexicon would not
    still goes through the same identity tie-break and the same refusals.
    """
    lexicon = load_lexicon() if lexicon is None else lexicon
    candidates: list[_Candidate] = []
    unaddressable: list[str] = []
    for part in parts:
        for entry in part.records:
            # Two different reasons a row cannot become a column, kept apart
            # because only one of them is a finding about the *corpus*. A row
            # with no id predates ADR 0005 and is reported with the fix; a row
            # that printed no value in any column is already named, once, by
            # `parse_population`'s listing below — saying it twice, and once
            # under the wrong reason, would be worse than saying it plainly.
            if not entry.record.id:
                unaddressable.append(_unaddressable(part.part_number, entry.record))
                continue
            candidate = _spec_candidate(
                part.part_number, entry, lexicon=lexicon, key_for=key_for
            )
            if candidate is not None:
                candidates.append(candidate)

    comparison = _assemble(
        [p.part_number for p in parts],
        candidates,
        kind=kind,
        query=term,
    )
    comparison.unparsed.extend(unaddressable)
    for part in parts:
        population = parse_population(entry.record for entry in part.records)
        comparison.notes.append(f"{part.part_number}: {population.describe()}.")
        comparison.unparsed.extend(
            f"{part.part_number}: {line}" for line in population.listing()
        )
    if not comparison.rows:
        comparison.empty_reason = _empty_reason(parts, term=term, kind=kind)
    return comparison


def build_card_comparison(
    cards: Sequence[DesignCard],
    *,
    name: str,
    lexicon: AliasLexicon | None = None,
) -> PartComparison:
    """Compare one design card of several parts, row by row.

    The rows are already derived — a card row's values are `DerivedValue`s
    carrying their own source, page and rule — so this adds exactly one thing:
    the alignment, and the delta where two aligned rows state a comparable
    number in the same column. A card that is honestly empty for one part
    contributes no rows, and every parameter the others print then reports that
    part under `missing_from`, which is the useful reading during part selection.
    """
    lexicon = load_lexicon() if lexicon is None else lexicon
    candidates = [
        _card_candidate(card.part_number, row, lexicon=lexicon)
        for card in cards
        for row in card.rows
    ]
    comparison = _assemble(
        [card.part_number for card in cards],
        candidates,
        kind=KIND_CARD,
        query=name,
    )
    for card in cards:
        comparison.notes.append(f"{card.part_number}: {_card_population(card)}.")
        comparison.unparsed.extend(
            f"{card.part_number}: {line}" for line in _card_listing(card)
        )
        if card.empty_reason:
            comparison.unparsed.append(f"{card.part_number}: {card.empty_reason}")
    if not comparison.rows:
        comparison.empty_reason = (
            f"no {name} comparison: none of {', '.join(c.part_number for c in cards)} "
            f"publishes a {name} card row that any other part also publishes "
            f"(`dsa card --part <PART> --card {name}` shows what each one holds)"
        )
    return comparison


# --- candidates --------------------------------------------------------------


def _spec_candidate(
    part: str,
    entry: CompareRecord,
    *,
    lexicon: AliasLexicon,
    key_for: SpecKeyFn | None = None,
) -> _Candidate | None:
    """One spec record as a comparison candidate, or `None` when it cannot be one.

    Two ways that happens, and the caller reports them differently (see
    `build_spec_comparison`): a record with no `id` cannot be **cited** — a
    corpus published before ADR 0005 — and an uncited value has no business on a
    derived artifact; a record with no printed value in any column has nothing to
    put in a cell, and is already named by the part's own unparsed population.
    """
    record = entry.record
    if not record.id:
        return None
    values = {
        role: value
        for role, value in (
            (r, _cell(part, entry.doc, record, r)) for r in ("min", "typ", "max", "value")
        )
        if value is not None
    }
    if not values:
        return None
    group = ""
    if key_for is not None:
        key, aligned_on, group = key_for(record)
    else:
        key, aligned_on = _alignment_key(record.symbol, record.name, lexicon=lexicon)
    return _Candidate(
        part=part,
        key=key,
        label_key=key if aligned_on.startswith(ALIGNED_ALIAS) else "",
        aligned_on=aligned_on,
        group=group,
        label=record.symbol or record.name,
        detail=record.name if record.symbol else record.conditions,
        section=record.section,
        section_title=record.section_title,
        matched_via=entry.matched_via,
        page=record.page,
        identity=_identity_cells(record.symbol, record.name),
        values=values,
    )


def _card_candidate(part: str, row, *, lexicon: AliasLexicon) -> _Candidate:
    """One design-card row as a comparison candidate.

    Its values are already envelopes, so nothing is re-derived here: a card
    comparison quotes the card, and the card quotes the record.
    """
    key, aligned_on = _alignment_key(row.label, row.detail, lexicon=lexicon)
    return _Candidate(
        part=part,
        key=key,
        label_key=key if aligned_on.startswith(ALIGNED_ALIAS) else "",
        # Both halves: that these rows came off a card, *and* what aligned them
        # inside it. "card-row" alone would say where a row is from and not what
        # it matched on, which is the half a reader needs to check an alignment.
        aligned_on=f"{ALIGNED_CARD}+{aligned_on}",
        group=row.group,
        label=row.label,
        detail=row.detail,
        section=row.section,
        section_title=row.section_title,
        matched_via=row.selector,
        page=next((v.page for v in row.values.values() if v.page is not None), None),
        identity=_identity_cells(row.label, ""),
        values={role: _qualify(value, part) for role, value in row.values.items()},
    )


def _qualify(value: DerivedValue, part: str) -> DerivedValue:
    """The card's value with every reference named to its part.

    A design card lives inside one corpus, so its references leave the part
    implicit — correctly, since naming it there would be noise. A *comparison*
    holds values from two corpora at once, and `rec_1` exists in both: a
    reference that does not say which part it belongs to resolves to a
    confident, wrong record. Nothing else about the value is touched, and a
    reference this module cannot parse is left exactly as the card wrote it
    rather than rewritten on a guess.
    """
    return value.model_copy(
        update={
            "source": _qualified(value.source, part),
            "sources": [_qualified(ref, part) for ref in value.sources],
        }
    )


def _qualified(ref: str, part: str) -> str:
    """One reference, part-qualified; unchanged when it already is, or is not one."""
    parsed = parse_source(ref)
    if parsed is None or parsed.part:
        return ref
    return source_ref(
        parsed.record_id, artifact=parsed.artifact, doc=parsed.doc, part=part
    )


def _cell(part: str, doc: str, record: SpecRecord, role: str) -> DerivedValue | None:
    """One printed cell in its provenance envelope, or `None` when it is empty.

    The same rule `cards.build._cell` applies, for the same reason: `verbatim`
    carries the row's printed unit (`"150 °C"`), because a value quoted without
    its unit is the one way this artifact could mislead someone who trusts it —
    and a cross-part comparison is read by someone choosing a part.
    """
    cell = getattr(record, role, "").strip()
    if not cell:
        return None
    unit = record.unit.verbatim or record.unit.canonical
    quantity = parse_quantity(cell, unit)
    scalar = None if quantity is None else _scalar(quantity)
    return DerivedValue(
        verbatim=f"{cell} {unit}".strip(),
        value_si=scalar,
        unit_si=quantity.unit_si if quantity else "",
        source=source_ref(record.id, artifact=SPECS_ARTIFACT, doc=doc, part=part),
        page=record.page,
        section=record.section,
        derivation=DERIVATION_CELL_SI if quantity else DERIVATION_CELL,
        confidence=record.confidence,
    )


def _scalar(quantity) -> float | None:
    """The single comparable number a parsed cell states, or `None`.

    A point states one, a tolerance its magnitude, a **bound** the side it
    printed (`< 5` is a ceiling of 5); a **range** states no single number, so a
    range is not silently reduced to one of its endpoints — it is published
    verbatim and listed as not comparable. (`cards.build._scalar` decides the
    same thing for the same reason.)
    """
    if quantity.value_si is not None:
        return quantity.value_si
    low, high = quantity.span
    if low is not None and high is None:
        return low
    if high is not None and low is None:
        return high
    return None


def _alignment_key(symbol: str, name: str, *, lexicon: AliasLexicon) -> tuple[str, str]:
    """`(key, aligned_on)` — the alias-resolved symbol where one exists.

    The lexicon is what makes `TJ` and `Junction temperature` one row; where it
    claims nothing, two parts still align on a printed identity they share, and
    the row says which of the two happened.
    """
    entry = lexicon.entry_for(symbol, name)
    if entry is not None:
        return entry.symbol, f"{ALIGNED_ALIAS}:{entry.symbol}"
    printed = normalize(symbol) or normalize(name)
    return printed or "(unnamed row)", ALIGNED_PRINTED


def _identity_cells(symbol: str, name: str) -> frozenset[str]:
    """The printed strings that name a row, normalized for comparison.

    Symbol and name as separate cells, never joined: one part's *name* cell can
    be another's *symbol* cell (`cards.build._identity_cells`, same reason).
    """
    return frozenset(text for text in (normalize(symbol), normalize(name)) if text)


# --- assembly ----------------------------------------------------------------


def _assemble(
    part_numbers: Sequence[str],
    candidates: Sequence[_Candidate],
    *,
    kind: str,
    query: str,
) -> PartComparison:
    """Group candidates into rows, compute the deltas, and report the refusals."""
    comparison = PartComparison(
        schema_version=COMPARE_SCHEMA_VERSION,
        card_version=CARD_VERSION,
        kind=kind,
        query=query,
        parts=list(part_numbers),
        reference=part_numbers[0] if part_numbers else "",
    )
    buckets: dict[tuple[str, str], list[_Candidate]] = {}
    for candidate in candidates:
        buckets.setdefault((candidate.group, candidate.key), []).append(candidate)

    for (group, key), bucket in buckets.items():
        rows, reasons = _bucket_rows(key, group, bucket, part_numbers)
        comparison.rows.extend(rows)
        comparison.unparsed.extend(reasons)

    compared = sum(1 for row in comparison.rows if row.n_deltas)
    only_in = sum(1 for row in comparison.rows if FLAG_ONLY_IN in row.flags)
    comparison.notes.insert(
        0,
        f"{len(comparison.rows)} aligned parameters across "
        f"{', '.join(part_numbers)}: {compared} carry an SI delta against "
        f"{comparison.reference}; {len(comparison.rows) - compared - only_in} align "
        f"but state no comparable number in one printed column and are listed "
        f"under 'not comparable'; {only_in} are printed by only some of these "
        f"parts.",
    )
    return comparison


def _bucket_rows(
    key: str, group: str, bucket: Sequence[_Candidate], part_numbers: Sequence[str]
) -> tuple[list[ComparisonRow], list[str]]:
    """Every row one alignment key produces, and the refusals beside them.

    The refusal is **per part, not per key**: a part that prints several rows a
    shared printed name cannot pair contributes no column and is named in
    `ambiguous_in`, while the parts that print exactly one still line up and
    still get their delta. Refusing the whole key instead would let a third
    device's messy table erase a comparison between two clean ones — and the
    rows nobody could pair are listed verbatim either way, so nothing is lost by
    keeping the honest half.
    """
    per_part = {part: [c for c in bucket if c.part == part] for part in part_numbers}
    missing = [part for part in part_numbers if not per_part[part]]
    present = [part for part in part_numbers if per_part[part]]

    if len(present) == 1:
        # Only one part prints this parameter at all: every row of it is an
        # `only in A` row, and there is no ambiguity to refuse because there is
        # nothing on the other side to pair against.
        rows, reasons = [], []
        for candidate in bucket:
            row, why = _row(key, group, [candidate], part_numbers, missing_from=missing)
            rows.append(row)
            reasons.extend(why)
        return rows, reasons

    if all(len(found) <= 1 for found in per_part.values()):
        row, reasons = _row(key, group, bucket, part_numbers, missing_from=missing)
        return [row], reasons

    paired, leftover = _pair_by_identity(key, bucket, part_numbers)
    rows, reasons = [], []
    for identity, group_of in paired:
        row, why = _row(
            key, group, group_of, part_numbers,
            aligned_on=f"{ALIGNED_IDENTITY}:{identity}",
            missing_from=missing,
        )
        rows.append(row)
        reasons.extend(why)

    left = {part: [c for c in leftover if c.part == part] for part in part_numbers}
    singles = [found[0] for part in part_numbers for found in [left[part]] if len(found) == 1]
    ambiguous = [part for part in part_numbers if len(left[part]) > 1]
    if singles:
        row, why = _row(
            key, group, singles, part_numbers,
            missing_from=missing, ambiguous_in=ambiguous,
        )
        rows.append(row)
        reasons.extend(why)
    unpaired = [c for part in ambiguous for c in left[part]]
    if unpaired:
        reasons.extend(_ambiguous(key, unpaired, part_numbers))
    return rows, reasons


def _pair_by_identity(
    key: str, bucket: Sequence[_Candidate], part_numbers: Sequence[str]
) -> tuple[list[tuple[str, list[_Candidate]]], list[_Candidate]]:
    """Split an ambiguous key into rows sharing a printed identity cell.

    The one widening an ambiguous alignment allows, and the same one the limits
    card allows: a group is made only where the shared cell picks **at most one
    row per part** and reaches **at least two parts**, because a cell matching
    two rows on one side proves nothing about which was meant. Everything else
    is left for the caller to refuse with its values quoted.

    The **key's own cell does not count**. Every row in this bucket carries it —
    that is what made the bucket ambiguous in the first place — so pairing on it
    would be the pairing this rung exists to replace, and it would label the row
    with the one word that cannot tell its rows apart (`TJ` rather than
    `industrial`).
    """
    ignored = normalize(key)
    order: list[str] = []
    by_cell: dict[str, list[_Candidate]] = {}
    for candidate in bucket:
        for cell in sorted(candidate.identity - {ignored}):
            if cell not in by_cell:
                by_cell[cell] = []
                order.append(cell)
            by_cell[cell].append(candidate)

    paired: list[tuple[str, list[_Candidate]]] = []
    used: set[int] = set()
    for cell in order:
        group = [c for c in by_cell[cell] if id(c) not in used]
        parts_hit = [c.part for c in group]
        if len(set(parts_hit)) < 2 or len(parts_hit) != len(set(parts_hit)):
            continue
        paired.append((cell, _in_part_order(group, part_numbers)))
        used.update(id(c) for c in group)
    return paired, [c for c in bucket if id(c) not in used]


def _in_part_order(
    group: Sequence[_Candidate], part_numbers: Sequence[str]
) -> list[_Candidate]:
    """Candidates in the order the caller named their parts."""
    return sorted(group, key=lambda c: part_numbers.index(c.part))


def _row(
    key: str,
    group: str,
    bucket: Sequence[_Candidate],
    part_numbers: Sequence[str],
    *,
    aligned_on: str = "",
    missing_from: Sequence[str] = (),
    ambiguous_in: Sequence[str] = (),
) -> tuple[ComparisonRow, list[str]]:
    """One comparison row and the reasons it could not compare something.

    `missing_from` and `ambiguous_in` are two different findings and stay apart:
    a part that publishes **no** record under this parameter is an absence a
    buyer wants to know about, while a part that publishes several this module
    refused to choose between has said something — just not something that can
    be put in one column.
    """
    cells = _in_part_order(bucket, part_numbers)
    reference = cells[0]
    role = _shared_role(reference, cells[1:])
    row = ComparisonRow(
        key=_display_key(key, reference),
        aligned_on=aligned_on or reference.aligned_on,
        group=group,
        role=role,
        reference=reference.part,
        missing_from=list(missing_from),
        ambiguous_in=list(ambiguous_in),
    )
    reasons: list[str] = []
    for candidate in cells:
        cell = _cell_of(candidate)
        if candidate is not reference:
            delta, reason = _delta(role, reference, candidate)
            cell.delta = delta
            if reason:
                reasons.append(f"{row.key}: {reason}")
        row.cells.append(cell)
    row.citation = "; ".join(
        dict.fromkeys(f"{c.part_number} {c.citation}" for c in row.cells if c.citation)
    )
    notes = []
    if row.missing_from:
        row.flags.append(FLAG_ONLY_IN)
        notes.append(
            f"only in {', '.join(c.part_number for c in row.cells)} — "
            f"{', '.join(row.missing_from)} publishes no record under this parameter"
        )
    if row.ambiguous_in:
        row.flags.append(FLAG_AMBIGUOUS)
        notes.append(
            f"{', '.join(row.ambiguous_in)} prints several rows here that share no "
            f"printed name with these — they are listed under 'not comparable' "
            f"rather than guessed at"
        )
    # A part can be absent from *this* row and still have answered: the printed
    # identity rung splits one key into several rows, and a part's other rows are
    # on the other lines. Saying nothing here would leave a `—` that reads like
    # the `only-in` case, which is a claim about the device rather than about the
    # table.
    covered = {cell.part_number for cell in row.cells}
    elsewhere = [
        part
        for part in part_numbers
        if part not in covered
        and part not in row.missing_from
        and part not in row.ambiguous_in
    ]
    if elsewhere:
        notes.append(
            f"{', '.join(elsewhere)} prints this parameter on another line of "
            f"this table, under a name these rows do not share"
        )
    if not notes and not role:
        notes.append("no delta: the parts state no comparable number in one column")
    row.note = "; ".join(notes)
    return row, reasons


def _display_key(key: str, reference: _Candidate) -> str:
    """The row's heading: the canonical symbol, or the reference's printed name.

    A key the alias lexicon resolved is already a symbol a reader knows (`TJ`);
    a key that is only a normalized printed string is not, so the row shows the
    reference part's own label instead of a lowercased echo of it.
    """
    return key if reference.label_key else (reference.label or key)


def _cell_of(candidate: _Candidate) -> ComparisonCell:
    """One part's column of a row, cited by the retrieval core's own citation."""
    return ComparisonCell(
        part_number=candidate.part,
        label=candidate.label,
        detail=candidate.detail,
        section=candidate.section,
        section_title=candidate.section_title,
        matched_via=candidate.matched_via,
        citation=Citation(
            section=candidate.section,
            page_start=candidate.page,
            page_end=candidate.page,
        ).label,
        values=dict(candidate.values),
    )


def _shared_role(reference: _Candidate, others: Sequence[_Candidate]) -> str:
    """The printed column a delta may be computed on, or `""`.

    One column per row, chosen once: comparing one part's `typ` against
    another's `max` would be a number no reader could check, and letting each
    pair pick its own column would put two different claims in one table.
    """
    for role in ROLE_ORDER:
        left = reference.values.get(role)
        if left is None or left.value_si is None:
            continue
        for other in others:
            right = other.values.get(role)
            if right is not None and right.value_si is not None and right.unit_si == left.unit_si:
                return role
    return ""


def _delta(
    role: str, reference: _Candidate, candidate: _Candidate
) -> tuple[DerivedValue | None, str]:
    """This part's value minus the reference's, or `None` and the reason why.

    Sign convention, stated once: the delta is `candidate − reference`, so a
    positive number means this part states the larger value. It is a **computed**
    value and therefore carries no `verbatim` — no page printed the difference
    between two datasheets — and it cites both operands, because a delta that
    cited one of its two rows would be traceable by exactly half.
    """
    if not role:
        # Two sides that *did* parse the same column in different bases are a
        # different finding from two sides that printed different columns, and
        # a reader chasing a missing delta needs to be told which.
        clash = _base_clash(reference, candidate)
        if clash:
            return None, (
                f"{candidate.part} states its {clash[0]} in a different base than "
                f"{reference.part} ({clash[2] or 'unitless'} against "
                f"{clash[1] or 'unitless'}) — no delta"
            )
        return None, (
            f"{candidate.part} and {reference.part} state no comparable number in "
            f"one printed column ({_printed(reference)} against "
            f"{_printed(candidate)}) — both are published above, verbatim"
        )
    left = reference.values.get(role)
    right = candidate.values.get(role)
    if left is None or right is None or right.value_si is None:
        return None, (
            f"{candidate.part} states no comparable {role} "
            f"({_printed(candidate)}) — no delta against {reference.part}"
        )
    if right.unit_si != left.unit_si:
        return None, (
            f"{candidate.part} states its {role} in a different base than "
            f"{reference.part} ({right.unit_si or 'unitless'} against "
            f"{left.unit_si or 'unitless'}) — no delta"
        )
    return (
        DerivedValue(
            value_si=right.value_si - left.value_si,
            unit_si=left.unit_si,
            source=right.source,
            sources=[left.source],
            page=right.page,
            section=right.section,
            derivation=f"{DERIVATION_DELTA}:{role}",
            confidence=weakest(right.confidence, left.confidence),
        ),
        "",
    )


def _base_clash(
    reference: _Candidate, candidate: _Candidate
) -> tuple[str, str, str] | None:
    """`(role, reference base, candidate base)` for a column both parsed in
    different SI bases, or `None`.

    A volt is not an amp, and 1.8 V against 1800 mA is not a delta of 1798 of
    anything — the whole reason `SI_UNITS` refuses a unit it cannot scale.
    """
    for role in ROLE_ORDER:
        left, right = reference.values.get(role), candidate.values.get(role)
        if left is None or right is None:
            continue
        if left.value_si is None or right.value_si is None:
            continue
        if left.unit_si != right.unit_si:
            return role, left.unit_si, right.unit_si
    return None


def _printed(candidate: _Candidate) -> str:
    """What one part printed for a row, quoted — never summarized away."""
    printed = [
        f"{role} {value.verbatim}"
        for role, value in candidate.values.items()
        if value.verbatim
    ]
    return "; ".join(printed) if printed else "no printed value"


def _ambiguous(
    key: str, leftover: Sequence[_Candidate], part_numbers: Sequence[str]
) -> list[str]:
    """The refusal for a key no shared printed name could pair, plus its values.

    The reason first, then one line per row that was left unpaired, quoting what
    it printed and the page it is on — so a reader can do by eye what this module
    refuses to do by guess.
    """
    counts = ", ".join(
        f"{part} {len([c for c in leftover if c.part == part])}"
        for part in part_numbers
        if any(c.part == part for c in leftover)
    )
    lines = [
        (
            f"uncomparable: {key} — rows under this parameter ({counts}) share no "
            f"printed name; pairing them would be a guess, so all of them are "
            f"listed here instead"
        )
    ]
    for candidate in _in_part_order(leftover, part_numbers):
        page = f"p.{candidate.page}" if candidate.page is not None else "p.?"
        lines.append(
            f"uncomparable: {key} / {candidate.part}: {candidate.label} — "
            f"{_printed(candidate)} ({page})"
        )
    return lines


def _unaddressable(part: str, record: SpecRecord) -> str:
    """The listing line for a row that cannot be cited, so it is never silent."""
    label = record.symbol or record.name or "(unnamed row)"
    page = f"p.{record.page}" if record.page is not None else "p.?"
    return (
        f"{part}: {label} ({page}) has no addressable record id — that corpus "
        f"predates ADR 0005; rebuild it (`dsa build <pdf> --part {part}`)"
    )


def _card_population(card: DesignCard) -> str:
    """`parse_population`'s sentence, for values a card already derived.

    A card row's numbers were parsed when the card was built, so re-parsing the
    printed strings here would measure the same thing twice and could disagree
    with the card the same command prints. What is counted instead is the card's
    own outcome: a row carrying no comparable number cannot enter a delta, and
    invariant 8 says a comparison must say how many of those there were.
    """
    total = len(card.rows)
    if not total:
        return "0 card rows to compare"
    unreadable = sum(1 for row in card.rows if not _has_number(row))
    if not unreadable:
        return f"all {total} card rows state a comparable number"
    return f"{unreadable} of {total} card rows state no comparable number"


def _card_listing(card: DesignCard) -> list[str]:
    """One line per card row that carries no comparable number."""
    lines = []
    for row in card.rows:
        if _has_number(row):
            continue
        printed = "; ".join(
            f"{role} {value.verbatim}" for role, value in row.values.items() if value.verbatim
        )
        page = next((v.page for v in row.values.values() if v.page is not None), None)
        lines.append(
            f"{row.label}: {printed or '(no value printed)'} "
            f"({'p.' + str(page) if page is not None else 'p.?'})"
        )
    return lines


def _has_number(row) -> bool:
    return any(value.value_si is not None for value in row.values.values())


def _empty_reason(parts: Sequence[ComparePart], *, term: str, kind: str) -> str:
    """Why a comparison has no rows — the honestly empty artifact.

    Separates the two absences a reader must not confuse: **no part resolved the
    term at all**, which is a finding about the query, from *some* part resolving
    it while none of the rows it found could be published — which is a finding
    about those rows, and every one of them is listed with what it printed.

    A parameter only one part prints is *not* one of these: it is a row, flagged
    `only-in`, because during part selection that is the answer rather than the
    absence of one.
    """
    found = [p.part_number for p in parts if p.records]
    if not found:
        return (
            f"no comparison for --{kind} {term!r}: none of "
            f"{', '.join(p.part_number for p in parts)} publishes a record that "
            f"resolves it. Try `dsa query --part <PART> --{kind} {term!r}` to see "
            f"what each part does publish"
        )
    n_records = sum(len(p.records) for p in parts)
    return (
        f"no comparison for --{kind} {term!r}: {', '.join(found)} resolve it, but "
        f"none of the {n_records} rows they found could be published — a row with "
        f"no addressable record id cannot be cited (and an uncited value has no "
        f"place on a derived artifact), and a row that printed no value has "
        f"nothing to compare. Each one is listed below with what it printed"
    )
