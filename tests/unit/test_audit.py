"""`dsa audit` — the corpus scorecard and its rubric (phase 7, ticket 05).

What these prove, criterion by criterion:

- **every metric the plan names is graded**, and the scorecard publishes all
  thirteen of them whether or not the corpus can answer each one;
- **the rubric is data-driven** — asserted three ways, because "the thresholds
  are not in Python" is the ticket's own acceptance criterion and one
  assertion can be satisfied by accident. Editing a threshold in the YAML moves
  a metric's grade; editing a weight moves the overall grade; **deleting** a
  metric from the YAML makes it `n/a`, which is what proves there is no hidden
  Python fallback behind the data;
- **an unavailable metric is neither zero nor full marks** — the sharpest test
  here. The same corpus is graded twice, once with `tables_pinned: null` (the
  statistic was never recorded) and once with `tables_pinned: 0` (it was
  recorded and it is zero). The first must be `n/a` and excluded; the second
  must be graded, and must score strictly *lower*. If `n/a` were being read as
  0 the two would tie;
- **missing artifacts reduce the grade rather than erroring** — a corpus with
  no pins, no registers and no card rows still produces a scorecard, with those
  three graded down;
- **the staleness banner reaches this surface** — the `dsa audit` scorecard is
  one of the four places ticket 02 requires the warning, and until this ticket
  it was only reachable through `staleness.audit_metric`;
- **MCP `get_audit` exposes the grade**, validates against its declared schema,
  and carries the headline sentence an agent uses to downgrade its own
  confidence language;
- **no model call anywhere in the derivation path** (invariant 8), asserted as
  a source-level guard over the package, and every metric carries `source` and
  `derivation`.

Hermetic by construction (invariant 4): the corpora are the synthetic ones
`mcp_corpus.py` already builds and one hand-written manifest. Nothing here
touches the network, an LLM, or a real PDF.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from mcp_corpus import built_settings

from datasheet_analyzer import cli
from datasheet_analyzer.audit import (
    METRIC_KEYS,
    RUBRIC_PATH,
    AuditRubric,
    build_scorecard,
    clear_audit_rubric_cache,
    load_audit_rubric,
    render_fleet,
    render_scorecard,
)
from datasheet_analyzer.audit import rubric as rubric_module
from datasheet_analyzer.config import AUDIT_SCHEMA_VERSION, Settings
from datasheet_analyzer.models import AuditGrade, CorpusManifest, MetricKind
from datasheet_analyzer.retrieve import clear_index_cache

SRC = Path(__file__).resolve().parent.parent.parent / "src" / "datasheet_analyzer"


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Two structurally real, modern corpora (`TEST` and `OTHER`)."""
    return built_settings(tmp_path)


@pytest.fixture
def part_dir(settings: Settings) -> Path:
    return settings.parts_dir / "TEST"


@pytest.fixture(autouse=True)
def fresh_rubric():
    """The packaged rubric is process-cached; a test that repoints it must not
    leak that into the next one."""
    clear_audit_rubric_cache()
    yield
    clear_audit_rubric_cache()


def _rewrite_manifest(part_dir: Path, **stats) -> None:
    """Edit a built corpus's manifest statistics in place, then drop the cache."""
    path = part_dir / "manifest.json"
    manifest = CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))
    for key, value in stats.items():
        setattr(manifest.stats, key, value)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    clear_index_cache()


def _edited_rubric(tmp_path: Path, edit) -> Path:
    """A copy of the shipped rubric with `edit(data)` applied, on disk."""
    data = yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))
    edit(data)
    dest = tmp_path / "audit_rubric.yaml"
    dest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return dest


# --- the metric surface ------------------------------------------------------


