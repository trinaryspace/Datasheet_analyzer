"""Seed and measure `registry/aliases.yaml` against built corpora.

The alias lexicon is only worth what it covers, so it is seeded from the
symbols the six built corpora actually print — not from imagination. This
script is that procedure, checked in so the coverage number is reproducible.

Procedure (Git Bash on Windows; every command is one the README already
documents). Build the four gate parts into a scratch parts dir so the repo's
own `parts/` is untouched:

    DSA_PARTS_DIR=/tmp/seedparts DSA_CACHE_DIR=/tmp/seedcache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/ad9081.pdf   --part AD9081
    DSA_PARTS_DIR=/tmp/seedparts DSA_CACHE_DIR=/tmp/seedcache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/lm741.pdf    --part LM741 --vendor unknown
    DSA_PARTS_DIR=/tmp/seedparts DSA_CACHE_DIR=/tmp/seedcache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/QPA1003P.pdf --part QPA1003P
    DSA_PARTS_DIR=/tmp/seedparts DSA_CACHE_DIR=/tmp/seedcache \\
      .venv/Scripts/dsa.exe build tests/fixtures/pdf/hmc520a.pdf  --part HMC520A

Then harvest all six (the two reference corpora are committed under `parts/`)
and refresh the checked-in inventory the alias tests measure against:

    .venv/Scripts/python.exe scripts/seed_aliases.py \\
      parts/AFE7950 parts/AFE7953 \\
      /tmp/seedparts/AD9081 /tmp/seedparts/LM741 \\
      /tmp/seedparts/QPA1003P /tmp/seedparts/HMC520A \\
      --inventory tests/fixtures/alias_seed_symbols.json

The report it prints is the per-corpus symbol coverage plus the most common
uncovered symbols, as a YAML skeleton ready to paste into
`registry/aliases.yaml`. Adding a synonym stays a data edit — this script
never writes the lexicon itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from datasheet_analyzer.retrieve import CorpusIndex
from datasheet_analyzer.structure.aliases import AliasLexicon, load_lexicon

INVENTORY_SCHEMA_VERSION = "1"


def harvest(part_dir: Path) -> list[dict]:
    """Every distinct `(symbol, name, unit)` a part's specs.json records.

    Deduped on that triple (first row of a repeated triple keeps its values)
    and sorted, so the artifact is stable across runs and a diff means the
    extraction changed — not that a dict reordered. The min/typ/max/value
    cells travel with it so the inventory is a faithful sample of the corpus,
    not just a word list.
    """
    index = CorpusIndex.load(part_dir)
    rows: dict[tuple, dict] = {}
    for doc in index.docs:
        for rec in doc.specs:
            key = (rec.symbol, rec.name, rec.unit.canonical)
            if key in rows:
                continue
            rows[key] = {
                "symbol": rec.symbol,
                "name": rec.name,
                "min": rec.min,
                "typ": rec.typ,
                "max": rec.max,
                "value": rec.value,
                "unit": rec.unit.verbatim,
                "unit_canonical": rec.unit.canonical,
                "section": rec.section,
                "page": rec.page,
            }
    return [rows[k] for k in sorted(rows)]


def covers(lexicon: AliasLexicon, row: dict) -> str:
    """The alias entry covering this row, or `""` — the coverage rule.

    A row is covered when the lexicon knows its symbol as a canonical symbol,
    as a member of a prefix family, or by one of its alias phrases appearing
    in the row's own symbol or name text. The rule itself lives in
    `AliasLexicon.entry_for`, which `structure/confidence.py` also asks, so
    the measured coverage and the shipped grade can never disagree.
    """
    entry = lexicon.entry_for(row["symbol"], row["name"])
    return entry.symbol if entry is not None else ""


def coverage(lexicon: AliasLexicon, rows: list[dict]) -> tuple[int, int, Counter]:
    """`(covered, total, uncovered symbol counts)` over distinct rows."""
    covered = 0
    uncovered: Counter = Counter()
    for row in rows:
        if covers(lexicon, row):
            covered += 1
        elif row["symbol"] or row["name"]:
            uncovered[row["symbol"] or row["name"]] += 1
    return covered, len(rows), uncovered


def yaml_skeleton(uncovered: Counter, limit: int) -> str:
    """Paste-ready entries for the symbols the lexicon does not yet know."""
    lines = ["# uncovered symbols - candidate entries for registry/aliases.yaml"]
    for symbol, count in uncovered.most_common(limit):
        lines.append(f"# seen in {count} corpus row(s)")
        lines.append(f"{symbol}:")
        lines.append(f"  names: [{symbol.lower()}]")
        lines.append("  expect_unit: ")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("part_dirs", nargs="+", help="built part corpora to harvest")
    parser.add_argument(
        "--inventory",
        default="",
        help="write the harvested symbol inventory here (JSON, test fixture)",
    )
    parser.add_argument(
        "--suggest", type=int, default=20, help="how many uncovered symbols to print"
    )
    args = parser.parse_args(argv)

    lexicon = load_lexicon()
    inventory: dict[str, list[dict]] = {}
    total_covered = total_rows = 0
    all_uncovered: Counter = Counter()

    print(f"alias lexicon: {len(lexicon.entries)} entries")
    for raw in args.part_dirs:
        part_dir = Path(raw)
        rows = harvest(part_dir)
        inventory[part_dir.name] = rows
        covered, total, uncovered = coverage(lexicon, rows)
        total_covered += covered
        total_rows += total
        all_uncovered.update(uncovered)
        pct = covered / total if total else 0.0
        print(
            f"  {part_dir.name:<10} {covered:>4}/{total:<4} distinct spec rows covered ({pct:.0%})"
        )

    pct = total_covered / total_rows if total_rows else 0.0
    print(f"  {'TOTAL':<10} {total_covered:>4}/{total_rows:<4} ({pct:.0%})")

    if args.inventory:
        path = Path(args.inventory)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": INVENTORY_SCHEMA_VERSION,
            "note": (
                "Harvested by scripts/seed_aliases.py from the six built corpora. "
                "Regenerate with the procedure in that script's docstring."
            ),
            "parts": inventory,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path} ({sum(len(v) for v in inventory.values())} rows)")

    if args.suggest:
        print()
        print(yaml_skeleton(all_uncovered, args.suggest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
