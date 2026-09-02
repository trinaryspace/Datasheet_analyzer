"""Cross-part comparison — `dsa compare` (phase 6, ticket 09).

The part-selection question, answered in one call: *these two (or five) parts
are candidates; where do they actually differ?* Everything it prints is
already in `specs.json` or on a design card, in two corpora nobody reads side
by side, which is why the question is normally answered by two browser tabs
and a guess.

**It derives one thing: a difference.** `si_delta` is `b - a` over two parsed
numbers in the same base unit, and it is computed *only* where both sides
parsed (invariant 8, clause (b), ADR 0007). Everything else on the table is a
verbatim copy of what each part printed, with the page it was printed on.

Four rules are the ones a reader should test:

**Alignment is stated, never assumed.** Every aligned row records `matched_on`
— the printed identity string, the alias family, or the printed symbol that
put those two rows together — so a mis-alignment is visible on the page rather
than hidden in a join. The join is the same two-rung one `derive/cards.py`
uses for the `limits` card, applied across parts instead of across tables:

1. **printed identity** — a string one part printed as a symbol or a name and
   another printed as either, paired only where it names exactly one free row
   in each part;
2. **alias family** — `TJ` and `Junction temperature` are the same parameter
   because `registry/aliases.yaml` says so, and that is how differently-named
   equivalents line up. A part with no lexicon entry falls back to its printed
   symbol, which still lines `tRESET` up with `tRESET`.

**Ambiguity is refused, not resolved.** `AFE7950` prints sixteen `Pdiss` rows
and `AFE7953` prints twelve, one per operating mode, and the mode names are
not the same. Nothing printed says which pairs with which, so nothing is
paired: every one of those rows is listed with its verbatim value, its page
and its operating mode, under a heading that says why. Pairing them by
position would put a delta between two unrelated modes, which is the worst
thing this command could do — it would look exactly like an answer.

**Nothing is silently dropped.** A parameter one part prints and the other
does not is a row (`only in AFE7950`), because during part selection an absent
parameter *is* the finding. A pair that could not be subtracted — one side
unparseable, or two different units — is a row too, listed under "not
comparable" with both verbatim values, and counted: "3 of 47 aligned value
pair(s) could not be compared". Per-part parse coverage is reported beside it
with the same sentence `structure/quantities.coverage` produces everywhere
else.

**More than two parts is supported, not truncated.** With N parts the first is
the baseline and every other part is deltaed against it, so `dsa compare A B
C` is three columns and two deltas per row. A single part is refused with a
message; a repeated part is refused rather than compared with itself.

`compare_parts` is the seam the MCP `compare_parts` tool sits on;
`cli_compare` is the entry point `cli.py` froze.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from datasheet_analyzer.config import get_settings
from datasheet_analyzer.derive.cards import (
    CardCorpus,
    CardDocument,
    cell_value,
    format_number,
    load_card_corpus,
    load_or_build_card,
)
from datasheet_analyzer.derive.provenance import check_provenance, resolve_source
from datasheet_analyzer.models import (
    CARD_KINDS,
    VALUE_KIND_POINT,
    Card,
    CompareCell,
    CompareDelta,
    CompareRow,
    Confidence,
    DerivedValue,
    SpecRecord,
)
from datasheet_analyzer.structure.aliases import AliasEntry, AliasLexicon, load_lexicon, padded
from datasheet_analyzer.structure.quantities import ParseCoverage, coverage

log = logging.getLogger(__name__)

#: This module publishes no file; the version rides on the `--json` payload so
#: an agent that stores a comparison can tell which rules produced it.
COMPARE_SCHEMA_VERSION = "1"

#: The one derivation rule this module owns (invariant 8, clause (b)): the
#: difference between two parsed values in the same base unit, `b - a`.
DERIVATION_DELTA = "si_delta"

#: The record cells a spec-mode comparison lines up, in render order. A card
#: comparison uses whatever columns the card itself filled.
SPEC_CELLS: tuple[str, ...] = ("min", "typ", "max", "value")

#: How a row was aligned. Recorded per row so a mis-alignment is impossible to
#: produce silently — the reader can always see what matched.
MATCH_IDENTITY = "printed identity"
MATCH_FAMILY = "alias family"
MATCH_SYMBOL = "printed symbol"

#: `(join key, aligned_on)` for one spec record — an **additive** override of
#: the alias-resolved key `dsa compare` normally joins on (phase 7, ticket 07).
#:
#: It exists for the family index, whose members are one vendor's one document
#: template published for several devices: there the identity that survives is
#: the row exactly as printed inside the section it was printed in, and
#: resolving it through the alias lexicon would collapse `IVDD1P8` and
#: `IVDD1P2` onto one key and then refuse them both as ambiguous. The second
#: element replaces the row's `matched_on` sentence, because a caller holding a
#: stronger identity than the lexicon is also the only one that can say in
#: words what it matched on.
#:
#: Everything downstream of the key is unchanged — the four join rungs, the
#: exactly-one-free-row-per-part rule, the refusal of an ambiguous key, the
#: delta, the parse population. One alignment engine, two artifacts.
SpecKeyFn = Callable[[SpecRecord], tuple[str, str]]

#: What became of a row.
STATUS_ALIGNED = "aligned"  # every part has exactly one row for this key
STATUS_PARTIAL = "partial"  # some parts have it, at least one does not
STATUS_ONLY_IN = "only-in"  # exactly one part has it at all
STATUS_AMBIGUOUS = "ambiguous"  # several parts have several rows; nothing pairs them

#: Machine-readable row flags.
FLAG_ONLY_IN = "only-in-one-part"
FLAG_AMBIGUOUS = "ambiguous-alignment"
FLAG_IDENTICAL = "identical"
FLAG_DIFFERS = "differs"

#: Row ordering: what is comparable leads, what is missing follows, what could
#: not be aligned comes last with its reason.
_STATUS_ORDER = (STATUS_ALIGNED, STATUS_PARTIAL, STATUS_ONLY_IN, STATUS_AMBIGUOUS)

_CONFIDENCE_ORDER = (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW, Confidence.UNKNOWN)

__all__ = [
    "COMPARE_SCHEMA_VERSION",
    "DERIVATION_DELTA",
    "CompareCell",
    "CompareCoverage",
    "CompareDelta",
    "CompareRow",
    "Comparison",
    "PartCoverage",
    "SpecKeyFn",
    "audit_comparison",
    "cli_compare",
    "compare_cards",
    "compare_parts",
    "compare_specs",
    "render_comparison",
    "resolve_symbol_query",
    "si_delta",
]


# --- the comparison, as data ------------------------------------------------


class CompareCoverage(BaseModel):
    """How much of what lined up could actually be subtracted.

    `considered` counts the (row, column) pairs where **both** sides printed
    something — the population a delta was possible for. `compared` counts the
    ones that became a number. The difference is listed in `reasons`, with
    both verbatim values, so a short delta table can never read as a complete
    one.
    """

    considered: int = 0
    compared: int = 0
    reasons: list[str] = Field(default_factory=list)

    @property
    def uncompared(self) -> int:
        return len(self.reasons)

    def describe(self, *, limit: int = 20) -> str:
        if not self.considered:
            return "no aligned value pair printed a value on both sides"
        if not self.reasons:
            return f"all {self.considered} aligned value pair(s) compared"
        head = (
            f"{self.uncompared} of {self.considered} aligned value pair(s) could not be "
            f"compared, listed below:"
        )
        lines = "\n".join(f"  - {r}" for r in self.reasons[:limit])
        if self.uncompared > limit:
            lines += f"\n  - ... and {self.uncompared - limit} more"
        return f"{head}\n{lines}"


class PartCoverage(BaseModel):
    """One part's parse coverage over the records that entered the comparison.

    The same sentence `structure/quantities.coverage` produces everywhere
    else — "3 of 47 rows could not be parsed, listed below" — carried on the
    comparison so a consumer of the JSON gets it too, not just a reader of the
    table.
    """

    part_number: str = ""
    considered: int = 0
    parsed: int = 0
    unparsed: list[str] = Field(default_factory=list)

    @property
    def unparsed_count(self) -> int:
        return len(self.unparsed)

    def describe(self, *, limit: int = 20) -> str:
        if not self.considered:
            return f"{self.part_number}: no selected row printed a value to parse"
        if not self.unparsed:
            return f"{self.part_number}: all {self.considered} selected row(s) parsed"
        head = (
            f"{self.part_number}: {self.unparsed_count} of {self.considered} selected row(s) "
            f"could not be parsed, listed below:"
        )
        lines = "\n".join(f"  - {u}" for u in self.unparsed[:limit])
        if self.unparsed_count > limit:
            lines += f"\n  - ... and {self.unparsed_count - limit} more"
        return f"{head}\n{lines}"

    @classmethod
    def from_coverage(cls, part: str, parsed: ParseCoverage) -> PartCoverage:
        return cls(
            part_number=part,
            considered=parsed.considered,
            parsed=parsed.parsed,
            unparsed=[cell.describe() for cell in parsed.unparsed],
        )


class Comparison(BaseModel):
    """Everything `dsa compare` found, as one document.

    An empty `rows` is an honest answer and not an error: two parts that share
    no parameter under any of the join's rungs have nothing to compare, and
    saying so is different from failing.
    """

    schema_version: str = COMPARE_SCHEMA_VERSION
    parts: list[str] = Field(default_factory=list)
    baseline: str = ""  # `parts[0]`: what every delta is measured against
    mode: str = ""  # "specs" or "card"
    card: str = ""  # the card compared, when mode is "card"
    symbol: str = ""  # the `--symbol` query, verbatim
    resolved_symbol: str = ""  # what the alias lexicon turned it into, "" when nothing
    rows: list[CompareRow] = Field(default_factory=list)
    coverage: CompareCoverage = Field(default_factory=CompareCoverage)
    parse_coverage: list[PartCoverage] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def rows_with(self, status: str) -> list[CompareRow]:
        return [row for row in self.rows if row.status == status]

    @property
    def aligned(self) -> list[CompareRow]:
        """Rows every part contributed to — the ones a delta is possible for."""
        return self.rows_with(STATUS_ALIGNED)

    @property
    def delta_count(self) -> int:
        return sum(len(row.deltas) for row in self.rows)

    def summary(self) -> str:
        counts = {status: len(self.rows_with(status)) for status in _STATUS_ORDER}
        return (
            f"{counts[STATUS_ALIGNED]} aligned row(s), {counts[STATUS_PARTIAL]} partial, "
            f"{counts[STATUS_ONLY_IN]} present in one part only, "
            f"{counts[STATUS_AMBIGUOUS]} not aligned; {self.delta_count} delta(s) computed"
        )


# --- candidates -------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    """One row of one part, ready to be joined against the other parts'."""

    part: str
    label: str
    symbol: str
    identities: tuple[str, ...]
    family: str  # the rung-2 join key: alias family, else normalized symbol
    alias: str  # the alias family alone, "" when the lexicon claims nothing
    note: str
    conditions: str
    page: int | None
    order: tuple[str, int, int]
    values: dict[str, DerivedValue]
    #: What put this row's key together, in words, when a `SpecKeyFn` supplied
    #: it. Empty for every row `dsa compare` builds, which is what keeps
    #: `_matched_on`'s four sentences exactly as they were.
    aligned_on: str = ""

    def cell(self) -> CompareCell:
        return CompareCell(
            part_number=self.part,
            label=self.label,
            symbol=self.symbol,
            note=self.note,
            conditions=self.conditions,
            page=self.page,
            values=dict(self.values),
        )

    def cite(self) -> str:
        where = f"p.{self.page}" if self.page else "no page"
        printed = "; ".join(
            f"{cell} {value.verbatim!r}" for cell, value in self.values.items() if value.filled
        )
        return f"{self.part} {self.label or self.symbol} ({printed or 'nothing printed'}, {where})"


