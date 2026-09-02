"""The nine agent tools (GUI ticket 11) — `datasheet_analyzer/app/tools.py`.

Four properties are worth a test here, and they are the four the ticket is
about; everything else is `retrieve/`'s job and is tested there.

- **The seam.** These tools are format-only, the same rule
  `tests/unit/test_mcp_responses.py::TestMcpServerIsFormatOnly` enforces on
  the MCP server: no corpus walk, no record parsing, no hand-built citation,
  and — specifically for this module — no import from the MCP package, whose
  token cap is wrong for this consumer.
- **Scope is injected, never chosen.** No tool takes a part or project name,
  so the agent has no argument through which to widen the scope mid-answer,
  and every payload reports back the scope it was handed.
- **A project scope is a first-class scope** for the four tools that support
  it, and an honest refusal for the three that cannot.
- **Truncation is announced.** A payload that dropped rows or trimmed text
  says so and names the setting that would bring it back.

Hermetic per AGENTS.md invariant 4: the corpus is built on disk by
`mcp_corpus.built_settings` (the shared fixture factory the MCP tests already
use), settings point at `tmp_path`, and nothing here touches the network or a
model.
"""

from __future__ import annotations

import ast
import inspect
from importlib.util import find_spec
from pathlib import Path
from typing import ClassVar

import pytest
from mcp_corpus import DOC, FIGURE, PNG_BYTES, build_part, built_settings

from datasheet_analyzer.app import tools as T
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.projects import load_project, part_dirs
from datasheet_analyzer.retrieve import Citation, ProjectRetriever, Retriever
from datasheet_analyzer.retrieve.family import FamilyRetriever

