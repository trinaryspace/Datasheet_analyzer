"""Projects — the noun above `part` (Phase 5, ticket 06).

What these prove, criterion by criterion:

- `new` → `add` → `build` produces a `PROJECT_INDEX.md` inside its token
  budget, listing every member with its revision and a pointer to its own
  `INDEX.md`;
- the budget is **hard**: an oversized project drops its least-important
  content first, says so, and never drops a part or an index pointer — the
  same rule the answer pack applies to citations;
- `ask --project` labels every answer with the part it came from, and a
  question two parts answer returns **both**;
- adding a part with no corpus fails naming the build command, and leaves
  neither `project.json` nor the index half-written;
- removing a part and rebuilding leaves no stale entry;
- `dsa status` lists projects alongside parts;
- `query` / `search` / `plots --project` fan out and label their hits.

The measured 3-part project built from the real gate corpora, with its index
token count recorded for the phase report, lives in
`tests/integration/test_phase4_layout_gate.py::TestProjectIndexEconomics`.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.models import (
    Confidence,
    DocType,
    PlotRecord,
    PlotSet,
    Project,
    ProjectMember,
    RawDocument,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.projects import (
    ProjectError,
    add_parts,
    build_project_index_markdown,
    list_projects,
    load_project,
    new_project,
    remove_parts,
    save_project,
    summarize_project,
    write_project_index,
)
from datasheet_analyzer.publish import write_corpus
from datasheet_analyzer.retrieve import (
    ROUTE_NONE,
    ROUTE_SPEC,
    ROUTE_UNAVAILABLE,
    ProjectRetriever,
    validate_pack,
)
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.tokens import count_tokens

# Three parts of one imaginary board. Each prints a supply-voltage family (so
# one project-wide question genuinely hits several parts) and one quantity
# only it has (so a per-part answer is distinguishable).
BOARD = {
    "TRX9000": ("SBASA41E", "1.8", "transceiver"),
    "AMP4400": ("Rev. A", "3.3", "driver amplifier"),
    "CLK2200": ("Rev. I", "2.5", "clock source"),
}


def _doc_hash(part: str) -> str:
    return (part.lower() + "0" * 64)[:64]


def _sections(part: str) -> list[SectionNode]:
    return [
        SectionNode(
            number="4.3",
            title="Recommended Operating Conditions",
            page_start=6,
            page_end=6,
            paragraphs=[
                (
                    f"The {part} supply rails are specified here. Exceeding them "
                    "degrades reliability long before an absolute maximum is reached."
                )
            ],
        ),
        SectionNode(
            number="4.9",
            title="Thermal Information",
            page_start=11,
            page_end=12,
            paragraphs=[
                (
                    f"{part} thermal pad soldering is required for the stated "
                    "junction-to-ambient resistance."
                )
            ],
        ),
    ]


def _specs(part: str, rail: str) -> SpecSet:
    return SpecSet(
        schema_version="2",
        part_number=part,
        doc_hash=_doc_hash(part),
        records=[
            SpecRecord(
                section="4.3",
                table_index=0,
                row_index=0,
                symbol=f"VDD{rail.replace('.', 'P')}",
                name=f"{rail}V supply",
                min=rail,
                unit=SpecUnit(verbatim="V", canonical="V"),
                page=6,
                confidence=Confidence.HIGH,
            ),
            SpecRecord(
                section="4.9",
                table_index=0,
                row_index=0,
                symbol=f"{part}RJA",
                name=f"{part} junction-to-ambient thermal resistance",
                typ="21.4",
                unit=SpecUnit(verbatim="°C/W", canonical="°C/W"),
                page=11,
                confidence=Confidence.MEDIUM,
            ),
        ],
    )


def _plots(part: str) -> PlotSet:
    return PlotSet(
        schema_version="2",
        part_number=part,
        doc_hash=_doc_hash(part),
        plots=[
            PlotRecord(
                id="4.9-f001",
                section="4.9",
                caption=f"Figure 1. {part} Thermal Derating vs Ambient Temperature",
                page_start=11,
                page_end=11,
                tags=["thermal"],
                confidence=Confidence.MEDIUM,
            )
        ],
    )


def _build_corpus(parts_dir: Path, part: str) -> Path:
    revision, rail, _role = BOARD[part]
    source = SourceDocument(
        content_hash=_doc_hash(part),
        path=f"pdfs/{part.lower()}.pdf",
        part_number=part,
        doc_type=DocType.DATASHEET,
        revision=revision,
        page_count=42,
    )
    raw = RawDocument(
        source=source,
        sections=_sections(part),
        extractor="ti_html",
        extractor_version="test-1",
    )
    part_dir = parts_dir / part
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        f"# {part} — datasheet corpus\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        specsets=[_specs(part, rail)],
        plotsets=[_plots(part)],
    )
    return part_dir


@pytest.fixture
def board(tmp_path: Path) -> Path:
    """Three built corpora under one `parts/` directory."""
    parts_dir = tmp_path / "parts"
    for part in BOARD:
        _build_corpus(parts_dir, part)
    return parts_dir


@pytest.fixture
def settings(tmp_path: Path, board: Path) -> Settings:
    return Settings(
        parts_dir=board,
        projects_dir=tmp_path / "projects",
        cache_dir=tmp_path / ".cache",
    ).resolve()


@pytest.fixture
def wired(settings: Settings, monkeypatch) -> Settings:
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    return settings


@pytest.fixture
def project(settings: Settings) -> Project:
    """`rf-frontend` with all three parts, saved but not yet built."""
    project = new_project(
        "rf-frontend",
        settings.projects_dir,
        interfaces="TRX9000 TX out -> AMP4400 in; CLK2200 drives both SYSREF inputs.",
        notes="Prototype board revision B.",
    )
    for part, (_rev, _rail, role) in BOARD.items():
        add_parts(project, [part], parts_dir=settings.parts_dir, role=role)
    save_project(project, settings.projects_dir)
    return project


def _scope(project: Project, settings: Settings) -> ProjectRetriever:
    from datasheet_analyzer.projects import part_dirs

    return ProjectRetriever.for_parts(project.name, part_dirs(project, settings.parts_dir))


class TestTheProjectIndexIsBuiltAndBounded:
    """Criteria 1 and 2: it builds, and the budget is hard."""

    def test_new_add_build_produces_an_index_within_budget(self, project, settings):
        path, text = write_project_index(
            project,
            parts_dir=settings.parts_dir,
            projects_dir=settings.projects_dir,
            token_budget=settings.project_index_token_budget,
        )
        assert path.name == "PROJECT_INDEX.md"
        assert path.read_text(encoding="utf-8") == text
        assert count_tokens(text) <= settings.project_index_token_budget
        for part, (revision, _rail, role) in BOARD.items():
            assert part in text
            assert revision in text, f"{part}: the printed revision must be on the page"
            assert role in text, f"{part}: the designer's one-line role must survive"
        assert text.count("INDEX.md") >= len(BOARD), "each part points at its own index"
        assert "TRX9000 TX out" in text, "the interfaces note is the designer's"

    def test_the_pointer_resolves_to_the_parts_real_index(self, project, settings):
        path, _text = write_project_index(
            project,
            parts_dir=settings.parts_dir,
            projects_dir=settings.projects_dir,
            token_budget=4000,
        )
        members = summarize_project(project, settings.parts_dir, relative_to=path.parent)
        for member in members:
            target = (path.parent / member.index_path).resolve()
            assert target.exists(), f"{member.part_number}: {member.index_path}"
            assert target.name == "INDEX.md"

    def test_an_oversized_project_drops_the_least_important_first(self, project, settings):
        members = summarize_project(project, settings.parts_dir)
        full = build_project_index_markdown(project, members, token_budget=4000)
        assert "How to use this project" in full and "Prototype board" in full

        squeezed = build_project_index_markdown(project, members, token_budget=180)
        assert count_tokens(squeezed) <= 180
        assert "How to use this project" not in squeezed, "conventions go first"
        assert "Truncated to fit" in squeezed, "a drop is always announced"
        # the product survives every stage
        for part in BOARD:
            assert part in squeezed
        assert squeezed.count("INDEX.md") >= len(BOARD)

    def test_the_stages_degrade_in_the_documented_order(self, project, settings):
        members = summarize_project(project, settings.parts_dir)
        seen: list[str] = []
        for budget in (4000, 220, 190, 170, 150, 120):
            text = build_project_index_markdown(project, members, token_budget=budget)
            seen.append(text)
            # Under the last stage the part list itself is the floor; that case
            # goes over budget and says so rather than dropping a part.
            assert count_tokens(text) <= budget or "below this project's part list" in text, budget
        # each step is a subset of the one before it in the blocks it carries
        blocks = [
            "How to use this project",
            "Prototype board",  # notes
            "TRX9000 TX out",  # interfaces
        ]
        kept = [[b for b in blocks if b in text] for text in seen]
        for earlier, later in pairwise(kept):
            assert set(later) <= set(earlier), (earlier, later)

    def test_a_budget_below_the_part_list_keeps_the_parts_and_says_so(self, project, settings):
        members = summarize_project(project, settings.parts_dir)
        text = build_project_index_markdown(project, members, token_budget=10)
        assert count_tokens(text) > 10, "the floor is real, not a silent trim"
        assert "below this project's part list" in text
        for part in BOARD:
            assert part in text

    def test_a_member_with_no_corpus_reads_honestly(self, settings):
        project = new_project("gappy", settings.projects_dir)
        project.parts.append(ProjectMember(part_number="GHOST9"))
        members = summarize_project(project, settings.parts_dir)
        text = build_project_index_markdown(project, members, token_budget=4000)
        assert "no corpus on disk" in text
        assert "dsa build <pdf> --part GHOST9" in text


class TestMembershipIsExplicitAndSafe:
    """Criteria 4 and 5: no half-index, and no stale entry after a removal."""

    def test_adding_an_unbuilt_part_fails_naming_the_build_command(self, project, settings):
        with pytest.raises(ProjectError) as exc:
            add_parts(project, ["NOSUCH1"], parts_dir=settings.parts_dir)
        assert "dsa build <pdf> --part NOSUCH1" in str(exc.value)
        assert "NOSUCH1" not in project.part_numbers

    def test_a_failed_add_adds_none_of_the_batch(self, project, settings):
        before = list(project.part_numbers)
        with pytest.raises(ProjectError):
            add_parts(project, ["TRX9000", "NOSUCH1"], parts_dir=settings.parts_dir)
        assert project.part_numbers == before

    def test_removing_a_part_rebuilds_with_no_stale_entry(self, project, settings):
        _path, before = write_project_index(
            project,
            parts_dir=settings.parts_dir,
            projects_dir=settings.projects_dir,
            token_budget=4000,
        )
        assert "- **AMP4400**" in before

        assert remove_parts(project, ["AMP4400"]) == ["AMP4400"]
        save_project(project, settings.projects_dir)
        reloaded = load_project("rf-frontend", settings.projects_dir)
        _path, after = write_project_index(
            reloaded,
            parts_dir=settings.parts_dir,
            projects_dir=settings.projects_dir,
            token_budget=4000,
        )
        assert "- **AMP4400**" not in after, "no stale entry survives a rebuild"
        assert "Rev. A" not in after, "the removed part's revision goes with it"
        assert "- **TRX9000**" in after and "- **CLK2200**" in after
        # The designer's own words are never rewritten — the interfaces note
        # still names the part it always named. Membership changed; prose did not.
        assert "AMP4400 in;" in after

    def test_re_adding_a_member_updates_its_role_instead_of_duplicating_it(self, project, settings):
        assert (
            add_parts(project, ["TRX9000"], parts_dir=settings.parts_dir, role="main radio") == []
        )
        assert project.part_numbers.count("TRX9000") == 1
        assert project.parts[0].role == "main radio"

    def test_a_project_name_is_validated_not_sanitized(self, settings):
        for bad in ("../escape", "has space", "", "/abs"):
            with pytest.raises(ProjectError):
                new_project(bad, settings.projects_dir)

    def test_creating_the_same_project_twice_refuses(self, project, settings):
        with pytest.raises(ProjectError) as exc:
            new_project("rf-frontend", settings.projects_dir)
        assert "already exists" in str(exc.value)

    def test_loading_a_missing_project_says_how_to_create_it(self, settings):
        with pytest.raises(ProjectError) as exc:
            load_project("nope", settings.projects_dir)
        assert "dsa project new nope" in str(exc.value)

    def test_free_text_survives_a_round_trip(self, project, settings):
        reloaded = load_project("rf-frontend", settings.projects_dir)
        assert reloaded.interfaces == project.interfaces
        assert reloaded.notes == project.notes
        assert [m.role for m in reloaded.parts] == [m.role for m in project.parts]


class TestProjectScopedAsk:
    """Criterion 3: the answer says which part it came from, and two parts
    that both answer both appear."""

    def test_an_answer_is_labelled_with_the_part_it_came_from(self, project, settings):
        pack = _scope(project, settings).ask(
            "junction-to-ambient thermal resistance of the CLK2200", budget=3000
        )
        assert pack.route == ROUTE_SPEC
        assert pack.project == "rf-frontend"
        assert pack.parts == ("TRX9000", "AMP4400", "CLK2200")
        assert pack.answers[0].part in BOARD
        assert f"[{pack.answers[0].part}]" in pack.markdown
        assert pack.answers[0].citation.startswith("§")

    def test_a_project_wide_question_returns_every_part_that_answers(self, project, settings):
        pack = _scope(project, settings).ask("supply voltage", budget=3000)
        assert pack.route == ROUTE_SPEC
        answered = {line.part for line in pack.answers}
        assert answered == set(BOARD), answered
        for part in BOARD:
            assert f"[{part}]" in pack.markdown

    def test_each_part_answers_before_any_part_answers_twice(self, project, settings):
        """Interleaving is what makes a tight budget keep every device."""
        pack = _scope(project, settings).ask("thermal resistance", budget=3000)
        leading = [line.part for line in pack.answers][: len(BOARD)]
        assert len(set(leading)) == len(leading), leading

    def test_a_tight_budget_still_names_more_than_one_part(self, project, settings):
        wide = _scope(project, settings).ask("supply voltage", budget=3000)
        tight = _scope(project, settings).ask("supply voltage", budget=120)
        assert tight.tokens <= 120 < wide.tokens
        assert len({line.part for line in tight.answers}) >= 2
        assert tight.truncated and "--budget" in tight.notice

    def test_the_header_names_the_design_and_its_members(self, project, settings):
        pack = _scope(project, settings).ask("supply voltage", budget=3000)
        assert pack.header == "## rf-frontend — project (TRX9000, AMP4400, CLK2200)"

    def test_the_verify_footer_names_the_part_it_verifies(self, project, settings):
        pack = _scope(project, settings).ask("supply voltage", budget=3000)
        assert pack.verify.split(" — ")[0] in BOARD
        assert "Printed page 6" in pack.verify

    def test_the_excerpt_names_its_part_too(self, project, settings):
        pack = _scope(project, settings).ask("supply voltage", budget=3000)
        assert pack.excerpt is not None
        assert pack.excerpt.part in BOARD
        assert pack.excerpt.label.startswith(pack.excerpt.part)

    def test_a_project_no_match_is_explicit(self, project, settings):
        pack = _scope(project, settings).ask("flux capacitor rating", budget=3000)
        assert pack.route == ROUTE_NONE
        assert "Nothing was guessed." in pack.markdown
        assert pack.suggestions

    def test_an_unsearchable_member_makes_absence_a_gap_not_a_no_match(self, project, settings):
        """A part whose full-text path never ran cannot license "not in this
        design" — the project-level form of the `unavailable` rule."""
        for index in (settings.parts_dir / "AMP4400").glob("docs/*/search_index.json"):
            index.unlink()
        scope = _scope(project, settings)
        assert scope.unsearchable_parts == ("AMP4400",)
        assert scope.search_unavailable() == "", "the other two are searchable"
        pack = scope.ask("flux capacitor rating", budget=3000)
        assert pack.route == ROUTE_UNAVAILABLE
        assert "AMP4400" in pack.markdown
        assert "could not run" in pack.markdown

    def test_an_empty_project_says_so_instead_of_answering(self, settings):
        empty = new_project("bare", settings.projects_dir)
        scope = _scope(empty, settings)
        assert "has no parts" in scope.search_unavailable()
        pack = scope.ask("supply voltage", budget=3000)
        assert pack.route == ROUTE_NONE
        assert pack.parts == ()

    def test_the_declared_schema_admits_a_project_pack(self, project, settings):
        payload = _scope(project, settings).ask("supply voltage", budget=3000).as_dict()
        assert validate_pack(payload) == []
        assert payload["project"] == "rf-frontend"
        assert payload["parts"] == ["TRX9000", "AMP4400", "CLK2200"]
        assert all(line["part"] for line in payload["answers"])

    def test_a_single_part_pack_is_unchanged_by_project_scope(self, project, settings):
        """The project fields are additive: a part pack still renders exactly
        as it did, with no `[PART]` prefix and no project header."""
        from datasheet_analyzer.retrieve import Retriever

        pack = Retriever.for_part(settings.parts_dir / "TRX9000").ask("supply voltage", budget=3000)
        assert pack.project == "" and pack.parts == ()
        assert pack.header.startswith("## TRX9000 — SBASA41E")
        assert "[TRX9000]" not in pack.markdown
        assert all(line.part == "" for line in pack.answers)


