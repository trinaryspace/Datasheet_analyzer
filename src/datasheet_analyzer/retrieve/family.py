"""`FamilyRetriever` - one question, one answer, for a whole series.

Phase 7, ticket 07. A family is a declared list of parts, so asking it a
question is `ProjectRetriever`'s fan-out with one rule added, and the rule *is*
the ticket: **an answer every member gives identically is returned once**, and an
answer that is not common is returned per member and flagged as divergent.

Three decisions are worth stating.

- **"Common" means the members produced the identical finding, character for
  character.** Not "the same magnitude", not "close enough": the answer row's
  text is composed from printed cells, and two members that printed `1.35 A` and
  `1350 mA` have not printed the same answer even though the numbers agree. The
  strict rule is the only one that can be checked by reading, which is the
  standard every other alignment in this repo is held to.
- **A shared row keeps one member's citation, and says whose.** It is the
  reference member's - the first declared - and the row names the members it is
  common to, because a designer who reads one page must know which page they
  read and which devices it stands for.
- **The collapse is `ask`'s alone. It does not extend to `query`, `search` or
  `plots`, and that is a decision rather than an omission.** All four verbs
  resolve `--family` and fan out identically; only the answer pack folds. The
  reason is the citation. `_collapse` keeps *one* member's citation and says
  whose (`[common to A, B]`), which is honest in a rendered pack because the
  pack has somewhere to say it. A record list has nowhere: a `SpecHit` reaches
  a `--json` consumer as one row with one `citation`, so folding two members
  into one row means shipping a page number that is wrong for the other
  member. Measured on AFE795x, the one declared family: of the 1155 spec rows
  the family returns, 763 are distinct printed rows and 387 are common to both
  members - and **177 of those 387 (45.7%) print on different pages in the two
  datasheets** (`ADC resolution` is p.14 in AFE7950 and p.13 in AFE7953).
  Collapsing would attach a wrong citation to nearly half the rows it merged.
  The other two verbs would not pay for themselves either: on the same family
  `plots(q="output power")` returns 46 hits with 46 distinct
  (caption, citation) pairs - nothing to fold - and a `SearchHit` carries a
  BM25 score computed against its own corpus's statistics, which
  `ProjectRetriever` already documents as not strictly comparable.

  The record-level view of a series exists, under the verb built for it:
  `dsa family build` (and the `get_family_index` MCP tool) lists shared
  sections once and tabulates only what moved, with **both** operands' pages
  on every delta. That is the aligned view, produced by an engine that decides
  identity explicitly rather than by string equality.

This module also owns the corpus walk that feeds `families/build.py`
(`load_members`), for the same reason `retrieve/revdiff.py` owns the revision
selection: a derived module stays pure over records, and the reading of a part
directory happens exactly once, here.

Everything this module needs out of `datasheet_analyzer.families` and
`datasheet_analyzer.derive` is imported **at call time**. Both of those packages
reach back into `retrieve.results` for the one `Citation` type, so a
module-level import here would close a cycle the moment a caller happened to
import `datasheet_analyzer.families` first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from datasheet_analyzer.retrieve.index import CorpusIndex
from datasheet_analyzer.retrieve.project import ProjectRetriever
from datasheet_analyzer.retrieve.retriever import Retriever

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from datasheet_analyzer.families.build import FamilyMember
    from datasheet_analyzer.retrieve.pack import AnswerPack


@dataclass(frozen=True)
class FamilyRetriever(ProjectRetriever):
    """Lookups across the declared members of one family.

    A `ProjectRetriever` by composition rather than by copy: every fan-out a
    design needs, a series needs identically, and re-implementing them here
    would be a second retrieval implementation - the thing `retrieve/` exists to
    prevent. What a family adds is the *answer* rule, and that lives in
    `pack.build_family_pack`.
    """

    @classmethod
    def for_parts(cls, name: str, part_dirs) -> FamilyRetriever:
        return cls(name=name, members=tuple(Retriever.for_part(d) for d in part_dirs))

    @property
    def reference(self) -> str:
        """The member every shared answer is cited from: the first declared."""
        return self.members[0].part if self.members else ""

    def ask(self, question: str, *, budget: int = 0) -> AnswerPack:
        """One cited, budget-bounded pack over the whole series.

        Imported at call time only: `retrieve.pack` composes this class, so a
        module-level import here would be a cycle.
        """
        from datasheet_analyzer.retrieve.pack import build_family_pack

        return build_family_pack(self, question, budget=budget)


def load_members(part_numbers, parts_dir: Path) -> list[FamilyMember]:
    """Read each declared member's corpus once, in declared order.

    A member with no corpus on disk is **not** dropped: it comes back with a
    `gap` naming the build that would fix it, and the family index prints that
    note. A family index that quietly answered for two of three devices would be
    read as answering for all three, which is the failure this whole ticket is
    built around.

    Pins and registers are read here rather than carried on `CorpusIndex`, and
    through the same loaders `dsa pins` and `dsa regs` use, so a family index and
    a lookup can never disagree about what a document published. The `ref_base`
    each record is cited under comes off the part's `CardCorpus`, which is what
    resolves a document published once into the shared library store.
    """
    from datasheet_analyzer.derive.cards import load_card_corpus
    from datasheet_analyzer.derive.pins import load_part_pins
    from datasheet_analyzer.derive.registers import load_part_registers
    from datasheet_analyzer.families.build import FamilyMember, MemberRecord

    out: list[FamilyMember] = []
    for part_number in part_numbers:
        part_dir = Path(parts_dir) / part_number
        index = CorpusIndex.load(part_dir)
        if index.manifest is None:
            out.append(
                FamilyMember(
                    part_number=part_number,
                    gap=(
                        f"no corpus on disk - build it "
                        f"(`dsa build <pdf> --part {part_number}`); this member "
                        f"contributes no section and no record to the family"
                    ),
                )
            )
            continue
        bases = {
            doc.name: doc.ref_base for doc in load_card_corpus(part_dir, part_number).documents
        }
        out.append(
            FamilyMember(
                part_number=part_number,
                part_dir=part_dir,
                sections=tuple(index.sections),
                bodies=_bodies(part_number, part_dir, index),
                pins=tuple(
                    MemberRecord(ref_base=bases.get(doc, f"docs/{doc}"), record=record)
                    for doc, pinset in load_part_pins(part_dir, part_number).sets
                    for record in pinset.pins
                    if record.id
                ),
                registers=tuple(
                    MemberRecord(ref_base=bases.get(doc, f"docs/{doc}"), record=record)
                    for doc, registerset in load_part_registers(part_dir, part_number).sets
                    for record in registerset.registers
                    if record.id
                ),
            )
        )
    return out


def _bodies(part_number: str, part_dir: Path, index: CorpusIndex) -> dict[str, str]:
    """Each section file's comparable body, read once per member.

    A section file that has gone missing reads as a marker naming **this**
    member, never as an empty string: two members whose files both failed to read
    would otherwise compare equal and be published as "identical in every
    member", which is the one wrong answer this artifact must not give. The
    marker cannot collide with real content - it holds a NUL, which no section
    file does.
    """
    from datasheet_analyzer.families.build import section_body

    out: dict[str, str] = {}
    for section in index.sections:
        path = part_dir / section.file
        try:
            out[section.file] = section_body(path.read_text(encoding="utf-8"))
        except OSError:
            out[section.file] = f"\x00unreadable:{part_number}/{section.file}"
    return out
