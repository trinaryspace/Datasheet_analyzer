"""Answer packs — `dsa ask` (Phase 5, ticket 05).

What these prove:

- one call returns a complete, cited payload: the `TJ` record with `§4.3, p.6`
  and its confidence grade, for a question phrased in a designer's words;
- routing is **deterministic and named**: each of the three routes (spec /
  plot / search) is exercised by a test that asserts which one fired, and no
  LLM is anywhere in the path;
- the budget is a hard limit, enforced over the rendered payload;
- **citations are never what a budget removes** — asserted with a deliberately
  tiny budget, and again with a budget below the pack's own citation floor;
- truncation is always announced, and the notice names `--budget`;
- a no-match says so and offers nearest candidates: it never degrades into a
  full-text dump or a guess;
- `--json` validates against the *declared* schema (`ANSWER_PACK_SCHEMA`,
  which ticket 07's MCP tool reuses), and the validator itself bites.

The measured proof over real corpora — every golden question of every gate
part, asked in natural language, at or under budget — lives in
`tests/integration/test_phase4_layout_gate.py::TestAnswerPacks` and
`tests/integration/test_afe7950_build.py::TestAnswerPacksOnTheRealCorpus`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.models import (
    Confidence,
    DocType,
    PlotRecord,
    PlotSet,
    RawDocument,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.publish import write_corpus
from datasheet_analyzer.retrieve import (
    ANSWER_PACK_SCHEMA,
    ROUTE_NONE,
    ROUTE_PLOT,
    ROUTE_SEARCH,
    ROUTE_SPEC,
    ROUTE_UNAVAILABLE,
    Retriever,
    validate_pack,
)
from datasheet_analyzer.retrieve.pack import PLOT_VOCABULARY
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.tokens import count_tokens

DOC_HASH = "a1b2c3d4" + "0" * 56
DOC = f"datasheet-{DOC_HASH[:8]}"


def _sections() -> list[SectionNode]:
    return [
        SectionNode(
            number="4.3",
            title="Recommended Operating Conditions",
            page_start=6,
            page_end=6,
            paragraphs=[
                (
                    "Operating junction temperature TJ ranges from -40 to 105 °C. "
                    "The 1.2 V rails accept 1.15 V minimum."
                ),
                (
                    "Exceeding the recommended operating conditions degrades "
                    "reliability long before an absolute maximum is reached."
                ),
            ],
        ),
        SectionNode(
            number="4.5",
            title="Transmitter Electrical Characteristics",
            page_start=7,
            page_end=8,
            paragraphs=[
                (
                    "SYSREF setup time must be met for deterministic latency. "
                    "The SYSREF capture window is programmable per converter."
                ),
                "The transmit DAC resolution is 14 bits across every channel.",
            ],
        ),
        SectionNode(
            number="4.12.1",
            title="TX Typical Characteristics",
            page_start=29,
            page_end=37,
            paragraphs=[
                "Typical transmitter characteristics measured at 800 MHz.",
            ],
        ),
    ]


def _specs() -> SpecSet:
    return SpecSet(
        schema_version="2",
        part_number="TEST",
        doc_hash=DOC_HASH,
        records=[
            SpecRecord(
                section="4.3",
                table_index=0,
                row_index=0,
                symbol="TJ",
                name="Operating junction temperature",
                max="105",
                unit=SpecUnit(verbatim="°C", canonical="°C"),
                page=6,
                confidence=Confidence.HIGH,
            ),
            SpecRecord(
                section="4.3",
                table_index=0,
                row_index=1,
                symbol="VDD1P2",
                name="1.2V supply",
                min="1.15",
                typ="1.2",
                unit=SpecUnit(verbatim="V", canonical="V"),
                page=6,
                confidence=Confidence.MEDIUM,
            ),
            SpecRecord(
                section="4.3",
                table_index=0,
                row_index=2,
                symbol="VDD1P8",
                name="1.8V supply",
                min="1.75",
                typ="1.8",
                unit=SpecUnit(verbatim="V", canonical="V"),
                page=6,
                confidence=Confidence.MEDIUM,
            ),
            SpecRecord(
                section="4.3",
                table_index=0,
                row_index=3,
                symbol="VDD3P3",
                name="3.3V supply",
                min="3.15",
                typ="3.3",
                unit=SpecUnit(verbatim="V", canonical="V"),
                page=6,
                confidence=Confidence.MEDIUM,
            ),
            SpecRecord(
                section="4.5",
                table_index=0,
                row_index=0,
                symbol="DACRES",
                name="DAC resolution",
                typ="14",
                unit=SpecUnit(verbatim="bits", canonical="bits"),
                page=7,
                confidence=Confidence.LOW,
            ),
        ],
    )


def _plots() -> PlotSet:
    return PlotSet(
        schema_version="2",
        part_number="TEST",
        doc_hash=DOC_HASH,
        plots=[
            PlotRecord(
                id="4.12.1-f001",
                section="4.12.1",
                caption="Figure 4-1 TX Output Fullscale vs Output Frequency",
                conditions="DSA = 0",
                page_start=29,
                page_end=29,
                file=f"docs/{DOC}/figures/4.12.1-f001.png",
                tags=["tx", "fullscale"],
                confidence=Confidence.HIGH,
            ),
            PlotRecord(
                id="4.12.1-f002",
                section="4.12.1",
                caption="Figure 4-2 TX Calibrated Gain Error vs DSA Setting",
                page_start=30,
                page_end=30,
                tags=["tx"],
                confidence=Confidence.MEDIUM,
            ),
        ],
    )


def _build_part(part_dir: Path, sections: list[SectionNode] | None = None) -> Path:
    source = SourceDocument(
        content_hash=DOC_HASH,
        path="pdfs/afe7950.pdf",
        part_number=part_dir.name,
        doc_type=DocType.DATASHEET,
        revision="SBASA41E",
        page_count=146,
    )
    raw = RawDocument(
        source=source,
        sections=_sections() if sections is None else sections,
        extractor="ti_html",
        extractor_version="test-1",
    )
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        "# INDEX\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        specsets=[_specs()],
        plotsets=[_plots()],
    )
    return part_dir


@pytest.fixture
def part(tmp_path: Path) -> Path:
    return _build_part(tmp_path / "parts" / "TEST")


@pytest.fixture
def retriever(part) -> Retriever:
    return Retriever.for_part(part)


class TestTheHeadlineQuestion:
    """The ticket's own example, on a corpus shaped like the real one."""

    def test_max_junction_temperature_returns_tj_cited_and_graded(self, retriever):
        pack = retriever.ask("max junction temperature", budget=3000)
        assert pack.route == ROUTE_SPEC
        answer = pack.answers[0]
        assert answer.text.startswith("TJ  Operating junction temperature")
        assert "105 °C (max)" in answer.text
        assert answer.citation == "§4.3, p.6"
        assert answer.confidence == "high"
        # the whole payload carries it too, so an agent that reads only the
        # markdown still sees the citation and the grade
        assert "§4.3, p.6" in pack.markdown
        assert "[high]" in pack.markdown

    def test_the_verify_footer_names_the_printed_page_and_the_grade(self, retriever):
        pack = retriever.ask("max junction temperature", budget=3000)
        assert pack.verify == "Printed page 6 of afe7950.pdf.  Confidence: high."
        assert "### Verify" in pack.markdown

    def test_a_low_grade_tells_the_reader_to_open_the_page(self, retriever):
        pack = retriever.ask("dac resolution", budget=3000)
        assert pack.answers[0].confidence == "low"
        assert "Open the printed page before relying on this value." in pack.verify

    def test_the_supporting_excerpt_is_verbatim_corpus_text_with_its_own_cite(
        self, retriever, part
    ):
        pack = retriever.ask("max junction temperature", budget=3000)
        assert pack.excerpt is not None
        assert pack.excerpt.heading == "§4.3 Recommended Operating Conditions"
        assert pack.excerpt.citation == "§4.3, p.6"
        section = next(s for s in retriever.index.sections if s.number == "4.3")
        body = (part / section.file).read_text(encoding="utf-8")
        probe = pack.excerpt.text.strip("…").split(" ")[1:6]
        assert " ".join(probe) in " ".join(body.split())

    def test_the_excerpt_is_the_tightest_section_not_the_parent_stub(self, tmp_path):
        """A printed page is covered by a whole chain of sections.

        Real corpora carry `4 Specifications` spanning a hundred pages with no
        body of its own; quoting that instead of `4.3` would spend the whole
        excerpt budget on nothing.
        """
        nested = [
            SectionNode(
                number="4",
                title="Specifications",
                page_start=6,
                page_end=37,
                paragraphs=["See the subsections that follow."],
            ),
            *_sections(),
        ]
        part = _build_part(tmp_path / "parts" / "NESTED", sections=nested)
        pack = Retriever.for_part(part).ask("max junction temperature", budget=3000)
        assert pack.excerpt is not None
        assert pack.excerpt.heading == "§4.3 Recommended Operating Conditions"
        assert "See the subsections that follow" not in pack.excerpt.text

    def test_the_header_names_part_revision_and_document(self, retriever):
        pack = retriever.ask("max junction temperature", budget=3000)
        assert pack.header == f"## TEST — SBASA41E ({DOC})"


