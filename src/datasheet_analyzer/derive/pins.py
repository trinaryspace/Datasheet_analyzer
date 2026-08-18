"""Pins — `pins.json` and `dsa pins` (phase 6, ticket 04).

During schematic capture the pin table *is* the datasheet, so this is the
first consumer of the device-table abstraction and the proof that it works:
`structure/device_tables.py` finds the table, validates it and emits rows;
this module turns those rows into `PinRecord`s, labels each one from a
checked-in lexicon, cross-checks the count against the printed package, and
answers questions about the result.

Everything here obeys **invariant 8** (ADR 0007). Concretely:

- every printed field — designator, name, direction, description — is
  **copied verbatim** (clause (a)); this module normalizes whitespace and
  nothing else;
- `type` is a structural label from `registry/pin_types.yaml` (clause (c)),
  and every record carries `type_evidence`, the entry that produced it, so a
  label can be checked against the lexicon instead of trusted;
- the package cross-check is a documented pure function (clause (b)) whose
  disagreement is a **warning**, never a correction: the pin table is still
  the best record available, and silently "fixing" a count would invent pins;
- `unknown` is a legitimate type and an unfilled field stays unfilled. There
  is no model call anywhere in this path.

Two rules are worth stating because they are the ones a reader will test:

**A part with no parseable pin table produces no `pins.json` at all.** Not an
empty one, and never a partial one — a half-read pin table is the single most
dangerous artifact this tool could publish, because a missing pin reads as
"this pin does not exist" during schematic capture. When the device-table
layer rejects a candidate, the reason travels into
`ExtractionStats.rejection_reasons`, where `dsa status` already prints it.

**A multi-pin row expands and every expanded pin is individually citable.**
`A1, A2, B1` and `A1-A4` become separate records that share the printed name,
type and description and each carry their own stable id (`pin_t0-r3-A2`) and
the cell they expanded from. The shared name is deliberate: pairing four
designators against a name cell that happens to hold four comma-separated
tokens would be a *correspondence* nobody printed, and inventing one is
exactly what clause (a) forbids. The row as printed stays in `row_verbatim`.

The CLI entry point is `cli_pins`, whose flags `cli.py` froze; `find_pins` is
the lookup underneath it, shared with the MCP `find_pin` tool.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from datasheet_analyzer.config import PINS_SCHEMA_VERSION, get_settings
from datasheet_analyzer.derive.provenance import PINS_ARTIFACT
from datasheet_analyzer.models import (
    PIN_TYPE_UNKNOWN,
    PIN_TYPES,
    Confidence,
    ExtractionStats,
    PinRecord,
    PinSet,
    RawDocument,
)
from datasheet_analyzer.retrieve.results import Citation
from datasheet_analyzer.structure.device_tables import (
    KIND_PIN,
    DeviceRow,
    DeviceTableExtraction,
    extract_device_tables,
    record_rejections,
)

log = logging.getLogger(__name__)

#: The checked-in pin-type lexicon. Data, not code — see the file's header.
PIN_LEXICON_PATH = Path(__file__).resolve().parent.parent / "registry" / "pin_types.yaml"

#: Evidence recorded when nothing in the lexicon matched. Not a lexicon entry,
#: which is the point: `type` is `unknown` and no claim is being made.
NO_EVIDENCE = "no lexicon entry matched"

_WS = re.compile(r"\s+")
# Footnote markers a printed cell may carry: "VDD(2)", "Name[1]".
_MARKER = re.compile(r"\(\d+\)|\[\d+\]")
# Separators between several names printed in one cell: "DAC0P, DAC0N".
_NAME_SPLIT = re.compile(r"\s*[,;/]\s*|\s+to\s+", re.IGNORECASE)
# A designator that is a plain number ("12") rather than a package coordinate
# ("A1") or a named pad ("EPAD"). Only used to *describe* a count mismatch.
_NUMERIC_KEY = re.compile(r"\d+")


# --- the lexicon -----------------------------------------------------------


@dataclass(frozen=True)
class PinTypeSpec:
    """One pin type and every phrase that names it, in priority order."""

    type: str
    printed: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageSpec:
    """How a printed pin count is recognized (the package cross-check)."""

    count_words: tuple[str, ...] = ()
    context_words: tuple[str, ...] = ()
    min_count: int = 4


@dataclass(frozen=True)
class PinLexicon:
    """The parsed `pin_types.yaml`, in declaration order."""

    types: tuple[PinTypeSpec, ...] = ()
    directions: frozenset[str] = frozenset()
    package: PackageSpec = field(default_factory=PackageSpec)
    schema_version: int = 0


def _phrases(entries: object, *, where: str) -> tuple[str, ...]:
    """Normalize a YAML list of phrases, warning about the YAML traps.

    `no` is a boolean in YAML 1.1 and `#` opens a comment, so an unquoted
    entry can silently become `False` or lose half its words. The lexicon is
    meant to be editable by anyone; a warning naming the entry is the
    difference between "quote it" and "why did my label stop matching".
    """
    out: list[str] = []
    for entry in entries or ():
        if not isinstance(entry, str):
            log.warning("pin lexicon: %s entry %r is not text — quote it in the YAML", where, entry)
            continue
        phrase = normalize(entry)
        if phrase:
            out.append(phrase)
    return tuple(out)


def _parse_lexicon(data: dict) -> PinLexicon:
    types: list[PinTypeSpec] = []
    for entry in data.get("types") or ():
        if not isinstance(entry, dict):
            log.warning("pin lexicon: type entry %r is not a mapping", entry)
            continue
        name = str(entry.get("type", "")).strip()
        if name not in PIN_TYPES or name == PIN_TYPE_UNKNOWN:
            # `unknown` is what the *absence* of a match means; an entry that
            # claims it, or claims a label the model does not know, would put
            # a word in `PinRecord.type` that no consumer can filter on.
            log.warning("pin lexicon: %r is not one of %s", name, list(PIN_TYPES))
            continue
        types.append(
            PinTypeSpec(
                type=name,
                printed=_phrases(entry.get("printed"), where=f"{name}.printed"),
                names=_phrases(entry.get("names"), where=f"{name}.names"),
                keywords=_phrases(entry.get("keywords"), where=f"{name}.keywords"),
            )
        )
    package = data.get("package") or {}
    return PinLexicon(
        types=tuple(types),
        directions=frozenset(_phrases(data.get("directions"), where="directions")),
        package=PackageSpec(
            count_words=_phrases(package.get("count_words"), where="package.count_words"),
            context_words=_phrases(package.get("context_words"), where="package.context_words"),
            min_count=int(package.get("min_count", 4) or 4),
        ),
        schema_version=int(data.get("schema_version", 0) or 0),
    )


@cache
def load_pin_lexicon(path: Path | None = None) -> PinLexicon:
    """Load and cache `registry/pin_types.yaml` (or a caller's copy of it)."""
    target = Path(path) if path is not None else PIN_LEXICON_PATH
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError) as exc:
        log.warning("pin lexicon unreadable (%s): %s — every pin reads `unknown`", target, exc)
        return PinLexicon()
    if not isinstance(data, dict):
        log.warning("pin lexicon %s is not a mapping — every pin reads `unknown`", target)
        return PinLexicon()
    return _parse_lexicon(data)


