"""Writing to a project — the working-set endpoints.

Hermetic by construction: no network, no live model, no browser. The only
filesystem is a `tmp_path` `parts_dir` / `projects_dir` these tests build, and
`Settings` is injected through `dependency_overrides` so nothing reads the
environment.

The behaviour under test is the seam, not the store: which writes are
accepted, what a rejection says, and — the assertion that matters most — that
curating a project never touches a corpus. A project is a view; leaving one
must not delete anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.app.routers import catalog as catalog_router
from datasheet_analyzer.app.routers import projects as projects_router
from datasheet_analyzer.config import Settings, reset_settings_cache


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    reset_settings_cache()
    made = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / "cache",
        projects_dir=tmp_path / "projects",
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
    ).resolve()
    made.parts_dir.mkdir(parents=True, exist_ok=True)
    made.projects_dir.mkdir(parents=True, exist_ok=True)
    yield made
    reset_settings_cache()


def build_part(settings: Settings, part_number: str) -> Path:
    """The smallest thing `is_built`/`add_parts` will accept as a real part."""
    part_dir = settings.parts_dir / part_number
    (part_dir / "docs").mkdir(parents=True, exist_ok=True)
    (part_dir / "manifest.json").write_text(
        json.dumps({"part_number": part_number, "documents": [], "sections": []}),
        encoding="utf-8",
    )
    return part_dir


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(projects_router.router)
    app.include_router(catalog_router.router)
    app.dependency_overrides[get_settings_dep] = lambda: settings
    return TestClient(app)


def test_a_new_project_starts_empty_and_is_listed(client: TestClient) -> None:
    created = client.post("/api/projects", json={"name": "lna-front-end"})
    assert created.status_code == 201
    assert created.json()["name"] == "lna-front-end"
    assert created.json()["parts"] == []

    listed = client.get("/api/projects").json()
    assert [row["name"] for row in listed["projects"]] == ["lna-front-end"]


def test_reusing_a_project_name_is_a_conflict_not_a_silent_overwrite(
    client: TestClient,
) -> None:
    client.post("/api/projects", json={"name": "lna-front-end"})
    again = client.post("/api/projects", json={"name": "lna-front-end"})
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]


def test_parts_move_into_and_out_of_a_project(client: TestClient, settings: Settings) -> None:
    build_part(settings, "AFE7950")
    build_part(settings, "LMX1204")
    client.post("/api/projects", json={"name": "rx-chain"})

    added = client.post("/api/projects/rx-chain/parts", json={"parts": ["AFE7950", "LMX1204"]})
    assert added.status_code == 200
    assert [row["part_number"] for row in added.json()["parts"]] == ["AFE7950", "LMX1204"]

    removed = client.delete("/api/projects/rx-chain/parts/LMX1204")
    assert removed.status_code == 200
    assert [row["part_number"] for row in removed.json()["parts"]] == ["AFE7950"]


def test_leaving_a_project_never_deletes_the_corpus(client: TestClient, settings: Settings) -> None:
    """The load-bearing one: a project is a view over parts, not a container."""
    part_dir = build_part(settings, "AFE7950")
    manifest = (part_dir / "manifest.json").read_bytes()
    client.post("/api/projects", json={"name": "rx-chain"})
    client.post("/api/projects/rx-chain/parts", json={"parts": ["AFE7950"]})

    client.delete("/api/projects/rx-chain/parts/AFE7950")

    assert part_dir.exists()
    assert (part_dir / "manifest.json").read_bytes() == manifest


def test_removing_a_part_the_project_never_held_is_not_an_error(client: TestClient) -> None:
    """The caller asked for a project without that part; that is the state."""
    client.post("/api/projects", json={"name": "rx-chain"})
    response = client.delete("/api/projects/rx-chain/parts/NEVER-ADDED")
    assert response.status_code == 200
    assert response.json()["parts"] == []


def test_adding_a_part_that_was_never_analyzed_is_refused_with_the_reason(
    client: TestClient,
) -> None:
    client.post("/api/projects", json={"name": "rx-chain"})
    response = client.post("/api/projects/rx-chain/parts", json={"parts": ["NOT-A-PART"]})
    assert response.status_code == 400
    assert "NOT-A-PART" in response.json()["detail"]


def test_writing_to_an_unknown_project_is_a_404_naming_it(client: TestClient) -> None:
    response = client.post("/api/projects/nope/parts", json={"parts": []})
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


def test_a_write_returns_the_shape_a_later_get_would_show(
    client: TestClient, settings: Settings
) -> None:
    """So a screen can replace its row with the response and not re-fetch."""
    build_part(settings, "AFE7950")
    client.post("/api/projects", json={"name": "rx-chain"})
    written = client.post("/api/projects/rx-chain/parts", json={"parts": ["AFE7950"]}).json()

    fetched = next(
        row for row in client.get("/api/projects").json()["projects"] if row["name"] == "rx-chain"
    )
    assert written == fetched


def test_an_illegal_project_name_is_a_400_that_says_what_is_legal(client: TestClient) -> None:
    """Not a 500. `exists()` validates the name too, so the guard must cover it."""
    response = client.post("/api/projects", json={"name": "LNA front-end"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "invalid project name" in detail
    assert "rf-frontend" in detail


# --- ticket 28: a project remembers its directory --------------------------------


def test_a_project_round_trips_its_directory(client: TestClient) -> None:
    client.post("/api/projects", json={"name": "rx-chain"})
    patched = client.patch("/api/projects/rx-chain", json={"directory": "D:/shelf/rx"})
    assert patched.status_code == 200
    assert patched.json()["directory"] == "D:/shelf/rx"

    listed = client.get("/api/projects").json()["projects"][0]
    assert listed["directory"] == "D:/shelf/rx"


def test_a_project_written_before_this_field_still_loads(
    client: TestClient, settings: Settings
) -> None:
    """Additive and backward compatible: an old file reads `directory == ""`."""
    old = settings.projects_dir / "legacy"
    old.mkdir(parents=True, exist_ok=True)
    (old / "project.json").write_text(
        json.dumps(
            {
                "name": "legacy",
                "parts": [],
                "interfaces": "",
                "notes": "",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    row = next(r for r in client.get("/api/projects").json()["projects"] if r["name"] == "legacy")
    assert row["error"] == ""
    assert row["directory"] == ""


def test_patch_leaves_the_fields_it_was_not_given_alone(
    client: TestClient, settings: Settings
) -> None:
    """`None` means "leave it alone", so editing one cannot blank the others."""
    build_part(settings, "AFE7950")
    client.post("/api/projects", json={"name": "rx-chain", "notes": "keep me"})
    client.post("/api/projects/rx-chain/parts", json={"parts": ["AFE7950"]})

    row = client.patch("/api/projects/rx-chain", json={"directory": "D:/shelf/rx"}).json()
    assert row["notes"] == "keep me"
    assert [p["part_number"] for p in row["parts"]] == ["AFE7950"]

    row = client.patch("/api/projects/rx-chain", json={"notes": "changed"}).json()
    assert row["directory"] == "D:/shelf/rx"
    assert row["notes"] == "changed"


def test_patching_an_unknown_project_is_a_404_naming_it(client: TestClient) -> None:
    response = client.patch("/api/projects/nope", json={"directory": "D:/x"})
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]
