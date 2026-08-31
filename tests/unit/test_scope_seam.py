"""Ticket 05 — the shared scope seam, `SectionHit.as_dict()`, and `dsa serve`.

Three small things, one theme: the places where a *third* front end would
otherwise have had to copy something.

- `retrieve.scope.resolve_scope` is now the only implementation of "one part
  or one project, never both, never neither" (ADR 0006). `cli.py` and
  `mcp_server/server.py` delegate to it, and the GUI will too.
- `SectionHit.as_dict()` closes the one result type that an adapter had to
  hand-serialize.
- `dsa serve` (no flag) runs the local workbench; `dsa serve --mcp` is
  unchanged.

Everything here is hermetic: the corpus is the synthetic one
`tests/unit/mcp_corpus.py` builds, no server is ever started, and the web
extra is faked in `sys.modules` rather than imported — so this module runs the
same on a core install as on a full one.
"""

from __future__ import annotations

import sys
import types
from importlib.util import find_spec
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import Project, ProjectMember, SectionFile
from datasheet_analyzer.projects import save_project
from datasheet_analyzer.retrieve import Citation, ProjectRetriever, Retriever, SectionHit
from datasheet_analyzer.retrieve import scope as scope_module
from datasheet_analyzer.retrieve.scope import (
    PART_REQUIRED_ERROR,
    SCOPE_ERROR,
    missing_corpus_warning,
    resolve_part,
    resolve_scope,
    unbuilt_members,
)
from tests.unit.mcp_corpus import built_settings, empty_settings

