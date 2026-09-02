"""`dsa audit` - the corpus scorecard and its rubric (phase 7, ticket 05).

What these prove, criterion by criterion:

- **every metric this branch's audit names is graded**, and the scorecard
  publishes all thirteen of them whether or not the corpus can answer each one;
- **the rubric is data-driven** - asserted three ways, because "the thresholds
  are not in Python" is the ticket's own acceptance criterion and one assertion
  can be satisfied by accident. Editing a threshold in the YAML moves a
  metric's grade; editing a weight moves the overall grade; **deleting** a
  metric from the YAML makes it `n/a`, which is what proves there is no hidden
  Python fallback behind the data;
- **an unavailable metric is neither zero nor full marks** - the sharpest test
  here. The same corpus is graded twice: once with no `errata_links.json` at
  all (the fact was never recorded) and once with an errata set holding three
  items none of which could be placed (it was recorded and it is zero). The
  first must be `n/a` and excluded; the second must be graded, and must score
  strictly *lower*. If `n/a` were being read as 0 the two would tie;
- **a measured zero is a reading, not an absence** - the reviewer note carried
  into this port. `mean_fidelity` decides availability from the recorded
  backend, so a `pdf_layout` document that really did score 0.0 grades `F`
  instead of reporting "no document records a fidelity score";
- **missing artifacts reduce the grade rather than erroring** - a corpus with
  no pins, no registers and no card rows still produces a scorecard, with those
  three graded down;
- **the staleness banner reaches this surface** - the `dsa audit` scorecard is
  one of the four places ticket 02 requires the warning, and until this ticket
  it was only reachable through `staleness.audit_metric`;
- **no model call anywhere in the derivation path** (invariant 8), asserted as
  a source-level guard over the package, and every metric carries `source` and
  `derivation`.

Hermetic by construction (invariant 4): the corpora are the synthetic ones
`mcp_corpus.py` already builds. Nothing here touches the network, an LLM, or a
real PDF.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from mcp_corpus import build_part, built_settings

from datasheet_analyzer import cli
from datasheet_analyzer.audit import (
    METRIC_KEYS,
    RUBRIC_PATH,
    AuditRubric,
    build_scorecard,
    clear_audit_rubric_cache,
    render_fleet,
    render_scorecard,
)
from datasheet_analyzer.config import AUDIT_SCHEMA_VERSION, Settings
from datasheet_analyzer.models import (
    AuditGrade,
    CorpusManifest,
    ErrataItem,
    ErrataLink,
    ErrataLinkSet,
    ErrataTarget,
    ExtractionStats,
    MetricKind,
)
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


def _rewrite_manifest(part_dir: Path, **fields) -> CorpusManifest:
    """Edit a built corpus's manifest in place, then drop the index cache."""
    path = part_dir / "manifest.json"
    manifest = CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))
    for key, value in fields.items():
        if key in CorpusManifest.model_fields:
            setattr(manifest, key, value)
        else:
            setattr(manifest.stats, key, value)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    clear_index_cache()
    return manifest


def _write_errata(part_dir: Path, *, linked: int, unlinked: int) -> None:
    """An `errata_links.json` with the given placed / unplaced populations."""
    from datasheet_analyzer.errata.render import ERRATA_LINKS_FILENAME

    def _item(i: int, targets: list[ErrataTarget]) -> ErrataLink:
        return ErrataLink(
            errata_item_id=f"err_{i}",
            item=ErrataItem(text=f"known issue {i}"),
            targets=targets,
        )

    link_set = ErrataLinkSet(
        schema_version="1",
        part_number=part_dir.name,
        errata_docs=["errata-deadbeef"],
        links=[
            _item(i, [ErrataTarget(reference="docs/x/specs.json#rec_1")]) for i in range(linked)
        ],
        unlinked=[_item(100 + i, []) for i in range(unlinked)],
    )
    (part_dir / ERRATA_LINKS_FILENAME).write_text(
        link_set.model_dump_json(indent=2), encoding="utf-8"
    )
    clear_index_cache()


def _edited_rubric(tmp_path: Path, edit) -> Path:
    """A copy of the shipped rubric with `edit(data)` applied, on disk."""
    data = yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))
    edit(data)
    dest = tmp_path / "audit_rubric.yaml"
    dest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return dest


