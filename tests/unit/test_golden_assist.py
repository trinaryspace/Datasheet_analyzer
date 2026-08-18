"""`dsa golden suggest|confirm` — generated candidates and the human decision
(phase 7, ticket 06).

What these prove, criterion by criterion:

- **an unconfirmed candidate does not move `dsa verify`** — the ticket's own
  sharpest criterion and invariant 5's new clause. Asserted with a *control*:
  the same verify run is compared before and after generation (byte for byte,
  exit code included), and then again after the candidate is **confirmed**,
  where the report must grow. Without the control the first assertion would
  pass just as well against a generator that wrote nothing;
- **candidates are stratified across sections, backends and confidence
  grades** — asserted on a two-document, two-backend corpus, and asserted as
  *spread* rather than as a count: the first k candidates come from k distinct
  strata, so twenty variations of the easiest lookup cannot pass;
- **every candidate carries its answer verbatim, its page and the record it
  came from** — walked back through `provenance.resolve_source` to the record
  and the page it was printed on (invariant 8), for every candidate of every
  corpus here;
- **`confirm` shows the printed page text** — the PDF page when one is given,
  the corpus section with an explicit warning when it is not, because a
  candidate confirmed against the extraction that produced it has not been
  checked;
- **accepted candidates merge without disturbing hand-written questions** —
  the pre-existing bytes must remain the prefix of the file and every existing
  question must still parse identically;
- **rejected candidates are not re-suggested** — the ledger keys on the record
  reference plus the template, both of which the next run reproduces;
- **a part with no built corpus errors clearly** rather than generating
  questions with no answers;
- **no model call anywhere in the path** (invariant 8), as a source-level guard,
  plus determinism: two runs over one corpus produce identical bytes.

Hermetic by construction (invariant 4): the corpora are the synthetic ones
`mcp_corpus.py` builds plus one two-backend corpus written here. Nothing
touches the network, an LLM, a real PDF or a terminal — the interactive shell
is driven through its injected reader.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import yaml
from mcp_corpus import build_part, empty_settings

from datasheet_analyzer import cli
from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.evalh.candidates import (
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
    candidate_golden_path,
    default_golden_path,
    load_golden,
    rejected_golden_path,
)
from datasheet_analyzer.evalh.suggest import (
    ARTIFACT_ORDER,
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
    PinType,
    RawDocument,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.provenance import resolve_source
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
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    path = fixtures / "golden_qa_TEST.yaml"
    path.write_text(HAND_WRITTEN, encoding="utf-8")
    return path


# --- a two-document, two-backend corpus --------------------------------------


def _doc(part: str, doc_hash: str, extractor: str, symbol: str, page: int):
    source = SourceDocument(
        content_hash=doc_hash,
        path=f"pdfs/{extractor}.pdf",
        part_number=part,
        doc_type=DocType.DATASHEET if extractor == "ti_html" else DocType.REGISTER_MAP,
        revision="SBASA41E",
        page_count=40,
    )
    raw = RawDocument(
        source=source,
        sections=[
            SectionNode(
                number="7.1",
                title=f"{extractor} characteristics",
                page_start=page,
                page_end=page,
                paragraphs=[f"The {symbol} is specified as 3.3 V on this page."],
            )
        ],
        extractor=extractor,
        extractor_version="test-1",
    )
    specs = SpecSet(
        schema_version="5",
        part_number=part,
        doc_hash=doc_hash,
        records=[
            SpecRecord(
                id="rec_1",
                section="7.1",
                section_title=f"{extractor} characteristics",
                symbol=symbol,
                name=f"{symbol} supply voltage",
                max="3.3",
                unit=SpecUnit(verbatim="V", canonical="V"),
                page=page,
                confidence=Confidence.HIGH if extractor == "ti_html" else Confidence.LOW,
            )
        ],
    )
    return raw, specs


def _two_backend_part(part_dir: Path) -> Path:
    """One part, two documents, two extraction backends — the backend stratum.

    A single-document corpus cannot prove a backend spread, and asserting the
    dimension on a corpus that has only one value for it would be asserting
    nothing.
    """
    part = part_dir.name
    a_raw, a_specs = _doc(part, "a" * 64, "ti_html", "VDDA", 4)
    b_raw, b_specs = _doc(part, "b" * 64, "pdf_layout", "VDDB", 9)
    write_corpus(
        part_dir,
        [
            (a_raw, build_section_plans(a_raw), {}),
            (b_raw, build_section_plans(b_raw), {}),
        ],
        f"# {part}\n\nTwo documents.\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        specsets=[a_specs, b_specs],
    )
    return part_dir


def _skewed_part(part_dir: Path) -> Path:
    """One document: twelve spec rows across six printed tables, and two pins.

    The shape a flat stratification gets wrong — many spec strata, one pin
    stratum — reproduced small enough to assert on exactly.
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
        schema_version="5",
        part_number=part,
        doc_hash=doc_hash,
        records=[
            SpecRecord(
                id=f"rec_{i + 1}",
                section="",
                section_title=f"Table {i % 6} Specifications",
                symbol=f"V{i}",
                name=f"V{i} supply voltage",
                max=f"{i + 1}.0",
                unit=SpecUnit(verbatim="V", canonical="V"),
                page=3,
                confidence=Confidence.HIGH,
            )
            for i in range(12)
        ],
    )
    pins = PinSet(
        schema_version="1",
        part_number=part,
        doc_hash=doc_hash,
        pins=[
            PinRecord(
                id=f"pin_{i + 1}",
                pin=f"A{i + 1}",
                pin_verbatim=f"A{i + 1}",
                name=f"VDD{i + 1}",
                type=PinType.POWER,
                type_evidence="supply",
                description="Supply pin",
                section="",
                page=3,
                confidence=Confidence.HIGH,
            )
            for i in range(2)
        ],
    )
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        f"# {part}\n\nOne document.\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="unknown",
        specsets=[specs],
        pinsets=[pins],
    )
    return part_dir