def clear_pin_lexicon_cache() -> None:
    """Drop the cached lexicon (tests that write their own copy)."""
    load_pin_lexicon.cache_clear()


def normalize(text: str) -> str:
    """Lowercase, footnote markers dropped, whitespace collapsed.

    Deliberately gentle: `#`, `/`, `+`, `-` and `.` survive, because `CS#`,
    `I/O`, `VS+` and `N.C.` are the printed names and stripping their
    punctuation would merge pins that a datasheet keeps apart.
    """
    return _WS.sub(" ", _MARKER.sub(" ", (text or "").lower())).strip()


def _glob_to_re(pattern: str) -> re.Pattern[str]:
    """`*vdd*` -> a whole-token matcher. Globs, not regexes, on purpose.

    The lexicon is edited by people who know datasheets, not necessarily
    regex; `*` is the one metacharacter and everything else is literal, so a
    `.` in `n.c.` matches a dot and nothing else.
    """
    body = "".join(".*" if part == "*" else re.escape(part) for part in re.split(r"(\*)", pattern))
    return re.compile(rf"^{body}$")


@cache
def _matcher(pattern: str) -> re.Pattern[str]:
    return _glob_to_re(pattern)


def _matches(text: str, patterns: Sequence[str]) -> str:
    """The first pattern that matches `text` whole, or `""`."""
    for pattern in patterns:
        if _matcher(pattern).match(text):
            return pattern
    return ""