def _identities(*texts: str) -> tuple[str, ...]:
    """The printed strings a row may be joined on, normalized and deduplicated.

    Both the symbol and the name, because vendors disagree about which column
    holds which and the layout floor records whichever the datasheet printed.
    """
    return tuple(sorted({padded(text).strip() for text in texts if text and text.strip()}))


def _family_of(lexicon: AliasLexicon, symbol: str, name: str) -> tuple[str, str]:
    """`(join key, alias family)` for one row's printed symbol and name."""
    entry = lexicon.entry_for(symbol, name)
    alias = entry.symbol if entry is not None else ""
    return alias or padded(symbol).strip() or padded(name).strip(), alias


def resolve_symbol_query(query: str, lexicon: AliasLexicon) -> tuple[AliasEntry | None, str]:
    """Resolve a `--symbol` query through the alias lexicon.

    Returns the entry and how it was reached, or `(None, "")` when the lexicon
    knows nothing about the query — which is not a failure: the selector falls
    back to matching the query against what each part printed, and the
    comparison says which of the two happened.
    """
    text = (query or "").strip()
    if not text:
        return None, ""
    entry = lexicon.by_symbol(text)
    if entry is not None:
        return entry, f"alias lexicon entry {entry.symbol}"
    prefixes = lexicon.prefix_hits(text)
    if prefixes:
        return prefixes[0][0], f"prefix family {prefixes[0][1]}"
    phrases = lexicon.phrase_hits(text)
    if phrases:
        return phrases[0][0], f"alias phrase {phrases[0][1]!r}"
    return None, ""


