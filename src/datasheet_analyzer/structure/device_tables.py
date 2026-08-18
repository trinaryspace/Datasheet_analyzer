"""Device tables — one abstraction, two consumers (phase 6, ticket 03).

A pin table and a register-summary table are the same structural animal: wide,
repetitive, keyed by a first column that names the thing each row is about. So
this module is one pipeline with a data-driven vocabulary, not two parsers:

    identify -> map columns -> validate -> emit

- **Identify** by the checked-in header lexicon (`registry/device_tables.yaml`).
  Adding a header variant a vendor prints is a data change; there is no vendor
  branch anywhere in this file. Identification failure is *silent* — a
  parametric spec table is simply not a device table, and saying so in every
  document's rejection reasons would drown the reasons that matter.
- **Map columns** by header match — abbreviations included, because the
  abbreviations live in the lexicon — with a positional fallback for a table
  that printed no header row at all. The fallback is deliberately hard to
  reach: an explicitly requested kind, a caption or section title declaring
  that kind, and a key column that reads like keys. A headerless grid of small
  integers otherwise reads as a pin table *and* a register table, and guessing
  between them is precisely the guess invariant 8 forbids.
- **Validate** the mapped table as a whole: the key column has to look like
  keys, keys have to be unique, addresses have to run in one direction, and a
  real share of the printed rows has to survive. **A validation failure rejects
  the table with a recorded reason** — never a half-parsed record set. That is
  the same honesty contract `extract/pdf_layout.py` already applies to
  parametric tables, and the reasons join `ExtractionStats.rejection_reasons`
  (`record_rejections`) so device tables are as measurable as parametric ones.
- **Emit** `DeviceRow`s carrying full provenance: section, table index, row
  index, printed page, the row exactly as printed, and — when one printed row
  named several pins — the cell it expanded from.

Every cell this module emits is **copied verbatim** (clause (a) of invariant 8,
ADR 0007); the only things computed are the structural role labels, which come
from the lexicon (clause (c)), and `parse_address`, a documented pure function
(clause (b)). No model call appears anywhere in this path.

**Row indices count printed body rows.** That is the grid index in the ordinary
case; when the printed header row turns out to *be* data (a headerless table
whose first row the layout engine took for a header), the header row is row 0
and every grid row shifts by one. The index is a pure function of the table's
own coordinates either way, so `pin_record_id` / `register_record_id` stay
stable across a rebuild of identical input.

No consumer ships in this ticket: `derive/pins.py` (04) and `derive/registers.py`
(05) are the first two, and the seam is deliberately narrow enough that neither
of them needs to know what the other's tables look like.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import cache
from itertools import pairwise
from pathlib import Path

import yaml

from datasheet_analyzer.models import (
    RECONSTRUCTION_RESCUED,
    Confidence,
    ExtractionStats,
    RawDocument,
    SectionNode,
    TableBlock,
)

log = logging.getLogger(__name__)

#: The checked-in header lexicon. Data, not code — see the file's own header.
DEVICE_LEXICON_PATH = Path(__file__).resolve().parent.parent / "registry" / "device_tables.yaml"

#: The two kinds the lexicon ships. Named here so a consumer never spells one.
KIND_PIN = "pin"
KIND_REGISTER = "register"

#: How a table's columns were found. `header` means the table declared them;
#: `positional` means it did not and the lexicon's declared column order was
#: used instead — which is why a positionally-mapped row is never graded
#: `high`.
METHOD_HEADER = "header"
METHOD_POSITIONAL = "positional"

_WS = re.compile(r"\s+")
# Footnote markers a header may carry ("Pin(2)", "Name 1)") — noise for matching.
_HEADER_MARKER = re.compile(r"\(\d+\)|\[\d+\]")
_NON_WORD = re.compile(r"[^a-z0-9/#.]+")
# Separators between several keys printed in one cell: "A1, A2; B1".
_KEY_SPLIT = re.compile(r"\s*[,;]\s*")
# "A1-A4", "A1 – A4", "12 to 15" — a printed run of keys.
_KEY_RANGE = re.compile(
    r"^(?P<p1>[A-Za-z]{0,3})(?P<n1>\d{1,4})\s*(?:[-‐-―−]|to)\s*"
    r"(?P<p2>[A-Za-z]{0,3})(?P<n2>\d{1,4})$"
)
#: A printed run wider than this is not a pin range anybody printed; it is a
#: misread. The row keeps its cell verbatim instead of exploding into fiction.
MAX_KEY_EXPANSION = 256

_HEX_PREFIX = re.compile(r"^0x([0-9a-f]+)$", re.IGNORECASE)
_HEX_SUFFIX = re.compile(r"^([0-9a-f]+)h$", re.IGNORECASE)
_DECIMAL = re.compile(r"^\d+$")
_BARE_HEX = re.compile(r"^[0-9a-f]+$", re.IGNORECASE)


# --- the lexicon -----------------------------------------------------------


@dataclass(frozen=True)
class RoleSpec:
    """One column a device table of some kind may print."""

    role: str
    headers: tuple[str, ...] = ()
    position: int = 0
    required: bool = False


@dataclass(frozen=True)
class KindSpec:
    """One device-table kind: its columns, its key, and how it is validated."""

    kind: str
    label: str
    key_role: str
    key_pattern: re.Pattern[str]
    key_names: frozenset[str] = frozenset()
    key_share: float = 0.6
    min_rows: int = 2
    min_header_roles: int = 2
    min_row_yield: float = 0.5
    expand_keys: bool = False
    validators: tuple[str, ...] = ()
    captions: tuple[str, ...] = ()
    roles: tuple[RoleSpec, ...] = ()

    @property
    def required_roles(self) -> tuple[str, ...]:
        return tuple(r.role for r in self.roles if r.required)

    def role_spec(self, role: str) -> RoleSpec | None:
        for spec in self.roles:
            if spec.role == role:
                return spec
        return None

    def key_matches(self, key: str) -> bool:
        """Whether one printed key has the shape this kind's keys have."""
        text = key.strip()
        if not text:
            return False
        if normalize_header(text) in self.key_names:
            return True
        return bool(self.key_pattern.fullmatch(text))

    def declared_by(self, *texts: str) -> bool:
        """Whether a caption or section title says a table is of this kind.

        The positional fallback's only evidence. A table that declares no
        columns has to be declared by *something* — `Table 4-1 Pin Functions`,
        or a section titled `Pin Configuration and Functions`. Without it, a
        grid of small integers reads as a pin table, a register table and a
        mode-selection table at once, which is three guesses, not one reading.
        """
        haystacks = [f" {normalize_header(t)} " for t in texts if t]
        return any(f" {phrase} " in hay for phrase in self.captions for hay in haystacks)


