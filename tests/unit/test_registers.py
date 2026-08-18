"""Registers — routing, `registers.json`, address parsing, `dsa regs`.

Hermetic per invariant 4: every fixture is a synthetic PDF built in-test with
PyMuPDF and read by the real layout backend, or a hand-built `RegisterSet` for
the functions that only ever see records. No network, no model, no subprocess,
no built part on disk. The gate against the real reference register map lives
in `tests/integration/test_phase6_registers.py`, where it belongs.

Coverage, one class per acceptance checkbox of ticket 05:

- `REGISTER_MAP` routes to `pdf_layout` for every vendor while every other
  companion type keeps `pdf_text`, and `PIPELINE_VERSION` is bumped so the
  cached paragraph-only readings of register maps invalidate;
- addresses carry both the printed form and the parsed integer, and a print
  that does not parse stays verbatim-only rather than being guessed — the
  same rule for reset values;
- a summary table that fails validation is rejected **whole**, with the reason
  recorded where `dsa status` already prints rejections, and a document whose
  only candidate table is rejected publishes no `registers.json` at all;
- the honest gaps are said out loud: a column the map never printed, a printed
  row that carried no readable address, and the unparsed address population;
- `dsa regs --addr` resolves by parsed value, so `0x1A04`, `0x1a04` and `6660`
  are one question, and a part that published no register map is told apart
  from a part whose map has no match.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import ClassVar

import fitz
import pytest

from datasheet_analyzer.config import (
    PIPELINE_VERSION,
    REGISTERS_SCHEMA_VERSION,
    Settings,
    reset_settings_cache,
)
from datasheet_analyzer.derive.provenance import REGISTERS_ARTIFACT, parse_source, resolve_source
from datasheet_analyzer.derive.registers import (
    ADDRESS_DERIVATION,
    PartRegisters,
    RegisterBuild,
    build_registers,
    cli_regs,
    find_registers,
    format_register_hits,
    load_part_registers,
    load_registerset,
    no_bit_fields_message,
    no_registers_message,
    parse_query_address,
    record_register_rejections,
    write_registerset,
)
from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.models import (
    Confidence,
    DocType,
    ExtractionStats,
    RawDocument,
    RegisterRecord,
    RegisterSet,
    RegisterValue,
    SourceDocument,
    register_record_id,
)
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.publish.writer import document_dirs
from datasheet_analyzer.structure.device_tables import clear_device_lexicon_cache
from datasheet_analyzer.vendor import select_backend

PAGE_W, PAGE_H = 612.0, 792.0
COL_X = (56.0, 150.0, 280.0, 380.0)
RIGHT_EDGE = 560.0
PITCH = 13.0
CAP_Y = 140.0
BODY_Y = 153.0

CAPTION = "Table 5-1. Device Registers"
REG_HEADERS = ["Address", "Register", "Reset", "Access"]
#: A four-register map: two clean rows, one whose reset value is a footnote
#: pointer rather than a number, and one more so the address column is long
#: enough to read as a column.
REG_ROWS: list[list[str]] = [
    ["0x1A04", "TXDIG_CTRL0", "0x00", "R/W"],
    ["0x1A05", "TXDIG_CTRL1", "0x0F", "RO"],
    ["0x1A08", "NCO_FTW", "Note 2", "R/W"],
    ["0x1A0C", "GAIN_CTRL", "0x80", "R/W"],
]
REG_TOC = [[1, "5 Register Map", 1]]


def _build_pdf(
    path: Path,
    rows: list[list[str]],
    *,
    caption: str = CAPTION,
) -> Path:
    """A one-page synthetic register map: a ruled table under a `Table N-M.`
    caption — the shape the layout engine accepts as tabular, so the
    `TableBlock` under test is the one a real build would produce."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((COL_X[0], CAP_Y), caption)
    for r, row in enumerate(rows):
        for x, cell in zip(COL_X, row):
            if cell:
                page.insert_text((x, BODY_Y + r * PITCH), cell)
    top, bottom = BODY_Y - 10.0, BODY_Y + len(rows) * PITCH + 2.0
    for x in (*COL_X[: len(rows[0])], RIGHT_EDGE):
        page.draw_line((x - 4.0, top), (x - 4.0, bottom))
    doc.set_toc(REG_TOC)
    doc.save(str(path))
    doc.close()
    return path


