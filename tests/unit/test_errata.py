"""Errata cross-linking (phase 7, ticket 04) - rule by rule.

Ported from `feat/phase7-reach-trust` onto this branch's layout. The gate
(`tests/integration/test_phase7_errata.py`) proves the linker against a **real**
datasheet's published records with declared errata prose; what is proven here is
every rule on its own, and that each one refuses for the right reason:

- a section number links only when the item **cues** it, because an uncued `6.1`
  in errata prose is a supply voltage far more often than a section, and this
  rule's output is what puts a warning banner on a page;
- a symbol links only when it **reads like** a symbol: the layout floor records
  `Supply` and `Input` in the symbol column of datasheets that print no symbol
  column, and matching those would link on an ordinary English word;
- a register address is compared **as an integer**, so a register whose printed
  address the grammar could not read is honestly unreachable rather than matched
  by a string comparison against another notation;
- **nothing is ever lost**: `n_items` is the sum of two named lists, an item no
  rule could place is published under a constant heading, and a rule that hit the
  lexicon's cap states how many it found;
- and there is **no similarity rung anywhere** - asserted twice, once over the
  package source and once behaviourally on prose that paraphrases a section title
  and names no identifier.

The one adaptation this branch forces is the reference shape: a record target is
`models.source_ref(f"{ref_base}/{artifact}", record.id)`, and `ref_base` is
carried on `TargetDoc` rather than composed from the document name, because a
document published once into the shared library store (ADR 0008) is cited
`@library/docs/<doc>/...` and a part-relative reference to it resolves to
nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.config import ERRATA_SCHEMA_VERSION, PIPELINE_VERSION, Settings
from datasheet_analyzer.errata import (
    ERRATA_LINKS_FILENAME,
    ERRATA_MARKDOWN_FILENAME,
    RULES,
    UNLINKED_HEADING,
    ErrataLexicon,
    TargetDoc,
    build_errata_links,
    build_items,
    insert_banner,
    is_errata,
    links_by_target,
    load_errata_lexicon,
    pack_warning,
    render_errata,
    section_banner,
    sections_to_banner,
)
from datasheet_analyzer.errata.items import (
    DERIVATION_MARKER,
    DERIVATION_ORDINAL,
    DERIVATION_SECTION,
)
from datasheet_analyzer.errata.lexicon import (
    RULE_ALIAS_PHRASE,
    RULE_PIN_NAME,
    RULE_REGISTER_ADDRESS,
    RULE_REGISTER_NAME,
    RULE_SECTION_NUMBER,
    RULE_SPEC_SYMBOL,
    RULE_TABLE_CAPTION,
)
from datasheet_analyzer.models import (
    Confidence,
    DocType,
    ErrataTargetKind,
    ExtractionStats,
    PinRecord,
    RawDocument,
    RegisterRecord,
    RegisterValue,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecUnit,
    TableBlock,
)

DOC = "datasheet-c0ffee00"
ERRATA_DOC = "errata-deadbeef"
BASE = f"docs/{DOC}"


# --- helpers ------------------------------------------------------------------


def _errata_doc(*paragraphs: str, number: str = "1", page: int = 1) -> RawDocument:
    """An errata document as `pdf_text` publishes one: a section of printed lines."""
    return RawDocument(
        source=SourceDocument(
            content_hash="ee" + "0" * 62,
            path="errata.pdf",
            part_number="TESTPART",
            doc_type=DocType.ERRATA,
            page_count=1,
        ),
        sections=[
            SectionNode(
                number=number,
                title=f"Page {page}",
                page_start=page,
                page_end=page,
                paragraphs=list(paragraphs),
            )
        ],
        extractor="pdf_text",
        extractor_version="test-1",
        extraction_stats=ExtractionStats(backend="pdf_text"),
    )


def _spec(row: int, symbol: str = "", name: str = "", section: str = "4.1", **kw) -> SpecRecord:
    return SpecRecord(
        section=section,
        section_key=section.replace(".", "_"),
        table_index=0,
        row_index=row,
        symbol=symbol,
        name=name,
        unit=SpecUnit(verbatim="V", canonical="V"),
        page=4,
        confidence=Confidence.HIGH,
        **kw,
    )


def _pin(row: int, pin: str, name: str) -> PinRecord:
    return PinRecord(
        pin=pin,
        name=name,
        type="power",
        section="6",
        table_index=0,
        row_index=row,
        page=9,
        confidence=Confidence.HIGH,
    )


def _register(row: int, addr: str, value: int | None, name: str) -> RegisterRecord:
    return RegisterRecord(
        address=RegisterValue(verbatim=addr, value=value),
        name=name,
        section="1",
        table_index=0,
        row_index=row,
        doc_key="d0",
        page=2,
        confidence=Confidence.HIGH,
    )


def _section(number: str, title: str, page: int = 4, tables=()) -> SectionNode:
    return SectionNode(
        number=number, title=title, page_start=page, page_end=page, tables=list(tables)
    )


def _target(**kw) -> TargetDoc:
    """One published document as a surface an erratum can point at."""
    sections = kw.pop("sections", ())
    return TargetDoc(
        name=DOC,
        doc_hash="c0" + "0" * 62,
        ref_base=BASE,
        sections=tuple((s, f"{BASE}/sections/{s.number or s.title}.md") for s in sections),
        **kw,
    )


def _link_one(text: str, target: TargetDoc, *, marker: str = "Advisory 1"):
    """One item's link set, built from one printed paragraph block."""
    items = build_items([(ERRATA_DOC, _errata_doc(marker, text))])
    assert len(items) == 1
    return build_errata_links("TESTPART", items, [target], errata_docs=[ERRATA_DOC])


