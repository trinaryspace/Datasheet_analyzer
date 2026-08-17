"""Tests for deterministic plot lookup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import (
    AxisScale,
    Confidence,
    CorpusManifest,
    PlotRecord,
    PlotSet,
)
from datasheet_analyzer.query import find_plots, format_axes, format_plot_answer
from datasheet_analyzer.retrieve import Retriever, gap_axis


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


# --- the axis catalog as a filter (phase 6, ticket 08) ------------------------

def _axis_part(tmp_path: Path) -> Path:
    """A part whose figures cover the three states an axis filter must handle:
    a readable frequency plot, a readable temperature plot, and a raster plot
    whose axes could not be read at all."""
    plots = [
        PlotRecord(
            id="4.12.1-f001", section="4.12.1",
            caption="Figure 4-1 TX Output Fullscale vs Output Frequency",
            figure_number="4-1", page_start=29, page_end=29,
            x_label="Output Frequency", x_unit="MHz", x_min=600.0, x_max=1500.0,
            x_scale=AxisScale.LINEAR,
            y_label="Output Full Scale", y_unit="dBm", y_min=-2.0, y_max=7.0,
            y_scale=AxisScale.LINEAR,
            axis_confidence=Confidence.HIGH, axis_page=29,
            axis_derivation="figure_region+tick_cluster+axis_title_run",
        ),
        PlotRecord(
            id="4.12.1-f002", section="4.12.1",
            caption="Figure 4-2 TX Output Fullscale vs Temperature",
            figure_number="4-2", page_start=29, page_end=29,
            x_label="Temperature", x_unit="°C", x_min=-40.0, x_max=105.0,
            x_scale=AxisScale.LINEAR,
            y_label="Output Full Scale", y_unit="dBm", y_min=2.0, y_max=6.5,
            y_scale=AxisScale.LINEAR,
            axis_confidence=Confidence.HIGH, axis_page=29,
        ),
        PlotRecord(
            id="4.12.1-f003", section="4.12.1",
            caption="Figure 4-32 TX Output FFT", figure_number="4-32",
            page_start=30, page_end=30, axis_confidence=Confidence.LOW,
        ),
    ]
    part_dir = _write_plotset(tmp_path, plots)
    (part_dir / "manifest.json").write_text(
        CorpusManifest(part_number="TEST", pipeline_version="0.5.0").model_dump_json(),
        encoding="utf-8",
    )
    return part_dir


@pytest.fixture
def axis_part(tmp_path):
    return _axis_part(tmp_path)


class TestAxisFilters:
    def test_x_label_narrows_by_the_printed_title(self, axis_part):
        hits = Retriever.for_part(axis_part).plots(x_label="Frequency")
        assert [h.record.figure_number for h in hits] == ["4-1"]
        assert hits[0].matched_via == "axis-label"

    def test_y_label_narrows_and_is_case_insensitive(self, axis_part):
        hits = Retriever.for_part(axis_part).plots(y_label="output full scale")
        assert [h.record.figure_number for h in hits] == ["4-1", "4-2"]

    def test_near_x_scales_the_question_to_the_axis_unit(self, axis_part):
        """The hand-checked example: the caller says 1.35 GHz, the axis printed
        MHz, and figure 4-1's printed ticks run 600 to 1500 MHz."""
        hits = Retriever.for_part(axis_part).plots(near_x="1.35GHz")
        assert [h.record.figure_number for h in hits] == ["4-1"]
        assert hits[0].matched_via == "axis-range"

    def test_near_x_outside_every_range_matches_nothing(self, axis_part):
        assert Retriever.for_part(axis_part).plots(near_x="20GHz") == []

    def test_near_x_will_not_match_a_different_physical_quantity(self, axis_part):
        """A temperature axis is not a frequency axis, even though both are
        numbers over the same interval."""
        hits = Retriever.for_part(axis_part).plots(near_x="50 °C")
        assert [h.record.figure_number for h in hits] == ["4-2"]
        assert Retriever.for_part(axis_part).plots(near_x="50MHz") == []

    def test_an_unscalable_axis_unit_is_unmatchable_not_matched_raw(self, tmp_path):
        """`Cq` is what AFE7950's own temperature axes print — a degree glyph its
        font mangled — and the unit lexicon cannot scale it. The figure is
        therefore honestly unmatchable by range rather than compared at face
        value, which is the same refusal `quantities._si` makes: a unit read
        wrongly would hand back a figure with a valid-looking citation.
        """
        part = _write_plotset(tmp_path, [PlotRecord(
            id="p1", figure_number="1", x_label="Temperature", x_unit="Cq",
            x_min=-40.0, x_max=105.0, x_scale=AxisScale.LINEAR,
        )])
        (part / "manifest.json").write_text(
            CorpusManifest(part_number="TEST").model_dump_json(), encoding="utf-8"
        )
        assert Retriever.for_part(part).plots(near_x="50 °C") == []
        # …and it is still findable by its printed label, which is the point of
        # having both filters.
        assert len(Retriever.for_part(part).plots(x_label="Temperature")) == 1

    def test_an_unparseable_near_x_matches_nothing(self, axis_part):
        assert Retriever.for_part(axis_part).plots(near_x="somewhere") == []

    def test_axis_filters_are_and_clauses(self, axis_part):
        hits = Retriever.for_part(axis_part).plots(
            q="Fullscale", x_label="Temperature"
        )
        assert [h.record.figure_number for h in hits] == ["4-2"]

    def test_a_figure_with_no_axes_is_never_returned_by_an_axis_filter(self, axis_part):
        for kwargs in ({"x_label": "Frequency"}, {"near_x": "1.35GHz"}):
            hits = Retriever.for_part(axis_part).plots(**kwargs)
            assert "4-32" not in [h.record.figure_number for h in hits]


