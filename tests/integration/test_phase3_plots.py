"""Phase 3 integration: plot pixels + plot lookup on the real AFE7950 build."""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.evalh.citations import load_golden_yaml
from datasheet_analyzer.extract import get_backend
from datasheet_analyzer.extract.http import ReplayBinaryFetcher, ReplayFetcher
from datasheet_analyzer.models import PlotSet
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.query import find_plots
from datasheet_analyzer.tokens import count_tokens

RECORDED = Path(__file__).parent.parent / "fixtures" / "recorded_http"
RECORDED_BIN = Path(__file__).parent.parent / "fixtures" / "recorded_http_bin"
GOLDEN = Path(__file__).parent.parent / "fixtures" / "golden_qa_AFE7950.yaml"

# Minimal valid GIF for the 511 plots we don't need real pixels for.
TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory, afe7950_pdf, monkeymodule):
    if not RECORDED.is_dir():
        pytest.skip("recorded HTTP fixtures not present")
    if not RECORDED_BIN.is_dir():
        pytest.skip("recorded binary fixtures not present")

    tmp = tmp_path_factory.mktemp("built_phase3")
    settings = Settings(parts_dir=tmp / "parts", cache_dir=tmp / ".cache").resolve()

    backend = get_backend("ti_html")
    backend.fetcher = ReplayFetcher(RECORDED)
    monkeymodule.setattr("datasheet_analyzer.pipeline.get_backend", lambda name: backend)

    # All unrecorded plot URLs get a tiny stand-in GIF so 514 files exist.
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


@pytest.mark.integration
class TestPhase3Plots:
    def test_plots_json_exists_and_validates(self, built):
        result, _ = built
        doc = result.manifest.documents[0]
        plots_path = (
            result.part_dir / f"docs/datasheet-{doc.content_hash[:8]}" / "plots.json"
        )
        assert plots_path.exists()
        plotset = PlotSet.model_validate_json(
            plots_path.read_text(encoding="utf-8")
        )
        assert plotset.schema_version
        assert plotset.part_number == "AFE7950"
        assert plotset.doc_hash == doc.content_hash
        assert len(plotset.plots) == 514

    def test_all_figure_files_exist(self, built):
        result, _ = built
        doc = result.manifest.documents[0]
        plotset = PlotSet.model_validate_json(
            (
                result.part_dir / f"docs/datasheet-{doc.content_hash[:8]}" / "plots.json"
            ).read_text(encoding="utf-8")
        )
        missing = []
        for rec in plotset.plots:
            if not rec.file:
                missing.append(rec.id)
                continue
            fpath = result.part_dir / rec.file
            if not fpath.exists():
                missing.append(rec.id)
        assert missing == [], f"missing plot files: {missing[:10]}"
        assert result.manifest.stats.n_plot_files == 514

    def test_golden_plot_queries_pass(self, built):
        result, _ = built
        questions = load_golden_yaml(GOLDEN)
        plot_questions = [q for q in questions if q.plot_query]
        assert len(plot_questions) == 3
        passed = 0
        for q in plot_questions:
            query = q.plot_query or {}
            recs = find_plots(
                result.part_dir,
                caption=query.get("caption_contains", ""),
                conditions=query.get("conditions_contain", ""),
                section=query.get("section", ""),
            )
            file_hits = []
            for r in recs:
                if r.page_start not in q.pages:
                    continue
                if not r.file:
                    continue
                fpath = result.part_dir / r.file
                if fpath.exists() and fpath.stat().st_size > 1024:
                    file_hits.append(r)
            text = " ".join(r.caption + " " + r.conditions for r in file_hits)
            if file_hits and all(sub in text for sub in q.expected_substrings):
                passed += 1
        assert passed == 3, f"only {passed}/3 plot queries passed"

    def test_golden_plot_files_are_real_size(self, built):
        result, _ = built
        plotset = PlotSet.model_validate_json(
            (
                result.part_dir
                / f"docs/datasheet-{result.manifest.documents[0].content_hash[:8]}"
                / "plots.json"
            ).read_text(encoding="utf-8")
        )
        # The three golden plots must be the real (>5 KB) recordings, not tiny GIFs.
        golden_ids = {"4.12.1-f001", "4.12.1-f003", "4.12.8-f017"}
        for rec in plotset.plots:
            if rec.id not in golden_ids:
                continue
            fpath = result.part_dir / rec.file
            assert fpath.stat().st_size > 5000, f"{rec.id} is not a real recording"

    def test_plot_question_token_cost(self, built):
        """INDEX + plots slice + one image should fit in ~4k tokens."""
        result, _settings = built
        index_md = (result.part_dir / "INDEX.md").read_text(encoding="utf-8")
        index_tokens = count_tokens(index_md)

        plot_recs = find_plots(
            result.part_dir,
            caption="Output Fullscale vs Output Frequency",
            section="4.12.1",
        )
        plots_text = format_plot_answer_for_test(plot_recs[:8])
        plots_tokens = count_tokens(plots_text)

        # Approximate vision token cost for a ~400x300 GIF (~1.5k tokens).
        image_tokens = 1500
        total = index_tokens + plots_tokens + image_tokens
        assert total <= 4200, f"plot question cost {total} tokens exceeds budget"


def format_plot_answer_for_test(records: list) -> str:
    lines = []
    for r in records:
        cond = f" — {r.conditions}" if r.conditions else ""
        lines.append(f"{r.caption} — §{r.section}{cond}")
    return "\n".join(lines)


@pytest.mark.integration
@pytest.mark.llm
@pytest.mark.skipif(
    not Settings().llm_available, reason="no ANTHROPIC_API_KEY available"
)
class TestPhase3VisionSmoke:
    def test_vision_reads_one_golden_plot(self, built):
        result, settings = built
        from datasheet_analyzer.enrich.llm import AnthropicClient

        plotset = PlotSet.model_validate_json(
            (
                result.part_dir
                / f"docs/datasheet-{result.manifest.documents[0].content_hash[:8]}"
                / "plots.json"
            ).read_text(encoding="utf-8")
        )
        rec = next(p for p in plotset.plots if p.id == "4.12.1-f001")
        fpath = result.part_dir / rec.file
        image_bytes = fpath.read_bytes()
        client = AnthropicClient(settings.anthropic_api_key, settings.model)
        answer = client.complete(
            "You are looking at a datasheet plot.",
            "What quantity is plotted on the Y axis? Answer with one word.",
            max_tokens=256,
            image_bytes=image_bytes,
            image_media_type="image/gif",
        )
        assert any(
            word in answer for word in ("dBm", "Output", "Gain", "Power", "Fullscale")
        ), f"unexpected vision answer: {answer!r}"
