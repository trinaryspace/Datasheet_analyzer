"""Cross-part comparison (phase 6, ticket 09): alignment, deltas, refusals.

The rules under test are ADR 0005's, applied to the artifact a part *selection*
is made on — which is the one place a wrong number costs a board spin:

- rows align by **alias-resolved symbol**, and every row records what it aligned
  on, so a mis-alignment cannot be produced silently;
- a delta exists only where both sides parsed the **same printed column** into
  the same SI base, carries no `verbatim` (no page printed it), cites both
  operands and takes the weaker grade;
- a parameter one part prints and another does not is an `only in A` row, never
  a dropped one;
- a part printing several rows no shared printed name can pair holds no column,
  is named as `ambiguous_in`, and every one of its rows is listed verbatim —
  while the parts that *are* unambiguous still compare;
- everything that could not be compared is under one heading, with its printed
  values, beside `quantities.parse_population`'s sentence per part.

The same code runs over four real corpora in
`tests/integration/test_phase4_layout_gate.py::TestCrossPartCompareOnTheGateCorpora`,
where the numbers are hand-read off the printed pages; this module is where each
rule is pinned in isolation, including the ones no real pair happens to print.
"""

from __future__ import annotations

import json

import pytest

from datasheet_analyzer.compare import (
    DERIVATION_CELL,
    DERIVATION_CELL_SI,
    DERIVATION_DELTA,
    FLAG_ONLY_IN,
    KIND_SYMBOL,
    ComparePart,
    CompareRecord,
    build_card_comparison,
    build_spec_comparison,
    render_comparison,
)
from datasheet_analyzer.compare.build import FLAG_AMBIGUOUS
from datasheet_analyzer.compare.render import BANNER_PREFIX, NOT_COMPARABLE_HEADING
from datasheet_analyzer.config import CARD_VERSION, COMPARE_SCHEMA_VERSION
from datasheet_analyzer.models import (
    CardRow,
    ComparisonRow,
    Confidence,
    DerivedValue,
    DesignCard,
    PartComparison,
    SpecRecord,
)
from datasheet_analyzer.retrieve import Comparison, check_parts
from datasheet_analyzer.structure.units import canonical_unit

DOC = "datasheet-a1b2c3d4"


def rec(
    ordinal: int,
    *,
    symbol: str = "",
    name: str = "",
    unit: str = "°C",
    page: int = 4,
    section: str = "6.1",
    confidence: Confidence = Confidence.HIGH,
    record_id: str | None = None,
    **cells: str,
) -> SpecRecord:
    """One published spec record, as `structure/specs.py` would have written it."""
    return SpecRecord(
        id=f"rec_{ordinal}" if record_id is None else record_id,
        section=section,
        symbol=symbol,
        name=name,
        unit=canonical_unit(unit),
        page=page,
        confidence=confidence,
        **cells,
    )


def part(name: str, *records: SpecRecord, matched_via: str = "symbol") -> ComparePart:
    return ComparePart(
        part_number=name,
        records=tuple(
            CompareRecord(doc=DOC, record=r, matched_via=matched_via) for r in records
        ),
    )


def compare(*parts: ComparePart, term: str = "junction temperature") -> PartComparison:
    return build_spec_comparison(list(parts), term=term, kind=KIND_SYMBOL)


def row_of(comparison: PartComparison, key: str) -> ComparisonRow:
    return next(r for r in comparison.rows if r.key == key)


def value(
    verbatim: str,
    value_si: float | None,
    *,
    unit_si: str = "°C",
    source: str = f"docs/{DOC}/specs.json#rec_1",
    page: int = 4,
    confidence: Confidence = Confidence.HIGH,
) -> DerivedValue:
    """A card's already-derived value, for the card-comparison tests."""
    return DerivedValue(
        verbatim=verbatim,
        value_si=value_si,
        unit_si=unit_si,
        source=source,
        page=page,
        section="",
        derivation=DERIVATION_CELL_SI if value_si is not None else DERIVATION_CELL,
        confidence=confidence,
    )