PART = "TEST"
PROJECT = "rf-frontend"
FAMILY = "TESTx"


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Invariant 4: no cached process-wide settings leak between tests."""
    reset_settings_cache()
    yield
    reset_settings_cache()


def make_settings(tmp_path: Path, **overrides) -> Settings:
    """Two built parts, one project and one family over both, all under tmp.

    `registry_dir` and `families_dir` are carried across from `built_settings`
    deliberately: without them `list_families` and `get_family_index` would
    read the family registry **this repository ships**, which is a test
    reaching into the source tree (invariant 4) and would make the assertions
    below depend on what somebody declared in `registry/families.yaml`.
    """
    base = built_settings(tmp_path)
    return Settings(
        parts_dir=base.parts_dir,
        cache_dir=base.cache_dir,
        projects_dir=base.projects_dir,
        families_dir=base.families_dir,
        registry_dir=base.registry_dir,
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
        **overrides,
    ).resolve()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def part(settings: Settings) -> Retriever:
    return Retriever.for_part(settings.parts_dir / PART)


@pytest.fixture
def project(settings: Settings) -> ProjectRetriever:
    loaded = load_project(PROJECT, settings.projects_dir)
    return ProjectRetriever.for_parts(loaded.name, part_dirs(loaded, settings.parts_dir))


@pytest.fixture
def family(settings: Settings) -> FamilyRetriever:
    """The declared family over the same two parts, resolved the one way."""
    from datasheet_analyzer.retrieve.scope import resolve_scope

    scope, reason = resolve_scope("", "", settings=settings, family=FAMILY)
    assert reason == "", reason
    return scope


# --- the seam ----------------------------------------------------------------


class TestAgentToolsAreFormatOnly:
    """`app/tools.py` must never grow a retrieval implementation of its own.

    The same guard `mcp_server/server.py` carries, for the same reason: three
    front ends over one core can only stay consistent if none of them is
    allowed to look at the corpus itself. Read off the source file rather than
    by importing, so the property is about the code and not about what happens
    to be importable.
    """

    SOURCE = Path(find_spec("datasheet_analyzer.app.tools").origin).read_text(encoding="utf-8")
    TREE = ast.parse(SOURCE)

    @pytest.mark.parametrize(
        "token",
        [
            "rglob",
            "specs.json",
            "plots.json",
            "search_index.json",
            "model_validate_json",
            "SpecSet",
            "PlotSet",
            "SpecRecord",
            "PlotRecord",
            "SearchIndex",
            "bm25",
            "\u00a7",  # a citation label is built by `Citation`, never here
            "p.{",
        ],
    )
    def test_the_source_holds_no_retrieval_logic(self, token):
        assert token not in self.SOURCE

    def _imported_modules(self) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(self.TREE):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        return names

    def test_nothing_is_imported_from_the_mcp_package(self):
        """A different consumer with a different budget — not a shared body.

        The MCP tools cap at `DSA_MCP_MAX_TOKENS` for a model reading over a
        wire; these cap at `chat_tool_max_tokens` for a browser rendering the
        result. Sharing them would mean threading a budget through everything.
        """
        assert not [m for m in self._imported_modules() if "mcp" in m.split(".")]

    def test_the_image_type_is_data_not_host_configuration(self):
        """`mimetypes.guess_type` seeds itself from the Windows registry.

        The media type the browser is handed for a PNG must not depend on the
        machine `dsa serve` happens to run on (invariant 4).
        """
        assert "mimetypes" not in self._imported_modules()
        for extension in (".png", ".gif", ".jpg", ".jpeg", ".svg"):
            assert extension in T.FIGURE_MEDIA_TYPES

    def test_a_search_hit_is_the_hit_s_own_dict(self, part, settings):
        hits = part.search("sysref")
        payload = T.search(scope=part, query="sysref", settings=settings)
        assert payload["hits"] == [hit.as_dict() for hit in hits]

    def test_a_spec_hit_is_the_hit_s_own_dict(self, part, settings):
        hits = part.specs(symbol="TJ")
        payload = T.find_spec(scope=part, symbol="TJ", settings=settings)
        assert payload["hits"] == [hit.as_dict() for hit in hits]

    def test_a_plot_hit_is_the_hit_s_own_dict(self, part, settings):
        hits = part.plots()
        payload = T.find_plots(scope=part, settings=settings)
        assert payload["hits"] == [hit.as_dict() for hit in hits]

    def test_a_figure_payload_is_the_plot_hit_s_own_dict(self, part, settings):
        hit = part.plot_for_file(FIGURE)
        payload = T.get_figure(scope=part, file=FIGURE, settings=settings)
        assert payload["figure"] == hit.as_dict()

    def test_an_answer_pack_is_the_pack_s_own_dict(self, part, settings):
        payload = T.ask(scope=part, question="operating junction temperature", settings=settings)
        assert (
            payload["pack"]
            == part.ask(
                "operating junction temperature", budget=payload["pack"]["budget"]
            ).as_dict()
        )


# --- the nine signatures -----------------------------------------------------


EXPECTED_PARAMS = {
    "list_parts": ["settings"],
    "list_projects": ["settings"],
    "list_families": ["settings"],
    "get_index": ["scope", "settings"],
    "get_family_index": ["scope", "settings"],
    "search": ["scope", "query", "limit", "settings"],
    "find_spec": ["scope", "symbol", "name", "section", "settings"],
    "find_plots": ["scope", "q", "section", "tags", "settings"],
    "read_section": ["scope", "ref", "max_tokens", "settings"],
    "get_figure": ["scope", "file", "settings"],
    "ask": ["scope", "question", "budget", "settings"],
    "get_audit": ["scope", "settings"],
}


class TestTheTwelveToolsExistAsFrozen:
    """Ticket 00 froze nine names and signatures; phase 7 added three.

    `list_families`, `get_family_index` and `get_audit` reached the MCP
    surface with the phase-7 port and not this one. They take **no name**
    here, unlike their MCP twins: the scope is resolved once before the loop
    starts and shown to the user, so a `name` or `part` argument would let the
    agent answer from a corpus the user was not shown.
    """

    def test_the_registry_is_the_twelve_names_in_order(self):
        assert T.TOOL_NAMES == tuple(EXPECTED_PARAMS)
        assert tuple(T.TOOLS) == T.TOOL_NAMES

    @pytest.mark.parametrize("name", list(EXPECTED_PARAMS))
    def test_each_tool_keeps_its_frozen_signature(self, name):
        params = inspect.signature(T.TOOLS[name]).parameters
        assert list(params) == EXPECTED_PARAMS[name]
        assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())

    @pytest.mark.parametrize("name", list(EXPECTED_PARAMS))
    def test_no_tool_is_still_a_stub(self, name):
        assert "NotImplementedError" not in inspect.getsource(T.TOOLS[name])


# --- scope is injected, never chosen -----------------------------------------


class TestScopeIsInjectedNeverChosen:
    """The scope shown to the user has to be the scope the answer came from.

    Resolution happened once, before the loop started (ticket 10, ADR 0006).
    A tool that accepted a `part` or `project` string would let the agent
    silently answer from somewhere else, which is exactly the implicit scope
    the invariant forbids.
    """

    @pytest.mark.parametrize("name", list(EXPECTED_PARAMS))
    def test_no_tool_accepts_a_part_project_or_family_name(self, name):
        params = set(inspect.signature(T.TOOLS[name]).parameters)
        assert not params & {"part", "project", "family", "part_number", "scope_ref"}

    def test_a_part_scope_is_reported_back_verbatim(self, part, settings):
        payload = T.find_spec(scope=part, symbol="TJ", settings=settings)
        assert payload["scope"] == {"kind": "part", "name": PART, "parts": [PART]}

    def test_a_project_scope_is_reported_back_verbatim(self, project, settings):
        payload = T.find_spec(scope=project, symbol="TJ", settings=settings)
        assert payload["scope"] == {
            "kind": "project",
            "name": PROJECT,
            "parts": ["TEST", "OTHER"],
        }

    def test_every_hit_stays_inside_the_scope_it_was_given(self, part, settings):
        payload = T.find_spec(scope=part, name="", settings=settings)
        assert {hit["part"] for hit in payload["hits"]} == {PART}


# --- part-only tools refuse a project ----------------------------------------


class TestPartOnlyToolsRefuseAProjectScope:
    """An index, a section file and a figure each belong to one part.

    The refusal has to be a payload: a `ProjectRetriever` has no
    `index_markdown`, and letting that surface as an `AttributeError` would
    hand the agent a traceback where a sentence belongs.
    """

    CALLS: ClassVar[dict[str, dict]] = {
        "get_index": {},
        "read_section": {"ref": "4.3"},
        "get_figure": {"file": FIGURE},
        # A scorecard is a statement about one published corpus, so it joins
        # the three that cannot answer for a design.
        "get_audit": {},
    }

    def test_the_four_part_only_tools_are_the_declared_four(self):
        assert set(T.PART_ONLY_TOOLS) == set(self.CALLS)

    @pytest.mark.parametrize("name", sorted(CALLS))
    def test_a_project_scope_is_refused_with_a_reason(self, name, project, settings):
        payload = T.TOOLS[name](scope=project, settings=settings, **self.CALLS[name])
        assert payload["error"]
        assert PROJECT in payload["error"]
        assert "TEST" in payload["error"] and "OTHER" in payload["error"]
        assert payload["tool"] == name

    @pytest.mark.parametrize("name", sorted(CALLS))
    def test_the_refusal_still_carries_the_tool_s_body_keys(self, name, project, settings):
        """A refusal is the declared shape, so a caller reads it the same way."""
        refused = T.TOOLS[name](scope=project, settings=settings, **self.CALLS[name])
        answered = T.TOOLS[name](
            scope=Retriever.for_part(settings.parts_dir / PART),
            settings=settings,
            **self.CALLS[name],
        )
        assert set(answered) <= set(refused)

    def test_the_refused_figure_carries_no_image(self, project, settings):
        payload = T.get_figure(scope=project, file=FIGURE, settings=settings)
        assert payload["image"] == b""
        assert payload["media_type"] == ""
        assert payload["figure"] is None


# --- a project scope spans its members ---------------------------------------


class TestAProjectScopeSpansItsMembers:
    """The four project-capable tools answer from every member part."""

    def test_find_spec_returns_both_parts(self, project, settings):
        payload = T.find_spec(scope=project, symbol="TJ", settings=settings)
        assert {hit["part"] for hit in payload["hits"]} == {"TEST", "OTHER"}

    def test_search_returns_both_parts(self, project, settings):
        payload = T.search(scope=project, query="sysref", limit=10, settings=settings)
        assert {hit["part"] for hit in payload["hits"]} == {"TEST", "OTHER"}

    def test_find_plots_returns_both_parts(self, project, settings):
        payload = T.find_plots(scope=project, settings=settings)
        assert {hit["part"] for hit in payload["hits"]} == {"TEST", "OTHER"}

    def test_ask_answers_as_the_project(self, project, settings):
        payload = T.ask(scope=project, question="operating junction temperature", settings=settings)
        assert payload["pack"]["project"] == PROJECT
        assert payload["pack"]["parts"] == ["TEST", "OTHER"]
        assert {line["part"] for line in payload["pack"]["answers"]} == {"TEST", "OTHER"}


# --- citations ----------------------------------------------------------------


class TestEveryCitationComesFromACitationObject:
    """No payload may contain a citation string this module composed.

    Each asserted citation is recomputed here from a `Citation` built by
    `retrieve/`, so a formatting change in one place can never leave the two
    disagreeing about what a citation looks like.
    """

    def test_spec_citations_are_the_retriever_s(self, part, settings):
        expected = {hit.citation.label for hit in part.specs(name="")}
        payload = T.find_spec(scope=part, name="", settings=settings)
        assert {hit["citation"] for hit in payload["hits"]} <= expected
        assert set(payload["citations"]) <= expected

    def test_plot_citations_are_the_retriever_s(self, part, settings):
        expected = {hit.citation.label for hit in part.plots()}
        payload = T.find_plots(scope=part, settings=settings)
        assert set(payload["citations"]) <= expected

    def test_search_citations_are_the_retriever_s(self, part, settings):
        expected = {hit.citation.label for hit in part.search("sysref")}
        payload = T.search(scope=part, query="sysref", settings=settings)
        assert set(payload["citations"]) <= expected

    def test_the_section_citation_is_the_citation_s_own_label(self, part, settings):
        hit = part.resolve_section("4.3")
        payload = T.read_section(scope=part, ref="4.3", settings=settings)
        assert payload["citation"] == hit.citation.label
        assert payload["citations"] == [hit.citation.label]

    def test_the_figure_citation_is_the_citation_s_own_label(self, part, settings):
        hit = part.plot_for_file(FIGURE)
        payload = T.get_figure(scope=part, file=FIGURE, settings=settings)
        assert payload["figure"]["citation"] == hit.citation.label
        assert payload["citations"] == [hit.citation.label]

    def test_a_citation_the_tools_emit_is_one_a_citation_renders(self, part, settings):
        """The label is `Citation`'s, character for character."""
        record = part.specs(symbol="TJ")[0]
        rebuilt = Citation(
            doc=record.citation.doc,
            doc_hash=record.citation.doc_hash,
            section=record.citation.section,
            page_start=record.citation.page_start,
            page_end=record.citation.page_end,
            part=record.citation.part,
        )
        payload = T.find_spec(scope=part, symbol="TJ", settings=settings)
        assert payload["hits"][0]["citation"] == rebuilt.label

    def test_a_catalog_listing_fabricates_no_citation(self, settings):
        assert T.list_parts(settings=settings)["citations"] == []
        assert T.list_projects(settings=settings)["citations"] == []


