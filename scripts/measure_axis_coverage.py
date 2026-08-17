"""Measure the plot axis catalog's coverage over built corpora, per part.

Phase 6, ticket 08. The ticket's ≥60% is *a floor to beat and record*, not a
target to fit to, so what ships is a measurement anyone can reproduce — and the
parts that read 0% are as much of the finding as the ones that read 88%: a
datasheet whose plots are raster images prints no axis text at all, and the
honest number for it is zero.

Procedure (Git Bash on Windows), the same shape `scripts/measure_parse_rate.py`
documents. Build the gate parts into a scratch parts dir so the repo's own
`parts/` is untouched:

    DSA_PARTS_DIR=/tmp/aparts DSA_CACHE_DIR=/tmp/acache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/ad9081.pdf   --part AD9081
    DSA_PARTS_DIR=/tmp/aparts DSA_CACHE_DIR=/tmp/acache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/lm741.pdf    --part LM741 --vendor unknown
    DSA_PARTS_DIR=/tmp/aparts DSA_CACHE_DIR=/tmp/acache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/QPA1003P.pdf --part QPA1003P
    DSA_PARTS_DIR=/tmp/aparts DSA_CACHE_DIR=/tmp/acache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/hmc520a.pdf  --part HMC520A

Then measure, passing each part directory beside the PDF its figures are printed
in (the axes are re-read from the page rather than taken off the stored fields,
so a corpus published before the catalog existed measures exactly like a fresh
one and the number never depends on when it was built):

    .venv/Scripts/python.exe scripts/measure_axis_coverage.py \\
      parts/AFE7950=afe7950.pdf \\
      /tmp/aparts/AD9081=tests/fixtures/pdf/ad9081.pdf \\
      /tmp/aparts/HMC520A=tests/fixtures/pdf/hmc520a.pdf

`parts/AFE7953` has no offline build path (its corpus is the committed one), so
pass it the same way against `afe7953.pdf`.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from datasheet_analyzer.extract.pdf_layout import figure_text_regions
from datasheet_analyzer.models import Confidence
from datasheet_analyzer.retrieve import CorpusIndex
from datasheet_analyzer.structure.plot_axes import annotate_record, read_axes, region_for


def measure(part_dir: Path, pdf: Path) -> str:
    """One markdown row: how many of a part's figures publish which grade."""
    index = CorpusIndex.load(part_dir)
    records = [record for doc in index.docs for record in doc.plots]
    if not records:
        return f"| {index.part_number} | 0 | — | — | — | — |"
    regions = figure_text_regions(pdf)
    grades: Counter[str] = Counter()
    scales: Counter[str] = Counter()
    for record in records:
        region = region_for(record, regions)
        annotate_record(record, read_axes(region) if region is not None else None)
        grades[record.axis_confidence.value] += 1
        for axis in ("x", "y"):
            scale = getattr(record, f"{axis}_scale")
            if scale is not None:
                scales[scale.value] += 1
    high = grades[Confidence.HIGH.value]
    return (
        f"| {index.part_number} | {len(records)} | {high} "
        f"| {high / len(records):.0%} | {grades[Confidence.MEDIUM.value]} "
        f"| {grades[Confidence.LOW.value]} | "
        f"{scales['linear']} linear / {scales['log']} log |"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "parts", nargs="+",
        help="<part dir>=<pdf path> pairs, e.g. parts/AFE7950=afe7950.pdf",
    )
    args = ap.parse_args()
    print("| Part | Figures | high | high % | medium | low | axes read |")
    print("|---|---:|---:|---:|---:|---:|---|")
    for pair in args.parts:
        part_str, _, pdf_str = pair.partition("=")
        part_dir, pdf = Path(part_str), Path(pdf_str)
        if not (part_dir / "manifest.json").exists():
            print(f"skipped {part_dir}: no manifest.json (build it first)", file=sys.stderr)
            continue
        if not pdf.exists():
            print(f"skipped {part_dir}: no PDF at {pdf}", file=sys.stderr)
            continue
        print(measure(part_dir, pdf))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