def _contains(text: str, phrases: Sequence[str]) -> str:
    """The first phrase that appears in `text`, or `""`."""
    for phrase in phrases:
        if phrase and phrase in text:
            return phrase
    return ""


# --- classification --------------------------------------------------------


@dataclass(frozen=True)
class PinType:
    """A label and the lexicon entry that produced it (never one without the other)."""

    type: str = PIN_TYPE_UNKNOWN
    evidence: str = NO_EVIDENCE


def _printed_type(cell: str, lexicon: PinLexicon) -> PinType | None:
    text = normalize(cell)
    if not text or text in lexicon.directions:
        return None
    for spec in lexicon.types:
        hit = _matches(text, spec.printed)
        if hit:
            return PinType(spec.type, f"printed:{hit}")
    return None


def _name_type(name: str, lexicon: PinLexicon) -> PinType | None:
    """The label the printed *name* carries, or `None` when it carries none.

    One cell may name several pins (`DAC0P, DAC0N`, `GPIO0 to GPIO5`). Each
    token is labelled on its own and they have to agree: a cell reading
    `VDD, GND` is a row this tool cannot label, and picking the first would be
    a coin toss dressed as a reading.
    """
    labels: dict[str, str] = {}
    for token in _NAME_SPLIT.split(normalize(name)):
        token = token.strip()
        if not token:
            continue
        for spec in lexicon.types:
            hit = _matches(token, spec.names)
            if hit:
                labels.setdefault(spec.type, f"name:{hit}")
                break
    if not labels:
        return None
    if len(labels) > 1:
        return PinType(PIN_TYPE_UNKNOWN, "conflict:name=" + "|".join(sorted(labels)))
    label, evidence = next(iter(labels.items()))
    return PinType(label, evidence)


def _description_type(description: str, lexicon: PinLexicon) -> PinType | None:
    text = normalize(description)
    if not text:
        return None
    for spec in lexicon.types:
        hit = _contains(text, spec.keywords)
        if hit:
            return PinType(spec.type, f"description:{hit}")
    return None


def classify_pin_type(
    *,
    printed: str = "",
    name: str = "",
    description: str = "",
    lexicon: PinLexicon | None = None,
) -> PinType:
    """Label one pin from the checked-in lexicon. `unknown` is a real answer.

    Three ranks of evidence, strongest first — the printed type cell, then the
    pin's name, then a phrase in its description — and the first rank that
    says anything decides. Two readings produce `unknown` rather than a label:

    - **the printed cell and the name disagree** (`GND` printed on a pin named
      `VDD18`). The datasheet contradicts itself on that row and this function
      does not get to pick a winner;
    - **one name cell names pins that disagree** (`VDD, GND`) — see
      `_name_type`.

    The returned `evidence` always names what produced the label, so a reader
    can check it against `registry/pin_types.yaml`. Nothing here looks at a
    model, a heuristic score, or the pin's neighbours.
    """
    lex = lexicon or load_pin_lexicon()
    from_printed = _printed_type(printed, lex)
    from_name = _name_type(name, lex)
    if from_name is not None and from_name.type == PIN_TYPE_UNKNOWN:
        return from_name
    if from_printed is not None and from_name is not None and from_printed.type != from_name.type:
        return PinType(
            PIN_TYPE_UNKNOWN,
            f"conflict:{from_printed.evidence} vs {from_name.evidence}",
        )
    for candidate in (from_printed, from_name, _description_type(description, lex)):
        if candidate is not None:
            return candidate
    return PinType(PIN_TYPE_UNKNOWN, NO_EVIDENCE)


def printed_direction(cell: str, lexicon: PinLexicon | None = None) -> str:
    """The direction cell **verbatim**, when it reads as a direction at all.

    A type column that prints `PWR` is printing a type, not a direction, and
    recording `PWR` as a direction would make `--type power` and the printed
    direction two names for the same thing. A column that prints `—` is
    printing "no direction", and that glyph is kept exactly as it is: it is
    what a reader will find on the page.
    """
    lex = lexicon or load_pin_lexicon()
    return (cell or "").strip() if normalize(cell) in lex.directions else ""


