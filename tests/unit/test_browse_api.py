"""Choosing a folder — the listing, and the dialog's honest failure.

Hermetic: `tmp_path` directories only, and the native dialog is never actually
opened. What matters about the dialog here is its *contract* — three distinct
outcomes, and a host with no display reporting `available=False` rather than
raising — because that flag is the only thing telling the client to fall back
to the in-app browser.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.app.routers import browse as browse_router
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
    yield made
    reset_settings_cache()


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(browse_router.router)
    app.dependency_overrides[get_settings_dep] = lambda: settings
    return TestClient(app)


def test_listing_a_directory_returns_only_its_subdirectories(
    client: TestClient, tmp_path: Path
) -> None:
    """It picks a *folder*; two hundred unselectable PDFs would be noise."""
    root = tmp_path / "work"
    (root / "radar").mkdir(parents=True)
    (root / "lna").mkdir()
    (root / "notes.pdf").write_bytes(b"%PDF-1.4")

    out = client.get("/api/browse/list", params={"path": str(root)}).json()

    assert [e["name"] for e in out["entries"]] == ["lna", "radar"]
    assert out["path"] == str(root)
    assert out["parent"] == str(tmp_path)


def test_hidden_directories_are_not_offered(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "work"
    (root / ".git").mkdir(parents=True)
    (root / "radar").mkdir()

    out = client.get("/api/browse/list", params={"path": str(root)}).json()
    assert [e["name"] for e in out["entries"]] == ["radar"]


def test_an_empty_path_lists_somewhere_to_start(client: TestClient) -> None:
    out = client.get("/api/browse/list", params={"path": ""}).json()
    assert out["entries"], "a browse with no path must offer a starting point"
    assert out["parent"] == ""


def test_listing_something_that_is_not_a_directory_is_a_400(
    client: TestClient, tmp_path: Path
) -> None:
    lonely = tmp_path / "file.txt"
    lonely.write_text("x", encoding="utf-8")
    response = client.get("/api/browse/list", params={"path": str(lonely)})
    assert response.status_code == 400
    assert "not a directory" in response.json()["detail"]


def test_a_host_with_no_dialog_reports_it_rather_than_failing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`available=False` is the signal to fall back — not an error to render."""
    import builtins

    real_import = builtins.__import__

    def no_tkinter(name, *args, **kwargs):
        if name == "tkinter":
            raise ImportError("no display name and no $DISPLAY environment variable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_tkinter)

    out = client.post("/api/browse/dialog").json()
    assert out["available"] is False
    assert out["picked"] is False
    assert "no native dialog" in out["reason"]


def test_cancelling_is_an_answer_and_not_a_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled dialog must not send the client to the fallback browser."""
    monkeypatch.setattr(browse_router, "_pick_directory", lambda: "", raising=False)

    class FakeDialog:
        @staticmethod
        def askdirectory(**_kwargs: object) -> str:
            return ""

    class FakeTk:
        def withdraw(self) -> None: ...
        def attributes(self, *_a: object) -> None: ...
        def destroy(self) -> None: ...

    import sys
    import types

    fake = types.ModuleType("tkinter")
    fake.Tk = FakeTk  # type: ignore[attr-defined]
    fake.filedialog = FakeDialog  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tkinter", fake)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", FakeDialog)

    out = client.post("/api/browse/dialog").json()
    assert out["available"] is True
    assert out["picked"] is False
    assert out["directory"] == ""
