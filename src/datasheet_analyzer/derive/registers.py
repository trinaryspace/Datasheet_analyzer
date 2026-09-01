"""Registers — `registers.json` and `dsa regs` (phase 6, ticket 05).

A register map is what an agent is for during **bring-up**, the way a pin
table is what it is for during schematic capture. This module is the second
consumer of the device-table abstraction and it is deliberately thin:
`structure/device_tables.py` identifies the summary table, maps its columns,
validates it and emits rows; this module turns those rows into
`RegisterRecord`s, parses the printed numbers into integers beside the
verbatim prints, and answers questions about the result.

Scope here is shape **(a)**, the register *summary* table — address, name,
reset, access. Per-register bit fields are the harder shape and are ticket
06's; `derive/bitfields.py` reads them and `_bit_fields` attaches an accepted
field set to the summary record whose name the field table's caption printed.
A register whose field table was refused keeps `fields: []` and is named in
the set's warnings, and a part that publishes no bit field at all gets
`dsa regs --field` saying so rather than answering nothing.

**The routing change lives here too.** `DocType.REGISTER_MAP` used to prefer
the degraded `pdf_text` backend for every vendor, which meant a register map
was paragraphs and nothing else: no tables, so no register question could be
answered at all. `vendor.select_backend` now routes it to `pdf_layout`
(`vendor.TABLE_COMPANION_TYPES`), and `PIPELINE_VERSION` is bumped so the
`(content_hash, backend)` extraction-cache entries for those documents
invalidate rather than serving the paragraph-only reading forever. Every other
companion type — errata, app notes — keeps `pdf_text` untouched.

Everything here obeys **invariant 8** (ADR 0007):

- every printed cell — address, name, reset, access — is **copied verbatim**
  (clause (a)); this module normalizes whitespace and nothing else;
- `address.value` and `reset.value` are computed from the print by
  `device_tables.parse_address`, a documented pure function (clause (b)), and
  stay `None` when the print does not parse. **A hex address that fails to
  parse stays verbatim-only rather than being guessed**, and the count of
  those is reported out loud rather than quietly dropped;
- a summary table that fails validation is rejected **whole**, with the
  reason recorded where `dsa status` already prints rejections;
- there is no model call anywhere in this path.

Two rules are worth stating because they are the ones a reader will test:

**A column the map does not print stays unfilled, and the set says so.** The
LMX1204 register map prints address and acronym and no reset or access column
at all. `reset.verbatim` is `""` for all 35 of its registers, and the set
carries a warning naming the table and the columns it never printed — because
a blank reset column read as "reset is zero" is exactly the confidently wrong
answer that breaks a bring-up sequence.

**`--addr` resolves by parsed value.** `0x1A04`, `0x1a04` and `6660` are one
question, so they find one register. An address the tool could not parse is
still findable by its printed form, and never by a value it does not have.

**A printed row that produced no register is counted out loud.** The
device-table layer rejects a table whose key column is mostly unreadable and
emits the rows whose key reads like an address; the row in between — a `TBD`,
a mangled glyph — is dropped, and this module says how many. A register
missing from a map reads as "this register does not exist" during bring-up,
which is the same lie as inventing its address.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.config import REGISTERS_SCHEMA_VERSION, get_settings
from datasheet_analyzer.derive.bitfields import iter_bit_field_tables
from datasheet_analyzer.derive.provenance import REGISTERS_ARTIFACT
from datasheet_analyzer.models import (
    DOC_KEY_LEN,
    BitField,
    Confidence,
    ExtractionStats,
    RawDocument,
    RegisterRecord,
    RegisterSet,
    RegisterValue,
)
from datasheet_analyzer.retrieve.results import Citation
from datasheet_analyzer.structure.device_tables import (
    KIND_REGISTER,
    DeviceRow,
    DeviceTableExtraction,
    DeviceTableResult,
    extract_device_tables,
    parse_address,
    record_rejections,
)

# `_column_is_hex` decides hex-ness for a printed number column *as a whole*
# rather than per cell, and the register validator already orders addresses
# with it. Importing the one implementation is deliberate: a second copy that
# disagreed would let `monotonic_addresses` accept an order `--addr` then
# cannot reproduce, which is the worst kind of drift — two parts of the tool
# reading one printed column as two different numbers.
from datasheet_analyzer.structure.device_tables import _column_is_hex as column_is_hex

log = logging.getLogger(__name__)

#: The pure function that produced each parsed integer, named the way a
#: `DerivedValue.derivation` names its rule. Nothing else fills these fields.
ADDRESS_DERIVATION = "parse_address"

#: Roles the register lexicon maps. `address` and `name` are required by the
#: lexicon; `reset` and `access` are printed by some maps and not by others.
ROLE_ADDRESS = "address"
ROLE_NAME = "name"
ROLE_RESET = "reset"
ROLE_ACCESS = "access"

#: Optional roles whose absence is worth saying out loud: a blank reset column
#: read as "reset is 0x00" is a wrong answer a driver gets written against.
OPTIONAL_ROLES: tuple[str, ...] = (ROLE_RESET, ROLE_ACCESS)


# --- building `registers.json` ---------------------------------------------


def _values(rows: Iterable[DeviceRow], role: str) -> list[str]:
    return [row.value(role) for row in rows]


def _register_value(text: str, *, hex_column: bool) -> RegisterValue:
    """One printed number -> verbatim + parsed integer, or verbatim only.

    Clause (b) of invariant 8 in its smallest form: `value` is
    `parse_address`'s output and nothing else, and `None` is a first-class
    result. A register address the tool guessed at is worse than one it admits
    it cannot read, because the guess is what a driver gets written against.
    """
    printed = (text or "").strip()
    if not printed:
        return RegisterValue()
    return RegisterValue(verbatim=printed, value=parse_address(printed, hex_default=hex_column))


def _record(
    row: DeviceRow, *, hex_addresses: bool, hex_resets: bool, doc_key: str = ""
) -> RegisterRecord:
    """One `DeviceRow` -> one `RegisterRecord`, every printed cell copied.

    `doc_key` is the document's content-hash prefix, which the record needs in
    order to compute an id unique inside its *part* (`register_record_id`).
    """
    return RegisterRecord(
        name=row.value(ROLE_NAME),
        address=_register_value(row.key, hex_column=hex_addresses),
        reset=_register_value(row.value(ROLE_RESET), hex_column=hex_resets),
        access=row.value(ROLE_ACCESS),
        section=row.section,
        table_index=row.table_index,
        row_index=row.row_index,
        doc_key=doc_key,
        page=row.page,
        row_verbatim=list(row.row_verbatim),
        confidence=row.confidence,
    )


def _table_label(result: DeviceTableResult) -> str:
    """How a warning names one accepted table: its caption, else its section."""
    caption = (result.caption or "").strip()
    if caption:
        return repr(caption)
    if result.section:
        return f"table {result.table_index} of §{result.section}"
    return "the register table"


def _missing_column_warnings(result: DeviceTableResult) -> list[str]:
    """Say which optional columns a map never printed, per accepted table.

    Not a defect and not a rejection — plenty of summary tables print only
    address and name. It is recorded because the alternative is a reader
    seeing an empty `reset` and concluding the datasheet says zero.
    """
    mapping = result.mapping
    if mapping is None:
        return []
    missing = [role for role in OPTIONAL_ROLES if role not in mapping.columns]
    if not missing:
        return []
    return [
        (
            f"{_table_label(result)} prints no {' or '.join(missing)} column; "
            f"those fields stay unfilled for its {len(result.rows)} registers"
        )
    ]


def _dropped_row_warning(result: DeviceTableResult) -> list[str]:
    """Say when an accepted table printed rows that produced no register.

    The device-table layer emits only rows whose key reads like an address,
    and it rejects the table outright when too few do. Between those two
    outcomes sits a printed row that carried a key nothing could read — a
    `TBD`, a mangled glyph — which is dropped from the record set. Dropping it
    silently is the same lie as guessing its address: a register missing from
    a map reads as "this register does not exist" during bring-up.

    Rows the layer *explains* (a band label, a continuation of the row above)
    are accounted for by its notes and are not losses, so only the remainder
    is reported.
    """
    unexplained = result.n_printed_rows - len(result.rows) - len(result.notes)
    if unexplained <= 0:
        return []
    return [
        (
            f"{_table_label(result)} printed {result.n_printed_rows} rows and produced "
            f"{len(result.rows)} registers; {unexplained} printed row(s) carried no "
            f"readable address and are not in this map"
        )
    ]


def _unparsed_warning(registers: Sequence[RegisterRecord]) -> list[str]:
    """Report the unparsed address population explicitly, never by omission.

    The phase plan's rule for every consumer that sorts or looks up by a
    parsed number: "3 of 47 rows could not be parsed" is an answer; silently
    holding 44 is not, because `dsa regs --addr` cannot find the other three
    and nothing would have said why.
    """
    unparsed = [r for r in registers if r.address.verbatim and r.address.value is None]
    if not unparsed:
        return []
    shown = ", ".join(r.address.verbatim for r in unparsed[:6])
    more = f", and {len(unparsed) - 6} more" if len(unparsed) > 6 else ""
    return [
        (
            f"{len(unparsed)} of {len(registers)} addresses did not parse to an integer "
            f"({shown}{more}); `--addr` finds those by their printed form only"
        )
    ]


def _bit_fields(raw: RawDocument) -> tuple[dict[str, tuple[BitField, ...]], list[str]]:
    """Every register in this document whose field table read whole.

    `derive/bitfields.py` accepts a field table whole or refuses it whole, so
    the only thing left to decide here is **which register a field set belongs
    to**, and the answer is the one the caption printed: `Table 1-6. R4
    Register Field Descriptions` attaches to the summary row named `R4`. A
    caption that names no register attaches to nothing.

    Two registers' worth of caution, both fail-closed:

    - a name carried by **two** field tables in one document is dropped, not
      merged — two printed breakdowns of one register are a question this
      module cannot answer, and answering it with the first would be a guess;
    - a register whose table was **refused** publishes no fields *and* is
      named in a warning, so an empty `fields` list is never mistaken for "the
      document printed no breakdown".
    """
    accepted: dict[str, tuple[BitField, ...]] = {}
    refused: dict[str, tuple[str, ...]] = {}
    duplicated: set[str] = set()
    for extraction in iter_bit_field_tables(raw):
        name = extraction.register_name
        if not name:
            continue
        if name in accepted or name in refused:
            duplicated.add(name)
            continue
        if extraction.accepted:
            accepted[name] = extraction.fields
        else:
            refused[name] = extraction.reasons
    for name in duplicated:
        accepted.pop(name, None)
        refused.pop(name, None)

    warnings: list[str] = []
    if refused:
        shown = "; ".join(f"{name}: {reasons[0]}" for name, reasons in sorted(refused.items())[:3])
        more = f", and {len(refused) - 3} more" if len(refused) > 3 else ""
        warnings.append(
            f"{len(refused)} register(s) print a bit-field table this tool could not read "
            f"whole, and publish no fields ({shown}{more})"
        )
    if duplicated:
        warnings.append(
            f"{len(duplicated)} register(s) are named by more than one bit-field table in "
            f"this document and publish no fields ({', '.join(sorted(duplicated))})"
        )
    return accepted, warnings


@dataclass(frozen=True)
class RegisterBuild:
    """What one document yielded: a register set, or nothing and why not.

    `registerset` is `None` when the document printed no summary table this
    tool could read — including the case where it printed one and validation
    rejected it. That is the honest artifact: no file at all rather than a
    half-read map, because a register missing from a map reads as "this
    register does not exist" during bring-up.
    """

    registerset: RegisterSet | None = None
    rejection_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    accepted_tables: int = 0

    @property
    def n_registers(self) -> int:
        return len(self.registerset.registers) if self.registerset else 0


def build_registers(raw: RawDocument, part_number: str = "") -> RegisterBuild:
    """Read one document's register summary table(s), or report there are none.

    Never raises: a document with no register map is the common case, not an
    error, and a rejected table is a recorded outcome rather than an
    exception. Hex-ness is decided per accepted table and per column — one
    reading for a whole printed column, so `0x0A` and `10` in the same column
    are 10 and 16, never 10 and 10.
    """
    extraction: DeviceTableExtraction = extract_device_tables(raw, kind=KIND_REGISTER)
    reasons = tuple(extraction.rejection_reasons)
    accepted = extraction.accepted
    if not extraction.rows:
        return RegisterBuild(registerset=None, rejection_reasons=reasons)

    registers: list[RegisterRecord] = []
    warnings: list[str] = []
    # What makes an id unique inside the *part*: LMX1204's two documents print
    # the same 35 registers at the same coordinates (`register_record_id`).
    doc_key = raw.source.content_hash[:DOC_KEY_LEN]
    for result in accepted:
        if not result.rows:
            continue
        hex_addresses = column_is_hex(row.key for row in result.rows)
        hex_resets = column_is_hex(_values(result.rows, ROLE_RESET))
        registers.extend(
            _record(row, hex_addresses=hex_addresses, hex_resets=hex_resets, doc_key=doc_key)
            for row in result.rows
        )
        warnings.extend(_missing_column_warnings(result))
        warnings.extend(_dropped_row_warning(result))
    warnings.extend(_unparsed_warning(registers))

    field_sets, field_warnings = _bit_fields(raw)
    if field_sets:
        registers = [
            record.model_copy(update={"fields": list(field_sets[record.name])})
            if record.name in field_sets
            else record
            for record in registers
        ]
    warnings.extend(field_warnings)

    registerset = RegisterSet(
        schema_version=REGISTERS_SCHEMA_VERSION,
        part_number=part_number,
        doc_hash=raw.source.content_hash,
        registers=registers,
        rejection_reasons=list(reasons),
        warnings=warnings,
    )
    return RegisterBuild(
        registerset=registerset,
        rejection_reasons=reasons,
        warnings=tuple(warnings),
        accepted_tables=len(accepted),
    )


def record_register_rejections(
    stats: ExtractionStats | None, build: RegisterBuild
) -> ExtractionStats | None:
    """Join a build's rejected register tables to the document's reasons.

    Delegates to the device-table layer's own recorder, so a refused register
    table lands exactly where a refused pin table and a refused parametric
    table land: `ExtractionStats.rejection_reasons`, which `dsa status`
    already prints.
    """
    return record_rejections(stats, build.rejection_reasons)


# --- reading and writing the artifact --------------------------------------


def write_registerset(doc_dir: Path, registerset: RegisterSet, *, shared: bool = False) -> Path:
    """Write `registers.json` beside the document's other artifacts.

    `shared` blanks `part_number` for the same reason `pins.json` and
    `specs.json` do: which part published a shared document first is an
    accident of ordering, and stamping it into the bytes would make two parts
    disagree about the file and rewrite it forever. Readers take the part from
    `manifest.part_number`.

    Written **atomically and only when the bytes change**, because
    `dsa batch --workers N` can have two jobs publishing the same shared
    document at once and a half-written file reads as a corrupt corpus.
    """
    target = Path(doc_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / REGISTERS_ARTIFACT
    payload = registerset.model_copy(update={"part_number": ""}) if shared else registerset
    text = payload.model_dump_json(indent=2)
    try:
        if path.read_text(encoding="utf-8") == text:
            return path
    except (OSError, ValueError):
        pass
    fd, tmp = tempfile.mkstemp(dir=target, prefix=f"{REGISTERS_ARTIFACT}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def load_registerset(doc_dir: Path) -> RegisterSet | None:
    """Read one document's `registers.json`; `None` when absent or unreadable.

    Unreadable warns and returns `None` rather than raising — one corrupt file
    must not take a part down, the rule every artifact reader follows.
    """
    path = Path(doc_dir) / REGISTERS_ARTIFACT
    if not path.is_file():
        return None
    try:
        return RegisterSet.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("unreadable %s: %s", path, exc)
        return None


@dataclass(frozen=True)
class PartRegisters:
    """One part's published register records, with the documents they came from."""

    part: str
    sets: tuple[tuple[str, RegisterSet], ...] = ()  # (document directory name, set)

    @property
    def registers(self) -> tuple[RegisterRecord, ...]:
        return tuple(reg for _doc, regset in self.sets for reg in regset.registers)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(w for _doc, regset in self.sets for w in regset.warnings)

    @property
    def has_bit_fields(self) -> bool:
        """Whether any published register carries a bit-field breakdown.

        Ticket 05 publishes summary rows only, so this is `False` for every
        corpus it builds. `dsa regs --field` reads it to tell "no register
        matches that field" apart from "no bit fields were extracted at all",
        which are different answers to a firmware engineer.
        """
        return any(reg.fields for reg in self.registers)