# --- grades and rungs travel unchanged ---------------------------------------


class TestFindSpecCarriesConfidenceAndRung:
    """`confidence` is the record's grade and `matched_via` the ladder's rung.

    Both are read off the hit and passed through: this module never grades,
    never re-ranks and never drops a hit for being low-confidence — grading is
    metadata, and retrieval order stays the ladder's.
    """

    def test_the_grade_and_the_rung_are_the_hit_s_own(self, part, settings):
        hits = part.specs(symbol="TJ")
        payload = T.find_spec(scope=part, symbol="TJ", settings=settings)
        assert [h["confidence"] for h in payload["hits"]] == [h.confidence for h in hits]
        assert [h["matched_via"] for h in payload["hits"]] == [h.matched_via for h in hits]

    def test_a_low_confidence_record_is_returned_not_hidden(self, part, settings):
        payload = T.find_spec(scope=part, symbol="DACRES", settings=settings)
        assert [h["confidence"] for h in payload["hits"]] == ["low"]

    def test_no_match_offers_candidates_rather_than_a_guess(self, part, settings):
        payload = T.find_spec(scope=part, symbol="ZZZNOSUCH", settings=settings)
        assert payload["hits"] == []
        assert isinstance(payload["suggestions"], list)


# --- get_figure ---------------------------------------------------------------


