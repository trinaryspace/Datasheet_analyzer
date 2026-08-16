"""Driving the MCP server in-process, over the SDK's memory transport.

Not a test module — the harness two suites share. `tests/unit/test_mcp_server.py`
exercises the whole tool surface against a synthetic corpus; the phase-5 gate
(`tests/integration/test_phase4_layout_gate.py`) exercises it against four real
datasheets. One harness, so "in-process" means the same thing in both: a real
`ClientSession` talking to the real server over in-memory streams — no
subprocess, no port, hermetic per invariant #4.

Every function here imports the `mcp` SDK lazily. The SDK is an optional extra,
and a module-level import would turn a lean install into a **collection error**
that disables every other test — the same rule `tests/unit/test_mcp_responses.py`
exists to keep.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager


@asynccontextmanager
async def connected(server):
    """A real `ClientSession` wired to `server` over the SDK's memory streams."""
    import anyio
    from mcp import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        low = server._lowlevel_server
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: low.run(
                    server_read,
                    server_write,
                    low.create_initialization_options(),
                    raise_exceptions=True,
                )
            )
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                yield session
            tg.cancel_scope.cancel()


def over_session(server, work):
    """Run `work(session)` against `server` over the memory transport."""

    async def _run():
        async with connected(server) as session:
            return await work(session)

    return asyncio.run(_run())


def call(server, tool: str, **arguments):
    """One tool call, over the memory transport, returning the raw result."""

    async def _work(session):
        return await session.call_tool(tool, arguments)

    return over_session(server, _work)


def payload_of(result) -> dict:
    """The declared JSON payload of a tool result.

    Read from the structured content when the SDK carried it, and otherwise
    parsed out of the text block — `get_figure` returns content blocks by hand
    because one of them is an image.
    """
    from mcp.types import TextContent

    if result.structured_content is not None:
        return result.structured_content
    text = next(c for c in result.content if isinstance(c, TextContent))
    return json.loads(text.text)