@dataclass(frozen=True)
class DeviceLexicon:
    """The parsed `device_tables.yaml`, in declaration order."""

    kinds: tuple[KindSpec, ...] = ()
    schema_version: int = 0

    def kind(self, name: str) -> KindSpec | None:
        for spec in self.kinds:
            if spec.kind == name:
                return spec
        return None


def _phrases(entries: object, *, where: str) -> tuple[str, ...]:
    """Normalize a YAML list of phrases, warning about the YAML traps.

    `no` is a boolean in YAML 1.1 and `#` opens a comment, so an unquoted
    header variant can silently become `False` or lose half its words. The
    lexicon is meant to be editable by anyone; a warning naming the entry is
    the difference between "quote it" and "why did my header stop matching".
    """
    out: list[str] = []
    for entry in entries or ():
        if not isinstance(entry, str):
            log.warning(
                "device-table lexicon: %s entry %r is not text — quote it in the YAML",
                where,
                entry,
            )
            continue
        phrase = normalize_header(entry)
        if phrase:
            out.append(phrase)
    return tuple(out)


def _parse_lexicon(data: dict) -> DeviceLexicon:
    kinds: list[KindSpec] = []
    for name, body in data.items():
        if name == "schema_version" or not isinstance(body, dict):
            continue
        roles = tuple(
            RoleSpec(
                role=role,
                headers=_phrases(rbody.get("headers"), where=f"{name}.{role}.headers"),
                position=int(rbody.get("position", i)),
                required=bool(rbody.get("required", False)),
            )
            for i, (role, rbody) in enumerate((body.get("roles") or {}).items())
        )
        kinds.append(
            KindSpec(
                kind=name,
                label=str(body.get("label", name)),
                key_role=str(body.get("key_role", "")),
                key_pattern=re.compile(str(body.get("key_pattern", "$^")), re.IGNORECASE),
                key_names=frozenset(_phrases(body.get("key_names"), where=f"{name}.key_names")),
                key_share=float(body.get("key_share", 0.6)),
                min_rows=int(body.get("min_rows", 2)),
                min_header_roles=int(body.get("min_header_roles", 2)),
                min_row_yield=float(body.get("min_row_yield", 0.5)),
                expand_keys=bool(body.get("expand_keys", False)),
                validators=tuple(body.get("validators") or ()),
                captions=_phrases(body.get("captions"), where=f"{name}.captions"),
                roles=roles,
            )
        )
    return DeviceLexicon(kinds=tuple(kinds), schema_version=int(data.get("schema_version", 0)))