class TestEveryMetricIsGraded:
    def test_the_scorecard_publishes_every_metric_the_plan_names(self, part_dir):
        card = build_scorecard(part_dir)
        assert [m.key for m in card.metrics] == list(METRIC_KEYS)
        # the plan's table, key by key — a metric quietly dropped from
        # METRIC_KEYS would otherwise pass the assertion above
        assert set(METRIC_KEYS) == {
            "section_page_coverage", "table_pin_rate", "table_accept_rate",
            "mean_fidelity", "spec_page_rate", "record_confidence",
            "pins_present", "registers_present", "cards_present",
            "axis_coverage", "alias_hit_rate", "revision_freshness",
            "golden_pass_rate",
        }

    def test_a_real_corpus_grades_and_carries_its_headline(self, part_dir):
        card = build_scorecard(part_dir)
        assert card.grade is not None
        assert card.score is not None
        assert card.part == "TEST"
        assert card.schema_version == AUDIT_SCHEMA_VERSION
        assert card.rubric_version == load_audit_rubric().schema_version
        assert card.headline.startswith("This corpus grades ")
        assert card.n_graded + card.n_unavailable == len(card.metrics)

    def test_every_metric_carries_its_source_and_its_rule(self, part_dir):
        """Invariant 8: a derived value names where it came from and what made it."""
        card = build_scorecard(part_dir)
        missing = [m.key for m in card.metrics if not m.source or not m.derivation]
        assert missing == []

    def test_the_readings_are_the_corpus_s_own_counts(self, part_dir):
        """Spot-check two metrics against the manifest they were read from."""
        manifest = CorpusManifest.model_validate_json(
            (part_dir / "manifest.json").read_text(encoding="utf-8")
        )
        by_key = {m.key: m for m in build_scorecard(part_dir).metrics}
        coverage = by_key["section_page_coverage"]
        assert coverage.numerator == manifest.stats.sections_with_pages
        assert by_key["pins_present"].numerator == manifest.stats.n_pins
        assert by_key["pins_present"].kind is MetricKind.BOOLEAN

    def test_an_unbuilt_part_grades_nothing_and_names_the_build_command(self, tmp_path):
        empty = tmp_path / "parts" / "NOTBUILT"
        empty.mkdir(parents=True)
        card = build_scorecard(empty)
        assert card.grade is None and card.metrics == []
        assert "dsa build" in card.notes[0]
        assert "ungraded" in card.headline


# --- the ticket's data-driven criterion --------------------------------------


class TestTheRubricIsData:
    """Editing `registry/audit_rubric.yaml` must change a grade.

    Three assertions, because the criterion is about the *absence* of hidden
    Python: a threshold move, a weight move, and a deletion.
    """

    def test_raising_a_threshold_lowers_that_metric_s_grade(self, part_dir, tmp_path):
        before = {m.key: m.grade for m in build_scorecard(part_dir).metrics}
        assert before["section_page_coverage"] is AuditGrade.A

        def raise_it(data):
            # 100 % coverage no longer earns an A; nothing under 1.5 earns one,
            # and a ratio is never above 1.0, so the top rung is now the D.
            data["metrics"]["section_page_coverage"]["thresholds"] = [
                {"grade": "A", "min": 1.5},
                {"grade": "D", "min": 0.0},
            ]

        edited = AuditRubric.read(_edited_rubric(tmp_path, raise_it))
        after = {m.key: m.grade for m in build_scorecard(part_dir, rubric=edited).metrics}
        assert after["section_page_coverage"] is AuditGrade.D
        # and only that metric moved
        assert {k: v for k, v in after.items() if k != "section_page_coverage"} == {
            k: v for k, v in before.items() if k != "section_page_coverage"
        }

    def test_reweighting_moves_the_overall_grade(self, part_dir, tmp_path):
        base = build_scorecard(part_dir)
        assert base.grade is not None

        def sink_it(data):
            # The corpus reads `unknown` freshness, which the rubric grades C.
            # Make that the only metric that counts and the whole corpus is a C.
            for key, body in data["metrics"].items():
                body["weight"] = 100 if key == "revision_freshness" else 0

        edited = AuditRubric.read(_edited_rubric(tmp_path, sink_it))
        card = build_scorecard(part_dir, rubric=edited)
        assert card.grade is AuditGrade.C
        assert card.grade is not base.grade or base.grade is AuditGrade.C

    def test_deleting_a_metric_makes_it_n_a_rather_than_falling_back(
        self, part_dir, tmp_path
    ):
        """The proof there is no threshold hidden in Python behind the YAML."""

        def drop_it(data):
            del data["metrics"]["record_confidence"]

        graded = next(
            m for m in build_scorecard(part_dir).metrics if m.key == "record_confidence"
        )
        assert graded.available is True and graded.value is not None

        edited = AuditRubric.read(_edited_rubric(tmp_path, drop_it))
        card = build_scorecard(part_dir, rubric=edited)
        metric = next(m for m in card.metrics if m.key == "record_confidence")
        assert metric.grade is None and metric.available is False
        assert "record_confidence" in metric.unavailable_reason
        assert card.n_graded == build_scorecard(part_dir).n_graded - 1
        # the reading was real, so it is kept — but not in `value`, which
        # `available: false` promises is null. A payload that says "not
        # measured" while carrying a number is one a client cannot act on.
        assert metric.value is None and metric.numerator is None
        assert f"read {graded.value:.0%}" in metric.detail

    def test_the_packaged_rubric_is_what_the_default_reads(self, monkeypatch, tmp_path):
        """`load_audit_rubric()` reads the checked-in file, not a built-in copy."""
        shipped = load_audit_rubric()
        assert shipped.keys == METRIC_KEYS
        assert shipped.unavailable_policy
        clear_audit_rubric_cache()
        monkeypatch.setattr(rubric_module, "RUBRIC_PATH", tmp_path / "nothing.yaml")
        assert load_audit_rubric().rules == ()

    def test_an_unreadable_rubric_grades_nothing_and_says_so(self, part_dir, tmp_path):
        """Honest degradation (invariant 7): no rubric, no invented grade."""
        broken = tmp_path / "broken.yaml"
        broken.write_text("metrics: [not, a, mapping\n", encoding="utf-8")
        card = build_scorecard(part_dir, rubric=AuditRubric.read(broken))
        assert card.grade is None and card.score is None
        assert card.n_graded == 0 and card.n_unavailable == len(METRIC_KEYS)
        assert card.notes and "rubric" in card.notes[0]

    def test_the_cli_reads_the_rubric_file_too(
        self, settings, monkeypatch, capsys, tmp_path
    ):
        """The data-driven criterion, end to end through `dsa audit`."""

        def sink_it(data):
            for key, body in data["metrics"].items():
                body["weight"] = 100 if key == "revision_freshness" else 0

        edited = _edited_rubric(tmp_path, sink_it)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["audit", "TEST"]) == 0
        first = capsys.readouterr().out
        clear_audit_rubric_cache()
        monkeypatch.setattr(rubric_module, "RUBRIC_PATH", edited)
        assert cli.main(["audit", "TEST"]) == 0
        second = capsys.readouterr().out
        assert "**Grade: C**" in second
        assert first != second


