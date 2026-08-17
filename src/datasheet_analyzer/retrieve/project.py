"""`ProjectRetriever` — one question, every part of a design.

A project is an explicit list of parts (`projects/`); this is what asking it a
question means. It holds one `Retriever` per member and fans a lookup out
across them in membership order, returning the **same typed hits** a single
part returns — every one already carrying `citation.part`, because `Retriever`
fills that in. Nothing is relabelled here and no citation is built here: the
fan-out is composition, not a second retrieval implementation.

Two decisions are worth stating:

- **Membership order is the tie-break, everywhere.** Concatenation for the
  record paths, and for full text a score sort with `(part, doc, file)`
  underneath it. BM25 scores from two different corpora are not strictly
  comparable — they are computed against each part's own statistics — so the
  merge is honest about being a merge, and every hit says which part it came
  from rather than pretending to one ranking.
- **A part that could not be searched is a gap, not an absence.** `search()`
  returning nothing means "nothing matched" only for the members that had an
  index. `search_gap()` reports any member that had none, so an answer pack
  across a project can refuse to claim absence it never established — the
  project-level form of the rule `Retriever.search_unavailable()` carries for
  one part.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from datasheet_analyzer.retrieve.results import (
    PinHit,
    PlotHit,
    RegisterHit,
    SearchHit,
    SectionHit,
    SpecHit,
)
from datasheet_analyzer.retrieve.retriever import Retriever, gap_axis

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from datasheet_analyzer.retrieve.pack import AnswerPack


@dataclass(frozen=True)
class ProjectRetriever:
    """Lookups across the member parts of one project."""

    name: str
    members: tuple[Retriever, ...] = ()

    @classmethod
    def for_parts(cls, name: str, part_dirs: list[Path] | tuple[Path, ...]) -> ProjectRetriever:
        """A retriever per member corpus, in the order the project lists them.

        Takes directories rather than a `Project`: resolving membership is the
        project store's job, and keeping it there is what lets `retrieve/`
        stay unaware of how a project is stored.
        """
        return cls(name=name, members=tuple(Retriever.for_part(d) for d in part_dirs))

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(m.part for m in self.members)

    @property
    def missing_parts(self) -> tuple[str, ...]:
        """Members with no corpus on disk — reported, never silently skipped."""
        return tuple(m.part for m in self.members if m.index.manifest is None)

    def specs(self, *, symbol: str = "", name: str = "", section: str = "") -> list[SpecHit]:
        """Every member's spec ladder, run independently, in member order.

        Each part resolves the term against its *own* records: a ladder rung
        is a statement about one corpus's vocabulary, so a rung-1 hit in one
        part must not suppress a rung-2 hit in another. The caller sees both,
        each naming its part and its rung.
        """
        return [
            hit
            for member in self.members
            for hit in member.specs(symbol=symbol, name=name, section=section)
        ]

    def pins(
        self, *, pin: str = "", name: str = "", type: str = "", q: str = ""
    ) -> list[PinHit]:
        """Every member's pin table, filtered the same way, in member order.

        Two parts of a design can print the same designator (`A1` exists on
        both), so a project-scoped pin lookup returns both and each hit names
        its part — the same rule every other project lookup follows.
        """
        return [
            hit
            for member in self.members
            for hit in member.pins(pin=pin, name=name, type=type, q=q)
        ]

    def pins_for_terms(self, text: str, *, limit: int = 6) -> list[PinHit]:
        """Every member's named-pin ladder, run independently, in member order.

        Each part resolves the question's words against its *own* pin table, for
        the same reason `specs()` runs each part's own ladder: a rung is a
        statement about one corpus's vocabulary, and `A1` on one device is not
        `A1` on another. The caller sees both, each hit naming its part.
        """
        return [
            hit for member in self.members for hit in member.pins_for_terms(text, limit=limit)
        ]

    def registers_for_terms(self, text: str, *, limit: int = 4) -> list[RegisterHit]:
        """Every member's named-register ladder, run independently, in member order."""
        return [
            hit
            for member in self.members
            for hit in member.registers_for_terms(text, limit=limit)
        ]

    def pin_gap(self) -> str:
        """`""` when some member has a pin table, else why none has.

        A design where no member published pins cannot answer a pin question,
        and must say so rather than return an empty list that reads as "this
        board has no such pin". Weaker than the single-part form only in that
        one member with pins is enough to make the lookup meaningful; the
        members without one are still visible as parts with no hits.
        """
        if any(not member.pin_gap() for member in self.members):
            return ""
        parts = ", ".join(self.parts) or "(none)"
        return (
            f"no part of project {self.name} ({parts}) published a pin table — "
            "a pin lookup across this design establishes nothing."
        )

    def registers(
        self, *, addr: str = "", name: str = "", field: str = "", q: str = ""
    ) -> list[RegisterHit]:
        """Every member's register map, filtered the same way, in member order.

        Two parts of a design can print the same address (`0x0` exists on
        both), so a project-scoped register lookup returns both and each hit
        names its part — the same rule every other project lookup follows.
        """
        return [
            hit
            for member in self.members
            for hit in member.registers(addr=addr, name=name, field=field, q=q)
        ]

    def register_gap(self) -> str:
        """`""` when some member has a register map, else why none has.

        `pin_gap()`'s twin one level up: a design where no member published a
        register summary must say so rather than return an empty list that
        reads as "this design has no such register".
        """
        if any(not member.register_gap() for member in self.members):
            return ""
        parts = ", ".join(self.parts) or "(none)"
        return (
            f"no part of project {self.name} ({parts}) published a register "
            "summary — a register lookup across this design establishes nothing."
        )

    def register_field_gap(self) -> str:
        """Every member's bit-field gap, one line each, in membership order.

        The counts are per part and stay per part: "7 of 35" means nothing merged
        across two devices, and a design-wide number would hide which device it
        was about.
        """
        return "\n".join(
            gap for gap in (m.register_field_gap() for m in self.members) if gap
        )

    def plots(
        self,
        *,
        q: str = "",
        caption: str = "",
        conditions: str = "",
        section: str = "",
        tags: list[str] | None = None,
        x_label: str = "",
        y_label: str = "",
        near_x: str = "",
    ) -> list[PlotHit]:
        return [
            hit
            for member in self.members
            for hit in member.plots(
                q=q, caption=caption, conditions=conditions, section=section,
                tags=tags, x_label=x_label, y_label=y_label, near_x=near_x,
            )
        ]

    def plot_axis_gap(self, *, axis: str = "x") -> str:
        """Every member's axis-catalog gap, one line each, in membership order.

        Per part, like `register_field_gap()`: "100 of 100 figures" is a fact
        about AD9081, and merging it into a design-wide count would hide which
        device's figures cannot be filtered by axis.
        """
        return "\n".join(
            gap for gap in (m.plot_axis_gap(axis=axis) for m in self.members) if gap
        )

    def plot_axis_gap_for(
        self, *, x_label: str = "", y_label: str = "", near_x: str = ""
    ) -> str:
        """`Retriever.plot_axis_gap_for`'s twin, so a front end asks one question
        of either scope."""
        axis = gap_axis(x_label=x_label, y_label=y_label, near_x=near_x)
        return self.plot_axis_gap(axis=axis) if axis else ""

    def sections(
        self, *, number: str = "", title: str = "", page: int | None = None
    ) -> list[SectionHit]:
        return [
            hit
            for member in self.members
            for hit in member.sections(number=number, title=title, page=page)
        ]

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        """Merge every member's BM25 hits, best score first (see module docs)."""
        hits = [hit for member in self.members for hit in member.search(query, limit=limit)]
        hits.sort(
            key=lambda h: (-h.score, h.citation.part, h.citation.doc, h.section.file)
        )
        return hits[:limit] if limit > 0 else hits

    def suggest_specs(self, term: str, limit: int = 5) -> list[str]:
        """Nearest candidates from every member, de-duplicated in member order."""
        out: list[str] = []
        for member in self.members:
            for candidate in member.suggest_specs(term, limit=limit):
                if candidate not in out:
                    out.append(candidate)
        return out[:limit]

    @property
    def unsearchable_parts(self) -> tuple[str, ...]:
        """Members with no current full-text index."""
        return tuple(m.part for m in self.members if m.search_unavailable())

    def search_unavailable(self) -> str:
        """`""` when *any* member can be searched, else why none can.

        Same contract as `Retriever.search_unavailable()`: this is the "the
        path cannot run at all" signal, which is what a front end turns into
        an exit code. A project where only some members lack an index can
        still be searched — see `search_gap()` for that.
        """
        if not self.members:
            return (
                f"project {self.name!r} has no parts — add one with "
                f"`dsa project add {self.name} <PART>`"
            )
        if not self.unsearchable_parts:
            return ""
        if len(self.unsearchable_parts) < len(self.members):
            return ""
        return (
            f"no full-text index for any part of project {self.name} "
            f"({', '.join(self.parts)}) — these corpora predate search (or were "
            "built against an older index schema). Rebuild them to enable "
            "search: dsa build <pdf> --part <PART>"
        )

    def search_gap(self) -> str:
        """`""` when every member is searchable, else which ones are not.

        A gap is weaker than unavailability and must not be confused with it:
        the project can still answer from the members that *do* have an index.
        What it cannot do is claim the design says nothing, which is why an
        answer pack asks this before it reports a no-match.
        """
        gaps = self.unsearchable_parts
        if not gaps:
            return ""
        return (
            f"the full-text path could not run for {', '.join(gaps)} "
            "(no current search index). Rebuild to enable search: "
            "dsa build <pdf> --part <PART>"
        )

    def ask(self, question: str, *, budget: int = 0) -> AnswerPack:
        """One cited, budget-bounded pack over the whole project.

        Imported at call time only: `retrieve.pack` composes this class, so a
        module-level import here would be a cycle.
        """
        from datasheet_analyzer.retrieve.pack import build_project_pack

        return build_project_pack(self, question, budget=budget)
