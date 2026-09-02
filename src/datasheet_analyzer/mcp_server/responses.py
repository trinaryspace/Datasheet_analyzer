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


def envelope(
    tool: str,
    *,
    max_tokens: int,
    part: str = "",
    project: str = "",
    family: str = "",
    staleness: str = "",
) -> dict:
    """The keys every MCP response carries, whatever the tool.

    `tokens` starts at `max_tokens` as a placeholder and stays that way while
    the payload is fitted, because the field's own width must not change the
    fit. The final value can only be smaller (it is a number ≤ the cap, so it
    can never be wider), which makes the reported `tokens` an honest upper
    bound rather than a figure measured on a payload that no longer exists.

    `staleness` is the corpus's three-state revision reading. It defaults to
    `""` (no corpus in scope) rather than to `current`, so a tool that forgot
    to pass one can only ever under-claim.

    `family` is the third scope, and it rides here rather than in four tool
    bodies for the reason `scope` exists at all — see `_ENVELOPE_PROPS`.
    """
    return {
        "tool": tool,
        "scope": {"part": part, "project": project, "family": family},
        "staleness": staleness or NO_STALENESS,
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
    tool: str,
    message: str,
    *,
    max_tokens: int,
    part: str = "",
    project: str = "",
    family: str = "",
    **body: Any,
) -> dict:
    """A refused call in the declared shape, with the reason in `error`.

    Refusals are payloads, not exceptions, so an agent reads *why* in the same
    structure it reads an answer from — and the empty body says plainly that
    nothing was found, rather than a stack trace implying something broke.

    The refused scope is echoed back on all three names, so a caller that
    named a family reads its own argument in `scope.family` rather than an
    empty object that looks like a call which named nothing.
    """
    payload = envelope(tool, max_tokens=max_tokens, part=part, project=project, family=family)
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

#: Revision freshness of the corpus a response was drawn from (phase 7,
#: ticket 02). It rides the **envelope**, not one tool's body, because a remote
#: agent needs it on whatever call it happens to make - an agent that reads a
#: spec row over MCP and never calls `get_index` would otherwise never learn
#: that the datasheet behind that row has been superseded.
#: One enum, not an object: this field is paid for on **every** response,
#: against the same cap the answer is measured under, so it carries the state
#: and nothing else. The sentence that goes with it is where a caller is
#: already looking - `get_index` returns an `INDEX.md` whose first block is the
#: banner, `ask` returns a pack whose reserved tail is the footer, and
#: `list_parts` shows the state per corpus. Repeating a warning sentence on
#: every `find_spec` would spend the cap restating what the agent read once.
#: `""` means no single corpus was in scope (`list_parts`, `compare_parts`);
#: it is *not* a fourth state and must never be read as `current`.
_STALENESS_SCHEMA = {"enum": ["current", "stale", "unknown", ""]}

#: The reading a response carries when no single corpus is in scope.
NO_STALENESS = ""

_ENVELOPE_PROPS: dict[str, dict] = {
    "tool": _STR,
    #: **All three scopes, on every response.** `retrieve.scope` resolves
    #: `part | project | family`, and a response whose `scope` object could
    #: only name two of them cannot say which one answered: a family lookup
    #: would report `{"part": "", "project": ""}`, the same reading
    #: `compare_parts` returns for *no* corpus in scope. Silently misreporting
    #: the scope of an answer is the one failure this envelope exists to
    #: prevent, so `family` is declared here rather than in the four tool
    #: bodies that can fill it — the alternative writes the same fact in two
    #: places and leaves the generic reading wrong.
    #: The cost was measured rather than argued: `"family": ""` adds **4
    #: tokens** to a 65-token envelope, 0.067 % of the 6000-token cap. The
    #: objection that only some tools can fill it is already true of the two
    #: keys that were here first — `list_projects` can never fill `part`.
    "scope": {
        "type": "object",
        "additionalProperties": False,
        "required": ["part", "project", "family"],
        "properties": {"part": _STR, "project": _STR, "family": _STR},
    },
    "staleness": _STALENESS_SCHEMA,
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
        "symbol",
        "name",
        "conditions",
        "min",
        "typ",
        "max",
        "value",
        "unit",
        "unit_canonical",
        "section",
        "page",
        "part",
        "doc",
        "doc_hash",
        "citation",
        "matched_via",
        "confidence",
    ],
    "properties": {
        "symbol": _STR,
        "name": _STR,
        "conditions": _STR,
        "min": _STR,
        "typ": _STR,
        "max": _STR,
        "value": _STR,
        "unit": _STR,
        "unit_canonical": _STR,
        "section": _STR,
        "page": _INT_OR_NULL,
        "part": _STR,
        "doc": _STR,
        "doc_hash": _STR,
        "citation": _STR,
        "matched_via": _STR,
        "confidence": _CONFIDENCE,
    },
}

