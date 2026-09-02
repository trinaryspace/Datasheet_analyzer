"""Ticket 06 — dependency wiring, the catalog endpoints, and static serving.

Hermetic per AGENTS.md invariant 4: a temp `parts_dir` / `projects_dir` via
`DSA_*` env plus `reset_settings_cache()`, a manifest written directly rather
than a real build, and `TestClient` over the ASGI app. No network, no model,
no subprocess, no browser.

One deliberate stand-in: `retrieve/scope.py` is ticket 05's file. When it has
not landed, the `resolve_scope_available` fixture puts a module with the
**frozen** signature in its place so ticket 06 can be tested on its own — and
steps aside the moment the real one exists, so this file never masks it.
"""

from __future__ import annotations

import mimetypes
import os
import sys
import types
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from datasheet_analyzer.app import static as static_module
from datasheet_analyzer.app.contracts import (
    JobRegistryLike,
    PartsOut,
    ProjectsOut,
    ScopeRef,
)
from datasheet_analyzer.app.deps import (
    get_job_registry,
    get_library,
    get_retriever,
    get_session_store,
    get_settings_dep,
    reset_job_registry,
)
from datasheet_analyzer.app.main import create_app
from datasheet_analyzer.app.sessions import SessionStore
from datasheet_analyzer.app.static import mount_static
from datasheet_analyzer.config import (
    PIPELINE_VERSION,
    Settings,
    get_settings,
    reset_settings_cache,
)
from datasheet_analyzer.library.store import LibraryStore
from datasheet_analyzer.models import (
    CorpusManifest,
    CorpusStats,
    DocType,
    ExtractionStats,
    Project,
    ProjectMember,
    SectionFile,
    SourceDocument,
)
from datasheet_analyzer.projects import save_project
from datasheet_analyzer.retrieve import ProjectRetriever, Retriever

DOC_HASH = "a1b2c3d4" + "0" * 56

#: ADR 0006's refusal, verbatim from `mcp_server/server.py::_SCOPE_ERROR`.
#: Ticket 05 moves this text to `retrieve/scope.py` unchanged; the assertions
#: below match on its distinctive middle so a reflow cannot silently pass.
SCOPE_ERROR = (
    "name exactly one of `part` or `project` — a lookup has to know what it "
    "is asking, and defaulting to 'everything' would make the scope of an "
    "answer implicit"
)


# --- environment --------------------------------------------------------------


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """A machine with nothing built: every directory under `tmp_path`."""
    for var, name in (
        ("DSA_PARTS_DIR", "parts"),
        ("DSA_CACHE_DIR", ".cache"),
        ("DSA_PROJECTS_DIR", "projects"),
        ("DSA_LIBRARY_DIR", "library"),
        ("DSA_SESSIONS_DIR", "sessions"),
    ):
        monkeypatch.setenv(var, str(tmp_path / name))
    # No built frontend unless a test asks for one, so `create_app()` never
    # picks up a `web/dist` a concurrent `npm run build` happened to leave.
    monkeypatch.setenv(static_module.WEB_DIST_ENV, str(tmp_path / "no-such-dist"))
    reset_settings_cache()
    reset_job_registry()
    yield tmp_path
    reset_settings_cache()
    reset_job_registry()


