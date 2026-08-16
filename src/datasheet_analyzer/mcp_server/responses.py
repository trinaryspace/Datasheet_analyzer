"""MCP response shapes: the envelope, the declared schemas, the response cap.

This module deliberately imports **nothing from the `mcp` SDK**. Two reasons,
both load-bearing:

- the `[mcp]` extra is optional, and the rule that bounds a response must not
  become unavailable — or untestable — when the SDK is not installed;
- the cap is a *product* decision (a client cannot bound a payload it did not
  build), not a transport detail, so it belongs beside the shapes it bounds
  rather than inside the adapter that ships them.

**Every response is capped at `DSA_MCP_MAX_TOKENS` (default 6000) and every
truncation is announced.** The rule is the answer pack's rule one level up:
what a cap removes is extra *rows*, never a citation — list bodies are filled
greedily in retrieval order and stop, text bodies are trimmed to what remains,
and the notice names the setting that would raise the limit. Silent loss is
the one failure an agent cannot detect, so it is the one failure that must not
exist here.

One exception is stated rather than hidden: an **image block is atomic**, the
same way a table is. Base64 pixels are not prose, and trimming them produces a
corrupt PNG instead of a shorter one, so `get_figure`'s image content block is
not measured against the token cap — only the JSON payload that cites it is.
The payload reports the image's byte size so a caller can decide for itself.

`SCHEMAS` is the declared shape of each tool's payload, checked by
`validate_response`. The checker is `retrieve.pack.validate_pack`, reused
rather than rewritten: the answer pack already needed a dependency-free
JSON-Schema subset, and having two of them is how two shapes start to drift.
"""

from __future__ import annotations

import json
from typing import Any

from datasheet_analyzer.retrieve import ANSWER_PACK_SCHEMA, validate_pack
from datasheet_analyzer.tokens import count_tokens, truncate_to_tokens

#: The setting every truncation notice names. A notice that does not say how
#: to see the rest is only half a notice.
CAP_SETTING = "DSA_MCP_MAX_TOKENS"

_CAP_NOTICE = (
    "Truncated to fit the {cap}-token response cap — raise {setting} to see "
    "the rest, or narrow the query."
)
_ARG_NOTICE = (
    "Truncated to fit max_tokens={requested} — raise it (up to the "
    "{setting}={cap} response cap) to see the rest."
)
_FLOOR_NOTICE = (
    "A {cap}-token cap ({setting}) is below this response's citation floor; "
    "the answer and its citation are kept regardless."
)
#: Lowest `dsa ask` budget the cap ladder will fall to before it gives up and
#: reports `over_cap`. Below this a pack is nothing but its reserved tail.
ASK_BUDGET_FLOOR = 200


def response_tokens(payload: dict) -> int:
    """Size of a payload as the client will receive it.

    Measured over the same indented JSON the SDK renders into the response's
    text content block, so the number the cap is enforced on is the number the
    caller pays — not a prettier one measured over a compact dump.
    """
    return count_tokens(json.dumps(payload, ensure_ascii=False, indent=2))


def envelope(tool: str, *, max_tokens: int, part: str = "", project: str = "") -> dict:
    """The keys every MCP response carries, whatever the tool.

    `tokens` starts at `max_tokens` as a placeholder and stays that way while
    the payload is fitted, because the field's own width must not change the
    fit. The final value can only be smaller (it is a number ≤ the cap, so it
    can never be wider), which makes the reported `tokens` an honest upper
    bound rather than a figure measured on a payload that no longer exists.
    """
    return {
        "tool": tool,
        "scope": {"part": part, "project": project},
        "error": "",
        # `error` means the call could not be answered; `warning` means it was
        # answered but something about the result is incomplete (a project
        # member with no search index, say). Conflating the two is how an
        # agent ends up reporting a gap as an absence.
        "warning": "",
        "max_tokens": max_tokens,
        "tokens": max_tokens,
        "truncated": False,
        "over_cap": False,
        "notice": "",
        "citations": [],
    }


