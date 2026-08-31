"""The reference family, built offline from both printed datasheets.

Phase 7, ticket 07, first acceptance criterion: *a family of AFE7950 + AFE7953
builds with a correct delta table, hand-verified against both printed
datasheets*. This module is that criterion, run rather than asserted.

**Why the corpora are built here instead of read from `parts/`.** The two
corpora committed under `parts/` were published by an older pipeline and carry
no record ids, so nothing in them can be cited and no delta table can honestly
be produced from them (`tests/unit/test_families.py::TestTheCheckedInDeclarationBuilds`
asserts exactly that reading, and `dsa audit`'s fleet test asserts the same
corpora are old-schema). Rebuilding them **in this test** is what gives the
ticket a current-schema pair without touching a committed corpus that other
tests measure. Both members go through the vendor-neutral layout floor
(`--vendor unknown`, the same escape hatch LM741 and LMX1204 use), which is
offline by construction — the recorded TI document-viewer pages under
`tests/fixtures/recorded_http/` are AFE7950's only, so the ti_html path cannot
be replayed for AFE7953 at all. That gap is recorded as a live step in
`Reports/PHASE_7_LIVE_RUN.md`.

**What "hand-verified" means here.** The one spec delta both members print is
IVDD1P8 for `Group 3C: VDD1P8PLL +`: 12.6 mA on AFE7950 p.24 and 16 mA on
AFE7953 p.24. The test does not take the corpus's word for either number — it
re-reads the *printed page* of each PDF and requires the value to appear there,
which is the same standard the phase-6 bit-field gate holds itself to.
"""

from __future__ import annotations

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.extract.pdf_structure import page_texts
from datasheet_analyzer.families import (
    STATE_SHARED,
    build_family_index,
    load_families,
    render_family_index,
    resolve,
)
from datasheet_analyzer.families.store import write_family_index
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.provenance import parse_source
from datasheet_analyzer.retrieve import FamilyRetriever, load_members
from datasheet_analyzer.tokens import count_tokens

MEMBERS = ("AFE7950", "AFE7953")

#: The hand-verified difference. `(section, printed symbol, printed name, the
#: value each member prints, the printed page)` — read off p.24 of both PDFs.
HAND_VERIFIED = {
    "section": "4.9",
    "symbol": "IVDD1P8",
    "name": "Group 3C: VDD1P8PLL +",
    "printed": {"AFE7950": "12.6", "AFE7953": "16"},
    "page": 24,
    "unit": "mA",
}


@pytest.fixture(scope="module")
def family(tmp_path_factory, afe7950_pdf, afe7953_pdf):
    """Both members built offline through the layout floor, once per module."""
    root = tmp_path_factory.mktemp("family")
    settings = Settings(
        parts_dir=root / "parts",
        cache_dir=root / ".cache",
        families_dir=root / "families",
    ).resolve()
    for pdf, part in ((afe7950_pdf, "AFE7950"), (afe7953_pdf, "AFE7953")):
        build_part(
            pdf, part_number=part, settings=settings, vendor="unknown",
            use_llm=False, use_cache=False,
        )
    entry = resolve(load_families(), "AFE795x")
    index = build_family_index(
        load_members(entry.members, settings.parts_dir),
        name=entry.name,
        title=entry.title,
    )
    return settings, index