class TestRoutingIsDeterministic:
    """Each route is exercised by a test that asserts which one fired."""

    def test_spec_route_fires_on_an_alias_hit(self, retriever):
        pack = retriever.ask("what is the maximum junction temperature?", budget=3000)
        assert pack.route == ROUTE_SPEC
        assert pack.answers[0].text.startswith("TJ")

    def test_plot_route_fires_on_plot_vocabulary_plus_a_matching_figure(self, retriever):
        pack = retriever.ask(
            "which figure shows TX output fullscale vs output frequency?", budget=3000
        )
        assert pack.route == ROUTE_PLOT
        assert pack.answers[0].text.startswith("Figure 4-1 TX Output Fullscale")
        assert pack.answers[0].citation == "§4.12.1, p.29"
        assert pack.answers[0].file.endswith("4.12.1-f001.png")

    def test_search_route_fires_when_no_record_answers(self, retriever):
        pack = retriever.ask("sysref capture window", budget=3000)
        assert pack.route == ROUTE_SEARCH
        assert pack.answers[0].citation == "§4.5, p.7-8"
        assert "SYSREF capture window" in (pack.excerpt.text if pack.excerpt else "")

    def test_a_figure_question_beats_an_alias_hit_on_the_same_words(self, retriever):
        """ "gain error" is an alias phrase; a question naming a figure is
        still a figure question. The override only applies when a figure was
        actually found, so it can never cost an answer that exists."""
        pack = retriever.ask("which figure shows the gain error vs DSA setting?", budget=3000)
        assert pack.route == ROUTE_PLOT
        assert "Gain Error" in pack.answers[0].text

    def test_plot_vocabulary_without_a_matching_figure_keeps_the_spec_answer(self, retriever):
        pack = retriever.ask("plot the maximum junction temperature for me", budget=3000)
        assert pack.route == ROUTE_SPEC
        assert pack.answers[0].text.startswith("TJ")

    def test_the_router_and_the_ranker_share_one_plot_vocabulary(self):
        for word in ("plot", "curve", "vs", "vs.", "versus", "graph", "figure", "diagram"):
            assert PLOT_VOCABULARY.search(f"which {word} shows this")

    def test_no_llm_is_reachable_from_the_ask_path(self):
        """Routing is by feature hits only — the plan's hard boundary."""
        source = Path(
            __import__("datasheet_analyzer.retrieve.pack", fromlist=["x"]).__file__
        ).read_text(encoding="utf-8")
        for token in ("anthropic", "LLMClient", "enrich"):
            assert token not in source

    def test_rows_are_ordered_by_the_questions_own_words(self, retriever):
        """A rung that returns a family still has to pick the row asked for.

        `supply voltage` is an alias phrase covering the whole VDD family, so
        the rung hands back three rows in the table's own order — VDD1P2
        first. Only the question's own words separate them, and that is the
        entire job of the pack's relevance ordering: remove it and this
        answers VDD1P2 to a question that names 1.8 V.
        """
        ladder = [h.record.symbol for h in retriever.specs(name="supply voltage")]
        assert ladder[:3] == ["VDD1P2", "VDD1P8", "VDD3P3"], (
            "the fixture must offer a family for the ordering to act on"
        )
        pack = retriever.ask("what is the 1.8V supply voltage minimum?", budget=3000)
        assert pack.route == ROUTE_SPEC
        assert [line.text.split()[0] for line in pack.answers][:3] == [
            "VDD1P8",
            "VDD1P2",
            "VDD3P3",
        ]


