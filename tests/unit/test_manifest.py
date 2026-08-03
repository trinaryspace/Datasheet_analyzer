"""Pain point: manifest integrity — every referenced file exists, page
ranges stay within document bounds, stats are consistent, multi-doc parts
serialize correctly."""

from __future__ import annotations

import json

from datasheet_analyzer.models import (
    CorpusManifest,
    RawDocument,
    SectionNode,
    SourceDocument,
    TableBlock,
)
from datasheet_analyzer.publish import doc_dir_name, write_corpus
from datasheet_analyzer.structure.corpus import build_section_plans


def _raw(hash_char: str, dtype: str = "datasheet") -> RawDocument:
    from datasheet_analyzer.models import DocType

    return RawDocument(
        source=SourceDocument(
            content_hash=hash_char * 64, path="x.pdf", revision="TEST1A",
            doc_type=DocType(dtype), page_count=50,
        ),
        sections=[
            SectionNode(number="1", title="Features", level=1, page_start=1, page_end=1,
                        paragraphs=["Feature one."]),
            SectionNode(number="4.5", title="TX", level=2, page_start=7, page_end=13,
                        tables=[TableBlock(headers=["P", "V"], grid=[["A", "1"]])]),
        ],
        extractor="test",
    )


def test_write_corpus_layout_and_manifest(tmp_path):
    raw = _raw("a")
    plans = build_section_plans(raw)
    desc = {"1": "features desc", "4.5": "tx desc"}
    manifest = write_corpus(
        tmp_path / "AFE7950", [(raw, plans, desc)], "# INDEX\n", pipeline_version="0.1.0"
    )
    assert manifest.stats.n_sections == 2

    part = tmp_path / "AFE7950"
    assert (part / "INDEX.md").read_text() == "# INDEX\n"
    doc = part / "docs" / f"datasheet-{'aaaaaaaa'}"
    assert (doc / "sections" / "1-features.md").exists()
    assert (doc / "sections" / "4-5-tx.md").exists()
    assert (doc / "tables" / "4-5-tx-t01.csv").exists()

    on_disk = json.loads((part / "manifest.json").read_text())
    m = CorpusManifest.model_validate(on_disk)  # schema round-trip
    assert m.part_number == "AFE7950"
    assert m.stats.n_sections == 2 and m.stats.n_tables == 1
    assert m.stats.sections_with_pages == 2
    assert m.sections[1].description == "tx desc"
    assert m.documents[0].revision == "TEST1A"


def test_manifest_references_resolve_to_real_files(tmp_path):
    raw = _raw("b")
    plans = build_section_plans(raw)
    manifest = write_corpus(tmp_path / "P", [(raw, plans, {})], "idx", pipeline_version="x")
    for s in manifest.sections:
        assert (tmp_path / "P" / s.file).exists(), s.file


def test_page_ranges_within_document_bounds(tmp_path):
    raw = _raw("c")
    plans = build_section_plans(raw)
    manifest = write_corpus(tmp_path / "P", [(raw, plans, {})], "idx", pipeline_version="x")
    for s in manifest.sections:
        if s.page_start is not None:
            assert 1 <= s.page_start <= raw.source.page_count
            assert (s.page_end or s.page_start) >= s.page_start


def test_multi_doc_part(tmp_path):
    ds, rm = _raw("d", "datasheet"), _raw("e", "register_map")
    docs = [
        (ds, build_section_plans(ds), {}),
        (rm, build_section_plans(rm), {}),
    ]
    manifest = write_corpus(tmp_path / "P", docs, "idx", pipeline_version="x")
    assert manifest.stats.n_documents == 2
    assert len({s.doc_hash for s in manifest.sections}) == 2
    dirs = {s.file.split("/")[1] for s in manifest.sections}
    assert "datasheet-dddddddd" in dirs and "register_map-eeeeeeee" in dirs


def test_doc_dir_name_is_stable_and_typed():
    raw = _raw("f")
    assert doc_dir_name(raw) == "datasheet-ffffffff"


def test_manifest_carries_vendor_and_per_doc_extraction_stats(tmp_path):
    raw = _raw("g")
    plans = build_section_plans(raw)
    manifest = write_corpus(
        tmp_path / "P",
        [(raw, plans, {})],
        "idx",
        pipeline_version="0.2.0",
        vendor="adi",
    )
    assert manifest.vendor == "adi"
    assert manifest.pipeline_version == "0.2.0"
    stats = manifest.extraction_stats[raw.source.content_hash]
    assert stats.backend == "test"
    assert stats.tables_detected == 0

    on_disk = json.loads((tmp_path / "P" / "manifest.json").read_text())
    m = CorpusManifest.model_validate(on_disk)  # schema round-trip
    assert m.vendor == "adi"
    assert m.extraction_stats[raw.source.content_hash].backend == "test"


def test_manifest_without_vendor_defaults_empty(tmp_path):
    manifest = write_corpus(tmp_path / "P", [], "idx", pipeline_version="x")
    assert manifest.vendor == ""
    assert manifest.extraction_stats == {}