def card(part_number: str, *rows: CardRow, name: str = "thermal") -> DesignCard:
    return DesignCard(
        schema_version="1",
        card=name,
        title=name,
        part_number=part_number,
        card_version=CARD_VERSION,
        rows=list(rows),
    )


class TestAlignment:
    """Rows line up on the alias-resolved symbol, and say that they did."""

    def test_two_parts_naming_one_parameter_differently_still_line_up(self):
        """The whole reason the alias lexicon exists, applied across parts.

        ADI prints `OPERATING JUNCTION TEMPERATURE (TJ)` where TI prints
        `Junction temperature`; both resolve to `TJ` and become one row.
        """
        comparison = compare(
            part("A", rec(1, symbol="OPERATING JUNCTION TEMPERATURE (TJ)", max="120")),
            part("B", rec(1, symbol="Junction temperature", max="150")),
        )
        row = row_of(comparison, "TJ")
        assert row.aligned_on == "alias:TJ"
        assert [c.part_number for c in row.cells] == ["A", "B"]
        assert [c.label for c in row.cells] == [
            "OPERATING JUNCTION TEMPERATURE (TJ)", "Junction temperature"
        ]

    def test_a_parameter_the_lexicon_does_not_know_aligns_on_the_printed_name(self):
        comparison = compare(
            part("A", rec(1, symbol="Widget factor", typ="3", unit="")),
            part("B", rec(1, symbol="widget factor", typ="5", unit="")),
            term="widget factor",
        )
        row = comparison.rows[0]
        assert row.aligned_on == "printed-symbol"
        assert row.key == "Widget factor", "the reference part's own printed label"
        assert row.n_deltas == 1

    def test_every_cell_records_the_rung_its_own_part_matched_on(self):
        """A comparison that aligned two rows must be able to say how each side
        was found; a rung is a statement about one corpus, not about the pair."""
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120"), matched_via="symbol"),
            part(
                "B",
                rec(1, symbol="Junction temperature", max="150"),
                matched_via="alias:junction temperature",
            ),
        )
        assert [c.matched_via for c in row_of(comparison, "TJ").cells] == [
            "symbol", "alias:junction temperature"
        ]

    def test_the_reference_is_the_first_part_named(self):
        comparison = compare(
            part("B", rec(1, symbol="TJ", max="150")),
            part("A", rec(1, symbol="TJ", max="120")),
        )
        assert comparison.reference == "B"
        assert row_of(comparison, "TJ").cells[1].delta.value_si == pytest.approx(-30.0)