class TestBudgetIsHard:
    def test_pack_is_at_or_under_budget(self, retriever):
        for budget in (100, 150, 300, 1000, 4000):
            pack = retriever.ask("max junction temperature", budget=budget)
            assert pack.tokens <= budget, (budget, pack.markdown)
            assert count_tokens(pack.markdown) == pack.tokens

    def test_the_default_budget_comes_from_settings(self, retriever, monkeypatch):
        monkeypatch.setattr(
            "datasheet_analyzer.retrieve.pack.get_settings",
            lambda: Settings(ask_budget=777),
        )
        assert retriever.ask("max junction temperature").budget == 777

    def test_a_tiny_budget_never_truncates_the_citation(self, retriever):
        """Criterion: citations are never the truncated part."""
        full = retriever.ask("max junction temperature", budget=4000)
        tiny = retriever.ask("max junction temperature", budget=90)
        assert tiny.tokens <= 90 < full.tokens
        assert tiny.truncated and not full.truncated
        assert tiny.citations[0] == full.citations[0] == "§4.3, p.6"
        assert "§4.3, p.6" in tiny.markdown
        assert "Printed page 6 of afe7950.pdf" in tiny.markdown
        # what went is the discretionary prose, not the evidence
        assert tiny.excerpt is None or len(tiny.excerpt.text) < len(full.excerpt.text)

    def test_truncation_notice_names_the_flag_that_would_raise_the_budget(self, retriever):
        pack = retriever.ask("max junction temperature", budget=90)
        assert pack.truncated
        assert "--budget" in pack.notice and "DSA_ASK_BUDGET" in pack.notice
        assert pack.notice in pack.markdown

    def test_an_untruncated_pack_says_nothing_about_truncation(self, retriever):
        pack = retriever.ask("max junction temperature", budget=4000)
        assert not pack.truncated and pack.notice == ""
        assert "Truncated" not in pack.markdown

    def test_a_budget_below_the_citation_floor_keeps_the_citation_and_says_so(self, retriever):
        pack = retriever.ask("max junction temperature", budget=20)
        assert pack.over_budget
        assert "§4.3, p.6" in pack.markdown, "the citation survives any budget"
        assert "citation floor" in pack.notice
        assert "--budget" in pack.notice

    def test_extra_rows_are_dropped_before_the_first_one_is(self, retriever):
        """Greedy fill in retrieval order over a reserved first row.

        The budget is tightened until a row genuinely goes, so the drop is
        observed rather than assumed: a fill that kept everything would fail
        the strict `<` below.
        """
        wide = retriever.ask("supply voltage", budget=4000)
        narrow = retriever.ask("supply voltage", budget=80)
        assert len(wide.answers) >= 3, "the VDD family must answer as a family"
        assert len(narrow.answers) >= 1
        assert len(narrow.answers) < len(wide.answers), "no row was actually dropped"
        assert narrow.answers[0] == wide.answers[0]
        assert narrow.truncated and "--budget" in narrow.notice

    def test_every_answer_line_carries_its_own_citation(self, retriever):
        pack = retriever.ask("max junction temperature", budget=4000)
        assert pack.answers
        assert all(line.citation for line in pack.answers)
        assert len(pack.citations) >= len(pack.answers)


