"""End-to-end pipeline on a synthetic part: PDF (for TOC/identity) +
replayed TI HTML (no network) -> corpus on disk. Pins the whole contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.pipeline import build_part

SYN = Path(__file__).parent.parent / "fixtures" / "synthetic"


@pytest.fixture
def synthetic_env(tmp_path, monkeypatch, make_synthetic_pdf):
    """Settings + a MappingFetcher replaying the synthetic TI pages."""
    pdf = tmp_path / "test9000.pdf"
    make_synthetic_pdf(pdf)
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()

    main = (SYN / "ti_main.html").read_text(encoding="utf-8")
    sec1 = (SYN / "ti_sec_features.html").read_text(encoding="utf-8")
    sec41 = (SYN / "ti_sec_absmax.html").read_text(encoding="utf-8")
    mapping = {
        "https://www.ti.com/document-viewer/TEST9000/datasheet": main,
        "https://www.ti.com/document-viewer/TEST9000/datasheet/GUID-AAAA1111-0000-0000-0000-000000000001#TITLE-X1": sec1,
        "https://www.ti.com/document-viewer/TEST9000/datasheet/GUID-BBBB2222-0000-0000-0000-000000000002#TITLE-X2": sec41,
    }

    from datasheet_analyzer.extract import get_backend
    from datasheet_analyzer.extract.http import MappingFetcher

    backend = get_backend("ti_html")
    backend.fetcher = MappingFetcher(mapping)

    # pipeline constructs its own backend via get_backend; patch the registry
    # entry to return our pre-wired instance for this test.
    monkeypatch.setattr(
        "datasheet_analyzer.pipeline.get_backend", lambda name: backend
    )
    return pdf, settings


def test_full_build_produces_navigable_corpus(synthetic_env):
    pdf, settings = synthetic_env
    result = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)

    part = result.part_dir
    assert (part / "INDEX.md").exists()
    assert (part / "sources.json").exists()
    assert (part / "manifest.json").exists()

    doc = part / "docs" / f"datasheet-{result.manifest.documents[0].content_hash[:8]}"
    features = (doc / "sections" / "1-features.md").read_text(encoding="utf-8")
    absmax = (doc / "sections" / "4-1-absolute-maximum-ratings.md").read_text(encoding="utf-8")

    # features content survived
    assert "12GSPS" in features
    # parametric table: rowspan expanded, footnotes attached, conditions inline
    assert "VDD1P2" in absmax and "–0.3" in absmax
    assert "Supply voltage 1.2V" in absmax.split("VDD1P2")[1]  # rowspan fill
    assert "Transient only, 100 ms maximum" in absmax  # footnote (2)
    assert "free-air temperature" in absmax  # conditions preamble
    # CSV twin written
    csv = (doc / "tables" / "4-1-absolute-maximum-ratings-t01.csv").read_text(encoding="utf-8")
    assert "VDD1P2" in csv

    # INDEX.md navigational essentials
    index = (part / "INDEX.md").read_text(encoding="utf-8")
    assert "# TEST9000" in index
    assert "4-1-absolute-maximum-ratings.md" in index
    assert "p.1" in index

    # manifest stats
    stats = result.manifest.stats
    assert stats.n_sections == 2
    assert stats.n_tables == 1
    assert stats.n_footnotes == 2
    assert stats.sections_with_pages == 2  # both pages mapped from PDF TOC

    # additive stats contract: ti_html documents carry the backend name and
    # zero table stats (only pdf_layout fills detected/accepted/rejected)
    ds_doc = result.manifest.documents[0]
    estats = result.manifest.extraction_stats[ds_doc.content_hash]
    assert estats.backend == "ti_html"
    assert estats.tables_detected == estats.tables_accepted == estats.tables_rejected == 0
    assert estats.rejection_reasons == []
    assert estats.mean_fidelity == 0.0


def test_second_build_uses_extraction_cache(synthetic_env):
    pdf, settings = synthetic_env
    first = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
    assert not first.cached_extraction
    second = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
    assert second.cached_extraction


def test_no_cache_flag_forces_reextract(synthetic_env):
    pdf, settings = synthetic_env
    build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
    again = build_part(pdf, part_number="TEST9000", settings=settings,
                       use_cache=False, use_llm=False)
    assert not again.cached_extraction