_NUM_OR_NULL = {"type": ["number", "null"]}

#: One printed axis of a figure (phase 6, ticket 08). Every field is nullable
#: because an axis this tool could not read stays null and says so through
#: `axes.confidence` — a plausible range is never interpolated.
_AXIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "unit", "min", "max"],
    "properties": {
        "label": _STR,
        "unit": _STR,
        "min": _NUM_OR_NULL,
        "max": _NUM_OR_NULL,
    },
}

#: `PlotHit.as_dict()`.
PLOT_HIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "caption",
        "figure_number",
        "conditions",
        "section",
        "page_start",
        "page_end",
        "part",
        "doc",
        "doc_hash",
        "citation",
        "file",
        "tags",
        "axes",
        "matched_via",
        "confidence",
    ],
    "properties": {
        "id": _STR,
        "caption": _STR,
        "figure_number": _STR,
        "conditions": _STR,
        "section": _STR,
        "page_start": _INT_OR_NULL,
        "page_end": _INT_OR_NULL,
        "part": _STR,
        "doc": _STR,
        "doc_hash": _STR,
        "citation": _STR,
        "file": _STR,
        "tags": {"type": "array", "items": _STR},
        "axes": {
            "type": "object",
            "additionalProperties": False,
            "required": ["x", "y", "confidence"],
            "properties": {
                "x": _AXIS_SCHEMA,
                "y": _AXIS_SCHEMA,
                "confidence": _CONFIDENCE,
            },
        },
        "matched_via": _STR,
        "confidence": _CONFIDENCE,
    },
}

#: `PinHit.as_dict()` — `derive/pins.py` owns the shape, this declares it.
PIN_HIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "pin",
        "name",
        "type",
        "direction",
        "description",
        "type_evidence",
        "expanded_from",
        "part",
        "doc",
        "page",
        "citation",
        "matched_via",
        "confidence",
    ],
    "properties": {
        "id": _STR,
        "pin": _STR,
        "name": _STR,
        "type": _STR,
        "direction": _STR,
        "description": _STR,
        # The lexicon entry behind `type`, and the printed cell a multi-pin row
        # expanded from: a derived label is only usable if it is traceable.
        "type_evidence": _STR,
        "expanded_from": _STR,
        "part": _STR,
        "doc": _STR,
        "page": _INT_OR_NULL,
        "citation": _STR,
        "matched_via": _STR,
        "confidence": _CONFIDENCE,
    },
}

_REGISTER_VALUE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verbatim", "value"],
    "properties": {"verbatim": _STR, "value": _INT_OR_NULL},
}

_BIT_FIELD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "bits", "access", "reset", "description", "page", "confidence"],
    "properties": {
        "name": _STR,
        "bits": {
            "type": "object",
            "additionalProperties": False,
            "required": ["verbatim", "hi", "lo"],
            "properties": {"verbatim": _STR, "hi": _INT_OR_NULL, "lo": _INT_OR_NULL},
        },
        "access": _STR,
        "reset": _STR,
        "description": _STR,
        "page": _INT_OR_NULL,
        "confidence": _CONFIDENCE,
    },
}

#: `RegisterHit.as_dict()`. `fields` is `[]` when no bit breakdown was
#: extracted — which is every published register today (ticket 06 parked); the
#: empty list means "not extracted", and `find_register` says so in `warning`.
REGISTER_HIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "name",
        "block",
        "address",
        "reset",
        "access",
        "width",
        "fields",
        "part",
        "doc",
        "page",
        "citation",
        "matched_via",
        "confidence",
        "address_derivation",
    ],
    "properties": {
        "id": _STR,
        "name": _STR,
        "block": _STR,
        "address": _REGISTER_VALUE_SCHEMA,
        "reset": _REGISTER_VALUE_SCHEMA,
        "access": _STR,
        "width": _INT_OR_NULL,
        "fields": {"type": "array", "items": _BIT_FIELD_SCHEMA},
        "part": _STR,
        "doc": _STR,
        "page": _INT_OR_NULL,
        "citation": _STR,
        "matched_via": _STR,
        "confidence": _CONFIDENCE,
        # The named pure function behind `address.value`, empty when the
        # printed address did not parse (invariant 8: a computed value names
        # the rule that computed it).
        "address_derivation": _STR,
    },
}

