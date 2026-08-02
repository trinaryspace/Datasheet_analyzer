"""Tests for the plot catalog transform."""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.extract import get_backend
from datasheet_analyzer.extract.http import ReplayFetcher
from datasheet_analyzer.extract.pdf_structure import make_source, read_toc
from datasheet_analyzer.models import RawDocument, SectionNode
from datasheet_analyzer.structure.plots import (
    build_plotset,
    caption_tags,
    figure_number,
    section_tags,
)

RECORDED = Path(__file__).parent.parent / "fixtures" / "recorded_http"
AFE7950_PDF = Path(__file__).parent.parent.parent / "afe7950.pdf"


def _raw_from_recorded() -> RawDocument | None:
    if not RECORDED.is_dir() or not AFE7950_PDF.exists():
        return None
    source = make_source(AFE7950_PDF, part_number="AFE7950")
    backend = get_backend("ti_html")
    backend.fetcher = ReplayFetcher(RECORDED)
    pdf_toc = read_toc(AFE7950_PDF)
    return backend.extract(source, pdf_toc=pdf_toc)


@pytest.fixture(scope="module")
def afe7950_raw() -> RawDocument:
    raw = _raw_from_recorded()
    if raw is None:
        pytest.skip("recorded HTTP fixtures or afe7950.pdf not present")
    return raw


class TestFigureNumberParsing:
    def test_figure_number_parse(self):
        assert figure_number("Figure 4-1 TX Output Fullscale vs Output Frequency") == "4-1"
        assert figure_number("Figure 12-3a Detail") == "12-3a"
        assert figure_number("TX Output Fullscale vs Output Frequency") == ""
        assert figure_number("") == ""


class TestTagExtraction:
    def test_section_and_caption_tags(self):
        sec = SectionNode(number="4.12.1", title="TX Typical Characteristics at 1.8 GHz")
        assert "tx" in section_tags(sec)
        assert "1800mhz" in section_tags(sec)
        assert "pll-clock" not in section_tags(sec)

    def test_caption_tags_acpr_output_power(self):
        tags = caption_tags("TX ACPR vs Output Power at 0.85 GHz")
        assert "acpr" in tags
        assert "output power" in tags

    def test_caption_tags_case_insensitive(self):
        tags = caption_tags("Phase Noise vs Frequency")
        assert "phase noise" in tags


class TestBuildPlotset:
    def test_build_plotset_real_counts(self, afe7950_raw):
        plotset = build_plotset(afe7950_raw, "AFE7950")
        assert plotset.schema_version
        assert plotset.part_number == "AFE7950"
        assert plotset.doc_hash == afe7950_raw.source.content_hash
        assert len(plotset.plots) == 514, (
            f"expected 514 plots, got {len(plotset.plots)}"
        )
        # IDs are stable: sorted by section order then figure order.
        ids = [p.id for p in plotset.plots]
        assert len(set(ids)) == len(ids)
        assert ids[0].startswith("4.12.1-")

    def test_records_carry_section_page_range_not_guessed_pages(self, afe7950_raw):
        plotset = build_plotset(afe7950_raw, "AFE7950")
        for rec in plotset.plots:
            # page_start/page_end must equal the owning section's range;
            # individual figures are not page-pinned.
            sec = next(s for s in afe7950_raw.sections if s.number == rec.section)
            assert rec.page_start == sec.page_start
            assert rec.page_end == sec.page_end

    def test_every_figure_referenced_exactly_once(self, afe7950_raw):
        plotset = build_plotset(afe7950_raw, "AFE7950")
        total_figures = sum(len(s.figures) for s in afe7950_raw.sections)
        assert len(plotset.plots) == total_figures

    def test_tags_combined_from_section_and_caption(self, afe7950_raw):
        plotset = build_plotset(afe7950_raw, "AFE7950")
        fullscale = [p for p in plotset.plots if "fullscale" in p.tags]
        assert fullscale
        for p in fullscale:
            assert "fullscale" in p.caption.lower()
            # section contributes a path tag (tx/rx/fb/pll-clock) and caption
            # contributes the measure keyword.
            assert any(t in {"tx", "rx", "fb", "pll-clock"} for t in p.tags)
