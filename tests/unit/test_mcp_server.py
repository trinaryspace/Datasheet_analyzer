"""The local stdio MCP server, driven over a real session (Phase 5, ticket 07).

What these prove:

- **every tool is exercised in-process over the SDK's memory transport** — a
  real `ClientSession` talking to the real server over in-memory streams, no
  subprocess, no port, hermetic per invariant #4;
- every content-returning tool carries citations *and* a confidence grade, and
  every response validates against its **declared** schema (`SCHEMAS`);
- `DSA_MCP_MAX_TOKENS` caps every response, and a truncated one says so in a
  notice **naming the setting** — asserted on a deliberately tiny cap for a
  list body, a text body, an answer pack and a pinned resource;
- `get_figure` returns a real image content block, and refuses a path that
  leaves the part directory;
- both resources resolve and return index text;
- a server over an empty parts directory lists nothing and answers honestly,
  rather than failing to start;
- `dsa serve --mcp` hands the process to that server.

Everything here needs the `[mcp]` extra, so the module is gated by
`pytest.importorskip("mcp")`: a core install skips it instead of failing
collection and taking the rest of the suite down with it. The half of the
ticket that must hold **without** the SDK — the seam guard, the declared
shapes, the path-safety refusal, the install hint — lives in
`test_mcp_responses.py`, where no lean install can switch it off. The corpus
both halves run against is built once in `mcp_corpus.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp_corpus import DOC, FIGURE, PNG_BYTES, build_part, built_settings, empty_settings
from mcp_session import call, over_session, payload_of

pytest.importorskip("mcp", reason="the MCP server tests need the optional [mcp] extra")

from mcp.types import ImageContent

from datasheet_analyzer import cli
from datasheet_analyzer.config import Settings
from datasheet_analyzer.mcp_server import responses as R
from datasheet_analyzer.mcp_server import server as S
from datasheet_analyzer.retrieve import Comparison, Retriever, clear_index_cache
from datasheet_analyzer.tokens import count_tokens

# Tools that return corpus content, and therefore must cite it. `list_parts`,
# `list_projects` and `get_index` are catalog/orientation calls: they make no
# claim about what a datasheet says, so an empty citation list is the honest
# answer there rather than a manufactured one.
CITING_TOOLS = (
    "search", "find_spec", "find_plots", "find_pin", "find_register", "get_card",
    "read_section", "get_figure", "ask", "compare_parts",
)

#: One representative call per tool — the whole surface, in one list, so a cap
#: assertion cannot quietly skip a tool someone forgot to add.
ALL_CALLS = [
    ("list_parts", {}),
    ("list_projects", {}),
    ("get_index", {"part": "TEST"}),
    ("search", {"part": "TEST", "query": "sysref setup"}),
    ("find_spec", {"part": "TEST", "name": "supply"}),
    ("read_section", {"part": "TEST", "ref": "4.3"}),
    ("find_plots", {"part": "TEST"}),
    ("find_pin", {"part": "TEST", "type": "ground"}),
    ("find_register", {"part": "TEST", "addr": "0x19"}),
    ("get_card", {"part": "TEST", "card": "power"}),
    # phase 7, ticket 05 — the trust signal, read before an answer is composed
    ("get_audit", {"part": "TEST"}),
    ("get_figure", {"part": "TEST", "file": FIGURE}),
    ("ask", {"part": "TEST", "question": "max junction temperature"}),
    ("compare_parts", {"parts": ["TEST", "OTHER"], "name": "junction temperature"}),
]
# Everything with no floor of its own. `ask` has one: a pack carries its own
# rendered markdown *and* its structured rows, so it has a real serialization
# floor of a few hundred tokens that no amount of budget-shrinking gets under.
# `compare_parts` has one for a different reason — its population sentences and
# its "not comparable" listing are invariant 8's honesty half, so a cap may drop
# comparison *rows* and may never drop the record of what could not be compared.
# Both cases are asserted separately, and asserted to *announce* themselves.
FLOORED_TOOLS = ("ask", "compare_parts")
SHEDDABLE_CALLS = [c for c in ALL_CALLS if c[0] not in FLOORED_TOOLS]
CITING_CALLS = [c for c in ALL_CALLS if c[0] in CITING_TOOLS]


# --- corpus fixtures ---------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A settings object pointed at two built parts and one project."""
    return built_settings(tmp_path)