#: `models.DerivedValue` — the invariant-8 provenance envelope, and the reason
#: this file declares nested shapes at all. Every number on a card or a
#: comparison ships inside one of these, so a client can check *before reading
#: a value* that it carries a source, a page and the rule that produced it.
DERIVED_VALUE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verbatim",
        "value_si",
        "value_si_hi",
        "unit_si",
        "value_kind",
        "source",
        "sources",
        "page",
        "section",
        "derivation",
        "confidence",
        "null_reason",
    ],
    "properties": {
        "verbatim": _STR,
        "value_si": _NUM_OR_NULL,
        "value_si_hi": _NUM_OR_NULL,
        "unit_si": _STR,
        "value_kind": _STR,
        "source": _STR,
        # The other records a value computed from more than one rests on.
        # `source` stays the primary; an invariant-8 walk resolves all of
        # them, so a consumer that only read `source` would trace half a
        # margin. Empty on every single-source value, which is most of them.
        "sources": {"type": "array", "items": _STR},
        "page": _INT_OR_NULL,
        # The printed section number the source record sits in, so a value
        # cites as `§4.1, p.4` without the reader re-opening the record.
        "section": _STR,
        "derivation": _STR,
        "confidence": _CONFIDENCE,
        # Why a field is empty, which invariant 8 requires of every unfilled
        # value: a card leaves a field null and *says so*.
        "null_reason": _STR,
    },
}

#: One row of a design card. `values` is keyed by column name — the columns
#: differ per card — so it is declared as a map whose every value is a
#: provenance envelope.
CARD_ROW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "symbol", "note", "flags", "citation", "values"],
    "properties": {
        "label": _STR,
        "symbol": _STR,
        "note": _STR,
        "flags": {"type": "array", "items": _STR},
        "citation": _STR,
        "values": {"type": "object", "additionalProperties": DERIVED_VALUE_SCHEMA},
    },
}

_COMPARE_CELL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "part",
        "label",
        "symbol",
        "note",
        "conditions",
        "page",
        "citation",
        "values",
    ],
    "properties": {
        "part": _STR,
        "label": _STR,
        "symbol": _STR,
        "note": _STR,
        "conditions": _STR,
        "page": _INT_OR_NULL,
        "citation": _STR,
        "values": {"type": "object", "additionalProperties": DERIVED_VALUE_SCHEMA},
    },
}

_COMPARE_DELTA_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "cell",
        "baseline",
        "part",
        "value",
        "baseline_source",
        "baseline_page",
    ],
    "properties": {
        "cell": _STR,
        "baseline": _STR,
        "part": _STR,
        "value": DERIVED_VALUE_SCHEMA,
        "baseline_source": _STR,
        "baseline_page": _INT_OR_NULL,
    },
}

#: One aligned row of a cross-part comparison. `status` and the three name
#: lists are what make a row honest: a parameter one part prints and another
#: does not is reported as such, never silently dropped.
COMPARE_ROW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "key",
        "label",
        "symbol",
        "matched_on",
        "status",
        "citation",
        "cells",
        "deltas",
        "present_in",
        "missing_from",
        "not_comparable",
        "flags",
    ],
    "properties": {
        "key": _STR,
        "label": _STR,
        "symbol": _STR,
        "matched_on": _STR,
        "status": _STR,
        "citation": _STR,
        "cells": {"type": "array", "items": _COMPARE_CELL_SCHEMA},
        "deltas": {"type": "array", "items": _COMPARE_DELTA_SCHEMA},
        "present_in": {"type": "array", "items": _STR},
        "missing_from": {"type": "array", "items": _STR},
        "not_comparable": {"type": "array", "items": _STR},
        "flags": {"type": "array", "items": _STR},
    },
}

