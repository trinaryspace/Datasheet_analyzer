"""Phase 7, ticket 03 gate — `dsa diff-rev` against a declared revision pair.

This repo carries exactly one revision of every part it holds, so there is no
real revision pair to diff. The honest substitute — and, for a *gate*, a stronger
one — is a **declared** pair: `tests/fixtures/synthetic/revision_pair.py` writes
two PDFs whose differences are a fixed, hand-written list (`EDITS`), and this
gate asserts the command finds **exactly** those differences and nothing else.
With a real pair the expected delta would itself have to be read off two PDFs by
hand; here it is known by construction, so a diff that missed a change or
invented one fails rather than looking plausible.

Everything runs through the real machinery: the PDFs go through
`PdfLayoutBackend` and the whole pipeline (`dsa build --rev`), land as two
document directories under one part, and the diff reads what was published.

The one thing this gate cannot prove is that a *vendor's* revision moves things
the way this fixture does. That is recorded as a live step in
`Reports/PHASE_7_LIVE_RUN.md` — the repo owner runs `dsa fetch` for a second
revision and re-runs the command with network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.config import Settings
from datasheet_analyzer.pipeline import BuildRefused, build_part
from datasheet_analyzer.retrieve import Retriever, clear_index_cache
from datasheet_analyzer.retrieve.revdiff import RevisionPair
from datasheet_analyzer.revdiff import (
    CHANGE_ADDED,
    CHANGE_CHANGED,
    CHANGE_PAGE_SHIFTED,
    CHANGE_REMOVED,
    CHANGE_RENAMED,
    CHANGE_RETITLED,
    FLAG_REVIEW,
    KIND_PIN,
    KIND_SECTION,
    KIND_SPEC,
)

# The fixture generator is a module under `tests/fixtures/synthetic/`, imported by
# path rather than as a package so it stays beside the other synthetic fixtures.
sys.path.insert(0, str(Path(__file__).parent.parent / "fixtures" / "synthetic"))
import revision_pair

#: The diff `EDITS` must produce, as `(kind, change, key, printed column)`. Read
#: this beside `revision_pair.EDITS`: every line here is one line there, and the
#: gate asserts the two sets are equal — no change missed, none invented.
EXPECTED: set[tuple[str, str, str, str]] = {
    # rev B inserts a page, so §4 now spans two and §5 starts one later
    (KIND_SECTION, CHANGE_PAGE_SHIFTED, "4", "page"),
    (KIND_SECTION, CHANGE_ADDED, "4.2", ""),
    (KIND_SECTION, CHANGE_RETITLED, "5", "title"),
    (KIND_SECTION, CHANGE_PAGE_SHIFTED, "5", "page"),
    # the two numeric moves, and the three that cannot be scored
    (KIND_SPEC, CHANGE_CHANGED, "TJ", "max"),
    (KIND_SPEC, CHANGE_CHANGED, "IDD", "typ"),
    (KIND_SPEC, CHANGE_CHANGED, "Output noise", "typ"),
    (KIND_SPEC, CHANGE_ADDED, "Turn-on time", ""),
    (KIND_SPEC, CHANGE_REMOVED, "Gain Error", ""),
    # the deltas designers least expect to have to check
    (KIND_PIN, CHANGE_RENAMED, "A2", "name"),
    (KIND_PIN, CHANGE_ADDED, "B3", ""),
    (KIND_PIN, CHANGE_REMOVED, "A4", ""),
}


@pytest.fixture(scope="module")
def two_revisions(tmp_path_factory):
    """Both revisions built under one part, through the real pipeline.

    Module-scoped because building two PDFs twice per test would be the slowest
    thing in this file for no gain; nothing here mutates the corpus.
    """
    tmp_path = tmp_path_factory.mktemp("revdiff")
    rev_a, rev_b = revision_pair.write_pair(tmp_path / "pdfs")
    settings = Settings(
        parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache"
    ).resolve()
    for pdf, label in ((rev_a, "A"), (rev_b, "B")):
        build_part(
            pdf,
            part_number=revision_pair.PART,
            settings=settings,
            vendor="unknown",
            use_llm=False,
            revision_label=label,
        )
    clear_index_cache()
    return settings, settings.parts_dir / revision_pair.PART, rev_a


class TestTwoRevisionsCoexist:
    """The ticket's first criterion, end to end through `dsa build --rev`."""

    def test_each_revision_gets_its_own_document_directory(self, two_revisions):
        _, part_dir, _ = two_revisions
        docs = sorted(d.name for d in (part_dir / "docs").iterdir())
        assert len(docs) == 2
        assert sorted(d.rsplit("-rev", 1)[1] for d in docs) == ["a", "b"]
        # the content hash still distinguishes them; the label is legibility
        assert docs[0].rsplit("-rev", 1)[0] != docs[1].rsplit("-rev", 1)[0]
        for doc in docs:
            assert (part_dir / "docs" / doc / "specs.json").exists()
            assert (part_dir / "docs" / doc / "pins.json").exists()

    def test_the_inventory_records_both_labels_beside_both_hashes(self, two_revisions):
        _, part_dir, _ = two_revisions
        sources = json.loads((part_dir / "sources.json").read_text(encoding="utf-8"))
        assert [s["revision_label"] for s in sources] == ["A", "B"]
        assert len({s["content_hash"] for s in sources}) == 2

    def test_both_revisions_remain_independently_queryable(self, two_revisions):
        """One query, two answers, each cited to the revision it came from."""
        _, part_dir, _ = two_revisions
        # the designer's-words door, because the layout floor read this row's
        # printed name rather than a symbol — which is exactly why the diff
        # aligns on the alias lexicon and not on the printed string
        hits = Retriever.for_part(part_dir).specs(name="junction temperature")
        by_doc = {hit.citation.doc: hit.record.max for hit in hits}
        assert len(by_doc) == 2
        assert sorted(by_doc.values()) == ["105", "125"]
        assert all("-rev" in doc for doc in by_doc)

    def test_a_contradicting_label_for_the_same_bytes_is_refused(self, two_revisions):
        """Re-labelling would rename a directory every citation points at."""
        settings, _, rev_a = two_revisions
        with pytest.raises(BuildRefused) as excinfo:
            build_part(
                rev_a,
                part_number=revision_pair.PART,
                settings=settings,
                vendor="unknown",
                use_llm=False,
                revision_label="C",
            )
        assert "already registered" in str(excinfo.value)
        assert "'A'" in str(excinfo.value)