@cache
def load_device_lexicon(path: Path | None = None) -> DeviceLexicon:
    """The shipped lexicon, parsed once per process (or one at `path`).

    An unreadable lexicon degrades to an empty one — every table then simply
    fails to identify, which is the honest outcome: no device tables rather
    than device tables built from a guess.
    """
    target = path or DEVICE_LEXICON_PATH
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:  # pragma: no cover - defensive
        log.warning("device-table lexicon unavailable (%s: %s) — no device tables", target, exc)
        return DeviceLexicon()
    return _parse_lexicon(data)


def clear_device_lexicon_cache() -> None:
    """Test hook: re-read the lexicon file on the next `load_device_lexicon`."""
    load_device_lexicon.cache_clear()


def normalize_header(text: str) -> str:
    """The phrase form headers are matched in: lowercase, marker-free, tight.

    `"Pin No.(2)"` and `"PIN NO"` are the same column to a reader and must be
    the same string here. `/` and `#` survive because `I/O` and `Pin #` are
    header words, not punctuation.
    """
    folded = _HEADER_MARKER.sub(" ", (text or "").lower())
    folded = _NON_WORD.sub(" ", folded)
    folded = folded.replace(".", " ")
    return _WS.sub(" ", folded).strip()


# --- column mapping --------------------------------------------------------


@dataclass(frozen=True)
class ColumnMapping:
    """Which printed column carries which role, and how that was decided."""

    kind: str
    columns: dict[str, int] = field(default_factory=dict)
    method: str = METHOD_HEADER
    header_row_is_data: bool = False
    unmapped_headers: tuple[str, ...] = ()

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(self.columns)

    def cell(self, row: Sequence[str], role: str) -> str:
        """The verbatim cell this row prints for `role`, or `""`."""
        index = self.columns.get(role)
        if index is None or index >= len(row):
            return ""
        return _WS.sub(" ", row[index]).strip()


def map_columns_by_header(headers: Sequence[str], spec: KindSpec) -> ColumnMapping | None:
    """Map columns from a printed header row, longest matching phrase first.

    A header matches a role when one of the role's lexicon phrases is the whole
    normalized header or a run of whole words inside it, and the phrase with the
    most words wins — so a `Pin Name` column reads as `name`, not as `pin`, even
    though both entries claim a word of it. A role claimed by two columns keeps
    the leftmost, which is the one a reader would read it as.

    `None` when the table does not declare enough of this kind to be it:
    the key role missing, or fewer roles than the kind's `min_header_roles`.
    Unmapped roles stay unmapped — a header row that says nothing about a
    column is not evidence about that column, and filling it positionally here
    would be a guess dressed as a mapping.
    """
    best: dict[str, tuple[int, int]] = {}  # role -> (phrase words, column)
    unmapped: list[str] = []
    for column, raw in enumerate(headers):
        norm = normalize_header(raw)
        if not norm:
            continue
        words = f" {norm} "
        hit_role, hit_len = "", 0
        for role_spec in spec.roles:
            for phrase in role_spec.headers:
                if phrase and f" {phrase} " in words and len(phrase.split()) > hit_len:
                    hit_role, hit_len = role_spec.role, len(phrase.split())
        if not hit_role:
            unmapped.append(raw.strip())
            continue
        prior = best.get(hit_role)
        if prior is None or hit_len > prior[0]:
            best[hit_role] = (hit_len, column)
    columns = {role: col for role, (_len, col) in best.items()}
    if spec.key_role not in columns or len(columns) < spec.min_header_roles:
        return None
    return ColumnMapping(
        kind=spec.kind,
        columns=dict(sorted(columns.items(), key=lambda kv: kv[1])),
        method=METHOD_HEADER,
        unmapped_headers=tuple(unmapped),
    )


def map_columns_by_position(
    n_cols: int, spec: KindSpec, *, header_row_is_data: bool
) -> ColumnMapping:
    """Map columns by the lexicon's declared column order.

    The fallback for a table that printed no header row at all — `identify`
    decides when that is the case and refuses to reach here for a table whose
    headers merely say something the lexicon has not been taught. Roles whose
    declared position is past the printed column count stay unmapped rather
    than sliding onto whatever column happens to exist.
    """
    columns = {r.role: r.position for r in spec.roles if r.position < n_cols}
    return ColumnMapping(
        kind=spec.kind,
        columns=dict(sorted(columns.items(), key=lambda kv: kv[1])),
        method=METHOD_POSITIONAL,
        header_row_is_data=header_row_is_data,
    )


# --- key expansion ---------------------------------------------------------


