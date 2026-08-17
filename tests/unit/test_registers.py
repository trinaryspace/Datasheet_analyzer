"""Registers (phase 6, ticket 05) — `registers.json`, `dsa regs`, and routing.

The second consumer of the device-table abstraction. The gate
(`tests/integration/test_phase6_registers.py`) proves it against the real
LMX1204 programmer's guide; what is proven *here* is every rule on its own,
and — the point of a rule test — that each one fails for the right reason:

- an **address carries both forms**, and the parsed one is allowed to fail: a
  cell the anchored grammar cannot read stays verbatim-only rather than being
  guessed at from its leading digits;
- **`--addr` resolves by value**, so `0x1A04`, `0x1a04` and `6660` are one
  question, while a register whose address never parsed is still reachable by
  typing exactly what the page printed;
- a **register table failing validation is rejected whole, with a recorded
  reason** — never emitted half-parsed, and never leaving a stale
  `registers.json` behind;
- a **reset is read only where the document prints one**: the summary table's
  own column, else the register's printed declaration heading, joined on the
  parsed offset and refused when the heading names a different register. A
  register the document declares nothing for publishes `reset: null`, and the
  set says how many did;
- **access is verbatim or absent** — a document that prints an access column
  gets one, and LMX1204's, which prints none, gets `""` rather than a guess;
- a register lookup **never reads absence into a corpus with no register
  summary** (`register_gap`, the twin of `pin_gap`), and `dsa regs` exits 2;
- **`REGISTER_MAP` routes to the layout floor**, and every other companion
  type keeps `pdf_text` exactly as before.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from datasheet_analyzer.config import (
    PIPELINE_VERSION,
    REGISTERS_SCHEMA_VERSION,
    Settings,
)
from datasheet_analyzer.evalh.citations import verify_reg_queries
from datasheet_analyzer.evalh.golden import render_reg_query_report
from datasheet_analyzer.models import (
    RECONSTRUCTION_HEADER,
    RECONSTRUCTION_RESCUED,
    Confidence,
    DocType,
    ExtractionStats,
    GoldenQuestion,
    RawDocument,
    SectionNode,
    SourceDocument,
    TableBlock,
)
from datasheet_analyzer.provenance import resolve_source, source_ref
from datasheet_analyzer.publish import registers_current, write_corpus
from datasheet_analyzer.retrieve import Retriever, clear_index_cache
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.structure.registers import (
    RESET_COLUMN_DERIVATION,
    RESET_HEADING_DERIVATION,
    build_registerset,
    parse_register_word,
    read_declarations,
)
from datasheet_analyzer.vendor import select_backend

DOC_HASH = "cafe" + "0" * 60
DOC = f"register_map-{DOC_HASH[:8]}"

REG_HEADERS = ["Address", "Acronym", "Features Requiring This Register", "Section"]
REG_ROWS = [
    ["0x0", "R0", "Powerdown, Reset, Multiplier Mode Calibration", "Go"],
    ["0x2", "R2", "Multiplier Mode (State Machine Clock)", "Go"],
    ["0x1A04", "TXDIG_CTRL0", "Transmit digital control", "Go"],
]

#: The declaration heading TI prints above each register's field table. Only
#: two of the three rows above are declared, which is the measured shape: the
#: set has to be able to say so.
DECLARATIONS = [
    "1.1 R0 Register (Offset = 0x0) [Reset = 0x0000]",
    "1.2 R2 Register (Offset = 0x2) [Reset = 0x0223]",
]


def _table(**kwargs) -> TableBlock:
    defaults = {
        "caption": "Table 1-1. LMX1204 Registers",
        "headers": list(REG_HEADERS),
        "grid": [list(row) for row in REG_ROWS],
        "page": 2,
        "reconstruction": RECONSTRUCTION_HEADER,
    }
    return TableBlock(**{**defaults, **kwargs})


def _section(**kwargs) -> SectionNode:
    defaults = {
        "number": "1",
        "title": "Device Registers",
        "page_start": 2,
        "page_end": 2,
        "paragraphs": list(DECLARATIONS),
    }
    return SectionNode(**{**defaults, **kwargs})


def _raw(sections: list[SectionNode] | None = None, **kwargs) -> RawDocument:
    defaults = {
        "source": SourceDocument(
            content_hash=DOC_HASH, path="regmap.pdf", part_number="TESTPART",
            doc_type=DocType.REGISTER_MAP, page_count=25,
        ),
        "sections": sections if sections is not None else [_section(tables=[_table()])],
        "extractor": "pdf_layout",
        "extractor_version": "test-1",
        "extraction_stats": ExtractionStats(backend="pdf_layout"),
    }
    return RawDocument(**{**defaults, **kwargs})


def _build(part_dir: Path, raw: RawDocument | None = None) -> Path:
    """A corpus written by the real publisher, so `registers.json` lands where
    the retrieval core looks for it."""
    raw = _raw() if raw is None else raw
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        f"# {part_dir.name}\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        registersets=[build_registerset(raw, part_dir.name)],
    )
    clear_index_cache()
    return part_dir


class TestRegisterWordGrammar:
    """An address carries both forms, and the parsed one may honestly fail."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("0x1A04", 6660),
            ("0x1a04", 6660),
            ("0X0", 0),
            ("1A04h", 6660),
            ("1a04H", 6660),
            ("12", 12),          # bare digits are decimal, not hex
            ("0x5A", 90),
            (" 0x2 ", 2),
        ],
    )
    def test_every_printed_form_reads_as_the_same_integer(self, text, expected):
        assert parse_register_word(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "0x00-0xFF",        # an address *block*, not one register
            "See Table 7-1",
            "0x1A04 (reserved)",
            "R12",
            "0xZZ",
            # bare hex with no marker: the base is the document's, not ours
            "AB",
            "0A",
        ],
    )
    def test_anything_that_is_not_wholly_a_word_parses_to_nothing(self, text):
        assert parse_register_word(text) is None

    def test_a_cell_that_will_not_parse_keeps_its_printed_form(self):
        raw = _raw([_section(tables=[_table(grid=[["AB", "R0", "Odd", "Go"]])])])
        (record,) = build_registerset(raw, "TESTPART").registers
        assert record.address.verbatim == "AB"
        assert record.address.value is None
        # ...and the grade says so rather than the record looking sound.
        assert record.confidence is Confidence.MEDIUM