def _metric(card, key: str):
    return next(m for m in card.metrics if m.key == key)


# --- the metric surface ------------------------------------------------------


class TestEveryMetricIsGraded:
    #: The metrics this branch's audit publishes, written out here rather than
    #: imported, so a metric silently disappearing from `METRIC_KEYS` fails.
    EXPECTED = (
        "section_page_coverage",
        "table_accept_rate",
        "mean_fidelity",
        "spec_page_rate",
        "record_confidence",
        "pins_present",
        "registers_present",
        "cards_present",
        "axis_coverage",
        "errata_link_rate",
        "alias_hit_rate",
        "revision_freshness",
        "golden_pass_rate",
    )

    def test_the_scorecard_publishes_every_metric_this_branch_names(self, part_dir):
        card = build_scorecard(part_dir)
        assert [m.key for m in card.metrics] == list(self.EXPECTED)
        assert METRIC_KEYS == self.EXPECTED

    def test_the_rubric_grades_exactly_those_metrics(self):
        data = yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))
        assert list(data["metrics"]) == list(self.EXPECTED)

    def test_table_pin_rate_is_absent_rather_than_permanently_n_a(self, part_dir):
        # This branch's manifest records no table pinning count, so the metric
        # could only ever say `n/a`. A row that can never say anything is not
        # honesty, it is noise - so it is not published at all.
        assert "table_pin_rate" not in METRIC_KEYS
        assert "tables_pinned" not in type(build_scorecard(part_dir)).model_fields
        assert (
            "tables_pinned"
            not in json.loads((part_dir / "manifest.json").read_text(encoding="utf-8"))["stats"]
        )

    def test_a_real_corpus_grades_and_carries_its_headline(self, part_dir):
        card = build_scorecard(part_dir)
        assert card.grade is not None
        assert card.score is not None
        assert card.part == "TEST"
        assert card.schema_version == AUDIT_SCHEMA_VERSION
        assert card.headline.startswith("This corpus grades ")
        assert card.n_graded + card.n_unavailable == len(card.metrics)

    def test_every_metric_carries_its_source_and_its_rule(self, part_dir):
        # Invariant 8 applies even though a scorecard is never written to disk.
        for metric in build_scorecard(part_dir).metrics:
            assert metric.source, metric.key
            assert metric.derivation, metric.key

    def test_the_readings_are_the_corpus_s_own_counts(self, part_dir):
        manifest = CorpusManifest.model_validate_json(
            (part_dir / "manifest.json").read_text(encoding="utf-8")
        )
        coverage = _metric(build_scorecard(part_dir), "section_page_coverage")
        assert coverage.numerator == manifest.stats.sections_with_pages
        assert coverage.denominator == (
            manifest.stats.sections_with_pages + manifest.stats.sections_without_pages
        )

    def test_an_unbuilt_part_grades_nothing_and_names_the_build_command(self, tmp_path):
        card = build_scorecard(tmp_path / "NOPE")
        assert card.grade is None
        assert card.metrics == []
        assert "dsa build" in card.notes[0]
        assert "is ungraded" in card.headline