# --- the package cross-check ----------------------------------------------


@dataclass(frozen=True)
class PackageCount:
    """What the package/ordering text says the part's pin count is.

    `count` is filled only when every declaration found agrees. Two different
    counts (a part offered in two packages, or a revision history mentioning a
    pinout that was removed) leave it `None` with `ambiguous` set — the honest
    reading, because picking one would turn a cross-check into a guess.
    """

    count: int | None = None
    candidates: tuple[tuple[int, str], ...] = ()
    ambiguous: bool = False

    @property
    def values(self) -> tuple[int, ...]:
        return tuple(sorted({n for n, _text in self.candidates}))


def _count_pattern(lexicon: PinLexicon) -> re.Pattern[str]:
    words = "|".join(re.escape(w) for w in lexicon.package.count_words) or "pin"
    return re.compile(rf"(\d{{1,4}})(\s*[-‐-―−]\s*|\s+)({words})(s?)\b", re.IGNORECASE)


def _texts_of(raw: RawDocument) -> Iterable[str]:
    """Every printed blob a package declaration could be printed in."""
    for section in raw.sections:
        yield section.title
        yield from section.paragraphs
        for table in section.tables:
            yield table.caption
            yield " ".join(table.headers)
            for row in table.grid:
                yield " ".join(row)


def package_pin_count(raw: RawDocument, lexicon: PinLexicon | None = None) -> PackageCount:
    """Read the pin count the package or ordering text prints, if it prints one.

    A documented pure function (invariant 8, clause (b)) over the document's
    own printed text. Three guards keep a sentence out of the count, and each
    of them is a measured necessity rather than a precaution — without them a
    table of contents line (`21 Pin Configuration and Functions`) and a body
    sentence (`connect the IF1 pin to the hybrid`) both parse as declarations:

    1. the number and the count word are **hyphenated** (`324-Ball`) or the
       word is **plural** (`400 PINS`) — how a package is actually written;
    2. the count is at least `package.min_count` — no package has three pins,
       but plenty of sentences mention pin 1;
    3. the same blob of text also names a **package** (`BGA`, `VQFN`,
       `package`, `orderable`, …) from the lexicon's `context_words`.

    Disagreeing declarations return `ambiguous` with `count` left `None`.
    """
    lex = lexicon or load_pin_lexicon()
    pattern = _count_pattern(lex)
    candidates: list[tuple[int, str]] = []
    for text in _texts_of(raw):
        blob = normalize(text)
        if not blob or not _contains(blob, lex.package.context_words):
            continue
        for match in pattern.finditer(blob):
            count = int(match.group(1))
            hyphenated = "-" in match.group(2) or any(ch in match.group(2) for ch in "‐‑‒–—―−")
            plural = bool(match.group(4))
            if count < lex.package.min_count or not (hyphenated or plural):
                continue
            candidates.append((count, _WS.sub(" ", text).strip()[:160]))
    values = {n for n, _text in candidates}
    if len(values) == 1:
        return PackageCount(count=next(iter(values)), candidates=tuple(candidates))
    return PackageCount(count=None, candidates=tuple(candidates), ambiguous=len(values) > 1)


def cross_check_warnings(pins: Sequence[PinRecord], declared: PackageCount) -> list[str]:
    """Compare the record count against the printed package count. Warnings only.

    Never fatal and never a correction: a pin table that yields fewer records
    than the package has pins is still the best record of those pins that
    exists, and a designer is better served by "these 210, and the package
    says 324" than by silence. A mismatch is usually one of three things and
    the warning says which is plausible: pads that carry a name instead of a
    number (`EPAD`, `DAP`), a printed table that genuinely lists a subset, or
    a row the layout engine misread.
    """
    warnings: list[str] = []
    if declared.ambiguous:
        printed = ", ".join(str(v) for v in declared.values)
        warnings.append(
            f"package pin count is ambiguous — the document prints {printed}; "
            f"no cross-check was made against the {len(pins)} pin records"
        )
        return warnings
    if declared.count is None or not pins:
        return warnings
    if declared.count == len(pins):
        return warnings
    named = [p.pin for p in pins if not _NUMERIC_KEY.search(p.pin)]
    tail = (
        f" ({len(named)} of them carry a name rather than a number: {', '.join(sorted(named)[:4])})"
        if named
        else ""
    )
    warnings.append(
        f"package cross-check: the package/ordering text declares "
        f"{declared.count} pins but the pin table yields {len(pins)} "
        f"records{tail} — the records are what was printed in the table; "
        f"the difference is not resolved here"
    )
    return warnings


