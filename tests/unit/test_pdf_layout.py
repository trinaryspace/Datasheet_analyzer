"""pdf_layout paragraph core — external corpus behavior only.

Synthetic fitz-built PDFs pin the structure ladder and the furniture rules
through the single seam the spec allows: `build_part` with temp-dir
settings, asserting what lands in the corpus (section files + page citations,
manifest backend + vendor evidence, INDEX). No engine internals are touched.

Coverage:
- structure ladder: numbered outline -> numbered sections; unnumbered
  outline -> honestly unnumbered slug-keyed files; bookmark-less PDF with a
  printed-TOC (dot leaders) -> sections from the generic parse; nothing at
  all -> per-page sections ("Page N").
- furniture families (universal patterns + recurrence, zero vendor strings):
  ADI "Rev. 0 | N of M", Qorvo "- N of M -", old-TI web chrome + bare page
  numbers — all absent from section paragraphs; a furniture-free PDF keeps
  every line; pattern-shaped mid-page prose survives.
- paragraphs land in the deepest covering section only (parents never
  duplicate children); mechanics: extraction-cache hit on rebuild, manifest
  records the pdf_layout backend and the pinned vendor evidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from datasheet_analyzer.config import Settings
from datasheet_analyzer.pipeline import build_part

PAGE_W, PAGE_H = 612.0, 792.0


def _make_pdf(path: Path, pages, toc: list[list] | None = None) -> None:
    """pages: list of pages; each page = list of (x, y, text) lines."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text in lines:
            page.insert_text((x, y), text)
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()


def _body(texts: list[str], x: float = 56.0, y0: float = 90.0, step: float = 18.0):
    return [(x, y0 + i * step, t) for i, t in enumerate(texts)]


def _top(texts: list[str], y0: float = 24.0, step: float = 15.0):
    return _body(texts, x=56.0, y0=y0, step=step)


def _bottom(texts: list[str], y0: float = 748.0, step: float = 13.0):
    return _body(texts, x=56.0, y0=y0, step=step)


def _build(tmp_path, name: str, pages, toc: list[list] | None = None, *,
           part: str = "P1", vendor: str = "unknown"):
    """Synthetic part through the pipeline seam; vendor pinned to the layout
    floor so the engine (not TI HTML) must serve the build."""
    pdf = Path(tmp_path) / name
    _make_pdf(pdf, pages, toc)
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    return build_part(pdf, part_number=part, settings=settings,
                      vendor=vendor, use_llm=False)


def _doc_dir(result) -> Path:
    return result.part_dir / "docs" / f"datasheet-{result.manifest.documents[0].content_hash[:8]}"


def _section_md(result, stem: str) -> str:
    path = _doc_dir(result) / "sections" / f"{stem}.md"
    assert path.exists(), f"missing section file {path.name}"
    return path.read_text(encoding="utf-8")


def _paras(md: str) -> list[str]:
    """Paragraphs of a rendered section file (after title + source comment)."""
    blocks = [b.strip() for b in md.split("\n\n")]
    return [b for b in blocks[2:] if b]


def _pages(md: str) -> str:
    """The page citation of a rendered section file ("p.3-4")."""
    m = re.search(r"<!-- source: .*? (p\.\d+(?:-\d+)?) -->", md)
    assert m, f"no source comment in {md!r}"
    return m.group(1)


