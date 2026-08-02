"""Tests for the degraded pdf_text backend."""

from __future__ import annotations

import fitz

from datasheet_analyzer.extract.pdf_structure import make_source
from datasheet_analyzer.extract.pdf_text import PdfTextBackend
from datasheet_analyzer.structure.specs import build_specset


def _make_pdf_with_toc(tmp_path, pages):
    pdf_path = tmp_path / "register_map.pdf"
    doc = fitz.open()
    for i, content in enumerate(pages):
        page = doc.new_page()
        # Insert the page number as footer and some content.
        page.insert_text((300, 750), str(i + 1))
        page.insert_text((72, 72), content)
    # Create a simple TOC referencing existing pages only.
    toc = [[1, f"{i + 1} Section {i + 1}", i + 1] for i in range(len(pages))]
    doc.set_toc(toc)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_pdf_text_strips_page_number_but_keeps_data(tmp_path):
    pdf_path = _make_pdf_with_toc(
        tmp_path,
        [
            "This is the overview. It contains 1234 as a data value.",
            "Register map begins here.",
            "Control register 0x00 = 0xFF.",
        ],
    )
    source = make_source(pdf_path, doc_type="register_map")
    raw = PdfTextBackend().extract(source)
    assert raw.extractor == "pdf_text"
    assert len(raw.sections) == 3
    overview = raw.sections[0]
    assert overview.number == "1"
    assert "Section 1" in overview.title
    assert "This is the overview" in overview.paragraphs[0]
    assert "1234" in overview.paragraphs[0]
    # The page-number footer was stripped.
    assert "1" not in overview.paragraphs


def test_pdf_text_tables_and_figures_empty(tmp_path):
    pdf_path = _make_pdf_with_toc(tmp_path, ["Content"])
    source = make_source(pdf_path, doc_type="register_map")
    raw = PdfTextBackend().extract(source)
    for sec in raw.sections:
        assert sec.tables == []
        assert sec.figures == []


def test_pdf_text_no_toc_one_section_per_page(tmp_path):
    pdf_path = tmp_path / "no_toc.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((300, 750), str(i + 1))
        page.insert_text((72, 72), f"Page {i + 1} content.")
    doc.save(str(pdf_path))
    doc.close()

    source = make_source(pdf_path, doc_type="app_note")
    raw = PdfTextBackend().extract(source)
    assert len(raw.sections) == 2
    assert raw.sections[0].number == "1"
    assert raw.sections[1].number == "2"
    assert "Page 1 content" in raw.sections[0].paragraphs[0]


def test_pdf_text_emits_no_specs(tmp_path):
    pdf_path = _make_pdf_with_toc(tmp_path, ["Content"])
    source = make_source(pdf_path, doc_type="register_map")
    raw = PdfTextBackend().extract(source)
    specset = build_specset(raw, "TEST")
    assert specset is None
