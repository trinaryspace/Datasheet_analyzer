"""Phase 6 gate — design cards over the reference parts (ticket 07).

The acceptance gate, run against real published corpora rather than fixtures:

1. **All four cards build for AFE7950 and AD9081.**
2. **Every value on every card resolves to a spec/pin record and a printed
   page**, asserted programmatically by walking each card's `source` fields.
   This is the invariant-8 test and the most important test in the phase.
3. The `limits` card's margins are **hand-verified against the printed PDF
   pages** — AFE7950 p.4 (Absolute Maximum Ratings) against p.6 (Recommended
   Operating Conditions).
4. Every pair the join could not compare is **named on the card**, and any
   parameter whose recommended maximum equals its absolute-maximum rating is
   flagged `zero-margin`.
5. The rendered `cards/*.md` carries the `card_version` banner and a citation
   on every row.

This is the one place invariant 4 is relaxed, exactly as far as the phase plan
allows: it reads built parts under `parts/` and (for the hand-verification)
their source PDFs, and it skips whenever either is absent. It never reaches the
network, never calls a model, never rebuilds anything.

**A finding this gate records rather than hides:** neither reference part
prints a parameter whose recommended maximum equals its absolute maximum, so
there is no zero-margin row to point at in real data. The flag is proved on a
synthetic corpus in `tests/unit/test_cards.py`, and the assertion here is the
one that would catch a regression either way — every equal-limit pair found in
a reference part must carry the flag, and today that set is empty.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.derive.cards import (
    FLAG_NEGATIVE_MARGIN,
    FLAG_ZERO_MARGIN,
    audit_card,
    build_part_cards,
    render_card,
    row_citation,
)
from datasheet_analyzer.derive.provenance import check_provenance, describe_problems
from datasheet_analyzer.models import CARD_KINDS, CARD_LIMITS, CARD_THERMAL, Card
from datasheet_analyzer.publish import document_dirs, read_manifest
from datasheet_analyzer.retrieve.index import CorpusIndex

REPO_ROOT = Path(__file__).resolve().parents[2]
PARTS_DIR = REPO_ROOT / "parts"
REFERENCE_PARTS = ("AFE7950", "AD9081")

#: The card version these assertions were written against. Passed explicitly
#: so the gate does not depend on the ambient `DSA_CARD_VERSION`.
CARD_VERSION = "2"


def _part_dir(part: str) -> Path:
    path = PARTS_DIR / part
    if not (path / "manifest.json").is_file():
        pytest.skip(f"{part} is not built under parts/")
    return path


@pytest.fixture(scope="module")
def built_cards() -> dict[str, dict[str, Card]]:
    """Every card of every reference part, built once for the module."""
    out: dict[str, dict[str, Card]] = {}
    for part in REFERENCE_PARTS:
        path = PARTS_DIR / part
        if not (path / "manifest.json").is_file():
            continue
        out[part] = build_part_cards(path, part, card_version=CARD_VERSION)
    if not out:
        pytest.skip("no reference part is built under parts/")
    return out


@pytest.fixture(scope="module")
def limits(built_cards) -> Card:
    """AFE7950's `limits` card — the one with both tables to join."""
    if "AFE7950" not in built_cards:
        pytest.skip("AFE7950 is not built under parts/")
    return built_cards["AFE7950"][CARD_LIMITS]


class TestAllFourCardsBuild:
    """Gate 1: all four cards build for AFE7950 and AD9081."""

    @pytest.mark.parametrize("part", REFERENCE_PARTS)
    def test_every_card_kind_is_produced(self, part, built_cards):
        if part not in built_cards:
            pytest.skip(f"{part} is not built under parts/")
        cards = built_cards[part]
        assert set(cards) == set(CARD_KINDS)
        for kind, card in cards.items():
            assert card.card == kind
            assert card.part_number == part
            assert card.card_version == CARD_VERSION

    @pytest.mark.parametrize("part", REFERENCE_PARTS)
    def test_a_card_with_no_rows_says_what_it_looked_for(self, part, built_cards):
        """An empty card is an answer; a silent one is not."""
        if part not in built_cards:
            pytest.skip(f"{part} is not built under parts/")
        for card in built_cards[part].values():
            if not card.rows:
                assert card.unresolved, f"{part}/{card.card} is empty and says nothing"

    def test_afe7950_fills_every_card_it_has_the_data_for(self, built_cards):
        if "AFE7950" not in built_cards:
            pytest.skip("AFE7950 is not built under parts/")
        cards = built_cards["AFE7950"]
        for kind in CARD_KINDS:
            assert cards[kind].rows, f"AFE7950/{kind} came out empty"


