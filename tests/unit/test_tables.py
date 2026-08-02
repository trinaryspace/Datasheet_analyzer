"""Pain point: merged cells / dense parametric grids must survive extraction.

If rowspan/colspan expansion is wrong, an agent reading row N gets a value
with the wrong parameter, unit, or conditions — silently wrong hardware
decisions. These tests pin the expansion behavior hard.
"""

from __future__ import annotations

from datasheet_analyzer.structure.tables import (
    cell_text,
    cited_markers,
    html_table_to_block,
)

# --- synthetic tables -------------------------------------------------------

SIMPLE = """
<table><thead><tr><th>PARAMETER</th><th>MIN</th><th>MAX</th><th>UNIT</th></tr></thead>
<tbody>
<tr><td>VDD</td><td>1.15</td><td>1.25</td><td>V</td></tr>
<tr><td>IDD</td><td>10</td><td>40</td><td>mA</td></tr>
</tbody></table>
"""

# TI 4.5-style: 'PARAMETER' colspan=2 header; parameter symbol+name+unit
# rowspan over many condition rows; sup footnote refs in values.
TI_STYLE = """
<table>
<thead><tr>
  <th colspan="2">PARAMETER</th><th>TEST CONDITIONS</th>
  <th>MIN</th><th>TYP</th><th>MAX</th><th>UNIT</th>
</tr></thead>
<tbody>
<tr><td rowspan="2"><i>f</i><sub>RFout</sub></td>
    <td rowspan="2">RF output frequency range</td>
    <td>fDAC = 12 GSPS, 1<sup class="ph sup">st</sup> Nyquist</td>
    <td>600</td><td></td><td>6000</td><td rowspan="2">MHz</td></tr>
<tr><td>fDAC = 12 GSPS, 2<sup class="ph sup">nd</sup> Nyquist</td>
    <td>6000</td><td></td><td>12000</td></tr>
<tr><td rowspan="2">ATT<sub>step-acc</sub></td>
    <td rowspan="2">DSA step accuracy (DNL)</td>
    <td>before calibration</td><td></td><td>±0.2</td><td></td>
    <td rowspan="2">dB</td></tr>
<tr><td>after calibration<sup>(2)</sup></td><td></td><td>±0.1</td><td></td></tr>
</tbody></table>
"""

MULTIROW_THEAD = """
<table><thead>
<tr><th rowspan="2">PARAM</th><th colspan="2">GROUP</th></tr>
<tr><th>MIN</th><th>MAX</th></tr>
</thead><tbody>
<tr><td>X</td><td>1</td><td>2</td></tr>
</tbody></table>
"""

MALFORMED_SHORT_ROWS = """
<table><tbody>
<tr><td rowspan="3">A</td><td>1</td><td rowspan="2">C1</td></tr>
<tr><td>2</td></tr>
<tr></tr>
<tr><td>B</td><td>3</td><td>C2</td></tr>
</tbody></table>
"""

SPACER_ROWS = """
<table><tbody>
<tr><td>A</td><td>1</td></tr>
<tr><td colspan="2"> </td></tr>
<tr><td>B</td><td>2</td></tr>
</tbody></table>
"""

UNICODE_TABLE = """
<table><tbody>
<tr><td>R<sub>θJA</sub></td><td>16.2</td><td>°C/W</td></tr>
<tr><td>Z<sub>in</sub></td><td>100</td><td>Ω</td></tr>
<tr><td>I<sub>IH</sub></td><td>–250 … 250</td><td>µA</td></tr>
<tr><td>T<sub>A</sub></td><td>±0.1</td><td>dB</td></tr>
</tbody></table>
"""


# --- tests ------------------------------------------------------------------


def test_simple_table_grid_and_headers():
    t = html_table_to_block(SIMPLE)
    assert t.headers == ["PARAMETER", "MIN", "MAX", "UNIT"]
    assert t.grid == [["VDD", "1.15", "1.25", "V"], ["IDD", "10", "40", "mA"]]
    assert t.n_rows == 2 and t.n_cols == 4