class TestStructureLadder:
    def test_numbered_outline_produces_numbered_sections_and_ranges(self, tmp_path):
        pages = [
            _body(["1 Features", "Overload protection on the input and output."]),
            _body(["A continuation line with data 0.5 mV."]),
            _body(["2 Specifications", "2.1 Electrical Characteristics",
                   "Supply range 3 to 32 V."]),
            _body(["Offset voltage 1 mV typical."]),
        ]
        toc = [
            [1, "1 Features", 1],
            [1, "2 Specifications", 3],
            [2, "2.1 Electrical Characteristics", 3],
        ]
        result = _build(tmp_path, "num.pdf", pages, toc)

        features = _section_md(result, "1-features")
        assert _pages(features) == "p.1-2"
        assert _paras(features) == [
            "Overload protection on the input and output.",
            "A continuation line with data 0.5 mV.",
        ]
        specs = _section_md(result, "2-specifications")
        assert _pages(specs) == "p.3-4"
        assert _paras(specs) == []  # both pages belong to the deeper 2.1
        ec = _section_md(result, "2-1-electrical-characteristics")
        assert _pages(ec) == "p.3-4"
        assert _paras(ec) == [
            "Supply range 3 to 32 V.", "Offset voltage 1 mV typical."]
        assert [s.number for s in result.manifest.sections] == ["1", "2", "2.1"]

    def test_child_paragraphs_never_duplicate_into_parent(self, tmp_path):
        pages = [
            _body(["1 Features", "Only features prose lives here."]),
            _body(["2 Specifications", "2.1 Electrical Characteristics",
                   "Supply range 3 to 32 V."]),
            _body(["Offset voltage 1 mV typical."]),
        ]
        toc = [
            [1, "1 Features", 1],
            [1, "2 Specifications", 2],
            [2, "2.1 Electrical Characteristics", 2],
        ]
        result = _build(tmp_path, "dedup.pdf", pages, toc)
        specs = _section_md(result, "2-specifications")
        ec = _section_md(result, "2-1-electrical-characteristics")
        assert "Supply range 3 to 32 V." in ec
        assert "Supply range 3 to 32 V." not in specs
        assert "Offset voltage 1 mV typical." not in specs

    def test_unnumbered_outline_stays_honest_slugged(self, tmp_path):
        pages = [
            _body(["Features", "Quad RF sampling at 12 GSPS."]),
            _body(["General Description", "The device integrates four DACs."]),
            _body(["Specifications", "Full-scale current 6.43 mA."]),
            _body(["More specs with trailing data."]),
        ]
        toc = [
            [1, "Features", 1],
            [1, "General Description", 2],
            [1, "Specifications", 3],
        ]
        result = _build(tmp_path, "unnum.pdf", pages, toc)

        features = _section_md(result, "features")
        assert _pages(features) == "p.1"
        assert _paras(features) == ["Quad RF sampling at 12 GSPS."]
        general = _section_md(result, "general-description")
        assert _pages(general) == "p.2"
        assert _paras(general) == ["The device integrates four DACs."]
        specs = _section_md(result, "specifications")
        assert _pages(specs) == "p.3-4"
        assert [s.number for s in result.manifest.sections] == ["", "", ""]
        index = (result.part_dir / "INDEX.md").read_text(encoding="utf-8")
        assert "general-description.md" in index

    def test_printed_toc_fallback_when_no_bookmarks(self, tmp_path):
        pages = [
            [(56, 90, "1 Features .......... 3"),
             (56, 106, "General Description .......... 3"),
             (56, 122, "2 Specifications .......... 4"),
             (80, 138, "2.1 Electrical Characteristics .......... 4")],
            _body(["unrelated front-matter line"]),
            _body(["Features", "General Description",
                   "Dual op amp with 1234 microvolt offset."]),
            _body(["2 Specifications", "2.1 Electrical Characteristics",
                   "Supply range 3 to 32 V at 25 C."]),
        ]
        result = _build(tmp_path, "printed.pdf", pages)

        features = _section_md(result, "1-features")
        assert _pages(features) == "p.3"
        general = _section_md(result, "general-description")
        assert _pages(general) == "p.3"
        assert _paras(general) == ["Dual op amp with 1234 microvolt offset."]
        specs = _section_md(result, "2-specifications")
        assert _pages(specs) == "p.4"
        ec = _section_md(result, "2-1-electrical-characteristics")
        assert _pages(ec) == "p.4"
        assert _paras(ec) == ["Supply range 3 to 32 V at 25 C."]
        assert [s.number for s in result.manifest.sections] == ["1", "", "2", "2.1"]

    def test_no_bookmarks_no_printed_toc_degrades_to_per_page(self, tmp_path):
        pages = [
            _body(["Solo page one content."]),
            _body(["Solo page two content."]),
        ]
        result = _build(tmp_path, "bare.pdf", pages)

        assert [s.number for s in result.manifest.sections] == ["1", "2"]
        p1 = _section_md(result, "1-page-1")
        p2 = _section_md(result, "2-page-2")
        assert _pages(p1) == "p.1" and _paras(p1) == ["Solo page one content."]
        assert _pages(p2) == "p.2" and _paras(p2) == ["Solo page two content."]


