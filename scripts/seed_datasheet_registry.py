"""Regenerate `src/datasheet_analyzer/registry/datasheets.yaml` from the
documents physically committed to this repo.

The registry ships non-empty (phase 7, ticket 01) and every field in it is a
fact this script can *compute*, not a fact anyone remembered:

- **sha256** is the hash of a PDF that is in this repo, and `sha256_origin`
  names the file it was taken from. Nothing here records a hash "expected"
  upstream.
- **revision** is the TI literature number parsed out of the document's own
  first pages when there is exactly one, otherwise `sniff_revision`'s reading
  of the printed revision token. Never a value from memory.
- **url** is derived *only* for a TI **datasheet** whose literature number was
  parsed, through the one literature-path pattern this repo carries
  (`https://www.ti.com/lit/ds/<lit>/<lit>.pdf`). A derived URL is a hypothesis:
  it ships `url_verified: false` and records the rule that produced it, and
  only a live `dsa fetch` may flip that flag.
- **every other part has `url: null` plus the reason**, because no URL pattern
  for that vendor is encoded anywhere in this repo and guessing one would put a
  wrong document in front of a designer with a citation that looks exactly as
  trustworthy as a right one. `dsa fetch` then asks for `--url`, which is the
  designed growth path.
- **retrieved_at is null** for every seed entry: nothing was fetched.

Only **git-tracked** documents are seeded. A hash whose `local_file:` path is
absent from a fresh clone is a claim nobody downstream can re-verify, and the
whole point of `sha256_origin` is that the claim *is* checkable — so a PDF that
is in this working tree but not in the repo is left out rather than recorded.
`LMX1204`'s two documents are exactly that case on this branch; the growth path
for them is `dsa fetch --url <URL> --part LMX1204`.

Run it after adding a document to the repo:

    .venv/Scripts/python.exe scripts/seed_datasheet_registry.py [--check]

`tests/unit/test_fetch.py::TestSeedRegistry` asserts the checked-in file
agrees with this render and that every recorded sha256 still matches the file
it names, so the registry cannot drift away from the bytes it describes.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from datasheet_analyzer.acquire.registry import (
    TI_LIT_DERIVATION,
    DocumentRegistry,
    RegistryDocument,
    RegistryEntry,
    registry_path,
    registry_yaml,
    ti_lit_url,
)
from datasheet_analyzer.extract.pdf_structure import sniff_revision
from datasheet_analyzer.models import DocType
from datasheet_analyzer.vendor import detect_vendor

#: The documents this repo actually holds, as (part number, repo-relative
#: path, doc type). The part number is the one the corpus under `parts/` is
#: filed as, so `dsa check-revisions --all` can pair a built corpus with its
#: entry; the repo-root copies are the documented `dsa build` working files and
#: the Mini-Circuits parts live only under `tests/fixtures/pdf/`.
SEED_DOCUMENTS: list[tuple[str, str, DocType]] = [
    ("AFE7950", "afe7950.pdf", DocType.DATASHEET),
    ("AFE7953", "afe7953.pdf", DocType.DATASHEET),
    ("AD9081", "ad9081.pdf", DocType.DATASHEET),
    ("HMC520A", "hmc520a.pdf", DocType.DATASHEET),
    ("lm741", "lm741.pdf", DocType.DATASHEET),
    ("QPA1003P", "QPA1003P.pdf", DocType.DATASHEET),
    ("LHA-83W+", "tests/fixtures/pdf/LHA-83W+.pdf", DocType.DATASHEET),
    ("PMA1-14LN+", "tests/fixtures/pdf/PMA1-14LN+.pdf", DocType.DATASHEET),
    ("PSA-8A+", "tests/fixtures/pdf/PSA-8A+.pdf", DocType.DATASHEET),
    ("ZX10R-2-183-S+", "tests/fixtures/pdf/ZX10R-2-183-S+.pdf", DocType.DATASHEET),
]

#: TI literature numbers as they are printed: a four-letter series code and a
#: short alphanumeric tail. Anchored on word boundaries so an ordinary
#: capitalised word can never read as one, and the series list is closed — a
#: pattern that matched any four capitals would happily read `SYSREFOUT0` as a
#: literature number.
_LIT_RE = re.compile(r"\b(?:SBAS|SBAA|SNAS|SNAU|SNOS|SLAS|SLAA|SLLS|SWRA)[A-Z0-9]{3,6}\b")

#: How many pages a literature number is looked for on. TI prints it in the
#: page-1 footer and repeats it on the following pages; looking further would
#: start picking up *referenced* documents rather than this one.
_LIT_PAGES = 3


def literature_number(path: Path) -> str:
    """The single TI literature number printed on this document, or `""`.

    Two different numbers on the front pages means the document cites another
    one, and there is no way to tell which is its own — so nothing is returned
    rather than the first one seen.
    """
    import pymupdf

    doc = pymupdf.open(path)
    try:
        text = "\n".join(doc[i].get_text() for i in range(min(_LIT_PAGES, doc.page_count)))
    finally:
        doc.close()
    found = sorted(set(_LIT_RE.findall(text)))
    return found[0] if len(found) == 1 else ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def seed_document(rel_path: str, doc_type: DocType) -> tuple[RegistryDocument, str]:
    """Build one seed entry from one committed document. Returns (doc, vendor)."""
    path = REPO_ROOT / rel_path
    vendor, _evidence = detect_vendor(path)
    lit = literature_number(path)
    doc = RegistryDocument(
        doc_type=doc_type,
        revision=lit or sniff_revision(path),
        sha256=_sha256(path),
        sha256_origin=f"local_file:{rel_path}",
    )
    if vendor == "ti" and lit and doc_type == DocType.DATASHEET:
        doc.url = ti_lit_url(lit)
        doc.url_verified = False
        doc.url_derivation = f"{TI_LIT_DERIVATION}({lit})"
    elif vendor == "ti" and lit:
        doc.url_reason = (
            f"the only literature-path pattern this repo carries is TI's datasheet "
            f"path (lit/ds); {lit} is a {doc_type.value} and its path is not encoded "
            f"here, so no URL is guessed"
        )
    elif vendor == "ti":
        doc.url_reason = (
            "no literature number could be parsed from the document, so TI's "
            "literature path cannot be derived from anything this repo holds"
        )
    elif vendor == "unknown":
        doc.url_reason = (
            "no vendor could be pinned from this document's own pages, so there is no "
            "vendor whose URL pattern could apply, and this tool never guesses one"
        )
    else:
        doc.url_reason = (
            f"no {vendor} document-URL pattern is encoded in this repo, and this "
            f"tool never guesses one"
        )
    return doc, vendor


def build_registry() -> DocumentRegistry:
    """The registry rendered from every seed document present in this checkout.

    A seed path that is absent is skipped rather than fabricated: this script
    can only record hashes of bytes it can read, and saying nothing about a
    document is the honest answer when the document is not here.
    """
    registry = DocumentRegistry()
    for part_number, rel_path, doc_type in SEED_DOCUMENTS:
        if not (REPO_ROOT / rel_path).exists():
            print(f"skipping {part_number}: {rel_path} is not in this checkout", file=sys.stderr)
            continue
        doc, vendor = seed_document(rel_path, doc_type)
        entry = registry.get(part_number)
        if entry is None:
            registry.put(RegistryEntry(part_number=part_number, vendor=vendor, document=doc))
        else:
            entry.companions.append(doc)
    return registry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = ap.parse_args(argv)

    rendered = registry_yaml(build_registry())
    dest = registry_path()
    if args.check:
        current = dest.read_text(encoding="utf-8") if dest.exists() else ""
        if current != rendered:
            print(f"stale: {dest} — re-run {Path(__file__).name}", file=sys.stderr)
            return 1
        print(f"current: {dest}")
        return 0
    dest.write_text(rendered, encoding="utf-8")
    print(f"wrote {dest} ({len(rendered.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