def load_part_registers(part_dir: Path, part: str = "") -> PartRegisters:
    """Every `registers.json` a built part references, wherever it was published.

    Documents may live under the part or once in the shared library store, so
    the manifest is what says where they are — the same resolution
    `publish.document_dirs` performs for every other artifact.
    """
    from datasheet_analyzer.publish import document_dirs, read_manifest

    part_dir = Path(part_dir)
    manifest = read_manifest(part_dir)
    if manifest is None:
        return PartRegisters(part=part or part_dir.name)
    dirs = document_dirs(manifest, part_dir=part_dir)
    sets: list[tuple[str, RegisterSet]] = []
    for source in manifest.documents:
        doc_dir = dirs.get(source.content_hash)
        if doc_dir is None:
            continue
        regset = load_registerset(doc_dir)
        if regset is not None:
            sets.append((doc_dir.name, regset))
    return PartRegisters(part=part or manifest.part_number or part_dir.name, sets=tuple(sets))


# --- lookup ----------------------------------------------------------------


def parse_query_address(text: str) -> int | None:
    """What `--addr 0x1A04` means as a number, or `None` when it means nothing.

    The same `parse_address` the records were built with, called **without**
    `hex_default`: a query has no column to decide its base from, so `10` is
    ten and `0x10` is sixteen. A bare `1A04` is genuinely ambiguous and parses
    to `None` — the lookup then falls back to the printed form, which finds the
    register only if that is what the datasheet actually printed.
    """
    return parse_address(text)


