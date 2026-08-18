"""Pins — `pins.json`, the type lexicon, the package cross-check, `dsa pins`.

Hermetic per invariant 4: every fixture is either a synthetic PDF built
in-test with PyMuPDF and read by the real layout backend, or a hand-built
`RawDocument` for the functions that only ever see printed text. No network,
no model, no subprocess, no built part on disk.

Coverage, one class per acceptance checkbox of ticket 04:

- a pin table extracts with full provenance, and a part whose only candidate
  table fails validation gets **no `pins.json` at all** — plus the reason,
  recorded where `dsa status` already prints rejections;
- multi-pin rows expand and every expanded pin is individually citable: unique
  stable ids that `derive/provenance.resolve_source` resolves back to a record
  and a printed page in the written file;
- type classification is lexicon-driven (adding a name pattern is a YAML edit,
  not a code change), and the two ambiguous shapes — a printed cell that
  contradicts the name, and one name cell naming pins that disagree — yield
  `unknown` rather than a guess;
- the package cross-check runs on every document, warns on a mismatch, says so
  when the printed counts disagree with each other, and stays silent when the
  document prints no count at all;
- `dsa pins` answers pin -> name, name -> pins and count-by-type over a corpus
  built end to end by the real pipeline, with a page cite on every line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import ClassVar

import fitz
import pytest

from datasheet_analyzer.config import PINS_SCHEMA_VERSION, Settings, reset_settings_cache
from datasheet_analyzer.derive.pins import (
    NO_EVIDENCE,
    PinBuild,
    build_pins,
    classify_pin_type,
    clear_pin_lexicon_cache,
    cli_pins,
    cross_check_warnings,
    find_pins,
    format_pin_hits,
    load_part_pins,
    load_pin_lexicon,
    load_pinset,
    package_pin_count,
    printed_direction,
    record_pin_rejections,
    type_counts,
    write_pinset,
)
from datasheet_analyzer.derive.provenance import PINS_ARTIFACT, parse_source, resolve_source
from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.models import (
    PIN_TYPE_UNKNOWN,
    PIN_TYPES,
    Confidence,
    ExtractionStats,
    PinRecord,
    RawDocument,
    SectionNode,
    SourceDocument,
    pin_record_id,
)
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.publish.writer import document_dirs
from datasheet_analyzer.structure.device_tables import clear_device_lexicon_cache

PAGE_W, PAGE_H = 612.0, 792.0
COL_X = (56.0, 140.0, 250.0, 340.0)
RIGHT_EDGE = 560.0
PITCH = 13.0
CAP_Y = 140.0
BODY_Y = 153.0

PIN_HEADERS = ["Pin", "Name", "Type", "Description"]
#: Five pins covering five lexicon labels plus one the lexicon cannot name.
PIN_ROWS = [
    ["A1", "VSSA", "-", "Analog ground"],
    ["A2", "AVDD18", "-", "Analog 1.8 V supply"],
    ["B1", "CLKIN_P", "I", "Differential reference clock input"],
    ["B2", "SDI", "I", "SPI data input"],
    ["B3", "NC", "-", "No connect. Leave this pin open."],
]
PACKAGE_TEXT = "PINTEST is supplied in an 8-Pin VQFN package."
PIN_TOC = [
    [1, "6 Pin Configuration and Functions", 1],
    [1, "9 Mechanical, Packaging, and Orderable Information", 2],
]


def _build_pdf(
    path: Path,
    rows: list[list[str]],
    *,
    caption: str = "Table 6-1. Pin Functions",
    package_lines: tuple[str, ...] = (PACKAGE_TEXT,),
) -> Path:
    """A two-page synthetic datasheet: a ruled pin table, then a package page.

    Geometry models a real pin table — four ruled columns under a `Table N-M.`
    caption — because that is the shape the layout engine accepts as tabular,
    and reading the fixture through the real backend is what makes the
    `TableBlock` under test the one a build would actually produce.
    """
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((COL_X[0], CAP_Y), caption)
    for r, row in enumerate(rows):
        for x, cell in zip(COL_X, row):
            if cell:
                page.insert_text((x, BODY_Y + r * PITCH), cell)
    top, bottom = BODY_Y - 10.0, BODY_Y + len(rows) * PITCH + 2.0
    for x in (*COL_X, RIGHT_EDGE):
        page.draw_line((x - 4.0, top), (x - 4.0, bottom))
    back = doc.new_page(width=PAGE_W, height=PAGE_H)
    for i, line in enumerate(package_lines):
        back.insert_text((72.0, 120.0 + i * 20.0), line)
    doc.set_toc(PIN_TOC)
    doc.save(str(path))
    doc.close()
    return path


def _extract(tmp_path: Path, name: str, rows: list[list[str]], **kwargs) -> RawDocument:
    pdf = _build_pdf(tmp_path / name, rows, **kwargs)
    source = SourceDocument(
        content_hash=hashlib.sha256(pdf.read_bytes()).hexdigest(), path=str(pdf)
    )
    return PdfLayoutBackend().extract(source)


def _pin_doc(tmp_path: Path, name: str = "pins.pdf", rows: list[list[str]] | None = None, **kw):
    return _extract(
        tmp_path, name, [PIN_HEADERS] + list(rows if rows is not None else PIN_ROWS), **kw
    )


def _text_doc(*blobs: str) -> RawDocument:
    """A `RawDocument` that prints only paragraphs — for the text functions.

    `package_pin_count` reads printed text and nothing else, so a hand-built
    document is the honest fixture for it: it makes the *words* the variable
    under test instead of the layout engine's opinion of a page.
    """
    return RawDocument(
        source=SourceDocument(content_hash="0" * 64, path="synthetic.pdf"),
        extractor="pdf_layout",
        sections=[
            SectionNode(
                number="9",
                title="Mechanical, Packaging, and Orderable Information",
                paragraphs=list(blobs),
            )
        ],
    )


@pytest.fixture(autouse=True)
def _fresh_lexicons():
    """Both lexicons are process-cached; a temp copy must not outlive its test."""
    clear_pin_lexicon_cache()
    clear_device_lexicon_cache()
    yield
    clear_pin_lexicon_cache()
    clear_device_lexicon_cache()


def _lexicon_text() -> str:
    from datasheet_analyzer.derive.pins import PIN_LEXICON_PATH

    return PIN_LEXICON_PATH.read_text(encoding="utf-8")


class TestBuildsAndProvenance:
    """A pin table becomes records that carry everything needed to cite them."""

    def test_records_carry_verbatim_cells_and_provenance(self, tmp_path):
        build = build_pins(_pin_doc(tmp_path), "PINTEST")
        assert build.pinset is not None
        pinset = build.pinset
        assert pinset.schema_version == PINS_SCHEMA_VERSION
        assert pinset.part_number == "PINTEST"
        assert [p.pin for p in pinset.pins] == ["A1", "A2", "B1", "B2", "B3"]

        first = pinset.pins[0]
        assert first.name == "VSSA"
        assert first.description == "Analog ground"
        # The printed glyph is the authority: the direction cell is copied,
        # never re-spelled (PyMuPDF's base font cannot lay down an em dash, so
        # the fixture prints the hyphen a datasheet would; `printed_direction`
        # is asserted on the em dash itself below).
        assert first.direction == "-"
        assert first.section == "6"
        assert first.table_index == 0
        assert first.row_index == 0
        assert first.page == 1
        assert first.row_verbatim == ["A1", "VSSA", "-", "Analog ground"]
        assert first.confidence is Confidence.HIGH
        assert first.id == pin_record_id(0, 0, "A1")

    def test_ids_are_unique_and_stable_across_a_rebuild(self, tmp_path):
        first = build_pins(_pin_doc(tmp_path, "a.pdf"), "PINTEST").pinset
        second = build_pins(_pin_doc(tmp_path, "b.pdf"), "PINTEST").pinset
        ids = [p.id for p in first.pins]
        assert len(set(ids)) == len(ids)
        assert ids == [p.id for p in second.pins]

    def test_no_pin_table_yields_no_pinset(self, tmp_path):
        """A document with no pin table publishes nothing, and says nothing."""
        doc = _pin_doc(tmp_path, "prose.pdf", rows=[], caption="Table 6-1. Pin Functions")
        build = build_pins(doc, "PINTEST")
        assert build.pinset is None
        assert build.rejection_reasons == ()

    def test_a_rejected_table_publishes_nothing_but_records_the_reason(self, tmp_path):
        """Duplicate keys reject the table whole — never a partial pin set."""
        rows = [
            ["A1", "VSSA", "-", "Analog ground"],
            ["A1", "AVDD18", "—", "Analog 1.8 V supply"],
            ["B1", "CLKIN_P", "I", "Differential reference clock input"],
            ["B2", "SDI", "I", "SPI data input"],
        ]
        build = build_pins(_pin_doc(tmp_path, "dupe.pdf", rows=rows), "PINTEST")
        assert build.pinset is None
        assert build.n_pins == 0
        assert any("duplicate key" in r for r in build.rejection_reasons)

        stats = record_pin_rejections(ExtractionStats(backend="pdf_layout"), build)
        assert any("duplicate key" in r for r in stats.rejection_reasons)

    def test_rejection_recording_tolerates_a_document_with_no_stats(self):
        assert record_pin_rejections(None, PinBuild(rejection_reasons=("x",))) is None


class TestExpansion:
    """One printed row, several pins, each individually citable."""

    ROWS: ClassVar[list[list[str]]] = [
        ["A1, A2, B1", "VDD18", "-", "Digital 1.8 V supply"],
        ["C1-C4", "GND", "-", "Ground"],
        ["D1", "CLKIN_P", "I", "Differential reference clock input"],
    ]

    def test_list_and_range_cells_expand_sharing_the_printed_row(self, tmp_path):
        build = build_pins(_pin_doc(tmp_path, "expand.pdf", rows=self.ROWS), "PINTEST")
        pins = build.pinset.pins
        assert [p.pin for p in pins] == ["A1", "A2", "B1", "C1", "C2", "C3", "C4", "D1"]

        expanded = [p for p in pins if p.pin in {"A1", "A2", "B1"}]
        assert {p.name for p in expanded} == {"VDD18"}
        assert {p.expanded_from for p in expanded} == {"A1, A2, B1"}
        assert {p.row_index for p in expanded} == {0}
        # Each keeps the source row exactly as printed, and its own id.
        assert all(p.row_verbatim[0] == "A1, A2, B1" for p in expanded)
        assert len({p.id for p in expanded}) == 3
        # A row that named one pin says so: `expanded_from` is empty.
        assert [p.expanded_from for p in pins if p.pin == "D1"] == [""]

    def test_every_expanded_pin_resolves_back_to_its_record_and_page(self, tmp_path):
        """Individually citable, checked the way a card will check it."""
        build = build_pins(_pin_doc(tmp_path, "expand.pdf", rows=self.ROWS), "PINTEST")
        doc_dir = tmp_path / "docs" / "datasheet-deadbeef"
        write_pinset(doc_dir, build.pinset)

        for pin in build.pinset.pins:
            source = f"{PINS_ARTIFACT}#{pin.id}"
            assert parse_source(source) == (PINS_ARTIFACT, pin.id)
            resolved = resolve_source(source, roots=doc_dir)
            assert resolved is not None, source
            assert resolved.record["pin"] == pin.pin
            assert resolved.page == pin.page == 1


class TestClassification:
    """The label comes from the checked-in lexicon, or it is `unknown`."""

    def test_labels_and_evidence_over_a_real_table(self, tmp_path):
        pins = {p.pin: p for p in build_pins(_pin_doc(tmp_path), "PINTEST").pinset.pins}
        assert pins["A1"].type == "ground"
        assert pins["A2"].type == "power"
        assert pins["B1"].type == "clock"
        assert pins["B2"].type == "digital"
        assert pins["B3"].type == "nc"
        # Every label names the lexicon entry behind it.
        assert pins["A1"].type_evidence.startswith("name:")
        assert all(p.type in PIN_TYPES for p in pins.values())

    def test_evidence_ranks_printed_cell_over_name_over_description(self):
        assert classify_pin_type(printed="PWR", name="MYSTERY").type == "power"
        assert classify_pin_type(name="AVDD18").evidence == "name:*vdd*"
        assert (
            classify_pin_type(description="Analog ground for the DAC").evidence
            == "description:ground"
        )

    def test_a_rail_word_beats_a_function_word_in_the_same_name(self):
        """`CLKVDD1` is a supply, not a clock — declaration order decides."""
        assert classify_pin_type(name="CLKVDD1").type == "power"
        assert classify_pin_type(name="CLKIN_P").type == "clock"

    def test_ambiguous_rows_yield_unknown_rather_than_a_guess(self):
        # The printed cell contradicts the name: the datasheet disagrees with
        # itself and this tool does not get to pick a winner.
        conflict = classify_pin_type(printed="GND", name="VDD18")
        assert conflict.type == PIN_TYPE_UNKNOWN
        assert conflict.evidence.startswith("conflict:")

        # One name cell naming pins whose own labels disagree.
        mixed = classify_pin_type(name="VDD18, GND")
        assert mixed.type == PIN_TYPE_UNKNOWN
        assert mixed.evidence == "conflict:name=ground|power"

        # Nothing matched at all: `unknown`, and it says why.
        silent = classify_pin_type(name="ZQ7", description="See Figure 12.")
        assert silent == classify_pin_type(name="", description="")
        assert silent.type == PIN_TYPE_UNKNOWN
        assert silent.evidence == NO_EVIDENCE

    def test_an_ambiguous_row_survives_the_whole_build_as_unknown(self, tmp_path):
        rows = [
            ["A1", "VDD18", "GND", "Supply and return"],
            ["A2", "AVDD18", "-", "Analog 1.8 V supply"],
            ["B1", "CLKIN_P", "I", "Differential reference clock input"],
        ]
        pins = {
            p.pin: p for p in build_pins(_pin_doc(tmp_path, "amb.pdf", rows=rows), "P").pinset.pins
        }
        assert pins["A1"].type == PIN_TYPE_UNKNOWN
        assert pins["A1"].type_evidence.startswith("conflict:")
        # …and the row is still published, verbatim, with its provenance.
        assert pins["A1"].row_verbatim == ["A1", "VDD18", "GND", "Supply and return"]

    def test_direction_is_kept_only_when_the_cell_prints_one(self):
        assert printed_direction("I/O") == "I/O"
        assert printed_direction("—") == "—"
        # `PWR` is a type, not a direction; recording it as one would make
        # `--type power` and the printed direction two names for one thing.
        assert printed_direction("PWR") == ""

    def test_adding_a_name_pattern_is_a_data_change(self, tmp_path):
        """`ZQ7` is nobody's rail — until the lexicon says it is."""
        assert classify_pin_type(name="ZQ7").type == PIN_TYPE_UNKNOWN

        text = _lexicon_text().replace('names: ["*vdd*",', 'names: [zq7, "*vdd*",')
        path = tmp_path / "pin_types.yaml"
        path.write_text(text, encoding="utf-8")
        patched = load_pin_lexicon(path)

        label = classify_pin_type(name="ZQ7", lexicon=patched)
        assert label.type == "power"
        assert label.evidence == "name:zq7"

    def test_shipped_lexicon_only_names_known_types(self):
        lex = load_pin_lexicon()
        assert next(s.type for s in lex.types) == "ground"  # order is priority
        assert {s.type for s in lex.types} <= set(PIN_TYPES)
        assert PIN_TYPE_UNKNOWN not in {s.type for s in lex.types}
        assert "i/o" in lex.directions


