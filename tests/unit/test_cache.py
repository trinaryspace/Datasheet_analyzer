"""Pain point: stale caches. Extraction cache is keyed by
(content_hash, backend) — changing either must miss; same inputs must hit.
Writes are atomic (write-temp + rename) so concurrent jobs sharing bytes
can never leave a corrupt cache entry.

Two producers write into one cached record, and both must be able to
invalidate it: the backend (`extractor_version`) and the structure stage that
runs inside `_extract_document` afterwards (`structure_version`). The second
one is here because it was missing, and the miss was measured — see
`TestTheStructureStageCanInvalidateToo`."""

from __future__ import annotations

import threading

from datasheet_analyzer.acquire.inventory import register_source
from datasheet_analyzer.config import STRUCTURE_STAGE_VERSION, Settings
from datasheet_analyzer.models import DocType, RawDocument, SourceDocument
from datasheet_analyzer.pipeline import (
    _extract_document,
    _load_cached_raw,
    _store_cached_raw,
)


def _settings(tmp_path) -> Settings:
    s = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache")
    return s.resolve()


def _raw(hash_char: str, extractor: str = "ti_html", page_count: int = 0) -> RawDocument:
    return RawDocument(
        source=SourceDocument(content_hash=hash_char * 64, path="x.pdf", page_count=page_count),
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


class TestTheStructureStageCanInvalidateToo:
    """A fix in the structure layer must not be invisible behind a cache.

    `pipeline._extract_document` pins table pages and per-row pages
    (`structure/pagemap.py`) after the backend returns and before the result
    is cached, so that code's output is inside the cached `RawDocument` while
    none of its identity was. Measured in phase 6.5: bumping
    `PdfLayoutBackend.output_version` re-extracted every `pdf_layout` document
    and left every `ti_html` one — AFE7950, AFE7953, LMX1204's datasheet —
    served from a cache written before per-row pinning existed, so LMX1204's
    `0x5A` row still cited a page it is not printed on. Only
    `dsa build --no-cache` produced a correct corpus.
    """

    def _source(self, tmp_path, make_synthetic_pdf):
        pdf = tmp_path / "structure-stage.pdf"
        make_synthetic_pdf(pdf)
        source = register_source(
            pdf, part_number="P1", doc_type=DocType.DATASHEET, vendor="unknown"
        )
        return pdf, source

    def test_a_fresh_extraction_records_the_stage_version(self, tmp_path, make_synthetic_pdf):
        pdf, source = self._source(tmp_path, make_synthetic_pdf)
        raw, cached = _extract_document(source, pdf, _settings(tmp_path), True)
        assert not cached
        assert raw.structure_version == STRUCTURE_STAGE_VERSION

    def test_the_same_stage_version_is_a_cache_hit(self, tmp_path, make_synthetic_pdf):
        pdf, source = self._source(tmp_path, make_synthetic_pdf)
        settings = _settings(tmp_path)
        _extract_document(source, pdf, settings, True)
        _raw, cached = _extract_document(source, pdf, settings, True)
        assert cached, "identical inputs and versions must be served from cache"

    def test_a_changed_stage_version_is_a_cache_miss(
        self, tmp_path, monkeypatch, make_synthetic_pdf
    ):
        """The whole point: bump the structure stage, get a re-extraction.

        The PDF's bytes, the backend and its `output_version` are all
        unchanged — the only thing that moved is the version of the code that
        runs *after* the backend, which is exactly the case that used to be
        served a stale reading.
        """
        pdf, source = self._source(tmp_path, make_synthetic_pdf)
        settings = _settings(tmp_path)
        _extract_document(source, pdf, settings, True)
        assert _extract_document(source, pdf, settings, True)[1] is True

        monkeypatch.setattr("datasheet_analyzer.pipeline.STRUCTURE_STAGE_VERSION", "pagemap-99")
        raw, cached = _extract_document(source, pdf, settings, True)
        assert not cached, "a structure-stage version change must miss"
        assert raw.structure_version == "pagemap-99"

    def test_a_cache_entry_written_before_the_field_is_stale(self, tmp_path, make_synthetic_pdf):
        """Every entry on disk today carries "" and re-extracts once."""
        pdf, source = self._source(tmp_path, make_synthetic_pdf)
        settings = _settings(tmp_path)
        raw, _cached = _extract_document(source, pdf, settings, True)
        raw.structure_version = ""  # a record written before this version existed
        _store_cached_raw(settings, raw)

        again, cached = _extract_document(source, pdf, settings, True)
        assert not cached
        assert again.structure_version == STRUCTURE_STAGE_VERSION