def _matches_address(record: RegisterRecord, *, query: str, value: int | None) -> bool:
    """Whether one register answers `--addr`, by value first, print second."""
    if value is not None and record.address.value is not None:
        return record.address.value == value
    return record.address.verbatim.strip().casefold() == query.strip().casefold()


def _matching_fields(record: RegisterRecord, term: str) -> list[int]:
    return [i for i, f in enumerate(record.fields) if term in f.name.casefold()]


@dataclass(frozen=True)
class RegisterHit:
    """One matching register, with the citation a reader verifies it by."""

    record: RegisterRecord
    citation: Citation
    matched_via: str = "all"
    field_indexes: tuple[int, ...] = ()

    @property
    def confidence(self) -> str:
        value = self.record.confidence
        return str(getattr(value, "value", value) or "") or Confidence.UNKNOWN.value

    @property
    def fields(self) -> list:
        """The bit fields this hit matched, or every field the register has."""
        if not self.field_indexes:
            return list(self.record.fields)
        return [self.record.fields[i] for i in self.field_indexes]

    def as_dict(self) -> dict:
        """The one JSON shape for a register hit — CLI and MCP both emit this."""
        rec = self.record
        return {
            "id": rec.id,
            "name": rec.name,
            "block": rec.block,
            "address": {"verbatim": rec.address.verbatim, "value": rec.address.value},
            "reset": {"verbatim": rec.reset.verbatim, "value": rec.reset.value},
            "access": rec.access,
            "width": rec.width,
            "fields": [f.model_dump(mode="json") for f in self.fields],
            "part": self.citation.part,
            "doc": self.citation.doc,
            "page": rec.page,
            "citation": self.citation.label,
            "matched_via": self.matched_via,
            "confidence": self.confidence,
            "address_derivation": ADDRESS_DERIVATION if rec.address.value is not None else "",
        }


