"""Phase 6 gate — pins over every built part (ticket 04).

The acceptance gate, run against real corpora rather than fixtures: pin tables
either extract or are **honestly rejected with a recorded reason**, multi-pin
rows expand into individually citable records, the package cross-check runs on
every part, and a hand-checked golden set (pin -> name, name -> pins, count by
type) verifies at 100% **with the cited page checked against the printed PDF**.

This is the one place invariant 4 is relaxed, exactly as far as the phase plan
allows: it reads built parts under `parts/`, their extraction cache and their
source PDFs, and it skips whenever any of those is absent. It never reaches the
network, never calls a model, and never rebuilds anything — the cached
`RawDocument` is the same object a build would hand `derive/pins.py`.

Reading the cache rather than re-extracting is deliberate: re-running
`pdf_layout` over eleven datasheets would take minutes and would test the
layout engine, which has its own gate (`test_phase4_layout_gate.py`). What is
under test here is what `derive/pins.py` makes of what the layout engine
already produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer.derive.pins import (
    PartPins,
    build_pins,
    find_pins,
    load_pinset,
    type_counts,
    write_pinset,
)
from datasheet_analyzer.derive.provenance import PINS_ARTIFACT, resolve_source
from datasheet_analyzer.models import RawDocument, SourceDocument
from datasheet_analyzer.publish import read_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
PARTS_DIR = REPO_ROOT / "parts"
EXTRACT_CACHE = REPO_ROOT / ".cache" / "extract"


@dataclass(frozen=True)
class Built:
    """One built part, read back off disk without rebuilding it."""

    part: str
    docs: tuple[tuple[SourceDocument, RawDocument], ...]

    def pin_builds(self):
        for source, raw in self.docs:
            yield source, raw, build_pins(raw, self.part)


def _cached_raw(content_hash: str, backend: str) -> RawDocument | None:
    path = EXTRACT_CACHE / f"{content_hash}__{backend}.json"
    if not path.is_file():
        return None
    try:
        return RawDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _built_parts() -> list[Built]:
    """Every part under `parts/` whose documents are still in the cache."""
    if not PARTS_DIR.is_dir() or not EXTRACT_CACHE.is_dir():
        return []
    built: list[Built] = []
    for part_dir in sorted(p for p in PARTS_DIR.iterdir() if p.is_dir()):
        manifest = read_manifest(part_dir)
        if manifest is None:
            continue
        docs: list[tuple[SourceDocument, RawDocument]] = []
        for source in manifest.documents:
            stats = manifest.extraction_stats.get(source.content_hash)
            raw = _cached_raw(source.content_hash, stats.backend if stats else "")
            if raw is not None:
                docs.append((source, raw))
        if docs:
            built.append(Built(part=part_dir.name, docs=tuple(docs)))
    return built


@pytest.fixture(scope="module")
def corpus() -> list[Built]:
    parts = _built_parts()
    if not parts:
        pytest.skip("no built parts with cached extractions under parts/ + .cache/extract")
    return parts


def _find(corpus: list[Built], part: str) -> Built:
    for built in corpus:
        if built.part == part:
            return built
    pytest.skip(f"{part} is not built in this working tree")


def _pins_of(corpus: list[Built], part: str):
    """`(source, PinSet)` for the one document of `part` that has a pin table."""
    for source, _raw, build in _find(corpus, part).pin_builds():
        if build.pinset is not None:
            return source, build
    pytest.skip(f"{part} publishes no pin table in this working tree")


class TestEveryPartIsHonest:
    def test_a_part_either_extracts_a_pin_table_or_is_rejected_with_a_reason(self, corpus):
        """No part ships a partial pin table, and no rejection is silent.

        The two acceptable outcomes are "records" and "nothing, and here is
        why". The third — a `pins.json` with some of the rows — is the one
        this phase exists to make impossible, because a missing pin reads as
        "this pin does not exist" during schematic capture.
        """
        report: list[str] = []
        for built in corpus:
            for source, _raw, build in built.pin_builds():
                doc = Path(source.path).name
                if build.pinset is not None:
                    assert build.pinset.pins, f"{built.part}/{doc}: empty pin set published"
                    assert all(p.pin.strip() for p in build.pinset.pins)
                    report.append(f"{built.part}/{doc}: {build.n_pins} pins")
                else:
                    for reason in build.rejection_reasons:
                        assert reason.strip(), f"{built.part}/{doc}: blank rejection reason"
                    why = "; ".join(build.rejection_reasons) or "no candidate pin table"
                    report.append(f"{built.part}/{doc}: none — {why}")
        assert report, "no documents were read"
        print("\n".join(report))

    def test_a_rejected_pin_table_names_the_table_and_the_failure(self, corpus):
        """HMC520A's pin table is rejected whole — and says what failed.

        Its exposed-pad row is misread by the layout engine into a duplicate
        designator, which is exactly the case the device-table layer refuses.
        Losing 24 real pins to that refusal is the cost of not publishing a
        wrong one; the reason is recorded so the cost is visible rather than
        silent.
        """
        built = _find(corpus, "HMC520A")
        reasons = [r for _s, _raw, b in built.pin_builds() for r in b.rejection_reasons]
        if not reasons:
            pytest.skip("HMC520A's pin table is no longer rejected in this working tree")
        assert any("pin table" in r for r in reasons)
        assert any("duplicate key" in r for r in reasons)

    def test_afe7950_prints_no_pin_table_at_all(self, corpus):
        """The phase plan's `dsa pins --type power` on AFE7950, answered honestly.

        The AFE7950 datasheet in this corpus has no pin-configuration section
        — section 4 (Specifications) is followed by section 5 (Revision
        History) — so there is no printed pin table to read and no supply pin
        set to hand back. That is an absence in the document, not a parse
        failure, and the honest artifact is no `pins.json` at all. Recorded in
        `KNOWN_SHORTCOMINGS.md`.
        """
        built = _find(corpus, "AFE7950")
        for _source, raw, build in built.pin_builds():
            assert build.pinset is None
            titles = " ".join(s.title.lower() for s in raw.sections)
            assert "pin configuration" not in titles


class TestExpansionIsCitable:
    def test_multi_pin_rows_expand_into_individually_resolvable_records(self, corpus, tmp_path):
        """AD9081 prints `A2, E2, H2, L2, P2, V2` on one row: six records.

        Each carries its own stable id and its own citation, and every one of
        them resolves back through `derive/provenance.resolve_source` to the
        record and printed page it names — the check a design card will make
        against `pins.json` when it cites a supply pin.
        """
        source, build = _pins_of(corpus, "AD9081")
        pins = build.pinset.pins
        expanded = [p for p in pins if p.expanded_from]
        assert expanded, "AD9081 prints multi-pin rows; none expanded"

        avdd2 = [p for p in pins if p.name == "AVDD2"]
        assert [p.pin for p in avdd2] == ["A2", "E2", "H2", "L2", "P2", "V2"]
        assert {p.expanded_from for p in avdd2} == {"A2, E2, H2, L2, P2, V2"}
        assert {p.row_index for p in avdd2} == {avdd2[0].row_index}
        assert len({p.id for p in pins}) == len(pins), "pin ids are not unique"

        doc_dir = tmp_path / "docs" / "datasheet-ad9081"
        write_pinset(doc_dir, build.pinset)
        reloaded = load_pinset(doc_dir)
        assert len(reloaded.pins) == len(pins)
        for pin in avdd2:
            resolved = resolve_source(f"{PINS_ARTIFACT}#{pin.id}", roots=doc_dir)
            assert resolved is not None, pin.id
            assert resolved.record["pin"] == pin.pin
            assert resolved.record["name"] == "AVDD2"
            assert resolved.page == pin.page
        assert Path(source.path).exists()


class TestPackageCrossCheck:
    def test_the_cross_check_runs_on_every_part_that_has_pins(self, corpus):
        """Every pin set carries the check's verdict, including "nothing printed"."""
        seen = 0
        for built in corpus:
            for _source, _raw, build in built.pin_builds():
                if build.pinset is None:
                    continue
                seen += 1
                # The verdict is always recorded: a count, or an honest null.
                assert build.pinset.declared_pin_count == build.declared.count
                if build.declared.count is None:
                    assert not build.declared.ambiguous or build.warnings
        assert seen, "no part published a pin set"

    def test_real_mismatches_are_reported_as_warnings_naming_both_numbers(self, corpus):
        """Two genuine mismatches in the corpus, neither of them fatal.

        AD9081: a 324-ball package whose printed pin table yields 210 records
        (the table groups balls into rows this tool expands, and the layout
        engine loses some cell content to page wrapping).
        LMX1204: a 40-pin package whose table also prints the exposed pad,
        which is a pin a designer must connect but not one the package count
        includes.
        """
        _source, ad = _pins_of(corpus, "AD9081")
        assert ad.declared.count == 324
        assert len(ad.pinset.pins) != 324
        assert len(ad.warnings) == 1
        assert "324" in ad.warnings[0] and str(len(ad.pinset.pins)) in ad.warnings[0]

        _source, lmx = _pins_of(corpus, "LMX1204")
        assert lmx.declared.count == 40
        assert len(lmx.pinset.pins) == 41
        assert len(lmx.warnings) == 1
        assert "40" in lmx.warnings[0] and "41" in lmx.warnings[0]
        assert "DAP" in lmx.warnings[0]