class TestDeltas:
    """The one number a comparison adds, and every case it refuses to add it."""

    def test_a_delta_is_computed_where_both_sides_parsed_the_same_column(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120")),
            part("B", rec(1, symbol="TJ", max="150")),
        )
        row = row_of(comparison, "TJ")
        assert row.role == "max"
        delta = row.cells[1].delta
        assert delta.value_si == pytest.approx(30.0)
        assert delta.unit_si == "°C"
        assert delta.derivation == f"{DERIVATION_DELTA}:max"
        assert delta.verbatim == "", "no page printed a difference between datasheets"

    def test_a_delta_cites_both_operands_and_names_each_ones_part(self):
        """Citing one of two rows would make the value traceable by half — and a
        cross-part reference that does not name its part is not traceable at all,
        because `rec_9` exists in most corpora."""
        comparison = compare(
            part("A", rec(7, symbol="TJ", max="120")),
            part("B", rec(9, symbol="TJ", max="150")),
        )
        delta = row_of(comparison, "TJ").cells[1].delta
        assert delta.source == f"parts/B/docs/{DOC}/specs.json#rec_9"
        assert delta.sources == [f"parts/A/docs/{DOC}/specs.json#rec_7"]
        assert delta.refs == [
            f"parts/B/docs/{DOC}/specs.json#rec_9",
            f"parts/A/docs/{DOC}/specs.json#rec_7",
        ]

    def test_a_delta_takes_the_weaker_of_the_two_grades(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120", confidence=Confidence.HIGH)),
            part("B", rec(1, symbol="TJ", max="150", confidence=Confidence.LOW)),
        )
        assert row_of(comparison, "TJ").cells[1].delta.confidence == Confidence.LOW

    def test_an_unparsed_side_publishes_both_values_and_no_delta(self):
        """`See Figure 7` has no number; the row is still published, verbatim,
        and the pair is listed under 'not comparable'."""
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120")),
            part("B", rec(1, symbol="TJ", max="See Figure 7")),
        )
        row = row_of(comparison, "TJ")
        assert row.cells[1].delta is None
        assert row.cells[1].values["max"].verbatim == "See Figure 7 °C"
        assert row.cells[1].values["max"].value_si is None
        assert any("no comparable number" in line for line in comparison.unparsed)

    def test_two_different_columns_are_never_subtracted(self):
        """A typical is not a maximum. Both are published; neither is compared."""
        comparison = compare(
            part("A", rec(1, symbol="TJ", typ="120")),
            part("B", rec(1, symbol="TJ", max="150")),
        )
        row = row_of(comparison, "TJ")
        assert row.role == ""
        assert row.n_deltas == 0
        assert row.cells[0].values["typ"].verbatim == "120 °C"
        assert row.cells[1].values["max"].verbatim == "150 °C"
        assert any("one printed column" in line for line in comparison.unparsed)

    def test_two_different_si_bases_are_refused_with_the_reason(self):
        comparison = compare(
            part("A", rec(1, symbol="VDD", max="1.8", unit="V")),
            part("B", rec(1, symbol="VDD", max="1800", unit="mA")),
            term="supply voltage",
        )
        row = comparison.rows[0]
        assert row.n_deltas == 0
        assert any("different base" in line for line in comparison.unparsed)

    def test_a_printed_range_is_not_reduced_to_one_of_its_endpoints(self):
        """`-55 to 150` states an interval, not a ceiling. Comparing it against a
        ceiling would invent a number the page does not print."""
        comparison = compare(
            part("A", rec(1, symbol="Tstg", value="-65 to 150")),
            part("B", rec(1, symbol="Tstg", value="-55 to 150")),
            term="storage temperature",
        )
        row = comparison.rows[0]
        assert row.n_deltas == 0
        assert [c.values["value"].verbatim for c in row.cells] == [
            "-65 to 150 °C", "-55 to 150 °C"
        ]

    def test_the_delta_is_the_other_part_minus_the_reference(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="150")),
            part("B", rec(1, symbol="TJ", max="120")),
        )
        assert row_of(comparison, "TJ").cells[1].delta.value_si == pytest.approx(-30.0)


class TestParametersOnlyOnePartPrints:
    """`only in A` is a finding during part selection, never a dropped row."""

    def test_a_parameter_absent_from_the_other_part_is_reported(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120")),
            part("B", rec(1, symbol="Tstg", value="-65 to 150")),
            term="temperature",
        )
        only = next(r for r in comparison.rows if FLAG_ONLY_IN in r.flags)
        assert only.missing_from == ["B"] or only.missing_from == ["A"]
        assert "publishes no record" in only.note
        assert len(comparison.rows) == 2, "both parameters are rows; neither is dropped"

    def test_an_only_in_row_still_carries_the_printed_value_and_its_citation(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120")),
            part("B", rec(1, symbol="Tstg", value="-65 to 150")),
            term="temperature",
        )
        row = row_of(comparison, "TJ")
        assert row.cells[0].values["max"].verbatim == "120 °C"
        assert row.cells[0].citation == "§6.1, p.4"
        assert row.cells[0].delta is None


