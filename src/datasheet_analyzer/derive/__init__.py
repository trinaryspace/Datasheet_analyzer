"""Derived artifacts — data the pipeline *computes* rather than extracts.

Everything under here is governed by **invariant 8** (ADR 0007): a derived
artifact may contain only (a) values copied verbatim from a spec, table or pin
record, (b) values computed from those by a documented pure function, or
(c) structural labels from a checked-in lexicon. Every field carries `source`
(record id + page) and `derivation` (the named rule), and no model call may
appear anywhere in the derivation path.

`provenance.py` is the contract's machinery: the artifact names, the
`<artifact>#<record id>` source format, the resolver that turns one of those
strings back into the record and printed page it names, and the checker that
walks any derived artifact and reports every place the invariant is broken.
It is the module the phase's other tickets import; the artifacts themselves
are their own modules, added beside it:

| module | artifact | phase 6 ticket |
|---|---|---|
| `derive/provenance.py` | — (the contract) | 01 |
| `derive/pins.py` | `pins.json`, `dsa pins` | 04 |
| `derive/registers.py` | `registers.json`, `dsa regs` | 05 / 06 |
| `derive/cards.py` | `cards/<kind>.json` + `.md`, `dsa card` | 07 |
| `derive/compare.py` | `dsa compare` | 09 |

Each of those exposes one `cli_*(args) -> int` entry point, because `cli.py`
is frozen by ticket 01 and delegates to them by name: the command line
belongs to the contract, the behaviour belongs to the ticket.
"""

from __future__ import annotations

from datasheet_analyzer.derive.provenance import (
    CARDS_DIRNAME,
    PINS_ARTIFACT,
    PLOTS_ARTIFACT,
    REGISTERS_ARTIFACT,
    SPECS_ARTIFACT,
    ResolvedSource,
    check_provenance,
    describe_problems,
    is_derivation_rule,
    iter_derived_values,
    parse_source,
    resolve_source,
)

__all__ = [
    "CARDS_DIRNAME",
    "PINS_ARTIFACT",
    "PLOTS_ARTIFACT",
    "REGISTERS_ARTIFACT",
    "SPECS_ARTIFACT",
    "ResolvedSource",
    "check_provenance",
    "describe_problems",
    "is_derivation_rule",
    "iter_derived_values",
    "parse_source",
    "resolve_source",
]
