"""Register bit fields — the field table as citable records, or nothing at all.

Phase 6, ticket 06, and the most dangerous artifact in this repo. A register's
bit fields are what a driver is written against: `NCO_EN` at bit 3 is a line of
firmware, and if this module publishes bit 3 when the page printed bit 4, the
firmware compiles, runs, and silently misconfigures silicon. Nothing else the
corpus emits fails that quietly. **Wrong bit positions are worse than absent
ones**, so every rule below is written to refuse rather than approximate, and
the ticket that commissioned this module explicitly permitted it to ship
nothing.

It ships something, and here is exactly what and why.

Two printed shapes exist, and both are read here:

- **the bit column** (`Bit | Field | Type | Reset | Description`, one row per
  field with the range printed as text — `15:3`, `2`, `0`). This is what the
  reference document prints, on every one of its 35 registers, and it is read
  through the device-table abstraction (`structure/device_tables.py`, kind
  `bitfield`) exactly as a pin table and a register summary are: identify → map
  columns → validate → emit. The one thing this module insists on beyond that
  is that the table's **own header row** declared its `Bit` and `Field`
  columns. The positional fallback is refused here — for a pin table a wrong
  column costs a description, for a field table it costs the bit range.
- **the bit diagram**: a bit-position header row (`7 6 5 4 3 2 1 0`) with field
  names in the row beneath, each spanning the columns of the bits it occupies.
  There the range is *not* in the cell text at all — it is the geometry — so it
  is derived from the header row's cell boundaries: a field cell's bits are the
  bit numbers of the header columns its span covers (`bit_header_span`). A
  field cell outside those columns, or a header row that is not a descending
  run, refuses the whole table. One reading of that geometry is stated rather
  than assumed: **an empty column continues the field to its left**, because
  that is what a cell spanning four bit columns looks like once the layout floor
  has reduced it to text in the band its words start in. Columns *before* the
  first named cell continue nothing and are reported as unaccounted.

Four rules make a published field set trustworthy, and each is a refusal:

1. **A register width, or no fields.** A field list that cannot be checked
   against the register's width is unverifiable by construction, so the width
   has to be read from something printed: the register's own reset word
   (`[Reset = 0x0000]` → four hex digits → 16 bits) or, for a diagram, its bit
   header row. A register with neither publishes `fields: []` and says so.
2. **No overlap, no overflow.** Two fields claiming one bit, or a field
   claiming a bit the register does not have, rejects the register's **whole**
   field set with a recorded reason. Measured: the reference document's own R90
   table prints `15:8` and then `15:0`, which is a typo in the datasheet — and
   the corpus refuses to publish either field rather than pick one.
3. **Coverage is published, not assumed.** Bits of the register that no field
   claims are listed in `unaccounted_bits`, so "does this field list cover the
   register?" is answerable by reading the artifact instead of trusting it.
   `RESERVED` ranges are fields like any other — the document printed them, and
   dropping them is what would make a gap invisible.
4. **A register is never dropped for having no readable fields.** It keeps its
   summary record, `fields: []`, and `fields_reason`. A firmware engineer who
   greps for a register must find it and be told what is missing.

Nothing here mutates a printed cell: a field's name, access, reset and
description are the table's own text, and `bits` is the only derived value on
it (hence its `derivation`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from itertools import pairwise

from datasheet_analyzer.models import (
    BitRange,
    RawDocument,
    RegisterField,
    RegisterRecord,
    SectionNode,
    TableBlock,
)
from datasheet_analyzer.structure.confidence import grade_register_fields
from datasheet_analyzer.structure.device_tables import (
    BITFIELD,
    DeviceLexicon,
    DeviceSpec,
    DeviceTable,
    DeviceTableRejection,
    load_device_lexicon,
    normalize_header,
    read_device_table,
)
from datasheet_analyzer.structure.units import normalize_text

log = logging.getLogger(__name__)

#: The named rules this module publishes (ADR 0005: a rule nobody can name is
#: not a derivation). `bits` carries one of the first two, the register's
#: `width_derivation` one of the last two.
BIT_RANGE_DERIVATION = "parse_bit_range"
BIT_SPAN_DERIVATION = "bit_header_span"
WIDTH_FROM_RESET = "register_width_from_reset"
WIDTH_FROM_BIT_HEADER = "register_width_from_bit_header"

#: How a register's fields were read, published as `RegisterRecord.fields_route`.
ROUTE_COLUMN = "bit-column"
ROUTE_DIAGRAM = "bit-diagram"

#: A printed bit range. Anchored, and deliberately narrow: `15:3`, `3`, `[3]`,
#: `[15:3]` and `7..0` are what documents print, and a cell holding anything
#: else has no bit range in it. Two digits at most — no production register is
#: 100 bits wide, and a three-digit "range" is a value that landed in the bit
#: column.
_BIT_RANGE_RE = re.compile(
    r"^\[?\s*(?P<hi>\d{1,2})\s*(?:(?::|\.\.)\s*(?P<lo>\d{1,2})\s*)?\]?$"
)

#: A field-description table's caption naming the register it belongs to
#: (`Table 1-3. R0 Register Field Descriptions`). This is the join, so it is
#: matched on the register's own printed acronym and nothing looser.
_FIELD_TABLE_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])(?P<name>[A-Za-z][A-Za-z0-9_]*)\s+register\s+field",
    re.IGNORECASE,
)

#: The register declaration heading, as `structure/registers.py` reads it for
#: the reset value. Here only its *name* matters: a field table whose preamble
#: declares a different register than its caption names is refused rather than
#: reconciled.
_DECLARED_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9_]*)\s+register\s*\(\s*offset\s*=",
    re.IGNORECASE,
)

#: A hex word as a document prints a reset (`0x0000`, `FF86h`). The **digit
#: count** is what this module wants: four hex digits is a 16-bit register.
_HEX_WORD_RE = re.compile(r"^(?:0[xX](?P<hx>[0-9A-Fa-f]+)|(?P<hs>[0-9A-Fa-f]+)[hH])$")

#: How many header cells must be glued to their data before the repair below
#: fires. One is a coincidence; two is a merged row.
_MIN_GLUED_CELLS = 2


def parse_bit_range(text: str, *, derivation: str = BIT_RANGE_DERIVATION) -> BitRange | None:
    """`15:3` as a bit range, or `None`.

    Anchored for the reason `parse_register_word` is: a cell that is not
    *wholly* a bit range has no bit range in it, and reading one out of its
    leading digits is how a driver ends up writing the wrong bit. An inverted
    range (`3:15`) is refused too — it is a misread grid, not a field, and the
    caller must not be able to publish it by sorting the endpoints.
    """
    cleaned = normalize_text(text or "").strip()
    if not cleaned:
        return None
    match = _BIT_RANGE_RE.match(cleaned)
    if match is None:
        return None
    hi = int(match.group("hi"))
    lo = int(match.group("lo")) if match.group("lo") is not None else hi
    if hi < lo:
        return None
    return BitRange(verbatim=cleaned, hi=hi, lo=lo, derivation=derivation)


def field_table_register(caption: str) -> str:
    """The register a field table's caption names, or `""`.

    `Table 1-3. R0 Register Field Descriptions` → `R0`. Shared with
    `structure/registers.py`, which uses the same caption to give a register's
    declaration heading a page to cite: one caption, one reading.
    """
    match = _FIELD_TABLE_RE.search(normalize_text(caption or ""))
    return match.group("name") if match else ""


def declared_register(text: str) -> str:
    """The register a printed declaration heading names, or `""`."""
    match = _DECLARED_RE.search(normalize_text(text or ""))
    return match.group("name") if match else ""


def register_width(word: str) -> int | None:
    """A register's width in bits, read from a printed reset word.

    `0x0000` is four hex digits, so the register is 16 bits wide — the only
    width statement a TI programmer's guide makes, and a *printed* one, which
    is what invariant 8 requires of a derived value. A decimal reset (`0`) says
    nothing about width and returns `None`: a width guessed from the fields it
    is supposed to check would make the check vacuous.

    The cost is stated rather than hidden: a document printing `[Reset = 0x0]`
    for a 16-bit register yields width 4, its top fields overflow, and its
    field set is refused with a reason. That is the fail-closed direction.
    """
    match = _HEX_WORD_RE.match(normalize_text(word or "").strip())
    if match is None:
        return None
    digits = match.group("hx") or match.group("hs")
    return 4 * len(digits) if digits else None


def format_bits(hi: int, lo: int) -> str:
    """`(15, 3)` → `"15:3"`, `(2, 2)` → `"2"` — the way a page prints it.

    Used for the *derived* description of a gap (`unaccounted_bits`), never to
    rewrite a printed cell.
    """
    return f"{hi}:{lo}" if hi != lo else f"{hi}"


@dataclass(frozen=True)
class FieldTable:
    """One register's field table, read — or claimed and refused.

    `register` is the acronym the caption (or the preamble declaration) named;
    `""` means nothing in the table said which register it belongs to, which
    makes it unattachable rather than wrong. `reason` is why `fields` is empty,
    and it is what the register's record publishes as `fields_reason`.
    """

    register: str
    route: str
    evidence: str  # the printed caption
    section_index: int
    table_index: int
    page: int | None = None
    fields: tuple[RegisterField, ...] = ()
    #: Width the *table* declares, for the diagram route: the highest bit its
    #: header row prints, plus one. `None` for the column route, whose table
    #: says nothing about the register's width.
    declared_width: int | None = None
    #: Printed lines that carried no readable bit range and are therefore not
    #: published as fields. Counted, and reported at set level, because a
    #: swallowed field shows up as a gap in `unaccounted_bits` and a caller
    #: deserves both halves of that.
    unread_rows: int = 0
    reason: str = ""


@dataclass
class FieldTableSet:
    """Every field table of one document, plus what the abstraction refused."""

    tables: list[FieldTable] = field(default_factory=list)
    rejections: list[DeviceTableRejection] = field(default_factory=list)


def read_field_tables(
    raw: RawDocument, *, lexicon: DeviceLexicon | None = None
) -> FieldTableSet:
    """Every per-register field table of one document.

    A table is a candidate only when something printed on it names the register
    it describes — its caption (`R0 Register Field Descriptions`) or a
    declaration heading in its preamble. That is not a filter of convenience:
    the join *is* the provenance, and a field list attached to the wrong
    register is the failure this module exists to prevent.

    `pdf_text` documents are skipped for the reason every device-table read
    skips them: that backend carries no trusted tables.
    """
    result = FieldTableSet()
    if raw.extractor == "pdf_text":
        return result
    lexicon = load_device_lexicon() if lexicon is None else lexicon
    spec = lexicon.by_kind(BITFIELD)
    if spec is None:
        log.warning("no %r device-table kind in the lexicon — no bit fields", BITFIELD)
        return result

    for section_index, section in enumerate(raw.sections):
        for table_index, table in enumerate(section.tables):
            register, reason = _register_for(table)
            if not register and not reason:
                continue  # not a field table; nothing to say about it
            read, rejection = _read_one(
                lexicon, spec, section, section_index, table, table_index, register, reason
            )
            if read is not None:
                result.tables.append(read)
            if rejection is not None:
                result.rejections.append(rejection)
    return result


def _register_for(table: TableBlock) -> tuple[str, str]:
    """`(register acronym, refusal reason)` for one table's own printed text.

    The caption is preferred because it is the table's own label; a declaration
    heading in the preamble is the fallback for a document that captions its
    field tables generically. When both speak and they disagree, no fields are
    published — two names for one table is a misread region, and picking one
    would be a coin flip on which register a driver gets configured against —
    but the *reason* is still carried under the caption's register, because the
    register that looks like it has a field table is the one whose record has to
    explain why it has no fields.
    """
    caption = field_table_register(table.caption)
    declared = declared_register(table.conditions)
    if caption and declared and caption.casefold() != declared.casefold():
        return caption, (
            f"field table caption names {caption} but its preamble declares "
            f"{declared} — no fields published"
        )
    return caption or declared, ""


def _read_one(
    lexicon: DeviceLexicon,
    spec: DeviceSpec,
    section: SectionNode,
    section_index: int,
    table: TableBlock,
    table_index: int,
    register: str,
    reason: str,
) -> tuple[FieldTable | None, DeviceTableRejection | None]:
    """One candidate field table, by whichever route its shape declares."""
    def _table(**kwargs) -> FieldTable:
        defaults = {
            "register": register,
            "route": "",
            "evidence": (table.caption or "").strip(),
            "section_index": section_index,
            "table_index": table_index,
            "page": _region_page(table, section),
        }
        return FieldTable(**{**defaults, **kwargs})

    if reason:
        return _table(reason=reason), None

    # The diagram shape is tried first, because its bit header row would read
    # as data to the column route: `7 6 5 4 3 2 1 0` is eight cells of
    # bit-shaped text, and a positional map over them would publish eight
    # fields named after each other's bits.
    diagram = _read_bit_diagram(table, table_index)
    if diagram is not None:
        fields, width, diagram_reason = diagram
        return _table(
            route=ROUTE_DIAGRAM,
            fields=tuple(fields),
            declared_width=width,
            reason=diagram_reason,
        ), None

    block, _glued = _unglue_header_row(spec, table)
    accepted, rejection = read_device_table(
        section, block, table_index, kind=BITFIELD, lexicon=lexicon
    )
    if rejection is not None:
        return _table(route=ROUTE_COLUMN, reason=rejection.reason), rejection
    if accepted is None:
        return _table(
            route=ROUTE_COLUMN,
            reason="no bit-field table shape was identified in this table",
        ), None
    if accepted.column_map.via != "header" or accepted.column_map.index("name") is None:
        # The positional fallback is refused here. For a pin table a
        # half-understood header row costs a description; for a field table it
        # costs the bit range, and a bit range read from the wrong column is
        # indistinguishable from a correct one to whoever writes the driver.
        return _table(
            route=ROUTE_COLUMN,
            reason=(
                "field table does not declare its Bit and Field columns in its "
                "own header row — read positionally, a bit range could come "
                "from any column, so no fields are published"
            ),
        ), None

    fields, unread = _fields_from_column(accepted, block)
    note = "" if fields else "no row of the field table prints a readable bit range"
    return _table(
        route=ROUTE_COLUMN,
        fields=tuple(fields),
        unread_rows=unread,
        reason=note,
    ), None


def _fields_from_column(
    table: DeviceTable, block: TableBlock
) -> tuple[list[RegisterField], int]:
    """Records of an accepted `bitfield` device table as fields.

    Every record whose key reads as a bit range becomes a field, verbatim in
    everything but `bits`. A record whose key does not read as one is **not** a
    field and is counted: a table region routinely picks up the navigation line
    printed under it (`R2 is shown in Table 1-4.`), and reading that as a field
    with no bits would be worse than counting it. Anything it swallows shows up
    as a gap in the register's `unaccounted_bits`.
    """
    fields: list[RegisterField] = []
    unread = 0
    for record in table.records:
        bits = parse_bit_range(record.key)
        if bits is None:
            unread += 1
            continue
        fields.append(
            RegisterField(
                name=record.field("name"),
                bits=bits,
                access=record.field("access"),
                reset=record.field("reset"),
                description=record.field("description"),
                table_index=record.table_index,
                row_index=record.row_index,
                page=record.page if record.page is not None else block.page,
                row_verbatim=list(record.row_verbatim),
            )
        )
    return fields, unread


def _read_bit_diagram(
    table: TableBlock, table_index: int = 0
) -> tuple[list[RegisterField], int | None, str] | None:
    """The bit-diagram shape, read geometrically. `None` when it is not one.

    A bit diagram states a field's range **only** in the layout: the header row
    numbers the bit columns, and a field name spans the columns of the bits it
    occupies. So the range here is derived from the header row's cell
    boundaries — which column each bit number sits in, and which of those
    columns a field cell spans — and never from the field cell's own text.

    Returns `(fields, width, reason)`; a non-empty `reason` means the shape was
    recognised and refused, which is the fail-closed direction:

    - a header run that does not descend by one (`7 6 4 3`) is not a bit
      header, and a table whose header is unreadable has no geometry to read;
    - a field cell outside the header's columns cannot be given a range at all;
    - a header row with no field row under it describes nothing.
    """
    rows: list[tuple[int, list[str]]] = [(-1, list(table.headers))]
    rows.extend((index, list(row)) for index, row in enumerate(table.grid))

    fields: list[RegisterField] = []
    highest: int | None = None
    seen_run = False
    index = 0
    while index < len(rows):
        run = _bit_header_run(rows[index][1])
        if run is None:
            index += 1
            continue
        seen_run = True
        if index + 1 >= len(rows):
            return [], None, (
                "bit diagram prints a bit-position header row with no field row "
                "under it — no fields published"
            )
        row_index, row = rows[index + 1]
        spans, reason = _spans_for(run, row)
        if reason:
            return [], None, reason
        highest = max(run.values()) if highest is None else max(highest, max(run.values()))
        for name, hi, lo, verbatim in spans:
            fields.append(
                RegisterField(
                    name=name,
                    bits=BitRange(
                        verbatim=verbatim, hi=hi, lo=lo, derivation=BIT_SPAN_DERIVATION
                    ),
                    table_index=table_index,
                    row_index=row_index,
                    page=_row_page(table, row_index),
                    row_verbatim=list(row),
                )
            )
        index += 2

    if not seen_run:
        return None
    if not fields:
        return [], None, "bit diagram names no field under its bit-position header row"
    return fields, (None if highest is None else highest + 1), ""


def _bit_header_run(row: list[str]) -> dict[int, int] | None:
    """`{column index: bit number}` when this row is a bit-position header row.

    A bit header row is a run of bit numbers **descending by exactly one**, in
    consecutive non-empty cells, at least two of them: that is what makes the
    mapping from a column to a bit unambiguous. `7 6 4 3` is not one — a column
    whose bit nobody printed cannot be given a bit — and neither is a row that
    holds one number, which is a value that landed in a cell.
    """
    numbered: list[tuple[int, int]] = []
    for index, cell in enumerate(row):
        text = normalize_text(cell or "").strip()
        if not text:
            continue
        if not re.fullmatch(r"\d{1,2}", text):
            return None
        numbered.append((index, int(text)))
    if len(numbered) < 2:
        return None
    for (_col, high), (_next_col, low) in pairwise(numbered):
        if high - 1 != low:
            return None
    return {col: bit for col, bit in numbered}


def _spans_for(
    run: dict[int, int], row: list[str]
) -> tuple[list[tuple[str, int, int, str]], str]:
    """Field spans of one diagram row: `[(name, hi, lo, printed range)]`.

    A cell begins a field and the empty cells to its right continue it, which
    is exactly what a column-spanning cell looks like once the layout floor has
    put it in the band its text starts in. That reading is the one assumption
    this route makes, and it is the diagram's own convention: every bit column
    of a bit diagram belongs to a field box, and a blank column is the middle of
    the box that started to its left.

    Columns *before* the first named cell continue nothing, so those bits are
    unnamed and are reported as unaccounted rather than folded backwards into
    the field on their right — extending a field leftwards to make the row tile
    is the one move here that would put wrong bits in a driver.
    """
    columns = sorted(run)
    spans: list[tuple[str, int, int, str]] = []
    current: tuple[str, int, int] | None = None
    for index, cell in enumerate(row):
        text = " ".join((cell or "").split())
        if index not in run:
            if text:
                return [], (
                    f'bit diagram prints "{text}" outside the columns its '
                    f"bit-position header row numbers — no fields published"
                )
            continue
        bit = run[index]
        if text:
            if current is not None:
                spans.append((*current, format_bits(current[1], current[2])))
            current = (text, bit, bit)
        elif current is not None:
            current = (current[0], current[1], bit)
    if current is not None:
        spans.append((*current, format_bits(current[1], current[2])))
    # A column past the row's own length is an empty cell of the last field's
    # span, which the loop above cannot see; extend it to the run's last column.
    if spans and len(row) <= max(columns):
        name, hi, _lo, _printed = spans[-1]
        lo = run[max(columns)]
        spans[-1] = (name, hi, lo, format_bits(hi, lo))
    return spans, ""


def _unglue_header_row(spec: DeviceSpec, table: TableBlock) -> tuple[TableBlock, bool]:
    """A field table whose header row swallowed its first data row, repaired.

    The layout floor sometimes merges a field table's header line with the line
    under it, cell by cell: `Bit 15:13`, `Field RESERVED`, `Type R`,
    `Reset 0x0`. Measured on the reference document, that happens to 5 of its
    35 registers — and for three of them the merged line is the register's
    *only* field, so without this the field set would be empty or short a
    range at the top.

    The repair is deliberately hard to trigger by accident: at least
    `_MIN_GLUED_CELLS` cells must be a lexicon header phrase followed by more
    text, one of them must be the key column, and **the key column's remainder
    must read as a bit range**. A cell the lexicon does not recognise is left
    alone (a field table's region picks up cross-reference fragments), and
    nothing is split when the key column's remainder is not a range — a header
    row reading `Bit Field` is a header row.

    Returns the block to read and whether it was repaired.
    """
    phrases = {
        phrase: name for name in spec.fields for phrase in spec.headers.get(name, ())
    }
    headers: list[str] = []
    recovered: list[str] = []
    glued: list[str] = []
    key_index: int | None = None
    for index, cell in enumerate(table.headers):
        text = " ".join((cell or "").split())
        if normalize_header(text) in phrases:
            headers.append(text)
            recovered.append("")
            continue
        split = _split_glued(text, phrases)
        if split is None:
            headers.append(text)
            recovered.append("")
            continue
        header, remainder, name = split
        headers.append(header)
        recovered.append(remainder)
        glued.append(name)
        if name == spec.key_field and key_index is None:
            key_index = index

    if len(glued) < _MIN_GLUED_CELLS or key_index is None:
        return table, False
    if parse_bit_range(recovered[key_index]) is None:
        return table, False

    page = _row_page(table, 0)
    repaired = table.model_copy(
        update={
            "headers": headers,
            "grid": [recovered, *[list(row) for row in table.grid]],
            "row_pages": [page, *list(table.row_pages)],
        }
    )
    return repaired, True


def _split_glued(
    text: str, phrases: dict[str, str]
) -> tuple[str, str, str] | None:
    """`"Bit 15:13"` → `("Bit", "15:13", "bit")`, or `None`.

    Longest phrase first, so a `Bit Field` column is read as the header it is
    rather than as `Bit` plus data. The comparison is case-folded on the cell as
    printed (whitespace already collapsed by the caller), so the slice below
    cuts the original text at the phrase it actually matched.
    """
    low = text.casefold()
    for phrase in sorted(phrases, key=len, reverse=True):
        if low.startswith(f"{phrase} "):
            remainder = text[len(phrase):].strip()
            if remainder:
                return text[: len(phrase)].strip(), remainder, phrases[phrase]
    return None


def _row_page(table: TableBlock, row_index: int) -> int | None:
    """The printed page of one grid row, falling back to the table's own."""
    if 0 <= row_index < len(table.row_pages):
        page = table.row_pages[row_index]
        if page is not None:
            return page
    return table.page


def _region_page(table: TableBlock, section: SectionNode) -> int | None:
    """The page a table's region was printed on (`structure/registers.py`'s rule)."""
    for page in table.row_pages:
        if page is not None:
            return page
    return table.page if table.page is not None else section.page_start


def attach_fields(
    records: list[RegisterRecord],
    raw: RawDocument,
    *,
    lexicon: DeviceLexicon | None = None,
) -> tuple[FieldTableSet, list[str]]:
    """Attach each register's validated bit fields to its record, in place.

    Returns the field tables that were read (so the caller can record what the
    abstraction refused) and the warnings the *set* has to carry: how many
    registers publish fields, and what was read but could not be attached.

    Every register is left with either a validated field set or an empty one
    plus `fields_reason`. There is no third outcome, and in particular no
    partial one: a set that fails validation is refused whole.
    """
    result = read_field_tables(raw, lexicon=lexicon)
    by_register: dict[str, list[int]] = {}
    for index, read in enumerate(result.tables):
        by_register.setdefault(read.register.casefold(), []).append(index)

    attached: set[int] = set()
    for record in records:
        candidates = by_register.get(record.name.strip().casefold(), [])
        if not record.name.strip():
            record.fields_reason = (
                "the summary row prints no register name, so no field table can "
                "be joined to it"
            )
            continue
        if not candidates:
            record.fields_reason = (
                f"no bit-field table was read for {record.name} — the document "
                f"prints none, or the one it prints was rejected"
            )
            continue
        if len(candidates) > 1:
            claimed = sorted(
                result.tables[i].evidence or "(uncaptioned)" for i in candidates
            )
            record.fields_reason = (
                f"{len(candidates)} field tables claim {record.name} "
                f"({', '.join(claimed)}) — no fields published"
            )
            continue
        attached.add(candidates[0])
        _attach_one(record, result.tables[candidates[0]], raw)

    orphans = [
        read for index, read in enumerate(result.tables) if index not in attached
    ]
    warnings = _warnings(records, result, orphans)
    return result, warnings


def _attach_one(record: RegisterRecord, read: FieldTable, raw: RawDocument) -> None:
    """Validate one field table against its register and publish or refuse it."""
    record.fields_route = read.route
    record.fields_evidence = read.evidence
    if read.reason:
        record.fields_reason = read.reason
        return

    width, evidence, derivation = _width_for(record, read)
    if width is None:
        record.fields_reason = (
            f"register width unknown for {record.name}: the document states no "
            f"hex reset word to read it from, and a field list that cannot be "
            f"checked against a width is not published"
        )
        return

    reason = _validate(list(read.fields), width)
    if reason:
        record.fields_reason = reason
        return

    record.fields = list(read.fields)
    record.width = width
    record.width_evidence = evidence
    record.width_derivation = derivation
    record.unaccounted_bits = _unaccounted(list(read.fields), width)
    block = _block_for(raw, read)
    if block is not None:
        record.fields_confidence = grade_register_fields(record, block)


def _width_for(record: RegisterRecord, read: FieldTable) -> tuple[int | None, str, str]:
    """`(width, printed evidence, derivation)` for one register.

    The register's own reset word leads — it is a statement about the register,
    printed on the page, and it is the only width statement TI's programmer's
    guides make. A bit diagram's header row is the fallback, because there the
    *table* states the width by numbering every bit it has.
    """
    reset = record.reset
    if reset is not None:
        width = register_width(reset.verbatim)
        if width is not None:
            return width, reset.verbatim, WIDTH_FROM_RESET
    if read.declared_width is not None:
        return read.declared_width, read.evidence, WIDTH_FROM_BIT_HEADER
    return None, "", ""


def _validate(fields: list[RegisterField], width: int) -> str:
    """`""` when this field set is sound, else why the **whole** set is refused.

    Two failures, both fatal to the set rather than to one field, because a
    field list with one bad range in it cannot be told from a good one by
    whoever reads it:

    - **overflow** — a field claiming a bit the register does not have means the
      width and the table disagree, and one of them is misread;
    - **overlap** — two fields claiming one bit means at least one is wrong.
      Measured: the reference document's R90 table prints `15:8` and `15:0`,
      a typo in the document itself, and this is what stops the corpus from
      publishing a guess about which was meant.

    A *gap* is not a failure. Bits nobody claims are reported
    (`unaccounted_bits`) — the document may simply not name them, and refusing
    the set would throw away every field it does name.
    """
    if not fields:
        return "no row of the field table prints a readable bit range"
    owner: dict[int, RegisterField] = {}
    for field_record in fields:
        hi, lo = field_record.bits.hi, field_record.bits.lo
        if hi is None or lo is None:  # pragma: no cover - never emitted
            return f'field "{field_record.name}" has no readable bit range'
        if hi >= width:
            return (
                f'field "{field_record.name}" claims bit {hi} of a {width}-bit '
                f"register — no fields published"
            )
        for bit in range(lo, hi + 1):
            other = owner.get(bit)
            if other is not None:
                return (
                    f'fields "{other.name}" ({other.bits.verbatim}) and '
                    f'"{field_record.name}" ({field_record.bits.verbatim}) both '
                    f"claim bit {bit} — no fields published"
                )
            owner[bit] = field_record
    return ""


def _unaccounted(fields: list[RegisterField], width: int) -> list[str]:
    """The bits of a `width`-bit register no field claims, printed high first.

    This is the checkable half of "reserved and unnamed ranges are represented
    honestly": every range the document *printed* is a field (`RESERVED`
    included — it is a name, not a gap), and everything left over is listed
    here rather than left for a reader to work out.
    """
    claimed = {
        bit
        for record in fields
        if record.bits.hi is not None and record.bits.lo is not None
        for bit in range(record.bits.lo, record.bits.hi + 1)
    }
    gaps: list[str] = []
    bit = width - 1
    while bit >= 0:
        if bit in claimed:
            bit -= 1
            continue
        hi = bit
        while bit >= 0 and bit not in claimed:
            bit -= 1
        gaps.append(format_bits(hi, bit + 1))
    return gaps


def _warnings(
    records: list[RegisterRecord], result: FieldTableSet, orphans: list[FieldTable]
) -> list[str]:
    """What the set has to say out loud about its bit-field coverage.

    Invariant 8's honesty clause, for this artifact: a caller that lists bit
    fields must be able to say "28 of 35 registers publish them" instead of
    quietly showing a shorter list — and the same for the printed lines that
    carried no readable range, and for field tables that belong to no register
    the summary lists.

    A document that prints **no** field table says nothing here, which is the
    stance ticket 04 took on a datasheet with no pin table: an absence in the
    document is not a finding about the extraction, and a warning on every
    register map that simply does not print field tables would bury the ones
    that do. The per-register `fields_reason` still records it, register by
    register, which is where a caller asking about one register looks.
    """
    warnings: list[str] = []
    if not records or not result.tables:
        return warnings
    with_fields = sum(1 for record in records if record.fields)
    if with_fields < len(records):
        warnings.append(
            f"bit fields published for {with_fields} of {len(records)} registers; "
            f"the remaining {len(records) - with_fields} publish fields: [] with a "
            f"recorded reason"
        )
    unread = sum(read.unread_rows for read in result.tables)
    if unread:
        warnings.append(
            f"{unread} field-table row(s) print no readable bit range and are not "
            f"published as fields; any bits they hold appear in unaccounted_bits"
        )
    if orphans:
        named = ", ".join(sorted({read.register or "(unnamed)" for read in orphans}))
        warnings.append(
            f"{len(orphans)} field table(s) belong to no register the summary "
            f"lists ({named})"
        )
    return warnings


def _block_for(raw: RawDocument, read: FieldTable) -> TableBlock | None:
    """The `TableBlock` a field table was read from, by position."""
    if not (0 <= read.section_index < len(raw.sections)):
        return None
    tables = raw.sections[read.section_index].tables
    if not (0 <= read.table_index < len(tables)):
        return None
    return tables[read.table_index]
