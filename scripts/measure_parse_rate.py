"""Measure the numeric layer's parse rate over built corpora, by section.

Phase 6, ticket 02. The numeric layer is *allowed to fail* — `See Figure 7` has
no number in it — so the honest thing to publish is not a target but a
measurement, per part and per section, reproducible by whoever doubts it.

Procedure (Git Bash on Windows), the same shape `scripts/seed_aliases.py`
documents. Build the four gate parts into a scratch parts dir so the repo's own
`parts/` is untouched:

    DSA_PARTS_DIR=/tmp/qparts DSA_CACHE_DIR=/tmp/qcache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/ad9081.pdf   --part AD9081
    DSA_PARTS_DIR=/tmp/qparts DSA_CACHE_DIR=/tmp/qcache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/lm741.pdf    --part LM741 --vendor unknown
    DSA_PARTS_DIR=/tmp/qparts DSA_CACHE_DIR=/tmp/qcache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/QPA1003P.pdf --part QPA1003P
    DSA_PARTS_DIR=/tmp/qparts DSA_CACHE_DIR=/tmp/qcache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/hmc520a.pdf  --part HMC520A

Then measure all six (the two reference corpora are committed under `parts/`):

    .venv/Scripts/python.exe scripts/measure_parse_rate.py \\
      parts/AFE7950 parts/AFE7953 \\
      /tmp/qparts/AD9081 /tmp/qparts/LM741 \\
      /tmp/qparts/QPA1003P /tmp/qparts/HMC520A

Records are re-parsed rather than read off the stored `value_si` fields, so a
corpus published before the layer existed measures exactly like a fresh one and
the number never depends on when the corpus was built.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from datasheet_analyzer.retrieve import CorpusIndex
from datasheet_analyzer.structure.quantities import parse_rate


def measure(part_dir: Path, *, sections: bool) -> str:
    """The parse-rate report for one built part."""
    index = CorpusIndex.load(part_dir)
    records = [record for doc in index.docs for record in doc.specs]
    rate = parse_rate(records)
    if not records:
        return f"### {index.part_number}\n\n_no spec records_"
    if sections:
        return rate.as_table(title=index.part_number)
    return (
        f"| {index.part_number} | {rate.n_records} | {rate.n_parsed} "
        f"| {rate.rate:.0%} |"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("parts", nargs="+", type=Path, help="built part directories")
    ap.add_argument(
        "--summary-only",
        action="store_true",
        help="one row per part instead of the per-section breakdown",
    )
    args = ap.parse_args()

    if args.summary_only:
        print("| Part | Records | Parsed | Rate |")
        print("|---|---:|---:|---:|")
    for part_dir in args.parts:
        if not (part_dir / "manifest.json").exists():
            print(f"skipped {part_dir}: no manifest.json (build it first)", file=sys.stderr)
            continue
        print(measure(part_dir, sections=not args.summary_only))
        if not args.summary_only:
            print()
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
