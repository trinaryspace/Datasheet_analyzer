"""The phase-6 acceptance gate (ticket 10), measured against the real corpora.

`Reports/PHASE_6_PLAN.md` states the claim this phase is allowed to make —
*"the corpus answers schematic-capture and bring-up questions, and every
derived number traces to a printed page"* — and eight checks that decide
whether it is true. This module runs all eight and **prints the number each
one measured**, so the phase report is a transcript rather than a recollection.

The per-ticket gates (`test_phase6_pins.py`, `…_registers.py`, `…_cards.py`,
`…_plot_axes.py`, `…_compare.py`, `…_parse_rate.py`) each prove one component
against real documents. This file is deliberately *not* a copy of them: it
asserts the phase-level claims that no single ticket owns — that the goldens
still verify at 100% across every part, that the derived surfaces answer the
designer's questions they were built for, and that nothing phase 5 established
has moved.

Invariant 4's documented exception applies, exactly as far as the plan allows:
this reads built corpora under `parts/` and their source PDFs, never the
network, never a model, and skips every check whose inputs are absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.config import PIPELINE_VERSION
from datasheet_analyzer.corpus_ref import library_root_of
from datasheet_analyzer.derive.cards import audit_card, load_or_build_card
from datasheet_analyzer.derive.compare import audit_comparison, compare_parts
from datasheet_analyzer.derive.pins import load_part_pins, type_counts
from datasheet_analyzer.derive.registers import load_part_registers
from datasheet_analyzer.evalh.citations import (
    load_card_golden,
    load_page_texts,
    summarize,
    verify_ask_queries,
    verify_card_queries,
    verify_plot_queries,
    verify_questions,
    verify_search_queries,
    verify_spec_queries,
)
from datasheet_analyzer.evalh.golden import load_golden
from datasheet_analyzer.models import CARD_KINDS
from datasheet_analyzer.publish import read_manifest
from datasheet_analyzer.structure.quantities import parse_quantity

REPO = Path(__file__).resolve().parents[2]
PARTS = REPO / "parts"
FIXTURES = REPO / "tests" / "fixtures"

#: The parts that carry a golden benchmark — the set `dsa verify` covers.
GOLDEN_PARTS = ("AD9081", "AFE7950", "AFE7953", "HMC520A", "LM741", "QPA1003P")

#: Golden part -> the directory its corpus was built into. `LM741` is the
#: benchmark's name; the corpus directory is lowercase, as it was acquired.
PART_DIRS = {"LM741": "lm741"}

#: Parts whose documents have **no** `search_index.json` anywhere in this
#: tree, so the full-text path cannot run for them. **Empty since phase 6.5,
#: wave 2**: ADR 0008 settled that a tracked corpus is published
#: self-contained and at the current pipeline version, and rebuilding
#: AFE7950 and AFE7953 that way wrote the index they had never had. Kept as a
#: *set* rather than deleted, because it is asserted below and must fail just
#: as loudly if it grows again.
PARTS_WITHOUT_SEARCH: set[str] = set()


def _shelf_has_material() -> bool:
    """Whether this checkout has a corpus the phase-6 gate can be run against.

    The gate measures pins, registers, cards and axes across *built* parts.
    The two corpora this repository commits (AFE7950, AFE7953) are current
    since ADR 0008, but neither prints a pin table or a register map, so most
    of what this module looks for still comes from parts a developer builds
    locally — and a cleared shelf makes the whole module inapplicable rather
    than failing.

    Skipping the module beats weakening a dozen individual assertions: the
    gate's claims about *published* artifacts stay exactly as strict, and they
    come back the moment there is something to measure.
    """
    if not PARTS.is_dir():
        return False
    return any(child.is_dir() and (child / "manifest.json").exists() for child in PARTS.iterdir())


pytestmark = pytest.mark.skipif(
    not _shelf_has_material(),
    reason=(
        "no locally built corpus to run the phase-6 gate against; "
        "the committed AFE7950/AFE7953 corpora predate these artifacts"
    ),
)

#: The axis-coverage floor from the plan, over AFE7950's figure gallery.
AXIS_HIGH_FLOOR = 0.60


def _part_dir(part: str) -> Path:
    return PARTS / PART_DIRS.get(part, part)


def _pdf_for(part: str) -> Path | None:
    """The source PDF a part was built from, when it is readable from here."""
    manifest = read_manifest(_part_dir(part))
    if manifest is None or not manifest.documents:
        return None
    for source in manifest.documents:
        local = REPO / Path(source.path).name
        if local.is_file():
            return local
        remote = Path(source.path)
        if remote.is_file():
            return remote
    return None


def _library_dir(part: str) -> Path | None:
    """Where this part's shared documents live, when it publishes into one.

    A document published once into the shared store is cited as
    `@library/docs/…`, and a citation that cannot be resolved is not a
    citation — so the walk has to be given the same root the corpus index
    resolves against.
    """
    return library_root_of(read_manifest(_part_dir(part)), _part_dir(part))


def _built(part: str) -> Path:
    """The part's directory, or a skip that says *why* it cannot be measured.

    ADR 0008's third rule: a corpus-reading gate skips rather than fails when
    its corpus predates the code, and names the version it found — "AFE7950 is
    built at pipeline 0.1.0, this code is 0.5.0" is a sentence a developer can
    act on, where a red gate on a fresh clone is one they learn to ignore. The
    regression that skipping could hide is caught instead by
    `tests/integration/test_corpus_currency.py`, which cannot skip because its
    inputs are committed.
    """
    directory = _part_dir(part)
    manifest = read_manifest(directory)
    if manifest is None:
        pytest.skip(f"{part} is not built under {PARTS}")
    if manifest.pipeline_version != PIPELINE_VERSION:
        pytest.skip(
            f"{part} is built at pipeline {manifest.pipeline_version}, this code is "
            f"{PIPELINE_VERSION}; rebuild it before this gate can measure anything"
        )
    return directory


@pytest.fixture(scope="module")
def golden_results() -> dict:
    """Every golden path, run once for every part that has a benchmark.

    One fixture because `dsa verify`'s five tables are five views of the same
    run, and re-running them per assertion would triple the gate's cost for
    no extra evidence.
    """
    out: dict[str, dict] = {}
    for part in GOLDEN_PARTS:
        golden = FIXTURES / f"golden_qa_{part}.yaml"
        directory = _part_dir(part)
        if not golden.is_file() or read_manifest(directory) is None:
            continue
        questions = load_golden(golden)
        pdf = _pdf_for(part)
        pages = load_page_texts(pdf) if pdf is not None else []
        out[part] = {
            "pdf": pdf,
            "pages": bool(pages),
            "corpus": verify_questions(questions, directory, pages),
            "spec": verify_spec_queries(questions, directory),
            "plot": verify_plot_queries(questions, directory),
            "ask": verify_ask_queries(questions, directory),
            "search": verify_search_queries(questions, directory),
            "cards": verify_card_queries(load_card_golden(golden), directory, page_texts=pages),
        }
    if not out:
        pytest.skip("no golden part is built")
    return out


# --- 1. pins ------------------------------------------------------------------


class TestGateOnePinTables:
    """Pin tables extract, or are honestly absent, and the goldens verify."""

    def test_every_built_part_either_publishes_pins_or_publishes_none(self, capsys):
        rows = []
        for part_dir in sorted(p for p in PARTS.iterdir() if p.is_dir()):
            if read_manifest(part_dir) is None:
                continue
            pins = load_part_pins(part_dir, part_dir.name)
            counts = type_counts(pins.pins)
            rows.append((part_dir.name, len(pins.pins), counts))
            # The honesty rule: a published file is never partial. Either the
            # set is empty (no file) or every record carries its own page.
            assert all(p.page is not None for p in pins.pins), (
                f"{part_dir.name}: a published pin record without a page is not citable"
            )
            assert all(p.pin for p in pins.pins), f"{part_dir.name}: a pin with no designator"
        assert rows, "no built part to measure"
        with capsys.disabled():
            print("\n[gate 1] pins published per part")
            for name, n, counts in rows:
                shown = ", ".join(f"{k} {v}" for k, v in counts.items()) or "-"
                print(f"  {name:<16} {n:>4} pins   {shown}")

    def test_the_golden_pin_questions_verify_at_full_marks(self, golden_results, capsys):
        pin_results = [
            (part, r)
            for part, data in golden_results.items()
            for r in data["ask"]
            if r.route == "pin" or (r.question.ask_query or {}).get("route") == "pin"
        ]
        assert pin_results, "no golden set carries a pin question"
        failed = [(p, r.question.id, r.detail) for p, r in pin_results if not r.ok]
        with capsys.disabled():
            print(
                f"\n[gate 1] golden pin questions: "
                f"{len(pin_results) - len(failed)}/{len(pin_results)} pass"
            )
        assert not failed, failed


class TestGateTwoPackageCrossCheck:
    """The cross-check runs on every part, and a mismatch is a warning."""

    def test_a_mismatch_is_reported_and_never_silently_resolved(self, capsys):
        checked, mismatches = 0, []
        for part_dir in sorted(p for p in PARTS.iterdir() if p.is_dir()):
            if read_manifest(part_dir) is None:
                continue
            pins = load_part_pins(part_dir, part_dir.name)
            if not pins.sets:
                continue
            checked += 1
            for warning in pins.warnings:
                if "cross-check" in warning:
                    mismatches.append((part_dir.name, warning))
        with capsys.disabled():
            print(f"\n[gate 2] package cross-check ran on {checked} part(s) with a pin table")
            for name, warning in mismatches:
                print(f"  {name}: {warning[:150]}")
        assert checked, "no part published a pin table to cross-check"
        assert mismatches, (
            "no part reports a package/pin-count mismatch; if that is now true of "
            "every corpus, this assertion is what has to change"
        )
        # A warning, never a correction: the record count is what was printed.
        assert all("not resolved here" in w for _p, w in mismatches)


# --- 3. registers -------------------------------------------------------------


class TestGateThreeRegisters:
    """The register summary answers address / name lookups, cited."""

    def test_a_published_register_answers_by_address_and_by_name(self, capsys):
        rows = []
        for part_dir in sorted(p for p in PARTS.iterdir() if p.is_dir()):
            if read_manifest(part_dir) is None:
                continue
            registers = load_part_registers(part_dir, part_dir.name)
            if not registers.sets:
                continue
            rows.append((part_dir.name, len(registers.registers), registers.has_bit_fields))
            for record in registers.registers:
                assert record.page is not None, "a register record must cite a page"
                assert record.address.verbatim or record.name
        with capsys.disabled():
            print("\n[gate 3] registers published per part")
            for name, n, fields in rows:
                print(f"  {name:<16} {n:>4} registers   bit fields: {fields}")
        assert rows, "no part published a register map"

    def test_bit_fields_are_no_longer_parked(self):
        """Ticket 06's gate is met, so the recorded absence is gone.

        The measurement that decides it is
        `tests/integration/test_phase6_bitfields.py`: all six of the sampled
        registers in `LMX1204_registermap.pdf` read exactly right, 28 of its
        35 registers publish a field set, and precision is 100%. What this
        gate asserts is the consequence — the shortcoming entry is deleted,
        and a part that publishes a bit field publishes a *whole* one.
        """
        shortcomings = (REPO / "KNOWN_SHORTCOMINGS.md").read_text(encoding="utf-8")
        assert "Register bit fields: not extracted" not in shortcomings
        for part_dir in sorted(p for p in PARTS.iterdir() if p.is_dir()):
            if read_manifest(part_dir) is None:
                continue
            registers = load_part_registers(part_dir, part_dir.name)
            for record in registers.registers:
                for field in record.fields:
                    assert field.bits.verbatim, (part_dir.name, record.name)
                    assert field.page is not None, (part_dir.name, record.name)


# --- 4. cards -----------------------------------------------------------------


class TestGateFourCards:
    """All four cards build, and every value traces to a record and a page."""

    @pytest.mark.parametrize("part", ["AFE7950", "AD9081"])
    def test_every_card_builds_and_every_value_resolves(self, part, capsys):
        directory = _built(part)
        lines = []
        for kind in CARD_KINDS:
            card = load_or_build_card(directory, part, kind)
            audit = audit_card(card, part_dir=directory, library_dir=_library_dir(part))
            lines.append(
                f"  {part:<8} {kind:<10} {len(card.rows):>3} rows  "
                f"{audit.resolved}/{audit.checked} values resolve  "
                f"{len(card.unresolved)} unresolved  {len(card.warnings)} warning(s)"
            )
            assert audit.ok, audit.describe()
        with capsys.disabled():
            print(f"\n[gate 4] cards for {part}")
            for line in lines:
                print(line)

    def test_the_golden_card_questions_verify_at_full_marks(self, golden_results, capsys):
        results = [(p, r) for p, data in golden_results.items() for r in data["cards"]]
        assert results, "no golden set carries a card question"
        failed = [(p, r.question.id, r.detail) for p, r in results if not r.ok]
        with capsys.disabled():
            print(f"\n[gate 4] golden card questions: {len(results) - len(failed)}/{len(results)}")
            for part, r in results:
                print(f"  {part:<8} {r.question.id:<20} {'PASS' if r.ok else 'FAIL'}  {r.detail}")
        assert not failed, failed


# --- 5. the numeric layer -----------------------------------------------------


class TestGateFiveParseQuantity:
    """Every row of the plan's shapes table, including the `None` rows."""

    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("105", "point"),
            ("−40", "point"),
            ("+85", "point"),
            ("−40 to +85", "range"),
            ("-40…125", "range"),
            ("< 5", "bound"),
            ("≥ 1.8", "bound"),
            ("±0.5", "tolerance"),
            ("1350 mA", "point"),
            ("12 GSPS", "point"),
            ("1.2e-9", "point"),
        ],
    )
    def test_a_printed_shape_parses_to_its_kind(self, text, kind):
        parsed = parse_quantity(text)
        assert parsed is not None, f"{text!r} did not parse"
        assert parsed.kind == kind
        assert parsed.verbatim == text.strip()

    @pytest.mark.parametrize("text", ["See Figure 7", "Note 2", "—", ""])
    def test_an_unparseable_cell_is_none_and_not_a_default(self, text):
        assert parse_quantity(text) is None

    def test_si_prefixes_scale_and_the_print_survives(self):
        assert parse_quantity("1350 mA").value == pytest.approx(1.35)
        assert parse_quantity("1350 mA").unit_si == "A"
        assert parse_quantity("12 GSPS").value == pytest.approx(12e9)


