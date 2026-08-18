"""Session persistence and export (ticket 15).

Hermetic by construction: no network, no live model, no browser. Everything
here runs against a real `SessionStore` over a `tmp_path` `sessions_dir` —
the store *is* the thing under test, so faking it would test nothing — and
the router is mounted alone, with `get_session_store` pointed at that same
temp directory.

What is asserted is the external behaviour of the seam: that a conversation
survives the round trip through disk with its citations, its scope and its
timestamps intact; that appending never rewrites history; that a caller
cannot choose the file its session is written to; and that both exports say
something true (and something valid) about the answers they carry — including
when there are none.

Citations are built through `retrieve.results.Citation` and
`CitationOut.from_citation`, not hand-assembled, so the `§4.5, p.7` the
markdown export prints is provably the retrieval core's own label rather than
a second copy of the format.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from datasheet_analyzer.app import sessions as sessions_module
from datasheet_analyzer.app.deps import get_session_store, get_settings_dep
from datasheet_analyzer.app.routers import sessions as sessions_router
from datasheet_analyzer.app.sessions import SessionStore
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.evalh.citations import load_golden_yaml
from datasheet_analyzer.models import (
    ChatMessage,
    ChatSession,
    CitationOut,
    GoldenQuestion,
    ScopeRef,
)
from datasheet_analyzer.retrieve.results import Citation

# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Env changes never leak between tests (AGENTS.md invariant 4)."""
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A temp tree; `sessions_dir` is the only directory this ticket writes."""
    return Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        projects_dir=tmp_path / "projects",
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
        anthropic_api_key="",
    ).resolve()


@pytest.fixture
def store(settings: Settings) -> SessionStore:
    return SessionStore.for_settings(settings)


@pytest.fixture
def client(settings: Settings, store: SessionStore) -> TestClient:
    """A minimal app holding only this ticket's router.

    Deliberately not `create_app()`: auto-discovery would import every other
    ticket's router, and this test must not depend on their state.
    """
    app = FastAPI()
    app.include_router(sessions_router.router)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_settings_dep] = lambda: settings
    return TestClient(app)


def citation(
    *,
    section: str = "4.5",
    page_start: int | None = 7,
    page_end: int | None = 7,
    part: str = "AD9081",
    doc: str = "ad9081.pdf",
) -> CitationOut:
    """A citation that came out of the retrieval core, label and all."""
    return CitationOut.from_citation(
        Citation(
            doc=doc,
            doc_hash="hash-1",
            section=section,
            page_start=page_start,
            page_end=page_end,
            part=part,
        )
    )


def answered(store: SessionStore, *, scope: str = "AD9081") -> ChatSession:
    """A session carrying one question, one cited answer."""
    session = store.create(title="Supply rails", scope=ScopeRef(kind="part", name=scope))
    store.append(
        session.id,
        ChatMessage(role="user", text="What is the maximum supply voltage?"),
    )
    return store.append(
        session.id,
        ChatMessage(
            role="assistant",
            text="The absolute maximum supply voltage is ±22 V.",
            citations=[citation()],
        ),
    )


# --- storage round trip -------------------------------------------------------


class TestRoundTrip:
    def test_session_survives_disk_unchanged(self, store: SessionStore, settings: Settings):
        """Citations, scope and timestamps come back exactly as they went in."""
        original = answered(store)

        # A second store over the same directory: nothing is served from the
        # writer's memory, so this is genuinely a read from disk.
        reloaded = SessionStore(settings.sessions_dir).get(original.id)

        assert reloaded == original
        assert reloaded.scope == ScopeRef(kind="part", name="AD9081")
        assert reloaded.created_at == original.created_at
        assert reloaded.updated_at == original.updated_at
        assert reloaded.messages[1].citations[0] == citation()
        assert reloaded.messages[1].citations[0].label == "§4.5, p.7"

    def test_append_bumps_updated_at_and_keeps_history(self, store: SessionStore):
        session = store.create(title="Rails", scope=ScopeRef(kind="part", name="AD9081"))
        first = ChatMessage(role="user", text="first question")
        store.append(session.id, first)
        before = store.get(session.id)

        after = store.append(session.id, ChatMessage(role="assistant", text="an answer"))

        assert after.updated_at > before.updated_at
        assert after.created_at == session.created_at
        assert after.messages[0] == first  # earlier turns untouched
        assert [m.role for m in after.messages] == ["user", "assistant"]
        assert store.get(session.id).messages[0] == first

    def test_unknown_id_is_none_not_an_error(self, store: SessionStore):
        assert store.get("nope") is None
        with pytest.raises(KeyError):
            store.append("nope", ChatMessage(role="user", text="hi"))

    def test_list_is_newest_first(self, store: SessionStore):
        oldest = store.create(title="oldest")
        middle = store.create(title="middle")
        newest = store.create(title="newest")
        # Explicit, well-separated timestamps: ordering must not depend on
        # how fast the machine ran the three creates.
        base = oldest.updated_at
        store.save(oldest.model_copy(update={"updated_at": base}))
        store.save(middle.model_copy(update={"updated_at": base + timedelta(minutes=1)}))
        store.save(newest.model_copy(update={"updated_at": base + timedelta(minutes=2)}))

        assert [s.title for s in store.list()] == ["newest", "middle", "oldest"]

    def test_missing_directory_lists_empty(self, tmp_path: Path):
        assert SessionStore(tmp_path / "never-created").list() == []


# --- durability ---------------------------------------------------------------


class TestDurability:
    def test_no_tmp_file_survives_a_save(self, store: SessionStore, settings: Settings):
        answered(store)
        assert list(settings.sessions_dir.glob("*.tmp")) == []
        assert [p.suffix for p in settings.sessions_dir.iterdir()] == [".json"]

    def test_failed_write_leaves_the_stored_session_intact(
        self, store: SessionStore, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ):
        """Atomicity, the only way it can be observed: a broken rename.

        The visible file flips at `os.replace()` or not at all, so a write
        that dies mid-flight must leave the previous transcript readable and
        no temp file behind.
        """
        session = answered(store)
        before = (settings.sessions_dir / f"{session.id}.json").read_bytes()

        def boom(src, dst):
            raise OSError("simulated rename failure")

        monkeypatch.setattr(sessions_module.os, "replace", boom)
        with pytest.raises(OSError):
            store.append(session.id, ChatMessage(role="assistant", text="lost turn"))

        assert (settings.sessions_dir / f"{session.id}.json").read_bytes() == before
        assert list(settings.sessions_dir.glob("*.tmp")) == []
        monkeypatch.setattr(sessions_module.os, "replace", os.replace)
        assert store.get(session.id).n_messages == 2

    def test_malformed_file_is_skipped_with_a_warning(
        self, store: SessionStore, settings: Settings, caplog: pytest.LogCaptureFixture
    ):
        """One truncated record must not cost the caller the whole list."""
        good = answered(store)
        settings.sessions_dir.mkdir(parents=True, exist_ok=True)
        (settings.sessions_dir / "truncated.json").write_text('{"id": "trunc"', encoding="utf-8")
        (settings.sessions_dir / "wrong-shape.json").write_text(
            json.dumps({"id": "x", "messages": "not a list"}), encoding="utf-8"
        )

        with caplog.at_level(logging.WARNING, logger="datasheet_analyzer.app.sessions"):
            listed = store.list()

        assert [s.id for s in listed] == [good.id]
        assert store.get("truncated") is None
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "truncated.json" in messages and "wrong-shape.json" in messages


# --- id safety ----------------------------------------------------------------


class TestIdSafety:
    @pytest.mark.parametrize(
        "hostile",
        ["../../pwned", "..", "a/b", "a\\b", "", "with space", "C:/abs"],
    )
    def test_hostile_ids_never_touch_the_filesystem(
        self, store: SessionStore, settings: Settings, hostile: str
    ):
        assert store.get(hostile) is None
        with pytest.raises(KeyError):
            store.append(hostile, ChatMessage(role="user", text="hi"))
        with pytest.raises(ValueError):
            store.save(ChatSession(id=hostile, title="t", scope=ScopeRef()))
        assert not settings.sessions_dir.exists() or list(settings.sessions_dir.iterdir()) == []

    def test_client_supplied_id_cannot_choose_the_filename(
        self, client: TestClient, settings: Settings, tmp_path: Path
    ):
        response = client.post(
            "/api/sessions",
            json={"title": "smuggled", "id": "../../pwned", "scope": {"kind": "part", "name": "X"}},
        )

        assert response.status_code == 200
        generated = response.json()["id"]
        assert generated != "../../pwned"
        written = sorted(p.name for p in settings.sessions_dir.iterdir())
        assert written == [f"{generated}.json"]
        assert not list(tmp_path.rglob("*pwned*"))


# --- HTTP surface -------------------------------------------------------------


class TestSessionsApi:
    def test_post_creates_a_session_and_returns_its_id(
        self, client: TestClient, settings: Settings
    ):
        response = client.post(
            "/api/sessions",
            json={"title": "Rails", "scope": {"kind": "part", "name": "AD9081"}},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["id"]
        assert body["title"] == "Rails"
        assert body["scope"] == {"kind": "part", "name": "AD9081"}
        assert body["messages"] == []
        assert body["n_messages"] == 0
        assert (settings.sessions_dir / f"{body['id']}.json").is_file()

    def test_list_is_newest_first_with_title_scope_and_count(
        self, client: TestClient, store: SessionStore
    ):
        older = store.create(title="older", scope=ScopeRef(kind="project", name="rx-frontend"))
        newer = answered(store)
        store.save(older.model_copy(update={"updated_at": newer.updated_at - timedelta(hours=1)}))

        body = client.get("/api/sessions").json()

        assert body["count"] == 2
        assert [row["id"] for row in body["sessions"]] == [newer.id, older.id]
        assert body["sessions"][0]["title"] == "Supply rails"
        assert body["sessions"][0]["scope"] == {"kind": "part", "name": "AD9081"}
        assert body["sessions"][0]["n_messages"] == 2
        assert body["sessions"][1]["scope"] == {"kind": "project", "name": "rx-frontend"}
        assert body["sessions"][1]["n_messages"] == 0

    def test_get_returns_the_transcript_with_citations_intact(
        self, client: TestClient, store: SessionStore
    ):
        session = answered(store)

        body = client.get(f"/api/sessions/{session.id}").json()

        assert body["n_messages"] == 2
        assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
        cited = body["messages"][1]["citations"]
        assert len(cited) == 1
        assert cited[0]["label"] == "§4.5, p.7"
        assert cited[0]["pages"] == "p.7"
        assert cited[0]["part"] == "AD9081"
        assert cited[0]["doc_hash"] == "hash-1"

    def test_unknown_session_is_404(self, client: TestClient):
        response = client.get("/api/sessions/does-not-exist")

        assert response.status_code == 404
        assert "does-not-exist" in response.json()["detail"]

    def test_unknown_session_export_is_404(self, client: TestClient):
        assert client.get("/api/sessions/nope/export").status_code == 404

    def test_unknown_export_format_is_rejected(self, client: TestClient, store: SessionStore):
        session = answered(store)

        assert client.get(f"/api/sessions/{session.id}/export?format=pdf").status_code == 422


# --- markdown export ----------------------------------------------------------


class TestMarkdownExport:
    def test_export_carries_answer_citation_and_part(self, client: TestClient, store: SessionStore):
        session = answered(store)

        response = client.get(f"/api/sessions/{session.id}/export?format=markdown")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        text = response.text
        assert "What is the maximum supply voltage?" in text
        assert "The absolute maximum supply voltage is ±22 V." in text
        # The citation, in the repo's own form, and the part it was answered
        # under — which `Citation.label` deliberately omits.
        assert "§4.5, p.7" in text
        assert "AD9081 — §4.5, p.7" in text
        assert "Supply rails" in text

    def test_markdown_is_the_default_format(self, client: TestClient, store: SessionStore):
        session = answered(store)

        assert client.get(f"/api/sessions/{session.id}/export").text == store.export_markdown(
            session.id
        )

    def test_project_scope_prints_each_hit_s_own_part(self, store: SessionStore):
        session = store.create(title="Chain", scope=ScopeRef(kind="project", name="rx-frontend"))
        store.append(session.id, ChatMessage(role="user", text="Which parts set the rails?"))
        store.append(
            session.id,
            ChatMessage(
                role="assistant",
                text="Both rails are 3.3 V.",
                citations=[citation(part="AD9081"), citation(part="HMC520A", section="6.1")],
            ),
        )

        text = store.export_markdown(session.id)

        assert "project: rx-frontend" in text
        assert "AD9081 — §4.5, p.7" in text
        assert "HMC520A — §6.1, p.7" in text

    def test_unpinned_citation_stays_honest(self, store: SessionStore):
        session = store.create(title="Unpinned", scope=ScopeRef(kind="part", name="AD9081"))
        store.append(session.id, ChatMessage(role="user", text="Where is that stated?"))
        store.append(
            session.id,
            ChatMessage(
                role="assistant",
                text="Stated in the overview.",
                citations=[citation(section="", page_start=None, page_end=None)],
            ),
        )

        assert "p.?" in store.export_markdown(session.id)

    def test_empty_session_exports_a_valid_document(self, client: TestClient, store: SessionStore):
        """No assistant messages is an empty document, never an error."""
        session = store.create(title="Nothing asked yet")

        response = client.get(f"/api/sessions/{session.id}/export?format=markdown")

        assert response.status_code == 200
        assert response.text.startswith("# Nothing asked yet")
        assert "No answers recorded" in response.text


# --- golden-Q&A export --------------------------------------------------------


class TestGoldenExport:
    def test_entries_match_the_existing_fixture_schema(
        self, client: TestClient, store: SessionStore, tmp_path: Path
    ):
        session = answered(store)

        response = client.get(f"/api/sessions/{session.id}/export?format=golden")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/yaml")
        assert "golden_qa_AD9081.yaml" in response.headers["content-disposition"]
        data = yaml.safe_load(response.text)
        entry = data["questions"][0]
        assert set(entry) >= {"id", "question", "expected_substrings", "pages"}
        assert entry["question"] == "What is the maximum supply voltage?"
        assert entry["expected_substrings"] == ["±22 V"]
        assert entry["pages"] == [7]
        assert entry["id"].startswith("q01-")
        # The real loader is the schema: if this validates, the file drops
        # straight into tests/fixtures/.
        fixture = tmp_path / "golden_qa_AD9081.yaml"
        fixture.write_text(response.text, encoding="utf-8")
        loaded = load_golden_yaml(fixture)
        assert loaded == [GoldenQuestion.model_validate(entry)]
        assert loaded[0].pages == [7]

    def test_pages_come_from_citations_only(self, store: SessionStore):
        """A range contributes its pages; an unpinned citation contributes none."""
        session = store.create(title="Ranges", scope=ScopeRef(kind="part", name="AD9081"))
        store.append(session.id, ChatMessage(role="user", text="Where are the specs?"))
        store.append(
            session.id,
            ChatMessage(
                role="assistant",
                text="Specified across the electrical tables.",
                citations=[
                    citation(page_start=29, page_end=31),
                    citation(page_start=None, page_end=None),
                    citation(page_start=7, page_end=7),
                ],
            ),
        )

        entry = yaml.safe_load(store.export_golden(session.id))["questions"][0]

        assert entry["pages"] == [7, 29, 30, 31]

    def test_a_page_reference_in_prose_is_not_an_expected_value(self, store: SessionStore):
        session = store.create(title="Prose", scope=ScopeRef(kind="part", name="LM741"))
        store.append(session.id, ChatMessage(role="user", text="What is the dissipation?"))
        store.append(
            session.id,
            ChatMessage(
                role="assistant",
                text="Maximum power dissipation is 500 mW (§6.1, p.4).",
                citations=[citation(section="6.1", page_start=4, page_end=4, part="LM741")],
            ),
        )

        entry = yaml.safe_load(store.export_golden(session.id))["questions"][0]

        assert entry["expected_substrings"] == ["500 mW"]
        assert entry["pages"] == [4]

    def test_a_qualitative_answer_falls_back_to_its_own_words(self, store: SessionStore):
        session = store.create(title="Qualitative", scope=ScopeRef(kind="part", name="LM741"))
        store.append(session.id, ChatMessage(role="user", text="Does it latch up?"))
        store.append(
            session.id,
            ChatMessage(
                role="assistant",
                text="The device features No Latch-Up behavior.",
                citations=[citation(section="1", page_start=1, page_end=1, part="LM741")],
            ),
        )

        entry = yaml.safe_load(store.export_golden(session.id))["questions"][0]

        assert entry["expected_substrings"] == ["The device features No Latch-Up behavior."]
        assert GoldenQuestion.model_validate(entry).kind == "direct"

    def test_every_answer_becomes_one_entry(self, store: SessionStore):
        session = answered(store)
        store.append(session.id, ChatMessage(role="user", text="And the current?"))
        store.append(
            session.id,
            ChatMessage(role="assistant", text="Typically 1.7 mA.", citations=[citation()]),
        )

        entries = yaml.safe_load(store.export_golden(session.id))["questions"]

        assert [e["id"][:3] for e in entries] == ["q01", "q02"]
        assert entries[1]["question"] == "And the current?"
        assert entries[1]["expected_substrings"] == ["1.7 mA"]

    def test_empty_session_exports_a_valid_empty_document(
        self, client: TestClient, store: SessionStore
    ):
        session = store.create(title="Nothing asked yet")

        response = client.get(f"/api/sessions/{session.id}/export?format=golden")

        assert response.status_code == 200
        assert yaml.safe_load(response.text) == {"questions": []}