# --- the lexicon --------------------------------------------------------------


class TestLexicon:
    def test_the_shipped_lexicon_grades_every_named_rule(self):
        lexicon = load_errata_lexicon()
        assert set(RULES) == {name for name, _grade in lexicon.rules}
        for rule in RULES:
            assert lexicon.grade(rule) in (Confidence.HIGH, Confidence.MEDIUM)

    def test_a_marker_needs_an_identifier_after_the_word(self):
        lexicon = load_errata_lexicon()
        assert lexicon.marker_start("Advisory 3  the device...") == "Advisory 3"
        assert lexicon.marker_start("Erratum no. 12b applies") == "Erratum no. 12b"
        # Prose that merely opens with a marker word is prose.
        assert lexicon.marker_start("Item numbers are listed below") == ""
        assert lexicon.marker_start("Advisories are published quarterly") == ""

    def test_the_longest_marker_phrase_wins(self):
        lexicon = load_errata_lexicon()
        assert lexicon.marker_start("Errata item 4 - the device") == "Errata item 4"

    def test_an_unreadable_lexicon_degrades_to_one_that_links_nothing(self, tmp_path):
        """Invariant 7: every item is still published, under "unlinked errata"."""
        empty = ErrataLexicon.read(tmp_path / "missing.yaml")
        assert empty.item_markers == ()
        assert empty.section_cue_pattern is None
        assert empty.pin_cue_pattern is None
        assert empty.grade(RULE_SECTION_NUMBER) == Confidence.UNKNOWN

    def test_a_rule_graded_with_nonsense_reads_as_unknown(self):
        lexicon = ErrataLexicon.from_mapping({"rules": {RULE_SPEC_SYMBOL: "definitely"}})
        assert lexicon.grade(RULE_SPEC_SYMBOL) == Confidence.UNKNOWN

    def test_the_registry_file_declares_no_similarity_threshold(self):
        """The one knob that could turn a coincidence into a link must not exist."""
        from datasheet_analyzer.errata.lexicon import LEXICON_PATH

        text = LEXICON_PATH.read_text(encoding="utf-8").lower()
        for forbidden in ("similarity", "threshold", "fuzzy", "ratio", "distance"):
            assert f"\n{forbidden}" not in text
            assert f"{forbidden}:" not in text


# --- segmentation -------------------------------------------------------------