class TestProjectScopedLookups:
    """`query` / `search` / `plots` fan out and label every hit."""

    def test_specs_fan_out_and_carry_their_part(self, project, settings):
        hits = _scope(project, settings).specs(name="supply voltage")
        assert {h.citation.part for h in hits} == set(BOARD)
        assert all(h.as_dict()["part"] for h in hits)

    def test_search_merges_every_member_best_score_first(self, project, settings):
        hits = _scope(project, settings).search("thermal pad soldering", limit=10)
        assert hits
        assert {h.citation.part for h in hits} == set(BOARD)
        assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
        assert all(h.citation.page_start is not None for h in hits)

    def test_a_single_part_retriever_labels_its_hits_too(self, settings):
        from datasheet_analyzer.retrieve import Retriever

        hits = Retriever.for_part(settings.parts_dir / "CLK2200").specs(symbol="VDD2P5")
        assert hits and all(h.citation.part == "CLK2200" for h in hits)


class TestProjectCli:
    def test_new_add_build_status_end_to_end(self, wired, capsys):
        assert cli.main(["project", "new", "board1"]) == 0
        assert cli.main(["project", "add", "board1", "TRX9000", "AMP4400"]) == 0
        assert cli.main(["project", "build", "board1"]) == 0
        out = capsys.readouterr().out
        assert "PROJECT_INDEX.md" in out
        assert f"budget {wired.project_index_token_budget}" in out
        # ticket 08: the protocol is published with the index, and its size is
        # reported against its budget rather than claimed anywhere.
        assert "agent protocol: AGENT.md" in out
        assert (wired.projects_dir / "board1" / "AGENT.md").exists()
        assert list_projects(wired.projects_dir) == ["board1"]

        assert cli.main(["project", "status"]) == 0
        status = capsys.readouterr().out
        assert "project: board1 [built] parts: TRX9000, AMP4400" in status

    def test_adding_an_unbuilt_part_exits_2_with_the_build_command(self, wired, capsys):
        assert cli.main(["project", "new", "board2"]) == 0
        assert cli.main(["project", "add", "board2", "NOSUCH1"]) == 2
        err = capsys.readouterr().err
        assert "dsa build <pdf> --part NOSUCH1" in err
        assert load_project("board2", wired.projects_dir).parts == []

    def test_status_lists_projects_alongside_parts(self, wired, capsys):
        assert cli.main(["project", "new", "board3"]) == 0
        assert cli.main(["project", "add", "board3", "CLK2200"]) == 0
        capsys.readouterr()
        assert cli.main(["status"]) == 0
        out = capsys.readouterr().out
        assert "part: TRX9000" in out
        assert "project: board3" in out
        assert "parts: CLK2200" in out
        assert f"projects_dir: {wired.projects_dir}" in out

    def test_ask_project_labels_the_part(self, wired, capsys):
        assert cli.main(["project", "new", "board4"]) == 0
        assert cli.main(["project", "add", "board4", "TRX9000", "AMP4400"]) == 0
        capsys.readouterr()
        assert cli.main(["ask", "--project", "board4", "supply voltage"]) == 0
        out = capsys.readouterr().out
        assert "[TRX9000]" in out and "[AMP4400]" in out
        assert "§4.3, p.6" in out

    def test_query_project_labels_each_hit(self, wired, capsys):
        assert cli.main(["project", "new", "board5"]) == 0
        assert cli.main(["project", "add", "board5", "TRX9000", "CLK2200"]) == 0
        capsys.readouterr()
        assert cli.main(["query", "--project", "board5", "--name", "supply"]) == 0
        out = capsys.readouterr().out
        assert "[TRX9000]" in out and "[CLK2200]" in out

    def test_query_json_carries_the_part_of_every_hit(self, wired, capsys):
        assert cli.main(["project", "new", "board6"]) == 0
        assert cli.main(["project", "add", "board6", "TRX9000", "CLK2200"]) == 0
        capsys.readouterr()
        assert cli.main(["query", "--project", "board6", "--name", "supply", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["project"] == "board6"
        assert {h["part"] for h in payload["hits"]} == {"TRX9000", "CLK2200"}

    def test_search_project_labels_each_hit(self, wired, capsys):
        assert cli.main(["project", "new", "board7"]) == 0
        assert cli.main(["project", "add", "board7", "TRX9000", "AMP4400"]) == 0
        capsys.readouterr()
        assert cli.main(["search", "--project", "board7", "thermal pad"]) == 0
        out = capsys.readouterr().out
        assert "[TRX9000]" in out and "[AMP4400]" in out

    def test_a_single_part_lookup_prints_no_part_label(self, wired, capsys):
        assert cli.main(["query", "--part", "TRX9000", "--name", "supply"]) == 0
        out = capsys.readouterr().out
        assert "[TRX9000]" not in out
        assert "§4.3, p.6" in out

    def test_an_unknown_project_exits_2(self, wired, capsys):
        assert cli.main(["ask", "--project", "ghost", "supply voltage"]) == 2
        assert "dsa project new ghost" in capsys.readouterr().err

    def test_a_member_with_no_corpus_is_warned_about_not_hidden(self, wired, capsys):
        assert cli.main(["project", "new", "board8"]) == 0
        assert cli.main(["project", "add", "board8", "TRX9000"]) == 0
        project = load_project("board8", wired.projects_dir)
        project.parts.append(ProjectMember(part_number="GHOST9"))
        save_project(project, wired.projects_dir)
        capsys.readouterr()
        assert cli.main(["ask", "--project", "board8", "supply voltage"]) == 0
        err = capsys.readouterr().err
        assert "no corpus for GHOST9" in err

    def test_removing_a_part_then_rebuilding_leaves_no_stale_entry(self, wired, capsys):
        assert cli.main(["project", "new", "board9"]) == 0
        assert cli.main(["project", "add", "board9", "TRX9000", "AMP4400"]) == 0
        assert cli.main(["project", "build", "board9"]) == 0
        index = wired.projects_dir / "board9" / "PROJECT_INDEX.md"
        assert "AMP4400" in index.read_text(encoding="utf-8")

        assert cli.main(["project", "remove", "board9", "AMP4400"]) == 0
        assert cli.main(["project", "build", "board9"]) == 0
        text = index.read_text(encoding="utf-8")
        assert "AMP4400" not in text and "TRX9000" in text

    def test_plots_project_labels_each_hit(self, wired, capsys):
        assert cli.main(["project", "new", "board10"]) == 0
        assert cli.main(["project", "add", "board10", "TRX9000", "CLK2200"]) == 0
        capsys.readouterr()
        assert cli.main(["plots", "--project", "board10", "--q", "thermal derating"]) == 0
        out = capsys.readouterr().out
        assert "[TRX9000]" in out and "[CLK2200]" in out

    def test_search_project_warns_about_a_member_it_could_not_search(self, wired, capsys):
        """A gap is announced; the parts that *can* answer still do."""
        assert cli.main(["project", "new", "board11"]) == 0
        assert cli.main(["project", "add", "board11", "TRX9000", "AMP4400"]) == 0
        for index in (wired.parts_dir / "AMP4400").glob("docs/*/search_index.json"):
            index.unlink()
        capsys.readouterr()
        assert cli.main(["search", "--project", "board11", "thermal pad"]) == 0
        captured = capsys.readouterr()
        assert "AMP4400" in captured.err and "could not run" in captured.err
        assert "[TRX9000]" in captured.out

    def test_scope_is_required_and_exclusive(self, wired):
        with pytest.raises(SystemExit):
            cli.main(["query", "--symbol", "VDD1P8"])
        with pytest.raises(SystemExit):
            cli.main(["query", "--part", "TRX9000", "--project", "board1", "--symbol", "X"])