class TestDeclaredEditsAreFoundExactly:
    """The ticket's hand-checked expectation: exactly `EDITS`, nothing else."""

    def test_the_diff_is_the_declared_edit_list(self, two_revisions):
        _, part_dir, _ = two_revisions
        pair, error = RevisionPair.for_part(part_dir, before="A", after="B")
        assert error == "", error
        diff = pair.diff()

        found = {(c.kind, c.change, c.key, c.field) for c in diff.changes}
        assert found == EXPECTED
        assert len(diff.changes) == len(EXPECTED) == len(revision_pair.EDITS)

    def test_the_two_numeric_moves_carry_deltas_and_nothing_else_does(
        self, two_revisions
    ):
        _, part_dir, _ = two_revisions
        pair, _ = RevisionPair.for_part(part_dir, before="A", after="B")
        diff = pair.diff()

        scored = {c.key: c for c in diff.changes if c.delta is not None}
        assert set(scored) == {"TJ", "IDD"}
        assert scored["TJ"].delta.value_si == pytest.approx(20.0)
        assert scored["TJ"].delta.unit_si == "°C"
        assert scored["TJ"].delta.derivation == "si_delta:max"
        assert "105 °C -> 125 °C" in scored["TJ"].summary
        # mA is scaled to its SI base before subtraction, as everywhere else
        assert scored["IDD"].delta.value_si == pytest.approx(0.015)
        assert scored["IDD"].delta.unit_si == "A"

    def test_everything_else_is_quoted_verbatim_and_never_scored(self, two_revisions):
        _, part_dir, _ = two_revisions
        pair, _ = RevisionPair.for_part(part_dir, before="A", after="B")
        diff = pair.diff()

        unscored = [c for c in diff.changes if c.delta is None]
        assert len(unscored) == len(EXPECTED) - 2
        assert all(FLAG_REVIEW in c.flags for c in unscored)
        assert len(diff.review_by_hand) == len(unscored)
        noise = next(c for c in unscored if c.key == "Output noise")
        assert (noise.before.verbatim, noise.after.verbatim) == (
            "See Figure 7 nV/rtHz",
            "See Figure 9 nV/rtHz",
        )
        assert any("See Figure 7" in line for line in diff.review_by_hand)

    def test_the_rows_that_did_not_move_say_nothing(self, two_revisions):
        """Including the one printing an unreadable value on both sides."""
        _, part_dir, _ = two_revisions
        pair, _ = RevisionPair.for_part(part_dir, before="A", after="B")
        diff = pair.diff()

        keys = {c.key for c in diff.changes}
        assert "Phase noise" not in keys  # prints "See Figure 12" in both
        assert "Supply voltage" not in keys
        assert not any(c.kind == KIND_SECTION and c.key == "4.1" for c in diff.changes)
        assert not any(c.kind == KIND_PIN and c.key in {"A1", "A3", "B1", "B2"}
                       for c in diff.changes)

    def test_every_change_cites_the_pages_both_revisions_printed_it_on(
        self, two_revisions
    ):
        _, part_dir, _ = two_revisions
        pair, _ = RevisionPair.for_part(part_dir, before="A", after="B")
        diff = pair.diff()

        for change in diff.changes:
            for value in (change.before, change.after):
                if value is None:
                    continue
                assert value.page is not None, change.summary
                assert value.source, change.summary

    def test_diffing_a_revision_against_itself_is_empty(self, two_revisions):
        """The determinism check: identical input, no changes, and it says so."""
        _, part_dir, _ = two_revisions
        pair, error = RevisionPair.for_part(part_dir, before="A", after="A")
        assert error == ""
        diff = pair.diff()
        assert diff.changes == []
        assert diff.identical is True
        assert diff.review_by_hand == []


class TestTheWrittenReport:
    def test_the_command_writes_revision_diff_md_with_every_change_in_it(
        self, two_revisions, monkeypatch, capsys
    ):
        settings, part_dir, _ = two_revisions
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)

        assert cli.main(
            ["diff-rev", "--part", revision_pair.PART, "--from", "A", "--to", "B"]
        ) == 0
        capsys.readouterr()

        text = (part_dir / "REVISION_DIFF.md").read_text(encoding="utf-8")
        assert "## Sections" in text and "## Specs" in text and "## Pins" in text
        assert "## Review by hand" in text
        assert "105 °C" in text and "125 °C" in text
        assert "+20 °C *(derived)*" in text
        assert "Pin Configuration and Functions" in text
        assert "VDD1P8" in text
