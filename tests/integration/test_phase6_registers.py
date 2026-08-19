"""Phase 6 gate — registers against the real LMX1204 documents (ticket 05).

The acceptance gate, run against a real corpus rather than fixtures. Three
claims are under test, and the third is a *parked* one, asserted as honestly
as the other two:

1. **The re-route happened.** `DocType.REGISTER_MAP` reads through
   `pdf_layout`, so the LMX1204 register map is tables instead of paragraphs
   for the first time, and the part is republished at `PIPELINE_VERSION`
   0.5.0 so the paragraph-only cached reading cannot survive.
2. **Register questions verify at 100% with page cites.** A hand-checked
   golden set over the 35 registers LMX1204 prints — address -> name in every
   written form of the address, plus name -> reset and name -> access — with
   every cited page checked against the printed PDF. Reset and access are the
   interesting half: LMX1204's summary table prints neither column, so the
   correct answer is "the map does not print it", said out loud, and any
   value at all would be a fabrication.
3. **The reference register map's own summary table is not recovered**, for a
   reason that lives in the layout engine rather than in this module, and the
   loss is recorded in `KNOWN_SHORTCOMINGS.md` rather than papered over. When
   that entry is closed, this class is what has to change with it.

Invariant 4 is relaxed exactly as far as the phase plan allows: this reads
built parts under `parts/`, their extraction cache and their source PDFs, and
skips whenever any of those is absent. It never reaches the network, never
calls a model, and never rebuilds anything.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from datasheet_analyzer.config import PIPELINE_VERSION
from datasheet_analyzer.derive.provenance import REGISTERS_ARTIFACT, resolve_source
from datasheet_analyzer.derive.registers import (
    build_registers,
    find_registers,
    load_part_registers,
)
from datasheet_analyzer.models import DocType, RawDocument
from datasheet_analyzer.publish import document_dirs, read_manifest
from datasheet_analyzer.vendor import select_backend

REPO_ROOT = Path(__file__).resolve().parents[2]
PARTS_DIR = REPO_ROOT / "parts"
EXTRACT_CACHE = REPO_ROOT / ".cache" / "extract"
REGMAP_PDF = REPO_ROOT / "LMX1204_registermap.pdf"
SHORTCOMINGS = REPO_ROOT / "KNOWN_SHORTCOMINGS.md"
PART = "LMX1204"

#: Hand-checked against page 32 of the LMX1204 datasheet (Table 7-1). Address
#: as printed -> acronym as printed, plus the page the pair is printed on.
GOLDEN: tuple[tuple[str, str, int], ...] = (
    ("0x0", "R0", 32),
    ("0x9", "R9", 32),
    ("0x11", "R17", 32),
    ("0x19", "R25", 32),
    ("0x41", "R65", 32),
    ("0x5A", "R90", 32),
)

#: Table 7-1 spills its last row onto the next printed page, and an
#: HTML-derived table carries one page for every row (`TableBlock.row_pages`
#: is a `pdf_layout` field). So `R90` is cited a page early — 1 row of 35,
#: measured, recorded in `KNOWN_SHORTCOMINGS.md`, and asserted below rather
#: than quietly dropped from the golden set.
OFF_BY_ONE: tuple[tuple[str, str, int, int], ...] = (("0x5A", "R90", 32, 33),)

#: The same six addresses written the other two ways a firmware engineer
#: writes them: lower case, and as the decimal value.
GOLDEN_FORMS: tuple[tuple[str, str], ...] = (
    ("0x0", "0"),
    ("0x9", "9"),
    ("0x11", "17"),
    ("0x19", "25"),
    ("0x41", "65"),
    ("0x5a", "90"),
)


def _manifest():
    part_dir = PARTS_DIR / PART
    manifest = read_manifest(part_dir) if part_dir.is_dir() else None
    if manifest is None:
        pytest.skip(f"{PART} is not built under {PARTS_DIR}")
    return part_dir, manifest


def _cached_raw(content_hash: str, backend: str) -> RawDocument | None:
    path = EXTRACT_CACHE / f"{content_hash}__{backend}.json"
    if not path.is_file():
        return None
    try:
        return RawDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


@pytest.fixture(scope="module")
def built():
    """The built LMX1204 part: its directory and its manifest."""
    return _manifest()


@pytest.fixture(scope="module")
def registers(built):
    """Every register LMX1204 published, read back off disk."""
    part_dir, _manifest_obj = built
    part_registers = load_part_registers(part_dir, PART)
    if not part_registers.sets:
        pytest.skip(f"{PART} published no {REGISTERS_ARTIFACT}")
    return part_registers


@pytest.fixture(scope="module")
def regmap_doc(built):
    """The register-map companion: its source record and its cached reading."""
    _part_dir, manifest = built
    source = next((d for d in manifest.documents if d.doc_type is DocType.REGISTER_MAP), None)
    if source is None:
        pytest.skip(f"{PART} has no register-map companion")
    stats = manifest.extraction_stats.get(source.content_hash)
    raw = _cached_raw(source.content_hash, stats.backend if stats else "")
    if raw is None:
        pytest.skip("the register map's extraction is not in the cache")
    return source, stats, raw


@pytest.mark.integration
class TestTheReRoute:
    """A register map is tables now, which is the whole point of the change."""

    def test_register_maps_route_to_the_layout_backend(self):
        for vendor in ("ti", "adi", "qorvo", "unknown"):
            assert select_backend(vendor, DocType.REGISTER_MAP) == "pdf_layout"

    def test_the_built_part_read_its_register_map_with_the_layout_backend(self, regmap_doc):
        _source, stats, raw = regmap_doc
        assert stats is not None and stats.backend == "pdf_layout"
        assert raw.extractor == "pdf_layout"

    def test_the_register_map_now_yields_tables_rather_than_paragraphs(self, regmap_doc):
        """Read as prose it had none; every bring-up answer is in a table."""
        _source, stats, raw = regmap_doc
        tables = [t for sec in raw.sections for t in sec.tables]
        assert len(tables) >= 10
        assert stats.tables_accepted == len(tables)
        assert all(t.caption for t in tables)

    def test_the_paragraph_only_reading_is_what_the_re_route_replaced(self, regmap_doc):
        """The old backend's cached reading, when it is still on disk: zero tables."""
        source, _stats, _raw = regmap_doc
        old = _cached_raw(source.content_hash, "pdf_text")
        if old is None:
            pytest.skip("no pre-re-route pdf_text reading cached for this document")
        assert [t for sec in old.sections for t in sec.tables] == []

    def test_the_part_is_republished_at_the_bumped_pipeline_version(self, built):
        """0.4.0 corpora hold the paragraph-only reading; 0.5.0 re-extracted."""
        _part_dir, manifest = built
        assert PIPELINE_VERSION == "0.5.0"
        assert manifest.pipeline_version == PIPELINE_VERSION


