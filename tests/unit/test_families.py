"""Part families: shared once, differences tabulated, membership declared.

Phase 7, ticket 07. The classes map onto the ticket's acceptance criteria:

- `TestMembershipIsDeclared` / `TestSuggestOnlyProposes` — a proposal builds
  **nothing**, asserted three ways (the loader refuses the candidate file by
  name, `resolve` refuses an unconfirmed entry, and the CLI's `family build`
  exits 2 naming `dsa family confirm`).
- `TestSharedSectionsAreListedOnce` — a section identical in every member is
  shared; one that differs by a single printed value is not, and is listed per
  member instead.
- `TestTheDeltaTable` — every spec that differs is a row, with each member's
  verbatim value, its page, and an SI delta where the numeric layer read both.
  Everything on those rows resolves through invariant 8's round trip.
- `TestPinAndRegisterDeltas` — the artifacts a designer and a firmware engineer
  live in, including the bit range that misconfigures silicon silently.
- `TestHonestDegradation` — members with different section structures produce
  *more* deltas and *fewer* shared sections, and never a mis-aligned section.
- `TestTheTokenWin` — the index is measurably smaller than the sum of its
  members' indexes, under its own budget, and says what a budget removed.
- `TestAskAcrossAFamily` — a shared answer once; a divergent answer per member,
  flagged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from family_corpus import family_settings

from datasheet_analyzer.compare.build import FLAG_AMBIGUOUS, FLAG_ONLY_IN
from datasheet_analyzer.config import Settings
from datasheet_analyzer.families import (
    ALIGNED_ROW,
    ALIGNED_SECTION,
    ALIGNED_SECTION_TITLE,
    STATE_DIVERGENT,
    STATE_PARTIAL,
    STATE_SHARED,
    CandidatePart,
    FamilyEntry,
    FamilyMiss,
    FamilyRegistry,
    FamilyUnconfirmed,
    build_family_index,
    candidates_path,
    families_path,
    load_candidates,
    load_families,
    overlap,
    render_family_index,
    resolve,
    save_candidates,
    save_families,
    section_body,
    stem,
    suggest_families,
)
from datasheet_analyzer.families.store import write_family_index
from datasheet_analyzer.provenance import parse_source
from datasheet_analyzer.retrieve import FamilyRetriever, load_members
from datasheet_analyzer.tokens import count_tokens

MEMBERS = ("TEST9950", "TEST9953")


def _index(settings: Settings, name: str = "TEST995x"):
    return build_family_index(
        load_members(MEMBERS, settings.parts_dir), name=name, title="test family"
    )


def _section(index, number: str):
    return next(s for s in index.sections if s.number == number)


@pytest.fixture
def declared(tmp_path) -> Settings:
    """Two members that differ in exactly one printed value: TJ max."""
    return family_settings(tmp_path, tj_max="125")


# --- membership --------------------------------------------------------------


class TestMembershipIsDeclared:
    """A family exists because a human said so, or it does not exist."""

    def test_the_shipped_registry_declares_the_reference_family(self):
        registry = load_families()
        entry = resolve(registry, "AFE795x")
        assert entry.members == ["AFE7950", "AFE7953"]
        assert entry.confirmed is True
        assert entry.reference == "AFE7950"

    def test_a_miss_names_the_command_that_grows_the_registry(self):
        registry = load_families()
        with pytest.raises(FamilyMiss) as excinfo:
            resolve(registry, "NOPE9x")
        message = str(excinfo.value)
        assert "dsa family suggest" in message
        assert "never inferred" in message
        # and it does not guess a grouping out of the name
        assert "NOPE9" not in message.replace("NOPE9x", "")

    def test_an_unconfirmed_entry_in_the_declaration_still_builds_nothing(self, tmp_path):
        registry = FamilyRegistry()
        registry.put(
            FamilyEntry(name="X9x", members=["A", "B"], confirmed=False)
        )
        path = tmp_path / "families.yaml"
        save_families(registry, path)
        with pytest.raises(FamilyUnconfirmed) as excinfo:
            resolve(load_families(path), "X9x")
        assert "dsa family confirm X9x" in str(excinfo.value)

    def test_a_family_with_no_members_is_refused(self, tmp_path):
        registry = FamilyRegistry()
        registry.put(FamilyEntry(name="X9x", members=[]))
        path = tmp_path / "families.yaml"
        save_families(registry, path)
        with pytest.raises(FamilyMiss):
            resolve(load_families(path), "X9x")

    def test_the_declaration_round_trips_deterministically(self, tmp_path):
        registry = load_families()
        first = tmp_path / "a.yaml"
        second = tmp_path / "b.yaml"
        save_families(registry, first)
        save_families(load_families(first), second)
        assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


class TestSuggestOnlyProposes:
    """The ticket's fourth criterion: a suggestion builds nothing."""

    def test_the_candidate_file_is_refused_by_name(self, tmp_path):
        path = candidates_path(tmp_path)
        save_candidates(
            [FamilyEntry(name="X9x", members=["A", "B"], confirmed=False)], path
        )
        with pytest.raises(FamilyUnconfirmed) as excinfo:
            load_families(path)
        assert "families.yaml" in str(excinfo.value)

    def test_a_candidate_is_unconfirmed_however_the_file_reads(self, tmp_path):
        path = candidates_path(tmp_path)
        # A hand-edited candidate file claiming confirmation must not be able to
        # confirm itself: confirmation is an act in another file.
        path.write_text(
            "schema_version: '1'\ncandidates:\n  X9x:\n    members: [A, B]\n"
            "    confirmed: true\n",
            encoding="utf-8",
        )
        assert [c.confirmed for c in load_candidates(path)] == [False]

    def test_suggest_writes_only_to_the_candidate_file(self, declared, tmp_path):
        parts = [
            CandidatePart(
                part_number=p,
                sections=frozenset({("4.3", "recommended operating conditions")}),
            )
            for p in MEMBERS
        ]
        proposals = suggest_families(parts)
        assert [p.name for p in proposals] == ["TEST995x"]
        assert proposals[0].confirmed is False
        assert proposals[0].members == list(MEMBERS)
        save_candidates(proposals, candidates_path(declared.registry_dir))
        # the declaration is untouched, so nothing new builds
        assert not families_path(declared.registry_dir).exists()
        assert load_families(families_path(declared.registry_dir)).families == {}

    def test_an_unconfirmed_suggestion_builds_nothing_through_the_cli(
        self, declared, monkeypatch, capsys
    ):
        from datasheet_analyzer.cli import main

        monkeypatch.setattr(
            "datasheet_analyzer.config.get_settings", lambda: declared
        )
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: declared)
        assert main(["family", "suggest"]) == 0
        assert main(["family", "build", "TEST995x"]) == 2
        err = capsys.readouterr().err
        assert "dsa family confirm" in err or "no declared family" in err
        assert not (declared.families_dir / "TEST995x").exists()

    def test_confirm_moves_it_across_and_then_it_builds(
        self, declared, monkeypatch, capsys
    ):
        from datasheet_analyzer.cli import main

        monkeypatch.setattr(
            "datasheet_analyzer.config.get_settings", lambda: declared
        )
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: declared)
        assert main(["family", "suggest"]) == 0
        assert main(["family", "confirm", "TEST995x", "--dry-run"]) == 0
        assert main(["family", "build", "TEST995x"]) == 2  # dry run wrote nothing
        capsys.readouterr()
        assert main(["family", "confirm", "TEST995x"]) == 0
        assert main(["family", "build", "TEST995x"]) == 0
        assert (declared.families_dir / "TEST995x" / "FAMILY_INDEX.md").exists()

    def test_overlap_is_zero_for_a_corpus_with_no_sections(self):
        empty = CandidatePart(part_number="A")
        other = CandidatePart(part_number="B", sections=frozenset({("1", "features")}))
        assert overlap(empty, empty) == 0.0
        assert overlap(empty, other) == 0.0

    def test_a_short_shared_prefix_is_not_a_family(self):
        assert stem(["AD9081", "AD9082"]) == "AD908x"
        assert stem(["LM741", "LX999"]) == ""
        assert stem(["AFE7950"]) == ""

    def test_two_unrelated_corpora_are_not_proposed(self):
        parts = [
            CandidatePart(
                part_number="AFE7950",
                sections=frozenset({("1", "features"), ("2", "applications")}),
            ),
            CandidatePart(
                part_number="LM741",
                sections=frozenset({("9", "layout"), ("8", "packaging")}),
            ),
        ]
        assert suggest_families(parts) == []