@pytest.fixture
def bare_settings(tmp_path: Path) -> Settings:
    """A machine where nothing has been built yet."""
    return empty_settings(tmp_path)


@pytest.fixture
def server(settings: Settings):
    return S.build_server(settings)


# --- in-process memory transport ---------------------------------------------
#
# The harness itself lives in `tests/mcp_session.py`, because the phase-5 gate
# drives the same server against four real datasheets and "in-process" must
# mean the same thing in both places: a real session — initialize, list, call —
# with both ends in this process and nothing on a socket or a pipe.


# --- the tool surface --------------------------------------------------------


class TestEveryToolOverTheMemoryTransport:
    """The whole surface, driven as a client drives it."""

    def test_the_declared_tools_are_the_ticket_s_tools(self, server):
        async def _work(session):
            return await session.list_tools()

        names = {t.name for t in over_session(server, _work).tools}
        assert names == {
            "list_parts", "list_projects", "get_index", "search", "find_spec",
            "read_section", "find_plots", "get_figure", "ask",
            # phase 6, ticket 09 — the one tool whose scope is a list of parts
            "compare_parts",
            # phase 6, ticket 10 — the two device tables and the design card
            "find_pin", "find_register", "get_card",
            # phase 7, ticket 05 — the trust signal an agent reads *before* it answers
            "get_audit",
        }

    def test_every_tool_ships_its_declared_response_schema(self, server):
        async def _work(session):
            return await session.list_tools()

        for tool in over_session(server, _work).tools:
            assert (tool.meta or {}).get("response_schema") == R.SCHEMAS[tool.name]

    @pytest.mark.parametrize(
        "tool,arguments",
        [
            ("list_parts", {}),
            ("list_projects", {}),
            ("get_index", {"part": "TEST"}),
            ("search", {"part": "TEST", "query": "sysref setup"}),
            ("find_spec", {"part": "TEST", "name": "junction temperature"}),
            ("read_section", {"part": "TEST", "ref": "4.3"}),
            ("find_plots", {"part": "TEST", "q": "Fullscale"}),
            ("find_pin", {"part": "TEST", "type": "ground"}),
            ("find_register", {"part": "TEST", "field": "CLK_MUX"}),
            ("get_card", {"part": "TEST", "card": "power"}),
            ("get_card", {"part": "TEST"}),
            ("get_figure", {"part": "TEST", "file": FIGURE}),
            ("ask", {"part": "TEST", "question": "max junction temperature"}),
            (
                "compare_parts",
                {"parts": ["TEST", "OTHER"], "name": "junction temperature"},
            ),
        ],
    )
    def test_every_response_validates_against_its_declared_schema(
        self, server, tool, arguments
    ):
        payload = payload_of(call(server, tool, **arguments))
        assert R.validate_response(payload, tool) == []
        assert payload["tool"] == tool
        assert payload["error"] == ""

    @pytest.mark.parametrize("tool,arguments", CITING_CALLS)
    def test_every_content_response_carries_citations(self, server, tool, arguments):
        payload = payload_of(call(server, tool, **arguments))
        assert payload["citations"], f"{tool} returned corpus content with no citation"
        assert all("p." in c for c in payload["citations"])

    @pytest.mark.parametrize(
        "tool,arguments,where",
        [
            ("find_spec", {"part": "TEST", "name": "junction temperature"}, "hits"),
            ("find_plots", {"part": "TEST", "q": "Fullscale"}, "hits"),
            ("search", {"part": "TEST", "query": "sysref setup"}, "hits"),
            ("find_pin", {"part": "TEST", "type": "ground"}, "hits"),
            ("find_register", {"part": "TEST", "addr": "0x19"}, "hits"),
        ],
    )
    def test_every_hit_carries_a_confidence_grade(self, server, tool, arguments, where):
        payload = payload_of(call(server, tool, **arguments))
        assert payload[where]
        assert all(hit["confidence"] in {"high", "medium", "low", "unknown"}
                   for hit in payload[where])

    def test_find_spec_answers_a_designer_s_words_through_the_alias_ladder(self, server):
        payload = payload_of(call(server, "find_spec", part="TEST",
                                  name="junction temperature"))
        top = payload["hits"][0]
        assert top["symbol"] == "TJ"
        assert top["max"] == "105"
        assert top["citation"] == "§4.3, p.6"
        assert top["confidence"] == "high"
        assert top["matched_via"].startswith("alias:")

    def test_find_spec_with_no_match_suggests_instead_of_guessing(self, server):
        payload = payload_of(call(server, "find_spec", part="TEST",
                                  symbol="ZZQQ"))
        assert payload["hits"] == []
        assert payload["suggestions"]

    def test_search_hits_are_cited_by_construction(self, server):
        payload = payload_of(call(server, "search", part="TEST", query="sysref setup"))
        top = payload["hits"][0]
        assert top["section"] == "4.5"
        assert top["citation"] == "§4.5, p.7-8"
        assert "SYSREF" in top["snippet"]

    def test_read_section_returns_the_corpus_markdown_with_its_citation(
        self, server, settings
    ):
        payload = payload_of(call(server, "read_section", part="TEST", ref="4.3"))
        assert payload["citation"] == "§4.3, p.6"
        assert "junction temperature" in payload["text"]
        on_disk = (settings.parts_dir / "TEST" / payload["file"]).read_text(encoding="utf-8")
        assert payload["text"] == on_disk

    def test_read_section_resolves_a_title_as_well_as_a_number(self, server):
        payload = payload_of(call(server, "read_section", part="TEST",
                                  ref="Transmitter Electrical"))
        assert payload["section"] == "4.5"
        assert payload["matched_via"] == "title"

    def test_read_section_says_so_when_the_reference_matches_nothing(self, server):
        payload = payload_of(call(server, "read_section", part="TEST", ref="99.9"))
        assert payload["text"] == ""
        assert "no section matching" in payload["error"]
        assert R.validate_response(payload, "read_section") == []

    def test_ask_returns_the_answer_pack_the_cli_returns(self, server, settings):
        payload = payload_of(call(server, "ask", part="TEST",
                                  question="max junction temperature"))
        pack = payload["pack"]
        assert pack["route"] == "spec"
        assert pack["answers"][0]["citation"] == "§4.3, p.6"
        assert pack["answers"][0]["confidence"] == "high"
        # the same pack the CLI would print, not a second implementation
        direct = Retriever.for_part(settings.parts_dir / "TEST").ask(
            "max junction temperature", budget=pack["budget"]
        )
        assert pack["markdown"] == direct.markdown

    def test_compare_parts_returns_the_comparison_the_cli_returns(self, server, settings):
        """Phase 6, ticket 09 — the part-selection question over the transport.

        The two built parts print the same table except for the junction
        temperature (105 °C against 125 °C), so the row must carry both printed
        values, both citations, and the one number the comparison adds.
        """
        payload = payload_of(call(server, "compare_parts", parts=["TEST", "OTHER"],
                                  name="junction temperature"))
        assert payload["error"] == ""
        assert payload["comparison"]["parts"] == ["TEST", "OTHER"]
        assert payload["comparison"]["reference"] == "TEST"
        row = next(r for r in payload["rows"] if r["key"] == "TJ")
        assert row["aligned_on"] == "alias:TJ"
        assert row["role"] == "max"
        assert [c["values"]["max"]["verbatim"] for c in row["cells"]] == [
            "105 °C", "125 °C"
        ]
        assert [c["citation"] for c in row["cells"]] == ["§4.3, p.6", "§4.3, p.6"]
        assert row["cells"][1]["delta"]["value_si"] == 20.0
        assert row["cells"][1]["delta"]["derivation"] == "si_delta:max"
        # the same comparison the CLI would print, not a second implementation
        direct = Comparison.for_parts(
            [settings.parts_dir / "TEST", settings.parts_dir / "OTHER"]
        ).specs(name="junction temperature")
        assert payload["rows"] == direct.model_dump(mode="json")["rows"]

    def test_compare_parts_refuses_one_part_and_a_repeated_part(self, server):
        for parts, needle in (
            (["TEST"], "at least two parts"),
            (["TEST", "TEST"], "named twice"),
        ):
            payload = payload_of(call(server, "compare_parts", parts=parts, symbol="TJ"))
            assert needle in payload["error"]
            assert payload["rows"] == []
            assert R.validate_response(payload, "compare_parts") == []

    def test_compare_parts_names_an_unbuilt_part_instead_of_dropping_it(self, server):
        payload = payload_of(call(server, "compare_parts", parts=["TEST", "NOPE"],
                                  symbol="TJ"))
        assert "NOPE" in payload["error"] and "dsa build" in payload["error"]
        assert payload["comparison"] is None

    def test_list_parts_reports_revision_counts_and_the_confidence_mix(self, server):
        payload = payload_of(call(server, "list_parts"))
        row = next(p for p in payload["parts"] if p["part"] == "TEST")
        assert row["built"] is True
        assert row["revision"] == "SBASA41E"
        assert row["sections"] == 2
        assert row["specs"] == 3
        assert row["searchable"] is True
        assert row["spec_confidence"] == {"high": 1, "medium": 1, "low": 1}

    def test_list_projects_reports_members_and_whether_they_are_built(self, server):
        payload = payload_of(call(server, "list_projects"))
        project = payload["projects"][0]
        assert project["name"] == "rf-frontend"
        assert [m["part"] for m in project["parts"]] == ["TEST", "OTHER"]
        assert all(m["built"] for m in project["parts"])
        assert project["built"] is True

    def test_a_project_scoped_answer_names_the_part_it_came_from(self, server):
        payload = payload_of(call(server, "find_spec", project="rf-frontend",
                                  name="junction temperature"))
        assert {hit["part"] for hit in payload["hits"]} == {"TEST", "OTHER"}

    def test_naming_both_part_and_project_is_refused_not_guessed(self, server):
        payload = payload_of(call(server, "search", part="TEST",
                                  project="rf-frontend", query="sysref"))
        assert payload["hits"] == []
        assert "exactly one" in payload["error"]
        assert R.validate_response(payload, "search") == []

    def test_an_unbuilt_part_is_an_error_that_names_the_build_command(self, server):
        payload = payload_of(call(server, "get_index", part="NOPE"))
        assert payload["text"] == ""
        assert "dsa build" in payload["error"]
        assert R.validate_response(payload, "get_index") == []

    def test_a_corpus_with_no_search_index_is_told_to_rebuild_not_told_nothing(
        self, settings
    ):
        """An empty result and an unrunnable path are different findings."""
        for stale in (settings.parts_dir / "TEST").rglob("search_index.json"):
            stale.unlink()
        # the loaded corpus is cached on manifest identity, which deleting an
        # artifact behind its back does not change — a rebuild would
        clear_index_cache()
        payload = payload_of(
            call(S.build_server(settings), "search", part="TEST", query="sysref")
        )
        assert payload["hits"] == []
        assert "rebuild" in payload["error"].lower()

    def test_the_validator_bites_on_a_real_session_payload(self, server):
        """A payload that came off the wire, made wrong, must stop validating."""
        payload = payload_of(call(server, "find_spec", part="TEST", symbol="TJ"))
        assert R.validate_response(payload, "find_spec") == []
        payload["hits"][0]["confidence"] = "excellent"
        assert R.validate_response(payload, "find_spec")


