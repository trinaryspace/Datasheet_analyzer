"""The numeric layer against real corpora (phase 6, ticket 02).

The unit tests prove the grammar; this proves the two things only a real corpus
can show. First, that running the layer over a published part changes **no**
printed string — the additive promise, checked cell by cell across 1,100-odd
records rather than on a hand-made row. Second, the parse rate itself, per
section, which is a *measurement* for the phase report and not a target: a
section whose values read `See Figure 7` is supposed to score low, and tuning
the grammar until it scores high would be the failure this whole phase is
organised against.

The two TI reference corpora are measured here, off the ones committed under
`parts/`; the four layout-floor gate parts are measured in
`test_phase4_layout_gate.py`, which already builds them, so the six-corpus
number costs no second build.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.models import SpecRecord
from datasheet_analyzer.retrieve import CorpusIndex
from datasheet_analyzer.structure.quantities import (
    annotate_record,
    parse_population,
    parse_rate,
)

PARTS = Path(__file__).parent.parent.parent / "parts"

# Measured on the corpora committed under `parts/` (see
# `scripts/measure_parse_rate.py`, which reproduces the table). Floors, not
# targets: they fail on a regression in the grammar, and a genuine improvement
# is recorded by raising them.
REFERENCE_FLOORS = {"AFE7950": 0.93, "AFE7953": 0.92}

VERBATIM_FIELDS = (
    "symbol", "name", "conditions", "table_conditions",
    "min", "typ", "max", "value",
)


def _snapshot(record: SpecRecord) -> tuple:
    return (
        tuple(getattr(record, f) for f in VERBATIM_FIELDS),
        record.unit.verbatim,
        record.unit.canonical,
        tuple(record.row_verbatim),
    )


@pytest.fixture(params=sorted(REFERENCE_FLOORS))
def reference(request) -> tuple[str, list[SpecRecord]]:
    """One committed reference corpus's spec records."""
    part = request.param
    if not (PARTS / part / "manifest.json").exists():
        pytest.skip(f"committed parts/{part} corpus not present")
    index = CorpusIndex.load(PARTS / part)
    records = [record for doc in index.docs for record in doc.specs]
    assert records, f"{part} publishes no spec records — the measurement is vacuous"
    return part, records


class TestVerbatimSurvivesARealCorpus:
    def test_no_printed_cell_of_any_record_is_mutated(self, reference):
        part, records = reference
        before = [_snapshot(record) for record in records]
        for record in records:
            annotate_record(record)
        assert [_snapshot(record) for record in records] == before, part


class TestParseRateIsMeasuredAndPrinted:
    def test_rate_holds_its_floor_and_breaks_down_by_section(self, reference, capsys):
        part, records = reference
        rate = parse_rate(records)
        with capsys.disabled():
            print()
            print(rate.as_table(title=part))
        assert rate.n_records == len(records)
        assert sum(total for _, total in rate.by_section.values()) == len(records)
        assert sum(done for done, _ in rate.by_section.values()) == rate.n_parsed
        assert rate.rate >= REFERENCE_FLOORS[part], (
            f"{part} parse rate fell to {rate.rate:.0%}"
        )

    def test_every_section_with_records_appears_in_the_breakdown(self, reference):
        _, records = reference
        rate = parse_rate(records)
        assert set(rate.by_section) == {record.section for record in records}


class TestNothingIsSilentlyDropped:
    def test_the_population_accounts_for_every_record(self, reference):
        """Invariant 8's honesty half on a real corpus: a comparison over these
        records reports its unparsed rows rather than shrinking its input."""
        part, records = reference
        population = parse_population(records, role="max")
        assert population.total == len(records), part
        assert len(population.listing()) == population.n_unparsed
        assert population.describe().endswith(
            "rows could not be parsed"
        ) or population.describe().startswith("all ")
