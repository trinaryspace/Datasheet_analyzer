"""Regression: `dsa verify` spec/plot summary lines must count only passing
questions. A generator missing `if ok` made every run claim N/N passed even
when the per-row table showed ❌ (exit code was still correct)."""

from __future__ import annotations

import yaml

from datasheet_analyzer import cli
from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import PlotRecord, PlotSet, SpecRecord, SpecSet, SpecUnit

DOC = "datasheet-deadbeef"

GOLDEN = {
    "questions": [
        {
            "id": "spec-pass",
            "question": "passes",
            "expected_substrings": ["14", "bits"],
            "pages": [7],
            "spec_query": {"symbol": "DACRES"},
        },
        {
            "id": "spec-fail",
            "question": "fails: no such spec",
            "expected_substrings": ["zzz"],
            "pages": [1],
            "spec_query": {"symbol": "NOSUCHSYMBOL"},
        },
        {
            "id": "plot-pass",
            "question": "passes",
            "expected_substrings": ["DSA = 0"],
            "pages": [29],
            "plot_query": {"caption_contains": "Output Fullscale"},
        },
        {
            "id": "plot-fail",
            "question": "fails: no such plot",
            "expected_substrings": ["zzz"],
            "pages": [1],
            "plot_query": {"caption_contains": "NOSUCHPLOT"},
        },
    ]
}


def _make_part(part_dir):
    doc_dir = part_dir / "docs" / DOC
    (doc_dir / "figures").mkdir(parents=True)
    (part_dir / "manifest.json").write_text('{"sections": []}', encoding="utf-8")

    specset = SpecSet(
        schema_version="1",
        part_number="T",
        records=[
            SpecRecord(
                section="4.5",
                symbol="DACRES",
                name="DAC resolution",
                value="14",
                unit=SpecUnit(verbatim="bits", canonical="bits"),
                page=7,
            )
        ],
    )
    (doc_dir / "specs.json").write_text(specset.model_dump_json(), encoding="utf-8")

    plotset = PlotSet(
        schema_version="1",
        part_number="T",
        plots=[
            PlotRecord(
                id="4.12.1-f001",
                section="4.12.1",
                caption="TX Output Fullscale vs Output Frequency",
                conditions="DSA = 0",
                page_start=29,
                page_end=37,
                file=f"docs/{DOC}/figures/f1.gif",
            )
        ],
    )
    (doc_dir / "plots.json").write_text(plotset.model_dump_json(), encoding="utf-8")
    (doc_dir / "figures" / "f1.gif").write_bytes(b"\x00" * 2048)  # >1 KB requirement


def test_verify_summary_counts_only_passing(tmp_path, monkeypatch, capsys):
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    part_dir = settings.parts_dir / "T"
    part_dir.mkdir(parents=True)
    _make_part(part_dir)
    golden_path = tmp_path / "golden.yaml"
    golden_path.write_text(yaml.safe_dump(GOLDEN), encoding="utf-8")

    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    exit_code = cli.main(
        ["verify", "--part", "T", "--specs", "--golden", str(golden_path)]
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    # 1 of 2 spec queries and 1 of 2 plot queries pass — the summary must not
    # round that up to 2/2.
    assert out.count("**1/2 passed**") == 2
    assert "**2/2 passed**" not in out
