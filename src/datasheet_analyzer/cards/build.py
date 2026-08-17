"""Records -> design cards: the datasheet reorganised around a design task.

Phase 6, ticket 07. Every card here is a **view**: it owns no value, it selects
rows that `specs.json` and `pins.json` already published, and it says of every
number where it came from. That is ADR 0005 / invariant 8 in one module —
nothing is written to a card that is not

- **(a)** a cell copied verbatim from a spec record (`copy_cell`), possibly with
  the additive SI reading beside it (`+parse_quantity+si_normalize`);
- **(b)** a value computed from records by a documented pure function here — the
  largest of a parameter's printed values (`max_over_rows`), a margin between two
  tables (`abs_max-recommended_max`), a count of pins sharing a name
  (`pins_by_name+count`);
- **(c)** a structural label from `registry/cards.yaml` (which group a row is in,
  recorded on the row as its `selector`).

Four rules govern the whole module.

**A computed value has no verbatim.** A margin was printed on no page, so its
`verbatim` stays empty and its number lives in `value_si` / `unit_si`. Rendering
a margin into a string and storing it as verbatim would claim the datasheet said
something it did not.

**An empty card is a valid card.** A part with no interface section gets an
interface card that states what was looked for and not found. Not a fabricated
one, and not a missing file that reads as "not built yet" — that is the ADR's
own worked example of this clause.

**Arithmetic reports its unparsed population.** The two places this module
compares numbers — the `reduce: max` groups and the limits join — run
`quantities.parse_population` and publish its sentence plus one line per row it
could not read. Dropping those rows from the decision silently is a defect, not
a tidy-up (invariant 8, and `AGENTS.md` names the helper).

**An ambiguous join is refused, not resolved.** When a parameter has several
abs-max rows or several recommended rows, the pair is listed as uncomparable
with the counts. AFE7950 prints three supply-voltage ranges on its abs-max table
and three rails on its recommended table; choosing a pairing between them would
compute a margin for a 0.9 V rail against a 1.8 V rating, which is worse than
publishing no margin at all.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

from datasheet_analyzer.cards.lexicon import (
    KIND_PINS,
    REDUCE_MAX,
    ROLES,
    CardGroup,
    CardLexicon,
    CardSpec,
    LimitsJoin,
    load_card_lexicon,
)
from datasheet_analyzer.config import CARD_VERSION, CARDS_SCHEMA_VERSION
from datasheet_analyzer.models import (
    CardRow,
    DerivedValue,
    DesignCard,
    PinRecord,
    PinSet,
    SpecRecord,
    SpecSet,
)
from datasheet_analyzer.provenance import (
    PINS_ARTIFACT,
    SPECS_ARTIFACT,
    source_ref,
)
from datasheet_analyzer.structure.aliases import normalize
from datasheet_analyzer.structure.confidence import weakest
from datasheet_analyzer.structure.quantities import (
    Quantity,
    parse_population,
    parse_quantity,
)

log = logging.getLogger(__name__)

#: The rule names a card's `DerivedValue`s record (invariant 8's `derivation`).
DERIVATION_CELL = "copy_cell"
DERIVATION_CELL_SI = "copy_cell+parse_quantity+si_normalize"
DERIVATION_MARGIN = "abs_max-recommended_max"
DERIVATION_PIN_COUNT = "pins_by_name+count"
#: Named on a row rather than on a value: it selected *which row*, not the number.
DERIVATION_REDUCE_MAX = "max_over_rows"

#: The keys a limits row publishes.
ROLE_ABS_MAX = "abs_max"
ROLE_RECOMMENDED_MAX = "recommended_max"
ROLE_MARGIN = "margin"

#: The limits join is a card table like any other, and names itself the same way.
GROUP_LIMITS = "Absolute maximum against recommended operating"

#: Row flags a reader must not miss.
FLAG_ZERO_MARGIN = "zero-margin"
FLAG_OVER_ABS_MAX = "recommended-exceeds-abs-max"

#: Two scaled values count as equal at this relative tolerance. Scaling is a
#: multiplication (1850 mV -> 1.85 V), so two genuinely identical printed limits
#: can differ in the last bit of a double; an exact `==` would miss the very
#: zero-margin hazard this card exists to flag. Nine digits is far tighter than
#: any datasheet states a limit to.
MARGIN_EQUAL_REL_TOL = 1e-9

#: How many pin designators a pin row names before it points at `pins.json`.
PIN_LISTING_LIMIT = 8


@dataclass(frozen=True)
class CardDoc:
    """One document's published records, as a card builder consumes them.

    Deliberately not a `CorpusIndex` or a `RawDocument`: a card is derived from
    *published* records, and both callers have those — the publisher holds the
    sets it is about to write, and `Retriever` holds the ones it read back off
    disk. One shape for both is what makes "the card on disk is the card the CLI
    prints" a testable statement rather than a hope.

    `name` is the corpus document directory (`datasheet-a1b2c3d4`), which is what
    a fully qualified `source` reference names.
    """

    name: str
    specs: tuple[SpecRecord, ...] = ()
    pins: tuple[PinRecord, ...] = ()

    @classmethod
    def of(
        cls, name: str, specset: SpecSet | None = None, pinset: PinSet | None = None
    ) -> CardDoc:
        """A `CardDoc` from the sets the publish stage is writing."""
        return cls(
            name=name,
            specs=tuple(specset.records) if specset else (),
            pins=tuple(pinset.pins) if pinset else (),
        )


def card_docs(index: object) -> list[CardDoc]:
    """The documents of a loaded corpus (`CorpusIndex`), as card input.

    Takes the index structurally rather than by type so `cards/` never imports
    the retrieval core: `IndexedDoc` already carries exactly the three fields a
    card needs.
    """
    return [
        CardDoc(name=doc.name, specs=tuple(doc.specs), pins=tuple(doc.pins))
        for doc in index.docs
    ]


def build_cards(
    part_number: str,
    docs: Sequence[CardDoc],
    *,
    card_version: str = CARD_VERSION,
    lexicon: CardLexicon | None = None,
) -> list[DesignCard]:
    """Every card the lexicon declares, in lexicon order."""
    lexicon = load_card_lexicon() if lexicon is None else lexicon
    return [
        _build(spec, part_number, docs, card_version=card_version, lexicon=lexicon)
        for spec in lexicon.cards
    ]


def build_card(
    name: str,
    part_number: str,
    docs: Sequence[CardDoc],
    *,
    card_version: str = CARD_VERSION,
    lexicon: CardLexicon | None = None,
) -> DesignCard | None:
    """One card by name, or `None` when the lexicon declares no such card.

    `None` is "there is no such card", which a caller must be able to tell from
    "that card is empty for this part" — the second is a `DesignCard` with an
    `empty_reason`, and conflating them would report a typo as a finding about
    the datasheet.
    """
    lexicon = load_card_lexicon() if lexicon is None else lexicon
    spec = lexicon.card(name)
    if spec is None:
        return None
    return _build(spec, part_number, docs, card_version=card_version, lexicon=lexicon)


def _build(
    spec: CardSpec,
    part_number: str,
    docs: Sequence[CardDoc],
    *,
    card_version: str,
    lexicon: CardLexicon,
) -> DesignCard:
    """Build one declared card over one part's documents."""
    card = DesignCard(
        schema_version=CARDS_SCHEMA_VERSION,
        card=spec.name,
        title=spec.title,
        purpose=spec.purpose,
        part_number=part_number,
        card_version=card_version,
    )
    for group in spec.groups:
        if group.kind == KIND_PINS:
            _pin_group(card, group, docs)
        else:
            _spec_group(card, group, docs, lexicon=lexicon)
    if spec.join is not None:
        _limits(card, spec.join, docs, lexicon=lexicon)
    if not card.rows:
        card.empty_reason = _empty_reason(spec, docs)
    return card


