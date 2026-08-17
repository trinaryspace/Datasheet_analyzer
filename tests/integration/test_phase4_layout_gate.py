"""Phase 4 gate: four really different PDFs build fully offline via pdf_layout.

Layout families: ADI new (AD9081, outline, unnumbered), old TI (lm741,
numbered outline), Qorvo (QPA1003P, no outline at all -> per-page), and
Hittite-era ADI (HMC520A, unnumbered outline). The seam is exactly what
users run — `build_part` with temp-dir settings — with one documented
override: lm741's page 1 carries no brand mark, so detection cannot pin a
pdf_layout-routable profile; the spec's `--vendor` escape hatch is used
there and recorded honestly as cli-override evidence.

Assertions are corpus products only: section files with page citations,
furniture golden strings absent from paragraphs, content preserved,
inventory vendor evidence, pdf_layout backend in the manifest, honest
numbered vs unnumbered section identity, and (ticket 03) caption-anchored
tables: AD9081's partial-ruling spec tables land as atomic grids with ADI
"Test Conditions/Comments" columns, specs.json records resolve through the
user-facing SpecQuery, ohm glyphs canonicalize, and table pages are pinned
so that cell values verify against the PDF's own page text. lm741/QPA1003P
(section-headed, captionless tables) stay honestly paragraph-only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import ClassVar

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.pipeline import build_part


def _squash_text(text: str) -> str:
    """Aggressive normalizer: lowercase alnum only, space-immune."""
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"\s+", " ", text).lower())


REPO = Path(__file__).parent.parent.parent
FIXTURES = Path(__file__).parent.parent / "fixtures"
GATE_PDFS = FIXTURES / "pdf"

# Ungated fixtures (SPEC "Testing Decisions"): the four PDFs are committed
# under tests/fixtures/pdf/ — a missing fixture is a hard failure, never a
# skip. Ticket 07 kickoff decision: root copies (AGENTS.md build examples)
# stay as the documented working location; git stores the identical blobs
# once.
GATE: dict[str, dict] = {
    "AD9081": {
        "pdf": GATE_PDFS / "ad9081.pdf", "part": "AD9081", "override": "", "vendor": "adi",
        "golden": FIXTURES / "golden_qa_AD9081.yaml",
        "noise": ["of 45", "analog.com", "Rev. 0 |", "Data Sheet"],
        "content": ["12 GSPS", "Full-scale output current range",
                    "Test Conditions/Comments"],
    },
    "LM741": {
        "pdf": GATE_PDFS / "lm741.pdf", "part": "LM741", "override": "unknown",
        "vendor": "unknown",
        "golden": FIXTURES / "golden_qa_LM741.yaml",
        "noise": ["www.ti.com", "Submit Documentation Feedback", "Copyright (c)",
                  "Product Folder Links"],
        "content": ["overload protection", "Absolute Maximum Ratings"],
    },
    "QPA1003P": {
        "pdf": GATE_PDFS / "QPA1003P.pdf", "part": "QPA1003P", "override": "", "vendor": "qorvo",
        # ticket 09 superseded the honest zeros: the golden mixes text +
        # spec_query + plot_query questions (5 tables / 41 specs / 4
        # title-anchored figures measured), asserted by the corpus tests
        "golden": FIXTURES / "golden_qa_QPA1003P.yaml",
        # the sniffed revision lands in provenance comments ("<!-- source:
        # Rev. I p.1 -->", lm741's SNOSC25D precedent) so only the full
        # furniture line is checked, never the bare "Rev. I" token
        "noise": ["of 20", "Data Sheet Rev. I, January 2026"],
        "content": ["wideband high power MMIC", "matched to 50"],
    },
    "HMC520A": {
        "pdf": GATE_PDFS / "hmc520a.pdf", "part": "HMC520A", "override": "", "vendor": "adi",
        "golden": FIXTURES / "golden_qa_HMC520A.yaml",
        "noise": ["of 32", "Rev. A | Page", "| Page"],
        "content": ["Rev. 0 to Rev. A", "Conversion loss"],
    },
}


@pytest.fixture(scope="module")
def gate(tmp_path_factory):
    """One offline corpus per gate part. Ungated: fixtures are committed."""
    results: dict[str, object] = {}
    for name, spec in GATE.items():
        assert spec["pdf"].exists(), f"gate fixture missing: {spec['pdf']}"
        tmp = tmp_path_factory.mktemp(f"gate-{name}")
        settings = Settings(parts_dir=tmp / "parts", cache_dir=tmp / ".cache").resolve()
        results[name] = build_part(
            spec["pdf"], part_number=spec["part"], settings=settings,
            vendor=spec["override"], use_llm=False,
        )
    return results


def _blob(result) -> str:
    return "\n".join(
        (result.part_dir / sec.file).read_text(encoding="utf-8")
        for sec in result.manifest.sections
    )


class TestGateCorpora:
    def test_every_part_builds_with_evidence_and_no_furniture(self, gate):
        for name, spec in GATE.items():
            result = gate[name]
            assert result.manifest.vendor == spec["vendor"], name
            assert len(result.manifest.sections) >= 20, name
            for sec in result.manifest.sections:
                assert sec.page_start is not None, f"{name}: {sec.title} lacks pages"
                assert (result.part_dir / sec.file).exists(), f"{name}: {sec.file}"
            assert (result.part_dir / "INDEX.md").exists(), name

            doc = result.manifest.documents[0]
            assert result.manifest.extraction_stats[doc.content_hash].backend == "pdf_layout"
            sources = json.loads((result.part_dir / "sources.json").read_text(encoding="utf-8"))
            assert sources[0]["vendor"] == spec["vendor"], name
            assert sources[0]["vendor_evidence"], f"{name}: no vendor evidence"

            blob = _blob(result)
            for golden in spec["noise"]:
                assert golden not in blob, f"{name}: furniture {golden!r} leaked"
            for needle in spec["content"]:
                assert needle in blob, f"{name}: content {needle!r} missing"

    def test_lm741_numbered_outline_keeps_printed_numbers(self, gate):
        """Old-TI outline titles carry numbers; sections and files keep them."""
        result = gate["LM741"]
        nums = [s.number for s in result.manifest.sections]
        assert nums[:3] == ["1", "2", "3"]
        assert "12" in nums
        assert list((result.part_dir / "docs").glob("**/1-features.md")), "1-features.md missing"

    def test_ad9081_unnumbered_sections_stay_honest_and_slugged(self, gate):
        result = gate["AD9081"]
        assert all(s.number == "" for s in result.manifest.sections)
        files = {p.name for p in (result.part_dir / "docs").glob("**/sections/*.md")}
        assert "features.md" in files
        assert "general-description.md" in files
        index = (result.part_dir / "INDEX.md").read_text(encoding="utf-8")
        # "General Description" brief now feeds the INDEX (ADI parts)
        assert "MxFE Quad" in index

    def test_qpa1003p_no_outline_no_printed_toc_degrades_per_page(self, gate):
        result = gate["QPA1003P"]
        assert len(result.manifest.sections) == 20
        assert [s.title for s in result.manifest.sections[:2]] == ["Page 1", "Page 2"]
        assert list((result.part_dir / "docs").glob("**/1-page-1.md"))

    def test_hmc520a_unnumbered_outline_slugged(self, gate):
        result = gate["HMC520A"]
        assert all(s.number == "" for s in result.manifest.sections)
        files = {p.name for p in (result.part_dir / "docs").glob("**/sections/*.md")}
        assert "features.md" in files
        assert "revision-history.md" in files

    def test_gate_revisions_sniffed_from_the_shared_lexicon(self, gate):
        # SPEC story 23: "Rev. A"-style tokens for ADI/Qorvo-era parts and
        # TI document ids for TI parts, out of one lexicon — no per-vendor
        # branches. Measured on the real PDFs: AD9081 "Rev. 0" title line,
        # HMC520A "Rev. A | Page 2 of 32" footer, QPA1003P "Data Sheet
        # Rev. I, January 2026", lm741 keeps its document id "SNOSC25D".
        expected = {"AD9081": "Rev. 0", "HMC520A": "Rev. A",
                    "QPA1003P": "Rev. I", "LM741": "SNOSC25D"}
        for name, rev in expected.items():
            result = gate[name]
            sources = json.loads(
                (result.part_dir / "sources.json").read_text(encoding="utf-8"))
            assert sources[0]["revision"] == rev, name


class TestGateTables:
    """Ticket 03: caption-anchored tables + specs for non-TI parts."""

    def test_ad9081_spec_tables_build_with_stats(self, gate):
        result = gate["AD9081"]
        doc = result.manifest.documents[0]
        stats = result.manifest.extraction_stats[doc.content_hash]
        assert stats.tables_detected >= 25
        assert stats.tables_accepted >= 25
        assert stats.tables_rejected <= 2
        # ticket 09: trailing note lines attach as footnotes instead of
        # grid rows, so the mean reconstruction (measured 0.881) honestly
        # sits below the pre-09 0.902
        assert stats.mean_fidelity >= 0.85
        assert result.manifest.stats.n_tables >= 20
        assert result.manifest.stats.n_specs >= 300
        # atomic tables render in section files with a markdown grid
        blob = _blob(result)
        assert "| Parameter | Test Conditions/Comments | Min | Typ | Max | Unit |" in blob
        assert "Table 3. DAC DC Specifications" in blob
        csvs = list((result.part_dir / "docs").glob("**/tables/*.csv"))
        assert len(csvs) >= 15, "CSV twins missing"

    def test_ad9081_spec_records_resolve_via_query(self, gate):
        from datasheet_analyzer.query import SpecQuery

        result = gate["AD9081"]
        q = SpecQuery(result.part_dir)
        fsocr = q.find(symbol="Full-Scale Output Current Range")
        # ticket 09 materialization: the spanning parent replicates into
        # its child rows, so the parent + three value-carrying children
        # resolve (the parent row itself honestly keeps empty values)
        assert len(fsocr) == 4
        parent = next(r for r in fsocr if "DC Coupling" not in r.symbol)
        assert "AC coupling" in parent.conditions  # ADI conditions column mapped
        assert parent.page == 5
        assert parent.section == ""  # AD9081 outline is honestly unnumbered
        assert parent.min == "" and parent.typ == "" and parent.max == ""
        children = [r for r in fsocr if r.min or r.typ]
        assert len(children) == 3
        ac = next(r for r in children if "AC Coupling" in r.symbol)
        # the printed '6.43' and '26.5' share one unheaded mini-column, so
        # the materialized child's min cell honestly carries both values
        assert ac.min == "6.43 26.5" and ac.typ == "37.75"
        assert ac.unit.canonical == "mA"
        ac = q.find(symbol="Gain Matching")
        assert ac and ac[0].typ == "0.7" and ac[0].unit.canonical == "% FSR"
        # both ohm glyphs canonicalize (SPEC probe fact: AD9081 has both)
        v = q.find(symbol="Differential Resistance")
        assert v and v[0].unit.canonical == "ohm"

    def test_ad9081_table_pages_pinned_and_verified_against_pdf_text(self, gate):
        import json

        import fitz

        result = gate["AD9081"]
        pdf = GATE["AD9081"]["pdf"]
        page_texts = {
            p.number + 1: _squash_text(p.get_text())
            for p in fitz.open(str(pdf))
        }
        specs = json.loads(
            next((result.part_dir / "docs").glob("*/specs.json")).read_text(
                encoding="utf-8"))
        checked = verified = 0
        misses = []
        for rec in specs["records"]:
            if rec["page"] is None or not (rec["typ"] or rec["min"] or rec["max"]):
                continue
            needle = rec["row_verbatim"][0] if rec["row_verbatim"] else ""
            squashed = _squash_text(needle)
            if len(squashed) < 4:
                continue
            checked += 1
            if squashed in page_texts.get(rec["page"], ""):
                verified += 1
            else:
                misses.append((rec["page"], needle[:30]))
        assert checked >= 100
        # Ticket 09 re-measured band: 172/212 = 81.1% verified on the
        # exact cited PDF page (stricter than the ticket-08 168/189 =
        # 88.9% under looser first-page citation). The 40 residuals are
        # three honest classes, never wrong citations:
        #   1. continuation rows whose materialized symbol prints on the
        #      block's earlier page (20 p13 singles-tone fOUT rows of the
        #      p12-p16 block — the row's own page carries its values);
        #   2. materialized children whose composite symbol prints as
        #      separate lines (Table 3/4 span children, VCO divide rows,
        #      SCLK clock rows);
        #   3. the known 'Maximum Aperture Jitter2' text-rendering blind
        #      spot (1 row).
        # Never 100%: the composite symbols are the printer's own split
        # layout, and the check verifies the cited page's text verbatim.
        assert verified / checked >= 0.78, f"pin misses: {misses[:5]}"

    def test_hmc520a_captioned_tables_build(self, gate):
        result = gate["HMC520A"]
        stats = result.manifest.extraction_stats[
            result.manifest.documents[0].content_hash]
        assert stats.tables_accepted == 6
        assert result.manifest.stats.n_specs >= 20
        assert "Table 1." in _blob(result) or "Table 1" in _blob(result)

    def test_captionless_vendors_land_heading_anchored_tables(self, gate):
        # ticket 09: lm741 (old TI, section-headed tables) and QPA1003P
        # (Qorvo, no outline) get their heading-anchored tables — but the
        # captionless era never fabricates a number: the tables render as
        # "## Unnumbered table", every line still lands in the corpus, and
        # specs.json flows from the grids (the ticket-07 honest zeros are
        # superseded; recorded in the ledger + issue 09)
        for name in ("LM741", "QPA1003P"):
            result = gate[name]
            stats = result.manifest.extraction_stats[
                result.manifest.documents[0].content_hash]
            assert stats.tables_accepted >= 4, name
            assert result.manifest.stats.n_tables >= 4, name
            assert result.manifest.stats.n_specs >= 20, name
            blob = _blob(result)
            assert "## Unnumbered table" in blob, name
            assert not re.search(r"^## Table \d", blob, re.MULTILINE), name
            assert len(blob) > 500, name

    def test_qpa1003p_specs_and_figures_materialize(self, gate):
        # ticket 09 supersedes the honest zeros: QPA1003P's heading-anchored
        # tables (abs-max + recommended operating conditions pair split at
        # the mirrored header, electrical specifications, thermal table,
        # handling-precautions table) yield spec records, and its
        # title-anchored figures (block diagram + the layout/plot headings)
        # render plot files. Zero silently stays the count here.
        result = gate["QPA1003P"]
        assert result.manifest.stats.n_specs >= 20
        assert result.manifest.stats.n_figures >= 4
        assert result.manifest.stats.n_plot_files >= 4
        spec_files = list((result.part_dir / "docs").glob("*/specs.json"))
        assert spec_files and all(
            json.loads(p.read_text(encoding="utf-8"))["records"]
            for p in spec_files
        )
        plot_files = list((result.part_dir / "docs").glob("*/plots.json"))
        assert plot_files and all(
            json.loads(p.read_text(encoding="utf-8"))["plots"]
            for p in plot_files
        )
        plots = json.loads(plot_files[0].read_text(encoding="utf-8"))["plots"]
        assert any("Functional Block Diagram" in p["caption"] for p in plots)


class TestGateFootnotesAndFigures:
    """Ticket 05: footnotes from font geometry + figures rendered from
    vector regions, proven on the real gate PDFs."""

    def test_ad9081_footnotes_attach_with_markers_once(self, gate):
        result = gate["AD9081"]
        blob = _blob(result)
        assert "**Footnotes:**" in blob
        # footnote 1 of Table 3 (p5) — the continuation is merged into the
        # body and the block appears exactly once, never as paragraphs
        assert blob.count("For dc-coupled applications, the maximum full-scale output "
                          "current is limited by the maximum VCMOUT specification.") == 1
        assert blob.count("The actual measured full-scale power is frequency dependent "
                          "due to DAC sinc response, impedance mismatch loss, and "
                          "balun insertion loss.") == 1

    def test_ad9081_spec_citation_resolves_marker_to_footnote(self, gate):
        import json

        from datasheet_analyzer.query import SpecQuery, format_answer

        result = gate["AD9081"]
        doc_dir = next((result.part_dir / "docs").glob("datasheet-*"))
        specs = json.loads((doc_dir / "specs.json").read_text(encoding="utf-8"))
        row = next(r for r in specs["records"]
                   if "Full-Scale Sine Wave Output Power with AC Coupling2" in r["symbol"])
        # table 3 cites footnote 2 on this row and footnote 1 on the DC
        # coupling row ("201" = value 20 + citation 1) — both real, both
        # detected from the superscript geometry
        assert sorted(row["cited_markers"]) == ["1", "2"], row["cited_markers"]
        dc = next(r for r in specs["records"]
                  if "50" in r["conditions"] and "shunt to GND" in r["conditions"])
        # the printed "201" is value 20 + citation 1: the marker survives in
        # the max cell and the record cites footnote 1
        assert dc["max"] == "201" and "1" in dc["cited_markers"]
        # the glued superscript text stays in the symbol (project convention)
        rec = SpecQuery(result.part_dir).find(
            symbol="Full-Scale Sine Wave Output Power")[0]
        answer = format_answer([rec])
        assert "frequency dependent due to DAC sinc response" in answer

    def test_gate_figures_render_as_files_and_plot_query_finds_them(self, gate):
        from datasheet_analyzer.query import find_plots

        result = gate["AD9081"]
        assert result.manifest.stats.n_figures >= 100
        files = list((result.part_dir / "docs").glob("*/figures/*/*.png"))
        assert len(files) >= 100
        assert all(f.stat().st_size > 1024 for f in files)

        found = find_plots(result.part_dir,
                           q="HD2 vs. fOUT over Digital Scale, 6 GSPS")
        assert found, "dsa plots query must resolve the vector figure"
        assert found[0].file and (result.part_dir / found[0].file).stat().st_size > 1024

    def test_hmc520a_figures_render_under_captions(self, gate):
        result = gate["HMC520A"]
        assert result.manifest.stats.n_figures >= 100
        files = list((result.part_dir / "docs").glob("*/figures/*/*.png"))
        assert len(files) >= 100
        plots = json.loads(
            next((result.part_dir / "docs").glob("*/plots.json")).read_text(
                encoding="utf-8"))
        caption = "Conversion Gain vs. RF Frequency at Various Temperatures"
        hits = [p for p in plots["plots"] if caption in p["caption"]]
        assert hits and (result.part_dir / hits[0]["file"]).exists()

    def test_lm741_old_ti_figures_render(self, gate):
        # old-TI section pages carry captioned vector figures too — they get
        # image files even though lm741 has no "Table N." captions at all
        result = gate["LM741"]
        plots = json.loads(
            next((result.part_dir / "docs").glob("*/plots.json")).read_text(
                encoding="utf-8"))["plots"]
        files = list((result.part_dir / "docs").glob("*/figures/*/*.png"))
        assert len(plots) >= 3 and len(files) == len(plots)
        for rec in plots:
            assert rec["file"] and (result.part_dir / rec["file"]).stat().st_size > 1024


class TestAliasSeedInventory:
    """Phase 5, ticket 02: the alias lexicon is seeded from what these
    corpora actually print, and `tests/fixtures/alias_seed_symbols.json` is
    the recorded harvest the fast alias tests measure against. Freshly built
    here, the gate parts must still harvest to exactly that — otherwise the
    seed is stale and the measured coverage is fiction."""

    def test_recorded_seed_matches_a_fresh_build(self, gate):
        from datasheet_analyzer.retrieve import CorpusIndex

        recorded = json.loads(
            (FIXTURES / "alias_seed_symbols.json").read_text(encoding="utf-8")
        )["parts"]
        for name in GATE:
            fresh = {
                (rec.symbol, rec.name, rec.unit.canonical)
                for doc in CorpusIndex.load(gate[name].part_dir).docs
                for rec in doc.specs
            }
            assert name in recorded, f"{name} missing from the alias seed inventory"
            seeded = {
                (row["symbol"], row["name"], row["unit_canonical"])
                for row in recorded[name]
            }
            assert seeded == fresh, (
                f"{name}: alias seed inventory is stale — regenerate with "
                "scripts/seed_aliases.py (procedure in its docstring)"
            )


class TestSearchIndexEconomics:
    """Phase 5, ticket 03: the full-text index is measured on real corpora.

    Size is recorded per part in `CorpusStats` (so every manifest carries the
    number the phase report quotes) and printed here two ways, because one
    ratio alone would flatter or damn it unfairly:

    - against the **whole corpus on disk**, which is what "must not dominate
      the corpus" means and where the index is a single-digit percentage;
    - against the **section markdown it indexes**, the strict comparison. The
      index is never larger than that text, but it is the same order of
      magnitude — a datasheet's prose vocabulary is large and its section
      files are mostly numeric tables that the index deliberately skips.
    """

    def test_index_size_is_recorded_and_does_not_dominate(self, gate, capsys):
        from datasheet_analyzer.publish import INDEX_FILENAME

        rows: list[str] = []
        for name in GATE:
            result = gate[name]
            stats = result.manifest.stats
            on_disk = sum(
                p.stat().st_size
                for p in (result.part_dir / "docs").glob(f"*/{INDEX_FILENAME}")
            )
            assert on_disk == stats.search_index_bytes, name
            assert stats.section_bytes > 0, name
            corpus_bytes = sum(
                p.stat().st_size for p in result.part_dir.rglob("*") if p.is_file()
            )
            of_corpus = stats.search_index_bytes / corpus_bytes
            of_text = stats.search_index_bytes / stats.section_bytes
            rows.append(
                f"  {name:<9} index {stats.search_index_bytes:>7,} B   "
                f"sections {stats.section_bytes:>8,} B   corpus {corpus_bytes:>9,} B   "
                f"{of_corpus:>5.1%} of corpus   {of_text:>5.0%} of section text"
            )
            assert of_corpus < 0.15, f"{name}: index dominates the corpus ({of_corpus:.1%})"
            assert of_text < 1.0, f"{name}: index exceeds the text it indexes ({of_text:.0%})"

        with capsys.disabled():
            print("\nsearch index size, four gate corpora\n" + "\n".join(rows) + "\n")

    def test_every_document_of_every_gate_part_is_searchable(self, gate):
        from datasheet_analyzer.retrieve import Retriever

        for name in GATE:
            retriever = Retriever.for_part(gate[name].part_dir)
            assert retriever.search_unavailable() == "", name

    def test_search_finds_real_content_with_a_real_page_cite(self, gate):
        """A search hit is cited by construction — the page comes from the
        manifest, and the quoted snippet is text the section file contains."""
        from datasheet_analyzer.retrieve import Retriever

        probes = {
            "AD9081": ("full-scale output current", "12 GSPS"),
            "LM741": ("overload protection", "Absolute Maximum Ratings"),
            "QPA1003P": ("wideband high power MMIC", "matched to 50"),
            "HMC520A": ("conversion loss", "Revision History"),
        }
        for name, (query, _other) in probes.items():
            result = gate[name]
            hits = Retriever.for_part(result.part_dir).search(query, limit=3)
            assert hits, f"{name}: {query!r} found nothing"
            top = hits[0]
            assert top.citation.page_start is not None, name
            assert top.snippet, name
            body = (result.part_dir / top.section.file).read_text(encoding="utf-8")
            probe = top.snippet.strip("…").split(" ")[1:6]
            assert " ".join(probe) in " ".join(body.split()), name


class TestConfidenceMix:
    """Phase 5, ticket 04: every spec and plot record is graded, the mix is
    recorded per part in the manifest, and the grade is metadata only — no
    record's value or page moves because grading landed.

    The mix is printed rather than pinned to exact numbers: it is a measured
    property of four real datasheets, and pinning it would turn every honest
    extraction improvement into a test failure. What *is* asserted is that the
    counts are complete, that they match the records on disk, and that the
    three captionless-era corpora really are all-`low` for the documented
    reason (their grids only ever reconstruct on a rescue split).
    """

    def test_mix_is_recorded_per_part_and_matches_the_records(self, gate, capsys):
        from datasheet_analyzer.retrieve import CorpusIndex
        from datasheet_analyzer.structure.confidence import mix

        rows: list[str] = []
        for name in GATE:
            result = gate[name]
            stats = result.manifest.stats
            index = CorpusIndex.load(result.part_dir)
            specs = [rec for doc in index.docs for rec in doc.specs]
            plots = [rec for doc in index.docs for rec in doc.plots]
            assert stats.spec_confidence == mix(specs), name
            assert sum(stats.spec_confidence.values()) == len(specs) == stats.n_specs
            if plots:
                assert stats.plot_confidence == mix(plots), name
                assert sum(stats.plot_confidence.values()) == len(plots)
            # nothing may be ungraded: every record went through the rule
            assert "unknown" not in stats.spec_confidence, name
            assert "unknown" not in stats.plot_confidence, name
            rows.append(
                f"  {name:<9} specs {len(specs):>4}  "
                + "  ".join(f"{g:>6} {n:>4}" for g, n in stats.spec_confidence.items())
                + f"   |  plots {len(plots):>4}  "
                + "  ".join(f"{g:>6} {n:>4}" for g, n in stats.plot_confidence.items())
            )
        with capsys.disabled():
            print("\nconfidence mix, four gate corpora\n" + "\n".join(rows) + "\n")

    def test_a_rescued_grid_is_why_the_captionless_corpora_are_low(self, gate):
        """LM741, QPA1003P and HMC520A print their tables under section
        headings with no caption and no header-declared column geometry the
        data obeys: measured, their grids only ever pass the gate on a rescue
        split, so every row is honestly `low`. AD9081's captioned ADI tables
        reconstruct from their own headers and produce all three grades."""
        for name in ("LM741", "QPA1003P", "HMC520A"):
            stats = gate[name].manifest.stats
            assert stats.spec_confidence["low"] == stats.n_specs, name
        ad9081 = gate["AD9081"].manifest.stats.spec_confidence
        assert min(ad9081.values()) > 0, ad9081

    def test_no_recorded_value_or_page_moved(self, gate):
        """Criterion: grading changes no answer. `alias_seed_symbols.json` is a
        harvest of these corpora's spec rows — values *and* pages — recorded
        before this ticket; every one of them must still read identically."""
        from datasheet_analyzer.retrieve import CorpusIndex

        recorded = json.loads(
            (FIXTURES / "alias_seed_symbols.json").read_text(encoding="utf-8")
        )["parts"]
        fields = ("min", "typ", "max", "value", "section", "page")
        for name in GATE:
            fresh: dict[tuple, dict] = {}
            for doc in CorpusIndex.load(gate[name].part_dir).docs:
                for rec in doc.specs:
                    key = (rec.symbol, rec.name, rec.unit.canonical)
                    fresh.setdefault(key, {f: getattr(rec, f) for f in fields})
            for row in recorded[name]:
                key = (row["symbol"], row["name"], row["unit_canonical"])
                assert key in fresh, f"{name}: {key} disappeared"
                assert fresh[key] == {f: row[f] for f in fields}, f"{name}: {key}"


class TestNumericLayerParseRate:
    """Phase 6, ticket 02: the numeric layer measured on the four gate corpora.

    It lives in this module because the four corpora are already built here —
    the six-part parse-rate number the phase report carries costs no second
    build. (The two TI reference corpora are measured in
    `test_phase6_quantities.py`, off the ones committed under `parts/`.)

    The rate is a **measurement, not a target**. The layout-floor parts score
    far below the TI ones, and the reason is not the grammar: measured, the
    overwhelming majority of their unparsed rows print *no value cell at all*,
    because a rescued grid put the numbers somewhere a value role never saw
    them. That is an extraction finding, and tuning the grammar to hide it
    would be exactly the wrong repair. What is asserted is the floor (so a
    grammar regression fails), that nothing is dropped, and that no printed
    cell of any published record was mutated by the layer.
    """

    # Measured; floors sit a little under, so an honest improvement raises
    # them and a regression fails.
    FLOORS: ClassVar[dict[str, float]] = {
        "AD9081": 0.30, "LM741": 0.62, "QPA1003P": 0.80, "HMC520A": 0.10,
    }

    VERBATIM_FIELDS: ClassVar[tuple[str, ...]] = (
        "symbol", "name", "conditions", "table_conditions",
        "min", "typ", "max", "value",
    )

    def _records(self, result):
        from datasheet_analyzer.retrieve import CorpusIndex

        return [rec for doc in CorpusIndex.load(result.part_dir).docs for rec in doc.specs]

    def _snapshot(self, record) -> tuple:
        return (
            tuple(getattr(record, f) for f in self.VERBATIM_FIELDS),
            record.unit.verbatim,
            record.unit.canonical,
            tuple(record.row_verbatim),
        )

    def test_parse_rate_holds_its_floor_and_breaks_down_by_section(self, gate, capsys):
        from datasheet_analyzer.structure.quantities import parse_rate

        tables: list[str] = []
        for name in GATE:
            records = self._records(gate[name])
            rate = parse_rate(records)
            assert rate.n_records == len(records), name
            assert sum(t for _, t in rate.by_section.values()) == len(records), name
            assert rate.rate >= self.FLOORS[name], f"{name} fell to {rate.rate:.0%}"
            tables.append(rate.as_table(title=name))
        with capsys.disabled():
            print("\nnumeric layer parse rate, four gate corpora\n")
            print("\n\n".join(tables) + "\n")

    def test_the_published_records_carry_the_layer(self, gate):
        from datasheet_analyzer.models import ParseConfidence

        for name in GATE:
            records = self._records(gate[name])
            parsed = [r for r in records if r.parse_confidence is ParseConfidence.EXACT]
            assert parsed, f"{name} parsed nothing at all"
            assert all(r.value_kind is not None for r in parsed), name
            # ...and an unparsed row is honestly null rather than zero
            for record in records:
                if record.parse_confidence is ParseConfidence.NONE:
                    assert record.value_si is None and record.unit_si == "", name

    def test_no_printed_cell_was_mutated_by_the_layer(self, gate):
        """The additive promise on four real corpora: re-running the layer over
        the published records changes no verbatim string."""
        from datasheet_analyzer.structure.quantities import annotate_record

        for name in GATE:
            records = self._records(gate[name])
            before = [self._snapshot(r) for r in records]
            for record in records:
                annotate_record(record)
            assert [self._snapshot(r) for r in records] == before, name

    def test_a_comparison_over_these_records_reports_what_it_could_not_read(self, gate):
        """Invariant 8: an unparseable row is listed, never quietly excluded."""
        from datasheet_analyzer.structure.quantities import parse_population

        for name in GATE:
            records = self._records(gate[name])
            population = parse_population(records, role="max")
            assert population.total == len(records), name
            assert len(population.listing()) == population.n_unparsed, name


class TestPinsOnTheGateCorpora:
    """Phase 6, ticket 04 — pins measured on four real datasheets.

    The ticket's first criterion is *"pin tables extract for all six built
    parts **or are honestly rejected with a recorded reason**; a part with no
    parseable pin table produces no `pins.json` rather than a partial one"*.
    Measured, the four gate PDFs land in three different states, and all three
    are the honest one:

    | Part | Printed pin table | Outcome |
    |---|---|---|
    | AD9081 | Table 21, 18x18 BGA | 321 pins published; the package states 324, so the cross-check warns |
    | HMC520A | Table 4, 24-terminal LCC | identified and **rejected whole** — pin 15 is claimed by two entries |
    | LM741 | printed, but the layout floor never reconstructs it as a grid | no pin table, no file |
    | QPA1003P | none printed | no pin table, no file |

    The two TI reference parts are the fifth and sixth built corpora and print
    no pin section at all; that is asserted in `test_afe7950_build.py`, where
    those corpora live.

    Numbers are printed as well as asserted, because the phase report quotes
    them; what is *asserted* is the contract — whole or nothing, every pin
    cited, the cross-check recorded — rather than a count that an honest
    extraction improvement would break.
    """

    #: Measured. AD9081 is the only gate part that publishes pins.
    PINS: ClassVar[dict[str, int]] = {
        "AD9081": 321, "LM741": 0, "QPA1003P": 0, "HMC520A": 0,
    }

    def _pins(self, result):
        from datasheet_analyzer.retrieve import CorpusIndex

        return [rec for doc in CorpusIndex.load(result.part_dir).docs for rec in doc.pins]

    def test_every_gate_part_extracts_its_pins_or_publishes_none(self, gate, capsys):
        rows: list[str] = []
        for name in GATE:
            result = gate[name]
            stats = result.manifest.stats
            files = list((result.part_dir / "docs").glob("*/pins.json"))
            pins = self._pins(result)
            assert len(pins) == stats.n_pins == self.PINS[name], name
            assert bool(files) == bool(pins), (
                f"{name}: a part with no pins must publish no pins.json"
            )
            reasons = [
                r
                for st in result.manifest.extraction_stats.values()
                for r in st.rejection_reasons
                if r.startswith("device-table")
            ]
            rows.append(
                f"  {name:<9} {len(pins):>4} pins   "
                f"{'pins.json' if files else 'no pins.json':<13} "
                f"{'; '.join(reasons) or '(no device-table rejection)'}"
            )
        with capsys.disabled():
            print("\npins, four gate corpora\n" + "\n".join(rows) + "\n")

    def test_a_rejected_pin_table_is_recorded_and_publishes_nothing(self, gate):
        """HMC520A prints a real 24-terminal pin table whose EPAD row the
        layout floor materializes onto pin 15. Two entries claiming one pin is
        a misread grid, so the table is refused **whole** and says why — a
        half-published pin table reads as a complete one to whoever greps it."""
        result = gate["HMC520A"]
        reasons = [
            r
            for st in result.manifest.extraction_stats.values()
            for r in st.rejection_reasons
            if r.startswith("device-table")
        ]
        assert reasons, "the rejection must be recorded, not merely logged"
        assert any('duplicate pin "15"' in r for r in reasons), reasons
        assert not list((result.part_dir / "docs").glob("*/pins.json"))
        # ...and the cross-check still ran: the package states 24 terminals.
        assert any(
            "no pin table was published" in w for w in result.manifest.derived_warnings
        ), result.manifest.derived_warnings

    def test_the_package_cross_check_warns_and_keeps_every_pin(self, gate):
        """ADR 0005's decided outcome, on a real mismatch. AD9081 is a
        324-ball BGA and 321 balls survive extraction: three are lost to a
        `M2 to` / `M5` range broken across two printed lines. The count warns,
        it is recorded in the manifest, and it suppresses nothing."""
        result = gate["AD9081"]
        warnings = result.manifest.derived_warnings
        assert any(
            "pin count mismatch" in w and "324" in w and "321" in w for w in warnings
        ), warnings
        assert result.manifest.stats.n_pins == 321, "a bad count never drops a good table"

    def test_every_published_pin_is_individually_cited_and_verbatim(self, gate):
        """Criterion 2, on the real table: `A2, E2, H2, L2, P2, V2` is one
        printed row and six citable pins, each quoting that row."""
        pins = self._pins(gate["AD9081"])
        by_pin = {rec.pin: rec for rec in pins}
        assert len(by_pin) == len(pins), "a pin designator is unique in a package"
        shared = [rec for rec in pins if rec.name == "AVDD2"]
        assert [rec.pin for rec in shared] == ["A2", "E2", "H2", "L2", "P2", "V2"]
        for rec in shared:
            assert rec.pin_verbatim == "A2, E2, H2, L2, P2, V2"
            assert rec.description == "Analog 2.0 V Supply Inputs for DAC."
            assert rec.page == 22
            assert rec.id and rec.confidence.value in ("high", "medium", "low")
        assert all(rec.page is not None for rec in pins), "an uncited pin is not an answer"

    def test_every_one_of_the_321_pins_resolves_through_its_source_reference(self, gate):
        """ADR 0005's enforcement clause on the real artifact: *every* `source`
        walks back to a real record and a printed page, not a sampled one.

        The unit suite runs the same loop over a 9-pin fixture; only the real
        table has enough records for an id collision or an ordinal drift to
        have somewhere to hide."""
        from datasheet_analyzer.provenance import PINS_ARTIFACT, resolve_source, source_ref
        from datasheet_analyzer.retrieve import CorpusIndex

        part_dir = gate["AD9081"].part_dir
        index = CorpusIndex.load(part_dir)
        ids = [rec.id for doc in index.docs for rec in doc.pins]
        assert len(ids) == 321 and len(set(ids)) == 321, "a pin id is unique per part"
        for doc in index.docs:
            for record in doc.pins:
                ref = source_ref(record.id, artifact=PINS_ARTIFACT, doc=doc.name)
                found = resolve_source(part_dir, ref)
                assert found is not None, ref
                assert found.record.pin == record.pin
                assert found.page is not None and found.page == record.page

    def test_the_type_lexicon_labels_the_table_and_admits_what_it_cannot(
        self, gate, capsys
    ):
        """Criterion 3 on real data: labels come from
        `registry/pin_types.yaml`, every labelled pin names the phrase that
        decided it, and the rows the lexicon cannot read stay `unknown` with no
        evidence rather than being guessed into a category."""
        from collections import Counter

        from datasheet_analyzer.models import PinType

        pins = self._pins(gate["AD9081"])
        counts = Counter(rec.type.value for rec in pins)
        for rec in pins:
            assert bool(rec.type_evidence) == (rec.type is not PinType.UNKNOWN), rec.pin
            if rec.type_evidence:
                assert rec.type_evidence.startswith(("name:", "description:"))
        assert counts["unknown"], "a lexicon that claims every row is not honest"
        assert counts["power"] and counts["ground"] and counts["digital"]
        with capsys.disabled():
            print(
                "\nAD9081 pin types (registry/pin_types.yaml)\n  "
                + "  ".join(f"{t} {n}" for t, n in sorted(counts.items()))
                + "\n"
            )

    def test_dsa_pins_type_power_returns_the_hand_checked_supply_set(self, gate, capsys):
        """Criterion 6, on AD9081 rather than AFE7950: the two TI reference
        datasheets print no pin section at all, so the hand-checked supply set
        is measured on the one built part that has one.

        Hand-checked against "Table 21. Pin Function Descriptions", p.22-23:
        every AD9081 supply rail is present and nothing else is. Asserted as
        the *rail set* rather than the ball count, because the balls are what
        an extraction improvement may legitimately move and the rails are what
        a designer is asking for.
        """
        from datasheet_analyzer.retrieve import Retriever

        hits = Retriever.for_part(gate["AD9081"].part_dir).pins(type="power")
        rails = sorted({hit.record.name for hit in hits})
        assert rails == [
            "AVDD1", "AVDD1_ADC", "AVDD2", "AVDD2_PLL", "BVDD2", "BVDD3", "BVNN2",
            "CLKVDD1", "DAVDD1", "DCLKVDD1", "DVDD1", "DVDD1P8", "DVDD1_RT", "FVDD1",
            "NVG1_OUT", "PLLCLKVDD1", "RVDD2", "SVDD1", "SVDD1_PLL", "SVDD2_PLL",
            "VCO_VREG", "VDD1_NVG", "VNN1",
        ]
        assert len(hits) == 85
        assert all(hit.citation.page_start in (22, 23) for hit in hits)
        assert all(hit.matched_via == "type" for hit in hits)
        # no ground, no signal, no no-connect leaked into the supply set
        assert not any(hit.record.name in ("GND", "NC", "DNC") for hit in hits)
        with capsys.disabled():
            print(
                f"\ndsa pins --part AD9081 --type power: {len(hits)} balls across "
                f"{len(rails)} rails\n  {', '.join(rails)}\n"
            )

    def test_a_part_with_no_pin_table_says_so_rather_than_no_such_pin(self, gate):
        """The honest-absence half. LM741 prints a "Pin Functions" table the
        layout floor never reconstructs as a grid; a pin lookup there must not
        read as "this device has no VDD pin"."""
        from datasheet_analyzer.retrieve import Retriever

        for name in ("LM741", "QPA1003P", "HMC520A"):
            retriever = Retriever.for_part(gate[name].part_dir)
            assert retriever.pins() == [], name
            assert "establishes nothing" in retriever.pin_gap(), name
        assert Retriever.for_part(gate["AD9081"].part_dir).pin_gap() == ""

    def test_the_pin_goldens_verify_at_100_percent_with_page_cites(self, gate, capsys):
        """Criterion 5, through the shipped verifier `dsa verify` runs."""
        from datasheet_analyzer.evalh.citations import verify_pin_queries
        from datasheet_analyzer.evalh.golden import load_golden

        questions = load_golden(GATE["AD9081"]["golden"])
        results = verify_pin_queries(questions, gate["AD9081"].part_dir)
        assert len(results) == 3, "pin -> name, name -> pins, count by type"
        failed = [(r.question.id, r.detail) for r in results if not r.ok]
        assert failed == [], failed
        with capsys.disabled():
            print(
                "\npin-path goldens, AD9081\n"
                + "\n".join(f"  {r.question.id:<24} {r.detail}" for r in results)
                + "\n"
            )

    def test_package_drawings_stay_figures_and_nothing_here_parses_one(self, gate):
        """The ticket's last criterion. AD9081's pin *configuration* is a
        drawing; it is still a retrievable figure with real pixels, and the
        pin records all come from the printed table — every one of them cites a
        page inside it."""
        from datasheet_analyzer.retrieve import Retriever

        retriever = Retriever.for_part(gate["AD9081"].part_dir)
        figures = [
            hit for hit in retriever.plots()
            if hit.record.file
            and (gate["AD9081"].part_dir / hit.record.file).stat().st_size > 1024
        ]
        assert figures, "the figure catalog must still hand over drawings"
        # ...and specifically *this* drawing. A generic "some figure has pixels"
        # would pass on a typical-characteristics curve while the package
        # drawing had been dropped from the catalog, which is the regression
        # this criterion exists to catch.
        drawings = [
            hit for hit in figures if "Pin Configuration" in hit.record.caption
        ]
        assert drawings, sorted({hit.record.caption for hit in figures})[:10]
        assert all(
            (gate["AD9081"].part_dir / hit.record.file).exists() for hit in drawings
        )
        table_pages = {22, 23, 24, 25, 26}
        assert {rec.page for rec in self._pins(gate["AD9081"])} <= table_pages


class TestAnswerPacks:
    """Phase 5, ticket 05: `dsa ask` measured on four real corpora.

    Three claims are proven here rather than asserted in prose:

    1. **Budget compliance is numeric over the whole golden set**, not
       spot-checked — every question of every gate part, at a generous budget
       and again at a tight one.
    2. **Citations are never what a budget removes**: at the tight budget
       every pack that answers at all still carries a citation, and the
       citation it carries is the one the generous pack carried.
    3. **Twin agreement**: a golden question carrying a `spec_query` /
       `plot_query` is the *symbol-path* question; asked in the designer's own
       natural-language wording, the pack must land on a cited golden page and
       carry the same verbatim expected substrings — the exact pass rule
       `evalh.citations.verify_spec_queries` applies to the symbol path.

    The misses are recorded per question rather than hidden behind a rate:
    `KNOWN_ASK_MISSES` is an exact set, so a regression fails *and* so does a
    fix that lands without updating the record.
    """

    BUDGET = 3000
    TIGHT_BUDGET = 400

    # Measured, not aspirational, and recorded per question so a regression
    # fails *and* so does a fix that lands without updating the record.
    #
    # The one residual is not alias coverage and cannot be closed by a YAML
    # edit. LM741 prints its absolute-maximum supply row as a parent row
    # (`Supply` / `voltage`, max ±22) followed by nameless device-variant
    # sub-rows carrying the per-variant maxima (`Supply` / `` , ±10 ±15 ±22
    # and ±10 ±15 ±18). The ask path reaches the *named* rows through
    # `supply voltages` and cites p.4 correctly, but the ±18 the question also
    # expects lives on a sub-row whose only text is the symbol `Supply` —
    # nothing distinguishes it from §6.5's `Supply` rows (PSRR 86 dB, supply
    # current 1.7 mA) except the parameter its parent printed. The symbol path
    # reaches it because `spec_query: {symbol: "Supply"}` takes every row with
    # that symbol wholesale. Closing this means materializing an inherited
    # *parameter name* into continuation rows at extraction time (ticket 09
    # materializes the symbol only) — a corpus change, not a retrieval one.
    KNOWN_ASK_MISSES: ClassVar[dict[str, set[str]]] = {
        "AD9081": set(),
        "LM741": {"s1-spec-supply-absmax"},
        "QPA1003P": set(),
        "HMC520A": set(),
    }

    def _twin_ok(self, question, pack) -> bool:
        """The symbol path's own pass rule, applied to the pack's answers.

        Ticket 09 moved that rule into `evalh.citations` as
        `pack_answers_question`, because `dsa verify` now applies it to every
        `ask_query` golden — one rule, one place, so this measurement and the
        shipped command can never disagree about what "the pack answered it"
        means."""
        from datasheet_analyzer.evalh.citations import pack_answers_question

        return pack_answers_question(question, pack)

    def test_every_golden_question_answers_inside_its_budget(self, gate, capsys):
        from datasheet_analyzer.evalh.golden import load_golden
        from datasheet_analyzer.retrieve import ROUTE_NONE, Retriever

        rows: list[str] = []
        routes: dict[str, int] = {}
        total = answered = 0
        largest = 0
        for name in GATE:
            retriever = Retriever.for_part(gate[name].part_dir)
            questions = load_golden(GATE[name]["golden"])
            costs = []
            for q in questions:
                pack = retriever.ask(q.question, budget=self.BUDGET)
                assert pack.tokens <= self.BUDGET, f"{name}/{q.id} blew its budget"
                assert not pack.over_budget, f"{name}/{q.id}"
                assert pack.route in ("spec", "plot", "search", ROUTE_NONE)
                if pack.route != ROUTE_NONE:
                    assert pack.citations, f"{name}/{q.id}: an answer with no citation"
                    assert all(line.citation for line in pack.answers), f"{name}/{q.id}"
                    answered += 1
                routes[pack.route] = routes.get(pack.route, 0) + 1
                costs.append(pack.tokens)
                total += 1
                largest = max(largest, pack.tokens)
            rows.append(
                f"  {name:<9} {len(questions):>2} questions   "
                f"mean {sum(costs) / len(costs):>6.0f} tok   max {max(costs):>5} tok"
            )
        with capsys.disabled():
            print(
                f"\nanswer packs, four gate corpora (budget {self.BUDGET})\n"
                + "\n".join(rows)
                + f"\n  {'TOTAL':<9} {total:>2} questions   {answered} answered   "
                + "  ".join(f"{r}: {n}" for r, n in sorted(routes.items()))
                + f"\n  largest pack {largest} tokens\n"
            )
        assert total >= 40
        assert routes.get("spec", 0) and routes.get("plot", 0) and routes.get("search", 0), (
            "all three routes must fire somewhere across four real datasheets"
        )

    def test_a_tight_budget_costs_prose_and_never_the_citation(self, gate):
        from datasheet_analyzer.evalh.golden import load_golden
        from datasheet_analyzer.retrieve import ROUTE_NONE, Retriever

        for name in GATE:
            retriever = Retriever.for_part(gate[name].part_dir)
            for q in load_golden(GATE[name]["golden"]):
                wide = retriever.ask(q.question, budget=self.BUDGET)
                tight = retriever.ask(q.question, budget=self.TIGHT_BUDGET)
                assert tight.tokens <= self.TIGHT_BUDGET, f"{name}/{q.id}"
                assert tight.route == wide.route, f"{name}/{q.id}: routing moved"
                if wide.route == ROUTE_NONE:
                    continue
                assert tight.citations, f"{name}/{q.id}: budget ate the citation"
                assert tight.citations[0] == wide.citations[0], f"{name}/{q.id}"
                assert tight.answers[0] == wide.answers[0], f"{name}/{q.id}"
                if tight.truncated:
                    assert "--budget" in tight.notice, f"{name}/{q.id}"

    def test_natural_language_lands_on_the_symbol_paths_answer(self, gate, capsys):
        from datasheet_analyzer.evalh.golden import load_golden
        from datasheet_analyzer.retrieve import Retriever

        rows: list[str] = []
        hits = twins = 0
        for name in GATE:
            retriever = Retriever.for_part(gate[name].part_dir)
            questions = [
                q for q in load_golden(GATE[name]["golden"]) if q.spec_query or q.plot_query
            ]
            misses = set()
            for q in questions:
                pack = retriever.ask(q.question, budget=self.BUDGET)
                if self._twin_ok(q, pack):
                    hits += 1
                else:
                    misses.add(q.id)
            twins += len(questions)
            rows.append(
                f"  {name:<9} {len(questions) - len(misses):>2}/{len(questions):<2} twins"
                + (f"   missed: {', '.join(sorted(misses))}" if misses else "")
            )
            assert misses == self.KNOWN_ASK_MISSES[name], (
                f"{name}: ask-path twin agreement moved — expected misses "
                f"{sorted(self.KNOWN_ASK_MISSES[name])}, got {sorted(misses)}"
            )
        with capsys.disabled():
            print(
                "\nask-path twin agreement (natural language vs the symbol path)\n"
                + "\n".join(rows)
                + f"\n  {'TOTAL':<9} {hits:>2}/{twins:<2} "
                f"({hits / twins:.0%})\n"
            )
        assert twins >= 15

    def test_the_json_pack_validates_against_its_declared_schema(self, gate):
        from datasheet_analyzer.evalh.golden import load_golden
        from datasheet_analyzer.retrieve import Retriever, validate_pack

        for name in GATE:
            retriever = Retriever.for_part(gate[name].part_dir)
            for q in load_golden(GATE[name]["golden"]):
                payload = retriever.ask(q.question, budget=self.BUDGET).as_dict()
                assert validate_pack(payload) == [], f"{name}/{q.id}"


PROJECT_MEMBERS = ["AD9081", "LM741", "HMC520A"]
# A phrase each part prints that the others do not (GATE[...]["content"]).
PROJECT_PROBES = {
    "AD9081": "full-scale output current range",
    "LM741": "overload protection",
    "HMC520A": "conversion loss",
}


@pytest.fixture(scope="module")
def board(gate, tmp_path_factory):
    """Three gate corpora under one parts dir, plus the project over them."""
    import shutil

    from datasheet_analyzer.config import Settings
    from datasheet_analyzer.projects import add_parts, new_project, save_project

    root = tmp_path_factory.mktemp("project-gate")
    settings = Settings(
        parts_dir=root / "parts",
        projects_dir=root / "projects",
        cache_dir=root / ".cache",
    ).resolve()
    for name in PROJECT_MEMBERS:
        shutil.copytree(
            gate[name].part_dir,
            settings.parts_dir / name,
            ignore=shutil.ignore_patterns("figures"),
        )
    project = new_project(
        "rf-frontend",
        settings.projects_dir,
        interfaces="AD9081 DAC out -> HMC520A DSA -> board edge; LM741 bias buffer.",
    )
    for name in PROJECT_MEMBERS:
        add_parts(project, [name], parts_dir=settings.parts_dir, role=f"{name} role")
    save_project(project, settings.projects_dir)
    return settings, project


class TestProjectIndexEconomics:
    """Phase 5, ticket 06: a real 3-part project, measured.

    The gate builds each part into its own `parts/` directory; a project is a
    list of parts under *one* directory, so the three corpora are copied into
    a shared one. `figures/` is deliberately left behind: a project index and
    a project-scoped ask read manifests, records and section text, never
    pixels, and copying a hundred PNGs per part would buy the test nothing.

    The index token count is printed rather than pinned: it is a measured
    property of three real datasheets, and the phase report quotes it. What is
    *asserted* is the promise — inside the budget, every member named, every
    member pointing at its own `INDEX.md` — and that a project-scoped question
    lands on the part that actually prints the answer.
    """

    MEMBERS: ClassVar[list[str]] = PROJECT_MEMBERS
    PROBES: ClassVar[dict[str, str]] = PROJECT_PROBES

    def test_a_three_part_project_index_fits_its_budget(self, board, capsys):
        from datasheet_analyzer.projects import write_project_index
        from datasheet_analyzer.tokens import count_tokens

        settings, project = board
        path, text = write_project_index(
            project,
            parts_dir=settings.parts_dir,
            projects_dir=settings.projects_dir,
            token_budget=settings.project_index_token_budget,
        )
        tokens = count_tokens(text)
        assert tokens <= settings.project_index_token_budget
        assert "Truncated to fit" not in text, "3 real parts must fit comfortably"
        for name in self.MEMBERS:
            assert f"**{name}**" in text
            target = (path.parent / f"../../parts/{name}/INDEX.md").resolve()
            assert target.exists()
        assert text.count("INDEX.md") >= len(self.MEMBERS)

        with capsys.disabled():
            print(
                f"\nPROJECT_INDEX.md, 3 gate parts ({', '.join(self.MEMBERS)}): "
                f"{tokens} tokens (budget {settings.project_index_token_budget}); "
                f"{path.stat().st_size:,} B\n"
            )

    def test_a_project_scoped_ask_returns_the_right_part(self, board, capsys):
        from datasheet_analyzer.projects import part_dirs
        from datasheet_analyzer.retrieve import ROUTE_NONE, ProjectRetriever

        settings, project = board
        scope = ProjectRetriever.for_parts(
            project.name, part_dirs(project, settings.parts_dir)
        )
        rows: list[str] = []
        for name, probe in self.PROBES.items():
            pack = scope.ask(probe, budget=3000)
            assert pack.route != ROUTE_NONE, probe
            assert pack.tokens <= 3000, probe
            parts = [line.part for line in pack.answers]
            assert name in parts, f"{probe!r} -> {parts}, expected {name}"
            assert all(line.citation for line in pack.answers), probe
            rows.append(f"  {probe:<32} -> {pack.route:<7} {', '.join(dict.fromkeys(parts))}")

        with capsys.disabled():
            print("\nproject-scoped ask, 3 gate parts\n" + "\n".join(rows) + "\n")

    def test_a_project_ask_answers_from_the_part_whose_golden_it_is(self, board, capsys):
        """Ticket 09: the project box, tied to the benchmarks rather than to
        hand-picked probes. Each member's own ask-path golden, asked of the
        *design*, must be answered by that member — on the page its benchmark
        cites — and every row must still name the part it came from, because
        across a board a value with no device is not an answer."""
        from datasheet_analyzer.evalh.citations import contains
        from datasheet_analyzer.evalh.golden import load_golden
        from datasheet_analyzer.projects import part_dirs
        from datasheet_analyzer.retrieve import ProjectRetriever

        settings, project = board
        scope = ProjectRetriever.for_parts(
            project.name, part_dirs(project, settings.parts_dir)
        )
        rows: list[str] = []
        for name in self.MEMBERS:
            golden = next(
                q for q in load_golden(GATE[name]["golden"]) if q.ask_query is not None
            )
            pack = scope.ask(golden.question, budget=3000)
            assert pack.tokens <= 3000, name
            assert all(line.part for line in pack.answers), name
            cited = [
                line for line in pack.answers
                if line.part == name and line.page_start in golden.pages
            ]
            assert cited, f"{name}: {golden.question!r} -> {[l.part for l in pack.answers]}"
            assert all(
                any(contains(line.text, sub) for line in cited)
                for sub in golden.expected_substrings
            ), name
            rows.append(
                f"  {golden.question[:52]:<54} -> "
                f"{', '.join(dict.fromkeys(line.part for line in pack.answers))}"
            )
        with capsys.disabled():
            print(
                "\nproject-scoped ask over each member's own golden\n"
                + "\n".join(rows) + "\n"
            )

    def test_every_hit_of_a_project_search_names_its_part(self, board):
        from datasheet_analyzer.projects import part_dirs
        from datasheet_analyzer.retrieve import ProjectRetriever

        settings, project = board
        scope = ProjectRetriever.for_parts(
            project.name, part_dirs(project, settings.parts_dir)
        )
        assert scope.search_unavailable() == "" and scope.search_gap() == ""
        hits = scope.search("output current", limit=8)
        assert hits
        assert all(hit.citation.part in self.MEMBERS for hit in hits)
        assert all(hit.citation.page_start is not None for hit in hits)

    def test_dsa_status_lists_the_project_alongside_the_parts(
        self, board, monkeypatch, capsys
    ):
        from datasheet_analyzer import cli

        settings, _project = board
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["status"]) == 0
        out = capsys.readouterr().out
        for name in self.MEMBERS:
            assert f"part: {name}" in out
        assert "project: rf-frontend" in out


class TestGateGoldens:
    """Ticket 07: per-part golden benchmarks, 100% on text + --specs +
    plot lookups for every gate part in a plain offline pytest run.
    Ground truth of every golden_qa_<PART>.yaml came from printed page
    text (page_texts) and was author-probed against the built corpus
    before shipping; these tests prove the seam itself."""

    @pytest.mark.parametrize("name", ["AD9081", "LM741", "QPA1003P", "HMC520A"])
    def test_golden_verifies_100_percent_on_text(self, gate, name):
        from datasheet_analyzer.evalh.citations import (
            summarize,
            verify_questions,
        )
        from datasheet_analyzer.evalh.golden import load_golden
        from datasheet_analyzer.extract.pdf_structure import page_texts

        spec = GATE[name]
        questions = load_golden(spec["golden"])
        assert questions, f"{name}: golden must not be empty"
        res = verify_questions(questions, gate[name].part_dir, page_texts(spec["pdf"]))
        summary = summarize(res)
        assert summary["passed"] == summary["total"] == len(questions), name
        unclaimed = set(summary["questions_without_covering_section"])
        assert unclaimed <= {q.id for q in questions if q.plot_query}, name

    @pytest.mark.parametrize("name", ["AD9081", "LM741", "QPA1003P", "HMC520A"])
    def test_dsa_verify_end_to_end_100_percent(self, gate, name, monkeypatch, capsys):
        # the user-facing command: per-part golden discovery (no --golden),
        # full text + spec-query + plot-query verification against the
        # built corpus, zero exit. The spec/plot counts are derived from
        # the benchmark itself, so a golden edit can never silently drift
        # the expectations below (LM741 3 spec, QPA1003P 2 spec + 1 plot).
        from datasheet_analyzer import cli
        from datasheet_analyzer.config import Settings
        from datasheet_analyzer.evalh.golden import load_golden

        spec = GATE[name]
        result = gate[name]
        settings = Settings(
            parts_dir=result.part_dir.parent, cache_dir=result.part_dir.parent / ".cache"
        ).resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        code = cli.main(["verify", "--part", name, "--specs", "--pdf", str(spec["pdf"])])
        assert code == 0, name
        out = capsys.readouterr().out
        questions = load_golden(spec["golden"])
        assert f"**{len(questions)}/{len(questions)} passed" in out, name
        # summary counts are derived from the benchmark itself, so a golden
        # edit can never silently drift the expectations above
        n_spec = sum(1 for q in questions if q.spec_query)
        n_plot = sum(1 for q in questions if q.plot_query)
        assert f"**{n_spec}/{n_spec} passed" in out, name
        if n_plot:
            assert f"**{n_plot}/{n_plot} passed" in out, name
        # ticket 09: the two new paths are part of the same command and the
        # same exit code, and their tables must be in the same output
        assert "## Ask-path verification" in out, name
        assert "## Search-path verification" in out, name


class TestGoldenPathsOnTheGateCorpora:
    """Phase 5, ticket 09 — the phase's claim, measured on four real PDFs.

    *"A designer's question, in a designer's words, returns a cited answer
    inside a budget."* Each gate part's benchmark gained an **ask-path**
    question (natural language, no symbols) and a **search-path** question
    (top-1 must be the section holding the answer), both judged against the
    ground truth the set already carried: the printed page it cites and the
    verbatim substrings read off that page.

    The verifiers are the shipped ones — `evalh.citations.verify_ask_queries`
    / `verify_search_queries`, the very code `dsa verify` runs — so this gate
    cannot pass by a rule written only for the test.
    """

    BUDGET = 3000

    def test_every_gate_part_carries_both_new_paths(self):
        from datasheet_analyzer.evalh.golden import load_golden

        for name in GATE:
            questions = load_golden(GATE[name]["golden"])
            assert any(q.ask_query is not None for q in questions), name
            assert any(q.search_query is not None for q in questions), name

    def test_the_ask_path_answers_every_golden_it_carries(self, gate, capsys):
        from datasheet_analyzer.evalh.citations import verify_ask_queries
        from datasheet_analyzer.evalh.golden import load_golden

        rows: list[str] = []
        for name in GATE:
            questions = load_golden(GATE[name]["golden"])
            results = verify_ask_queries(
                questions, gate[name].part_dir, budget=self.BUDGET
            )
            assert results, f"{name}: no ask-path question"
            failed = [r.question.id for r in results if not r.ok]
            assert failed == [], f"{name}: ask path missed {failed}"
            for r in results:
                assert r.tokens <= self.BUDGET, f"{name}/{r.question.id}"
                rows.append(
                    f"  {name:<9} {r.question.id:<28} {r.route:<7} "
                    f"{r.tokens:>4}/{r.budget} tok   {r.detail}"
                )
        with capsys.disabled():
            print("\nask-path goldens, four gate corpora\n" + "\n".join(rows) + "\n")

    def test_the_search_path_ranks_the_answering_section_first(self, gate, capsys):
        from datasheet_analyzer.evalh.citations import verify_search_queries
        from datasheet_analyzer.evalh.golden import load_golden

        rows: list[str] = []
        for name in GATE:
            questions = load_golden(GATE[name]["golden"])
            results = verify_search_queries(questions, gate[name].part_dir)
            assert results, f"{name}: no search-path question"
            failed = [(r.question.id, r.detail) for r in results if not r.ok]
            assert failed == [], f"{name}: search path missed {failed}"
            for r in results:
                rows.append(f"  {name:<9} {r.question.id:<30} {r.detail}")
        with capsys.disabled():
            print("\nsearch-path goldens, four gate corpora\n" + "\n".join(rows) + "\n")

    def test_budget_compliance_is_numeric_over_the_whole_golden_set(
        self, gate, capsys
    ):
        """Every question of every gate part — not only the ask-path ones —
        asked at a generous budget and again at a tight one, with the cost
        measured rather than sampled. The tight budget is the interesting
        one: it must cost prose, never a citation."""
        from datasheet_analyzer.evalh.golden import load_golden
        from datasheet_analyzer.retrieve import ROUTE_NONE, Retriever

        tight, rows, worst = 400, [], 0
        total = 0
        for name in GATE:
            retriever = Retriever.for_part(gate[name].part_dir)
            costs: list[int] = []
            for q in load_golden(GATE[name]["golden"]):
                wide = retriever.ask(q.question, budget=self.BUDGET)
                lean = retriever.ask(q.question, budget=tight)
                assert wide.tokens <= self.BUDGET and not wide.over_budget, q.id
                assert lean.tokens <= tight, q.id
                if wide.route != ROUTE_NONE:
                    assert lean.citations[0] == wide.citations[0], q.id
                costs.append(wide.tokens)
                total += 1
                worst = max(worst, wide.tokens)
            rows.append(
                f"  {name:<9} {len(costs):>2} questions   "
                f"mean {sum(costs) / len(costs):>5.0f} tok   max {max(costs):>4} tok"
            )
        with capsys.disabled():
            print(
                f"\nbudget compliance, four gate corpora (budget {self.BUDGET}, "
                f"tight {tight})\n" + "\n".join(rows)
                + f"\n  {'TOTAL':<9} {total:>2} questions   largest {worst} tok\n"
            )
        assert total >= 45


class TestMcpOverTheGateCorpora:
    """Phase 5, ticket 09: the MCP tools exercised **in the gate**, in-process.

    `tests/unit/test_mcp_server.py` proves the surface against a synthetic
    corpus — every tool, every declared schema, the response cap. What it
    cannot prove is that the tools answer *real* datasheets: a 45-page ADI
    part with unnumbered sections, an old-TI part with numbered ones, a Qorvo
    part with no outline at all. That is what this does, over the same memory
    transport (a real `ClientSession`, no subprocess, no port), driving the
    corpora the gate just built and the golden questions ticket 09 added.

    The SDK is an optional extra, so it is imported inside the fixture rather
    than at module scope: a lean install skips this class instead of failing
    collection and taking the whole phase-4 gate down with it.
    """

    @pytest.fixture
    def servers(self, gate, tmp_path_factory):
        pytest.importorskip("mcp", reason="the MCP gate needs the [mcp] extra")
        from datasheet_analyzer.mcp_server import server as S

        out = {}
        for name in GATE:
            part_dir = gate[name].part_dir
            settings = Settings(
                parts_dir=part_dir.parent,
                cache_dir=part_dir.parent / ".cache",
                projects_dir=tmp_path_factory.mktemp(f"mcp-projects-{name}"),
            ).resolve()
            out[name] = S.build_server(settings)
        return out

    def _golden(self, name, attr):
        from datasheet_analyzer.evalh.golden import load_golden

        return next(
            q for q in load_golden(GATE[name]["golden"])
            if getattr(q, attr) is not None
        )

    def test_every_tool_answers_every_gate_corpus_over_a_real_session(
        self, servers, gate, capsys
    ):
        from mcp_session import call, payload_of

        from datasheet_analyzer.mcp_server import responses as R

        rows: list[str] = []
        for name, server in servers.items():
            ask_q = self._golden(name, "ask_query")
            search_q = self._golden(name, "search_query")
            calls = {
                "list_parts": {},
                "list_projects": {},
                "get_index": {"part": name},
                "search": {"part": name, "query": search_q.search_query["query"]},
                "find_spec": {"part": name, "name": ask_q.question},
                "find_plots": {"part": name},
                "ask": {"part": name, "question": ask_q.question, "budget": 3000},
            }
            payloads = {}
            for tool, arguments in calls.items():
                payloads[tool] = payload_of(call(server, tool, **arguments))
                assert R.validate_response(payloads[tool], tool) == [], f"{name}/{tool}"
                assert payloads[tool]["error"] == "", f"{name}/{tool}"

            # the index is this corpus's own, not another part's
            assert name in payloads["get_index"]["text"], name
            assert payloads["list_parts"]["parts"][0]["part"] == name

            # a search hit is cited by construction, and its section reads back
            top = payloads["search"]["hits"][0]
            assert "p." in top["citation"], name
            section = payload_of(call(server, "read_section", part=name, ref=top["file"]))
            assert R.validate_response(section, "read_section") == [], name
            assert section["text"], name
            assert section["text"] == (
                gate[name].part_dir / top["file"]
            ).read_text(encoding="utf-8")

            # the ask tool lands the golden's cited page, inside its budget
            pack = payloads["ask"]["pack"]
            assert pack["route"] == ask_q.ask_query["route"], name
            assert pack["tokens"] <= pack["budget"], name
            assert any(
                line["page_start"] in ask_q.pages for line in pack["answers"]
            ), f"{name}: the MCP pack missed the cited page"

            # narrow the catalog, then receive the one figure as an image
            figure = self._first_figure(gate[name].part_dir, payloads["find_plots"])
            image = call(server, "get_figure", part=name, file=figure)
            blocks = [c for c in image.content if c.type == "image"]
            assert blocks and blocks[0].data, f"{name}: no image content block"
            assert payload_of(image)["figure"]["citation"], name

            rows.append(
                f"  {name:<9} {len(payloads['search']['hits']):>2} search hits   "
                f"{len(payloads['find_spec']['hits']):>3} spec hits   "
                f"ask {pack['route']:<6} {pack['tokens']:>4} tok   "
                f"figure {figure.rsplit('/', 1)[-1]}"
            )
        with capsys.disabled():
            print(
                "\nMCP tools over four gate corpora (in-process memory transport)\n"
                + "\n".join(rows) + "\n"
            )

    def _first_figure(self, part_dir, find_plots_payload) -> str:
        for hit in find_plots_payload["hits"]:
            if hit["file"] and (part_dir / hit["file"]).exists():
                return hit["file"]
        raise AssertionError(f"{part_dir.name}: no cataloged figure has pixels on disk")

    def test_a_traversal_attempt_is_refused_for_that_reason(self, servers):
        """The one refusal that must hold on a real corpus too: a caller's
        string becomes a path in exactly one place, and it refuses rather
        than normalizes."""
        from mcp_session import call, payload_of

        payload = payload_of(
            call(servers["AD9081"], "get_figure", part="AD9081",
                 file="../../../etc/passwd")
        )
        assert "refused" in payload["error"]
        assert "inside the part directory" in payload["error"]

    def test_the_response_cap_announces_itself_on_a_real_index(self, servers, gate):
        """A real `INDEX.md` is thousands of tokens; under a tiny cap the
        response must come back trimmed *and* say so, naming the setting."""
        from mcp_session import call, payload_of

        from datasheet_analyzer.mcp_server import responses as R
        from datasheet_analyzer.mcp_server import server as S

        part_dir = gate["AD9081"].part_dir
        settings = Settings(
            parts_dir=part_dir.parent,
            cache_dir=part_dir.parent / ".cache",
            mcp_max_tokens=120,
        ).resolve()
        payload = payload_of(
            call(S.build_server(settings), "get_index", part="AD9081")
        )
        assert R.validate_response(payload, "get_index") == []
        assert payload["truncated"]
        assert R.CAP_SETTING in payload["notice"]
        assert payload["tokens"] <= 120
