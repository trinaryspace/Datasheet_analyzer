"""Unit canonicalization for specs.json.

Derived-artifact only: the corpus markdown/CSV keeps the verbatim unit
(including U+2126 OHM SIGN) exactly as TI printed it.
"""

from __future__ import annotations

import re

from datasheet_analyzer.models import SpecUnit

CANONICAL_UNITS: dict[str, str] = {
    # ohm (TI emits U+2126; some sources use U+03A9)
    "Ω": "ohm",
    "Ω": "ohm",
    "ohm": "ohm",
    # No prefixed ohm entries (kohm, Mohm): giving them a canonical form would
    # rename a unit string this corpus already publishes, for three rows of
    # numeric coverage. Left as honest lexicon growth.
    # logarithmic / angle / ratio
    "dB": "dB",
    "dBm": "dBm",
    "dBc": "dBc",
    "dBc/Hz": "dBc/Hz",
    "dBFS": "dBFS",
    "dBFS/Hz": "dBFS/Hz",
    "deg": "deg",
    "%": "%",
    # voltage
    "V": "V",
    "kV": "kV",
    "mV": "mV",
    "µV": "µV",
    "mVpp": "mVpp",
    "Vppdiff": "Vppdiff",
    # current
    "A": "A",
    "mA": "mA",
    "µA": "µA",
    "nA": "nA",
    "pA": "pA",
    # temperature
    "°C": "°C",
    "°C/W": "°C/W",
    # frequency / data rate
    "Hz": "Hz",
    "kHz": "kHz",
    "MHz": "MHz",
    "GHz": "GHz",
    "SPS": "SPS",
    "MSPS": "MSPS",
    "GSPS": "GSPS",
    "bps": "bps",
    "Mbps": "Mbps",
    "Gbps": "Gbps",
    # time
    "s": "s",
    "ms": "ms",
    "µs": "µs",
    "ns": "ns",
    "ps": "ps",
    "UI": "UI",
    # misc
    "F": "F",
    "µF": "µF",
    "nF": "nF",
    "pF": "pF",
    "W": "W",
    "mW": "mW",
    "µW": "µW",
    "bits": "bits",
}

_DASHES = re.compile(r"[–−—]")
_WS = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """Derived-artifact normalizer for value text only.

    Trims, collapses whitespace, unifies en/em/minus dashes to '-'.
    Never applied to corpus markdown.
    """
    s = _DASHES.sub("-", s)
    s = _WS.sub(" ", s)
    return s.strip()


def canonical_unit(verbatim: str, unknown: set[str] | None = None) -> SpecUnit:
    """Return a SpecUnit for a verbatim unit string.

    Unknown units are kept verbatim and added to the optional `unknown` set
    so callers can report them.
    """
    key = verbatim.strip()
    canonical = CANONICAL_UNITS.get(key, key)
    if canonical == key and unknown is not None and key:
        unknown.add(key)
    return SpecUnit(verbatim=verbatim, canonical=canonical)