#: The XOR refusal exactly as `mcp_server/server.py::_SCOPE_ERROR` spelled it
#: before this ticket moved it. Written out here, not imported, so that the
#: assertion below compares the moved text against a literal copy of the
#: original rather than against itself. It is the only place ADR 0006's
#: rationale is written down in code, and it must survive the move verbatim.
HISTORICAL_SCOPE_ERROR = (
    "name exactly one of `part` or `project` — a lookup has to know what it "
    "is asking, and defaulting to 'everything' would make the scope of an "
    "answer implicit"
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Two built parts (`TEST`, `OTHER`) and one project over both."""
    return built_settings(tmp_path)


# --- 1. one `_scope`, not three ----------------------------------------------


class TestResolveScope:
    def test_a_built_part_resolves_to_a_retriever(self, settings):
        scope, reason = resolve_scope("TEST", "", settings=settings)
        assert isinstance(scope, Retriever)
        assert reason == ""
        assert scope.part == "TEST"

    def test_a_project_resolves_to_a_project_retriever(self, settings):
        scope, reason = resolve_scope("", "rf-frontend", settings=settings)
        assert isinstance(scope, ProjectRetriever)
        assert reason == ""

    def test_the_resolved_scope_actually_answers(self, settings):
        """Not just the right type — the right corpus behind it."""
        part, _ = resolve_scope("TEST", "", settings=settings)
        project, _ = resolve_scope("", "rf-frontend", settings=settings)
        assert {h.citation.part for h in part.specs(symbol="TJ")} == {"TEST"}
        assert {h.citation.part for h in project.specs(symbol="TJ")} == {"TEST", "OTHER"}

    def test_naming_both_is_refused_with_the_xor_reason(self, settings):
        scope, reason = resolve_scope("TEST", "rf-frontend", settings=settings)
        assert scope is None
        assert reason == SCOPE_ERROR

    def test_naming_neither_is_refused_with_the_same_reason(self, settings):
        scope, reason = resolve_scope("", "", settings=settings)
        assert scope is None
        assert reason == SCOPE_ERROR

    def test_whitespace_is_not_a_scope(self, settings):
        """`--part "  "` is naming nothing, not naming a part called space."""
        assert resolve_scope("   ", "", settings=settings) == (None, SCOPE_ERROR)

    def test_an_unbuilt_part_names_the_build_command(self, settings):
        scope, reason = resolve_scope("NOPE", "", settings=settings)
        assert scope is None
        # Both front ends' historical wording is preserved: the CLI's tests
        # assert the first, the MCP server's tests assert the second.
        assert "run `dsa build` first" in reason
        assert "dsa build <pdf> --part NOPE" in reason

    def test_an_unknown_project_carries_the_store_s_own_fix(self, settings):
        scope, reason = resolve_scope("", "ghost", settings=settings)
        assert scope is None
        assert "dsa project new ghost" in reason

    def test_nothing_built_at_all_is_a_refusal_not_a_crash(self, tmp_path):
        bare = empty_settings(tmp_path)
        assert resolve_scope("TEST", "", settings=bare)[0] is None

    def test_resolve_part_refuses_an_empty_part_by_name(self, settings):
        assert resolve_part("", settings=settings) == (None, PART_REQUIRED_ERROR)

    def test_resolve_part_returns_a_retriever_for_a_built_part(self, settings):
        scope, reason = resolve_part("TEST", settings=settings)
        assert isinstance(scope, Retriever) and reason == ""


class TestTheXorRationaleSurvivedTheMove:
    """ADR 0006's reason for refusing an implicit "everything", character for
    character. If a front end ever re-words it, the rationale stops being
    written down anywhere — this assertion is what stops that."""

    def test_the_text_is_unchanged(self):
        assert SCOPE_ERROR == HISTORICAL_SCOPE_ERROR

    def test_the_mcp_server_still_shows_that_exact_text(self, settings):
        pytest.importorskip("mcp")
        from datasheet_analyzer.mcp_server import server as mcp_server

        built = mcp_server.build_server(settings)
        assert built is not None  # the module imported and wired against it
        assert SCOPE_ERROR in mcp_server.resolve_scope("A", "B", settings=settings)[1]


class TestNeitherFrontEndKeepsACopy:
    """Grep-shaped, like `TestCliIsFormatOnly` — and for the same reason: it
    is the assertion that fails the moment someone re-inlines the resolution
    instead of calling the shared one."""

    CLI_SOURCE = Path(cli.__file__).read_text(encoding="utf-8")
    SERVER_SOURCE = Path(find_spec("datasheet_analyzer.mcp_server.server").origin).read_text(
        encoding="utf-8"
    )

    @pytest.mark.parametrize("source_name", ["CLI_SOURCE", "SERVER_SOURCE"])
    def test_the_front_end_calls_the_shared_resolver(self, source_name):
        assert "resolve_scope" in getattr(self, source_name)

    @pytest.mark.parametrize("source_name", ["CLI_SOURCE", "SERVER_SOURCE"])
    def test_the_front_end_builds_no_project_scope_of_its_own(self, source_name):
        source = getattr(self, source_name)
        assert "ProjectRetriever.for_parts" not in source
        assert "part_dirs" not in source

    @pytest.mark.parametrize("source_name", ["CLI_SOURCE", "SERVER_SOURCE"])
    def test_the_front_end_does_not_restate_the_xor_reason(self, source_name):
        assert "defaulting to 'everything'" not in getattr(self, source_name)

    def test_the_shared_module_is_where_it_is_written_down(self):
        source = Path(scope_module.__file__).read_text(encoding="utf-8")
        assert "defaulting to 'everything'" in source


class TestTheCliStillBehavesTheSame:
    """The refactor is a refactor: every message the CLI's own tests assert on
    is still the message it prints."""

    @pytest.fixture
    def wired(self, settings, monkeypatch):
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        return settings

    def test_a_part_lookup_answers_through_the_core(self, wired, capsys):
        assert cli.main(["query", "--part", "TEST", "--symbol", "TJ"]) == 0
        assert "p.6" in capsys.readouterr().out

    def test_a_project_lookup_labels_each_hit_with_its_part(self, wired, capsys):
        assert cli.main(["query", "--project", "rf-frontend", "--symbol", "TJ"]) == 0
        out = capsys.readouterr().out
        assert "[TEST]" in out and "[OTHER]" in out

    def test_an_unbuilt_part_exits_2_with_the_build_hint(self, wired, capsys):
        assert cli.main(["query", "--part", "NOPE", "--symbol", "TJ"]) == 2
        assert "run `dsa build` first" in capsys.readouterr().err

    def test_an_unknown_project_exits_2_with_the_project_hint(self, wired, capsys):
        assert cli.main(["query", "--project", "ghost", "--symbol", "TJ"]) == 2
        assert "dsa project new ghost" in capsys.readouterr().err

    def test_a_member_with_no_corpus_is_warned_about_not_hidden(self, wired, capsys):
        save_project(
            Project(
                name="gappy",
                parts=[
                    ProjectMember(part_number="TEST"),
                    ProjectMember(part_number="GHOST9"),
                ],
            ),
            wired.projects_dir,
        )
        capsys.readouterr()
        assert cli.main(["query", "--project", "gappy", "--symbol", "TJ"]) == 0
        assert "no corpus for GHOST9" in capsys.readouterr().err

    def test_argparse_still_refuses_both_and_neither(self, wired):
        for argv in (
            ["query", "--symbol", "TJ"],
            ["query", "--part", "TEST", "--project", "rf-frontend", "--symbol", "TJ"],
        ):
            with pytest.raises(SystemExit):
                cli.main(argv)


class TestTheProjectGapWarning:
    def test_unbuilt_members_are_listed_in_membership_order(self, settings):
        save_project(
            Project(
                name="gappy",
                parts=[
                    ProjectMember(part_number="GHOST9"),
                    ProjectMember(part_number="TEST"),
                    ProjectMember(part_number="GHOST1"),
                ],
            ),
            settings.projects_dir,
        )
        assert unbuilt_members("gappy", settings=settings) == ["GHOST9", "GHOST1"]

    def test_a_fully_built_project_warns_about_nothing(self, settings):
        assert unbuilt_members("rf-frontend", settings=settings) == []
        assert missing_corpus_warning([]) == ""

    def test_the_warning_names_every_member_and_the_fix(self):
        warning = missing_corpus_warning(["GHOST9", "GHOST1"])
        assert "GHOST9" in warning and "GHOST1" in warning
        assert "dsa build <pdf> --part GHOST9" in warning

    def test_an_unreadable_project_reports_no_members_rather_than_raising(self, settings):
        assert unbuilt_members("ghost", settings=settings) == []


# --- 2. SectionHit.as_dict() -------------------------------------------------


#: `SearchHit`'s key set minus the three search-only fields.
#: `doc_hash` joined the shape at integration (ticket 22): the workbench's
#: citation -> PDF handoff calls `/api/locate` with a `doc_hash`, and a hit
#: that carried only the eight-character directory name (`doc`) could not
#: supply one.
SECTION_HIT_KEYS = {
    "section",
    "title",
    "file",
    "part",
    "doc",
    "doc_hash",
    "page_start",
    "page_end",
    "citation",
    "matched_via",
    "confidence",
}


class TestSectionHitAsDict:
    @pytest.fixture
    def hit(self, settings) -> SectionHit:
        found = Retriever.for_part(settings.parts_dir / "TEST").resolve_section("4.5")
        assert found is not None
        return found

    def test_the_key_set_is_exact(self, hit):
        assert set(hit.as_dict()) == SECTION_HIT_KEYS

    def test_it_is_the_search_hit_key_set_minus_the_search_only_fields(self, settings):
        search_hit = Retriever.for_part(settings.parts_dir / "TEST").search("sysref")[0]
        assert set(search_hit.as_dict()) - {"score", "snippet", "terms"} == SECTION_HIT_KEYS

    def test_the_values_are_the_section_and_its_citation(self, hit):
        payload = hit.as_dict()
        assert payload["section"] == "4.5"
        assert payload["title"] == "Transmitter Electrical Characteristics"
        assert payload["file"] == hit.section.file
        assert payload["part"] == hit.citation.part == "TEST"
        assert payload["doc"] == hit.citation.doc
        assert (payload["page_start"], payload["page_end"]) == (7, 8)
        assert payload["citation"] == hit.citation.label == "§4.5, p.7-8"
        assert payload["matched_via"] == hit.matched_via
        assert payload["confidence"] == hit.confidence

    def test_an_unpinned_page_stays_honestly_none(self):
        """A section with no page range reports `None`, never a guessed page."""
        hit = SectionHit(
            section=SectionFile(
                number="9.1",
                title="Appendix",
                file="docs/d/sections/9-1.md",
                doc_hash="d" * 64,
            ),
            citation=Citation(doc="d", section="9.1", part="TEST"),
        )
        payload = hit.as_dict()
        assert payload["page_start"] is None and payload["page_end"] is None
        assert payload["citation"] == "§9.1, p.?"

    def test_it_is_json_serializable(self, hit):
        import json

        assert json.loads(json.dumps(hit.as_dict()))["section"] == "4.5"


# --- 3. `dsa serve` ----------------------------------------------------------


class _FakeUvicorn(types.ModuleType):
    """Stands in for uvicorn so no socket is ever bound (invariant #4)."""

    def __init__(self):
        super().__init__("uvicorn")
        self.calls: list[dict] = []

    def run(self, app, **kwargs):
        self.calls.append({"app": app, **kwargs})


def _fake_app_main() -> types.ModuleType:
    """Stands in for `datasheet_analyzer.app.main`.

    Faked rather than imported because importing the real module builds a
    FastAPI application at module scope; this test is about the CLI's wiring,
    not about the app, and it must not depend on the state of any other
    ticket's routers.
    """
    module = types.ModuleType("datasheet_analyzer.app.main")
    module.created = []  # type: ignore[attr-defined]

    def create_app(settings=None):
        module.created.append(settings)  # type: ignore[attr-defined]
        return f"app<{settings.serve_host}:{settings.serve_port}>"

    module.create_app = create_app  # type: ignore[attr-defined]
    return module


@pytest.fixture
def serve_settings(tmp_path) -> Settings:
    return Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        projects_dir=tmp_path / "projects",
        serve_host="127.0.0.1",
        serve_port=9123,
    ).resolve()


class TestServeTheWorkbench:
    @pytest.fixture
    def wired(self, monkeypatch, serve_settings):
        """`dsa serve` with a fake runner and a fake app module."""
        uvicorn = _FakeUvicorn()
        app_main = _fake_app_main()
        monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
        monkeypatch.setitem(sys.modules, "datasheet_analyzer.app.main", app_main)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: serve_settings)
        return uvicorn, app_main

    def test_plain_serve_runs_the_app_on_the_configured_host_and_port(self, wired, serve_settings):
        uvicorn, _app_main = wired
        assert cli.main(["serve"]) == 0
        assert len(uvicorn.calls) == 1
        call = uvicorn.calls[0]
        assert call["host"] == serve_settings.serve_host
        assert call["port"] == serve_settings.serve_port

    def test_the_app_is_built_from_the_same_settings(self, wired, serve_settings):
        uvicorn, app_main = wired
        assert cli.main(["serve"]) == 0
        assert app_main.created == [serve_settings]
        assert uvicorn.calls[0]["app"] == "app<127.0.0.1:9123>"

    def test_it_prints_the_url_a_person_should_open(self, wired, capsys):
        assert cli.main(["serve"]) == 0
        assert "http://127.0.0.1:9123" in capsys.readouterr().out

    def test_it_never_starts_the_mcp_server(self, wired, monkeypatch):
        started: list[str] = []
        monkeypatch.setattr("datasheet_analyzer.cli._serve_mcp", lambda: started.append("mcp") or 0)
        assert cli.main(["serve"]) == 0
        assert started == []


