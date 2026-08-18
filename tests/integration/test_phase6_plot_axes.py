"""Phase 6, ticket 08: the axis catalog measured against the real documents.

Three questions a synthetic PDF cannot answer:

1. **How much of a real gallery is actually readable?** The gate is
   AFE7950's 514 figures at `axis_confidence: high` — a floor to beat and to
   record, never a target to fit to. Every part with a local PDF is measured
   and printed for the phase report, including the ones that read nothing.
2. **Are the values right?** Coverage is worthless if the numbers are wrong,
   so the figures asserted here were read off the printed page by hand:
   Figure 4-1 on page 29 prints "Output Frequency (MHz)" from 600 to 1500
   under "Output Full Scale (dBm)" from -2 to 7.
3. **Do the filters narrow a real catalog?** `find_plots --y-label
   --near-x` is what the catalog exists for; here it runs over the annotated
   AFE7950 catalog rather than three hand-written records.

Hermetic in the sense that matters (AGENTS.md invariant 4's documented
exception for corpus gates): it reads a PDF and JSON already on disk, never
the network, never a model, and skips itself when they are absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.models import Confidence, PlotSet
from datasheet_analyzer.query import find_plots
from datasheet_analyzer.structure.plot_axes import annotate_plot_axes

REPO = Path(__file__).parent.parent.parent
PARTS = REPO / "parts"

#: The ticket's floor: >= 60% of AFE7950's 514 figures at `high`. Measured at
#: 77.8% when the catalog landed. A build below this has regressed the
#: geometry; a build above it has not "passed a quota", it has read more of
#: the page.
HIGH_FRACTION_FLOOR = 0.60


def _catalogs() -> list[tuple[str, Path, Path]]:
    """(part, plots.json, source PDF) for every built part with a local PDF."""
    out: list[tuple[str, Path, Path]] = []
    for manifest_path in sorted(PARTS.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sources = {
            doc["content_hash"][:8]: Path(doc["path"]) for doc in manifest.get("documents", [])
        }
        docs_dir = manifest_path.parent / "docs"
        if not docs_dir.is_dir():
            continue
        for doc_dir in sorted(docs_dir.iterdir()):
            plots_json = doc_dir / "plots.json"
            if not plots_json.is_file():
                continue
            doc_hash = json.loads(plots_json.read_text(encoding="utf-8")).get("doc_hash", "")
            pdf = sources.get(doc_hash[:8])
            if pdf is not None and pdf.suffix.lower() == ".pdf" and pdf.is_file():
                out.append((manifest_path.parent.name, plots_json, pdf))
    return out


def _annotate(plots_json: Path, pdf: Path) -> tuple[PlotSet, object]:
    plotset = PlotSet.model_validate(json.loads(plots_json.read_text(encoding="utf-8")))
    coverage = annotate_plot_axes(plotset, pdf)
    return plotset, coverage


@pytest.fixture(scope="module")
def afe7950_axes() -> tuple[PlotSet, object]:
    hits = [entry for entry in _catalogs() if entry[0] == "AFE7950"]
    if not hits:
        pytest.skip("AFE7950 corpus or afe7950.pdf not present")
    _part, plots_json, pdf = hits[0]
    return _annotate(plots_json, pdf)


def test_axis_coverage_gate(afe7950_axes, capsys):
    """>= 60% of AFE7950's figures read at high axis confidence."""
    plotset, coverage = afe7950_axes
    with capsys.disabled():
        print(f"\nAFE7950 axis coverage: {json.dumps(coverage.as_dict())}")
    assert coverage.total == len(plotset.plots)
    assert coverage.high_fraction >= HIGH_FRACTION_FLOOR, (
        f"axis coverage regressed: {coverage.high}/{coverage.total} "
        f"= {coverage.high_fraction:.1%} < {HIGH_FRACTION_FLOOR:.0%}"
    )


def test_coverage_is_recorded_for_every_part_with_a_pdf(capsys):
    """Per-part coverage for the phase report — including the honest zeroes.

    A datasheet whose plots are raster screenshots (AD9081, lm741) reads
    nothing, and that is a property of the document rather than a failure of
    the pass: this catalog reads printed text and does not analyse pixels.
    """
    entries = _catalogs()
    if not entries:
        pytest.skip("no built part has a local source PDF")
    rows: list[str] = []
    for part, plots_json, pdf in entries:
        plotset, coverage = _annotate(plots_json, pdf)
        rows.append(
            f"  {part:<10} {coverage.total:>4} figures  "
            f"high {coverage.high:>4} ({coverage.high_fraction:6.1%})  "
            f"log {coverage.log_axes:>3}"
        )
        # whatever the coverage, the catalog is intact
        assert coverage.total == len(plotset.plots)
        assert all(rec.caption or rec.image_url or rec.file for rec in plotset.plots)
    with capsys.disabled():
        print("\nplot axis coverage per part:\n" + "\n".join(rows))


