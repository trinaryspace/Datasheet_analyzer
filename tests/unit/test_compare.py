"""Cross-part comparison: alignment, deltas, and everything it refuses to do.

Ticket 09. `dsa compare` is the one derived artifact whose citations span two
corpora, and the two ways it could quietly lie are the two things this file
spends most of its assertions on:

- **a mis-alignment** — two rows put in one row of the table because they share
  a symbol, when the datasheets measured them under different conditions. Every
  aligned row records `matched_on`, ambiguity is refused rather than resolved,
  and `TestAmbiguity` proves a sixteen-against-twelve sweep produces no delta
  at all;
- **a silent drop** — a short table that reads as a complete one. Nothing is
  dropped: a parameter one part prints and the other does not is a row, a pair
  that could not be subtracted is a row *and* a counted line in the coverage
  report, and `test_every_candidate_is_accounted_for` counts the cells back.

`TestInvariantEight` is the provenance walk: every value on a comparison
resolves to a record and a printed page in *its own* part's corpus, and the
walk is proved non-vacuous by breaking a citation and watching it complain.

Hermetic per invariant 4: corpora are hand-published from models into a temp
`parts_dir`. No network, no model, no subprocess.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from datasheet_analyzer.config import SPECS_SCHEMA_VERSION, Settings, reset_settings_cache
from datasheet_analyzer.derive.compare import (
    DERIVATION_DELTA,
    FLAG_AMBIGUOUS,
    FLAG_DIFFERS,
    FLAG_IDENTICAL,
    FLAG_ONLY_IN,
    MATCH_FAMILY,
    MATCH_IDENTITY,
    STATUS_ALIGNED,
    STATUS_AMBIGUOUS,
    STATUS_ONLY_IN,
    STATUS_PARTIAL,
    Comparison,
    audit_comparison,
    cli_compare,
    compare_cards,
    compare_parts,
    compare_specs,
    render_comparison,
    resolve_symbol_query,
    si_delta,
)
from datasheet_analyzer.derive.provenance import SPECS_ARTIFACT
from datasheet_analyzer.models import (
    CARD_POWER,
    Confidence,
    CorpusManifest,
    DerivedValue,
    DocType,
    SectionFile,
    SourceDocument,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.structure.aliases import load_lexicon

DOC = "datasheet-1f2e3d4c"
DOC_HASH = "1f2e3d4c" + "0" * 56

SECTIONS = [
    ("4.1", "Absolute Maximum Ratings"),
    ("4.3", "Recommended Operating Conditions"),
    ("4.9", "Power Supply Electrical Characteristics"),
]


# --- hand-published corpora -------------------------------------------------


def _spec(
    section: str,
    row: int,
    symbol: str,
    name: str = "",
    *,
    table: int = 0,
    min: str = "",
    typ: str = "",
    max: str = "",
    value: str = "",
    unit: str = "",
    page: int = 4,
    conditions: str = "",
) -> SpecRecord:
    return SpecRecord(
        section=section,
        table_index=table,
        row_index=row,
        symbol=symbol,
        name=name,
        conditions=conditions,
        min=min,
        typ=typ,
        max=max,
        value=value,
        unit=SpecUnit(verbatim=unit, canonical=unit),
        page=page,
        confidence=Confidence.HIGH,
    )


def publish(part_dir: Path, part: str, records: list[SpecRecord]) -> Path:
    """The smallest corpus `CorpusIndex` will read: a manifest and specs."""
    doc_dir = part_dir / "docs" / DOC
    doc_dir.mkdir(parents=True, exist_ok=True)
    manifest = CorpusManifest(
        part_number=part,
        documents=[
            SourceDocument(
                content_hash=DOC_HASH,
                path=f"{part}.pdf",
                doc_type=DocType.DATASHEET,
                page_count=32,
            )
        ],
        sections=[
            SectionFile(
                number=number,
                title=title,
                file=f"docs/{DOC}/sections/{number}.md",
                doc_hash=DOC_HASH,
                page_start=4,
            )
            for number, title in SECTIONS
        ],
    )
    (part_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (doc_dir / SPECS_ARTIFACT).write_text(
        SpecSet(
            schema_version=SPECS_SCHEMA_VERSION,
            part_number=part,
            doc_hash=DOC_HASH,
            records=records,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    return part_dir


def part_a_records() -> list[SpecRecord]:
    """A TI-shaped part: symbols in the symbol column, one swept parameter."""
    return [
        _spec("4.1", 0, "TJ", "Junction temperature", max="150", unit="°C"),
        _spec("4.1", 1, "Tstg", "Storage temperature", min="-65", max="150", unit="°C"),
        _spec("4.1", 2, "IDD", "Supply current", typ="1350", unit="mA"),
        _spec("4.1", 3, "PMAX", "Peak input power", max="See Figure 7", unit="dBm"),
        _spec("4.1", 4, "tRESET", "Minimum RESETZ pulse width", min="10", unit="ns"),
        _spec("4.3", 0, "VOH", "High-level output voltage", min="2.4", unit="V", page=6),
        # A swept parameter: one symbol, three rows, told apart by conditions.
        _spec("4.9", 0, "NF", "Noise figure", typ="3.1", unit="dB", page=9, conditions="f = 1 GHz"),
        _spec("4.9", 1, "NF", "Noise figure", typ="3.6", unit="dB", page=9, conditions="f = 2 GHz"),
        _spec("4.9", 2, "NF", "Noise figure", typ="4.2", unit="dB", page=9, conditions="f = 3 GHz"),
        # Only in A.
        _spec("4.1", 5, "ISOL", "Channel isolation", min="60", unit="dB"),
    ]


def part_b_records() -> list[SpecRecord]:
    """A part with no symbol column: the name carries the parameter."""
    return [
        # Differently named, same parameter — only the alias lexicon lines these
        # two up, which is what makes this the alias-resolution test.
        _spec("4.1", 0, "", "Junction temperature", max="125", unit="°C"),
        _spec("4.1", 1, "Tstg", "Storage temperature", min="-65", max="150", unit="°C"),
        _spec("4.1", 2, "IDD", "Supply current", typ="1.5", unit="A"),
        _spec("4.1", 3, "PMAX", "Peak input power", max="12", unit="dBm"),
        _spec("4.1", 4, "tRESET", "Minimum RESET pulse width", min="25", unit="ns"),
        _spec("4.3", 0, "VOH", "High-level output voltage", min="2.2", unit="V", page=6),
        _spec("4.9", 0, "NF", "Noise figure", typ="3.4", unit="dB", page=8, conditions="f = 1 GHz"),
        _spec("4.9", 1, "NF", "Noise figure", typ="3.9", unit="dB", page=8, conditions="f = 2 GHz"),
        _spec("4.9", 2, "NF", "Noise figure", typ="4.9", unit="dB", page=8, conditions="f = 3 GHz"),
        # Only in B.
        _spec("4.1", 5, "VNOISE", "Output noise density", typ="12", unit="nV", page=5),
    ]


@pytest.fixture
def two_parts(tmp_path: Path) -> list[tuple[str, Path]]:
    root = tmp_path / "parts"
    publish(root / "PART-A", "PART-A", part_a_records())
    publish(root / "PART-B", "PART-B", part_b_records())
    return [("PART-A", root / "PART-A"), ("PART-B", root / "PART-B")]


@pytest.fixture
def compared(two_parts) -> Comparison:
    return compare_specs(two_parts)


def row_for(comparison: Comparison, label: str):
    """The single row whose label matches, so a missing row fails loudly."""
    hits = [row for row in comparison.rows if row.label.lower() == label.lower()]
    assert len(hits) == 1, f"expected exactly one {label!r} row, got {len(hits)}"
    return hits[0]


def delta_for(row, part: str, cell: str) -> DerivedValue | None:
    for delta in row.deltas:
        if delta.part_number == part and delta.cell == cell:
            return delta.value
    return None


# --- the pure function ------------------------------------------------------


class TestSiDelta:
    """`si_delta` is the one thing this module derives; it never guesses."""

    def _value(self, verbatim: str, si: float | None, unit: str, hi: float | None = None):
        return DerivedValue(
            verbatim=verbatim, value_si=si, value_si_hi=hi, unit_si=unit, source="s#1", page=4
        )

    def test_subtracts_baseline_from_other(self):
        a = self._value("110", 110.0, "°C")
        b = self._value("125", 125.0, "°C")
        assert si_delta(a, b, "max") == (15.0, "°C")

    def test_scaled_units_are_comparable(self):
        a = self._value("1350 mA", 1.35, "A")
        b = self._value("1.5 A", 1.5, "A")
        delta, unit = si_delta(a, b, "typ")
        assert unit == "A"
        assert delta == pytest.approx(0.15)

    def test_unlike_units_do_not_subtract(self):
        a = self._value("150", 150.0, "°C")
        b = self._value("150", 150.0, "W")
        assert si_delta(a, b, "max") is None

    def test_unparsed_side_does_not_subtract(self):
        a = self._value("See Figure 7", None, "")
        b = self._value("12", 12.0, "dBm")
        assert si_delta(a, b, "max") is None
        assert si_delta(b, a, "max") is None

    def test_a_bound_naming_column_uses_the_end_it_names(self):
        a = self._value("-40 to 85", -40.0, "°C", hi=85.0)
        b = self._value("-40 to 125", -40.0, "°C", hi=125.0)
        # `max` names the top of what it printed; `min` names the bottom.
        assert si_delta(a, b, "max") == (40.0, "°C")
        assert si_delta(a, b, "min") == (0.0, "°C")

    def test_a_range_in_a_column_that_names_no_end_does_not_subtract(self):
        """The Qorvo case: a lone unnamed `value` column holding a range.

        `-55 to 150` and `-55 to +125` share a low end and differ by 25 °C at
        the top. Reading either one's `value_si` publishes `0 °C` for parts
        that are 25 °C apart, which is worse than no answer.
        """
        a = self._value("-55 to 150", -55.0, "°C", hi=150.0)
        b = self._value("-55 to +125", -55.0, "°C", hi=125.0)
        assert si_delta(a, b, "value") is None
        assert si_delta(a, b, "typ") is None

    def test_a_range_against_a_point_does_not_subtract(self):
        a = self._value("-55 to 150", -55.0, "°C", hi=150.0)
        b = self._value("125", 125.0, "°C")
        assert si_delta(a, b, "value") is None
        assert si_delta(b, a, "value") is None

    def test_the_tolerance_is_relative_to_the_operands_not_a_fixed_floor(self):
        """Timing lives at 1e-9 s; a fixed absolute floor would swallow it."""
        a = self._value("1 to 2 ns", 1e-9, "s", hi=2e-9)
        b = self._value("2 to 4 ns", 2e-9, "s", hi=4e-9)
        # +1 ns at the bottom and +2 ns at the top is not one number.
        assert si_delta(a, b, "value") is None

    def test_ranges_that_move_together_subtract_to_one_number(self):
        """A shifted span *is* a scalar difference: +20 °C at both ends."""
        a = self._value("-40 to 85", -40.0, "°C", hi=85.0)
        b = self._value("-20 to 105", -20.0, "°C", hi=105.0)
        assert si_delta(a, b, "value") == (20.0, "°C")
        # Two identical ranges still report the zero they honestly are.
        assert si_delta(a, a, "value") == (0.0, "°C")


# --- alignment --------------------------------------------------------------


class TestAlignment:
    def test_printed_identity_alignment_records_what_it_matched_on(self, compared):
        row = row_for(compared, "Storage temperature")
        assert row.status == STATUS_ALIGNED
        assert MATCH_IDENTITY in row.matched_on
        assert "storage temperature" in row.matched_on
        assert set(row.cells) == {"PART-A", "PART-B"}

    def test_alias_resolution_lines_up_differently_named_equivalents(self, compared):
        """PART-A prints the symbol `TJ`; PART-B prints only the name."""
        row = row_for(compared, "Junction temperature")
        assert row.status == STATUS_ALIGNED
        assert row.cells["PART-A"].symbol == "TJ"
        assert row.cells["PART-B"].symbol == "Junction temperature"
        assert MATCH_IDENTITY in row.matched_on or MATCH_FAMILY in row.matched_on
        delta = delta_for(row, "PART-B", "max")
        assert delta is not None and delta.value_si == pytest.approx(-25.0)

    def test_printed_symbol_lines_up_what_the_lexicon_does_not_claim(self, compared):
        """`tRESET` is named differently in each part (RESETZ vs RESET)."""
        row = row_for(compared, "Minimum RESETZ pulse width")
        assert row.status == STATUS_ALIGNED
        assert row.cells["PART-B"].label == "Minimum RESET pulse width"
        assert "treset" in row.matched_on.lower()
        delta = delta_for(row, "PART-B", "min")
        # 25 ns - 10 ns, in the base unit both were normalized to.
        assert delta is not None and delta.unit_si == "s"
        assert delta.value_si == pytest.approx(15e-9)

    def test_conditions_tell_a_swept_parameter_apart(self, compared):
        """Three noise-figure rows per part align by the frequency each states."""
        rows = [row for row in compared.rows if row.label == "Noise figure"]
        assert len(rows) == 3
        by_condition = {row.cells["PART-A"].conditions: row for row in rows}
        assert set(by_condition) == {"f = 1 GHz", "f = 2 GHz", "f = 3 GHz"}
        for row in rows:
            assert row.status == STATUS_ALIGNED
            assert "conditions" in row.matched_on
            # The pairing is the datasheet's, not this tool's: both sides of
            # every row state the same frequency.
            assert row.cells["PART-A"].conditions == row.cells["PART-B"].conditions
        expected = {"f = 1 GHz": 0.3, "f = 2 GHz": 0.3, "f = 3 GHz": 0.7}
        for condition, row in by_condition.items():
            delta = delta_for(row, "PART-B", "typ")
            assert delta is not None
            assert delta.value_si == pytest.approx(expected[condition])

    def test_pages_are_carried_from_both_sides(self, compared):
        row = row_for(compared, "High-level output voltage")
        assert row.cells["PART-A"].values["min"].page == 6
        assert row.cells["PART-B"].values["min"].page == 6
        assert row.cells["PART-A"].values["min"].verbatim == "2.4"
        assert row.cells["PART-B"].values["min"].verbatim == "2.2"


class TestRangeInAnUnnamedColumn:
    """A single unnamed `value` column holding a range publishes no delta.

    Qorvo's absolute-maximum tables are one column wide, so a range lands in a
    cell called `value`. Before this refusal, `-55 to 150 °C` against `-55 to
    +125 °C` published `0 °C` and flagged the row `identical` — two parts 25 °C
    apart, reported as the same part.
    """

    @pytest.fixture
    def spans(self, tmp_path: Path) -> Comparison:
        root = tmp_path / "parts"
        publish(
            root / "A",
            "A",
            [
                _spec("4.1", 0, "Tstg", "Storage temperature", value="-55 to 150", unit="°C"),
                _spec("4.1", 1, "TA", "Operating temperature", value="-40 to 85", unit="°C"),
            ],
        )
        publish(
            root / "B",
            "B",
            [
                _spec("4.1", 0, "Tstg", "Storage temperature", value="-55 to +125", unit="°C"),
                _spec("4.1", 1, "TA", "Operating temperature", value="-20 to 105", unit="°C"),
            ],
        )
        comparison, reason = compare_parts(["A", "B"], parts_dir=root, write=False)
        assert comparison is not None, reason
        return comparison

    def test_ends_that_do_not_move_together_publish_no_number(self, spans: Comparison):
        row = row_for(spans, "Storage temperature")
        assert row.status == STATUS_ALIGNED
        assert row.deltas == []
        assert FLAG_IDENTICAL not in row.flags
        assert FLAG_DIFFERS not in row.flags

    def test_the_refusal_says_why_and_is_counted(self, spans: Comparison):
        row = row_for(spans, "Storage temperature")
        assert any("names neither end of a range" in reason for reason in row.not_comparable)
        assert any("names neither end of a range" in reason for reason in spans.coverage.reasons)
        assert spans.coverage.considered > spans.coverage.compared

    def test_a_span_that_shifts_wholesale_is_still_one_number(self, spans: Comparison):
        """`-40 to 85` against `-20 to 105` is `+20 °C` at both ends."""
        row = row_for(spans, "Operating temperature")
        delta = delta_for(row, "B", "value")
        assert delta is not None and delta.value_si == pytest.approx(20.0)
        assert FLAG_DIFFERS in row.flags


class TestAmbiguity:
    """A key several parts print several rows under is never resolved."""

    @pytest.fixture
    def unpairable(self, tmp_path: Path) -> Comparison:
        root = tmp_path / "parts"
        publish(
            root / "A",
            "A",
            [
                _spec("4.9", i, "Pdiss", "Power dissipation", typ=str(v), unit="mW", conditions=c)
                for i, (v, c) in enumerate(((6027, "Mode 1: 4T2F"), (6359, "Mode 2: 4T4R")))
            ],
        )
        publish(
            root / "B",
            "B",
            [
                _spec("4.9", i, "Pdiss", "Power dissipation", typ=str(v), unit="mW", conditions=c)
                for i, (v, c) in enumerate(
                    ((2399, "Mode 1a: 2T2R"), (2414, "Mode 1b: 2T2R"), (3374, "Mode 2: 2T2R FDD"))
                )
            ],
        )
        return compare_specs([("A", root / "A"), ("B", root / "B")])

    def test_nothing_is_paired_and_nothing_is_dropped(self, unpairable):
        assert unpairable.aligned == []
        assert unpairable.delta_count == 0
        ambiguous = unpairable.rows_with(STATUS_AMBIGUOUS)
        assert len(ambiguous) == 5  # two rows from A, three from B, all listed
        assert {row.cells and next(iter(row.cells)) for row in ambiguous} == {"A", "B"}

    def test_the_reason_names_the_counts_and_the_key(self, unpairable):
        reasons = {row.matched_on for row in unpairable.rows_with(STATUS_AMBIGUOUS)}
        assert len(reasons) == 1
        reason = reasons.pop()
        assert "2 row(s) in A" in reason and "3 row(s) in B" in reason
        assert "pdiss" in reason
        assert "nothing printed says which pairs with which" in reason

    def test_every_row_still_shows_its_verbatim_value_and_page(self, unpairable):
        printed = {
            cell.values["typ"].verbatim
            for row in unpairable.rows_with(STATUS_AMBIGUOUS)
            for cell in row.cells.values()
        }
        assert printed == {"6027", "6359", "2399", "2414", "3374"}
        for row in unpairable.rows_with(STATUS_AMBIGUOUS):
            for cell in row.cells.values():
                assert cell.values["typ"].page == 4
                assert FLAG_AMBIGUOUS in row.flags

    def test_the_ambiguous_population_is_rendered_under_its_own_heading(self, unpairable):
        text = render_comparison(unpairable)
        assert "## Not aligned (5)" in text
        assert "no delta is invented" in text


# --- what is missing --------------------------------------------------------


class TestOnlyInOnePart:
    def test_a_parameter_only_one_part_prints_is_a_row(self, compared):
        row = row_for(compared, "Channel isolation")
        assert row.status == STATUS_ONLY_IN
        assert row.present_in == ["PART-A"]
        assert row.missing_from == ["PART-B"]
        assert FLAG_ONLY_IN in row.flags
        assert row.deltas == []
        assert "only in PART-A" in row.matched_on
        assert row.cells["PART-A"].values["min"].verbatim == "60"

    def test_it_is_reported_for_both_directions(self, compared):
        only = {row.present_in[0]: row.label for row in compared.rows_with(STATUS_ONLY_IN)}
        assert only == {"PART-A": "Channel isolation", "PART-B": "Output noise density"}

    def test_every_candidate_is_accounted_for(self, compared):
        """Ten records per part in, twenty cells out — nothing dropped."""
        cells = sum(len(row.cells) for row in compared.rows)
        assert cells == len(part_a_records()) + len(part_b_records())

    def test_the_rendered_table_says_not_printed(self, compared):
        text = render_comparison(compared)
        assert "## Only in one part (2)" in text
        assert "not printed" in text


# --- deltas and the unparsed population -------------------------------------


class TestDeltas:
    def test_a_delta_is_computed_only_where_both_sides_parsed(self, compared):
        row = row_for(compared, "Peak input power")
        assert row.status == STATUS_ALIGNED
        assert row.deltas == []
        assert any("See Figure 7" in reason for reason in row.not_comparable)

    def test_the_unparsed_pair_is_counted_and_listed(self, compared):
        assert compared.coverage.considered >= 1
        assert compared.coverage.uncompared == 1
        listed = "\n".join(compared.coverage.reasons)
        assert "'See Figure 7'" in listed and "'12'" in listed
        assert "did not both parse to a number in the same unit" in listed
        sentence = compared.coverage.describe()
        assert sentence.startswith(
            f"1 of {compared.coverage.considered} aligned value pair(s) could not be compared"
        )
        assert "listed below:" in sentence

    def test_si_scaling_makes_unlike_prefixes_comparable(self, compared):
        row = row_for(compared, "Supply current")
        delta = delta_for(row, "PART-B", "typ")
        assert delta is not None
        assert delta.unit_si == "A"
        assert delta.value_si == pytest.approx(0.15)
        assert delta.verbatim.startswith("+0.15")

    def test_identical_values_are_flagged_as_identical(self, compared):
        row = row_for(compared, "Storage temperature")
        assert FLAG_IDENTICAL in row.flags
        assert all(delta.value.value_si == 0 for delta in row.deltas)

    def test_differing_values_are_flagged_as_differing(self, compared):
        assert FLAG_DIFFERS in row_for(compared, "Junction temperature").flags

    def test_a_delta_names_its_rule_and_both_sides(self, compared):
        row = row_for(compared, "Junction temperature")
        delta = row.deltas[0]
        assert delta.value.derivation == DERIVATION_DELTA
        assert delta.baseline == "PART-A" and delta.part_number == "PART-B"
        assert delta.baseline_source and delta.baseline_page == 4
        assert delta.value.source and delta.value.page == 4

    def test_the_not_comparable_heading_is_unconditional(self, compared):
        assert "## Not comparable" in render_comparison(compared)


class TestParseCoverage:
    def test_each_part_reports_what_it_could_not_parse(self, compared):
        by_part = {part.part_number: part for part in compared.parse_coverage}
        assert set(by_part) == {"PART-A", "PART-B"}
        a = by_part["PART-A"]
        assert a.considered == len(part_a_records())
        assert a.unparsed_count == 1  # "See Figure 7"
        assert "See Figure 7" in a.describe()
        assert a.describe().startswith("PART-A: 1 of 10 selected row(s) could not be parsed")
        assert by_part["PART-B"].unparsed_count == 0

    def test_coverage_is_rendered(self, compared):
        assert "## Parse coverage" in render_comparison(compared)


# --- symbol and card modes --------------------------------------------------


class TestSymbolFilter:
    def test_a_known_symbol_resolves_through_the_lexicon(self, two_parts):
        comparison = compare_specs(two_parts, symbol="TJ")
        assert comparison.resolved_symbol.startswith("alias lexicon entry")
        assert {row.label for row in comparison.rows} == {"Junction temperature"}

    def test_an_unknown_symbol_falls_back_to_printed_text_and_says_so(self, two_parts):
        comparison = compare_specs(two_parts, symbol="ISOL")
        assert comparison.resolved_symbol == ""
        assert any("no entry for 'ISOL'" in w for w in comparison.warnings)
        assert [row.label for row in comparison.rows] == ["Channel isolation"]

    def test_resolve_symbol_query_reaches_a_family_by_phrase(self):
        lexicon = load_lexicon()
        entry, how = resolve_symbol_query("junction temperature", lexicon)
        assert entry is not None and entry.symbol == "TJ"
        assert "alias phrase" in how or "alias lexicon entry" in how

    def test_a_symbol_nothing_prints_is_an_honest_empty_comparison(self, two_parts):
        comparison = compare_specs(two_parts, symbol="ZZTOP")
        assert comparison.rows == []
        assert len(comparison.unresolved) == 2
        assert all("no published spec record matched" in line for line in comparison.unresolved)


class TestCardMode:
    def test_a_whole_card_compares_row_by_row(self, two_parts):
        comparison = compare_cards(two_parts, CARD_POWER, write=False)
        assert comparison.mode == "card"
        assert comparison.card == CARD_POWER
        row = row_for(comparison, "Supply current")
        assert row.status == STATUS_ALIGNED
        delta = delta_for(row, "PART-B", "typ")
        assert delta is not None and delta.value_si == pytest.approx(0.15)

    def test_the_cards_own_unresolved_lines_travel_with_the_comparison(self, two_parts):
        comparison = compare_cards(two_parts, CARD_POWER, write=False)
        assert comparison.unresolved
        assert all(line.startswith(("PART-A:", "PART-B:")) for line in comparison.unresolved)

    def test_card_mode_writes_nothing_when_asked_not_to(self, two_parts):
        compare_cards(two_parts, CARD_POWER, write=False)
        for _part, part_dir in two_parts:
            assert not (part_dir / "cards").exists()


# --- more than two ----------------------------------------------------------


class TestPartCount:
    @pytest.fixture
    def three_parts(self, tmp_path: Path) -> Path:
        root = tmp_path / "parts"
        publish(root / "PART-A", "PART-A", part_a_records())
        publish(root / "PART-B", "PART-B", part_b_records())
        publish(
            root / "PART-C",
            "PART-C",
            [
                _spec("4.1", 0, "TJ", "Junction temperature", max="175", unit="°C"),
                _spec("4.1", 1, "Tstg", "Storage temperature", min="-65", max="150", unit="°C"),
            ],
        )
        return root

    def test_three_parts_are_compared_not_truncated(self, three_parts):
        comparison, reason = compare_parts(
            ["PART-A", "PART-B", "PART-C"], parts_dir=three_parts, symbol="TJ"
        )
        assert reason == ""
        assert comparison.parts == ["PART-A", "PART-B", "PART-C"]
        row = row_for(comparison, "Junction temperature")
        assert set(row.cells) == {"PART-A", "PART-B", "PART-C"}
        assert delta_for(row, "PART-B", "max").value_si == pytest.approx(-25.0)
        assert delta_for(row, "PART-C", "max").value_si == pytest.approx(25.0)

    def test_a_row_missing_from_one_of_three_is_partial_not_dropped(self, three_parts):
        comparison, _reason = compare_parts(
            ["PART-A", "PART-B", "PART-C"], parts_dir=three_parts, symbol="VOH"
        )
        row = row_for(comparison, "High-level output voltage")
        assert row.status == STATUS_PARTIAL
        assert row.present_in == ["PART-A", "PART-B"]
        assert row.missing_from == ["PART-C"]

    def test_one_part_is_refused_with_a_reason(self, three_parts):
        comparison, reason = compare_parts(["PART-A"], parts_dir=three_parts)
        assert comparison is None
        assert "at least two parts" in reason

    def test_a_repeated_part_is_refused(self, three_parts):
        comparison, reason = compare_parts(["PART-A", "PART-A"], parts_dir=three_parts)
        assert comparison is None
        assert "named more than once" in reason

    def test_an_unbuilt_part_is_refused(self, three_parts):
        comparison, reason = compare_parts(["PART-A", "NOPE"], parts_dir=three_parts)
        assert comparison is None
        assert "NOPE" in reason


# --- invariant 8 ------------------------------------------------------------


class TestInvariantEight:
    """Every value on a comparison resolves to a record and a printed page."""

    def test_every_citation_resolves_in_its_own_corpus(self, two_parts, compared):
        dirs = dict(two_parts)
        assert audit_comparison(compared, dirs) == []

    def test_the_walk_is_not_vacuous(self, two_parts, compared):
        dirs = dict(two_parts)
        row = row_for(compared, "Junction temperature")
        broken = compared.model_copy(deep=True)
        target = row_for(broken, "Junction temperature")
        target.cells["PART-A"].values["max"].source = f"{SPECS_ARTIFACT}#rec_nonexistent"
        problems = audit_comparison(broken, dirs)
        assert any("resolves to no record in PART-A" in p for p in problems)
        assert row.cells["PART-A"].values["max"].source != ""

    def test_a_delta_cites_both_sides(self, two_parts, compared):
        dirs = dict(two_parts)
        broken = compared.model_copy(deep=True)
        row_for(broken, "Junction temperature").deltas[0].baseline_source = ""
        assert any("names no baseline source" in p for p in audit_comparison(broken, dirs))

    def test_no_value_is_uncited(self, compared):
        for row in compared.rows:
            for cell in row.cells.values():
                for value in cell.values.values():
                    assert value.source and value.page, f"{row.label}: uncited {value.verbatim!r}"
                    assert value.derivation

    def test_a_comparison_names_no_derivation_rule_this_module_does_not_own(self, compared):
        rules = {delta.value.derivation for row in compared.rows for delta in row.deltas}
        assert rules <= {DERIVATION_DELTA}


# --- the CLI ----------------------------------------------------------------


def _args(**kwargs) -> argparse.Namespace:
    base = {"parts": [], "symbol": "", "card": "", "json": False}
    base.update(kwargs)
    return argparse.Namespace(**base)


class TestCli:
    @pytest.fixture(autouse=True)
    def _settings(self, tmp_path, monkeypatch):
        root = tmp_path / "parts"
        publish(root / "PART-A", "PART-A", part_a_records())
        publish(root / "PART-B", "PART-B", part_b_records())
        monkeypatch.setenv("DSA_PARTS_DIR", str(root))
        monkeypatch.setenv("DSA_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setenv("DSA_LIBRARY_DIR", str(tmp_path / "library"))
        reset_settings_cache()
        yield Settings().resolve()
        reset_settings_cache()

    def test_a_comparison_prints_a_table_and_exits_zero(self, capsys):
        assert cli_compare(_args(parts=["PART-A", "PART-B"], symbol="TJ")) == 0
        out = capsys.readouterr().out
        assert "# Compare: PART-A vs PART-B" in out
        assert "Junction temperature" in out
        assert "150 (p.4)" in out and "125 (p.4)" in out
        assert "-25 °C" in out

    def test_json_carries_the_rows_and_the_schema_version(self, capsys):
        assert cli_compare(_args(parts=["PART-A", "PART-B"], symbol="TJ", json=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["schema_version"] == "1"
        assert payload["parts"] == ["PART-A", "PART-B"]
        assert payload["rows"][0]["deltas"][0]["value"]["derivation"] == DERIVATION_DELTA
        assert payload["rows"][0]["cells"]["PART-B"]["values"]["max"]["page"] == 4

    def test_nothing_in_common_exits_one_with_the_reason_printed(self, capsys):
        assert cli_compare(_args(parts=["PART-A", "PART-B"], symbol="ZZTOP")) == 1
        assert "no published spec record matched" in capsys.readouterr().out

    def test_one_part_exits_two(self, capsys):
        assert cli_compare(_args(parts=["PART-A"])) == 2
        assert "at least two parts" in capsys.readouterr().err

    def test_an_unknown_card_exits_two(self, capsys):
        assert cli_compare(_args(parts=["PART-A", "PART-B"], card="nope")) == 2
        assert "unknown card" in capsys.readouterr().err