# --- the axis catalog over the wire ------------------------------------------


class TestFindPlotsAxisFilters:
    """Phase 6, ticket 08: `find_plots` narrows by axis before a vision call.

    The corpus prints figure 4-2's axes (`DSA (dB)` 0…40 against a gain-error
    axis in dB) and figure 4-1 with none — a precisely cited figure whose plot is
    a raster image. That is the pair every axis filter must separate.
    """

    def test_x_label_narrows_to_the_figure_whose_axis_says_so(self, server):
        payload = payload_of(call(server, "find_plots", part="TEST", x_label="DSA"))
        assert [h["id"] for h in payload["hits"]] == ["4.12.1-f002"]
        assert payload["hits"][0]["matched_via"] == "axis-label"
        assert R.validate_response(payload, "find_plots") == []

    def test_near_x_selects_by_the_printed_tick_range(self, server):
        payload = payload_of(call(server, "find_plots", part="TEST", near_x="20dB"))
        assert len(payload["hits"]) == 1
        hit = payload["hits"][0]
        assert hit["matched_via"] == "axis-range"
        assert hit["axes"]["x"] == {
            "label": "DSA", "unit": "dB", "min": 0.0, "max": 40.0, "scale": "linear",
        }
        assert hit["axes"]["page"] == 30
        assert R.validate_response(payload, "find_plots") == []

    def test_a_value_outside_every_printed_range_matches_nothing(self, server):
        payload = payload_of(call(server, "find_plots", part="TEST", near_x="90dB"))
        assert payload["hits"] == []
        # …and it says so as a *gap*, not as an absence: the corpus holds a
        # figure whose axes are unreadable, so nothing was established about it.
        assert "cannot establish that no such figure exists" in payload["warning"]
        assert payload["error"] == ""
        assert R.validate_response(payload, "find_plots") == []

    def test_the_axis_gap_names_the_population_it_could_not_consider(self, server):
        payload = payload_of(call(server, "find_plots", part="TEST", y_label="Gain Error"))
        assert [h["id"] for h in payload["hits"]] == ["4.12.1-f002"]
        assert "no readable y axis" in payload["warning"]

    def test_a_caption_lookup_carries_no_axis_warning(self, server):
        payload = payload_of(call(server, "find_plots", part="TEST", q="Fullscale"))
        assert payload["warning"] == ""

    def test_every_hit_carries_the_grade_and_a_null_block_when_unread(self, server):
        payload = payload_of(call(server, "find_plots", part="TEST"))
        by_id = {h["id"]: h for h in payload["hits"]}
        assert by_id["4.12.1-f002"]["axis_confidence"] == "high"
        assert by_id["4.12.1-f001"]["axis_confidence"] == "low"
        assert by_id["4.12.1-f001"]["axes"] is None