# --- the n/a rule ------------------------------------------------------------


class TestUnavailableIsNeitherZeroNorFullMarks:
    def test_a_null_statistic_is_n_a_and_a_recorded_zero_is_graded(self, part_dir):
        """The sharp one: `null` and `0` must not produce the same grade.

        `tables_pinned` is the field built for exactly this distinction — a
        corpus published before it existed carries `null`, and one whose tables
        genuinely could not be pinned carries `0`.
        """
        _rewrite_manifest(part_dir, n_tables=10, tables_pinned=None)
        absent = build_scorecard(part_dir)
        _rewrite_manifest(part_dir, n_tables=10, tables_pinned=0)
        zero = build_scorecard(part_dir)

        missing = next(m for m in absent.metrics if m.key == "table_pin_rate")
        measured = next(m for m in zero.metrics if m.key == "table_pin_rate")
        assert missing.available is False and missing.grade is None
        assert missing.value is None
        assert measured.available is True and measured.value == 0.0
        assert measured.grade is not None
        # excluded, not scored: one fewer graded metric, and a *better* score
        assert absent.n_graded == zero.n_graded - 1
        assert absent.score is not None and zero.score is not None
        assert absent.score > zero.score

    def test_a_null_statistic_is_not_full_marks_either(self, part_dir):
        """The other half: `n/a` must not flatter a corpus into an A."""
        _rewrite_manifest(part_dir, n_tables=10, tables_pinned=None)
        absent = build_scorecard(part_dir)
        _rewrite_manifest(part_dir, n_tables=10, tables_pinned=10)
        perfect = build_scorecard(part_dir)
        assert perfect.score is not None and absent.score is not None
        assert perfect.score > absent.score

    def test_the_policy_travels_in_the_output(self, part_dir):
        card = build_scorecard(part_dir)
        assert "never scored 0" in card.unavailable_policy
        assert card.unavailable_policy in render_scorecard(card)

    def test_an_n_a_metric_keeps_its_row_and_its_reason(self, part_dir):
        """Dropping the row would leave a scorecard that looks complete."""
        card = build_scorecard(part_dir)
        rendered = render_scorecard(card)
        for metric in card.metrics:
            assert metric.label in rendered
            if not metric.available:
                assert metric.unavailable_reason
                assert metric.unavailable_reason in rendered

    def test_a_corpus_predating_the_derived_artifacts_reports_n_a_not_absence(
        self, part_dir
    ):
        """The reference-corpus case: no `card_version` means "not measured"."""
        path = part_dir / "manifest.json"
        manifest = CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))
        manifest.card_version = ""
        manifest.stats.n_pins = 0
        manifest.stats.n_registers = 0
        manifest.stats.n_card_rows = 0
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        clear_index_cache()
        card = build_scorecard(part_dir)
        for key in ("pins_present", "registers_present", "cards_present"):
            metric = next(m for m in card.metrics if m.key == key)
            assert metric.available is False, key
            assert "predates the derived artifacts" in metric.unavailable_reason
        assert any("needs a rebuild" in note for note in card.notes)

    def test_too_few_metrics_means_no_overall_grade(self, part_dir, tmp_path):
        def demand_more(data):
            data["min_graded_metrics"] = 99

        edited = AuditRubric.read(_edited_rubric(tmp_path, demand_more))
        card = build_scorecard(part_dir, rubric=edited)
        assert card.grade is None and card.score is None
        assert "metrics could be computed" in card.notes[0]
        assert "ungraded" in card.headline


