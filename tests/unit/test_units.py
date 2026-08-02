"""Unit canonicalization and value-text normalization."""

from __future__ import annotations

import pytest

from datasheet_analyzer.structure.units import CANONICAL_UNITS, canonical_unit, normalize_text


@pytest.mark.parametrize("verbatim", ["Ω", "Ω", "ohm"])
def test_ohm_sign_canonicalizes(verbatim):
    u = canonical_unit(verbatim)
    assert u.verbatim == verbatim
    assert u.canonical == "ohm"


@pytest.mark.parametrize("unit", list(CANONICAL_UNITS.keys()))
def test_known_units_passthrough(unit):
    u = canonical_unit(unit)
    assert u.canonical == CANONICAL_UNITS[unit]


def test_unknown_unit_recorded_verbatim():
    unknown: set[str] = set()
    u = canonical_unit("dBmV", unknown=unknown)
    assert u.canonical == "dBmV"
    assert "dBmV" in unknown


def test_normalize_text_dash_space_only():
    assert normalize_text("  ±0.1  ") == "±0.1"
    assert normalize_text("1 – 2") == "1 - 2"
    assert normalize_text("1\n2") == "1 2"