# --- spec groups -----------------------------------------------------------


def _spec_group(
    card: DesignCard, group: CardGroup, docs: Sequence[CardDoc], *, lexicon: CardLexicon
) -> None:
    """Append one group's rows (and its honesty report) to the card."""
    claimed: list[tuple[CardDoc, SpecRecord, str]] = [
        (doc, record, selector)
        for doc in docs
        for record, selector in (
            (r, group.claims(r, aliases=lexicon.aliases)) for r in doc.specs
        )
        if selector and not _is_heading_row(record, group)
    ]
    if not claimed:
        return
    if group.reduce == REDUCE_MAX:
        _reduced_rows(card, group, claimed)
        return
    for doc, record, selector in claimed:
        row = _row(doc, record, group, selector)
        if row is not None:
            card.rows.append(row)
        else:
            card.unparsed.append(_unaddressable(record, group))


def _reduced_rows(
    card: DesignCard, group: CardGroup, claimed: list[tuple[CardDoc, SpecRecord, str]]
) -> None:
    """One row per parameter: the printed row stating the largest value.

    A datasheet states a rail's current once per operating configuration — the
    reference part prints 16 — and a designer sizing a regulator wants the
    largest, cited to the configuration that states it. So this is a comparison,
    and it reports its population: the sentence goes in `notes`, one line per row
    that could not be parsed goes in `unparsed`, and every published row says how
    many values it was the largest of.

    A parameter whose rows *none* parse is still published, from its first
    printed row, with a note saying so: "no comparable value" is a reason to show
    the row unranked, not a reason to drop the parameter off the card.
    """
    order: list[tuple[str, str]] = []
    buckets: dict[tuple[str, str], list[tuple[CardDoc, SpecRecord, str]]] = {}
    for entry in claimed:
        key = (entry[1].symbol, entry[1].name)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(entry)

    population = parse_population(record for _doc, record, _sel in claimed)
    card.notes.append(
        f"{group.title}: {len(order)} parameters from {len(claimed)} printed rows — "
        f"the largest value stated for each; {population.describe()}."
    )
    card.unparsed.extend(f"{group.id}: {line}" for line in population.listing())

    for key in order:
        bucket = buckets[key]
        ranked = [
            (ceiling, entry)
            for entry, ceiling in ((e, _row_ceiling(e[1], group)) for e in bucket)
            if ceiling is not None
        ]
        if ranked:
            _ceiling, (doc, record, selector) = max(ranked, key=lambda pair: pair[0])
            note = (
                f"largest of {len(bucket)} printed values for this parameter"
                if len(bucket) > 1
                else ""
            )
        else:
            doc, record, selector = bucket[0]
            note = (
                f"no value among the {len(bucket)} printed rows for this parameter "
                f"could be parsed — this is the first of them, unranked"
                if len(bucket) > 1
                else "the printed value could not be parsed"
            )
        row = _row(doc, record, group, f"{selector}+{DERIVATION_REDUCE_MAX}", note=note)
        if row is not None:
            card.rows.append(row)
        else:
            card.unparsed.append(_unaddressable(record, group))


