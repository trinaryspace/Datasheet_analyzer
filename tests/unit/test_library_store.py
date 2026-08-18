"""Ticket 01 — the library store: round-trips, views, labels, and bad files.

Hermetic by construction (AGENTS.md invariant 4): every test runs against a
`Settings(library_dir=tmp_path/...)` with the `reset_settings_cache` hook. No
PDFs are opened, no network is touched and no model is called — the store is
pure filesystem plumbing over `LibraryDocument`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from datasheet_analyzer.config import LIBRARY_SCHEMA_VERSION, Settings, reset_settings_cache
from datasheet_analyzer.library.store import LibraryStore, clear_library_cache
from datasheet_analyzer.models import Applicability, DocType, LibraryDocument, SourceDocument

STORE_LOGGER = "datasheet_analyzer.library.store"


def _hash(seed: str) -> str:
    """A plausible 64-char sha256-shaped identity built from one seed char."""
    return (seed * 64)[:64]


def make_doc(
    seed: str,
    *,
    part_number: str = "AD9081",
    applicability: Applicability | None = None,
    labels: list[str] | None = None,
    filename: str = "",
) -> LibraryDocument:
    content_hash = _hash(seed)
    return LibraryDocument(
        source=SourceDocument(
            content_hash=content_hash,
            path=filename or f"{part_number.lower()}-{seed}.pdf",
            part_number=part_number,
            doc_type=DocType.DATASHEET,
            page_count=12,
            vendor="adi",
            vendor_evidence="brand match: Analog Devices",
        ),
        applicability=applicability or Applicability.for_parts([part_number], evidence="title"),
        labels=list(labels or []),
    )


@pytest.fixture(autouse=True)
def fresh_library_cache():
    """The read cache is process-global: one test's shelf must never leak."""
    clear_library_cache()
    yield
    clear_library_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    reset_settings_cache()
    resolved = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        library_dir=tmp_path / "library",
    ).resolve()
    yield resolved
    reset_settings_cache()


@pytest.fixture
def store(settings: Settings) -> LibraryStore:
    return LibraryStore.for_settings(settings)


# --- construction -------------------------------------------------------------


def test_construction_has_no_filesystem_side_effects(settings: Settings):
    """Binding a store creates nothing, the rule `config.py` follows."""
    store = LibraryStore.for_settings(settings)

    assert store.library_dir == settings.library_dir
    assert not settings.library_dir.exists()
    assert store.all() == []


def test_for_settings_defaults_to_cached_settings(tmp_path: Path, monkeypatch):
    """No argument means `get_settings().library_dir`."""
    monkeypatch.setenv("DSA_LIBRARY_DIR", str(tmp_path / "shelf"))
    reset_settings_cache()
    try:
        assert LibraryStore.for_settings().library_dir == (tmp_path / "shelf").resolve()
    finally:
        reset_settings_cache()


# --- round-trip ---------------------------------------------------------------


def test_put_then_get_round_trips_exactly(store: LibraryStore):
    doc = make_doc(
        "a",
        applicability=Applicability.for_family("AFE79xx", evidence="title block: AFE79xx"),
        labels=["reviewed", "jesd204"],
    )

    store.put(doc)
    loaded = store.get(doc.content_hash)

    assert loaded is not None
    assert loaded.source == doc.source
    assert loaded.applicability == doc.applicability
    assert loaded.labels == ["reviewed", "jesd204"]
    assert loaded.added_at == doc.added_at
    assert loaded.schema_version == LIBRARY_SCHEMA_VERSION


def test_get_unknown_hash_returns_none(store: LibraryStore):
    store.put(make_doc("a"))

    assert store.get(_hash("f")) is None
    assert store.get("") is None


# --- the whole shelf ----------------------------------------------------------


def test_all_returns_every_document_sorted_by_content_hash(store: LibraryStore):
    for seed in ("c", "a", "d", "b"):
        store.put(make_doc(seed))

    hashes = [doc.content_hash for doc in store.all()]

    assert hashes == sorted(hashes)
    assert hashes == [_hash(seed) for seed in ("a", "b", "c", "d")]


def test_two_puts_for_one_hash_produce_one_file(store: LibraryStore):
    doc = make_doc("a", part_number="AD9081")
    store.put(doc)
    store.put(doc.model_copy(update={"applicability": Applicability.for_all(evidence="redo")}))

    assert len(list(store.library_dir.glob("*.json"))) == 1
    assert len(store.all()) == 1
    assert store.get(doc.content_hash).applicability.kind == "all"


# --- the part view ------------------------------------------------------------


def test_for_part_covers_named_family_and_all(store: LibraryStore):
    named = make_doc("a", applicability=Applicability.for_parts(["AD9081"], evidence="title"))
    family = make_doc("b", applicability=Applicability.for_family("AD90x1", evidence="title"))
    everything = make_doc("c", applicability=Applicability.for_all(evidence="fallback"))
    other = make_doc("d", applicability=Applicability.for_parts(["LM741"], evidence="title"))
    for doc in (named, family, everything, other):
        store.put(doc)

    reached = {doc.content_hash for doc in store.for_part("AD9081")}

    assert reached == {named.content_hash, family.content_hash, everything.content_hash}