class TestAxisGap:
    def test_the_gap_names_the_population_it_could_not_consider(self, axis_part):
        gap = Retriever.for_part(axis_part).plot_axis_gap()
        assert "1 of 3 figures publish no readable x axis" in gap
        assert "cannot establish that no such figure exists" in gap

    def test_the_axis_a_query_owes_a_gap_for_is_decided_in_one_place(self, axis_part):
        """`dsa plots` and the MCP `find_plots` tool ask one question, so the
        choice of which population to report cannot live in either of them."""
        retriever = Retriever.for_part(axis_part)
        assert gap_axis() == ""
        assert gap_axis(near_x="1GHz") == "x"
        assert gap_axis(y_label="Gain") == "y"
        # An x clause beside a y one asks about x: the narrower filter is the
        # one whose population an empty result would be misread as absence of.
        assert gap_axis(x_label="Frequency", y_label="Gain") == "x"
        assert retriever.plot_axis_gap_for() == ""
        assert "no readable y axis" in retriever.plot_axis_gap_for(y_label="Gain")
        assert "no readable x axis" in retriever.plot_axis_gap_for(near_x="1GHz")

    def test_a_fully_readable_catalog_has_no_gap(self, tmp_path):
        part = _write_plotset(tmp_path, [PlotRecord(
            id="p1", figure_number="1", x_label="Frequency", x_unit="MHz",
            x_min=1.0, x_max=2.0, x_scale=AxisScale.LINEAR,
            axis_confidence=Confidence.HIGH,
        )])
        (part / "manifest.json").write_text(
            CorpusManifest(part_number="TEST").model_dump_json(), encoding="utf-8"
        )
        assert Retriever.for_part(part).plot_axis_gap() == ""


def _axis_member(root: Path, part: str, plots: list[PlotRecord]) -> Path:
    """One built-enough part directory, for the project fan-out below."""
    part_dir = root / part
    doc_dir = part_dir / "docs/datasheet-a1b2c3d4"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "plots.json").write_text(
        PlotSet(schema_version="1", part_number=part, doc_hash="x" * 64,
                plots=plots).model_dump_json(indent=2),
        encoding="utf-8",
    )
    (part_dir / "manifest.json").write_text(
        CorpusManifest(part_number=part).model_dump_json(), encoding="utf-8"
    )
    return part_dir