# --- stratification ----------------------------------------------------------


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

        Asserted at two levels: the artifacts rotate, and inside each artifact
        the confidence grades rotate. A generator that emitted twenty rows of
        one spec table would repeat on element two.
        """
        candidates = suggest_candidates(part_dir, n=20).candidates
        assert _round_robin_respected([c.artifact for c in candidates])
        for artifact in {c.artifact for c in candidates}:
            grades = [
                c.confidence.value for c in candidates if c.artifact == artifact
            ]
            assert _round_robin_respected(grades), artifact

    def test_a_scarce_artifact_is_not_crowded_out_by_a_plentiful_one(self, tmp_path):
        """A flat round-robin over the composite stratum would let a table with
        many printed sections outvote a whole artifact — AD9081 prints its specs
        under twelve titles and its 321 pins under none. Every pin the corpus
        has must still reach a set of six."""
        part_dir = _skewed_part(tmp_path / "parts" / "SKEW")
        candidates = suggest_candidates(part_dir, n=6).candidates
        counts = strata_of(candidates)["artifact"]
        assert counts["pins.json"] == 2
        assert counts["specs.json"] == 4

    def test_the_set_spans_sections_artifacts_and_confidence_grades(self, part_dir):
        candidates = suggest_candidates(part_dir, n=8).candidates
        assert len({c.section for c in candidates}) >= 3
        assert len({c.artifact for c in candidates}) >= 4
        assert {c.confidence for c in candidates} >= {
            Confidence.HIGH,
            Confidence.MEDIUM,
            Confidence.LOW,
        }

    def test_no_single_artifact_dominates_the_set(self, part_dir):
        """An all-easy-lookup set satisfies `--n` and defeats the purpose."""
        candidates = suggest_candidates(part_dir, n=8).candidates
        counts = strata_of(candidates)["artifact"]
        assert max(counts.values()) <= len(candidates) // 2 + 1

    def test_both_backends_appear_when_the_part_has_two(self, tmp_path):
        part_dir = _two_backend_part(tmp_path / "parts" / "TWO")
        candidates = suggest_candidates(part_dir, n=2).candidates
        assert {c.backend for c in candidates} == {"ti_html", "pdf_layout"}

    def test_the_file_publishes_the_mix_it_selected(self, part_dir, tmp_path):
        candidates = suggest_candidates(part_dir, n=8)
        path = write_candidates(tmp_path / "c.candidate.yaml", candidates)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert set(data["strata"]) == set(STRATA_DIMENSIONS)
        assert sum(data["strata"]["artifact"].values()) == len(data["candidates"])

    def test_the_pool_is_reported_even_for_an_artifact_with_no_records(self, settings):
        """A corpus with no register map says so rather than reading as broken."""
        build_part(settings.parts_dir / "BARE", with_device_tables=False)
        clear_index_cache()
        candidates = suggest_candidates(settings.parts_dir / "BARE", n=5)
        assert candidates.pool["registers.json"] == 0
        assert any("registers.json" in note for note in candidates.notes)


# --- provenance --------------------------------------------------------------


class TestEveryCandidateCarriesItsAnswerPageAndRecord:
    def test_every_source_resolves_to_the_record_and_the_page(self, part_dir):
        candidates = suggest_candidates(part_dir, n=20).candidates
        assert candidates
        for candidate in candidates:
            resolved = resolve_source(part_dir, candidate.source)
            assert resolved is not None, candidate.source
            assert resolved.page == candidate.page
            assert candidate.question.pages == [candidate.page]
            assert candidate.verbatim
            assert candidate.template in TEMPLATES
            assert candidate.artifact in ARTIFACT_ORDER

    def test_the_expected_substrings_are_printed_cells_of_that_record(self, part_dir):
        """Nothing in a candidate's answer is composed — every substring is a
        cell the record already published."""
        candidates = suggest_candidates(part_dir, n=20).candidates
        for candidate in candidates:
            resolved = resolve_source(part_dir, candidate.source)
            blob = resolved.record.model_dump_json()
            for substring in candidate.question.expected_substrings:
                assert substring in blob, (candidate.question.id, substring)

    def test_every_candidate_is_written_unconfirmed(self, part_dir, tmp_path):
        candidates = suggest_candidates(part_dir, n=8)
        assert all(not c.confirmed for c in candidates.candidates)
        path = write_candidates(tmp_path / "c.candidate.yaml", candidates)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["candidates"]
        assert all(row["confirmed"] is False for row in data["candidates"])


# --- invariant 5: an unconfirmed candidate is inert --------------------------


def _verify(settings, golden: Path, capsys) -> tuple[int, str]:
    code = cli.main(["verify", "--part", "TEST", "--golden", str(golden)])
    return code, capsys.readouterr().out


class TestAnUnconfirmedCandidateDoesNotAffectVerify:
    """Invariant 5's new clause, with the control that makes it mean something."""

    def test_generating_candidates_leaves_verify_byte_identical(
        self, settings, golden, monkeypatch, capsys
    ):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        before_code, before_out = _verify(settings, golden, capsys)

        exit_code = cli.main(
            ["golden", "suggest", "--part", "TEST", "--n", "6", "--golden", str(golden)]
        )
        capsys.readouterr()
        assert exit_code == 0
        candidates = candidate_path(golden)
        assert candidates.exists()

        after_code, after_out = _verify(settings, golden, capsys)
        assert (after_code, after_out) == (before_code, before_out)
        for candidate in read_candidates(candidates).candidates:
            assert candidate.question.id not in after_out

    def test_confirming_one_does_change_verify(
        self, settings, golden, monkeypatch, capsys
    ):
        """The control: the path is live, so the invariance above is the
        confirmation gate doing its job rather than a dead generator."""
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        _, before_out = _verify(settings, golden, capsys)

        cli.main(["golden", "suggest", "--part", "TEST", "--n", "6", "--golden", str(golden)])
        first = read_candidates(candidate_path(golden)).candidates[0]
        cli.main(
            [
                "golden", "confirm", "--part", "TEST", "--golden", str(golden),
                "--accept-ids", first.question.id,
            ]
        )
        capsys.readouterr()

        _, after_out = _verify(settings, golden, capsys)
        assert first.question.id not in before_out
        assert first.question.id in after_out
        assert len(load_golden(golden)) == 2

    def test_the_candidate_file_is_not_the_benchmark_file(self):
        assert candidate_golden_path("AFE7950") != default_golden_path("AFE7950")
        assert rejected_golden_path("AFE7950") != default_golden_path("AFE7950")
        assert candidate_golden_path("AFE7950").name.endswith(".candidate.yaml")

    def test_load_golden_refuses_a_candidate_file(self, part_dir, tmp_path):
        path = write_candidates(
            tmp_path / "golden_qa_TEST.candidate.yaml",
            suggest_candidates(part_dir, n=3),
        )
        with pytest.raises(GoldenAssistError, match="counts toward nothing"):
            load_golden(path)

    def test_verify_refuses_a_candidate_file_passed_as_golden(
        self, settings, part_dir, tmp_path, monkeypatch, capsys
    ):
        path = write_candidates(
            tmp_path / "golden_qa_TEST.candidate.yaml",
            suggest_candidates(part_dir, n=3),
        )
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        code = cli.main(["verify", "--part", "TEST", "--golden", str(path)])
        assert code == 2
        assert "generated candidates" in capsys.readouterr().err

    def test_a_candidate_file_has_no_questions_key_at_all(self, part_dir, tmp_path):
        path = write_candidates(
            tmp_path / "c.candidate.yaml", suggest_candidates(part_dir, n=3)
        )
        assert "questions" not in yaml.safe_load(path.read_text(encoding="utf-8"))