def error_response(
    tool: str, message: str, *, max_tokens: int, part: str = "", project: str = "", **body: Any
) -> dict:
    """A refused call in the declared shape, with the reason in `error`.

    Refusals are payloads, not exceptions, so an agent reads *why* in the same
    structure it reads an answer from — and the empty body says plainly that
    nothing was found, rather than a stack trace implying something broke.
    """
    payload = envelope(tool, max_tokens=max_tokens, part=part, project=project)
    payload["error"] = message
    payload.update(body)
    return finalize(payload, max_tokens)


def finalize(payload: dict, max_tokens: int) -> dict:
    """Stamp the measured size and whether the payload still exceeds the cap."""
    measured = response_tokens(payload)
    payload["over_cap"] = measured > max_tokens
    if payload["over_cap"] and not payload["notice"]:
        payload["notice"] = _FLOOR_NOTICE.format(cap=max_tokens, setting=CAP_SETTING)
        measured = response_tokens(payload)
    payload["tokens"] = measured
    return payload


def fit_list(payload: dict, key: str, max_tokens: int) -> dict:
    """Fill `payload[key]` greedily in retrieval order until the cap bites.

    Retrieval order *is* score order everywhere in this project, so filling
    from the front and stopping at the first item that does not fit keeps the
    best hits and drops the weakest — and each surviving hit keeps its own
    citation, because a hit is dropped whole or not at all.
    """
    items = list(payload.get(key) or [])

    def fill(notice: str) -> list:
        kept: list = []
        for item in items:
            if response_tokens(_shaped(payload, key, items, [*kept, item], notice)) <= max_tokens:
                kept.append(item)
            else:
                break  # retrieval order is score order: after a miss, stop
        return kept

    kept = fill("")
    notice = ""
    if len(kept) < len(items):
        # One re-fit, not a loop: the notice text depends only on the cap, so
        # adding it can shrink the fill but can never change its own text.
        notice = _CAP_NOTICE.format(cap=max_tokens, setting=CAP_SETTING)
        kept = fill(notice)
    return finalize(_shaped(payload, key, items, kept, notice), max_tokens)


def fit_text(payload: dict, key: str, max_tokens: int, *, requested: int = 0) -> dict:
    """Trim `payload[key]` to the binding limit and announce it if trimmed.

    Two limits can bind, and they bind different things:

    - the caller's own `max_tokens` argument bounds **the text it asked for**.
      It is a reading budget, not a wire budget: the citation, the page range
      and the section heading are the reserved tail here, exactly as they are
      in an answer pack, and a budget must never be paid for by deleting the
      provenance of the thing it bounded.
    - `DSA_MCP_MAX_TOKENS` bounds **the whole response**, because that is what
      lands in the caller's context.

    Whichever bit, the notice names it, so a caller that asked for 500 tokens
    is never told to raise a 6000-token setting it never reached.
    """
    text = payload.get(key) or ""

    def shaped(body: str, notice: str) -> dict:
        out = dict(payload)
        out[key] = body
        out["notice"] = notice
        out["truncated"] = bool(notice)
        return out

    notice = ""
    if requested > 0 and count_tokens(text) > requested:
        text = truncate_to_tokens(text, requested)
        notice = _ARG_NOTICE.format(requested=requested, cap=max_tokens, setting=CAP_SETTING)

    if response_tokens(shaped(text, notice)) > max_tokens:
        notice = _CAP_NOTICE.format(cap=max_tokens, setting=CAP_SETTING)
        room = max_tokens - response_tokens(shaped("", notice))
        text = truncate_to_tokens(text, room)
        # JSON escaping (a newline is two characters on the wire, a quote is
        # two) makes an encoded body longer than the text it holds, so the
        # estimate is corrected against the real payload rather than trusted.
        while text and response_tokens(shaped(text, notice)) > max_tokens:
            room -= 1
            text = truncate_to_tokens(text, room)

    return finalize(shaped(text, notice), max_tokens)


def capped_markdown(text: str, max_tokens: int) -> str:
    """A resource body under the cap, with the notice appended when it bit.

    Resources hand a client raw markdown rather than a payload, so the notice
    has to travel *in* the text. It still names the setting, because a pinned
    index that quietly lost its last section is exactly the silent loss this
    server refuses to ship.
    """
    if count_tokens(text) <= max_tokens:
        return text
    notice = "\n\n_" + _CAP_NOTICE.format(cap=max_tokens, setting=CAP_SETTING) + "_\n"
    return truncate_to_tokens(text, max_tokens - count_tokens(notice)) + notice