def build_manifest(parts_dir: Path, part: str, *, revision: str = "SBASA41E") -> Path:
    """A *built* part: `manifest.json` only, which is what `built` means here.

    Written directly rather than through `publish.write_corpus` so this
    ticket's tests do not depend on another ticket's in-flight publisher.
    """
    part_dir = parts_dir / part
    part_dir.mkdir(parents=True, exist_ok=True)
    manifest = CorpusManifest(
        part_number=part,
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        extraction_stats={DOC_HASH: ExtractionStats(backend="pdf_layout", extractor_version="7")},
        documents=[
            SourceDocument(
                content_hash=DOC_HASH,
                path=f"pdfs/{part.lower()}.pdf",
                part_number=part,
                doc_type=DocType.DATASHEET,
                revision=revision,
                page_count=146,
            )
        ],
        sections=[
            SectionFile(
                number="4.3",
                title="Recommended Operating Conditions",
                file=f"docs/datasheet-{DOC_HASH[:8]}/4.3.md",
                doc_hash=DOC_HASH,
                page_start=6,
                page_end=6,
                token_count=120,
            )
        ],
        stats=CorpusStats(
            n_documents=1,
            n_sections=1,
            n_specs=3,
            n_plot_files=2,
            total_tokens=1234,
            spec_confidence={"high": 2, "low": 1},
            plot_confidence={"high": 2},
        ),
    )
    (part_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return part_dir


def _reference_resolve_scope(part: str, project: str, *, settings: Settings):
    """Ticket 05's frozen signature, standing in until ticket 05 lands.

    Deliberately a transcription of `mcp_server/server.py::_scope` — the
    thing ticket 05 will *move*, not a second design.
    """
    from datasheet_analyzer.projects import (
        ProjectError,
        is_built,
        load_project,
        part_dirs,
    )

    part, project = (part or "").strip(), (project or "").strip()
    if bool(part) == bool(project):
        return None, SCOPE_ERROR
    if project:
        try:
            loaded = load_project(project, settings.projects_dir)
        except ProjectError as exc:
            return None, str(exc)
        return (
            ProjectRetriever.for_parts(loaded.name, part_dirs(loaded, settings.parts_dir)),
            "",
        )
    if not is_built(part, settings.parts_dir):
        return None, (
            f"no corpus for part {part} under {settings.parts_dir} — build "
            f"it first: `dsa build <pdf> --part {part}`"
        )
    return Retriever.for_part(settings.parts_dir / part), ""


@pytest.fixture
def resolve_scope_available(monkeypatch):
    """Ticket 05's module when it exists; the frozen stand-in when it does not."""
    try:  # pragma: no cover - depends on which tickets have landed
        import datasheet_analyzer.retrieve.scope  # noqa: F401

        return "real"
    except ImportError:
        pass
    import datasheet_analyzer.retrieve as retrieve_pkg

    module = types.ModuleType("datasheet_analyzer.retrieve.scope")
    module.resolve_scope = _reference_resolve_scope
    monkeypatch.setitem(sys.modules, "datasheet_analyzer.retrieve.scope", module)
    monkeypatch.setattr(retrieve_pkg, "scope", module, raising=False)
    return "stub"


# --- providers ----------------------------------------------------------------


class TestProviders:
    """Every provider is importable, zero-argument, and returns its type."""

    def test_settings_provider_returns_cached_settings(self, gui_env):
        settings = get_settings_dep()
        assert isinstance(settings, Settings)
        assert settings.parts_dir == (gui_env / "parts").resolve()
        # The *cached* settings, not a fresh read: two calls are one object.
        assert get_settings_dep() is get_settings()

    def test_library_provider_binds_the_configured_directory(self, gui_env):
        store = get_library()
        assert isinstance(store, LibraryStore)
        assert store.library_dir == (gui_env / "library").resolve()
        # Constructing a store has no filesystem side effects.
        assert not store.library_dir.exists()

    def test_session_store_provider_binds_the_configured_directory(self, gui_env):
        store = get_session_store()
        assert isinstance(store, SessionStore)
        assert store.sessions_dir == (gui_env / "sessions").resolve()

    def test_job_registry_is_process_wide_and_satisfies_the_protocol(self, gui_env):
        registry = get_job_registry()
        assert isinstance(registry, JobRegistryLike)
        # A run outlives the request that started it: same object every call.
        assert get_job_registry() is registry
        reset_job_registry()
        assert get_job_registry() is not registry


class TestGetRetriever:
    """`get_retriever` delegates scope rules; it never re-implements them."""

    def test_part_scope_returns_a_retriever(self, gui_env, resolve_scope_available):
        build_manifest(gui_env / "parts", "TEST")
        scope = get_retriever(ScopeRef(kind="part", name="TEST"))
        assert isinstance(scope, Retriever)
        assert scope.part == "TEST"

    def test_project_scope_returns_a_project_retriever(self, gui_env, resolve_scope_available):
        build_manifest(gui_env / "parts", "TEST")
        build_manifest(gui_env / "parts", "OTHER")
        settings = get_settings()
        save_project(
            Project(
                name="rf-frontend",
                parts=[
                    ProjectMember(part_number="TEST", role="transceiver"),
                    ProjectMember(part_number="OTHER", role="attenuator"),
                ],
            ),
            settings.projects_dir,
        )
        scope = get_retriever(ScopeRef(kind="project", name="rf-frontend"))
        assert isinstance(scope, ProjectRetriever)

    def test_family_scope_returns_a_family_retriever(self, gui_env, resolve_scope_available):
        """The third scope reaches the HTTP surface (phase 7, ticket 07).

        Declared into a *tmp* registry, never the packaged one: a test may not
        read or rewrite the families this repository ships.
        """
        from datasheet_analyzer.families.registry import (
            FamilyEntry,
            FamilyRegistry,
            families_path,
            save_families,
        )
        from datasheet_analyzer.retrieve.family import FamilyRetriever

        build_manifest(gui_env / "parts", "TEST")
        build_manifest(gui_env / "parts", "OTHER")
        registry_dir = gui_env / "registry"
        save_families(
            FamilyRegistry(
                families={
                    "TESTx": FamilyEntry(name="TESTx", title="fixture", members=["TEST", "OTHER"])
                }
            ),
            families_path(registry_dir),
        )
        os.environ["DSA_REGISTRY_DIR"] = str(registry_dir)
        try:
            reset_settings_cache()
            scope = get_retriever(ScopeRef(kind="family", name="TESTx"))
        finally:
            os.environ.pop("DSA_REGISTRY_DIR", None)
            reset_settings_cache()
        assert isinstance(scope, FamilyRetriever)
        assert scope.parts == ("TEST", "OTHER")
        assert scope.reference == "TEST", "a shared answer is cited from the first declared"

    def test_an_undeclared_family_is_400_and_never_inferred(self, gui_env, resolve_scope_available):
        with pytest.raises(HTTPException) as caught:
            get_retriever(ScopeRef(kind="family", name="AFE79xx"))
        assert caught.value.status_code == 400
        assert "never inferred from a part number" in caught.value.detail

    def test_unknown_part_is_400_carrying_the_refusal_text(self, gui_env, resolve_scope_available):
        with pytest.raises(HTTPException) as caught:
            get_retriever(ScopeRef(kind="part", name="NOSUCH"))
        assert caught.value.status_code == 400
        assert "no corpus for part NOSUCH" in caught.value.detail

    def test_empty_scope_carries_the_xor_refusal(self, gui_env, resolve_scope_available):
        with pytest.raises(HTTPException) as caught:
            get_retriever(ScopeRef(kind="part", name=""))
        assert caught.value.status_code == 400
        assert "exactly one of `part` or `project`" in caught.value.detail

    def test_unknown_part_reaches_the_client_as_a_400_body_not_a_500(
        self, gui_env, resolve_scope_available
    ):
        app = FastAPI()

        @app.post("/probe/retriever")
        def _probe(scope: ScopeRef) -> dict:
            return {"scope": type(get_retriever(scope)).__name__}

        response = TestClient(app).post("/probe/retriever", json={"kind": "part", "name": "NOSUCH"})
        assert response.status_code == 400
        assert "no corpus for part NOSUCH" in response.json()["detail"]


class TestOverridability:
    """Tickets 07–15 test their routers against fakes, not each other."""

    @staticmethod
    def _probe_app() -> FastAPI:
        app = FastAPI()

        @app.get("/probe/settings")
        def _settings(dep: Annotated[Settings, Depends(get_settings_dep)]) -> dict:
            return {"value": str(dep.parts_dir)}

        @app.get("/probe/library")
        def _library(dep: Annotated[object, Depends(get_library)]) -> dict:
            return {"value": str(dep.library_dir)}

        @app.get("/probe/sessions")
        def _sessions(dep: Annotated[object, Depends(get_session_store)]) -> dict:
            return {"value": str(dep.sessions_dir)}

        @app.get("/probe/jobs")
        def _jobs(dep: Annotated[object, Depends(get_job_registry)]) -> dict:
            return {"value": type(dep).__name__}

        @app.post("/probe/retriever")
        def _retriever(dep: Annotated[object, Depends(get_retriever)]) -> dict:
            return {"value": str(dep)}

        return app

    def test_each_provider_is_overridable(self, gui_env):
        app = self._probe_app()
        client = TestClient(app)

        app.dependency_overrides[get_settings_dep] = lambda: Settings(
            parts_dir=gui_env / "fake-parts"
        ).resolve()
        app.dependency_overrides[get_library] = lambda: LibraryStore(gui_env / "fake-library")
        app.dependency_overrides[get_session_store] = lambda: SessionStore(
            gui_env / "fake-sessions"
        )
        app.dependency_overrides[get_job_registry] = lambda: _FakeRegistry()
        app.dependency_overrides[get_retriever] = lambda: "fake-retriever"

        assert client.get("/probe/settings").json()["value"].endswith("fake-parts")
        assert client.get("/probe/library").json()["value"].endswith("fake-library")
        assert client.get("/probe/sessions").json()["value"].endswith("fake-sessions")
        assert client.get("/probe/jobs").json()["value"] == "_FakeRegistry"
        posted = client.post("/probe/retriever", json={"kind": "part", "name": "TEST"})
        assert posted.json()["value"] == "fake-retriever"

        app.dependency_overrides.clear()
        assert client.get("/probe/settings").json()["value"] == str((gui_env / "parts").resolve())


class _FakeRegistry:
    """A stand-in registry; overriding must not require ticket 07's module."""

    def start(self, *, directory: str, proposals: list) -> str:
        return "run-1"

    def exists(self, run_id: str) -> bool:
        return run_id == "run-1"

    def run(self, run_id: str) -> list:
        return []

    def snapshot(self, run_id: str):
        return None

    def events(self, run_id: str):
        return None


# --- catalog ------------------------------------------------------------------


class TestCatalogEndpoints:
    """`/api/parts` and `/api/projects` — the two calls the shell makes first."""

    def test_parts_lists_built_and_half_built_and_says_which(self, gui_env):
        build_manifest(gui_env / "parts", "TEST")
        (gui_env / "parts" / "HALFBUILT").mkdir(parents=True)
        client = TestClient(create_app(get_settings()))

        response = client.get("/api/parts")
        assert response.status_code == 200
        payload = PartsOut.model_validate(response.json())

        assert payload.count == 2
        assert [p.part_number for p in payload.parts] == ["HALFBUILT", "TEST"]
        half, built = payload.parts
        assert half.built is False
        assert (half.sections, half.specs, half.plots, half.revision) == (0, 0, 0, "")
        assert built.built is True
        assert built.revision == "SBASA41E"
        assert built.vendor == "ti"
        assert built.sections == 1
        assert built.specs == 3
        assert built.plots == 2
        assert built.tokens == 1234
        assert built.backends == ["pdf_layout"]
        assert built.spec_confidence == {"high": 2, "low": 1}
        # No `search_index.json` was published, so search is honestly absent.
        assert built.searchable is False

    def test_parts_on_an_empty_dir_is_an_empty_list_with_200(self, gui_env):
        client = TestClient(create_app(get_settings()))
        response = client.get("/api/parts")
        assert response.status_code == 200
        payload = PartsOut.model_validate(response.json())
        assert payload.parts == []
        assert payload.count == 0

    def test_projects_lists_members_roles_and_built_state(self, gui_env):
        build_manifest(gui_env / "parts", "TEST")
        settings = get_settings()
        save_project(
            Project(
                name="rf-frontend",
                parts=[
                    ProjectMember(part_number="TEST", role="transceiver"),
                    ProjectMember(part_number="UNBUILT", role="attenuator"),
                ],
                interfaces="TEST TX -> UNBUILT DSA",
                notes="bench board",
            ),
            settings.projects_dir,
        )
        client = TestClient(create_app(settings))

        response = client.get("/api/projects")
        assert response.status_code == 200
        payload = ProjectsOut.model_validate(response.json())

        assert payload.count == 1
        project = payload.projects[0]
        assert project.name == "rf-frontend"
        assert project.interfaces == "TEST TX -> UNBUILT DSA"
        assert project.notes == "bench board"
        # No PROJECT_INDEX.md was written, so the project is not built.
        assert project.built is False
        assert project.error == ""
        assert [(p.part_number, p.role, p.built) for p in project.parts] == [
            ("TEST", "transceiver", True),
            ("UNBUILT", "attenuator", False),
        ]

    def test_projects_with_no_projects_dir_is_an_empty_list_with_200(self, gui_env):
        settings = get_settings()
        assert not settings.projects_dir.exists()
        client = TestClient(create_app(settings))
        response = client.get("/api/projects")
        assert response.status_code == 200
        payload = ProjectsOut.model_validate(response.json())
        assert payload.projects == []
        assert payload.count == 0

    def test_catalog_router_is_auto_discovered_and_main_names_nothing(self, gui_env):
        """`main.py` is ticket 00's and stays unedited: discovery, not a registry."""
        main_source = (
            Path(__file__).resolve().parents[2] / "src" / "datasheet_analyzer" / "app" / "main.py"
        )
        text = main_source.read_text(encoding="utf-8")
        assert "catalog" not in text
        assert "include_router" in text

        app = create_app(get_settings())
        assert "catalog" not in app.state.router_errors
        assert {"/api/parts", "/api/projects"} <= set(app.openapi()["paths"])


# --- static -------------------------------------------------------------------


def _build_dist(root: Path) -> Path:
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>workbench</title><div id=root></div>", encoding="utf-8"
    )
    # Bytes, not text: this is compared byte-for-byte off the wire, and
    # Windows would translate the newline on the way in.
    (dist / "assets" / "app-abc123.js").write_bytes(b"export const x = 1;\n")
    # A root-level module too: it comes off the SPA catch-all rather than
    # the `assets` mount, and the two paths type their responses apart.
    (dist / "registerSW.js").write_bytes(b"export const y = 2;" + bytes([10]))
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return dist


