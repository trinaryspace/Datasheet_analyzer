"""Errata cross-linking (phase 7, ticket 04) — rule by rule.

The gate (`tests/integration/test_phase7_errata.py`) proves the whole path on the
real LM741 datasheet. What is proven here is each rule on its own, and — the
point of a rule test — that each one *refuses* for the right reason:

- a section number links only when the item **cues** it, so a bare `6.1` in
  errata prose (a supply voltage far more often than a section) links nothing;
- a spec symbol links only when it reads like a symbol, so the layout floor's
  `Supply` / `Input` pseudo-symbols cannot link an erratum on an English word,
  while `TJ` and `IVDD1P8` can;
- an alias phrase links through `registry/aliases.yaml` at **both** ends, which
  is what reaches a row whose printed symbol is `Junction temperature`;
- a pin designator is cued like a section number, a register address is compared
  as an integer, and a register whose address the grammar could not read is
  honestly unreachable;
- **no rule uses prose similarity** — asserted twice: as a source-level guard
  over the package, and behaviourally, on an item that reads like a section title
  and names no identifier;
- every item is published, and an item nothing matched lands under the
  "unlinked errata" heading with its verbatim text intact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.config import ERRATA_SCHEMA_VERSION, PIPELINE_VERSION
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
from datasheet_analyzer.errata.link import _is_identifier
from datasheet_analyzer.errata.render import BANNER_MARKER
from datasheet_analyzer.models import (
    Confidence,
    CorpusManifest,
    DocType,
    ErrataLinkSet,
    PinRecord,
    PinType,
    RawDocument,
    RegisterRecord,
    RegisterWord,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecUnit,
    TableBlock,
)
from datasheet_analyzer.publish.writer import errata_current, write_errata

DOC = "datasheet-aabbccdd"


# --- fixtures ----------------------------------------------------------------


def _errata_doc(lines: list[list[str]], *, doc_type: str = "errata") -> RawDocument:
    """A `pdf_text`-shaped errata document: one section per page, one line each."""
    sections = [
        SectionNode(
            number=str(i + 1),
            title=f"Page {i + 1}",
            page_start=i + 1,
            page_end=i + 1,
            paragraphs=list(page),
        )
        for i, page in enumerate(lines)
    ]
    return RawDocument(
        source=SourceDocument(
            path="errata.pdf",
            content_hash="e" * 64,
            doc_type=DocType(doc_type),
            page_count=len(lines),
        ),
        sections=sections,
        extractor="pdf_text",
    )


def _spec(
    rec_id: str, symbol: str, name: str = "", section: str = "6.1", page: int = 4
) -> SpecRecord:
    return SpecRecord(
        id=rec_id, symbol=symbol, name=name, section=section, page=page,
        max="125", unit=SpecUnit(verbatim="°C", canonical="°C"),
        confidence=Confidence.HIGH,
    )


def _target_doc(
    *,
    sections: tuple[tuple[SectionNode, str], ...] = (),
    specs: tuple[SpecRecord, ...] = (),
    pins: tuple[PinRecord, ...] = (),
    registers: tuple[RegisterRecord, ...] = (),
) -> TargetDoc:
    return TargetDoc(
        name=DOC, doc_hash="a" * 64, sections=sections, specs=specs,
        pins=pins, registers=registers,
    )


def _section(number: str, title: str, page: int = 4, tables=()) -> SectionNode:
    return SectionNode(
        number=number, title=title, page_start=page, page_end=page,
        tables=list(tables),
    )


def _link(text: str, targets: TargetDoc | None = None, **kwargs):
    """One item's link, built the way the publisher builds it."""
    items = build_items([(DOC, _errata_doc([["Advisory 1", text]]))])
    return build_errata_links(
        "P1", items, [targets] if targets else [], **kwargs
    ).all_items()[0]


# --- the lexicon -------------------------------------------------------------


class TestLexicon:
    def test_shipped_lexicon_grades_every_named_rule(self):
        lex = load_errata_lexicon()
        for rule in RULES:
            assert lex.grade(rule) in (
                Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW
            ), rule

    def test_an_ungraded_rule_is_unknown_not_high(self):
        lex = ErrataLexicon(rules=())
        assert lex.grade("section-number") == Confidence.UNKNOWN

    def test_longest_marker_wins(self):
        lex = ErrataLexicon(item_markers=("item", "errata item"))
        assert lex.marker_start("Errata item 4: the thing") == "Errata item 4"

    def test_a_marker_word_without_an_identifier_is_prose(self):
        lex = load_errata_lexicon()
        assert lex.marker_start("Item numbers are listed below") == ""

    def test_an_unreadable_lexicon_degrades_to_linking_nothing(self, tmp_path):
        """Honest degradation: every item still publishes, unlinked."""
        missing = tmp_path / "nope.yaml"
        lex = ErrataLexicon.read(missing)
        assert lex.item_markers == ()
        doc = _errata_doc([["Advisory 1", "Section 6.1 is wrong."]])
        items = build_items([(DOC, doc)], lexicon=lex)
        link_set = build_errata_links(
            "P1", items, [_target_doc()], lexicon=lex
        )
        assert link_set.n_items == 1
        assert link_set.unlinked and not link_set.links