class TestMoreThanTwoParts:
    """Three parts is a supported question; nothing is truncated."""

    def test_three_parts_all_compare_against_the_first(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120")),
            part("B", rec(1, symbol="TJ", max="150")),
            part("C", rec(1, symbol="TJ", max="105")),
        )
        row = row_of(comparison, "TJ")
        assert comparison.parts == ["A", "B", "C"]
        assert [c.part_number for c in row.cells] == ["A", "B", "C"]
        assert [c.delta.value_si for c in row.cells[1:]] == [
            pytest.approx(30.0), pytest.approx(-15.0)
        ]

    def test_one_part_of_three_missing_the_parameter_is_named(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120")),
            part("B", rec(1, symbol="TJ", max="150")),
            part("C", rec(1, symbol="Tstg", value="-65 to 150")),
            term="temperature",
        )
        row = row_of(comparison, "TJ")
        assert row.missing_from == ["C"]
        assert row.n_deltas == 1

    @pytest.mark.parametrize(
        "names,needle",
        [
            (["A"], "at least two parts"),
            ([], "at least two parts"),
            (["A", "A"], "named twice"),
            (["A", "B", "A"], "named twice"),
        ],
    )
    def test_a_list_that_is_not_a_comparison_is_refused_with_the_reason(
        self, names, needle
    ):
        _parts, error = check_parts(names)
        assert needle in error

    def test_a_valid_list_is_accepted_whole(self):
        assert check_parts(["A", "B", "C", "D"]) == (["A", "B", "C", "D"], "")


class TestAmbiguity:
    """An ambiguous alignment is refused, and refused per part."""

    def test_a_part_printing_two_unpairable_rows_holds_no_column(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120")),
            part(
                "B",
                rec(1, symbol="Channel temperature (quiescent)", value="151"),
                rec(2, symbol="Channel temperature (under RF drive)", value="173"),
            ),
        )
        row = row_of(comparison, "TJ")
        assert [c.part_number for c in row.cells] == ["A"]
        assert row.ambiguous_in == ["B"]
        assert row.missing_from == [], "B did print something — it is not absent"
        assert FLAG_AMBIGUOUS in row.flags and FLAG_ONLY_IN not in row.flags

    def test_every_unpaired_row_is_listed_with_what_it_printed(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120")),
            part(
                "B",
                rec(1, symbol="Channel temperature (quiescent)", value="151"),
                rec(2, symbol="Channel temperature (under RF drive)", value="173"),
            ),
        )
        listing = "\n".join(comparison.unparsed)
        assert "151 °C" in listing and "173 °C" in listing
        assert "p.4" in listing

    def test_a_third_messy_part_does_not_erase_a_clean_comparison(self):
        """The refusal is per part: A and B still line up and still subtract."""
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120")),
            part("B", rec(1, symbol="Junction temperature", max="150")),
            part(
                "C",
                rec(1, symbol="Channel temperature (quiescent)", value="151"),
                rec(2, symbol="Channel temperature (under RF drive)", value="173"),
            ),
        )
        row = row_of(comparison, "TJ")
        assert [c.part_number for c in row.cells] == ["A", "B"]
        assert row.cells[1].delta.value_si == pytest.approx(30.0)
        assert row.ambiguous_in == ["C"]

    def test_a_leftover_row_is_not_reported_as_an_absence(self):
        """When the identity rung splits a key into several rows, a part missing
        from one of them answered on another — which is a fact about the table,
        not about the device, and must not read as `only in B`."""
        comparison = compare(
            part(
                "A",
                rec(1, symbol="TJ", name="commercial", max="85"),
                rec(2, symbol="TJ", name="industrial", max="105"),
            ),
            part(
                "B",
                rec(1, symbol="TJ", name="commercial", max="70"),
                rec(2, symbol="TJ", name="industrial", max="125"),
                rec(3, symbol="TJ", name="extended", max="150"),
            ),
        )
        leftover = next(r for r in comparison.rows if len(r.cells) == 1)
        assert leftover.cells[0].part_number == "B"
        assert leftover.missing_from == [] and FLAG_ONLY_IN not in leftover.flags
        assert "A prints this parameter on another line" in leftover.note

    def test_rows_sharing_a_printed_identity_cell_pair_up(self):
        """The one widening an ambiguous key allows — a fact about the page."""
        comparison = compare(
            part(
                "A",
                rec(1, symbol="TJ", name="commercial", max="85"),
                rec(2, symbol="TJ", name="industrial", max="105"),
            ),
            part(
                "B",
                rec(1, symbol="TJ", name="industrial", max="125"),
                rec(2, symbol="TJ", name="commercial", max="70"),
            ),
        )
        paired = {r.aligned_on: r for r in comparison.rows}
        assert set(paired) == {"printed-identity:commercial", "printed-identity:industrial"}
        assert paired["printed-identity:industrial"].cells[1].delta.value_si == pytest.approx(
            20.0
        )
        assert paired["printed-identity:commercial"].cells[1].delta.value_si == pytest.approx(
            -15.0
        )


