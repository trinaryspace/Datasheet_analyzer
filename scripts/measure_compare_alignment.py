"""Measure how much of one part's parameters a comparison can align to another.

Phase 6, ticket 09. `dsa compare` refuses far more often than it subtracts, on
purpose — a delta between the wrong two rows during part selection looks exactly
like a right one — so the honest thing to publish is *how often* it aligns, over
which parts, reproducible by anyone.

The walk is every alias phrase the lexicon knows (`registry/aliases.yaml`)
against every pair of the parts named, counting three outcomes per row: aligned
with a delta, aligned without one (both sides published, no comparable printed
column), and `only in A` (one part publishes nothing under that key). Rows
refused as ambiguous produce no row at all and are counted separately, from the
comparison's own listing.

The counts are **per lookup, not per parameter**: a parameter three alias phrases
reach is counted three times, because what is being measured is how often a
question a designer asks comes back aligned — not how many distinct rows the two
datasheets happen to share.

Procedure (Git Bash on Windows), the same shape `scripts/measure_axis_coverage.py`
documents. Build into a scratch parts dir so the repo's own `parts/` is
untouched:

    DSA_PARTS_DIR=/tmp/cparts DSA_CACHE_DIR=/tmp/ccache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/ad9081.pdf   --part AD9081
    DSA_PARTS_DIR=/tmp/cparts DSA_CACHE_DIR=/tmp/ccache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/lm741.pdf    --part LM741 --vendor unknown
    DSA_PARTS_DIR=/tmp/cparts DSA_CACHE_DIR=/tmp/ccache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/QPA1003P.pdf --part QPA1003P
    DSA_PARTS_DIR=/tmp/cparts DSA_CACHE_DIR=/tmp/ccache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/hmc520a.pdf  --part HMC520A

Then measure over every pair of them:

    .venv/Scripts/python.exe scripts/measure_compare_alignment.py \\
      /tmp/cparts/AD9081 /tmp/cparts/LM741 /tmp/cparts/QPA1003P /tmp/cparts/HMC520A

The two reference parts need an offline build of their own: the committed
`parts/AFE7950` and `parts/AFE7953` were published before ADR 0005 minted record
ids, so every row of them is honestly unaddressable and no comparison can cite
one (`KNOWN_SHORTCOMINGS.md`). Build them the same way (`--vendor unknown` routes
them through the layout floor) and pass the two directories to see what two parts
of **one family** align to, which is the number this feature exists for.

`--cards` adds the same walk over the design cards each part publishes.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from datasheet_analyzer.models import PartComparison
from datasheet_analyzer.retrieve import Comparison
from datasheet_analyzer.structure.aliases import load_lexicon

#: The fragment `compare.build._ambiguous` opens a refused key's reason with.
#: Matched rather than re-derived: a key nothing could pair produces no row at
#: all, so its own listing line is the only place the refusal is countable.
AMBIGUOUS_REASON = "rows under this parameter"


@dataclass
class Tally:
    """What one pair of parts produced, over every phrase walked."""

    aligned: int = 0
    with_delta: int = 0
    only_in: int = 0
    refused: int = 0

    def add(self, comparison: PartComparison) -> None:
        for row in comparison.rows:
            if len(row.cells) > 1:
                self.aligned += 1
                self.with_delta += bool(row.n_deltas)
            else:
                self.only_in += 1
        # One line per refused *key*, not per refused row: an ambiguous key
        # prints its reason once and then quotes every row under it, and the
        # rows are the evidence rather than the count.
        self.refused += sum(
            1 for line in comparison.unparsed if AMBIGUOUS_REASON in line
        )

    def row(self, label: str) -> str:
        return (
            f"| {label} | {self.aligned} | {self.with_delta} | {self.only_in} "
            f"| {self.refused} |"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("parts", nargs="+", help="built part directories")
    ap.add_argument(
        "--cards", action="store_true", help="also walk each declared design card"
    )
    args = ap.parse_args()

    dirs = [Path(p) for p in args.parts]
    for part_dir in dirs:
        if not (part_dir / "manifest.json").exists():
            print(f"no manifest.json in {part_dir} — build it first", file=sys.stderr)
            return 2
    if len(dirs) < 2:
        print("name at least two built parts", file=sys.stderr)
        return 2

    phrases = sorted({name for entry in load_lexicon().entries for name in entry.names})
    print(f"{len(phrases)} alias phrases, {len(dirs)} parts\n")
    print("| Pair | aligned rows | with a delta | only in one | keys refused |")
    print("|---|---:|---:|---:|---:|")
    for left, right in itertools.combinations(dirs, 2):
        scope = Comparison.for_parts([left, right])
        tally = Tally()
        for phrase in phrases:
            tally.add(scope.specs(name=phrase))
        print(tally.row(f"{left.name} vs {right.name}"))

    if args.cards:
        print("\n| Pair | card | rows | aligned | deltas |")
        print("|---|---|---:|---:|---:|")
        for left, right in itertools.combinations(dirs, 2):
            scope = Comparison.for_parts([left, right])
            for name in scope.card_names():
                comparison = scope.card(name)
                if comparison is None:
                    continue
                aligned = sum(1 for row in comparison.rows if len(row.cells) > 1)
                print(
                    f"| {left.name} vs {right.name} | {name} "
                    f"| {len(comparison.rows)} | {aligned} | {comparison.n_deltas} |"
                )
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