# --- segmentation ------------------------------------------------------------


class TestItemSegmentation:
    def test_marker_rule_splits_on_printed_markers(self):
        doc = _errata_doc(
            [["Advisory 1", "first line", "second line", "Advisory 2", "other"]]
        )
        items = build_items([(DOC, doc)])
        assert [i.marker for i in items] == ["Advisory 1", "Advisory 2"]
        assert items[0].text == "Advisory 1\nfirst line\nsecond line"
        assert all(i.derivation == DERIVATION_MARKER for i in items)

    def test_front_matter_before_the_first_marker_is_not_an_item(self):
        doc = _errata_doc([["ACME Errata Sheet", "Advisory 1", "body"]])
        items = build_items([(DOC, doc)])
        assert len(items) == 1
        assert items[0].text.startswith("Advisory 1")

    def test_an_item_may_span_pages_and_keeps_the_range(self):
        doc = _errata_doc([["Advisory 1", "starts here"], ["and ends here"]])
        items = build_items([(DOC, doc)])
        assert len(items) == 1
        assert (items[0].page, items[0].page_end) == (1, 2)
        assert items[0].pages == "p.1-2"

    def test_ordinal_rule_is_the_fallback_not_the_default(self):
        doc = _errata_doc([["1. first issue", "detail", "2. second issue"]])
        items = build_items([(DOC, doc)])
        assert [i.marker for i in items] == ["1.", "2."]
        assert all(i.derivation == DERIVATION_ORDINAL for i in items)

    def test_a_document_with_no_marker_at_all_still_publishes_every_line(self):
        doc = _errata_doc([["Something is wrong."], ["Something else is wrong."]])
        items = build_items([(DOC, doc)])
        assert len(items) == 2
        assert all(i.derivation == DERIVATION_SECTION for i in items)
        assert items[1].text == "Something else is wrong."

    def test_ids_are_minted_across_the_part_not_per_document(self):
        a = _errata_doc([["Advisory 1", "a"]])
        b = _errata_doc([["Advisory 2", "b"]])
        items = build_items([("errata-1", a), ("errata-2", b)])
        assert [i.id for i in items] == ["err_1", "err_2"]
        assert [i.doc for i in items] == ["errata-1", "errata-2"]

    def test_is_errata_only_claims_errata_documents(self):
        assert is_errata(_errata_doc([["x"]]))
        assert not is_errata(_errata_doc([["x"]], doc_type="datasheet"))


# --- the matching rules ------------------------------------------------------


class TestSectionNumberRule:
    def targets(self):
        return _target_doc(
            sections=(
                (_section("6.1", "Absolute Maximum Ratings"), "docs/d/sections/6-1.md"),
                (_section("7.3.2", "Latch-up Prevention", page=7), "docs/d/s/7-3-2.md"),
            )
        )

    def test_a_cued_number_links(self):
        link = _link("Section 6.1 states the wrong limit.", self.targets())
        assert [t.id for t in link.targets] == ["docs/d/sections/6-1.md"]
        assert link.targets[0].matched_on == (
            'section number "6.1" (cued by "Section")'
        )
        assert link.targets[0].confidence == Confidence.HIGH

    def test_the_section_sign_is_a_cue(self):
        link = _link("The behaviour in §7.3.2 is not guaranteed.", self.targets())
        assert [t.id for t in link.targets] == ["docs/d/s/7-3-2.md"]

    def test_an_uncued_number_links_nothing(self):
        """`6.1` in errata prose is a voltage far more often than a section."""
        link = _link("The rail may sag to 6.1 V under load.", self.targets())
        assert link.targets == []

    def test_a_number_the_document_does_not_print_links_nothing(self):
        link = _link("See Section 9.9 of the datasheet.", self.targets())
        assert link.targets == []