def _selected(symbol: str, entry: AliasEntry | None, alias: str, text: str) -> bool:
    """Whether a row answers a `--symbol` query.

    Two ways in, both exact: the lexicon claims the row for the queried family,
    or the query appears as a whole word in what the row printed. The second
    rung is what keeps a symbol the lexicon has never heard of answerable.
    """
    if not symbol:
        return True
    if entry is not None and alias and alias == entry.symbol:
        return True
    return padded(symbol) in padded(text)


def _spec_candidates(
    corpus: CardCorpus,
    part: str,
    lexicon: AliasLexicon,
    *,
    symbol: str = "",
    entry: AliasEntry | None = None,
    key_for: SpecKeyFn | None = None,
) -> tuple[list[_Candidate], list[SpecRecord], int]:
    """Every published spec record of one part that printed a value.

    Returns the candidates, the records they came from (for parse coverage)
    and how many matching records could not be cited so that the citation
    resolves back to them — refused rather than compared under another row's
    id, the same rule the design cards apply.

    `key_for` (additive, phase 7 ticket 07) replaces the alias-resolved join
    key with one the caller computed, and nothing else: the row still
    carries what it printed, still has to be citable, and still goes through
    the same four rungs and the same refusals.
    """
    candidates: list[_Candidate] = []
    records: list[SpecRecord] = []
    uncitable = 0
    for doc in corpus.documents:
        for position, record in enumerate(doc.records):
            key, alias = _family_of(lexicon, record.symbol, record.name)
            if not _selected(symbol, entry, alias, f"{record.symbol} {record.name}"):
                continue
            values = _record_values(doc, record, position)
            if values is None:
                uncitable += 1
                records.append(record)
                continue
            if not values:
                continue
            records.append(record)
            identities = _identities(record.symbol, record.name)
            aligned_on = ""
            if key_for is not None:
                # One key, offered at every rung, so the caller's identity
                # is the only thing that can pair two rows: an alias family
                # the caller did not ask for must not widen the join behind
                # it.
                key, aligned_on = key_for(record)
                identities, alias = (key,), ""
            candidates.append(
                _Candidate(
                    part=part,
                    label=record.name or record.symbol,
                    symbol=record.symbol or record.name,
                    identities=identities,
                    family=key,
                    alias=alias,
                    note=corpus.section_title(record.section, doc.doc_hash),
                    conditions=record.conditions,
                    page=record.page,
                    order=(record.section, record.table_index, record.row_index),
                    values=values,
                    aligned_on=aligned_on,
                )
            )
    return candidates, records, uncitable


def _record_values(
    doc: CardDocument, record: SpecRecord, position: int
) -> dict[str, DerivedValue] | None:
    """One record's printed cells as citable values; `None` when uncitable."""
    if not doc.can_cite(position, record):
        return None
    source = doc.spec_source(record)
    values: dict[str, DerivedValue] = {}
    for cell in SPEC_CELLS:
        value = cell_value(record, cell, source=source)
        if value is not None:
            values[cell] = value
    return values