class TestSegmentation:
    def test_the_marker_rule_starts_an_item_and_keeps_every_line_after_it(self):
        raw = _errata_doc(
            "TESTPART Errata",
            "Advisory 1",
            "The first line of the first item.",
            "The second line of the first item.",
            "Advisory 2",
            "The only line of the second item.",
        )
        items = build_items([(ERRATA_DOC, raw)])

        assert [i.marker for i in items] == ["Advisory 1", "Advisory 2"]
        assert [i.id for i in items] == ["err_1", "err_2"]
        assert all(i.derivation == DERIVATION_MARKER for i in items)
        # Front matter before the first marker is the document's, not an item's.
        assert "TESTPART Errata" not in items[0].text
        assert items[0].text.count("\n") == 2

    def test_the_ordinal_rule_fires_only_when_no_marker_word_appears(self):
        raw = _errata_doc(
            "1. The first numbered item.",
            "2. The second numbered item.",
        )
        items = build_items([(ERRATA_DOC, raw)])
        assert [i.marker for i in items] == ["1.", "2."]
        assert all(i.derivation == DERIVATION_ORDINAL for i in items)

    def test_the_section_floor_loses_nothing(self):
        """A document nothing else could segment still publishes every line."""
        raw = _errata_doc(
            "This device has a known problem with its supply sequencing.",
            "Contact the factory.",
        )
        items = build_items([(ERRATA_DOC, raw)])

        assert len(items) == 1
        assert items[0].derivation == DERIVATION_SECTION
        assert "supply sequencing" in items[0].text
        assert "Contact the factory." in items[0].text

    def test_ids_run_straight_through_two_errata_documents(self):
        first = _errata_doc("Advisory 1", "one")
        second = _errata_doc("Advisory 1", "two")
        second.source.content_hash = "ff" + "0" * 62
        items = build_items([("errata-aaaa", first), ("errata-bbbb", second)])
        assert [i.id for i in items] == ["err_1", "err_2"]
        assert [i.doc for i in items] == ["errata-aaaa", "errata-bbbb"]

    def test_the_page_is_a_range_never_an_invented_point(self):
        raw = _errata_doc("Advisory 1", "line", page=3)
        raw.sections[0].page_end = 5
        items = build_items([(ERRATA_DOC, raw)])
        assert items[0].pages == "p.3-5"

    def test_is_errata_reads_the_registered_type(self):
        assert is_errata(_errata_doc("Advisory 1", "x"))
        other = _errata_doc("Advisory 1", "x")
        other.source.doc_type = DocType.DATASHEET
        assert not is_errata(other)


# --- the eight matching rules -------------------------------------------------


