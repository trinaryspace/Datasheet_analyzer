"""Plot pixel stage: download/render figure images into the corpus.

This is the only place network bytes for figures are fetched. Every
successful download is cached on disk; failures are logged and leave
``PlotRecord.file`` empty so the caller can fall back to PDF rendering.

**Where a figure path is anchored** (ticket 04). Every image is written to
``<doc_dir>/figures/<section-stem>/<id>.<ext>`` and ``PlotRecord.file``
records that path *relative to the root the document directory was published
under* — the parent of the ``docs/`` directory holding it, which
``artifact_root()`` names:

| published into | root | `PlotRecord.file` |
|---|---|---|
| `parts/<PART>/docs/<doc>/` | the part dir | part-relative |
| `<library>/docs/<doc>/` (shared) | the library dir | library-relative |

The string is identical in both cases; only the root differs, and the root is
recoverable from where ``plots.json`` itself sits — it is always
``<root>/docs/<doc>/plots.json``. That is why ``resolve_plot_file()`` takes
the document directory rather than a root: a record can never be resolved
against a root the file it came from does not sit under.

What it *cannot* survive is a file written by the old code, whose paths were
always part-relative. Such a file resolved against a library root points at
nothing, or worse at another part's figure of the same name. So the schema
version is the gate: ``PLOTS_SCHEMA_VERSION == "2"`` means "these paths are
anchored at this file's own root", and anything older is rejected by
``load_plotset()`` with a message that says to republish, never silently
resolved. See `docs/adr/0005-documents-apply-to-parts.md` for why documents
are published once and referenced by many parts at all.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import fitz

from datasheet_analyzer.config import PLOTS_SCHEMA_VERSION
from datasheet_analyzer.extract.http import BinaryFetcher
from datasheet_analyzer.extract.pdf_layout import (
    figure_anchor_map,
    figure_caption_key,
    figure_title_anchor_map,
)
from datasheet_analyzer.models import PlotRecord, PlotSet

log = logging.getLogger(__name__)

PLOTS_FILENAME = "plots.json"


class StalePlotsSchemaError(ValueError):
    """A ``plots.json`` too old for its figure paths to be resolvable.

    Raised rather than returned: a caller that ignores a return value would
    go on to join a part-relative path onto a library root and read (or fail
    to read) the wrong file, which is the one outcome ticket 04 forbids.
    """


def artifact_root(doc_dir: Path | str) -> Path:
    """The root a published document's artifact paths are relative to.

    A document directory is always ``<root>/docs/<doc_type>-<hash8>``, so the
    root is two levels up — the part directory for a per-part publish, the
    library directory for a shared one. Named here so that the writer, the
    renderers and the resolver all agree on one rule instead of each
    re-deriving it.
    """
    return Path(doc_dir).parent.parent


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
    """Absolute destination of one record's pixels inside ``doc_dir``.

    Unchanged in shape by ticket 04 — a figure still lives beside its
    document — but it is now the single place that shape is written down, so
    that a shared document directory and a per-part one lay out identically
    and a record copied between them stays valid.
    """
    stem = _section_stem(record.section)
    return Path(doc_dir) / "figures" / stem / f"{record.id}{ext}"


def plot_file_path(record: PlotRecord, *, doc_dir: Path, ext: str = ".png") -> Path:
    """Public twin of ``_plot_file_path`` — where this record's pixels belong."""
    return _plot_file_path(Path(doc_dir), record, ext)


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
    """Record where the pixels landed, relative to the document's own root.

    Ticket 04: the root is ``artifact_root(doc_dir)`` — the part directory
    for a per-part publish and the *library* directory for a shared one — so
    a document published once into the shared store is referenced by every
    part that applies to it without any part holding a copy. The written
    string is the same either way (`docs/<doc>/figures/...`); which root it
    hangs off is carried by `PLOTS_SCHEMA_VERSION == "2"` and by the location
    of the `plots.json` the record is read back out of.
    """
    rel = Path(dest).relative_to(artifact_root(doc_dir))
    record.file = str(rel).replace("\\", "/")


def load_plotset(doc_dir: Path | str) -> PlotSet | None:
    """Read ``<doc_dir>/plots.json``; `None` when the document has none.

    Raises `StalePlotsSchemaError` for a file written before figure paths
    became root-anchored (schema `"1"`). A missing file is not an error — a
    `pdf_text` register map legitimately catalogs no figures — but a file at
    the wrong version is, because nothing downstream can tell which root its
    paths were meant for.
    """
    path = Path(doc_dir) / PLOTS_FILENAME
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("schema_version", "") if isinstance(data, dict) else ""
    if version != PLOTS_SCHEMA_VERSION:
        raise StalePlotsSchemaError(
            f"{path}: plots schema {version or '(unset)'}, expected "
            f"{PLOTS_SCHEMA_VERSION}. Its figure paths are part-relative and "
            f"would resolve against the wrong root — republish this document "
            f"instead of reading it."
        )
    return PlotSet.model_validate(data)


def resolve_plot_file(
    record: PlotRecord,
    *,
    doc_dir: Path | str,
    schema_version: str = PLOTS_SCHEMA_VERSION,
) -> Path | None:
    """Absolute path of a record's image, or `None` when it has none.

    `None` covers the three honest cases — a record cataloged without pixels,
    a file that has since been removed from the (possibly shared) store, and
    a path that tries to escape its root. A *stale* schema is not one of
    them: that raises, because resolving it would silently pick the wrong
    root.
    """
    if schema_version != PLOTS_SCHEMA_VERSION:
        raise StalePlotsSchemaError(
            f"plots schema {schema_version or '(unset)'}, expected "
            f"{PLOTS_SCHEMA_VERSION}: figure paths from an older publish are "
            f"part-relative and cannot be resolved against a library root."
        )
    if not record.file:
        return None
    root = artifact_root(doc_dir)
    candidate = Path(os.path.normpath(str(root / record.file)))
    try:
        candidate.relative_to(Path(os.path.normpath(str(root))))
    except ValueError:
        log.warning("figure path escapes its root: %s", record.file)
        return None
    return candidate if candidate.is_file() else None


def fetch_plot_images(
    plotset: PlotSet, doc_dir: Path, *, fetcher: BinaryFetcher, base_url: str = "https://www.ti.com"
) -> int:
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


def render_figure_regions(plotset: PlotSet, doc_dir: Path, pdf_path: Path, *, dpi: int) -> int:
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
    title_anchors = figure_title_anchor_map(pdf_path)
    if not plotset.plots:
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
            if hit is None:
                # ticket 09: captionless-era figures anchor by their printed
                # title band (QPA1003P block diagram + performance plots)
                for (pgnum, cap), (top, y) in title_anchors.items():
                    if cap != key:
                        continue
                    if record.page_start is not None and pgnum < record.page_start:
                        continue
                    if record.page_end is not None and pgnum > record.page_end:
                        continue
                    hit = (pgnum, top, y)
                    break
            if hit is None or hit[2] - hit[1] < 6.0:
                log.warning("no clip anchor for plot %s (%s)", record.id, record.caption[:60])
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


def render_plot_pages_fallback(plotset: PlotSet, doc_dir: Path, pdf_path: Path, *, dpi: int) -> int:
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