class TestGetFigureReturnsBytesAndAMediaType:
    def test_the_cataloged_figure_comes_back_as_bytes(self, part, settings):
        payload = T.get_figure(scope=part, file=FIGURE, settings=settings)
        assert payload["error"] == ""
        assert payload["image"] == PNG_BYTES
        assert payload["media_type"] == "image/png"
        assert payload["bytes"] == len(PNG_BYTES)

    @pytest.mark.parametrize(
        "escape", ["../outside.png", "a/../../b.png", "/abs/path.png", "C:/Windows/win.ini", ""]
    )
    def test_a_path_leaving_the_part_is_refused_as_a_path(self, escape, part, settings):
        payload = T.get_figure(scope=part, file=escape, settings=settings)
        assert "part directory" in payload["error"]
        assert payload["image"] == b""

    def test_a_file_no_record_claims_is_refused(self, part, settings):
        loose = f"docs/{DOC}/figures/not-cataloged.png"
        (settings.parts_dir / PART / loose).write_bytes(PNG_BYTES)
        payload = T.get_figure(scope=part, file=loose, settings=settings)
        assert "no cataloged figure" in payload["error"]
        assert payload["figure"] is None

    def test_a_cataloged_file_missing_on_disk_is_reported_not_raised(self, tmp_path, settings):
        build_part(settings.parts_dir / "NOPIX", with_figure=False)
        scope = Retriever.for_part(settings.parts_dir / "NOPIX")
        payload = T.get_figure(scope=scope, file=FIGURE, settings=settings)
        assert "not on disk" in payload["error"]
        assert payload["image"] == b""
        assert payload["media_type"] == ""