class TestInvariantEightOverRealCorpora:
    """Gate 2: every value on every card resolves to a record and a page.

    The phase's most important test. It walks each card's `source` fields with
    `derive/provenance.py`'s resolver — the same one every derived artifact
    answers to — and fails on an orphan value, a value with no provenance, or
    a citation naming a page the record is not printed on.
    """

    @pytest.mark.parametrize("part", REFERENCE_PARTS)
    def test_every_source_on_every_card_resolves(self, part, built_cards):
        if part not in built_cards:
            pytest.skip(f"{part} is not built under parts/")
        part_dir = _part_dir(part)
        library_dir = CorpusIndex.load(part_dir).library_dir
        checked = 0
        for card in built_cards[part].values():
            audit = audit_card(card, part_dir=part_dir, library_dir=library_dir)
            assert audit.ok, audit.describe()
            assert audit.resolved == audit.checked
            checked += audit.checked
        assert checked > 0, f"{part} produced no cited value to check"

    @pytest.mark.parametrize("part", REFERENCE_PARTS)
    def test_the_structural_half_of_the_contract_holds_too(self, part, built_cards):
        if part not in built_cards:
            pytest.skip(f"{part} is not built under parts/")
        for card in built_cards[part].values():
            problems = check_provenance(card)
            assert problems == [], describe_problems(problems, subject=f"{part}/{card.card}")

    @pytest.mark.parametrize("part", REFERENCE_PARTS)
    def test_every_unfilled_value_says_why_it_is_unfilled(self, part, built_cards):
        if part not in built_cards:
            pytest.skip(f"{part} is not built under parts/")
        for card in built_cards[part].values():
            for row in card.rows:
                for key, value in row.values.items():
                    if not value.filled:
                        assert value.null_reason, f"{part}/{card.card}/{row.label}/{key}"

    @pytest.mark.parametrize("part", REFERENCE_PARTS)
    def test_a_card_names_the_artifacts_it_drew_from(self, part, built_cards):
        if part not in built_cards:
            pytest.skip(f"{part} is not built under parts/")
        for card in built_cards[part].values():
            if card.rows:
                assert card.sources, f"{part}/{card.card} cites records but names no artifact"
                for source in card.sources:
                    assert source.endswith(".json")


class TestAFE7950Limits:
    """Gate 3+4: hand-verified margins, and everything else named out loud.

    The two comparable pairs were read off the printed PDF:

    - p.4 *Absolute Maximum Ratings*: `Junction temperature ... 150 °C`,
      `DVDD0P9, VDDT0P9 ... 1.2 V`
    - p.6 *Recommended Operating Conditions*:
      `Operating Junction Temperature ... 110(1) °C`,
      `DVDD0P9, VDDT0P9 ... 0.95 V`

    so the margins are 40 °C and 0.25 V.
    """

    def test_the_junction_temperature_margin_matches_the_printed_pages(self, limits):
        row = next(row for row in limits.rows if row.label == "Junction temperature")
        assert row.values["abs_max"].verbatim == "150"
        assert row.values["abs_max"].page == 4
        assert row.values["recommended"].verbatim == "110(1)"
        assert row.values["recommended"].page == 6
        margin = row.values["margin"]
        assert margin.value_si == pytest.approx(40.0)
        assert margin.unit_si == "°C"
        assert margin.derivation == "abs_max_margin"

    def test_the_supply_rail_margin_matches_the_printed_pages(self, limits):
        row = next(row for row in limits.rows if "DVDD0P9" in row.label)
        assert row.values["abs_max"].verbatim == "1.2"
        assert row.values["recommended"].verbatim == "0.95"
        assert row.values["margin"].value_si == pytest.approx(0.25)
        assert row.values["margin"].unit_si == "V"

    def test_margin_is_computed_only_where_both_sides_parsed(self, limits):
        for row in limits.rows:
            margin = row.values.get("margin")
            if margin is None or not margin.filled:
                continue
            for side in ("abs_max", "recommended"):
                assert row.values[side].filled, f"{row.label}: margin without a {side}"
                assert row.values[side].value_si is not None, (
                    f"{row.label}: margin computed from an unparsed {side}"
                )

    def test_every_pair_it_could_not_compare_is_listed(self, limits):
        uncompared = [row.label for row in limits.rows if not row.values["margin"].filled]
        assert uncompared, "the limits card compared everything — check the fixture"
        text = "\n".join(limits.unresolved)
        for label in uncompared:
            assert label in text, f"{label} was not compared and the card never says so"

    def test_a_value_that_is_not_a_number_is_carried_verbatim_not_dropped(self, limits):
        """`VDDRX1P8+0.3` is a real printed rating and not a quantity."""
        rows = [
            row
            for row in limits.rows
            if row.values.get("abs_max") is not None
            and row.values["abs_max"].filled
            and row.values["abs_max"].value_si is None
        ]
        assert rows, "AFE7950 §4.1 prints ratings that are expressions, not numbers"
        for row in rows:
            assert row.values["abs_max"].derivation == "verbatim_copy"
            assert not row.values["margin"].filled