class TestStatic:
    """`web/dist` present serves the SPA; absent serves only `/api/*`."""

    def test_dist_present_serves_index_and_falls_back_for_deep_links(self, gui_env):
        dist = _build_dist(gui_env / "web")
        app = create_app(get_settings())
        assert mount_static(app, settings=get_settings(), dist_dir=dist) is True
        client = TestClient(app)

        root = client.get("/")
        assert root.status_code == 200
        assert "workbench" in root.text

        deep = client.get("/chat/abc")
        assert deep.status_code == 200
        assert "workbench" in deep.text

        asset = client.get("/assets/app-abc123.js")
        assert asset.status_code == 200
        assert asset.text == "export const x = 1;\n"

        assert client.get("/favicon.svg").text == "<svg/>"

    def test_a_served_module_is_javascript_whatever_the_machine_says(self, gui_env, monkeypatch):
        """The defect: `mimetypes.guess_type` seeds itself from the Windows
        registry, and a machine whose `.js` key there carries
        `Content Type = text/plain` (measured on the one this was found on)
        served every Vite bundle as plain text. A browser applies strict MIME checking to
        `<script type="module">` and refuses such a response, so `dsa serve`
        in production mode rendered a blank page while `/api/*` answered.

        `guess_type` is forced to the broken answer here, so this fails on
        any build that still reads it --- including on a clean CI box whose
        registry is right and where the bug is otherwise invisible."""
        monkeypatch.setattr(mimetypes, "guess_type", lambda *a, **k: ("text/plain", None))
        dist = _build_dist(gui_env / "web")
        app = create_app(get_settings())
        mount_static(app, settings=get_settings(), dist_dir=dist)
        client = TestClient(app)

        mounted = client.get("/assets/app-abc123.js")
        assert mounted.status_code == 200
        assert mounted.headers["content-type"] == "text/javascript; charset=utf-8"

        spa_served = client.get("/registerSW.js")
        assert spa_served.status_code == 200
        assert spa_served.headers["content-type"] == "text/javascript; charset=utf-8"

        assert client.get("/").headers["content-type"] == "text/html; charset=utf-8"
        assert client.get("/favicon.svg").headers["content-type"] == "image/svg+xml"

    def test_the_media_type_table_is_read_by_suffix_and_never_guesses(self):
        assert static_module.web_media_type("bundle.MJS") == "text/javascript"
        assert static_module.web_media_type(Path("a/b/style.css")) == "text/css"
        # Unlisted: the response keeps its own default rather than being handed
        # a type this module has never measured.
        assert static_module.web_media_type("archive.tar.zst") is None

    def test_api_still_wins_over_the_spa_fallback(self, gui_env):
        dist = _build_dist(gui_env / "web")
        app = create_app(get_settings())
        mount_static(app, settings=get_settings(), dist_dir=dist)
        client = TestClient(app)

        assert client.get("/api/parts").status_code == 200
        missing = client.get("/api/nope")
        assert missing.status_code == 404
        assert "workbench" not in missing.text

    def test_traversal_is_refused_rather_than_normalized(self, gui_env):
        dist = _build_dist(gui_env / "web")
        (gui_env / "secret.txt").write_text("do-not-serve", encoding="utf-8")
        app = create_app(get_settings())
        mount_static(app, settings=get_settings(), dist_dir=dist)

        response = TestClient(app).get("/..%2F..%2Fsecret.txt")
        assert "do-not-serve" not in response.text

    def test_dist_absent_means_the_app_still_starts_and_serves_the_api(self, gui_env):
        app = create_app(get_settings())
        assert app.state.static_mounted is False
        client = TestClient(app)
        assert client.get("/api/parts").status_code == 200
        assert client.get("/").status_code == 404

    def test_mount_is_skipped_silently_when_dist_is_missing(self, gui_env):
        app = FastAPI()
        assert mount_static(app, settings=get_settings(), dist_dir=gui_env / "nope") is False
        # A dist directory with no index.html cannot serve an SPA either.
        empty = gui_env / "empty-dist"
        empty.mkdir()
        assert mount_static(app, settings=get_settings(), dist_dir=empty) is False

    def test_default_dist_dir_honours_the_env_override(self, gui_env, monkeypatch):
        monkeypatch.setenv(static_module.WEB_DIST_ENV, str(gui_env / "elsewhere"))
        assert static_module.default_dist_dir() == gui_env / "elsewhere"
        monkeypatch.delenv(static_module.WEB_DIST_ENV)
        assert static_module.default_dist_dir().name == "dist"
        assert static_module.default_dist_dir().parent.name == "web"