# --- missing artifacts -------------------------------------------------------


class TestMissingArtifactsReduceTheGradeRatherThanErroring:
    def test_a_modern_corpus_with_no_pins_registers_or_cards_still_grades(
        self, part_dir
    ):
        rich = build_scorecard(part_dir)
        _rewrite_manifest(part_dir, n_pins=0, n_registers=0, n_card_rows=0, n_cards=4)
        poor = build_scorecard(part_dir)
        assert poor.grade is not None  # graded, not an exception
        assert poor.n_graded == rich.n_graded
        for key in ("pins_present", "registers_present", "cards_present"):
            metric = next(m for m in poor.metrics if m.key == key)
            assert metric.available is True and metric.state == "false"
            assert metric.grade is not AuditGrade.A, key
        assert poor.score is not None and rich.score is not None
        assert poor.score < rich.score

    def test_a_corpus_with_no_figures_reports_axis_coverage_n_a(self, part_dir):
        """A document that prints no figures has no axis coverage — not 0 %."""
        for plots in part_dir.glob("docs/*/plots.json"):
            plots.unlink()
        clear_index_cache()
        card = build_scorecard(part_dir)
        metric = next(m for m in card.metrics if m.key == "axis_coverage")
        assert metric.available is False and metric.grade is None
        assert "no figures" in metric.unavailable_reason
        assert card.grade is not None  # still grades: an absence is not an error


# --- the golden-set metrics --------------------------------------------------