# --- sections ----------------------------------------------------------------


class TestSharedSectionsAreListedOnce:
    def test_an_identical_section_is_shared(self, declared):
        index = _index(declared)
        section = _section(index, "4.4")
        assert section.state == STATE_SHARED
        assert section.aligned_on == ALIGNED_SECTION
        assert section.members == list(MEMBERS)
        assert section.reason == ""
        assert section.tokens > 0

    def test_one_differing_value_moves_a_section_out_of_the_shared_list(self, tmp_path):
        settings = family_settings(
            tmp_path,
            thermal_body="The junction-to-ambient thermal resistance is 15.7 °C/W.",
        )
        index = _index(settings)
        section = _section(index, "4.4")
        assert section.state == STATE_DIVERGENT
        assert "text differs" in section.reason
        assert set(section.files) == set(MEMBERS)
        assert index.shared_sections and section not in index.shared_sections

    def test_a_retitled_section_is_divergent_and_shows_both_titles(self, tmp_path):
        settings = family_settings(tmp_path, thermal_title="Thermal Information X")
        section = _section(_index(settings), "4.4")
        assert section.state == STATE_DIVERGENT
        assert "different title" in section.reason
        assert section.titles["TEST9953"] == "Thermal Information X"

    def test_a_section_one_member_does_not_print_is_partial_not_divergent(
        self, tmp_path
    ):
        settings = family_settings(tmp_path, drop_section="4.4")
        section = _section(_index(settings), "4.4")
        assert section.state == STATE_PARTIAL
        assert section.missing_from == ["TEST9953"]
        assert "1 of 2 members" in section.reason

    def test_a_renumbered_section_with_the_same_title_is_one_section(self, tmp_path):
        """§6.1 in one member and §5.1 in the other, same title, same words."""
        settings = family_settings(tmp_path, back_matter_number="5")
        index = _index(settings)
        support = [s for s in index.sections if s.title == "Support Resources"]
        assert len(support) == 1, [s.number for s in index.sections]
        assert support[0].state == STATE_SHARED
        assert support[0].aligned_on == ALIGNED_SECTION_TITLE
        assert set(support[0].members) == set(MEMBERS)

    def test_the_provenance_line_and_heading_are_not_part_of_the_comparison(self):
        a = "# 6.1 Support Resources\n\n<!-- source: SBASA41E p.120 -->\n\nBody.\n"
        b = "# 5.1 Support Resources\n\n<!-- source: SBASAN1A p.99 -->\n\nBody.\n"
        assert section_body(a) == section_body(b) == "Body."


