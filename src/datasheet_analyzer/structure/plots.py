"""Plot catalog transform: RawDocument -> PlotSet.

Phase 3 turns the figure references cataloged in Phase 1 into a
machine-searchable plot index (the plot twin of Phase 2's specs.json).
"""

from __future__ import annotations

import re

from datasheet_analyzer.config import PLOTS_SCHEMA_VERSION
from datasheet_analyzer.models import PlotRecord, PlotSet, RawDocument, SectionNode
from datasheet_analyzer.structure.corpus import slugify

MEASURE_KEYWORDS: list[str] = [
    "acpr",
    "nsd",
    "output power",
    "fullscale",
    "gain error",
    "phase error",
    "phase noise",
    "imd",
    "hd2",
    "hd3",
    "harmonic",
    "return loss",
    "s11",
    "nf",
    "noise figure",
    "image rejection",
    "spurious",
    "sfdr",
    "snr",
    "eye diagram",
    "jitter",
    "settling",
    "bandwidth",
    "flatness",
    "dsa",
]

_SECTION_PATH_TAGS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\btx\b", re.IGNORECASE), "tx"),
    (re.compile(r"\brx\b", re.IGNORECASE), "rx"),
    (re.compile(r"\bfb\b", re.IGNORECASE), "fb"),
    (re.compile(r"\bpll\b|\bclock\b", re.IGNORECASE), "pll-clock"),
]

# Match common frequency expressions in section titles (e.g. "800 MHz", "0.85 GHz")
_FREQ_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mhz|ghz)", re.IGNORECASE)

# "Figure 4-1 TX Output ..." -> "4-1"; also accept "Figure 4-1a".
_FIGURE_RE = re.compile(r"Figure\s+(\d+(?:[-.]\d+)?[a-z]?)", re.IGNORECASE)


def figure_number(caption: str) -> str:
    """Extract the printed figure number from a caption."""
    m = _FIGURE_RE.search(caption)
    return m.group(1) if m else ""


def section_tags(section: SectionNode) -> list[str]:
    """Derive path + frequency tags from a section title."""
    title = section.title or ""
    tags: list[str] = []
    for pat, tag in _SECTION_PATH_TAGS:
        if pat.search(title) and tag not in tags:
            tags.append(tag)
    for m in _FREQ_RE.finditer(title):
        value = float(m.group(1))
        unit = m.group(2).lower()
        if unit == "ghz":
            value *= 1000
        # Normalize to a clean MHz integer when whole (e.g. 800.0 -> 800mhz)
        tag = f"{int(value)}mhz" if value == int(value) else f"{value}mhz"
        if tag not in tags:
            tags.append(tag)
    return tags


def caption_tags(caption: str) -> list[str]:
    """Return MEASURE_KEYWORDS that appear (substring, case-insensitive) in caption."""
    lowered = caption.lower()
    return [kw for kw in MEASURE_KEYWORDS if kw in lowered]


def plot_id(section: SectionNode, idx: int) -> str:
    """Stable plot id: section number + sequence ("4.12.1-f007").

    Honestly unnumbered sections (pdf_layout parts) key by their slugified
    title ("dac-f001") — otherwise two unnumbered figure sections of one
    part (AD9081's DAC and ADC subsections) would both emit "-f016" and
    collide on the same image file.
    """
    if section.number:
        return f"{section.number}-f{idx + 1:03d}"
    return f"{slugify(section.title)}-f{idx + 1:03d}"


def build_plotset(raw: RawDocument, part_number: str) -> PlotSet:
    """Convert every FigureRef in every section to a PlotRecord.

    IDs are stable: section order, then figure order within the section.
    The ``file`` field is left empty; pixel population is a separate stage.
    """
    plots: list[PlotRecord] = []
    for section in raw.sections:
        if not section.figures:
            continue
        tags_base = section_tags(section)
        for idx, fig in enumerate(section.figures):
            rec = PlotRecord(
                id=plot_id(section, idx),
                section=section.number,
                caption=fig.caption,
                figure_number=figure_number(fig.caption),
                conditions=fig.conditions,
                page_start=section.page_start,
                page_end=section.page_end,
                image_url=fig.image_url,
                file="",
                tags=tags_base + caption_tags(fig.caption),
            )
            plots.append(rec)
    return PlotSet(
        schema_version=PLOTS_SCHEMA_VERSION,
        part_number=part_number,
        doc_hash=raw.source.content_hash,
        plots=plots,
    )
