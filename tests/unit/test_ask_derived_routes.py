"""`dsa ask` routing over the phase-6 derived tables (ticket 10).

The phase's claim is that a *pin* question and a *register* question reach the
table that answers them instead of a paragraph that happens to contain the
word. That is one routing rule with two obligations, and both are tested here:

- **it fires** — pin vocabulary plus a named pin or a lexicon type reaches
  `pins.json`; register vocabulary plus a name or an address reaches
  `registers.json`; both answers carry the printed page;
- **it never fires by accident** — vocabulary alone routes nothing, a corpus
  that published no such table routes exactly as it did before phase 6, and a
  question that names nothing the table holds falls through rather than
  answering from the wrong place.

The second half is the one that protects the phase-5 goldens: the derived
routes are tried first, so the only thing standing between them and a
regression is that they decline cleanly. Every case here declines or answers
against a corpus built in a `tmp_path`, with no network, no model and no
subprocess (AGENTS.md invariant 4).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp_corpus import DOC, build_part, empty_settings

from datasheet_analyzer.config import Settings
from datasheet_analyzer.retrieve import (
    ANSWER_PACK_SCHEMA,
    ROUTE_PIN,
    ROUTE_REGISTER,
    ROUTE_SPEC,
    Retriever,
    clear_index_cache,
    validate_pack,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    build_part(tmp_path / "parts" / "TEST")
    return empty_settings(tmp_path)


@pytest.fixture
def scope(settings: Settings) -> Retriever:
    return Retriever.for_part(settings.parts_dir / "TEST")


@pytest.fixture
def bare(tmp_path: Path) -> Retriever:
    """The same corpus with its derived tables removed, and nothing else."""
    part_dir = tmp_path / "bare" / "parts" / "BARE"
    build_part(part_dir)
    for artifact in ("pins.json", "registers.json"):
        (part_dir / "docs" / DOC / artifact).unlink()
    clear_index_cache()
    return Retriever.for_part(part_dir)


class TestThePinRoute:
    def test_a_type_question_is_answered_from_the_pin_table(self, scope):
        pack = scope.ask("which pins are ground?", budget=2000)
        assert pack.route == ROUTE_PIN
        assert [line.page_start for line in pack.answers] == [6, 6]
        assert "VSSA" in pack.answers[0].text
        assert "[ground" in pack.answers[0].text

    def test_a_designator_question_is_answered_from_the_pin_table(self, scope):
        pack = scope.ask("what is pin B1?", budget=2000)
        assert pack.route == ROUTE_PIN
        assert "VDD1P8" in pack.answers[0].text

    def test_the_type_word_comes_from_the_checked_in_lexicon(self, scope):
        """`ground` labels a pin because `pin_types.yaml` says so, not because
        the router recognised the shape of the word."""
        from datasheet_analyzer.retrieve.pack import _pin_type_named

        assert _pin_type_named("which pins are ground?") == "ground"
        assert _pin_type_named("which pins are supply pins?") == "power"
        assert _pin_type_named("which pins are purple?") == ""

    def test_a_type_word_inside_a_longer_word_does_not_count(self, scope):
        """`background` is not `ground`; whole words only."""
        from datasheet_analyzer.retrieve.pack import _pin_type_named

        assert _pin_type_named("what is the background of these pins?") == ""

    def test_every_answer_line_carries_its_citation(self, scope):
        pack = scope.ask("which pins are ground?", budget=2000)
        assert pack.citations
        assert all(line.citation for line in pack.answers)
        assert all("p.6" in line.citation for line in pack.answers)


class TestTheRegisterRoute:
    def test_a_name_question_is_answered_from_the_register_map(self, scope):
        pack = scope.ask("what is the reset value of TXDIG_CTRL0?", budget=2000)
        assert pack.route == ROUTE_REGISTER
        assert "0x00" in pack.answers[0].text
        assert pack.answers[0].page_start == 7

    def test_an_address_question_resolves_by_value(self, scope):
        for form in ("0x1A04", "0x1a04"):
            pack = scope.ask(f"which register is at address {form}?", budget=2000)
            assert pack.route == ROUTE_REGISTER
            assert "TXDIG_CTRL0" in pack.answers[0].text

    def test_the_printed_access_travels_with_the_answer(self, scope):
        pack = scope.ask("what is register TXDIG_CTRL0?", budget=2000)
        assert "access R/W" in pack.answers[0].text


class TestTheRoutesDeclineCleanly:
    """The half that keeps phase 5 exactly where it was."""

    def test_a_corpus_with_no_pin_table_routes_as_it_did_before(self, bare):
        pack = bare.ask("which pins are ground?", budget=2000)
        assert pack.route != ROUTE_PIN

    def test_a_corpus_with_no_register_map_routes_as_it_did_before(self, bare):
        pack = bare.ask("what is the reset value of TXDIG_CTRL0?", budget=2000)
        assert pack.route != ROUTE_REGISTER

    def test_vocabulary_alone_routes_nothing(self, scope):
        """ "pin" is not a pin question until it names a pin or a type.

        The corpus here has a pin table and the question says "pins"; what it
        does not do is name one. The router therefore declines and the older
        routes answer — here with an explicit no-match, which is the honest
        outcome for a question this small corpus has nothing to say about.
        """
        pack = scope.ask("how many pins does the package have?", budget=2000)
        assert pack.route not in (ROUTE_PIN, ROUTE_REGISTER)

    def test_a_named_pin_the_table_does_not_hold_falls_through(self, scope):
        pack = scope.ask("what is pin ZZ99?", budget=2000)
        assert pack.route != ROUTE_PIN

    def test_a_spec_question_still_routes_to_the_spec_ladder(self, scope):
        """The phase-5 answer, asked of a corpus that now has both tables."""
        pack = scope.ask("max junction temperature", budget=2000)
        assert pack.route == ROUTE_SPEC
        assert "105" in pack.answers[0].text

    def test_the_word_register_in_a_spec_question_does_not_hijack_it(self, scope):
        """A phase-5 golden's exact shape: "register" appears, no register does."""
        pack = scope.ask("what is the minimum SCLK period for register writes?", budget=2000)
        assert pack.route != ROUTE_REGISTER


class TestTheDeclaredShapeKnowsTheNewRoutes:
    def test_a_pin_pack_validates_against_the_declared_schema(self, scope):
        payload = scope.ask("which pins are ground?", budget=2000).as_dict()
        assert validate_pack(payload) == []
        assert payload["route"] == ROUTE_PIN

    def test_the_schema_would_reject_a_route_nobody_declared(self, scope):
        payload = scope.ask("which pins are ground?", budget=2000).as_dict()
        payload["route"] = "vibes"
        assert validate_pack(payload)

    def test_both_new_routes_are_in_the_declared_enum(self):
        assert {ROUTE_PIN, ROUTE_REGISTER} <= set(ANSWER_PACK_SCHEMA["properties"]["route"]["enum"])