class TestFurniture:
    def _one_section_per_page(self, n_pages: int) -> list[list]:
        return [[1, f"{i + 1} Section {i + 1}", i + 1] for i in range(n_pages)]

    def test_adi_style_footers_and_header_stripped(self, tmp_path):
        n = 5
        pages = []
        for i in range(1, n + 1):
            pages.append(
                _top(["Data Sheet", "AD9081"])
                + _body([f"Unique body line of page {i}."])
                + _bottom([f"Rev. 0 | {i} of 5"])
            )
        result = _build(tmp_path, "adi.pdf", pages, self._one_section_per_page(n))
        for i in range(1, n + 1):
            paras = _paras(_section_md(result, f"{i}-section-{i}"))
            assert paras == [f"Unique body line of page {i}."]
            md = _section_md(result, f"{i}-section-{i}")
            for noise in ("Data Sheet", "Rev. 0", "of 5"):
                assert noise not in md, f"{noise!r} leaked into {i}-section-{i}"

    def test_qorvo_style_footer_and_header_stripped(self, tmp_path):
        n = 8
        pages = []
        for i in range(1, n + 1):
            pages.append(
                _top(["QPA1003P", "1 - 8 GHz 10 W GaN Power Amplifier"])
                + _body([f"Body content that only exists on page {i}."])
                + _bottom([f"- {i} of 8 -"])
            )
        result = _build(tmp_path, "qorvo.pdf", pages, self._one_section_per_page(n))
        for i in range(1, n + 1):
            paras = _paras(_section_md(result, f"{i}-section-{i}"))
            assert paras == [f"Body content that only exists on page {i}."]
            md = _section_md(result, f"{i}-section-{i}")
            for noise in ("QPA1003P", "Power Amplifier", "of 8"):
                assert noise not in md

    def test_old_ti_chrome_and_bare_page_numbers_stripped(self, tmp_path):
        n = 5
        pages = []
        for i in range(1, n + 1):
            pages.append(
                _top(["LM741 SNOSC25D -MAY 1998-REVISED OCTOBER 2015", "www.ti.com"])
                + _body([f"Page {i} has one unique line of specs."])
                + _bottom(["Submit Documentation Feedback",
                           "Copyright (c) 1998-2015, Texas Instruments Incorporated",
                           "Product Folder Links: LM741",
                           str(i)])
            )
        result = _build(tmp_path, "tiold.pdf", pages, self._one_section_per_page(n))
        for i in range(1, n + 1):
            paras = _paras(_section_md(result, f"{i}-section-{i}"))
            assert paras == [f"Page {i} has one unique line of specs."]
            md = _section_md(result, f"{i}-section-{i}")
            # SNOSC25D legitimately appears in the provenance comment (it is
            # the sniffed document revision); everything else is furniture.
            for noise in ("www.ti.com", "Submit Documentation Feedback",
                          "Copyright (c)", "Product Folder Links"):
                assert noise not in md, f"{noise!r} leaked into section {i}"

    def test_spec_section_heading_not_duplicated_in_paragraphs(self, tmp_path):
        pages = [
            _top(["TEST9000", "SBAS001A"])
            + _body(["1 Features", "Overload protection on the input and output."]),
            _body(["2 Specifications", "VDD 1.2 V to 1.4 V."]),
        ]
        toc = [[1, "1 Features", 1], [1, "2 Specifications", 2]]
        result = _build(tmp_path, "head.pdf", pages, toc)
        assert _paras(_section_md(result, "2-specifications")) == ["VDD 1.2 V to 1.4 V."]

    def test_furniture_free_pdf_keeps_every_line(self, tmp_path):
        pages = [
            _body(["First line with 1500 in the middle.",
                   "Second line is a lone number 42.",
                   "Rev. 0 pattern shaped prose to be preserved."]),
            _body(["Only content on page two.",
                   "Another 42 style number line."]),
        ]
        result = _build(tmp_path, "clean.pdf", pages)
        p1 = _paras(_section_md(result, "1-page-1"))
        assert p1 == ["First line with 1500 in the middle.",
                      "Second line is a lone number 42.",
                      "Rev. 0 pattern shaped prose to be preserved."]
        assert _paras(_section_md(result, "2-page-2")) == [
            "Only content on page two.", "Another 42 style number line."]

    def test_pattern_shaped_body_line_survives(self, tmp_path):
        pages = [
            _top(["DATA SHEET"])
            + [(56.0, 300.0, "Pre Rev. 0 | 1 of 45 | Page 2 in prose form.")]
            + _bottom(["Rev. A | 1 of 3"]),
            _top(["DATA SHEET"]) + _body(["Worth of a second page alone."])
            + _bottom(["Rev. A | 2 of 3"]),
            _top(["DATA SHEET"]) + _body(["A third page for the staircase."])
            + _bottom(["Rev. A | 3 of 3"]),
        ]
        toc = [[1, "1 A", 1], [1, "2 B", 2], [1, "3 C", 3]]
        result = _build(tmp_path, "prose.pdf", pages, toc)
        paras = _paras(_section_md(result, "1-a"))
        assert "Pre Rev. 0 | 1 of 45 | Page 2 in prose form." in paras
        assert not any("Rev. A |" in p for p in paras)
        assert not any("DATA SHEET" in p for p in paras)


class TestMechanics:
    def test_rebuild_uses_pdf_layout_extraction_cache(self, tmp_path):
        pages = [
            _top(["DATA SHEET"]) + _body([f"Body of page {i}."])
            + _bottom([f"Rev. 0 | {i} of 4"]) for i in range(1, 5)
        ]
        toc = [[1, f"{i} S{i}", i] for i in range(1, 5)]
        pdf = Path(tmp_path) / "cache.pdf"
        first = _build(tmp_path, "cache.pdf", pages, toc)
        assert not first.cached_extraction
        settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
        second = build_part(pdf, part_number="P1", settings=settings,
                            vendor="unknown", use_llm=False)
        assert second.cached_extraction

    def test_manifest_records_pdf_layout_backend_and_pinned_vendor(self, tmp_path):
        pages = [_body(["One solitary content line."]),
                 _body(["Another page of content."])]
        result = _build(tmp_path, "mech.pdf", pages)

        doc = result.manifest.documents[0]
        stats = result.manifest.extraction_stats[doc.content_hash]
        assert stats.backend == "pdf_layout"
        assert result.manifest.pipeline_version == "0.3.0"
        assert result.manifest.vendor == "unknown"
        sources = json.loads((result.part_dir / "sources.json").read_text(encoding="utf-8"))
        assert sources[0]["vendor"] == "unknown"
        assert sources[0]["vendor_evidence"] == "cli-override: --vendor unknown"
