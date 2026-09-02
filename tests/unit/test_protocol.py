"""The corpus agent protocol — `AGENT.md` + the in-repo skill (ticket 08).

What these prove, criterion by criterion:

- `AGENT.md` is emitted for **every part at publish** and every project when
  its index is built, and it fits the budget it records
  (`AGENT_DOC_TOKEN_BUDGET`, measured into `CorpusStats.agent_doc_tokens`);
- it documents **both** access paths — the `dsa` CLI and the MCP tools — each
  with a worked example scoped to that part or project;
- it states the confidence-and-fallback rule explicitly, including the case
  that sends the designer to the printed page;
- `.claude/skills/datasheet-corpus/SKILL.md` is discoverable by name and
  **cannot drift**: it is exactly what `build_skill_markdown()` renders, and
  every canonical rule string appears verbatim in all three documents;
- `INDEX.md` and `PROJECT_INDEX.md` **point** at the protocol instead of
  restating it — a second copy is a second protocol.

The drift test is the load-bearing one: three copies of a discipline is three
disciplines the moment somebody edits one of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.config import PIPELINE_VERSION
from datasheet_analyzer.enrich import SectionMeta, build_index_markdown
from datasheet_analyzer.models import (
    DocType,
    Project,
    ProjectMember,
    RawDocument,
    SectionNode,
    SourceDocument,
)
from datasheet_analyzer.projects import build_project_index_markdown, write_project_index
from datasheet_analyzer.protocol import (
    AGENT_DOC_TOKEN_BUDGET,
    AGENT_FILENAME,
    CONFIDENCE_ROWS,
    FALLBACK_RULE,
    NETWORK_RULE,
    PROTOCOL_MARKER,
    RULES,
    SKILL_NAME,
    SKILL_RELPATH,
    VERBS,
    agent_doc_current,
    build_part_agent_markdown,
    build_project_agent_markdown,
    build_skill_markdown,
)
from datasheet_analyzer.publish import write_corpus
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.tokens import count_tokens

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / SKILL_RELPATH


def _build_corpus(part_dir: Path, part: str = "TEST9000") -> None:
    """A minimal published corpus — enough to exercise the publish stage."""
    source = SourceDocument(
        content_hash=(part.lower() + "0" * 64)[:64],
        path=f"pdfs/{part.lower()}.pdf",
        part_number=part,
        doc_type=DocType.DATASHEET,
        revision="Rev. A",
        page_count=12,
    )
    raw = RawDocument(
        source=source,
        sections=[
            SectionNode(
                number="4.3",
                title="Recommended Operating Conditions",
                page_start=6,
                page_end=6,
                paragraphs=["Supply rails and junction temperature are specified here."],
            )
        ],
        extractor="ti_html",
        extractor_version="test-1",
    )
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        f"# {part} — datasheet corpus\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
    )


@pytest.fixture
def part_doc() -> str:
    return build_part_agent_markdown(
        "AFE7950",
        revision="SBASA41E",
        doc_dirs=["datasheet-c1b4663b"],
        n_sections=39,
        n_specs=619,
        n_plot_files=514,
    )


@pytest.fixture
def project_doc() -> str:
    return build_project_agent_markdown("rf-frontend", ["AFE7950", "HMC520A", "AD9081"])


@pytest.fixture
def skill_doc() -> str:
    return build_skill_markdown()


class TestEveryPartAndProjectShipsTheProtocol:
    """Criterion 1: emitted at publish, and small enough to load freely."""

    def test_publishing_a_part_writes_agent_md_beside_the_index(self, tmp_path: Path):
        part_dir = tmp_path / "parts" / "TEST9000"
        _build_corpus(part_dir)
        agent = part_dir / AGENT_FILENAME
        assert agent.exists(), "the protocol ships with the data, not with the prompt"
        text = agent.read_text(encoding="utf-8")
        assert PROTOCOL_MARKER in text
        assert "TEST9000" in text and "Rev. A" in text
        assert (part_dir / "INDEX.md").exists()

    def test_the_measured_size_is_recorded_in_the_manifest(self, tmp_path: Path):
        part_dir = tmp_path / "parts" / "TEST9000"
        _build_corpus(part_dir)
        from datasheet_analyzer.models import CorpusManifest

        manifest = CorpusManifest.model_validate_json(
            (part_dir / "manifest.json").read_text(encoding="utf-8")
        )
        text = (part_dir / AGENT_FILENAME).read_text(encoding="utf-8")
        assert manifest.stats.agent_doc_tokens == count_tokens(text)
        assert 0 < manifest.stats.agent_doc_tokens <= AGENT_DOC_TOKEN_BUDGET

    def test_building_a_project_index_writes_agent_md_beside_it(self, tmp_path: Path):
        project = Project(name="rf-frontend", parts=[ProjectMember(part_number="GHOST9")])
        path, _text = write_project_index(
            project,
            parts_dir=tmp_path / "parts",
            projects_dir=tmp_path / "projects",
            token_budget=4000,
        )
        agent = path.parent / AGENT_FILENAME
        assert agent.exists()
        assert PROTOCOL_MARKER in agent.read_text(encoding="utf-8")

    def test_both_documents_fit_the_recorded_budget(self, part_doc, project_doc):
        assert count_tokens(part_doc) <= AGENT_DOC_TOKEN_BUDGET
        assert count_tokens(project_doc) <= AGENT_DOC_TOKEN_BUDGET

    def test_a_large_design_does_not_push_the_protocol_over_budget(self):
        # long names, many of them: the fixed text must not be pushed over its
        # ceiling by a part list that belongs to PROJECT_INDEX.md anyway.
        big = build_project_agent_markdown(
            "rf-frontend-revision-c", [f"LONGPARTNUMBER{i:03d}A" for i in range(60)]
        )
        assert count_tokens(big) <= AGENT_DOC_TOKEN_BUDGET
        assert "PROJECT_INDEX.md" in big, "it defers to the index rather than listing 60"


class TestBothAccessPathsAreDocumented:
    """Criterion 2: CLI and MCP, each with a worked example."""

    @pytest.mark.parametrize("doc", ["part_doc", "project_doc", "skill_doc"])
    def test_each_document_carries_both_paths(self, doc, request):
        text = request.getfixturevalue(doc)
        assert "Access path 1 — the `dsa` CLI" in text
        assert "Access path 2 — MCP tools (`dsa serve --mcp`)" in text

    def test_the_cli_example_is_scoped_and_shows_what_comes_back(self, part_doc, project_doc):
        assert 'dsa ask --part AFE7950 "what is the maximum junction temperature?"' in part_doc
        assert 'dsa ask --project rf-frontend "what is the maximum junction' in project_doc
        for text in (part_doc, project_doc):
            assert "### Answer" in text and "### Verify" in text
            assert "§<n>, p.<page>" in text, "the example shows the citation coming back"

    def test_the_mcp_example_names_the_tools_and_the_image_block(self, part_doc, project_doc):
        for text, scope in (
            (part_doc, '"part": "AFE7950"'),
            (project_doc, '"project": "rf-frontend"'),
        ):
            assert scope in text, "the worked call is scoped to this corpus"
            assert "get_figure" in text and "image content block" in text
            assert "find_spec" in text and "read_section" in text
            assert "DSA_MCP_MAX_TOKENS" in text, "the cap is part of the protocol"

    def test_the_new_verbs_are_named_in_all_three(self, part_doc, project_doc, skill_doc):
        """Phase 7's commands reach every destination, or none of them.

        The failure this guards is the one the module exists to prevent: a
        skill that knows about `dsa audit` beside a shipped `AGENT.md` that
        does not is two protocols, and the corpus is the one an agent trusts.
        """
        for name, text in (("part", part_doc), ("project", project_doc), ("skill", skill_doc)):
            for verb in ("dsa fetch", "dsa check-revisions", "dsa diff-rev", "dsa audit"):
                assert verb in text, f"{name} lost {verb}"
            assert "--family <NAME>" in text, name
            assert NETWORK_RULE in text, f"{name} lost the network rule"
            assert "get_audit" in text and "get_family_index" in text, name

    def test_the_part_document_points_at_its_own_map_and_files(self, part_doc):
        assert "`INDEX.md`" in part_doc
        assert "`docs/datasheet-c1b4663b/`" in part_doc
        assert "39 sections, 619 spec records, 514 figure files" in part_doc

    def test_a_project_document_adds_the_two_rules_a_part_cannot_have(self, project_doc):
        assert "Name the part in every answer" in project_doc
        assert "A gap is not an absence" in project_doc


class TestTheConfidenceAndFallbackRuleIsExplicit:
    """Criterion 3: every grade, and when to open the printed page."""

    @pytest.mark.parametrize("doc", ["part_doc", "project_doc", "skill_doc"])
    def test_every_grade_is_stated_with_what_to_do(self, doc, request):
        text = request.getfixturevalue(doc)
        for grade in ("`high`", "`medium`", "`low`", "`unknown`"):
            assert grade in text, grade
        assert "tell the designer to open the printed page" in text

    @pytest.mark.parametrize("doc", ["part_doc", "project_doc", "skill_doc"])
    def test_the_fallback_is_a_fallback_and_never_a_filter(self, doc, request):
        text = request.getfixturevalue(doc)
        assert FALLBACK_RULE in text
        assert "never means you may withhold it" in text
        assert "the printed page is the authority" in text


class TestTheSkillIsDiscoverableAndDoesNotDrift:
    """Criterion 4: found by name, and the shared text cannot diverge."""

    def test_the_skill_is_where_claude_code_looks_for_it(self):
        assert SKILL_PATH.exists(), f"{SKILL_RELPATH} — run scripts/write_skill.py"
        head = SKILL_PATH.read_text(encoding="utf-8").splitlines()[:4]
        assert head[0] == "---"
        assert f"name: {SKILL_NAME}" in head, "discoverable by name"
        assert any(line.startswith("description: ") for line in head)

    def test_the_checked_in_skill_is_exactly_what_the_protocol_renders(self, skill_doc):
        assert SKILL_PATH.read_text(encoding="utf-8") == skill_doc, (
            "SKILL.md is generated from datasheet_analyzer.protocol — "
            "run `.venv/Scripts/python.exe scripts/write_skill.py`"
        )

    def test_every_shared_rule_appears_verbatim_in_all_three(
        self, part_doc, project_doc, skill_doc
    ):
        shared = [*RULES, *CONFIDENCE_ROWS, FALLBACK_RULE, *VERBS, NETWORK_RULE]
        assert len(shared) == len(RULES) + len(CONFIDENCE_ROWS) + len(VERBS) + 2
        for line in shared:
            for name, text in (("part", part_doc), ("project", project_doc), ("skill", skill_doc)):
                assert line in text, f"{name} AGENT.md/skill lost: {line[:60]}…"

    def test_the_skill_forbids_the_habits_the_corpus_exists_to_replace(self, skill_doc):
        assert "Do not `grep`/`cat` your way through" in skill_doc
        assert "from your own knowledge of the part" in skill_doc


class TestTheIndexPointsInsteadOfRepeating:
    """Criterion 5: a pointer, not duplicated prose."""

    def _index(self) -> str:
        return build_index_markdown(
            "AFE7950",
            "4T6R RF sampling AFE.",
            ["Quad RF sampling DACs"],
            [("datasheet", "SBASA41E", 146, "deadbeef")],
            [
                SectionMeta(
                    number="4.3",
                    title="Recommended Operating Conditions",
                    file="docs/datasheet-deadbeef/sections/4-3.md",
                    page_start=6,
                    page_end=6,
                    token_count=400,
                    n_tables=1,
                    n_figures=0,
                    description="Supply rails, junction temperature.",
                )
            ],
            token_budget=3000,
        )

    def test_index_md_points_at_the_protocol(self):
        text = self._index()
        assert "## How to use this corpus" in text
        assert f"`{AGENT_FILENAME}`" in text

    def test_index_md_does_not_restate_the_protocol(self):
        text = self._index()
        for rule in RULES:
            assert rule not in text, "the protocol lives in AGENT.md, once"
        # the pre-ticket prose block is gone, not merely supplemented
        assert "Tables are atomic" not in text
        assert "Answers must quote values WITH units" not in text
        body = text.split("## How to use this corpus")[1].split("##")[0]
        assert len([ln for ln in body.splitlines() if ln.strip()]) <= 2, (
            "a pointer is one or two lines; more than that is a second protocol"
        )

    def test_project_index_points_at_the_protocol_too(self):
        project = Project(name="rf-frontend", parts=[ProjectMember(part_number="GHOST9")])
        text = build_project_index_markdown(project, [], token_budget=4000)
        assert "## How to use this project" in text
        assert f"`{AGENT_FILENAME}`" in text
        for rule in RULES:
            assert rule not in text


class TestAStaleProtocolRepublishes:
    """Invalidation by embedded version field — invariant 6, one level up."""

    def test_missing_or_older_marker_reads_as_stale(self, tmp_path: Path):
        assert agent_doc_current(tmp_path) is False, "no file at all is stale"
        (tmp_path / AGENT_FILENAME).write_text(
            "# old\n\n<!-- dsa-agent-protocol: v0 -->\n", encoding="utf-8"
        )
        assert agent_doc_current(tmp_path) is False, "an older protocol is stale"

    def test_a_freshly_published_corpus_is_current(self, tmp_path: Path):
        part_dir = tmp_path / "parts" / "TEST9000"
        _build_corpus(part_dir)
        assert agent_doc_current(part_dir) is True