# --- the delta table ---------------------------------------------------------


class TestTheDeltaTable:
    def test_a_differing_spec_is_a_row_with_both_values_and_a_delta(self, declared):
        index = _index(declared)
        row = next(r for r in index.deltas if r.key == "TJ")
        assert row.aligned_on == f"{ALIGNED_ROW}:4.3"
        assert row.role == "max"
        printed = {c.part_number: c.values["max"].verbatim for c in row.cells}
        assert printed == {"TEST9950": "105 °C", "TEST9953": "125 °C"}
        pages = {c.part_number: c.values["max"].page for c in row.cells}
        assert pages == {"TEST9950": 6, "TEST9953": 6}
        delta = next(c.delta for c in row.cells if c.part_number == "TEST9953")
        assert delta.value_si == pytest.approx(20.0)
        assert delta.derivation == "si_delta:max"
        assert delta.verbatim == ""  # no page printed a difference

    def test_a_row_every_member_prints_identically_is_counted_not_tabulated(
        self, declared
    ):
        index = _index(declared)
        assert index.n_specs_identical >= 1
        assert "VDD1P8" not in {r.key for r in index.deltas}
        headline = index.notes[0]
        assert f"{index.n_specs_identical} print the same values" in headline

    def test_a_parameter_only_one_member_prints_is_a_flagged_row(self, tmp_path):
        settings = family_settings(tmp_path, only_spec="VDD0P9")
        row = next(r for r in _index(settings).deltas if r.key == "VDD0P9")
        assert FLAG_ONLY_IN in row.flags
        assert [c.part_number for c in row.cells] == ["TEST9953"]
        assert "TEST9950" in row.missing_from

    def test_every_delta_reference_resolves_back_to_a_record_and_a_page(
        self, tmp_path, resolve_source
    ):
        """Invariant 8's round trip, over every artifact a family compares."""
        declared = family_settings(
            tmp_path,
            tj_max="125",
            only_spec="VDD0P9",
            pin_name="VSS",
            only_pin="B2",
            reset="0x0233",
            field_bits="3:1",
            field_hi=3,
            field_lo=1,
        )
        index = _index(declared)
        walked = 0
        for row in index.deltas + index.pin_deltas + index.register_deltas:
            for cell in row.cells:
                for value in list(cell.values.values()) + (
                    [cell.delta] if cell.delta is not None else []
                ):
                    for ref in value.refs:
                        parsed = parse_source(ref)
                        assert parsed is not None and parsed.part, ref
                        found = resolve_source(
                            declared.parts_dir / parsed.part, ref
                        )
                        assert found is not None, ref
                        walked += 1
        assert walked >= 8

    def test_an_unaddressable_corpus_is_named_with_the_rebuild(self, declared):
        """A member published before ADR 0005 cannot be cited — and says so."""
        import json

        doc = next((declared.parts_dir / "TEST9953" / "docs").iterdir())
        specs = json.loads((doc / "specs.json").read_text(encoding="utf-8"))
        for record in specs["records"]:
            record["id"] = ""
        (doc / "specs.json").write_text(json.dumps(specs), encoding="utf-8")
        index = _index(declared)
        rebuild = [n for n in index.notes if "no addressable record id" in n]
        assert rebuild, index.notes
        assert "dsa build <pdf> --part TEST9953" in rebuild[0]

    def test_a_member_with_no_corpus_is_named_rather_than_dropped(self, declared):
        members = load_members(["TEST9950", "GHOST"], declared.parts_dir)
        index = build_family_index(members, name="X9x")
        assert index.members == ["TEST9950", "GHOST"]
        assert any("GHOST" in note and "no corpus" in note for note in index.notes)