# --- the device tables and the design card over the wire ----------------------


class TestDeviceTableAndCardTools:
    """Phase 6, ticket 10: `find_pin`, `find_register`, `get_card`.

    Three tools whose whole point is that they hand back an *artifact* rather
    than prose, so what is asserted here is the artifact's honesty: the exact
    designator rule, the derived label travelling with the evidence that decided
    it, the address resolving by parsed value, the absent reset staying absent,
    the bit-field gap being reported, and a card value arriving in its
    provenance envelope with the page it was printed on.
    """

    def test_find_pin_is_exact_on_a_designator(self, server):
        """`A1` is ball A1 and never A10 as well — a near-miss on a pin is a
        wiring error, not a disappointing search result."""
        payload = payload_of(call(server, "find_pin", part="TEST", pin="A1"))
        assert [hit["pin"] for hit in payload["hits"]] == ["A1"]
        assert payload["hits"][0]["citation"] == "§4.3, p.6"
        assert payload["hits"][0]["matched_via"] == "pin"

    def test_a_pin_type_travels_with_the_phrase_that_decided_it(self, server):
        """`type` is the one derived field a pin has, so invariant 8 says the
        rule that produced it must be readable in the same object."""
        payload = payload_of(call(server, "find_pin", part="TEST", type="ground"))
        assert [hit["pin"] for hit in payload["hits"]] == ["A1", "A10"]
        assert all(hit["type"] == "ground" for hit in payload["hits"])
        assert all(hit["type_evidence"] == "ground" for hit in payload["hits"])

    def test_a_corpus_with_no_pin_table_refuses_instead_of_answering_nothing(
        self, tmp_path
    ):
        """An empty list would read as "this datasheet has no such pin"; the
        corpus never looked, so the call is an error that says so."""
        build_part(tmp_path / "parts" / "BARE", with_device_tables=False)
        server = S.build_server(empty_settings(tmp_path))
        pins = payload_of(call(server, "find_pin", part="BARE", pin="A1"))
        assert pins["hits"] == []
        assert "establishes nothing" in pins["error"]
        assert R.validate_response(pins, "find_pin") == []
        # …and its register twin, which refuses for the same reason.
        regs = payload_of(call(server, "find_register", part="BARE", addr="0x19"))
        assert regs["hits"] == []
        assert "establishes nothing" in regs["error"]
        assert R.validate_response(regs, "find_register") == []

    def test_find_register_resolves_an_address_by_its_parsed_value(self, server):
        """`0x19`, `0x19` in lower case and `25` are one question."""
        seen = []
        for addr in ("0x19", "0x19".lower(), "25"):
            payload = payload_of(call(server, "find_register", part="TEST", addr=addr))
            assert len(payload["hits"]) == 1, addr
            seen.append(payload["hits"][0]["id"])
        assert seen == ["reg_2", "reg_2", "reg_2"]

    def test_a_register_the_document_states_no_reset_for_publishes_none(self, server):
        """`null`, never a plausible `0x0` — the absence is the reading."""
        payload = payload_of(call(server, "find_register", part="TEST", name="R0"))
        hit = payload["hits"][0]
        assert hit["reset"] is None
        assert hit["fields"] == []
        assert hit["fields_reason"]

    def test_a_published_field_set_carries_what_makes_it_checkable(self, server):
        payload = payload_of(call(server, "find_register", part="TEST", name="R25"))
        hit = payload["hits"][0]
        assert hit["reset"]["verbatim"] == "0x0211"
        assert hit["reset"]["page"] == 6
        assert hit["width"] == 16
        assert hit["fields"][0]["name"] == "CLK_MUX"
        assert hit["fields"][0]["bits"] == {
            "verbatim": "2:0", "hi": 2, "lo": 0, "derivation": "parse_bit_range"
        }
        assert hit["fields_unaccounted_for"] == ["15:3"]

    def test_a_bit_field_filter_reports_the_registers_that_publish_none(self, server):
        """The honesty clause for a filter on a derived value: without it, an
        empty `field` result would read as "this device has no such bit field"."""
        payload = payload_of(call(server, "find_register", part="TEST", field="CLK_MUX"))
        assert [hit["name"] for hit in payload["hits"]] == ["R25"]
        assert "1 of 2 registers" in payload["field_gap"]
        assert "cannot establish that a field does not exist" in payload["field_gap"]

    def test_a_lookup_that_filters_on_no_field_owes_no_gap(self, server):
        payload = payload_of(call(server, "find_register", part="TEST", name="R25"))
        assert payload["field_gap"] == ""

    def test_get_card_returns_the_card_the_cli_returns(self, server, settings):
        payload = payload_of(call(server, "get_card", part="TEST", card="power"))
        direct = Retriever.for_part(settings.parts_dir / "TEST").card("power")
        assert payload["rows"] == direct.model_dump(mode="json")["rows"]
        assert payload["card"]["card"] == "power"
        assert "rows" not in payload["card"], "rows are hoisted, never duplicated"

    def test_every_card_value_arrives_in_its_provenance_envelope(self, server):
        payload = payload_of(call(server, "get_card", part="TEST", card="power"))
        value = payload["rows"][0]["values"]["pins"]
        assert value["page"] == 6
        assert value["derivation"] == "pins_by_name+count"
        assert value["source"], "a derived value with no source is untraceable"
        assert payload["citations"] == ["§4.3, p.6"]

    def test_an_empty_card_is_a_valid_card_and_says_what_it_looked_for(self, server):
        payload = payload_of(call(server, "get_card", part="TEST", card="limits"))
        assert payload["error"] == ""
        assert payload["rows"] == []
        assert payload["card"]["empty_reason"]
        assert R.validate_response(payload, "get_card") == []

    def test_no_card_named_lists_the_cards_this_build_declares(self, server):
        payload = payload_of(call(server, "get_card", part="TEST"))
        assert payload["card"] is None
        assert payload["names"] == ["power", "thermal", "interface", "limits"]
        assert payload["error"] == ""

    def test_a_card_name_that_does_not_exist_is_an_error_that_lists_them(self, server):
        payload = payload_of(call(server, "get_card", part="TEST", card="nope"))
        assert "no card named" in payload["error"]
        assert payload["names"], "a typo must be answerable without a second call"

    def test_a_project_scoped_pin_lookup_names_the_part_each_hit_came_from(self, server):
        payload = payload_of(
            call(server, "find_pin", project="rf-frontend", type="ground")
        )
        assert {hit["part"] for hit in payload["hits"]} == {"TEST", "OTHER"}