class TestNoMatchIsExplicit:
    def test_a_no_match_says_so_and_offers_nearest_candidates(self, retriever):
        pack = retriever.ask("flux capacitor rating", budget=3000)
        assert pack.route == ROUTE_NONE
        assert "No spec record, figure or section in this corpus answers" in pack.markdown
        assert "Nothing was guessed." in pack.markdown
        assert pack.suggestions, "a no-match must still offer nearer terms"
        assert "### Nearest candidates" in pack.markdown

    def test_a_no_match_never_degrades_into_a_full_text_dump(self, retriever):
        pack = retriever.ask("flux capacitor rating", budget=3000)
        assert pack.excerpt is None
        assert pack.tokens < 200, "a no-match is cheap, not a corpus dump"

    def test_a_no_match_exits_the_verify_footer_honestly(self, retriever):
        pack = retriever.ask("flux capacitor rating", budget=3000)
        assert "explicit no-match" in pack.verify

    def test_an_empty_question_is_a_no_match_not_everything(self, retriever):
        pack = retriever.ask("   ", budget=3000)
        assert pack.route == ROUTE_NONE
        assert pack.suggestions == ()


class TestAnUnsearchableCorpusIsNotAnEmptyOne:
    """A corpus with no current full-text index is degraded, not empty.

    `Retriever.search()` returns `[]` both for "nothing matched" and for
    "there was nothing to match against"; only the first licenses a no-match.
    Reading the second as absence would turn a missing `search_index.json`
    into a claim about the datasheet — the misreading the retriever's own
    docstring warns about, and the one the honest-degradation convention
    forbids. The committed reference corpora are exactly in that state.
    """

    @pytest.fixture
    def unsearchable(self, part) -> Path:
        for index in part.glob("docs/*/search_index.json"):
            index.unlink()
        return part

    def test_the_pack_says_the_path_could_not_run_instead_of_no_match(self, unsearchable):
        pack = Retriever.for_part(unsearchable).ask("sysref capture window", budget=3000)
        assert pack.route == ROUTE_UNAVAILABLE
        assert "No spec record, figure or section in this corpus answers" not in (pack.markdown), (
            "an unsearchable corpus must never assert absence"
        )
        assert "the full-text path could not run" in pack.markdown
        assert "Rebuild to enable search" in pack.markdown
        assert "### Search unavailable" in pack.markdown

    def test_the_verify_footer_does_not_rule_the_answer_out(self, unsearchable):
        pack = Retriever.for_part(unsearchable).ask("sysref capture window", budget=3000)
        assert "never ran" in pack.verify
        assert "Rebuild" in pack.verify

    def test_it_still_offers_nearest_candidates_and_stays_cheap(self, unsearchable):
        pack = Retriever.for_part(unsearchable).ask("sysref capture window", budget=3000)
        assert pack.suggestions
        assert pack.excerpt is None
        assert pack.tokens < 300, "a degraded answer is not a corpus dump"

    def test_the_record_paths_still_answer_without_an_index(self, unsearchable):
        """The degradation is scoped to the path that is missing."""
        pack = Retriever.for_part(unsearchable).ask("max junction temperature", budget=3000)
        assert pack.route == ROUTE_SPEC
        assert pack.answers[0].citation == "§4.3, p.6"

    def test_a_searchable_corpus_still_reports_a_true_no_match(self, retriever):
        """The check must not swallow the honest no-match it guards."""
        pack = retriever.ask("flux capacitor rating", budget=3000)
        assert pack.route == ROUTE_NONE

    def test_the_declared_schema_admits_the_route(self, unsearchable):
        payload = Retriever.for_part(unsearchable).ask("sysref capture window").as_dict()
        assert payload["route"] == ROUTE_UNAVAILABLE
        assert validate_pack(payload) == []