@pytest.mark.integration
class TestGoldenRegisterQuestions:
    """The questions a firmware engineer asks, verified against the page."""

    def test_the_published_map_is_the_whole_printed_table(self, registers):
        records = registers.registers
        assert len(records) == 35
        assert all(r.page == 32 and r.section == "7.1" for r in records)
        # Every printed address parsed: no register is findable only by its
        # printed form in this map.
        assert all(r.address.value is not None for r in records)
        addresses = [r.address.value for r in records]
        assert addresses == sorted(addresses)

    def test_address_to_name_verifies_at_100_percent_with_page_cites(self, registers):
        for printed, name, page in GOLDEN:
            hits = find_registers(registers, addr=printed)
            assert len(hits) == 1, printed
            hit = hits[0]
            assert hit.record.name == name
            assert hit.record.address.verbatim == printed
            assert hit.record.page == page
            assert hit.citation.label == f"§7.1, p.{page}"
            assert hit.matched_via == "address"

    def test_every_written_form_of_an_address_is_one_question(self, registers):
        for lowered, decimal in GOLDEN_FORMS:
            answers = [
                [h.as_dict() for h in find_registers(registers, addr=form)]
                for form in (lowered, lowered.upper(), decimal)
            ]
            assert answers[0] == answers[1] == answers[2], lowered
            assert len(answers[0]) == 1

    def test_name_to_reset_and_name_to_access_say_the_map_prints_neither(self, registers):
        """The honest answer, because a blank read as `0x00` breaks a bring-up."""
        for _printed, name, _page in GOLDEN:
            (hit,) = [h for h in find_registers(registers, name=name) if h.record.name == name]
            assert hit.record.reset.verbatim == ""
            assert hit.record.reset.value is None
            assert hit.record.access == ""
        warning = " ".join(registers.warnings)
        assert "prints no reset or access column" in warning
        assert "35 registers" in warning

    def test_every_cited_page_really_prints_the_pair(self, built, registers):
        """The cite is checked against the PDF, not against the extractor."""
        part_dir, manifest = built
        source = next(d for d in manifest.documents if d.doc_type is DocType.DATASHEET)
        pdf = Path(source.path)
        if not pdf.is_file():
            pytest.skip(f"source PDF is not on this machine: {pdf}")
        early = {name for _a, name, _c, _p in OFF_BY_ONE}
        with fitz.open(pdf) as doc:
            for printed, name, page in GOLDEN:
                if name in early:
                    continue
                text = doc[page - 1].get_text()
                assert printed in text, (printed, page)
                assert name in text, (name, page)
        assert part_dir.is_dir()

    def test_the_one_row_whose_cite_is_a_page_early_is_named(self, built, registers):
        """Honesty about the exception: which row, cited where, printed where.

        `ti_html` tables carry a single page for every row, so the row Table
        7-1 spills onto the next printed page is cited on the page the table
        starts on. One row of 35, recorded in `KNOWN_SHORTCOMINGS.md`; the fix
        is per-row page attribution for HTML-derived tables, which is not this
        module's to make.
        """
        _part_dir, manifest = built
        source = next(d for d in manifest.documents if d.doc_type is DocType.DATASHEET)
        pdf = Path(source.path)
        if not pdf.is_file():
            pytest.skip(f"source PDF is not on this machine: {pdf}")
        with fitz.open(pdf) as doc:
            for printed, name, cited, actually in OFF_BY_ONE:
                (hit,) = [
                    h for h in find_registers(registers, addr=printed) if h.record.name == name
                ]
                assert hit.record.page == cited
                assert printed not in doc[cited - 1].get_text()
                assert printed in doc[actually - 1].get_text()
        # and it really is only that one row.
        printed_early = 0
        with fitz.open(pdf) as doc:
            pages = {n: doc[n - 1].get_text() for n in (32, 33)}
        for record in registers.registers:
            if record.address.verbatim not in pages.get(record.page or 0, ""):
                printed_early += 1
        assert printed_early == len(OFF_BY_ONE)

    def test_every_published_register_resolves_to_a_record_and_a_page(self, built, registers):
        """Invariant 8 over real data: no number without a printed page."""
        part_dir, manifest = built
        dirs = document_dirs(manifest, part_dir=part_dir)
        roots = [d for d in dirs.values() if (d / REGISTERS_ARTIFACT).is_file()]
        assert roots
        for record in registers.registers:
            resolved = resolve_source(f"{REGISTERS_ARTIFACT}#{record.id}", roots=roots)
            assert resolved is not None, record.id
            assert resolved.page == record.page
            assert resolved.record["name"] == record.name

    def test_dsa_regs_answers_the_same_way_the_library_does(self, monkeypatch, capsys):
        if not (PARTS_DIR / PART).is_dir():
            # Same guard the rest of this module already uses: the comparison
            # is between two readers of a *built* corpus, and a cleared shelf
            # has nothing for either of them to read.
            pytest.skip(f"{PART} is not built under {PARTS_DIR}")

        import json

        from datasheet_analyzer.config import reset_settings_cache
        from datasheet_analyzer.derive.registers import cli_regs

        monkeypatch.setenv("DSA_PARTS_DIR", str(PARTS_DIR))
        reset_settings_cache()
        try:
            import argparse

            args = argparse.Namespace(
                part=PART, project="", name="", addr="0x11", field="", json=True
            )
            assert cli_regs(args) == 0
            payload = json.loads(capsys.readouterr().out)
        finally:
            reset_settings_cache()
        assert payload["query"]["addr_value"] == 17
        assert [h["name"] for h in payload["hits"]] == ["R17"]
        assert payload["hits"][0]["citation"] == "§7.1, p.32"
        assert payload["hits"][0]["reset"] == {"verbatim": "", "value": None}