class TestHonesty:
    """Invariant 8's other half: what the comparison could not read, out loud."""

    def test_every_part_reports_its_unparsed_population(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120"), rec(2, symbol="TJ2", max="See Figure 7")),
            part("B", rec(1, symbol="TJ", max="150")),
        )
        assert any("1 of 2 rows could not be parsed" in n for n in comparison.notes)
        assert any(n.startswith("B: all 1 rows parsed") for n in comparison.notes)
        assert any("See Figure 7" in line for line in comparison.unparsed)

    def test_a_record_with_no_id_is_listed_rather_than_compared(self):
        """A corpus published before ADR 0005 has unaddressable rows, and an
        uncited value has no business on a derived artifact."""
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120", record_id="")),
            part("B", rec(1, symbol="TJ", max="150")),
        )
        assert not [r for r in comparison.rows if len(r.cells) > 1]
        assert any("no addressable record id" in line for line in comparison.unparsed)
        assert any("rebuild it" in line for line in comparison.unparsed)

    def test_the_headline_note_counts_deltas_refusals_and_absences(self):
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120"), rec(2, symbol="Tstg", value="-65 to 150")),
            part("B", rec(1, symbol="TJ", max="150"), rec(2, symbol="VDD", typ="1.8", unit="V")),
            term="temperature",
        )
        headline = comparison.notes[0]
        assert "1 carry an SI delta against A" in headline
        assert "2 are printed by only some of these parts" in headline

    def test_a_term_no_part_resolves_says_so(self):
        comparison = build_spec_comparison(
            [part("A"), part("B")], term="TJ", kind=KIND_SYMBOL
        )
        assert comparison.rows == []
        assert "none of A, B publishes a record" in comparison.empty_reason

    def test_a_row_that_printed_no_value_is_named_once_and_correctly(self):
        """Two reasons a row cannot become a column, and they must not be
        confused: a row with no printed value is the part's own unparsed
        population, not a corpus that predates ADR 0005."""
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120"), rec(2, symbol="TJ2")),
            part("B", rec(1, symbol="TJ", max="150")),
        )
        listing = [line for line in comparison.unparsed if "TJ2" in line]
        assert listing == ["A: TJ2: (no value printed) (p.4)"]
        assert not [line for line in comparison.unparsed if "predates ADR 0005" in line]

    def test_rows_that_could_not_be_published_are_a_different_absence(self):
        """Found, but uncitable — a finding about the rows, not about the query."""
        comparison = compare(
            part("A", rec(1, symbol="TJ", max="120", record_id="")),
            part("B", rec(1, symbol="TJ", max="150", record_id="")),
        )
        assert comparison.rows == []
        assert "A, B resolve it" in comparison.empty_reason
        assert "none of the 2 rows they found could be published" in comparison.empty_reason

    def test_a_parameter_only_one_part_prints_is_a_row_not_an_empty_comparison(self):
        comparison = compare(part("A", rec(1, symbol="TJ", max="120")), part("B"))
        assert comparison.empty_reason == ""
        assert row_of(comparison, "TJ").missing_from == ["B"]

    def test_an_empty_comparison_is_still_a_valid_artifact(self):
        comparison = build_spec_comparison(
            [part("A"), part("B")], term="TJ", kind=KIND_SYMBOL
        )
        assert comparison.schema_version == COMPARE_SCHEMA_VERSION
        assert comparison.card_version == CARD_VERSION
        assert comparison.empty_reason
        assert BANNER_PREFIX in render_comparison(comparison)