# --- building `pins.json` --------------------------------------------------


@dataclass(frozen=True)
class PinBuild:
    """What one document yielded: a pin set, or nothing and the reason why.

    `pinset` is `None` when the document printed no pin table this tool could
    read — including the case where it printed one and validation rejected it.
    That is the honest artifact: no file at all, rather than an empty or
    half-filled one that reads as "this part has no pins".
    """

    pinset: PinSet | None = None
    rejection_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    declared: PackageCount = field(default_factory=PackageCount)

    @property
    def n_pins(self) -> int:
        return len(self.pinset.pins) if self.pinset else 0


def _record(row: DeviceRow, lexicon: PinLexicon) -> PinRecord:
    """One `DeviceRow` -> one `PinRecord`, every printed cell copied verbatim."""
    name = row.value("name")
    printed_type = row.value("type")
    description = row.value("description")
    label = classify_pin_type(
        printed=printed_type, name=name, description=description, lexicon=lexicon
    )
    return PinRecord(
        pin=row.key,
        name=name,
        type=label.type,
        direction=printed_direction(printed_type, lexicon),
        description=description,
        section=row.section,
        table_index=row.table_index,
        row_index=row.row_index,
        page=row.page,
        row_verbatim=list(row.row_verbatim),
        expanded_from=row.expanded_from,
        type_evidence=label.evidence,
        confidence=row.confidence,
    )


def build_pins(
    raw: RawDocument,
    part_number: str = "",
    *,
    lexicon: PinLexicon | None = None,
) -> PinBuild:
    """Read one document's pin table, or report honestly that there is none.

    The whole pipeline for this artifact: the device-table layer identifies,
    maps, validates and expands; this function labels, cross-checks and
    packages. It never raises — a document with no pin table is the common
    case, not an error — and it never emits a `PinSet` from a rejected table.
    """
    lex = lexicon or load_pin_lexicon()
    extraction: DeviceTableExtraction = extract_device_tables(raw, kind=KIND_PIN)
    reasons = tuple(extraction.rejection_reasons)
    rows = extraction.rows
    if not rows:
        return PinBuild(pinset=None, rejection_reasons=reasons)

    pins = [_record(row, lex) for row in rows]
    declared = package_pin_count(raw, lex)
    warnings = cross_check_warnings(pins, declared)
    pinset = PinSet(
        schema_version=PINS_SCHEMA_VERSION,
        part_number=part_number,
        doc_hash=raw.source.content_hash,
        pins=pins,
        rejection_reasons=list(reasons),
        warnings=warnings,
        declared_pin_count=declared.count,
    )
    return PinBuild(
        pinset=pinset,
        rejection_reasons=reasons,
        warnings=tuple(warnings),
        declared=declared,
    )


def record_pin_rejections(stats: ExtractionStats | None, build: PinBuild) -> ExtractionStats | None:
    """Join a build's rejected pin tables to the document's rejection reasons.

    Delegates to the device-table layer's own recorder so device tables land
    in exactly the same place parametric ones do — `dsa status` prints that
    list, which is where a pin table that was refused has to show up if the
    refusal is to mean anything.
    """
    return record_rejections(stats, build.rejection_reasons)


