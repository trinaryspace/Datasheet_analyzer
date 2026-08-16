"""INDEX.md builder — the small always-loadable artifact.

INDEX.md is the only file an agent must read to navigate the whole corpus,
so it is built under a hard token budget. Section descriptions are the
decisive quality lever (an agent picks sections by these descriptions):
- `DeterministicWriter`: extractive descriptions (first informative
  sentence + key parameter symbols + figure count). Zero cost, offline.
- `LLMWriter`: one batched Claude call rewrites all descriptions for
  grep-ability; falls back to deterministic output on any failure.

Content rule: LLM writes *descriptions only*. Corpus content stays verbatim.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

from datasheet_analyzer.enrich.llm import LLMClient
from datasheet_analyzer.models import RawDocument
from datasheet_analyzer.protocol import AGENT_FILENAME
from datasheet_analyzer.structure.corpus import SectionPlan
from datasheet_analyzer.tokens import count_tokens, truncate_to_tokens

log = logging.getLogger(__name__)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class SectionMeta:
    """Everything INDEX.md knows about one section."""

    number: str
    title: str
    file: str  # path relative to part dir
    page_start: int | None
    page_end: int | None
    token_count: int
    n_tables: int
    n_figures: int
    description: str = ""


class DescriptionWriter(Protocol):
    def describe(self, raw: RawDocument, plans: list[SectionPlan]) -> dict[str, str]:
        """section key (number or title) -> description"""
        ...


def _section_key(number: str, title: str) -> str:
    return number or title


def _first_informative_sentence(paragraphs: list[str], max_words: int = 28) -> str:
    for para in paragraphs:
        sentence = _SENTENCE.split(para.strip().lstrip("• ").strip())[0].strip()
        if len(sentence.split()) >= 4:
            return " ".join(sentence.split()[:max_words])
    return ""


def _key_symbols(plan: SectionPlan, limit: int = 8) -> list[str]:
    """Distinctive first-column symbols from the section's tables."""
    out: list[str] = []
    for table in plan.section.tables:
        for row in table.grid:
            if row and row[0] and 1 < len(row[0]) <= 14 and row[0] not in out:
                out.append(row[0])
            if len(out) >= limit:
                return out
    return out


class DeterministicWriter:
    """Extractive descriptions: no LLM, no network, fully reproducible."""

    def describe(self, raw: RawDocument, plans: list[SectionPlan]) -> dict[str, str]:
        out: dict[str, str] = {}
        for plan in plans:
            sec = plan.section
            parts: list[str] = []
            sentence = _first_informative_sentence(sec.paragraphs)
            if sentence:
                parts.append(sentence)
            symbols = _key_symbols(plan)
            if symbols:
                parts.append("Parameters: " + ", ".join(symbols) + ".")
            if sec.figures:
                parts.append(f"{len(sec.figures)} plots.")
            out[_section_key(sec.number, sec.title)] = " ".join(parts) or "(no content)"
        return out


class LLMWriter:
    """LLM-rewritten descriptions in ONE batched call (cost control)."""

    SYSTEM = (
        "You write index entries for an electronics datasheet corpus. Each "
        "description lets a retrieval agent decide WHICH section to open: "
        "front-load the parameters, units, interfaces and synonyms an "
        "engineer would grep for. Never invent values. Descriptions must be "
        "faithful to the supplied excerpts."
    )

    def __init__(self, client: LLMClient, fallback: DescriptionWriter | None = None,
                 max_tokens: int = 4096):
        self.client = client
        self.fallback = fallback or DeterministicWriter()
        self.max_tokens = max_tokens

    def describe(self, raw: RawDocument, plans: list[SectionPlan]) -> dict[str, str]:
        base = self.fallback.describe(raw, plans)
        excerpts: list[str] = []
        for plan in plans:
            sec = plan.section
            excerpt = " ".join(sec.paragraphs)[:600]
            symbols = ", ".join(_key_symbols(plan))
            excerpts.append(
                f"[{_section_key(sec.number, sec.title)}] {sec.full_title}\n"
                f"excerpt: {excerpt}\nparams: {symbols}\nfigures: {len(sec.figures)}"
            )
        prompt = (
            "Below are the sections of one datasheet. Return ONLY a JSON object "
            "mapping each [section key] to a description of AT MOST 25 words, "
            "optimized for retrieval (key parameters, units, synonyms). "
            "No prose, no code fence.\n\n" + "\n\n".join(excerpts)
        )
        try:
            text = self.client.complete(self.SYSTEM, prompt, self.max_tokens)
            data = json.loads(text[text.find("{") : text.rfind("}") + 1])
        except Exception as exc:  # noqa: BLE001 - LLM/parse failures must never kill a build
            log.warning("LLM descriptions failed (%s); using deterministic", exc)
            return base
        for key in base:
            llm_desc = str(data.get(key, "")).strip()
            if llm_desc:
                base[key] = llm_desc
        return base