def _card_candidates(
    card: Card,
    part: str,
    lexicon: AliasLexicon,
    *,
    symbol: str = "",
    entry: AliasEntry | None = None,
) -> list[_Candidate]:
    """Every row of one part's card, ready to join against another part's."""
    candidates: list[_Candidate] = []
    for index, row in enumerate(card.rows):
        key, alias = _family_of(lexicon, row.symbol, row.label)
        if not _selected(symbol, entry, alias, f"{row.symbol} {row.label}"):
            continue
        filled = [value for value in row.values.values() if value.filled]
        candidates.append(
            _Candidate(
                part=part,
                label=row.label or row.symbol,
                symbol=row.symbol or row.label,
                identities=_identities(row.symbol, row.label),
                family=key,
                alias=alias,
                note=row.note,
                conditions="",
                page=next((value.page for value in filled if value.page), None),
                order=("", 0, index),
                values=dict(row.values),
            )
        )
    return candidates


# --- the join ---------------------------------------------------------------


@dataclass
class _Aligned:
    """A key, what matched on it, and the one row each part contributed."""

    key: str
    matched_on: str
    picks: dict[str, _Candidate] = field(default_factory=dict)


#: The join, most specific rung first. Each entry is `(basis, qualified)`:
#: `basis` names what the key is made of and `qualified` says whether the
#: printed conditions are part of it. A rung only ever pairs a key that names
#: **exactly one free row in each part that has it**, so a more specific rung
#: can never be less correct than a coarser one — it can only pair more.
_RUNGS: tuple[tuple[str, bool], ...] = (
    (MATCH_IDENTITY, True),
    (MATCH_IDENTITY, False),
    (MATCH_FAMILY, True),
    (MATCH_FAMILY, False),
)


def _keys(candidate: _Candidate, basis: str, qualified: bool) -> tuple[str, ...]:
    """The join keys one candidate offers at one rung."""
    keys = candidate.identities if basis == MATCH_IDENTITY else (candidate.family,)
    if not qualified:
        return tuple(key for key in keys if key)
    conditions = padded(candidate.conditions).strip()
    if not conditions:
        # Nothing printed to qualify by. The row is not skipped — the very
        # next rung joins on the identity alone — but it must not enter a
        # conditions bucket keyed by the empty string, where every other
        # unqualified row of every other parameter would join it.
        return ()
    return tuple(f"{key} @ {conditions}" for key in keys if key)


def _index(
    candidates: Iterable[_Candidate], basis: str, qualified: bool
) -> dict[str, dict[str, list[_Candidate]]]:
    """`{join key: {part: [candidate]}}` at one rung of the join."""
    index: dict[str, dict[str, list[_Candidate]]] = {}
    for candidate in candidates:
        for value in _keys(candidate, basis, qualified):
            index.setdefault(value, {}).setdefault(candidate.part, []).append(candidate)
    return index


def _join(
    parts: Sequence[str], candidates: Sequence[_Candidate]
) -> tuple[list[_Aligned], list[_Candidate], dict[int, str]]:
    """Align rows across parts. Returns `(aligned, leftovers, ambiguity reasons)`.

    Four rungs, every one of them exact, none of them ever guessing. A rung
    pairs a key only where it names **exactly one still-free row in each part
    that has it**, and at least two parts have it:

    1. **printed identity + printed conditions** — the same parameter measured
       under the same stated conditions. A datasheet that sweeps one parameter
       across seven frequencies prints the frequency in the conditions column,
       and that column is what tells one row from the next six;
    2. **printed identity** — a string one part printed as a symbol or a name
       and another printed as either;
    3. **alias family + conditions**, then
    4. **alias family** — `TJ` against `Junction temperature`, because
       `registry/aliases.yaml` says they are the same parameter. A row the
       lexicon does not claim falls back to its own printed symbol.

    Whatever is still free afterwards is returned unpaired. A key several
    parts print several rows under is left unpaired *with a recorded reason*:
    sixteen operating modes against twelve operating modes is a pairing the
    datasheet made and this tool did not read, and inventing one would put a
    delta between two unrelated measurements.
    """
    used: set[int] = set()
    aligned: list[_Aligned] = []
    ambiguous: dict[int, str] = {}

    for basis, qualified in _RUNGS:
        index = _index((c for c in candidates if id(c) not in used), basis, qualified)
        for key in sorted(index):
            picks: dict[str, _Candidate] = {}
            collisions: dict[str, int] = {}
            for part in parts:
                free = [c for c in index[key].get(part, ()) if id(c) not in used]
                if len(free) > 1:
                    collisions[part] = len(free)
                elif free:
                    picks[part] = free[0]
            if collisions:
                if len(collisions) + len(picks) >= 2:
                    _mark_ambiguous(index[key], parts, used, ambiguous, key, basis, qualified)
                continue
            if len(picks) < 2:
                continue
            used.update(id(c) for c in picks.values())
            aligned.append(
                _Aligned(key=key, matched_on=_matched_on(basis, key, qualified, picks), picks=picks)
            )

    leftovers = [c for c in candidates if id(c) not in used]
    return aligned, leftovers, ambiguous


def _matched_on(basis: str, key: str, qualified: bool, picks: dict[str, _Candidate]) -> str:
    """What put these rows together, in words a reader can check on the page.

    A caller that supplied its own key (`SpecKeyFn`) supplied the sentence
    too, and it wins: only that caller knows what its key means. Every row
    `dsa compare` builds carries an empty `aligned_on` and reaches the four
    sentences below unchanged.
    """
    sample = next(iter(picks.values()))
    if sample.aligned_on:
        return sample.aligned_on
    where = " and conditions" if qualified else ""
    if basis == MATCH_IDENTITY:
        return f"{MATCH_IDENTITY}{where} {key!r}"
    if sample.alias:
        printed = ", ".join(f"{part} prints {c.symbol!r}" for part, c in sorted(picks.items()))
        return f"{MATCH_FAMILY}{where} {sample.alias} ({printed})"
    return f"{MATCH_SYMBOL}{where} {key!r}"