def write_pinset(doc_dir: Path, pinset: PinSet, *, shared: bool = False) -> Path:
    """Write `pins.json` beside the document's other artifacts.

    `shared` blanks `part_number`, exactly as `publish/writer.py` does for
    `specs.json`: which part published a shared document first is an accident
    of ordering, and stamping it into the bytes would make two parts disagree
    about the file's contents and rewrite it forever. Readers take the part
    from `manifest.part_number`.

    Written **atomically and only when the bytes change**, for the same reason
    every other shared artifact is: `dsa batch --workers N` can have two jobs
    publishing the same shared document at once, and a half-written
    `pins.json` would read as a corrupt corpus to every part that references
    it.
    """
    target = Path(doc_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / PINS_ARTIFACT
    payload = pinset.model_copy(update={"part_number": ""}) if shared else pinset
    text = payload.model_dump_json(indent=2)
    try:
        if path.read_text(encoding="utf-8") == text:
            return path
    except (OSError, ValueError):
        pass
    fd, tmp = tempfile.mkstemp(dir=target, prefix=f"{PINS_ARTIFACT}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def load_pinset(doc_dir: Path) -> PinSet | None:
    """Read one document's `pins.json`; `None` when absent or unreadable.

    Unreadable warns and returns `None` rather than raising, the rule every
    other artifact reader in the corpus follows: one corrupt file must not
    take a part down.
    """
    path = Path(doc_dir) / PINS_ARTIFACT
    if not path.is_file():
        return None
    try:
        return PinSet.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("unreadable %s: %s", path, exc)
        return None


@dataclass(frozen=True)
class PartPins:
    """One part's published pin records, with the documents they came from."""

    part: str
    sets: tuple[tuple[str, PinSet], ...] = ()  # (document directory name, set)

    @property
    def pins(self) -> tuple[PinRecord, ...]:
        return tuple(pin for _doc, pinset in self.sets for pin in pinset.pins)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(w for _doc, pinset in self.sets for w in pinset.warnings)


def load_part_pins(part_dir: Path, part: str = "") -> PartPins:
    """Every `pins.json` a built part references, wherever it was published.

    Documents may live under the part or once in the shared library store, so
    the manifest is what says where they are — the same resolution
    `publish.document_dirs` performs for every other artifact.
    """
    from datasheet_analyzer.publish import document_dirs, read_manifest

    part_dir = Path(part_dir)
    manifest = read_manifest(part_dir)
    if manifest is None:
        return PartPins(part=part or part_dir.name)
    dirs = document_dirs(manifest, part_dir=part_dir)
    sets: list[tuple[str, PinSet]] = []
    for source in manifest.documents:
        doc_dir = dirs.get(source.content_hash)
        if doc_dir is None:
            continue
        pinset = load_pinset(doc_dir)
        if pinset is not None:
            sets.append((doc_dir.name, pinset))
    return PartPins(part=part or manifest.part_number or part_dir.name, sets=tuple(sets))


# --- lookup ----------------------------------------------------------------


@dataclass(frozen=True)
class PinHit:
    """One matching pin, with the citation a reader verifies it by."""

    record: PinRecord
    citation: Citation
    matched_via: str = "all"

    @property
    def confidence(self) -> str:
        value = self.record.confidence
        return str(getattr(value, "value", value) or "") or Confidence.UNKNOWN.value

    def as_dict(self) -> dict:
        """The one JSON shape for a pin hit — the CLI and MCP both emit this."""
        return {
            "id": self.record.id,
            "pin": self.record.pin,
            "name": self.record.name,
            "type": self.record.type,
            "direction": self.record.direction,
            "description": self.record.description,
            "type_evidence": self.record.type_evidence,
            "expanded_from": self.record.expanded_from,
            "part": self.citation.part,
            "doc": self.citation.doc,
            "page": self.record.page,
            "citation": self.citation.label,
            "matched_via": self.matched_via,
            "confidence": self.confidence,
        }


def _matched_via(record: PinRecord, term: str) -> str:
    """Which printed field the query term was found in (strongest first)."""
    if not term:
        return "all"
    if term == normalize(record.pin):
        return "pin"
    if term in normalize(record.name):
        return "name"
    if term in normalize(record.pin):
        return "pin-substring"
    return "description"


def find_pins(
    part_pins: PartPins,
    *,
    q: str = "",
    pin_type: str = "",
) -> list[PinHit]:
    """Pins matching a free-text term and/or a type, in printed order.

    `q` is matched against the designator, the name and the description —
    the three things a designer knows a pin by ("A1", "VDD18", "ground") — and
    an exact designator or a name substring outranks a description mention in
    `matched_via`, so a caller can tell a direct hit from a mention.

    `pin_type` filters on the lexicon label. It is an exact match against
    `PIN_TYPES`, including `unknown`: asking for the pins this tool could not
    label is a legitimate and useful question, and hiding them would make the
    lexicon's gaps invisible.
    """
    term = normalize(q)
    wanted = (pin_type or "").strip().lower()
    hits: list[PinHit] = []
    for doc, pinset in part_pins.sets:
        for record in pinset.pins:
            if wanted and record.type != wanted:
                continue
            if term and not any(
                term in normalize(text) for text in (record.pin, record.name, record.description)
            ):
                continue
            hits.append(
                PinHit(
                    record=record,
                    citation=Citation(
                        doc=doc,
                        doc_hash=pinset.doc_hash,
                        section=record.section,
                        page_start=record.page,
                        page_end=record.page,
                        part=part_pins.part,
                        needle=record.name or record.pin,
                    ),
                    matched_via=_matched_via(record, term),
                )
            )
    return hits


def format_pin_hits(hits: Sequence[PinHit], limit: int = 40, *, show_part: bool = False) -> str:
    """Render pin hits for a human or an agent, one line each, always cited."""
    if not hits:
        return "No matching pins."
    lines: list[str] = []
    for hit in hits[:limit]:
        rec = hit.record
        prefix = f"[{hit.citation.part}] " if show_part and hit.citation.part else ""
        direction = f" {rec.direction}" if rec.direction else ""
        description = f" — {rec.description}" if rec.description else ""
        lines.append(
            f"{prefix}{rec.pin}  {rec.name}  [{rec.type}{direction}] "
            f"({hit.citation.pages}){description}"
        )
    if len(hits) > limit:
        lines.append(f"... and {len(hits) - limit} more matches")
    return "\n".join(lines)


def type_counts(pins: Iterable[PinRecord]) -> dict[str, int]:
    """How many pins carry each lexicon label, `PIN_TYPES` order, zeros dropped."""
    counts = {t: 0 for t in PIN_TYPES}
    for pin in pins:
        counts[pin.type] = counts.get(pin.type, 0) + 1
    return {t: n for t, n in counts.items() if n}


def no_pins_message(part: str) -> str:
    """Why a built part has no pin table, said out loud rather than as silence.

    An empty result set from a part that never published `pins.json` reads as
    "this part has no pins", which is never true. The two states are different
    and the message says which one this is.
    """
    return (
        f"{part}: no pin table was published for this part. Either the "
        f"datasheet prints none this tool could read, or the candidate table "
        f"failed validation and was rejected whole — `dsa status` lists the "
        f"rejection reasons. Nothing partial is published for a pin table."
    )


# --- CLI -------------------------------------------------------------------


def _part_dirs(args: argparse.Namespace) -> tuple[list[tuple[str, Path]], str]:
    """`([(part, dir)], "")` for the requested scope, or `([], reason)`.

    Scope resolution is `retrieve/scope.py`'s rule (ADR 0006: exactly one of
    `--part` / `--project`), reused rather than re-decided here. Pins are read
    off published artifacts rather than through `Retriever`, so this resolves
    to directories instead of to a retriever.
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


def cli_pins(args: argparse.Namespace) -> int:
    """`dsa pins --part X [--q VDD] [--type power] [--json]`.

    Exit codes follow the other deterministic lookups exactly: 0 for hits,
    1 for an honest no-match, 2 for a scope that could not be resolved. A part
    that published no `pins.json` is *not* a no-match — it is told apart from
    one in the message and on stderr, because the two mean different things to
    someone deciding whether to open the PDF.
    """
    parts, reason = _part_dirs(args)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    show_part = bool((getattr(args, "project", "") or "").strip())
    wanted = (getattr(args, "type", "") or "").strip().lower()
    q = getattr(args, "q", "") or ""

    hits: list[PinHit] = []
    without: list[str] = []
    warnings: list[str] = []
    for part, part_dir in parts:
        part_pins = load_part_pins(part_dir, part)
        if not part_pins.sets:
            without.append(part)
            continue
        warnings.extend(part_pins.warnings)
        hits.extend(find_pins(part_pins, q=q, pin_type=wanted))

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for part in without:
        print(no_pins_message(part), file=sys.stderr)

    if getattr(args, "json", False):
        payload = {
            "part": getattr(args, "part", ""),
            "project": getattr(args, "project", ""),
            "query": {"q": q, "type": wanted},
            "hits": [h.as_dict() for h in hits],
            "counts": type_counts(h.record for h in hits),
            "parts_without_pins": without,
            "warnings": warnings,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 1
    print(format_pin_hits(hits, show_part=show_part))
    return 0 if hits else 1
