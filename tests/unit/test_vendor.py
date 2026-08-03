"""Vendor routing seam — external behavior only.

The vendor is a routing record: detected at acquire time with recorded
evidence (brand lexicon on page-1 text + filename), pinned into the
inventory, overrideable with ``--vendor``, surfaced by ``dsa status``, and
contradictions between detection and a pinned value warn loudly. Backend
selection follows the profile's preference chain.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.acquire.inventory import load_inventory, register_source, save_inventory
from datasheet_analyzer.config import Settings
from datasheet_analyzer.extract import BackendUnavailableError, get_backend
from datasheet_analyzer.extract.http import MappingFetcher
from datasheet_analyzer.extract.pdf_structure import compute_content_hash
from datasheet_analyzer.models import DocType, SourceDocument
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.vendor import (
    detect_vendor,
    is_known_vendor,
    select_backend,
    warn_vendor_drift,
)

SYN = Path(__file__).parent.parent / "fixtures" / "synthetic"


def _pdf(path, pages: list[str]):
    """Tiny synthetic PDF with known text per page (no TOC needed here)."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


@pytest.fixture
def vendor_env(tmp_path, monkeypatch, make_synthetic_pdf):
    """Synthetic part (same shape as test_pipeline) with replayed ti_html."""
    pdf = tmp_path / "test9000.pdf"
    make_synthetic_pdf(pdf)
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()

    mapping = {
        "https://www.ti.com/document-viewer/TEST9000/datasheet": (
            SYN / "ti_main.html"
        ).read_text(encoding="utf-8"),
        "https://www.ti.com/document-viewer/TEST9000/datasheet/GUID-AAAA1111-0000-0000-0000-000000000001#TITLE-X1": (
            SYN / "ti_sec_features.html"
        ).read_text(encoding="utf-8"),
        "https://www.ti.com/document-viewer/TEST9000/datasheet/GUID-BBBB2222-0000-0000-0000-000000000002#TITLE-X2": (
            SYN / "ti_sec_absmax.html"
        ).read_text(encoding="utf-8"),
    }
    backend = get_backend("ti_html")
    backend.fetcher = MappingFetcher(mapping)
    monkeypatch.setattr("datasheet_analyzer.pipeline.get_backend", lambda name: backend)
    return pdf, settings


class TestDetectVendor:
    def test_brand_on_page_one_text(self, tmp_path):
        pdf = tmp_path / "ad9081.pdf"
        _pdf(pdf, ["Analog Devices AD9081 MxFE data sheet, one page away"])
        vendor, evidence = detect_vendor(pdf)
        assert vendor == "adi"
        assert evidence == 'brand:"analog devices" (p.1)'

    def test_unmatched_text_and_filename_default_to_ti(self, tmp_path):
        pdf = tmp_path / "qpa1003p.pdf"
        _pdf(pdf, ["HIGH POWER AMPLIFIER 1 of 20"])  # no brand marks anywhere
        vendor, evidence = detect_vendor(pdf)
        assert vendor == "ti"
        assert evidence == ""

    def test_brand_in_filename(self, tmp_path):
        pdf = tmp_path / "qorvo-thing.pdf"
        _pdf(pdf, ["High Power Amplifier datasheet"])
        vendor, evidence = detect_vendor(pdf)
        assert vendor == "qorvo"
        assert evidence == 'brand:"qorvo" (filename)'

    def test_detection_order_is_ti_first(self, tmp_path):
        pdf = tmp_path / "x.pdf"
        _pdf(pdf, ["Texas Instruments and Analog Devices on one cover page"])
        assert detect_vendor(pdf)[0] == "ti"

    def test_unmatched_pdf_defaults_to_ti_with_empty_evidence(self, tmp_path):
        pdf = tmp_path / "mystery.pdf"
        _pdf(pdf, ["Untitled engineering document, page one"])
        assert detect_vendor(pdf) == ("ti", "")


