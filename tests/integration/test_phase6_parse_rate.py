"""Phase 6, ticket 02: the numeric layer measured against the built corpora.

Two questions a synthetic fixture cannot answer:

1. **What fraction of real printed spec cells parse?** The unit tests prove
   each shape in the plan's table; only a real corpus says how much of a
   datasheet is actually made of those shapes. The rate is measured per part
   *and broken down by section*, printed for the phase report, and held to a
   floor well under what was measured - the floor exists to catch a
   regression, not to be fitted to.
2. **Does the layer really leave the print alone?** The unit test snapshots
   four hand-built records; this one snapshots every verbatim field of every
   record of every built part - thousands of strings whose exact bytes are
   what a designer checks against the page - and compares them after the
   layer has run over all of them.

Hermetic in the sense that matters: it reads JSON already on disk, never the
network, never a model, and skips itself when no corpus is built (AGENTS.md
invariant 4's documented exception for corpus gates).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

from datasheet_analyzer.models import ParseConfidence, SpecRecord
from datasheet_analyzer.structure.quantities import annotate_records, coverage

REPO = Path(__file__).parent.parent.parent
PARTS = REPO / "parts"

#: A floor to beat and to record, not a target to fit to. Measured at 96.3%
#: across the corpora built in this tree when the layer landed; a build that
#: drops below this has regressed the grammar, not met a quota.
PARSE_RATE_FLOOR = 0.85

#: Every field of a `SpecRecord` holding something the datasheet printed.
VERBATIM_FIELDS = (
    "symbol",
    "name",
    "conditions",
    "table_conditions",
    "min",
    "typ",
    "max",
    "value",
    "unit",
    "row_verbatim",
    "footnotes",
    "cited_markers",
)


def _corpora() -> list[tuple[str, Path]]:
    """Every `specs.json` reachable from `parts/`, as (part number, path)."""
    if not PARTS.is_dir():
        return []
    return [(specs.parents[2].name, specs) for specs in sorted(PARTS.glob("*/docs/*/specs.json"))]


def _records(specs: Path) -> list[SpecRecord]:
    payload = json.loads(specs.read_text(encoding="utf-8"))
    return [SpecRecord.model_validate(row) for row in payload.get("records", [])]


def _verbatim(records: list[SpecRecord]) -> list[dict[str, object]]:
    return [{field: record.model_dump()[field] for field in VERBATIM_FIELDS} for record in records]


@pytest.fixture(scope="module")
def corpora() -> list[tuple[str, list[SpecRecord]]]:
    found = _corpora()
    if not found:
        pytest.skip("no built corpus in this tree - build a part to measure the parse rate")
    return [(part, _records(specs)) for part, specs in found]


def test_parse_rate_across_built_corpora_is_measured_and_printed(
    corpora: list[tuple[str, list[SpecRecord]]],
) -> None:
    """The phase-report number, per part and per section, with the misses listed."""
    lines: list[str] = ["", "parse rate across built corpora (phase 6, ticket 02)", "=" * 72]
    total_considered = total_parsed = 0

    for part, records in corpora:
        whole = coverage(records)
        total_considered += whole.considered
        total_parsed += whole.parsed
        lines.append(
            f"{part:16s} records={len(records):5d} with-values={whole.considered:5d} "
            f"parsed={whole.parsed:5d} rate={whole.rate:6.1%} blank={whole.blank:5d}"
        )
        by_section: dict[str, list[SpecRecord]] = defaultdict(list)
        for record in records:
            by_section[record.section or "(unsectioned)"].append(record)
        for section, rows in sorted(by_section.items()):
            section_coverage = coverage(rows)
            if not section_coverage.considered:
                continue
            lines.append(
                f"    §{section:10s} with-values={section_coverage.considered:5d} "
                f"parsed={section_coverage.parsed:5d} rate={section_coverage.rate:6.1%}"
            )
        if whole.unparsed:
            lines.append("    " + whole.describe(limit=8).replace("\n", "\n    "))

    rate = total_parsed / max(total_considered, 1)
    lines += [
        "-" * 72,
        (
            f"OVERALL parts={len(corpora)} with-values={total_considered} "
            f"parsed={total_parsed} rate={rate:.1%}"
        ),
        "",
    ]
    report = "\n".join(lines)
    print(report)

    assert total_considered > 0, "no spec record in any built corpus printed a value"
    assert rate >= PARSE_RATE_FLOOR, report


def test_layer_mutates_no_verbatim_field_of_any_built_record(
    corpora: list[tuple[str, list[SpecRecord]]],
) -> None:
    """Invariant 8, checked against every printed string in every built part."""
    for part, records in corpora:
        before = _verbatim(records)
        annotate_records(records)
        after = _verbatim(records)
        assert after == before, f"{part}: the numeric layer altered a verbatim field"


def test_every_parsed_record_carries_a_kind_and_every_unparsed_one_carries_nothing(
    corpora: list[tuple[str, list[SpecRecord]]],
) -> None:
    """No half-filled record: a number implies a kind, and no number implies no grade."""
    for part, records in corpora:
        annotate_records(records)
        for record in records:
            where = f"{part} {record.id}"
            if record.parse_confidence is ParseConfidence.NONE:
                assert record.value_si is None, where
                assert record.value_kind == "", where
                assert record.unit_si == "", where
            else:
                assert record.value_si is not None, where
                assert record.value_kind, where
                assert record.value_si_cell, where


#: Real unit columns from the built corpora, with the scale each implies.
#: Half of them are logarithmic or dimensionless and must *not* be scaled -
#: the mistake this pins is `dBm` read as milli-`dB`, which would be silent,
#: plausible, and wrong by three orders of magnitude.
SCALE_BY_PRINTED_UNIT = {
    "mA": 1e-3,
    "mW": 1e-3,
    "mV": 1e-3,
    "MHz": 1e6,
    "GHz": 1e9,
    "ns": 1e-9,
    "ps": 1e-12,
    "Gbps": 1e9,
    "V": 1.0,
    "dB": 1.0,
    "dBc": 1.0,
    "dBm": 1.0,
    "dBFS": 1.0,
    "dBc/Hz": 1.0,
    "°C": 1.0,
}

_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

#: A floor on the spot check itself, so a corpus that stopped producing unit
#: columns cannot turn this test into a silent no-op.
MIN_SPOT_CHECKS = 200


def test_printed_values_scale_by_their_unit_column_and_only_by_that(
    corpora: list[tuple[str, list[SpecRecord]]],
) -> None:
    """The scaling rule, checked against hundreds of real printed rows.

    Spec tables put the unit in its own column, so this exercises the
    `unit_hint` path on the print it was written for: a cell reading `1350`
    under a `mA` column is 1.35 A, and a cell reading `-155` under `dBc/Hz` is
    -155 - unscaled, because a logarithmic unit takes no prefix.
    """
    checked = 0
    for part, records in corpora:
        annotate_records(records)
        for record in records:
            scale = SCALE_BY_PRINTED_UNIT.get(record.unit.verbatim.strip())
            if scale is None:
                continue
            parsed = {"min": record.min_si, "typ": record.typ_si, "max": record.max_si}
            for cell, got in parsed.items():
                printed = (getattr(record, cell) or "").strip()
                if not _PLAIN_NUMBER.match(printed):
                    continue
                where = f"{part} {record.id} [{cell}] {printed!r} {record.unit.verbatim!r}"
                assert got == pytest.approx(float(printed) * scale), where
                checked += 1

    assert checked >= MIN_SPOT_CHECKS, f"only {checked} real rows spot-checked"
