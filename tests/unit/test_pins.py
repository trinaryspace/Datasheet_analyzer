"""Pins (phase 6, ticket 04) — `pins.json`, the type lexicon, and `dsa pins`.

The first consumer of the device-table abstraction. The gate
(`tests/integration/test_phase4_layout_gate.py`) proves it against four real
datasheets; what is proven *here* is every rule on its own, and — the point of
a rule test — that each one fails for the right reason:

- a **pin table is published whole or not at all**: a rejected table yields no
  `pins.json`, and the reason is recorded rather than lost;
- **multi-pin rows expand** and every expanded pin is individually citable,
  each still quoting the one printed row it came from;
- **type classification is lexicon-driven**: an invented lexicon this repo has
  never shipped classifies pins with no Python change, the name tier outranks
  the description tier, the longest phrase wins inside a tier, and a row whose
  evidence ties — or matches nothing — is `unknown` rather than a guess;
- the **package cross-check warns and is recorded** (ADR 0005's decided
  outcome), never suppressing a table, and it runs even when nothing was
  published because "24 terminals stated, none extracted" is the most useful
  thing a pin-less part can say;
- a pin lookup **never reads absence into a corpus with no pin table**
  (`pin_gap`, the twin of `search_unavailable`), and `dsa pins` exits 2 there.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import yaml

from datasheet_analyzer.config import PINS_SCHEMA_VERSION, PIPELINE_VERSION, Settings
from datasheet_analyzer.evalh.citations import verify_pin_queries
from datasheet_analyzer.evalh.golden import render_pin_query_report
from datasheet_analyzer.models import (
    RECONSTRUCTION_HEADER,
    RECONSTRUCTION_RESCUED,
    Confidence,
    DocType,
    GoldenQuestion,
    PinType,
    RawDocument,
    SectionNode,
    SourceDocument,
    TableBlock,
)
from datasheet_analyzer.provenance import resolve_source, source_ref
from datasheet_analyzer.publish import pins_current, write_corpus
from datasheet_analyzer.retrieve import Retriever, clear_index_cache
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.structure.pins import (
    LEXICON_PATH,
    PinTypeLexicon,
    build_pinset,
    classify_pin_type,
    load_pin_lexicon,
    stated_pin_count,
)

DOC_HASH = "beef" + "0" * 60
DOC = f"datasheet-{DOC_HASH[:8]}"

PIN_HEADERS = ["Pin No.", "Mnemonic", "Type", "Description"]
PIN_ROWS = [
    ["A1, A2, B1", "VSSA", "Input", "Analog ground pin for the converter core."],
    ["C1-C3", "AVDD1", "Input", "Analog 1.0 V Supply Inputs for the DAC."],
    ["D4", "CLKINP", "Input", "Differential Clock Input with 100 ohm termination."],
    ["D5", "SDIO", "Input/output", "Serial Port Bidirectional Data Input/Output."],
    ["D6", "NC", "", "No Connect. This pin can be left open."],
]


def _table(**kwargs) -> TableBlock:
    defaults = {
        "caption": "Table 5-1. Pin Function Descriptions",
        "headers": list(PIN_HEADERS),
        "grid": [list(row) for row in PIN_ROWS],
        "page": 4,
        "reconstruction": RECONSTRUCTION_HEADER,
    }
    return TableBlock(**{**defaults, **kwargs})


def _section(**kwargs) -> SectionNode:
    defaults = {
        "number": "5",
        "title": "Pin Configuration and Functions",
        "page_start": 4,
        "page_end": 4,
    }
    return SectionNode(**{**defaults, **kwargs})


def _raw(sections: list[SectionNode] | None = None, **kwargs) -> RawDocument:
    defaults = {
        "source": SourceDocument(
            content_hash=DOC_HASH, path="p1.pdf", part_number="TESTPART",
            doc_type=DocType.DATASHEET, page_count=20,
        ),
        "sections": sections if sections is not None else [_section(tables=[_table()])],
        "extractor": "pdf_layout",
        "extractor_version": "test-1",
    }
    return RawDocument(**{**defaults, **kwargs})


def _build(part_dir: Path, raw: RawDocument | None = None) -> Path:
    """A corpus written by the real publisher, so `pins.json` lands where the
    retrieval core looks for it."""
    raw = _raw() if raw is None else raw
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        f"# {part_dir.name}\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="adi",
        pinsets=[build_pinset(raw, part_dir.name)],
    )
    clear_index_cache()
    return part_dir


class TestPinTypeLexiconIsCheckedInData:
    """No pin word lives in Python: the classifier is whatever the YAML says."""

    def test_the_shipped_lexicon_covers_every_type_but_unknown(self):
        lexicon = load_pin_lexicon()
        assert set(lexicon.types) == set(PinType) - {PinType.UNKNOWN}
        for pin_type in lexicon.types:
            assert lexicon.names[pin_type] or lexicon.descriptions[pin_type], pin_type

    def test_a_lexicon_of_words_this_repo_never_ships_still_classifies(self):
        """The operational meaning of "no rule is hard-coded"."""
        invented = PinTypeLexicon.from_mapping(
            {"rf": {"names": ["flange"], "descriptions": ["waveguide port"]}}
        )
        assert classify_pin_type("FLANGE1", lexicon=invented) == (PinType.RF, 'name:"flange"')
        assert classify_pin_type("ZZ1", "The waveguide port.", lexicon=invented) == (
            PinType.RF, 'description:"waveguide port"'
        )
        # ...and a word the invented lexicon does not know stays unknown, even
        # though the *shipped* lexicon would have claimed it.
        assert classify_pin_type("AVDD2", "Supply input.", lexicon=invented) == (
            PinType.UNKNOWN, ""
        )

    def test_teaching_a_vendors_word_is_one_yaml_line(self, tmp_path):
        data = yaml.safe_load(LEXICON_PATH.read_text(encoding="utf-8"))
        assert classify_pin_type("VBB1")[0] is PinType.UNKNOWN, "fixture precondition"
        data["power"]["names"].append("vbb")
        edited = tmp_path / "pin_types.yaml"
        edited.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        taught = PinTypeLexicon.read(edited)
        assert classify_pin_type("VBB1", lexicon=taught) == (PinType.POWER, 'name:"vbb"')

    def test_a_malformed_entry_never_takes_the_lexicon_down(self, tmp_path, caplog):
        path = tmp_path / "broken.yaml"
        path.write_text(
            "not_a_pin_type:\n  names: [zz]\n"
            "unknown:\n  names: [qq]\n"
            "power: not-a-mapping\n"
            "ground:\n  names: [gnd]\n",
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING):
            lexicon = PinTypeLexicon.read(path)
        assert lexicon.types == (PinType.GROUND,)
        # skipped, and *said* to be skipped, each for its own reason
        assert "skipping unknown pin type" in caplog.text
        assert "it is the absence of a label" in caplog.text
        assert "not a mapping" in caplog.text

    def test_an_unreadable_lexicon_classifies_everything_unknown(self, tmp_path):
        lexicon = PinTypeLexicon.read(tmp_path / "absent.yaml")
        assert lexicon.types == ()
        assert classify_pin_type("AVDD2", "2.0 V supply input.", lexicon=lexicon) == (
            PinType.UNKNOWN, ""
        )


class TestClassificationRule:
    """The three tiers of the rule, and the two ways it declines to answer."""

    @pytest.mark.parametrize(
        ("name", "description", "expected"),
        [
            ("AVDD2", "Analog 2.0 V Supply Inputs for DAC.", PinType.POWER),
            ("GND", "Ground References.", PinType.GROUND),
            ("CLKINP", "Differential clock inputs.", PinType.CLOCK),
            ("SDIO", "Serial Port Bidirectional Data.", PinType.DIGITAL),
            ("NC", "No Connect.", PinType.NC),
            ("RSVD1", "Reserved pin.", PinType.RESERVED),
            ("ISET", "DAC Bias Current Setting Pin.", PinType.ANALOG),
            ("RF", "RF Port, ac-coupled internally.", PinType.RF),
        ],
    )
    def test_each_shipped_type_is_reachable(self, name, description, expected):
        assert classify_pin_type(name, description)[0] is expected

    def test_the_name_outranks_the_description(self):
        """A mnemonic is chosen to identify the pin; a description is a
        sentence about it. `DVDD1` is a supply even though its description
        talks about digital logic."""
        pin_type, evidence = classify_pin_type("DVDD1", "Digital logic input supply.")
        assert pin_type is PinType.POWER
        assert evidence.startswith("name:")

    def test_the_description_answers_only_when_the_name_says_nothing(self):
        pin_type, evidence = classify_pin_type("XQ7", "ADC0 Output Currents.")
        assert pin_type is PinType.ANALOG
        assert evidence == 'description:"output current"'

    def test_the_longest_phrase_wins_inside_a_tier(self):
        """`PLLCLKVDD1` carries both `clk` and `clkvdd`; the longer phrase
        explains more of the name, so the pin is a supply and not a clock.
        This is exactly how a lexicon edit closes an ambiguity."""
        assert classify_pin_type("PLLCLKVDD1", "Analog 1.0 V Supply Input for Clock PLL.") == (
            PinType.POWER, 'name:"clkvdd"'
        )

    def test_a_two_letter_phrase_matches_only_a_whole_token(self):
        """`nc` is a no-connect pin; the `nc` inside `SYNC0OUTB` is two letters
        of a synchronization output, and reading it as a no-connect would tell
        a designer to leave a JESD204B lane floating."""
        assert classify_pin_type("NC", "No Connect.")[0] is PinType.NC
        assert classify_pin_type("SYNC0OUTB", "JRx Link 0 Synchronization Outputs.")[0] is (
            PinType.DIGITAL
        )

    def test_an_ambiguous_row_is_unknown_and_carries_no_evidence(self):
        """A name naming two categories at the same phrase length is the
        lexicon saying it cannot tell them apart. `unknown` is a legitimate
        output; a coin flip between `power` and `ground` on a supply rail is
        not. (`VDDVSS` carries `vdd` and `vss`, both three characters.)"""
        assert classify_pin_type("VDDVSS", "") == (PinType.UNKNOWN, "")

    def test_a_tie_in_the_description_tier_is_unknown_too(self):
        """`clock input` and `logic input` are both eleven characters, so a
        description printing each of them decides nothing."""
        assert classify_pin_type("XQ7", "Clock input or logic input, selectable.") == (
            PinType.UNKNOWN, ""
        )

    def test_a_row_the_lexicon_does_not_recognise_is_unknown(self):
        assert classify_pin_type("XQ7", "See the layout guide for placement.") == (
            PinType.UNKNOWN, ""
        )

    def test_an_unknown_pin_is_still_published_and_still_cited(self, tmp_path):
        """`unknown` is metadata about the classification, never a filter: the
        pin is still a record, still verbatim, still on its printed page."""
        table = _table(grid=[["E1", "TDP", "Input", "Anode of the temperature diode."]])
        pinset = build_pinset(_raw([_section(tables=[table])]), "TESTPART")
        (record,) = pinset.pins
        assert record.type is PinType.UNKNOWN and record.type_evidence == ""
        assert (record.pin, record.name, record.page) == ("E1", "TDP", 4)


class TestMultiPinRowsExpand:
    """Criterion 2: every pin of a shared row is individually citable."""

    def test_a_shared_row_becomes_one_record_per_pin(self):
        pinset = build_pinset(_raw(), "TESTPART")
        assert [p.pin for p in pinset.pins] == [
            "A1", "A2", "B1", "C1", "C2", "C3", "D4", "D5", "D6",
        ]

    def test_every_expanded_pin_quotes_the_row_it_came_from(self):
        pinset = build_pinset(_raw(), "TESTPART")
        shared = [p for p in pinset.pins if p.pin in ("A1", "A2", "B1")]
        assert len(shared) == 3
        for record in shared:
            assert record.pin_verbatim == "A1, A2, B1"
            assert record.name == "VSSA"
            assert record.type is PinType.GROUND
            assert record.page == 4
            assert record.section == "5"
            assert record.row_index == 0
            assert record.row_verbatim == PIN_ROWS[0]

    def test_a_continuation_row_cites_its_own_printed_page(self):
        """A pin table that spans a page break must not cite the caption page
        for a pin printed two pages later."""
        table = _table(row_pages=[4, 5, 5, 6, 6])
        pinset = build_pinset(_raw([_section(page_end=6, tables=[table])]), "TESTPART")
        pages = {p.pin: p.page for p in pinset.pins}
        assert pages["A1"] == 4 and pages["C1"] == 5 and pages["D6"] == 6

    def test_every_record_carries_a_stable_addressable_id(self):
        first = [p.id for p in build_pinset(_raw(), "TESTPART").pins]
        second = [p.id for p in build_pinset(_raw(), "TESTPART").pins]
        assert first == second
        assert first[:3] == ["pin_1", "pin_2", "pin_3"]


class TestNothingPartialIsEverPublished:
    """Criterion 1: extracted, or honestly rejected — never half of either."""

    def test_a_rejected_table_publishes_no_pins_and_records_the_reason(self, tmp_path):
        from datasheet_analyzer.models import ExtractionStats

        duplicate = _table(
            grid=[
                ["A1", "VSSA", "Input", "Analog ground pin."],
                ["A1", "AVDD1", "Input", "Analog 1.0 V supply input."],
            ]
        )
        raw = _raw([_section(tables=[duplicate])])
        raw.extraction_stats = ExtractionStats(backend="pdf_layout")
        pinset = build_pinset(raw, "TESTPART")

        assert pinset.pins == []
        reasons = raw.extraction_stats.rejection_reasons
        assert any('duplicate pin "A1"' in line for line in reasons), reasons

        _build(tmp_path / "TESTPART", raw)
        assert not list((tmp_path / "TESTPART").glob("docs/*/pins.json"))

    def test_a_document_with_no_pin_table_writes_no_file_and_no_noise(self, tmp_path):
        spec_table = TableBlock(
            caption="Table 3. DAC DC Specifications",
            headers=["Parameter", "Min", "Typ", "Unit"],
            grid=[["DAC RESOLUTION", "16", "", "Bit"]],
            page=4,
        )
        raw = _raw([_section(number="7", title="Specifications", tables=[spec_table])])
        pinset = build_pinset(raw, "TESTPART")
        assert (pinset.pins, pinset.warnings) == ([], [])

        part_dir = _build(tmp_path / "TESTPART", raw)
        assert not list(part_dir.glob("docs/*/pins.json"))
        # ...and the corpus is still a corpus: no pin file is not a failure
        assert (part_dir / "manifest.json").exists()

    def test_a_rebuild_that_now_rejects_the_table_removes_the_old_file(self, tmp_path):
        """The rule has to hold over an *existing* corpus, not only a fresh one.

        A corpus is republished in place. If the pin table it published last
        time is now rejected — a re-extraction reads the grid differently, or
        the validation gets stricter — leaving the old `pins.json` behind would
        keep serving a superseded table under a manifest that no longer claims
        it, which is the same lie as publishing a partial one. It also keeps
        `pins_current` false, so the part rebuilds on every run and never
        settles (`tests/unit/test_batch.py`'s sibling assertion).
        """
        from datasheet_analyzer.models import ExtractionStats

        part_dir = _build(tmp_path / "TESTPART")
        (published,) = part_dir.glob("docs/*/pins.json")
        assert Retriever.for_part(part_dir).pins(pin="A1")

        rejected = _raw([_section(tables=[_table(grid=[
            ["A1", "VSSA", "Input", "Analog ground pin."],
            ["A1", "AVDD1", "Input", "Analog 1.0 V supply input."],
        ])])])
        rejected.extraction_stats = ExtractionStats(backend="pdf_layout")
        _build(part_dir, rejected)

        assert not published.exists(), "a superseded pin table must not survive a rebuild"
        assert pins_current(published.parent)
        retriever = Retriever.for_part(part_dir)
        assert retriever.pins() == []
        assert "establishes nothing" in retriever.pin_gap()

    def test_a_published_file_carries_the_current_schema_version(self, tmp_path):
        part_dir = _build(tmp_path / "TESTPART")
        (path,) = part_dir.glob("docs/*/pins.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == PINS_SCHEMA_VERSION
        assert pins_current(path.parent)

    def test_an_older_schema_is_stale_and_a_missing_file_is_not(self, tmp_path):
        """The publish-cache-key rule, both halves: a stale file republishes,
        an absent one does not put a pin-less part in a rebuild loop."""
        doc_dir = tmp_path / "docs" / DOC
        doc_dir.mkdir(parents=True)
        assert pins_current(doc_dir), "a datasheet with no pin table publishes none"
        (doc_dir / "pins.json").write_text('{"schema_version": "0"}', encoding="utf-8")
        assert not pins_current(doc_dir)


class TestPackageCountCrossCheck:
    """Criterion 4 / ADR 0005: it warns, it is recorded, it never suppresses."""

    def test_a_hyphen_joined_package_descriptor_is_the_only_count_read(self):
        """A table of contents prints "21 Pin Configuration and Function
        Descriptions" and a thermal table prints "8 PINS"; neither is a
        package descriptor, and the hyphen is what tells them apart."""
        raw = _raw([
            _section(paragraphs=[
                "15 mm x 15 mm, 324-ball BGA with 0.8 mm pitch",
                ".......... 21 Pin Configuration and Function Descriptions",
                "8 PINS 8 PINS 8 PINS",
            ], tables=[_table()]),
        ])
        assert stated_pin_count(raw) == 324

    def test_descriptors_that_disagree_are_no_evidence_at_all(self):
        """Two package descriptors contradicting each other cannot be a
        cross-check: running one against a coin flip produces warnings nobody
        can act on."""
        raw = _raw([_section(paragraphs=["8-Pin CDIP", "Removed the 10-Pin CLGA pinout"])])
        assert stated_pin_count(raw) is None

    def test_a_mismatch_warns_and_keeps_every_pin(self, tmp_path):
        raw = _raw([_section(paragraphs=["324-ball BGA"], tables=[_table()])])
        pinset = build_pinset(raw, "TESTPART")
        assert len(pinset.pins) == 9, "a bad count never throws away a good table"
        assert pinset.stated_count == 324
        assert any("count mismatch" in w and "324" in w for w in pinset.warnings)

    def test_an_agreeing_count_says_nothing(self):
        raw = _raw([_section(paragraphs=["9-ball BGA"], tables=[_table()])])
        pinset = build_pinset(raw, "TESTPART")
        assert pinset.stated_count == 9
        assert not [w for w in pinset.warnings if "mismatch" in w]

    def test_the_check_runs_even_when_no_pin_table_was_published(self):
        """"24 terminals stated, none extracted" is the single most useful
        thing a pin-less part can say, and it is invisible from a `pins.json`
        that does not exist."""
        raw = _raw([_section(paragraphs=["24-terminal ceramic LCC"], tables=[])])
        pinset = build_pinset(raw, "TESTPART")
        assert pinset.pins == []
        assert pinset.warnings == [
            (
                "pin count mismatch: document states 24, no pin table was "
                "published (see the recorded rejection reasons)"
            )
        ]

    def test_the_warning_is_recorded_in_the_manifest_not_only_logged(self, tmp_path):
        """ADR 0005: "warn, record the mismatch in the manifest". A warning is
        only weaker than a rejection when it can be ignored."""
        raw = _raw([_section(paragraphs=["324-ball BGA"], tables=[_table()])])
        part_dir = _build(tmp_path / "TESTPART", raw)
        manifest = json.loads((part_dir / "manifest.json").read_text(encoding="utf-8"))
        assert any("count mismatch" in w for w in manifest["derived_warnings"])

    def test_dsa_status_prints_the_recorded_warning(self, tmp_path, monkeypatch, capsys):
        from datasheet_analyzer import cli

        raw = _raw([_section(paragraphs=["324-ball BGA"], tables=[_table()])])
        _build(tmp_path / "parts" / "TESTPART", raw)
        settings = Settings(
            parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache",
            projects_dir=tmp_path / "projects",
        ).resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["status"]) == 0
        out = capsys.readouterr().out
        assert "derived warning: pin count mismatch" in out
        assert "pins 9 high" in out


class TestConfidenceOfAPinRow:
    def test_a_header_declared_grid_on_a_pinned_page_is_high(self):
        pinset = build_pinset(_raw(), "TESTPART")
        assert {p.confidence for p in pinset.pins} == {Confidence.HIGH}

    def test_a_rescued_grid_is_low(self):
        table = _table(reconstruction=RECONSTRUCTION_RESCUED)
        pinset = build_pinset(_raw([_section(tables=[table])]), "TESTPART")
        assert {p.confidence for p in pinset.pins} == {Confidence.LOW}

    def test_a_pin_with_no_name_is_low(self):
        """A designator with no signal on it is not something to wire.

        The way that arises in practice is a name header the device-table
        lexicon does not know: the column is honestly left unmapped rather
        than filled by position, every pin comes back nameless, and the grade
        says so instead of the corpus looking complete.
        """
        table = _table(headers=["Pin No.", "Bezeichnung", "Type", "Description"])
        pinset = build_pinset(_raw([_section(tables=[table])]), "TESTPART")
        assert pinset.pins and all(p.name == "" for p in pinset.pins)
        assert {p.confidence for p in pinset.pins} == {Confidence.LOW}

    def test_a_section_range_page_is_medium(self):
        table = _table(page=None)
        section = _section(page_start=4, page_end=9, tables=[table])
        pinset = build_pinset(_raw([section]), "TESTPART")
        assert {p.confidence for p in pinset.pins} == {Confidence.MEDIUM}


class TestPinLookup:
    """`Retriever.pins` — exact designator, name, type, free text, and the
    honest-absence half."""

    @pytest.fixture
    def part(self, tmp_path) -> Retriever:
        return Retriever.for_part(_build(tmp_path / "TESTPART"))

    def test_an_exact_designator_matches_only_that_pin(self, part):
        (hit,) = part.pins(pin="a1")
        assert (hit.record.pin, hit.record.name) == ("A1", "VSSA")
        assert hit.matched_via == "pin"
        assert hit.citation.label == "§5, p.4"

    def test_a_designator_is_never_a_prefix_search(self, part):
        """`A1` means ball A1. A near-miss on a pin designator is a wiring
        error, so the lookup is exact and not a ladder."""
        assert part.pins(pin="A") == []
        assert part.pins(pin="C") == []

    def test_a_name_substring_returns_every_pin_that_shares_it(self, part):
        hits = part.pins(name="AVDD")
        assert [h.record.pin for h in hits] == ["C1", "C2", "C3"]
        assert {h.matched_via for h in hits} == {"name"}

    def test_a_type_filter_uses_the_lexicon_label(self, part):
        assert [h.record.pin for h in part.pins(type="ground")] == ["A1", "A2", "B1"]
        assert [h.record.pin for h in part.pins(type="power")] == ["C1", "C2", "C3"]
        assert [h.record.pin for h in part.pins(type="nc")] == ["D6"]

    def test_free_text_searches_name_and_description_together(self, part):
        assert [h.record.pin for h in part.pins(q="termination")] == ["D4"]

    def test_filters_and(self, part):
        assert [h.record.pin for h in part.pins(type="power", name="AVDD")] == [
            "C1", "C2", "C3",
        ]
        assert part.pins(type="ground", name="AVDD") == []

    def test_no_filter_returns_the_table_in_printed_order(self, part):
        assert [h.record.pin for h in part.pins()] == [
            "A1", "A2", "B1", "C1", "C2", "C3", "D4", "D5", "D6",
        ]

    def test_the_json_view_carries_the_evidence_for_the_derived_field(self, part):
        (hit,) = part.pins(pin="C1")
        payload = hit.as_dict()
        assert payload["type"] == "power"
        assert payload["type_evidence"].startswith("name:")
        assert payload["citation"] == "§5, p.4"
        assert payload["pin_verbatim"] == "C1-C3"
        assert payload["confidence"] == "high"
        assert json.dumps(payload)  # the shape is JSON-serializable as declared

    def test_a_corpus_with_no_pin_table_says_so_instead_of_no_such_pin(self, tmp_path):
        """The twin of `search_unavailable`: an empty result means "nothing
        matched" only when there was a pin table to match against."""
        raw = _raw([_section(tables=[])])
        retriever = Retriever.for_part(_build(tmp_path / "EMPTY", raw))
        assert retriever.pins() == []
        gap = retriever.pin_gap()
        assert "no pin table in the corpus for part EMPTY" in gap
        assert "establishes nothing" in gap

    def test_a_corpus_with_pins_reports_no_gap(self, part):
        assert part.pin_gap() == ""


class TestPinsAreAddressableProvenance:
    """ADR 0005: a derived value's `source` must walk back to a real record."""

    def test_a_pin_reference_resolves_to_its_record_and_page(self, tmp_path):
        part_dir = _build(tmp_path / "TESTPART")
        ref = source_ref("pin_4", artifact="pins.json", doc=DOC)
        resolved = resolve_source(part_dir, ref)
        assert resolved is not None
        assert resolved.record.pin == "C1"
        assert resolved.page == 4

    def test_every_published_pin_resolves_to_its_own_record_and_printed_page(
        self, tmp_path
    ):
        """ADR 0005's enforcement clause, walked over the whole file rather
        than one hand-picked id: "a test walks every `source` field on every
        card and asserts it resolves to a real record and a printed page".

        The spec side already has this shape
        (`test_provenance.py::test_published_records_are_addressable_from_the_manifest_side`);
        a pin is addressable by the same round trip, and one sampled id would
        not notice an id collision or an off-by-one in the ordinals.
        """
        from datasheet_analyzer.provenance import PINS_ARTIFACT
        from datasheet_analyzer.retrieve import CorpusIndex

        part_dir = _build(tmp_path / "TESTPART")
        records = [rec for doc in CorpusIndex.load(part_dir).docs for rec in doc.pins]
        assert len(records) == 9
        assert len({rec.id for rec in records}) == len(records), "ids must be unique"
        for doc in CorpusIndex.load(part_dir).docs:
            for record in doc.pins:
                ref = source_ref(record.id, artifact=PINS_ARTIFACT, doc=doc.name)
                found = resolve_source(part_dir, ref)
                assert found is not None, ref
                assert found.record.pin == record.pin
                assert found.page is not None and found.page == record.page

    def test_a_reference_to_a_pin_that_does_not_exist_resolves_to_nothing(self, tmp_path):
        part_dir = _build(tmp_path / "TESTPART")
        assert resolve_source(part_dir, f"docs/{DOC}/pins.json#pin_999") is None


class TestTheCliSurface:
    @pytest.fixture
    def settings(self, tmp_path, monkeypatch) -> Settings:
        _build(tmp_path / "parts" / "TESTPART")
        resolved = Settings(
            parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache",
            projects_dir=tmp_path / "projects",
        ).resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: resolved)
        return resolved

    def test_dsa_pins_type_power_lists_the_supply_pins(self, settings, capsys):
        from datasheet_analyzer import cli

        assert cli.main(["pins", "--part", "TESTPART", "--type", "power"]) == 0
        out = capsys.readouterr().out
        assert "C1: AVDD1 (power) [Input] — p.4" in out
        assert "VSSA" not in out

    def test_dsa_pins_json_emits_the_hits_own_shape(self, settings, capsys):
        from datasheet_analyzer import cli

        assert cli.main(["pins", "--part", "TESTPART", "--pin", "D4", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["part"] == "TESTPART"
        assert [h["name"] for h in payload["hits"]] == ["CLKINP"]
        assert payload["hits"][0]["type"] == "clock"

    def test_no_match_exits_1_and_an_absent_pin_table_exits_2(
        self, tmp_path, monkeypatch, capsys
    ):
        from datasheet_analyzer import cli

        _build(tmp_path / "parts" / "TESTPART")
        _build(tmp_path / "parts" / "EMPTY", _raw([_section(tables=[])]))
        resolved = Settings(
            parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache",
            projects_dir=tmp_path / "projects",
        ).resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: resolved)

        assert cli.main(["pins", "--part", "TESTPART", "--pin", "Z99"]) == 1
        assert "No matching pins." in capsys.readouterr().out
        assert cli.main(["pins", "--part", "EMPTY"]) == 2
        assert "establishes nothing" in capsys.readouterr().err

    def test_a_project_scoped_lookup_labels_every_hit_with_its_part(self, tmp_path):
        from datasheet_analyzer.retrieve import ProjectRetriever

        _build(tmp_path / "A")
        _build(tmp_path / "B")
        scope = ProjectRetriever.for_parts("board", [tmp_path / "A", tmp_path / "B"])
        hits = scope.pins(pin="A1")
        assert [(h.citation.part, h.record.pin) for h in hits] == [("A", "A1"), ("B", "A1")]
        assert scope.pin_gap() == ""


class TestGoldenPinQueries:
    """Criterion 5's rule: a pin question passes on its *cited* records only,
    and a `count` is checked against the whole result set."""

    @pytest.fixture
    def part(self, tmp_path) -> Path:
        return _build(tmp_path / "TESTPART")

    def _question(self, **kwargs) -> GoldenQuestion:
        payload = {
            "id": "n1",
            "question": "What signal is on ball A1?",
            "expected_substrings": ["VSSA", "Analog ground pin"],
            "pages": [4],
            "kind": "pin",
            "pin_query": {"pin": "A1"},
        }
        payload.update(kwargs)
        return GoldenQuestion.model_validate(payload)

    def test_a_pin_question_passes_on_its_cited_record(self, part):
        (res,) = verify_pin_queries([self._question()], part)
        assert res.ok and res.n_records == 1 and res.n_verified == 1

    def test_questions_without_the_marker_are_not_pin_questions(self, part):
        assert verify_pin_queries([self._question(pin_query=None)], part) == []

    def test_a_right_pin_beside_a_wrong_page_fails(self, part):
        (res,) = verify_pin_queries([self._question(pages=[99])], part)
        assert not res.ok and res.n_records == 1 and res.n_verified == 0

    def test_a_substring_the_record_lacks_fails(self, part):
        (res,) = verify_pin_queries(
            [self._question(expected_substrings=["VSSA", "1.8 V"])], part
        )
        assert not res.ok

    def test_a_name_to_pins_question_checks_every_pin_it_names(self, part):
        (res,) = verify_pin_queries(
            [self._question(
                question="Which balls are the 1.0 V analog supply?",
                expected_substrings=["AVDD1", "C1", "C3"],
                pin_query={"name": "AVDD1", "count": "3"},
            )],
            part,
        )
        assert res.ok and res.n_records == 3

    def test_a_count_that_drifts_fails_even_when_the_text_matches(self, part):
        """A pin table that quietly gained or lost a row is exactly what a
        benchmark exists to catch."""
        (res,) = verify_pin_queries(
            [self._question(
                expected_substrings=["AVDD1"],
                pin_query={"name": "AVDD1", "count": "4"},
            )],
            part,
        )
        assert not res.ok
        assert res.detail == "3 pin(s), expected 4"

    def test_the_report_names_every_question_and_counts_only_passes(self, part):
        results = verify_pin_queries(
            [self._question(), self._question(id="n2", pages=[99])], part
        )
        text = render_pin_query_report(results)
        assert "**1/2 passed**" in text
        assert "Pin query verification" in text
        assert text.count("✅") == 1 and text.count("❌") == 1


class TestTheShippedPinBenchmark:
    """AD9081 is the one built part whose datasheet prints a machine-readable
    pin table, so it is where the ticket's three pin shapes live. The gate runs
    them against the corpus; this checks the benchmark is *shaped* right, which
    a typo would otherwise hide by dropping the question from the table."""

    GOLDEN = Path(__file__).parent.parent / "fixtures" / "golden_qa_AD9081.yaml"

    def test_the_benchmark_carries_all_three_pin_shapes(self):
        from datasheet_analyzer.evalh.golden import load_golden

        queries = [q.pin_query for q in load_golden(self.GOLDEN) if q.pin_query]
        assert len(queries) == 3
        assert any("pin" in q for q in queries), "pin -> name"
        assert any("name" in q for q in queries), "name -> pins"
        assert any(q.get("type") for q in queries), "count by type"
        assert sum(1 for q in queries if "count" in q) >= 1

    def test_every_pin_question_carries_the_ground_truth_it_is_judged_by(self):
        from datasheet_analyzer.evalh.golden import load_golden

        for q in load_golden(self.GOLDEN):
            if q.pin_query is None:
                continue
            assert q.pages, f"{q.id}: a pin question needs a cited page"
            assert q.expected_substrings, f"{q.id}: nothing to verify"
            assert set(q.pin_query) <= {"pin", "name", "type", "q", "count"}, q.id