class TestDeclaredJsonShape:
    def test_a_pack_validates_against_the_declared_schema(self, retriever):
        for question in (
            "max junction temperature",
            "which figure shows TX output fullscale vs output frequency?",
            "sysref capture window",
            "flux capacitor rating",
        ):
            payload = retriever.ask(question, budget=3000).as_dict()
            assert validate_pack(payload) == [], question

    def test_the_schema_declares_every_key_the_pack_emits(self, retriever):
        payload = retriever.ask("max junction temperature", budget=3000).as_dict()
        assert set(payload) == set(ANSWER_PACK_SCHEMA["properties"])
        assert set(ANSWER_PACK_SCHEMA["required"]) == set(payload)

    @pytest.mark.parametrize(
        ("mutate", "expected"),
        [
            (lambda p: p.pop("citations"), "required key missing"),
            (lambda p: p.update(route="vibes"), "is not one of"),
            (lambda p: p.update(tokens="lots"), "expected integer"),
            (lambda p: p.update(over_budget="yes"), "expected boolean"),
            (lambda p: p.update(extra=1), "unexpected key"),
            (lambda p: p["answers"][0].update(confidence="probably"), "is not one of"),
            (lambda p: p.update(excerpt=[]), "matches none of the allowed shapes"),
        ],
    )
    def test_the_validator_bites(self, retriever, mutate, expected):
        payload = retriever.ask("max junction temperature", budget=3000).as_dict()
        mutate(payload)
        errors = validate_pack(payload)
        assert errors and any(expected in e for e in errors), errors

    def test_a_boolean_is_not_accepted_where_an_integer_is_declared(self, retriever):
        payload = retriever.ask("max junction temperature", budget=3000).as_dict()
        payload["budget"] = True
        assert validate_pack(payload)

    def test_the_declaration_is_real_json_schema(self, retriever):
        """Cross-check against the reference implementation when it is
        installed; the dependency-free validator above is the contract."""
        jsonschema = pytest.importorskip("jsonschema")
        payload = retriever.ask("max junction temperature", budget=3000).as_dict()
        jsonschema.validate(payload, ANSWER_PACK_SCHEMA)

    def test_null_excerpt_is_declared_and_accepted(self, retriever):
        payload = retriever.ask("flux capacitor rating", budget=3000).as_dict()
        assert payload["excerpt"] is None
        assert validate_pack(payload) == []


