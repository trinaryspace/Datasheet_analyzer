"""Acquire stage: register source documents into a part's document set."""

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