class TestSelectBackend:
    def test_ti_datasheet_prefers_ti_html(self):
        assert select_backend("ti", DocType.DATASHEET) == "ti_html"

    def test_non_ti_datasheets_need_layout_backend_not_available(self):
        # pdf_layout lands in ticket 02; until then the chain raises honestly.
        with pytest.raises(BackendUnavailableError, match="pdf_layout"):
            select_backend("adi", DocType.DATASHEET)

    def test_unknown_vendor_falls_back_to_layout_backend(self):
        with pytest.raises(BackendUnavailableError, match="pdf_layout"):
            select_backend("unknown", DocType.DATASHEET)

    def test_companions_use_pdf_text_for_every_vendor(self):
        for vendor in ("ti", "adi", "qorvo", "unknown"):
            assert select_backend(vendor, DocType.REGISTER_MAP) == "pdf_text"
            assert select_backend(vendor, DocType.ERRATA) == "pdf_text"
            assert select_backend(vendor, DocType.APP_NOTE) == "pdf_text"

    def test_unknown_vendor_name_raises(self):
        with pytest.raises(KeyError, match="nvidia"):
            select_backend("nvidia", DocType.DATASHEET)

    def test_is_known_vendor(self):
        assert is_known_vendor("ti")
        assert is_known_vendor("adi")
        assert is_known_vendor("qorvo")
        assert is_known_vendor("unknown")
        assert not is_known_vendor("nvidia")


