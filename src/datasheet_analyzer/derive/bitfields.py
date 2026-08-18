"""Register bit fields — the parked half of the register map (phase 6, ticket 06).

**Read this first: nothing in this module reaches a published artifact.**
Ticket 06 attempted per-register bit fields, measured itself against the
reference register map, failed its accuracy gate, and **parked**. The reasons
are in `KNOWN_SHORTCOMINGS.md` under *"Register bit fields: not extracted"*,
measured by `tests/integration/test_phase6_bitfields.py`. This file is kept
for two jobs, and it does no others:

1. it is the **measurement instrument** the gate runs, so the park verdict is
   a number against a real document rather than an opinion;
2. it is the implementation that becomes live when the layout engine can hand
   over the register map's field tables intact — at which point the gate turns
   green on its own and the shortcoming entry is deleted with it.

Nothing imports it: not `derive/registers.py`, not the pipeline, not the CLI,
not the MCP surface. `RegisterRecord.fields` stays `[]` for every published
register, which is the ticket's fail-closed contract in one line — **wrong bit
positions are worse than absent ones**, because a driver written against a
wrong range misconfigures silicon silently, while an absent one sends a
firmware engineer to the page.

## The two printed shapes

**(a) The field-description table.** `Bit | Field | Type | Reset |
Description`, one printed row per field, which is what TI's LMX1204 register
map prints for all 35 of its registers.

**(b) The bit-position diagram.** A header row of bit numbers —
`7 6 5 4 3 2 1 0` — over field-name cells that span columns, with `Type` and
`Reset` rows beneath aligned to the same columns. **A field's bit range here
is read from the header row's column boundaries and never from the name
cell's text**: the name cell says `NCO_EN`, and the fact that it occupies the
one column the header prints `3` above is what makes it bit 3. That is the
geometric rule ticket 06 asks for, and it is why `_diagram_fields` walks
column indices rather than parsing anything.

## What "honest" means here, concretely

Every cell is **copied verbatim** (clause (a) of invariant 8, ADR 0007); the
only computed values are `BitRange.hi` / `.lo`, produced by `parse_bit_range`
in shape (a) and by column arithmetic over the bit header in shape (b) — both
documented pure functions (clause (b)); the role labels come from the checked-in
header lexicon in this file (clause (c)). No model call appears anywhere in
this path.

**A register's field set is accepted whole or refused whole.** There is no
partial field list, because a partial one is the dangerous artifact: a
register whose printed `8:7` field was dropped reads as "bits 8 and 7 are
unused", which is a false statement about silicon. `validate_fields` is
therefore deliberately severe, and each of its rules exists because the
reference document broke it:

- **every bit cell must parse** — a range this tool could not read is not a
  range it may guess at;
- **field names must be identifiers** — the layout engine re-joins a wrapped
  cell as `SYSREFREQ_DELAY_ST EPSIZE`, and a name with a space in it is a
  misread, not a name;
- **access and reset must be printed for every field** when the table declares
  those columns — a blank reset read as `0x0` is exactly the confidently wrong
  answer that breaks a bring-up sequence;
- **ranges may not overlap**, and R90 of the reference map prints `15:8` and
  then `15:0`, which no reading can make true at once;
- **the set must cover the register width with no gaps** — a truncated table
  (the reference map's R19 survives extraction as its first field alone) fails
  here rather than shipping one third of a register.

Reserved and unnamed spans are **kept, never filtered**: `RESERVED` rows are
fields like any other, and shape (b)'s unlabelled column runs become fields
with an empty name. That is what makes coverage checkable at all — a field
list you may not trim is a field list whose width arithmetic means something.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from datasheet_analyzer.models import (
    RECONSTRUCTION_RESCUED,
    BitField,
    BitRange,
    Confidence,
    RawDocument,
    SectionNode,
    TableBlock,
)
from datasheet_analyzer.structure.device_tables import normalize_header

log = logging.getLogger(__name__)

#: The two printed shapes, named so a caller never spells one.
SHAPE_DESCRIPTION = "description"
SHAPE_DIAGRAM = "diagram"

#: The named pure functions that produce `BitRange.hi` / `.lo`. A
#: `DerivedValue` would carry one of these in its `derivation`; `BitField`
#: has no such field in the frozen model, so the rule is named here and
#: recorded on the extraction instead.
BIT_RANGE_DERIVATION = "parse_bit_range"
BIT_SPAN_DERIVATION = "bit_header_span"

#: Where a width came from. `declared` is the register's printed width;
#: `observed` is the span the field set itself covers, which is weaker and is
#: labelled so no reader mistakes it for a printed fact.
WIDTH_DECLARED = "declared"
WIDTH_OBSERVED = "observed"

#: The checked-in header lexicon — clause (c) of invariant 8. Data, not
#: vendor rules: a header variant a vendor prints is a line added here.
BIT_HEADERS: tuple[str, ...] = ("bit", "bits", "bit no", "bit number", "bit position", "b")
NAME_HEADERS: tuple[str, ...] = ("field", "field name", "name", "bit field", "bit name")
ACCESS_HEADERS: tuple[str, ...] = ("type", "access", "access type", "r/w", "rw", "mode")
RESET_HEADERS: tuple[str, ...] = ("reset", "default", "por", "reset value", "default value")
DESCRIPTION_HEADERS: tuple[str, ...] = ("description", "function", "details", "comment")

_ROLE_BIT = "bit"
_ROLE_NAME = "name"
_ROLE_ACCESS = "access"
_ROLE_RESET = "reset"
_ROLE_DESCRIPTION = "description"

_ROLE_HEADERS: dict[str, tuple[str, ...]] = {
    _ROLE_BIT: BIT_HEADERS,
    _ROLE_NAME: NAME_HEADERS,
    _ROLE_ACCESS: ACCESS_HEADERS,
    _ROLE_RESET: RESET_HEADERS,
    _ROLE_DESCRIPTION: DESCRIPTION_HEADERS,
}

#: A caption that names the register whose fields a table describes:
#: "Table 1-4. R2 Register Field Descriptions" -> "R2".
_CAPTION_REGISTER = re.compile(
    r"(?:^|\s)(?P<name>[A-Za-z][A-Za-z0-9_]*)\s+register\s+(?:bit\s+)?"
    r"field(?:s)?(?:\s+descriptions?)?\s*$",
    re.IGNORECASE,
)

#: A field name a datasheet actually prints. An identifier, optionally
#: carrying the slice of a wider field it holds: `rb_CLKPOS[31:16]`. A space
#: inside one is a wrapped cell the layout engine re-joined, not a name.
_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*(?:\[\d+(?::\d+)?\])?$")

_WS = re.compile(r"\s+")
#: `15:3`, `[15:3]`, `15..3`, `15 to 3`, `15-3`, and the single-bit forms
#: `7`, `[7]`, `b7`, `D7`, `bit 7`.
_RANGE = re.compile(
    r"^\[?\s*(?:bits?\s*)?(?:[bdBD])?(?P<hi>\d{1,3})\s*(?::|\.\.|to|-|–|—|−)\s*"
    r"(?:[bdBD])?(?P<lo>\d{1,3})\s*\]?$",
    re.IGNORECASE,
)
_SINGLE = re.compile(r"^\[?\s*(?:bits?\s*)?(?:[bdBD])?(?P<bit>\d{1,3})\s*\]?$", re.IGNORECASE)

#: A bit header row shorter than this is a coincidence, not a bit diagram —
#: two adjacent integer columns happen in plenty of parametric tables.
MIN_DIAGRAM_COLUMNS = 4

#: A register wider than this is not one this shape prints; a run of integers
#: that long is a data column being misread as a bit header.
MAX_REGISTER_WIDTH = 64


def _clean(text: str) -> str:
    """One printed cell, whitespace-normalized and nothing else."""
    return _WS.sub(" ", (text or "").replace("\n", " ")).strip()


# --- bit ranges ------------------------------------------------------------


def parse_bit_range(text: str) -> BitRange:
    """A printed bit cell -> `BitRange`, or verbatim-only when it does not read.

    The documented pure function behind shape (a)'s `hi` / `lo`
    (`BIT_RANGE_DERIVATION`). Both orders of a printed range are accepted —
    `15:3` and `3:15` name the same bits — and `hi` is always the larger, so a
    consumer never has to ask which way round a vendor prints them.

    An unreadable cell returns `hi is None` and `lo is None` **with the
    verbatim print kept**. That is the whole contract of this module in
    miniature: the tool says what the page says and refuses to say what it
    could not read.
    """
    printed = _clean(text)
    if not printed:
        return BitRange()
    match = _RANGE.match(printed)
    if match:
        a, b = int(match.group("hi")), int(match.group("lo"))
        return BitRange(verbatim=printed, hi=max(a, b), lo=min(a, b))
    single = _SINGLE.match(printed)
    if single:
        bit = int(single.group("bit"))
        return BitRange(verbatim=printed, hi=bit, lo=bit)
    return BitRange(verbatim=printed)


def register_name_from_caption(caption: str) -> str:
    """`"Table 1-4. R2 Register Field Descriptions"` -> `"R2"`, else `""`.

    How a field table says which register it belongs to, when the register
    summary and the field tables are separate printed objects. Returning `""`
    is the honest outcome for a caption that does not name one — an unattached
    field set is not attached to a guess.
    """
    match = _CAPTION_REGISTER.search(_clean(caption))
    return match.group("name") if match else ""


# --- shape (a): the field-description table ---------------------------------


@dataclass(frozen=True)
class _ColumnMap:
    """Which printed column carries which role in a field-description table."""

    columns: dict[str, int] = dataclass_field(default_factory=dict)

    def cell(self, row: Sequence[str], role: str) -> str:
        index = self.columns.get(role)
        if index is None or index >= len(row):
            return ""
        return _clean(row[index])

    def has(self, role: str) -> bool:
        return role in self.columns


def map_description_columns(headers: Sequence[str]) -> _ColumnMap | None:
    """Map a field-description table's headers, or `None` when it is not one.

    A table qualifies only when it declares **both** a bit column and a field
    column — the two that make the shape what it is. Everything else is
    optional, and its absence is recorded rather than filled in.
    """
    columns: dict[str, int] = {}
    for index, header in enumerate(headers):
        phrase = normalize_header(header)
        if not phrase:
            continue
        for role, variants in _ROLE_HEADERS.items():
            if role not in columns and phrase in variants:
                columns[role] = index
                break
    if _ROLE_BIT not in columns or _ROLE_NAME not in columns:
        return None
    return _ColumnMap(columns=columns)


def _is_continuation(mapping: _ColumnMap, row: Sequence[str]) -> bool:
    """Whether a printed row continues the previous field's description.

    A wrapped description spills onto its own grid row carrying nothing else.
    Its *bit* cell is not trusted: the layout engine's row reconstruction
    routinely files a continuation under the next field's bit range, so the
    cell is ignored rather than believed.
    """
    if not mapping.cell(row, _ROLE_NAME):
        return bool(mapping.cell(row, _ROLE_DESCRIPTION))
    return False


def _description_fields(
    mapping: _ColumnMap, grid: Sequence[Sequence[str]], page: int | None, grade: Confidence
) -> tuple[list[BitField], int]:
    """Shape (a) rows -> fields, plus the count of rows that produced none."""
    fields: list[BitField] = []
    dropped = 0
    for row in grid:
        if _is_continuation(mapping, row):
            extra = mapping.cell(row, _ROLE_DESCRIPTION)
            if fields and extra:
                merged = f"{fields[-1].description} {extra}".strip()
                fields[-1] = fields[-1].model_copy(update={"description": merged})
            else:
                dropped += 1
            continue
        name = mapping.cell(row, _ROLE_NAME)
        bits = mapping.cell(row, _ROLE_BIT)
        if not name and not bits:
            dropped += 1
            continue
        fields.append(
            BitField(
                name=name,
                bits=parse_bit_range(bits),
                access=mapping.cell(row, _ROLE_ACCESS),
                reset=mapping.cell(row, _ROLE_RESET),
                description=mapping.cell(row, _ROLE_DESCRIPTION),
                page=page,
                confidence=grade,
            )
        )
    return fields, dropped


# --- shape (b): the bit-position diagram -----------------------------------


def read_bit_header(cells: Sequence[str]) -> dict[int, int]:
    """`{column index: bit position}` for a bit-position header row, else `{}`.

    The geometric anchor of shape (b). A row qualifies when its integer cells
    form **one contiguous run of consecutive bit numbers** — `7 6 5 4 3 2 1 0`
    or `0 1 2 3 4 5 6 7` — of at least `MIN_DIAGRAM_COLUMNS` columns, with the
    highest bit no wider than `MAX_REGISTER_WIDTH`. Leading label cells
    (`Bit`, `Bits`) are allowed before the run and are not part of it.

    Everything shape (b) knows about where a field starts and stops comes from
    this mapping. Nothing here reads a field name.
    """
    numbers: list[tuple[int, int]] = []
    for index, cell in enumerate(cells):
        printed = _clean(cell)
        if not printed:
            continue
        if printed.isdigit():
            numbers.append((index, int(printed)))
            continue
        if numbers:  # a non-numeric cell after the run ends it
            return {}
        if normalize_header(printed) not in BIT_HEADERS:
            return {}
    if len(numbers) < MIN_DIAGRAM_COLUMNS:
        return {}
    columns = [i for i, _ in numbers]
    if columns != list(range(columns[0], columns[0] + len(columns))):
        return {}
    bits = [b for _, b in numbers]
    if max(bits) >= MAX_REGISTER_WIDTH:
        return {}
    descending = list(range(bits[0], bits[0] - len(bits), -1))
    ascending = list(range(bits[0], bits[0] + len(bits)))
    if bits not in (descending, ascending):
        return {}
    return dict(numbers)


def _spans(row: Sequence[str], columns: Sequence[int]) -> list[tuple[str, list[int]]]:
    """Group the bit columns of the name row into the spans its cells occupy.

    Two printings of the same spanning cell are both read here, because both
    occur: an HTML-derived grid repeats a `colspan` cell's text in every
    column it covers, while a reconstructed PDF grid puts the text in the
    span's first column and leaves the rest empty. Either way a span runs from
    a named column up to the next differently-named one — and the *columns*,
    not the text, are what the caller turns into bits.

    The one thing this cannot tell apart is two adjacent one-bit fields that
    print the *same* name — two neighbouring `RESERVED` bits read as one
    two-bit `RESERVED` span. The bits are covered either way and no bit is
    misattributed, which is why it is accepted rather than refused; the
    alternative would need cell geometry the table model does not carry.
    """
    spans: list[tuple[str, list[int]]] = []
    for column in columns:
        text = _clean(row[column]) if column < len(row) else ""
        if spans and (not text or text == spans[-1][0]):
            spans[-1][1].append(column)
            continue
        spans.append((text, [column]))
    return spans


def _within(row: Sequence[str], span: Sequence[int]) -> str:
    """The one value a row prints across exactly these columns, or `""`.

    Read *against the name row's spans* rather than grouped on its own,
    because a `Type` row printing `R/W` over two neighbouring fields is
    genuinely ambiguous when grouped alone. A span that carries two different
    printed values is not describing one field, so it contributes nothing —
    a borrowed access bit is the kind of plausible default invariant 8 forbids.
    """
    seen = {_clean(row[c]) for c in span if c < len(row) and _clean(row[c])}
    return seen.pop() if len(seen) == 1 else ""


def _diagram_fields(
    grid: Sequence[Sequence[str]],
    headers: Sequence[str],
    page: int | None,
    grade: Confidence,
) -> tuple[list[BitField], int, int | None, frozenset[str]]:
    """Shape (b) -> fields, dropped rows, header width, and the roles it prints.

    The rows are read by their **leading label** — `Field`, `Type`, `Reset` —
    against the same checked-in lexicon shape (a) uses, so a diagram that
    prints its access row as `Access` and one that prints it as `Type` are one
    shape. Only the name row is required; a diagram that prints no reset row
    leaves every field's reset empty rather than inventing zero.
    """
    rows: list[Sequence[str]] = [headers, *grid] if headers else list(grid)
    bit_columns: dict[int, int] = {}
    header_index = -1
    for index, row in enumerate(rows):
        found = read_bit_header(row)
        if found:
            bit_columns, header_index = found, index
            break
    if not bit_columns:
        return [], 0, None, frozenset()

    columns = sorted(bit_columns)
    labelled: dict[str, Sequence[str]] = {}
    dropped = 0
    for row in rows[header_index + 1 :]:
        label = normalize_header(row[0]) if row else ""
        role = next((r for r, variants in _ROLE_HEADERS.items() if label in variants), "")
        if role and role not in labelled:
            labelled[role] = row
        else:
            dropped += 1
    name_row = labelled.get(_ROLE_NAME)
    if name_row is None:
        return [], dropped, None, frozenset()

    access_row = labelled.get(_ROLE_ACCESS)
    reset_row = labelled.get(_ROLE_RESET)

    fields: list[BitField] = []
    for text, span in _spans(name_row, columns):
        bits = [bit_columns[c] for c in span]
        hi, lo = max(bits), min(bits)
        fields.append(
            BitField(
                name=text,
                bits=BitRange(verbatim=f"{hi}:{lo}" if hi != lo else str(hi), hi=hi, lo=lo),
                access=_within(access_row, span) if access_row is not None else "",
                reset=_within(reset_row, span) if reset_row is not None else "",
                page=page,
                confidence=grade,
            )
        )
    fields.sort(key=lambda f: (-(f.bits.hi or 0), -(f.bits.lo or 0)))
    return fields, dropped, max(bit_columns.values()) + 1, frozenset(labelled)


# --- validation ------------------------------------------------------------


def validate_fields(
    fields: Sequence[BitField],
    *,
    declared_width: int | None = None,
    require_access: bool = False,
    require_reset: bool = False,
) -> tuple[list[str], int | None, str]:
    """Every reason this field set may not ship, plus the width it was checked at.

    Returns `(reasons, width, width_source)`. An empty `reasons` is the only
    thing that lets a field set out of this module; anything else refuses the
    **whole** set, because a register with one field quietly missing is a false
    statement about the bits that field covered.

    When no width is declared the set's own top bit is adopted as the width
    and labelled `observed`, so the coverage check still runs and no reader
    mistakes the number for something the datasheet printed.
    """
    reasons: list[str] = []
    if not fields:
        return ["no bit-field rows were read from the table"], declared_width, ""

    unparsed = [f for f in fields if f.bits.hi is None or f.bits.lo is None]
    if unparsed:
        shown = ", ".join(repr(f.bits.verbatim) for f in unparsed[:4])
        reasons.append(f"{len(unparsed)} bit range(s) did not parse ({shown})")

    malformed = [f for f in fields if f.name and not _FIELD_NAME.match(f.name)]
    if malformed:
        shown = ", ".join(repr(f.name) for f in malformed[:4])
        reasons.append(f"{len(malformed)} field name(s) are not identifiers ({shown})")

    # A span the diagram labels in no row at all is the "unnamed bit range"
    # case: the page prints nothing over those columns, and saying so is a
    # true statement rather than a missing value. A field that *is* named but
    # whose access or reset is blank is the dangerous one — that is a value
    # the page printed and this tool lost.
    claimed = [f for f in fields if f.name or f.access or f.reset or f.description]
    if require_access:
        blank = [f for f in claimed if not f.access]
        if blank:
            reasons.append(f"{len(blank)} field(s) print no access although the table declares one")
    if require_reset:
        blank = [f for f in claimed if not f.reset]
        if blank:
            reasons.append(f"{len(blank)} field(s) print no reset although the table declares one")

    ranges = [(f.bits.hi, f.bits.lo) for f in fields if f.bits.hi is not None]
    if not ranges:
        return reasons or ["no bit range in the table parsed"], declared_width, ""

    top = max(hi for hi, _ in ranges)
    width = declared_width if declared_width else top + 1
    width_source = WIDTH_DECLARED if declared_width else WIDTH_OBSERVED

    overflow = [f"{hi}:{lo}" for hi, lo in ranges if hi >= width]
    if overflow:
        reasons.append(
            f"{len(overflow)} bit range(s) fall outside the {width}-bit register "
            f"({', '.join(overflow[:4])})"
        )

    covered: dict[int, int] = {}
    overlaps: list[str] = []
    for hi, lo in ranges:
        for bit in range(lo, hi + 1):
            covered[bit] = covered.get(bit, 0) + 1
            if covered[bit] == 2:
                overlaps.append(str(bit))
    if overlaps:
        reasons.append(
            f"bit(s) {', '.join(overlaps[:8])} are claimed by more than one field; "
            f"no reading of the table can be true"
        )

    gaps = [bit for bit in range(width) if bit not in covered]
    if gaps:
        reasons.append(
            f"{len(gaps)} of {width} bits are covered by no field "
            f"({', '.join(str(b) for b in gaps[:8])}); the field list is incomplete"
        )
    return reasons, width, width_source


# --- one table -------------------------------------------------------------


@dataclass(frozen=True)
class BitFieldExtraction:
    """One field table read, accepted whole or refused whole.

    `fields` is empty whenever `reasons` is not: there is no third state and
    no partial field list, which is the one property a firmware engineer needs
    from this module. `register_name` is what the caption said, `""` when it
    said nothing — an unattached field set is never attached to a guess.
    """

    register_name: str = ""
    caption: str = ""
    shape: str = ""
    fields: tuple[BitField, ...] = ()
    reasons: tuple[str, ...] = ()
    width: int | None = None
    width_source: str = ""
    derivation: str = ""
    page: int | None = None
    section: str = ""
    table_index: int = 0
    n_printed_rows: int = 0
    n_dropped_rows: int = 0

    @property
    def accepted(self) -> bool:
        return bool(self.fields)


def _grade(table: TableBlock) -> Confidence:
    """How much one field table's rows can be trusted on their own.

    The same rule the device-table layer applies: a grid the layout engine had
    to rescue with a coarser split is `medium`, one it read from the table's
    own declared column edges is `high`. A field set is refused outright long
    before this matters, so the grade only ever describes rows that passed.
    """
    if table.reconstruction == RECONSTRUCTION_RESCUED:
        return Confidence.MEDIUM
    if table.page is None:
        return Confidence.MEDIUM
    return Confidence.HIGH


def extract_bit_fields(
    section: SectionNode,
    table: TableBlock,
    table_index: int = 0,
    *,
    declared_width: int | None = None,
) -> BitFieldExtraction | None:
    """One table -> one register's bit fields, or `None` when it is not one.

    `None` means "this table does not describe a register's bits", which is
    the ordinary case for every other table in a document and is deliberately
    silent. A table that *is* one and could not be read honestly comes back
    with `reasons` and no fields — that is a recorded refusal, not silence.
    """
    page = table.page if table.page is not None else section.page_start
    grade = _grade(table)
    name = register_name_from_caption(table.caption)

    mapping = map_description_columns(table.headers)
    if mapping is not None:
        fields, dropped = _description_fields(mapping, table.grid, page, grade)
        shape, derivation = SHAPE_DESCRIPTION, BIT_RANGE_DERIVATION
        require_access, require_reset = mapping.has(_ROLE_ACCESS), mapping.has(_ROLE_RESET)
        header_width = None
    else:
        fields, dropped, header_width, roles = _diagram_fields(
            table.grid, table.headers, page, grade
        )
        if not fields and header_width is None:
            return None
        shape, derivation = SHAPE_DIAGRAM, BIT_SPAN_DERIVATION
        require_access = _ROLE_ACCESS in roles
        require_reset = _ROLE_RESET in roles

    reasons, width, width_source = validate_fields(
        fields,
        declared_width=declared_width or header_width,
        require_access=require_access,
        require_reset=require_reset,
    )
    return BitFieldExtraction(
        register_name=name,
        caption=table.caption,
        shape=shape,
        fields=() if reasons else tuple(fields),
        reasons=tuple(reasons),
        width=width,
        width_source="" if reasons else width_source,
        derivation=derivation,
        page=page,
        section=section.number,
        table_index=table_index,
        n_printed_rows=len(table.grid),
        n_dropped_rows=dropped,
    )


def iter_bit_field_tables(raw: RawDocument) -> Iterator[BitFieldExtraction]:
    """Every register field table in one document, accepted and refused alike.

    The entry point the gate measures. A `pdf_text` document yields nothing at
    all: that backend publishes no trusted tables, so there is no field table
    in it to be honest or dishonest about.
    """
    if raw.extractor == "pdf_text":
        return
    for section in raw.sections:
        for table_index, table in enumerate(section.tables):
            extraction = extract_bit_fields(section, table, table_index)
            if extraction is not None:
                yield extraction
