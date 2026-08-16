# 0006 — Scope is auto-resolved and shown, never defaulted to everything

Retrieval refuses an "all parts" scope on purpose. `scope` is not a type but a
mutually-exclusive `part`/`project` pair, XOR-enforced in both the CLI and the
MCP server, and the rejection carries its own rationale: "a lookup has to know
what it is asking, and defaulting to 'everything' would make the scope of an
answer implicit." The GUI's premise runs the other way — point at a directory,
analyze it, then ask questions — which is library-wide by default. Left
unresolved, that collision has only two bad endings: a Library scope that
overturns a considered invariant, or a scope picker that makes the user perform
routing the application is perfectly able to do.

Scope is instead **resolved, displayed, and editable**. A question is matched
against the known built parts and project names to resolve exactly one Part or
Project scope; the resolved scope is rendered as a control attached to the
answer, so the reader always sees what the answer was drawn from and can change
it and re-ask. Ambiguity produces a question to the user, never a guess, and
there is no fallback that widens to everything. This satisfies the invariant as
written — the scope of an answer is never implicit, because it is on screen —
while keeping the interaction the application exists to provide.

Hard to reverse: scope is read by every retrieval path and stamped into every
citation, so a later "all parts" mode would mean re-deciding what a citation
without a part means, and re-deciding it after users have saved sessions.
Surprising without context: a future reader meets a UI that answers
apparently-library-wide questions sitting on a codebase whose error strings
refuse library-wide lookups, and will assume one of the two is a mistake. A
real trade-off: a manual scope picker was the safe alternative and is the
fallback if resolution proves unreliable, and it was rejected only because it
charges the user for routing that costs the machine nothing — part numbers are
distinctive strings and the built-part list is already enumerable via
`discover_parts()`.