@pytest.mark.integration
class TestTheReferenceFamily:
    def test_the_declared_membership_is_what_was_built(self, family):
        _settings, index = family
        assert index.members == list(MEMBERS)
        assert index.reference == "AFE7950"
        assert not any("no corpus" in note for note in index.notes)

    def test_shared_sections_are_listed_once_and_divergent_ones_per_member(
        self, family
    ):
        _settings, index = family
        assert index.shared_sections, "the two datasheets share nothing?"
        assert index.divergent_sections
        text = render_family_index(index)
        for section in index.shared_sections:
            assert section.state == STATE_SHARED
            assert set(section.members) == set(MEMBERS)
            # one file, from the reference member, not one per member
            assert text.count(section.files["AFE7950"]) == 1
            assert section.files["AFE7953"] not in text

    def test_a_section_that_differs_by_one_value_is_not_shared(self, family):
        """§4.5 prints different transmitter numbers in each device."""
        _settings, index = family
        transmitter = next(s for s in index.sections if s.number == "4.5")
        assert transmitter.state != STATE_SHARED
        assert set(transmitter.files) == set(MEMBERS)

    def test_the_renumbered_back_matter_folds_into_one_section(self, family):
        """AFE7950 numbers its support sections §6.x, AFE7953 §5.x."""
        _settings, index = family
        support = [s for s in index.sections if s.title == "Support Resources"]
        assert len(support) == 1
        assert set(support[0].members) == set(MEMBERS)

    def test_the_hand_verified_delta_is_in_the_table(self, family):
        _settings, index = family
        row = next(
            r
            for r in index.deltas
            if r.key == HAND_VERIFIED["symbol"] and r.group == HAND_VERIFIED["section"]
        )
        printed = {
            c.part_number: c.values["typ"].verbatim for c in row.cells
        }
        assert printed == {
            part: f"{value} {HAND_VERIFIED['unit']}"
            for part, value in HAND_VERIFIED["printed"].items()
        }
        assert all(
            c.values["typ"].page == HAND_VERIFIED["page"] for c in row.cells
        )
        delta = next(c.delta for c in row.cells if c.part_number == "AFE7953")
        assert delta.derivation == "si_delta:typ"
        assert delta.unit_si == "A"
        assert delta.value_si == pytest.approx(0.0034, rel=1e-6)
        assert delta.verbatim == ""

    def test_the_hand_verified_values_are_on_the_printed_pages(
        self, family, afe7950_pdf, afe7953_pdf
    ):
        """Not the corpus's word for it: the PDF's own page 24, both members."""
        pdfs = {"AFE7950": afe7950_pdf, "AFE7953": afe7953_pdf}
        for part, value in HAND_VERIFIED["printed"].items():
            text = page_texts(pdfs[part])[HAND_VERIFIED["page"] - 1]
            squashed = " ".join(text.split())
            assert HAND_VERIFIED["symbol"] in squashed, part
            assert "VDD1P8PLL" in squashed, part
            assert value in squashed, f"{part}: {value} not printed on p.24"

    def test_every_row_that_aligned_states_what_it_aligned_on(self, family):
        _settings, index = family
        for row in index.deltas:
            assert row.aligned_on.startswith("printed-row:"), row.key

    def test_every_reference_resolves_to_a_record_and_a_printed_page(self, family):
        """Invariant 8's round trip over the whole delta table."""
        from datasheet_analyzer.provenance import resolve_source

        settings, index = family
        walked = 0
        unresolved = []
        for row in index.deltas + index.pin_deltas + index.register_deltas:
            for cell in row.cells:
                values = list(cell.values.values())
                if cell.delta is not None:
                    values.append(cell.delta)
                for value in values:
                    for ref in value.refs:
                        parsed = parse_source(ref)
                        assert parsed is not None and parsed.part, ref
                        found = resolve_source(settings.parts_dir / parsed.part, ref)
                        walked += 1
                        if found is None:
                            unresolved.append(ref)
        assert not unresolved, unresolved[:5]
        assert walked > 100, walked

    def test_it_reports_what_it_refused_rather_than_dropping_it(self, family):
        _settings, index = family
        assert index.unparsed, "a 600-row alignment refused nothing?"
        assert any("uncomparable" in line for line in index.unparsed)
        headline = index.notes[0]
        assert f"{index.n_specs_identical} print the same values" in headline

    def test_neither_member_publishes_pins_or_registers_and_it_says_so(self, family):
        """Honest absence: 'no rows' must not read as 'the pinouts agree'."""
        _settings, index = family
        notes = " ".join(index.notes)
        assert "no member publishes pins" in notes
        assert "no member publishes registers" in notes
        assert index.pin_deltas == [] and index.register_deltas == []


@pytest.mark.integration
class TestTheFamilyIndexEconomics:
    """The ticket's third criterion, measured and printed for the report."""

    def test_it_is_measurably_smaller_than_the_sum_of_its_members(
        self, family, capsys
    ):
        settings, index = family
        path, text = write_family_index(
            index,
            families_dir=settings.families_dir,
            token_budget=settings.family_index_token_budget,
        )
        family_tokens = count_tokens(text)
        members = {
            part: count_tokens(
                (settings.parts_dir / part / "INDEX.md").read_text(encoding="utf-8")
            )
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
            shared = sum(s.tokens for s in index.shared_sections)
            print(
                f"  shared section bodies {shared:>6} tok, counted once instead "
                f"of {len(MEMBERS)}x"
            )
            print(
                f"  sections {len(index.sections)} "
                f"({len(index.shared_sections)} shared), spec rows aligned "
                f"{index.n_specs_aligned} ({index.n_specs_identical} identical, "
                f"{len(index.deltas)} in the delta table), "
                f"{len(index.unparsed)} refusals listed"
            )

    def test_the_json_twin_holds_every_row_the_markdown_capped(self, family):
        import json

        settings, index = family
        path, text = write_family_index(
            index,
            families_dir=settings.families_dir,
            token_budget=settings.family_index_token_budget,
        )
        payload = json.loads((path.parent / "family.json").read_text(encoding="utf-8"))
        assert len(payload["deltas"]) == len(index.deltas)
        if "rows shown" in text:
            assert len(payload["deltas"]) > text.count("\n| **")


@pytest.mark.integration
class TestAskTheRealFamily:
    def _scope(self, settings) -> FamilyRetriever:
        return FamilyRetriever.for_parts(
            "AFE795x", [settings.parts_dir / p for p in MEMBERS]
        )

    def test_a_finding_both_members_print_identically_comes_back_once(self, family):
        settings, _index = family
        pack = self._scope(settings).ask("maximum junction temperature")
        assert pack.family == "AFE795x"
        assert pack.route != "none"
        shared = [line for line in pack.answers if line.shared_with]
        assert shared, pack.markdown
        assert all(set(line.shared_with) == set(MEMBERS) for line in shared)
        assert "common to AFE7950, AFE7953" in pack.markdown

    def test_a_finding_the_members_disagree_on_is_flagged_per_member(self, family):
        settings, _index = family
        pack = self._scope(settings).ask("Group 3C VDD1P8PLL supply current")
        assert pack.shared is False
        assert pack.divergence
        assert "not** common to every member" in pack.markdown
        assert {line.part for line in pack.answers if line.part} == set(MEMBERS)