class TestTheRubricIsData:
    """No threshold, weight or letter exists in Python - asserted three ways."""

    def test_raising_a_threshold_lowers_that_metric_s_grade(self, part_dir, tmp_path):
        before = _metric(build_scorecard(part_dir), "section_page_coverage")
        assert before.grade is AuditGrade.A

        def raise_it(data):
            data["metrics"]["section_page_coverage"]["thresholds"] = [
                {"grade": "A", "min": 1.01},
                {"grade": "D", "min": 0.0},
            ]

        rubric = AuditRubric.read(_edited_rubric(tmp_path, raise_it))
        card = build_scorecard(part_dir, rubric=rubric)
        assert _metric(card, "section_page_coverage").grade is AuditGrade.D
        # and nothing else moved
        assert _metric(card, "spec_page_rate").grade is AuditGrade.A

    def test_reweighting_moves_the_overall_grade(self, part_dir, tmp_path):
        shipped = build_scorecard(part_dir)

        def crush(data):
            for key, rule in data["metrics"].items():
                rule["weight"] = 40 if key == "revision_freshness" else 1

        rubric = AuditRubric.read(_edited_rubric(tmp_path, crush))
        reweighted = build_scorecard(part_dir, rubric=rubric)
        # `unknown` grades C, so pinning almost all the weight on it must drag
        # the overall score down toward C without any reading changing.
        assert reweighted.score < shipped.score
        assert reweighted.grade is AuditGrade.C

    def test_deleting_a_metric_makes_it_n_a_rather_than_falling_back(self, part_dir, tmp_path):
        """The proof there is no Python fallback behind the data."""
        rubric = AuditRubric.read(
            _edited_rubric(tmp_path, lambda d: d["metrics"].pop("section_page_coverage"))
        )
        card = build_scorecard(part_dir, rubric=rubric)
        metric = _metric(card, "section_page_coverage")
        assert metric.available is False
        assert metric.grade is None
        assert metric.value is None
        assert "grades no metric" in metric.unavailable_reason
        # The reading is preserved rather than discarded: it was measured.
        assert "read 100%" in metric.detail
        assert card.n_graded == build_scorecard(part_dir).n_graded - 1

    def test_the_packaged_rubric_is_what_the_default_reads(self):
        from datasheet_analyzer.audit import load_audit_rubric

        shipped = yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8"))
        loaded = load_audit_rubric()
        assert loaded.schema_version == shipped["schema_version"]
        assert list(loaded.keys) == list(shipped["metrics"])

    def test_an_unreadable_rubric_grades_nothing_and_says_so(self, part_dir, tmp_path):
        bad = tmp_path / "broken.yaml"
        bad.write_text("metrics: [this is not a mapping\n", encoding="utf-8")
        card = build_scorecard(part_dir, rubric=AuditRubric.read(bad))
        assert card.grade is None
        assert card.n_graded == 0
        assert all(not m.available for m in card.metrics)
        assert card.notes and "rubric" in card.notes[0]

    def test_a_missing_rubric_file_degrades_to_an_empty_one(self, tmp_path):
        rubric = AuditRubric.read(tmp_path / "absent.yaml")
        assert rubric.rules == ()
        assert rubric.overall([(AuditGrade.A, 1.0)])[0] is None


class TestUnavailableIsNeitherZeroNorFullMarks:
    """The ticket's sharpest rule, proved arithmetically."""

    def test_an_unrecorded_fact_is_n_a_and_a_recorded_zero_is_graded(self, part_dir):
        absent = build_scorecard(part_dir)
        assert _metric(absent, "errata_link_rate").available is False
        assert _metric(absent, "errata_link_rate").grade is None

        _write_errata(part_dir, linked=0, unlinked=3)
        recorded = build_scorecard(part_dir)
        measured = _metric(recorded, "errata_link_rate")
        assert measured.available is True
        assert measured.value == 0.0
        assert (measured.numerator, measured.denominator) == (0, 3)
        assert measured.grade is AuditGrade.F

    def test_the_recorded_zero_scores_strictly_lower_than_the_absence(self, part_dir):
        """If `n/a` were folded in as a zero the two would tie."""
        absent = build_scorecard(part_dir)
        _write_errata(part_dir, linked=0, unlinked=3)
        recorded = build_scorecard(part_dir)
        assert recorded.score < absent.score
        assert recorded.n_graded == absent.n_graded + 1

    def test_an_absence_is_not_full_marks_either(self, part_dir):
        """The other half: a perfect reading must beat the absence too."""
        absent = build_scorecard(part_dir)
        _write_errata(part_dir, linked=4, unlinked=0)
        perfect = build_scorecard(part_dir)
        assert _metric(perfect, "errata_link_rate").grade is AuditGrade.A
        assert perfect.score > absent.score

    def test_the_policy_travels_in_the_output(self, part_dir):
        card = build_scorecard(part_dir)
        assert "never scored 0" in card.unavailable_policy
        assert card.unavailable_policy in render_scorecard(card)

    def test_an_n_a_metric_keeps_its_row_and_its_reason(self, part_dir):
        card = build_scorecard(part_dir)
        rendered = render_scorecard(card)
        golden = _metric(card, "golden_pass_rate")
        assert golden.available is False
        assert golden.unavailable_reason
        assert "golden pass rate" in rendered
        assert golden.unavailable_reason in rendered

    def test_too_few_metrics_means_no_overall_grade(self, part_dir, tmp_path):
        def demand_everything(data):
            data["min_graded_metrics"] = 13

        rubric = AuditRubric.read(_edited_rubric(tmp_path, demand_everything))
        card = build_scorecard(part_dir, rubric=rubric)
        assert card.grade is None
        assert card.score is None
        assert "metrics could be computed" in card.notes[0]
        assert "is ungraded" in card.headline


