"""A synthetic errata document for the real LM741 datasheet, with declared targets.

Phase 7, ticket 04. This repo carries no vendor errata PDF — `dsa add-doc --type
errata` and `dsa fetch --doc-type errata` have both existed for a while and
nothing has ever been filed under either — and one cannot be fetched offline.
What is *real* here is the document the errata items point **at**:
`tests/fixtures/pdf/lm741.pdf`, the committed gate datasheet, built by the real
pipeline into the corpus the linker matches against.

So every target below was read off that datasheet's own published records —
`§6.1 Absolute Maximum Ratings` on printed p.4 with its two `Junction
temperature` rows, and `§7.3.2 Latch-up Prevention` — and the errata *prose* is
the synthetic half. That split is what the gate can honestly claim: the matching
rules are proven against a real document's real section numbers and real spec
records, while the wording of the erratum, the part a vendor writes, is declared
here so the expectation is exact rather than approximate.

`ITEMS` is the contract. Item 2 exists to be **unplaceable**: it names no
section, no symbol, no pin and no register, so it must appear under "unlinked
errata" and must never disappear. A change to the linker that started matching
it on prose similarity would fail this fixture, which is the point.
"""

from __future__ import annotations

from pathlib import Path

import fitz

PAGE_W, PAGE_H = 612.0, 792.0

PART = "LM741"

#: `(marker, printed lines)` for each item, in printed order. The marker word is
#: one `registry/errata.yaml` declares, so segmentation is by the marker rule.
ITEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Advisory 1",
        (
            "Section 6.1 Absolute Maximum Ratings: the junction temperature",
            "limit printed for this device is incorrect and must be derated",
            "by 25 degrees for continuous operation.",
        ),
    ),
    (
        "Advisory 2",
        (
            "Under certain assembly conditions the part exhibits an anomaly",
            "that has not yet been characterized. Contact the factory before",
            "committing to a production build.",
        ),
    ),
    (
        "Advisory 3",
        (
            "The behaviour described in §7.3.2 is not guaranteed over the",
            "full ambient range and will be restated in a future revision.",
        ),
    ),
)

#: What each item must link to, as `(kind, a substring of the target reference)`,
#: read off the built LM741 corpus by hand. An empty tuple means the item must be
#: published **unlinked** — the criterion this ticket exists to protect.
#:
#: The reference shape is this branch's: a record id is a *stable* one
#: (`rec_<section key>-t<table>-r<row>`, ADR 0005 as this lineage spells it),
#: not an ordinal, and lm741 is published once into the shared library store, so
#: every reference here hangs off `@library/docs/<doc>/…`. Both halves are
#: asserted — the tail below, and the `@library/` root in the gate itself.
EXPECTED: dict[str, tuple[tuple[str, str], ...]] = {
    "Advisory 1": (
        ("section", "sections/6-1-absolute-maximum-ratings.md"),
        ("spec", "specs.json#rec_s6_1_absolute_maximum_ratings-t0-r8"),
        ("spec", "specs.json#rec_s6_1_absolute_maximum_ratings-t0-r9"),
    ),
    "Advisory 2": (),
    "Advisory 3": (("section", "sections/7-3-2-latch-up-prevention.md"),),
}

#: The rule each expected link must have been produced by, so a link that landed
#: on the right target for the wrong reason fails. `matched_on` carries the same
#: information in prose; this is its machine-checkable half.
#:
#: The two spec rows are reached by `alias-phrase`, not by `spec-symbol`, and
#: that is a fact about this datasheet rather than a preference: lm741 prints
#: no symbol column in its absolute-maximum table, so the layout floor records
#: `Junction temperature` in the symbol field and the symbol rule's
#: looks-like-a-symbol guard correctly declines it. The alias lexicon carries
#: `junction temperature -> TJ`, and that is the path that reaches the row —
#: graded `medium` because it went through a second artifact.
EXPECTED_RULES: dict[str, str] = {
    "sections/6-1-absolute-maximum-ratings.md": "section-number",
    "specs.json#rec_s6_1_absolute_maximum_ratings-t0-r8": "alias-phrase",
    "specs.json#rec_s6_1_absolute_maximum_ratings-t0-r9": "alias-phrase",
    "sections/7-3-2-latch-up-prevention.md": "section-number",
}


def write_errata_pdf(path: Path) -> Path:
    """Write the errata document to `path` and return it.

    One page, no outline: the `pdf_text` backend then publishes one section per
    page, which is the shape a short vendor errata sheet really has and the one
    that exercises the page-attribution rule — an item takes its section's page
    range, never an invented single page.
    """
    path = Path(path)
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    y = 72.0
    page.insert_text((72.0, y), f"{PART} Errata")
    y += 24.0
    for marker, lines in ITEMS:
        page.insert_text((72.0, y), marker)
        y += 16.0
        for line in lines:
            page.insert_text((72.0, y), line)
            y += 16.0
        y += 8.0
    page.insert_text((300.0, 750.0), "1")
    doc.save(str(path))
    doc.close()
    return path