class TestServeBindsLoopback:
    """A local single-user tool with no authentication must not listen on all
    interfaces: `0.0.0.0` would publish the corpus browser — and every
    document in it — to the network."""

    def test_the_configured_default_is_loopback(self):
        assert Settings.model_fields["serve_host"].default == "127.0.0.1"

    def test_the_cli_binds_whatever_the_setting_says_and_nothing_else(
        self, monkeypatch, serve_settings
    ):
        uvicorn = _FakeUvicorn()
        monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
        monkeypatch.setitem(sys.modules, "datasheet_analyzer.app.main", _fake_app_main())
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: serve_settings)
        assert cli.main(["serve"]) == 0
        assert uvicorn.calls[0]["host"] == "127.0.0.1"
        assert "0.0.0.0" not in str(uvicorn.calls[0])


class TestServeWithoutTheWebExtra:
    @pytest.fixture
    def missing_web(self, monkeypatch, serve_settings):
        # `None` in sys.modules is how the import system spells "this module
        # is not importable" — an ImportError at the import statement, which
        # is exactly what a machine without the extra would raise.
        monkeypatch.setitem(sys.modules, "datasheet_analyzer.app.main", None)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: serve_settings)
        return serve_settings

    def test_it_exits_2_rather_than_raising(self, missing_web):
        assert cli.main(["serve"]) == 2

    def test_it_prints_an_install_hint_naming_the_extra(self, missing_web, capsys):
        cli.main(["serve"])
        err = capsys.readouterr().err
        assert ".[web]" in err
        assert "not installed" in err

    def test_the_hint_is_a_message_not_a_traceback(self, missing_web, capsys):
        cli.main(["serve"])
        err = capsys.readouterr().err
        assert "Traceback" not in err
        assert err.startswith("serve error:")

    def test_a_missing_runner_is_the_same_hint(self, monkeypatch, serve_settings):
        monkeypatch.setitem(sys.modules, "uvicorn", None)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: serve_settings)
        assert cli.main(["serve"]) == 2