class TestPackageCrossCheck:
    """Run on every document; a mismatch is a warning, never a correction."""

    def test_reads_a_hyphenated_or_plural_count_near_a_package_word(self):
        assert package_pin_count(_text_doc("Supplied in a 40-Pin VQFN package.")).count == 40
        assert package_pin_count(_text_doc("RHA (VQFN) 400 PINS")).count == 400
        assert package_pin_count(_text_doc("324-Ball BGA_ED (15 mm × 15 mm)")).count == 324

    def test_refuses_the_shapes_that_are_not_declarations(self):
        # A table of contents line, a body sentence, and a count with no
        # package context anywhere near it.
        assert (
            package_pin_count(_text_doc("21 Pin Configuration and Functions ... 9")).count is None
        )
        assert (
            package_pin_count(_text_doc("Connect the IF1 pin to the package hybrid.")).count is None
        )
        assert package_pin_count(_text_doc("The 48-lead device ships in trays.")).count is None
        assert package_pin_count(_text_doc("2-Pin package")).count is None  # below min_count

    def test_disagreeing_counts_are_ambiguous_rather_than_resolved(self):
        found = package_pin_count(_text_doc("8-Pin CDIP package", "Removed the 10-Pin CLGA pinout"))
        assert found.count is None
        assert found.ambiguous is True
        assert found.values == (8, 10)

    def test_a_mismatch_warns_and_names_both_numbers(self, tmp_path):
        build = build_pins(_pin_doc(tmp_path), "PINTEST")  # 5 records, 8-Pin package
        assert build.declared.count == 8
        assert len(build.warnings) == 1
        warning = build.warnings[0]
        assert "8" in warning and "5" in warning
        assert build.pinset.warnings == list(build.warnings)
        assert build.pinset.declared_pin_count == 8

    def test_an_agreeing_count_is_silent(self, tmp_path):
        doc = _pin_doc(
            tmp_path,
            "match.pdf",
            package_lines=("PINTEST is supplied in a 5-Pin VQFN package.",),
        )
        build = build_pins(doc, "PINTEST")
        assert build.declared.count == 5
        assert build.warnings == ()

    def test_a_document_that_prints_no_count_is_not_a_finding(self, tmp_path):
        doc = _pin_doc(tmp_path, "silent.pdf", package_lines=("Contact sales for tape and reel.",))
        build = build_pins(doc, "PINTEST")
        assert build.declared.count is None
        assert build.pinset.declared_pin_count is None
        assert build.warnings == ()

    def test_ambiguity_is_reported_instead_of_a_cross_check(self):
        pins = [PinRecord(pin="1", name="VDD"), PinRecord(pin="EPAD", name="GND")]
        warnings = cross_check_warnings(
            pins, package_pin_count(_text_doc("8-Pin CDIP package", "10-Pin CLGA package"))
        )
        assert len(warnings) == 1
        assert "ambiguous" in warnings[0]

    def test_a_named_pad_is_called_out_in_the_mismatch(self):
        pins = [PinRecord(pin=str(n), name="GND") for n in range(1, 41)]
        pins.append(PinRecord(pin="DAP", name="GND"))
        warnings = cross_check_warnings(pins, package_pin_count(_text_doc("40-Pin VQFN package")))
        assert len(warnings) == 1
        assert "41" in warnings[0] and "DAP" in warnings[0]


