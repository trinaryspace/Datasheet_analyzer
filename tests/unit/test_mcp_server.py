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
from datasheet_analyzer.derive.provenance import resolve_source
from datasheet_analyzer.mcp_server import responses as R
from datasheet_analyzer.mcp_server import server as S
from datasheet_analyzer.retrieve import Retriever, clear_index_cache
from datasheet_analyzer.tokens import count_tokens

# Tools that return corpus content, and therefore must cite it. `list_parts`,
# `list_projects` and `get_index` are catalog/orientation calls: they make no
# claim about what a datasheet says, so an empty citation list is the honest
# answer there rather than a manufactured one.
CITING_TOOLS = (
    "search", "find_spec", "find_plots", "read_section", "get_figure", "ask",
    # Phase 6: a derived value is only usable if it names the printed page it
    # was copied from, so these cite exactly like the extracted surfaces.
    "find_pin", "find_register", "get_card", "compare_parts",
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
    ("get_figure", {"part": "TEST", "file": FIGURE}),
    ("ask", {"part": "TEST", "question": "max junction temperature"}),
    ("find_pin", {"part": "TEST", "pin_type": "ground"}),
    ("find_register", {"part": "TEST", "addr": "0x1A04"}),
    ("get_card", {"part": "TEST", "card": "power"}),
    ("compare_parts", {"parts": ["TEST", "OTHER"], "symbol": "TJ"}),
]
# Everything except `ask`: a pack carries its own rendered markdown *and* its
# structured rows, so it has a real serialization floor of a few hundred
# tokens that no amount of budget-shrinking gets under. That case is asserted
# separately — and asserted to *announce* itself.
# `compare_parts` joins it for a related reason: its coverage report — how
# many rows were considered, how many compared, and which could not be — is
# the honest half of a comparison and is not a droppable row, so a comparison
# has a serialization floor of its own.
SHEDDABLE_CALLS = [c for c in ALL_CALLS if c[0] not in ("ask", "compare_parts")]
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
            "find_pin", "find_register", "get_card", "compare_parts",
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
            ("get_figure", {"part": "TEST", "file": FIGURE}),
            ("ask", {"part": "TEST", "question": "max junction temperature"}),
            ("find_pin", {"part": "TEST", "pin_type": "ground"}),
            ("find_register", {"part": "TEST", "addr": "0x1A04"}),
            ("get_card", {"part": "TEST", "card": "power"}),
            ("compare_parts", {"parts": ["TEST", "OTHER"], "symbol": "TJ"}),
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
            ("find_pin", {"part": "TEST", "pin_type": "ground"}, "hits"),
            ("find_register", {"part": "TEST", "addr": "0x1A04"}, "hits"),
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


# --- the derived artifacts (phase 6) -----------------------------------------