#: The AD9081 supply rails, hand-checked against Table 21 of the datasheet
#: (`Pin Function Descriptions`, p.22-28): rail name -> how many balls carry
#: it. This is what `dsa pins --part AD9081 --type power` hands back, and it is
#: the phase plan's "plausible, hand-checked supply pin set" — moved to AD9081
#: because the AFE7950 datasheet in this corpus prints no pin table at all
#: (see `TestEveryPartIsHonest` and `KNOWN_SHORTCOMINGS.md`).
AD9081_RAILS: dict[str, int] = {
    "AVDD1": 10,
    "AVDD1_ADC": 4,
    "AVDD2": 6,
    "AVDD2_PLL": 1,
    "BVDD2": 4,
    "BVDD3": 2,
    "BVNN2": 2,
    "CLKVDD1": 2,
    "DAVDD1": 4,
    "DCLKVDD1": 1,
    "DVDD1": 10,
    "DVDD1P8": 3,
    "DVDD1_RT": 2,
    "FVDD1": 2,
    # The negative-voltage-generator *output*, labelled from its printed
    # description ("... supply ..."), not from a rail word in its name. The
    # one judgement call in this set, and `type_evidence` says so on the
    # record: `description:supply`.
    "NVG1_OUT": 2,
    "PLLCLKVDD1": 1,
    "RVDD2": 2,
    "SVDD1": 10,
    "SVDD1_PLL": 2,
    "SVDD2_PLL": 1,
    "VDD1_NVG": 2,
    "VNN1": 6,
}