def find_registers(
    part_registers: PartRegisters,
    *,
    name: str = "",
    addr: str = "",
    field: str = "",
) -> list[RegisterHit]:
    """Registers matching name / address / bit-field, in printed order.

    The three filters are conjunctive — `--name CLK --addr 0x19` is one
    question, not two — and `matched_via` says which of them decided the hit,
    strongest evidence first, so a caller can tell a direct address hit from a
    name substring.
    """
    wanted_name = (name or "").strip().casefold()
    wanted_addr = (addr or "").strip()
    wanted_field = (field or "").strip().casefold()
    addr_value = parse_query_address(wanted_addr) if wanted_addr else None
    if wanted_field:
        matched_via = "field"
    elif wanted_addr:
        matched_via = "address"
    elif wanted_name:
        matched_via = "name"
    else:
        matched_via = "all"

    hits: list[RegisterHit] = []
    for doc, regset in part_registers.sets:
        for record in regset.registers:
            if wanted_name and wanted_name not in record.name.casefold():
                continue
            if wanted_addr and not _matches_address(record, query=wanted_addr, value=addr_value):
                continue
            indexes = _matching_fields(record, wanted_field) if wanted_field else []
            if wanted_field and not indexes:
                continue
            hits.append(
                RegisterHit(
                    record=record,
                    citation=Citation(
                        doc=doc,
                        doc_hash=regset.doc_hash,
                        section=record.section,
                        page_start=record.page,
                        page_end=record.page,
                        part=part_registers.part,
                        needle=record.name or record.address.verbatim,
                    ),
                    matched_via=matched_via,
                    field_indexes=tuple(indexes),
                )
            )
    return hits