class TestMatchingRules:
    def test_a_cued_section_number_links_the_section_file(self):
        target = _target(sections=(_section("6.1", "Absolute Maximum Ratings"),))
        link_set = _link_one("Section 6.1 states the wrong limit.", target)

        assert len(link_set.links) == 1
        found = link_set.links[0].targets
        assert len(found) == 1
        assert found[0].kind == ErrataTargetKind.SECTION
        assert found[0].id == f"{BASE}/sections/6.1.md"
        assert found[0].rule == RULE_SECTION_NUMBER
        assert found[0].matched_on == 'section number "6.1" (cued by "Section")'
        assert found[0].confidence == Confidence.HIGH

    def test_the_section_glyph_is_a_cue(self):
        target = _target(sections=(_section("7.3.2", "Latch-up Prevention", page=7),))
        link_set = _link_one("The behaviour in \u00a77.3.2 is not guaranteed.", target)
        assert link_set.links[0].targets[0].section == "7.3.2"

    def test_an_uncued_number_links_nothing(self):
        """A bare `6.1` in errata prose is a supply voltage far more often."""
        target = _target(sections=(_section("6.1", "Absolute Maximum Ratings"),))
        link_set = _link_one("The rail may reach 6.1 V under load.", target)

        assert link_set.links == []
        assert len(link_set.unlinked) == 1

    def test_a_printed_table_caption_links_its_section(self):
        table = TableBlock(caption="Thermal Information", headers=["a"], grid=[["1"]], page=6)
        target = _target(sections=(_section("4.4", "Thermal", page=6, tables=[table]),))
        link_set = _link_one("The Thermal Information table is wrong.", target)

        found = link_set.links[0].targets
        assert found[0].rule == RULE_TABLE_CAPTION
        assert found[0].matched_on == 'table caption "Thermal Information"'
        assert found[0].confidence == Confidence.MEDIUM

    def test_a_short_caption_is_below_the_lexicon_floor(self):
        table = TableBlock(caption="Notes", headers=["a"], grid=[["1"]], page=6)
        target = _target(sections=(_section("4.4", "Thermal", page=6, tables=[table]),))
        link_set = _link_one("See the Notes for details.", target)
        assert link_set.links == []

    def test_a_printed_symbol_links_every_row_that_prints_it(self):
        target = _target(specs=(_spec(0, symbol="VDD1P8"), _spec(1, symbol="TA")))
        link_set = _link_one("VDD1P8 is misprinted in this revision.", target)

        found = link_set.links[0].targets
        assert len(found) == 1
        assert found[0].kind == ErrataTargetKind.SPEC
        assert found[0].rule == RULE_SPEC_SYMBOL
        assert found[0].matched_on == 'spec symbol "VDD1P8"'
        assert found[0].id.endswith("specs.json#rec_s4_1-t0-r0")
        assert found[0].id.startswith(BASE)

    def test_a_symbol_match_is_case_sensitive_and_whole_token(self):
        target = _target(specs=(_spec(0, symbol="VDD1P8"),))
        assert _link_one("vdd1p8 is misprinted.", target).links == []
        assert _link_one("XVDD1P8Y is misprinted.", target).links == []

    def test_an_alias_phrase_reaches_a_row_whose_symbol_is_prose(self):
        """The lexicon vouches for the phrase at both ends - `medium`, and said so."""
        target = _target(specs=(_spec(0, symbol="", name="Junction temperature"),))
        link_set = _link_one("the junction temperature limit is incorrect", target)

        found = link_set.links[0].targets
        assert found[0].rule == RULE_ALIAS_PHRASE
        assert found[0].matched_on == 'alias phrase "junction temperature" -> TJ'
        assert found[0].confidence == Confidence.MEDIUM

    def test_a_printed_pin_name_links_its_pin(self):
        target = _target(pins=(_pin(0, "A1", "VSSA"), _pin(1, "B2", "CLK1")))
        link_set = _link_one("VSSA is bonded incorrectly on some units.", target)

        found = link_set.links[0].targets
        assert found[0].kind == ErrataTargetKind.PIN
        assert found[0].rule == RULE_PIN_NAME
        assert found[0].label == "A1 VSSA"
        assert found[0].id.endswith("pins.json#pin_t0-r0-A1")

    def test_a_pin_designator_must_be_cued(self):
        target = _target(pins=(_pin(0, "A1", "VSSA"),))
        assert _link_one("ball A1 is bonded incorrectly.", target).links
        # Uncued `A1` is a package variant, a note marker, a hundred things.
        assert _link_one("Variant A1 ships in Q3.", target).links == []

    def test_a_register_name_links_its_register(self):
        target = _target(registers=(_register(0, "0x1A04", 6660, "TXDIG_CTRL0"),))
        link_set = _link_one("TXDIG_CTRL0 powers up in the wrong state.", target)

        found = link_set.links[0].targets
        assert found[0].kind == ErrataTargetKind.REGISTER
        assert found[0].rule == RULE_REGISTER_NAME
        assert found[0].id.endswith("registers.json#reg_dd0-t0-r0")

    def test_a_register_address_is_compared_as_an_integer(self):
        target = _target(registers=(_register(0, "0x1A04", 6660, "CTRL"),))
        link_set = _link_one("Register 0x1a04 resets to the wrong value.", target)

        found = link_set.links[0].targets
        assert found[0].rule == RULE_REGISTER_ADDRESS
        assert found[0].matched_on == 'register address "0x1a04"'

    def test_an_unparsed_address_is_honestly_unreachable(self):
        """No integer was published, so no string comparison stands in for one."""
        target = _target(registers=(_register(0, "0x1A04", None, "CTRL"),))
        link_set = _link_one("Register 0x1A04 resets to the wrong value.", target)
        assert link_set.links == []


# --- the refusals that are load-bearing ---------------------------------------


class TestRefusals:
    def test_a_symbol_that_is_an_ordinary_word_cannot_link(self):
        """Measured: the layout floor records `Supply` in the *symbol* column."""
        target = _target(
            specs=(
                _spec(0, symbol="Supply", name="Supply voltage range"),
                _spec(1, symbol="Input", name="Input voltage"),
                _spec(2, symbol="Large", name="Large signal response"),
            )
        )
        text = "Supply and Input behaviour is Large under load."
        assert _link_one(text, target).links == []

    def test_a_symbol_with_a_digit_a_second_capital_or_a_greek_letter_links(self):
        for symbol in ("TJ", "IVDD1P8", "R\u03b8JA"):
            target = _target(specs=(_spec(0, symbol=symbol),))
            link_set = _link_one(f"{symbol} is misprinted.", target)
            assert link_set.links, symbol
            assert link_set.links[0].targets[0].rule == RULE_SPEC_SYMBOL

    def test_a_record_published_without_an_id_yields_an_empty_reference(self):
        """Honestly unaddressable beats a reference pointed at a neighbouring row."""
        target = _target(pins=(_pin(0, "", "VSSA"),))
        link_set = _link_one("VSSA is bonded incorrectly.", target)

        found = link_set.links[0].targets[0]
        assert found.label == "VSSA"
        assert found.id.endswith("-r0-")  # the designator half is empty, not invented

    def test_an_errata_document_is_never_its_own_target(self):
        """The caller assembles the target surface; this asserts it stays out."""
        target = _target(sections=(_section("1", "Page 1", page=1),))
        link_set = _link_one("Section 1 is wrong.", target)
        for link in link_set.links:
            for found in link.targets:
                assert found.doc != ERRATA_DOC


