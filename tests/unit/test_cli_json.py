"""`--json` means stdout carries the payload and nothing else.

Phase 6.5, ticket 01. Every verb offering `--json` is a machine seam: an
agent, a shell pipeline, or `jq` reads stdout and parses it. PyMuPDF writes
its own diagnostics to stdout by default, so a dependency's warning — or a
malformed xref in the PDF being read — silently corrupts the payload.

The interesting property is that this is **not** decided by this repo today:
PyMuPDF 1.28.2 prints `warning: The 'fitz' API is deprecated...` on import and
1.28.0 prints nothing, while `pyproject.toml` pins `pymupdf>=1.24`. A test
that merely parses stdout on the installed version therefore asserts almost
nothing — on a quiet PyMuPDF it passes with the routing deleted. So the
mechanism is tested directly, and the end-to-end parse is the corroboration.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from mcp_corpus import built_settings

from datasheet_analyzer import cli

#: One invocation per verb that offers `--json`. Kept as data so
#: `test_every_json_verb_is_exercised` can hold it to the parser's own list.
JSON_INVOCATIONS: dict[str, list[str]] = {
    "query": ["query", "--part", "TEST", "--symbol", "VDD", "--json"],
    "search": ["search", "--part", "TEST", "supply", "--json"],
    "ask": ["ask", "--part", "TEST", "what is the supply voltage?", "--json"],
    "plots": ["plots", "--part", "TEST", "--json"],
    "pins": ["pins", "--part", "TEST", "--json"],
    "regs": ["regs", "--part", "TEST", "--json"],
    "card": ["card", "--part", "TEST", "--card", "power", "--json"],
    "compare": ["compare", "TEST", "OTHER", "--card", "power", "--json"],
    # The two phase-7 verbs are the ones that *may* reach the network, so both
    # are exercised on the branch that cannot: a registry entry carrying no URL
    # (see `_seed_registry`). They report the refusal as JSON on stdout, which
    # is exactly the property this module is about, and open no socket.
    "fetch": ["fetch", "TEST", "--json"],
    "check-revisions": ["check-revisions", "TEST", "--json"],
}


def _seed_registry(settings) -> None:
    """A document registry for TEST whose entry records no URL.

    `dsa fetch` and `dsa check-revisions` both refuse an entry with no URL and
    report the refusal - which keeps this test offline while still driving the
    real `--json` path of both verbs. `built_settings` points `registry_dir` at
    tmp, so nothing here touches the registry checked into the repo.
    """
    from datasheet_analyzer.acquire.registry import (
        DocumentRegistry,
        RegistryDocument,
        RegistryEntry,
        registry_path,
        save_registry,
    )

    registry = DocumentRegistry()
    registry.put(
        RegistryEntry(
            part_number="TEST",
            document=RegistryDocument(url=None, url_reason="no URL has been supplied"),
        )
    )
    save_registry(registry, registry_path(settings.registry_dir))


# --- the mechanism ---------------------------------------------------------


def test_routing_defaults_pymupdf_messages_to_stderr():
    env: dict[str, str] = {}
    cli._route_pymupdf_messages(env)
    assert env["PYMUPDF_MESSAGE"] == "fd:2"


def test_routing_keeps_an_operator_s_own_destination():
    """`setdefault`, not assignment: a deliberate routing survives."""
    env = {"PYMUPDF_MESSAGE": "path:/var/log/mupdf.log"}
    cli._route_pymupdf_messages(env)
    assert env["PYMUPDF_MESSAGE"] == "path:/var/log/mupdf.log"


def test_main_routes_before_dispatching(monkeypatch):
    """The routing must be in force by the time a command function runs.

    Asserted from inside the dispatch, because that is the moment a lazily
    imported `fitz` could first write to stdout.
    """
    monkeypatch.delenv("PYMUPDF_MESSAGE", raising=False)
    seen: list[str | None] = []

    import os

    def spy(_args):
        seen.append(os.environ.get("PYMUPDF_MESSAGE"))
        return 0

    monkeypatch.setattr(cli, "_cmd_status", spy)
    assert cli.main(["status"]) == 0
    assert seen == ["fd:2"]


def test_cli_import_does_not_reach_pymupdf():
    """Routing inside `main()` is only early enough if nothing beat it there.

    `cli.py` imports `config` and `models` eagerly and everything else
    lazily. If a future eager import pulled in `fitz`, the deprecation
    warning would already have been printed before `main()` ran, and the
    routing above would be decoration.
    """
    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    eager = {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in getattr(node, "names", [])
    } | {
        node.module.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "fitz" not in eager and "pymupdf" not in eager


# --- the corroboration -----------------------------------------------------


def test_every_json_verb_is_exercised():
    """The table above must cover every verb the parser gives a `--json`.

    A new verb added without a row here is the failure this catches: the
    guarantee is "every `--json` verb", not "the ones we thought of".
    """
    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    verb_of_var: dict[str, str] = {}
    vars_with_json: set[str] = set()

    def first_literal(call: ast.Call) -> str | None:
        head = call.args[0] if call.args else None
        return (
            head.value if isinstance(head, ast.Constant) and isinstance(head.value, str) else None
        )

    # `p_query = sub.add_parser("query", ...)` binds a verb to a variable.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "add_parser"
        ):
            verb = first_literal(node.value)
            if verb:
                verb_of_var[node.targets[0].id] = verb

    # `p_query.add_argument("--json", ...)` marks that variable's verb.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and isinstance(node.func.value, ast.Name)
            and first_literal(node) == "--json"
        ):
            vars_with_json.add(node.func.value.id)

    declared = {verb_of_var[v] for v in vars_with_json if v in verb_of_var}
    assert declared == set(JSON_INVOCATIONS), (
        f"parser declares --json on {sorted(declared)}; "
        f"this module exercises {sorted(JSON_INVOCATIONS)}"
    )


@pytest.mark.parametrize("verb", sorted(JSON_INVOCATIONS))
def test_json_verb_emits_only_json(verb, tmp_path, monkeypatch, capsys):
    settings = built_settings(tmp_path)
    _seed_registry(settings)
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)

    cli.main(JSON_INVOCATIONS[verb])
    captured = capsys.readouterr()

    payload = json.loads(captured.out)  # the assertion: parses, whole
    assert isinstance(payload, dict)
