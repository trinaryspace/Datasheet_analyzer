"""`dsa plots` must reach the axis filters that already exist beneath it.

Phase 6.5, ticket 02. Phase 6 ticket 08 built the axis catalog and wired
`--x-label` / `--y-label` / `--near-x` into `query.find_plots` and the MCP
surface, but `cli.py` was frozen as that phase's shared contract, so the flags
were never added to the argument parser. The capability shipped unreachable
from a shell.

Nothing here tests *filtering* — `test_plot_axes.py` owns that. What is tested
is reachability and faithful pass-through: the flags exist, they reach the
retriever unchanged, they work in both scopes, and a machine reader can see
which of them narrowed the result.
"""

from __future__ import annotations

import json

import pytest
from mcp_corpus import built_settings

from datasheet_analyzer import cli

#: `mcp_corpus` gives each part two figures: `4.12.1-f001` carries a read
#: axis catalog (x "Output Frequency" 600–1500 MHz, y "Output Full Scale"
#: −2–7 dBm), `4.12.1-f002` carries none. That pairing is the whole point —
#: every axis filter must keep the first and rule out the second.
WITH_AXES = "4.12.1-f001"
WITHOUT_AXES = "4.12.1-f002"


@pytest.fixture
def built(tmp_path, monkeypatch):
    settings = built_settings(tmp_path)
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    return settings


def _hits(capsys) -> tuple[dict, list[str]]:
    payload = json.loads(capsys.readouterr().out)
    return payload, [h["id"] for h in payload["hits"]]


def test_flags_exist_on_the_parser(built, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["plots", "--help"])
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    for flag in ("--x-label", "--y-label", "--near-x", "--near-y"):
        assert flag in help_text


def test_y_label_narrows_to_the_figure_that_printed_it(built, capsys):
    code = cli.main(["plots", "--part", "TEST", "--y-label", "Full Scale", "--json"])
    _payload, ids = _hits(capsys)
    assert code == 0
    assert ids == [WITH_AXES]


def test_near_x_converts_si_prefixes(built, capsys):
    """The axis prints MHz; the query asks in GHz and must still land."""
    code = cli.main(["plots", "--part", "TEST", "--near-x", "1.0GHz", "--json"])
    _payload, ids = _hits(capsys)
    assert code == 0
    assert ids == [WITH_AXES]


def test_near_x_outside_the_printed_range_matches_nothing(built, capsys):
    """The plan's worked example, on a figure whose range does not cover it.

    3.5 GHz is outside the fixture's 600–1500 MHz sweep, so the honest answer
    is no figure and exit 1 — not the nearest one.
    """
    code = cli.main(
        ["plots", "--part", "TEST", "--near-x", "3.5GHz", "--y-label", "Gain", "--json"]
    )
    _payload, ids = _hits(capsys)
    assert code == 1
    assert ids == []


def test_a_figure_with_unread_axes_is_ruled_out(built, capsys):
    """Matching `find_plots`'s documented direction, which is the honest one.

    A figure whose axes could not be read cannot be shown to cover 1 GHz, so
    an axis query must not return it. It stays reachable by caption.
    """
    cli.main(["plots", "--part", "TEST", "--near-x", "1.0GHz", "--json"])
    _payload, narrowed = _hits(capsys)
    assert WITHOUT_AXES not in narrowed

    cli.main(["plots", "--part", "TEST", "--q", "Gain Error", "--json"])
    _payload, by_caption = _hits(capsys)
    assert by_caption == [WITHOUT_AXES]


def test_json_query_block_reports_what_narrowed(built, capsys):
    cli.main(
        [
            "plots",
            "--part",
            "TEST",
            "--x-label",
            "Output Frequency",
            "--y-label",
            "Full Scale",
            "--near-x",
            "1.0GHz",
            "--near-y",
            "0dBm",
            "--json",
        ]
    )
    payload, ids = _hits(capsys)
    assert ids == [WITH_AXES]
    assert payload["query"] == {
        "q": "",
        "section": "",
        "tags": [],
        "x_label": "Output Frequency",
        "y_label": "Full Scale",
        "near_x": "1.0GHz",
        "near_y": "0dBm",
    }


def test_project_scope_accepts_the_same_filters(built, capsys):
    """A project fans out to members and must narrow by the same rules.

    `ProjectScope.plots` did not accept the axis keywords at all, so this
    invocation raised `TypeError` before ticket 02 — the flags could not have
    been wired without extending that seam too.
    """
    code = cli.main(["plots", "--project", "rf-frontend", "--y-label", "Full Scale", "--json"])
    _payload, ids = _hits(capsys)
    assert code == 0
    assert ids == [WITH_AXES, WITH_AXES]  # one per member part