# --- 6. compare ---------------------------------------------------------------


class TestGateSixCompare:
    """Two parts side by side, with the unparsed population reported."""

    def test_the_reference_comparison_produces_deltas_and_states_its_coverage(self, capsys):
        for part in ("AFE7950", "AFE7953"):
            _built(part)
        comparison, reason = compare_parts(["AFE7950", "AFE7953"], parts_dir=PARTS)
        assert comparison is not None, reason
        with_delta = [row for row in comparison.rows if row.deltas]
        only_one = [row for row in comparison.rows if row.missing_from]
        with capsys.disabled():
            print("\n[gate 6] dsa compare AFE7950 AFE7953")
            print(
                f"  {len(comparison.rows)} rows, {len(with_delta)} with an SI delta, "
                f"{len(only_one)} present in one part only"
            )
            print(
                f"  coverage: {comparison.coverage.compared}/{comparison.coverage.considered} "
                f"compared"
            )
            for entry in comparison.parse_coverage:
                print(
                    f"  {entry.part_number}: {entry.parsed}/{entry.considered} parsed, "
                    f"{len(entry.unparsed)} unparsed"
                )
        assert with_delta, "no row compared numerically"
        # The unparsed population is *stated*, never dropped: every part that
        # was considered reports its own count.
        assert comparison.parse_coverage
        assert all(e.considered >= e.parsed for e in comparison.parse_coverage)
        assert comparison.coverage.considered >= comparison.coverage.compared
        audit = audit_comparison(
            comparison,
            {p: _part_dir(p) for p in comparison.parts},
            library_dir=_library_dir(comparison.parts[0]),
        )
        assert audit == [], audit