class TestNoFuzzyMatching:
    def test_the_package_names_no_similarity_machinery(self):
        """A source guard, because the failure mode is a link that *looks* right."""
        package = Path("src/datasheet_analyzer/errata")
        forbidden = (
            "difflib",
            "SequenceMatcher",
            "similarity(",
            "get_close_matches",
            "nearest_names",
            "fuzz",
            "token_overlap",
        )
        for path in sorted(package.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                assert needle not in text, f"{path.name} names {needle}"

    def test_prose_that_paraphrases_a_section_title_links_nothing(self):
        """Resemblance between an erratum and a datasheet is the null hypothesis."""
        target = _target(
            sections=(_section("6.1", "Absolute Maximum Ratings"),),
            specs=(_spec(0, symbol="", name="Junction temperature"),),
        )
        text = "The absolute maximum ratings of this device are being restated."
        link_set = _link_one(text, target)
        assert link_set.links == []
        assert len(link_set.unlinked) == 1


class TestNothingIsLost:
    def test_the_count_is_the_sum_of_two_named_lists(self):
        raw = _errata_doc(
            "Advisory 1",
            "Section 6.1 is wrong.",
            "Advisory 2",
            "Something uncharacterized happens.",
            "Advisory 3",
            "Contact the factory.",
        )
        items = build_items([(ERRATA_DOC, raw)])
        target = _target(sections=(_section("6.1", "Absolute Maximum Ratings"),))
        link_set = build_errata_links("TESTPART", items, [target], errata_docs=[ERRATA_DOC])

        assert link_set.n_items == 3
        assert link_set.n_items == len(link_set.links) + len(link_set.unlinked)
        assert len(link_set.links) == 1 and len(link_set.unlinked) == 2
        assert [i.item.id for i in link_set.all_items()] == ["err_1", "err_2", "err_3"]

    def test_the_unlinked_population_is_stated_on_the_set(self):
        raw = _errata_doc("Advisory 1", "Something uncharacterized happens.")
        link_set = build_errata_links(
            "TESTPART",
            build_items([(ERRATA_DOC, raw)]),
            [_target()],
            errata_docs=[ERRATA_DOC],
        )
        assert any("could not be placed" in note for note in link_set.notes)

    def test_an_errata_document_that_yielded_nothing_says_which_empty_it_is(self):
        link_set = build_errata_links("TESTPART", [], [_target()], errata_docs=[ERRATA_DOC])
        assert link_set.n_items == 0
        assert "registers an errata document" in link_set.empty_reason
        assert "registry/errata.yaml" in link_set.empty_reason

    def test_a_rule_that_hit_the_cap_states_how_many_it_found(self):
        lexicon = ErrataLexicon.from_mapping(
            {
                "item_markers": ["advisory"],
                "max_targets_per_rule": 2,
                "rules": {RULE_SPEC_SYMBOL: "high"},
            }
        )
        target = _target(specs=tuple(_spec(i, symbol="VDD1P8") for i in range(5)))
        items = build_items(
            [(ERRATA_DOC, _errata_doc("Advisory 1", "VDD1P8 is wrong."))], lexicon=lexicon
        )
        link_set = build_errata_links(
            "TESTPART", items, [target], lexicon=lexicon, errata_docs=[ERRATA_DOC]
        )
        link = link_set.links[0]
        assert len(link.targets) == 2
        assert any("5 records" in note and "3 more are not" in note for note in link.notes)


# --- rendering ----------------------------------------------------------------


class TestRendering:
    def _set(self):
        raw = _errata_doc(
            "Advisory 1",
            "Section 6.1 states the wrong junction temperature.",
            "Advisory 2",
            "Something uncharacterized happens.",
        )
        target = _target(sections=(_section("6.1", "Absolute Maximum Ratings"),))
        return build_errata_links(
            "TESTPART",
            build_items([(ERRATA_DOC, raw)]),
            [target],
            errata_docs=[ERRATA_DOC],
        )

    def test_the_report_opens_with_an_arithmetic_a_reader_can_check(self):
        text = render_errata(self._set())
        assert "2 errata item(s)" in text
        assert "1 linked to a published record, 1 unlinked" in text

    def test_unplaced_items_are_published_under_the_constant_heading(self):
        text = render_errata(self._set())
        assert UNLINKED_HEADING in text
        head, _, tail = text.partition(UNLINKED_HEADING)
        assert "Something uncharacterized happens." in tail
        assert "Something uncharacterized happens." not in head
        assert "nothing here has been dropped" in tail

    def test_every_target_row_says_what_it_matched_on(self):
        text = render_errata(self._set())
        assert 'section number "6.1" (cued by "Section")' in text
        assert "| section |" in text

    def test_a_pack_warning_is_one_line_and_cites_the_item(self):
        link = self._set().links[0]
        note = pack_warning(link)
        assert note.startswith("\u26a0 errata err_1 (p.1):")
        assert "\n" not in note
        assert "Section 6.1" in note

    def test_a_banner_goes_under_the_source_comment_and_above_the_prose(self):
        link_set = self._set()
        target = _target(sections=(_section("6.1", "Absolute Maximum Ratings"),))
        banners = sections_to_banner(link_set, [target])
        file = f"{BASE}/sections/6.1.md"
        assert set(banners) == {file}

        markdown = "# 6.1 Absolute Maximum Ratings\n\n<!-- source: x p.4 -->\n\nBody.\n"
        out = insert_banner(
            markdown, section_banner(list(banners[file].links), banners[file].targets)
        )
        lines = out.split("\n")
        assert lines[0].startswith("# 6.1")
        assert lines[2].startswith("<!-- source:")
        assert "\u26a0 Errata" in lines[4]
        assert "matched on" in out
        assert out.index("Errata") < out.index("Body.")

    def test_a_section_no_erratum_named_gets_no_banner(self):
        link_set = self._set()
        target = _target(
            sections=(_section("6.1", "Absolute Maximum Ratings"), _section("7", "Layout"))
        )
        banners = sections_to_banner(link_set, [target])
        assert f"{BASE}/sections/7.md" not in banners

    def test_a_spec_target_banners_the_section_that_printed_it(self):
        """An erratum correcting one row has to warn whoever opens that table."""
        target = _target(
            sections=(_section("4.1", "Absolute Maximum Ratings"),),
            specs=(_spec(0, symbol="VDD1P8", section="4.1"),),
        )
        link_set = _link_one("VDD1P8 is misprinted.", target)
        banners = sections_to_banner(link_set, [target])
        assert f"{BASE}/sections/4.1.md" in banners

    def test_links_by_target_indexes_only_placed_items(self):
        index = links_by_target(self._set())
        assert set(index) == {f"{BASE}/sections/6.1.md"}
        assert [link.item.id for link in index[f"{BASE}/sections/6.1.md"]] == ["err_1"]


# --- publication --------------------------------------------------------------


def _datasheet(section_number: str = "4.1") -> RawDocument:
    return RawDocument(
        source=SourceDocument(
            content_hash="c0" + "0" * 62,
            path="datasheet.pdf",
            part_number="TESTPART",
            doc_type=DocType.DATASHEET,
            page_count=8,
        ),
        sections=[
            SectionNode(
                number=section_number,
                title="Absolute Maximum Ratings",
                page_start=4,
                page_end=4,
                paragraphs=["The absolute maximum ratings of this device."],
            )
        ],
        extractor="pdf_layout",
        extractor_version="test-1",
        extraction_stats=ExtractionStats(backend="pdf_layout"),
    )


@pytest.fixture
def errata_part(tmp_path, monkeypatch):
    """A part holding one datasheet and one errata document, published for real.

    Written by the real `write_corpus`, so the banner insertion, the search
    index and the manifest counts are the ones a build produces.
    """
    from datasheet_analyzer.config import SPECS_SCHEMA_VERSION
    from datasheet_analyzer.models import SpecSet
    from datasheet_analyzer.publish import write_corpus
    from datasheet_analyzer.retrieve import clear_index_cache
    from datasheet_analyzer.structure.corpus import build_section_plans

    settings = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        library_dir=tmp_path / "library",
    ).resolve()
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    part_dir = settings.parts_dir / "TESTPART"

    datasheet = _datasheet()
    errata = _errata_doc(
        "Advisory 1",
        "Section 4.1: the VDD1P8 limit printed for this device is incorrect.",
        "Advisory 2",
        "Something uncharacterized happens under assembly stress.",
    )
    specset = SpecSet(
        schema_version=SPECS_SCHEMA_VERSION,
        part_number="TESTPART",
        doc_hash=datasheet.source.content_hash,
        records=[_spec(0, symbol="VDD1P8", name="Supply voltage")],
    )
    manifest = write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {}) for raw in (datasheet, errata)],
        "# TESTPART\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        specsets=[specset],
        shared_docs_dir=None,
    )
    clear_index_cache()
    return part_dir, settings, manifest