# --- the image path ----------------------------------------------------------


class TestGetFigure:
    """The tool that makes the plot catalog pay off."""

    def test_returns_a_valid_image_content_block(self, server):
        result = call(server, "get_figure", part="TEST", file=FIGURE)
        assert not result.is_error
        images = [c for c in result.content if isinstance(c, ImageContent)]
        assert len(images) == 1
        import base64

        assert base64.b64decode(images[0].data) == PNG_BYTES
        assert images[0].mime_type == "image/png"

    def test_the_image_travels_with_the_record_that_cites_it(self, server):
        payload = payload_of(call(server, "get_figure", part="TEST", file=FIGURE))
        figure = payload["figure"]
        assert figure["caption"].startswith("Figure 4-1 TX Output Fullscale")
        assert figure["citation"] == "§4.12.1, p.29"
        assert figure["confidence"] == "high"
        assert figure["bytes"] == len(PNG_BYTES)

    @pytest.mark.parametrize(
        "escape",
        [
            "../../../secrets.png",
            f"docs/{DOC}/figures/../../../../secrets.png",
            "/etc/passwd",
            "C:/Windows/win.ini",
        ],
    )
    def test_a_path_outside_the_part_directory_is_refused(self, server, escape):
        result = call(server, "get_figure", part="TEST", file=escape)
        assert result.is_error
        payload = payload_of(result)
        assert payload["figure"] is None
        assert "must stay inside the part directory" in payload["error"]

    def test_an_uncataloged_file_inside_the_part_is_still_refused(self, server, settings):
        loose = settings.parts_dir / "TEST" / "docs" / DOC / "figures" / "loose.png"
        loose.write_bytes(PNG_BYTES)
        result = call(server, "get_figure", part="TEST",
                      file=f"docs/{DOC}/figures/loose.png")
        assert result.is_error
        assert "no cataloged figure" in payload_of(result)["error"]

    def test_a_cataloged_figure_with_no_pixels_says_so(self, tmp_path):
        build_part(tmp_path / "parts" / "DRY", with_figure=False)
        settings = empty_settings(tmp_path)
        result = call(S.build_server(settings), "get_figure", part="DRY", file=FIGURE)
        assert result.is_error
        assert "not on disk" in payload_of(result)["error"]