def expand_keys(cell: str) -> tuple[list[str], str]:
    """`"A1, A2"` -> `["A1", "A2"]`; `"A1-A4"` -> four keys. Returns (keys, note).

    A pin table prints one row for several pins all the time, and each of those
    pins has to be individually citable. Two printed shapes expand:

    - a **list** separated by `,` or `;`;
    - a **run** — `A1-A4`, `A1 – A4`, `12 to 15` — whose two ends share an
      alphabetic prefix and count upward.

    Anything else is kept exactly as printed, with `note` saying why it was not
    expanded: a descending run, a run across different prefixes, or one wider
    than `MAX_KEY_EXPANSION` is a misread, and inventing its members would be
    inventing pins. `note` is empty when nothing needed saying.
    """
    text = _WS.sub(" ", (cell or "")).strip()
    if not text:
        return [], ""
    notes: list[str] = []
    keys: list[str] = []
    for token in _KEY_SPLIT.split(text):
        token = token.strip()
        if not token:
            continue
        run = _KEY_RANGE.match(token)
        if run is None:
            keys.append(token)
            continue
        p1, p2 = run.group("p1"), run.group("p2")
        n1, n2 = int(run.group("n1")), int(run.group("n2"))
        if p2 and p1.upper() != p2.upper():
            notes.append(f"{token!r} spans two prefixes")
            keys.append(token)
        elif n2 < n1:
            notes.append(f"{token!r} counts down")
            keys.append(token)
        elif n2 - n1 + 1 > MAX_KEY_EXPANSION:
            notes.append(f"{token!r} spans more than {MAX_KEY_EXPANSION} keys")
            keys.append(token)
        else:
            width = len(run.group("n1")) if run.group("n1").startswith("0") else 0
            keys.extend(f"{p1}{n:0{width}d}" for n in range(n1, n2 + 1))
    return keys, "; ".join(notes)


def parse_address(text: str, *, hex_default: bool = False) -> int | None:
    """`"0x1A04"` -> 6660. A documented pure function (invariant 8, clause (b)).

    Three printed forms parse: `0x1A04`, `1A04h`, and plain digits. A bare
    string of hex letters and digits (`1A04`, with no marker either side) is
    ambiguous, so it parses only when the caller has decided the column is hex
    — `hex_default`, which `monotonic_addresses` derives from the column as a
    whole rather than from the cell. `None` for anything else: an address the
    tool guessed at is worse than one it admits it cannot read.
    """
    token = (text or "").strip().replace(" ", "")
    if not token:
        return None
    prefixed = _HEX_PREFIX.match(token)
    if prefixed:
        return int(prefixed.group(1), 16)
    suffixed = _HEX_SUFFIX.match(token)
    if suffixed:
        return int(suffixed.group(1), 16)
    if _DECIMAL.match(token):
        return int(token, 16) if hex_default else int(token)
    if hex_default and _BARE_HEX.match(token):
        return int(token, 16)
    return None


def _column_is_hex(values: Iterable[str]) -> bool:
    """Whether a printed address column is hexadecimal, judged whole.

    One `0x`/`h` marker, or one cell carrying a hex letter, makes the column
    hex — and then `10` in the same column is 16, not ten. Deciding per cell
    would order `0x0A` before `10` on one row and after it on the next.
    """
    for value in values:
        token = (value or "").strip()
        if not token:
            continue
        if _HEX_PREFIX.match(token) or _HEX_SUFFIX.match(token):
            return True
        if _BARE_HEX.match(token) and not _DECIMAL.match(token):
            return True
    return False


# --- emitted records -------------------------------------------------------


@dataclass(frozen=True)
class DeviceRow:
    """One emitted device-table row, with everything needed to cite it.

    `values` is keyed by lexicon role (`pin`/`name`/`type`/`description`, or
    `address`/`name`/`reset`/`access`) and every value is the cell **exactly as
    printed** — this module normalizes whitespace and nothing else, because the
    printed glyph is the authority (a direction printed `—` stays `—`).
    """

    kind: str
    key: str
    values: dict[str, str] = field(default_factory=dict)
    section: str = ""
    table_index: int = 0
    row_index: int = 0
    page: int | None = None
    row_verbatim: tuple[str, ...] = ()
    expanded_from: str = ""  # the printed cell, when this row expanded
    method: str = METHOD_HEADER
    confidence: Confidence = Confidence.UNKNOWN

    def value(self, role: str) -> str:
        return self.values.get(role, "")