def _row(
    doc: CardDoc,
    record: SpecRecord,
    group: CardGroup,
    selector: str,
    *,
    note: str = "",
) -> CardRow | None:
    """One card row from one spec record, or `None` when it is unaddressable.

    A record with no `id` cannot be cited (a corpus published before ADR 0005),
    and an uncited value has no business on a card — the caller lists it instead.
    """
    if not record.id:
        return None
    values = {
        role: value
        for role, value in ((r, _cell(doc, record, r)) for r in group.roles)
        if value is not None
    }
    if not values:
        return None
    return CardRow(
        group=group.title,
        label=record.symbol or record.name,
        # The row's own test conditions travel with it: a datasheet states one
        # parameter several times under different conditions (AFE7950 prints
        # three SerDes bit rates), and a card that showed three identical labels
        # would look like a duplicate rather than like the choice it is.
        detail=" · ".join(
            text
            for text in (record.name if record.symbol else "", record.conditions)
            if text.strip()
        ),
        section=record.section,
        section_title=record.section_title,
        selector=f"{group.id}+{selector}",
        values=values,
        note=note,
    )


def _cell(doc: CardDoc, record: SpecRecord, role: str) -> DerivedValue | None:
    """One printed cell in its provenance envelope, or `None` when it is empty.

    `verbatim` is the cell as printed *plus the row's printed unit*, which is the
    shape ADR 0005's own example gives (`"1350 mA"`): a value quoted without its
    unit is the one way this artifact could mislead a reader who trusts it. The
    SI pair beside it is the additive numeric layer and is allowed to be absent.
    """
    cell = getattr(record, role, "").strip()
    if not cell:
        return None
    unit = record.unit.verbatim or record.unit.canonical
    quantity = parse_quantity(cell, unit)
    return DerivedValue(
        verbatim=f"{cell} {unit}".strip(),
        value_si=_scalar(quantity),
        unit_si=quantity.unit_si if quantity else "",
        source=source_ref(record.id, artifact=SPECS_ARTIFACT, doc=doc.name),
        page=record.page,
        section=record.section,
        derivation=DERIVATION_CELL_SI if quantity else DERIVATION_CELL,
        confidence=record.confidence,
    )


