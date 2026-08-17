"""Device tables — one abstraction for pin tables and register summaries.

Phase 6, ticket 03. A pin table and a register-summary table are the same
structural animal: wide, repetitive, and **keyed by a first column** whose
cells are designators rather than prose. Building one abstraction with two
consumers is less code than two parsers and — the reason that matters here — a
single test surface for the one thing that can silently corrupt a derived
artifact: a table that was read as a device table when it was not.

The pipeline is four named steps, in this order:

1. **identify** — is this table a device table, and of which kind? Two routes,
   both driven by the checked-in lexicon (`registry/device_tables.yaml`, never
   a string in this file): its *headers* declare it (the key column plus at
   least `MIN_HEADER_FIELDS` fields in all), or its *caption* names it and the
   columns are then taken positionally. A table neither route claims is not a
   device table and is **not** a rejection either — a parametric spec table
   must not fill a manifest with reasons about not being a pin table.
2. **map columns** — header match first, positional fallback second. The
   fallback fires only when the headers matched *nothing*, because filling the
   gaps of a partly-recognised header row would be guessing at exactly the
   moment the document told us something we did not understand. A header the
   lexicon does not know leaves its field unmapped, and closing that gap is a
   YAML edit.
3. **validate** — a keyed row set, key cells shaped like keys, unique keys, and
   monotonic addresses where the kind says so. **A failure rejects the whole
   table with a recorded reason**; nothing partial is ever emitted. This is the
   same honesty contract `pdf_layout`'s reconstruction gate already applies to
   parametric tables, and `record_rejections` puts the reasons in the very same
   place (`ExtractionStats.rejection_reasons`) so device tables are as
   measurable as parametric ones.
4. **emit** — one `DeviceRecord` per key, carrying full provenance (section,
   table index, row index, page) and the row exactly as printed.

Four rules are load-bearing and deliberate:

- **A wrapped row is one row.** A printed device table breaks a long
  description — and a long key list, and sometimes the name itself — over
  several lines, and the layout floor hands each line back as its own grid row
  (the ticket-09 rowspan materialization even replicates the key cell into
  them). Read literally that is a duplicate key, and a duplicate key rejects
  the whole table: a real 322-pin table would be thrown away because its
  descriptions are long. So a row that prints **no identity field** (the column
  the lexicon names in `identity:`) is read as a continuation of the row above:
  its text appends, and any key-shaped keys in its key cell join that row. A row
  that *does* print an identity is a new entry even when its key cell repeats —
  unless the row above left that identity **mid-list** (a trailing `,`), which
  is how a wrapped name list looks on the page. That narrowness is the point:
  the reading only ever merges lines the page shows as one entry, and
  everything else stays a duplicate and rejects the table. A comma is the only
  marker precisely because it is the only one that cannot end a mnemonic —
  `VREF+` and `RESET-` are finished names, and reading the next line as their
  continuation would fuse two pins into one and quietly drop a pin.
- **Multi-value key cells expand.** `A1, A2, B1` and `A1-A4` are four pins that
  happen to share a row, and a designer grepping for `A3` must find it. Every
  expanded record keeps its source row's provenance and the cell as printed
  (`key_verbatim`), so an expansion is always traceable back to the one line
  the datasheet printed. A register address is deliberately **not** expanded:
  `0x00-0xFF` is one block, and 256 fabricated records is the confident-and-
  wrong failure ADR 0005 exists to prevent.
- **Nothing here mutates a verbatim cell.** Records quote the grid; the numeric
  reading of an address exists only inside the order check.
- **A count cross-check warns, it does not reject** (ADR 0005, "Decided: a
  pin-count mismatch warns, and is recorded"): the expected count is itself
  parsed from prose and is no more reliable than the table it would suppress.
  `cross_check_count` returns that warning; the caller records it.

This ticket ships no consumer. Publication shape (`pins.json`,
`registers.json`) and the per-record confidence grade belong to the consumers
(tickets 04 and 05), which is why nothing here is a pydantic model: a schema is
a promise to a reader on disk, and no reader exists yet.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path

import yaml

from datasheet_analyzer.models import (
    ExtractionStats,
    RawDocument,
    SectionNode,
    TableBlock,
)
from datasheet_analyzer.structure.aliases import padded
from datasheet_analyzer.structure.units import normalize_text

log = logging.getLogger(__name__)

LEXICON_PATH = Path(__file__).resolve().parent.parent / "registry" / "device_tables.yaml"

#: The two kinds the shipped lexicon defines. They are *data* — a third kind is
#: a YAML entry — and these names exist so a consumer can ask for one by name
#: without spelling a string the lexicon owns.
PIN = "pin"
REGISTER = "register"

#: How many of a kind's fields a header row must name before the header route
#: claims the table — the key column plus at least one more. One column is not
#: a table shape, it is a coincidence: an ordering-information table with a
#: lone `No.` column would otherwise read as a pin table.
MIN_HEADER_FIELDS = 2

#: The share of keyed rows whose key cell must actually look like a key. Below
#: it the "table" is prose that happens to be laid out in columns, and it is
#: rejected — the device-table half of the no-hallucinated-tables guarantee.
KEY_SHAPE_MIN = 0.6

#: The largest key range one cell may expand into. A pin row spanning more than
#: a package's worth of balls is a misread cell, not a record set; it is kept
#: whole and the table says so rather than emitting hundreds of inventions.
MAX_EXPANSION = 256

#: Row index of a record read out of the block's header row. `pdf_layout` takes
#: the first row of every table region as the header row, so a table that
#: prints no headers at all puts its first *data* row there. Reading it as data
#: recovers that row instead of losing it, and `-1` says exactly where it came
#: from rather than colliding with `grid[0]`.
HEADER_ROW_INDEX = -1

#: Prefix of every reason this module contributes to a document's
#: `ExtractionStats`, so a device-table rejection is never mistaken for a
#: reconstruction-gate one.
REJECTION_PREFIX = "device-table"

#: Cap on how many device-table reasons one document records. Mirrors the
#: layout engine's own cap: a manifest is a summary, not a log.
MAX_RECORDED_REASONS = 8

#: What the end of an *unfinished* identity cell looks like. A pin row printing
#: `SERDOUT0+,` has not finished naming itself, so the next line — which
#: repeats the same key cell — is the rest of that name rather than a second
#: pin. Nothing else lets a row with its own identity be absorbed.
#:
#: Deliberately the **list separator alone**. `-`, `+` and `/` all terminate
#: ordinary mnemonics (`RESET-`, `VREF+`, `CS/`), so treating them as "this
#: name is unfinished" misfires on a whole class of real tables: a misread grid
#: printing `A1 VREF+` then `A1 VREF-` would be absorbed into a single fused
#: record — one pin lost, two names concatenated into a string the page never
#: printed — instead of rejecting whole on the duplicate key. A partial pin
#: table published confidently is exactly the failure ADR 0005 exists to
#: prevent; a whole-table rejection with a recorded reason is the honest one.
#: A comma cannot end a mnemonic, which is what makes it safe to read as
#: "more of this name follows".
CONTINUATION_MARKERS = (",",)

_MARKER_RE = re.compile(r"\(\d+\)")
_WS = re.compile(r"\s+")

# A multi-value key cell separates its parts with commas or semicolons, and
# each part may be a range. `units.normalize_text` has already folded en/em/
# minus dashes to "-" by the time these run.
_SPLIT_RE = re.compile(r"\s*[,;]\s*")
_RANGE_RE = re.compile(r"^(?P<lo>[A-Za-z]*\d+)\s*(?:-|to|through)\s*(?P<hi>[A-Za-z]*\d+)$")
_DESIGNATOR_RE = re.compile(r"^(?P<alpha>[A-Za-z]*)(?P<digits>\d+)$")


def normalize_header(text: str) -> str:
    """A header cell reduced to the form the lexicon is keyed on.

    Lowercased, footnote markers dropped, trailing colon removed, whitespace
    collapsed. Deliberately *not* stripped of punctuation: `no.` and `i/o` are
    the abbreviations real datasheets print, and they are what distinguishes a
    pin column from a paragraph.
    """
    cleaned = _MARKER_RE.sub(" ", text or "").strip()
    cleaned = cleaned.rstrip(":").strip()
    return _WS.sub(" ", cleaned).lower()


@dataclass(frozen=True)
class DeviceSpec:
    """One kind of device table, as the checked-in lexicon describes it."""

    kind: str
    key_field: str
    fields: tuple[str, ...]
    headers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    captions: tuple[str, ...] = ()
    key_shape: re.Pattern[str] | None = None
    expand_key: bool = False
    monotonic_key: bool = False
    key_numeric: str = ""
    #: The column that declares "this row is a new entry" (`identity:` in the
    #: lexicon). `""` switches the wrapped-row reading off for this kind, which
    #: is the conservative default: a kind that has not said which column
    #: identifies a row gets every printed line as its own record, exactly as
    #: before.
    identity_field: str = ""

    def field_for_header(self, header: str) -> str:
        """The field a header cell names, or `""` when the lexicon has no entry.

        Whole-header match: `Part Number` is not a pin column. Fields are tried
        in printed order so a table declaring two fields with the same word
        resolves the same way every time.
        """
        key = normalize_header(header)
        if not key:
            return ""
        for name in self.fields:
            if key in self.headers.get(name, ()):
                return name
        return ""

    def caption_claims(self, text: str) -> str:
        """The caption phrase `text` contains, or `""`.

        Longest match wins, for the same reason the alias lexicon prefers it:
        the more specific phrase is the more of the caption it explains.
        """
        haystack = padded(text)
        hits = [phrase for phrase in self.captions if padded(phrase) in haystack]
        return max(hits, key=len) if hits else ""

    def key_shaped(self, key: str) -> bool:
        """True when one key cell looks like this kind's key.

        A lexicon entry with no `key_shape` declines to judge — everything
        passes, and the table is trusted to its other validations.
        """
        if self.key_shape is None:
            return True
        return bool(self.key_shape.match(key.strip()))

    def key_number(self, key: str) -> int | None:
        """The key read as a number, or `None` when it cannot be.

        Used only for the monotonic-order check. A key that will not read as a
        number is not an error — it is simply not orderable, and the table
        reports how many it skipped rather than pretending it checked them.
        """
        text = key.strip()
        if not text or not self.key_numeric:
            return None
        base = 16 if self.key_numeric == "hex" else 10
        if base == 16:
            text = text[2:] if text[:2].lower() == "0x" else text
            text = text[:-1] if text[-1:].lower() == "h" else text
        try:
            return int(text, base)
        except ValueError:
            return None


@dataclass(frozen=True)
class DeviceLexicon:
    """The loaded `device_tables.yaml`, in file order."""

    specs: tuple[DeviceSpec, ...] = ()

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(spec.kind for spec in self.specs)

    def by_kind(self, kind: str) -> DeviceSpec | None:
        key = (kind or "").strip().lower()
        for spec in self.specs:
            if spec.kind == key:
                return spec
        return None

    @classmethod
    def from_mapping(cls, data: dict | None) -> DeviceLexicon:
        """Build from parsed YAML. A malformed entry is warned about and skipped.

        One bad kind must not take the whole lexicon — and with it every device
        table of every other kind — down, the same stance `aliases.py` takes.
        """
        specs: list[DeviceSpec] = []
        for kind, body in (data or {}).items():
            if not isinstance(body, dict):
                log.warning("skipping malformed device-table entry %r: not a mapping", kind)
                continue
            columns = body.get("columns")
            key_field = str(body.get("key") or "")
            if not isinstance(columns, dict) or not columns:
                log.warning("skipping device-table entry %r: no columns", kind)
                continue
            if key_field not in columns:
                log.warning(
                    "skipping device-table entry %r: key %r is not one of its columns",
                    kind, key_field,
                )
                continue
            headers = {
                str(name): tuple(normalize_header(h) for h in (phrases or []))
                for name, phrases in columns.items()
            }
            pattern: re.Pattern[str] | None = None
            shape = body.get("key_shape")
            if shape:
                try:
                    pattern = re.compile(str(shape))
                except re.error as exc:
                    log.warning(
                        "skipping device-table entry %r: bad key_shape %r (%s)",
                        kind, shape, exc,
                    )
                    continue
            captions = body.get("captions") or []
            if isinstance(captions, str):
                captions = [captions]
            identity_field = str(body.get("identity") or "")
            if identity_field and identity_field not in columns:
                # Named a column that does not exist: the wrapped-row reading
                # would silently never fire, so say so and fall back to off.
                log.warning(
                    "device-table entry %r: identity %r is not one of its columns",
                    kind, identity_field,
                )
                identity_field = ""
            specs.append(
                DeviceSpec(
                    kind=str(kind).strip().lower(),
                    key_field=key_field,
                    identity_field=identity_field,
                    fields=tuple(str(name) for name in columns),
                    headers=headers,
                    captions=tuple(str(c) for c in captions),
                    key_shape=pattern,
                    expand_key=bool(body.get("expand_key")),
                    monotonic_key=bool(body.get("monotonic_key")),
                    key_numeric=str(body.get("key_numeric") or ""),
                )
            )
        return cls(specs=tuple(specs))

    @classmethod
    def read(cls, path: Path | None = None) -> DeviceLexicon:
        """Parse a lexicon file; an unreadable one degrades to an empty one.

        An empty lexicon identifies no table at all, which is the honest
        degradation: no device tables rather than device tables read by a rule
        nobody can see.
        """
        path = Path(path) if path else LEXICON_PATH
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            log.warning("device-table lexicon unavailable (%s: %s) — no device tables", path, exc)
            return cls()
        return cls.from_mapping(data)


@cache
def load_device_lexicon(path: Path | None = None) -> DeviceLexicon:
    """The shipped lexicon, parsed once per process (or one at `path`)."""
    return DeviceLexicon.read(path)


def clear_device_lexicon_cache() -> None:
    """Test hook: re-read the lexicon file on the next `load_device_lexicon`."""
    load_device_lexicon.cache_clear()


@dataclass(frozen=True)
class ColumnMap:
    """Which grid column holds which field of the target schema.

    `via` is `"header"` when the table's own header row declared the columns
    and `"positional"` when they were taken in the lexicon's printed order from
    a table that declared nothing. `missing` is what neither route filled —
    the honest half of the map, and the list a lexicon edit shortens.
    """

    kind: str
    columns: dict[str, int] = field(default_factory=dict)
    via: str = "header"
    header_row_is_data: bool = False
    missing: tuple[str, ...] = ()

    def index(self, name: str) -> int | None:
        return self.columns.get(name)


@dataclass(frozen=True)
class DeviceRecord:
    """One row of a device table, keyed and cited.

    `key` is one value even when the printed cell held several: `A1, A2` emits
    two records, both quoting the cell they came from in `key_verbatim`.
    `fields` holds the **non-key** columns the table actually had — the key
    lives in `key` — and `ColumnMap.missing` names the columns it did not, so
    an absent column is never confused with an empty cell. `row_verbatim` is
    the printed row exactly as extracted; nothing here rewrites a cell.
    """

    kind: str
    key: str
    key_verbatim: str
    fields: dict[str, str] = field(default_factory=dict)
    section: str = ""
    table_index: int = 0
    row_index: int = 0
    page: int | None = None
    row_verbatim: tuple[str, ...] = ()

    def field(self, name: str) -> str:
        """The record's value for `name`; `""` when the table had no such column."""
        return self.fields.get(name, "")


