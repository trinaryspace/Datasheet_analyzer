"""pdf_layout figures — "Figure N." captions cataloged + clip-rendered.

Ticket 05, through the spec's single seam (`build_part` with temp-dir
settings, assertions on the published corpus): synthetic fitz PDFs with
vector drawings (all gate PDFs are pure-vector — zero embedded images) and
figure captions modeled on the measured real geometry (AD9081 p27 has six
plots to a page under their own captions; HMC520A p13 pairs two captions on
one baseline; lm741 pages carry prose references like "the waveforms in
Figure 2 show ..." that must never be figures).

Coverage:
- a vector region renders as a PNG under its Figure caption: file > 1 KB,
  plots.json lists it with a file path, `find_plots` + `format_plot_answer`
  resolve it, and the pixel content actually contains the drawn shape;
- two figures on one page each get their own clip — the second region starts
  below the first caption and never bleeds the first shape into its PNG;
- a figure caption ends a table region (its labels never become grid rows)
  while the table itself still builds;
- prose references ("Figure 2 shows ...") stay paragraphs and never become
  figure records;
- same-baseline caption pairs (HMC520A p13 style) share the band clip.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from datasheet_analyzer.config import Settings
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.query import find_plots, format_plot_answer

PAGE_W, PAGE_H = 612.0, 792.0

DPIS = 150


def _make_pdf(path: Path, pages, toc: list[list] | None = None
              ) -> None:
    """pages: list of pages; each page = list of (x, y, text) lines plus
    optional drawing rects ((x0, y0, x1, y1, fill) entries)."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for item in lines:
            if len(item) == 5:
                x0, y0, x1, y1, fill = item
                page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=None, fill=fill)
            else:
                x, y, text = item
                page.insert_text((x, y), text)
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()


def _build(tmp_path, name: str, pages, toc=None) -> object:
    pdf = Path(tmp_path) / name
    _make_pdf(pdf, pages, toc)
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    return build_part(pdf, part_number="P1", settings=settings,
                      vendor="unknown", use_llm=False)


def _doc_dir(result) -> Path:
    return result.part_dir / "docs" / f"datasheet-{result.manifest.documents[0].content_hash[:8]}"


def _section_md(result, stem: str) -> str:
    path = _doc_dir(result) / "sections" / f"{stem}.md"
    assert path.exists(), f"missing section file {path.name}"
    return path.read_text(encoding="utf-8")


def _plot_files(result) -> list[Path]:
    return list(_doc_dir(result).rglob("figures/*/*.png"))


def _pixel_darkness(img_path: Path, x_frac: float, y_frac: float) -> int:
    """Sum of RGB at a relative position (0..1 of width/height) of a
    rendered clip PNG — resolution-independent."""
    with fitz.open(str(img_path)) as img:
        pix = img[0].get_pixmap()
    x = min(pix.width - 1, int(x_frac * pix.width))
    y = min(pix.height - 1, int(y_frac * pix.height))
    r, g, b = pix.pixel(x, y)[:3]
    return r + g + b


def _figure_page() -> list:
    return [
        (56.0, 96.0, "Absolute Output Power vs. Frequency"),
        (100.0, 110.0, 400.0, 210.0, (0.0, 0.0, 0.0)),  # the vector drawing
        (56.0, 250.0, "Figure 1. Absolute Output Power"),
    ]