# --- truncation is announced --------------------------------------------------


class TestTruncationIsAlwaysAnnounced:
    """Silent loss is the one failure an agent cannot detect.

    Every path that can shorten a payload sets `truncated` and writes a notice
    naming `DSA_CHAT_TOOL_MAX_TOKENS` — the tool budget, deliberately not the
    MCP cap, because this consumer renders results in a browser.
    """

    def test_the_setting_the_notice_names_is_the_chat_tool_budget(self):
        assert T.CAP_SETTING == "DSA_CHAT_TOOL_MAX_TOKENS"

    def test_a_reading_budget_trims_the_text_and_says_so(self, part, settings):
        full = T.read_section(scope=part, ref="4.3", settings=settings)
        short = T.read_section(scope=part, ref="4.3", max_tokens=5, settings=settings)
        assert full["truncated"] is False and full["notice"] == ""
        assert short["truncated"] is True
        assert "max_tokens=5" in short["notice"]
        assert 0 < len(short["text"]) < len(full["text"])

    def test_the_citation_survives_a_reading_budget_that_removes_the_text(self, part, settings):
        """The provenance is the reserved tail; a budget never pays with it."""
        payload = T.read_section(scope=part, ref="4.3", max_tokens=1, settings=settings)
        assert payload["citation"]
        assert payload["citations"] == [part.resolve_section("4.3").citation.label]

    def test_a_tight_tool_budget_trims_a_section_and_says_so(self, tmp_path):
        # Tight enough to trim, wide enough that *something* survives — the
        # assertion below is `0 < len(text) < full`, so the budget has to leave
        # room for the envelope plus a little prose. It was 200 until the
        # payload gained `doc_hash` (integration, ticket 22), whose 64-character
        # value spends about twenty tokens of it.
        tight = make_settings(tmp_path, chat_tool_max_tokens=220)
        scope = Retriever.for_part(tight.parts_dir / PART)
        payload = T.read_section(scope=scope, ref="4.3", settings=tight)
        assert payload["truncated"] is True
        assert T.CAP_SETTING in payload["notice"]
        assert (
            0 < len(payload["text"]) < len(scope.section_text(scope.resolve_section("4.3").section))
        )
        # the citation is reserved tail: the cap trims prose, never provenance
        assert payload["citations"]

    def test_a_tight_tool_budget_drops_rows_and_says_so(self, tmp_path):
        """Rows are dropped whole, in retrieval order, and each keeps its cite."""
        tight = make_settings(tmp_path, chat_tool_max_tokens=350)
        scope = Retriever.for_part(tight.parts_dir / PART)
        payload = T.find_spec(scope=scope, name="", settings=tight)
        assert 0 < payload["count"] < payload["total"]
        assert payload["hits"] == [h.as_dict() for h in scope.specs(name="")][: payload["count"]]
        assert payload["truncated"] is True
        assert T.CAP_SETTING in payload["notice"]

    def test_a_tight_tool_budget_trims_the_index_and_says_so(self, tmp_path):
        tight = make_settings(tmp_path, chat_tool_max_tokens=100)
        scope = Retriever.for_part(tight.parts_dir / PART)
        payload = T.get_index(scope=scope, settings=tight)
        assert payload["truncated"] is True
        assert T.CAP_SETTING in payload["notice"]

    def test_a_tight_tool_budget_shrinks_the_pack_and_says_so(self, tmp_path):
        tight = make_settings(tmp_path, chat_tool_max_tokens=300)
        scope = Retriever.for_part(tight.parts_dir / PART)
        payload = T.ask(scope=scope, question="junction temperature", settings=tight)
        assert T.CAP_SETTING in payload["notice"]
        assert payload["pack"]["budget"] <= 300

    def test_an_untruncated_payload_says_nothing(self, part, settings):
        payload = T.find_spec(scope=part, symbol="TJ", settings=settings)
        assert payload["truncated"] is False
        assert payload["notice"] == ""
        assert payload["over_cap"] is False
        assert payload["count"] == payload["total"]

    @pytest.mark.parametrize(
        ("name", "kwargs"),
        [
            ("list_parts", {}),
            ("list_projects", {}),
            ("find_spec", {"name": ""}),
            ("find_plots", {}),
            ("search", {"query": "sysref"}),
            ("read_section", {"ref": "4.3"}),
            ("get_index", {}),
            ("ask", {"question": "junction temperature"}),
            ("get_figure", {"file": FIGURE}),
        ],
    )
    def test_no_payload_is_ever_truncated_without_a_notice(self, name, kwargs, part, settings):
        scoped = {} if name in ("list_parts", "list_projects") else {"scope": part}
        payload = T.TOOLS[name](settings=settings, **scoped, **kwargs)
        assert not (payload["truncated"] and not payload["notice"])
        assert not (payload["over_cap"] and not payload["notice"])
        assert payload["max_tokens"] == settings.chat_tool_max_tokens


