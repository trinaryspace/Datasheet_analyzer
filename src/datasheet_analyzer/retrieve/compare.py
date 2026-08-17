"""`Comparison` — one question, several parts, side by side.

Phase 6, ticket 09. The third scope this package offers, beside one part
(`Retriever`) and one design (`ProjectRetriever`): an **ad-hoc list of parts a
buyer is choosing between**. It is deliberately not a project — nothing is
stored, no membership is curated, and the parts need have nothing to do with
each other — which is why it is a scope rather than a noun in `projects/`.

Like `ProjectRetriever` it holds one `Retriever` per part and composes: each
part resolves the query against its **own** vocabulary through its own alias
ladder, because a rung is a statement about one corpus, and the alignment
happens afterwards on the alias-resolved symbol. Nothing is relabelled here and
no citation is built here.

Two rules the scope itself enforces, before any lookup runs:

- **fewer than two parts is not a comparison**, and a part named twice would put
  one row in two columns and a delta of zero against itself. Both are refused
  with the reason (`check_parts`).
- **more than two parts is supported.** Nothing truncates a list to the first
  two; the first part named is simply the reference every delta is measured
  against, and it is named in the result.

The derivation — alignment, deltas, refusals — lives in `compare/`, imported at
call time exactly as `Retriever.card()` imports `cards/`: those packages render
text and reach back into `retrieve.results` for the one citation format.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import PartComparison
from datasheet_analyzer.retrieve.retriever import Retriever


def check_parts(names: Sequence[str]) -> tuple[list[str], str]:
    """`(parts, error)` — a caller's part list, checked before anything runs.

    One place, because both front ends ask: `dsa compare` and the MCP
    `compare_parts` tool must refuse the same lists for the same stated reasons.
    """
    parts = [name.strip() for name in names if name and name.strip()]
    duplicates = list(dict.fromkeys(p for i, p in enumerate(parts) if p in parts[:i]))
    if duplicates:
        return parts, (
            f"named twice: {', '.join(duplicates)} — a part cannot be compared "
            f"against itself"
        )
    if len(parts) < 2:
        return parts, (
            "name at least two parts to compare, e.g. `dsa compare AFE7950 "
            "AFE7953 --symbol Pdiss` (three or more is supported — nothing is "
            "truncated)"
        )
    return parts, ""


@dataclass(frozen=True)
class Comparison:
    """Lookups across the parts one comparison is being made over."""

    members: tuple[Retriever, ...] = ()

    @classmethod
    def for_parts(cls, part_dirs: Sequence[Path]) -> Comparison:
        """A retriever per part, in the order the caller named them.

        Takes directories rather than part numbers for the same reason
        `ProjectRetriever` does: resolving a name to a corpus belongs to the
        caller's settings, and keeping it there is what lets this package stay
        unaware of where parts live.
        """
        return cls(members=tuple(Retriever.for_part(d) for d in part_dirs))

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(m.part for m in self.members)

    @property
    def missing_parts(self) -> tuple[str, ...]:
        """Named parts with no corpus on disk — reported, never silently skipped."""
        return tuple(m.part for m in self.members if m.index.manifest is None)

    def specs(self, *, symbol: str = "", name: str = "") -> PartComparison:
        """Compare what each part publishes for one spec query.

        `symbol` and `name` are the same two doors `Retriever.specs` opens, and
        each member walks its own ladder: a rung-1 hit in one part must not
        suppress a rung-2 hit in another, exactly as for a project.
        """
        from datasheet_analyzer.compare import (
            KIND_NAME,
            KIND_SYMBOL,
            ComparePart,
            CompareRecord,
            build_spec_comparison,
        )

        term = (symbol or name).strip()
        parts = [
            ComparePart(
                part_number=member.part,
                records=tuple(
                    CompareRecord(
                        doc=hit.citation.doc,
                        record=hit.record,
                        matched_via=hit.matched_via,
                    )
                    for hit in member.specs(symbol=symbol, name=name)
                ),
            )
            for member in self.members
        ]
        return build_spec_comparison(
            parts, term=term, kind=KIND_SYMBOL if symbol else KIND_NAME
        )

    def card(self, name: str) -> PartComparison | None:
        """Compare one design card of every part, row by row; `None` when no
        such card exists.

        `None` is "there is no card by that name", which a caller must be able
        to tell from "that card is empty for these parts" — the same distinction
        `Retriever.card()` draws, and for the same reason: a typo must not read
        as a finding about the datasheets.
        """
        from datasheet_analyzer.compare import build_card_comparison

        cards = [member.card(name) for member in self.members]
        if any(card is None for card in cards):
            return None
        return build_card_comparison([c for c in cards if c is not None], name=name)

    def card_names(self) -> list[str]:
        """The cards these builds declare — what a front end may offer."""
        for member in self.members:
            return member.card_names()
        return []