class TestPublication:
    def test_both_files_are_written_and_the_counts_are_stamped(self, errata_part):
        part_dir, _settings, manifest = errata_part
        assert (part_dir / ERRATA_LINKS_FILENAME).is_file()
        assert (part_dir / ERRATA_MARKDOWN_FILENAME).is_file()

        payload = json.loads((part_dir / ERRATA_LINKS_FILENAME).read_text(encoding="utf-8"))
        assert payload["schema_version"] == ERRATA_SCHEMA_VERSION
        assert manifest.stats.n_errata_items == 2
        assert manifest.stats.n_errata_linked == 1

    def test_the_banner_is_in_the_file_and_in_the_search_index(self, errata_part):
        """What is searchable is exactly what is readable, erratum included."""
        part_dir, _settings, manifest = errata_part
        section = next(s for s in manifest.sections if s.number == "4.1")
        text = (part_dir / section.file).read_text(encoding="utf-8")
        assert "\u26a0 Errata" in text
        assert "err_1" in text

        doc_dir = part_dir / section.file.split("/sections/")[0]
        index = json.loads((doc_dir / "search_index.json").read_text(encoding="utf-8"))
        assert "errata" in json.dumps(index).lower()
        # The manifest's token count is the bannered text's, not the plain one's.
        assert section.token_count > 0

    def test_the_errata_document_carries_no_banner(self, errata_part):
        part_dir, _settings, manifest = errata_part
        for section in manifest.sections:
            if "errata-" in section.file:
                body = (part_dir / section.file).read_text(encoding="utf-8")
                assert "\u26a0 Errata" not in body

    def test_a_part_with_no_errata_document_is_completely_unaffected(self, tmp_path, monkeypatch):
        from datasheet_analyzer.publish import write_corpus
        from datasheet_analyzer.structure.corpus import build_section_plans

        settings = Settings(
            parts_dir=tmp_path / "parts",
            cache_dir=tmp_path / ".cache",
            library_dir=tmp_path / "library",
        ).resolve()
        part_dir = settings.parts_dir / "PLAIN"
        raw = _datasheet()
        manifest = write_corpus(
            part_dir,
            [(raw, build_section_plans(raw), {})],
            "# PLAIN\n",
            pipeline_version=PIPELINE_VERSION,
            vendor="ti",
            shared_docs_dir=None,
        )
        assert not (part_dir / ERRATA_LINKS_FILENAME).exists()
        assert not (part_dir / ERRATA_MARKDOWN_FILENAME).exists()
        assert manifest.stats.n_errata_items == 0
        section = manifest.sections[0]
        assert "\u26a0 Errata" not in (part_dir / section.file).read_text(encoding="utf-8")

    def test_removing_the_errata_document_takes_both_files_with_it(self, errata_part):
        """An empty errata file would read as "no known issues"."""
        from datasheet_analyzer.publish import write_corpus
        from datasheet_analyzer.structure.corpus import build_section_plans

        part_dir, _settings, _manifest = errata_part
        raw = _datasheet()
        write_corpus(
            part_dir,
            [(raw, build_section_plans(raw), {})],
            "# TESTPART\n",
            pipeline_version=PIPELINE_VERSION,
            vendor="ti",
            shared_docs_dir=None,
        )
        assert not (part_dir / ERRATA_LINKS_FILENAME).exists()
        assert not (part_dir / ERRATA_MARKDOWN_FILENAME).exists()

    def test_only_records_the_build_writes_are_targetable(self, tmp_path):
        """A link into a `pins.json` the build declines to write resolves to nothing."""
        from datasheet_analyzer.publish import write_corpus
        from datasheet_analyzer.structure.corpus import build_section_plans

        part_dir = tmp_path / "parts" / "NOPINS"
        datasheet = _datasheet()
        errata = _errata_doc("Advisory 1", "VSSA is bonded incorrectly on some units.")
        write_corpus(
            part_dir,
            [(raw, build_section_plans(raw), {}) for raw in (datasheet, errata)],
            "# NOPINS\n",
            pipeline_version=PIPELINE_VERSION,
            vendor="ti",
            # No pinsets: the build publishes no `pins.json`, so nothing may
            # point into one.
            shared_docs_dir=None,
        )
        payload = json.loads((part_dir / ERRATA_LINKS_FILENAME).read_text(encoding="utf-8"))
        assert payload["links"] == []
        assert len(payload["unlinked"]) == 1