class TestRegistersArePublishedWholeOrNotAtAll:
    def test_the_summary_table_becomes_one_record_per_address(self):
        result = build_registerset(_raw(), "TESTPART")
        assert [r.address.verbatim for r in result.registers] == ["0x0", "0x2", "0x1A04"]
        assert [r.address.value for r in result.registers] == [0, 2, 6660]
        assert [r.name for r in result.registers] == ["R0", "R2", "TXDIG_CTRL0"]
        assert [r.id for r in result.registers] == ["reg_1", "reg_2", "reg_3"]
        assert result.schema_version == REGISTERS_SCHEMA_VERSION

    def test_every_record_quotes_the_row_it_came_from(self):
        for record in build_registerset(_raw(), "TESTPART").registers:
            assert record.row_verbatim in [list(row) for row in REG_ROWS]
            assert record.page == 2

    def test_a_duplicate_address_rejects_the_whole_table_with_a_reason(self):
        raw = _raw([_section(tables=[_table(grid=[
            ["0x0", "R0", "Powerdown", "Go"],
            ["0x0", "R0_ALIAS", "Powerdown again", "Go"],
        ])])])
        result = build_registerset(raw, "TESTPART")
        assert result.registers == []
        reasons = raw.extraction_stats.rejection_reasons
        assert any("duplicate address" in r for r in reasons), reasons
        assert any(r.startswith("device-table (register)") for r in reasons)

    def test_addresses_out_of_order_reject_the_whole_table(self):
        raw = _raw([_section(tables=[_table(grid=[
            ["0x10", "R16", "SYSREF", "Go"],
            ["0x2", "R2", "Multiplier Mode", "Go"],
        ])])])
        result = build_registerset(raw, "TESTPART")
        assert result.registers == []
        assert any(
            "out of order" in r for r in raw.extraction_stats.rejection_reasons
        ), raw.extraction_stats.rejection_reasons

    def test_a_rejected_table_publishes_no_file_and_deletes_a_stale_one(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        published = part / "docs" / DOC / "registers.json"
        assert published.exists(), "fixture precondition: the good table publishes"

        broken = _raw([_section(tables=[_table(grid=[
            ["0x0", "R0", "Powerdown", "Go"],
            ["0x0", "R0", "Powerdown", "Go"],
        ])])])
        _build(part, broken)
        assert not published.exists(), (
            "a republish that yields no registers must take the superseded file "
            "with it — a corpus may never serve a rejected register map"
        )

    def test_a_document_with_no_register_table_records_nothing(self):
        """An absence in the document is not a finding about the extraction."""
        raw = _raw([_section(tables=[], paragraphs=["Prose only."])])
        result = build_registerset(raw, "TESTPART")
        assert result.registers == []
        assert raw.extraction_stats.rejection_reasons == []

    def test_a_pdf_text_document_is_skipped_entirely(self):
        """The degraded backend carries no trusted tables (`build_specset`'s rule)."""
        raw = _raw(extractor="pdf_text")
        assert build_registerset(raw, "TESTPART").registers == []


class TestResetIsReadOnlyWhereItIsPrinted:
    def test_the_declaration_heading_supplies_the_reset(self):
        registers = build_registerset(_raw(), "TESTPART").registers
        by_name = {r.name: r for r in registers}
        assert by_name["R0"].reset.verbatim == "0x0000"
        assert by_name["R0"].reset.value == 0
        assert by_name["R2"].reset.verbatim == "0x0223"
        assert by_name["R2"].reset.value == 0x223
        assert by_name["R2"].reset.derivation == RESET_HEADING_DERIVATION
        assert "R2 Register (Offset = 0x2)" in by_name["R2"].reset.evidence

    def test_a_register_the_document_declares_nothing_for_stays_null(self):
        registers = build_registerset(_raw(), "TESTPART").registers
        undeclared = next(r for r in registers if r.name == "TXDIG_CTRL0")
        assert undeclared.reset is None

    def test_the_set_reports_how_many_registers_state_a_reset(self):
        result = build_registerset(_raw(), "TESTPART")
        assert result.n_reset_stated == 2
        assert any(
            "reset value stated for 2 of 3 registers" in w for w in result.warnings
        ), result.warnings

    def test_a_fully_declared_set_says_nothing(self):
        raw = _raw([_section(
            tables=[_table(grid=[list(REG_ROWS[0]), list(REG_ROWS[1])])],
            paragraphs=list(DECLARATIONS),
        )])
        result = build_registerset(raw, "TESTPART")
        assert result.n_reset_stated == 2
        assert result.warnings == []

    def test_the_join_is_on_the_offset_and_refuses_a_contradicting_name(self, caplog):
        """`R0` at offset 0x2 is a misread, not a reset to publish."""
        raw = _raw([_section(
            tables=[_table(grid=[["0x2", "R2", "Multiplier Mode", "Go"]])],
            paragraphs=["1.9 R9 Register (Offset = 0x2) [Reset = 0x001E]"],
        )])
        with caplog.at_level(logging.WARNING):
            (record,) = build_registerset(raw, "TESTPART").registers
        assert record.reset is None
        assert "declared as 'R9'" in caplog.text

    def test_a_reset_column_on_the_row_wins_over_a_heading(self):
        raw = _raw([_section(
            tables=[_table(
                headers=["Address", "Acronym", "Reset", "Description"],
                grid=[["0x0", "R0", "0x1234", "Powerdown"]],
            )],
            paragraphs=list(DECLARATIONS),
        )])
        (record,) = build_registerset(raw, "TESTPART").registers
        assert record.reset.verbatim == "0x1234"
        assert record.reset.value == 0x1234
        assert record.reset.derivation == RESET_COLUMN_DERIVATION

    def test_declarations_are_read_from_a_tables_conditions_preamble_too(self):
        """The layout floor parks the lines above a caption in `conditions`;
        measured on LMX1204, 17 of 35 declarations land there."""
        raw = _raw([_section(
            tables=[
                _table(),
                TableBlock(
                    caption="Table 1-3. R0 Register Field Descriptions",
                    conditions=DECLARATIONS[0] + " R0 is shown in Table 1-3.",
                    headers=["Bit", "Field", "Type", "Reset", "Description"],
                    grid=[["0", "RESET", "R/W", "0x0", "Soft Reset."]],
                    page=4,
                ),
            ],
            paragraphs=[],
        )])
        declarations = read_declarations(raw)
        assert [d.name for d in declarations] == ["R0"]
        assert declarations[0].reset_verbatim == "0x0000"
        # the page comes from the table the preamble belongs to, so a reset
        # read out of a paragraph still cites the page it was printed on
        assert declarations[0].page == 4

    def test_the_page_is_the_region_the_lines_were_printed_in(self):
        """`pin_table_pages` rewrites `TableBlock.page` by matching cell text,
        and a field table of `R`, `R/W`, `0x0` and `RESERVED` matches half the
        document — LMX1204's Table 1-25 pins to p.17 while it is printed on
        p.19. The row pages are not rewritten, so they are what a preamble
        cites."""
        raw = _raw([_section(tables=[
            _table(),
            TableBlock(
                caption="Table 1-3. R0 Register Field Descriptions",
                conditions=DECLARATIONS[0],
                headers=["Bit", "Field", "Type", "Reset", "Description"],
                grid=[["0", "RESET", "R/W", "0x0", "Soft Reset."]],
                page=17,           # what pinning decided
                row_pages=[19],    # where the region actually was
            ),
        ], paragraphs=[])])
        (declaration,) = read_declarations(raw)
        assert declaration.page == 19

    def test_a_paragraph_declaration_is_pinned_through_its_field_table(self):
        raw = _raw([_section(tables=[
            _table(),
            TableBlock(
                caption="Table 1-4. R2 Register Field Descriptions",
                headers=["Bit", "Field", "Type", "Reset", "Description"],
                grid=[["0", "SMCLK_EN", "R/W", "0x1", "Enables the clock."]],
                page=17,
                row_pages=[4],
            ),
        ], paragraphs=[DECLARATIONS[1]])])
        (declaration,) = read_declarations(raw)
        assert declaration.name == "R2"
        assert declaration.page == 4

    def test_a_declaration_with_nothing_to_pin_it_cites_no_page(self):
        """Honest `None` beats a page the heading was not printed on."""
        raw = _raw([_section(tables=[_table()], paragraphs=[DECLARATIONS[0]])])
        (declaration,) = read_declarations(raw)
        assert declaration.page is None
        (record,) = [
            r for r in build_registerset(raw, "TESTPART").registers if r.name == "R0"
        ]
        assert record.reset.verbatim == "0x0000"
        assert record.reset.page is None

    def test_a_heading_with_no_reset_contributes_nothing(self):
        raw = _raw([_section(
            tables=[_table(grid=[["0x0", "R0", "Powerdown", "Go"]])],
            paragraphs=["1.1 R0 Register (Offset = 0x0)"],
        )])
        assert read_declarations(raw) == []
        (record,) = build_registerset(raw, "TESTPART").registers
        assert record.reset is None


class TestAccessIsVerbatimOrAbsent:
    def test_an_access_column_is_published_as_printed(self):
        raw = _raw([_section(tables=[_table(
            headers=["Address", "Register Name", "Reset", "Access"],
            grid=[
                ["0x00", "CONFIG", "0x00", "R/W"],
                ["0x01", "STATUS", "0x00", "R"],
            ],
        )])])
        registers = build_registerset(raw, "TESTPART").registers
        assert [r.access for r in registers] == ["R/W", "R"]
        assert [r.reset.verbatim for r in registers] == ["0x00", "0x00"]

    def test_a_document_with_no_access_column_publishes_no_access(self):
        """LMX1204's shape: TI states access per bit field, not per register."""
        for record in build_registerset(_raw(), "TESTPART").registers:
            assert record.access == ""


class TestConfidenceGrade:
    def test_a_rescued_grid_grades_low(self):
        raw = _raw([_section(tables=[_table(reconstruction=RECONSTRUCTION_RESCUED)])])
        for record in build_registerset(raw, "TESTPART").registers:
            assert record.confidence is Confidence.LOW

    def test_a_row_with_no_acronym_grades_low(self):
        raw = _raw([_section(tables=[_table(grid=[
            ["0x0", "R0", "Powerdown", "Go"],
            ["0x2", "", "Multiplier Mode", "Go"],
        ])])])
        registers = build_registerset(raw, "TESTPART").registers
        assert [r.confidence for r in registers][-1] is Confidence.LOW

    def test_a_header_declared_pinned_row_grades_high(self):
        for record in build_registerset(_raw(), "TESTPART").registers:
            assert record.confidence is Confidence.HIGH


class TestPublishedArtifact:
    def test_registers_json_is_written_with_its_schema_version(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        payload = json.loads(
            (part / "docs" / DOC / "registers.json").read_text(encoding="utf-8")
        )
        assert payload["schema_version"] == REGISTERS_SCHEMA_VERSION
        assert len(payload["registers"]) == 3
        assert payload["registers"][0]["address"] == {
            "verbatim": "0x0",
            "value": 0,
            "page": 2,
            "evidence": "",
            "derivation": "parse_register_word",
        }
        assert registers_current(part / "docs" / DOC)

    def test_the_reset_coverage_warning_lands_in_the_manifest(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        manifest = json.loads((part / "manifest.json").read_text(encoding="utf-8"))
        assert any(
            "reset value stated for 2 of 3 registers" in w
            for w in manifest["derived_warnings"]
        ), manifest["derived_warnings"]
        assert manifest["stats"]["n_registers"] == 3
        assert manifest["stats"]["register_confidence"] == {
            "high": 3, "medium": 0, "low": 0
        }

    def test_a_published_record_id_resolves_back_to_the_record(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        ref = source_ref("reg_3", artifact="registers.json", doc=DOC)
        resolved = resolve_source(part, ref)
        assert resolved is not None
        assert resolved.record.name == "TXDIG_CTRL0"
        assert resolved.page == 2

    def test_an_older_schema_is_not_current(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        path = part / "docs" / DOC / "registers.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema_version"] = "0"
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert not registers_current(path.parent)

    def test_a_missing_file_reads_as_current(self, tmp_path):
        """Almost no document prints a register summary; demanding one would
        rebuild those parts forever."""
        assert registers_current(tmp_path)


class TestRegisterLookup:
    def test_addr_resolves_by_value_in_every_printed_notation(self, tmp_path):
        retriever = Retriever.for_part(_build(tmp_path / "TESTPART"))
        for spelling in ("0x1A04", "0x1a04", "1A04h", "6660"):
            (hit,) = retriever.registers(addr=spelling)
            assert hit.record.name == "TXDIG_CTRL0", spelling
            assert hit.matched_via == "address"

    def test_an_unparseable_address_still_matches_what_the_page_printed(self, tmp_path):
        raw = _raw([_section(tables=[_table(grid=[["AB", "R0", "Odd", "Go"]])])])
        retriever = Retriever.for_part(_build(tmp_path / "TESTPART", raw))
        assert [h.record.name for h in retriever.registers(addr="ab")] == ["R0"]
        # ...and never by the integer *someone else's* base would have given it
        assert retriever.registers(addr="171") == []

    def test_name_is_exact_and_q_is_a_substring(self, tmp_path):
        retriever = Retriever.for_part(_build(tmp_path / "TESTPART"))
        assert [h.record.name for h in retriever.registers(name="r0")] == ["R0"]
        assert retriever.registers(name="R") == []
        assert [h.record.name for h in retriever.registers(q="Multiplier")] == ["R0", "R2"]
        assert len(retriever.registers()) == 3

    def test_a_hit_carries_its_citation_and_both_address_forms(self, tmp_path):
        retriever = Retriever.for_part(_build(tmp_path / "TESTPART"))
        (hit,) = retriever.registers(name="R2")
        assert hit.citation.label == "§1, p.2"
        payload = hit.as_dict()
        assert payload["address"] == "0x2"
        assert payload["address_value"] == 2
        assert payload["reset"]["verbatim"] == "0x0223"
        assert payload["reset"]["derivation"] == RESET_HEADING_DERIVATION
        assert payload["confidence"] == "high"

    def test_a_register_with_no_reset_serializes_it_as_null(self, tmp_path):
        retriever = Retriever.for_part(_build(tmp_path / "TESTPART"))
        (hit,) = retriever.registers(name="TXDIG_CTRL0")
        assert hit.as_dict()["reset"] is None


class TestAbsenceIsNeverAnAnswer:
    def test_a_corpus_with_no_register_summary_says_so(self, tmp_path):
        raw = _raw([_section(tables=[], paragraphs=["Prose only."])])
        retriever = Retriever.for_part(_build(tmp_path / "TESTPART", raw))
        gap = retriever.register_gap()
        assert "no register summary in the corpus" in gap
        assert "establishes nothing" in gap

    def test_a_corpus_with_registers_has_no_gap(self, tmp_path):
        assert Retriever.for_part(_build(tmp_path / "TESTPART")).register_gap() == ""

    def test_dsa_regs_exits_2_on_a_corpus_with_no_register_map(
        self, tmp_path, monkeypatch, capsys
    ):
        from datasheet_analyzer import cli

        raw = _raw([_section(tables=[], paragraphs=["Prose only."])])
        parts = tmp_path / "parts"
        _build(parts / "TESTPART", raw)
        monkeypatch.setattr(
            cli, "get_settings", lambda: Settings(parts_dir=parts).resolve()
        )
        assert cli.main(["regs", "--part", "TESTPART", "--addr", "0x0"]) == 2
        assert "establishes nothing" in capsys.readouterr().err

    def test_dsa_regs_prints_the_register_and_its_citation(
        self, tmp_path, monkeypatch, capsys
    ):
        from datasheet_analyzer import cli

        parts = tmp_path / "parts"
        _build(parts / "TESTPART")
        monkeypatch.setattr(
            cli, "get_settings", lambda: Settings(parts_dir=parts).resolve()
        )
        assert cli.main(["regs", "--part", "TESTPART", "--addr", "6660"]) == 0
        out = capsys.readouterr().out
        assert "0x1A04: TXDIG_CTRL0" in out
        # ADR 0005 at the surface a human reads: no reset is stated, so none is
        # printed — never a plausible zero.
        assert "reset=?" in out

    def test_dsa_regs_json_is_the_hits_own_shape(self, tmp_path, monkeypatch, capsys):
        from datasheet_analyzer import cli

        parts = tmp_path / "parts"
        _build(parts / "TESTPART")
        monkeypatch.setattr(
            cli, "get_settings", lambda: Settings(parts_dir=parts).resolve()
        )
        assert cli.main(["regs", "--part", "TESTPART", "--name", "R2", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["hits"][0]["address_value"] == 2
        assert payload["hits"][0]["citation"] == "§1, p.2"


class TestRegisterMapRouting:
    """The routing change this ticket makes, and the one it must not make."""

    def test_a_register_map_routes_to_the_layout_floor(self):
        for vendor in ("ti", "adi", "qorvo", "unknown"):
            assert select_backend(vendor, DocType.REGISTER_MAP) == "pdf_layout", vendor

    @pytest.mark.parametrize(
        "doc_type", [DocType.ERRATA, DocType.APP_NOTE, DocType.UNKNOWN]
    )
    def test_every_other_companion_keeps_pdf_text(self, doc_type):
        for vendor in ("ti", "adi", "qorvo", "unknown"):
            assert select_backend(vendor, doc_type) == "pdf_text", (vendor, doc_type)

    def test_a_datasheet_still_follows_its_vendors_chain(self):
        assert select_backend("ti", DocType.DATASHEET) == "ti_html"
        assert select_backend("adi", DocType.DATASHEET) == "pdf_layout"


class TestGoldenRegisterQuestions:
    """The `reg_query` marker: the pin rule, applied to registers."""

    def _question(self, **kwargs) -> GoldenQuestion:
        payload = {
            "id": "r1",
            "question": "Which register lives at 0x1A04?",
            "expected_substrings": ["TXDIG_CTRL0"],
            "pages": [2],
            "kind": "direct",
            "reg_query": {"addr": "6660"},
        }
        payload.update(kwargs)
        return GoldenQuestion.model_validate(payload)

    def test_a_cited_register_carrying_the_substrings_passes(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        (result,) = verify_reg_queries([self._question()], part)
        assert result.ok
        assert "1 cited register(s) of 1" in result.detail
        assert "Register query verification" in render_reg_query_report([result])

    def test_the_right_register_on_the_wrong_page_fails(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        (result,) = verify_reg_queries([self._question(pages=[99])], part)
        assert not result.ok
        assert result.n_records == 1 and result.n_verified == 0

    def test_the_reset_is_part_of_what_a_golden_may_assert(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        (result,) = verify_reg_queries(
            [self._question(
                expected_substrings=["R2", "0x0223"], reg_query={"name": "R2"}
            )],
            part,
        )
        assert result.ok, "a reset read from a declaration heading must be assertable"

    def test_a_count_that_drifts_fails(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        (ok,) = verify_reg_queries(
            [self._question(
                expected_substrings=["R0"],
                reg_query={"q": "Multiplier", "count": "2"},
            )],
            part,
        )
        assert ok.ok
        (bad,) = verify_reg_queries(
            [self._question(
                expected_substrings=["R0"],
                reg_query={"q": "Multiplier", "count": "3"},
            )],
            part,
        )
        assert not bad.ok
        assert "2 register(s), expected 3" in bad.detail

    def test_a_question_with_no_marker_is_not_a_register_question(self, tmp_path):
        part = _build(tmp_path / "TESTPART")
        assert verify_reg_queries([self._question(reg_query=None)], part) == []