def _scalar(quantity: Quantity | None) -> float | None:
    """The single comparable number a parsed cell states, or `None`.

    A point states one; a tolerance states its magnitude; a **bound** states the
    side it printed (`< 5` is a ceiling of 5); a **range** states no single
    number at all, and a range printed in a `max` column is therefore not a
    ceiling this module will compare — it stays unparsed, honestly, rather than
    silently becoming one of its endpoints.
    """
    if quantity is None:
        return None
    if quantity.value_si is not None:
        return quantity.value_si
    low, high = quantity.span
    if low is not None and high is None:
        return low
    if high is not None and low is None:
        return high
    return None


def _row_ceiling(record: SpecRecord, group: CardGroup) -> float | None:
    """The largest number this row states in the group's columns, or `None`.

    The ranking key for `reduce: max`. Deliberately the row's own maximum rather
    than one named column: a datasheet states a rail's draw as a typical in one
    table and as a min/max pair in another, and "the most current this row says
    the rail takes" is the same question in both.
    """
    hint = record.unit.verbatim or record.unit.canonical
    numbers = [
        scalar
        for scalar in (
            _scalar(parse_quantity(getattr(record, role, ""), hint)) for role in group.roles
        )
        if scalar is not None
    ]
    return max(numbers) if numbers else None


def _is_heading_row(record: SpecRecord, group: CardGroup) -> bool:
    """Whether this row is a spanning table heading rather than a parameter.

    A `<th colspan>` heading inside a parametric table flattens into a row whose
    every cell repeats the heading text (`CML SerDes Inputs [8:1]SRX+/-` in the
    symbol, the min, the typ and the max), and the layout floor's group headings
    print a symbol with no values at all. Neither is a parameter, so neither is a
    card row: they are the table's own furniture, still verbatim in `specs.json`
    where they belong.
    """
    cells = [getattr(record, role, "").strip() for role in group.roles]
    printed = [cell for cell in cells if cell]
    if not printed:
        return True
    label = (record.symbol or record.name).strip()
    return bool(label) and all(cell == label for cell in printed)


def _unaddressable(record: SpecRecord, group: CardGroup) -> str:
    """The listing line for a row that cannot be cited, so it is never silent."""
    label = record.symbol or record.name or "(unnamed row)"
    page = f"p.{record.page}" if record.page is not None else "p.?"
    return (
        f"{group.id}: {label} ({page}) has no addressable record id — this corpus "
        f"predates ADR 0005; rebuild it"
    )


# --- pin groups ------------------------------------------------------------


