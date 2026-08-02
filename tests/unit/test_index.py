"""Pain point: INDEX.md is the always-loaded artifact — it must stay inside
its token budget, contain everything an agent needs to navigate, and have
informative section descriptions (the proven retrieval lever)."""

from __future__ import annotations

import json

from datasheet_analyzer.enrich import (
    DeterministicWriter,
    FakeClient,
    LLMWriter,
    SectionMeta,
    build_index_markdown,
)
from datasheet_analyzer.models import RawDocument, SectionNode, SourceDocument, TableBlock
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.tokens import count_tokens


def _raw() -> RawDocument:
    return RawDocument(
        source=SourceDocument(content_hash="h" * 64, path="x.pdf", revision="TEST1A"),
        sections=[
            SectionNode(
                number="1", title="Features", level=1, page_start=1, page_end=1,
                paragraphs=["Quad RF sampling 12GSPS transmit DACs.",
                            "Package: 17mm FCBGA."],
            ),
            SectionNode(
                number="4.5", title="Transmitter Electrical Characteristics", level=2,
                page_start=7, page_end=13,
                paragraphs=["Typical values at TA = +25°C unless otherwise noted."],
                tables=[TableBlock(headers=["PARAMETER", "TYP"],
                                   grid=[["DACRES", "14"], ["Pmax_FS", "4.2"]])],
            ),
            SectionNode(
                number="4.12.1", title="TX Typical Characteristics 800 MHz", level=3,
                page_start=29, page_end=37,
                figures=[__import__("datasheet_analyzer.models", fromlist=["FigureRef"]).FigureRef(caption=f"Fig {i}") for i in range(43)],
            ),
        ],
        extractor="test",
    )


class TestDeterministicWriter:
    def test_descriptions_include_symbols_sentences_figure_counts(self):
        raw = _raw()
        plans = build_section_plans(raw)
        desc = DeterministicWriter().describe(raw, plans)
        assert "12GSPS" in desc["1"]
        assert "DACRES" in desc["4.5"] and "Pmax_FS" in desc["4.5"]
        assert "43 plots" in desc["4.12.1"]

    def test_empty_section_gets_placeholder(self):
        raw = _raw()
        raw.sections.append(SectionNode(number="9", title="Empty", level=1))
        plans = build_section_plans(raw)
        desc = DeterministicWriter().describe(raw, plans)
        assert desc["9"] == "(no content)"


class TestLLMWriter:
    def test_llm_descriptions_used_when_valid_json(self):
        raw = _raw()
        plans = build_section_plans(raw)
        payload = json.dumps({"4.5": "TX DAC specs: output power, DSA, ACPR, NSD"})
        writer = LLMWriter(FakeClient(payload))
        desc = writer.describe(raw, plans)
        assert desc["4.5"] == "TX DAC specs: output power, DSA, ACPR, NSD"
        # keys the LLM omitted keep their deterministic description
        assert "DACRES" in desc["4.5"] or "12GSPS" in desc["1"]

    def test_garbage_response_falls_back_to_deterministic(self):
        raw = _raw()
        plans = build_section_plans(raw)
        writer = LLMWriter(FakeClient("not json at all"))
        desc = writer.describe(raw, plans)
        assert "DACRES" in desc["4.5"]  # deterministic content survived

    def test_one_batched_call_only(self):
        raw = _raw()
        plans = build_section_plans(raw)
        client = FakeClient("{}")
        LLMWriter(client).describe(raw, plans)
        assert len(client.calls) == 1  # cost control: batched, not per-section


def _metas() -> list[SectionMeta]:
    return [
        SectionMeta(number="1", title="Features", file="docs/datasheet-deadbeef/sections/1-features.md",
                    page_start=1, page_end=1, token_count=120, n_tables=0, n_figures=0,
                    description="Headline capabilities and package."),
        SectionMeta(number="4.5", title="TX Electrical", file="docs/datasheet-deadbeef/sections/4-5-tx.md",
                    page_start=7, page_end=13, token_count=4200, n_tables=1, n_figures=0,
                    description="DAC resolution, output power, DSA range/step/accuracy, gain flatness."),
    ]


class TestBuildIndexMarkdown:
    def test_contains_all_navigation_essentials(self):
        md = build_index_markdown(
            "AFE7950", "4T6R RF sampling AFE with 12GSPS DACs and 3GSPS ADCs.",
            ["Quad RF sampling 12GSPS transmit DACs"],
            [("datasheet", "SBASA41E", 146, "deadbeef")],
            _metas(), token_budget=3000,
        )
        assert "# AFE7950" in md
        assert "12GSPS DACs" in md  # brief
        assert "Quad RF sampling" in md  # key facts
        assert "SBASA41E" in md and "146 pages" in md  # documents
        assert "docs/datasheet-deadbeef/" in md  # doc dir pointer
        assert "p.7-13" in md  # page ranges
        assert "DSA range/step/accuracy" in md  # descriptions
        assert "cite those pages" in md  # conventions

    def test_budget_enforcement_shrinks_descriptions(self):
        big = build_index_markdown("P", "brief", ["fact"], [("datasheet", "R", 10, "deadbeef")],
                                   _metas(), token_budget=3000)
        tiny = build_index_markdown("P", "brief", ["fact"], [("datasheet", "R", 10, "deadbeef")],
                                    _metas(), token_budget=140)
        assert count_tokens(tiny) <= 140
        assert count_tokens(tiny) < count_tokens(big)
        # even at the tightest budget the map itself survives
        assert "## Section map" in tiny and "4-5-tx.md" in tiny

    def test_unpaged_sections_render_honestly(self):
        metas = _metas()
        metas[0].page_start = metas[0].page_end = None
        md = build_index_markdown("P", "", [], [], metas, token_budget=3000)
        assert "p.?" in md