def _extract(tmp_path: Path, name: str, rows: list[list[str]], **kwargs) -> RawDocument:
    pdf = _build_pdf(tmp_path / name, rows, **kwargs)
    source = SourceDocument(
        content_hash=hashlib.sha256(pdf.read_bytes()).hexdigest(),
        path=str(pdf),
        doc_type=DocType.REGISTER_MAP,
    )
    return PdfLayoutBackend().extract(source)


def _reg_doc(
    tmp_path: Path,
    name: str = "regs.pdf",
    rows: list[list[str]] | None = None,
    headers: list[str] | None = None,
    **kw,
) -> RawDocument:
    body = list(rows if rows is not None else REG_ROWS)
    return _extract(tmp_path, name, [list(headers or REG_HEADERS)] + body, **kw)


@pytest.fixture(autouse=True)
def _fresh_lexicon():
    """The device lexicon is process-cached; no test may inherit another's."""
    clear_device_lexicon_cache()
    yield
    clear_device_lexicon_cache()


def _handmade_set(*records: RegisterRecord, doc_hash: str = "f" * 64) -> RegisterSet:
    return RegisterSet(
        schema_version=REGISTERS_SCHEMA_VERSION,
        part_number="REGTEST",
        doc_hash=doc_hash,
        registers=list(records),
    )


class TestRouting:
    """The re-route this ticket exists for, and the cache bump that pays for it."""

    def test_register_maps_read_by_the_layout_backend_for_every_vendor(self):
        for vendor in ("ti", "adi", "qorvo", "unknown"):
            assert select_backend(vendor, DocType.REGISTER_MAP) == "pdf_layout"

    def test_other_companions_are_untouched(self):
        """Errata and app notes are prose: they keep `pdf_text` exactly."""
        for vendor in ("ti", "adi", "qorvo", "unknown"):
            assert select_backend(vendor, DocType.ERRATA) == "pdf_text"
            assert select_backend(vendor, DocType.APP_NOTE) == "pdf_text"
            assert select_backend(vendor, DocType.UNKNOWN) == "pdf_text"

    def test_pipeline_version_is_bumped_so_cached_readings_invalidate(self):
        """0.4.0 corpora hold paragraph-only register maps; 0.5.0 re-extracts."""
        assert PIPELINE_VERSION == "0.5.0"

    def test_a_register_map_pdf_yields_tables_not_only_paragraphs(self, tmp_path):
        """The whole point: read as prose, a register map answers nothing."""
        raw = _reg_doc(tmp_path)
        assert raw.extractor == "pdf_layout"
        tables = [t for sec in raw.sections for t in sec.tables]
        assert tables and tables[0].caption == CAPTION


class TestBuildAndProvenance:
    """A summary table becomes records that carry everything needed to cite them."""

    def test_records_carry_verbatim_cells_and_parsed_addresses(self, tmp_path):
        build = build_registers(_reg_doc(tmp_path), "REGTEST")
        assert build.registerset is not None
        regset = build.registerset
        assert regset.schema_version == REGISTERS_SCHEMA_VERSION
        assert regset.part_number == "REGTEST"
        assert build.accepted_tables == 1
        assert [r.name for r in regset.registers] == [
            "TXDIG_CTRL0",
            "TXDIG_CTRL1",
            "NCO_FTW",
            "GAIN_CTRL",
        ]

        first = regset.registers[0]
        assert first.address.verbatim == "0x1A04"
        assert first.address.value == 6660
        assert first.reset.verbatim == "0x00"
        assert first.reset.value == 0
        assert first.access == "R/W"
        assert first.section == "5"
        assert first.table_index == 0
        assert first.row_index == 0
        assert first.page == 1
        assert first.row_verbatim == ["0x1A04", "TXDIG_CTRL0", "0x00", "R/W"]
        assert first.confidence is Confidence.HIGH
        assert first.id == register_record_id(0, 0)
        # Bit fields are ticket 06's: an empty list says "not extracted",
        # never "this register has no fields".
        assert first.fields == []

    def test_ids_are_unique_and_stable_across_a_rebuild(self, tmp_path):
        first = build_registers(_reg_doc(tmp_path, "a.pdf"), "REGTEST").registerset
        second = build_registers(_reg_doc(tmp_path, "b.pdf"), "REGTEST").registerset
        ids = [r.id for r in first.registers]
        assert len(set(ids)) == len(ids)
        assert ids == [r.id for r in second.registers]

    def test_every_register_resolves_back_to_its_record_and_printed_page(self, tmp_path):
        """Invariant 8's check, run the way a card will run it."""
        build = build_registers(_reg_doc(tmp_path), "REGTEST")
        doc_dir = tmp_path / "docs" / "register_map-deadbeef"
        write_registerset(doc_dir, build.registerset)

        for record in build.registerset.registers:
            source = f"{REGISTERS_ARTIFACT}#{record.id}"
            assert parse_source(source) == (REGISTERS_ARTIFACT, record.id)
            resolved = resolve_source(source, roots=doc_dir)
            assert resolved is not None, source
            assert resolved.record["name"] == record.name
            assert resolved.page == record.page == 1

    def test_a_document_with_no_register_table_yields_nothing(self, tmp_path):
        build = build_registers(_reg_doc(tmp_path, "prose.pdf", rows=[]), "REGTEST")
        assert build.registerset is None
        assert build.n_registers == 0
        assert build.rejection_reasons == ()