def test_for_part_returns_empty_when_nothing_covers_it(store: LibraryStore):
    store.put(make_doc("a", applicability=Applicability.for_parts(["AD9081"], evidence="title")))
    store.put(make_doc("b", applicability=Applicability.for_family("AFE79xx", evidence="title")))

    assert store.for_part("LM741") == []


# --- user-writable fields -----------------------------------------------------


def test_set_labels_replaces_labels_and_leaves_the_rest(store: LibraryStore):
    doc = make_doc("a", labels=["draft"])
    store.put(doc)

    updated = store.set_labels(doc.content_hash, ["reviewed", "thermal"])

    assert updated.labels == ["reviewed", "thermal"]
    assert updated.applicability == doc.applicability
    assert updated.source == doc.source
    assert store.get(doc.content_hash).labels == ["reviewed", "thermal"]


def test_set_applicability_replaces_it_and_leaves_the_rest(store: LibraryStore):
    doc = make_doc("a", labels=["reviewed"])
    store.put(doc)
    store.set_labels(doc.content_hash, ["reviewed"])
    widened = Applicability.for_family("AD90x1", evidence="user edit")

    updated = store.set_applicability(doc.content_hash, widened)

    assert updated.applicability == widened
    assert updated.labels == ["reviewed"]
    assert updated.source == doc.source
    assert store.get(doc.content_hash).applicability == widened


def test_put_preserves_labels_already_stored(store: LibraryStore):
    """A rebuild must not be able to destroy user annotation."""
    doc = make_doc("a")
    store.put(doc)
    store.set_labels(doc.content_hash, ["reviewed", "thermal"])

    rebuilt = doc.model_copy(
        update={
            "labels": [],
            "applicability": Applicability.for_all(evidence="re-inferred"),
        }
    )
    store.put(rebuilt)

    stored = store.get(doc.content_hash)
    assert stored.labels == ["reviewed", "thermal"]
    assert stored.applicability.kind == "all"


def test_put_of_a_new_document_keeps_the_labels_it_carries(store: LibraryStore):
    """Preservation is about *stored* labels; a first write is not overridden."""
    doc = make_doc("a", labels=["migrated"])

    store.put(doc)

    assert store.get(doc.content_hash).labels == ["migrated"]


def test_updating_an_unknown_hash_raises_key_error(store: LibraryStore):
    """The signature returns a document, not an optional: a miss cannot be silent."""
    with pytest.raises(KeyError):
        store.set_labels(_hash("f"), ["reviewed"])
    with pytest.raises(KeyError):
        store.set_applicability(_hash("f"), Applicability.for_all(evidence="x"))


# --- bad files ----------------------------------------------------------------


def test_malformed_json_is_skipped_with_a_warning(store: LibraryStore, caplog):
    good = make_doc("a")
    store.put(good)
    truncated = store.library_dir / f"{_hash('b')}.json"
    truncated.write_text('{"source": {"content_hash": "bb', encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=STORE_LOGGER):
        docs = store.all()

    assert [doc.content_hash for doc in docs] == [good.content_hash]
    assert store.get(_hash("b")) is None
    assert any(truncated.name in record.getMessage() for record in caplog.records)


def test_every_file_records_the_schema_version(store: LibraryStore):
    doc = make_doc("a")
    store.put(doc)

    payload = json.loads((store.library_dir / f"{doc.content_hash}.json").read_text("utf-8"))

    assert payload["schema_version"] == LIBRARY_SCHEMA_VERSION


def test_unknown_schema_version_is_skipped_with_a_warning(store: LibraryStore, caplog):
    good = make_doc("a")
    store.put(good)
    stranger = make_doc("b")
    path = store.library_dir / f"{stranger.content_hash}.json"
    payload = json.loads(stranger.model_dump_json())
    payload["schema_version"] = "99"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=STORE_LOGGER):
        docs = store.all()

    assert [doc.content_hash for doc in docs] == [good.content_hash]
    assert store.get(stranger.content_hash) is None
    assert any("schema_version" in record.getMessage() for record in caplog.records)


# --- caching and atomicity ----------------------------------------------------


def test_read_cache_is_invalidated_when_the_file_is_rewritten(store: LibraryStore):
    doc = make_doc("a", labels=["first"])
    store.put(doc)
    first = store.get(doc.content_hash)
    assert store.get(doc.content_hash) is first  # served from the read cache

    path = store.library_dir / f"{doc.content_hash}.json"
    before = path.stat().st_mtime_ns
    payload = json.loads(path.read_text("utf-8"))
    payload["labels"] = ["rewritten-out-of-band"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    # Bump the mtime explicitly rather than sleeping: the Windows filesystem
    # clock is coarse enough that two quick writes can share a timestamp, and
    # a test that sleeps to dodge that is a slow test that still flakes.
    bumped = before + 1_000_000_000
    os.utime(path, ns=(bumped, bumped))

    assert path.stat().st_mtime_ns != before
    reloaded = store.get(doc.content_hash)
    assert reloaded is not first
    assert reloaded.labels == ["rewritten-out-of-band"]


def test_put_leaves_no_temp_file_behind(store: LibraryStore):
    doc = make_doc("a")
    store.put(doc)
    store.put(doc)
    store.set_labels(doc.content_hash, ["reviewed"])

    assert list(store.library_dir.glob("*.tmp")) == []
    assert [p.name for p in store.library_dir.iterdir()] == [f"{doc.content_hash}.json"]
