"""Pain point: part = folder of docs. Inventory registration, doc-type
detection, revision sniffing, sources.json round-trip, hash identity."""

from __future__ import annotations

import fitz

from datasheet_analyzer.acquire.inventory import (
    detect_doc_type,
    load_inventory,
    register_source,
    save_inventory,
)
from datasheet_analyzer.extract.pdf_structure import compute_content_hash, read_toc
from datasheet_analyzer.models import DocType


def _make_pdf(path, pages: list[str], toc: list[list] | None = None):
    """Create a tiny synthetic PDF with known text per page (+ optional TOC)."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    if toc:
        doc.set_toc(toc)
    doc.save(path)
    doc.close()


class TestDocTypeDetection:
    def test_filename_hints(self, tmp_path):
        assert detect_doc_type(tmp_path / "AFE7950_register_map.pdf") == DocType.REGISTER_MAP
        assert detect_doc_type(tmp_path / "afe7950-errata.pdf") == DocType.ERRATA
        assert detect_doc_type(tmp_path / "SBAA403-app-note.pdf") == DocType.APP_NOTE
        assert detect_doc_type(tmp_path / "afe7950.pdf") == DocType.DATASHEET
        assert detect_doc_type(tmp_path / "mystery-document.xyz") == DocType.UNKNOWN


class TestRegisterSource:
    def test_hash_identity_and_metadata(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["SBASA41E – FEBRUARY 2021 hello", "page two"])
        src = register_source(pdf, part_number="AFE7950")
        assert src.content_hash == compute_content_hash(pdf)
        assert src.page_count == 2
        assert src.revision == "SBASA41E"
        assert src.part_number == "AFE7950"

    def test_hash_changes_with_bytes(self, tmp_path):
        p1 = tmp_path / "a.pdf"
        _make_pdf(p1, ["version one"])
        p2 = tmp_path / "b.pdf"
        _make_pdf(p2, ["version two"])
        assert register_source(p1).content_hash != register_source(p2).content_hash

    def test_explicit_doc_type_and_nda_flag(self, tmp_path):
        pdf = tmp_path / "regmap.pdf"
        _make_pdf(pdf, ["registers"])
        src = register_source(pdf, doc_type=DocType.REGISTER_MAP, nda=True)
        assert src.doc_type == DocType.REGISTER_MAP
        assert src.nda is True


class TestVendorRegistration:
    def test_detected_vendor_pins_with_evidence(self, tmp_path):
        pdf = tmp_path / "afe7950.pdf"
        _make_pdf(pdf, ["Texas Instruments AFE7950 datasheet"])
        src = register_source(pdf, part_number="AFE7950")
        assert src.vendor == "ti"
        assert src.vendor_evidence == 'brand:"texas instruments" (p.1)'

    def test_override_beats_detection(self, tmp_path):
        pdf = tmp_path / "afa710.pdf"
        _make_pdf(pdf, ["Some other vendor's datasheet"])
        src = register_source(pdf, vendor="adi")
        assert src.vendor == "adi"
        assert src.vendor_evidence == "cli-override: --vendor adi"

    def test_vendor_survives_inventory_roundtrip(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["Qorvo QPA1003P datasheet"])
        src = register_source(pdf, part_number="QPA1003P")
        part_dir = tmp_path / "parts" / "QPA1003P"
        save_inventory([src], part_dir)
        (loaded,) = load_inventory(part_dir)
        assert loaded.vendor == "qorvo"
        assert loaded.vendor_evidence == 'brand:"qorvo" (p.1)'


class TestInventoryRoundTrip:
    def test_save_load_preserves_everything(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["SBASA41E doc"])
        src = register_source(pdf, part_number="AFE7950", nda=True)
        part_dir = tmp_path / "parts" / "AFE7950"
        save_inventory([src], part_dir)
        (loaded,) = load_inventory(part_dir)
        assert loaded == src

    def test_load_missing_returns_empty(self, tmp_path):
        assert load_inventory(tmp_path) == []


class TestReadToc:
    def test_synthetic_pdf_toc(self, tmp_path):
        pdf = tmp_path / "toc.pdf"
        _make_pdf(
            pdf,
            ["features page", "spec page", "detail page"],
            toc=[[1, "1 Features", 1], [1, "4 Specifications", 2], [2, "4.1 Abs Max", 3]],
        )
        toc = read_toc(pdf)
        assert [(e.number, e.title, e.level, e.page) for e in toc] == [
            ("1", "Features", 1, 1),
            ("4", "Specifications", 1, 2),
            ("4.1", "Abs Max", 2, 3),
        ]
