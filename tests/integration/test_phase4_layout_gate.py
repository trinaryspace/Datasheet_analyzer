"""Phase 4 gate: four really different PDFs build fully offline via pdf_layout.

Layout families: ADI new (AD9081, outline, unnumbered), old TI (lm741,
numbered outline), Qorvo (QPA1003P, no outline at all -> per-page), and
Hittite-era ADI (HMC520A, unnumbered outline). The seam is exactly what
users run — `build_part` with temp-dir settings — with one documented
override: lm741's page 1 carries no brand mark, so detection cannot pin a
pdf_layout-routable profile; the spec's `--vendor` escape hatch is used
there and recorded honestly as cli-override evidence.

Assertions are corpus products only: section files with page citations,
furniture golden strings absent from paragraphs, content preserved,
inventory vendor evidence, pdf_layout backend in the manifest, and honest
numbered vs unnumbered section identity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.pipeline import build_part

REPO = Path(__file__).parent.parent.parent

GATE: dict[str, dict] = {
    "AD9081": {
        "pdf": REPO / "ad9081.pdf", "part": "AD9081", "override": "", "vendor": "adi",
        "noise": ["of 45", "analog.com", "Rev. 0 |", "Data Sheet"],
        "content": ["12 GSPS", "Full-scale output current range",
                    "Test Conditions/Comments"],
    },
    "LM741": {
        "pdf": REPO / "lm741.pdf", "part": "LM741", "override": "unknown",
        "vendor": "unknown",
        "noise": ["www.ti.com", "Submit Documentation Feedback", "Copyright (c)",
                  "Product Folder Links"],
        "content": ["overload protection", "Absolute Maximum Ratings"],
    },
    "QPA1003P": {
        "pdf": REPO / "QPA1003P.pdf", "part": "QPA1003P", "override": "", "vendor": "qorvo",
        "noise": ["of 20", "Data Sheet Rev. I", "Rev. I"],
        "content": ["wideband high power MMIC", "matched to 50"],
    },
    "HMC520A": {
        "pdf": REPO / "hmc520a.pdf", "part": "HMC520A", "override": "", "vendor": "adi",
        "noise": ["of 32", "Rev. A | Page", "| Page"],
        "content": ["Rev. 0 to Rev. A", "Conversion loss"],
    },
}


@pytest.fixture(scope="module")
def gate(tmp_path_factory):
    """One offline corpus per gate part; skip-guarded like AFE7950."""
    results: dict[str, object] = {}
    for name, spec in GATE.items():
        if not spec["pdf"].exists():
            pytest.skip(f"{spec['pdf'].name} not present at repo root")
        tmp = tmp_path_factory.mktemp(f"gate-{name}")
        settings = Settings(parts_dir=tmp / "parts", cache_dir=tmp / ".cache").resolve()
        results[name] = build_part(
            spec["pdf"], part_number=spec["part"], settings=settings,
            vendor=spec["override"], use_llm=False,
        )
    return results


def _blob(result) -> str:
    return "\n".join(
        (result.part_dir / sec.file).read_text(encoding="utf-8")
        for sec in result.manifest.sections
    )


class TestGateCorpora:
    def test_every_part_builds_with_evidence_and_no_furniture(self, gate):
        for name, spec in GATE.items():
            result = gate[name]
            assert result.manifest.vendor == spec["vendor"], name
            assert len(result.manifest.sections) >= 20, name
            for sec in result.manifest.sections:
                assert sec.page_start is not None, f"{name}: {sec.title} lacks pages"
                assert (result.part_dir / sec.file).exists(), f"{name}: {sec.file}"
            assert (result.part_dir / "INDEX.md").exists(), name

            doc = result.manifest.documents[0]
            assert result.manifest.extraction_stats[doc.content_hash].backend == "pdf_layout"
            sources = json.loads((result.part_dir / "sources.json").read_text(encoding="utf-8"))
            assert sources[0]["vendor"] == spec["vendor"], name
            assert sources[0]["vendor_evidence"], f"{name}: no vendor evidence"

            blob = _blob(result)
            for golden in spec["noise"]:
                assert golden not in blob, f"{name}: furniture {golden!r} leaked"
            for needle in spec["content"]:
                assert needle in blob, f"{name}: content {needle!r} missing"

    def test_lm741_numbered_outline_keeps_printed_numbers(self, gate):
        """Old-TI outline titles carry numbers; sections and files keep them."""
        result = gate["LM741"]
        nums = [s.number for s in result.manifest.sections]
        assert nums[:3] == ["1", "2", "3"]
        assert "12" in nums
        assert list((result.part_dir / "docs").glob("**/1-features.md")), "1-features.md missing"

    def test_ad9081_unnumbered_sections_stay_honest_and_slugged(self, gate):
        result = gate["AD9081"]
        assert all(s.number == "" for s in result.manifest.sections)
        files = {p.name for p in (result.part_dir / "docs").glob("**/sections/*.md")}
        assert "features.md" in files
        assert "general-description.md" in files
        index = (result.part_dir / "INDEX.md").read_text(encoding="utf-8")
        # "General Description" brief now feeds the INDEX (ADI parts)
        assert "MxFE Quad" in index

    def test_qpa1003p_no_outline_no_printed_toc_degrades_per_page(self, gate):
        result = gate["QPA1003P"]
        assert len(result.manifest.sections) == 20
        assert [s.title for s in result.manifest.sections[:2]] == ["Page 1", "Page 2"]
        assert list((result.part_dir / "docs").glob("**/1-page-1.md"))

    def test_hmc520a_unnumbered_outline_slugged(self, gate):
        result = gate["HMC520A"]
        assert all(s.number == "" for s in result.manifest.sections)
        files = {p.name for p in (result.part_dir / "docs").glob("**/sections/*.md")}
        assert "features.md" in files
        assert "revision-history.md" in files