class TestSupplyPinSet:
    def test_type_power_on_ad9081_is_the_hand_checked_rail_set(self, corpus):
        """`dsa pins --type power`, checked rail by rail against the printed table."""
        _source, build = _pins_of(corpus, "AD9081")
        part_pins = PartPins(part="AD9081", sets=(("datasheet", build.pinset),))
        hits = find_pins(part_pins, pin_type="power")

        counted: dict[str, int] = {}
        for hit in hits:
            counted[hit.record.name] = counted.get(hit.record.name, 0) + 1
        assert counted == AD9081_RAILS
        assert len(hits) == sum(AD9081_RAILS.values()) == 79
        # Every one of them cites a printed page and names its lexicon entry.
        assert all(h.record.page for h in hits)
        assert all(h.record.type_evidence for h in hits)


#: Hand-checked pin questions, one set per part that prints a pin table.
#: Each answer was read off the printed page named beside it; the test checks
#: both that the corpus answers it and that the page it cites really carries
#: the answer, so a right answer with a wrong citation still fails.
GOLDEN: dict[str, dict] = {
    "AD9081": {
        "pin_to_name": [("A2", "AVDD2", 22), ("J5", "PLLCLKVDD1", 22)],
        "name_to_pins": [("AVDD2", ["A2", "E2", "H2", "L2", "P2", "V2"], 22)],
        "type_counts": [("AVDD2", {"power": 6}), ("PLLCLKVDD1", {"power": 1})],
    },
    "LMX1204": {
        "pin_to_name": [("4", "VCC_CLKIN", 4), ("14", "CLKOUT0_P", 4)],
        "name_to_pins": [("GND", ["5", "13", "17", "26", "34", "38"], 4)],
        "type_counts": [("GND", {"ground": 6}), ("VCC_CLKIN", {"power": 1})],
    },
}


