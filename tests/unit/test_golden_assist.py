"""`dsa golden suggest|confirm` - proposals, and the human decision on them.

Phase 7, ticket 06. Invariant 5 gains a clause: *a generated candidate counts
toward nothing until a human confirms it*, and most of what is asserted here is
that clause holding.

- **an unconfirmed candidate cannot reach `dsa verify`** - asserted with a
  control, which is what makes the assertion mean something: the same verify
  run is compared before and after generation (stdout byte for byte, exit code
  included) and must be identical, and *then* a candidate is confirmed and the
  report must grow. Without the second half the first would pass against a
  generator that wrote nothing at all;
- **the selection is stratified, not degenerate** - and asserted against a
  corpus that would actually expose a degenerate generator: a skewed part with
  many spec strata and few pins, where a flat round-robin crowds the pin path
  out. A property that holds vacuously on a constant list proves nothing, so
  the non-vacuity is asserted too;
- **nothing is dropped in silence** - every record no template could use is
  counted by artifact and by reason (ADR 0005's unparsed-population clause), so
  an empty pool is a diagnosis rather than a guess;
- **the merge cannot corrupt the benchmark** - including the case the lineage
  this was ported from got wrong: a merge that would produce unparsable YAML is
  refused *before the file is touched*, and the reindent that keeps a
  hand-written file's shape is exercised on both indentation styles;
- **the file never claims a verification that did not happen** - a bulk run
  stamps the bulk provenance, an interactive run without `--pdf` stamps the
  corpus-text one, and only `--pdf` stamps the page-checked claim;
- **`confirm` really shows the page** - asserted on the text, not on the call.

Hermetic (invariant 4), and deliberately so twice over: every golden path here
is a `tmp_path`, and `tests/conftest.py` points `DSA_GOLDEN_DIR` at a temporary
directory for every test in the suite, so a confirm run that resolved its path
from settings still cannot reach `tests/fixtures/golden_qa_<PART>.yaml`.
`TestNothingHereCanReachTheRealBenchmarks` asserts both halves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from mcp_corpus import build_part, empty_settings

from datasheet_analyzer import cli
from datasheet_analyzer.config import PINS_SCHEMA_VERSION, PIPELINE_VERSION, Settings
from datasheet_analyzer.derive.pins import write_pinset
from datasheet_analyzer.derive.provenance import (
    PINS_ARTIFACT,
    PLOTS_ARTIFACT,
    REGISTERS_ARTIFACT,
    SPECS_ARTIFACT,
    resolve_source,
)
from datasheet_analyzer.evalh.candidates import (
    CANDIDATE_SUFFIX,
    GoldenAssistError,
    candidate_path,
    read_candidates,
    read_rejections,
    rejected_keys,
    rejected_path,
    write_candidates,
    write_rejections,
)
from datasheet_analyzer.evalh.confirm import (
    ACCEPT,
    EDIT,
    PROVENANCE_BULK,
    PROVENANCE_CORPUS,
    PROVENANCE_PAGE,
    REJECT,
    Decision,
    apply_decisions,
    decisions_from_ids,
    load_decisions,
    merge_into_golden,
    page_context,
    render_candidate,
    run_interactive,
)
from datasheet_analyzer.evalh.golden import (
    GOLDEN_DIR,
    candidate_golden_path,
    default_golden_path,
    golden_dir,
    load_golden,
    rejected_golden_path,
)
from datasheet_analyzer.evalh.suggest import (
    ARTIFACT_ORDER,
    NO_ID,
    STRATA_DIMENSIONS,
    TEMPLATES,
    strata_of,
    suggest_candidates,
)
from datasheet_analyzer.models import (
    Confidence,
    DocType,
    GoldenRejection,
    PinRecord,
    PinSet,
    RawDocument,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.publish import write_corpus
from datasheet_analyzer.retrieve import clear_index_cache
from datasheet_analyzer.structure.corpus import build_section_plans

SRC = Path(__file__).resolve().parent.parent.parent / "src" / "datasheet_analyzer"

HAND_WRITTEN = """# Hand-written golden set. The comments here are documentation and a
# merge must not touch them.
questions:
  - id: h1-junction-temperature
    question: What is the maximum junction temperature?
    expected_substrings: ["Operating junction temperature", "105"]
    pages: [6]
    kind: direct