class TestAddressParsing:
    """Both forms, and `None` as a first-class outcome."""

    def test_a_printed_number_that_does_not_parse_stays_verbatim_only(self, tmp_path):
        """`Note 2` in the reset column is real, printed, and not a number."""
        build = build_registers(_reg_doc(tmp_path), "REGTEST")
        note = next(r for r in build.registerset.registers if r.name == "NCO_FTW")
        assert note.reset.verbatim == "Note 2"
        assert note.reset.value is None
        # ... and nothing invented one for it.
        assert note.reset.model_dump() == {"verbatim": "Note 2", "value": None}

    def test_a_hex_column_is_read_as_hex_for_every_row_in_it(self, tmp_path):
        """`0x10` and `10` in one column are 16 and 16, never 16 and ten."""
        rows = [
            ["0x0A", "REG_A", "0x00", "R/W"],
            ["10", "REG_B", "0x00", "R/W"],
            ["1F", "REG_C", "0x00", "R/W"],
        ]
        build = build_registers(_reg_doc(tmp_path, "hex.pdf", rows=rows), "REGTEST")
        assert [r.address.value for r in build.registerset.registers] == [10, 16, 31]

    def test_a_query_has_no_column_so_it_is_read_on_its_own_terms(self):
        assert parse_query_address("0x1A04") == 6660
        assert parse_query_address("0x1a04") == 6660
        assert parse_query_address("1A04h") == 6660
        assert parse_query_address("6660") == 6660
        # A bare hex string is genuinely ambiguous with no column to judge it.
        assert parse_query_address("1A04") is None
        assert parse_query_address("") is None
        assert parse_query_address("R12") is None

    def test_the_derivation_is_named_on_every_parsed_address(self, tmp_path):
        build = build_registers(_reg_doc(tmp_path), "REGTEST")
        part = PartRegisters(part="REGTEST", sets=(("doc", build.registerset),))
        hit = find_registers(part, addr="0x1A04")[0]
        assert hit.as_dict()["address_derivation"] == ADDRESS_DERIVATION == "parse_address"


class TestRejection:
    """A table that fails validation is refused whole, and says why."""

    DUPES: ClassVar[list[list[str]]] = [
        ["0x1A04", "TXDIG_CTRL0", "0x00", "R/W"],
        ["0x1A04", "TXDIG_CTRL1", "0x0F", "RO"],
        ["0x1A08", "NCO_FTW", "0x00", "R/W"],
    ]
    BACKWARDS: ClassVar[list[list[str]]] = [
        ["0x1A08", "NCO_FTW", "0x00", "R/W"],
        ["0x1A04", "TXDIG_CTRL0", "0x00", "R/W"],
        ["0x1A0C", "GAIN_CTRL", "0x80", "R/W"],
    ]

    def test_duplicate_addresses_publish_nothing_and_record_the_reason(self, tmp_path):
        build = build_registers(_reg_doc(tmp_path, "dupe.pdf", rows=self.DUPES), "REGTEST")
        assert build.registerset is None
        assert build.n_registers == 0
        assert any("duplicate key" in r for r in build.rejection_reasons)

    def test_an_address_that_steps_backwards_rejects_the_table(self, tmp_path):
        build = build_registers(_reg_doc(tmp_path, "back.pdf", rows=self.BACKWARDS), "REGTEST")
        assert build.registerset is None
        assert any("does not follow" in r for r in build.rejection_reasons)

    def test_the_reason_lands_where_dsa_status_already_prints_rejections(self, tmp_path):
        build = build_registers(_reg_doc(tmp_path, "dupe.pdf", rows=self.DUPES), "REGTEST")
        stats = record_register_rejections(ExtractionStats(backend="pdf_layout"), build)
        assert any("duplicate key" in r for r in stats.rejection_reasons)

    def test_rejection_recording_tolerates_a_document_with_no_stats(self):
        assert record_register_rejections(None, RegisterBuild(rejection_reasons=("x",))) is None