@dataclass(frozen=True)
class DeviceTableRejection:
    """A table the abstraction claimed and then refused, with the reason why.

    Only a table some route *identified* can be rejected. A parametric spec
    table is not rejected, it is simply not a device table, and recording it
    would bury the real findings.
    """

    kind: str
    section: str
    table_index: int
    reason: str
    page: int | None = None

    def describe(self) -> str:
        """The one line this rejection contributes to `ExtractionStats`."""
        where = f"§{self.section}" if self.section else "(unnumbered)"
        page = f" p.{self.page}" if self.page is not None else ""
        return (
            f"{REJECTION_PREFIX} ({self.kind}) {where} table {self.table_index}"
            f"{page}: {self.reason}"
        )


@dataclass(frozen=True)
class DeviceTable:
    """One accepted device table: its records, its map, and what it could not read."""

    kind: str
    section: str
    table_index: int
    column_map: ColumnMap
    records: list[DeviceRecord] = field(default_factory=list)
    unkeyed_rows: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()
    page: int | None = None
    #: Which of the document's sections this table came from, by position.
    #: `section` above is the *printed* number, and a whole era of datasheets
    #: prints none (ADR 0004), so a consumer that needs the section back — to
    #: grade a record against the grid it was read from, say — cannot look it
    #: up by number. `-1` when the table was read outside a document walk.
    section_index: int = -1