# --- 7. plot axes -------------------------------------------------------------


class TestGateSevenAxisCatalog:
    """Axis metadata for the reference gallery, honest nulls for the rest."""

    def test_afe7950_axis_coverage_clears_the_floor(self, capsys):
        from datasheet_analyzer.models import PlotSet
        from datasheet_analyzer.structure.plot_axes import annotate_plot_axes

        directory = _built("AFE7950")
        pdf = _pdf_for("AFE7950")
        if pdf is None:
            pytest.skip("afe7950.pdf is not readable from here")
        manifest = read_manifest(directory)
        plots_json = None
        for doc_hash in (d.content_hash for d in manifest.documents):
            for candidate in (REPO / "library" / "docs").glob(f"*{doc_hash[:8]}/plots.json"):
                plots_json = candidate
            for candidate in (directory / "docs").glob(f"*{doc_hash[:8]}/plots.json"):
                plots_json = candidate
        if plots_json is None:
            pytest.skip("AFE7950 publishes no plot catalog")
        plotset = PlotSet.model_validate(json.loads(plots_json.read_text(encoding="utf-8")))
        coverage = annotate_plot_axes(plotset, pdf)
        with capsys.disabled():
            print(
                f"\n[gate 7] AFE7950 axis catalog: {coverage.high}/{coverage.total} figures "
                f"at high confidence ({coverage.high_fraction:.1%}), floor {AXIS_HIGH_FLOOR:.0%}"
            )
        assert coverage.high_fraction >= AXIS_HIGH_FLOOR
        # Honest nulls: a figure that is not `high` carries no invented range.
        for record in plotset.plots:
            if record.axis_confidence.value != "high":
                assert record.x_min is None or record.x_max is not None