class TestRendering:
    """The table a choice is made on."""

    @pytest.fixture
    def markdown(self) -> str:
        comparison = compare(
            part(
                "A",
                rec(1, symbol="TJ", max="120"),
                rec(2, symbol="VDD", max="See Figure 7", unit="V"),
            ),
            part(
                "B",
                rec(1, symbol="Junction temperature", max="150"),
                rec(2, symbol="VDD", max="1.8", unit="V"),
            ),
            part("C", rec(1, symbol="Tstg", value="-65 to 150")),
            term="temperature",
        )
        return render_comparison(comparison)

    def _row(self, markdown: str, key: str) -> str:
        return next(
            line
            for line in markdown.splitlines()
            if line.startswith("|") and key in line and "Parameter" not in line
        )

    def test_it_opens_with_the_derived_banner(self, markdown):
        assert markdown.startswith(f"{BANNER_PREFIX} {CARD_VERSION} -->")

    def test_both_printed_values_and_both_page_cites_are_in_one_row(self, markdown):
        row = self._row(markdown, "TJ")
        assert "120 °C" in row and "150 °C" in row
        assert row.count("p.4") >= 2

    def test_a_delta_is_marked_derived_and_names_its_direction(self, markdown):
        assert "Δ B − A" in markdown
        assert "+30 °C *(derived)*" in markdown

    def test_a_part_that_prints_nothing_gets_a_dash_never_a_blank(self, markdown):
        assert "| — |" in self._row(markdown, "TJ")

    def test_a_row_with_no_comparable_column_still_shows_both_sides(self, markdown):
        row = self._row(markdown, "VDD")
        assert "See Figure 7 V" in row and "1.8 V" in row

    def test_what_could_not_be_compared_has_its_own_heading(self, markdown):
        assert NOT_COMPARABLE_HEADING in markdown

    def test_a_row_says_what_it_aligned_on(self, markdown):
        assert "alias:TJ" in markdown


class TestComparingWholeCards:
    """`--card power` compares two cards row by row."""

    def _cards(self) -> list[DesignCard]:
        return [
            card(
                "A",
                CardRow(
                    group="Temperature limits", label="TJ", section="4.1",
                    selector="temperature+alias:TJ",
                    values={"max": value("+120 °C", 120.0)},
                ),
                CardRow(
                    group="Thermal resistance", label="RthJA", section="4.2",
                    selector="thermal+alias:RthJA",
                    values={"value": value("30 °C/W", 30.0, unit_si="°C/W")},
                ),
            ),
            card(
                "B",
                CardRow(
                    group="Temperature limits", label="Junction temperature",
                    section="6.1", selector="temperature+alias:TJ",
                    values={"max": value("150 °C", 150.0)},
                ),
            ),
        ]

    def test_card_rows_align_and_subtract(self):
        comparison = build_card_comparison(self._cards(), name="thermal")
        row = row_of(comparison, "TJ")
        assert row.group == "Temperature limits"
        # both halves: off a card, and aligned by the alias lexicon inside it
        assert row.aligned_on == "card-row+alias:TJ"
        assert row.cells[1].delta.value_si == pytest.approx(30.0)
        assert row.cells[1].delta.derivation == f"{DERIVATION_DELTA}:max"

    def test_a_card_row_only_one_part_publishes_is_reported(self):
        comparison = build_card_comparison(self._cards(), name="thermal")
        row = row_of(comparison, "RthJA")
        assert row.missing_from == ["B"]
        assert FLAG_ONLY_IN in row.flags

    def test_a_card_row_keeps_the_provenance_the_card_gave_it(self):
        """A card comparison re-derives nothing: the envelope it shows is the
        one the card published, rule included — with the one addition a
        cross-part artifact needs, its part."""
        comparison = build_card_comparison(self._cards(), name="thermal")
        cell = row_of(comparison, "TJ").cells[0]
        assert cell.values["max"].source == f"parts/A/docs/{DOC}/specs.json#rec_1"
        assert cell.values["max"].verbatim == "+120 °C"
        assert cell.values["max"].derivation == DERIVATION_CELL_SI

    def test_an_empty_card_contributes_nothing_and_says_why(self):
        empty = DesignCard(
            card="thermal", part_number="C", card_version=CARD_VERSION,
            empty_reason="no thermal card: nothing matched",
        )
        comparison = build_card_comparison([*self._cards(), empty], name="thermal")
        assert "C: no thermal card" in "\n".join(comparison.unparsed)
        assert row_of(comparison, "TJ").missing_from == ["C"]


