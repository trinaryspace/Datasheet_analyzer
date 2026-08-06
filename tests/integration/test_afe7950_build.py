"""Integration: full AFE7950 build from recorded TI pages (hermetic —
ReplayFetcher cannot touch the network) + golden Q&A verification + a
whole-corpus footnote-orphan audit.

This is the end-to-end proof that Phase 1 works on the real target.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.evalh.citations import load_golden_yaml, verify_questions
from datasheet_analyzer.evalh.golden import estimate_lookup_tokens
from datasheet_analyzer.extract import get_backend
from datasheet_analyzer.extract.http import ReplayBinaryFetcher, ReplayFetcher
from datasheet_analyzer.extract.pdf_structure import page_texts
from datasheet_analyzer.models import CorpusManifest
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.structure.footnotes import audit_table_footnotes

RECORDED = Path(__file__).parent.parent / "fixtures" / "recorded_http"
RECORDED_BIN = Path(__file__).parent.parent / "fixtures" / "recorded_http_bin"
GOLDEN = Path(__file__).parent.parent / "fixtures" / "golden_qa_AFE7950.yaml"

TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory, afe7950_pdf, monkeymodule):
    """Build the real corpus once per module, replaying recorded HTTP."""
    if not RECORDED.is_dir():
        pytest.skip("recorded HTTP fixtures not present")

    tmp = tmp_path_factory.mktemp("built")
    settings = Settings(parts_dir=tmp / "parts", cache_dir=tmp / ".cache").resolve()

    backend = get_backend("ti_html")
    backend.fetcher = ReplayFetcher(RECORDED)
    monkeymodule.setattr("datasheet_analyzer.pipeline.get_backend", lambda name: backend)

    # Plot pixels must be hermetic too; use real recordings for golden plots
    # and a tiny stand-in GIF for everything else.
    bin_fetcher = ReplayBinaryFetcher(RECORDED_BIN, default=TINY_GIF)
    monkeymodule.setattr(
        "datasheet_analyzer.pipeline.CachingBinaryFetcher",
        lambda *args, **kwargs: bin_fetcher,
    )

    result = build_part(afe7950_pdf, part_number="AFE7950", settings=settings,
                        use_llm=False, use_cache=False)
    return result, settings


@pytest.fixture(scope="module")
def monkeymodule():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.mark.integration
class TestRealBuild:
    def test_corpus_shape(self, built):
        result, _ = built
        s = result.manifest.stats
        assert s.n_documents == 1
        assert s.n_sections == 39  # 40 TOC anchors minus the cover page
        assert s.n_tables >= 15
        assert s.n_figures >= 500  # the plot gallery is fully cataloged
        assert s.n_footnotes >= 20
        assert s.n_specs >= 150  # Phase 2: parametric rows normalized
        assert s.index_tokens <= 3000  # INDEX.md stays inside its budget

    def test_page_coverage_complete(self, built):
        result, _ = built
        for s in result.manifest.sections:
            assert s.page_start is not None, f"{s.number} {s.title} has no pages"
            assert 1 <= s.page_start <= 146
            assert (s.page_end or s.page_start) >= s.page_start

    def test_every_manifest_file_exists(self, built):
        result, _ = built
        for s in result.manifest.sections:
            assert (result.part_dir / s.file).exists(), s.file
        # Phase 2: specs.json written next to the sections dir
        doc_dir = result.part_dir / f"docs/datasheet-{result.manifest.documents[0].content_hash[:8]}"
        assert (doc_dir / "specs.json").exists()

    def test_manifest_schema_roundtrip(self, built):
        result, _ = built
        data = json.loads((result.part_dir / "manifest.json").read_text(encoding="utf-8"))
        m = CorpusManifest.model_validate(data)
        assert m.part_number == "AFE7950"

    def test_no_footnote_orphans_in_whole_corpus(self, built):
        """Every footnote marker cited in any table resolves to a note."""
        result, settings = built
        from datasheet_analyzer.models import RawDocument

        cache = result.manifest.documents[0].content_hash
        raw_path = settings.cache_dir / "extract" / f"{cache}__ti_html.json"
        raw = RawDocument.model_validate_json(raw_path.read_text(encoding="utf-8"))
        orphans = []
        for sec in raw.sections:
            for t in sec.tables:
                audit = audit_table_footnotes(t, set(t.cited_markers))
                if not audit.ok:
                    orphans.append((sec.number, sorted(audit.orphans)))
        assert orphans == [], f"orphan footnote citations: {orphans}"

    def test_exact_spec_values_in_corpus_files(self, built):
        result, _ = built
        tx45 = next(
            f for f in result.part_dir.rglob("4-5-transmitter-electrical-characteristics.md")
        )
        text = tx45.read_text(encoding="utf-8")
        for needle in ["DAC resolution", "14", "DSA Attenuation range", "±0.1",
                       "After DSA calibration procedure", "Typical values at"]:
            assert needle in text, f"{needle!r} missing from 4.5 section file"

    def test_golden_qa_all_pass(self, built, afe7950_pdf):
        result, _ = built
        questions = load_golden_yaml(GOLDEN)
        results = verify_questions(questions, result.part_dir, page_texts(afe7950_pdf))
        failed = [r.question.id for r in results if not r.passed]
        assert failed == [], f"golden QA failures: {failed}"

    def test_token_economics(self, built):
        result, _ = built
        questions = load_golden_yaml(GOLDEN)
        results = verify_questions(questions, result.part_dir, ["x"] * 146)
        est = estimate_lookup_tokens(result.part_dir, results)
        # the whole point of the architecture: lookups are far cheaper
        # than dumping the corpus into context
        assert est["avg_per_question"] < est["full_dump_tokens"] / 5
        assert est["max_per_question"] < est["full_dump_tokens"] / 3

    def test_rebuild_uses_extraction_cache(self, built, monkeymodule):
        result, settings = built
        backend = get_backend("ti_html")  # fetcher still wired by fixture
        monkeymodule.setattr("datasheet_analyzer.pipeline.get_backend", lambda name: backend)
        second = build_part(
            Path(result.manifest.documents[0].path),
            part_number="AFE7950", settings=settings, use_llm=False,
        )
        assert second.cached_extraction