class TestZeroMarginHazard:
    """Gate 4: a zero-margin parameter is flagged wherever one is printed."""

    def test_every_equal_limit_pair_in_a_reference_part_is_flagged(self, built_cards):
        equal: list[tuple[str, str]] = []
        for part, cards in built_cards.items():
            for row in cards[CARD_LIMITS].rows:
                abs_max = row.values.get("abs_max")
                recommended = row.values.get("recommended")
                if abs_max is None or recommended is None:
                    continue
                if abs_max.value_si is None or recommended.value_si is None:
                    continue
                if abs_max.unit_si != recommended.unit_si:
                    continue
                if abs_max.value_si == recommended.value_si:
                    equal.append((part, row.label))
                    assert FLAG_ZERO_MARGIN in row.flags, f"{part}/{row.label}"
                    assert row.values["margin"].value_si == 0.0
        # Recorded rather than asserted away: today this list is empty, which
        # is why the flag itself is proved on synthetic data in the unit test.
        assert isinstance(equal, list)

    def test_no_reference_part_prints_a_recommended_maximum_above_its_rating(self, built_cards):
        """If one ever does, the flag fires and this test tells us it happened."""
        offenders = [
            (part, row.label)
            for part, cards in built_cards.items()
            for row in cards[CARD_LIMITS].rows
            if FLAG_NEGATIVE_MARGIN in row.flags
        ]
        assert offenders == []


class TestAFE7950Thermal:
    def test_the_thermal_card_carries_the_printed_resistances(self, built_cards):
        if "AFE7950" not in built_cards:
            pytest.skip("AFE7950 is not built under parts/")
        rows = {row.label: row for row in built_cards["AFE7950"][CARD_THERMAL].rows}
        rtheta = rows["Junction-to-ambient thermal resistance"]
        assert rtheta.values["value"].verbatim == "16.2"
        assert rtheta.values["value"].unit_si == "°C/W"
        assert rtheta.values["value"].page == 6
        assert "Junction-to-top characterization parameter" in rows
        assert "Junction-to-board characterization parameter" in rows


class TestRenderedCards:
    """Gate 5: the banner, and a citation on every rendered row."""

    @pytest.mark.parametrize("part", REFERENCE_PARTS)
    def test_the_banner_names_the_card_version(self, part, built_cards):
        if part not in built_cards:
            pytest.skip(f"{part} is not built under parts/")
        for card in built_cards[part].values():
            first = render_card(card).splitlines()[0]
            assert first == f"<!-- derived: card_version {CARD_VERSION} -->"

    @pytest.mark.parametrize("part", REFERENCE_PARTS)
    def test_every_rendered_row_carries_a_citation(self, part, built_cards):
        if part not in built_cards:
            pytest.skip(f"{part} is not built under parts/")
        for card in built_cards[part].values():
            for row in card.rows:
                assert row_citation(row), f"{part}/{card.card}: {row.label} is uncited"
            for line in render_card(card).splitlines():
                if not line.startswith("|") or line.startswith("|---"):
                    continue
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if cells[0] == "Parameter":
                    continue
                assert cells[-1] not in ("", "—"), f"{part}/{card.card}: {line}"


