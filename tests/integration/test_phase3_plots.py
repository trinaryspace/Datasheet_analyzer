"""Phase 3 integration: plot pixels + plot lookup on the real AFE7950 build."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.evalh.citations import load_golden_yaml, squash
from datasheet_analyzer.extract import get_backend
from datasheet_analyzer.extract.http import ReplayBinaryFetcher, ReplayFetcher
from datasheet_analyzer.models import AxisScale, Confidence, PlotSet
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.query import find_plots
from datasheet_analyzer.retrieve import Retriever
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


@pytest.mark.integration
class TestPlotAxisCatalogOnTheReferencePart:
    """Phase 6, ticket 08's gate: the axis catalog on AFE7950's 514 figures.

    The ≥60% floor is measured on a fresh build, and the two hand-verified
    figures are read off the printed pages — figure 4-1 on p.29 and figure 4-492
    on p.129, the latter being the log-axis case. `axis_confidence` is what makes
    the remainder honest: a figure whose plot is a raster image publishes null
    axes and says `low`, and still publishes its caption, conditions and image.
    """

    @staticmethod
    def _plots(result) -> list:
        path = (
            result.part_dir
            / f"docs/datasheet-{result.manifest.documents[0].content_hash[:8]}"
            / "plots.json"
        )
        return PlotSet.model_validate_json(path.read_text(encoding="utf-8")).plots

    @staticmethod
    def _by_number(plots: list, number: str):
        return next(p for p in plots if p.figure_number == number)

    def test_axis_coverage_beats_the_sixty_percent_floor(self, built):
        result, _ = built
        plots = self._plots(result)
        assert len(plots) == 514
        grades = Counter(p.axis_confidence.value for p in plots)
        high = grades["high"]
        # Measured 458/514 = 89% (`scripts/measure_axis_coverage.py`). The
        # assertion is the ticket's floor, not the measurement, so improving the
        # reader never fails the gate — but a regression below the floor does.
        assert high / len(plots) >= 0.60, f"axis coverage {high}/{len(plots)}: {grades}"
        assert grades["unknown"] == 0, "every figure was read, or said it was not"

    def test_the_remainder_is_honestly_null(self, built):
        """Every record on all three grades, checked for a half-filled axis.

        A `low` record has *nothing* — that is what "honestly null" means. A
        `medium` one read one axis and not the other. What no record may ever
        have is half an axis: a range with no title, half a range, or a scale
        with no range. All of it comes from one tick sequence and one title run,
        and none of it is a default.
        """
        for rec in self._plots(built[0]):
            for axis in ("x", "y"):
                label = getattr(rec, f"{axis}_label")
                lo = getattr(rec, f"{axis}_min")
                hi = getattr(rec, f"{axis}_max")
                scale = getattr(rec, f"{axis}_scale")
                assert (lo is None) == (hi is None), f"{rec.id}: half a {axis} range"
                assert (lo is None) == (not label), f"{rec.id}: unnamed {axis} range"
                assert (scale is None) == (lo is None), f"{rec.id}: {axis} scale alone"
            if rec.axis_confidence is not Confidence.LOW:
                continue
            assert (rec.x_label, rec.x_unit, rec.y_label, rec.y_unit) == ("", "", "", "")
            assert rec.x_min is None and rec.y_min is None

    def test_no_figure_is_lost_to_a_failed_axis_parse(self, built):
        result, _ = built
        blind = [p for p in self._plots(result) if p.axis_confidence is Confidence.LOW]
        assert blind, "the reference part has figures whose axes are pixels"
        for rec in blind:
            assert rec.caption, f"{rec.id} lost its caption"
            assert rec.page_start is not None
            assert rec.file, f"{rec.id} lost its image"
            assert rec.axis_derivation == "" and rec.axis_page is None

    def test_every_published_axis_string_is_on_the_page_it_cites(
        self, built, afe7950_pdf
    ):
        """The ticket's accuracy walk, over all 514 figures at once.

        Ticket 06's field walk applied to this artifact: take every axis string
        the corpus published — both titles and both printed units — and require
        it to appear in the text of the page that record's own `axis_page` cites.
        A reading that borrowed a neighbouring figure's axis on the *same* page
        survives this; one that drifted a page, matched a caption instead of an
        axis, or invented a unit does not. Measured: 491 of 514 records cite an
        axis page, and **0** of their strings are absent from it.
        """
        from datasheet_analyzer.extract.pdf_structure import page_texts

        # `page_texts` is 0-indexed; a record's `axis_page` is the printed page.
        pages = {n: squash(t) for n, t in enumerate(page_texts(afe7950_pdf), start=1)}
        walked = 0
        for rec in self._plots(built[0]):
            if rec.axis_page is None:
                assert rec.axis_derivation == "", f"{rec.id} names a rule but no page"
                continue
            walked += 1
            page = pages.get(rec.axis_page, "")
            assert page, f"{rec.id} cites p.{rec.axis_page}, which has no text"
            for field in ("x_label", "x_unit", "y_label", "y_unit"):
                printed = getattr(rec, field)
                if not printed:
                    continue
                assert squash(printed) in page, (
                    f"{rec.id} publishes {field}={printed!r}, which p.{rec.axis_page} "
                    f"does not print"
                )
        assert walked >= 0.90 * len(self._plots(built[0]))

    def test_figure_4_1_matches_the_printed_page(self, built):
        """Hand-verified on p.29: `Output Frequency (MHz)` 600…1500 against
        `Output Full Scale (dBm)` −2…7, both linear."""
        rec = self._by_number(self._plots(built[0]), "4-1")
        assert rec.axis_confidence is Confidence.HIGH
        assert rec.axis_page == 29
        assert (rec.x_label, rec.x_unit) == ("Output Frequency", "MHz")
        assert (rec.x_min, rec.x_max) == (600.0, 1500.0)
        assert rec.x_scale is AxisScale.LINEAR
        assert (rec.y_label, rec.y_unit) == ("Output Full Scale", "dBm")
        assert (rec.y_min, rec.y_max) == (-2.0, 7.0)
        assert rec.y_scale is AxisScale.LINEAR

    def test_a_rotated_y_title_is_read_on_a_real_figure(self, built):
        """The real half of the ticket's rotated-title criterion: every y title
        in this document is printed at a quarter turn, so a majority of 514
        figures carrying one is only possible if rotation is read correctly."""
        plots = self._plots(built[0])
        rotated = [p for p in plots if p.y_label]
        assert len(rotated) / len(plots) >= 0.60
        assert self._by_number(plots, "4-1").y_label == "Output Full Scale"

    def test_a_real_log_axis_is_marked_log_not_linear(self, built):
        """Hand-verified on p.129: figure 4-492 prints `1E+3 … 1E+8` under
        `Offset Frequency (Hz)`. A linear reading of that axis would be the
        confidently-wrong number invariant 8 exists to prevent."""
        plots = self._plots(built[0])
        rec = self._by_number(plots, "4-492")
        assert rec.axis_page == 129
        assert (rec.x_label, rec.x_unit) == ("Offset Frequency", "Hz")
        assert (rec.x_min, rec.x_max) == (1000.0, 1e8)
        assert rec.x_scale is AxisScale.LOG
        assert (rec.y_label, rec.y_unit) == ("Phase Noise", "dBc/Hz")
        assert (rec.y_min, rec.y_max) == (-160.0, -80.0)
        assert rec.y_scale is AxisScale.LINEAR
        # And the document really does print both kinds, so "log" is not a label
        # this build hands out to everything.
        assert 0 < sum(1 for p in plots if p.x_scale is AxisScale.LOG) < len(plots)

    def test_the_axis_filters_narrow_five_hundred_figures_to_a_handful(self, built):
        """The ticket's purpose, on the hand-checked example: an agent wanting
        phase noise at a 1 MHz offset picks the figure before spending a vision
        call. 514 figures in, a short list out, every one of them actually
        covering the question."""
        retriever = Retriever.for_part(built[0].part_dir)
        assert len(retriever.plots()) == 514
        hits = retriever.plots(y_label="Phase Noise", near_x="1MHz")
        assert 0 < len(hits) < 40, f"{len(hits)} hits is not a shortlist"
        for hit in hits:
            rec = hit.record
            assert "Phase Noise" in rec.y_label
            assert rec.x_unit == "Hz"
            assert rec.x_min <= 1e6 <= rec.x_max
        assert hits[0].matched_via == "axis-range"
        # A figure whose axis stops below 1 MHz is excluded rather than fudged.
        assert all(rec.figure_number != "4-1" for rec in (h.record for h in hits))

    def test_the_filter_reports_the_population_it_could_not_consider(self, built):
        gap = Retriever.for_part(built[0].part_dir).plot_axis_gap()
        assert "figures publish no readable x axis" in gap
        assert "cannot establish that no such figure exists" in gap


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
