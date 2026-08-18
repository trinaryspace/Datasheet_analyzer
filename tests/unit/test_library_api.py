"""Library and label endpoints (ticket 09).

Hermetic by construction: no network, no live model, no real `LibraryStore`.
The store is a fake injected through `dependency_overrides`, and the only
filesystem the router reads is a `tmp_path` `parts_dir` these tests build.

What is asserted here is the *external behaviour of the seam*: which parts a
document reaches, what a patch validates, and — as load-bearing as either —
what a patch leaves alone. `parts/` and the extraction cache are byte-for-byte
untouched by every write on this surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from datasheet_analyzer.app.deps import get_library, get_settings_dep
from datasheet_analyzer.app.routers import library as library_router
from datasheet_analyzer.config import LIBRARY_SCHEMA_VERSION, Settings, reset_settings_cache
from datasheet_analyzer.models import Applicability, DocType, LibraryDocument, SourceDocument

# --- fakes --------------------------------------------------------------------


class FakeLibraryStore:
    """An in-memory `LibraryStore` honouring the surface ticket 00 froze.

    Only the store's *contract* is modelled — notably `put()` preserving
    stored labels, since labels are user annotation and a build must never
    destroy them. Nothing here mirrors ticket 01's on-disk implementation.
    """

    def __init__(self, documents: list[LibraryDocument] | None = None) -> None:
        self._docs: dict[str, LibraryDocument] = {}
        for doc in documents or []:
            self.put(doc)

    def get(self, content_hash: str) -> LibraryDocument | None:
        return self._docs.get(content_hash)

    def put(self, doc: LibraryDocument) -> None:
        existing = self._docs.get(doc.content_hash)
        labels = list(existing.labels) if existing is not None else list(doc.labels)
        self._docs[doc.content_hash] = doc.model_copy(
            update={"labels": labels, "schema_version": LIBRARY_SCHEMA_VERSION}
        )

    def all(self) -> list[LibraryDocument]:
        return [self._docs[key] for key in sorted(self._docs)]

    def for_part(self, part_number: str) -> list[LibraryDocument]:
        return [doc for doc in self.all() if doc.covers(part_number)]

    def set_applicability(self, content_hash: str, applicability: Applicability):
        doc = self._docs[content_hash]
        updated = doc.model_copy(update={"applicability": applicability})
        self._docs[content_hash] = updated
        return updated

    def set_labels(self, content_hash: str, labels: list[str]):
        doc = self._docs[content_hash]
        updated = doc.model_copy(update={"labels": list(labels)})
        self._docs[content_hash] = updated
        return updated


def make_doc(
    content_hash: str,
    *,
    filename: str = "doc.pdf",
    part_number: str = "",
    applicability: Applicability | None = None,
    labels: list[str] | None = None,
    doc_type: DocType = DocType.DATASHEET,
) -> LibraryDocument:
    return LibraryDocument(
        source=SourceDocument(
            content_hash=content_hash,
            path=f"C:/pdfs/{filename}",
            part_number=part_number,
            doc_type=doc_type,
            page_count=7,
            vendor="ti",
        ),
        applicability=applicability or Applicability.for_all(evidence="fallback: no part token"),
        labels=list(labels or []),
    )


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Env changes never leak between tests (AGENTS.md invariant 4)."""
    reset_settings_cache()
    yield
    reset_settings_cache()


def write_built_part(parts_dir: Path, part_number: str, *, doc_hashes: list[str]) -> None:
    """A part directory that carries a manifest referencing these documents."""
    part_dir = parts_dir / part_number
    part_dir.mkdir(parents=True, exist_ok=True)
    (part_dir / "manifest.json").write_text(
        json.dumps(
            {
                "part_number": part_number,
                "pipeline_version": "0.4.0",
                "documents": [
                    {"content_hash": h, "path": f"C:/pdfs/{h}.pdf", "part_number": part_number}
                    for h in doc_hashes
                ],
                "sections": [],
            }
        ),
        encoding="utf-8",
    )


def write_unbuilt_part(parts_dir: Path, part_number: str) -> None:
    """A part directory with no manifest — half-built, and honestly so."""
    (parts_dir / part_number).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def env(tmp_path: Path):
    """A temp corpus tree plus the settings the router reads it through."""
    parts_dir = tmp_path / "parts"
    cache_dir = tmp_path / ".cache"
    parts_dir.mkdir()
    (cache_dir / "extract").mkdir(parents=True)
    (cache_dir / "extract" / "aaaa__pdf_layout.json").write_text('{"ok": true}', encoding="utf-8")
    settings = Settings(
        parts_dir=parts_dir,
        cache_dir=cache_dir,
        projects_dir=tmp_path / "projects",
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
        anthropic_api_key="",
    ).resolve()
    return settings