def _pin_group(card: DesignCard, group: CardGroup, docs: Sequence[CardDoc]) -> None:
    """One row per pin *name* of the wanted types, with how many pins share it.

    A power card that listed AD9081's 85 supply pins one by one would be a pin
    table, not a card; what a designer needs here is "which supplies exist and
    how many balls each one has". The count is a documented pure function over
    records (`pins_by_name+count`) and cites **every** record it counted, so the
    invariant-8 walk resolves all of them rather than one and a promise.
    """
    order: list[tuple[str, str]] = []
    buckets: dict[tuple[str, str], list[tuple[CardDoc, PinRecord]]] = {}
    for doc in docs:
        for pin in doc.pins:
            if pin.type not in group.pin_types or not pin.id:
                continue
            key = (pin.name, pin.type.value)
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append((doc, pin))
    for key in order:
        bucket = buckets[key]
        refs = [
            source_ref(pin.id, artifact=PINS_ARTIFACT, doc=doc.name) for doc, pin in bucket
        ]
        first = bucket[0][1]
        designators = [pin.pin for _doc, pin in bucket]
        shown = designators[:PIN_LISTING_LIMIT]
        listing = ", ".join(shown)
        if len(designators) > len(shown):
            listing += f", … (+{len(designators) - len(shown)} more in pins.json)"
        card.rows.append(
            CardRow(
                group=group.title,
                label=key[0] or "(unnamed pin)",
                detail=key[1],
                section=first.section,
                selector=f"{group.id}+pin_type:{key[1]}",
                values={
                    "pins": DerivedValue(
                        value_si=float(len(bucket)),
                        source=refs[0],
                        sources=refs[1:],
                        page=first.page,
                        section=first.section,
                        derivation=DERIVATION_PIN_COUNT,
                        confidence=first.confidence,
                    )
                },
                note=f"designators: {listing}",
            )
        )


# --- the limits join -------------------------------------------------------


def _limits(
    card: DesignCard, join: LimitsJoin, docs: Sequence[CardDoc], *, lexicon: CardLexicon
) -> None:
    """Join the abs-max and recommended tables, and compute the headroom.

    The card that earns its keep alone: the two tables are pages apart, and a
    parameter whose recommended maximum *is* its absolute maximum has no
    headroom at all — a genuine design hazard that is invisible when they are
    read separately.

    The join key is the **alias-resolved** symbol, because the two tables rarely
    name a parameter the same way (TI's abs-max table prints `Supply Voltage
    Range` in the symbol column and the rail names beside it, while its
    recommended table prints the rail as the symbol). A row the alias lexicon
    does not claim keys on its own printed symbol, so a parameter both tables
    spell identically still joins.
    """
    if not join.usable:
        return
    abs_side = _side(docs, join, abs_max=True)
    rec_side = _side(docs, join, abs_max=False)
    if not abs_side and not rec_side:
        return

    # Invariant 8's honesty half, per side: what the numeric layer could read of
    # the column being compared, and one line for every row it could not.
    for label, side in (("absolute maximum", abs_side), ("recommended operating", rec_side)):
        population = parse_population(
            (record for _doc, record in side), role=join.role
        )
        card.notes.append(f"{label} {join.role}: {population.describe()}.")
        card.unparsed.extend(f"{label}: {line}" for line in population.listing())

    abs_by_key = _by_key(abs_side, lexicon=lexicon)
    rec_by_key = _by_key(rec_side, lexicon=lexicon)
    keys = list(abs_by_key) + [k for k in rec_by_key if k not in abs_by_key]

    compared = considered = 0
    for key in keys:
        # A pair may be *published* (both printed sides, cited) and still not
        # comparable, so rows and reasons are independent: the rows go on the
        # card, the reasons go in the listing, and only a row carrying a margin
        # counts as compared.
        rows, reasons = _limit_rows(key, abs_by_key.get(key, []), rec_by_key.get(key, []), join)
        card.rows.extend(rows)
        card.unparsed.extend(f"uncomparable: {key} — {reason}" for reason in reasons)
        compared += sum(1 for row in rows if ROLE_MARGIN in row.values)
        considered += len(rows) + len(reasons)
    card.notes.append(
        f"limits: {compared} of {considered} parameter pairs have a computed "
        f"margin; {considered - compared} could not be compared and are listed "
        f"below."
    )