class TestProjectScopedAxisFilters:
    """A design asks the same axis question of every member.

    The filters had to reach `ProjectRetriever` too, because `dsa plots` and the
    MCP `find_plots` tool both take `--project` and neither may implement a
    lookup of its own. The gap stays **per part** for the same reason
    `register_field_gap()` does: "all 1 figures publish a readable x axis" is a
    fact about one device, and a design-wide count would hide *which* device's
    figures cannot be filtered by axis.
    """

    @pytest.fixture
    def scope(self, tmp_path):
        from datasheet_analyzer.retrieve import ProjectRetriever

        _axis_member(tmp_path, "A", [PlotRecord(
            id="a1", figure_number="1", caption="Figure 1 Gain vs Frequency",
            x_label="Output Frequency", x_unit="MHz", x_min=600.0, x_max=1500.0,
            x_scale=AxisScale.LINEAR, y_label="Gain", y_unit="dB",
            y_min=0.0, y_max=20.0, y_scale=AxisScale.LINEAR,
            axis_confidence=Confidence.HIGH, axis_page=29,
        )])
        # The second device's plot is a raster image: nothing readable, and it
        # must not be what an empty axis-filtered result is read as absence from.
        _axis_member(tmp_path, "B", [PlotRecord(
            id="b1", figure_number="1", caption="Figure 1 Output Spectrum",
            axis_confidence=Confidence.LOW,
        )])
        return ProjectRetriever.for_parts("board", [tmp_path / "A", tmp_path / "B"])

    def test_the_filter_fans_out_and_every_hit_names_its_part(self, scope):
        hits = scope.plots(near_x="1.2GHz")
        assert [(h.citation.part, h.record.id) for h in hits] == [("A", "a1")]
        assert hits[0].matched_via == "axis-range"

    def test_the_label_filter_fans_out_too(self, scope):
        assert [h.citation.part for h in scope.plots(x_label="Frequency")] == ["A"]
        assert scope.plots(x_label="Temperature") == []

    def test_the_gap_is_one_line_per_member_that_has_one(self, scope):
        gap = scope.plot_axis_gap()
        assert "part B" in gap
        assert "part A" not in gap, "a member with nothing to report says nothing"
        assert len(gap.splitlines()) == 1

    def test_a_lookup_that_filtered_on_no_axis_owes_no_gap(self, scope):
        assert scope.plot_axis_gap_for() == ""
        assert "no readable y axis" in scope.plot_axis_gap_for(y_label="Gain")
        assert "no readable x axis" in scope.plot_axis_gap_for(near_x="1.2GHz")


class TestAxisRendering:
    def test_the_axis_line_quotes_the_printed_range_and_unit(self, axis_part):
        hits = Retriever.for_part(axis_part).plots(x_label="Frequency")
        line = format_axes(hits[0].record)
        assert "x: Output Frequency 600–1500 MHz (linear)" in line
        assert "y: Output Full Scale -2–7 dBm (linear)" in line

    def test_a_figure_with_no_axes_renders_no_axis_line(self, axis_part):
        hits = Retriever.for_part(axis_part).plots(q="FFT")
        assert format_axes(hits[0].record) == ""

    def test_the_json_shape_always_carries_the_axis_grade(self, axis_part):
        """A figure with no axes says so in one field, not in fifteen nulls: the
        same shape is an MCP response, and a cap exists to buy room for
        citations."""
        payload = Retriever.for_part(axis_part).plots(q="FFT")[0].as_dict()
        assert payload["axis_confidence"] == "low"
        assert payload["axes"] is None

    def test_the_json_shape_carries_the_block_when_it_was_read(self, axis_part):
        payload = Retriever.for_part(axis_part).plots(x_label="Frequency")[0].as_dict()
        assert payload["axis_confidence"] == "high"
        assert payload["axes"]["x"] == {
            "label": "Output Frequency", "unit": "MHz",
            "min": 600.0, "max": 1500.0, "scale": "linear",
        }
        assert payload["axes"]["page"] == 29
        assert payload["axes"]["derivation"].startswith("figure_region")


class TestPlotsCli:
    @pytest.fixture
    def settings(self, tmp_path, monkeypatch) -> Settings:
        _axis_part(tmp_path)
        resolved = Settings(parts_dir=tmp_path / "parts",
                            cache_dir=tmp_path / ".cache").resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: resolved)
        return resolved

    def test_near_x_narrows_and_prints_the_gap(self, settings, capsys):
        assert cli.main(["plots", "--part", "TEST", "--near-x", "1.35GHz"]) == 0
        out = capsys.readouterr().out
        assert "Figure 4-1 TX Output Fullscale vs Output Frequency" in out
        assert "Figure 4-2" not in out
        assert "axes — x: Output Frequency 600–1500 MHz (linear)" in out
        assert "note: 1 of 3 figures publish no readable x axis" in out

    def test_y_label_reports_the_y_population(self, settings, capsys):
        assert cli.main(["plots", "--part", "TEST", "--y-label", "Full Scale"]) == 0
        assert "no readable y axis" in capsys.readouterr().out

    def test_json_carries_the_query_the_axes_and_the_gap(self, settings, capsys):
        assert cli.main(
            ["plots", "--part", "TEST", "--x-label", "Frequency", "--json"]
        ) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["query"]["x_label"] == "Frequency"
        assert payload["hits"][0]["axes"]["x"]["scale"] == "linear"
        assert payload["hits"][0]["axis_confidence"] == "high"
        assert "no readable x axis" in payload["axis_gap"]

    def test_a_plain_lookup_reports_no_axis_gap(self, settings, capsys):
        assert cli.main(["plots", "--part", "TEST", "--q", "Fullscale"]) == 0
        assert "note:" not in capsys.readouterr().out
