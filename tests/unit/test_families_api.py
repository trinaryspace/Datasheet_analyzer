"""`GET /api/families`, and the scope resolver reading the same declaration.

Hermetic: `tmp_path` only, no network, no model, no built corpus beyond a
`manifest.json` touched into place to make `is_built` true.

The whole file is about one rule, tested from both ends. **A family is
declared, never inferred.** So the endpoint may only ever return what a human
wrote in `registry/families.yaml` — not a proposal, not an unconfirmed entry,
not an empty one — and a name it did not return must come back from the API as
the registry's own refusal rather than as an empty answer. If either half slips,
a pane can put another part's numbers in front of a designer with no visible
seam, which is the failure the whole noun exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from datasheet_analyzer.app import chat as chat_module
from datasheet_analyzer.app.deps import get_retriever, get_settings_dep
from datasheet_analyzer.app.routers import families as families_router
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.families import (
    FamilyEntry,
    FamilyRegistry,
    candidates_path,
    families_path,
    save_candidates,
    save_families,
)
from datasheet_analyzer.models import ScopeRef


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    reset_settings_cache()
    made = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / "cache",
        projects_dir=tmp_path / "projects",
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
        registry_dir=tmp_path / "registry",
    ).resolve()
    (tmp_path / "registry").mkdir(parents=True, exist_ok=True)
    yield made
    reset_settings_cache()


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(families_router.router)
    app.dependency_overrides[get_settings_dep] = lambda: settings
    return TestClient(app)


def declare(settings: Settings, **fields) -> None:
    """Write one entry into the real `families.yaml`, through the real writer."""
    registry = FamilyRegistry()
    registry.put(FamilyEntry(**fields))
    save_families(registry, families_path(settings.registry_dir))


def build(settings: Settings, part: str) -> None:
    """The minimum that makes `is_built` true: a manifest beside the part."""
    directory = settings.parts_dir / part
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text("{}", encoding="utf-8")


class TestDeclaredFamiliesEndpoint:
    def test_a_shelf_with_no_registry_lists_nothing_with_200(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A shelf with no declaration answers "none", and answers it with 200."""
        assert not families_path(settings.registry_dir).exists()

        response = client.get("/api/families")

        assert response.status_code == 200
        assert response.json() == {"families": [], "count": 0}

    def test_a_declared_family_is_listed_whole(
        self, client: TestClient, settings: Settings
    ) -> None:
        declare(
            settings,
            name="AFE795x",
            title="AFE79xx RF-sampling transceivers",
            members=["AFE7950", "AFE7953"],
            note="one document template, 39 identically-titled sections",
        )
        build(settings, "AFE7950")

        body = client.get("/api/families").json()

        assert body["count"] == 1
        (family,) = body["families"]
        assert family["name"] == "AFE795x"
        assert family["title"] == "AFE79xx RF-sampling transceivers"
        assert family["members"] == ["AFE7950", "AFE7953"]
        # The reference is the first member declared: what every delta is
        # signed against, so a pane can say which document it is reading.
        assert family["reference"] == "AFE7950"
        assert "39 identically-titled sections" in family["note"]
        # Reported, not filtered: a partly built family is still declared.
        assert family["unbuilt_members"] == ["AFE7953"]

    def test_an_unconfirmed_entry_is_not_offered(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A hand-copied `confirmed: false` builds nothing and offers nothing."""
        declare(settings, name="AFE795x", members=["AFE7950", "AFE7953"], confirmed=False)

        assert client.get("/api/families").json() == {"families": [], "count": 0}

    def test_a_family_with_no_members_is_not_offered(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A family of nothing shares nothing; offering it would be an empty scope."""
        declare(settings, name="AFE795x", title="a heading and no devices", members=[])

        assert client.get("/api/families").json() == {"families": [], "count": 0}

    def test_the_candidate_file_is_never_read(self, client: TestClient, settings: Settings) -> None:
        """A proposal is not a declaration, and this route reads only the latter."""
        save_candidates(
            [FamilyEntry(name="LMX120x", members=["LMX1204", "LMX1214"])],
            candidates_path(settings.registry_dir),
        )
        assert candidates_path(settings.registry_dir).exists()

        assert client.get("/api/families").json() == {"families": [], "count": 0}

    def test_families_are_name_ordered(self, client: TestClient, settings: Settings) -> None:
        registry = FamilyRegistry()
        registry.put(FamilyEntry(name="LMX120x", members=["LMX1204"]))
        registry.put(FamilyEntry(name="AFE795x", members=["AFE7950"]))
        save_families(registry, families_path(settings.registry_dir))

        names = [f["name"] for f in client.get("/api/families").json()["families"]]

        assert names == ["AFE795x", "LMX120x"]


class TestTheResolverReadsTheSameDeclaration:
    def test_a_declared_family_named_in_a_question_is_offered(self, settings: Settings) -> None:
        declare(settings, name="AFE795x", members=["AFE7950", "AFE7953"])
        build(settings, "AFE7950")

        _parts, _projects, families = chat_module.known_scopes(settings)
        assert families == ["AFE795x"]

        result = chat_module.resolve_question("what changes across the AFE795x?", settings=settings)

        assert result.confident is False
        assert ScopeRef(kind="family", name="AFE795x") in result.candidates
        assert result.matched_via == "family-declared"

    def test_an_unconfirmed_family_is_invisible_to_the_resolver(self, settings: Settings) -> None:
        """One declaration, read one way: what the picker hides, the resolver hides."""
        declare(settings, name="AFE795x", members=["AFE7950"], confirmed=False)

        _, _, families = chat_module.known_scopes(settings)

        assert families == []
        result = chat_module.resolve_question("about the AFE795x?", settings=settings)
        assert all(ref.kind != "family" for ref in result.candidates)


class TestAnUndeclaredFamilyIsRefusedNotEmptied:
    def test_get_retriever_400s_with_the_registrys_own_words(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refusal a pane renders: it names the fix, not just the failure."""
        monkeypatch.setattr(
            "datasheet_analyzer.app.deps.get_settings_dep", lambda: settings, raising=True
        )
        declare(settings, name="AFE795x", members=["AFE7950"])
        build(settings, "AFE7950")

        with pytest.raises(HTTPException) as raised:
            get_retriever(ScopeRef(kind="family", name="LMX120x"))

        assert raised.value.status_code == 400
        detail = str(raised.value.detail)
        assert "no declared family 'LMX120x'" in detail
        assert "never inferred from a part number" in detail
        # The declared set is recited, so the reader can pick a real one.
        assert "AFE795x" in detail
        assert "dsa family confirm LMX120x" in detail

    def test_a_declared_family_resolves_to_a_retriever(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "datasheet_analyzer.app.deps.get_settings_dep", lambda: settings, raising=True
        )
        declare(settings, name="AFE795x", members=["AFE7950"])
        build(settings, "AFE7950")

        retriever = get_retriever(ScopeRef(kind="family", name="AFE795x"))

        assert retriever is not None