class TestHonestGaps:
    """What the map did not print is stated, never filled in."""

    def test_a_map_with_no_reset_or_access_column_says_so(self, tmp_path):
        rows = [
            ["0x0", "R0", "", ""],
            ["0x2", "R2", "", ""],
            ["0x3", "R3", "", ""],
        ]
        build = build_registers(
            _reg_doc(tmp_path, "thin.pdf", rows=rows, headers=["Address", "Acronym", "", ""]),
            "REGTEST",
        )
        assert [r.name for r in build.registerset.registers] == ["R0", "R2", "R3"]
        assert all(
            r.reset.verbatim == "" and r.reset.value is None for r in build.registerset.registers
        )
        warning = " ".join(build.warnings)
        assert "prints no reset or access column" in warning
        assert "3 registers" in warning

    def test_a_printed_row_that_carried_no_readable_address_is_reported(self, tmp_path):
        """Dropping a register silently reads as "this register does not exist"."""
        rows = [
            ["0x1A04", "TXDIG_CTRL0", "0x00", "R/W"],
            ["TBD", "TXDIG_CTRL1", "0x0F", "RO"],
            ["0x1A08", "NCO_FTW", "0x00", "R/W"],
            ["0x1A0C", "GAIN_CTRL", "0x80", "R/W"],
        ]
        build = build_registers(_reg_doc(tmp_path, "tbd.pdf", rows=rows), "REGTEST")
        assert [r.name for r in build.registerset.registers] == [
            "TXDIG_CTRL0",
            "NCO_FTW",
            "GAIN_CTRL",
        ]
        assert any("carried no readable address" in w for w in build.warnings)

    def test_the_unparsed_address_population_is_reported_rather_than_dropped(self):
        """Hand-built records: the report is the contract, not the parser."""
        good = RegisterRecord(name="A", address=RegisterValue(verbatim="0x00", value=0))
        bad = RegisterRecord(name="B", address=RegisterValue(verbatim="0x1G"), row_index=1)
        from datasheet_analyzer.derive.registers import _unparsed_warning

        (warning,) = _unparsed_warning([good, bad])
        assert "1 of 2 addresses did not parse" in warning
        assert "0x1G" in warning