class TestLookup:
    def test_find_by_designator_name_and_type_with_citations(self, tmp_path):
        build = build_pins(_pin_doc(tmp_path), "PINTEST")
        doc_dir = tmp_path / "docs" / "datasheet-deadbeef"
        write_pinset(doc_dir, build.pinset)
        from datasheet_analyzer.derive.pins import PartPins

        loaded = load_pinset(doc_dir)
        part_pins = PartPins(part="PINTEST", sets=((doc_dir.name, loaded),))

        by_pin = find_pins(part_pins, q="A1")
        assert [h.record.name for h in by_pin] == ["VSSA"]
        assert by_pin[0].matched_via == "pin"
        assert by_pin[0].citation.label == "§6, p.1"
        assert by_pin[0].as_dict()["confidence"] == "high"

        by_name = find_pins(part_pins, q="clkin")
        assert [h.record.pin for h in by_name] == ["B1"]
        assert by_name[0].matched_via == "name"

        by_type = find_pins(part_pins, pin_type="power")
        assert [h.record.pin for h in by_type] == ["A2"]

        assert type_counts(loaded.pins) == {
            "power": 1,
            "ground": 1,
            "digital": 1,
            "clock": 1,
            "nc": 1,
        }
        rendered = format_pin_hits(by_pin)
        assert "A1" in rendered and "p.1" in rendered
        assert format_pin_hits([]) == "No matching pins."

    def test_a_description_mention_is_ranked_below_a_direct_hit(self, tmp_path):
        build = build_pins(_pin_doc(tmp_path), "PINTEST")
        from datasheet_analyzer.derive.pins import PartPins

        part_pins = PartPins(part="PINTEST", sets=(("doc", build.pinset),))
        hits = find_pins(part_pins, q="ground")
        assert [h.matched_via for h in hits] == ["description"]