def make_client(settings: Settings, store: FakeLibraryStore) -> TestClient:
    """A minimal app holding only this ticket's router.

    Deliberately not `create_app()`: auto-discovery would import every other
    ticket's router, and this test must not depend on their state.
    """
    app = FastAPI()
    app.include_router(library_router.router)
    app.dependency_overrides[get_library] = lambda: store
    app.dependency_overrides[get_settings_dep] = lambda: settings
    return TestClient(app)


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    """Every file under `root` as (bytes, mtime_ns) — a write shows up here."""
    out: dict[str, tuple[bytes, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = (path.read_bytes(), path.stat().st_mtime_ns)
    return out


def by_hash(payload: dict, content_hash: str) -> dict:
    return next(d for d in payload["documents"] if d["content_hash"] == content_hash)


# --- GET /api/library ---------------------------------------------------------


class TestListLibrary:
    def test_lists_applicability_labels_and_parts_reached(self, env):
        write_built_part(env.parts_dir, "AD9081", doc_hashes=["hash-ds"])
        write_unbuilt_part(env.parts_dir, "AFE7950")
        store = FakeLibraryStore(
            [
                make_doc(
                    "hash-ds",
                    filename="ad9081.pdf",
                    part_number="AD9081",
                    applicability=Applicability.for_parts(["AD9081"], evidence="title block"),
                    labels=["reviewed", "jesd204"],
                ),
                make_doc(
                    "hash-an",
                    filename="afe79xx-jesd.pdf",
                    applicability=Applicability.for_family("AFE79xx", evidence="title: AFE79xx"),
                    doc_type=DocType.APP_NOTE,
                ),
                make_doc("hash-misc", filename="thermal.pdf"),
            ]
        )
        client = make_client(env, store)

        response = client.get("/api/library")
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 3
        # The label union feeds the editor's autocomplete in one request.
        assert payload["labels"] == ["jesd204", "reviewed"]

        datasheet = by_hash(payload, "hash-ds")
        assert datasheet["applicability"]["kind"] == "parts"
        assert datasheet["applicability"]["parts"] == ["AD9081"]
        assert datasheet["labels"] == ["reviewed", "jesd204"]
        assert datasheet["parts_reached"] == ["AD9081"]
        assert datasheet["filename"] == "ad9081.pdf"
        assert datasheet["doc_type"] == "datasheet"
        assert datasheet["page_count"] == 7

        app_note = by_hash(payload, "hash-an")
        assert app_note["parts_reached"] == ["AFE7950"]
        assert app_note["unbuilt_parts"] == ["AFE7950"]

        # kind="all" reaches every part the library can name.
        assert by_hash(payload, "hash-misc")["parts_reached"] == ["AD9081", "AFE7950"]

    def test_empty_library_is_an_empty_list_with_200(self, env):
        client = make_client(env, FakeLibraryStore())

        response = client.get("/api/library")
        assert response.status_code == 200
        assert response.json() == {"documents": [], "count": 0, "labels": []}

    def test_rebuild_needed_names_parts_whose_corpus_lacks_the_document(self, env):
        write_built_part(env.parts_dir, "AD9081", doc_hashes=["hash-ds"])
        store = FakeLibraryStore(
            [
                make_doc(
                    "hash-ds",
                    part_number="AD9081",
                    applicability=Applicability.for_parts(["AD9081"], evidence="title block"),
                ),
                make_doc(
                    "hash-new", applicability=Applicability.for_parts(["AD9081"], evidence="x")
                ),
            ]
        )
        client = make_client(env, store)

        payload = client.get("/api/library").json()
        # Already published into AD9081's corpus: nothing to rebuild.
        assert by_hash(payload, "hash-ds")["rebuild_needed"] == []
        # Reaches AD9081 but the built manifest has never seen it.
        assert by_hash(payload, "hash-new")["parts_reached"] == ["AD9081"]
        assert by_hash(payload, "hash-new")["unbuilt_parts"] == []
        assert by_hash(payload, "hash-new")["rebuild_needed"] == ["AD9081"]


# --- PATCH /api/library/{content_hash} ----------------------------------------


class TestPatchLibraryDocument:
    def test_labels_only_leaves_applicability_untouched(self, env):
        store = FakeLibraryStore(
            [
                make_doc(
                    "hash-ds",
                    applicability=Applicability.for_parts(["AD9081"], evidence="title block"),
                    labels=["draft"],
                )
            ]
        )
        client = make_client(env, store)

        response = client.patch("/api/library/hash-ds", json={"labels": ["reviewed", "thermal"]})
        assert response.status_code == 200
        body = response.json()
        assert body["labels"] == ["reviewed", "thermal"]
        assert body["applicability"] == {
            "kind": "parts",
            "parts": ["AD9081"],
            "family": "",
            "evidence": "title block",
        }
        stored = store.get("hash-ds")
        assert stored.labels == ["reviewed", "thermal"]
        assert stored.applicability.kind == "parts"
        assert stored.applicability.evidence == "title block"

    def test_applicability_only_leaves_labels_untouched(self, env):
        store = FakeLibraryStore(
            [make_doc("hash-ds", applicability=Applicability.for_all(), labels=["reviewed"])]
        )
        client = make_client(env, store)

        response = client.patch(
            "/api/library/hash-ds",
            json={"applicability": {"kind": "family", "family": "AFE79xx", "evidence": "by hand"}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["applicability"]["kind"] == "family"
        assert body["applicability"]["family"] == "AFE79xx"
        assert body["labels"] == ["reviewed"]
        assert store.get("hash-ds").labels == ["reviewed"]

    def test_both_change_in_one_write(self, env):
        store = FakeLibraryStore([make_doc("hash-ds", labels=["draft"])])
        client = make_client(env, store)

        response = client.patch(
            "/api/library/hash-ds",
            json={
                "applicability": {"kind": "parts", "parts": ["AD9081", "AD9082"]},
                "labels": ["reviewed"],
            },
        )
        assert response.status_code == 200
        stored = store.get("hash-ds")
        assert stored.applicability.kind == "parts"
        assert stored.applicability.parts == ["AD9081", "AD9082"]
        assert stored.labels == ["reviewed"]
        assert response.json()["parts_reached"] == ["AD9081", "AD9082"]

    def test_empty_label_list_clears_labels(self, env):
        store = FakeLibraryStore([make_doc("hash-ds", labels=["draft", "thermal"])])
        client = make_client(env, store)

        response = client.patch("/api/library/hash-ds", json={"labels": []})
        assert response.status_code == 200
        assert response.json()["labels"] == []
        assert store.get("hash-ds").labels == []

    def test_unknown_content_hash_is_404(self, env):
        client = make_client(env, FakeLibraryStore([make_doc("hash-ds")]))

        response = client.patch("/api/library/nope", json={"labels": ["reviewed"]})
        assert response.status_code == 404
        assert "nope" in response.json()["detail"]

    def test_parts_kind_with_no_parts_is_400(self, env):
        store = FakeLibraryStore(
            [make_doc("hash-ds", applicability=Applicability.for_all(evidence="fallback"))]
        )
        client = make_client(env, store)

        response = client.patch(
            "/api/library/hash-ds", json={"applicability": {"kind": "parts", "parts": []}}
        )
        assert response.status_code == 400
        assert "part number" in response.json()["detail"]
        # Refused, not silently written: the stored value is unchanged.
        assert store.get("hash-ds").applicability.kind == "all"

    def test_parts_kind_of_only_blank_names_is_400(self, env):
        store = FakeLibraryStore([make_doc("hash-ds")])
        client = make_client(env, store)

        response = client.patch(
            "/api/library/hash-ds", json={"applicability": {"kind": "parts", "parts": ["", "  "]}}
        )
        assert response.status_code == 400
        assert store.get("hash-ds").applicability.kind == "all"

    def test_family_kind_with_blank_family_is_400(self, env):
        store = FakeLibraryStore(
            [make_doc("hash-ds", applicability=Applicability.for_all(evidence="fallback"))]
        )
        client = make_client(env, store)

        response = client.patch(
            "/api/library/hash-ds", json={"applicability": {"kind": "family", "family": "   "}}
        )
        assert response.status_code == 400
        assert "family" in response.json()["detail"]
        assert store.get("hash-ds").applicability.kind == "all"

    def test_hand_edit_without_evidence_records_that_it_was_a_hand_edit(self, env):
        store = FakeLibraryStore([make_doc("hash-ds")])
        client = make_client(env, store)

        response = client.patch(
            "/api/library/hash-ds", json={"applicability": {"kind": "parts", "parts": ["AD9081"]}}
        )
        assert response.status_code == 200
        assert response.json()["applicability"]["evidence"] == library_router.USER_EDIT_EVIDENCE


class TestPatchReach:
    def test_naming_an_unbuilt_part_succeeds_and_reports_it_unbuilt(self, env):
        write_built_part(env.parts_dir, "AD9081", doc_hashes=["hash-ds"])
        store = FakeLibraryStore(
            [
                make_doc(
                    "hash-ds",
                    part_number="AD9081",
                    applicability=Applicability.for_parts(["AD9081"], evidence="title block"),
                )
            ]
        )
        client = make_client(env, store)

        response = client.patch(
            "/api/library/hash-ds",
            json={"applicability": {"kind": "parts", "parts": ["AD9081", "AD9082"]}},
        )
        assert response.status_code == 200
        body = response.json()
        # ADR 0005: the part comes into existence with this document as its
        # corpus, so naming it is legal — it is reported, never rejected.
        assert body["parts_reached"] == ["AD9081", "AD9082"]
        assert body["unbuilt_parts"] == ["AD9082"]

    def test_response_lists_affected_parts_and_which_need_a_rebuild(self, env):
        write_built_part(env.parts_dir, "AD9081", doc_hashes=["hash-ds"])
        write_built_part(env.parts_dir, "AD9082", doc_hashes=[])
        store = FakeLibraryStore(
            [
                make_doc(
                    "hash-ds",
                    part_number="AD9081",
                    applicability=Applicability.for_parts(["AD9081"], evidence="title block"),
                )
            ]
        )
        client = make_client(env, store)

        body = client.patch(
            "/api/library/hash-ds",
            json={"applicability": {"kind": "parts", "parts": ["AD9081", "AD9082", "AD9099"]}},
        ).json()
        assert body["parts_reached"] == ["AD9081", "AD9082", "AD9099"]
        assert body["unbuilt_parts"] == ["AD9099"]
        # AD9081 already carries this document; AD9082 is built without it and
        # AD9099 does not exist yet — both need a build to materialize.
        assert body["rebuild_needed"] == ["AD9082", "AD9099"]

    def test_narrowing_applicability_drops_the_part_from_reach(self, env):
        write_built_part(env.parts_dir, "AD9081", doc_hashes=["hash-an"])
        write_built_part(env.parts_dir, "AFE7950", doc_hashes=["hash-an"])
        store = FakeLibraryStore([make_doc("hash-an", applicability=Applicability.for_all())])
        client = make_client(env, store)

        before = client.get("/api/library").json()
        assert by_hash(before, "hash-an")["parts_reached"] == ["AD9081", "AFE7950"]

        body = client.patch(
            "/api/library/hash-an",
            json={"applicability": {"kind": "parts", "parts": ["AFE7950"]}},
        ).json()
        assert body["parts_reached"] == ["AFE7950"]
        assert body["rebuild_needed"] == []


class TestPatchWritesNothingDerived:
    def test_no_patch_touches_parts_or_the_extraction_cache(self, env):
        write_built_part(env.parts_dir, "AD9081", doc_hashes=["hash-ds"])
        write_unbuilt_part(env.parts_dir, "AFE7950")
        store = FakeLibraryStore([make_doc("hash-ds", part_number="AD9081", labels=["draft"])])
        client = make_client(env, store)

        parts_before = snapshot(env.parts_dir)
        cache_before = snapshot(env.cache_dir)

        assert (
            client.patch("/api/library/hash-ds", json={"labels": ["reviewed"]}).status_code == 200
        )
        assert (
            client.patch(
                "/api/library/hash-ds",
                json={"applicability": {"kind": "parts", "parts": ["AD9081", "BRAND-NEW"]}},
            ).status_code
            == 200
        )
        assert client.get("/api/library").status_code == 200

        assert snapshot(env.parts_dir) == parts_before
        assert snapshot(env.cache_dir) == cache_before
        # A patch never creates a part directory either — that is a build's job.
        assert sorted(p.name for p in env.parts_dir.iterdir()) == ["AD9081", "AFE7950"]


class TestLabelsSurviveARebuild:
    def test_labels_survive_a_subsequent_put_for_the_same_document(self, env):
        """`LibraryStore.put()` preserves stored labels — asserted through the
        store's frozen contract, which is what a build calls on every run."""
        store = FakeLibraryStore([make_doc("hash-ds", part_number="AD9081")])
        client = make_client(env, store)

        assert (
            client.patch("/api/library/hash-ds", json={"labels": ["reviewed"]}).status_code == 200
        )

        # What a rebuild does: re-register the same document, labels absent.
        store.put(make_doc("hash-ds", part_number="AD9081", labels=[]))

        payload = client.get("/api/library").json()
        assert by_hash(payload, "hash-ds")["labels"] == ["reviewed"]
        assert payload["labels"] == ["reviewed"]