class TestAd9081RecordsAreIndividuallyAddressable:
    """The collision phase 6 refused around, closed by phase 6.5 ticket 08.

    `spec_record_id` was a pure function of `(section, table_index, row_index)`
    and `build_specset` numbered tables *within* a section, so AD9081 — whose
    sections carry no printed numbers — restarted `table_index` at 0 in every
    one of them: 549 records carried 259 distinct ids, `rec_s-t0-r0` alone was
    carried by 14, and the card cited the first record of each id and refused
    the rest. Its interface card kept 1 row of the 21 its selectors matched.

    The id now keys on the section's published file stem. Measured on the
    rebuild: 549 records, 549 distinct ids, no card refusing a record for
    sharing one, and the interface card publishing all 21 rows including the
    JESD204B and JESD204C rate rows the datasheet prints on p.11.
    """

    def test_every_spec_record_id_is_distinct(self):
        from datasheet_analyzer.models import SpecSet

        part_dir = _part_dir("AD9081")
        manifest = read_manifest(part_dir)
        totals = []
        for directory in document_dirs(manifest, part_dir=part_dir).values():
            path = directory / "specs.json"
            if not path.is_file():
                continue
            specset = SpecSet.model_validate_json(path.read_text(encoding="utf-8"))
            ids = [record.id for record in specset.records]
            totals.append((len(ids), len(set(ids))))
            assert len(ids) == len(set(ids))
        assert totals == [(549, 549)], totals

    def test_no_card_refuses_a_record_for_sharing_an_id(self, built_cards):
        if "AD9081" not in built_cards:
            pytest.skip("AD9081 is not built under parts/")
        offenders = [
            warning
            for card in built_cards["AD9081"].values()
            for warning in card.warnings
            if "share a record id" in warning
        ]
        assert offenders == [], offenders

    def test_the_interface_card_publishes_the_rows_its_selectors_match(self, built_cards):
        if "AD9081" not in built_cards:
            pytest.skip("AD9081 is not built under parts/")
        interface = built_cards["AD9081"]["interface"]
        assert len(interface.rows) == 21
        labels = [row.label.upper() for row in interface.rows]
        assert "JESD204B SERIAL INTERFACE RATE" in labels
        assert "JESD204C SERIAL INTERFACE RATE" in labels

    def test_what_survives_the_refusal_still_resolves(self, built_cards):
        if "AD9081" not in built_cards:
            pytest.skip("AD9081 is not built under parts/")
        part_dir = _part_dir("AD9081")
        library_dir = CorpusIndex.load(part_dir).library_dir
        for card in built_cards["AD9081"].values():
            audit = audit_card(card, part_dir=part_dir, library_dir=library_dir)
            assert audit.ok, audit.describe()


class TestHonestlyEmptyOnARealPart:
    """The empty card, asserted against a real part that has no interface.

    LM741 is an operational amplifier: it prints absolute-maximum ratings and
    electrical characteristics, and it has no digital interface of any kind.
    Its `interface` card must come out empty *and say what it looked for* —
    "this part has no interface section" and "nobody built this card" are
    different answers, and only one of them is true here.
    """

    def test_lm741s_interface_card_is_empty_with_a_stated_reason(self):
        part_dir = PARTS_DIR / "lm741"
        if not (part_dir / "manifest.json").is_file():
            pytest.skip("lm741 is not built under parts/")
        cards = build_part_cards(part_dir, "lm741", card_version=CARD_VERSION)
        interface = cards["interface"]
        assert interface.rows == []
        assert interface.is_empty
        assert interface.unresolved
        for group in ("standards", "lanes", "lane_rate", "spi_timing"):
            assert any(f"interface/{group}" in line for line in interface.unresolved)
        assert "This card is empty" in render_card(interface)

    def test_lm741_still_fills_the_cards_it_does_have_data_for(self):
        part_dir = PARTS_DIR / "lm741"
        if not (part_dir / "manifest.json").is_file():
            pytest.skip("lm741 is not built under parts/")
        cards = build_part_cards(part_dir, "lm741", card_version=CARD_VERSION)
        assert cards["thermal"].rows, "lm741 prints thermal information"
        assert cards["limits"].rows, "lm741 prints absolute maximum ratings"
        library_dir = CorpusIndex.load(part_dir).library_dir
        for card in cards.values():
            audit = audit_card(card, part_dir=part_dir, library_dir=library_dir)
            assert audit.ok, audit.describe()