def test_colspan_header_expands_to_all_spanned_columns():
    t = html_table_to_block(TI_STYLE)
    # colspan=2 'PARAMETER' covers symbol + description columns
    assert t.headers == ["PARAMETER", "PARAMETER", "TEST CONDITIONS", "MIN", "TYP", "MAX", "UNIT"]


def test_csv_disambiguates_duplicate_headers():
    t = html_table_to_block(TI_STYLE)
    first_line = t.csv.splitlines()[0]
    assert first_line.split(",")[:2] == ["PARAMETER", "PARAMETER_2"]


def test_rowspan_values_reach_every_spanned_row():
    t = html_table_to_block(TI_STYLE)
    # both Nyquist rows must carry the parameter symbol, name and unit
    assert t.grid[0][0] == "fRFout" and t.grid[1][0] == "fRFout"
    assert t.grid[0][1] == "RF output frequency range" == t.grid[1][1]
    assert t.grid[0][6] == "MHz" == t.grid[1][6]
    # ...while the per-row conditions stay distinct
    assert t.grid[0][2] != t.grid[1][2]
    # second parameter block: before/after calibration rows
    assert t.grid[2][0] == "ATTstep-acc" == t.grid[3][0]
    assert "before calibration" in t.grid[2][2]
    assert "after calibration" in t.grid[3][2]
    assert t.grid[3][4] == "±0.1"


def test_sub_sup_joined_to_base_text():
    assert cell_text(_frag("<td><i>f</i><sub>RFout</sub></td>")) == "fRFout"
    assert cell_text(_frag("<td>1<sup>st</sup> Nyquist</td>")) == "1st Nyquist"
    # footnote refs stay glued to their value — the association we must keep
    assert cell_text(_frag("<td>±0.1<sup>(2)</sup></td>")) == "±0.1(2)"


def _frag(html: str):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "lxml").find("td")


def test_multirow_thead_flattens_per_column():
    t = html_table_to_block(MULTIROW_THEAD)
    assert t.headers == ["PARAM", "GROUP MIN", "GROUP MAX"]
    assert t.grid == [["X", "1", "2"]]


def test_malformed_rows_still_consume_rowspans_and_get_padded():
    t = html_table_to_block(MALFORMED_SHORT_ROWS)
    # rowspan=3 over 'A' must fill rows 0..2 even though row 2 has no cells
    assert t.grid[0][0] == "A"
    assert t.grid[1][0] == "A"
    assert t.grid[2][0] == "A"
    # all rows padded to equal width
    assert len({len(r) for r in t.grid}) == 1
    # and the span on C1 (rowspan=2) reached row 1
    assert t.grid[1][2] == "C1"


def test_spacer_rows_dropped():
    t = html_table_to_block(SPACER_ROWS)
    assert t.grid == [["A", "1"], ["B", "2"]]


def test_unicode_units_survive_end_to_end():
    t = html_table_to_block(UNICODE_TABLE)
    flat = "\n".join(" ".join(r) for r in t.grid)
    for needle in ["θ", "°C/W", "Ω", "µA", "±", "–"]:
        assert needle in flat
    assert "°C/W" in t.csv and "Ω" in t.markdown


def test_markdown_escapes_pipes():
    t = html_table_to_block(
        "<table><tbody><tr><td>a|b</td><td>1</td></tr></tbody></table>"
    )
    assert "a\\|b" in t.markdown


def test_cited_markers_come_from_sup_only():
    # "(0.5)" as plain text is a value, not a footnote ref; <sup>(2)</sup> is.
    t = cited_markers(TI_STYLE)
    assert t == {"(2)"}


def test_conditions_and_page_are_carried():
    t = html_table_to_block(SIMPLE, conditions="Typical values at TA = +25°C", page=7)
    assert t.conditions == "Typical values at TA = +25°C"
    assert t.page == 7
    # conditions appear in the markdown-ready state via the block, not lost
    assert "25°C" in t.conditions