class TestTableCaptionRule:
    def targets(self):
        table = TableBlock(caption="Recommended Operating Conditions")
        short = TableBlock(caption="Notes")
        return _target_doc(
            sections=(
                (_section("6.3", "Specifications", tables=[table]), "docs/d/6-3.md"),
                (_section("6.9", "Other", tables=[short]), "docs/d/6-9.md"),
            )
        )

    def test_a_quoted_caption_links_its_section(self):
        link = _link(
            "The Recommended Operating Conditions table understates VIN.",
            self.targets(),
        )
        assert [t.id for t in link.targets] == ["docs/d/6-3.md"]
        assert "table caption" in link.targets[0].matched_on
        assert link.targets[0].confidence == Confidence.MEDIUM

    def test_a_short_caption_is_below_the_threshold(self):
        link = _link("See the Notes for details.", self.targets())
        assert link.targets == []


class TestSpecSymbolRule:
    def targets(self):
        return _target_doc(
            specs=(
                _spec("rec_1", "TJ", "Operating junction temperature"),
                _spec("rec_2", "IVDD1P8", "Supply current"),
                _spec("rec_3", "Supply", "voltage"),
                _spec("rec_4", "Input", ""),
            )
        )

    def test_a_printed_symbol_links_its_row(self):
        link = _link("The stated TJ rating is optimistic.", self.targets())
        assert [t.id for t in link.targets] == [f"docs/{DOC}/specs.json#rec_1"]
        assert link.targets[0].matched_on == 'spec symbol "TJ"'

    def test_a_prose_pseudo_symbol_never_links(self):
        """`Supply` and `Input` are what the layout floor records for datasheets
        that print no symbol column; matching them would link on a word."""
        link = _link(
            "The Supply and Input behaviour changes above 70 degrees.",
            self.targets(),
        )
        assert link.targets == []

    def test_case_matters(self):
        link = _link("the tj of the part", self.targets())
        assert link.targets == []

    @pytest.mark.parametrize(
        "text,expected",
        [("TJ", True), ("IVDD1P8", True), ("RθJA", True), ("Supply", False),
         ("Input", False), ("V", False), ("Vc", False)],
    )
    def test_identifier_shape(self, text, expected):
        assert _is_identifier(text, 2) is expected


class TestAliasPhraseRule:
    def targets(self):
        # The printed "symbol" is prose — the layout floor's shape — so only the
        # alias lexicon can reach it.
        return _target_doc(specs=(_spec("rec_9", "Junction temperature"),))

    def test_a_designers_phrase_reaches_a_prose_symbol(self):
        link = _link(
            "The junction temperature limit must be derated.", self.targets()
        )
        assert [t.id for t in link.targets] == [f"docs/{DOC}/specs.json#rec_9"]
        assert link.targets[0].matched_on.startswith('alias phrase "junction')
        assert link.targets[0].matched_on.endswith("-> TJ")
        assert link.targets[0].confidence == Confidence.MEDIUM

    def test_a_phrase_the_lexicon_does_not_declare_links_nothing(self):
        link = _link("The general vibe of the part is poor.", self.targets())
        assert link.targets == []


class TestPinRules:
    def targets(self):
        return _target_doc(
            pins=(
                PinRecord(id="pin_1", pin="A1", name="VSSA", type=PinType.GROUND,
                          section="5", page=3),
                PinRecord(id="pin_2", pin="A2", name="VDD1P8", type=PinType.POWER,
                          section="5", page=3),
            )
        )

    def test_a_printed_pin_name_links_its_record(self):
        link = _link("VDD1P8 must be sequenced first.", self.targets())
        assert [t.id for t in link.targets] == [f"docs/{DOC}/pins.json#pin_2"]
        assert link.targets[0].matched_on == 'pin name "VDD1P8"'

    def test_a_designator_links_only_when_cued(self):
        cued = _link("Ball A1 is misprinted in the pinout.", self.targets())
        assert [t.id for t in cued.targets] == [f"docs/{DOC}/pins.json#pin_1"]
        assert 'cued by "Ball"' in cued.targets[0].matched_on
        bare = _link("Revision A1 of the board is affected.", self.targets())
        assert bare.targets == []