class TestTheCliIsFormatOnly:
    """`dsa compare` chooses parts, a query and a format — nothing else."""

    @pytest.fixture
    def settings(self, tmp_path, monkeypatch):
        from mcp_corpus import built_settings

        from datasheet_analyzer import cli

        resolved = built_settings(tmp_path)
        monkeypatch.setattr(cli, "get_settings", lambda: resolved)
        return resolved

    def _run(self, argv: list[str], capsys) -> tuple[int, str, str]:
        from datasheet_analyzer import cli

        code = cli.main(argv)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    def test_it_prints_the_comparison_the_core_built(self, settings, capsys):
        code, out, _err = self._run(
            ["compare", "TEST", "OTHER", "--name", "junction temperature"], capsys
        )
        assert code == 0
        assert "105 °C" in out and "125 °C" in out
        assert "+20 °C *(derived)*" in out
        assert NOT_COMPARABLE_HEADING not in out or "uncomparable" not in out

    def test_json_is_the_model_s_own_shape(self, settings, capsys):
        code, out, _err = self._run(
            ["compare", "TEST", "OTHER", "--symbol", "TJ", "--json"], capsys
        )
        payload = json.loads(out)
        assert code == 0
        assert payload["schema_version"] == COMPARE_SCHEMA_VERSION
        assert payload["parts"] == ["TEST", "OTHER"]
        row = next(r for r in payload["rows"] if r["key"] == "TJ")
        assert row["cells"][1]["delta"]["value_si"] == 20.0
        assert row["cells"][1]["delta"]["sources"]

    def test_a_card_comparison_runs_over_the_same_parts(self, settings, capsys):
        """`--card thermal` compares the whole card, row by row — the same two
        junction-temperature rows, reached through the card lexicon instead of
        through a query."""
        code, out, _err = self._run(
            ["compare", "TEST", "OTHER", "--card", "thermal"], capsys
        )
        assert code == 0
        assert "105 °C" in out and "125 °C" in out
        assert "+20 °C *(derived)*" in out

    def test_an_empty_card_comparison_says_why_and_exits_one(self, settings, capsys):
        """An empty comparison is a valid one — and a caller scripting against
        it can tell it apart without parsing the text."""
        code, out, _err = self._run(
            ["compare", "TEST", "OTHER", "--card", "interface"], capsys
        )
        assert code == 1
        assert "No rows." in out

    def test_an_unknown_card_is_refused_with_the_declared_names(self, settings, capsys):
        code, _out, err = self._run(
            ["compare", "TEST", "OTHER", "--card", "nope"], capsys
        )
        assert code == 2
        assert "no card named 'nope'" in err

    @pytest.mark.parametrize(
        "argv,needle",
        [
            (["compare", "TEST", "--symbol", "TJ"], "at least two parts"),
            (["compare", "TEST", "TEST", "--symbol", "TJ"], "named twice"),
            (["compare", "TEST", "NOPE", "--symbol", "TJ"], "no corpus for NOPE"),
        ],
    )
    def test_a_comparison_that_cannot_be_made_exits_two(
        self, settings, capsys, argv, needle
    ):
        code, _out, err = self._run(argv, capsys)
        assert code == 2
        assert needle in err

    def test_the_scope_object_answers_what_the_cli_prints(self, settings):
        """The seam: the CLI formats what `retrieve/` returned, and the same
        call from anywhere returns the same comparison."""
        scope = Comparison.for_parts(
            [settings.parts_dir / "TEST", settings.parts_dir / "OTHER"]
        )
        assert scope.parts == ("TEST", "OTHER")
        assert scope.missing_parts == ()
        assert row_of(scope.specs(symbol="TJ"), "TJ").cells[1].delta.value_si == 20.0
        assert scope.card("nope") is None
        assert "thermal" in scope.card_names()
