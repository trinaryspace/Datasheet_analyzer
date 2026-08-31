"""`dsa family suggest` — propose groupings. Never assume one.

Phase 7, ticket 07, and the ticket's fourth criterion in one sentence: **this
module's output builds nothing**. It writes `registry/families.candidate.yaml`,
whose entries carry `confirmed: false` and which `families/registry.load_families`
refuses by name; only `dsa family confirm` moves one across. The design is the
same one invariant 5 already applies to generated golden questions — the tooling
removes the typing, never the judgment — and here it is load-bearing for a
different reason: a family index says "this section is identical in every member,
read it once", and a wrong member makes that sentence a lie a designer cannot see.

The proposal itself is deliberately weak evidence, and says so. Two readings, both
off what the corpora already publish:

- the **part-number stem**: the longest shared alphabetic prefix, with the
  trailing digits replaced by `x` (`AFE7950` + `AFE7953` -> `AFE795x`). This is
  the name; it is not evidence of anything on its own, because vendors reuse
  prefixes across unrelated lines.
- the **section structure**: the Jaccard overlap of the two corpora's
  `(number, normalized title)` pairs. Two documents built from one template
  overlap almost completely; two unrelated datasheets do not.

Both must clear their floor. Neither is a claim: two devices can share a section
map and be different parts, which is exactly why a human confirms.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from datasheet_analyzer.families.registry import FamilyEntry
from datasheet_analyzer.structure.aliases import normalize

#: How much of the section map two members must share. High on purpose: the
#: suggester is allowed to miss a family (a human declares it in one YAML line)
#: and is not allowed to make a grouping look plausible.
MIN_SECTION_OVERLAP = 0.8
#: How many leading characters two part numbers must share. Below this the
#: "family" is a coincidence of the vendor's alphabet.
MIN_STEM = 4
#: The rule name a proposal records, so a confirmed entry still says what
#: proposed it.
PROPOSED_BY = "section-structure+part-stem"

_TRAILING_DIGITS = re.compile(r"\d+$")


@dataclass(frozen=True)
class CandidatePart:
    """One built part as the suggester reads it: its number and its section map.

    Deliberately not a `CorpusIndex` — the corpus walk belongs to `retrieve/`,
    the same split every other derived module makes.
    """

    part_number: str
    sections: frozenset[tuple[str, str]] = frozenset()
    title: str = ""


def section_signature(sections) -> frozenset[tuple[str, str]]:
    """`(printed number, normalized title)` per section — the structure reading."""
    return frozenset(
        (section.number.strip(), normalize(section.title)) for section in sections
    )


def overlap(a: CandidatePart, b: CandidatePart) -> float:
    """Jaccard overlap of two section maps; `0.0` when either publishes none.

    Zero rather than one for two empty maps: "neither corpus published a section
    map" is not evidence that they are the same device, and returning a perfect
    score for an absence is how an auto-grouper proposes nonsense confidently.
    """
    if not a.sections or not b.sections:
        return 0.0
    return len(a.sections & b.sections) / len(a.sections | b.sections)


def stem(numbers: Sequence[str]) -> str:
    """The family name a set of part numbers suggests, or `""`.

    `AFE7950` + `AFE7953` -> `AFE795x`: the shared prefix with the digits that
    differ replaced by one `x`. A shared prefix shorter than `MIN_STEM` yields
    nothing — a two-letter vendor prefix is not a family.
    """
    if len(numbers) < 2:
        return ""
    shared = numbers[0]
    for number in numbers[1:]:
        limit = min(len(shared), len(number))
        cut = 0
        while cut < limit and shared[cut] == number[cut]:
            cut += 1
        shared = shared[:cut]
    if len(shared) < MIN_STEM:
        return ""
    return f"{shared}x" if shared[-1].isdigit() else shared


def suggest_families(
    parts: Sequence[CandidatePart],
    *,
    min_overlap: float = MIN_SECTION_OVERLAP,
    min_stem: int = MIN_STEM,
) -> list[FamilyEntry]:
    """Propose groupings over built corpora — every one of them unconfirmed.

    Grouping is transitive closure over "shares a stem **and** clears the section
    overlap": a series is normally three or four devices, and a pair-only
    proposal would ask a human to confirm the same family several times. The
    closure is computed in part-number order, so the proposal is deterministic.
    """
    ordered = sorted(parts, key=lambda p: p.part_number)
    groups: list[list[CandidatePart]] = []
    placed: set[str] = set()
    for i, part in enumerate(ordered):
        if part.part_number in placed:
            continue
        group = [part]
        placed.add(part.part_number)
        # One pass over the rest, comparing against every member already in the
        # group: a candidate joins only if it looks like *all* of them, which
        # stops a chain of near-misses from growing a family nobody would.
        for other in ordered[i + 1 :]:
            if other.part_number in placed:
                continue
            if all(
                _pairs(member, other, min_overlap=min_overlap, min_stem=min_stem)
                for member in group
            ):
                group.append(other)
                placed.add(other.part_number)
        if len(group) > 1:
            groups.append(group)

    out: list[FamilyEntry] = []
    for group in groups:
        numbers = [p.part_number for p in group]
        name = stem(numbers)
        if not name:
            continue
        worst = min(
            overlap(a, b)
            for i, a in enumerate(group)
            for b in group[i + 1 :]
        )
        out.append(
            FamilyEntry(
                name=name,
                title=f"proposed from {', '.join(numbers)}",
                members=numbers,
                note=(
                    f"section maps overlap {worst:.0%} (floor {min_overlap:.0%}); "
                    f"shared part-number stem. This is a starting point, not a "
                    f"finding — two devices can share a section map and be "
                    f"different parts. Check both datasheets before confirming."
                ),
                proposed_by=PROPOSED_BY,
                confirmed=False,
            )
        )
    return out


def _pairs(
    a: CandidatePart, b: CandidatePart, *, min_overlap: float, min_stem: int
) -> bool:
    numbers = sorted((a.part_number, b.part_number))
    shared = stem(numbers)
    if not shared or len(shared.rstrip("x")) < min_stem:
        return False
    return overlap(a, b) >= min_overlap
