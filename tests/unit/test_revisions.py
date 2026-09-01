"""Revision awareness + staleness surfacing (phase 7, ticket 02).

This file grows with the ticket. What is proven here so far:

- **the revision parser is tight enough to read a literature number** -
  `sniff_revision` returns `SNAS800B` for `lmx1204.pdf` rather than the page-1
  pin name `SYSREFOUT0`, and reads nothing at all off the three Mini-Circuits
  datasheets whose heading word `SPECIFICATIONS1` used to pass for one. Every
  document in this checkout is asserted, so tightening the shape cannot quietly
  cost a reading that already worked;
- **one lexicon, two doors** - a document on disk and a document that only
  exists as downloaded bytes read through the same rules, which is what lets
  `dsa check-revisions` compare an upstream document it never writes down.

Hermetic by construction (invariant 4): nothing here opens a socket, and the
synthetic PDFs are built in-test with `fitz`.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from datasheet_analyzer.extract.pdf_structure import (
    revision_from_texts,
    sniff_revision,
    sniff_revision_bytes,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Every PDF this checkout can hold, with the revision the shared lexicon must
#: read off it. The first two are the readings the ticket moved; the rest are
#: the regression guard. Repo-root working copies are skip-guarded because they
#: are not all tracked - `lmx1204.pdf` and `LMX1204_registermap.pdf` in
#: particular are working files on this branch, not committed documents.
COMMITTED_DOCUMENTS = [
    ("lmx1204.pdf", "SNAS800B"),
    ("tests/fixtures/pdf/LHA-83W+.pdf", ""),
    ("tests/fixtures/pdf/PMA1-14LN+.pdf", ""),
    ("tests/fixtures/pdf/PSA-8A+.pdf", ""),
    ("tests/fixtures/pdf/ZX10R-2-183-S+.pdf", ""),
    ("LMX1204_registermap.pdf", "SNAU269A"),
    ("tests/fixtures/pdf/lm741.pdf", "SNOSC25D"),
    ("tests/fixtures/pdf/ad9081.pdf", "Rev. 0"),
    ("tests/fixtures/pdf/hmc520a.pdf", "Rev. A"),
    ("tests/fixtures/pdf/QPA1003P.pdf", "Rev. I"),
    ("afe7950.pdf", "SBASA41E"),
    ("afe7953.pdf", "SBASAN1A"),
]


def _make_pdf(path: Path, revision: str, marker: str = "") -> bytes:
    """A tiny, readable datasheet-shaped PDF with a sniffable revision.

    `marker` changes the bytes without changing the revision - which is exactly
    the upstream behaviour the ticket measured (a package-materials addendum
    regenerated with the current date) and the case that must NOT read stale.
    """
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), f"TEST9100 Quad RF transceiver. {marker}")
    p1.insert_text((72, 700), f"Rev. {revision}")
    p2 = doc.new_page()
    p2.insert_text(
        (72, 72),
        "4.1 Absolute Maximum Ratings VDD1P2 Supply voltage 1.2V -0.3 1.4 V TJ 150 C",
    )
    doc.set_toc([[1, "1 Features", 1], [1, "4.1 Absolute Maximum Ratings", 2]])
    doc.save(path)
    doc.close()
    return path.read_bytes()


class TestRevisionParser:
    def test_lmx1204_reads_its_own_literature_number(self):
        """The ticket headline defect: a pin name won over the real id."""
        pdf = REPO_ROOT / "lmx1204.pdf"
        if not pdf.exists():
            pytest.skip("lmx1204.pdf is not present in this checkout")
        assert sniff_revision(pdf) == "SNAS800B"

    @pytest.mark.parametrize("rel,expected", COMMITTED_DOCUMENTS)
    def test_every_document_in_this_checkout_still_reads_its_revision(self, rel, expected):
        path = REPO_ROOT / rel
        if not path.exists():  # the repo-root working copies are skip-guarded
            pytest.skip(f"{rel} is not present in this checkout")
        assert sniff_revision(path) == expected

    def test_a_signal_name_is_not_a_document_id(self):
        """The exact page-1 token order measured on LMX1204."""
        page = "SYSREFOUT0 SYSREFOUT1 SYSREFOUT2 SYSREFOUT3 ... SNAS800B"
        assert revision_from_texts([page]) == "SNAS800B"

    @pytest.mark.parametrize(
        "text",
        [
            "SUPPORT",  # all letters: no digit in the tail
            "SYSREF1",  # ends in a digit, not a revision letter
            "SYSREFOUT0",  # too long to be a literature number
            "SPI SDI SDO",  # ordinary three-letter signal names
            "SPECIFICATIONS1",  # the Mini-Circuits heading word, measured here
        ],
    )
    def test_shapes_that_are_not_literature_numbers_read_as_nothing(self, text):
        assert revision_from_texts([text]) == ""

    def test_a_rev_token_still_wins_within_a_page(self):
        assert revision_from_texts(["SNAS800B and Rev. C"]) == "Rev. C"

    def test_bytes_and_paths_read_the_same_lexicon(self, tmp_path):
        payload = _make_pdf(tmp_path / "x.pdf", "C")
        assert sniff_revision_bytes(payload) == "Rev. C"
        assert sniff_revision(tmp_path / "x.pdf") == "Rev. C"

    def test_unreadable_bytes_are_an_honest_miss_not_a_crash(self):
        assert sniff_revision_bytes(b"<html>document not found</html>") == ""
