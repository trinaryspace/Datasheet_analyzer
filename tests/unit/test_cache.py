"""Pain point: stale caches. Extraction cache is keyed by
(content_hash, backend) — changing either must miss; same inputs must hit."""

from __future__ import annotations

from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import RawDocument, SourceDocument
from datasheet_analyzer.pipeline import (
    _load_cached_raw,
    _store_cached_raw,
)


def _settings(tmp_path) -> Settings:
    s = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache")
    return s.resolve()


def _raw(hash_char: str, extractor: str = "ti_html") -> RawDocument:
    return RawDocument(
        source=SourceDocument(content_hash=hash_char * 64, path="x.pdf"),
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


def test_corrupt_cache_file_treated_as_miss(tmp_path):
    s = _settings(tmp_path)
    path = s.cache_dir / "extract" / f"{'c' * 64}__ti_html.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupt json", encoding="utf-8")
    import pytest

    with pytest.raises(ValueError):  # pydantic ValidationError subclasses ValueError
        _load_cached_raw(s, "c" * 64, "ti_html")


def test_concurrent_stores_same_identity_leave_valid_file(tmp_path):
    """Two threads storing the identical (hash, backend) cache entry must
    never leave a corrupt file or temp litter (parallel-dispatch ticket:
    cache writes are atomic write-temp + rename)."""
    import threading

    from datasheet_analyzer.models import SectionNode
    from datasheet_analyzer.pipeline import _load_cached_raw, _store_cached_raw

    s = _settings(tmp_path)
    # chunky payload so an interleaved plain write would visibly corrupt
    raw = _raw("d")
    raw.sections = [
        SectionNode(
            number=str(i),
            title=f"Section {i}",
            paragraphs=[f"paragraph {j}: " + "word " * 400 for j in range(20)],
        )
        for i in range(40)
    ]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _hammer() -> None:
        barrier.wait()
        for _ in range(8):
            try:
                _store_cached_raw(s, raw)
            except BaseException as exc:  # noqa: BLE001 — record, keep hammering
                errors.append(exc)

    threads = [threading.Thread(target=_hammer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    loaded = _load_cached_raw(s, "d" * 64, "ti_html")
    assert loaded is not None
    assert len(loaded.sections) == 40  # complete payload, never a torn slice
    assert not list((s.cache_dir / "extract").glob("*.tmp"))  # no temp litter
