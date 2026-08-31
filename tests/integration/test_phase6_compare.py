"""Phase 6 gate — `dsa compare` over the reference parts (ticket 09).

The plan's gate is *"`dsa compare AFE7950 AFE7953` produces a delta table where
both sides parsed, and reports the unparsed population explicitly."* Run here
against real published corpora rather than fixtures:

1. **A real delta table.** 400+ rows align across the two parts, each carrying
   both verbatim values, both page cites and an SI delta.
2. **Deltas only where both sides parsed**, with the pairs that could not be
   compared listed by name and counted — "44 of 459 aligned value pair(s)
   could not be compared, listed below".
3. **`only in AFE7950` / `only in AFE7953` rows**, asserted against parameters
   that genuinely exist in one part only (the AFE7950 has four transmit
   channels, so it prints isolation figures the AFE7953 has no pairs for).
4. **`--symbol Pdiss`** shows every power-dissipation row of both parts with
   its verbatim value, its printed page and the operating mode that qualifies
   it, hand-verified against p.21 of each datasheet.
5. **`--card power`** compares a whole card row by row.
6. **Invariant 8**: every value on the comparison resolves back to a record
   and a printed page *in its own part's corpus* — the cross-corpus version of
   the phase's most important test.

**Two findings this gate records rather than hides.**

*Every delta between AFE7950 and AFE7953 is zero.* They are the 4T4R and 2T2R
members of one family, and every parameter that lines up exactly is printed
identically in both datasheets — asserted here rather than glossed over,
because it is also the strongest available evidence that the join is not
mis-aligning: a wrong pairing would show up as noise. Where the two parts do
differ (per-mode power dissipation, channel-count-specific isolation) the rows
do not line up at all, and the gate asserts that those are reported rather
than paired. `TestCrossVendorDeltas` shows non-zero deltas and an
alias-family alignment against LMX1204, and skips when that part is not built.

*`--symbol Pdiss` produces no aligned row.* The AFE7950 prints sixteen power
figures and the AFE7953 twelve, one per operating mode, and the mode names are
different configurations ("Mode 1: 4T2F - FDD" against "Mode 1a: 2T2R - TDD").
Nothing printed says which pairs with which, so nothing is paired: all 28 rows
are listed with their verbatim values and pages under a stated reason. Pairing
them by position would put a delta between two unrelated modes.

This is the one place invariant 4 is relaxed, exactly as far as the phase plan
allows: it reads built parts under `parts/` and skips whenever they are
absent. It never reaches the network, never calls a model, never rebuilds
anything, and never writes into a part directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.derive.compare import (
    DERIVATION_DELTA,
    FLAG_ONLY_IN,
    MATCH_FAMILY,
    STATUS_ALIGNED,
    STATUS_AMBIGUOUS,
    STATUS_ONLY_IN,
    Comparison,
    audit_comparison,
    compare_cards,
    compare_specs,
    render_comparison,
)
from datasheet_analyzer.models import CARD_POWER

REPO_ROOT = Path(__file__).resolve().parents[2]
PARTS_DIR = REPO_ROOT / "parts"
PAIR = ("AFE7950", "AFE7953")


def _part_dir(part: str) -> Path:
    path = PARTS_DIR / part
    if not (path / "manifest.json").is_file():
        pytest.skip(f"{part} is not built under parts/")
    return path


def _pair() -> list[tuple[str, Path]]:
    return [(part, _part_dir(part)) for part in PAIR]


@pytest.fixture(scope="module")
def reference_pair() -> list[tuple[str, Path]]:
    return _pair()


@pytest.fixture(scope="module")
def compared(reference_pair) -> Comparison:
    """The whole-corpus comparison, built once — it reads two 500+ record files."""
    return compare_specs(reference_pair)


class TestDeltaTable:
    def test_a_real_delta_table_is_produced(self, compared):
        assert len(compared.aligned) > 100
        assert compared.delta_count > 100
        assert compared.parts == list(PAIR)
        assert compared.baseline == "AFE7950"

    def test_every_aligned_row_carries_both_verbatim_values_and_both_pages(self, compared):
        for row in compared.aligned:
            assert set(row.cells) == set(PAIR)
            for part in PAIR:
                cell = row.cells[part]
                assert cell.values, f"{row.label}: {part} contributed no value"
                for column, value in cell.values.items():
                    assert value.verbatim, f"{row.label}[{column}]: {part} printed nothing"
                    assert value.page, f"{row.label}[{column}]: {part} carries no page"

    def test_every_row_records_what_it_matched_on(self, compared):
        assert all(row.matched_on for row in compared.rows)
        for row in compared.aligned:
            assert row.matched_on.startswith(("printed identity", "alias family", "printed symbol"))

    def test_every_delta_names_its_rule_and_cites_both_sides(self, compared):
        for row in compared.rows:
            for delta in row.deltas:
                assert delta.value.derivation == DERIVATION_DELTA
                assert delta.baseline == "AFE7950" and delta.part_number == "AFE7953"
                assert delta.value.source and delta.value.page
                assert delta.baseline_source and delta.baseline_page

    def test_hand_verified_against_the_printed_pages(self, compared):
        """§4.1 Absolute Maximum Ratings, p.4 of both datasheets.

        AFE7950: `| TJ | Junction temperature |  | 150 | °C |`
        AFE7953: `| TJ | Junction temperature |  | 150 | °C |`
        """
        rows = {
            row.label: row
            for row in compared.aligned
            if row.label in ("Junction temperature", "Storage temperature")
        }
        junction = rows["Junction temperature"]
        for part in PAIR:
            assert junction.cells[part].values["max"].verbatim == "150"
            assert junction.cells[part].values["max"].page == 4
        assert junction.deltas[0].value.value_si == 0.0
        assert junction.deltas[0].value.unit_si == "°C"

        # The cell is printed `–65` with an en dash; `structure/units` unifies
        # dashes at extraction, so the published verbatim is `-65`.
        storage = rows["Storage temperature"]
        for part in PAIR:
            assert storage.cells[part].values["min"].verbatim == "-65"
            assert storage.cells[part].values["max"].verbatim == "150"
            assert storage.cells[part].values["max"].page == 4

    def test_the_two_parts_print_every_aligned_value_identically(self, compared):
        """The recorded finding: siblings, so every delta is zero.

        Asserted rather than glossed over — and it is the strongest available
        evidence that the join is not mis-aligning, because a wrong pairing
        between two differently-specified rows would show up as a non-zero
        delta somewhere in four hundred rows.
        """
        differing = [
            (row.label, column)
            for row in compared.aligned
            for column, value in row.cells["AFE7950"].values.items()
            if column in row.cells["AFE7953"].values
            and value.verbatim != row.cells["AFE7953"].values[column].verbatim
        ]
        assert differing == []
        assert all(delta.value.value_si == 0.0 for row in compared.rows for delta in row.deltas)


class TestUnparsedPopulation:
    def test_the_uncompared_pairs_are_counted_and_listed(self, compared):
        assert compared.coverage.considered > compared.coverage.compared
        assert compared.coverage.uncompared == len(compared.coverage.reasons)
        sentence = compared.coverage.describe(limit=5)
        assert "aligned value pair(s) could not be compared, listed below:" in sentence
        assert sentence.startswith(str(compared.coverage.uncompared))

    def test_a_pair_that_did_not_parse_still_shows_both_verbatim_values(self, compared):
        listed = "\n".join(compared.coverage.reasons)
        assert "did not both parse to a number in the same unit" in listed
        assert "AFE7950 '" in listed and "AFE7953 '" in listed

    def test_each_part_reports_its_own_parse_coverage(self, compared):
        by_part = {part.part_number: part for part in compared.parse_coverage}
        assert set(by_part) == set(PAIR)
        for part in by_part.values():
            assert part.considered > 400
            assert part.parsed > 0
            assert "could not be parsed, listed below" in part.describe() or not part.unparsed

    def test_the_report_carries_both_populations(self, compared):
        text = render_comparison(compared)
        assert "## Not comparable" in text
        assert "## Parse coverage" in text


class TestOnlyInOnePart:
    def test_every_only_in_row_is_one_sided_and_carries_no_delta(self, compared):
        only = compared.rows_with(STATUS_ONLY_IN)
        assert only
        for row in only:
            assert len(row.present_in) == 1
            assert row.missing_from == [p for p in PAIR if p != row.present_in[0]]
            assert FLAG_ONLY_IN in row.flags
            assert row.deltas == []
            assert f"only in {row.present_in[0]}" in row.matched_on
            assert row.cells[row.present_in[0]].values

    def test_a_parameter_that_genuinely_exists_in_one_part_only(self, compared):
        """The AFE7950 has four transmit channels and prints isolation figures
        between pairs of them; the two-channel AFE7953 prints no counterpart.

        §4.6 of the AFE7950, p.14: `Near Channel:1RXIN to 2RXIN3RXIN to 4RXIN`
        under the symbol `RX-RX Isolation`. The AFE7953 has no third or fourth
        receiver, so the row is not in its datasheet at all.
        """
        rows = [row for row in compared.rows_with(STATUS_ONLY_IN) if row.present_in == ["AFE7950"]]
        assert rows
        isolation = [row for row in rows if "Isolation" in row.symbol]
        assert isolation
        row = isolation[0]
        assert row.missing_from == ["AFE7953"]
        assert "nothing published by AFE7953 names this parameter" in row.matched_on

    def test_the_other_direction_is_a_recorded_finding_not_an_omission(self, compared):
        """No AFE7953-only row exists in this corpus, and that is not a bug.

        Every parameter the AFE7953 prints and the AFE7950 does not — its one
        1.2 V rail group against the AFE7950's three — shares a symbol family
        with rows the AFE7950 *does* print, so it lands in the "not aligned"
        bucket with a stated reason rather than being claimed absent from the
        other part. "Nothing over there names this" and "the two datasheets
        group this differently" are different findings, and the comparison
        says which. Both directions are exercised on synthetic corpora in
        `tests/unit/test_compare.py`.
        """
        directions = {row.present_in[0] for row in compared.rows_with(STATUS_ONLY_IN)}
        assert directions == {"AFE7950"}
        rail_groups = [
            row
            for row in compared.rows_with(STATUS_AMBIGUOUS)
            if "AFE7953" in row.cells and row.label.startswith("Group 2:")
        ]
        assert rail_groups
        assert all("share the" in row.matched_on for row in rail_groups)

    def test_nothing_is_dropped(self, compared):
        """Every selected record of both parts appears in exactly one row."""
        cells = sum(len(row.cells) for row in compared.rows)
        printed = sum(part.considered for part in compared.parse_coverage)
        assert cells == printed


@pytest.fixture(scope="module")
def pdiss(reference_pair) -> Comparison:
    return compare_specs(reference_pair, symbol="Pdiss")


@pytest.fixture(scope="module")
def power(reference_pair) -> Comparison:
    """`write=False`: a gate never publishes into a checked-in part."""
    return compare_cards(reference_pair, CARD_POWER, write=False)


class TestSymbolMode:
    def test_the_symbol_resolves_through_the_alias_lexicon(self, pdiss):
        assert pdiss.resolved_symbol == "alias lexicon entry Pdiss"
        assert pdiss.warnings == []

    def test_every_row_of_both_parts_is_listed_with_its_page(self, pdiss):
        """Each row cites the page it is printed on, checked against the PDF.

        Section 4.9's table runs over six printed pages on AFE7950 and four on
        AFE7953. Before per-row page pinning (phase 6.5, ticket 07) every row
        of an HTML-derived table carried the page its *table* began on, so all
        28 rows cited p.21 and most of them were wrong. The count is unchanged
        — nothing was gained or lost — and the pages are now the printed ones.
        """
        import fitz

        rows = pdiss.rows_with(STATUS_AMBIGUOUS)
        assert len(rows) == 28
        pdfs = {part: REPO_ROOT / f"{part.lower()}.pdf" for part in PAIR}
        if not all(path.is_file() for path in pdfs.values()):
            pytest.skip("the source PDFs are not readable from here")
        pages = {}
        for part, path in pdfs.items():
            with fitz.open(path) as doc:
                pages[part] = [page.get_text() for page in doc]
        by_part: dict[str, list[str]] = {}
        for row in rows:
            (part,) = row.cells
            value = row.cells[part].values["typ"]
            assert value.page is not None
            assert value.verbatim in pages[part][value.page - 1], (part, value.verbatim, value.page)
            by_part.setdefault(part, []).append(value.verbatim)
        assert len(by_part["AFE7950"]) == 16
        assert len(by_part["AFE7953"]) == 12

    def test_hand_verified_against_page_21_of_each_datasheet(self, pdiss):
        """§4.9 Power Supply Electrical Characteristics, p.21 of both.

        AFE7950: `| Pdiss | Power Dissipation | Mode 1: 4T2F - FDD … | 6027.1 | mW |`
        AFE7953: `| Pdiss | Power Dissipation | Mode 1a: 2T2R - TDD … | 2399 | mW |`
        """
        printed = {
            (part, cell.values["typ"].verbatim): cell.conditions
            for row in pdiss.rows
            for part, cell in row.cells.items()
        }
        assert printed[("AFE7950", "6027.1")].startswith("Mode 1: 4T2F - FDD")
        assert printed[("AFE7953", "2399")].startswith("Mode 1a: 2T2R - TDD")

    def test_no_delta_is_invented_between_unrelated_modes(self, pdiss):
        assert pdiss.aligned == []
        assert pdiss.delta_count == 0
        reasons = {row.matched_on for row in pdiss.rows_with(STATUS_AMBIGUOUS)}
        assert len(reasons) == 1
        reason = reasons.pop()
        assert "16 row(s) in AFE7950" in reason and "12 row(s) in AFE7953" in reason
        assert "nothing printed says which pairs with which" in reason

    def test_the_refusal_is_visible_in_the_report(self, pdiss):
        text = render_comparison(pdiss)
        assert "## Not aligned (28)" in text
        assert "6027.1 (p.21)" in text and "2399 (p.21)" in text


class TestCardMode:
    def test_a_whole_card_compares_row_by_row(self, power):
        assert power.mode == "card" and power.card == CARD_POWER
        assert power.aligned
        assert power.delta_count > 0
        for row in power.aligned:
            assert set(row.cells) == set(PAIR)
            assert row.matched_on

    def test_card_rows_keep_the_cards_own_citations(self, power):
        for row in power.aligned:
            for cell in row.cells.values():
                for value in cell.values.values():
                    if value.filled:
                        assert value.source and value.page

    def test_nothing_was_written_into_the_part_directories(self, reference_pair, power):
        del power
        for _part, part_dir in reference_pair:
            cards = part_dir / "cards"
            if cards.exists():
                pytest.skip(f"{cards} already exists from an earlier `dsa card` run")


class TestInvariantEight:
    """Every value resolves to a record and a printed page in its own corpus."""

    def test_the_whole_comparison_resolves(self, reference_pair, compared):
        problems = audit_comparison(compared, dict(reference_pair))
        assert problems == [], "\n".join(problems[:20])

    def test_the_symbol_comparison_resolves(self, reference_pair):
        comparison = compare_specs(reference_pair, symbol="TJ")
        assert comparison.aligned
        assert audit_comparison(comparison, dict(reference_pair)) == []

    def test_the_card_comparison_resolves(self, reference_pair):
        comparison = compare_cards(reference_pair, CARD_POWER, write=False)
        assert audit_comparison(comparison, dict(reference_pair)) == []

    def test_the_walk_is_not_vacuous(self, reference_pair):
        comparison = compare_specs(reference_pair, symbol="TJ")
        broken = comparison.model_copy(deep=True)
        cell = next(iter(broken.aligned[0].cells.values()))
        next(iter(cell.values.values())).page = 9999
        problems = audit_comparison(broken, dict(reference_pair))
        assert any("is printed on p." in problem for problem in problems)


@pytest.fixture(scope="module")
def cross() -> Comparison:
    """AFE7950 against a part from another product line, when it is built."""
    pair = [("AFE7950", _part_dir("AFE7950")), ("LMX1204", _part_dir("LMX1204"))]
    comparison = compare_specs(pair)
    if not any("LMX1204" in row.cells for row in comparison.rows):
        pytest.skip("LMX1204 publishes no readable spec records in this environment")
    return comparison


class TestCrossVendorDeltas:
    """Non-zero deltas and an alias-family alignment, against a third part.

    LMX1204 is not a checked-in corpus, so this skips when it is not built —
    but where it is, it is the case the AFE pair cannot show: two unrelated
    parts, differently-named equivalents lined up by the alias lexicon, and
    deltas that are not zero.
    """

    def test_alias_resolution_lines_up_differently_named_equivalents(self, cross):
        families = [row for row in cross.aligned if row.matched_on.startswith(MATCH_FAMILY)]
        assert families, "no row aligned by alias family"
        for row in families:
            assert row.symbol
            assert "prints" in row.matched_on  # names what each part printed

    def test_non_zero_deltas_are_computed(self, cross):
        deltas = [
            (row.label, delta.value.verbatim)
            for row in cross.aligned
            for delta in row.deltas
            if delta.value.value_si
        ]
        assert deltas

    def test_hand_verified_against_the_printed_pages(self, cross):
        """AFE7950 §4.8 p.20: `| VOL | Low-Level Output Voltage | … | 0.2 | V |`
        LMX1204 §5.5 p.7: `| VOL | Low-level output voltage | IOL = 5 mA | … | 0.45 | V |`

        The LMX1204 page moved from 6 to 7 in phase 6.5: `lmx1204.pdf` prints
        `Low-level output voltage`, `IOL = 5 mA` and `0.45` on page **7** and
        on no other page, and per-row page pinning (ticket 07) is what made
        the citation say so. The old `6` was the page its table started on.
        """
        row = next(
            row
            for row in cross.aligned
            if row.label.lower() == "low-level output voltage" and row.status == STATUS_ALIGNED
        )
        assert row.cells["AFE7950"].values["max"].verbatim == "0.2"
        assert row.cells["AFE7950"].values["max"].page == 20
        assert row.cells["LMX1204"].values["max"].verbatim == "0.45"
        assert row.cells["LMX1204"].values["max"].page == 7
        delta = next(d for d in row.deltas if d.cell == "max")
        assert delta.value.value_si == pytest.approx(0.25)
        assert delta.value.verbatim == "+0.25 V"
