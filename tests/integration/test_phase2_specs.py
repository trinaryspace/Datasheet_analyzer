"""Phase 2 integration: specs.json on the real AFE7950 build."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.config import Settings
from datasheet_analyzer.evalh.citations import load_golden_yaml, verify_questions
from datasheet_analyzer.extract import get_backend
from datasheet_analyzer.extract.http import ReplayBinaryFetcher, ReplayFetcher
from datasheet_analyzer.extract.pdf_structure import page_texts
from datasheet_analyzer.models import CorpusManifest, SpecSet
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.publish import document_dirs
from datasheet_analyzer.query import SpecQuery

RECORDED = Path(__file__).parent.parent / "fixtures" / "recorded_http"
RECORDED_BIN = Path(__file__).parent.parent / "fixtures" / "recorded_http_bin"
GOLDEN = Path(__file__).parent.parent / "fixtures" / "golden_qa_AFE7950.yaml"

TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory, afe7950_pdf, monkeymodule):
    if not RECORDED.is_dir():
        pytest.skip("recorded HTTP fixtures not present")

    tmp = tmp_path_factory.mktemp("built_phase2")
    settings = Settings(parts_dir=tmp / "parts", cache_dir=tmp / ".cache").resolve()

    backend = get_backend("ti_html")
    backend.fetcher = ReplayFetcher(RECORDED)
    monkeymodule.setattr("datasheet_analyzer.pipeline.get_backend", lambda name: backend)

    bin_fetcher = ReplayBinaryFetcher(RECORDED_BIN, default=TINY_GIF)
    monkeymodule.setattr(
        "datasheet_analyzer.pipeline.CachingBinaryFetcher",
        lambda *args, **kwargs: bin_fetcher,
    )

    result = build_part(
        afe7950_pdf,
        part_number="AFE7950",
        settings=settings,
        use_llm=False,
        use_cache=False,
    )
    return result, settings


@pytest.fixture(scope="module")
def monkeymodule():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


def _doc_dir(result, doc):
    """Where this document's artifacts landed — under the part, or shared.

    Ticket 04 publishes a document once into the library and has every part
    that references it point there, so the directory is a fact of the
    manifest rather than a path a test can spell.
    """
    return document_dirs(result.manifest, part_dir=result.part_dir)[doc.content_hash]


@pytest.mark.integration
class TestPhase2Specs:
    def test_specs_json_exists_and_validates(self, built):
        result, _ = built
        doc = result.manifest.documents[0]
        specs_path = _doc_dir(result, doc) / "specs.json"
        assert specs_path.exists()
        specset = SpecSet.model_validate_json(
            specs_path.read_text(encoding="utf-8")
        )
        assert specset.schema_version
        # A document published once into the shared store is part-*neutral*
        # (ticket 04): which part published it first is an accident of
        # ordering, and stamping it here would make two parts rewrite the file
        # forever. The part identity lives in the manifest that references it.
        assert specset.part_number == ""
        assert result.manifest.part_number == "AFE7950"
        assert specset.doc_hash == doc.content_hash
        assert len(specset.records) >= 150

    def test_every_record_page_in_section_range(self, built):
        result, _ = built
        manifest = CorpusManifest.model_validate(
            json.loads((result.part_dir / "manifest.json").read_text(encoding="utf-8"))
        )
        section_ranges = {
            s.number: (s.page_start, s.page_end or s.page_start)
            for s in manifest.sections
            if s.page_start is not None
        }
        doc = result.manifest.documents[0]
        specset = SpecSet.model_validate_json(
            (_doc_dir(result, doc) / "specs.json").read_text(encoding="utf-8")
        )
        bad = []
        for rec in specset.records:
            if rec.page is None:
                continue
            start, end = section_ranges.get(rec.section, (None, None))
            if start is None or not (start <= rec.page <= end):
                bad.append((rec.section, rec.page, (start, end)))
        assert bad == [], f"records with page outside section range: {bad[:10]}"

    def test_golden_spec_queries_pass(self, built):
        result, _ = built
        questions = load_golden_yaml(GOLDEN)
        q = SpecQuery(result.part_dir)
        spec_questions = [q_ for q_ in questions if q_.spec_query]
        assert len(spec_questions) >= 8
        passed = 0
        for question in spec_questions:
            recs = q.find(**question.spec_query)
            paged = [r for r in recs if r.page is not None and r.page in question.pages]
            if not paged:
                continue
            ok = all(
                any(sub in _fields(r) for r in paged)
                for sub in question.expected_substrings
            )
            if ok:
                passed += 1
        assert passed >= 8, f"only {passed}/{len(spec_questions)} spec queries passed"

    def test_query_cli_smoke(self, built, monkeypatch, capsys):
        _result, settings = built
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        exit_code = cli.main(["query", "--part", "AFE7950", "--symbol", "ATTstep"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "ATTstep" in captured.out
        assert "p.7" in captured.out

    def test_phase1_golden_regression(self, built, afe7950_pdf):
        result, _ = built
        questions = load_golden_yaml(GOLDEN)
        results = verify_questions(questions, result.part_dir, page_texts(afe7950_pdf))
        failed = [r.question.id for r in results if not r.passed]
        assert failed == [], f"golden QA failures: {failed}"


def _fields(rec) -> str:
    return (
        f"{rec.symbol} {rec.name} {rec.conditions} "
        f"{rec.min} {rec.typ} {rec.max} {rec.value} "
        f"{rec.unit.verbatim} {rec.unit.canonical}"
    )
