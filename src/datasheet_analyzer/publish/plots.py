"""Plot pixel stage: download/render figure images into the corpus.

This is the only place network bytes for figures are fetched. Every
successful download is cached on disk; failures are logged and leave
``PlotRecord.file`` empty so the caller can fall back to PDF rendering.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz

from datasheet_analyzer.extract.http import BinaryFetcher
from datasheet_analyzer.extract.pdf_layout import (
    figure_anchor_map,
    figure_caption_key,
)
from datasheet_analyzer.models import PlotRecord, PlotSet

log = logging.getLogger(__name__)

# TI image URLs commonly end in "-low.gif"; probe the likely variants and
# keep the largest successful response.
_VARIANT_SUFFIXES: list[str] = ["-high.gif", ".gif", ".png", ".jpg", ""]


def _image_variants(url: str) -> list[str]:
    """Return candidate URLs to try, starting with the original."""
    variants = [url]
    # If the URL has a -low/-high suffix, also try the others.
    base = url
    for suffix in ("-low.gif", "-high.gif"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    else:
        # No recognized suffix; still probe bare GUID-ish variants.
        base = re.sub(r"\.[^.]+$", "", url)
    for ext in _VARIANT_SUFFIXES:
        candidate = base + ext
        if candidate != url:
            variants.append(candidate)
    return variants


def _section_stem(number: str) -> str:
    return number.replace(".", "-") if number else "unsectioned"


def _plot_file_path(doc_dir: Path, record: PlotRecord, ext: str) -> Path:
    stem = _section_stem(record.section)
    return doc_dir / "figures" / stem / f"{record.id}{ext}"


def _extension_from_url(url: str) -> str:
    suffix = Path(url).suffix.lower()
    return suffix if suffix in {".gif", ".png", ".jpg", ".jpeg", ".svg", ".bin"} else ".bin"


def _absolute_url(url: str, base: str = "https://www.ti.com") -> str:
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        return base.rstrip("/") + url
    return url


def _set_record_file(record: PlotRecord, dest: Path, doc_dir: Path) -> None:
    # Record a path relative to the part dir (doc_dir's parent's parent).
    rel = dest.relative_to(doc_dir.parent.parent)
    record.file = str(rel).replace("\\", "/")


def fetch_plot_images(plotset: PlotSet, doc_dir: Path, *, fetcher: BinaryFetcher,
                      base_url: str = "https://www.ti.com") -> int:
    """Download plot images for every PlotRecord with an image_url.

    The largest successful variant is kept (see probe findings in the Phase 3
    report). Images are written to ``figures/<section-stem>/<id>.<ext>`` under
    ``doc_dir``. Returns the number of files written. Failures are logged and
    leave ``record.file`` empty.
    """
    doc_dir = Path(doc_dir)
    written = 0
    for record in plotset.plots:
        if not record.image_url:
            continue
        best: tuple[int, bytes, str] | None = None
        for candidate in _image_variants(_absolute_url(record.image_url, base_url)):
            try:
                data = fetcher(candidate)
                if best is None or len(data) > best[0]:
                    best = (len(data), data, candidate)
            except Exception as exc:  # noqa: BLE001
                log.debug("plot fetch failed for %s: %s", candidate[:120], exc)
                continue
        if best is None:
            log.warning("all image variants failed for %s", record.id)
            continue
        ext = _extension_from_url(best[2])
        dest = _plot_file_path(doc_dir, record, ext)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(best[1])
        _set_record_file(record, dest, doc_dir)
        written += 1
    return written


def render_figure_regions(
    plotset: PlotSet, doc_dir: Path, pdf_path: Path, *, dpi: int
) -> int:
    """Clip-render each cataloged figure's vector region (pdf_layout path).

    The clip is the region above the figure's own "Figure N." caption
    (SPEC story 20), recomputed deterministically with the extractor's own
    caption scan via ``figure_anchor_map`` so the image always matches the
    cataloged caption and page. Records whose caption is not found on any
    section page keep ``file == ""`` — cataloged but honestly unpictured.
    """
    doc_dir = Path(doc_dir)
    pdf_path = Path(pdf_path)
    written = 0
    anchors = figure_anchor_map(pdf_path)
    if not anchors or not plotset.plots:
        return 0
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    with fitz.open(str(pdf_path)) as pdf:
        for record in plotset.plots:
            if record.file:
                continue
            key = figure_caption_key(record.caption)
            hit = None
            for (pgnum, cap), (top, y) in anchors.items():
                if cap != key:
                    continue
                if record.page_start is not None and pgnum < record.page_start:
                    continue
                if record.page_end is not None and pgnum > record.page_end:
                    continue
                hit = (pgnum, top, y)
                break
            if hit is None or hit[2] - hit[1] < 6.0:
                log.warning("no clip anchor for plot %s (%s)",
                            record.id, record.caption[:60])
                continue
            pgnum, top, y = hit
            if pgnum - 1 >= len(pdf):
                continue
            page = pdf[pgnum - 1]
            clip = fitz.Rect(0.0, max(0.0, top), page.rect.width, y - 3.0)
            try:
                pix = page.get_pixmap(matrix=matrix, clip=clip)
            except Exception as exc:  # noqa: BLE001 — honesty over crash
                log.warning("clip render failed for plot %s: %s", record.id, exc)
                continue
            dest = _plot_file_path(doc_dir, record, ".png")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(pix.tobytes("png"))
            _set_record_file(record, dest, doc_dir)
            written += 1
    return written


def render_plot_pages_fallback(
    plotset: PlotSet, doc_dir: Path, pdf_path: Path, *, dpi: int
) -> int:
    """Render full PDF pages for plots that still have no image file.

    Used when a download 404s and for ``--offline`` builds. No bbox cropping
    is attempted — vector plot bboxes are unreliable.
    """
    doc_dir = Path(doc_dir)
    pdf_path = Path(pdf_path)
    written = 0
    matrix = fitz.Matrix(dpi / 72, dpi / 72)

    with fitz.open(str(pdf_path)) as pdf:
        for record in plotset.plots:
            if record.file or record.page_start is None:
                continue
            # Render the section's page range as a single PNG (use start page).
            page_idx = record.page_start - 1  # PDF pages are 0-based in fitz
            if page_idx < 0 or page_idx >= len(pdf):
                log.warning("plot %s page %s out of PDF range", record.id, record.page_start)
                continue
            page = pdf[page_idx]
            pix = page.get_pixmap(matrix=matrix)
            dest = _plot_file_path(doc_dir, record, ".png")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(pix.tobytes("png"))
            _set_record_file(record, dest, doc_dir)
            written += 1
    return written