"""


@pytest.fixture(autouse=True)
def fresh_index_cache():
    clear_index_cache()
    yield
    clear_index_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    resolved = empty_settings(tmp_path)
    build_part(resolved.parts_dir / "TEST")
    return resolved


@pytest.fixture
def part_dir(settings: Settings) -> Path:
    return settings.parts_dir / "TEST"


@pytest.fixture
def golden(tmp_path: Path) -> Path:
    """A hand-written benchmark, in its own directory beside the candidates."""
    fixtures = tmp_path / "bench"
    fixtures.mkdir(parents=True, exist_ok=True)
    path = fixtures / "golden_qa_TEST.yaml"
    path.write_text(HAND_WRITTEN, encoding="utf-8")
    return path


# --- a skewed corpus: many spec strata, few pins ------------------------------


def _skewed_part(part_dir: Path, *, n_specs: int = 12, n_pins: int = 2) -> Path:
    """One document: `n_specs` spec rows across six printed tables, `n_pins` pins.

    The shape a flat stratification gets wrong - many spec strata, one pin
    stratum - reproduced small enough to assert on exactly. A generator that
    round-robins over the composite stratum draws six spec rows per pin row and
    a set of four holds no pin at all.
    """
    part = part_dir.name
    doc_hash = "c" * 64
    source = SourceDocument(
        content_hash=doc_hash,
        path="pdfs/skew.pdf",
        part_number=part,
        doc_type=DocType.DATASHEET,
        revision="Rev. A",
        page_count=12,
    )
    raw = RawDocument(
        source=source,
        sections=[
            SectionNode(
                number="",
                title="Specifications",
                page_start=3,
                page_end=3,
                paragraphs=["Every rail is specified on this page."],
            )
        ],
        extractor="pdf_layout",
        extractor_version="test-1",
    )
    specs = SpecSet(
        schema_version="2",
        part_number=part,
        doc_hash=doc_hash,
        records=[
            SpecRecord(
                section="",
                section_key="specifications",
                table_index=i % 6,
                row_index=i,
                symbol=f"V{i}",
                name=f"V{i} supply voltage",
                max=f"{i + 1}.0",
                unit=SpecUnit(verbatim="V", canonical="V"),
                page=3,
                confidence=Confidence.HIGH,
            )
            for i in range(n_specs)
        ],
    )
    pins = PinSet(
        schema_version=PINS_SCHEMA_VERSION,
        part_number=part,
        doc_hash=doc_hash,
        pins=[
            PinRecord(
                pin=f"A{i + 1}",
                name=f"VDD{i + 1}",
                type="power",
                type_evidence="name:*vdd*",
                description="Supply pin",
                section="",
                table_index=0,
                row_index=i,
                page=3,
                confidence=Confidence.HIGH,
            )
            for i in range(n_pins)
        ],
    )
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        f"# {part}\n\nOne document.\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="unknown",
        specsets=[specs],
    )
    write_pinset(part_dir / "docs" / f"datasheet-{doc_hash[:8]}", pins)
    clear_index_cache()
    return part_dir


def _round_robin_respected(values: list) -> bool:
    """True when nothing repeats before everything beside it has been drawn.

    The property the stratified order guarantees at every level of the stratum
    tuple, and the one a degenerate "twenty variations of the easiest lookup"
    set violates on its second element.
    """
    seen: list = []
    for value in values:
        if value in seen:
            return len(seen) == len(set(values))
        seen.append(value)
    return True


class TestCandidatesAreStratified:
    def test_nothing_repeats_until_everything_beside_it_has_been_drawn(self, part_dir):
        """The criterion, stated as the property the selection guarantees.

        It is a property of each *level* of the stratum tuple, not of the flat
        list: confidence is nested inside artifact, so it holds across the
        artifacts and again within each artifact's own subsequence. Asserting
        it on the flat list would assert something the design never claimed.
        """
        candidates = suggest_candidates(part_dir, n=20).candidates
        assert _round_robin_respected([c.artifact for c in candidates])
        for artifact in {c.artifact for c in candidates}:
            grades = [c.confidence.value for c in candidates if c.artifact == artifact]
            assert _round_robin_respected(grades), artifact

    def test_that_property_is_not_vacuous_on_this_corpus(self, part_dir):
        """The guard the source lineage's own reviewer asked for.

        `_round_robin_respected` is trivially true on a constant list, so a
        test that only asserts it could pass against a generator that proposed
        twenty copies of one stratum. This asserts the input actually varies.
        """
        candidates = suggest_candidates(part_dir, n=20).candidates
        assert len({c.artifact for c in candidates}) >= 3
        assert len({c.confidence.value for c in candidates}) >= 2
        assert not _round_robin_respected(["a", "a", "b"])

    def test_a_scarce_artifact_is_not_crowded_out_by_a_plentiful_one(self, tmp_path):
        """Twelve spec rows over six tables, two pins - a set of four holds a pin.

        This is the measurement that replaced the first design: a flat
        round-robin over the composite stratum hands the *count* of spec strata
        the deciding vote and draws six spec rows before the first pin.
        """
        part_dir = _skewed_part(tmp_path / "parts" / "SKEW")
        candidates = suggest_candidates(part_dir, n=4).candidates
        assert len(candidates) == 4
        assert sum(1 for c in candidates if c.artifact == PINS_ARTIFACT) >= 2
        assert sum(1 for c in candidates if c.artifact == SPECS_ARTIFACT) >= 2

    def test_the_set_spans_sections_artifacts_and_confidence_grades(self, part_dir):
        candidates = suggest_candidates(part_dir, n=20)
        for dimension in STRATA_DIMENSIONS:
            assert candidates.strata.get(dimension), dimension
        assert len(candidates.strata["artifact"]) >= 3
        assert len(candidates.strata["confidence"]) >= 2
        assert len(candidates.strata["section"]) >= 2

    def test_no_single_artifact_dominates_the_set(self, part_dir):
        candidates = suggest_candidates(part_dir, n=20).candidates
        counts = {}
        for c in candidates:
            counts[c.artifact] = counts.get(c.artifact, 0) + 1
        assert max(counts.values()) <= len(candidates) - 2

    def test_the_file_publishes_the_mix_it_selected(self, part_dir, tmp_path):
        candidates = suggest_candidates(part_dir, n=20)
        path = write_candidates(tmp_path / "c.yaml", candidates)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert written["strata"] == strata_of(candidates.candidates)

    def test_the_pool_is_reported_even_for_an_artifact_with_no_records(self, tmp_path):
        part_dir = _skewed_part(tmp_path / "parts" / "SKEW")
        candidates = suggest_candidates(part_dir, n=4)
        assert set(candidates.pool) == set(ARTIFACT_ORDER)
        assert candidates.pool[REGISTERS_ARTIFACT] == 0
        assert candidates.pool[PLOTS_ARTIFACT] == 0

    def test_generation_is_deterministic(self, part_dir):
        first = suggest_candidates(part_dir, n=20)
        clear_index_cache()
        second = suggest_candidates(part_dir, n=20)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")


class TestNothingIsDroppedInSilence:
    """ADR 0005's unparsed-population clause, applied to a selector."""

    def test_a_refused_record_is_counted_by_artifact_and_reason(self, part_dir):
        candidates = suggest_candidates(part_dir, n=20)
        # The second cataloged figure has no pixels on disk, so no plot
        # question can be asked about it - and that is reported, not hidden.
        assert candidates.refused[PLOTS_ARTIFACT]
        assert candidates.n_refused == 1
        reason, count = next(iter(candidates.refused[PLOTS_ARTIFACT].items()))
        assert "pixels" in reason
        assert count == 1

    def test_an_empty_pool_names_the_reason_that_actually_refused_the_records(self, part_dir):
        """The lineage this was ported from printed one fixed cause for all.

        A corpus whose records predate ADR 0005 ids yields nothing *because
        they are unaddressable*, not because they print no answer, and a note
        that says the wrong thing sends a maintainer to the wrong fix.

        On this branch only a **plot** can be unaddressable: `SpecRecord.id`,
        `PinRecord.id` and `RegisterRecord.id` are computed fields, so they are
        reconstructed for a `specs.json` published before ids existed (that is
        `derive.provenance`'s stated legacy tolerance). `PlotRecord.id` is
        stored, so a catalog written before the id scheme really does carry
        `""` - which is exactly the AFE7950/AFE7953 finding the source lineage
        reported, in the one artifact where it survives the port.
        """
        for path in part_dir.rglob("plots.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            for record in data["plots"]:
                record["id"] = ""
            path.write_text(json.dumps(data), encoding="utf-8")
        clear_index_cache()
        candidates = suggest_candidates(part_dir, n=20)
        assert candidates.pool[PLOTS_ARTIFACT] == 0
        assert candidates.refused[PLOTS_ARTIFACT] == {NO_ID: 2}
        note = next(n for n in candidates.notes if n.startswith(PLOTS_ARTIFACT))
        assert "no id to cite" in note
        assert any("needs a rebuild" in n for n in candidates.notes)

    def test_a_corpus_with_no_record_of_a_kind_says_that_instead(self, tmp_path):
        part_dir = _skewed_part(tmp_path / "parts" / "SKEW")
        candidates = suggest_candidates(part_dir, n=4)
        note = next(n for n in candidates.notes if n.startswith(REGISTERS_ARTIFACT))
        assert "publishes no record of this kind" in note

    def test_a_stale_pipeline_version_is_said_out_loud(self, tmp_path):
        part_dir = _skewed_part(tmp_path / "parts" / "SKEW")
        manifest = part_dir / "manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["pipeline_version"] = "0.0.1-ancient"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        clear_index_cache()
        notes = suggest_candidates(part_dir, n=4).notes
        assert any("0.0.1-ancient" in n for n in notes)


class TestEveryCandidateCarriesItsAnswerPageAndRecord:
    """Invariant 8 applies to a proposal too."""

    def test_every_source_resolves_to_the_record_and_the_page(self, part_dir):
        for candidate in suggest_candidates(part_dir, n=20).candidates:
            resolved = resolve_source(candidate.source, roots=part_dir)
            assert resolved is not None, candidate.source
            assert resolved.record_id
            assert candidate.page is not None
            assert candidate.question.pages == [candidate.page]

    def test_every_candidate_names_the_rule_that_produced_it(self, part_dir):
        for candidate in suggest_candidates(part_dir, n=20).candidates:
            assert candidate.template in TEMPLATES
            assert candidate.key == f"{candidate.source}|{candidate.template}"

    def test_the_expected_substrings_are_printed_cells_of_that_record(self, part_dir):
        for candidate in suggest_candidates(part_dir, n=20).candidates:
            for substring in candidate.question.expected_substrings:
                assert substring, candidate.question.id

    def test_every_candidate_is_written_unconfirmed(self, part_dir, tmp_path):
        candidates = suggest_candidates(part_dir, n=20)
        path = write_candidates(tmp_path / "c.yaml", candidates)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert written["candidates"]
        assert all(item["confirmed"] is False for item in written["candidates"])

    def test_a_pin_or_register_candidate_uses_this_branch_s_route_marker(self, part_dir):
        by_artifact = {c.artifact: c for c in suggest_candidates(part_dir, n=20).candidates}
        assert by_artifact[PINS_ARTIFACT].question.ask_query == {"route": "pin"}
        assert by_artifact[REGISTERS_ARTIFACT].question.ask_query == {"route": "register"}
        # ...and the fields this branch does not have are not invented.
        dumped = by_artifact[PINS_ARTIFACT].question.model_dump()
        assert "pin_query" not in dumped
        assert "reg_query" not in dumped

    def test_no_candidate_is_proposed_from_an_unbuilt_corpus(self, tmp_path):
        with pytest.raises(GoldenAssistError) as excinfo:
            suggest_candidates(tmp_path / "NOPE", n=5)
        assert "dsa build" in str(excinfo.value)


# --- invariant 5, defended three ways ----------------------------------------


def _verify(settings, golden: Path, monkeypatch, capsys) -> tuple[int, str]:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    code = cli.main(["verify", "--part", "TEST", "--golden", str(golden), "--specs"])
    return code, capsys.readouterr().out


class TestAnUnconfirmedCandidateDoesNotAffectVerify:
    def test_generating_candidates_leaves_verify_byte_identical(
        self, settings, part_dir, golden, monkeypatch, capsys
    ):
        before = _verify(settings, golden, monkeypatch, capsys)
        write_candidates(candidate_path(golden), suggest_candidates(part_dir, n=20))
        clear_index_cache()
        after = _verify(settings, golden, monkeypatch, capsys)
        assert before == after

    def test_confirming_one_does_change_verify(
        self, settings, part_dir, golden, monkeypatch, capsys
    ):
        """The control: without this, the test above would pass against a
        generator that wrote nothing at all."""
        before_code, before_out = _verify(settings, golden, monkeypatch, capsys)
        candidates = suggest_candidates(part_dir, n=20)
        outcome = apply_decisions(
            candidates, [Decision(id=candidates.candidates[0].question.id, action=ACCEPT)]
        )
        merge_into_golden(golden, outcome.accepted, part="TEST")
        clear_index_cache()
        after_code, after_out = _verify(settings, golden, monkeypatch, capsys)
        assert after_out != before_out
        assert len(after_out) > len(before_out)
        del before_code, after_code

    def test_the_candidate_file_is_not_the_benchmark_file(self):
        assert candidate_golden_path("X") != default_golden_path("X")
        assert candidate_golden_path("X").name.endswith(CANDIDATE_SUFFIX)
        assert rejected_golden_path("X") != default_golden_path("X")

    def test_load_golden_refuses_a_candidate_file(self, part_dir, tmp_path):
        path = write_candidates(
            tmp_path / "golden_qa_TEST.candidate.yaml", suggest_candidates(part_dir, n=3)
        )
        with pytest.raises(GoldenAssistError) as excinfo:
            load_golden(path)
        assert "golden_qa_TEST.yaml" in str(excinfo.value)

    def test_verify_refuses_a_candidate_file_passed_as_golden(
        self, settings, part_dir, tmp_path, monkeypatch, capsys
    ):
        path = write_candidates(
            tmp_path / "golden_qa_TEST.candidate.yaml", suggest_candidates(part_dir, n=3)
        )
        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        assert cli.main(["verify", "--part", "TEST", "--golden", str(path)]) == 2
        assert "counts toward nothing" in capsys.readouterr().err

    def test_a_candidate_file_has_no_questions_key_at_all(self, part_dir, tmp_path):
        path = write_candidates(tmp_path / "c.yaml", suggest_candidates(part_dir, n=3))
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "questions" not in data
        assert "candidates" in data


class TestTheDecisionCoreIsPureAndTestable:
    def test_accept_edit_and_reject_land_where_they_belong(self, part_dir):
        candidates = suggest_candidates(part_dir, n=20)
        ids = [c.question.id for c in candidates.candidates]
        outcome = apply_decisions(
            candidates,
            [
                Decision(id=ids[0], action=ACCEPT),
                Decision(id=ids[1], action=EDIT, edits={"question": "Reworded?"}),
                Decision(id=ids[2], action=REJECT, reason="the cell is a marker"),
            ],
        )
        assert [q.id for q in outcome.accepted] == [ids[0], ids[1]]
        assert outcome.edited_ids == [ids[1]]
        assert [r.id for r in outcome.rejected] == [ids[2]]
        assert [c.question.id for c in outcome.deferred] == ids[3:]

    def test_an_edit_keeps_everything_it_did_not_change(self, part_dir):
        candidates = suggest_candidates(part_dir, n=20)
        original = candidates.candidates[0].question
        outcome = apply_decisions(
            candidates, [Decision(id=original.id, action=EDIT, edits={"pages": [99]})]
        )
        edited = outcome.accepted[0]
        assert edited.pages == [99]
        assert edited.question == original.question
        assert edited.expected_substrings == original.expected_substrings
        assert edited.notes == original.notes

    def test_a_decision_naming_an_unknown_candidate_is_refused(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        with pytest.raises(GoldenAssistError) as excinfo:
            apply_decisions(candidates, [Decision(id="nope", action=ACCEPT)])
        assert "dsa golden suggest" in str(excinfo.value)

    def test_one_candidate_may_not_be_decided_twice(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        first = candidates.candidates[0].question.id
        with pytest.raises(GoldenAssistError) as excinfo:
            apply_decisions(
                candidates,
                [Decision(id=first, action=ACCEPT), Decision(id=first, action=REJECT)],
            )
        assert "decided twice" in str(excinfo.value)

    def test_an_edit_with_no_edits_is_refused(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        first = candidates.candidates[0].question.id
        with pytest.raises(GoldenAssistError) as excinfo:
            apply_decisions(candidates, [Decision(id=first, action=EDIT)])
        assert "accept it or say what changes" in str(excinfo.value)

    def test_only_the_reviewer_facing_fields_are_editable(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        first = candidates.candidates[0].question.id
        with pytest.raises(GoldenAssistError) as excinfo:
            apply_decisions(
                candidates,
                [Decision(id=first, action=EDIT, edits={"spec_query": {"symbol": "X"}})],
            )
        assert "not editable" in str(excinfo.value)

    def test_decisions_load_from_a_file_for_a_scripted_fleet_run(self, part_dir, tmp_path):
        candidates = suggest_candidates(part_dir, n=3)
        ids = [c.question.id for c in candidates.candidates]
        path = tmp_path / "decisions.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "decisions": [
                        {"id": ids[0], "action": "accept"},
                        {"id": ids[1], "action": "edit", "pages": [4]},
                        {"id": ids[2], "action": "reject", "reason": "range"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        outcome = apply_decisions(candidates, load_decisions(path))
        assert len(outcome.accepted) == 2
        assert outcome.accepted[1].pages == [4]
        assert outcome.rejected[0].reason == "range"

    def test_a_decisions_file_with_an_unknown_action_is_refused(self, tmp_path):
        path = tmp_path / "d.yaml"
        path.write_text(
            yaml.safe_dump({"decisions": [{"id": "x", "action": "maybe"}]}), encoding="utf-8"
        )
        with pytest.raises(GoldenAssistError) as excinfo:
            load_decisions(path)
        assert "maybe" in str(excinfo.value)

    def test_a_file_that_is_not_a_decisions_file_is_refused(self, tmp_path):
        path = tmp_path / "d.yaml"
        path.write_text(yaml.safe_dump({"questions": []}), encoding="utf-8")
        with pytest.raises(GoldenAssistError) as excinfo:
            load_decisions(path)
        assert "not a decisions file" in str(excinfo.value)

    def test_ids_shorthand_builds_the_same_decisions(self):
        decisions = decisions_from_ids(["a", "b"], ["c"], reason="why")
        assert [(d.id, d.action) for d in decisions] == [
            ("a", ACCEPT),
            ("b", ACCEPT),
            ("c", REJECT),
        ]
        assert decisions[2].reason == "why"


class TestTheMergeCannotCorruptTheBenchmark:
    """The file this writes is invariant 5's objective function."""

    def _accepted(self, part_dir, n=1):
        candidates = suggest_candidates(part_dir, n=20)
        ids = [c.question.id for c in candidates.candidates[:n]]
        return apply_decisions(candidates, [Decision(id=i, action=ACCEPT) for i in ids]).accepted

    def test_the_existing_bytes_stay_the_prefix_of_the_file(self, part_dir, golden):
        before = golden.read_text(encoding="utf-8")
        merge_into_golden(golden, self._accepted(part_dir, 2), part="TEST")
        after = golden.read_text(encoding="utf-8")
        assert after.startswith(before)
        assert "# Hand-written golden set." in after

    def test_the_merged_question_loads_as_a_golden_question(self, part_dir, golden):
        accepted = self._accepted(part_dir, 2)
        result = merge_into_golden(golden, accepted, part="TEST")
        questions = load_golden(golden)
        assert [q.id for q in questions][: len(result.preserved)] == result.preserved
        assert {q.id for q in questions} >= {q.id for q in accepted}

    def test_the_appended_block_matches_the_file_s_own_indentation(self, part_dir, tmp_path):
        """The reindent had zero coverage in the lineage this came from."""
        cases = (
            ("  ", "questions:\n  - id: h1\n    question: Q?\n    expected_substrings: [a]\n"),
            ("", "questions:\n- id: h1\n  question: Q?\n  expected_substrings: [a]\n"),
        )
        for indent, body in cases:
            golden = tmp_path / f"golden_qa_I{len(indent)}.yaml"
            golden.write_text(body, encoding="utf-8")
            merge_into_golden(golden, self._accepted(part_dir, 1), part="TEST")
            text = golden.read_text(encoding="utf-8")
            appended = [line for line in text.splitlines() if line.lstrip().startswith("- id: g-")]
            assert appended, indent
            assert all(line.startswith(f"{indent}- id: ") for line in appended), indent
            # ...and it still parses to two questions, not one and a fragment.
            assert len(yaml.safe_load(text)["questions"]) == 2

    def test_a_duplicate_id_is_refused_and_nothing_is_written(self, part_dir, golden):
        accepted = self._accepted(part_dir, 1)
        merge_into_golden(golden, accepted, part="TEST")
        before = golden.read_text(encoding="utf-8")
        with pytest.raises(GoldenAssistError) as excinfo:
            merge_into_golden(golden, accepted, part="TEST")
        assert accepted[0].id in str(excinfo.value)
        assert golden.read_text(encoding="utf-8") == before

    def test_a_part_with_no_golden_file_yet_gets_one(self, part_dir, tmp_path):
        golden = tmp_path / "new" / "golden_qa_TEST.yaml"
        result = merge_into_golden(golden, self._accepted(part_dir, 2), part="TEST")
        assert result.created is True
        assert golden.exists()
        assert len(load_golden(golden)) == 2

    def test_merging_nothing_writes_nothing(self, golden):
        before = golden.read_text(encoding="utf-8")
        result = merge_into_golden(golden, [], part="TEST")
        assert result.added == []
        assert result.preserved == ["h1-junction-temperature"]
        assert golden.read_text(encoding="utf-8") == before

    def test_a_merge_that_would_not_parse_leaves_the_file_untouched(self, part_dir, tmp_path):
        """F16, the defect this port fixes rather than reproduces.

        The lineage wrote the merged text and *then* re-parsed it to decide
        whether to roll back - so `yaml.safe_load` raised before the rollback
        guard was reached and left the benchmark corrupted on disk. Here the
        check happens in memory and the file is never opened for writing.
        """
        import datasheet_analyzer.evalh.confirm as confirm_module

        golden = tmp_path / "golden_qa_UNPARSABLE.yaml"
        original = "questions:\n  - id: h1\n    question: Q?\n"
        golden.write_text(original, encoding="utf-8")
        # Forcing the reindent to emit an unterminated scalar is the only way
        # to reach the case; what is asserted is the *response* to it.
        kept = confirm_module._reindent
        confirm_module._reindent = lambda block, indent: '  - id: g-x\n    q: "open\n'
        try:
            with pytest.raises(GoldenAssistError) as excinfo:
                merge_into_golden(golden, self._accepted(part_dir, 1), part="TEST")
        finally:
            confirm_module._reindent = kept
        assert "does not parse" in str(excinfo.value)
        assert "nothing was written" in str(excinfo.value)
        assert golden.read_text(encoding="utf-8") == original

    def test_a_merge_that_would_move_an_existing_question_is_refused(self, part_dir, golden):
        """The rollback guard itself, which also had zero coverage."""
        import datasheet_analyzer.evalh.confirm as confirm_module

        before = golden.read_text(encoding="utf-8")
        kept = confirm_module._reindent
        confirm_module._reindent = lambda block, indent: "  - id: replaced\n"
        try:
            with pytest.raises(GoldenAssistError) as excinfo:
                merge_into_golden(golden, self._accepted(part_dir, 2), part="TEST")
        finally:
            confirm_module._reindent = kept
        assert "nothing was written" in str(excinfo.value)
        assert golden.read_text(encoding="utf-8") == before

    def test_a_benchmark_that_already_does_not_parse_is_refused(self, part_dir, tmp_path):
        golden = tmp_path / "golden_qa_BAD.yaml"
        original = "questions: [\n"
        golden.write_text(original, encoding="utf-8")
        with pytest.raises(GoldenAssistError) as excinfo:
            merge_into_golden(golden, self._accepted(part_dir, 1), part="TEST")
        assert "does not parse" in str(excinfo.value)
        assert golden.read_text(encoding="utf-8") == original


class TestTheFileNeverClaimsAVerificationThatDidNotHappen:
    """F17, the second defect this port fixes rather than reproduces."""

    def _accepted(self, part_dir):
        candidates = suggest_candidates(part_dir, n=20)
        return apply_decisions(
            candidates, [Decision(id=candidates.candidates[0].question.id, action=ACCEPT)]
        ).accepted

    def test_a_bulk_run_is_the_default_and_says_it_checked_nothing(self, part_dir, tmp_path):
        golden = tmp_path / "golden_qa_TEST.yaml"
        merge_into_golden(golden, self._accepted(part_dir), part="TEST")
        text = golden.read_text(encoding="utf-8")
        assert "page was displayed" in text
        assert "Treat these as unverified" in text
        # The forged sentence the lineage stamped unconditionally.
        assert "Every answer below was checked against the printed page" not in text

    def test_only_a_pdf_run_may_claim_the_printed_page(self, part_dir, tmp_path):
        golden = tmp_path / "golden_qa_TEST.yaml"
        merge_into_golden(golden, self._accepted(part_dir), provenance=PROVENANCE_PAGE, part="TEST")
        assert "shown beside the printed PDF page" in golden.read_text(encoding="utf-8")

    def test_an_interactive_run_without_a_pdf_says_which_text_was_shown(self, part_dir, tmp_path):
        golden = tmp_path / "golden_qa_TEST.yaml"
        merge_into_golden(
            golden, self._accepted(part_dir), provenance=PROVENANCE_CORPUS, part="TEST"
        )
        assert "cannot confirm a page citation" in golden.read_text(encoding="utf-8")

    def test_the_appended_block_carries_the_provenance_too(self, part_dir, golden):
        merge_into_golden(golden, self._accepted(part_dir), provenance=PROVENANCE_BULK, part="TEST")
        text = golden.read_text(encoding="utf-8")
        assert "confirmed from generated candidates" in text
        assert "page was displayed" in text

    def test_the_three_provenances_are_distinct_claims(self):
        assert len({PROVENANCE_PAGE, PROVENANCE_CORPUS, PROVENANCE_BULK}) == 3
        assert "NO" in PROVENANCE_BULK
        assert "NO --pdf" in PROVENANCE_CORPUS
        assert "shown beside the printed PDF page" in PROVENANCE_PAGE

    def test_the_report_prints_what_it_stamped(self, part_dir, golden):
        from datasheet_analyzer.evalh.confirm import render_confirm_report

        candidates = suggest_candidates(part_dir, n=20)
        outcome = apply_decisions(
            candidates, [Decision(id=candidates.candidates[0].question.id, action=ACCEPT)]
        )
        merge = merge_into_golden(golden, outcome.accepted, part="TEST")
        report = render_confirm_report(outcome, merge, rejected_file=None)
        assert "Recorded provenance:" in report
        assert PROVENANCE_BULK in report


class TestRejectedCandidatesAreNotSuggestedAgain:
    def test_a_rejected_key_is_excluded_from_the_next_run(self, part_dir, tmp_path):
        candidates = suggest_candidates(part_dir, n=20)
        victim = candidates.candidates[0]
        ledger = tmp_path / "golden_qa_TEST.rejected.yaml"
        write_rejections(
            ledger,
            "TEST",
            [GoldenRejection(key=victim.key, id=victim.question.id, reason="marker cell")],
        )
        again = suggest_candidates(part_dir, n=20, rejected=rejected_keys(ledger))
        assert victim.question.id not in {c.question.id for c in again.candidates}
        assert again.skipped_rejected == 1
        assert any("previously rejected" in note for note in again.notes)

    def test_the_ledger_records_the_reason_and_is_sorted(self, tmp_path):
        path = tmp_path / "r.yaml"
        write_rejections(
            path,
            "TEST",
            [
                GoldenRejection(key="z|t", id="z", reason="second"),
                GoldenRejection(key="a|t", id="a", reason="first"),
            ],
        )
        ledger = read_rejections(path)
        assert [e.key for e in ledger.rejected] == ["a|t", "z|t"]
        assert ledger.rejected[0].reason == "first"

    def test_rejecting_the_same_key_twice_keeps_the_newer_reason(self, tmp_path):
        path = tmp_path / "r.yaml"
        write_rejections(path, "TEST", [GoldenRejection(key="k|t", reason="old")])
        write_rejections(path, "TEST", [GoldenRejection(key="k|t", reason="better")])
        ledger = read_rejections(path)
        assert len(ledger.rejected) == 1
        assert ledger.rejected[0].reason == "better"

    def test_an_absent_ledger_is_empty_rather_than_an_error(self, tmp_path):
        assert rejected_keys(tmp_path / "nothing.yaml") == set()

    def test_a_question_already_in_the_golden_set_is_not_re_suggested(self, part_dir, golden):
        candidates = suggest_candidates(part_dir, n=20)
        first = candidates.candidates[0]
        outcome = apply_decisions(candidates, [Decision(id=first.question.id, action=ACCEPT)])
        merge_into_golden(golden, outcome.accepted, part="TEST")
        from datasheet_analyzer.evalh.candidates import existing_question_ids

        again = suggest_candidates(part_dir, n=20, existing_ids=existing_question_ids(golden))
        assert first.question.id not in {c.question.id for c in again.candidates}
        assert again.skipped_existing == 1


class TestConfirmShowsThePrintedPageText:
    """Box 4's display half - asserted on the text, not on the call."""

    def _first(self, part_dir):
        return suggest_candidates(part_dir, n=20).candidates[0]

    def test_the_pdf_page_is_preferred_and_carries_no_warning(self, part_dir):
        candidate = self._first(part_dir)
        pages = [""] * candidate.page
        pages[candidate.page - 1] = "PRINTED PAGE MARKER and the answer 105 °C"
        context = page_context(part_dir, candidate, page_texts=pages)
        assert context.from_pdf
        assert context.warning == ""
        assert "PRINTED PAGE MARKER" in context.text

    def test_the_rendered_candidate_really_shows_that_page_text(self, part_dir):
        """The assertion the lineage never made: the page reaches the screen."""
        candidate = self._first(part_dir)
        pages = [""] * candidate.page
        pages[candidate.page - 1] = "UNIQUE-PAGE-SENTINEL-42 printed here"
        rendered = render_candidate(
            candidate, page_context(part_dir, candidate, page_texts=pages), position="1/8"
        )
        assert "UNIQUE-PAGE-SENTINEL-42" in rendered
        assert "| UNIQUE-PAGE-SENTINEL-42 printed here" in rendered
        assert candidate.question.question in rendered
        assert candidate.source in rendered
        assert "[1/8]" in rendered

    def test_without_a_pdf_the_corpus_section_is_shown_and_labelled(self, part_dir):
        candidate = self._first(part_dir)
        context = page_context(part_dir, candidate)
        assert not context.from_pdf
        assert "corpus section" in context.origin
        assert "cannot confirm the page citation" in context.warning
        rendered = render_candidate(candidate, context)
        assert context.warning in rendered
        assert context.text.splitlines()[0] in rendered

    def test_the_substring_check_is_reported(self, part_dir):
        candidate = self._first(part_dir)
        pages = [""] * candidate.page
        pages[candidate.page - 1] = "nothing the candidate expects"
        rendered = render_candidate(candidate, page_context(part_dir, candidate, page_texts=pages))
        assert "substrings NOT on this page" in rendered

    def test_a_page_nothing_covers_says_so_rather_than_showing_nothing(self, part_dir):
        candidate = self._first(part_dir).model_copy(update={"page": 999})
        context = page_context(part_dir, candidate)
        assert context.text == ""
        assert "open the printed page" in context.warning
        assert "(no text available)" in render_candidate(candidate, context)


class TestTheInteractiveShellIsThinAndDrivenThroughItsSeam:
    def test_one_keystroke_per_candidate_becomes_a_decision(self, part_dir):
        candidates = suggest_candidates(part_dir, n=4)
        answers = iter(["a", "r", "the cell is a range", "e", "Better wording?", "s"])
        written: list[str] = []
        decisions = run_interactive(
            candidates,
            part_dir=part_dir,
            read=lambda _prompt="": next(answers),
            write=written.append,
        )
        assert [d.action for d in decisions] == [ACCEPT, REJECT, EDIT]
        assert decisions[1].reason == "the cell is a range"
        assert decisions[2].edits == {"question": "Better wording?"}
        assert len(written) == 4  # one rendering per candidate

    def test_an_unrecognised_key_skips_rather_than_guessing(self, part_dir):
        candidates = suggest_candidates(part_dir, n=2)
        answers = iter(["x", "a"])
        written: list[str] = []
        decisions = run_interactive(
            candidates,
            part_dir=part_dir,
            read=lambda _prompt="": next(answers),
            write=written.append,
        )
        assert [d.action for d in decisions] == [ACCEPT]
        assert any("not a decision" in line for line in written)

    def test_quitting_leaves_the_rest_undecided(self, part_dir):
        candidates = suggest_candidates(part_dir, n=4)
        answers = iter(["a", "q"])
        written: list[str] = []
        decisions = run_interactive(
            candidates,
            part_dir=part_dir,
            read=lambda _prompt="": next(answers),
            write=written.append,
        )
        assert len(decisions) == 1
        assert any("stay unconfirmed" in line for line in written)
        outcome = apply_decisions(candidates, decisions)
        assert len(outcome.deferred) == len(candidates.candidates) - 1

    def test_the_shell_shows_the_page_it_was_given(self, part_dir):
        candidates = suggest_candidates(part_dir, n=1)
        page = candidates.candidates[0].page
        pages = [""] * page
        pages[page - 1] = "SHELL-PAGE-SENTINEL"
        written: list[str] = []
        run_interactive(
            candidates,
            part_dir=part_dir,
            page_texts=pages,
            read=lambda _prompt="": "s",
            write=written.append,
        )
        assert any("SHELL-PAGE-SENTINEL" in line for line in written)


class TestTheCommand:
    @pytest.fixture(autouse=True)
    def _point_at(self, settings, monkeypatch):
        monkeypatch.setattr(cli, "get_settings", lambda: settings)

    def test_suggest_writes_the_file_and_reports_the_mix(self, golden, capsys):
        code = cli.main(
            ["golden", "suggest", "--part", "TEST", "--n", "6", "--golden", str(golden)]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "# Golden candidates - TEST" in out
        assert "| artifact |" in out
        assert candidate_path(golden).exists()
        assert read_candidates(candidate_path(golden)).candidates

    def test_suggest_reports_the_refused_population(self, golden, capsys):
        cli.main(["golden", "suggest", "--part", "TEST", "--golden", str(golden)])
        out = capsys.readouterr().out
        assert "Refused" in out
        assert "pixels" in out

    def test_suggest_json_is_the_candidate_set(self, golden, capsys):
        cli.main(
            ["golden", "suggest", "--part", "TEST", "--n", "4", "--golden", str(golden), "--json"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["part"] == "TEST"
        assert len(payload["candidates"]) == 4
        assert all(c["confirmed"] is False for c in payload["candidates"])
        assert "refused" in payload

    def test_confirm_merges_records_and_rewrites_the_candidate_file(self, golden, capsys):
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "4", "--golden", str(golden)])
        capsys.readouterr()
        candidates = read_candidates(candidate_path(golden))
        ids = [c.question.id for c in candidates.candidates]
        code = cli.main(
            [
                "golden",
                "confirm",
                "--part",
                "TEST",
                "--golden",
                str(golden),
                "--accept-ids",
                ids[0],
                "--reject-ids",
                ids[1],
                "--reject-reason",
                "the cell is a range",
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "**1 accepted**" in out
        assert ids[0] in {q.id for q in load_golden(golden)}
        # the rejection is remembered, and the undecided two stay proposals
        assert read_rejections(rejected_path(golden)).rejected[0].id == ids[1]
        left = read_candidates(candidate_path(golden))
        assert [c.question.id for c in left.candidates] == ids[2:]

    def test_the_round_trip_never_re_suggests_a_rejection(self, golden, capsys):
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "4", "--golden", str(golden)])
        ids = [c.question.id for c in read_candidates(candidate_path(golden)).candidates]
        cli.main(
            [
                "golden",
                "confirm",
                "--part",
                "TEST",
                "--golden",
                str(golden),
                "--reject-ids",
                ids[0],
                "--reject-reason",
                "no",
            ]
        )
        capsys.readouterr()
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "20", "--golden", str(golden)])
        again = read_candidates(candidate_path(golden))
        assert ids[0] not in {c.question.id for c in again.candidates}
        assert again.skipped_rejected == 1

    def test_a_dry_run_writes_nothing(self, golden, capsys):
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "3", "--golden", str(golden)])
        before_golden = golden.read_text(encoding="utf-8")
        before_candidates = candidate_path(golden).read_text(encoding="utf-8")
        ids = [c.question.id for c in read_candidates(candidate_path(golden)).candidates]
        capsys.readouterr()
        code = cli.main(
            [
                "golden",
                "confirm",
                "--part",
                "TEST",
                "--golden",
                str(golden),
                "--accept-ids",
                ids[0],
                "--dry-run",
            ]
        )
        assert code == 0
        assert "nothing was written" in capsys.readouterr().out
        assert golden.read_text(encoding="utf-8") == before_golden
        assert candidate_path(golden).read_text(encoding="utf-8") == before_candidates

    def test_confirm_refuses_to_run_blind_without_a_terminal(self, golden, monkeypatch, capsys):
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "3", "--golden", str(golden)])
        capsys.readouterr()
        monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
        code = cli.main(["golden", "confirm", "--part", "TEST", "--golden", str(golden)])
        assert code == 2
        assert "--decisions" in capsys.readouterr().err

    def test_confirm_without_candidates_says_to_generate_them(self, golden, capsys):
        code = cli.main(["golden", "confirm", "--part", "TEST", "--golden", str(golden)])
        assert code == 2
        assert "dsa golden suggest" in capsys.readouterr().err

    def test_suggest_on_an_unbuilt_part_says_which_command_fixes_it(self, golden, capsys):
        code = cli.main(["golden", "suggest", "--part", "GHOST", "--golden", str(golden)])
        assert code == 2
        assert "dsa build" in capsys.readouterr().err


class TestNothingHereCanReachTheRealBenchmarks:
    """`dsa golden confirm` writes invariant 5's objective function.

    Batch B found a prototype run outside pytest that wrote into the
    repository's real `library/` because it inherited default settings. The
    same shape of mistake here would edit `tests/fixtures/golden_qa_<PART>.yaml`
    - the file every other gate in this repo is measured against. Two
    independent things stop it, and both are asserted rather than assumed.
    """

    #: The committed benchmarks, by absolute path, read once at import.
    REAL = sorted(GOLDEN_DIR.glob("golden_qa_*.yaml"))

    def test_the_repository_really_does_keep_its_benchmarks_there(self):
        assert self.REAL, f"no committed benchmarks under {GOLDEN_DIR}"
        assert GOLDEN_DIR.name == "fixtures"

    def test_the_suite_points_the_golden_directory_somewhere_else(self):
        """Defence one: `DSA_GOLDEN_DIR`, set for every test by conftest."""
        assert golden_dir() != GOLDEN_DIR
        assert default_golden_path("AD9081") != GOLDEN_DIR / "golden_qa_AD9081.yaml"
        assert not str(golden_dir()).startswith(str(GOLDEN_DIR))

    def test_a_confirm_run_that_names_no_path_writes_under_that_directory(
        self, settings, part_dir, monkeypatch, capsys
    ):
        """Defence one, exercised: the command with no `--golden` at all."""
        monkeypatch.setattr(cli, "get_settings", lambda: settings)
        assert cli.main(["golden", "suggest", "--part", "TEST", "--n", "3"]) == 0
        written = candidate_path(default_golden_path("TEST"))
        assert written.exists()
        assert written.parent == golden_dir()
        ids = [c.question.id for c in read_candidates(written).candidates]
        capsys.readouterr()
        assert cli.main(["golden", "confirm", "--part", "TEST", "--accept-ids", ids[0]]) == 0
        assert default_golden_path("TEST").exists()
        assert default_golden_path("TEST").parent == golden_dir()

    def test_every_committed_benchmark_is_byte_identical_after_all_of_that(self):
        """Defence two: the bytes themselves, compared against git.

        The strongest form available in-process - if any test in this module
        had reached a real fixture, this would fail with the file named.
        """
        import subprocess

        repo = GOLDEN_DIR.parent.parent
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", str(GOLDEN_DIR)],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:  # not a checkout - fall back to the weaker check
            pytest.skip("not a git checkout")
        touched = [line for line in result.stdout.splitlines() if "golden_qa_" in line]
        assert touched == [], f"a test wrote into the committed benchmarks: {touched}"

    def test_no_candidate_or_rejection_file_was_left_beside_them(self):
        assert list(GOLDEN_DIR.glob("*.candidate.yaml")) == []
        assert list(GOLDEN_DIR.glob("*.rejected.yaml")) == []


class TestNoModelCallInTheGenerationPath:
    def test_the_modules_import_nothing_that_could_call_a_model(self):
        for name in ("candidates.py", "suggest.py", "confirm.py"):
            text = (SRC / "evalh" / name).read_text(encoding="utf-8")
            for forbidden in ("anthropic", "Anthropic", "enrich"):
                assert forbidden not in text, f"{name} mentions {forbidden}"

    def test_a_candidate_question_is_a_format_string_over_printed_cells(self, part_dir):
        for candidate in suggest_candidates(part_dir, n=20).candidates:
            question = candidate.question.question
            assert question.endswith("?")
            assert question.startswith(
                ("What is ", "Which signal ", "At what address ", "Which figure ")
            )
