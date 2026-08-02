"""Tests for plot pixel publishing."""

from __future__ import annotations

import fitz

from datasheet_analyzer.models import PlotRecord, PlotSet
from datasheet_analyzer.publish.plots import (
    fetch_plot_images,
    render_plot_pages_fallback,
)


def test_fetch_plot_images_writes_files_and_updates_records(tmp_path):
    doc_dir = tmp_path / "docs" / "datasheet-abc123"
    doc_dir.mkdir(parents=True)
    payload = b"GIF89a\x01\x00\x01\x00\x00\x00\x00!"

    def fetcher(url: str) -> bytes:
        return payload

    plotset = PlotSet(
        schema_version="1",
        part_number="TEST",
        doc_hash="a" * 64,
        plots=[
            PlotRecord(
                id="4.12.1-f001",
                section="4.12.1",
                caption="Figure 4-1 TX Output Fullscale",
                image_url="https://ti.com/ods/images/SBASA41E/GUID-low.gif",
            )
        ],
    )

    written = fetch_plot_images(plotset, doc_dir, fetcher=fetcher)
    assert written == 1
    rec = plotset.plots[0]
    assert rec.file
    assert "figures/4-12-1/4.12.1-f001.gif" in rec.file
    assert (doc_dir / "figures" / "4-12-1" / "4.12.1-f001.gif").exists()


def test_fetch_plot_images_skips_missing_url(tmp_path):
    doc_dir = tmp_path / "docs" / "datasheet-abc123"
    doc_dir.mkdir(parents=True)

    def fetcher(_url: str) -> bytes:
        raise ConnectionError("nope")

    plotset = PlotSet(
        schema_version="1",
        part_number="TEST",
        doc_hash="a" * 64,
        plots=[
            PlotRecord(
                id="4.12.1-f001",
                section="4.12.1",
                caption="Figure 4-1 TX Output Fullscale",
                image_url="https://ti.com/ods/images/SBASA41E/GUID-low.gif",
            )
        ],
    )

    written = fetch_plot_images(plotset, doc_dir, fetcher=fetcher)
    assert written == 0
    assert plotset.plots[0].file == ""


def test_render_plot_pages_fallback(tmp_path):
    pdf_path = tmp_path / "one_page.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "plot area")
    doc.save(str(pdf_path))
    doc.close()

    doc_dir = tmp_path / "docs" / "datasheet-abc123"
    doc_dir.mkdir(parents=True)

    plotset = PlotSet(
        schema_version="1",
        part_number="TEST",
        doc_hash="a" * 64,
        plots=[
            PlotRecord(
                id="4.5-f001",
                section="4.5",
                caption="Figure 4-1",
                page_start=1,
            )
        ],
    )

    written = render_plot_pages_fallback(plotset, doc_dir, pdf_path, dpi=72)
    assert written == 1
    rec = plotset.plots[0]
    assert "figures/4-5/4.5-f001.png" in rec.file
    assert (doc_dir / "figures" / "4-5" / "4.5-f001.png").exists()