class TestAMeasuredZeroIsAReading:
    """The reviewer note this port fixes: 0.0 is a finding, not an absence."""

    def test_a_layout_document_scoring_zero_fidelity_grades_f(self, part_dir):
        _rewrite_manifest(
            part_dir,
            extraction_stats={
                "deadbeef": ExtractionStats(
                    backend="pdf_layout",
                    tables_detected=4,
                    tables_accepted=4,
                    mean_fidelity=0.0,
                )
            },
        )
        metric = _metric(build_scorecard(part_dir), "mean_fidelity")
        assert metric.available is True
        assert metric.value == 0.0
        assert metric.grade is AuditGrade.F

    def test_a_backend_that_computes_no_fidelity_is_still_n_a(self, part_dir):
        _rewrite_manifest(
            part_dir,
            extraction_stats={"deadbeef": ExtractionStats(backend="ti_html", tables_detected=4)},
        )
        metric = _metric(build_scorecard(part_dir), "mean_fidelity")
        assert metric.available is False
        assert "pdf_layout" in metric.unavailable_reason

    def test_a_layout_document_that_accepted_no_table_is_n_a(self, part_dir):
        _rewrite_manifest(
            part_dir,
            extraction_stats={
                "deadbeef": ExtractionStats(
                    backend="pdf_layout", tables_detected=4, tables_accepted=0
                )
            },
        )
        metric = _metric(build_scorecard(part_dir), "mean_fidelity")
        assert metric.available is False
        assert "accepted no table" in metric.unavailable_reason
        # ...but the accept rate it *did* record is graded, and graded badly.
        accept = _metric(build_scorecard(part_dir), "table_accept_rate")
        assert accept.value == 0.0
        assert accept.grade is AuditGrade.F


class TestMissingArtifactsReduceTheGradeRatherThanErroring:
    def test_a_modern_corpus_with_no_pins_registers_or_cards_still_grades(self, tmp_path):
        part_dir = build_part(tmp_path / "parts" / "BARE")
        for name in ("pins.json", "registers.json"):
            for path in part_dir.rglob(name):
                path.unlink()
        clear_index_cache()
        card = build_scorecard(part_dir)
        assert card.grade is not None
        assert _metric(card, "pins_present").grade is AuditGrade.D
        assert _metric(card, "registers_present").grade is AuditGrade.C
        assert _metric(card, "cards_present").grade is AuditGrade.D
        assert all(m.available for m in card.metrics if m.key.endswith("_present"))

    def test_a_corpus_published_at_an_older_pipeline_reports_n_a_not_absence(self, tmp_path):
        part_dir = build_part(tmp_path / "parts" / "OLD")
        for name in ("pins.json", "registers.json"):
            for path in part_dir.rglob(name):
                path.unlink()
        _rewrite_manifest(part_dir, pipeline_version="0.0.1-ancient")
        card = build_scorecard(part_dir)
        for key in ("pins_present", "registers_present", "cards_present"):
            metric = _metric(card, key)
            assert metric.available is False, key
            assert "predate the derived artifacts" in metric.unavailable_reason
        assert any("needs a rebuild" in note for note in card.notes)

    def test_a_corpus_with_no_figures_reports_axis_coverage_n_a(self, tmp_path):
        part_dir = build_part(tmp_path / "parts" / "NOFIG")
        for path in part_dir.rglob("plots.json"):
            path.unlink()
        clear_index_cache()
        metric = _metric(build_scorecard(part_dir), "axis_coverage")
        assert metric.available is False
        assert "no figures" in metric.unavailable_reason