@dataclass(frozen=True)
class DeviceTableResult:
    """What became of one candidate device table — accepted, or why not."""

    kind: str
    section: str
    table_index: int
    caption: str = ""
    accepted: bool = False
    rows: tuple[DeviceRow, ...] = ()
    reason: str = ""  # "" when accepted; the recorded rejection otherwise
    mapping: ColumnMapping | None = None
    n_printed_rows: int = 0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeviceTableExtraction:
    """Every device table of one kind in one document."""

    kind: str
    results: tuple[DeviceTableResult, ...] = ()

    @property
    def rows(self) -> tuple[DeviceRow, ...]:
        return tuple(row for r in self.results if r.accepted for row in r.rows)

    @property
    def accepted(self) -> tuple[DeviceTableResult, ...]:
        return tuple(r for r in self.results if r.accepted)

    @property
    def rejected(self) -> tuple[DeviceTableResult, ...]:
        return tuple(r for r in self.results if not r.accepted)

    @property
    def rejection_reasons(self) -> tuple[str, ...]:
        return tuple(r.reason for r in self.rejected if r.reason)


# --- the pipeline ----------------------------------------------------------


@dataclass(frozen=True)
class _PrintedRow:
    """One printed body row, before validation decides the table's fate."""

    row_index: int
    cells: tuple[str, ...]
    page: int | None
    grid_index: int | None  # None for a header row that turned out to be data


def _is_repeat_header(cells: Sequence[str], headers: Sequence[str]) -> bool:
    """A continuation page's header reprinted inside a merged grid."""
    if not headers:
        return False
    return [normalize_header(c) for c in cells] == [normalize_header(h) for h in headers]


def _row_page(table: TableBlock, section: SectionNode, grid_index: int | None) -> int | None:
    """The printed page this row is on — its own first, the table's next."""
    if grid_index is not None and len(table.row_pages) > grid_index:
        page = table.row_pages[grid_index]
        if page is not None:
            return page
    if table.page is not None:
        return table.page
    return section.page_start


def _page_is_exact(table: TableBlock, section: SectionNode, grid_index: int | None) -> bool:
    """Whether this row cites one printed page rather than a section's range.

    The same rule `structure/confidence.py` applies to a spec row; its
    docstring is the normative version.
    """
    if (
        grid_index is not None
        and len(table.row_pages) > grid_index
        and table.row_pages[grid_index] is not None
    ):
        return True
    if table.page is not None:
        return True
    if section.page_start is None:
        return False
    return (section.page_end or section.page_start) == section.page_start


def _printed_rows(
    table: TableBlock, section: SectionNode, mapping: ColumnMapping
) -> list[_PrintedRow]:
    """The table's body rows in printed order, blanks and reprints removed."""
    offset = 1 if mapping.header_row_is_data else 0
    rows: list[_PrintedRow] = []
    if mapping.header_row_is_data:
        rows.append(
            _PrintedRow(
                row_index=0,
                cells=tuple(table.headers),
                page=_row_page(table, section, None),
                grid_index=None,
            )
        )
    for grid_index, cells in enumerate(table.grid):
        if not any(c.strip() for c in cells):
            continue
        if _is_repeat_header(cells, table.headers):
            continue
        rows.append(
            _PrintedRow(
                row_index=grid_index + offset,
                cells=tuple(cells),
                page=_row_page(table, section, grid_index),
                grid_index=grid_index,
            )
        )
    return rows


def _grade_device_row(
    *,
    table: TableBlock,
    section: SectionNode,
    mapping: ColumnMapping,
    spec: KindSpec,
    printed: _PrintedRow,
    values: dict[str, str],
) -> Confidence:
    """Grade one device row on how well its columns and page are known.

    Worst first, mirroring `structure/confidence.grade_spec_record`:

    | grade | when |
    |---|---|
    | `low` | the grid was rescued by the layout retry ladder, **or** the columns were mapped positionally (the table never declared them) |
    | `medium` | the row cites a section range rather than a printed page, **or** a required role printed nothing |
    | `high` | pinned page, header-declared columns, every required cell printed |
    """
    if table.reconstruction == RECONSTRUCTION_RESCUED:
        return Confidence.LOW
    if mapping.method == METHOD_POSITIONAL:
        return Confidence.LOW
    if not _page_is_exact(table, section, printed.grid_index):
        return Confidence.MEDIUM
    if any(not values.get(role, "").strip() for role in spec.required_roles):
        return Confidence.MEDIUM
    return Confidence.HIGH


