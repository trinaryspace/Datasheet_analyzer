"""Tests for deterministic plot lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.models import PlotRecord, PlotSet
from datasheet_analyzer.query import find_plots, format_plot_answer


def _write_plotset(tmp_path: Path, plots: list[PlotRecord], doc_type: str = "datasheet",
                   hash8: str = "a1b2c3d4") -> Path:
    part_dir = tmp_path / "parts" / "TEST"
    doc_dir = part_dir / f"docs/{doc_type}-{hash8}"
    doc_dir.mkdir(parents=True, exist_ok=True)
    plotset = PlotSet(
        schema_version="1", part_number="TEST", doc_hash="x" * 64, plots=plots
    )
    (doc_dir / "plots.json").write_text(
        plotset.model_dump_json(indent=2), encoding="utf-8"
    )
    return part_dir


@pytest.fixture
def sample_part(tmp_path):
    plots = [
        PlotRecord(
            id="4.12.1-f001",
            section="4.12.1",
            caption="Figure 4-1 TX Output Fullscale vs Output Frequency",
            conditions="DSA = 0",
            page_start=29,
            page_end=37,
            file="docs/datasheet-a1b2c3d4/figures/4-12-1/4.12.1-f001.gif",
            tags=["tx", "800mhz", "fullscale"],
        ),
        PlotRecord(
            id="4.12.1-f002",
            section="4.12.1",
            caption="Figure 4-2 TX Calibrated Differential Gain Error vs DSA Setting",
            conditions="0.85 GHz",
            page_start=29,
            page_end=37,
            file="",
            tags=["tx", "800mhz", "gain error", "dsa"],
        ),
        PlotRecord(
            id="4.12.8-f001",
            section="4.12.8",
            caption="Figure 4-100 RX Input Fullscale vs Frequency",
            conditions="DSA = 0",
            page_start=38,
            page_end=42,
            file="docs/datasheet-a1b2c3d4/figures/4-12-8/4.12.8-f001.gif",
            tags=["rx", "800mhz", "fullscale"],
        ),
    ]
    return _write_plotset(tmp_path, plots)


class TestFindPlots:
    def test_substring_match_caption(self, sample_part):
        hits = find_plots(sample_part, q="Fullscale")
        assert len(hits) == 2
        assert all("Fullscale" in p.caption for p in hits)

    def test_substring_match_conditions(self, sample_part):
        hits = find_plots(sample_part, q="DSA = 0")
        assert len(hits) == 2

    def test_section_exact(self, sample_part):
        hits = find_plots(sample_part, section="4.12.1")
        assert len(hits) == 2
        assert all(p.section == "4.12.1" for p in hits)

    def test_tag_and_semantics(self, sample_part):
        hits = find_plots(sample_part, tags=["tx", "fullscale"])
        assert len(hits) == 1
        assert hits[0].id == "4.12.1-f001"

    def test_and_combination(self, sample_part):
        hits = find_plots(sample_part, q="Gain", section="4.12.1", tags=["dsa"])
        assert len(hits) == 1
        assert hits[0].id == "4.12.1-f002"

    def test_case_insensitive(self, sample_part):
        hits = find_plots(sample_part, q="fullscale")
        assert len(hits) == 2


class TestFormatPlotAnswer:
    def test_includes_file_and_pages(self, sample_part):
        hits = find_plots(sample_part, q="TX Output Fullscale")
        text = format_plot_answer(hits)
        assert "TX Output Fullscale vs Output Frequency" in text
        assert "§4.12.1" in text
        assert "p.29-37" in text
        assert "DSA = 0" in text
        assert "file:" in text

    def test_no_matches_message(self):
        assert "No matching plots" in format_plot_answer([])