class TestServeMcpIsUnchanged:
    def test_the_mcp_flag_still_hands_off_to_the_stdio_server(self, monkeypatch, serve_settings):
        pytest.importorskip("mcp")
        from datasheet_analyzer.mcp_server import server as mcp_server

        started: list[str] = []
        monkeypatch.setattr(
            mcp_server.MCPServer,
            "run",
            lambda self, transport="stdio", **kw: started.append(transport),
        )
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: serve_settings)
        assert cli.main(["serve", "--mcp"]) == 0
        assert started == ["stdio"]

    def test_the_mcp_flag_never_starts_the_web_app(self, monkeypatch, serve_settings):
        pytest.importorskip("mcp")
        from datasheet_analyzer.mcp_server import server as mcp_server

        uvicorn = _FakeUvicorn()
        monkeypatch.setitem(sys.modules, "uvicorn", uvicorn)
        monkeypatch.setattr(mcp_server.MCPServer, "run", lambda self, **kw: None)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: serve_settings)
        assert cli.main(["serve", "--mcp"]) == 0
        assert uvicorn.calls == []

    def test_without_the_mcp_sdk_it_still_prints_its_own_hint(self, monkeypatch, serve_settings):
        monkeypatch.setitem(sys.modules, "datasheet_analyzer.mcp_server", None)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: serve_settings)
        assert cli.main(["serve", "--mcp"]) == 2


class TestTheWebExtraIsDeclared:
    """`dsa serve` must be installable the way `dsa serve --mcp` already is."""

    PYPROJECT = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")

    def test_pyproject_declares_a_web_extra(self):
        assert "\nweb = [" in self.PYPROJECT

    @pytest.mark.parametrize("package", ["fastapi", "uvicorn", "sse-starlette"])
    def test_the_extra_names_what_the_workbench_needs(self, package):
        web_block = self.PYPROJECT.split("\nweb = [", 1)[1].split("]", 1)[0]
        assert package in web_block

    def test_the_hint_names_the_extra_the_pyproject_declares(self):
        assert ".[web]" in cli.WEB_INSTALL_HINT
