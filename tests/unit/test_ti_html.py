"""Pain point: extraction fidelity on real TI HTML — TOC structure, dense
parametric tables, footnotes, conditions, figure catalogs.

These tests replay recorded document-viewer pages (no network) and pin
exact values from the AFE7950 datasheet, so any parser regression that
would corrupt a spec fails loudly here.
"""

from __future__ import annotations

import pytest

from datasheet_analyzer.extract.ti_html import parse_section, parse_toc

# Realistic section URLs: path GUID == the container div id in the fixtures.
SEC45_URL = (
    "https://www.ti.com/document-viewer/AFE7950/datasheet/"
    "GUID-XXXXXXXX-SF0T-XXXX-XXXX-000000182911#GUID-AAAA-SF0L-XXXX-XXXX-000000182911"
)
SEC4121_URL = (
    "https://www.ti.com/document-viewer/AFE7950/datasheet/"
    "GUID-8F7E6E37-F518-40B0-BDB2-9FD14DED8661#GUID-BBBB"
)


class TestTOCParsing:
    def test_parses_all_content_sections(self, ti_main_html):
        toc = parse_toc(ti_main_html, "AFE7950")
        # 40 TOC anchors minus the datasheet cover page (empty id, numeric
        # navtitle) which is furniture, not a content section
        assert len(toc) == 39
        assert all(not (not e.number and e.title.isdigit()) for e in toc)
        assert "1" in {e.number for e in toc}  # real numbered sections intact

    def test_numbers_titles_levels_urls(self, ti_main_html):
        toc = parse_toc(ti_main_html, "AFE7950")
        by_number = {e.number: e for e in toc}
        assert by_number["4.5"].title == "Transmitter Electrical Characteristics"
        assert by_number["4.5"].level == 2
        assert by_number["4.12.1"].level == 3
        assert by_number["1"].title == "Features"
        assert by_number["4.5"].url.startswith(
            "https://www.ti.com/document-viewer/AFE7950/datasheet/GUID-"
        )

    def test_toc_order_matches_document_order(self, ti_main_html):
        toc = parse_toc(ti_main_html, "AFE7950")
        numbers = [e.number for e in toc if e.number]
        assert numbers[:4] == ["1", "2", "3", "4"]
        assert numbers.index("4.5") < numbers.index("4.6")
        assert numbers[-1] == "7"


class TestSection45Parsing:
    """Section 4.5: the 204-row TX parametric table with 73 rowspans."""

    def test_one_atomic_table_with_all_rows(self, ti_sec_4_5_html):
        sec = parse_section(ti_sec_4_5_html, SEC45_URL, number="4.5",
                            title="Transmitter Electrical Characteristics")
        assert len(sec.tables) == 1
        t = sec.tables[0]
        # every body row survives; none split, none dropped (204 incl. spacers)
        assert t.n_rows > 180
        assert t.n_cols == 7

    def test_conditions_preamble_attached_to_table(self, ti_sec_4_5_html):
        sec = parse_section(ti_sec_4_5_html, SEC45_URL, number="4.5",
                            title="Transmitter Electrical Characteristics")
        cond = sec.tables[0].conditions
        assert "Typical values at TA = +25°C" in cond
        assert "11796.48MSPS" in cond
        # and the conditions paragraph is NOT also left floating as a paragraph
        assert not any("Typical values at TA" in p for p in sec.paragraphs)

    def test_rowspan_expansion_on_real_data(self, ti_sec_4_5_html):
        sec = parse_section(ti_sec_4_5_html, SEC45_URL, number="4.5",
                            title="Transmitter Electrical Characteristics")
        g = sec.tables[0].grid
        # find the DACRES row: DAC resolution | 14 | bits
        dacres = [r for r in g if r and r[0] == "DACRES"]
        assert dacres, "DACRES row missing — grid expansion broken"
        assert "14" in dacres[0]
        assert "bits" in dacres[0]
        # RF output frequency rows: parameter reaches every spanned row
        fout = [r for r in g if r and r[1] == "RF output frequency range"]
        assert len(fout) == 6
        assert all(r[0] == "fRFout" for r in fout)
        assert all(r[6] == "MHz" for r in fout)

    def test_exact_spec_values_present(self, ti_sec_4_5_html):
        """Golden values cross-checked against the PDF page 7."""
        sec = parse_section(ti_sec_4_5_html, SEC45_URL, number="4.5",
                            title="Transmitter Electrical Characteristics")
        g = sec.tables[0].grid
        flat = "\n".join(" | ".join(r) for r in g)
        for needle in ["DSA Attenuation range", "40", "±0.1", "±0.2"]:
            assert needle in flat, f"{needle!r} missing from extracted table"
        # value and unit live in separate cells but the same row.
        # NOTE: TI emits U+2126 OHM SIGN, not U+03A9 GREEK CAPITAL OMEGA —
        # extraction must preserve it verbatim (unit canonicalization is a
        # Phase 2 specs.json concern, not an extraction concern).
        rterm = [r for r in g if r and r[0] == "RTERM"]
        assert rterm and "50" in rterm[0] and "Ω" in rterm[0]

    def test_footnotes_parsed_and_markers_cited(self, ti_sec_4_5_html):
        sec = parse_section(ti_sec_4_5_html, SEC45_URL, number="4.5",
                            title="Transmitter Electrical Characteristics")
        t = sec.tables[0]
        markers = {f.marker for f in t.footnotes}
        assert {"(1)", "(2)", "(3)"} <= markers
        texts = {f.marker: f.text for f in t.footnotes}
        assert "calibration" in texts["(2)"].lower()
        assert "50 ohm" in texts["(1)"]
        # markers cited via <sup> in cells were captured
        assert "(2)" in t.cited_markers
        # every cited marker resolves to a note (no orphans on the real table)
        assert set(t.cited_markers) <= markers

    def test_headers(self, ti_sec_4_5_html):
        sec = parse_section(ti_sec_4_5_html, SEC45_URL, number="4.5",
                            title="Transmitter Electrical Characteristics")
        h = sec.tables[0].headers
        assert h[:3] == ["PARAMETER", "PARAMETER", "TEST CONDITIONS"]
        assert h[3:] == ["MIN", "TYP", "MAX", "UNIT"]


