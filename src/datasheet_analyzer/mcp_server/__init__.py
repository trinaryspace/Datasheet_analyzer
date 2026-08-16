"""Local stdio MCP server over the retrieval core (`dsa serve --mcp`).

The `mcp` SDK is an **optional extra** (`pip install -e ".[mcp]"`), so this
package must stay importable without it: `responses` — the envelope, the
declared schemas and the response cap — imports nothing from the SDK, and
`server` is loaded only when something actually asks for it. That is why the
two public entry points below arrive through a module `__getattr__` rather
than a top-level import: a core install that never runs the server never pays
for it, and `dsa serve --mcp` on a core install gets a clean `ImportError`
that `cli.py` turns into an install hint.
"""

from __future__ import annotations

from typing import Any

from datasheet_analyzer.mcp_server.responses import (
    CAP_SETTING,
    SCHEMAS,
    response_tokens,
    validate_response,
)

_LAZY = {"build_server", "serve_stdio", "SERVER_NAME", "PART_INDEX_URI", "PROJECT_INDEX_URI"}

__all__ = [
    "CAP_SETTING",
    "PART_INDEX_URI",
    "PROJECT_INDEX_URI",
    "SCHEMAS",
    "SERVER_NAME",
    "build_server",
    "response_tokens",
    "serve_stdio",
    "validate_response",
]


def __getattr__(name: str) -> Any:
    """Load the SDK-backed server on first use, never at import time."""
    import importlib

    if name == "server":
        return importlib.import_module("datasheet_analyzer.mcp_server.server")
    if name in _LAZY:
        return getattr(importlib.import_module("datasheet_analyzer.mcp_server.server"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
