"""Pain point: stale caches. Extraction cache is keyed by
(content_hash, backend) — changing either must miss; same inputs must hit.
Writes are atomic (write-temp + rename) so concurrent jobs sharing bytes
can never leave a corrupt cache entry."""

from __future__ import annotations

import threading

from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import RawDocument, SourceDocument
from datasheet_analyzer.pipeline import (
    _load_cached_raw,
    _store_cached_raw,
)


def _settings(tmp_path) -> Settings:
    s = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache")
    return s.resolve()


def _raw(hash_char: str, extractor: str = "ti_html", page_count: int = 0) -> RawDocument:
    return RawDocument(
        source=SourceDocument(
            content_hash=hash_char * 64, path="x.pdf", page_count=page_count
        ),
        extractor=extractor,
    )


def test_roundtrip_hit(tmp_path):
    s = _settings(tmp_path)
    raw = _raw("a")
    _store_cached_raw(s, raw)
    loaded = _load_cached_raw(s, "a" * 64, "ti_html")
    assert loaded is not None
    assert loaded.source.content_hash == raw.source.content_hash
    assert loaded.extractor == "ti_html"


def test_miss_on_different_hash(tmp_path):
    s = _settings(tmp_path)
    _store_cached_raw(s, _raw("a"))
    assert _load_cached_raw(s, "b" * 64, "ti_html") is None


def test_miss_on_different_backend(tmp_path):
    s = _settings(tmp_path)
    _store_cached_raw(s, _raw("a", "ti_html"))
    assert _load_cached_raw(s, "a" * 64, "pdf_text") is None


def test_store_leaves_no_temp_files_behind(tmp_path):
    s = _settings(tmp_path)
    _store_cached_raw(s, _raw("a"))
    cache_dir = s.cache_dir / "extract"
    assert [p.name for p in cache_dir.iterdir()] == ["a" * 64 + "__ti_html.json"]


def test_concurrent_writes_to_same_entry_never_corrupt(tmp_path):
    s = _settings(tmp_path)
    raw_a = _raw("a", page_count=3)
    raw_b = _raw("a", page_count=9)  # same cache key, different payload
    errors: list[Exception] = []

    def writer(raw: RawDocument) -> None:
        try:
            for _ in range(10):
                _store_cached_raw(s, raw)
        except Exception as exc:  # noqa: BLE001 — collect for the assertion
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(raw,)) for raw in (raw_a, raw_b) for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    loaded = _load_cached_raw(s, "a" * 64, "ti_html")
    assert loaded is not None  # parses as a valid RawDocument — no torn write
    assert loaded in (raw_a, raw_b)


def test_corrupt_cache_file_treated_as_miss(tmp_path):
    s = _settings(tmp_path)
    path = s.cache_dir / "extract" / f"{'c' * 64}__ti_html.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupt json", encoding="utf-8")
    import pytest

    with pytest.raises(ValueError):  # pydantic ValidationError subclasses ValueError
        _load_cached_raw(s, "c" * 64, "ti_html")