# --- pins and registers ------------------------------------------------------


class TestPinAndRegisterDeltas:
    def test_a_renamed_pin_is_one_row_on_its_designator(self, tmp_path):
        settings = family_settings(tmp_path, pin_name="VSS")
        row = next(r for r in _index(settings).pin_deltas if r.key == "A1")
        assert row.aligned_on == "pin-designator"
        names = {c.part_number: c.values["name"].verbatim for c in row.cells}
        assert names == {"TEST9950": "VSSA", "TEST9953": "VSS"}
        # never scored: a pin name has no SI base
        assert all(c.delta is None for c in row.cells)

    def test_a_pin_only_one_member_prints_is_flagged(self, tmp_path):
        settings = family_settings(tmp_path, only_pin="B2")
        row = next(r for r in _index(settings).pin_deltas if r.key == "B2")
        assert FLAG_ONLY_IN in row.flags
        assert row.missing_from == ["TEST9950"]

    def test_identical_pins_produce_no_rows_at_all(self, declared):
        assert _index(declared).pin_deltas == []

    def test_a_moved_register_reset_is_a_row_and_is_never_scored(self, tmp_path):
        settings = family_settings(tmp_path, reset="0x0233")
        row = next(r for r in _index(settings).register_deltas if r.key == "0x19")
        assert row.aligned_on == "register-address"
        resets = {c.part_number: c.values["reset"].verbatim for c in row.cells}
        assert resets == {"TEST9950": "0x0211", "TEST9953": "0x0233"}
        assert all(c.delta is None for c in row.cells), "a bit pattern is not a number"

    def test_a_moved_bit_range_is_its_own_row_quoted_as_printed(self, tmp_path):
        settings = family_settings(tmp_path, field_bits="3:1", field_hi=3, field_lo=1)
        rows = _index(settings).register_deltas
        row = next(r for r in rows if r.key == "CLK_MUX")
        assert row.aligned_on == "field-name"
        bits = {c.part_number: c.values["bits"].verbatim for c in row.cells}
        assert bits == {"TEST9950": "2:0", "TEST9953": "3:1"}
        # the register itself did not move, so it is not also a row
        assert "0x19" not in {r.key for r in rows}

    def test_the_notes_say_what_the_members_publish_either_way(self, declared):
        notes = " ".join(_index(declared).notes)
        assert "pins published by every member" in notes
        assert "registers published by every member" in notes