# --- the decision core -------------------------------------------------------


class TestTheDecisionCoreIsPureAndTestable:
    def test_accept_edit_and_reject_land_where_they_belong(self, part_dir):
        candidates = suggest_candidates(part_dir, n=6)
        ids = [c.question.id for c in candidates.candidates]
        outcome = apply_decisions(
            candidates,
            [
                Decision(id=ids[0], action=ACCEPT),
                Decision(id=ids[1], action=EDIT, edits={"question": "Reworded?"}),
                Decision(id=ids[2], action=REJECT, reason="the cell is a footnote marker"),
            ],
        )
        assert [q.id for q in outcome.accepted] == [ids[0], ids[1]]
        assert outcome.edited_ids == [ids[1]]
        assert outcome.accepted[1].question == "Reworded?"
        assert [r.id for r in outcome.rejected] == [ids[2]]
        assert [c.question.id for c in outcome.deferred] == ids[3:]

    def test_an_edit_keeps_everything_it_did_not_change(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        original = candidates.candidates[0].question
        outcome = apply_decisions(
            candidates, [Decision(id=original.id, action=EDIT, edits={"pages": [99]})]
        )
        edited = outcome.accepted[0]
        assert edited.pages == [99]
        assert edited.expected_substrings == original.expected_substrings
        assert edited.spec_query == original.spec_query

    def test_a_decision_naming_an_unknown_candidate_is_refused(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        with pytest.raises(GoldenAssistError, match="no candidate"):
            apply_decisions(candidates, [Decision(id="g-nope", action=ACCEPT)])

    def test_one_candidate_may_not_be_decided_twice(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        one = candidates.candidates[0].question.id
        with pytest.raises(GoldenAssistError, match="decided twice"):
            apply_decisions(
                candidates,
                [Decision(id=one, action=ACCEPT), Decision(id=one, action=REJECT)],
            )

    def test_an_edit_with_no_edits_is_refused(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        one = candidates.candidates[0].question.id
        with pytest.raises(GoldenAssistError, match="no edits"):
            apply_decisions(candidates, [Decision(id=one, action=EDIT)])

    def test_only_the_reviewer_facing_fields_are_editable(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        one = candidates.candidates[0].question.id
        with pytest.raises(GoldenAssistError, match="not editable"):
            apply_decisions(
                candidates, [Decision(id=one, action=EDIT, edits={"kind": "plot"})]
            )

    def test_decisions_load_from_a_file_for_a_scripted_fleet_run(
        self, part_dir, tmp_path
    ):
        candidates = suggest_candidates(part_dir, n=4)
        ids = [c.question.id for c in candidates.candidates]
        path = tmp_path / "decisions.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "decisions": [
                        {"id": ids[0], "action": "accept"},
                        {"id": ids[1], "action": "reject", "reason": "wrong page"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        outcome = apply_decisions(candidates, load_decisions(path))
        assert [q.id for q in outcome.accepted] == [ids[0]]
        assert outcome.rejected[0].reason == "wrong page"

    def test_a_decisions_file_with_an_unknown_action_is_refused(self, tmp_path):
        path = tmp_path / "decisions.yaml"
        path.write_text(
            yaml.safe_dump({"decisions": [{"id": "x", "action": "maybe"}]}),
            encoding="utf-8",
        )
        with pytest.raises(GoldenAssistError, match="expected one of"):
            load_decisions(path)

    def test_ids_shorthand_builds_the_same_decisions(self):
        decisions = decisions_from_ids(["a"], ["b"], reason="no")
        assert [(d.id, d.action) for d in decisions] == [("a", ACCEPT), ("b", REJECT)]
        assert decisions[1].reason == "no"


# --- the merge ---------------------------------------------------------------


class TestAcceptedCandidatesMergeWithoutDisturbingHandWrittenQuestions:
    def test_the_existing_bytes_stay_the_prefix_of_the_file(self, part_dir, golden):
        before = golden.read_text(encoding="utf-8")
        before_questions = yaml.safe_load(before)["questions"]
        candidates = suggest_candidates(part_dir, n=3)
        outcome = apply_decisions(
            candidates,
            [Decision(id=candidates.candidates[0].question.id, action=ACCEPT)],
        )
        result = merge_into_golden(golden, outcome.accepted)

        after = golden.read_text(encoding="utf-8")
        assert after.startswith(before)
        assert "# Hand-written golden set." in after
        after_questions = yaml.safe_load(after)["questions"]
        assert after_questions[: len(before_questions)] == before_questions
        assert result.preserved == ["h1-junction-temperature"]
        assert result.added == [candidates.candidates[0].question.id]

    def test_the_merged_question_loads_as_a_golden_question(self, part_dir, golden):
        candidates = suggest_candidates(part_dir, n=3)
        outcome = apply_decisions(
            candidates,
            [Decision(id=candidates.candidates[0].question.id, action=ACCEPT)],
        )
        merge_into_golden(golden, outcome.accepted)
        questions = load_golden(golden)
        assert len(questions) == 2
        assert questions[1].id == candidates.candidates[0].question.id
        assert questions[1].pages == candidates.candidates[0].question.pages

    def test_a_duplicate_id_is_refused_and_nothing_is_written(self, part_dir, golden):
        candidates = suggest_candidates(part_dir, n=3)
        outcome = apply_decisions(
            candidates,
            [Decision(id=candidates.candidates[0].question.id, action=ACCEPT)],
        )
        merge_into_golden(golden, outcome.accepted)
        after_first = golden.read_text(encoding="utf-8")
        with pytest.raises(GoldenAssistError, match="already holds question id"):
            merge_into_golden(golden, outcome.accepted)
        assert golden.read_text(encoding="utf-8") == after_first

    def test_a_part_with_no_golden_file_yet_gets_one(self, part_dir, tmp_path):
        target = tmp_path / "fixtures" / "golden_qa_NEW.yaml"
        candidates = suggest_candidates(part_dir, n=3)
        outcome = apply_decisions(
            candidates,
            [Decision(id=candidates.candidates[0].question.id, action=ACCEPT)],
        )
        result = merge_into_golden(target, outcome.accepted)
        assert result.created and target.exists()
        assert len(load_golden(target)) == 1

    def test_merging_nothing_writes_nothing(self, golden):
        before = golden.read_text(encoding="utf-8")
        result = merge_into_golden(golden, [])
        assert result.added == []
        assert golden.read_text(encoding="utf-8") == before


# --- the rejection ledger ----------------------------------------------------


class TestRejectedCandidatesAreNotSuggestedAgain:
    def test_a_rejected_key_is_excluded_from_the_next_run(self, part_dir, tmp_path):
        first = suggest_candidates(part_dir, n=4)
        victim = first.candidates[0]
        ledger = tmp_path / "golden_qa_TEST.rejected.yaml"
        write_rejections(
            ledger,
            "TEST",
            [
                GoldenRejection(
                    key=victim.key,
                    id=victim.question.id,
                    question=victim.question.question,
                    reason="the value cell is a footnote marker",
                )
            ],
        )
        second = suggest_candidates(part_dir, n=4, rejected=rejected_keys(ledger))
        assert victim.key not in {c.key for c in second.candidates}
        assert second.skipped_rejected == 1

    def test_the_ledger_records_the_reason_and_is_sorted(self, tmp_path):
        ledger = tmp_path / "r.yaml"
        write_rejections(ledger, "TEST", [GoldenRejection(key="b|t", reason="second")])
        write_rejections(ledger, "TEST", [GoldenRejection(key="a|t", reason="first")])
        stored = read_rejections(ledger)
        assert [entry.key for entry in stored.rejected] == ["a|t", "b|t"]
        assert stored.rejected[0].reason == "first"

    def test_rejecting_the_same_key_twice_keeps_the_newer_reason(self, tmp_path):
        ledger = tmp_path / "r.yaml"
        write_rejections(ledger, "TEST", [GoldenRejection(key="a|t", reason="old")])
        write_rejections(ledger, "TEST", [GoldenRejection(key="a|t", reason="new")])
        stored = read_rejections(ledger)
        assert len(stored.rejected) == 1 and stored.rejected[0].reason == "new"

    def test_a_question_already_in_the_golden_set_is_not_re_suggested(
        self, part_dir, golden
    ):
        first = suggest_candidates(part_dir, n=3)
        outcome = apply_decisions(
            first, [Decision(id=first.candidates[0].question.id, action=ACCEPT)]
        )
        merge_into_golden(golden, outcome.accepted)
        from datasheet_analyzer.evalh.candidates import existing_question_ids

        second = suggest_candidates(
            part_dir, n=3, existing_ids=existing_question_ids(golden)
        )
        assert first.candidates[0].question.id not in {
            c.question.id for c in second.candidates
        }
        assert second.skipped_existing == 1


# --- the printed page beside the candidate -----------------------------------


class TestConfirmShowsThePrintedPageText:
    def test_the_pdf_page_is_preferred_and_carries_no_warning(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3).candidates
        candidate = next(c for c in candidates if c.page == 6)
        pages = ["p1", "p2", "p3", "p4", "p5", "printed page six text"]
        context = page_context(part_dir, candidate, page_texts=pages)
        assert context.origin == "printed PDF p.6"
        assert context.text == "printed page six text"
        assert context.warning == ""

    def test_without_a_pdf_the_corpus_section_is_shown_and_labelled(self, part_dir):
        candidate = suggest_candidates(part_dir, n=3).candidates[0]
        context = page_context(part_dir, candidate)
        assert context.origin.startswith("corpus section docs/")
        assert "not the printed page" in context.warning
        assert context.available

    def test_the_rendered_candidate_shows_the_page_and_the_substring_check(
        self, part_dir
    ):
        candidate = suggest_candidates(part_dir, n=3).candidates[0]
        context = page_context(part_dir, candidate, page_texts=["", "", "", "", "", "nope"])
        rendered = render_candidate(candidate, context, position="1/3")
        assert "[1/3]" in rendered
        assert candidate.source in rendered
        assert "printed PDF p.6" in rendered
        assert "substrings NOT on this page" in rendered

    def test_a_page_nothing_covers_says_so_rather_than_showing_nothing(self, part_dir):
        candidate = suggest_candidates(part_dir, n=3).candidates[0]
        candidate = candidate.model_copy(update={"page": 999})
        context = page_context(part_dir, candidate)
        assert not context.available
        assert "no corpus section covers p.999" in context.warning


class TestTheInteractiveShellIsThinAndDrivenThroughItsSeam:
    def test_one_keystroke_per_candidate_becomes_a_decision(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        answers = iter(["a", "r", "because the page is wrong", "s"])
        written: list[str] = []
        decisions = run_interactive(
            candidates,
            part_dir=part_dir,
            read=lambda _prompt="": next(answers),
            write=written.append,
        )
        ids = [c.question.id for c in candidates.candidates]
        assert [(d.id, d.action) for d in decisions] == [
            (ids[0], ACCEPT),
            (ids[1], REJECT),
        ]
        assert decisions[1].reason == "because the page is wrong"
        assert any(ids[2] in line for line in written)

    def test_quitting_leaves_the_rest_undecided(self, part_dir):
        candidates = suggest_candidates(part_dir, n=3)
        answers = iter(["a", "q"])
        decisions = run_interactive(
            candidates,
            part_dir=part_dir,
            read=lambda _prompt="": next(answers),
            write=lambda _line: None,
        )
        assert len(decisions) == 1
        outcome = apply_decisions(candidates, decisions)
        assert len(outcome.deferred) == 2


# --- a part with no corpus ---------------------------------------------------


class TestAPartWithNoBuiltCorpus:
    def test_suggest_errors_rather_than_generating_answerless_questions(self, tmp_path):
        with pytest.raises(GoldenAssistError, match="dsa build"):
            suggest_candidates(tmp_path / "parts" / "NOSUCH", n=5)

    def test_the_cli_says_which_command_fixes_it(self, settings, monkeypatch, capsys):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        code = cli.main(["golden", "suggest", "--part", "NOSUCH"])
        err = capsys.readouterr().err
        assert code == 2
        assert "no corpus" in err and "dsa build" in err

    def test_confirm_without_candidates_says_to_generate_them(
        self, settings, golden, monkeypatch, capsys
    ):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        code = cli.main(
            ["golden", "confirm", "--part", "TEST", "--golden", str(golden),
             "--accept-ids", "anything"]
        )
        assert code == 2
        assert "dsa golden suggest" in capsys.readouterr().err


# --- the command surface -----------------------------------------------------


class TestTheCommand:
    def test_suggest_writes_the_file_and_reports_the_mix(
        self, settings, golden, monkeypatch, capsys
    ):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        code = cli.main(
            ["golden", "suggest", "--part", "TEST", "--n", "6", "--golden", str(golden)]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert candidate_path(golden).exists()
        assert "6 candidate(s)" in out
        for dimension in STRATA_DIMENSIONS:
            assert f"| {dimension} |" in out

    def test_confirm_merges_records_and_rewrites_the_candidate_file(
        self, settings, golden, monkeypatch, capsys
    ):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "4", "--golden", str(golden)])
        capsys.readouterr()
        ids = [c.question.id for c in read_candidates(candidate_path(golden)).candidates]

        code = cli.main(
            [
                "golden", "confirm", "--part", "TEST", "--golden", str(golden),
                "--accept-ids", ids[0],
                "--reject-ids", ids[1],
                "--reject-reason", "the address cell is a range",
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "1 accepted" in out
        assert ids[0] in {q.id for q in load_golden(golden)}
        ledger = read_rejections(rejected_path(golden))
        assert [entry.id for entry in ledger.rejected] == [ids[1]]
        assert ledger.rejected[0].reason == "the address cell is a range"
        left = read_candidates(candidate_path(golden))
        assert [c.question.id for c in left.candidates] == ids[2:]
        assert sum(left.strata["artifact"].values()) == len(left.candidates)

    def test_the_command_round_trip_never_re_suggests_a_rejection(
        self, settings, golden, monkeypatch, capsys
    ):
        """suggest -> reject -> suggest again, through the CLI, end to end.

        The exclusion is unit-tested above; this proves the command actually
        reads the ledger it wrote, which is the half a wiring mistake breaks.
        """
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "4", "--golden", str(golden)])
        first = read_candidates(candidate_path(golden)).candidates
        victim = first[0].question.id
        cli.main(
            ["golden", "confirm", "--part", "TEST", "--golden", str(golden),
             "--reject-ids", victim, "--reject-reason", "the page cite is wrong"]
        )
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "4", "--golden", str(golden)])
        out = capsys.readouterr().out
        second = read_candidates(candidate_path(golden))
        assert victim not in {c.question.id for c in second.candidates}
        assert second.skipped_rejected == 1
        assert "1 previously rejected" in out

    def test_a_dry_run_writes_nothing(self, settings, golden, monkeypatch, capsys):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "3", "--golden", str(golden)])
        capsys.readouterr()
        before_golden = golden.read_text(encoding="utf-8")
        before_candidates = candidate_path(golden).read_text(encoding="utf-8")
        one = read_candidates(candidate_path(golden)).candidates[0].question.id

        code = cli.main(
            ["golden", "confirm", "--part", "TEST", "--golden", str(golden),
             "--accept-ids", one, "--dry-run"]
        )
        assert code == 0
        assert "--dry-run" in capsys.readouterr().out
        assert golden.read_text(encoding="utf-8") == before_golden
        assert candidate_path(golden).read_text(encoding="utf-8") == before_candidates
        assert not rejected_path(golden).exists()

    def test_confirm_refuses_to_run_blind_without_a_terminal(
        self, settings, golden, monkeypatch, capsys
    ):
        """No decisions and nobody to ask is a refusal, never a silent accept."""
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        monkeypatch.setattr("sys.stdin", io.StringIO())
        cli.main(["golden", "suggest", "--part", "TEST", "--n", "3", "--golden", str(golden)])
        capsys.readouterr()
        code = cli.main(["golden", "confirm", "--part", "TEST", "--golden", str(golden)])
        assert code == 2
        assert "--accept-ids" in capsys.readouterr().err

    def test_suggest_json_is_the_candidate_set(self, settings, golden, monkeypatch, capsys):
        import json

        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        cli.main(
            ["golden", "suggest", "--part", "TEST", "--n", "3", "--golden", str(golden),
             "--json"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["part"] == "TEST"
        assert len(payload["candidates"]) == 3
        assert all(row["confirmed"] is False for row in payload["candidates"])


# --- invariant 8 -------------------------------------------------------------


class TestNoModelCallInTheGenerationPath:
    def test_the_modules_import_nothing_that_could_call_a_model(self):
        for name in ("candidates.py", "suggest.py", "confirm.py"):
            source = (SRC / "evalh" / name).read_text(encoding="utf-8")
            for token in ("anthropic", "LLMClient", "enrich."):
                assert token not in source, f"{name} references {token}"

    def test_two_runs_over_one_corpus_produce_identical_bytes(self, part_dir, tmp_path):
        first = write_candidates(
            tmp_path / "a.candidate.yaml", suggest_candidates(part_dir, n=8)
        ).read_text(encoding="utf-8")
        clear_index_cache()
        second = write_candidates(
            tmp_path / "b.candidate.yaml", suggest_candidates(part_dir, n=8)
        ).read_text(encoding="utf-8")
        assert first.replace("a.candidate", "b.candidate") == second.replace(
            "a.candidate", "b.candidate"
        )

    def test_nothing_written_carries_a_timestamp(self, part_dir, tmp_path):
        """A generated file that dated itself would differ on every run and
        could never be diffed against the corpus it describes."""
        text = write_candidates(
            tmp_path / "c.candidate.yaml", suggest_candidates(part_dir, n=8)
        ).read_text(encoding="utf-8")
        assert "generated_at" not in text
