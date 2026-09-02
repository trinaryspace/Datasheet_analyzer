"""The reference family, over the corpora this repository actually ships.

Phase 7, ticket 07, first acceptance criterion: *a family of AFE7950 + AFE7953
builds with a correct delta table, hand-verified against both printed
datasheets*. This module is that criterion, run rather than asserted.

**Why the committed corpora and not a rebuild.** The lineage this ticket was
ported from rebuilt both members inside the test, because *its* committed
corpora carried no record ids and so could cite nothing. That is not this
branch's situation: `parts/AFE7950/docs/.../specs.json` carries an id on all
619 records and `parts/AFE7953` on all 536, so every row here is citable and
the delta table is real. A rebuild would also cost roughly six minutes (a
single `--vendor unknown` build of afe7950.pdf measured 181 s), which is not a
price a gate should pay for a substrate it already has.

**What "hand-verified" means here.** Two findings are checked against the
*printed page* of each PDF rather than against the corpus that produced them,
which is the same standard the phase-6 bit-field gate holds itself to:

- a **shared** row - `Peak Input Current`, §4.1, `20` (max), page 4 of both
  documents. Both members print it identically, so the family counts it and
  does not tabulate it;
- an **only-in** row - `IVDD0P9` under `Mode 10: 4T4R2F`, `3578.9` typ on page
  25 of AFE7950. AFE7950 is the quad-transmitter device and AFE7953 the dual,
  so `4T4R2F` appears on no page of afe7953.pdf at all. An absence is the
  finding a series reader is asking about, and this one is checked by reading
  every page of the other document rather than by trusting its corpus.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.derive.compare import compare_specs
from datasheet_analyzer.derive.provenance import parse_source, resolve_source
from datasheet_analyzer.extract.pdf_structure import page_texts
from datasheet_analyzer.families import (
    ALIGNED_ROW,
    STATE_SHARED,
    build_family_index,
    load_families,
    render_family_index,
    resolve,
    section_of,
    write_family_index,
)
from datasheet_analyzer.retrieve import FamilyRetriever, load_members
from datasheet_analyzer.tokens import count_tokens

MEMBERS = ("AFE7950", "AFE7953")
PARTS = Path(__file__).parent.parent.parent / "parts"

#: The shared finding, read off page 4 of both PDFs.
SHARED_ROW = {"section": "4.1", "name": "Peak Input Current", "max": "20", "page": 4}

#: The only-in finding, read off page 25 of afe7950.pdf. `4T4R2F` is the quad
#: device's operating mode and is printed nowhere in the dual device's document.
ONLY_IN_ROW = {
    "section": "4.9",
    "symbol": "IVDD0P9",
    "mode": "4T4R2F",
    "typ": "3578.9",
    "page": 25,
    "member": "AFE7950",
    "absent_from": "AFE7953",
}


@pytest.fixture(scope="module")
def family():
    """The declared family, built from the corpora committed under `parts/`."""
    if not (PARTS / "AFE7950" / "manifest.json").exists():
        pytest.skip("committed parts/AFE7950 corpus not present")
    if not (PARTS / "AFE7953" / "manifest.json").exists():
        pytest.skip("committed parts/AFE7953 corpus not present")
    entry = resolve(load_families(), "AFE795x")
    return build_family_index(
        load_members(entry.members, PARTS), name=entry.name, title=entry.title
    )


def _squashed(pdf: Path, page: int) -> str:
    """One printed page as a single run of text, whitespace collapsed."""
    return " ".join(page_texts(pdf)[page - 1].split())


@pytest.mark.integration
class TestTheReferenceFamily:
    def test_the_declared_membership_is_what_was_built(self, family):
        assert family.members == list(MEMBERS)
        assert family.reference == "AFE7950"
        assert not any("no corpus" in note for note in family.notes)

    def test_shared_sections_are_listed_once_and_divergent_ones_per_member(self, family):
        assert family.shared_sections, "the two datasheets share nothing?"
        assert family.divergent_sections
        text = render_family_index(family)
        for section in family.shared_sections:
            assert section.state == STATE_SHARED
            assert set(section.members) == set(MEMBERS)
            # one file, from the reference member, not one per member
            assert text.count(section.files["AFE7950"]) == 1
            assert section.files["AFE7953"] not in text

    def test_a_section_that_differs_by_one_value_is_not_shared(self, family):
        """Section 4.9 prints each device's own supply-current modes."""
        supplies = next(s for s in family.sections if s.number == "4.9")
        assert supplies.state != STATE_SHARED
        assert set(supplies.files) == set(MEMBERS)
        assert supplies.reason

    def test_the_renumbered_back_matter_folds_into_one_section(self, family):
        """AFE7950 numbers its support sections 6.x, AFE7953 numbers them 5.x."""
        support = [s for s in family.sections if s.title == "Support Resources"]
        assert len(support) == 1
        assert set(support[0].members) == set(MEMBERS)

    def test_the_hand_verified_shared_row_is_counted_and_not_tabulated(self, family):
        """A row both members print identically is the family's claim, not a row."""
        assert family.n_specs_identical > 0
        tabulated = {
            (r.symbol, section_of(r))
            for r in family.deltas
            if r.symbol == SHARED_ROW["name"] and section_of(r) == SHARED_ROW["section"]
        }
        assert tabulated == set(), "an identically-printed row must not be in the delta table"

    def test_the_hand_verified_shared_values_are_on_the_printed_pages(
        self, afe7950_pdf, afe7953_pdf
    ):
        """Not the corpus's word for it: page 4 of both PDFs."""
        for pdf in (afe7950_pdf, afe7953_pdf):
            printed = _squashed(pdf, SHARED_ROW["page"])
            assert SHARED_ROW["name"] in printed, pdf.name
            assert SHARED_ROW["max"] in printed, pdf.name

    def test_the_hand_verified_only_in_row_is_in_the_delta_table(self, family):
        row = next(
            r
            for r in family.deltas
            if r.symbol == ONLY_IN_ROW["symbol"]
            and section_of(r) == ONLY_IN_ROW["section"]
            and ONLY_IN_ROW["mode"] in next(iter(r.cells.values())).conditions
        )
        assert list(row.cells) == [ONLY_IN_ROW["member"]]
        assert row.missing_from == [ONLY_IN_ROW["absent_from"]]
        cell = row.cells[ONLY_IN_ROW["member"]]
        assert cell.values["typ"].verbatim == ONLY_IN_ROW["typ"]
        assert cell.values["typ"].page == ONLY_IN_ROW["page"]
        # The refusal, in the words the join wrote it: nothing this tool did
        # not read is invented to fill the other column.
        assert any("nothing published by" in line for line in row.not_comparable)

    def test_the_only_in_row_is_printed_by_one_pdf_and_by_no_page_of_the_other(
        self, afe7950_pdf, afe7953_pdf
    ):
        """An absence proved by reading every page, not by trusting a corpus."""
        printed = _squashed(afe7950_pdf, ONLY_IN_ROW["page"])
        assert ONLY_IN_ROW["symbol"] in printed
        assert ONLY_IN_ROW["typ"] in printed
        assert ONLY_IN_ROW["mode"] in printed.replace(" ", "")
        whole = "".join("".join(page.split()) for page in page_texts(afe7953_pdf))
        assert ONLY_IN_ROW["mode"] not in whole, "the dual device prints a quad-TX mode?"

    def test_every_row_that_aligned_states_what_it_aligned_on(self, family):
        for row in family.deltas:
            assert row.matched_on, row.key
            if row.status == "aligned":
                assert row.matched_on.startswith(f"{ALIGNED_ROW}:"), row.key

    def test_every_reference_resolves_to_a_record_and_a_printed_page(self, family):
        """Invariant 8's round trip over the whole delta table."""
        walked, unresolved = 0, []
        for row in family.deltas + family.pin_deltas + family.register_deltas:
            for part, cell in row.cells.items():
                for value in cell.values.values():
                    assert parse_source(value.source) is not None, value.source
                    walked += 1
                    if resolve_source(value.source, roots=PARTS / part) is None:
                        unresolved.append(value.source)
        assert not unresolved, unresolved[:5]
        assert walked > 100, walked

    def test_it_reports_what_it_refused_rather_than_dropping_it(self, family):
        assert family.unparsed, "a 700-row alignment refused nothing?"
        assert any(
            "nothing printed says which pairs with which" in line for line in family.unparsed
        )
        # Three kinds, measured on this family: 360 keys only one member
        # publishes, 16 keys a member prints several rows under, and 43
        # printed pairs whose two sides did not read into the same unit.
        # Every one of them is a line with the printed values on it.
        assert any("did not both parse to a number" in line for line in family.unparsed)

    def test_neither_member_publishes_pins_or_registers_and_it_says_so(self, family):
        """Honest absence: "no rows" must not read as "the pinouts agree"."""
        notes = " ".join(family.notes)
        assert "no member publishes pins" in notes
        assert "no member publishes registers" in notes
        assert family.pin_deltas == [] and family.register_deltas == []

    def test_the_printed_row_key_aligns_more_here_than_the_alias_key_would(self, family):
        """The design point of the `key_for` hook, measured on this family.

        `dsa compare` aligns two *unrelated* parts on the alias-resolved symbol.
        For one vendor's one document template that key is too coarse: it puts
        every supply current on one bucket. The printed-row key is strictly
        finer, so it pairs strictly more rows here, and the difference is the
        whole reason the hook exists.
        """
        alias = compare_specs([(p, PARTS / p) for p in MEMBERS])
        assert family.n_specs_aligned > len(alias.rows)