def _shaped(payload: dict, key: str, items: list, kept: list, notice: str) -> dict:
    """The payload as it would look carrying `kept` — the unit the cap measures."""
    out = dict(payload)
    out[key] = kept
    out["total"] = len(items)
    out["count"] = len(kept)
    out["citations"] = citations_of(kept)
    out["notice"] = notice
    out["truncated"] = bool(notice)
    return out


def citations_of(items: list) -> list[str]:
    """Every citation the returned items carry, in order, de-duplicated.

    Hoisted to the envelope so a caller can check "is this response cited?"
    without walking a body whose shape differs per tool. Items that are not
    corpus findings (a part listing, a project listing) contribute none, and
    the empty list is the honest answer there rather than a fabricated one.
    """
    out: list[str] = []
    for item in items:
        cite = item.get("citation", "") if isinstance(item, dict) else ""
        if cite and cite not in out:
            out.append(cite)
    return out


# --- declared shapes ---------------------------------------------------------

_CONFIDENCE = {"enum": ["high", "medium", "low", "unknown"]}
_STR = {"type": "string"}
_INT_OR_NULL = {"type": ["integer", "null"]}

_ENVELOPE_PROPS: dict[str, dict] = {
    "tool": _STR,
    "scope": {
        "type": "object",
        "additionalProperties": False,
        "required": ["part", "project"],
        "properties": {"part": _STR, "project": _STR},
    },
    "error": _STR,
    "warning": _STR,
    "max_tokens": {"type": "integer"},
    "tokens": {"type": "integer"},
    "truncated": {"type": "boolean"},
    "over_cap": {"type": "boolean"},
    "notice": _STR,
    "citations": {"type": "array", "items": _STR},
}
_LIST_PROPS: dict[str, dict] = {"count": {"type": "integer"}, "total": {"type": "integer"}}

#: `SpecHit.as_dict()` — declared here, asserted against the real hit in
#: `tests/unit/test_mcp_server.py` so the two cannot drift apart.
SPEC_HIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "symbol", "name", "conditions", "min", "typ", "max", "value", "unit",
        "unit_canonical", "section", "page", "part", "doc", "citation",
        "matched_via", "confidence",
    ],
    "properties": {
        "symbol": _STR, "name": _STR, "conditions": _STR, "min": _STR, "typ": _STR,
        "max": _STR, "value": _STR, "unit": _STR, "unit_canonical": _STR,
        "section": _STR, "page": _INT_OR_NULL, "part": _STR, "doc": _STR,
        "citation": _STR, "matched_via": _STR, "confidence": _CONFIDENCE,
    },
}

#: `PlotHit.as_dict()`.
PLOT_HIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id", "caption", "figure_number", "conditions", "section", "page_start",
        "page_end", "part", "doc", "citation", "file", "tags", "matched_via",
        "confidence",
    ],
    "properties": {
        "id": _STR, "caption": _STR, "figure_number": _STR, "conditions": _STR,
        "section": _STR, "page_start": _INT_OR_NULL, "page_end": _INT_OR_NULL,
        "part": _STR, "doc": _STR, "citation": _STR, "file": _STR,
        "tags": {"type": "array", "items": _STR}, "matched_via": _STR,
        "confidence": _CONFIDENCE,
    },
}

#: `SearchHit.as_dict()`.
SEARCH_HIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "section", "title", "file", "part", "doc", "page_start", "page_end",
        "citation", "score", "snippet", "terms", "matched_via", "confidence",
    ],
    "properties": {
        "section": _STR, "title": _STR, "file": _STR, "part": _STR, "doc": _STR,
        "page_start": _INT_OR_NULL, "page_end": _INT_OR_NULL, "citation": _STR,
        "score": {"type": "number"}, "snippet": _STR,
        "terms": {"type": "array", "items": _STR}, "matched_via": _STR,
        "confidence": _CONFIDENCE,
    },
}