def format_register_hits(
    hits: Sequence[RegisterHit], limit: int = 40, *, show_part: bool = False
) -> str:
    """Render register hits for a human or an agent, always cited.

    A column the map never printed shows as nothing at all rather than as a
    placeholder value: the line says what the page says.
    """
    if not hits:
        return "No matching registers."
    lines: list[str] = []
    for hit in hits[:limit]:
        rec = hit.record
        prefix = f"[{hit.citation.part}] " if show_part and hit.citation.part else ""
        parts = [f"{prefix}{rec.address.verbatim or '?'}  {rec.name or '(unnamed)'}"]
        if rec.reset.verbatim:
            parts.append(f"reset {rec.reset.verbatim}")
        if rec.access:
            parts.append(f"access {rec.access}")
        parts.append(f"({hit.citation.pages})")
        lines.append("  ".join(parts))
        for bit in hit.fields:
            bits = bit.bits.verbatim or "?"
            lines.append(f"    [{bits}] {bit.name}  {bit.access}  {bit.description}".rstrip())
    if len(hits) > limit:
        lines.append(f"... and {len(hits) - limit} more matches")
    return "\n".join(lines)


def no_registers_message(part: str) -> str:
    """Why a built part has no register map, said out loud rather than as silence.

    An empty result from a part that never published `registers.json` reads as
    "this part has no registers", which is a different claim entirely. The two
    states are told apart here because they lead a reader to different next
    steps.
    """
    return (
        f"{part}: no register map was published for this part. Either no "
        f"document registered for it prints a register summary table this "
        f"tool could read, or the candidate table failed validation and was "
        f"rejected whole — `dsa status` lists the rejection reasons. Nothing "
        f"partial is published for a register map."
    )