class TestFigureRendering:
    def test_vector_region_renders_png_under_caption(self, tmp_path):
        result = _build(tmp_path, "fig1.pdf", [_figure_page()],
                        toc=[[1, "1 Typical Performance", 1]])
        md = _section_md(result, "1-typical-performance")
        # the caption is cataloged under ## Figures, never duplicated as prose
        assert "## Figures" in md
        assert "- **Figure 1. Absolute Output Power** (p.1)" in md
        assert md.count("Figure 1. Absolute Output Power") == 1

        plots = json.loads((_doc_dir(result) / "plots.json").read_text(
            encoding="utf-8"))["plots"]
        assert len(plots) == 1
        rec = plots[0]
        assert rec["caption"] == "Figure 1. Absolute Output Power"
        assert rec["figure_number"] == "1"
        assert rec["page_start"] == 1
        assert rec["file"], "plot must have a rendered image file"

        files = _plot_files(result)
        assert len(files) == 1
        fle = files[0]
        assert fle.stat().st_size > 1024
        # the PNG contains the drawn shape at its mid-band ...
        assert _pixel_darkness(fle, 0.45, 0.6) < 300
        assert _pixel_darkness(fle, 0.45, 0.1) > 700
        # ... and the clip ends above the caption line (the region only)
        assert _pixel_darkness(fle, 0.45, 0.98) > 700

        # the query surface resolves the plot end-to-end
        found = find_plots(result.part_dir, q="Absolute Output Power")
        assert len(found) == 1
        answer = format_plot_answer(found)
        assert "Figure 1. Absolute Output Power" in answer
        assert "file:" in answer

    def test_two_figures_on_one_page_each_own_clip(self, tmp_path):
        # AD9081 p27 shape: two stacked vector plots, one caption each; the
        # shapes sit at different x so each clip can be told apart by pixel
        page = [
            (100.0, 120.0, 200.0, 220.0, (0.0, 0.0, 0.0)),      # figure 6 art
            (56.0, 260.0, "Figure 6. HD2 vs. fOUT over Digital Scale, 6 GSPS"),
            (300.0, 330.0, 400.0, 430.0, (0.0, 0.0, 0.0)),      # figure 7 art
            (56.0, 470.0, "Figure 7. HD2 vs. fOUT over Digital Scale, 12 GSPS"),
        ]
        result = _build(tmp_path, "fig2.pdf", [page])
        plots = json.loads((_doc_dir(result) / "plots.json").read_text(
            encoding="utf-8"))["plots"]
        assert [p["figure_number"] for p in plots] == ["6", "7"]

        f1, f2 = sorted(_plot_files(result))
        # figure 6's clip ends at caption 6: figure 6's shape (x 100..200) is
        # in it, and figure 7's shape (x 300..400, below caption 6) is not
        assert _pixel_darkness(f1, 0.25, 0.65) < 300
        assert _pixel_darkness(f1, 0.55, 0.65) > 700
        # figure 7's clip starts below caption 6: only its own shape appears
        assert _pixel_darkness(f2, 0.25, 0.55) > 700
        assert _pixel_darkness(f2, 0.55, 0.55) < 300

    def test_same_baseline_caption_pair_shares_band_clip(self, tmp_path):
        # AD9081/HMC520A shape: two captions on one baseline within ~1pt of
        # each other (measured 0.7-1.4pt offsets) share the band clip
        page = [
            (80.0, 120.0, 300.0, 220.0, (0.0, 0.0, 0.0)),
            (74.2, 251.5, "Figure 42. Noise Figure vs. RF Frequency at Various LO Powers,"),
            (351.0, 252.2, "Figure 43. Input P1dB vs. RF Frequency at Various Temperatures"),
        ]
        result = _build(tmp_path, "fig3.pdf", [page])
        plots = json.loads((_doc_dir(result) / "plots.json").read_text(
            encoding="utf-8"))["plots"]
        assert len(plots) == 2
        files = sorted(_plot_files(result))
        assert len(files) == 2
        # both never render a zero-height clip and both contain the shape band
        for fle in files:
            assert fle.stat().st_size > 0
            assert _pixel_darkness(fle, 0.3, 0.6) < 300