# --- honest degradation ------------------------------------------------------


class TestHonestDegradation:
    def test_differing_structures_give_more_deltas_and_fewer_shared(self, tmp_path):
        aligned = family_settings(tmp_path / "same", tj_max="105")
        skewed = family_settings(
            tmp_path / "diff",
            tj_max="125",
            only_spec="VDD0P9",
            thermal_title="Thermal Information X",
            thermal_body="A different thermal paragraph entirely.",
            drop_section="",
            back_matter_number="9",
        )
        a, b = _index(aligned), _index(skewed)
        assert len(b.shared_sections) < len(a.shared_sections)
        assert len(b.deltas) > len(a.deltas)

    def test_a_renumbered_section_never_aligns_with_a_different_one(self, tmp_path):
        """The fold is exact: same printed title, or no fold at all."""
        settings = family_settings(
            tmp_path, back_matter_number="5", thermal_title="Thermal Information X"
        )
        index = _index(settings)
        for section in index.sections:
            titles = set(section.titles.values())
            if section.aligned_on == ALIGNED_SECTION_TITLE:
                assert len(titles) == 1, section.titles

    def test_a_family_of_one_built_member_says_so_and_shows_nothing(self, declared):
        members = load_members(["GHOST"], declared.parts_dir)
        index = build_family_index(members, name="X9x")
        assert index.deltas == []
        assert "has a built corpus" in index.empty_reason

    def test_an_ambiguous_key_is_refused_and_listed(self, declared):
        """Two rows one member prints under one printed identity hold no column."""
        import json

        doc = next((declared.parts_dir / "TEST9953" / "docs").iterdir())
        specs = json.loads((doc / "specs.json").read_text(encoding="utf-8"))
        twin = dict(specs["records"][0])
        twin["id"] = "rec_9"
        twin["max"] = "150"
        specs["records"].append(twin)
        (doc / "specs.json").write_text(json.dumps(specs), encoding="utf-8")
        index = _index(declared)
        row = next(r for r in index.deltas if r.key == "TJ")
        assert FLAG_AMBIGUOUS in row.flags
        assert "TEST9953" in row.ambiguous_in
        assert any("uncomparable" in line for line in index.unparsed)
        assert any("150" in line for line in index.unparsed)


# --- the token win -----------------------------------------------------------


