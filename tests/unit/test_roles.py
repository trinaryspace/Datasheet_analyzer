"""Header role detection and table classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.extract import get_backend
from datasheet_analyzer.extract.http import ReplayFetcher
from datasheet_analyzer.extract.pdf_structure import read_toc
from datasheet_analyzer.structure.roles import assign_roles, classify_table

RECORDED = Path(__file__).parent.parent / "fixtures" / "recorded_http"


def test_standard_parametric_headers():
    headers = ["PARAMETER", "PARAMETER", "TEST CONDITIONS", "MIN", "TYP", "MAX", "UNIT"]
    roles, unmapped = assign_roles(headers)
    assert roles == ["symbol", "name", "conditions", "min", "typ", "max", "unit"]
    assert unmapped == []


def test_nom_maps_to_typ():
    headers = ["", "", "MIN", "NOM", "MAX", "UNIT"]
    roles, unmapped = assign_roles(headers)
    assert roles == ["symbol", "name", "min", "typ", "max", "unit"]
    assert unmapped == []


def test_adi_conditions_variant_maps_to_conditions():
    # measured in AD9081/HMC520A: "Test Conditions/Comments" (no MIN/MAX cols)
    headers = ["Parameter", "Test Conditions/Comments", "Min", "Typ", "Max", "Unit"]
    roles, unmapped = assign_roles(headers)
    assert roles == ["symbol", "conditions", "min", "typ", "max", "unit"]
    assert unmapped == []
    # footnote-suffixed variants stay mapped too
    roles, _ = assign_roles(["", "", "TEST CONDITIONS/COMMENTS(1)", "MIN", "MAX", "UNIT"])
    assert roles == ["symbol", "name", "conditions", "min", "max", "unit"]


def test_value_and_thermal_metric_roles():
    esd_roles, _ = assign_roles(["", "", "", "VALUE", "UNIT"])
    assert esd_roles == ["symbol", "name", "conditions", "value", "unit"]
    thermal_roles, _ = assign_roles(
        ["THERMAL METRIC(1)", "THERMAL METRIC(1)", "AFE7950 ABJ or ALK", "UNIT"]
    )
    assert thermal_roles == ["symbol", "name", "value", "unit"]


def test_info_table_classification():
    headers = ["PART NUMBER", "PACKAGE(1)", "PACKAGE SIZE(2)"]
    roles, unmapped = assign_roles(headers)
    assert classify_table(headers, roles) == "info"
    assert unmapped == []


def test_unmapped_headers_recorded_not_forced():
    headers = ["PARAMETER", "FROBNICATOR", "UNIT"]
    roles, unmapped = assign_roles(headers)
    assert roles == ["symbol", "other", "unit"]
    assert unmapped == ["FROBNICATOR"]


@pytest.mark.integration
def test_all_real_tables_classify(afe7950_pdf):
    if not RECORDED.is_dir():
        pytest.skip("recorded HTTP fixtures not present")
    if not afe7950_pdf.exists():
        pytest.skip("afe7950.pdf not present")

    backend = get_backend("ti_html")
    backend.fetcher = ReplayFetcher(RECORDED)
    pdf_toc = read_toc(afe7950_pdf)
    from datasheet_analyzer.acquire.inventory import register_source

    source = register_source(afe7950_pdf, part_number="AFE7950")
    raw = backend.extract(source, pdf_toc=pdf_toc)

    parametric_sections = {
        "4.1",
        "4.2",
        "4.3",
        "4.4",
        "4.5",
        "4.6",
        "4.7",
        "4.8",
        "4.9",
        "4.10",
        "4.11",
    }
    seen_parametric: set[str] = set()
    all_unmapped: list[tuple[str, int, list[str]]] = []
    for sec in raw.sections:
        for i, table in enumerate(sec.tables):
            roles, unmapped = assign_roles(table.headers)
            kind = classify_table(table.headers, roles)
            if unmapped:
                all_unmapped.append((sec.number, i, unmapped))
            if sec.number in parametric_sections:
                assert kind == "parametric", (
                    f"section {sec.number} table {i} expected parametric, got {kind}"
                )
                seen_parametric.add(sec.number)
            if sec.number == "3":
                assert kind == "info", f"section 3 expected info, got {kind}"

    assert seen_parametric == parametric_sections
    assert all_unmapped == [], f"unmapped headers found: {all_unmapped}"