class TestArtifact:
    """`registers.json`: written once, part-neutral, never half-written."""

    def test_a_shared_document_publishes_a_part_neutral_file(self, tmp_path):
        regset = _handmade_set(RegisterRecord(name="R0"))
        path = write_registerset(tmp_path / "doc", regset, shared=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["part_number"] == ""
        assert data["schema_version"] == REGISTERS_SCHEMA_VERSION
        # The in-memory set is untouched by the blanking.
        assert regset.part_number == "REGTEST"

    def test_rewriting_identical_bytes_leaves_no_temporary_files(self, tmp_path):
        regset = _handmade_set(RegisterRecord(name="R0"))
        doc = tmp_path / "doc"
        first = write_registerset(doc, regset)
        stamp = first.stat().st_mtime_ns
        second = write_registerset(doc, regset)
        assert second == first
        assert first.stat().st_mtime_ns == stamp
        assert [p.name for p in doc.iterdir()] == [REGISTERS_ARTIFACT]

    def test_a_missing_or_unreadable_file_reads_as_none(self, tmp_path):
        assert load_registerset(tmp_path) is None
        (tmp_path / REGISTERS_ARTIFACT).write_text("{not json", encoding="utf-8")
        assert load_registerset(tmp_path) is None

    def test_a_part_with_no_manifest_holds_no_registers(self, tmp_path):
        loaded = load_part_registers(tmp_path / "NOPART", "NOPART")
        assert loaded.sets == () and loaded.registers == ()


class TestLookup:
    """One question, one register — whichever way the address is written."""

    @pytest.fixture
    def part(self, tmp_path) -> PartRegisters:
        build = build_registers(_reg_doc(tmp_path), "REGTEST")
        return PartRegisters(part="REGTEST", sets=(("register_map-abcd1234", build.registerset),))

    def test_every_written_form_of_one_address_finds_one_register(self, part):
        for query in ("0x1A04", "0x1a04", "0X1A04", "1A04h", "6660"):
            hits = find_registers(part, addr=query)
            assert [h.record.name for h in hits] == ["TXDIG_CTRL0"], query
            assert hits[0].matched_via == "address"

    def test_a_name_is_a_substring_and_the_filters_are_one_question(self, part):
        assert [h.record.name for h in find_registers(part, name="txdig")] == [
            "TXDIG_CTRL0",
            "TXDIG_CTRL1",
        ]
        # name + address is one question, not two.
        assert find_registers(part, name="TXDIG", addr="0x1A08") == []
        assert len(find_registers(part, name="TXDIG", addr="0x1A05")) == 1

    def test_a_hit_carries_the_citation_a_reader_verifies_it_by(self, part):
        hit = find_registers(part, addr="6660")[0]
        assert hit.citation.label == "§5, p.1"
        assert hit.citation.part == "REGTEST"
        payload = hit.as_dict()
        assert payload["address"] == {"verbatim": "0x1A04", "value": 6660}
        assert payload["reset"] == {"verbatim": "0x00", "value": 0}
        assert payload["page"] == 1
        assert payload["confidence"] == "high"
        assert payload["id"] == register_record_id(0, 0)

    def test_an_unparsed_address_is_findable_by_its_printed_form_only(self):
        record = RegisterRecord(name="MYSTERY", address=RegisterValue(verbatim="0x1G"))
        part = PartRegisters(part="REGTEST", sets=(("doc", _handmade_set(record)),))
        assert [h.record.name for h in find_registers(part, addr="0x1G")] == ["MYSTERY"]
        assert find_registers(part, addr="0") == []

    def test_bit_field_questions_are_told_apart_from_no_match(self, part):
        assert part.has_bit_fields is False
        assert find_registers(part, field="NCO") == []
        assert "no bit-field records" in no_bit_fields_message("REGTEST")
        assert "no register map was published" in no_registers_message("REGTEST")

    def test_rendering_prints_what_the_page_prints(self, part):
        rendered = format_register_hits(find_registers(part))
        assert "0x1A04  TXDIG_CTRL0  reset 0x00  access R/W  (p.1)" in rendered
        # The register whose reset is a footnote pointer prints that pointer.
        assert "reset Note 2" in rendered
        assert format_register_hits([]) == "No matching registers."

    def test_the_hit_limit_says_how_many_it_held_back(self, part):
        records = [
            RegisterRecord(name=f"R{i}", address=RegisterValue(verbatim=hex(i), value=i))
            for i in range(5)
        ]
        many = PartRegisters(part="REGTEST", sets=(("doc", _handmade_set(*records)),))
        rendered = format_register_hits(find_registers(many), limit=2)
        assert "and 3 more matches" in rendered


class TestCli:
    """`dsa regs` over a corpus the real pipeline built, end to end."""

    @pytest.fixture
    def built(self, tmp_path, monkeypatch):
        pdf = _build_pdf(tmp_path / "regtest.pdf", [REG_HEADERS] + REG_ROWS)
        parts = tmp_path / "parts"
        monkeypatch.setenv("DSA_PARTS_DIR", str(parts))
        monkeypatch.setenv("DSA_CACHE_DIR", str(tmp_path / ".cache"))
        reset_settings_cache()
        settings = Settings(
            parts_dir=parts, cache_dir=tmp_path / ".cache", library_dir=tmp_path / "library"
        ).resolve()
        result = build_part(
            pdf, part_number="REGTEST", settings=settings, vendor="adi", use_llm=False
        )
        yield result
        reset_settings_cache()

    def _doc_dir(self, built) -> Path:
        return document_dirs(built.manifest, part_dir=built.part_dir)[
            built.manifest.documents[0].content_hash
        ]

    def test_the_pipeline_publishes_registers_json_beside_the_other_artifacts(self, built):
        path = self._doc_dir(built) / REGISTERS_ARTIFACT
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == REGISTERS_SCHEMA_VERSION
        assert data["part_number"] == ""  # shared artifacts are part-neutral
        assert [r["address"]["value"] for r in data["registers"]] == [6660, 6661, 6664, 6668]
        assert data["registers"][0]["id"] == register_record_id(0, 0)

        loaded = load_part_registers(built.part_dir, "REGTEST")
        assert [r.name for r in loaded.registers] == [
            "TXDIG_CTRL0",
            "TXDIG_CTRL1",
            "NCO_FTW",
            "GAIN_CTRL",
        ]

    def test_regs_answers_address_to_name_and_name_to_reset(self, built, capsys):
        assert cli_regs(_args(part="REGTEST", addr="0x1A04")) == 0
        out = capsys.readouterr().out
        assert "TXDIG_CTRL0" in out and "p.1" in out

        assert cli_regs(_args(part="REGTEST", name="TXDIG_CTRL1", json=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert [h["reset"]["verbatim"] for h in payload["hits"]] == ["0x0F"]
        assert [h["access"] for h in payload["hits"]] == ["RO"]
        assert payload["hits"][0]["citation"] == "§5, p.1"

    def test_the_three_written_forms_of_one_address_answer_identically(self, built, capsys):
        payloads = []
        for query in ("0x1A04", "0x1a04", "6660"):
            assert cli_regs(_args(part="REGTEST", addr=query, json=True)) == 0
            payloads.append(json.loads(capsys.readouterr().out)["hits"])
        assert payloads[0] == payloads[1] == payloads[2]
        assert [h["name"] for h in payloads[0]] == ["TXDIG_CTRL0"]

    def test_no_match_is_exit_1_and_a_bad_scope_is_exit_2(self, built, capsys):
        assert cli_regs(_args(part="REGTEST", addr="0xFFFF")) == 1
        assert "No matching registers." in capsys.readouterr().out
        assert cli_regs(_args()) == 2
        assert cli_regs(_args(part="REGTEST", project="p")) == 2
        assert cli_regs(_args(part="NOPE")) == 2

    def test_a_part_without_a_register_map_says_so_instead_of_answering_nothing(
        self, built, capsys
    ):
        (self._doc_dir(built) / REGISTERS_ARTIFACT).unlink()
        assert cli_regs(_args(part="REGTEST")) == 1
        captured = capsys.readouterr()
        assert "no register map was published" in captured.err
        assert "No matching registers." in captured.out

    def test_a_field_question_against_a_summary_only_corpus_says_which_is_missing(
        self, built, capsys
    ):
        assert cli_regs(_args(part="REGTEST", field="NCO_EN")) == 1
        assert "no bit-field records are published" in capsys.readouterr().err

    def test_a_project_scope_labels_every_hit_with_its_part(
        self, built, capsys, tmp_path, monkeypatch
    ):
        """`--project` is a frozen flag, so it is exercised, not assumed."""
        from datasheet_analyzer.projects import add_parts, new_project, save_project

        projects = tmp_path / "projects"
        monkeypatch.setenv("DSA_PROJECTS_DIR", str(projects))
        reset_settings_cache()
        project = new_project("bring-up", projects)
        add_parts(project, ["REGTEST"], parts_dir=built.part_dir.parent)
        save_project(project, projects)

        assert cli_regs(_args(project="bring-up", addr="0x1A05")) == 0
        assert "[REGTEST]" in capsys.readouterr().out
        assert cli_regs(_args(project="nope")) == 2


def _args(**kwargs) -> argparse.Namespace:
    """The frozen `dsa regs` namespace, as `cli.py` builds it."""
    return argparse.Namespace(
        part=kwargs.get("part", ""),
        project=kwargs.get("project", ""),
        name=kwargs.get("name", ""),
        addr=kwargs.get("addr", ""),
        field=kwargs.get("field", ""),
        json=kwargs.get("json", False),
    )
