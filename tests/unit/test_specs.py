"""Spec record extraction from real and synthetic tables."""

from __future__ import annotations

from datasheet_analyzer.extract.ti_html import parse_section
from datasheet_analyzer.models import SectionNode, TableBlock
from datasheet_analyzer.structure.specs import build_specset, table_to_records

SEC45_URL = (
    "https://www.ti.com/document-viewer/AFE7950/datasheet/"
    "GUID-XXXXXXXX-SF0T-XXXX-XXXX-000000182911#GUID-AAAA-SF0L-XXXX-XXXX-000000182911"
)


def _parse_45(ti_sec_4_5_html):
    sec = parse_section(ti_sec_4_5_html, SEC45_URL, number="4.5",
                        title="Transmitter Electrical Characteristics")
    sec.page_start = 7
    sec.page_end = 13
    return sec


class TestRowExtraction:
    def test_dacres_exact_values(self, ti_sec_4_5_html):
        sec = _parse_45(ti_sec_4_5_html)
        sec.tables[0].page = 7
        records, _info = table_to_records(sec, sec.tables[0], 0)
        dacres = [r for r in records if r.symbol == "DACRES"]
        assert len(dacres) == 1
        r = dacres[0]
        assert r.name == "DAC resolution"
        assert r.typ == "14"
        assert r.unit.canonical == "bits"
        assert r.page == 7
        assert r.table_index == 0

    def test_attstep_after_calibration(self, ti_sec_4_5_html):
        sec = _parse_45(ti_sec_4_5_html)
        sec.tables[0].page = 7
        records, _ = table_to_records(sec, sec.tables[0], 0)
        row = next(
            r for r in records
            if "DSA Attenuation step accuracy" in r.name
            and "after calibration" in r.conditions
        )
        assert row.typ == "±0.1"
        assert row.unit.canonical == "dB"
        assert row.page == 7

    def test_row_footnote_markers_scoped_per_row(self, ti_sec_4_5_html):
        sec = _parse_45(ti_sec_4_5_html)
        records, _ = table_to_records(sec, sec.tables[0], 0)
        attphase = next(
            r for r in records
            if "Phase accuracy" in r.name or "850MHz" in r.conditions
        )
        assert attphase.cited_markers == ["(2)"]
        dacres = next(r for r in records if r.symbol == "DACRES")
        assert dacres.cited_markers == []

    def test_footnotes_attached_to_every_record(self, ti_sec_4_5_html):
        sec = _parse_45(ti_sec_4_5_html)
        records, _ = table_to_records(sec, sec.tables[0], 0)
        assert records
        markers = {fn.marker for fn in records[0].footnotes}
        assert {"(1)", "(2)", "(3)"} <= markers
        for r in records:
            assert len(r.footnotes) == len(records[0].footnotes)

    def test_row_verbatim_roundtrip(self, ti_sec_4_5_html):
        sec = _parse_45(ti_sec_4_5_html)
        records, _ = table_to_records(sec, sec.tables[0], 0)
        grid = sec.tables[0].grid
        non_empty_rows = [r for r in grid if any(c.strip() for c in r)]
        assert len(records) == len(non_empty_rows)
        for rec, row in zip(records, non_empty_rows):
            assert rec.row_verbatim == list(row)


class TestPageAndEdgeCases:
    def test_page_falls_back_to_section_start_when_unpinned(self):
        table = TableBlock(
            headers=["PARAMETER", "MIN", "MAX", "UNIT"],
            grid=[["FOO", "1", "2", "V"]],
            page=None,
        )
        sec = SectionNode(number="9.9", title="Synthetic", page_start=42)
        records, _ = table_to_records(sec, table, 0)
        assert records[0].page == 42

    def test_page_none_when_section_unpaged(self):
        table = TableBlock(
            headers=["PARAMETER", "MIN", "MAX", "UNIT"],
            grid=[["FOO", "1", "2", "V"]],
            page=None,
        )
        sec = SectionNode(number="9.9", title="Synthetic")
        records, _ = table_to_records(sec, table, 0)
        assert records[0].page is None

    def test_empty_rows_skipped(self):
        table = TableBlock(
            headers=["PARAMETER", "MIN", "UNIT"],
            grid=[["A", "1", "V"], ["", "", ""], ["B", "2", "V"]],
        )
        sec = SectionNode(number="9.9", title="Synthetic")
        records, _ = table_to_records(sec, table, 0)
        assert len(records) == 2
        assert records[0].symbol == "A"
        assert records[1].symbol == "B"


class TestSpecSetBuild:
    def test_build_specset_schema_validates(self, ti_sec_4_5_html):
        sec = _parse_45(ti_sec_4_5_html)
        raw = type("Raw", (), {
            "source": type("Source", (), {
                "content_hash": "a" * 64,
            })(),
            "sections": [sec],
            "extractor": "ti_html",
        })()
        specset = build_specset(raw, "AFE7950")
        assert specset.schema_version
        assert specset.part_number == "AFE7950"
        assert specset.records
        # Pydantic round-trip
        assert specset.model_validate_json(specset.model_dump_json()) == specset