# --- the catalog tools --------------------------------------------------------


class TestTheCatalogTools:
    def test_list_parts_reports_the_built_corpora(self, settings):
        payload = T.list_parts(settings=settings)
        rows = {row["part_number"]: row for row in payload["parts"]}
        assert {"TEST", "OTHER"} <= set(rows)
        assert rows["TEST"]["built"] is True
        assert rows["TEST"]["revision"] == "SBASA41E"
        assert rows["TEST"]["specs"] == 3
        assert rows["TEST"]["searchable"] is True
        assert rows["TEST"]["spec_confidence"]

    def test_an_unbuilt_part_is_listed_rather_than_hidden(self, settings):
        (settings.parts_dir / "HALFDONE").mkdir(parents=True)
        rows = {r["part_number"]: r for r in T.list_parts(settings=settings)["parts"]}
        assert rows["HALFDONE"]["built"] is False
        assert rows["HALFDONE"]["specs"] == 0

    def test_list_projects_reports_members_and_roles(self, settings):
        payload = T.list_projects(settings=settings)
        (row,) = payload["projects"]
        assert row["name"] == PROJECT
        assert [m["part_number"] for m in row["parts"]] == ["TEST", "OTHER"]
        assert row["parts"][0]["role"] == "quad RF transceiver"
        assert all(m["built"] for m in row["parts"])
        assert row["built"] is True

    def test_an_empty_machine_lists_nothing_rather_than_failing(self, tmp_path):
        bare = Settings(
            parts_dir=tmp_path / "parts",
            cache_dir=tmp_path / ".cache",
            projects_dir=tmp_path / "projects",
            library_dir=tmp_path / "library",
            sessions_dir=tmp_path / "sessions",
        ).resolve()
        assert T.list_parts(settings=bare)["parts"] == []
        assert T.list_projects(settings=bare)["projects"] == []

    def test_omitting_settings_reads_the_configured_ones(self, tmp_path, monkeypatch):
        """`settings=None` means the process settings, not a hidden default."""
        configured = make_settings(tmp_path)
        monkeypatch.setenv("DSA_PARTS_DIR", str(configured.parts_dir))
        monkeypatch.setenv("DSA_PROJECTS_DIR", str(configured.projects_dir))
        monkeypatch.setenv("DSA_CACHE_DIR", str(configured.cache_dir))
        monkeypatch.setenv("DSA_LIBRARY_DIR", str(tmp_path / "library"))
        monkeypatch.setenv("DSA_SESSIONS_DIR", str(tmp_path / "sessions"))
        reset_settings_cache()
        rows = {row["part_number"] for row in T.list_parts()["parts"]}
        assert {"TEST", "OTHER"} <= rows