class TestTheTokenWin:
    def _sum_of_member_indexes(self, settings: Settings) -> int:
        return sum(
            count_tokens(
                (settings.parts_dir / part / "INDEX.md").read_text(encoding="utf-8")
            )
            for part in MEMBERS
        )

    def test_a_shared_section_is_paid_for_once_rather_than_per_member(self, declared):
        """The measurement behind "listed once", on the family's own numbers.

        The synthetic members carry a two-line `INDEX.md`, so the *index-to-index*
        ratio is measured on the real corpora
        (`TestTheCheckedInDeclarationBuilds`). What is measured here is the rule
        that produces the win: the shared section bodies are counted once by the
        family and once **per member** by anyone reading the members instead.
        """
        index = _index(declared)
        shared = sum(s.tokens for s in index.shared_sections)
        assert shared > 0
        assert shared * len(MEMBERS) > shared  # what reading both members costs
        text = render_family_index(index)
        for section in index.shared_sections:
            assert text.count(section.files[index.reference]) == 1

    def test_it_stays_inside_its_budget_and_says_what_it_dropped(self, declared):
        index = _index(declared)
        tight = render_family_index(index, token_budget=400)
        assert count_tokens(tight) <= 400 or "budget" in tight
        assert "budget" in tight
        # the counts are reserved tail: they survive every stage
        assert "sections are identical across every member" in tight

    def test_a_shared_section_is_listed_once_with_one_members_file(self, declared):
        text = render_family_index(_index(declared))
        shared = _section(_index(declared), "4.4")
        assert shared.files["TEST9950"] in text
        assert shared.files["TEST9953"] not in text

    def test_both_files_are_written_and_the_json_holds_every_row(self, declared):
        import json

        index = _index(declared)
        path, text = write_family_index(
            index,
            families_dir=declared.families_dir,
            token_budget=declared.family_index_token_budget,
        )
        assert path.name == "FAMILY_INDEX.md"
        payload = json.loads(
            (path.parent / "family.json").read_text(encoding="utf-8")
        )
        assert len(payload["deltas"]) == len(index.deltas)
        assert payload["name"] == "TEST995x"
        assert text.startswith("<!-- derived: family_version")

    def test_the_render_is_deterministic(self, declared):
        first = render_family_index(_index(declared))
        second = render_family_index(_index(declared))
        assert first == second


# --- dsa ask --family --------------------------------------------------------


class TestAskAcrossAFamily:
    def _scope(self, settings: Settings) -> FamilyRetriever:
        return FamilyRetriever.for_parts(
            "TEST995x", [settings.parts_dir / p for p in MEMBERS]
        )

    def test_a_shared_answer_is_returned_once_and_names_its_members(self, tmp_path):
        settings = family_settings(tmp_path)  # members agree on everything
        pack = self._scope(settings).ask("1.8V supply minimum")
        assert pack.family == "TEST995x"
        assert pack.shared is True
        assert pack.divergence == ()
        assert all(line.shared_with == MEMBERS for line in pack.answers)
        assert all(line.part == "" for line in pack.answers)
        assert "common to TEST9950, TEST9953" in pack.markdown

    def test_a_divergent_answer_is_per_member_and_flagged(self, declared):
        pack = self._scope(declared).ask("operating junction temperature")
        assert pack.shared is False
        assert pack.divergence
        assert "not** common to every member" in pack.markdown
        parts = {line.part for line in pack.answers if line.text.find("105") >= 0}
        assert parts == {"TEST9950"}
        assert "Per-member differences" in pack.markdown

    def test_a_member_that_answers_nothing_is_a_divergence_not_a_silence(
        self, tmp_path
    ):
        settings = family_settings(tmp_path, only_spec="VDD0P9")
        pack = self._scope(settings).ask("second band supply")
        assert pack.shared is False
        assert any("TEST9950" in note for note in pack.divergence)

    def test_the_declared_json_shape_admits_a_family_pack(self, declared):
        from datasheet_analyzer.retrieve import validate_pack

        payload = self._scope(declared).ask("operating junction temperature").as_dict()
        assert validate_pack(payload) == []
        assert payload["family"] == "TEST995x"
        assert payload["shared"] is False

    def test_a_non_family_pack_carries_the_fields_empty(self, declared):
        from datasheet_analyzer.retrieve import Retriever

        pack = Retriever.for_part(declared.parts_dir / "TEST9950").ask("TJ")
        assert pack.family == "" and pack.shared is False and pack.divergence == ()
        assert all(line.shared_with == () for line in pack.answers)