class TestBatchGate:
    def test_a_part_that_registers_errata_and_published_none_is_stale(self, errata_part):
        from datasheet_analyzer.publish import errata_current

        part_dir, _settings, manifest = errata_part
        assert errata_current(part_dir, manifest) is True
        (part_dir / ERRATA_LINKS_FILENAME).unlink()
        assert errata_current(part_dir, manifest) is False

    def test_a_part_with_no_errata_document_and_no_file_is_current(self, errata_part):
        from datasheet_analyzer.models import CorpusManifest
        from datasheet_analyzer.publish import errata_current

        part_dir, _settings, _manifest = errata_part
        (part_dir / ERRATA_LINKS_FILENAME).unlink()
        assert errata_current(part_dir, CorpusManifest(part_number="TESTPART")) is True

    def test_an_older_schema_version_is_stale(self, errata_part):
        from datasheet_analyzer.publish import errata_current

        part_dir, _settings, manifest = errata_part
        path = part_dir / ERRATA_LINKS_FILENAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema_version"] = "0"
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert errata_current(part_dir, manifest) is False


class TestAnswerPackCarriesTheWarning:
    def test_the_warning_rides_on_the_row_that_quotes_the_record(self, errata_part):
        from datasheet_analyzer.retrieve import Retriever, build_pack

        part_dir, _settings, _manifest = errata_part
        pack = build_pack(Retriever.for_part(part_dir), "what is the VDD1P8 supply voltage?")

        assert any(line.errata for line in pack.answers), pack.markdown
        line = next(line for line in pack.answers if line.errata)
        assert line.source.endswith("specs.json#rec_s4_1-t0-r0")
        assert "\u26a0 errata err_1" in line.errata[0]
        assert "\u26a0 errata err_1" in pack.markdown
        assert "errata" in json.dumps(pack.as_dict())

    def test_the_declared_shape_still_validates(self, errata_part):
        from datasheet_analyzer.retrieve import Retriever, build_pack, validate_pack

        part_dir, _settings, _manifest = errata_part
        pack = build_pack(Retriever.for_part(part_dir), "what is the VDD1P8 supply voltage?")
        assert validate_pack(pack.as_dict()) == []

    def test_a_part_with_no_errata_produces_the_pack_it_always_did(self, tmp_path):
        from datasheet_analyzer.config import SPECS_SCHEMA_VERSION
        from datasheet_analyzer.models import SpecSet
        from datasheet_analyzer.publish import write_corpus
        from datasheet_analyzer.retrieve import Retriever, build_pack, clear_index_cache
        from datasheet_analyzer.structure.corpus import build_section_plans

        part_dir = tmp_path / "parts" / "PLAIN2"
        raw = _datasheet()
        write_corpus(
            part_dir,
            [(raw, build_section_plans(raw), {})],
            "# PLAIN2\n",
            pipeline_version=PIPELINE_VERSION,
            vendor="ti",
            specsets=[
                SpecSet(
                    schema_version=SPECS_SCHEMA_VERSION,
                    part_number="PLAIN2",
                    doc_hash=raw.source.content_hash,
                    records=[_spec(0, symbol="VDD1P8", name="Supply voltage")],
                )
            ],
            shared_docs_dir=None,
        )
        clear_index_cache()
        pack = build_pack(Retriever.for_part(part_dir), "what is the VDD1P8 supply voltage?")
        assert all(line.errata == () for line in pack.answers)
        assert "\u26a0 errata" not in pack.markdown
