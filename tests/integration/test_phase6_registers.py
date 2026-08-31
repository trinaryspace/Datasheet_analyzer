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
3. **The reference register map's own summary table is recovered** (phase
   6.5, ticket 05). `Table 1-1` on page 2 of `LMX1204_registermap.pdf` was
   eaten by the furniture detector and published nothing; it now publishes its
   own 35 registers. The part therefore answers a register question twice —
   once from each document that prints the map — and each answer cites its own
   document and printed page.

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
    #: Table 7-1 spills its last row onto page 33, and phase 6.5 ticket 07
    #: gave HTML-derived tables per-row page pinning, so `R90` now cites the
    #: page it is printed on. Before that it was cited on 32 — the one
    #: off-by-one row this gate used to name.
    ("0x5A", "R90", 33),
)

#: The same table as the register map's own `Table 1-1` prints it: one page,
#: section `1`, all 35 rows. Hand-checked against page 2 of
#: `LMX1204_registermap.pdf`.
REGMAP_PAGE = 2
REGMAP_SECTION = "1"

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


def _set_from(part_registers, prefix: str):
    """One published register set, by the document directory it came from."""
    for name, registerset in part_registers.sets:
        if name.startswith(prefix):
            return registerset
    pytest.skip(f"no published register set from a {prefix} document")
    return None


@pytest.fixture(scope="module")
def datasheet_registers(registers):
    """`Table 7-1` of the datasheet — the map phase 6 already read."""
    return _set_from(registers, "datasheet-")


@pytest.fixture(scope="module")
def regmap_registers(registers):
    """`Table 1-1` of the register map — recovered by phase 6.5, ticket 05."""
    return _set_from(registers, "register_map-")


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

    def test_the_published_map_is_the_whole_printed_table(
        self, registers, datasheet_registers, regmap_registers
    ):
        """Both documents that print the map publish all 35 of its rows."""
        assert len(registers.sets) == 2
        assert len(registers.registers) == 70
        assert len(datasheet_registers.registers) == 35
        assert len(regmap_registers.registers) == 35
        assert all(r.section == "7.1" for r in datasheet_registers.registers)
        assert {r.page for r in datasheet_registers.registers} == {32, 33}
        assert all(
            r.section == REGMAP_SECTION and r.page == REGMAP_PAGE
            for r in regmap_registers.registers
        )
        # The two readings agree on what the table says, which is the check
        # that matters: one page prints it, another page reprints it.
        assert [r.name for r in datasheet_registers.registers] == [
            r.name for r in regmap_registers.registers
        ]
        # Every printed address parsed: no register is findable only by its
        # printed form in either map.
        for registerset in (datasheet_registers, regmap_registers):
            records = registerset.registers
            assert all(r.address.value is not None for r in records)
            addresses = [r.address.value for r in records]
            assert addresses == sorted(addresses)

    def test_address_to_name_verifies_at_100_percent_with_page_cites(self, registers):
        """Two documents print this map, so one address is two cited answers."""
        for printed, name, page in GOLDEN:
            hits = find_registers(registers, addr=printed)
            assert len(hits) == 2, printed
            assert all(h.record.name == name for h in hits)
            assert all(h.record.address.verbatim == printed for h in hits)
            assert all(h.matched_via == "address" for h in hits)
            labels = sorted(h.citation.label for h in hits)
            assert labels == sorted([f"§7.1, p.{page}", f"§{REGMAP_SECTION}, p.{REGMAP_PAGE}"]), (
                labels
            )

    def test_every_written_form_of_an_address_is_one_question(self, registers):
        for lowered, decimal in GOLDEN_FORMS:
            answers = [
                [h.as_dict() for h in find_registers(registers, addr=form)]
                for form in (lowered, lowered.upper(), decimal)
            ]
            assert answers[0] == answers[1] == answers[2], lowered
            assert len(answers[0]) == 2

    def test_name_to_reset_and_name_to_access_say_the_map_prints_neither(self, registers):
        """The honest answer, because a blank read as `0x00` breaks a bring-up."""
        for _printed, name, _page in GOLDEN:
            hits = [h for h in find_registers(registers, name=name) if h.record.name == name]
            assert len(hits) == 2, name
            for hit in hits:
                assert hit.record.reset.verbatim == ""
                assert hit.record.reset.value is None
                assert hit.record.access == ""
        warning = " ".join(registers.warnings)
        assert "prints no reset or access column" in warning
        assert "35 registers" in warning
        # Both documents say it, and each says it about its own table.
        assert sum("prints no reset or access column" in w for w in registers.warnings) == 2

    def test_every_cited_page_really_prints_the_pair(self, built, registers):
        """The cite is checked against the PDF, not against the extractor."""
        part_dir, manifest = built
        source = next(d for d in manifest.documents if d.doc_type is DocType.DATASHEET)
        pdf = Path(source.path)
        if not pdf.is_file():
            pytest.skip(f"source PDF is not on this machine: {pdf}")
        with fitz.open(pdf) as doc:
            for printed, name, page in GOLDEN:
                text = doc[page - 1].get_text()
                assert printed in text, (printed, page)
                assert name in text, (name, page)
        assert part_dir.is_dir()

    def test_no_row_cites_a_page_it_is_not_printed_on(self, built, datasheet_registers):
        """Phase 6.5, ticket 07 — the off-by-one row this gate used to name.

        `ti_html` tables carried a single page for every row, so the row Table
        7-1 spills onto page 33 was cited on 32. Per-row page pinning fixed it;
        this counts the whole table against the printed pages, so the number
        cannot creep back up unnoticed.
        """
        _part_dir, manifest = built
        source = next(d for d in manifest.documents if d.doc_type is DocType.DATASHEET)
        pdf = Path(source.path)
        if not pdf.is_file():
            pytest.skip(f"source PDF is not on this machine: {pdf}")
        with fitz.open(pdf) as doc:
            pages = {n: doc[n - 1].get_text() for n in range(1, doc.page_count + 1)}
        # The spilled row is cited where it prints, not where its table began.
        (spilled,) = [r for r in datasheet_registers.registers if r.name == "R90"]
        assert spilled.page == 33
        assert "0x5A" not in pages[32] and "0x5A" in pages[33]
        early = [
            r.name
            for r in datasheet_registers.registers
            if r.address.verbatim not in pages.get(r.page or 0, "")
        ]
        assert early == [], early

    def test_every_published_register_resolves_to_a_record_and_a_page(self, built, registers):
        """Invariant 8 over real data: no number without a printed page.

        Resolved against **its own document's** root, which is what invariant 8
        says a citation is: a record id is unique inside one document, and a
        derived value cites a record inside one document. LMX1204 is the first
        part in this corpus whose two documents both publish a register map,
        so it is also the first where the same id exists twice across the part
        — measured and recorded in `KNOWN_SHORTCOMINGS.md`.
        """
        part_dir, manifest = built
        dirs = document_dirs(manifest, part_dir=part_dir)
        checked = 0
        for _name, registerset in registers.sets:
            root = dirs.get(registerset.doc_hash)
            assert root is not None and (root / REGISTERS_ARTIFACT).is_file()
            for record in registerset.registers:
                resolved = resolve_source(f"{REGISTERS_ARTIFACT}#{record.id}", roots=[root])
                assert resolved is not None, record.id
                assert resolved.page == record.page
                checked += 1
        assert checked == 70

    def test_one_id_is_carried_by_a_record_in_each_document(self, built, registers):
        """The measured limitation, asserted rather than left to be discovered.

        A register record's id is a pure function of its coordinates *inside a
        document*, so the two documents that print this map compute the same
        ids. Resolving `registers.json#reg_t0-r15` against the part's roots as
        a list returns whichever document comes first. Recorded in
        `KNOWN_SHORTCOMINGS.md`; the fix belongs with `models.py`, not here.
        """
        by_id: dict[str, set[str]] = {}
        for _name, registerset in registers.sets:
            for record in registerset.registers:
                by_id.setdefault(record.id, set()).add(registerset.doc_hash)
        shared = {rid: docs for rid, docs in by_id.items() if len(docs) > 1}
        assert len(by_id) == 35
        assert len(shared) == 35, "every id is carried by a record in both documents"

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
        # Both documents that print the map answer, each citing its own page.
        assert [h["name"] for h in payload["hits"]] == ["R17", "R17"]
        assert sorted(h["citation"] for h in payload["hits"]) == sorted(
            ["§7.1, p.32", f"§{REGMAP_SECTION}, p.{REGMAP_PAGE}"]
        )
        assert all(h["reset"] == {"verbatim": "", "value": None} for h in payload["hits"])