def identify(
    table: TableBlock,
    *,
    kind: str | None = None,
    lexicon: DeviceLexicon | None = None,
    section_title: str = "",
) -> ColumnMapping | None:
    """Decide what kind of device table this is and where its columns are.

    Header evidence first, across every kind (or the requested one): the kind
    that maps the most roles wins, and a tie between kinds is not resolved —
    a table that looks equally like two schemas is not evidence for either.

    Only when a **specific** kind was requested and its headers say nothing
    does the positional fallback run, and then only when two further things
    hold: the caption or the section title declares the kind (measured
    necessity — without it, LMX1204's mode-selection tables read as pin tables
    *and* as register tables, because a column of small integers looks like
    both), and the column that would be the key actually reads like keys.
    That covers the shape a real datasheet prints: a table with no header row
    at all, where the layout engine has taken the first data row for the
    header — which `header_row_is_data` records so the row is emitted rather
    than lost.

    A table whose headers the lexicon simply does not know is **not** guessed
    at positionally: unrecognized headers are evidence of a schema, not the
    absence of evidence. Teaching the lexicon that header is a data change,
    which is the whole point of keeping it in YAML.

    `None` means "not a device table", and is silent by design: most tables in
    a datasheet are parametric, and reporting each one as a rejected device
    table would bury the rejections that mean something.
    """
    lex = lexicon or load_device_lexicon()
    specs = [s for s in lex.kinds if kind is None or s.kind == kind]
    if not specs:
        return None

    scored: list[tuple[int, ColumnMapping]] = []
    for spec in specs:
        mapped = map_columns_by_header(table.headers, spec)
        if mapped is not None:
            scored.append((len(mapped.columns), mapped))
    if scored:
        scored.sort(key=lambda pair: -pair[0])
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            log.debug("device table ambiguous between %s", [m.kind for _s, m in scored])
            return None
        return scored[0][1]

    if kind is None:
        return None
    spec = specs[0]
    if not spec.declared_by(table.caption, section_title):
        return None
    n_cols = max(table.n_cols, len(table.headers))
    if n_cols < len(spec.required_roles):
        return None
    key_spec = spec.role_spec(spec.key_role)
    if key_spec is None or key_spec.position >= n_cols:
        return None

    header_keys = (
        [table.headers[key_spec.position]] if len(table.headers) > key_spec.position else []
    )
    body_keys = [row[key_spec.position] for row in table.grid if len(row) > key_spec.position]
    header_is_data = bool(header_keys) and spec.key_matches(header_keys[0])
    if any(h.strip() for h in table.headers) and not header_is_data:
        # The table printed a header row the lexicon does not know. That is a
        # schema this module has not been taught, not a table without one.
        return None
    candidates = [k for k in (header_keys if header_is_data else []) + body_keys if k.strip()]
    if len(candidates) < spec.min_rows:
        return None
    matched = sum(1 for k in candidates if spec.key_matches(k))
    if matched < spec.key_share * len(candidates):
        return None
    return map_columns_by_position(n_cols, spec, header_row_is_data=header_is_data)


# --- validation ------------------------------------------------------------


def _validate_key_column_shape(spec: KindSpec, rows: list[dict]) -> str | None:
    """The key column has to read like keys, or the table is prose in columns.

    This is what keeps a paragraph laid out in two columns from becoming a pin
    table: its first cells are sentences, not designators.

    Judged over the rows that printed *something* in the key column — a blank
    key is a row the table did not key, which is the count cross-check's
    question (`row_yield`), not this one's.
    """
    printed = [r for r in rows if r["key"].strip()]
    if not printed:
        return "no printed keys"
    matched = sum(1 for r in printed if r["key_ok"])
    if matched < spec.key_share * len(printed):
        return f"key column is not {spec.label} keys ({matched} of {len(printed)} rows)"
    return None


def _validate_unique_keys(spec: KindSpec, rows: list[dict]) -> str | None:
    """Two rows claiming one key means the mapping is wrong, not the datasheet."""
    seen: dict[str, int] = {}
    for row in rows:
        if not row["key_ok"]:
            continue
        for key in row["keys"]:
            folded = key.strip().upper()
            if folded in seen:
                return f"duplicate key {key!r} (rows {seen[folded]} and {row['row_index']})"
            seen[folded] = row["row_index"]
    return None


def _validate_monotonic_addresses(spec: KindSpec, rows: list[dict]) -> str | None:
    """Addresses run one way through a map; a step backwards means a lost row.

    Enforced over the rows whose address parsed, judged as one column (hex or
    decimal for all of them, never per cell). A map that genuinely restarts its
    numbering per block is rejected here on purpose — the reason names the two
    rows, and splitting the map by block is a data change in the lexicon, not
    an approximation smuggled into the records.
    """
    parsed: list[tuple[int, int, str]] = []
    hex_column = _column_is_hex(row["key"] for row in rows if row["key_ok"])
    for row in rows:
        if not row["key_ok"]:
            continue
        value = parse_address(row["key"], hex_default=hex_column)
        if value is not None:
            parsed.append((value, row["row_index"], row["key"]))
    for (prev, prev_row, prev_text), (curr, curr_row, curr_text) in pairwise(parsed):
        if curr <= prev:
            return (
                f"address {curr_text!r} (row {curr_row}) does not follow "
                f"{prev_text!r} (row {prev_row})"
            )
    return None


