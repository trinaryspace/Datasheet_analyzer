"""Regression: `dsa verify` spec/plot summary lines must count only passing
questions. A generator missing `if ok` made every run claim N/N passed even
when the per-row table showed ❌ (exit code was still correct).

Also (phase 5, ticket 09) the wiring of the two paths the phase added: `dsa
verify` must *run* a golden set's ask- and search-path questions and fail on
them, exactly as it does for spec and plot queries — a benchmark the command
silently skips is not a benchmark.
"""

from __future__ import annotations

import yaml
from mcp_corpus import build_part as build_mcp_part

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
    settings = _part_settings(tmp_path)
    golden_path = tmp_path / "golden.yaml"
    golden_path.write_text(yaml.safe_dump(GOLDEN), encoding="utf-8")

    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    exit_code = cli.main(["verify", "--part", "T", "--specs", "--golden", str(golden_path)])

    out = capsys.readouterr().out
    assert exit_code == 1
    # 1 of 2 spec queries and 1 of 2 plot queries pass — the summary must not
    # round that up to 2/2.
    assert out.count("**1/2 passed**") == 2
    assert "**2/2 passed**" not in out


PLOT_ONLY_GOLDEN = {
    "questions": [
        {
            "id": "plot-pass-only",
            "question": "passes",
            "expected_substrings": ["DSA = 0"],
            "pages": [29],
            "plot_query": {"caption_contains": "Output Fullscale"},
        },
    ]
}


def _part_settings(tmp_path):
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    part_dir = settings.parts_dir / "T"
    part_dir.mkdir(parents=True)
    _make_part(part_dir)
    return settings


class TestPerPartGoldenDiscovery:
    """SPEC story 26: `dsa verify --part X` resolves golden_qa_<PART>.yaml
    by part name and hard-fails (no silent zero-question pass) when a
    part's benchmark is missing or empty."""

    def test_default_golden_is_per_part_by_name(self, monkeypatch):
        # With no override the benchmark lives beside the committed ones. The
        # suite always sets `DSA_GOLDEN_DIR` (conftest), because `dsa golden
        # confirm` writes here - so the unoverridden rule is asserted by
        # clearing it rather than by trusting the ambient environment.
        from datasheet_analyzer.config import reset_settings_cache
        from datasheet_analyzer.evalh.golden import GOLDEN_DIR

        monkeypatch.delenv("DSA_GOLDEN_DIR", raising=False)
        reset_settings_cache()
        path = cli._default_golden_path("AFE7950")
        assert path.name == "golden_qa_AFE7950.yaml"
        assert path.parent.name == "fixtures"
        assert path.parent == GOLDEN_DIR
        reset_settings_cache()

    def test_the_golden_directory_follows_its_setting(self, monkeypatch, tmp_path):
        """`DSA_GOLDEN_DIR` is what keeps a confirm run off the real fixtures."""
        from datasheet_analyzer.config import reset_settings_cache

        monkeypatch.setenv("DSA_GOLDEN_DIR", str(tmp_path / "elsewhere"))
        reset_settings_cache()
        assert cli._default_golden_path("AFE7950") == (
            tmp_path / "elsewhere" / "golden_qa_AFE7950.yaml"
        )
        reset_settings_cache()

    def test_verify_discovers_golden_from_part_name(self, tmp_path, monkeypatch, capsys):
        settings = _part_settings(tmp_path)
        golden_path = tmp_path / "golden_qa_T.yaml"
        golden_path.write_text(yaml.safe_dump(PLOT_ONLY_GOLDEN), encoding="utf-8")

        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        monkeypatch.setattr(
            "datasheet_analyzer.cli._default_golden_path",
            lambda part: golden_path,
        )
        # no --golden flag: discovery + full verification, quiet success
        exit_code = cli.main(["verify", "--part", "T", "--specs"])
        assert exit_code == 0
        assert "**1/1 passed" in capsys.readouterr().out

    def test_verify_hard_fails_when_part_golden_missing(self, tmp_path, monkeypatch, capsys):
        settings = _part_settings(tmp_path)
        missing = tmp_path / "golden_qa_NOSUCHPART.yaml"
        assert not missing.exists()

        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        monkeypatch.setattr(
            "datasheet_analyzer.cli._default_golden_path",
            lambda part: missing,
        )
        exit_code = cli.main(["verify", "--part", "T"])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "no golden benchmark" in captured.err
        assert "NOSUCHPART" in captured.err

    def test_verify_hard_fails_on_empty_golden(self, tmp_path, monkeypatch, capsys):
        settings = _part_settings(tmp_path)
        golden_path = tmp_path / "golden_qa_T.yaml"
        golden_path.write_text("questions: []\n", encoding="utf-8")

        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        monkeypatch.setattr(
            "datasheet_analyzer.cli._default_golden_path",
            lambda part: golden_path,
        )
        exit_code = cli.main(["verify", "--part", "T"])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "0 questions" in captured.err

    def test_verify_explicit_golden_missing_fails_loudly(self, tmp_path, monkeypatch, capsys):
        # previously an unhandled FileNotFoundError traceback
        settings = _part_settings(tmp_path)
        missing = tmp_path / "no-such-golden.yaml"

        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        exit_code = cli.main(["verify", "--part", "T", "--golden", str(missing)])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "no golden benchmark" in captured.err
        assert "FileNotFoundError" not in captured.err


