"""The provenance contract every derived artifact conforms to (invariant 8).

Phase 6 creates the first artifacts in this tool that are not verbatim
extraction output — pin tables, register maps, design cards, cross-part
comparisons. That puts pressure on invariant 1 ("LLM writes indexes, never
content"), and ADR 0007 resolves it by making derivation *deterministic and
traceable* rather than forbidden:

> A derived artifact may contain only **(a)** values copied verbatim from a
> spec, table or pin record; **(b)** values computed from those by a
> documented pure function; **(c)** structural labels drawn from a checked-in
> lexicon. Every field carries `source` (record id + page) and `derivation`
> (the named rule that produced it). No model call may appear anywhere in the
> derivation path. A derived artifact that cannot fill a field leaves it null
> and says so — it never interpolates, and it never emits a plausible default.

This module is what makes that claim *checkable* instead of aspirational:

- **`source` has one format**, `<artifact>#<record id>` — `parse_source` and
  `models.source_ref` are its only two ends.
- **`resolve_source` turns a source string back into the record and the
  printed page it names.** A citation that cannot be resolved is not a
  citation, and this is the function that says so. It reads only JSON already
  on disk: no network, no model, no rebuild.
- **`check_provenance` walks any derived artifact** — a `Card`, a list of
  them, anything holding `DerivedValue`s at any depth — and returns every
  place the invariant is broken. Phase 6's tickets use it as their
  invariant-8 test; there is deliberately one implementation of the rule
  rather than one per artifact.

**Legacy tolerance, on purpose.** `SpecRecord.id` is a *computed* field: it is
a pure function of the record's own coordinates, so `resolve_source` can
reconstruct it for a `specs.json` published before the id existed and resolve
citations against a corpus nobody has rebuilt yet. The
`SPECS_SCHEMA_VERSION` bump still republishes those files; this only means a
card is not unresolvable in the meantime.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from datasheet_analyzer.corpus_ref import resolve_artifact_ref
from datasheet_analyzer.models import (
    VALUE_KINDS,
    DerivedValue,
    pin_record_id,
    register_record_id,
    source_ref,
    spec_record_id,
)

#: The on-disk names of every artifact a `source` may point at. Frozen here so
#: a card writes the same string a resolver reads and neither hardcodes it.
SPECS_ARTIFACT = "specs.json"
PLOTS_ARTIFACT = "plots.json"
PINS_ARTIFACT = "pins.json"
REGISTERS_ARTIFACT = "registers.json"
#: Design cards live in a directory under the *part*, not under a document: a
#: card composes records from several documents and belongs to none of them.
CARDS_DIRNAME = "cards"

#: Separates the artifact from the record id inside a `source` string.
SOURCE_SEPARATOR = "#"

#: A `derivation` names the pure function that produced the value, and a
#: pipeline of them chains with `+` (`parse_quantity+si_normalize`). The shape
#: is checkable without a central registry of rule names, which is what keeps
#: ten parallel tickets from having to edit one file to add a rule.
DERIVATION_RULE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\+[a-z][a-z0-9_]*)*$")

__all__ = [
    "CARDS_DIRNAME",
    "DERIVATION_RULE_RE",
    "PINS_ARTIFACT",
    "PLOTS_ARTIFACT",
    "REGISTERS_ARTIFACT",
    "SOURCE_SEPARATOR",
    "SPECS_ARTIFACT",
    "ResolvedSource",
    "check_provenance",
    "describe_problems",
    "is_derivation_rule",
    "iter_derived_values",
    "parse_source",
    "resolve_source",
    "source_ref",
]


def is_derivation_rule(name: str) -> bool:
    """Whether `name` is a well-formed derivation rule name.

    Well-formed is not the same as *documented* — no checker can prove a
    function was written down. This is the mechanical half of clause (b), and
    it catches the failure that actually happens: a derivation left blank, or
    filled with prose ("estimated from the plot") that no function answers to.
    """
    return bool(DERIVATION_RULE_RE.match(name or ""))


def parse_source(source: str) -> tuple[str, str] | None:
    """`"specs.json#rec_s4.5-t2-r13"` -> `("specs.json", "rec_s4.5-t2-r13")`.

    `None` for anything that is not a source string. Split on the *last*
    separator so a path may contain one, and normalized to POSIX separators
    because a source is data, not a local path.
    """
    text = (source or "").strip().replace("\\", "/")
    if SOURCE_SEPARATOR not in text:
        return None
    artifact, _, record = text.rpartition(SOURCE_SEPARATOR)
    artifact, record = artifact.strip(), record.strip()
    if not artifact or not record:
        return None
    return artifact, record


@dataclass(frozen=True)
class ResolvedSource:
    """What a `source` string turned out to name.

    `record` is the published dict rather than a model, because the resolver
    must work against artifacts written by any ticket in the phase (and by an
    older version of this one) without importing every model that ever
    existed.
    """

    source: str
    artifact: str
    record_id: str
    path: Path
    record: dict[str, Any]
    page: int | None


def _synthetic_record_id(artifact: str, node: dict[str, Any]) -> str:
    """Reconstruct a record's id for an artifact published before ids existed.

    Ids are pure functions of a record's coordinates, so this is a
    reconstruction and never a guess: it returns exactly what the current
    model computes for the same row, or `""` when the record does not carry
    the coordinates the id is built from.
    """
    name = artifact.rsplit("/", 1)[-1]
    if "row_index" not in node:
        return ""
    try:
        table_index = int(node.get("table_index", 0))
        row_index = int(node["row_index"])
    except (TypeError, ValueError):
        return ""
    if name == SPECS_ARTIFACT:
        key = str(node.get("section_key") or node.get("section", ""))
        return spec_record_id(key, table_index, row_index)
    if name == PINS_ARTIFACT:
        return pin_record_id(table_index, row_index, str(node.get("pin", "")))
    if name == REGISTERS_ARTIFACT:
        return register_record_id(table_index, row_index)
    return ""


def _walk_records(
    node: Any, artifact: str, page: int | None = None
) -> Iterator[tuple[str, dict[str, Any], int | None]]:
    """Every identifiable record in a loaded artifact, with its printed page.

    The page is inherited downward, so a nested record carrying none — a
    `BitField` inside a `RegisterRecord`, say — still resolves to the page its
    parent was printed on, which is the page a reader would open.
    """
    if isinstance(node, dict):
        own = node.get("page")
        if isinstance(own, int):
            page = own
        found = node.get("id")
        if not isinstance(found, str) or not found:
            found = _synthetic_record_id(artifact, node)
        if found:
            yield found, node, page
        for value in node.values():
            yield from _walk_records(value, artifact, page)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_records(value, artifact, page)


def _candidate_paths(
    artifact: str,
    roots: Sequence[Path | str],
    library_dir: Path | str | None,
) -> Iterator[Path]:
    for root in roots:
        try:
            yield resolve_artifact_ref(artifact, part_dir=root, library_dir=library_dir)
        except ValueError:
            # A shared `@library/…` reference with no library root to resolve
            # against. Refusing is `corpus_ref`'s rule and it is the right one:
            # joining it onto the part directory would name the wrong copy.
            continue


def resolve_source(
    source: str,
    *,
    roots: Path | str | Sequence[Path | str] = (),
    library_dir: Path | str | None = None,
) -> ResolvedSource | None:
    """Resolve `source` back to the record and printed page it names.

    `roots` is what the artifact path is relative to — a document directory
    (`parts/X/docs/datasheet-1f2e3d4c/`) when the source is bare
    (`specs.json#…`), a part directory when it is corpus-relative
    (`docs/datasheet-1f2e3d4c/specs.json#…`), or both. Each is tried in order
    and the first that holds the record wins. An `@library/…` source needs
    `library_dir`, exactly as a manifest reference does.

    `None` means the citation does not resolve — a missing file, an unreadable
    one, or a record id nothing on disk carries. It is never an exception: a
    broken citation is a finding to report, not a crash.
    """
    parsed = parse_source(source)
    if parsed is None:
        return None
    artifact, record_id = parsed
    if isinstance(roots, (str, Path)):
        roots = [roots]
    for path in _candidate_paths(artifact, list(roots), library_dir):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for found_id, record, page in _walk_records(data, artifact):
            if found_id == record_id:
                return ResolvedSource(
                    source=source,
                    artifact=artifact,
                    record_id=record_id,
                    path=Path(path),
                    record=record,
                    page=page,
                )
    return None


def iter_derived_values(obj: Any, *, path: str = "") -> Iterator[tuple[str, DerivedValue]]:
    """Every `DerivedValue` inside `obj`, with a readable path to each.

    Walks pydantic models, dicts, lists and tuples to any depth, so a caller
    never has to know the shape of the artifact it is checking. The path
    (`rows[3].values[max]`) is what makes a reported violation actionable.
    """
    if isinstance(obj, DerivedValue):
        yield path or "<value>", obj
        return
    if isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            child = f"{path}.{name}" if path else name
            yield from iter_derived_values(getattr(obj, name, None), path=child)
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from iter_derived_values(value, path=f"{path}[{key}]")
        return
    if isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            yield from iter_derived_values(value, path=f"{path}[{index}]")


def _check_value(
    value: DerivedValue,
    *,
    roots: Sequence[Path | str],
    library_dir: Path | str | None,
) -> list[str]:
    problems: list[str] = []
    if value.value_kind and value.value_kind not in VALUE_KINDS:
        problems.append(f"value_kind {value.value_kind!r} is not one of {list(VALUE_KINDS)}")
    if not value.filled:
        # The "and says so" half of the invariant. An empty envelope with no
        # reason is indistinguishable from an oversight, and reads to a
        # designer as "the datasheet does not say" when that was never checked.
        if not value.null_reason.strip():
            problems.append("null value carries no null_reason")
        return problems

    if not is_derivation_rule(value.derivation):
        problems.append(
            f"derivation {value.derivation!r} is not a rule name "
            f"(lowercase identifiers joined by '+')"
        )
    parsed = parse_source(value.source)
    if parsed is None:
        problems.append(f"source {value.source!r} is not '<artifact>#<record id>'")
    if value.page is None:
        problems.append("filled value carries no page")
    elif value.page < 1:
        problems.append(f"page {value.page} is not a printed page number")
    if parsed is None or not roots:
        return problems

    resolved = resolve_source(value.source, roots=roots, library_dir=library_dir)
    if resolved is None:
        problems.append(f"source {value.source!r} resolves to no record on disk")
        return problems
    if resolved.page is not None and value.page is not None and resolved.page != value.page:
        problems.append(f"cites p.{value.page} but {value.source} is printed on p.{resolved.page}")
    return problems


def check_provenance(
    obj: Any,
    *,
    roots: Path | str | Sequence[Path | str] = (),
    library_dir: Path | str | None = None,
) -> list[str]:
    """Every way `obj` breaks invariant 8, as readable strings. Empty is a pass.

    With `roots`, each filled value's `source` is resolved against the
    artifacts on disk and its page checked against the record's — the full
    test. Without them the check is structural only (the shape of `source`,
    `derivation` and `page`; a reason on every null), which is what a unit
    test over synthetic data can assert without building a corpus.
    """
    if isinstance(roots, (str, Path)):
        roots = [roots]
    roots = list(roots)
    problems: list[str] = []
    for path, value in iter_derived_values(obj):
        problems.extend(
            f"{path}: {problem}"
            for problem in _check_value(value, roots=roots, library_dir=library_dir)
        )
    return problems


def describe_problems(problems: Sequence[str], *, subject: str = "derived artifact") -> str:
    """Render `check_provenance` output as an assertion message worth reading."""
    if not problems:
        return f"{subject}: provenance intact"
    lines = "\n".join(f"  - {p}" for p in problems)
    return f"{subject}: {len(problems)} provenance violation(s)\n{lines}"