def _mark_ambiguous(
    bucket: dict[str, list[_Candidate]],
    parts: Sequence[str],
    used: set[int],
    ambiguous: dict[int, str],
    key: str,
    basis: str,
    qualified: bool,
) -> None:
    """Record why a multiply-printed key was left unaligned, on every row of it."""
    counts = {
        part: len([c for c in bucket.get(part, ()) if id(c) not in used])
        for part in parts
        if any(id(c) not in used for c in bucket.get(part, ()))
    }
    what = f"{basis} and conditions" if qualified else basis
    reason = (
        f"{', '.join(f'{n} row(s) in {p}' for p, n in counts.items())} share the "
        f"{what} {key!r} and nothing printed says which pairs with which"
    )
    for rows in bucket.values():
        for candidate in rows:
            if id(candidate) not in used:
                ambiguous.setdefault(id(candidate), reason)


# --- the one derived value --------------------------------------------------


def _scalar(value: DerivedValue, cell: str) -> float | None:
    """The single number a column asserts, or `None` when it parsed to none.

    A cell that printed a range in a `max` column (`-40 to 125`) asserts its
    top; every other column asserts the number itself. The same rule
    `structure/quantities.annotate_record` applies, for the same reason.
    """
    if value.value_si is None:
        return None
    if cell == "max" and value.value_si_hi is not None:
        return value.value_si_hi
    return value.value_si


def si_delta(a: DerivedValue, b: DerivedValue, cell: str) -> tuple[float, str] | None:
    """`(b - a, unit)` in the base unit both parsed to, or `None`.

    The documented pure function behind `si_delta`. `None` — never a guess —
    when either side did not parse to a number, or when the two numbers are
    not in the same unit: `1.35 A` and `1350 mA` are the same quantity and
    subtract cleanly, `150 degC` and `150 W` do not.
    """
    left, right = _scalar(a, cell), _scalar(b, cell)
    if left is None or right is None:
        return None
    if a.unit_si != b.unit_si:
        return None
    return right - left, a.unit_si


def _weaker(*grades: Confidence) -> Confidence:
    """The least trustworthy grade — how a value computed from two is graded."""
    known = [g for g in grades if g in _CONFIDENCE_ORDER]
    if not known:
        return Confidence.UNKNOWN
    return max(known, key=_CONFIDENCE_ORDER.index)


def _delta_verbatim(delta: float, unit: str) -> str:
    sign = "+" if delta > 0 else ""
    return f"{sign}{format_number(delta)} {unit}".strip()


def _delta(
    baseline: _Candidate, other: _Candidate, cell: str
) -> tuple[CompareDelta | None, str | None]:
    """One column of one row compared; the second element is a stated reason.

    Exactly one of the two is ever non-`None`: a pair either becomes a delta
    or becomes a sentence saying why it did not.
    """
    a, b = baseline.values.get(cell), other.values.get(cell)
    if a is None or b is None or not a.filled or not b.filled:
        missing = baseline.part if a is None or not a.filled else other.part
        printed = other.part if missing == baseline.part else baseline.part
        return None, (
            f"{baseline.label or baseline.symbol} [{cell}]: {printed} printed a value and "
            f"{missing} printed none — nothing to subtract"
        )
    computed = si_delta(a, b, cell)
    if computed is None:
        return None, (
            f"{baseline.label or baseline.symbol} [{cell}]: {baseline.part} {a.verbatim!r} "
            f"(p.{a.page}) and {other.part} {b.verbatim!r} (p.{b.page}) did not both parse to "
            f"a number in the same unit"
        )
    delta, unit = computed
    return (
        CompareDelta(
            cell=cell,
            baseline=baseline.part,
            part_number=other.part,
            value=DerivedValue(
                verbatim=_delta_verbatim(delta, unit),
                value_si=delta,
                unit_si=unit,
                value_kind=VALUE_KIND_POINT,
                source=b.source,
                page=b.page,
                derivation=DERIVATION_DELTA,
                confidence=_weaker(a.confidence, b.confidence),
            ),
            baseline_source=a.source,
            baseline_page=a.page,
        ),
        None,
    )


def _cells_of(sides: Iterable[dict[str, DerivedValue]]) -> list[str]:
    """Every column any side of this row filled, in a stable render order."""
    seen = {cell for values in sides for cell in values}
    ordered = [cell for cell in SPEC_CELLS if cell in seen]
    ordered.extend(sorted(cell for cell in seen if cell not in SPEC_CELLS))
    return ordered


# --- building rows ----------------------------------------------------------


