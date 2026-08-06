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

    def test_ug_prefix_companion_hints(self, tmp_path):
        # ADI user-guide prefixes (SPEC story 24): ug-named companions are
        # app notes unless register/regmap words win (those classify as
        # register maps — the register_map line precedes the app_note one)
        assert detect_doc_type(tmp_path / "ug-1578.pdf") == DocType.APP_NOTE
        assert detect_doc_type(tmp_path / "UG_1578.pdf") == DocType.APP_NOTE
        assert detect_doc_type(tmp_path / "ug1578.pdf") == DocType.APP_NOTE
        assert detect_doc_type(tmp_path / "ug-1578 register map.pdf") == DocType.REGISTER_MAP
        assert detect_doc_type(tmp_path / "Register map UG.pdf") == DocType.REGISTER_MAP
        # mid-word "ug" never counts ("drug1578" stays a bare-part-name
        # datasheet), and a bare "ug.pdf" has no number to pin it
        assert detect_doc_type(tmp_path / "drug1578.pdf") == DocType.DATASHEET
        assert detect_doc_type(tmp_path / "ug.pdf") == DocType.DATASHEET


class TestRevisionSniffing:
    """Ticket 06: revision shapes from a shared lexicon (SPEC story 23) —
    "Rev. A"-style tokens for any vendor's era, TI document ids unchanged."""

    def test_hittite_style_rev_caption(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["HMC520A", "Rev. A | Page 2 of 32", "body"])
        assert register_source(pdf).revision == "Rev. A"

    def test_adi_footer_rev_with_page_count(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["AD9081", "Rev. 0 | 2 of 45", "body"])
        assert register_source(pdf).revision == "Rev. 0"

    def test_rev_embedded_in_datasheet_title_line(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["Data Sheet Rev. I, January 2026 | Subject to change"])
        assert register_source(pdf).revision == "Rev. I"

    def test_rev_to_rev_shape_keeps_the_current_revision(self, tmp_path):
        # the revision-history "Rev. 0 to Rev. A" shape: last token wins
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["Revision History", "6/2018 Rev. 0 to Rev. A"])
        assert register_source(pdf).revision == "Rev. A"

    def test_revision_words_are_not_rev_tokens(self, tmp_path):
        # "Revision N" (full word), "REVISED", "REVISION HISTORY" and
        # "Changes from Revision C ... to Revision D" carry no Rev-token
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["REVISION HISTORY", "4/2021 Revision 0: Initial Version",
                        "Changes from Revision C to Revision D"])
        assert register_source(pdf).revision == ""

    def test_ti_doc_id_still_sniffed_for_ti_parts(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["SBASA41E - FEBRUARY 2021 - REVISED MAY 2025", "body"])
        assert register_source(pdf).revision == "SBASA41E"

    def test_ti_doc_id_requires_a_digit_so_bare_words_stay_out(self, tmp_path):
        # old regex read bare all-letter S-words as doc ids: "TECHNICAL
        # SUPPORT" (AD9081 p.1) came out as revision "SUPPORT"
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["TECHNICAL SUPPORT", "Information furnished by Analog Devices"])
        assert register_source(pdf).revision == ""

    def test_rev_token_beats_a_ti_doc_id_lookalike_on_the_same_page(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["AD9081", "Rev. 0", "TECHNICAL SUPPORT"])
        assert register_source(pdf).revision == "Rev. 0"

    def test_later_page_within_the_window_still_found(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _make_pdf(pdf, ["page one", "page two", "Rev. A | Page 3 of 8"])
        assert register_source(pdf).revision == "Rev. A"


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
