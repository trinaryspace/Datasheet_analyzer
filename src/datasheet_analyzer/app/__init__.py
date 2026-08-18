"""The local GUI backend: a thin FastAPI adapter over `retrieve/`.

The third front end beside `cli.py` and `mcp_server/`, and held to the same
rule: no retrieval logic, no citation formatting, and no JSON shapes of its
own. Result shapes come from `retrieve/` and each hit's `as_dict()`; every
citation comes from a `Citation`.

Module map:

| Module | Ticket | What lives there |
|---|---|---|
| `contracts.py` | 00 | every request/response model + the endpoint table |
| `main.py` | 00 | `create_app()` and router auto-discovery |
| `routers/*.py` | 06–15 | one module per endpoint group, each exposing `router` |
| `deps.py` | 06 | the FastAPI `Depends` providers |
| `static.py` | 06 | serves the built frontend from `web/dist` |
| `jobs.py` | 07 | the process-wide analyze `JobRegistry` |
| `scope_resolver.py` | 10 | question -> exactly one Part or Project |
| `tools.py` | 11 | the nine agent tool callables |
| `chat.py` | 12 | the Anthropic tool-runner loop |
| `locate.py` | 13 | citation -> highlight rectangles |
| `sessions.py` | 15 | `SessionStore` and the exports |

Importing this package pulls in nothing heavy: `contracts.py` is pure
pydantic (so `acquire/` can import `DocProposal` without the web extra) and
FastAPI is only imported by `main.py` and the routers.
"""

from __future__ import annotations

__all__: list[str] = []