def pages_label(start: int | None, end: int | None) -> str:
    if start is None:
        return "?"
    if end and end != start:
        return f"{start}-{end}"
    return str(start)


def build_index_markdown(
    part_number: str,
    brief: str,
    key_facts: list[str],
    docs: list[tuple[str, str, int, str]],  # (doc_type, revision, pages, hash8)
    sections: list[SectionMeta],
    *,
    token_budget: int,
) -> str:
    """Render INDEX.md. If the section map would blow the budget, section
    descriptions are progressively truncated until it fits."""
    header = [
        f"# {part_number} — datasheet corpus",
        "",
        f"> {brief}" if brief else "",
        "",
    ]
    facts = ["## Key facts (verbatim from Features, p.1)", ""]
    facts += [f"- {f}" for f in key_facts] or ["- (none extracted)"]
    facts.append("")

    doc_lines = ["## Documents", ""]
    for dtype, rev, pages, h8 in docs:
        doc_lines.append(f"- `{dtype}` {rev or ''} — {pages} pages — `docs/{dtype}-{h8}/`")
    doc_lines.append("")

    # A pointer, not a copy. The retrieval discipline used to live here as
    # prose; ticket 08 promoted it to `AGENT.md`, published beside this file.
    # Restating it here would create a second protocol that can disagree with
    # the first — and would spend the budget of the map on text that is one
    # file away.
    conventions = [
        "## How to use this corpus",
        "",
        (
            f"- Read `{AGENT_FILENAME}` beside this file first: the retrieval "
            "protocol (both access paths, citations, the confidence rule)."
        ),
        "",
    ]

    def _doc_label(s: SectionMeta) -> tuple[str, str]:
        # s.file is like docs/<doc_type>-<hash8>/sections/...; extract prefix.
        parts = s.file.split("/")
        if len(parts) >= 2 and parts[0] == "docs":
            return (parts[0], parts[1])
        return ("docs", "unknown")

    def render_map(desc_budget: int) -> list[str]:
        lines: list[str] = []
        # Group sections by document directory.
        grouped: dict[str, list[SectionMeta]] = {}
        for s in sections:
            grouped.setdefault(_doc_label(s)[1], []).append(s)
        for doc_dir, secs in grouped.items():
            lines.append(f"## Section map — `{doc_dir}`")
            lines.append("")
            for s in secs:
                desc = truncate_to_tokens(s.description, desc_budget) if s.description else ""
                title = f"{s.number} {s.title}".strip()
                bits = f"{s.token_count} tok"
                if s.n_tables:
                    bits += f", {s.n_tables} tables"
                if s.n_figures:
                    bits += f", {s.n_figures} figs"
                lines.append(
                    f"- **{title}** — p.{pages_label(s.page_start, s.page_end)} "
                    f"— `{s.file}` ({bits})"
                )
                if desc:
                    lines.append(f"  {desc}")
            lines.append("")
        return lines

    # Staged degradation under budget pressure: truncate descriptions first,
    # then drop the conventions block, then key facts. The section map and
    # document pointers are the product — they are never dropped.
    for desc_budget, with_conv, with_facts in [
        (30, True, True), (20, True, True), (12, True, True), (6, True, True),
        (0, True, True), (0, False, True), (0, False, False),
    ]:
        body = list(header)  # copy: += below must not mutate `header`
        if with_facts:
            body += facts
        body += doc_lines
        if with_conv:
            body += conventions
        body += render_map(desc_budget)
        text = "\n".join(body)
        if count_tokens(text) <= token_budget:
            return text
    return "\n".join(list(header) + doc_lines + render_map(0))
