"""`dsa status` must surface per-document extraction stats: the layout
engine's detected/accepted/rejected table counts with rejection reasons
for pdf_layout parts, and honest zero counts for every other backend
(ti_html / pdf_text) — the additive stats contract at the CLI seam."""

from __future__ import annotations

import fitz

from datasheet_analyzer import cli
from datasheet_analyzer.acquire import append_to_inventory, register_source
from datasheet_analyzer.config import Settings
from datasheet_analyzer.pipeline import build_part

PAGE_W, PAGE_H = 612.0, 792.0


def _make_pdf(path, pages, toc=None) -> None:
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text in lines:
            page.insert_text((x, y), text)
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()


def _ok_table_page() -> list[tuple[float, float, str]]:
    return [
        (56.0, 140.0, "Table 3. DAC DC Specifications"),
        (56.0, 153.0, "Parameter"),
        (222.0, 153.0, "Test Conditions/Comments"),
        (435.0, 153.0, "Min"),
        (460.0, 153.0, "Typ"),
        (515.0, 153.0, "Max"),
        (548.0, 153.0, "Unit"),
        (56.0, 166.0, "DAC RESOLUTION"),
        (435.0, 166.0, "16"),
        (548.0, 166.0, "Bit"),
        (62.4, 179.0, "Gain Error"),
        (460.0, 179.0, "1.5"),
        (548.0, 179.0, "% FSR"),
    ]


def _bad_table_page() -> list[tuple[float, float, str]]:
    # scattered word tracks: every split yields an unstable grid -> the
    # ladder rejects and records the reason
    return [
        (56.0, 96.0, "Table 7. Noise"),
        (56.0, 120.0, "Alpha Beta"),
        (306.0, 120.0, "Gamma"),
        (100.0, 134.0, "Delta Epsilon"),
        (410.0, 134.0, "Zeta"),
        (175.0, 148.0, "Eta"),
        (465.0, 148.0, "Theta"),
        (240.0, 162.0, "Iota Kappa"),
        (520.0, 162.0, "Lambda"),
    ]


def _prose_companion_pdf(tmp_path) -> object:
    """An errata companion: prose, so it still routes to `pdf_text`.

    It was a register map until phase 6 ticket 05 re-routed those to
    `pdf_layout`. The contract under test here is the *stats* one — a
    non-layout document reports honest zeros rather than absent fields — so
    the fixture moved to a companion type that is still read as paragraphs.
    """
    path = tmp_path / "errata.pdf"
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((72.0, 72.0), "Overview content on page one.")
    page.insert_text((300.0, 750.0), "1")
    doc.set_toc([[1, "1 Overview", 1]])
    doc.save(str(path))
    doc.close()
    return path


def _build_status_part(tmp_path, datasheet_pdf, settings, with_map=False) -> object:
    ds = register_source(datasheet_pdf, part_number="P1", doc_type="datasheet")
    sources = [ds]
    if with_map:
        sources.append(register_source(_prose_companion_pdf(tmp_path),
                                       part_number="P1",
                                       doc_type="errata"))
    append_to_inventory(sources, settings.parts_dir / "P1")
    return build_part(datasheet_pdf, part_number="P1", settings=settings,
                      vendor="unknown", use_llm=False)


def test_status_shows_per_doc_counts_and_reasons(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "stats.pdf"
    _make_pdf(pdf, [_ok_table_page(), _bad_table_page()],
              toc=[[1, "1 Spec", 1]])
    settings = Settings(parts_dir=tmp_path / "parts",
                        cache_dir=tmp_path / ".cache").resolve()
    result = _build_status_part(tmp_path, pdf, settings)
    doc = result.manifest.documents[0]

    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    exit_code = cli.main(["status"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "part: P1 [built]" in out
    assert "vendor: unknown" in out
    assert "extraction: pdf_layout" in out
    # per-document line with detected/accepted/rejected + the reason
    assert f"datasheet-{doc.content_hash[:8]}" in out
    assert "tables: 2 detected / 1 accepted / 1 rejected" in out
    assert "rejection reasons: columns not stable across rows" in out
    assert "fidelity" in out


def test_status_zeros_are_honest_for_non_layout_docs(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "multi.pdf"
    _make_pdf(pdf, [_ok_table_page()], toc=[[1, "1 Spec", 1]])
    settings = Settings(parts_dir=tmp_path / "parts",
                        cache_dir=tmp_path / ".cache").resolve()
    result = _build_status_part(tmp_path, pdf, settings, with_map=True)
    assert result.manifest.stats.n_documents == 2
    map_doc = next(d for d in result.manifest.documents if d.doc_type.value == "errata")

    # the additive stats contract: pdf_text carries zero table stats
    mstats = result.manifest.extraction_stats[map_doc.content_hash]
    assert mstats.backend == "pdf_text"
    assert (mstats.tables_detected, mstats.tables_accepted, mstats.tables_rejected) == (0, 0, 0)

    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    cli.main(["status"])
    out = capsys.readouterr().out
    assert f"errata-{map_doc.content_hash[:8]}" in out
    assert "backend pdf_text" in out
    assert "tables: 0 detected / 0 accepted / 0 rejected" in out
    assert "rejection reasons" not in out