@pytest.mark.integration
class TestTheFamilyIndexEconomics:
    """The ticket's third criterion, measured and printed for the report."""

    def test_it_is_measurably_smaller_than_the_sum_of_its_members(self, family, tmp_path, capsys):
        settings = Settings(
            parts_dir=PARTS, cache_dir=tmp_path / ".cache", families_dir=tmp_path / "families"
        ).resolve()
        path, text = write_family_index(
            family,
            families_dir=settings.families_dir,
            token_budget=settings.family_index_token_budget,
        )
        family_tokens = count_tokens(text)
        members = {
            part: count_tokens((PARTS / part / "INDEX.md").read_text(encoding="utf-8"))
            for part in MEMBERS
        }
        total = sum(members.values())
        assert family_tokens <= settings.family_index_token_budget
        assert family_tokens < total
        assert path.exists() and (path.parent / "family.json").exists()
        with capsys.disabled():
            print()
            print("AFE795x family index economics")
            for part, tokens in members.items():
                print(f"  {part} INDEX.md          {tokens:>6} tok")
            print(f"  sum of member indexes {total:>6} tok")
            print(f"  FAMILY_INDEX.md       {family_tokens:>6} tok")
            print(f"  ratio                 {family_tokens / total:>6.3f}")
            shared = sum(s.tokens for s in family.shared_sections)
            print(
                f"  shared section bodies {shared:>6} tok, counted once instead of {len(MEMBERS)}x"
            )
            print(
                f"  sections {len(family.sections)} "
                f"({len(family.shared_sections)} shared), spec rows aligned "
                f"{family.n_specs_aligned} ({family.n_specs_identical} identical, "
                f"{len(family.deltas)} in the delta table), "
                f"{len(family.unparsed)} refusals listed"
            )

    def test_the_json_twin_holds_every_row_the_markdown_capped(self, family, tmp_path):
        import json

        path, text = write_family_index(
            family, families_dir=tmp_path / "families", token_budget=4000
        )
        payload = json.loads((path.parent / "family.json").read_text(encoding="utf-8"))
        assert len(payload["deltas"]) == len(family.deltas)
        if "rows shown" in text:
            assert len(payload["deltas"]) > text.count("\n| **")


@pytest.mark.integration
class TestAskTheRealFamily:
    def _scope(self) -> FamilyRetriever:
        return FamilyRetriever.for_parts("AFE795x", [PARTS / p for p in MEMBERS])

    def test_a_finding_both_members_print_identically_comes_back_once(self, family):
        pack = self._scope().ask("maximum junction temperature")
        assert pack.family == "AFE795x"
        assert pack.route != "none"
        shared = [line for line in pack.answers if line.shared_with]
        assert shared, pack.markdown
        assert all(set(line.shared_with) == set(MEMBERS) for line in shared)
        assert "common to AFE7950, AFE7953" in pack.markdown

    def test_a_finding_the_members_disagree_on_is_flagged_per_member(self, family):
        pack = self._scope().ask("Group 3C VDD1P8PLL supply current")
        assert pack.shared is False
        assert pack.divergence
        assert "not** common to every member" in pack.markdown
        assert "Per-member differences" in pack.markdown
        assert {line.part for line in pack.answers if line.part} <= set(MEMBERS)