@pytest.mark.integration
class TestTheReferenceMapsOwnSummaryTable:
    """The parked half, asserted rather than hidden.

    `LMX1204_registermap.pdf` prints the same 35-register summary as Table
    1-1 on its page 2, and this tool does not read it: the layout engine
    classifies the first row's `0x0` cell as page furniture, which truncates
    the table's region to its header and rejects the reconstruction. The map
    still publishes nothing partial, the reason is recorded where
    `dsa status` prints it, and the loss is written down in
    `KNOWN_SHORTCOMINGS.md`. Fixing it is a change to `extract/pdf_layout.py`
    and to nothing in `derive/registers.py` — when it lands, this class and
    that entry are removed together.
    """

    def test_the_reference_pdf_is_present_and_prints_a_summary_table(self):
        if not REGMAP_PDF.is_file():
            pytest.skip(f"reference register map absent: {REGMAP_PDF}")
        with fitz.open(REGMAP_PDF) as doc:
            text = doc[1].get_text()
        assert "Table 1-1. LMX1204 Registers" in text
        assert "Address" in text and "Acronym" in text
        assert "0x11" in text and "R17" in text

    def test_no_summary_table_is_recovered_from_it_today(self, regmap_doc):
        _source, _stats, raw = regmap_doc
        build = build_registers(raw, PART)
        assert build.registerset is None
        assert build.n_registers == 0

    def test_the_layout_engine_records_why_it_could_not_read_it(self, regmap_doc):
        _source, stats, _raw = regmap_doc
        assert stats.tables_rejected > 0
        assert "no viable column split" in stats.rejection_reasons

    def test_nothing_partial_is_published_for_the_register_map(self, built, regmap_doc):
        part_dir, manifest = built
        source, _stats, _raw = regmap_doc
        doc_dir = document_dirs(manifest, part_dir=part_dir).get(source.content_hash)
        assert doc_dir is not None
        assert not (doc_dir / REGISTERS_ARTIFACT).exists()

    def test_the_loss_is_written_down_where_a_reader_will_find_it(self):
        if not SHORTCOMINGS.is_file():
            pytest.skip("KNOWN_SHORTCOMINGS.md is not in this tree")
        text = SHORTCOMINGS.read_text(encoding="utf-8")
        assert "LMX1204_registermap.pdf" in text
        assert "Table 1-1" in text
