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
        specset = SpecSet.model_validate_json(specs_path.read_text(encoding="utf-8"))
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
        """A record cites its own section's pages — plus, at most, the next one.

        The section range comes from the PDF outline, so it is a *heading*
        boundary: the next section's heading starts partway down a page, and a
        table that began in this section can finish on it. Phase 6.5 ticket 07
        pins each row to the page it is printed on, and four rows of AFE7950's
        section 4.8 (`VOCOM`, `VOD`, `ZT` and their LVDS band header) then
        cited page 21 against a recorded range of 20-20. Checked against the
        PDF's own page text: those rows appear on page 21 and **not** on 20.
        The citation is right and the range is the approximation, so the
        invariant allows exactly one page of spill and no more.
        """
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
            if start is None or not (start <= rec.page <= end + 1):
                bad.append((rec.section, rec.page, (start, end)))
        assert bad == [], f"records with page outside section range: {bad[:10]}"

    def test_a_record_beyond_its_section_really_prints_there(self, built, afe7950_pdf):
        """The spill allowed above must be evidence, never slack.

        Every record citing the page after its section's recorded end is
        checked against that page's own text: the row's distinctive cells have
        to be on it. Without this, widening the range by one page would let a
        genuinely mis-pinned row through.
        """
        from datasheet_analyzer.structure.pagemap import _hits, _row_needles

        result, _ = built
        manifest = CorpusManifest.model_validate(
            json.loads((result.part_dir / "manifest.json").read_text(encoding="utf-8"))
        )
        ends = {
            s.number: (s.page_end or s.page_start)
            for s in manifest.sections
            if s.page_start is not None
        }
        doc = result.manifest.documents[0]
        specset = SpecSet.model_validate_json(
            (_doc_dir(result, doc) / "specs.json").read_text(encoding="utf-8")
        )
        texts = page_texts(afe7950_pdf)
        unproven = []
        for rec in specset.records:
            end = ends.get(rec.section)
            if rec.page is None or end is None or rec.page <= end:
                continue
            needles = _row_needles(list(rec.row_verbatim))
            if needles and not _hits(needles, texts, rec.page):
                unproven.append((rec.section, rec.page, rec.row_verbatim[:2]))
        assert unproven == [], f"spilled records not found on the page they cite: {unproven[:5]}"

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
            ok = all(any(sub in _fields(r) for r in paged) for sub in question.expected_substrings)
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