def _aligned_row(
    group: _Aligned, parts: Sequence[str], coverage_acc: CompareCoverage
) -> CompareRow:
    """One aligned parameter, with a delta wherever both sides parsed."""
    baseline_part = parts[0]
    present = [p for p in parts if p in group.picks]
    missing = [p for p in parts if p not in group.picks]
    baseline = group.picks.get(baseline_part)
    deltas: list[CompareDelta] = []
    reasons: list[str] = []

    if baseline is not None:
        for other_part in present[1:]:
            other = group.picks[other_part]
            for cell in _cells_of(c.values for c in group.picks.values()):
                a, b = baseline.values.get(cell), other.values.get(cell)
                if a is None or b is None or not a.filled or not b.filled:
                    _, reason = _delta(baseline, other, cell)
                    if reason:
                        reasons.append(reason)
                    continue
                coverage_acc.considered += 1
                delta, reason = _delta(baseline, other, cell)
                if delta is not None:
                    coverage_acc.compared += 1
                    deltas.append(delta)
                elif reason:
                    coverage_acc.reasons.append(reason)
                    reasons.append(reason)
    else:
        reasons.append(
            f"the baseline part {baseline_part} does not print this parameter; no delta is "
            f"measured against a part that never stated it"
        )

    anchor = baseline or group.picks[present[0]]
    flags: list[str] = []
    if missing:
        flags.append(FLAG_ONLY_IN if len(present) == 1 else "missing-from-some")
    if deltas:
        flags.append(FLAG_IDENTICAL if all(d.value.value_si == 0 for d in deltas) else FLAG_DIFFERS)
    status = STATUS_ALIGNED if not missing else STATUS_PARTIAL
    return CompareRow(
        key=group.key,
        label=anchor.label,
        symbol=anchor.alias or anchor.symbol,
        matched_on=group.matched_on,
        status=status,
        cells={part: candidate.cell() for part, candidate in group.picks.items()},
        deltas=deltas,
        present_in=present,
        missing_from=missing,
        not_comparable=reasons,
        flags=flags,
    )


def _leftover_row(
    candidate: _Candidate, parts: Sequence[str], reason: str, others: Sequence[str]
) -> CompareRow:
    """One row nothing lined up with — never dropped, always explained."""
    ambiguous = bool(reason)
    if not reason:
        absent = ", ".join(p for p in parts if p != candidate.part)
        reason = (
            f"only in {candidate.part}: nothing published by {absent} names this parameter "
            f"under any join rung"
        )
    return CompareRow(
        key=candidate.family or candidate.label,
        label=candidate.label,
        symbol=candidate.alias or candidate.symbol,
        matched_on=reason,
        status=STATUS_AMBIGUOUS if ambiguous else STATUS_ONLY_IN,
        cells={candidate.part: candidate.cell()},
        deltas=[],
        present_in=[candidate.part],
        missing_from=list(others),
        not_comparable=[f"{candidate.cite()} — {reason}"],
        flags=[FLAG_AMBIGUOUS] if ambiguous else [FLAG_ONLY_IN],
    )


def _sort_key(row: CompareRow) -> tuple[int, str, str]:
    rank = _STATUS_ORDER.index(row.status) if row.status in _STATUS_ORDER else len(_STATUS_ORDER)
    return rank, row.key, row.label


def _build(
    parts: Sequence[str],
    candidates: Sequence[_Candidate],
) -> tuple[list[CompareRow], CompareCoverage]:
    """Join, compare and account for every candidate exactly once."""
    aligned, leftovers, ambiguous = _join(parts, candidates)
    acc = CompareCoverage()
    rows = [_aligned_row(group, parts, acc) for group in aligned]
    for candidate in leftovers:
        others = [p for p in parts if p != candidate.part]
        rows.append(_leftover_row(candidate, parts, ambiguous.get(id(candidate), ""), others))
    rows.sort(key=_sort_key)
    return rows, acc


# --- the two front doors ----------------------------------------------------


def _resolve_parts(
    parts: Sequence[str], parts_dir: Path | None = None
) -> tuple[list[tuple[str, Path]], str]:
    """`([(part, dir)], "")` for named parts, or `([], reason)`.

    Refuses fewer than two parts and a repeated part rather than comparing
    something with itself; more than two is a supported comparison and is
    never truncated to the first two.
    """
    from datasheet_analyzer.projects import is_built
    from datasheet_analyzer.retrieve.scope import no_corpus_error

    settings = get_settings()
    root = Path(parts_dir) if parts_dir is not None else settings.parts_dir
    named = [p.strip() for p in parts if p and p.strip()]
    if len(named) < 2:
        return [], (
            "dsa compare needs at least two parts — a comparison of one part against "
            "nothing is a `dsa card` or a `dsa specs` query"
        )
    duplicates = sorted({p for p in named if named.count(p) > 1})
    if duplicates:
        return [], (
            f"dsa compare: {', '.join(duplicates)} named more than once; every column has to "
            f"be a different part or the deltas are zero by construction"
        )
    resolved: list[tuple[str, Path]] = []
    for part in named:
        if not is_built(part, root):
            return [], no_corpus_error(part, settings=settings)
        resolved.append((part, root / part))
    return resolved, ""


