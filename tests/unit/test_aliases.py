"""The alias lexicon and the spec resolution ladder (Phase 5, ticket 02).

What these prove:

- the lexicon is **data**: a synonym added to a YAML file changes resolution
  with no code change at all;
- the ladder resolves designers' words to a datasheet's symbols, first hit
  wins, and every hit names the rung that found it (`matched_via`);
- `expect_unit` breaks ties *by ranking* and never suppresses a record whose
  unit is missing — the tidier behaviour would be the dishonest one;
- prefix families expand (`IDD` -> every `IVDD*` supply-current record);
- a query that matches nothing says so and offers the nearest candidates,
  instead of guessing;
- the CLI shows the rung, in text and in `--json`;
- coverage is measured, not claimed: the checked-in symbol inventory
  (`tests/fixtures/alias_seed_symbols.json`, produced by the checked-in
  `scripts/seed_aliases.py`) rebuilds all six corpora's spec vocabulary, and
  the alias hit rate over their golden questions is measured and printed.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.evalh.citations import load_golden_yaml
from datasheet_analyzer.models import (
    CorpusManifest,
    SectionFile,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.retrieve import Retriever
from datasheet_analyzer.structure.aliases import AliasLexicon, load_lexicon

FIXTURES = Path(__file__).parent.parent / "fixtures"
INVENTORY = FIXTURES / "alias_seed_symbols.json"
SEED_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "seed_aliases.py"
DOC = "datasheet-a1b2c3d4"
DOC_HASH = "a1b2c3d4" + "0" * 56

# The six built corpora the lexicon is seeded from.
SEED_PARTS = ("AFE7950", "AFE7953", "AD9081", "LM741", "QPA1003P", "HMC520A")


def _write_part(part_dir: Path, rows: list[dict]) -> Path:
    """A corpus whose specs.json holds exactly `rows` (symbol/name/unit/page)."""
    doc_dir = part_dir / "docs" / DOC
    doc_dir.mkdir(parents=True, exist_ok=True)
    records = [
        SpecRecord(
            section=row.get("section", ""),
            table_index=0,
            row_index=i,
            symbol=row.get("symbol", ""),
            name=row.get("name", ""),
            min=row.get("min", ""),
            typ=row.get("typ", ""),
            max=row.get("max", ""),
            value=row.get("value", ""),
            unit=SpecUnit(
                verbatim=row.get("unit", ""),
                canonical=row.get("unit_canonical", row.get("unit", "")),
            ),
            page=row.get("page"),
        )
        for i, row in enumerate(rows)
    ]
    (doc_dir / "specs.json").write_text(
        SpecSet(
            schema_version="1",
            part_number=part_dir.name,
            doc_hash=DOC_HASH,
            records=records,
        ).model_dump_json(),
        encoding="utf-8",
    )
    (part_dir / "manifest.json").write_text(
        CorpusManifest(
            part_number=part_dir.name,
            pipeline_version="0.4.0",
            sections=[
                SectionFile(
                    number="4.1",
                    title="Absolute Maximum Ratings",
                    file=f"docs/{DOC}/sections/4-1.md",
                    doc_hash=DOC_HASH,
                    page_start=1,
                    page_end=99,
                )
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    return part_dir


@pytest.fixture(scope="module")
def inventory() -> dict[str, list[dict]]:
    """The checked-in spec vocabulary of the six built corpora."""
    assert INVENTORY.exists(), (
        f"{INVENTORY} missing — regenerate with scripts/seed_aliases.py "
        "(procedure in its docstring)"
    )
    data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    return data["parts"]


@pytest.fixture
def seeded_corpora(tmp_path: Path, inventory) -> dict[str, Path]:
    """Six corpora rebuilt from the recorded vocabulary — real symbols, real
    names, real units, real pages, hermetic and instant."""
    return {
        part: _write_part(tmp_path / part, rows) for part, rows in inventory.items()
    }


@pytest.fixture
def afe7950(seeded_corpora) -> Retriever:
    return Retriever.for_part(seeded_corpora["AFE7950"])


class TestLexiconIsData:
    def test_shipped_lexicon_loads_with_entries(self):
        lex = load_lexicon()
        assert len(lex.entries) >= 40
        tj = lex.by_symbol("tj")  # case-insensitive
        assert tj is not None
        assert "junction temperature" in tj.names
        assert tj.expect_unit == "°C"

    def test_prefix_family_declares_its_members(self):
        idd = load_lexicon().by_symbol("IDD")
        assert idd is not None and idd.prefix_match
        assert "IVDD" in idd.match_prefixes

    def test_a_synonym_is_a_yaml_edit_not_a_code_change(self, tmp_path, monkeypatch):
        """The whole point of the lexicon: extend coverage without Python."""
        part = _write_part(
            tmp_path / "P",
            [{"symbol": "TJ", "name": "Junction temperature", "unit": "°C", "page": 4}],
        )
        assert Retriever.for_part(part).specs(name="how hot can the die get") == []

        lexfile = tmp_path / "aliases.yaml"
        lexfile.write_text(
            "TJ:\n  names: [how hot can the die get]\n  expect_unit: \"°C\"\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "datasheet_analyzer.retrieve.retriever.load_lexicon",
            lambda: AliasLexicon.read(lexfile),
        )
        hits = Retriever.for_part(part).specs(name="how hot can the die get")
        assert [h.record.symbol for h in hits] == ["TJ"]
        assert hits[0].matched_via == "alias:how hot can the die get"

    def test_malformed_entry_is_skipped_not_fatal(self, caplog):
        with caplog.at_level(logging.WARNING):
            lex = AliasLexicon.from_mapping({"TJ": {"names": ["junction temperature"]}, "X": 3})
        assert lex.symbols == ("TJ",)
        assert "skipping malformed alias entry" in caplog.text

    def test_missing_lexicon_file_degrades_to_symbol_lookups(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            lex = AliasLexicon.read(tmp_path / "nope.yaml")
        assert lex.entries == ()
        assert "alias lexicon unavailable" in caplog.text


class TestResolutionLadder:
    def test_designer_words_resolve_to_the_symbol_answer(self, afe7950):
        """Ticket criterion: `--name "junction temperature"` gives what
        `--symbol TJ` gives — same verbatim value, same page."""
        by_name = afe7950.specs(name="junction temperature")
        by_symbol = afe7950.specs(symbol="TJ")
        assert by_name and by_symbol
        assert [h.record.symbol for h in by_name] == [h.record.symbol for h in by_symbol]
        first_name, first_symbol = by_name[0].record, by_symbol[0].record
        assert first_name.max == first_symbol.max == "150"
        assert first_name.page == first_symbol.page == 4
        assert first_name.unit.verbatim == first_symbol.unit.verbatim

    def test_a_whole_question_still_resolves(self, afe7950):
        hits = afe7950.specs(name="What is the max junction temperature?")
        assert hits and hits[0].record.symbol == "TJ"
        assert hits[0].matched_via == "alias:max junction temperature"

    def test_every_rung_names_itself(self, afe7950):
        assert afe7950.specs(symbol="DACRES")[0].matched_via == "symbol"
        assert afe7950.specs(name="dac resolution")[0].matched_via == "alias:dac resolution"
        assert afe7950.specs(symbol="IDD")[0].matched_via == "alias-prefix:IDD"
        assert afe7950.specs(symbol="ACRE")[0].matched_via == "symbol-substring"
        assert afe7950.specs(name="junction")[0].matched_via == "name-substring"

    def test_first_hit_wins_the_ladder_never_falls_through(self, tmp_path):
        """An exact symbol outranks an alias phrase that would also match."""
        part = _write_part(
            tmp_path / "P",
            [
                {"symbol": "TJ", "name": "Junction temperature", "unit": "°C", "page": 4},
                {"symbol": "OTHER", "name": "junction temperature note", "page": 9},
            ],
        )
        hits = Retriever.for_part(part).specs(symbol="TJ")
        assert [h.record.symbol for h in hits] == ["TJ"]
        assert hits[0].matched_via == "symbol"

    def test_layout_floor_parts_resolve_through_the_same_entry(self, seeded_corpora):
        """LM741 prints `Junction temperature` as the *symbol* (it has no
        symbol column at all), AFE7950 prints `TJ`. One YAML entry must reach
        both, or the lexicon is a TI-only feature."""
        term = "maximum junction temperature"
        lm741 = Retriever.for_part(seeded_corpora["LM741"]).specs(name=term)
        assert lm741, "alias phrase must match a record's own symbol text too"
        assert lm741[0].matched_via == f"alias:{term}"
        assert "junction temperature" in lm741[0].record.symbol.lower()

        afe = Retriever.for_part(seeded_corpora["AFE7950"]).specs(name=term)
        assert afe and afe[0].record.symbol == "TJ"

    def test_fuzzy_needs_more_than_one_token(self, tmp_path):
        part = _write_part(
            tmp_path / "P",
            [{"symbol": "XYZ", "name": "Wibble frobnicator rating", "page": 3}],
        )
        r = Retriever.for_part(part)
        assert r.specs(name="frobnicator wibble rating")[0].matched_via == "fuzzy"
        # a single unrelated token must never fuzz its way to an answer
        assert r.specs(name="capacitance") == []


class TestExpectUnitDisambiguates:
    """`expect_unit` ranks, it never filters — asserted both ways."""

    @pytest.fixture
    def part(self, tmp_path) -> Path:
        return _write_part(
            tmp_path / "P",
            [
                # deliberately first in document order, and deliberately not °C
                {"symbol": "TJ", "name": "Total Jitter Tolerance", "unit": "UI",
                 "max": "0.42", "page": 20},
                # no unit at all: the record a filter would quietly drop
                {"symbol": "TJ", "name": "Junction temperature (unitless print)",
                 "max": "150", "page": 4},
                {"symbol": "TJ", "name": "Operating junction temperature",
                 "unit": "°C", "max": "105", "page": 6},
            ],
        )

    def test_expected_unit_wins_the_tie(self, part):
        hits = Retriever.for_part(part).specs(name="junction temperature")
        assert hits[0].record.unit.canonical == "°C"
        assert hits[0].record.max == "105"

    def test_a_record_with_no_unit_is_never_suppressed(self, part):
        hits = Retriever.for_part(part).specs(name="junction temperature")
        unitless = [h for h in hits if not h.record.unit.canonical]
        assert unitless, "expect_unit must rank, not filter"
        assert unitless[0].record.max == "150"

    def test_a_record_with_a_different_unit_is_never_suppressed(self, part):
        hits = Retriever.for_part(part).specs(name="junction temperature")
        assert "UI" in {h.record.unit.canonical for h in hits}

    def test_symbol_and_alias_paths_rank_identically(self, part):
        r = Retriever.for_part(part)
        assert [h.record.name for h in r.specs(symbol="TJ")] == [
            h.record.name for h in r.specs(name="junction temperature")
        ]


class TestPrefixFamilies:
    def test_idd_returns_every_ivdd_supply_current_record(self, afe7950):
        hits = afe7950.specs(symbol="IDD")
        symbols = {h.record.symbol for h in hits}
        assert symbols == {"IVDD0P9", "IVDD1P2", "IVDD1P8"}
        assert all(h.matched_via == "alias-prefix:IDD" for h in hits)

    def test_the_family_is_reachable_by_its_words_too(self, afe7950):
        hits = afe7950.specs(name="supply current")
        assert {h.record.symbol for h in hits} == {"IVDD0P9", "IVDD1P2", "IVDD1P8"}
        assert all(h.matched_via == "alias:supply current" for h in hits)

    def test_a_family_prefix_does_not_swallow_unrelated_symbols(self, afe7950):
        symbols = {h.record.symbol for h in afe7950.specs(symbol="IDD")}
        assert "IIH" not in symbols and "IIL" not in symbols


class TestNoMatchIsExplicit:
    def test_nothing_matched_returns_nothing_plus_candidates(self, afe7950):
        assert afe7950.specs(name="thermal noise floor of the widget") == []
        suggestions = afe7950.suggest_specs("junction temp")
        assert suggestions
        assert any("junction" in s.lower() for s in suggestions)

    def test_suggestions_are_deterministic(self, afe7950):
        assert afe7950.suggest_specs("dac res") == afe7950.suggest_specs("dac res")

    def test_no_term_gets_no_suggestions(self, afe7950):
        assert afe7950.suggest_specs("   ") == []


class TestCliReportsTheRung:
    @pytest.fixture
    def settings(self, seeded_corpora, monkeypatch):
        from datasheet_analyzer.config import Settings

        parts_dir = seeded_corpora["AFE7950"].parent
        resolved = Settings(parts_dir=parts_dir, cache_dir=parts_dir / ".cache").resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: resolved)
        return resolved

    def test_text_output_names_the_rung(self, settings, capsys):
        assert cli.main(["query", "--part", "AFE7950", "--name", "junction temperature"]) == 0
        out = capsys.readouterr().out
        assert "via alias:junction temperature" in out
        assert "p.4" in out

    def test_json_output_carries_matched_via_and_citation(self, settings, capsys):
        code = cli.main(
            ["query", "--part", "AFE7950", "--name", "junction temperature", "--json"]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["part"] == "AFE7950"
        first = payload["hits"][0]
        assert first["symbol"] == "TJ"
        assert first["matched_via"] == "alias:junction temperature"
        assert first["page"] == 4
        assert first["citation"].endswith("p.4")
        assert first["confidence"] == "unknown"  # ticket 04 grades it
        assert payload["suggestions"] == []

    def test_no_match_exits_nonzero_with_candidates(self, settings, capsys):
        code = cli.main(["query", "--part", "AFE7950", "--name", "flux capacitor rating"])
        assert code == 1
        out = capsys.readouterr().out
        assert "No spec record matches 'flux capacitor rating'." in out
        assert "Nearest candidates:" in out

    def test_no_match_json_carries_candidates(self, settings, capsys):
        code = cli.main(
            ["query", "--part", "AFE7950", "--name", "flux capacitor rating", "--json"]
        )
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["hits"] == []
        assert payload["suggestions"], "a no-match must still offer nearer terms"


def _seed_module():
    """Import the checked-in seeding script without spawning a process."""
    spec = importlib.util.spec_from_file_location("seed_aliases", SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestSeedingIsReproducible:
    def test_the_seeding_script_is_checked_in_and_importable(self):
        module = _seed_module()
        assert hasattr(module, "harvest") and hasattr(module, "coverage")

    def test_inventory_covers_the_six_built_corpora(self, inventory):
        assert set(inventory) == set(SEED_PARTS)
        for part, rows in inventory.items():
            assert rows, f"{part}: empty inventory"
            assert all("symbol" in r and "unit_canonical" in r for r in rows)

    def test_harvest_reproduces_the_recorded_inventory(self, seeded_corpora, inventory):
        """The rebuilt corpus harvests back to what was recorded — the fixture
        and the script agree, so the seed is reproducible rather than a
        hand-edited artifact."""
        module = _seed_module()
        for part, part_dir in seeded_corpora.items():
            harvested = module.harvest(part_dir)
            recorded = sorted(
                (r["symbol"], r["name"], r["unit_canonical"]) for r in inventory[part]
            )
            assert (
                sorted((r["symbol"], r["name"], r["unit_canonical"]) for r in harvested)
                == recorded
            ), part

    def test_alias_hit_rate_over_the_goldens_is_measured(self, seeded_corpora, capsys):
        """Coverage is a number, not a claim — printed for the phase report.

        An "alias hit" is a golden question, asked in the designer's own words
        with no symbol, that the lexicon resolves to at least one spec record.
        Text-only questions (features, package, prose) have no spec answer at
        all, so 100% is not the target and never will be — a regression in the
        lexicon or the ladder is what this floor catches.
        """
        module = _seed_module()
        lexicon = load_lexicon()
        rows: list[str] = []
        total = hits = 0
        for part in SEED_PARTS:
            golden = FIXTURES / f"golden_qa_{part}.yaml"
            questions = load_golden_yaml(golden) if golden.exists() else []
            retriever = Retriever.for_part(seeded_corpora[part])
            resolved = sum(
                1
                for q in questions
                if any(
                    h.matched_via.startswith("alias")
                    for h in retriever.specs(name=q.question)
                )
            )
            covered, n_rows, _ = module.coverage(lexicon, module.harvest(seeded_corpora[part]))
            total += len(questions)
            hits += resolved
            pct = resolved / len(questions) if questions else 0.0
            rows.append(
                f"  {part:<9} golden {resolved:>2}/{len(questions):<2} ({pct:>4.0%})"
                f"   vocabulary {covered:>3}/{n_rows:<3}"
                + ("   (no benchmark)" if not questions else "")
            )
        rate = hits / total if total else 0.0
        report = "\n".join(
            ["", f"alias lexicon: {len(lexicon.entries)} entries over 6 built corpora", *rows,
             f"  {'TOTAL':<9} golden {hits:>2}/{total:<2} ({rate:.0%}) resolved via alias", ""]
        )
        with capsys.disabled():
            print(report)

        assert total >= 60, "the six corpora's goldens should be the whole benchmark"
        assert rate >= 0.45, f"alias hit rate regressed to {rate:.0%}\n{report}"
        assert hits > 0
