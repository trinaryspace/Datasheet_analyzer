"""Deterministic spec query interface."""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.models import Footnote, SpecRecord, SpecSet, SpecUnit
from datasheet_analyzer.query import SpecQuery, format_answer


def _write_specset(path: Path, records: list[SpecRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    specset = SpecSet(
        schema_version="1",
        part_number="TEST",
        doc_hash="a" * 64,
        records=records,
        tables=[],
    )
    path.write_text(specset.model_dump_json(indent=2), encoding="utf-8")


@pytest.fixture
def query_dir(tmp_path: Path) -> Path:
    part = tmp_path / "TEST"
    rec_a = SpecRecord(
        section="4.5",
        table_index=0,
        row_index=0,
        symbol="DACRES",
        name="DAC resolution",
        typ="14",
        unit=SpecUnit(verbatim="bits", canonical="bits"),
        page=7,
    )
    rec_b = SpecRecord(
        section="4.5",
        table_index=0,
        row_index=1,
        symbol="ATTstep",
        name="DSA Attenuation step accuracy (DNL)",
        conditions="after calibration",
        typ="±0.1",
        unit=SpecUnit(verbatim="dB", canonical="dB"),
        page=7,
        cited_markers=["(2)"],
        footnotes=[Footnote(marker="(2)", text="After DSA calibration procedure")],
    )
    rec_c = SpecRecord(
        section="4.3",
        table_index=0,
        row_index=0,
        symbol="VDD1P2",
        name="1.2V supply",
        min="1.15",
        unit=SpecUnit(verbatim="V", canonical="V"),
        page=6,
    )
    _write_specset(part / "docs" / "doc-a-1111" / "specs.json", [rec_a, rec_b])
    _write_specset(part / "docs" / "doc-b-2222" / "specs.json", [rec_c])
    return part


def test_find_by_symbol(query_dir: Path):
    q = SpecQuery(query_dir)
    hits = q.find(symbol="DACRES")
    assert len(hits) == 1
    assert hits[0].symbol == "DACRES"


def test_find_by_name_case_insensitive(query_dir: Path):
    q = SpecQuery(query_dir)
    hits = q.find(name="STEP ACCURACY")
    assert len(hits) == 1
    assert hits[0].symbol == "ATTstep"


def test_find_and_semantics(query_dir: Path):
    q = SpecQuery(query_dir)
    assert len(q.find(symbol="ATTstep", section="4.5")) == 1
    assert len(q.find(symbol="ATTstep", section="4.3")) == 0


def test_find_empty_result(query_dir: Path):
    q = SpecQuery(query_dir)
    assert q.find(symbol="NOPE") == []


def test_format_answer_has_citation_and_footnote(query_dir: Path):
    q = SpecQuery(query_dir)
    rec = q.find(symbol="ATTstep")[0]
    text = format_answer([rec])
    assert "§4.5" in text
    assert "p.7" in text
    assert "After DSA calibration procedure" in text
    assert "[table 0 row 1]" in text