class TestTheGoldenMetrics:
    def test_no_benchmark_is_n_a_on_both_golden_metrics(self, part_dir):
        card = build_scorecard(part_dir, golden=None)
        for key in ("golden_pass_rate", "alias_hit_rate"):
            assert _metric(card, key).available is False
            assert "no golden benchmark" in _metric(card, key).unavailable_reason

    def test_a_missing_benchmark_file_says_which_file(self, part_dir, tmp_path):
        metric = _metric(
            build_scorecard(part_dir, golden=tmp_path / "golden_qa_TEST.yaml"),
            "golden_pass_rate",
        )
        assert metric.available is False
        assert "golden_qa_TEST.yaml" in metric.unavailable_reason

    def test_a_benchmark_is_measured_and_names_what_it_did_not_run(self, part_dir, tmp_path):
        golden = tmp_path / "golden_qa_TEST.yaml"
        golden.write_text(
            yaml.safe_dump(
                {
                    "questions": [
                        {
                            "id": "q1",
                            "question": "What is the maximum supply voltage?",
                            "expected_substrings": ["1.4"],
                            "pages": [6],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        metric = _metric(build_scorecard(part_dir, golden=golden), "golden_pass_rate")
        assert metric.available is True
        assert metric.denominator == 1
        # The narrowing is stated on the metric rather than left to be inferred.
        assert "page-truth" in metric.detail
        assert metric.derivation == "golden_corpus_checks"

    def test_an_empty_benchmark_is_n_a_rather_than_a_perfect_score(self, part_dir, tmp_path):
        golden = tmp_path / "golden_qa_TEST.yaml"
        golden.write_text(yaml.safe_dump({"questions": []}), encoding="utf-8")
        metric = _metric(build_scorecard(part_dir, golden=golden), "golden_pass_rate")
        assert metric.available is False
        assert "holds no questions" in metric.unavailable_reason


class TestTheScorecardCarriesTheStalenessBanner:
    """Ticket 02's fourth surface, which until this ticket did not exist."""

    def test_an_unchecked_corpus_says_so_on_the_scorecard(self, part_dir):
        card = build_scorecard(part_dir)
        assert card.staleness == "unknown"
        assert "not checked" in card.banner.lower()
        assert card.banner in render_scorecard(card)
        assert _metric(card, "revision_freshness").state == "unknown"
        assert _metric(card, "revision_freshness").grade is AuditGrade.C

    def test_the_banner_is_rendered_once_with_one_marker(self, part_dir):
        rendered = render_scorecard(build_scorecard(part_dir))
        # The scorecard renders the shared sentence; it does not compose a
        # second one and it does not add a second marker to the banner line.
        assert rendered.count("Run `dsa check-revisions --part TEST`") == 2
        banner_lines = [ln for ln in rendered.splitlines() if ln.startswith("⚠")]
        assert len(banner_lines) == 1


class TestTheCommand:
    @pytest.fixture(autouse=True)
    def _point_at(self, settings, monkeypatch):
        monkeypatch.setattr(cli, "get_settings", lambda: settings)

    def test_one_part_prints_a_scorecard(self, capsys):
        assert cli.main(["audit", "TEST"]) == 0
        out = capsys.readouterr().out
        assert "# Corpus audit — TEST" in out
        assert "| Metric | Reading |" in out

    def test_all_prints_the_fleet_table(self, capsys):
        assert cli.main(["audit", "--all"]) == 0
        out = capsys.readouterr().out
        assert "# Corpus audit — fleet" in out
        assert "TEST" in out and "OTHER" in out

    def test_json_feeds_tooling(self, capsys):
        assert cli.main(["audit", "--part", "TEST", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["part"] == "TEST"
        assert len(payload["metrics"]) == len(METRIC_KEYS)
        assert payload["schema_version"] == AUDIT_SCHEMA_VERSION

    def test_json_all_is_a_list(self, capsys):
        assert cli.main(["audit", "--all", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list) and len(payload) == 2

    def test_an_unavailable_metric_travels_as_null(self, capsys):
        assert cli.main(["audit", "TEST", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        na = [m for m in payload["metrics"] if not m["available"]]
        assert na, "this corpus should carry at least one n/a metric"
        for metric in na:
            assert metric["value"] is None
            assert metric["grade"] is None
            assert metric["unavailable_reason"]

    def test_an_unknown_part_names_the_build_command(self, capsys):
        assert cli.main(["audit", "NOSUCH"]) == 2
        assert "dsa build" in capsys.readouterr().err

    def test_naming_nothing_is_refused(self, capsys):
        assert cli.main(["audit"]) == 2
        assert "name a part" in capsys.readouterr().err

    def test_a_grade_floor_is_opt_in(self, capsys):
        assert cli.main(["audit", "TEST"]) == 0
        assert cli.main(["audit", "TEST", "--min-grade", "F"]) == 0

    def test_a_graded_part_below_the_floor_exits_one(self, capsys):
        # The half of `--min-grade` the source lineage never exercised: a part
        # that really is graded, and really is below the floor.
        graded = build_scorecard(cli.get_settings().parts_dir / "TEST")
        assert graded.grade is not None and graded.grade is not AuditGrade.A
        assert cli.main(["audit", "TEST", "--min-grade", "A"]) == 1
        assert "below the A floor: TEST" in capsys.readouterr().err

    def test_an_ungraded_part_is_always_below_the_floor(self, capsys, tmp_path):
        settings = cli.get_settings()
        (settings.parts_dir / "EMPTY").mkdir(parents=True)
        clear_index_cache()
        assert cli.main(["audit", "--all", "--min-grade", "F"]) == 1
        assert "EMPTY" in capsys.readouterr().err


class TestTheFleetTable:
    def test_the_worst_corpus_sorts_first(self, settings, tmp_path):
        good = build_scorecard(settings.parts_dir / "TEST")
        bad = build_scorecard(settings.parts_dir / "OTHER")
        bad.grade = AuditGrade.F
        rendered = render_fleet([good, bad])
        rows = [ln for ln in rendered.splitlines() if ln.startswith(("| OTHER", "| TEST"))]
        assert rows[0].startswith("| OTHER")

    def test_an_ungraded_corpus_sorts_above_every_graded_one(self, settings, tmp_path):
        graded = build_scorecard(settings.parts_dir / "TEST")
        ungraded = build_scorecard(tmp_path / "GHOST")
        rendered = render_fleet([graded, ungraded])
        rows = [ln for ln in rendered.splitlines() if ln.startswith(("| GHOST", "| TEST"))]
        assert rows[0].startswith("| GHOST")
        assert "ungraded" in rows[0]

    def test_every_part_s_headline_is_printed(self, settings):
        cards = [build_scorecard(settings.parts_dir / p) for p in ("TEST", "OTHER")]
        rendered = render_fleet(cards)
        for card in cards:
            assert card.headline in rendered


class TestNoModelCallInTheDerivationPath:
    def test_the_package_imports_nothing_that_could_call_a_model(self):
        for path in sorted((SRC / "audit").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for forbidden in ("anthropic", "enrich", "llm", "Anthropic"):
                assert forbidden not in text, f"{path.name} mentions {forbidden}"

    def test_two_runs_of_the_same_corpus_grade_identically(self, part_dir):
        first = build_scorecard(part_dir)
        clear_index_cache()
        second = build_scorecard(part_dir)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")


class TestTheReadingsRender:
    def test_a_ratio_prints_its_counts_beside_its_percentage(self, part_dir):
        rendered = render_scorecard(build_scorecard(part_dir))
        coverage = _metric(build_scorecard(part_dir), "section_page_coverage")
        assert f"| {coverage.numerator}/{coverage.denominator} |" in rendered

    def test_a_boolean_reads_yes_or_no_and_a_state_reads_its_word(self, part_dir):
        card = build_scorecard(part_dir)
        assert _metric(card, "pins_present").kind is MetricKind.BOOLEAN
        assert _metric(card, "revision_freshness").kind is MetricKind.STATE
        rendered = render_scorecard(card)
        assert "| pin records published | yes |" in rendered
        assert "| revision freshness | unknown |" in rendered