@pytest.mark.integration
class TestTheReferenceMapsOwnSummaryTable:
    """The half phase 6 parked, closed by phase 6.5, ticket 05.

    `LMX1204_registermap.pdf` prints the same 35-register summary as `Table
    1-1` on its page 2, and phase 6 read none of it: the furniture detector
    classified the first body row's `0x0` address cell as page machinery — the
    string prints in that y-band on 11 of the document's 25 pages — which
    truncated the table's region to its header row and rejected the
    reconstruction with `no viable column split`. The document published no
    `registers.json` at all.

    The detector now releases everything below a `Table N.` caption, because
    page machinery never prints directly under one. This class asserts the
    recovery on the printed page rather than on the extractor's word for it.
    """

    def test_the_reference_pdf_is_present_and_prints_a_summary_table(self):
        if not REGMAP_PDF.is_file():
            pytest.skip(f"reference register map absent: {REGMAP_PDF}")
        with fitz.open(REGMAP_PDF) as doc:
            text = doc[1].get_text()
        assert "Table 1-1. LMX1204 Registers" in text
        assert "Address" in text and "Acronym" in text
        assert "0x11" in text and "R17" in text

    def test_the_summary_table_is_recovered_whole(self, regmap_doc):
        _source, _stats, raw = regmap_doc
        build = build_registers(raw, PART)
        assert build.registerset is not None
        assert build.n_registers == 35
        assert build.accepted_tables == 1

    def test_the_first_row_the_furniture_filter_used_to_eat_is_there(self, regmap_doc):
        """`0x0` / `R0` — the cell whose loss cost the whole table."""
        _source, _stats, raw = regmap_doc
        build = build_registers(raw, PART)
        first = build.registerset.registers[0]
        assert (first.address.verbatim, first.name) == ("0x0", "R0")
        assert first.page == REGMAP_PAGE

    def test_the_layout_engine_no_longer_rejects_it_for_a_column_split(self, regmap_doc):
        _source, stats, _raw = regmap_doc
        assert "no viable column split" not in stats.rejection_reasons

    def test_the_recovered_map_is_published_for_the_register_map(self, built, regmap_doc):
        part_dir, manifest = built
        source, _stats, _raw = regmap_doc
        doc_dir = document_dirs(manifest, part_dir=part_dir).get(source.content_hash)
        assert doc_dir is not None
        assert (doc_dir / REGISTERS_ARTIFACT).is_file()

    def test_the_closed_shortcoming_is_no_longer_recorded_as_open(self):
        if not SHORTCOMINGS.is_file():
            pytest.skip("KNOWN_SHORTCOMINGS.md is not in this tree")
        text = SHORTCOMINGS.read_text(encoding="utf-8")
        assert "the LMX1204 register map's own summary table is not read" not in text.lower()