class TestAskCli:
    @pytest.fixture
    def wired(self, part, monkeypatch) -> Path:
        settings = Settings(parts_dir=part.parent, cache_dir=part.parent / ".cache").resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        return part

    def test_ask_prints_the_pack_with_its_citation(self, wired, capsys):
        assert cli.main(["ask", "--part", "TEST", "max junction temperature"]) == 0
        out = capsys.readouterr().out
        assert "### Answer" in out
        assert "§4.3, p.6" in out
        assert "[high]" in out
        assert "### Verify" in out

    def test_budget_flag_is_honoured(self, wired, capsys):
        assert (
            cli.main(["ask", "--part", "TEST", "max junction temperature", "--budget", "90"]) == 0
        )
        out = capsys.readouterr().out
        assert count_tokens(out.strip()) <= 90
        assert "§4.3, p.6" in out
        assert "--budget" in out

    def test_json_emits_the_declared_shape(self, wired, capsys):
        assert cli.main(["ask", "--part", "TEST", "max junction temperature", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert validate_pack(payload) == []
        assert payload["route"] == "spec"
        assert payload["citations"][0] == "§4.3, p.6"

    def test_no_match_exits_1_without_pretending(self, wired, capsys):
        assert cli.main(["ask", "--part", "TEST", "flux capacitor rating"]) == 1
        assert "No spec record, figure or section" in capsys.readouterr().out

    def test_an_unsearchable_corpus_exits_2_like_dsa_search(self, wired, capsys):
        for index in wired.glob("docs/*/search_index.json"):
            index.unlink()
        assert cli.main(["ask", "--part", "TEST", "sysref capture window"]) == 2
        out = capsys.readouterr().out
        assert "Rebuild to enable search" in out
        assert "No spec record, figure or section" not in out

    def test_unbuilt_part_exits_2(self, wired, capsys):
        assert cli.main(["ask", "--part", "NOPE", "anything"]) == 2
        assert "run `dsa build` first" in capsys.readouterr().err