# --- the response cap --------------------------------------------------------


class TestTheResponseCap:
    """`DSA_MCP_MAX_TOKENS` bounds every response, and truncation is loud."""

    @staticmethod
    def _capped(settings: Settings, cap: int) -> Settings:
        return settings.model_copy(update={"mcp_max_tokens": cap})

    @pytest.mark.parametrize("tool,arguments", SHEDDABLE_CALLS)
    def test_a_sheddable_response_always_fits_a_tight_cap(self, settings, tool, arguments):
        server = S.build_server(self._capped(settings, 400))
        payload = payload_of(call(server, tool, **arguments))
        assert R.response_tokens(payload) <= 400
        assert payload["over_cap"] is False

    @pytest.mark.parametrize("tool,arguments", ALL_CALLS)
    @pytest.mark.parametrize("cap", [40, 400, 6000])
    def test_over_cap_is_never_silent(self, settings, tool, arguments, cap):
        """The invariant that matters: nothing exceeds the cap unannounced."""
        server = S.build_server(self._capped(settings, cap))
        payload = payload_of(call(server, tool, **arguments))
        if R.response_tokens(payload) > cap:
            assert payload["over_cap"] is True
            assert payload["notice"], "an over-cap response must say so"
        else:
            assert payload["over_cap"] is False

    @pytest.mark.parametrize("tool,arguments", ALL_CALLS)
    def test_the_default_cap_truncates_nothing_on_a_small_corpus(
        self, settings, tool, arguments
    ):
        payload = payload_of(call(S.build_server(settings), tool, **arguments))
        assert payload["truncated"] is False
        assert payload["over_cap"] is False

    def test_a_truncated_list_drops_rows_and_names_the_setting(self, settings):
        server = S.build_server(self._capped(settings, 300))
        payload = payload_of(call(server, "find_plots", part="TEST"))
        assert payload["truncated"] is True
        assert 0 < payload["count"] < payload["total"]
        assert "DSA_MCP_MAX_TOKENS" in payload["notice"]
        # what survives is still whole and still cited
        assert R.validate_response(payload, "find_plots") == []
        assert payload["citations"]

    def test_a_truncated_text_body_names_the_setting(self, settings):
        server = S.build_server(self._capped(settings, 170))
        payload = payload_of(call(server, "read_section", part="TEST", ref="4.3"))
        assert payload["truncated"] is True
        assert R.response_tokens(payload) <= 170
        assert "DSA_MCP_MAX_TOKENS" in payload["notice"]
        assert payload["citation"] == "§4.3, p.6", "a cap must never cost the citation"

    def test_the_caller_s_own_max_tokens_bounds_the_text_and_is_named(self, settings):
        """`max_tokens` is a reading budget: it bounds the text, not the cite."""
        server = S.build_server(self._capped(settings, 6000))
        payload = payload_of(
            call(server, "read_section", part="TEST", ref="4.3", max_tokens=20)
        )
        assert payload["truncated"] is True
        assert "max_tokens=20" in payload["notice"]
        assert "DSA_MCP_MAX_TOKENS" in payload["notice"]
        assert 0 < count_tokens(payload["text"]) <= 20
        assert payload["citation"] == "§4.3, p.6"

    def test_an_answer_pack_shrinks_by_budget_rather_than_losing_a_citation(
        self, settings
    ):
        server = S.build_server(self._capped(settings, 800))
        payload = payload_of(call(server, "ask", part="TEST", question="supply voltage"))
        pack = payload["pack"]
        assert pack["budget"] <= 800
        assert R.response_tokens(payload) <= 800
        # every answer row still carries the page it came from
        assert all(line["citation"] for line in pack["answers"])
        assert "DSA_MCP_MAX_TOKENS" in payload["notice"]

    def test_a_cap_below_the_citation_floor_says_over_cap_instead_of_lying(
        self, settings
    ):
        server = S.build_server(self._capped(settings, 20))
        payload = payload_of(call(server, "ask", part="TEST",
                                  question="max junction temperature"))
        assert payload["over_cap"] is True
        assert payload["notice"]
        assert payload["pack"]["answers"][0]["citation"] == "§4.3, p.6"

    def test_a_pinned_resource_is_capped_and_says_so(self, settings):
        server = S.build_server(self._capped(settings, 12))

        async def _work(session):
            return await session.read_resource("dsa://part/TEST/INDEX.md")

        text = over_session(server, _work).contents[0].text
        assert "DSA_MCP_MAX_TOKENS" in text


