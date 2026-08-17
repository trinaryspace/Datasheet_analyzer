"""RawDocument -> registers.json: the register summary as citable records.

Phase 6, ticket 05 — the second consumer of the device-table abstraction, and
the artifact a firmware engineer lives inside during bring-up. Nothing here
reads a PDF: `structure/device_tables.py` has already done
identify → map → validate → emit over the register-summary table, and this
module is the *publication* of that result as registers — one record per
printed address, its parsed integer beside the string, and the reset value the
document states for it.

Four rules are load-bearing.

- **A register table is published whole or not at all.** Exactly the pin rule
  (see `structure/pins.py`): the device-table abstraction rejects what it
  cannot validate — a duplicate address, addresses out of order, a key column
  of prose — and this module never back-fills the gap. The reason lands in
  `ExtractionStats.rejection_reasons`; `build_registerset` still returns a set,
  and the publisher writes no file for an empty one. A firmware engineer who
  greps for `0x1A04`, gets no hit and concludes the register does not exist has
  been misled in the most expensive possible way.
- **An address carries both forms, and the parsed one is allowed to fail.**
  `0x1A04` is the answer; `6660` is what makes `dsa regs --addr 0x1a04` and
  `dsa regs --addr 6660` the same question. A cell the grammar cannot read as
  an integer stays verbatim-only (`RegisterWord.value is None`) rather than
  being guessed at, and the record's confidence grade says so.
- **A reset value is read only where the document prints one.** The summary
  table's own reset column when it has one; otherwise the register's printed
  declaration heading — `1.1 R0 Register (Offset = 0x0) [Reset = 0x0000]`, the
  form every TI programmer's guide uses and the only place LMX1204 states a
  reset at all. The join is on the **parsed offset**, never on the name alone,
  and a declaration whose name contradicts the row it would attach to is
  refused rather than reconciled. A register the document declares nothing for
  keeps `reset = None`: null and saying so, per ADR 0005.
- **The reset coverage is reported, not hidden.** "reset value stated for 18 of
  35 registers" is the invariant-8 honesty clause applied to this artifact: a
  consumer listing reset values must be able to say what it could not read
  instead of showing a shorter list. It is recorded in
  `RegisterSet.n_reset_stated` and, when there is a gap, joins
  `CorpusManifest.derived_warnings`. (LMX1204 happens to state all 35 in both
  of its documents, so it raises no warning — which is what the *absence* of
  one has to mean.)

Access is deliberately *not* derived. LMX1204 — both its datasheet and its
programmer's guide — prints access per **bit field**, in the per-register field
tables, and states no register-level access anywhere; `access` is therefore
verbatim from a summary-table access column when the document prints one, and
`""` when it does not. Composing a register's access out of its fields' would
still be a derivation nobody printed, so ticket 06 does not do it either: it
publishes the **fields'** own access verbatim, beside their bit ranges.

Ticket 06 attaches those bit fields here (`structure/bitfields.py` reads and
validates them), which is why they live on `RegisterRecord` rather than in a
file of their own: a bit field is only meaningful as part of a register, and a
register whose fields could not be read must still be published — with
`fields: []` and a recorded reason — rather than dropped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from datasheet_analyzer.config import REGISTERS_SCHEMA_VERSION
from datasheet_analyzer.models import (
    RawDocument,
    RegisterRecord,
    RegisterSet,
    RegisterWord,
    SectionNode,
    TableBlock,
)
from datasheet_analyzer.provenance import register_record_id
from datasheet_analyzer.structure.bitfields import attach_fields, field_table_register
from datasheet_analyzer.structure.confidence import grade_register_record
from datasheet_analyzer.structure.device_tables import (
    REGISTER,
    DeviceTable,
    read_device_tables,
    record_rejections,
)
from datasheet_analyzer.structure.units import normalize_text

log = logging.getLogger(__name__)

#: The named rules this module publishes as `RegisterWord.derivation`. They are
#: strings on disk, so they are constants here: a rule nobody can name is not a
#: derivation, and a rule spelled two ways is two rules (ADR 0005).
ADDRESS_DERIVATION = "parse_register_word"
RESET_COLUMN_DERIVATION = "register_table_reset"
RESET_HEADING_DERIVATION = "register_heading_reset"

#: A register word as datasheets print it: `0x1A04`, `1A04h`, `0X0`, or a bare
#: decimal. Anchored — a cell has to be *only* a word, so `0x00-0xFF` (an
#: address block) and `See Table 7-1` both read as unparseable rather than as
#: their first few digits.
_HEX_RE = re.compile(r"^(?:0[xX](?P<hx>[0-9A-Fa-f]+)|(?P<hs>[0-9A-Fa-f]+)[hH])$")
_DEC_RE = re.compile(r"^(?P<dec>\d+)$")

#: The register declaration heading TI's programmer's guides print above every
#: register's field table:
#:
#:     1.1 R0 Register (Offset = 0x0) [Reset = 0x0000]
#:     7.1.31 R72 Register (Offset = 0x48) [Reset = 0x0000]
#:
#: The offset is required (it is what the record joins on) and the reset is
#: optional, because a heading that states no reset must contribute nothing
#: rather than a zero.
_DECLARATION_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9_]*)\s+register\s*\(\s*offset\s*=\s*"
    r"(?P<offset>[0-9A-Fa-fxXhH]+)\s*\)"
    r"(?:\s*\[\s*reset\s*=\s*(?P<reset>[0-9A-Fa-fxXhH]+)\s*\])?",
    re.IGNORECASE,
)

#: A field-description table's caption names the register it belongs to
#: (`Table 1-3. R0 Register Field Descriptions`), which is how a declaration
#: found in a bare paragraph gets a page to cite. The reading itself lives in
#: `structure/bitfields.py` (`field_table_register`), which joins the same
#: caption to the same register for its fields: one caption, one reading.


def parse_register_word(text: str) -> int | None:
    """`0x1A04` / `1A04h` / `6660` as an integer, or `None`.

    Anchored on purpose: a cell that is not *entirely* a register word has no
    integer form, and inventing one out of its leading digits is how a lookup
    starts answering with the wrong register.

    Hex is recognised **only** by the marker the document printed — an explicit
    `0x` prefix or an `h` suffix. That is what makes a caller's string and a
    record's cell comparable at all: `dsa regs --addr 6660` has no document to
    take a base from, so a bare number has to mean the same thing on both
    sides, and decimal is the only reading a caller can spell. The cost is
    stated rather than hidden: a register map that prints bare hex (`0A`)
    publishes `value: null` for those cells and `dsa regs --addr` reaches them
    by their printed text instead. Widening that would mean guessing a base
    from the characters in a cell, which is precisely the confident-and-wrong
    move ADR 0005 forbids.
    """
    cleaned = normalize_text(text or "").strip()
    if not cleaned:
        return None
    match = _HEX_RE.match(cleaned)
    if match is not None:
        return int(match.group("hx") or match.group("hs"), 16)
    match = _DEC_RE.match(cleaned)
    if match is not None:
        return int(match.group("dec"))
    return None


@dataclass(frozen=True)
class RegisterDeclaration:
    """One printed register declaration heading, parsed.

    `page` is the page of the field-description table the declaration
    introduces, or `None` when the document has none to pin it to — a reset
    with no page is still recorded, and it says `p.?` like every other unpinned
    citation in this corpus rather than borrowing a page it was not read from.
    """

    name: str
    offset: int | None
    reset_verbatim: str
    reset: int | None
    printed: str
    page: int | None = None


def read_declarations(raw: RawDocument) -> list[RegisterDeclaration]:
    """Every register declaration heading the document prints, in printed order.

    The headings survive extraction as ordinary text (a whole era of
    layout-floor documents numbers no sub-section, ADR 0004), so this scans
    text rather than the section tree — and it scans two places, because the
    layout floor puts them in either one:

    - a table's **test-conditions preamble**, which is where the lines directly
      above a caption land. Those lines are part of that table's region, so the
      region's own page (`_region_page`) is the page they were printed on;
    - a section's title and paragraphs, where nothing pins the line directly.
      There the page comes from the register's own field-description table
      (`_field_table_pages`), which the heading introduces — and `None` when
      the document has none to pin it to.

    Measured on LMX1204: 17 of 35 declarations sit in a preamble and 12 more
    are pinned through their field table, so 29 of 35 resets cite an exact
    printed page and 6 honestly cite none. `page = None` is a first-class
    outcome here for the reason invariant 3 gives: a citation is right or it is
    absent, and a declaration in a bare paragraph the layout floor could not
    pin has no page to claim.

    Only headings that carry a **reset** are kept: the offset alone repeats
    what the summary table already printed.
    """
    pages = _field_table_pages(raw)
    out: list[RegisterDeclaration] = []
    for section in raw.sections:
        sources: list[tuple[str, int | None]] = [
            (section.full_title, None),
            *((para, None) for para in section.paragraphs),
        ]
        sources.extend(
            (table.conditions, _region_page(table))
            for table in section.tables
            if table.conditions
        )
        for text, page in sources:
            for match in _DECLARATION_RE.finditer(normalize_text(text)):
                reset_verbatim = (match.group("reset") or "").strip()
                if not reset_verbatim:
                    continue
                name = match.group("name")
                out.append(
                    RegisterDeclaration(
                        name=name,
                        offset=parse_register_word(match.group("offset")),
                        reset_verbatim=reset_verbatim,
                        reset=parse_register_word(reset_verbatim),
                        printed=match.group(0).strip(),
                        page=page if page is not None else pages.get(name.casefold()),
                    )
                )
    return out


def _field_table_pages(raw: RawDocument) -> dict[str, int]:
    """`{register name: printed page}` from field-description table regions.

    The declaration heading introduces the register's own field-description
    table (`Table 1-3. R0 Register Field Descriptions`), so that table's region
    page is where the heading was printed. A name two captions claim, or whose
    captions disagree on the page, is left out: an ambiguous page is no page,
    the same stance `provenance.resolve_source` takes on an ambiguous reference.
    """
    seen: dict[str, set[int]] = {}
    for section in raw.sections:
        for table in section.tables:
            name = field_table_register(table.caption)
            page = _region_page(table)
            if not name or page is None:
                continue
            seen.setdefault(name.casefold(), set()).add(page)
    return {name: next(iter(pages)) for name, pages in seen.items() if len(pages) == 1}


def _region_page(table: TableBlock) -> int | None:
    """The page a table's *region* was printed on — not the page it was pinned to.

    `TableBlock.page` is overwritten by `pagemap.pin_table_pages`, which finds
    the page whose text best matches the grid's cells. That is the right rule
    for a spec row and the wrong one for a preamble: a register field table
    whose cells are `R`, `R/W`, `0x0` and `RESERVED` matches half the document,
    and LMX1204's Table 1-25 pins to p.17 while it is printed on p.19. The row
    pages are *not* rewritten by pinning — the layout engine records the page
    each row was read from — so the first of them is the region's own page, and
    a declaration in the region's preamble was printed there too.
    """
    for page in table.row_pages:
        if page is not None:
            return page
    return table.page


def build_registerset(raw: RawDocument, part_number: str) -> RegisterSet:
    """Build a `RegisterSet` from every register-summary table of a document.

    Always returns a set, even an empty one — a document whose register table
    was rejected has a *finding*, and the reason is recorded here (where the
    read happened) into the same `rejection_reasons` list the reconstruction
    gate writes to. The publisher is what refuses to write `registers.json` for
    a set with no registers.

    Each published register then gains its **bit fields** where the document
    prints a readable field table for it (ticket 06) and `fields: []` plus a
    recorded reason where it does not; the coverage of that is reported in
    `n_field_sets` and in the set's warnings, never left to be noticed.
    """
    result = read_device_tables(raw, kind=REGISTER)
    if raw.extraction_stats is not None:
        record_rejections(raw.extraction_stats, result.rejections)

    declarations = read_declarations(raw)
    registers: list[RegisterRecord] = []
    for table in result.tables:
        registers.extend(_table_to_registers(table, raw, declarations))

    # Stable, addressable ids (ADR 0005): emission order is fully determined by
    # the document — section order, table order, row order — so a rebuild of
    # identical input reproduces every id exactly.
    for ordinal, record in enumerate(registers):
        record.id = register_record_id(ordinal)

    # Bit fields (ticket 06). Every register comes back with either a validated
    # field set or an empty one and a recorded reason; the field tables the
    # abstraction refused join the same `rejection_reasons` list the summary's
    # own rejections do.
    fields_result, field_warnings = attach_fields(registers, raw)
    if raw.extraction_stats is not None:
        record_rejections(raw.extraction_stats, fields_result.rejections)

    warnings = list(result.warnings)
    with_reset = sum(1 for record in registers if record.reset is not None)
    if registers and with_reset < len(registers):
        # Invariant 8's honesty clause: a caller listing reset values has to be
        # able to say what the document did not state, rather than quietly
        # showing a shorter list.
        warning = (
            f"reset value stated for {with_reset} of {len(registers)} registers; "
            f"the remaining {len(registers) - with_reset} publish reset: null"
        )
        log.info("%s: %s", part_number, warning)
        warnings.append(warning)

    for warning in field_warnings:
        log.info("%s: %s", part_number, warning)
    warnings.extend(field_warnings)

    return RegisterSet(
        schema_version=REGISTERS_SCHEMA_VERSION,
        part_number=part_number,
        doc_hash=raw.source.content_hash,
        registers=registers,
        n_reset_stated=with_reset,
        n_field_sets=sum(1 for record in registers if record.fields),
        warnings=warnings,
    )


def _table_to_registers(
    table: DeviceTable, raw: RawDocument, declarations: list[RegisterDeclaration]
) -> list[RegisterRecord]:
    """One accepted register-summary table as records, graded where it was read."""
    section = _section_for(raw, table.section_index)
    block = _block_for(section, table.table_index)
    out: list[RegisterRecord] = []
    for device in table.records:
        address = RegisterWord(
            verbatim=device.key,
            value=parse_register_word(device.key),
            page=device.page,
            derivation=ADDRESS_DERIVATION,
        )
        record = RegisterRecord(
            address=address,
            name=device.field("name"),
            access=device.field("access"),
            description=device.field("description"),
            reset=_reset_for(device.field("reset"), address, record_name=device.field("name"),
                             page=device.page, declarations=declarations),
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
            record.confidence = grade_register_record(record, block, section)
        out.append(record)
    return out


def _reset_for(
    printed: str,
    address: RegisterWord,
    *,
    record_name: str,
    page: int | None,
    declarations: list[RegisterDeclaration],
) -> RegisterWord | None:
    """The register's reset value, or `None` when the document states none.

    The summary table's own reset column wins — it is verbatim on the very row
    being published. Otherwise the register's printed declaration heading is
    consulted, matched on the **parsed offset**: a name match alone would let
    `R1` claim `R11`'s reset, and a heading that names a different register than
    the row it would attach to is refused rather than reconciled.
    """
    cell = (printed or "").strip()
    if cell:
        return RegisterWord(
            verbatim=cell,
            value=parse_register_word(cell),
            page=page,
            derivation=RESET_COLUMN_DERIVATION,
        )
    if address.value is None:
        return None
    hits = [
        decl for decl in declarations
        if decl.offset is not None and decl.offset == address.value
    ]
    if len(hits) != 1:
        if hits:
            log.info(
                "register %s: %d declarations claim offset %s — no reset published",
                record_name or address.verbatim, len(hits), address.verbatim,
            )
        return None
    declaration = hits[0]
    if record_name.strip() and declaration.name.casefold() != record_name.strip().casefold():
        log.warning(
            "register %s at %s is declared as %r — no reset published",
            record_name, address.verbatim, declaration.name,
        )
        return None
    return RegisterWord(
        verbatim=declaration.reset_verbatim,
        value=declaration.reset,
        page=declaration.page,
        evidence=declaration.printed,
        derivation=RESET_HEADING_DERIVATION,
    )


def _section_for(raw: RawDocument, section_index: int) -> SectionNode | None:
    """The section an accepted device table came from, by position.

    By position rather than by printed number, because a whole era of
    datasheets numbers no section at all (ADR 0004).
    """
    if not (0 <= section_index < len(raw.sections)):
        return None
    return raw.sections[section_index]


def _block_for(section: SectionNode | None, table_index: int) -> TableBlock | None:
    """The `TableBlock` an accepted device table came from, or `None`."""
    if section is None or not (0 <= table_index < len(section.tables)):
        return None
    return section.tables[table_index]