class TestTheGoldenMetrics:
    def test_no_benchmark_is_n_a_on_both_golden_metrics(self, part_dir):
        card = build_scorecard(part_dir, golden=None)
        for key in ("golden_pass_rate", "alias_hit_rate"):
            metric = next(m for m in card.metrics if m.key == key)
            assert metric.available is False and metric.grade is None

    def test_a_benchmark_is_measured_and_names_what_it_did_not_run(
        self, part_dir, tmp_path
    ):
        golden = tmp_path / "golden_qa_TEST.yaml"
        golden.write_text(
            "questions:\n"
            "  - id: q1\n"
            "    question: What is the operating junction temperature range?\n"
            "    expected_substrings: [\"junction temperature\"]\n"
            "    pages: [6]\n"
            "  - id: q2\n"
            "    question: What is nowhere in this corpus?\n"
            "    expected_substrings: [\"a phrase no section prints\"]\n"
            "    pages: [6]\n",
            encoding="utf-8",
        )
        metric = next(
            m
            for m in build_scorecard(part_dir, golden=golden).metrics
            if m.key == "golden_pass_rate"
        )
        assert metric.available is True
        assert metric.denominator == 2 and metric.numerator == 1
        assert metric.value == pytest.approx(0.5)
        # the honesty clause: this is not the whole of `dsa verify`
        assert "page-truth" in metric.detail
        assert "q2" in metric.detail

    def test_a_missing_benchmark_file_says_which_file(self, part_dir, tmp_path):
        metric = next(
            m
            for m in build_scorecard(part_dir, golden=tmp_path / "golden_qa_TEST.yaml").metrics
            if m.key == "golden_pass_rate"
        )
        assert "golden_qa_TEST.yaml" in metric.unavailable_reason

    def test_alias_hit_rate_counts_only_lexicon_rungs(self, part_dir, tmp_path):
        """A designer-words lookup that lands on the alias rung is the hit."""
        golden = tmp_path / "golden_qa_TEST.yaml"
        golden.write_text(
            "questions:\n"
            "  - id: a1\n"
            "    question: What is the maximum junction temperature?\n"
            "    expected_substrings: [\"105\"]\n"
            "    pages: [6]\n"
            "    spec_query: {name: \"junction temperature\"}\n"
            "  - id: a2\n"
            "    question: What is the supply voltage?\n"
            "    expected_substrings: [\"1.15\"]\n"
            "    pages: [6]\n"
            "    spec_query: {name: \"Supply\"}\n",
            encoding="utf-8",
        )
        metric = next(
            m
            for m in build_scorecard(part_dir, golden=golden).metrics
            if m.key == "alias_hit_rate"
        )
        assert metric.available is True
        assert metric.denominator == 2
        assert metric.numerator == 1  # only "junction temperature" is an alias phrase
        assert "a2" in metric.detail


# --- the staleness surface ---------------------------------------------------


class TestTheScorecardCarriesTheStalenessBanner:
    """Ticket 02 requires the warning on four surfaces; this is the fourth."""

    def test_an_unchecked_corpus_says_so_on_the_scorecard(self, part_dir):
        card = build_scorecard(part_dir)
        assert card.staleness == "unknown"
        assert "not checked" in card.banner
        assert card.banner in render_scorecard(card)
        metric = next(m for m in card.metrics if m.key == "revision_freshness")
        assert metric.state == "unknown"
        assert metric.grade is not AuditGrade.A  # unknown is emphatically not current

    def test_the_banner_is_rendered_once_with_one_marker(self, part_dir):
        rendered = render_scorecard(build_scorecard(part_dir))
        assert rendered.count("Revision not checked") == 2  # banner + metric row
        assert "⚠ ⚠" not in rendered


# --- the CLI -----------------------------------------------------------------


class TestTheCommand:
    def test_one_part_prints_a_scorecard(self, settings, monkeypatch, capsys):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["audit", "--part", "TEST"]) == 0
        out = capsys.readouterr().out
        assert "# Corpus audit — TEST" in out
        assert "**Grade:" in out
        assert "n/a" in out

    def test_all_prints_the_fleet_table(self, settings, monkeypatch, capsys):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["audit", "--all"]) == 0
        out = capsys.readouterr().out
        assert "# Corpus audit — fleet" in out
        assert "| TEST |" in out and "| OTHER |" in out

    def test_json_feeds_tooling(self, settings, monkeypatch, capsys):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["audit", "TEST", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["part"] == "TEST"
        assert [m["key"] for m in payload["metrics"]] == list(METRIC_KEYS)
        assert payload["unavailable_policy"]
        # a metric that could not be computed serializes as null, not 0
        absent = [m for m in payload["metrics"] if not m["available"]]
        assert absent and all(m["value"] is None and m["grade"] is None for m in absent)

    def test_json_all_is_a_list(self, settings, monkeypatch, capsys):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["audit", "--all", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list) and len(payload) == 2

    def test_an_unknown_part_names_the_build_command(self, settings, monkeypatch, capsys):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["audit", "NOSUCHPART"]) == 2
        assert "dsa build" in capsys.readouterr().err

    def test_naming_nothing_is_refused(self, settings, monkeypatch, capsys):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["audit"]) == 2
        assert "--all" in capsys.readouterr().err

    def test_a_grade_floor_is_opt_in(self, settings, monkeypatch, capsys):
        """Without `--min-grade` an audit reports; it never fails a build."""
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["audit", "--all"]) == 0
        capsys.readouterr()
        card = build_scorecard(settings.parts_dir / "TEST")
        assert card.grade is not None
        assert cli.main(["audit", "TEST", "--min-grade", card.grade.value]) == 0

    def test_an_ungraded_part_is_always_below_the_floor(
        self, settings, monkeypatch, capsys
    ):
        """A corpus nobody could grade must never satisfy a quality gate."""
        (settings.parts_dir / "HALFBUILT").mkdir()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["audit", "--all", "--min-grade", "F"]) == 1
        err = capsys.readouterr().err
        assert "below the F floor" in err and "HALFBUILT" in err