# --- resources ---------------------------------------------------------------


class TestResources:
    def test_both_index_resources_resolve_and_return_their_text(self, server):
        async def _work(session):
            part = await session.read_resource("dsa://part/TEST/INDEX.md")
            project = await session.read_resource(
                "dsa://project/rf-frontend/PROJECT_INDEX.md"
            )
            return part, project

        part, project = over_session(server, _work)
        assert part.contents[0].text.startswith("# TEST")
        assert "rf-frontend" in project.contents[0].text
        assert "TEST" in project.contents[0].text

    def test_built_parts_and_projects_are_listed_as_concrete_resources(self, server):
        async def _work(session):
            listed = await session.list_resources()
            templates = await session.list_resource_templates()
            return listed, templates

        listed, templates = over_session(server, _work)
        uris = {str(r.uri) for r in listed.resources}
        assert "dsa://part/TEST/INDEX.md" in uris
        assert "dsa://project/rf-frontend/PROJECT_INDEX.md" in uris
        assert {t.uri_template for t in templates.resource_templates} == {
            S.PART_INDEX_URI,
            S.PROJECT_INDEX_URI,
        }

    def test_an_unbuilt_part_resource_explains_itself(self, server):
        async def _work(session):
            return await session.read_resource("dsa://part/NOPE/INDEX.md")

        text = over_session(server, _work).contents[0].text
        assert "dsa build" in text