_PART_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "part", "built", "revision", "vendor", "backends", "sections", "specs",
        "plots", "tokens", "searchable", "spec_confidence", "plot_confidence",
    ],
    "properties": {
        "part": _STR, "built": {"type": "boolean"}, "revision": _STR, "vendor": _STR,
        "backends": {"type": "array", "items": _STR},
        "sections": {"type": "integer"}, "specs": {"type": "integer"},
        "plots": {"type": "integer"}, "tokens": {"type": "integer"},
        "searchable": {"type": "boolean"},
        "spec_confidence": {"type": "object"}, "plot_confidence": {"type": "object"},
    },
}

_PROJECT_MEMBER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["part", "role", "built"],
    "properties": {"part": _STR, "role": _STR, "built": {"type": "boolean"}},
}

_PROJECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "parts", "interfaces", "built", "error"],
    "properties": {
        "name": _STR,
        "parts": {"type": "array", "items": _PROJECT_MEMBER_SCHEMA},
        "interfaces": _STR,
        "built": {"type": "boolean"},
        "error": _STR,
    },
}

_FIGURE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "part", "file", "mime_type", "bytes", "id", "caption", "figure_number",
        "section", "page_start", "page_end", "citation", "confidence",
    ],
    "properties": {
        "part": _STR, "file": _STR, "mime_type": _STR, "bytes": {"type": "integer"},
        "id": _STR, "caption": _STR, "figure_number": _STR, "section": _STR,
        "page_start": _INT_OR_NULL, "page_end": _INT_OR_NULL, "citation": _STR,
        "confidence": _CONFIDENCE,
    },
}


def _schema(body: dict[str, dict], *, listed: bool = False) -> dict:
    """One tool's declared payload: the envelope plus its own body keys."""
    props = {**_ENVELOPE_PROPS, **(_LIST_PROPS if listed else {}), **body}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": list(props),
        "properties": props,
    }


#: The declared response shape of every tool, by tool name. Shipped to clients
#: in each tool's `_meta` (see `server.build_server`) so the contract travels
#: with the tool instead of living only in this repo's tests.
SCHEMAS: dict[str, dict] = {
    "list_parts": _schema({"parts": {"type": "array", "items": _PART_SCHEMA}}, listed=True),
    "list_projects": _schema(
        {"projects": {"type": "array", "items": _PROJECT_SCHEMA}}, listed=True
    ),
    # No `part` key of their own: the envelope's `scope.part` already names it,
    # and one fact in two places is one fact that can disagree with itself.
    "get_index": _schema({"revision": _STR, "file": _STR, "text": _STR}),
    "search": _schema({"hits": {"type": "array", "items": SEARCH_HIT_SCHEMA}}, listed=True),
    "find_spec": _schema(
        {
            "hits": {"type": "array", "items": SPEC_HIT_SCHEMA},
            "suggestions": {"type": "array", "items": _STR},
        },
        listed=True,
    ),
    "find_plots": _schema({"hits": {"type": "array", "items": PLOT_HIT_SCHEMA}}, listed=True),
    "read_section": _schema(
        {
            "section": _STR, "title": _STR, "file": _STR,
            "page_start": _INT_OR_NULL, "page_end": _INT_OR_NULL, "citation": _STR,
            "confidence": _CONFIDENCE, "matched_via": _STR, "text": _STR,
        }
    ),
    "get_figure": _schema({"figure": {"anyOf": [_FIGURE_SCHEMA, {"type": "null"}]}}),
    "ask": _schema({"pack": {"anyOf": [ANSWER_PACK_SCHEMA, {"type": "null"}]}}),
}


def validate_response(payload: object, tool: str) -> list[str]:
    """Check a payload against `SCHEMAS[tool]`; `[]` means it validates.

    Deliberately the answer pack's checker (`validate_pack`), not a second
    one: the dependency-free JSON-Schema subset already exists, and two
    validators is how two contracts start disagreeing about what "valid" is.
    """
    schema = SCHEMAS.get(tool)
    if schema is None:
        return [f"$: no declared schema for tool {tool!r}"]
    return validate_pack(payload, schema)