def compare_specs(
    parts: Sequence[tuple[str, Path]],
    *,
    symbol: str = "",
    lexicon: AliasLexicon | None = None,
    key_for: SpecKeyFn | None = None,
) -> Comparison:
    """Compare parts' published spec records, optionally filtered to one symbol.

    `key_for` is the family index's hook (`SpecKeyFn`): it replaces the join
    key and the row's `matched_on` sentence and touches nothing else.
    `dsa compare` never passes one.
    """
    aliases = lexicon or load_lexicon()
    entry, how = resolve_symbol_query(symbol, aliases)
    names = [part for part, _dir in parts]
    candidates: list[_Candidate] = []
    parse_coverage: list[PartCoverage] = []
    warnings: list[str] = []
    unresolved: list[str] = []

    for part, part_dir in parts:
        corpus = load_card_corpus(part_dir, part)
        found, records, uncitable = _spec_candidates(
            corpus, part, aliases, symbol=symbol, entry=entry, key_for=key_for
        )
        candidates.extend(found)
        parse_coverage.append(PartCoverage.from_coverage(part, coverage(records)))
        if not records:
            unresolved.append(
                f"{part}: no published spec record matched"
                + (f" the symbol {symbol!r}" if symbol else "")
                + " — either this part publishes no trusted tables or the symbol is not in it"
            )
        if uncitable:
            warnings.append(
                f"{part}: {uncitable} matching record(s) could not be cited so that the "
                f"citation resolves back to them; they are left out rather than compared "
                f"under another row's id"
            )
    if symbol and entry is None:
        warnings.append(
            f"the alias lexicon has no entry for {symbol!r}; rows were selected by matching "
            f"the query against what each part printed, so an equivalent parameter under a "
            f"different name will not have been selected"
        )
        nearest = aliases.nearest_names(symbol)
        if nearest:
            warnings.append("closest lexicon entries: " + ", ".join(nearest))

    rows, acc = _build(names, candidates)
    return Comparison(
        parts=names,
        baseline=names[0] if names else "",
        mode="specs",
        symbol=symbol,
        resolved_symbol=how,
        rows=rows,
        coverage=acc,
        parse_coverage=parse_coverage,
        unresolved=unresolved,
        warnings=warnings,
    )


def compare_cards(
    parts: Sequence[tuple[str, Path]],
    kind: str,
    *,
    symbol: str = "",
    lexicon: AliasLexicon | None = None,
    write: bool = True,
) -> Comparison:
    """Compare one design card across parts, row by row.

    The card is built through `derive.cards.load_or_build_card`, so the rows
    compared here are the same rows `dsa card` prints and carry the citations
    that card already resolved.
    """
    aliases = lexicon or load_lexicon()
    entry, how = resolve_symbol_query(symbol, aliases)
    names = [part for part, _dir in parts]
    candidates: list[_Candidate] = []
    unresolved: list[str] = []
    warnings: list[str] = []

    for part, part_dir in parts:
        card = load_or_build_card(part_dir, part, kind, write=write)
        candidates.extend(_card_candidates(card, part, aliases, symbol=symbol, entry=entry))
        unresolved.extend(f"{part}: {line}" for line in card.unresolved)
        warnings.extend(f"{part}: {line}" for line in card.warnings)
        if card.is_empty:
            unresolved.append(
                f"{part}: the {kind} card is empty — this part publishes nothing the card's "
                f"selectors claim, so every row below is one-sided"
            )

    rows, acc = _build(names, candidates)
    return Comparison(
        parts=names,
        baseline=names[0] if names else "",
        mode="card",
        card=kind,
        symbol=symbol,
        resolved_symbol=how,
        rows=rows,
        coverage=acc,
        parse_coverage=[],
        unresolved=unresolved,
        warnings=warnings,
    )


def compare_parts(
    parts: Sequence[str],
    *,
    symbol: str = "",
    card: str = "",
    parts_dir: Path | None = None,
    write: bool = True,
) -> tuple[Comparison | None, str]:
    """`(comparison, "")` for named parts, or `(None, reason)`.

    The seam the MCP `compare_parts` tool and `cli_compare` both sit on:
    nothing here prints, raises or exits — how a refusal reaches a user is the
    front end's decision.
    """
    resolved, reason = _resolve_parts(parts, parts_dir)
    if reason:
        return None, reason
    if card and card not in CARD_KINDS:
        return None, f"dsa compare: unknown card {card!r}; expected one of {', '.join(CARD_KINDS)}"
    if card:
        return compare_cards(resolved, card, symbol=symbol, write=write), ""
    return compare_specs(resolved, symbol=symbol), ""


# --- the invariant-8 walk ---------------------------------------------------


def _iter_values(comparison: Comparison) -> Iterator[tuple[str, str, DerivedValue]]:
    """`(part, path, value)` for every `DerivedValue` on a comparison.

    The part is what makes the walk resolvable: a comparison's citations point
    into several corpora, and each has to be resolved against its own.
    """
    for index, row in enumerate(comparison.rows):
        for part, cell in row.cells.items():
            for key, value in cell.values.items():
                yield part, f"rows[{index}]({row.label}).cells[{part}].values[{key}]", value
        for position, delta in enumerate(row.deltas):
            yield (
                delta.part_number,
                f"rows[{index}]({row.label}).deltas[{position}]({delta.cell})",
                delta.value,
            )


def audit_comparison(
    comparison: Comparison, part_dirs: dict[str, Path], *, library_dir: Path | None = None
) -> list[str]:
    """Resolve every value on a comparison back to the record and page it cites.

    The structural half is `derive/provenance.check_provenance` — one
    implementation of invariant 8, shared with every other derived artifact.
    The resolution half is per part, because a comparison is the one derived
    artifact whose citations span corpora. Empty is a pass.
    """
    problems = list(check_provenance(comparison))
    cache: dict[tuple[str, str], object] = {}
    for part, path, value in _iter_values(comparison):
        if not value.filled:
            continue
        root = part_dirs.get(part)
        if root is None:
            problems.append(f"{path}: no corpus directory given for {part!r}")
            continue
        key = (part, value.source)
        if key not in cache:
            cache[key] = resolve_source(value.source, roots=[root], library_dir=library_dir)
        found = cache[key]
        if found is None:
            problems.append(f"{path}: source {value.source!r} resolves to no record in {part}")
            continue
        page = getattr(found, "page", None)
        if page is not None and value.page is not None and page != value.page:
            problems.append(
                f"{path}: cites p.{value.page} but {value.source} is printed on p.{page}"
            )
    # A delta cites one side; the other half has to resolve too or the row is
    # only half-traceable, which is exactly what this walk exists to catch.
    for index, row in enumerate(comparison.rows):
        for position, delta in enumerate(row.deltas):
            root = part_dirs.get(delta.baseline)
            path = f"rows[{index}]({row.label}).deltas[{position}]({delta.cell}).baseline"
            if not delta.baseline_source:
                problems.append(f"{path}: computed delta names no baseline source")
            elif root is not None and resolve_source(delta.baseline_source, roots=[root]) is None:
                problems.append(
                    f"{path}: baseline source {delta.baseline_source!r} resolves to no record "
                    f"in {delta.baseline}"
                )
    return problems