def _side(
    docs: Sequence[CardDoc], join: LimitsJoin, *, abs_max: bool
) -> list[tuple[CardDoc, SpecRecord]]:
    """Every non-heading row printed on one side's table(s)."""
    return [
        (doc, record)
        for doc in docs
        for record in doc.specs
        if join.side(record, abs_max=abs_max) and not _is_limits_heading(record)
    ]


def _is_limits_heading(record: SpecRecord) -> bool:
    """A row with no identity at all is furniture, not a parameter.

    Unlike `_is_heading_row` this looks at every value column, not at a group's:
    the join has no group, and a row printing nothing anywhere is still reported
    as uncomparable rather than dropped — it is the *unnamed* rows that are
    furniture.
    """
    label = (record.symbol or record.name).strip()
    if not label:
        return True
    printed = [
        cell
        for cell in (getattr(record, role, "").strip() for role in ROLES)
        if cell
    ]
    return bool(printed) and all(cell == label for cell in printed)


def _by_key(
    side: list[tuple[CardDoc, SpecRecord]], *, lexicon: CardLexicon
) -> dict[str, list[tuple[CardDoc, SpecRecord]]]:
    """Group one side's rows by alias-resolved symbol, in printed order."""
    out: dict[str, list[tuple[CardDoc, SpecRecord]]] = {}
    for doc, record in side:
        entry = lexicon.aliases.entry_for(record.symbol, record.name)
        key = entry.symbol if entry is not None else (record.symbol or record.name).strip()
        out.setdefault(key, []).append((doc, record))
    return out


def _limit_rows(
    key: str,
    abs_rows: list[tuple[CardDoc, SpecRecord]],
    rec_rows: list[tuple[CardDoc, SpecRecord]],
    join: LimitsJoin,
) -> tuple[list[CardRow], list[str]]:
    """The rows and the refusals one join key produces.

    Every refusal is a *reason*, never a silence: a parameter on one table only,
    a parameter either table states no maximum for, an ambiguous many-to-many
    join, a value the numeric layer could not read, and two values in units that
    do not share a base all end up in the card's `unparsed` listing.

    One key can produce several rows. A datasheet states one rating per rail and
    an alias family covers all of them, so `VDD` arrives here as three rows
    against three — and the only pairing this module will make is between rows
    whose *printed identity is the same string* (see `_pair_by_identity`).
    Anything left over is refused as ambiguous, because a margin computed
    between a 0.9 V rail and a 1.8 V rating is worse than no margin at all.
    """
    abs_stated = [(doc, r) for doc, r in abs_rows if getattr(r, join.role, "").strip()]
    rec_stated = [(doc, r) for doc, r in rec_rows if getattr(r, join.role, "").strip()]
    if not abs_rows:
        return [], [
            f"printed only on the recommended operating table ({len(rec_rows)} row(s))"
        ]
    if not rec_rows:
        return [], [
            f"printed only on the absolute maximum table ({len(abs_rows)} row(s))"
        ]
    if not abs_stated:
        return [], [f"the absolute maximum table states no {join.role} for it"]
    if not rec_stated:
        return [], [f"the recommended operating table states no {join.role} for it"]

    one_to_one = len(abs_stated) == 1 and len(rec_stated) == 1
    if one_to_one:
        pairs, left_abs, left_rec = [(abs_stated[0], rec_stated[0])], [], []
    else:
        pairs, left_abs, left_rec = _pair_by_identity(abs_stated, rec_stated)

    rows: list[CardRow] = []
    reasons: list[str] = []
    for (abs_doc, abs_rec), (rec_doc, rec_rec) in pairs:
        # A key that arrived with several rows a side names *which* of them this
        # row is: three rails all key on `VDD`, and a card row labelled `VDD`
        # three times says nothing about which rail has the headroom.
        label = key if one_to_one else f"{key} — {_pair_label(abs_rec, rec_rec)}"
        row, reason = _compare(label, (abs_doc, abs_rec), (rec_doc, rec_rec), join)
        if row is not None:
            rows.append(row)
        if reason:
            reasons.append(reason)
    if left_abs or left_rec:
        reasons.append(
            f"ambiguous join: {len(left_abs)} absolute maximum row(s) and "
            f"{len(left_rec)} recommended row(s) carry it under no shared printed "
            f"name — pairing them would be a guess"
        )
    return rows, reasons


