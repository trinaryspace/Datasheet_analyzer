"""Regenerate `.claude/skills/datasheet-corpus/SKILL.md` from the protocol.

The skill is a *rendered* artifact, not a hand-written one: its rules are the
same strings `parts/<PART>/AGENT.md` ships (`datasheet_analyzer.protocol`), so
editing one and forgetting the other is impossible by construction. The
checked-in file is asserted byte-for-byte equal to this render by
`tests/unit/test_protocol.py`, which is what turns "they agree" into a
property of the build rather than a promise.

Edit `src/datasheet_analyzer/protocol.py`, then run:

    .venv/Scripts/python.exe scripts/write_skill.py

It prints the path and the token size, and exits 1 with a diff hint if run
with `--check` and the file is stale (useful in a pre-commit hook).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from datasheet_analyzer.protocol import SKILL_RELPATH, build_skill_markdown
from datasheet_analyzer.tokens import count_tokens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify the file is current; write nothing"
    )
    args = parser.parse_args(argv)

    path = REPO_ROOT / SKILL_RELPATH
    text = build_skill_markdown()
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if args.check:
        if current == text:
            print(f"current: {path}")
            return 0
        print(f"STALE: {path} — run `python scripts/write_skill.py`", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path} ({count_tokens(text)} tokens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