def no_bit_fields_message(part: str) -> str:
    """`--field` against a corpus whose registers carry no bit-field breakdown."""
    return (
        f"{part}: no bit-field records are published for this part, so "
        f"`--field` cannot match anything. The register summary (address, "
        f"name, reset, access) is published; the per-register bit breakdown "
        f"is not."
    )


# --- CLI -------------------------------------------------------------------


def _part_dirs(args: argparse.Namespace) -> tuple[list[tuple[str, Path]], str]:
    """`([(part, dir)], "")` for the requested scope, or `([], reason)`.

    Scope resolution is `retrieve/scope.py`'s rule (ADR 0006: exactly one of
    `--part` / `--project`), reused rather than re-decided here. Registers are
    read off published artifacts rather than through `Retriever`, so this
    resolves to directories instead of to a retriever.
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
    dirs = part_dirs(loaded, settings.parts_dir)
    return [(d.name, d) for d in dirs], ""


def cli_regs(args: argparse.Namespace) -> int:
    """`dsa regs --part X [--name] [--addr 0x1A04] [--field] [--json]`.

    Exit codes follow the other deterministic lookups exactly: 0 for hits,
    1 for an honest no-match, 2 for a scope that could not be resolved. A part
    that published no `registers.json` is *not* a no-match — it is told apart
    from one on stderr, because the two mean different things to someone
    deciding whether to open the PDF.
    """
    parts, reason = _part_dirs(args)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    show_part = bool((getattr(args, "project", "") or "").strip())
    name = getattr(args, "name", "") or ""
    addr = getattr(args, "addr", "") or ""
    wanted_field = getattr(args, "field", "") or ""

    hits: list[RegisterHit] = []
    without: list[str] = []
    fieldless: list[str] = []
    warnings: list[str] = []
    for part, part_dir in parts:
        part_registers = load_part_registers(part_dir, part)
        if not part_registers.sets:
            without.append(part)
            continue
        if wanted_field and not part_registers.has_bit_fields:
            fieldless.append(part)
        warnings.extend(part_registers.warnings)
        hits.extend(find_registers(part_registers, name=name, addr=addr, field=wanted_field))

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for part in without:
        print(no_registers_message(part), file=sys.stderr)
    for part in fieldless:
        print(no_bit_fields_message(part), file=sys.stderr)

    if getattr(args, "json", False):
        payload = {
            "part": getattr(args, "part", ""),
            "project": getattr(args, "project", ""),
            "query": {
                "name": name,
                "addr": addr,
                "addr_value": parse_query_address(addr) if addr.strip() else None,
                "field": wanted_field,
            },
            "hits": [h.as_dict() for h in hits],
            "parts_without_registers": without,
            "parts_without_bit_fields": fieldless,
            "warnings": warnings,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 1
    print(format_register_hits(hits, show_part=show_part))
    return 0 if hits else 1