# --- an empty machine --------------------------------------------------------


class TestZeroBuiltParts:
    """A server must start on a machine where nothing has been built."""

    def test_the_server_starts_and_lists_nothing(self, bare_settings):
        server = S.build_server(bare_settings)
        payload = payload_of(call(server, "list_parts"))
        assert payload["parts"] == []
        assert payload["total"] == 0
        assert payload["error"] == ""
        assert R.validate_response(payload, "list_parts") == []

    def test_no_resources_are_advertised(self, bare_settings):
        server = S.build_server(bare_settings)

        async def _work(session):
            return await session.list_resources()

        assert over_session(server, _work).resources == []

    def test_asking_an_absent_part_is_an_error_not_a_crash(self, bare_settings):
        server = S.build_server(bare_settings)
        payload = payload_of(call(server, "ask", part="TEST", question="anything"))
        assert payload["pack"] is None
        assert "dsa build" in payload["error"]


# --- the CLI hand-off --------------------------------------------------------


class TestServeWiring:
    def test_serve_with_the_extra_runs_the_stdio_server(self, monkeypatch, settings):
        """`dsa serve --mcp` hands off to the server and nothing else.

        The transport itself is not driven here — stdio would need a
        subprocess, which invariant #4 forbids; the sessions above prove the
        server, and this proves the wiring.
        """
        started: list[str] = []
        monkeypatch.setattr(
            S.MCPServer, "run", lambda self, transport="stdio", **kw: started.append(transport)
        )
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["serve", "--mcp"]) == 0
        assert started == ["stdio"]