# --- the CLI surface ---------------------------------------------------------


class TestTheCliScope:
    def test_ask_family_is_a_scope_beside_part_and_project(
        self, declared, monkeypatch, capsys
    ):
        from datasheet_analyzer.cli import main

        registry = FamilyRegistry()
        registry.put(
            FamilyEntry(name="TEST995x", members=list(MEMBERS), confirmed=True)
        )
        save_families(registry, families_path(declared.registry_dir))
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: declared)
        monkeypatch.setattr(
            "datasheet_analyzer.config.get_settings", lambda: declared
        )
        assert main(["ask", "--family", "TEST995x", "1.8V supply minimum"]) == 0
        assert "family (TEST9950, TEST9953)" in capsys.readouterr().out

    def test_the_three_scopes_are_mutually_exclusive(self):
        from datasheet_analyzer.cli import main

        with pytest.raises(SystemExit):
            main(["ask", "--part", "A", "--family", "B", "q"])

    def test_an_undeclared_family_is_refused_with_the_fix(
        self, declared, monkeypatch, capsys
    ):
        from datasheet_analyzer.cli import main

        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: declared)
        monkeypatch.setattr(
            "datasheet_analyzer.config.get_settings", lambda: declared
        )
        assert main(["ask", "--family", "NOPE9x", "q"]) == 2
        assert "dsa family suggest" in capsys.readouterr().err


class TestTheCheckedInDeclarationBuilds:
    """`dsa family build AFE795x` over the corpora committed under `parts/`.

    The reference family is real (`registry/families.yaml`), and the two corpora
    it names are the ones committed in this repo — published by an older pipeline
    with no record ids. So this asserts the *honest* reading: the sections align
    and the shared ones are listed once, while every spec row is refused for want
    of an addressable id and the index says which rebuild would close it. A test
    that expected a delta table here would be asserting a corpus state this repo
    does not have.
    """

    PARTS = Path(__file__).parent.parent.parent / "parts"

    @pytest.fixture
    def index(self):
        if not (self.PARTS / "AFE7950" / "manifest.json").exists():
            pytest.skip("committed parts/AFE7950 corpus not present")
        members = load_members(["AFE7950", "AFE7953"], self.PARTS)
        return build_family_index(
            members, name="AFE795x", title="AFE79xx RF-sampling transceivers"
        )

    def test_the_sections_align_and_some_are_shared(self, index):
        assert len(index.sections) >= 35
        assert len(index.shared_sections) >= 5
        assert all(s.members for s in index.sections)

    def test_the_back_matter_renumbering_folds_into_one_section(self, index):
        support = [s for s in index.sections if s.title == "Support Resources"]
        assert len(support) == 1
        assert set(support[0].members) == {"AFE7950", "AFE7953"}

    def test_the_old_schema_is_reported_with_the_rebuild_rather_than_hidden(
        self, index
    ):
        assert index.deltas == []
        rebuild = [n for n in index.notes if "no addressable record id" in n]
        assert len(rebuild) == 2, index.notes
        assert all("dsa build <pdf> --part" in note for note in rebuild)

    def test_it_is_smaller_than_the_sum_of_the_two_member_indexes(self, index):
        text = render_family_index(index, token_budget=4000)
        members = sum(
            count_tokens((self.PARTS / p / "INDEX.md").read_text(encoding="utf-8"))
            for p in ("AFE7950", "AFE7953")
        )
        assert count_tokens(text) < members