class TestTitleAnchoredFigures:
    """Ticket 09: captionless-era figures anchor by their printed title
    band — QPA1003P's 'Functional Block Diagram' shape (14 pt title inside
    a drawn emphasis band with a large vector rect directly below, prose
    headings never fire). Through the build_part seam."""

    @staticmethod
    def _make_title_pdf(path: Path, title: str, body_first_x: float,
                        big_rect: bool, body_words: int) -> None:
        """A 14 pt title inside an 18 pt emphasis band, a big drawn rect
        below (optional), and a body-prose line either in the title's own
        column (x=36) or the neighboring one (x=316)."""
        doc = fitz.open()
        page = doc.new_page(width=612.0, height=792.0)
        font = fitz.Font("helv")
        page.draw_rect(fitz.Rect(36.0, 92.0, 295.0, 110.0),
                       color=(0, 0, 0), width=1.0, fill=(0.85, 0.85, 0.85))
        if big_rect:
            page.draw_rect(fitz.Rect(36.0, 120.0, 295.0, 300.0),
                           color=(0, 0, 0), fill=(0.2, 0.2, 0.2))
        tw = fitz.TextWriter(page.rect)
        tw.append((36.0, 107.0), title, font=font, fontsize=14.04)
        tw.write_text(page)
        phrase = " ".join(["payload"] * body_words)
        page.insert_text((body_first_x, 320.0), phrase, fontsize=9.96)
        page.insert_text((36.0, 360.0), "1  Note line for the figure block.", fontsize=8.0)
        doc.set_toc([[1, "1 Page One", 1]])
        doc.save(str(path))
        doc.close()

    def _build(self, tmp_path, name: str, title, body_first_x, big_rect,
               body_words, body_size=9.96) -> object:
        pdf = Path(tmp_path) / name
        self._make_title_pdf(pdf, title, body_first_x, big_rect, body_words)
        settings = Settings(parts_dir=tmp_path / "parts",
                            cache_dir=tmp_path / ".cache").resolve()
        res = build_part(pdf, part_number="P1", settings=settings,
                         vendor="unknown", use_llm=False)
        return res

    def test_title_band_with_rect_below_yields_figure(self, tmp_path):
        # neighbor-column prose (the 'Applications' bullets at x=316) must
        # not block the title's claim
        result = self._build(tmp_path, "bd.pdf", "Functional Block Diagram",
                             body_first_x=316.0, big_rect=True, body_words=7)
        plots = json.loads((_doc_dir(result) / "plots.json").read_text(
            encoding="utf-8"))["plots"]
        assert len(plots) == 1
        rec = plots[0]
        assert rec["caption"] == "Functional Block Diagram"
        assert rec["page_start"] == 1
        assert rec["file"], "title-anchored figure must render"
        fle = result.part_dir / rec["file"]
        assert fle.stat().st_size > 1024
        # the clip contains the drawn rect (dark) not the caption area
        assert _pixel_darkness(fle, 0.45, 0.55) < 300
        found = find_plots(result.part_dir, caption="Functional Block Diagram")
        assert found and found[0].file
        md = _section_md(result, "1-page-one")
        assert "Functional Block Diagram" in md

    def test_same_column_prose_below_band_blocks_figure(self, tmp_path):
        # body prose directly under the title band in its own x-column is a
        # heading with a paragraph below, not a figure — even with a rect
        result = self._build(tmp_path, "bd2.pdf", "General Description Text",
                             body_first_x=36.0, big_rect=True, body_words=9)
        assert json.loads((_doc_dir(result) / "plots.json").read_text(
            encoding="utf-8"))["plots"] == []
        md = _section_md(result, "1-page-one")
        assert "payload payload payload payload payload payload payload payload payload" in md

    def test_note_line_under_drawing_stays_honest(self, tmp_path):
        # a short footnote-styled line below a title band is not prose and
        # never becomes a figure (p15 'Power Dissipation...' shape keeps
        # only the title)
        result = self._build(tmp_path, "bd3.pdf", "Power Dissipation and Maximum Gate Current",
                             body_first_x=316.0, big_rect=True, body_words=3)
        plots = json.loads((_doc_dir(result) / "plots.json").read_text(
            encoding="utf-8"))["plots"]
        assert len(plots) == 1
        assert plots[0]["caption"] == "Power Dissipation and Maximum Gate Current"