_COMPARE_COVERAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["considered", "compared", "reasons"],
    "properties": {
        "considered": {"type": "integer"},
        "compared": {"type": "integer"},
        "reasons": {"type": "array", "items": _STR},
    },
}

#: The unparsed population, per part — the number a comparison must report
#: rather than quietly drop ("3 of 47 rows could not be parsed").
_PARSE_COVERAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["part", "considered", "parsed", "unparsed"],
    "properties": {
        "part": _STR,
        "considered": {"type": "integer"},
        "parsed": {"type": "integer"},
        "unparsed": {"type": "array", "items": _STR},
    },
}

#: `SearchHit.as_dict()`.
SEARCH_HIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "section",
        "title",
        "file",
        "part",
        "doc",
        "doc_hash",
        "page_start",
        "page_end",
        "citation",
        "score",
        "snippet",
        "terms",
        "matched_via",
        "confidence",
    ],
    "properties": {
        "section": _STR,
        "title": _STR,
        "file": _STR,
        "part": _STR,
        "doc": _STR,
        "doc_hash": _STR,
        "page_start": _INT_OR_NULL,
        "page_end": _INT_OR_NULL,
        "citation": _STR,
        "score": {"type": "number"},
        "snippet": _STR,
        "terms": {"type": "array", "items": _STR},
        "matched_via": _STR,
        "confidence": _CONFIDENCE,
    },
}

_PART_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "part",
        "built",
        "revision",
        "vendor",
        "backends",
        "sections",
        "specs",
        "plots",
        "tokens",
        "searchable",
        "spec_confidence",
        "plot_confidence",
        "staleness",
    ],
    "properties": {
        "part": _STR,
        "built": {"type": "boolean"},
        "revision": _STR,
        "vendor": _STR,
        "backends": {"type": "array", "items": _STR},
        "sections": {"type": "integer"},
        "specs": {"type": "integer"},
        "plots": {"type": "integer"},
        "tokens": {"type": "integer"},
        "searchable": {"type": "boolean"},
        "spec_confidence": {"type": "object"},
        "plot_confidence": {"type": "object"},
        # A part row is always one corpus, so `""` is not among its states.
        "staleness": {"enum": ["current", "stale", "unknown"]},
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

#: One graded reading off `dsa audit` (phase 7, ticket 05). `value`, `grade`,
#: `numerator` and `denominator` are all nullable because "could not measure"
#: is a first-class outcome here: a metric the corpus cannot answer carries
#: `available: false` and a reason, and is excluded from the overall letter
#: rather than scored `0` (which would defame it) or full marks (which would
#: flatter it). `source` and `derivation` ride every reading for the reason
#: invariant 8 requires them on every derived value.
_AUDIT_METRIC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "key",
        "label",
        "kind",
        "value",
        "state",
        "numerator",
        "denominator",
        "grade",
        "weight",
        "available",
        "unavailable_reason",
        "detail",
        "source",
        "derivation",
    ],
    "properties": {
        "key": _STR,
        "label": _STR,
        "kind": {"enum": ["ratio", "boolean", "state"]},
        "value": {"type": ["number", "null"]},
        "state": _STR,
        "numerator": _INT_OR_NULL,
        "denominator": _INT_OR_NULL,
        "grade": {"enum": ["A", "B", "C", "D", "F", None]},
        "weight": {"type": "number"},
        "available": {"type": "boolean"},
        "unavailable_reason": _STR,
        "detail": _STR,
        "source": _STR,
        "derivation": _STR,
    },
}

#: One declared member of a family, as `list_families` reports it. `built`
#: is the same fact `list_projects` reports per member and for the same
#: reason: a series whose members are not all built answers for the ones that
#: are, and the caller has to be able to see which those were.
_FAMILY_MEMBER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["part", "built"],
    "properties": {"part": _STR, "built": {"type": "boolean"}},
}

#: One declared family. `confirmed` is always `true` here — `list_families`
#: reads `registry/families.yaml`, and an unconfirmed grouping lives in the
#: candidate file, which this server never reads — but it is carried anyway so
#: a client reads the fact rather than inferring it from which tool answered.
_FAMILY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "title", "members", "reference", "confirmed", "note", "built"],
    "properties": {
        "name": _STR,
        "title": _STR,
        "members": {"type": "array", "items": _FAMILY_MEMBER_SCHEMA},
        "reference": _STR,
        "confirmed": {"type": "boolean"},
        "note": _STR,
        "built": {"type": "boolean"},
    },
}

