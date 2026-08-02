"""Phase 3 integration: multi-document parts (datasheet + register map)."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.acquire import append_to_inventory, load_inventory, register_source
from datasheet_analyzer.config import Settings
from datasheet_analyzer.extract import get_backend as _original_get_backend
from datasheet_analyzer.extract.http import ReplayBinaryFetcher, ReplayFetcher
from datasheet_analyzer.models import DocType
from datasheet_analyzer.pipeline import build_part

RECORDED = Path(__file__).parent.parent / "fixtures" / "recorded_http"
RECORDED_BIN = Path(__file__).parent.parent / "fixtures" / "recorded_http_bin"

TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def _make_register_map_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "register_map.pdf"
    doc = fitz.open()
    for i, title in enumerate(["Overview", "Register Summary", "Control Registers"]):
        page = doc.new_page()
        page.insert_text((300, 750), str(i + 1))
        page.insert_text((72, 72), f"{title} content on page {i + 1}.")
    doc.set_toc([
        [1, "1 Overview", 1],
        [1, "2 Register Summary", 2],
        [2, "2.1 Control Registers", 3],
    ])
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture(scope="module")
def built(tmp_path_factory, afe7950_pdf, monkeymodule):
    if not RECORDED.is_dir():
        pytest.skip("recorded HTTP fixtures not present")

    tmp = tmp_path_factory.mktemp("built_phase3_multidoc")
    settings = Settings(parts_dir=tmp / "parts", cache_dir=tmp / ".cache").resolve()

    # Pre-register both the datasheet and the companion register-map PDF.
    ds_source = register_source(afe7950_pdf, part_number="AFE7950", doc_type=DocType.DATASHEET)
    reg_pdf = _make_register_map_pdf(tmp)
    reg_source = register_source(reg_pdf, part_number="AFE7950", doc_type=DocType.REGISTER_MAP)
    append_to_inventory([ds_source, reg_source], settings.parts_dir / "AFE7950")

    ti_backend = _original_get_backend("ti_html")
    ti_backend.fetcher = ReplayFetcher(RECORDED)

    def _patched_get_backend(name: str):
        if name == "ti_html":
            return ti_backend
        return _original_get_backend(name)

    monkeymodule.setattr("datasheet_analyzer.pipeline.get_backend", _patched_get_backend)

    bin_fetcher = ReplayBinaryFetcher(RECORDED_BIN, default=TINY_GIF)
    monkeymodule.setattr(
        "datasheet_analyzer.pipeline.CachingBinaryFetcher",
        lambda *args, **kwargs: bin_fetcher,
    )

    result = build_part(
        afe7950_pdf,
        part_number="AFE7950",
        settings=settings,
        use_llm=False,
        use_cache=False,
    )
    return result, settings, reg_source


@pytest.fixture(scope="module")
def monkeymodule():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.mark.integration
class TestPhase3MultiDoc:
    def test_manifest_has_two_documents(self, built):
        result, _settings, _reg_source = built
        assert result.manifest.stats.n_documents == 2
        dtypes = {d.doc_type.value for d in result.manifest.documents}
        assert dtypes == {"datasheet", "register_map"}

    def test_index_lists_both_documents(self, built):
        result, _settings, _reg_source = built
        index_md = (result.part_dir / "INDEX.md").read_text(encoding="utf-8")
        assert "datasheet" in index_md
        assert "register_map" in index_md
        assert "Section map" in index_md

    def test_both_section_trees_on_disk(self, built):
        result, _settings, _reg_source = built
        doc_dirs = list((result.part_dir / "docs").iterdir())
        assert len(doc_dirs) == 2
        for d in doc_dirs:
            assert (d / "sections").exists()

    def test_register_map_has_pdf_text_provenance(self, built):
        result, _settings, reg_source = built
        reg_dir = result.part_dir / f"docs/register_map-{reg_source.content_hash[:8]}"
        assert reg_dir.exists()
        # No specs.json for pdf_text documents.
        assert not (reg_dir / "specs.json").exists()
        # Sections were rendered.
        section_files = list((reg_dir / "sections").glob("*.md"))
        assert len(section_files) >= 1
        text = section_files[0].read_text(encoding="utf-8")
        assert "<!-- source:" in text

    def test_datasheet_still_has_specs(self, built):
        result, _settings, _reg_source = built
        ds_doc = next(d for d in result.manifest.documents if d.doc_type.value == "datasheet")
        specs_path = result.part_dir / f"docs/datasheet-{ds_doc.content_hash[:8]}" / "specs.json"
        assert specs_path.exists()

    def test_add_doc_idempotence(self, tmp_path):
        part_dir = tmp_path / "parts" / "TESTIDEM"
        pdf = _make_register_map_pdf(tmp_path)
        src1 = register_source(pdf, part_number="TESTIDEM", doc_type=DocType.REGISTER_MAP)
        append_to_inventory([src1], part_dir)
        first = load_inventory(part_dir)
        assert len(first) == 1
        # Re-add same bytes.
        src2 = register_source(pdf, part_number="TESTIDEM", doc_type=DocType.REGISTER_MAP)
        append_to_inventory([src2], part_dir)
        second = load_inventory(part_dir)
        assert len(second) == 1
        assert second[0].content_hash == src1.content_hash

    def test_cli_add_doc(self, built, monkeypatch, capsys):
        _result, settings, _reg_source = built
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        exit_code = cli.main(["status"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "AFE7950" in captured.out