class TestGoldenPinQuestions:
    """pin -> name, name -> pins, count by type — 100%, with page cites."""

    @pytest.mark.parametrize("part", sorted(GOLDEN))
    def test_golden_set_verifies_at_100_percent(self, corpus, part):
        source, build = _pins_of(corpus, part)
        pdf_path = Path(source.path)
        if not pdf_path.is_file():
            pytest.skip(f"{pdf_path.name} is not present at the path the corpus recorded")
        part_pins = PartPins(part=part, sets=(("datasheet", build.pinset),))
        pdf = fitz.open(str(pdf_path))
        try:
            page_text = [pdf[i].get_text() for i in range(pdf.page_count)]
        finally:
            pdf.close()
        golden = GOLDEN[part]
        failures: list[str] = []

        for pin, name, page in golden["pin_to_name"]:
            hits = [h for h in find_pins(part_pins, q=pin) if h.record.pin == pin]
            if len(hits) != 1 or hits[0].record.name != name:
                failures.append(f"pin {pin} -> {[h.record.name for h in hits]} (want {name})")
                continue
            record = hits[0].record
            if record.page != page:
                failures.append(f"pin {pin} cites p.{record.page} (want p.{page})")
                continue
            failures.extend(_page_misses(page_text, record.page, name, pin))

        for name, pins, page in golden["name_to_pins"]:
            hits = [h for h in find_pins(part_pins, q=name) if h.record.name == name]
            found = [h.record.pin for h in hits]
            if found != pins:
                failures.append(f"name {name} -> {found} (want {pins})")
                continue
            for hit in hits:
                if hit.record.page != page:
                    failures.append(f"{name}/{hit.record.pin} cites p.{hit.record.page}")
                    continue
                failures.extend(_page_misses(page_text, hit.record.page, name, hit.record.pin))

        for name, counts in golden["type_counts"]:
            records = [h.record for h in find_pins(part_pins, q=name) if h.record.name == name]
            got = type_counts(records)
            if got != counts:
                failures.append(f"count by type for {name}: {got} (want {counts})")

        total = (
            len(golden["pin_to_name"]) + len(golden["name_to_pins"]) + len(golden["type_counts"])
        )
        assert not failures, (
            f"{part}: {len(failures)} of {total} golden pin questions failed\n  - "
            + "\n  - ".join(failures)
        )


def _page_misses(page_text: list[str], page: int | None, name: str, pin: str) -> list[str]:
    """Whether the cited page really prints the answer. Empty is a pass.

    A one-character designator ("4") is not checked against the page: it
    appears in every page number and margin note, so finding it would prove
    nothing. The pin *name* is checked always — it is the string a reader
    would search the page for.
    """
    if page is None or not 1 <= page <= len(page_text):
        return [f"{pin}/{name}: page {page} is outside the document"]
    text = page_text[page - 1]
    misses = [] if name in text else [f"p.{page} does not print {name!r}"]
    if len(pin) >= 2 and pin not in text:
        misses.append(f"p.{page} does not print designator {pin!r}")
    return misses