class TestFigureBoundaries:
    def test_caption_ends_table_region_and_labels_stay_out(self, tmp_path):
        page = [
            (56.0, 96.0, "Table 3. DAC DC Specifications"),
            (56.0, 116.0, "Parameter"),
            (435.0, 116.0, "Min"),
            (460.0, 116.0, "Typ"),
            (515.0, 116.0, "Max"),
            (548.0, 116.0, "Unit"),
            (56.0, 132.0, "DAC RESOLUTION"),
            (435.0, 132.0, "16"),
            (548.0, 132.0, "Bit"),
            (62.4, 148.0, "Gain Error"),
            (460.0, 148.0, "1.5"),
            (548.0, 148.0, "% FSR"),
            (100.0, 200.0, 400.0, 280.0, (0.15, 0.15, 0.15)),  # timing art
            (56.0, 300.0, "Figure 5. Timing Diagram for 3-Wire Write Operation"),
            (120.0, 340.0, "CLK"),  # figure-internal label
        ]
        result = _build(tmp_path, "fig4.pdf", [page])
        assert result.manifest.stats.n_tables == 1
        md = _section_md(result, "1-page-1")
        # the timing labels and caption never joined the spec table's grid
        table_rows = md.split("## Table 3.")[1].split("## Figures")[0]
        assert "| CLK |" not in table_rows
        assert "| 16 |" in table_rows
        # the figure is cataloged with its own page citation
        assert "Figure 5. Timing Diagram for 3-Wire Write Operation" in md
        # the region above the caption is the figure's: caption consumed
        assert md.count("Figure 5. Timing Diagram") == 1

    def test_unnumbered_sections_never_collide_plot_ids(self, tmp_path):
        # AD9081 shape: two unnumbered figure sections in one part — plot
        # ids and image files must be distinct (a shared "-f001" id would
        # overwrite one section's image with the other's)
        page1 = [
            (100.0, 120.0, 200.0, 220.0, (0.0, 0.0, 0.0)),
            (56.0, 260.0, "Figure 6. HD2 vs. fOUT over Digital Scale, 6 GSPS"),
        ]
        page2 = [
            (300.0, 120.0, 400.0, 220.0, (0.0, 0.0, 0.0)),
            (56.0, 260.0, "Figure 36. Single-Tone SFDR and SNR vs. AIN at 450 MHz"),
        ]
        toc = [[1, "DAC", 1], [1, "ADC: 4 GSPS", 2]]
        result = _build(tmp_path, "fig7.pdf", [page1, page2], toc=toc)
        plots = json.loads((_doc_dir(result) / "plots.json").read_text(
            encoding="utf-8"))["plots"]
        assert len(plots) == 2
        ids = [p["id"] for p in plots]
        assert len(set(ids)) == 2, ids
        assert ids[0] == "dac-f001" and ids[1] == "adc-4-gsps-f001"
        files = _plot_files(result)
        assert len({f.name for f in files}) == 2
        # each image shows its own section's shape
        f_dac = next(f for f in files if "dac" in f.name)
        f_adc = next(f for f in files if "adc" in f.name)
        assert _pixel_darkness(f_dac, 0.25, 0.6) < 300
        assert _pixel_darkness(f_adc, 0.55, 0.6) < 300

    def test_prose_figure_reference_stays_paragraph(self, tmp_path):
        # lm741 p10 shape: "the waveforms in Figure 2 show the input ..."
        # is prose — never a figure record, never consumed
        page = [
            (56.0, 96.0,
             "The waveforms in Figure 2 show the input and output signals of the amplifier."),
        ]
        result = _build(tmp_path, "fig5.pdf", [page])
        plots = json.loads((_doc_dir(result) / "plots.json").read_text(
            encoding="utf-8"))["plots"]
        assert plots == []
        assert not _plot_files(result)
        md = _section_md(result, "1-page-1")
        assert "The waveforms in Figure 2 show the input and output signals" in md

    def test_captionless_vector_region_stays_honest(self, tmp_path):
        # a drawing with no caption: no figure record, text untouched
        page = [
            (100.0, 120.0, 400.0, 200.0, (0.0, 0.0, 0.0)),
            (56.0, 260.0, "Block Diagram"),
        ]
        result = _build(tmp_path, "fig6.pdf", [page])
        assert json.loads((_doc_dir(result) / "plots.json").read_text(
            encoding="utf-8"))["plots"] == []
        md = _section_md(result, "1-page-1")
        assert "Block Diagram" in md