def _validate_row_yield(spec: KindSpec, rows: list[dict]) -> str | None:
    """Most of the printed rows have to survive, or the mapping missed the table.

    The count cross-check: a table where the key column is empty or unreadable
    for half the rows has not been understood, and shipping the half that
    happened to parse would be exactly the partial record set this contract
    forbids.
    """
    if not rows:
        return "no printed rows"
    emitted = sum(1 for r in rows if r["key_ok"] and r["keys"])
    if emitted < spec.min_row_yield * len(rows):
        return f"only {emitted} of {len(rows)} printed rows produced a record"
    return None


#: Validator name -> implementation. A kind's `validators` list in the lexicon
#: selects from here, in the order it lists them; the first failure rejects the
#: table, so the order is the order a reader would check them in.
VALIDATORS = {
    "key_column_shape": _validate_key_column_shape,
    "unique_keys": _validate_unique_keys,
    "monotonic_addresses": _validate_monotonic_addresses,
    "row_yield": _validate_row_yield,
}


def _stage_rows(
    printed: list[_PrintedRow], mapping: ColumnMapping, spec: KindSpec
) -> tuple[list[dict], list[str]]:
    """Read the printed rows into staged records, before validation judges them.

    Two printed shapes are read here rather than being left for a validator to
    trip over, because both are *layout*, not content, and both were measured
    in the built corpora:

    - **Band labels.** `POWER SUPPLIES` printed alone across a pin table's first
      column (AD9081 Table 21) is a heading inside the table. It carries no key
      and no other cell, so it is set aside — counted in the notes, kept out of
      the shape and yield denominators, never emitted as a pin.
    - **Continuation rows.** A description too long for one printed line becomes
      a second grid row, and `pdf_layout`'s rowspan materialization copies the
      key into it (AD9081 rows 10-11, `D10, R10` twice). Such a tail is joined
      back onto the row it continues — the printed cell's text, whose line break
      was layout — instead of reading as two rows claiming one pin.

    A repeated key is only read as a continuation on structural evidence: the
    row **leaves empty a column the row above filled**. A row that prints no
    name is not a record; a row that prints every column its neighbour did is,
    and a repeated key there is a real contradiction that `unique_keys` rejects
    the table for. That is the right answer for HMC520A Table 4, where the
    exposed-pad row prints no pin number at all and materialization lends it
    the previous row's `15`: merging would silently attach one pin's name to
    another's description, and a rejection with a reason is worth more.
    """
    staged: list[dict] = []
    notes: list[str] = []
    tail_roles = [r for r in mapping.columns if r != spec.key_role]
    for row in printed:
        key_cell = mapping.cell(row.cells, spec.key_role)
        values = {role: mapping.cell(row.cells, role) for role in mapping.columns}
        if key_cell and not spec.key_matches(key_cell) and not any(values[r] for r in tail_roles):
            notes.append(f"row {row.row_index}: band label {key_cell!r}")
            continue
        if spec.expand_keys:
            keys, note = expand_keys(key_cell)
        else:
            keys, note = ([key_cell] if key_cell else []), ""
        if note:
            notes.append(f"row {row.row_index}: {note}")
        entry = {
            "printed": row,
            "row_index": row.row_index,
            "key": key_cell,
            "keys": keys,
            "key_ok": bool(keys) and all(spec.key_matches(k) for k in keys),
            "values": values,
        }
        prev = staged[-1] if staged else None
        continues = (
            prev is not None
            and entry["key_ok"]
            and key_cell.strip().upper() == prev["key"].strip().upper()
            and any(prev["values"][r].strip() and not values[r].strip() for r in tail_roles)
        )
        if continues:
            for role in tail_roles:
                tail = values[role].strip()
                if not tail:
                    continue
                head = prev["values"][role].strip()
                prev["values"][role] = f"{head} {tail}".strip()
            notes.append(f"row {row.row_index}: continues row {prev['row_index']}")
            continue
        staged.append(entry)
    return staged, notes