# --- the remaining read paths -------------------------------------------------


class TestReadSectionAndGetIndex:
    def test_the_index_is_the_corpus_s_own_markdown(self, part, settings):
        payload = T.get_index(scope=part, settings=settings)
        assert payload["text"] == part.index_markdown()
        assert payload["file"] == "INDEX.md"
        assert payload["revision"] == "SBASA41E"

    def test_a_section_comes_back_verbatim(self, part, settings):
        hit = part.resolve_section("4.3")
        payload = T.read_section(scope=part, ref="4.3", settings=settings)
        assert payload["text"] == part.section_text(hit.section)
        assert payload["section"] == "4.3"
        assert payload["matched_via"] == hit.matched_via

    def test_an_unknown_reference_is_an_error_not_an_empty_section(self, part, settings):
        payload = T.read_section(scope=part, ref="99.99", settings=settings)
        assert "no section matching" in payload["error"]
        assert payload["text"] == ""
        assert payload["citations"] == []

    def test_search_on_an_unindexed_corpus_is_an_error_not_an_absence(self, tmp_path, settings):
        """ "Could not look" and "not in the datasheet" are different answers."""
        bare = settings.parts_dir / "NOINDEX"
        bare.mkdir(parents=True)
        payload = T.search(scope=Retriever.for_part(bare), query="sysref", settings=settings)
        assert "no full-text index" in payload["error"]
        assert payload["hits"] == []


# --- phase 7's three, and the scope kind they answer for ----------------------


class TestTheFamilyScopeReportsItself:
    """`FamilyRetriever` subclasses `ProjectRetriever`, and that used to lie.

    Before phase 7's tools reached this surface every `isinstance` check here
    asked about the project first, so a turn scoped to a declared series came
    back as `kind: "project"` on every payload and every part-only refusal
    called it a design. Measured on the real corpus before the fix:
    `{"kind": "project", "name": "AFE795x", "parts": [...]}`, and
    "`get_index` needs one part, but this turn is scoped to project
    'AFE795x'". A response that misreports which scope produced it is the one
    failure the `scope` key exists to prevent.
    """

    def test_a_family_scope_is_reported_back_as_a_family(self, family, settings):
        payload = T.find_spec(scope=family, symbol="TJ", settings=settings)
        assert payload["scope"] == {
            "kind": "family",
            "name": FAMILY,
            "parts": ["TEST", "OTHER"],
        }

    def test_a_part_only_refusal_names_the_family_as_a_family(self, family, settings):
        payload = T.get_index(scope=family, settings=settings)
        assert f"scoped to family '{FAMILY}'" in payload["error"]
        assert "project" not in payload["error"]

    def test_the_fan_out_still_reaches_both_members(self, family, settings):
        payload = T.find_spec(scope=family, name="junction temperature", settings=settings)
        assert {hit["part"] for hit in payload["hits"]} == {"TEST", "OTHER"}