class TestRegisterRules:
    def targets(self):
        return _target_doc(
            registers=(
                RegisterRecord(
                    id="reg_1", name="CLK_MUX", section="8", page=12,
                    address=RegisterWord(verbatim="0x19", value=0x19),
                ),
                RegisterRecord(
                    id="reg_2", name="ODD", section="8", page=12,
                    address=RegisterWord(verbatim="0x1A?", value=None),
                ),
            )
        )

    def test_a_register_name_links_its_record(self):
        link = _link("CLK_MUX resets to the wrong value.", self.targets())
        assert [t.id for t in link.targets] == [f"docs/{DOC}/registers.json#reg_1"]
        assert link.targets[0].matched_on == 'register name "CLK_MUX"'

    def test_an_address_is_compared_as_an_integer(self):
        link = _link("Register 0X019 is documented incorrectly.", self.targets())
        assert [t.id for t in link.targets] == [f"docs/{DOC}/registers.json#reg_1"]
        assert link.targets[0].matched_on == 'register address "0X019"'

    def test_an_unparsed_address_is_unreachable_rather_than_string_matched(self):
        link = _link("Register 0x1A is documented incorrectly.", self.targets())
        assert link.targets == []


class TestNoFuzzyMatching:
    """The rule that must never be relaxed: only structured identifiers."""

    def test_the_package_imports_no_similarity_machinery(self):
        package = Path(__file__).parent.parent.parent / "src" / "datasheet_analyzer" / "errata"
        banned = ("difflib", "SequenceMatcher", "similarity(", "get_close_matches",
                  "nearest_names", "fuzz")
        for path in sorted(package.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            body = "\n".join(
                line for line in source.splitlines() if not line.strip().startswith("#")
            )
            for needle in banned:
                assert needle not in body, f"{path.name} reaches for {needle}"

    def test_prose_that_merely_resembles_a_section_links_nothing(self):
        targets = _target_doc(
            sections=(
                (_section("6.1", "Absolute Maximum Ratings"), "docs/d/6-1.md"),
            ),
            specs=(_spec("rec_1", "TJ"),),
        )
        link = _link(
            "The absolute maximum ratings of this device are optimistic and "
            "the maximum operating limits should be treated with care.",
            targets,
        )
        assert link.targets == []


class TestTargetCap:
    def test_an_overflowing_rule_states_how_many_it_found(self):
        specs = tuple(_spec(f"rec_{i}", "TJ") for i in range(1, 40))
        lex = ErrataLexicon(
            item_markers=("advisory",), section_cues=("section",),
            max_targets_per_rule=5, rules=(("spec-symbol", "high"),),
        )
        link = _link("TJ is wrong.", _target_doc(specs=specs), lexicon=lex)
        assert len(link.targets) == 5
        assert any("39" in note and "5 are listed" in note for note in link.notes)


# --- publication: nothing is ever lost ---------------------------------------


class TestNothingIsLost:
    def test_linked_and_unlinked_sum_to_every_item(self):
        doc = _errata_doc(
            [["Advisory 1", "Section 6.1 is wrong.", "Advisory 2", "Vibes are off."]]
        )
        targets = _target_doc(
            sections=((_section("6.1", "Absolute Maximum Ratings"), "docs/d/6-1.md"),)
        )
        link_set = build_errata_links("P1", build_items([(DOC, doc)]), [targets])
        assert link_set.n_items == 2
        assert len(link_set.links) == 1 and len(link_set.unlinked) == 1
        assert link_set.n_items == len(link_set.all_items())

    def test_the_unlinked_heading_is_always_rendered_when_there_is_one(self):
        doc = _errata_doc([["Advisory 1", "Vibes are off."]])
        link_set = build_errata_links("P1", build_items([(DOC, doc)]), [])
        markdown = render_errata(link_set)
        assert UNLINKED_HEADING in markdown
        assert "Vibes are off." in markdown.split(UNLINKED_HEADING, 1)[1]

    def test_a_part_with_no_target_document_still_publishes_its_items(self):
        doc = _errata_doc([["Advisory 1", "Section 6.1 is wrong."]])
        link_set = build_errata_links("P1", build_items([(DOC, doc)]), [])
        assert link_set.n_items == 1
        assert any("no document" in note for note in link_set.notes)

    def test_an_unreadable_errata_document_says_so_rather_than_writing_nothing(self):
        link_set = build_errata_links("P1", [], [], errata_docs=["errata-1"])
        assert link_set.n_items == 0
        assert link_set.empty_reason
        assert link_set.empty_reason in render_errata(link_set)


# --- banners and the pack warning --------------------------------------------


class TestBanners:
    def _set(self):
        doc = _errata_doc([["Advisory 1", "Section 6.1 is wrong."]])
        section = _section("6.1", "Absolute Maximum Ratings")
        targets = _target_doc(
            sections=((section, "docs/d/6-1.md"),),
            specs=(_spec("rec_9", "Junction temperature"),),
        )
        link_set = build_errata_links("P1", build_items([(DOC, doc)]), [targets])
        return link_set, targets

    def test_a_record_target_banners_the_section_that_printed_it(self):
        doc = _errata_doc([["Advisory 1", "The junction temperature is wrong."]])
        section = _section("6.1", "Absolute Maximum Ratings")
        targets = _target_doc(
            sections=((section, "docs/d/6-1.md"),),
            specs=(_spec("rec_9", "Junction temperature", section="6.1"),),
        )
        link_set = build_errata_links("P1", build_items([(DOC, doc)]), [targets])
        banners = sections_to_banner(link_set, [targets])
        assert set(banners) == {"docs/d/6-1.md"}

    def test_the_banner_names_the_item_and_what_it_matched_on(self):
        link_set, targets = self._set()
        banners = sections_to_banner(link_set, [targets])
        banner = banners["docs/d/6-1.md"]
        text = section_banner(list(banner.links), banner.targets)
        assert BANNER_MARKER in text
        assert "err_1" in text
        assert 'section number "6.1"' in text

    def test_insert_banner_sits_under_the_source_comment(self):
        markdown = "# 6.1 Title\n\n<!-- source: X p.4 -->\n\nbody text\n"
        out = insert_banner(markdown, "> **⚠ Errata:** something")
        assert out.index("<!-- source:") < out.index("⚠ Errata")
        assert out.index("⚠ Errata") < out.index("body text")
        assert out.startswith("# 6.1 Title")

    def test_insert_banner_is_a_no_op_without_a_banner(self):
        markdown = "# T\n\n<!-- source: X -->\n\nbody\n"
        assert insert_banner(markdown, "") == markdown

    def test_pack_warning_names_the_item_its_page_and_quotes_it(self):
        link_set, _targets = self._set()
        warning = pack_warning(link_set.links[0])
        assert warning.startswith("⚠ errata err_1 (p.1):")
        assert "Section 6.1 is wrong." in warning

    def test_links_by_target_indexes_only_placed_items(self):
        link_set, _targets = self._set()
        index = links_by_target(link_set)
        assert "docs/d/6-1.md" in index
        assert all(links for links in index.values())


# --- the published files -----------------------------------------------------


class TestPublishedFiles:
    def _set(self):
        doc = _errata_doc([["Advisory 1", "Section 6.1 is wrong."]])
        return build_errata_links("P1", build_items([(DOC, doc)]), [])

    def test_write_errata_writes_both_forms(self, tmp_path):
        written = write_errata(tmp_path, self._set())
        assert [p.name for p in written] == [
            ERRATA_LINKS_FILENAME, ERRATA_MARKDOWN_FILENAME
        ]
        data = json.loads((tmp_path / ERRATA_LINKS_FILENAME).read_text(encoding="utf-8"))
        assert data["schema_version"] == ERRATA_SCHEMA_VERSION
        assert ErrataLinkSet.model_validate(data).n_items == 1

    def test_none_removes_a_file_an_earlier_build_left(self, tmp_path):
        write_errata(tmp_path, self._set())
        assert write_errata(tmp_path, None) == []
        assert not (tmp_path / ERRATA_LINKS_FILENAME).exists()
        assert not (tmp_path / ERRATA_MARKDOWN_FILENAME).exists()

    def test_errata_current_is_keyed_on_the_inventory(self, tmp_path):
        no_errata = CorpusManifest(part_number="P1", pipeline_version=PIPELINE_VERSION)
        with_errata = CorpusManifest(
            part_number="P1",
            pipeline_version=PIPELINE_VERSION,
            documents=[
                SourceDocument(
                    path="e.pdf", content_hash="e" * 64, doc_type=DocType.ERRATA
                )
            ],
        )
        # No errata document: the *absence* of the file is what is current.
        assert errata_current(tmp_path, no_errata)
        # An errata document with no published links is a corpus built before
        # this ticket — republish once.
        assert not errata_current(tmp_path, with_errata)
        write_errata(tmp_path, self._set())
        assert errata_current(tmp_path, with_errata)
        assert not errata_current(tmp_path, no_errata)

    def test_an_unreadable_link_file_reads_as_stale(self, tmp_path):
        (tmp_path / ERRATA_LINKS_FILENAME).write_text("{not json", encoding="utf-8")
        manifest = CorpusManifest(
            part_number="P1",
            pipeline_version=PIPELINE_VERSION,
            documents=[
                SourceDocument(
                    path="e.pdf", content_hash="e" * 64, doc_type=DocType.ERRATA
                )
            ],
        )
        assert not errata_current(tmp_path, manifest)