class TestTheDerivedTools:
    """`find_pin`, `find_register`, `get_card`, `compare_parts` over a session.

    The extracted tools are tested for "does it find the record". These are
    tested for that *and* for the rule that only applies to derived data
    (AGENTS.md invariant 8): every value names the record it was copied from,
    the page that printed it and the rule that produced it, and a field that
    could not be filled is null and says why.
    """

    def test_find_pin_filters_by_the_lexicon_label_and_cites_the_page(self, server):
        payload = payload_of(call(server, "find_pin", part="TEST", pin_type="ground"))
        assert [hit["pin"] for hit in payload["hits"]] == ["A1", "A2"]
        assert payload["counts"] == {"ground": 2}
        top = payload["hits"][0]
        assert top["name"] == "VSSA"
        assert top["citation"] == "§4.3, p.6"
        # clause (c): the label is traceable to the checked-in lexicon entry
        assert top["type_evidence"] == "name:*vss*"

    def test_find_pin_answers_a_designator_and_a_signal_name(self, server):
        by_pin = payload_of(call(server, "find_pin", part="TEST", q="B1"))
        by_name = payload_of(call(server, "find_pin", part="TEST", q="VDD1P8"))
        assert [h["id"] for h in by_pin["hits"]] == [h["id"] for h in by_name["hits"]]
        assert by_pin["hits"][0]["matched_via"] == "pin"
        assert by_name["hits"][0]["matched_via"] == "name"

    def test_a_multi_pin_row_keeps_the_cell_it_expanded_from(self, server):
        payload = payload_of(call(server, "find_pin", part="TEST", q="A2"))
        assert payload["hits"][0]["expanded_from"] == "A1, A2"

    def test_a_part_with_no_pin_table_is_named_not_silently_empty(self, tmp_path):
        """"No pin table was published" and "this device has no pins" differ."""
        build_part(tmp_path / "parts" / "DRY")
        for pins in (tmp_path / "parts" / "DRY").rglob("pins.json"):
            pins.unlink()
        settings = empty_settings(tmp_path)
        payload = payload_of(
            call(S.build_server(settings), "find_pin", part="DRY", pin_type="power")
        )
        assert payload["hits"] == []
        assert payload["parts_without_pins"] == ["DRY"]
        assert "no pin table was published" in payload["warning"]
        assert payload["error"] == "", "an absent artifact is a warning, not a failed call"

    def test_find_register_resolves_an_address_by_value(self, server):
        """`0x1A04`, `0x1a04` and `6660` are one question, not three."""
        ids = {
            form: [
                hit["id"]
                for hit in payload_of(
                    call(server, "find_register", part="TEST", addr=form)
                )["hits"]
            ]
            for form in ("0x1A04", "0x1a04", "6660")
        }
        assert ids["0x1A04"] == ids["0x1a04"] == ids["6660"] != []

    def test_a_register_hit_names_the_rule_behind_its_parsed_address(self, server):
        payload = payload_of(call(server, "find_register", part="TEST", name="TXDIG"))
        top = payload["hits"][0]
        assert top["address"] == {"verbatim": "0x1A04", "value": 6660}
        assert top["reset"] == {"verbatim": "0x00", "value": 0}
        assert top["address_derivation"] == "parse_address"
        assert top["citation"] == "§4.5, p.7"

    def test_asking_for_a_bit_field_says_none_are_published(self, server):
        """An empty result must not read as "this register has no fields"."""
        payload = payload_of(call(server, "find_register", part="TEST", field="NCO"))
        assert payload["hits"] == []
        assert payload["bit_fields"] is False
        assert "no bit-field records are published" in payload["warning"]

    def test_get_card_carries_a_full_provenance_envelope_on_every_value(self, server):
        payload = payload_of(call(server, "get_card", part="TEST", card="power"))
        assert payload["card"] == "power"
        assert payload["rows"]
        for row in payload["rows"]:
            assert row["citation"], "a card row without a citation is not evidence"
            for value in row["values"].values():
                if value["verbatim"]:
                    assert value["source"], "a filled value must name its record"
                    assert value["page"] is not None
                    assert value["derivation"]
                else:
                    assert value["null_reason"], "an empty value must say why"

    def test_a_card_value_resolves_back_to_the_record_it_cites(self, server, settings):
        """The invariant-8 walk, run over what the tool actually returned."""
        payload = payload_of(call(server, "get_card", part="TEST", card="thermal"))
        filled = [
            value
            for row in payload["rows"]
            for value in row["values"].values()
            if value["verbatim"]
        ]
        assert filled
        for value in filled:
            found = resolve_source(value["source"], roots=[settings.parts_dir / "TEST"])
            assert found is not None, f"{value['source']} resolves to no record"
            assert found.page == value["page"]

    def test_an_unknown_card_is_refused_with_the_names_that_exist(self, server):
        payload = payload_of(call(server, "get_card", part="TEST", card="pinout"))
        assert payload["rows"] == []
        assert "unknown card" in payload["error"]
        assert "power" in payload["error"]
        assert R.validate_response(payload, "get_card") == []

    def test_compare_parts_aligns_a_symbol_and_reports_its_coverage(self, server):
        payload = payload_of(
            call(server, "compare_parts", parts=["TEST", "OTHER"], symbol="TJ")
        )
        assert payload["parts"] == ["TEST", "OTHER"]
        row = payload["rows"][0]
        assert row["symbol"] == "TJ"
        assert [cell["part"] for cell in row["cells"]] == ["TEST", "OTHER"]
        assert all(cell["citation"].startswith("p.") for cell in row["cells"])
        assert payload["coverage"]["considered"] >= payload["coverage"]["compared"]

    def test_compare_parts_refuses_a_part_it_cannot_resolve(self, server):
        payload = payload_of(call(server, "compare_parts", parts=["TEST", "NOPE"]))
        assert payload["rows"] == []
        assert "NOPE" in payload["error"]
        assert R.validate_response(payload, "compare_parts") == []

    def test_find_plots_narrows_the_catalog_by_printed_axis(self, server):
        """The whole point of the axis catalog: fewer figures, no vision call."""
        everything = payload_of(call(server, "find_plots", part="TEST"))
        by_axis = payload_of(call(server, "find_plots", part="TEST", y_label="Full Scale"))
        assert by_axis["total"] == 1 < everything["total"]
        axes = by_axis["hits"][0]["axes"]
        assert axes["x"] == {
            "label": "Output Frequency",
            "unit": "MHz",
            "min": 600.0,
            "max": 1500.0,
        }
        assert axes["confidence"] == "high"

    def test_a_figure_whose_axes_were_not_read_is_not_an_axis_match(self, server):
        """Null axes are honest, and honesty means they match no axis filter."""
        unread = payload_of(call(server, "find_plots", part="TEST", q="Gain Error"))
        assert unread["hits"][0]["axes"]["confidence"] == "unknown"
        assert unread["hits"][0]["axes"]["x"]["min"] is None
        narrowed = payload_of(call(server, "find_plots", part="TEST", near_x="900MHz"))
        assert [h["id"] for h in narrowed["hits"]] == ["4.12.1-f001"]


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
        # 300 held one plot hit before phase 6; a hit now carries its axis
        # catalog too, so the cap that keeps exactly one row moved up with it.
        # The rule under test is unchanged: some rows survive, whole and cited.
        server = S.build_server(self._capped(settings, 420))
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
