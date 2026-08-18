"""A synthetic errata document for the real LM741 datasheet, with declared targets.

Phase 7, ticket 04. This repo carries no vendor errata PDF — `dsa add-doc
--type errata` has existed since phase 3 and nothing has ever been filed under
it — and one cannot be fetched offline. What is *real* here is the document the
errata items point **at**: `tests/fixtures/pdf/lm741.pdf`, the committed gate
datasheet, built by the real pipeline into the corpus the linker matches
against. So every target below was read off that datasheet's own published
records by hand (`§6.1 Absolute Maximum Ratings` on printed p.4, its two
`Junction temperature` rows, `§7.3.2 Latch-up Prevention` on p.7), and the
errata *prose* is the synthetic half.

That split is deliberate and is what the gate can honestly claim: the matching
rules are proven against a real document's real section numbers and real spec
records, while the wording of the erratum — the part a vendor writes — is
declared here so the expectation is exact rather than approximate. Linking a
genuine vendor errata PDF is recorded as a live step in
`Reports/PHASE_7_LIVE_RUN.md`.

`ITEMS` is the contract. Item 2 exists to be **unplaceable**: it names no
section, no symbol, no pin and no register, so it must appear under "unlinked
errata" and never disappear. A change to the linker that started matching it on
prose similarity would fail this fixture, which is the point.
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

#: What each item must link to, as `(kind, a substring of the target id)`, read
#: off the built LM741 corpus by hand. An empty tuple means the item must be
#: published **unlinked** — the criterion this ticket exists to protect.
EXPECTED: dict[str, tuple[tuple[str, str], ...]] = {
    "Advisory 1": (
        ("section", "sections/6-1-absolute-maximum-ratings.md"),
        ("spec", "specs.json#rec_9"),
        ("spec", "specs.json#rec_10"),
    ),
    "Advisory 2": (),
    "Advisory 3": (("section", "sections/7-3-2-latch-up-prevention.md"),),
}

#: The rule each expected link must have been produced by, so a link that landed
#: on the right target for the wrong reason fails. `matched_on` carries the same
#: information in prose; this is its machine-checkable half.
EXPECTED_RULES: dict[str, str] = {
    "sections/6-1-absolute-maximum-ratings.md": "section-number",
    "specs.json#rec_9": "alias-phrase",
    "specs.json#rec_10": "alias-phrase",
    "sections/7-3-2-latch-up-prevention.md": "section-number",
}


def write_errata_pdf(path: Path) -> Path:
    """Write the errata document to `path` and return it.

    One page, no outline: the `pdf_text` backend then publishes one section per
    page, which is the shape a short vendor errata sheet really has and the one
    that exercises the page-attribution rule (an item takes its section's page
    range, never an invented single page).
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