def parse_device_table(
    section: SectionNode,
    table: TableBlock,
    table_index: int,
    *,
    kind: str | None = None,
    lexicon: DeviceLexicon | None = None,
) -> DeviceTableResult | None:
    """Run identify -> map -> validate -> emit over one table.

    `None` when this is not a device table at all. A `DeviceTableResult` with
    `accepted=False` and a `reason` when it is one and failed validation — and
    then `rows` is empty, whole: a rejected table never ships the rows that
    happened to parse before the failure.
    """
    lex = lexicon or load_device_lexicon()
    mapping = identify(table, kind=kind, lexicon=lex, section_title=section.full_title)
    if mapping is None:
        return None
    spec = lex.kind(mapping.kind)
    if spec is None:  # pragma: no cover - identify only returns known kinds
        return None

    printed = _printed_rows(table, section, mapping)
    result = DeviceTableResult(
        kind=spec.kind,
        section=section.number,
        table_index=table_index,
        caption=table.caption,
        mapping=mapping,
        n_printed_rows=len(printed),
    )
    if len(printed) < spec.min_rows:
        return _rejected(result, f"{spec.label}: fewer than {spec.min_rows} printed rows")

    staged, notes = _stage_rows(printed, mapping, spec)
    if not staged:
        return _rejected(result, f"{spec.label}: no keyed rows")

    for name in spec.validators:
        check = VALIDATORS.get(name)
        if check is None:  # pragma: no cover - lexicon typo guard
            log.warning("unknown device-table validator %r for kind %r", name, spec.kind)
            continue
        reason = check(spec, staged)
        if reason is not None:
            return _rejected(result, f"{spec.label}: {reason}")

    rows: list[DeviceRow] = []
    for entry in staged:
        if not entry["key_ok"]:
            continue
        row = entry["printed"]
        values = entry["values"]
        confidence = _grade_device_row(
            table=table,
            section=section,
            mapping=mapping,
            spec=spec,
            printed=row,
            values=values,
        )
        expanded = entry["key"] if len(entry["keys"]) > 1 else ""
        for key in entry["keys"]:
            rows.append(
                DeviceRow(
                    kind=spec.kind,
                    key=key,
                    values={**values, spec.key_role: key},
                    section=section.number,
                    table_index=table_index,
                    row_index=row.row_index,
                    page=row.page,
                    row_verbatim=row.cells,
                    expanded_from=expanded,
                    method=mapping.method,
                    confidence=confidence,
                )
            )
    return DeviceTableResult(
        kind=result.kind,
        section=result.section,
        table_index=result.table_index,
        caption=result.caption,
        accepted=True,
        rows=tuple(rows),
        mapping=mapping,
        n_printed_rows=len(printed),
        notes=tuple(notes),
    )


def _rejected(result: DeviceTableResult, reason: str) -> DeviceTableResult:
    """The whole table, refused, with the reason that refused it."""
    return DeviceTableResult(
        kind=result.kind,
        section=result.section,
        table_index=result.table_index,
        caption=result.caption,
        accepted=False,
        rows=(),
        reason=reason,
        mapping=result.mapping,
        n_printed_rows=result.n_printed_rows,
    )


def iter_tables(raw: RawDocument) -> Iterator[tuple[SectionNode, TableBlock, int]]:
    """Every table of a document, with its section and its index in it."""
    for section in raw.sections:
        for table_index, table in enumerate(section.tables):
            yield section, table, table_index


def extract_device_tables(
    raw: RawDocument,
    *,
    kind: str,
    lexicon: DeviceLexicon | None = None,
) -> DeviceTableExtraction:
    """Every device table of one kind in one document, accepted and rejected.

    The entry point a consumer wants: `derive/pins.py` asks for `KIND_PIN`,
    `derive/registers.py` for `KIND_REGISTER`, and neither needs to know what
    the other's tables look like. A `pdf_text` document is skipped whole — that
    backend is explicitly degraded and publishes no trusted tables, so there is
    nothing here to be honest about.
    """
    lex = lexicon or load_device_lexicon()
    if raw.extractor == "pdf_text":
        return DeviceTableExtraction(kind=kind)
    results = [
        result
        for section, table, table_index in iter_tables(raw)
        if (result := parse_device_table(section, table, table_index, kind=kind, lexicon=lex))
        is not None
    ]
    return DeviceTableExtraction(kind=kind, results=tuple(results))


def record_rejections(
    stats: ExtractionStats | None,
    reasons: Iterable[str],
    *,
    limit: int = 8,
) -> ExtractionStats | None:
    """Join device-table rejections to the document's `rejection_reasons`.

    Device tables are as measurable as parametric ones because they land in
    the same place: `dsa status` already prints this list, and a pin table that
    was refused shows up there beside the parametric tables the layout engine
    refused.

    The table *counts* are deliberately untouched. A device table was already
    counted as accepted by the layout engine — it is a real grid; what failed
    is the second reading of it — and incrementing `tables_rejected` here would
    make one table two.
    """
    if stats is None:
        return None
    existing = list(stats.rejection_reasons)
    seen = set(existing)
    added = 0
    for reason in reasons:
        if not reason or reason in seen or added >= limit:
            continue
        existing.append(reason)
        seen.add(reason)
        added += 1
    stats.rejection_reasons = existing
    return stats
