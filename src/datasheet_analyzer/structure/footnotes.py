"""Footnote association: keep table footnotes attached to their table.

Pain point addressed: in TI datasheets a value like "±1(2)" is meaningless
without footnote (2) ("After DSA calibration procedure"). The footnotes live
in <div class="tablenote"> elements *after* the table — a naive extractor
drops them or strands them far from the values they qualify. Here they are
parsed, validated against the markers cited in the table, and embedded in
the TableBlock so they travel with it everywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import Tag

from datasheet_analyzer.models import Footnote, TableBlock

# "(1) Measured with ..." / "† Note ..." / "1) Note ..."
_NOTE_PREFIX = re.compile(r"^\s*(\(\d+\)|[†‡*§#]+|\d+\))\s*(.*)$", re.DOTALL)


def parse_tablenote(text: str) -> Footnote | None:
    """Parse one tablenote div's text into a Footnote (None if unrecognized)."""
    m = _NOTE_PREFIX.match(text.strip())
    if not m:
        return None
    marker, body = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
    if not body:
        return None
    return Footnote(marker=marker, text=body)


def tablenotes_from_elements(note_divs: list[Tag]) -> list[Footnote]:
    """Parse tablenote <div> elements, skipping unparseable ones."""
    out: list[Footnote] = []
    for div in note_divs:
        fn = parse_tablenote(div.get_text(" ", strip=True))
        if fn:
            out.append(fn)
    return out


@dataclass
class FootnoteAudit:
    """Result of validating a table's citations against its footnotes."""

    cited: set[str] = field(default_factory=set)
    noted: set[str] = field(default_factory=set)

    @property
    def orphans(self) -> set[str]:
        """Markers cited in cells but with no matching footnote text."""
        return self.cited - self.noted

    @property
    def uncited(self) -> set[str]:
        """Footnotes present but never cited (kept anyway; informational)."""
        return self.noted - self.cited

    @property
    def ok(self) -> bool:
        return not self.orphans


def audit_table_footnotes(table: TableBlock, cited: set[str]) -> FootnoteAudit:
    """Cross-check the markers cited in a table vs its attached footnotes."""
    return FootnoteAudit(cited=set(cited), noted={f.marker for f in table.footnotes})


def attach_footnotes(table: TableBlock, notes: list[Footnote]) -> TableBlock:
    """Return a copy of `table` with `notes` attached (travel-with-table rule)."""
    merged = {f.marker: f for f in table.footnotes}
    for n in notes:
        merged.setdefault(n.marker, n)
    return table.model_copy(update={"footnotes": list(merged.values())})
