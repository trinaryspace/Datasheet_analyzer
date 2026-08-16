"""The MCP surface that must hold **without** the `[mcp]` extra (ticket 07).

The SDK is optional, so the rules that do not depend on it are tested where
they cannot be switched off by a lean install:

- the **seam**: `mcp_server/server.py` holds no retrieval logic (the same
  grep-shaped guard `cli.py` carries), read off the source file without
  importing it;
- the **declared shapes**: `SCHEMAS` is asserted against the hits' own
  `as_dict()`, and the validator is proven to bite, so a declared contract
  cannot drift from the data it describes;
- **no machine state**: a figure's MIME type is read from a declared table,
  not from `mimetypes.guess_type`, which seeds itself from the host registry;
- **path safety**: `Retriever.corpus_path` is the single place a caller's
  string becomes a path, and it refuses rather than normalizes;
- the **optional extra** itself: `responses` imports with `mcp` unimportable,
  and `dsa serve --mcp` on a core install prints an install hint.

Everything here would previously have been unrunnable on a core install,
because it shared a module with `from mcp import ClientSession`. The
session-driven half lives in `test_mcp_server.py`, behind an `importorskip`.
"""

from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path

import pytest
from mcp_corpus import DOC, FIGURE, built_settings

from datasheet_analyzer import cli
from datasheet_analyzer.config import Settings
from datasheet_analyzer.mcp_server import responses as R
from datasheet_analyzer.retrieve import Retriever


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return built_settings(tmp_path)


# --- the seam ----------------------------------------------------------------


class TestMcpServerIsFormatOnly:
    """The MCP server must never grow a retrieval implementation of its own.

    Same guard `cli.py` carries (`test_retrieve.py::TestCliIsFormatOnly`), and
    the same reason: two front ends over one core can only stay consistent if
    neither of them is allowed to look at the corpus itself.

    The source is read through `find_spec` rather than by importing the
    module, so this guard runs on a core install too — the seam is a property
    of the code, not of whether an optional dependency happens to be present.
    """

    SOURCE = Path(find_spec("datasheet_analyzer.mcp_server.server").origin).read_text(
        encoding="utf-8"
    )

    @pytest.mark.parametrize(
        "token",
        [
            "rglob",
            "specs.json",
            "plots.json",
            "search_index.json",
            "model_validate_json",
            "SpecSet",
            "PlotSet",
            "SpecRecord",
            "PlotRecord",
            "SearchIndex",
            "bm25",
            "§",
            "p.{",
        ],
    )
    def test_server_source_has_no_retrieval_logic(self, token):
        assert token not in self.SOURCE

    def test_the_declared_spec_shape_is_the_hit_s_own_shape(self, settings):
        hit = Retriever.for_part(settings.parts_dir / "TEST").specs(symbol="TJ")[0]
        assert set(hit.as_dict()) == set(R.SPEC_HIT_SCHEMA["required"])

    def test_the_declared_plot_shape_is_the_hit_s_own_shape(self, settings):
        hit = Retriever.for_part(settings.parts_dir / "TEST").plots()[0]
        assert set(hit.as_dict()) == set(R.PLOT_HIT_SCHEMA["required"])

    def test_the_declared_search_shape_is_the_hit_s_own_shape(self, settings):
        hit = Retriever.for_part(settings.parts_dir / "TEST").search("sysref")[0]
        assert set(hit.as_dict()) == set(R.SEARCH_HIT_SCHEMA["required"])

    def test_a_real_hit_validates_and_a_wrong_grade_does_not(self, settings):
        """The validator bites — without needing a session to produce a payload.

        A real `SpecHit.as_dict()` is dropped into the declared find_spec
        envelope: it must validate, and must stop validating the moment a
        field carries a value the contract does not allow.
        """
        hit = Retriever.for_part(settings.parts_dir / "TEST").specs(symbol="TJ")[0].as_dict()
        payload = R.error_response(
            "find_spec", "", max_tokens=6000, part="TEST",
            hits=[hit], suggestions=[], count=1, total=1,
        )
        assert R.validate_response(payload, "find_spec") == []
        hit["confidence"] = "excellent"
        assert R.validate_response(payload, "find_spec")