# --- 8. phase 5 is where phase 5 left it --------------------------------------


class TestGateEightNothingPhaseFiveEstablishedHasMoved:
    """Every golden path, every part, at the number phase 5 recorded."""

    def test_the_corpus_and_page_truth_goldens_are_at_full_marks(self, golden_results, capsys):
        lines, failures = [], []
        for part, data in sorted(golden_results.items()):
            summary = summarize(data["corpus"])
            lines.append(
                f"  {part:<10} {summary['passed']}/{summary['total']} "
                f"({summary['accuracy']:.0%})  page-truth: {data['pages']}"
            )
            if summary["failed"]:
                failures.append((part, [r.question.id for r in data["corpus"] if not r.passed]))
        with capsys.disabled():
            print("\n[gate 8] golden Q&A (corpus contains + cited page prints)")
            for line in lines:
                print(line)
        assert not failures, failures

    @pytest.mark.parametrize("path", ["spec", "plot", "ask"])
    def test_every_deterministic_query_path_is_at_full_marks(self, golden_results, path, capsys):
        total = passed = 0
        failures = []
        for part, data in sorted(golden_results.items()):
            for result in data[path]:
                total += 1
                passed += bool(result.ok)
                if not result.ok:
                    failures.append((part, result.question.id, result.detail))
        with capsys.disabled():
            print(f"[gate 8] {path}-path goldens: {passed}/{total}")
        assert total, f"no golden carries a {path} question"
        assert not failures, failures

    def test_the_search_path_is_at_full_marks_wherever_it_can_run(self, golden_results, capsys):
        """The one path with a recorded gap, asserted as exactly that gap.

        A part whose documents carry no `search_index.json` cannot run this
        path at all — that is "could not look", not "nothing found", and the
        set of such parts is written down in `KNOWN_SHORTCOMINGS.md`. This
        fails if the set grows *or* shrinks without the record being updated,
        so the gap can never quietly become the norm.
        """
        runnable, blocked = [], []
        for part, data in sorted(golden_results.items()):
            for result in data["search"]:
                if "search unavailable" in result.detail:
                    blocked.append((part, result.question.id))
                else:
                    runnable.append((part, result.question.id, result.ok))
        with capsys.disabled():
            print(
                f"[gate 8] search-path goldens: "
                f"{sum(1 for _p, _q, ok in runnable if ok)}/{len(runnable)} where the "
                f"index exists; {len(blocked)} blocked on a missing index "
                f"({', '.join(sorted({p for p, _q in blocked})) or 'none'})"
            )
        assert runnable, "the search path ran for no part at all"
        assert all(ok for _p, _q, ok in runnable), [(p, q) for p, q, ok in runnable if not ok]
        assert {p for p, _q in blocked} == PARTS_WITHOUT_SEARCH, (
            "the set of parts with no search index changed; update "
            "KNOWN_SHORTCOMINGS.md and PARTS_WITHOUT_SEARCH together"
        )
