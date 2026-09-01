"""Acquire stage: register source documents into a part's document set.

Phase 7, ticket 01 adds the step *before* registration: `registry.py` is the
curated `registry/datasheets.yaml` (where a part's documents come from) and
`fetch.py` is `dsa fetch` (resolve → download → hash-verify → register). They
are imported lazily by the CLI, so nothing on the build path pulls a network
seam in by importing this package.
"""

from datasheet_analyzer.acquire.inventory import (
    append_to_inventory,
    load_inventory,
    pin_vendor,
    register_source,
    save_inventory,
)

__all__ = [
    "append_to_inventory",
    "load_inventory",
    "pin_vendor",
    "register_source",
    "save_inventory",
]