class TestTheImageTypeIsDataNotHostConfiguration:
    """The MIME type a client sees must not depend on the host machine.

    `mimetypes.guess_type` seeds itself from the Windows registry
    (`HKCR\\.png\\Content Type`), so a box still carrying the historical
    `image/x-png` would mislabel the very same PNG. Invariant #4 forbids
    relying on machine state, and an image block is part of the product.
    Read off the source, so this holds on a core install too.
    """

    SOURCE = TestMcpServerIsFormatOnly.SOURCE

    def test_the_server_never_asks_the_host_what_a_png_is(self):
        # the module docstring may *name* `mimetypes` to explain the rule; what
        # must not exist is the import that would let it be called.
        assert "import mimetypes" not in self.SOURCE

    def test_the_extensions_the_publisher_writes_are_all_declared(self):
        # `publish/plots.py` renders `.png` and downloads what the vendor
        # serves; anything unlisted must be honestly opaque, not guessed.
        for extension in (".png", ".gif", ".jpg", ".jpeg", ".svg"):
            assert f'"{extension}"' in self.SOURCE


# --- path safety -------------------------------------------------------------


class TestPathSafety:
    """`corpus_path` is the only place a caller's string becomes a path."""

    @pytest.mark.parametrize(
        "escape",
        ["../outside.png", "a/../../b.png", "/abs/path.png", "C:/Windows/win.ini", ""],
    )
    def test_escaping_references_resolve_to_nothing(self, settings, escape):
        assert Retriever.for_part(settings.parts_dir / "TEST").corpus_path(escape) is None

    def test_a_traversal_dressed_as_a_figure_reference_is_refused(self, settings):
        escape = f"docs/{DOC}/figures/../../../../secrets.png"
        assert Retriever.for_part(settings.parts_dir / "TEST").corpus_path(escape) is None

    def test_a_corpus_relative_reference_resolves_inside_the_part(self, settings):
        resolved = Retriever.for_part(settings.parts_dir / "TEST").corpus_path(FIGURE)
        assert resolved is not None
        assert resolved.exists()
        assert (settings.parts_dir / "TEST").resolve() in resolved.parents


# --- the optional extra ------------------------------------------------------


class TestTheOptionalExtra:
    """A core install must work, and must say what is missing when it cannot."""

    def test_the_response_layer_imports_without_the_sdk(self, monkeypatch):
        """The cap and the schemas are product rules, not SDK details.

        Proven by importing the module with `mcp` made unimportable: if
        anything in `responses` reached for the SDK, this would raise.
        """
        import importlib

        monkeypatch.setitem(sys.modules, "mcp", None)
        monkeypatch.delitem(sys.modules, "datasheet_analyzer.mcp_server", raising=False)
        monkeypatch.delitem(
            sys.modules, "datasheet_analyzer.mcp_server.responses", raising=False
        )
        module = importlib.import_module("datasheet_analyzer.mcp_server.responses")
        assert module.CAP_SETTING == "DSA_MCP_MAX_TOKENS"
        assert set(module.SCHEMAS) >= {"ask", "search", "get_figure"}

    def test_serve_without_the_extra_errors_with_an_install_hint(
        self, monkeypatch, capsys
    ):
        monkeypatch.setitem(sys.modules, "mcp", None)
        monkeypatch.setitem(sys.modules, "mcp.server", None)
        for name in list(sys.modules):
            if name.startswith("datasheet_analyzer.mcp_server"):
                monkeypatch.delitem(sys.modules, name, raising=False)

        assert cli.main(["serve", "--mcp"]) == 2
        err = capsys.readouterr().err
        assert '".[mcp]"' in err
        assert "pip install" in err

    def test_serve_without_mcp_flag_states_the_only_transport(self, capsys):
        assert cli.main(["serve"]) == 2
        assert "--mcp" in capsys.readouterr().err