_FIGURE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "part",
        "file",
        "mime_type",
        "bytes",
        "id",
        "caption",
        "figure_number",
        "section",
        "page_start",
        "page_end",
        "citation",
        "confidence",
    ],
    "properties": {
        "part": _STR,
        "file": _STR,
        "mime_type": _STR,
        "bytes": {"type": "integer"},
        "id": _STR,
        "caption": _STR,
        "figure_number": _STR,
        "section": _STR,
        "page_start": _INT_OR_NULL,
        "page_end": _INT_OR_NULL,
        "citation": _STR,
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
    # Phase 7. A family is the third scope `retrieve.scope` resolves, and these
    # two are its catalog and its map — `list_families` is `list_projects` one
    # noun across, and `get_family_index` is `get_index` one noun across.
    # `get_family_index` names its family **twice, deliberately**: once on the
    # envelope's `scope.family`, which is where a caller reads what answered
    # whatever tool it called, and once in its own body, which is this tool's
    # subject and reports the *resolved*, canonical name rather than the string
    # the caller typed. `list_families` fills neither: its subject is every
    # family, so an empty `scope` is the honest reading there, the same one
    # `list_parts` and `compare_parts` carry.
    "list_families": _schema({"families": {"type": "array", "items": _FAMILY_SCHEMA}}, listed=True),
    "get_family_index": _schema(
        {
            "family": _STR,
            "title": _STR,
            "members": {"type": "array", "items": _STR},
            "reference": _STR,
            "unbuilt": {"type": "array", "items": _STR},
            "file": _STR,
            "n_sections": {"type": "integer"},
            "n_shared_sections": {"type": "integer"},
            "n_deltas": {"type": "integer"},
            "n_specs_aligned": {"type": "integer"},
            "n_specs_identical": {"type": "integer"},
            "schema_version": _STR,
            "text": _STR,
        }
    ),
    # `dsa audit`, one call across. The metrics list is the body a cap sheds
    # from; `grade`, `score`, `banner` and `headline` are the floor, because a
    # scorecard that lost its headline has lost the sentence it exists to
    # produce.
    "get_audit": _schema(
        {
            "grade": {"enum": ["A", "B", "C", "D", "F", None]},
            "score": {"type": ["number", "null"]},
            "rubric_version": _STR,
            "schema_version": _STR,
            "metrics": {"type": "array", "items": _AUDIT_METRIC_SCHEMA},
            "n_graded": {"type": "integer"},
            "n_unavailable": {"type": "integer"},
            "unavailable_policy": _STR,
            "banner": _STR,
            "headline": _STR,
            "notes": {"type": "array", "items": _STR},
        },
        listed=True,
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
    # Phase 6. Each names the parts that published no such artifact, because
    # "this part has no pins" and "no pin table was published for this part"
    # are different findings and only one of them is ever true.
    "find_pin": _schema(
        {
            "hits": {"type": "array", "items": PIN_HIT_SCHEMA},
            "counts": {"type": "object", "additionalProperties": {"type": "integer"}},
            "parts_without_pins": {"type": "array", "items": _STR},
        },
        listed=True,
    ),
    "find_register": _schema(
        {
            "hits": {"type": "array", "items": REGISTER_HIT_SCHEMA},
            "parts_without_registers": {"type": "array", "items": _STR},
            "bit_fields": {"type": "boolean"},
        },
        listed=True,
    ),
    "get_card": _schema(
        {
            "card": _STR,
            "card_version": _STR,
            "schema_version": _STR,
            "generated_at": _STR,
            "rows": {"type": "array", "items": CARD_ROW_SCHEMA},
            # What the card could not do, carried with what it could: records
            # whose citation would not resolve, and the reasons.
            "unresolved": {"type": "array", "items": _STR},
            "warnings": {"type": "array", "items": _STR},
            "sources": {"type": "array", "items": _STR},
        },
        listed=True,
    ),
    "compare_parts": _schema(
        {
            "parts": {"type": "array", "items": _STR},
            "baseline": _STR,
            "mode": _STR,
            "card": _STR,
            "symbol": _STR,
            "resolved_symbol": _STR,
            "schema_version": _STR,
            "generated_at": _STR,
            "rows": {"type": "array", "items": COMPARE_ROW_SCHEMA},
            "coverage": _COMPARE_COVERAGE_SCHEMA,
            "parse_coverage": {"type": "array", "items": _PARSE_COVERAGE_SCHEMA},
            "unresolved": {"type": "array", "items": _STR},
            "warnings": {"type": "array", "items": _STR},
        },
        listed=True,
    ),
    "read_section": _schema(
        {
            "section": _STR,
            "title": _STR,
            "file": _STR,
            "page_start": _INT_OR_NULL,
            "page_end": _INT_OR_NULL,
            "citation": _STR,
            "confidence": _CONFIDENCE,
            "matched_via": _STR,
            "text": _STR,
        }
    ),
    "get_figure": _schema({"figure": {"anyOf": [_FIGURE_SCHEMA, {"type": "null"}]}}),
    "ask": _schema({"pack": {"anyOf": [ANSWER_PACK_SCHEMA, {"type": "null"}]}}),
}


# --- derived-artifact bodies -------------------------------------------------
#
# A card and a comparison are pydantic models, not hits, so there is no
# `as_dict()` to reuse; these are the two places their model becomes a
# response body. They live here, beside the schemas that declare them, and
# they add exactly one thing the model does not carry: the **citation string**
# a reader verifies a row by. It is never assembled here — `Citation.label`
# and `derive.cards.row_citation` are the only two things that turn a page
# number into a printed citation anywhere in this project.


def card_rows(card: Any) -> list[dict]:
    """One design card's rows, each carrying its own citation.

    `values` stays keyed by column name (the model's own shape, and the reason
    one model serves four cards); every value is the full provenance envelope,
    unabridged — a card cell without its `source` and `derivation` is exactly
    the thing invariant 8 exists to prevent shipping.
    """
    from datasheet_analyzer.derive.cards import row_citation

    return [
        {
            "label": row.label,
            "symbol": row.symbol,
            "note": row.note,
            "flags": list(row.flags),
            "citation": row_citation(row),
            "values": {
                column: value.model_dump(mode="json") for column, value in row.values.items()
            },
        }
        for row in card.rows
    ]


def comparison_rows(comparison: Any) -> list[dict]:
    """One comparison's rows: a cell per part, in the order the call named them.

    The model keys its cells by part; the response lists them, so the columns
    of a row arrive in a defined order and a client does not have to re-derive
    it from `parts`. A part that did not print the parameter contributes no
    cell and is named in `missing_from` — the row says so rather than showing
    a blank that reads like a zero.
    """
    from datasheet_analyzer.retrieve import Citation

    def cited(page: int | None, part: str) -> str:
        return Citation(part=part, page_start=page, page_end=page).label if page else ""

    rows: list[dict] = []
    for row in comparison.rows:
        cells: list[dict] = []
        for part in comparison.parts:
            cell = row.cells.get(part)
            if cell is None:
                continue
            cells.append(
                {
                    "part": cell.part_number,
                    "label": cell.label,
                    "symbol": cell.symbol,
                    "note": cell.note,
                    "conditions": cell.conditions,
                    "page": cell.page,
                    "citation": cited(cell.page, cell.part_number),
                    "values": {
                        column: value.model_dump(mode="json")
                        for column, value in cell.values.items()
                    },
                }
            )
        rows.append(
            {
                "key": row.key,
                "label": row.label,
                "symbol": row.symbol,
                "matched_on": row.matched_on,
                "status": row.status,
                # The row's citation is every page it drew on: a comparison row
                # is only checkable if each side can be opened.
                "citation": ", ".join(dict.fromkeys(c["citation"] for c in cells if c["citation"])),
                "cells": cells,
                "deltas": [
                    {
                        "cell": delta.cell,
                        "baseline": delta.baseline,
                        "part": delta.part_number,
                        "value": delta.value.model_dump(mode="json"),
                        "baseline_source": delta.baseline_source,
                        "baseline_page": delta.baseline_page,
                    }
                    for delta in row.deltas
                ],
                "present_in": list(row.present_in),
                "missing_from": list(row.missing_from),
                "not_comparable": list(row.not_comparable),
                "flags": list(row.flags),
            }
        )
    return rows


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