PATH_GOLDEN = {
    "questions": [
        {
            "id": "ask-pass",
            "question": "What is the maximum junction temperature?",
            "expected_substrings": ["Operating junction temperature", "105"],
            "pages": [6],
            "kind": "ask",
            "ask_query": {"route": "spec"},
        },
        {
            "id": "ask-fail",
            "question": "What is the maximum junction temperature?",
            "expected_substrings": ["105"],
            "pages": [99],
            "kind": "ask",
            "ask_query": {"route": "spec"},
        },
        {
            "id": "search-pass",
            "question": "Where is the SYSREF setup requirement?",
            "expected_substrings": ["SYSREF setup time"],
            "pages": [7],
            "kind": "search",
            "search_query": {"query": "sysref setup"},
        },
        {
            "id": "search-fail",
            "question": "Where is the SYSREF setup requirement?",
            "expected_substrings": ["SYSREF setup time"],
            "pages": [6],
            "kind": "search",
            "search_query": {"query": "sysref setup"},
        },
    ]
}


class TestVerifyRunsTheNewPaths:
    """Phase 5, ticket 09: `dsa verify` runs a golden set's ask- and
    search-path questions, renders each as its own table, counts only the
    passing ones, and fails the command when one fails. Both tables run
    without `--pdf`: their ground truth is the page the question already
    cites, and both paths read only the corpus."""

    def _settings(self, tmp_path):
        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        build_mcp_part(settings.parts_dir / "T")
        return settings

    def _run(self, tmp_path, monkeypatch, golden: dict) -> int:
        settings = self._settings(tmp_path)
        path = tmp_path / "golden.yaml"
        path.write_text(yaml.safe_dump(golden), encoding="utf-8")
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        return cli.main(["verify", "--part", "T", "--golden", str(path)])

    def test_both_tables_render_and_count_only_passing(self, tmp_path, monkeypatch, capsys):
        exit_code = self._run(tmp_path, monkeypatch, PATH_GOLDEN)
        out = capsys.readouterr().out
        assert "## Ask-path verification (deterministic)" in out
        assert "## Search-path verification (deterministic)" in out
        # one of two passes in each table — and a failing path fails the run
        assert out.count("**1/2 passed**") == 2
        assert exit_code == 1

    def test_a_set_without_the_markers_prints_neither_table(self, tmp_path, monkeypatch, capsys):
        """Additive, like the plot table before it: a benchmark written before
        these paths existed still verifies, and says nothing about them."""
        golden = {
            "questions": [
                dict(PATH_GOLDEN["questions"][0], ask_query=None, search_query=None, kind="direct")
            ]
        }
        self._run(tmp_path, monkeypatch, golden)
        out = capsys.readouterr().out
        assert "Ask-path verification" not in out
        assert "Search-path verification" not in out

    def test_a_passing_set_passes_both_paths(self, tmp_path, monkeypatch, capsys):
        """Both paths green on their own terms. The command still reports the
        page-truth table as unproven here, because it was run without `--pdf`
        — which is exactly the honest degradation the text check already had,
        and the reason the new tables do not depend on it."""
        golden = {"questions": [q for q in PATH_GOLDEN["questions"] if q["id"].endswith("pass")]}
        self._run(tmp_path, monkeypatch, golden)
        out = capsys.readouterr().out
        assert out.count("**1/1 passed**") == 2
        tail = out.split("Ask-path verification")[1]
        assert "❌" not in tail
        # the measured cost of the pack, against the budget it was given
        assert "tok" in tail