class TestAcquirePinning:
    def test_register_detects_and_pins_vendor(self, tmp_path):
        pdf = tmp_path / "afe7950.pdf"
        _pdf(pdf, ["Texas Instruments AFE7950 page one"])
        src = register_source(pdf, part_number="AFE7950")
        assert src.vendor == "ti"
        assert src.vendor_evidence == 'brand:"texas instruments" (p.1)'

    def test_register_override_pins_with_cli_evidence(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _pdf(pdf, ["Some other company's datasheet"])
        src = register_source(pdf, part_number="X", vendor="qorvo")
        assert src.vendor == "qorvo"
        assert src.vendor_evidence == "cli-override: --vendor qorvo"

    def test_vendor_survives_inventory_roundtrip(self, tmp_path):
        pdf = tmp_path / "part.pdf"
        _pdf(pdf, ["Analog Devices UG-1234 user guide"])
        src = register_source(pdf, vendor="adi")
        part_dir = tmp_path / "parts" / "P"
        save_inventory([src], part_dir)
        (loaded,) = load_inventory(part_dir)
        assert loaded == src


class TestPinningPersistence:
    def test_override_pins_into_inventory_even_when_build_fails(self, vendor_env):
        pdf, settings = vendor_env
        with pytest.raises(BackendUnavailableError):
            build_part(pdf, part_number="TEST9000", settings=settings, vendor="adi",
                       use_llm=False)
        (src,) = load_inventory(settings.parts_dir / "TEST9000")
        assert src.vendor == "adi"
        assert src.vendor_evidence == "cli-override: --vendor adi"

    def test_rerun_without_override_keeps_pinned_vendor(self, vendor_env, caplog):
        pdf, settings = vendor_env
        with pytest.raises(BackendUnavailableError):
            build_part(pdf, part_number="TEST9000", settings=settings, vendor="adi",
                       use_llm=False)
        with caplog.at_level(logging.WARNING), pytest.raises(BackendUnavailableError):
            build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        (src,) = load_inventory(settings.parts_dir / "TEST9000")
        assert src.vendor == "adi"
        # a deliberate override is not treated as drift
        assert not any("vendor drift" in r.message for r in caplog.records)

    def test_unpinned_build_detects_vendor(self, vendor_env):
        pdf, settings = vendor_env
        result = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        (src,) = load_inventory(settings.parts_dir / "TEST9000")
        assert src.vendor == "ti"  # synthetic page has no brand -> project default
        assert result.manifest.vendor == "ti"


class TestLegacyEvidenceBackfill:
    def test_legacy_inventory_gains_evidence_on_rebuild(self, vendor_env):
        pdf, settings = vendor_env
        # legacy pre-0.2.0 record: vendor pinned, no evidence recorded
        _pdf(pdf, ["Texas Instruments TEST9000 page one"])
        source = SourceDocument(
            content_hash=compute_content_hash(pdf),
            path=str(pdf),
            part_number="TEST9000",
            doc_type=DocType.DATASHEET,
            vendor="ti",
        )
        save_inventory([source], settings.parts_dir / "TEST9000")
        build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        (src,) = load_inventory(settings.parts_dir / "TEST9000")
        assert src.vendor_evidence == 'brand:"texas instruments" (p.1)'


class TestDriftWarning:
    def test_contradicting_detection_warns_and_does_not_reroute(self, vendor_env, caplog):
        pdf, settings = vendor_env
        # page-1 text is a different brand: detection contradicts the pin
        _pdf(pdf, ["Analog Devices TEST9000 page one"])
        source = SourceDocument(
            content_hash=compute_content_hash(pdf),
            path=str(pdf),
            part_number="TEST9000",
            doc_type=DocType.DATASHEET,
            vendor="ti",
            vendor_evidence='brand:"texas instruments" (p.1)',
        )
        save_inventory([source], settings.parts_dir / "TEST9000")

        with caplog.at_level(logging.WARNING):
            result = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        assert any("vendor drift" in r.message for r in caplog.records)
        # routing still follows the pinned value: build succeeds via ti_html
        assert result.manifest.vendor == "ti"

    def test_no_warning_when_detection_agrees(self, vendor_env, caplog):
        pdf, settings = vendor_env
        result = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        with caplog.at_level(logging.WARNING):
            build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        assert not any("vendor drift" in r.message for r in caplog.records)
        assert result.manifest.vendor == "ti"


class TestManifestVendor:
    def test_rebuilt_manifest_carries_vendor_and_version(self, vendor_env):
        pdf, settings = vendor_env
        result = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        assert result.manifest.vendor == "ti"
        from datasheet_analyzer.config import PIPELINE_VERSION

        assert result.manifest.pipeline_version == PIPELINE_VERSION == "0.2.0"
        data = json.loads((result.part_dir / "manifest.json").read_text(encoding="utf-8"))
        assert data["vendor"] == "ti"
        doc = result.manifest.documents[0]
        assert data["extraction_stats"][doc.content_hash]["backend"] == "ti_html"


class TestCli:
    def test_status_shows_vendor_and_evidence(self, tmp_path, monkeypatch, capsys):
        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        part = settings.parts_dir / "AFE7950"
        src = SourceDocument(
            content_hash="ab" * 32,
            path="afe7950.pdf",
            part_number="AFE7950",
            doc_type=DocType.DATASHEET,
            vendor="ti",
            vendor_evidence='brand:"texas instruments" (p.1)',
        )
        save_inventory([src], part)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)

        code = cli.main(["status"])
        out = capsys.readouterr().out
        assert code == 0
        assert "AFE7950" in out and "vendor: ti" in out
        assert "texas instruments" in out

    def test_status_built_part_shows_vendor_and_extraction_backend(
        self, vendor_env, monkeypatch, capsys
    ):
        pdf, settings = vendor_env
        build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        code = cli.main(["status"])
        out = capsys.readouterr().out
        assert code == 0
        assert "TEST9000" in out and "vendor: ti" in out
        assert "extraction: ti_html" in out

    def test_cli_build_unknown_vendor_name_exits_2(self, vendor_env, monkeypatch, capsys):
        pdf, settings = vendor_env
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        code = cli.main(["build", str(pdf), "--part", "X", "--vendor", "nvidia", "--no-llm"])
        err = capsys.readouterr().err
        assert code == 2
        assert "unknown vendor" in err and "nvidia" in err

    def test_cli_add_doc_with_vendor_pins_it(self, tmp_path, monkeypatch):
        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        pdf = tmp_path / "regmap.pdf"
        _pdf(pdf, ["register description file"])
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        code = cli.main(
            ["add-doc", str(pdf), "--part", "X", "--type", "register_map", "--vendor", "adi"]
        )
        assert code == 0
        (src,) = load_inventory(settings.parts_dir / "X")
        assert src.vendor == "adi"
        assert src.vendor_evidence == "cli-override: --vendor adi"
        assert src.doc_type == DocType.REGISTER_MAP


class TestWarnVendorDriftStandalone:
    def test_missing_pdf_is_skipped_silently(self, tmp_path, caplog):
        source = SourceDocument(
            content_hash="cd" * 32,
            path=str(tmp_path / "gone.pdf"),
            doc_type=DocType.DATASHEET,
            vendor="ti",
        )
        with caplog.at_level(logging.WARNING):
            warn_vendor_drift([source])
        assert not any("vendor drift" in r.message for r in caplog.records)