class TestCli:
    """`dsa pins` over a corpus the real pipeline built, end to end."""

    @pytest.fixture
    def built(self, tmp_path, monkeypatch):
        pdf = _build_pdf(tmp_path / "pintest.pdf", [PIN_HEADERS] + PIN_ROWS)
        parts = tmp_path / "parts"
        monkeypatch.setenv("DSA_PARTS_DIR", str(parts))
        monkeypatch.setenv("DSA_CACHE_DIR", str(tmp_path / ".cache"))
        reset_settings_cache()
        settings = Settings(
            parts_dir=parts, cache_dir=tmp_path / ".cache", library_dir=tmp_path / "library"
        ).resolve()
        result = build_part(
            pdf, part_number="PINTEST", settings=settings, vendor="adi", use_llm=False
        )
        yield result
        reset_settings_cache()

    def test_the_pipeline_publishes_pins_json_beside_the_other_artifacts(self, built):
        doc_dir = document_dirs(built.manifest, part_dir=built.part_dir)[
            built.manifest.documents[0].content_hash
        ]
        path = doc_dir / PINS_ARTIFACT
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == PINS_SCHEMA_VERSION
        # A shared artifact is part-neutral; the reader takes the part from
        # the manifest, exactly as it does for specs.json.
        assert data["part_number"] == ""
        assert [p["pin"] for p in data["pins"]] == ["A1", "A2", "B1", "B2", "B3"]
        assert data["pins"][0]["id"] == pin_record_id(0, 0, "A1")

        loaded = load_part_pins(built.part_dir, "PINTEST")
        assert [p.pin for p in loaded.pins] == ["A1", "A2", "B1", "B2", "B3"]

    def test_pins_answers_pin_to_name_name_to_pins_and_type_counts(self, built, capsys):
        assert cli_pins(_args(part="PINTEST", q="A1")) == 0
        assert "VSSA" in capsys.readouterr().out

        assert cli_pins(_args(part="PINTEST", q="CLKIN_P")) == 0
        out = capsys.readouterr().out
        assert "B1" in out and "p.1" in out

        assert cli_pins(_args(part="PINTEST", type="power", json=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert [h["pin"] for h in payload["hits"]] == ["A2"]
        assert payload["hits"][0]["citation"] == "§6, p.1"
        assert payload["counts"] == {"power": 1}
        # The package cross-check travels with the answer rather than being
        # buried in a build log.
        assert payload["warnings"] and "8" in payload["warnings"][0]

    def test_no_match_is_exit_1_and_a_bad_scope_is_exit_2(self, built, capsys):
        assert cli_pins(_args(part="PINTEST", q="ZZTOP")) == 1
        assert "No matching pins." in capsys.readouterr().out
        assert cli_pins(_args()) == 2
        assert cli_pins(_args(part="NOPE")) == 2

    def test_a_project_scope_labels_every_hit_with_its_part(
        self, built, capsys, tmp_path, monkeypatch
    ):
        """`--project` is a frozen flag, so it is exercised, not assumed."""
        from datasheet_analyzer.projects import add_parts, new_project, save_project

        projects = tmp_path / "projects"
        monkeypatch.setenv("DSA_PROJECTS_DIR", str(projects))
        reset_settings_cache()
        project = new_project("rx-front-end", projects)
        add_parts(project, ["PINTEST"], parts_dir=built.part_dir.parent)
        save_project(project, projects)

        assert cli_pins(_args(project="rx-front-end", type="ground")) == 0
        out = capsys.readouterr().out
        assert "[PINTEST]" in out and "VSSA" in out
        assert cli_pins(_args(project="nope")) == 2

    def test_a_part_without_pins_says_so_instead_of_answering_nothing(
        self, built, capsys, tmp_path
    ):
        doc_dir = document_dirs(built.manifest, part_dir=built.part_dir)[
            built.manifest.documents[0].content_hash
        ]
        (doc_dir / PINS_ARTIFACT).unlink()
        assert cli_pins(_args(part="PINTEST")) == 1
        captured = capsys.readouterr()
        assert "no pin table was published" in captured.err
        assert "No matching pins." in captured.out


def _args(**kwargs) -> argparse.Namespace:
    """The frozen `dsa pins` namespace, as `cli.py` builds it."""
    return argparse.Namespace(
        part=kwargs.get("part", ""),
        project=kwargs.get("project", ""),
        q=kwargs.get("q", ""),
        type=kwargs.get("type", ""),
        json=kwargs.get("json", False),
    )