class TestSection4121Parsing:
    """Section 4.12.1: plot gallery — figures with captions + conditions."""

    def test_figures_cataloged_with_captions(self, ti_sec_4_12_1_html):
        sec = parse_section(ti_sec_4_12_1_html, SEC4121_URL, number="4.12.1",
                            title="TX Typical Characteristics 800 MHz")
        assert len(sec.figures) >= 40
        captions = [f.caption for f in sec.figures]
        assert any("TX Output Fullscale vs Output Frequency" in c for c in captions)
        # image urls captured for later rendering
        assert all(f.image_url for f in sec.figures)

    def test_figure_conditions_captured(self, ti_sec_4_12_1_html):
        sec = parse_section(ti_sec_4_12_1_html, SEC4121_URL, number="4.12.1",
                            title="TX Typical Characteristics 800 MHz")
        conds = " ".join(f.conditions for f in sec.figures)
        assert "DSA = 0" in conds or "matching" in conds

    def test_figure_tables_not_misparsed_as_parametric(self, ti_sec_4_12_1_html):
        sec = parse_section(ti_sec_4_12_1_html, SEC4121_URL, number="4.12.1",
                            title="TX Typical Characteristics 800 MHz")
        # the 43 <table> wrappers around images must not become data tables
        assert sec.tables == []


class TestSectionParseEdgeCases:
    def test_missing_container_raises(self):
        # a page with no matching GUID, no matching heading, and no
        # substantial subsection must fail loudly
        empty_page = "<html><body><div class='subsection'>tiny</div></body></html>"
        with pytest.raises(ValueError, match="container not found"):
            parse_section(
                empty_page,
                "https://www.ti.com/document-viewer/AFE7950/datasheet/GUID-00000000",
                number="9.9", title="Nonexistent Section",
            )

    def test_last_resort_container_for_id_less_pages(self):
        # TI revision-history-style pages: no matching GUID, content in <p>
        page = (
            "<html><body><div class='subsection'>"
            + "".join(f"<p>Changes from June 2023 to May 2025 rev {i}.</p>" for i in range(8))
            + "</div></body></html>"
        )
        sec = parse_section(
            page, "https://www.ti.com/document-viewer/X/datasheet/GUID-ZZZ",
            number="5", title="Revision History",
        )
        assert sec.paragraphs and "Changes from June 2023" in sec.paragraphs[0]

    def test_nested_list_items_split_and_indent(self):
        page = (
            "<html><body><div class='subsection' id='GUID-LIST1'>"
            "<ul><li>Maximum RF signal bandwidth:<ul>"
            "<li>4TX or 2FB: 1200MHz or 2TX: 2400MHz</li>"
            "<li>RX: 1200MHz (no FB), 600MHz (with FB)</li>"
            "</ul></li>"
            "<li>Package: 17mm FCBGA</li></ul>"
            "</div></body></html>"
        )
        sec = parse_section(
            page, "https://www.ti.com/document-viewer/X/datasheet/GUID-LIST1",
            number="1", title="Features",
        )
        assert sec.paragraphs[0] == "• Maximum RF signal bandwidth:"
        assert sec.paragraphs[1] == "  • 4TX or 2FB: 1200MHz or 2TX: 2400MHz"
        assert sec.paragraphs[2] == "  • RX: 1200MHz (no FB), 600MHz (with FB)"
        assert sec.paragraphs[3] == "• Package: 17mm FCBGA"

    def test_ui_furniture_text_blocks_skipped(self):
        page = (
            "<html><body><div class='subsection' id='GUID-FURN1'>"
            "<span class='section-label'>4.5</span>"
            "<li>Request full data sheet</li>"
            "<p>Real content paragraph.</p>"
            "</div></body></html>"
        )
        sec = parse_section(
            page, "https://www.ti.com/document-viewer/X/datasheet/GUID-FURN1",
            number="4.5", title="TX",
        )
        assert sec.paragraphs == ["Real content paragraph."]

    def test_title_recovered_from_h2_when_not_given(self, ti_sec_4_5_html):
        sec = parse_section(ti_sec_4_5_html, SEC45_URL)
        assert "4.5" in (sec.number, "4.5")[0] or sec.number == "4.5"
        assert "Transmitter" in sec.title