def _pair_by_identity(
    abs_stated: list[tuple[CardDoc, SpecRecord]],
    rec_stated: list[tuple[CardDoc, SpecRecord]],
) -> tuple[
    list[tuple[tuple[CardDoc, SpecRecord], tuple[CardDoc, SpecRecord]]],
    list[tuple[CardDoc, SpecRecord]],
    list[tuple[CardDoc, SpecRecord]],
]:
    """Pair rows of one key that print the *same identity cell*; leave the rest.

    The rung that rescues the case an alias family creates. TI's abs-max table
    prints `Supply Voltage Range` in the symbol column and the rail list beside
    it (`DVDD0P9, VDDT0P9`), and its recommended table prints that same rail list
    *as* the symbol — so the two rows share a printed cell, character for
    character. That is a fact about the page, not an inference about it, which is
    what makes it the only widening this join allows.

    A pairing is made only when it is **unique on both sides**: a cell matching
    two rows opposite proves nothing about which was meant, and both stay
    unpaired for the caller to refuse as ambiguous.
    """
    matches: dict[int, list[int]] = {}
    for i, (_doc, abs_rec) in enumerate(abs_stated):
        abs_cells = _identity_cells(abs_rec)
        matches[i] = [
            j
            for j, (_rdoc, rec_rec) in enumerate(rec_stated)
            if abs_cells & _identity_cells(rec_rec)
        ]
    pairs = []
    used_abs: set[int] = set()
    used_rec: set[int] = set()
    for i, js in matches.items():
        if len(js) != 1:
            continue
        j = js[0]
        if sum(1 for other in matches.values() if other == [j]) != 1:
            continue
        pairs.append((abs_stated[i], rec_stated[j]))
        used_abs.add(i)
        used_rec.add(j)
    return (
        pairs,
        [row for i, row in enumerate(abs_stated) if i not in used_abs],
        [row for j, row in enumerate(rec_stated) if j not in used_rec],
    )


def _identity_cells(record: SpecRecord) -> set[str]:
    """The printed strings that name this row, normalized for comparison.

    The symbol and the name as separate cells, never joined: the whole point is
    that one table's *name* cell can be another table's *symbol* cell.
    """
    return {
        normalize(text)
        for text in (record.symbol, record.name)
        if normalize(text)
    }


def _pair_label(abs_rec: SpecRecord, rec_rec: SpecRecord) -> str:
    """The printed cell two paired rows share, for the row's label."""
    shared = _identity_cells(abs_rec) & _identity_cells(rec_rec)
    for text in (abs_rec.name, abs_rec.symbol, rec_rec.symbol, rec_rec.name):
        if normalize(text) in shared:
            return text
    return rec_rec.symbol or rec_rec.name