class TestListFamilies:
    def test_it_reports_declared_membership_and_built_state(self, settings):
        payload = T.list_families(settings=settings)
        assert payload["error"] == ""
        [row] = payload["families"]
        assert row["name"] == FAMILY
        assert row["reference"] == "TEST", "deltas are signed against the first declared"
        assert row["members"] == [
            {"part": "TEST", "built": True},
            {"part": "OTHER", "built": True},
        ]
        assert row["confirmed"] is True

    def test_it_is_a_catalog_call_and_takes_no_scope(self, settings):
        """It names what exists and quotes no datasheet, so it cites nothing."""
        payload = T.list_families(settings=settings)
        assert payload["scope"] == {"kind": "", "name": "", "parts": []}
        assert payload["citations"] == []
        assert "scope" not in inspect.signature(T.list_families).parameters

    def test_a_machine_with_no_declared_families_lists_none(self, tmp_path):
        bare = Settings(
            parts_dir=tmp_path / "parts",
            cache_dir=tmp_path / ".cache",
            projects_dir=tmp_path / "projects",
            registry_dir=tmp_path / "registry",
            families_dir=tmp_path / "families",
            library_dir=tmp_path / "library",
            sessions_dir=tmp_path / "sessions",
        ).resolve()
        payload = T.list_families(settings=bare)
        assert payload["families"] == []
        assert payload["error"] == "", "nothing declared is an empty list, not a failure"


class TestGetFamilyIndex:
    def test_it_maps_the_family_this_turn_was_scoped_to(self, family, settings):
        payload = T.get_family_index(scope=family, settings=settings)
        assert payload["error"] == ""
        assert payload["family"] == FAMILY
        assert payload["members"] == ["TEST", "OTHER"]
        assert payload["n_sections"] > 0
        assert payload["scope"]["kind"] == "family"
        assert FAMILY in payload["text"]

    def test_it_is_derived_live_rather_than_read_off_disk(self, family, settings):
        """No `dsa family build` has run, and the call still answers."""
        assert not (settings.families_dir / FAMILY).exists()
        payload = T.get_family_index(scope=family, settings=settings)
        assert payload["n_sections"] > 0
        assert not (settings.families_dir / FAMILY).exists(), "reading writes nothing"

    @pytest.mark.parametrize("kind", ["part", "project"])
    def test_it_refuses_a_scope_that_is_not_a_family(self, kind, part, project, settings):
        scope = part if kind == "part" else project
        payload = T.get_family_index(scope=scope, settings=settings)
        assert "maps a declared series" in payload["error"]
        assert f"scoped to {kind}" in payload["error"]
        assert payload["text"] == "" and payload["members"] == []

    def test_the_family_only_refusal_carries_the_tool_s_body_keys(self, part, family, settings):
        refused = T.get_family_index(scope=part, settings=settings)
        answered = T.get_family_index(scope=family, settings=settings)
        assert set(answered) <= set(refused)

    def test_it_takes_no_family_name_the_model_could_choose(self):
        """The whole reason it differs from its MCP twin."""
        assert "name" not in inspect.signature(T.get_family_index).parameters
        assert "family" not in inspect.signature(T.get_family_index).parameters


class TestGetAudit:
    def test_it_grades_the_scoped_corpus_and_returns_the_headline(self, part, settings):
        payload = T.get_audit(scope=part, settings=settings)
        assert payload["error"] == ""
        assert payload["scope"] == {"kind": "part", "name": PART, "parts": [PART]}
        assert payload["grade"] in ("A", "B", "C", "D", "F", None)
        assert payload["headline"], "the sentence the whole artifact exists to produce"
        assert payload["rubric_version"], "a grade names the thresholds it was read under"
        assert payload["count"] == payload["total"] == len(payload["metrics"])

    def test_a_metric_it_could_not_measure_is_excluded_rather_than_scored(self, part, settings):
        payload = T.get_audit(scope=part, settings=settings)
        unavailable = [m for m in payload["metrics"] if not m["available"]]
        assert all(m["value"] is None and m["unavailable_reason"] for m in unavailable)
        assert payload["n_unavailable"] == len(unavailable)

    def test_it_computes_nothing_the_audit_package_did_not(self, part, settings):
        """Format-only: the payload is the scorecard, field for field."""
        from datasheet_analyzer.audit import build_scorecard
        from datasheet_analyzer.evalh.golden import default_golden_path

        card = build_scorecard(part.part_dir, golden=default_golden_path(part.part))
        payload = T.get_audit(scope=part, settings=settings)
        assert payload["headline"] == card.headline
        assert payload["score"] == card.score
        assert payload["metrics"] == [m.model_dump(mode="json") for m in card.metrics]

    def test_it_takes_no_part_name_the_model_could_choose(self):
        assert "part" not in inspect.signature(T.get_audit).parameters