# --- rendering --------------------------------------------------------------


def _escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _cell_text(cell: CompareCell | None, column: str) -> str:
    """One part's printed value for one column, with the page it is printed on."""
    if cell is None:
        return "— *not printed*"
    value = cell.values.get(column)
    if value is None or not value.filled:
        reason = value.null_reason if value is not None else ""
        return f"— *{_escape(reason)}*" if reason else "—"
    page = f" (p.{value.page})" if value.page else ""
    return f"{_escape(value.verbatim)}{page}"


def _delta_text(row: CompareRow, part: str, column: str) -> str:
    for delta in row.deltas:
        if delta.part_number == part and delta.cell == column:
            return _escape(delta.value.verbatim)
    return "—"


def _table(comparison: Comparison, rows: Sequence[CompareRow]) -> list[str]:
    """One markdown line per (row, column) — the shape a designer reads."""
    parts = comparison.parts
    baseline = comparison.baseline
    others = [p for p in parts if p != baseline]
    header = ["Parameter", "Symbol", "Limit", *parts]
    header.extend(f"Δ {p}" for p in others)
    header.append("Matched on")
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows:
        columns = _cells_of(cell.values for cell in row.cells.values())
        for column in columns or ["value"]:
            cells = [_cell_text(row.cells.get(part), column) for part in parts]
            deltas = [_delta_text(row, part, column) for part in others]
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape(row.label),
                        _escape(row.symbol),
                        column,
                        *cells,
                        *deltas,
                        _escape(row.matched_on),
                    ]
                )
                + " |"
            )
    return lines


def render_comparison(comparison: Comparison) -> str:
    """The comparison as markdown: what lined up, what did not, and why.

    Every section is unconditional. A comparison with nothing in a section
    says the section is empty rather than omitting it, because a missing
    "not comparable" heading and an empty one mean opposite things.
    """
    parts = " vs ".join(comparison.parts)
    lines = [f"# Compare: {parts}", ""]
    scope = f"card `{comparison.card}`" if comparison.mode == "card" else "published spec records"
    lines.append(
        f"Comparing {scope}; baseline **{comparison.baseline}** (every Δ is *part* − *baseline*)."
    )
    if comparison.symbol:
        resolved = comparison.resolved_symbol or "no alias-lexicon entry; matched on printed text"
        lines.append(f"Symbol filter: `{comparison.symbol}` → {resolved}.")
    lines.extend(["", comparison.summary(), ""])

    for status, heading, blurb in (
        (STATUS_ALIGNED, "Compared", "Every part printed this parameter."),
        (
            STATUS_PARTIAL,
            "Present in some parts",
            "At least one part printed this parameter and at least one did not.",
        ),
        (
            STATUS_ONLY_IN,
            "Only in one part",
            "An absent parameter is itself a finding during part selection.",
        ),
        (
            STATUS_AMBIGUOUS,
            "Not aligned",
            (
                "Several rows share a join key and nothing printed says which pairs with "
                "which. They are listed as printed; no delta is invented."
            ),
        ),
    ):
        rows = comparison.rows_with(status)
        # The blurb describes what the section holds, so it is only true when the
        # section holds something. Printing "Every part printed this parameter."
        # under "## Compared (0)" states the opposite of what was measured.
        lines.append(f"## {heading} ({len(rows)})")
        lines.append("")
        if rows:
            lines.extend([blurb, ""])
            lines.extend(_table(comparison, rows))
        else:
            lines.append("*(none)*")
        lines.append("")

    lines.extend(["## Not comparable", "", comparison.coverage.describe(), ""])
    if comparison.parse_coverage:
        lines.extend(["## Parse coverage", ""])
        for part in comparison.parse_coverage:
            lines.extend([part.describe(), ""])
    if comparison.unresolved:
        lines.extend(["## Unresolved", ""])
        lines.extend(f"- {line}" for line in comparison.unresolved)
        lines.append("")
    if comparison.warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {line}" for line in comparison.warnings)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --- CLI --------------------------------------------------------------------


def cli_compare(args: argparse.Namespace) -> int:
    """`dsa compare A B [--symbol S | --card power] [--json]`.

    Exit codes match the other deterministic lookups: 0 when something lined
    up, 1 when nothing did — an honest answer, printed with the reason — and 2
    for a scope this command refuses to guess at.
    """
    comparison, reason = compare_parts(
        list(getattr(args, "parts", []) or []),
        symbol=(getattr(args, "symbol", "") or "").strip(),
        card=(getattr(args, "card", "") or "").strip(),
    )
    if comparison is None:
        print(reason, file=sys.stderr)
        return 2
    if getattr(args, "json", False):
        print(json.dumps(json.loads(comparison.model_dump_json()), ensure_ascii=False, indent=2))
    else:
        print(render_comparison(comparison))
    return 0 if comparison.rows else 1
