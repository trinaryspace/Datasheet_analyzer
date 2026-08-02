"""Corpus builder: RawDocument -> renderable per-section file plans.

Pain points addressed here:
- Table atomicity: a table is rendered *inside* its section file, in one
  piece, with its conditions preamble and footnotes adjacent — never split
  across files or separated from context. A CSV twin is emitted for
  machine consumption.
- Page provenance: every section file opens with a source-page comment so
  answers can cite `p.N` without further lookup.
- Reading order: sections render in source (TOC) order; files are named so
  alphabetical listing preserves it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from datasheet_analyzer.models import RawDocument, SectionNode
from datasheet_analyzer.structure.boilerplate import strip_boilerplate_lines
from datasheet_analyzer.tokens import count_tokens

_WS = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    s = _WS.sub("-", text.lower()).strip("-")
    return s[:max_len].rstrip("-")


def section_stem(section: SectionNode) -> str:
    """File stem for a section; numbered sections keep their number first so
    directory listing preserves reading order."""
    if section.number:
        num = section.number.replace(".", "-")
        return slugify(f"{num}-{section.title}")
    return slugify(section.title)


@dataclass
class TableFile:
    name: str  # e.g. tables/4-5-...-t01.csv
    csv: str


@dataclass
class SectionPlan:
    section: SectionNode
    file: str  # sections/<stem>.md (relative to doc dir)
    markdown: str
    token_count: int
    table_files: list[TableFile] = field(default_factory=list)
    boilerplate_removed: int = 0


def render_section_markdown(
    section: SectionNode, *, doc_label: str, table_files: list[TableFile]
) -> str:
    """Render one section to self-contained markdown.

    Layout is deliberately stable so agents can parse it:
    H1 title, source-page comment, paragraphs, then each table as:
    caption + conditions quote + markdown table + footnotes + CSV pointer.
    """
    out: list[str] = [f"# {section.full_title}", ""]
    pages = ""
    if section.page_start is not None:
        pages = f" p.{section.page_start}"
        if section.page_end and section.page_end != section.page_start:
            pages += f"-{section.page_end}"
    out.append(f"<!-- source: {doc_label}{pages} -->")
    out.append("")

    for para in section.paragraphs:
        out += [para, ""]

    for i, table in enumerate(section.tables):
        title = table.caption or f"Table {i + 1}"
        out += [f"## {title}", ""]
        if table.conditions:
            out += [f"> **Test conditions:** {table.conditions}", ""]
        out += [table.markdown, ""]
        if table.footnotes:
            out.append("**Footnotes:**")
            out.append("")
            for fn in table.footnotes:
                out.append(f"- {fn.marker} {fn.text}")
            out.append("")
        if i < len(table_files):
            out += [f"*Machine-readable: `{table_files[i].name}`*", ""]

    if section.figures:
        out += ["## Figures", ""]
        for fig in section.figures:
            line = f"- **{fig.caption}**"
            if fig.conditions:
                line += f" — {fig.conditions}"
            if fig.page:
                line += f" (p.{fig.page})"
            out.append(line)
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def build_section_plans(raw: RawDocument) -> list[SectionPlan]:
    """Convert every section of a RawDocument into render plans."""
    doc_label = raw.source.revision or raw.source.path
    plans: list[SectionPlan] = []
    total_removed = 0

    for section in raw.sections:
        stem = section_stem(section)
        table_files = [
            TableFile(name=f"tables/{stem}-t{i + 1:02d}.csv", csv=t.csv)
            for i, t in enumerate(section.tables)
        ]
        clean_paras, removed = strip_boilerplate_lines(section.paragraphs)
        total_removed += removed
        section = section.model_copy(update={"paragraphs": clean_paras})
        md = render_section_markdown(section, doc_label=doc_label, table_files=table_files)
        plans.append(
            SectionPlan(
                section=section,
                file=f"sections/{stem}.md",
                markdown=md,
                token_count=count_tokens(md),
                table_files=table_files,
                boilerplate_removed=removed,
            )
        )
    return plans
