"""Pain point: tables split from their context; sections out of order;
missing provenance. Pins the corpus rendering contract."""

from __future__ import annotations

from datasheet_analyzer.models import (
    Footnote,
    RawDocument,
    SectionNode,
    SourceDocument,
)
from datasheet_analyzer.structure.corpus import (
    build_section_plans,
    section_stem,
    slugify,
)
from datasheet_analyzer.structure.tables import html_table_to_block

TABLE = """
<table><thead><tr><th>PARAMETER</th><th>TYP</th><th>UNIT</th></tr></thead>
<tbody><tr><td>DSA range</td><td>40</td><td>dB</td></tr></tbody></table>
"""


def _raw(sections: list[SectionNode]) -> RawDocument:
    return RawDocument(
        source=SourceDocument(content_hash="abc", path="x.pdf", revision="SBASA41E"),
        sections=sections,
        extractor="test",
    )


def _section(number: str, title: str, **kw) -> SectionNode:
    return SectionNode(number=number, title=title, **kw)


def test_slugify_and_stems_preserve_reading_order():
    assert slugify("TX Typical Characteristics at 1.75 GHz – 1.9 GHz") == (
        "tx-typical-characteristics-at-1-75-ghz-1-9-ghz"
    )
    s = _section("4.5", "Transmitter Electrical Characteristics")
    assert section_stem(s) == "4-5-transmitter-electrical-characteristics"
    s2 = _section("", "Features")
    assert section_stem(s2) == "features"


def test_table_is_atomic_within_one_section_file():
    t = html_table_to_block(
        TABLE,
        conditions="Typical values at TA = +25°C",
        footnotes=[Footnote(marker="(2)", text="After DSA calibration procedure")],
        page=7,
    )
    raw = _raw([_section("4.5", "TX Electrical", paragraphs=["intro"], tables=[t])])
    plans = build_section_plans(raw)
    assert len(plans) == 1
    md = plans[0].markdown

    # the whole table, in one file, exactly once
    assert md.count("DSA range") == 1
    # conditions travel with the table
    assert "Test conditions" in md and "TA = +25°C" in md
    # footnotes travel with the table
    assert "After DSA calibration procedure" in md
    # machine-readable twin is referenced and produced
    assert plans[0].table_files[0].name.endswith(".csv")
    assert "DSA range" in plans[0].table_files[0].csv


def test_page_provenance_header_present():
    raw = _raw([_section("4.5", "TX Electrical", page_start=7, page_end=13)])
    md = build_section_plans(raw)[0].markdown
    assert "<!-- source: SBASA41E p.7-13 -->" in md


def test_sections_render_in_source_order():
    secs = [
        _section("1", "Features"),
        _section("4.1", "Abs Max"),
        _section("4.12.1", "TX Typical 800 MHz"),
        _section("7", "Mechanical"),
    ]
    plans = build_section_plans(_raw(secs))
    titles = [p.section.number for p in plans]
    assert titles == ["1", "4.1", "4.12.1", "7"]


def test_boilerplate_removed_from_paragraphs_and_counted():
    raw = _raw(
        [_section("1", "Features", paragraphs=["Real content", "www.ti.com", "More content"])]
    )
    plans = build_section_plans(raw)
    assert plans[0].boilerplate_removed == 1
    assert "www.ti.com" not in plans[0].markdown
    assert "Real content" in plans[0].markdown


def test_figures_render_with_caption_conditions_page():
    from datasheet_analyzer.models import FigureRef

    fig = FigureRef(caption="TX Output Fullscale vs Frequency", conditions="DSA = 0", page=29)
    md = build_section_plans(_raw([_section("4.12.1", "TX 800", figures=[fig])]))[0].markdown
    assert "TX Output Fullscale vs Frequency" in md
    assert "DSA = 0" in md
    assert "(p.29)" in md