def _compare(
    label: str,
    abs_side: tuple[CardDoc, SpecRecord],
    rec_side: tuple[CardDoc, SpecRecord],
    join: LimitsJoin,
) -> tuple[CardRow | None, str]:
    """One paired parameter: the row, and the reason it has no margin, if any."""
    abs_doc, abs_rec = abs_side
    rec_doc, rec_rec = rec_side
    abs_value = _cell(abs_doc, abs_rec, join.role)
    rec_value = _cell(rec_doc, rec_rec, join.role)
    if abs_value is None or rec_value is None:
        return None, "one side has no addressable record id — rebuild this corpus"

    key = label
    row = CardRow(
        group=GROUP_LIMITS,
        label=key,
        detail=_limits_detail(abs_rec, rec_rec),
        section=rec_rec.section,
        section_title=rec_rec.section_title,
        selector=f"limits+join:{join.role}",
        values={ROLE_ABS_MAX: abs_value, ROLE_RECOMMENDED_MAX: rec_value},
    )
    if abs_value.value_si is None or rec_value.value_si is None:
        unread = "absolute maximum" if abs_value.value_si is None else "recommended"
        reason = (
            f"the {unread} value could not be read as a number "
            f"({abs_value.verbatim!r} against {rec_value.verbatim!r}); both are "
            f"published on the card, verbatim"
        )
        row.note = f"no margin: {reason}"
        return row, reason
    if abs_value.unit_si != rec_value.unit_si:
        reason = (
            f"the two sides are stated in units with different bases "
            f"({abs_value.unit_si or 'unitless'} against "
            f"{rec_value.unit_si or 'unitless'})"
        )
        row.note = f"no margin: {reason}"
        return row, reason

    margin = abs_value.value_si - rec_value.value_si
    # Assigned into the row's own dict, not into the one passed to the
    # constructor: pydantic copies a mapping at validation, so a later mutation
    # of the input would silently never reach the published card.
    row.values[ROLE_MARGIN] = DerivedValue(
        value_si=margin,
        unit_si=abs_value.unit_si,
        # The margin is a property of the recommended limit — how much room it
        # leaves — so that is its primary source; the rating it was measured
        # against is the other operand and is cited beside it. Both resolve.
        source=rec_value.source,
        sources=[abs_value.source],
        page=rec_value.page,
        section=rec_value.section,
        derivation=DERIVATION_MARGIN,
        confidence=weakest(abs_value.confidence, rec_value.confidence),
    )
    if margin < 0 and not math.isclose(margin, 0.0, rel_tol=MARGIN_EQUAL_REL_TOL,
                                       abs_tol=0.0):
        row.flags.append(FLAG_OVER_ABS_MAX)
        row.note = (
            "the recommended maximum is above the absolute maximum — read both "
            "printed pages before trusting either"
        )
    elif math.isclose(
        abs_value.value_si, rec_value.value_si, rel_tol=MARGIN_EQUAL_REL_TOL, abs_tol=0.0
    ):
        row.flags.append(FLAG_ZERO_MARGIN)
        row.note = (
            "no headroom: the recommended maximum is the absolute maximum, so any "
            "overshoot is out of specification"
        )
    return row, ""


def _limits_detail(abs_rec: SpecRecord, rec_rec: SpecRecord) -> str:
    """How the two tables named this parameter, when they named it differently."""
    names = [
        text
        for text in dict.fromkeys(
            [(abs_rec.name or abs_rec.symbol).strip(), (rec_rec.name or rec_rec.symbol).strip()]
        )
        if text
    ]
    return " / ".join(names)


# --- empty cards -----------------------------------------------------------


def _empty_reason(spec: CardSpec, docs: Sequence[CardDoc]) -> str:
    """Why this card has no rows — the ADR's "honestly empty card".

    Says what was looked for, and separates the two absences a reader must not
    confuse: a corpus with no records at all (nothing was searched) from one
    whose records simply do not carry this card's parameters (searched, absent).
    """
    n_specs = sum(len(doc.specs) for doc in docs)
    n_pins = sum(len(doc.pins) for doc in docs)
    if not n_specs and not n_pins:
        return (
            f"no {spec.name} card: this corpus publishes no spec or pin records at "
            f"all, so nothing was searched (a degraded-backend document publishes "
            f"none)"
        )
    wanted = [group.wanted() for group in spec.groups]
    if spec.join is not None:
        wanted.append(
            f"join: rows printed under "
            f"{', '.join(repr(t) for t in spec.join.abs_max_titles)} against "
            f"{', '.join(repr(t) for t in spec.join.recommended_titles)}"
        )
    looked = "; ".join(wanted)
    return (
        f"no {spec.name} card: none of this part's {n_specs} spec records and "
        f"{n_pins} pin records matched what this card selects ({looked}). Nothing "
        f"here is missing from the datasheet — it is absent from what was "
        f"extracted, or the datasheet prints it under wording the lexicon does "
        f"not know yet (registry/cards.yaml)"
    )