def test_hand_checked_figure_values(afe7950_axes):
    """Figure 4-1, printed on page 29 of SBASA41E, read by hand."""
    plotset, _coverage = afe7950_axes
    by_number = {rec.figure_number: rec for rec in plotset.plots}
    fig = by_number["4-1"]
    assert (fig.x_label, fig.x_unit) == ("Output Frequency", "MHz")
    assert (fig.x_min, fig.x_max) == (600.0, 1500.0)
    # the y title is printed rotated 90 degrees on the real page
    assert (fig.y_label, fig.y_unit) == ("Output Full Scale", "dBm")
    assert (fig.y_min, fig.y_max) == (-2.0, 7.0)
    assert fig.axis_confidence is Confidence.HIGH

    # a second hand-checked figure from the same page, with a different pair
    # of axes, so one lucky read cannot carry the assertion
    fig3 = by_number["4-3"]
    assert (fig3.x_label, fig3.x_unit, fig3.x_min, fig3.x_max) == ("DSA", "dB", 0.0, 40.0)
    assert (fig3.y_label, fig3.y_unit, fig3.y_min, fig3.y_max) == (
        "Output Power",
        "dBm",
        -35.0,
        5.0,
    )


def test_real_log_axis_is_marked_low_with_its_printed_endpoints(afe7950_axes):
    """The phase-noise figures print a decade x axis (1 kHz to 100 MHz).

    Their range is printed, so it is kept; the grade is `low` so that nothing
    downstream reads a linear mapping into a log axis.
    """
    plotset, coverage = afe7950_axes
    by_number = {rec.figure_number: rec for rec in plotset.plots}
    fig = by_number["4-493"]
    assert fig.x_label == "Offset Frequency"
    assert (fig.x_min, fig.x_max) == (1_000.0, 100_000_000.0)
    assert fig.y_label == "Phase Noise"
    assert fig.axis_confidence is Confidence.LOW
    assert coverage.log_axes >= 1


def test_every_figure_survives_the_pass(afe7950_axes):
    """No plot is lost to a failed axis parse, and nothing uncertain is
    filled in: a record without a range has no half of one either."""
    plotset, _coverage = afe7950_axes
    assert len(plotset.plots) == 514
    for rec in plotset.plots:
        assert rec.caption
        assert rec.axis_confidence is not Confidence.UNKNOWN
        assert (rec.x_min is None) == (rec.x_max is None)
        assert (rec.y_min is None) == (rec.y_max is None)
        if rec.axis_confidence is Confidence.HIGH:
            assert rec.x_label and rec.y_label
            assert rec.x_min is not None and rec.y_min is not None


def test_find_plots_narrows_the_real_catalog(afe7950_axes, tmp_path):
    """Hand-checked narrowing: of 514 figures, the ones whose y axis is
    labelled "Phase Noise" and whose x sweep covers 10 MHz offset are the
    phase-noise plots and nothing else."""
    plotset, _coverage = afe7950_axes
    part_dir = tmp_path / "parts" / "AFE7950"
    doc_dir = part_dir / "docs" / "datasheet-c1b4663b"
    doc_dir.mkdir(parents=True)
    (doc_dir / "plots.json").write_text(plotset.model_dump_json(indent=2), encoding="utf-8")

    everything = find_plots(part_dir)
    assert len(everything) == 514

    phase_noise = find_plots(part_dir, y_label="Phase Noise", near_x="10MHz")
    assert 0 < len(phase_noise) < len(everything)
    for rec in phase_noise:
        assert "Phase Noise" in rec.y_label
        assert rec.x_min <= 10_000_000.0 <= rec.x_max

    # a sweep no figure covers narrows to nothing rather than to a guess
    assert find_plots(part_dir, y_label="Phase Noise", near_x="10THz") == []

    # and the caption filter still composes with the axis one
    both = find_plots(part_dir, q="Phase Noise", y_label="Phase Noise")
    assert both and len(both) <= len(find_plots(part_dir, q="Phase Noise"))