# --- MCP ---------------------------------------------------------------------


class TestGetAuditOverMcp:
    """The tool an agent calls *before* it answers.

    The SDK is an optional extra, so the import is inside the fixture — the
    rest of this module must stay runnable on a core install.
    """

    @pytest.fixture
    def server(self, settings):
        pytest.importorskip("mcp", reason="get_audit over MCP needs the [mcp] extra")
        from datasheet_analyzer.mcp_server.server import build_server

        return build_server(settings)

    def test_it_returns_the_grade_and_the_headline(self, server):
        from mcp_session import call, payload_of

        from datasheet_analyzer.mcp_server import responses as R

        payload = payload_of(call(server, "get_audit", part="TEST"))
        assert R.validate_response(payload, "get_audit") == []
        assert payload["error"] == ""
        assert payload["grade"] in {"A", "B", "C", "D", "F"}
        assert payload["headline"].startswith("This corpus grades ")
        assert [m["key"] for m in payload["metrics"]] == list(METRIC_KEYS)
        assert payload["unavailable_policy"]
        assert payload["staleness"] == "unknown"

    def test_an_unavailable_metric_travels_as_null(self, server):
        from mcp_session import call, payload_of

        payload = payload_of(call(server, "get_audit", part="TEST"))
        absent = [m for m in payload["metrics"] if not m["available"]]
        assert absent
        for metric in absent:
            assert metric["value"] is None and metric["grade"] is None
            assert metric["unavailable_reason"]

    def test_an_unknown_part_is_a_refusal_in_the_declared_shape(self, server):
        from mcp_session import call, payload_of

        from datasheet_analyzer.mcp_server import responses as R

        payload = payload_of(call(server, "get_audit", part="NOSUCHPART"))
        assert R.validate_response(payload, "get_audit") == []
        assert "dsa build" in payload["error"]
        assert payload["grade"] is None and payload["metrics"] == []


# --- invariant 8 -------------------------------------------------------------


class TestNoModelCallInTheDerivationPath:
    def test_the_package_imports_nothing_that_could_call_a_model(self):
        """A source-level guard: the whole grading path is arithmetic."""
        for path in sorted((SRC / "audit").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for token in ("anthropic", "LLMClient", "enrich."):
                assert token not in source, f"{path.name} references {token}"

    def test_two_runs_of_the_same_corpus_grade_identically(self, part_dir):
        """Determinism: a scorecard is a pure function of what is on disk."""
        first = build_scorecard(part_dir)
        clear_index_cache()
        second = build_scorecard(part_dir)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")


# --- the fleet rendering -----------------------------------------------------


class TestTheFleetTable:
    def test_the_worst_corpus_sorts_first(self, settings):
        good = build_scorecard(settings.parts_dir / "TEST")
        bad = build_scorecard(settings.parts_dir / "TEST")
        bad.part = "BAD"
        bad.grade = AuditGrade.F
        rendered = render_fleet([good, bad])
        assert rendered.index("| BAD |") < rendered.index("| TEST |")

    def test_an_ungraded_corpus_sorts_above_every_graded_one(self, settings):
        graded = build_scorecard(settings.parts_dir / "TEST")
        ungraded = build_scorecard(settings.parts_dir / "TEST")
        ungraded.part = "UNKNOWN"
        ungraded.grade = None
        rendered = render_fleet([graded, ungraded])
        assert rendered.index("| UNKNOWN | ungraded") < rendered.index("| TEST |")

    def test_every_part_s_headline_is_printed(self, settings):
        cards = [
            build_scorecard(settings.parts_dir / name) for name in ("TEST", "OTHER")
        ]
        rendered = render_fleet(cards)
        for card in cards:
            assert card.headline in rendered