@dataclass(frozen=True)
class DeviceTableSet:
    """Every device table of one document — accepted, rejected, and warned about.

    A rejection is not an absence: `records` holds only what was accepted, and
    `rejections` is what a caller must record so the gap is measurable rather
    than invisible (`record_rejections`).
    """

    kind: str = ""
    tables: list[DeviceTable] = field(default_factory=list)
    rejections: list[DeviceTableRejection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def records(self) -> list[DeviceRecord]:
        return [record for table in self.tables for record in table.records]

    @property
    def n_candidates(self) -> int:
        return len(self.tables) + len(self.rejections)

    @property
    def n_accepted(self) -> int:
        return len(self.tables)

    @property
    def n_rejected(self) -> int:
        return len(self.rejections)

    def describe(self) -> str:
        """The sentence a consumer prints about its device-table coverage."""
        if not self.n_candidates:
            return "no device tables found"
        return (
            f"{self.n_accepted} of {self.n_candidates} device tables accepted, "
            f"{len(self.records)} records"
        )


def identify_table(
    table: TableBlock,
    *,
    section_title: str = "",
    kind: str = "",
    lexicon: DeviceLexicon | None = None,
) -> str:
    """The device-table kind this table is, or `""` when it is not one.

    Two routes, tried for every kind, best score first (ties break on lexicon
    order, so identification is reproducible):

    - **headers declare it** — the key column's header plus at least
      `MIN_HEADER_FIELDS` of the kind's fields in all;
    - **a caption names it** — a caption phrase appears in the table's caption
      or, for the captionless layout-floor era, in its section title.

    `kind` restricts the question to one kind, for a consumer that only wants
    pins. Identification is not acceptance: every candidate still has to pass
    validation, which is what stops a caption from smuggling prose in.
    """
    lexicon = load_device_lexicon() if lexicon is None else lexicon
    best_kind, best_score = "", 0
    for spec in lexicon.specs:
        if kind and spec.kind != kind.strip().lower():
            continue
        matched = {
            spec.field_for_header(header) for header in table.headers
        } - {""}
        if spec.key_field in matched and len(matched) >= MIN_HEADER_FIELDS:
            score = len(matched) + MIN_HEADER_FIELDS  # the header route leads
        elif spec.caption_claims(table.caption) or spec.caption_claims(section_title):
            score = 1
        else:
            continue
        if score > best_score:
            best_kind, best_score = spec.kind, score
    return best_kind


def map_columns(spec: DeviceSpec, table: TableBlock) -> ColumnMap:
    """Map the table's columns onto the kind's schema.

    Header match first. The positional fallback fires **only** when the header
    row named nothing at all — a table whose headers are half understood has
    told us something we did not follow, and filling the rest by position would
    be a guess dressed as a reading. When the fallback fires and the header row
    itself looks like data (`pdf_layout` puts the first row of every region in
    `headers`, so a table printing no header row puts its first *pin* there),
    the map says so and that row is read as data instead of discarded.
    """
    n_cols = max(table.n_cols, len(table.headers))
    columns: dict[str, int] = {}
    for index, header in enumerate(table.headers):
        name = spec.field_for_header(header)
        if name and name not in columns:
            columns[name] = index

    via = "header"
    header_row_is_data = False
    if not columns:
        via = "positional"
        for offset, name in enumerate(spec.fields):
            if offset < n_cols:
                columns[name] = offset
        key_index = columns.get(spec.key_field)
        header_row_is_data = (
            key_index is not None
            and len(table.headers) > key_index
            and any(
                spec.key_shaped(key)
                for key in expand_keys(table.headers[key_index], expand=spec.expand_key)
            )
        )

    missing = tuple(name for name in spec.fields if name not in columns)
    return ColumnMap(
        kind=spec.kind,
        columns=columns,
        via=via,
        header_row_is_data=header_row_is_data,
        missing=missing,
    )


def expand_keys(cell: str, *, expand: bool = True, limit: int = MAX_EXPANSION) -> list[str]:
    """The individual keys one key cell holds.

    `A1, A2, B1` is three pins and `A1-A4` is four; both are one printed row,
    and a designer who greps for `A3` must find it. Expansion is deliberately
    literal — a range expands only when both endpoints share an alphabetic
    prefix and count upward, so `RXA-CLK` is one key and never a range.

    `expand=False` (a register address) returns the cell as a single key: an
    address range names a block, and turning it into 256 records would invent
    every one of them. A cell that would expand past `limit` is likewise kept
    whole; the caller reports it.
    """
    text = normalize_text(cell or "")
    if not text:
        return []
    if not expand:
        return [text]

    keys: list[str] = []
    for part in _SPLIT_RE.split(text):
        part = part.strip()
        if not part:
            continue
        span = _expand_range(part, limit)
        if span is None:
            keys.append(part)
        else:
            keys.extend(span)
    return keys


def _range_span(part: str) -> tuple[str, int, int, int] | None:
    """`(prefix, first, last, printed width)` when `part` is a key range.

    A range is two designators sharing an alphabetic prefix and counting
    upward — nothing else. `RXA-CLK` has no digits, `A1-B4` crosses prefixes,
    and both are names that happen to hold a hyphen.
    """
    match = _RANGE_RE.match(part)
    if not match:
        return None
    lo, hi = _DESIGNATOR_RE.match(match.group("lo")), _DESIGNATOR_RE.match(match.group("hi"))
    if lo is None or hi is None:
        return None
    prefix = lo.group("alpha")
    if prefix.lower() != hi.group("alpha").lower():
        return None
    start, end = int(lo.group("digits")), int(hi.group("digits"))
    if end < start:
        return None
    width = len(lo.group("digits")) if lo.group("digits").startswith("0") else 0
    return prefix, start, end, width


def _expand_range(part: str, limit: int) -> list[str] | None:
    """`A1-A4` as four keys; `None` when this part is not a range, or is one
    too wide to believe (the caller reports that case)."""
    span = _range_span(part)
    if span is None:
        return None
    prefix, start, end, width = span
    if (end - start + 1) > limit:
        return None
    return [f"{prefix}{n:0{width}d}" if width else f"{prefix}{n}" for n in range(start, end + 1)]


def read_device_table(
    section: SectionNode,
    table: TableBlock,
    table_index: int,
    *,
    kind: str = "",
    lexicon: DeviceLexicon | None = None,
) -> tuple[DeviceTable | None, DeviceTableRejection | None]:
    """Identify → map → validate → emit, for one table.

    Returns `(table, None)` when the table is a device table and passed every
    validation, `(None, rejection)` when it was claimed and refused, and
    `(None, None)` when no route claimed it — which is not a finding about the
    table and is deliberately not recorded as one.
    """
    lexicon = load_device_lexicon() if lexicon is None else lexicon
    claimed = identify_table(
        table, section_title=section.full_title, kind=kind, lexicon=lexicon
    )
    spec = lexicon.by_kind(claimed) if claimed else None
    if spec is None:
        return None, None

    def _reject(reason: str) -> tuple[None, DeviceTableRejection]:
        return None, DeviceTableRejection(
            kind=spec.kind,
            section=section.number,
            table_index=table_index,
            reason=reason,
            page=table.page if table.page is not None else section.page_start,
        )

    column_map = map_columns(spec, table)
    key_index = column_map.index(spec.key_field)
    if key_index is None:
        return _reject(f"no {spec.key_field} column")

    records, unkeyed, warnings = _emit(
        spec, column_map, key_index, section, table, table_index
    )
    reason = _validate(spec, records, unkeyed)
    if reason:
        return _reject(reason)

    return (
        DeviceTable(
            kind=spec.kind,
            section=section.number,
            table_index=table_index,
            column_map=column_map,
            records=records,
            unkeyed_rows=tuple(unkeyed),
            warnings=tuple(warnings),
            page=table.page if table.page is not None else section.page_start,
        ),
        None,
    )


def read_device_tables(
    raw: RawDocument,
    *,
    kind: str = "",
    lexicon: DeviceLexicon | None = None,
    expected_count: int | None = None,
) -> DeviceTableSet:
    """Every device table of one document, accepted and rejected.

    `pdf_text` documents are skipped for the reason `build_specset` skips them:
    that backend is explicitly degraded and carries no trusted tables, so a
    device table read out of one would be a table nobody extracted.
    """
    result = DeviceTableSet(kind=kind)
    if raw.extractor == "pdf_text":
        return result
    lexicon = load_device_lexicon() if lexicon is None else lexicon
    for section_index, section in enumerate(raw.sections):
        for index, table in enumerate(section.tables):
            accepted, rejected = read_device_table(
                section, table, index, kind=kind, lexicon=lexicon
            )
            if accepted is not None:
                result.tables.append(replace(accepted, section_index=section_index))
                result.warnings.extend(accepted.warnings)
            elif rejected is not None:
                result.rejections.append(rejected)
    if expected_count is not None:
        warning = cross_check_count(result.records, expected_count, kind=kind or result.kind)
        if warning:
            result.warnings.append(warning)
    return result


@dataclass
class _Entry:
    """One printed entry of a device table — its anchor row plus any wrapped
    continuation lines, gathered before a single record per key is emitted."""

    fields: dict[str, str]
    identity: str
    key_cell: str
    #: `(row index, the key cell that row printed, one key)`, in printed order.
    keys: list[tuple[int, str, str]] = field(default_factory=list)
    #: The printed row each contributing line came from, by row index.
    rows: dict[int, tuple[str, ...]] = field(default_factory=dict)

    def absorb(self, spec: DeviceSpec, row_index: int, row: list[str],
               cell: str, keys: list[str], column_map: ColumnMap) -> None:
        """Fold a wrapped continuation line into this entry.

        Only **key-shaped** keys join: the anchor row's key cell is the row's
        own key as printed and validation judges it, but a continuation line is
        a wrap, and letting an arbitrary fragment of one add a pin would invent
        records out of a line break. Text appends field by field, so a
        description broken over four lines reads back as the sentence the page
        prints.
        """
        have = {key for _row, _cell, key in self.keys}
        for key in keys:
            if spec.key_shaped(key) and key not in have:
                self.keys.append((row_index, cell.strip(), key))
                have.add(key)
                self.rows[row_index] = tuple(row)
        for name, index in column_map.columns.items():
            if name == spec.key_field or len(row) <= index:
                continue
            text = row[index].strip()
            if not text:
                continue
            self.fields[name] = f"{self.fields.get(name, '')} {text}".strip()
        self.identity = self.fields.get(spec.identity_field, self.identity)
        if cell.strip():
            self.key_cell = cell.strip()

    def continues(self, spec: DeviceSpec, cell: str, identity: str) -> bool:
        """Whether the next printed line belongs to this entry.

        A line printing no identity always continues the entry above. A line
        that *does* print one continues it only when this entry's identity was
        left mid-list (`CONTINUATION_MARKERS`) **and** the key cell repeats
        verbatim — anything else is a second entry claiming the same key, which
        is a misread grid and must reject the whole table rather than merge.
        """
        if not identity:
            return True
        return bool(cell.strip()) and cell.strip() == self.key_cell and self.identity.endswith(
            CONTINUATION_MARKERS
        )


def _emit(
    spec: DeviceSpec,
    column_map: ColumnMap,
    key_index: int,
    section: SectionNode,
    table: TableBlock,
    table_index: int,
) -> tuple[list[DeviceRecord], list[int], list[str]]:
    """One record per key, plus the rows that had none and what was odd.

    Printed lines are gathered into entries first (see `_Entry`), because a
    wrapped description or a wrapped key list is one entry of the table however
    many lines it occupies. Each entry then emits one record per key, and every
    key keeps the row *it* was printed on — so an expanded pin cites its own
    page even when the entry spans a page break.
    """
    entries: list[_Entry] = []
    unkeyed: list[int] = []
    warnings: list[str] = []

    rows: list[tuple[int, list[str]]] = []
    if column_map.header_row_is_data:
        rows.append((HEADER_ROW_INDEX, list(table.headers)))
    rows.extend(enumerate(table.grid))

    # `None` both when the kind declares no identity column and when this
    # table's headers never named it. The second case is deliberate: a column
    # the lexicon did not recognise cannot be read as "this row is a new
    # entry", so the wrapped-row reading stays off and every printed line is
    # its own record — the conservative reading, and the one whose damage
    # (a row with no name) the confidence grade already reports.
    identity_index = column_map.index(spec.identity_field) if spec.identity_field else None

    for row_index, row in rows:
        if not any(cell.strip() for cell in row):
            continue
        cell = row[key_index] if len(row) > key_index else ""
        keys = expand_keys(cell, expand=spec.expand_key)
        identity = ""
        if identity_index is not None:
            identity = row[identity_index].strip() if len(row) > identity_index else ""
            if entries and entries[-1].continues(spec, cell, identity):
                entries[-1].absorb(spec, row_index, row, cell, keys, column_map)
                continue
            if not identity:
                # A line with no identity and no entry above it is a band
                # header ("POWER SUPPLIES"), not the table's first entry.
                unkeyed.append(row_index)
                continue
        if not keys:
            unkeyed.append(row_index)
            continue
        if spec.expand_key and len(keys) == 1 and _looks_oversized(cell):
            warnings.append(
                f'{spec.key_field} cell "{normalize_text(cell)}" spans more than '
                f"{MAX_EXPANSION} keys; kept whole"
            )
        entries.append(
            _Entry(
                fields={
                    name: (row[index].strip() if len(row) > index else "")
                    for name, index in column_map.columns.items()
                    if name != spec.key_field
                },
                identity=identity,
                key_cell=cell.strip(),
                keys=[(row_index, cell.strip(), key) for key in dict.fromkeys(keys)],
                rows={row_index: tuple(row)},
            )
        )

    records = [
        DeviceRecord(
            kind=spec.kind,
            key=key,
            key_verbatim=key_cell,
            fields=dict(entry.fields),
            section=section.number,
            table_index=table_index,
            row_index=row_index,
            page=_row_page(table, section, row_index),
            row_verbatim=entry.rows.get(row_index, ()),
        )
        for entry in entries
        for row_index, key_cell, key in entry.keys
    ]

    if unkeyed:
        warnings.append(
            f"{len(unkeyed)} of {len(unkeyed) + len({r.row_index for r in records})} rows "
            f"print no {spec.key_field} and were skipped"
        )
    return records, unkeyed, warnings


def _looks_oversized(cell: str) -> bool:
    """True when a cell is a genuine key range that was too wide to expand.

    Separated from `expand_keys` so the pure helper stays pure: the caller is
    the one that has to *say* a range was kept whole. A hyphenated *name*
    (`RXA-CLK`, `A1-B4`) is not a range at all and must not be reported as one.
    """
    span = _range_span(normalize_text(cell or ""))
    if span is None:
        return False
    _prefix, start, end, _width = span
    return (end - start + 1) > MAX_EXPANSION


def _row_page(table: TableBlock, section: SectionNode, row_index: int) -> int | None:
    """The printed page of one row — the same rule `structure/specs.py` uses.

    A merged multi-page grid's per-row page beats the table's caption page, so
    a continuation row is never cited by a page it does not appear on. The
    header row read as data (`HEADER_ROW_INDEX`) has no `row_pages` entry and
    falls back, rather than indexing the list from the end.
    """
    if 0 <= row_index < len(table.row_pages):
        row_page = table.row_pages[row_index]
        if row_page is not None:
            return row_page
    return table.page if table.page is not None else section.page_start


def _validate(spec: DeviceSpec, records: list[DeviceRecord], unkeyed: list[int]) -> str:
    """The rejection reason for this record set, or `""` when it is sound.

    Ordered worst-first so the reason names the deepest problem: a prose table
    is told it is prose rather than told its second sentence duplicates its
    first. Every rule here rejects the **whole** table — a half-parsed pin
    table is the "confident but incomplete" artifact ADR 0005 exists to
    prevent, because a designer who greps for a pin and gets no hit concludes
    it does not exist.
    """
    if not records:
        return f"no rows carry a {spec.key_field}"

    keyed_rows = {record.row_index for record in records}
    if len(unkeyed) > len(keyed_rows):
        return (
            f"{len(unkeyed)} of {len(unkeyed) + len(keyed_rows)} rows carry no "
            f"{spec.key_field}"
        )

    shaped = sum(1 for record in records if spec.key_shaped(record.key))
    if shaped / len(records) < KEY_SHAPE_MIN:
        odd = next(record.key for record in records if not spec.key_shaped(record.key))
        return (
            f'{spec.key_field} column does not hold {spec.kind} keys '
            f'(e.g. "{_trim(odd)}"): {shaped} of {len(records)} rows are shaped like one'
        )

    seen: dict[str, int] = {}
    for record in records:
        folded = record.key.casefold()
        if folded in seen:
            return (
                f'duplicate {spec.key_field} "{record.key}" '
                f"(rows {seen[folded]} and {record.row_index})"
            )
        seen[folded] = record.row_index

    if spec.monotonic_key:
        previous: tuple[str, int] | None = None
        for record in records:
            number = spec.key_number(record.key)
            if number is None:
                continue
            if previous is not None and number <= previous[1]:
                return (
                    f'{spec.key_field}es out of order: "{previous[0]}" then "{record.key}"'
                )
            previous = (record.key, number)

    return ""


def _trim(text: str, limit: int = 40) -> str:
    """A cell shortened for a one-line reason, with the cut marked."""
    flat = _WS.sub(" ", text.strip())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def cross_check_count(records: list[DeviceRecord], expected: int, *, kind: str = "") -> str:
    """The count-mismatch warning for a record set, or `""` when it agrees.

    ADR 0005 decided this **warns** rather than rejects: the expected count is
    itself read out of prose (a package or ordering-information section) and is
    no more reliable than the table it would suppress, so a bad count must not
    be able to throw away a good pin table. A warning is only weaker than a
    rejection when it can be ignored — recording it is what stops that, which
    is why this returns a string for the caller to keep rather than logging and
    forgetting.
    """
    label = kind or (records[0].kind if records else "device")
    return count_mismatch(len(records), expected, kind=label)


def count_mismatch(actual: int, expected: int, *, kind: str = "device") -> str:
    """The count-mismatch sentence itself, or `""` when the counts agree.

    Split out of `cross_check_count` so a consumer that already knows its own
    count — `structure/pins.py` counts `PinRecord`s, not `DeviceRecord`s —
    does not have to build throwaway records to ask the question. One wording,
    one place: the warning is recorded in a manifest and read by `dsa audit`,
    so two spellings of it would be two facts.
    """
    if expected < 0 or actual == expected:
        return ""
    return f"{kind} count mismatch: document states {expected}, table yields {actual}"


def record_rejections(
    stats: ExtractionStats, rejections: list[DeviceTableRejection]
) -> ExtractionStats:
    """Append device-table rejection reasons to a document's extraction stats.

    Reasons join `rejection_reasons` — the very list the reconstruction gate
    writes — so device tables are as measurable as parametric ones and one
    `dsa status` shows both. The detected/accepted/rejected **counts** are left
    alone deliberately: they measure table *reconstruction*, and a table that
    reconstructed perfectly and then turned out not to be a pin table did not
    fail reconstruction. Duplicates are dropped and the contribution is capped
    at `MAX_RECORDED_REASONS`, exactly as the layout engine caps its own — a
    manifest is a summary, not a log.
    """
    if not rejections:
        return stats
    reasons = list(stats.rejection_reasons)
    # The cap counts what is already recorded, not what this call adds, so a
    # caller that records twice tops nothing up.
    recorded = sum(1 for line in reasons if line.startswith(REJECTION_PREFIX))
    for rejection in rejections:
        if recorded >= MAX_RECORDED_REASONS:
            break
        line = rejection.describe()
        if line not in reasons:
            reasons.append(line)
            recorded += 1
    stats.rejection_reasons = reasons
    return stats
