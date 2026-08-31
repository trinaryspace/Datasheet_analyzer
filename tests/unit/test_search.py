"""Full-text search with citations attached (Phase 5, ticket 03).

What these prove:

- `search_index.json` is written at publish for **every** document, carries a
  `schema_version`, and participates in the publish cache key — a corpus
  without a current one rebuilds instead of answering nothing;
- rebuilds are byte-identical for identical input, so the index is a
  deterministic artifact and not a per-machine one;
- BM25 (k1=1.2, b=0.75) ranks, and ties break on the corpus path so two
  identical corpora rank identically;
- every hit carries doc, section, page range, score and a ±240-char snippet
  grown to sentence boundaries — cited **by construction**, from the
  manifest, never assembled by a front end;
- the datasheet's own vocabulary survives the tokenizer: `SYSREF`, `dBc/Hz`,
  `RθJA`, and **both** ohm glyphs, asserted per glyph (Unicode lowercasing
  would merge U+2126 and U+03A9 — ASCII-only folding is what keeps them
  apart);
- a corpus with no index says "rebuild to enable search" instead of crashing
  or, worse, returning an empty result that reads like "not in the datasheet".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.config import PIPELINE_VERSION, SEARCH_SCHEMA_VERSION, Settings
from datasheet_analyzer.models import (
    DocType,
    RawDocument,
    SearchIndex,
    SearchSection,
    SectionNode,
    SourceDocument,
)
from datasheet_analyzer.publish import search_index_current, write_corpus
from datasheet_analyzer.publish.search_index import INDEX_FILENAME, build_search_index, dump_json
from datasheet_analyzer.retrieve import CorpusIndex, Retriever, score_sections
from datasheet_analyzer.retrieve import search as search_mod
from datasheet_analyzer.retrieve.search import SNIPPET_RADIUS, SNIPPET_SLACK, snippet
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.structure.search import STOPWORDS, body_text, tokenize

DOC_HASH = "a1b2c3d4" + "0" * 56
DOC = f"datasheet-{DOC_HASH[:8]}"

# The two ohm glyphs this corpus preserves verbatim: TI prints U+2126 OHM
# SIGN, ADI prints U+03A9 GREEK CAPITAL LETTER OMEGA. `str.lower()` folds
# both onto U+03C9; the search tokenizer must not.
OHM_TI = "Ω"
OHM_ADI = "Ω"
THETA = "θ"


def _section(number: str, title: str, pages: tuple[int, int], paragraphs: list[str]):
    return SectionNode(
        number=number,
        title=title,
        page_start=pages[0],
        page_end=pages[1],
        paragraphs=paragraphs,
    )


def _sections() -> list[SectionNode]:
    """Three sections whose vocabulary is deliberately non-overlapping."""
    return [
        _section(
            "1",
            "Features",
            (1, 1),
            ["Quad RF sampling transmit DACs with an integrated digital up converter."],
        ),
        _section(
            "4.3",
            "Recommended Operating Conditions",
            (6, 6),
            [
                (
                    "Operating junction temperature TJ ranges from -40 to 105 °C. "
                    f"Termination resistance is 50 {OHM_ADI} single ended."
                ),
                (
                    f"The junction-to-ambient thermal resistance R{THETA}JA is 21.5 °C/W. "
                    "Supply voltage VDD1P2 is nominally 1.2 V."
                ),
            ],
        ),
        _section(
            "4.5",
            "Transmitter Electrical Characteristics",
            (7, 8),
            [
                (
                    "SYSREF setup time must be met for deterministic latency. "
                    "The SYSREF capture window is programmable per converter."
                ),
                (
                    "Phase noise is specified in dBc/Hz at 100 kHz offset. "
                    f"Differential output impedance is 100 {OHM_TI} balanced."
                ),
            ],
        ),
    ]


def _build_part(part_dir: Path, sections: list[SectionNode] | None = None) -> Path:
    """Publish a real corpus through `write_corpus` — index included."""
    source = SourceDocument(
        content_hash=DOC_HASH,
        path="datasheet.pdf",
        part_number=part_dir.name,
        doc_type=DocType.DATASHEET,
        revision="REV1",
        page_count=40,
    )
    raw = RawDocument(
        source=source,
        sections=sections if sections is not None else _sections(),
        extractor="pdf_layout",
        extractor_version="test-1",
    )
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        "# INDEX\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
    )
    return part_dir


@pytest.fixture
def part(tmp_path: Path) -> Path:
    return _build_part(tmp_path / "parts" / "TEST")


@pytest.fixture
def retriever(part) -> Retriever:
    return Retriever.for_part(part)


def _index_path(part_dir: Path) -> Path:
    return part_dir / "docs" / DOC / INDEX_FILENAME


class TestTokenizerKeepsTheDatasheetsVocabulary:
    def test_symbols_survive_intact_and_unstemmed(self):
        toks = tokenize("SYSREF setup ratings for the DACs")
        assert "sysref" in toks
        # no stemming: `ratings` and `dacs` must not be clipped to their stems
        assert "ratings" in toks and "dacs" in toks
        assert "rating" not in toks and "dac" not in toks

    def test_compound_unit_string_indexes_whole_and_split(self):
        toks = tokenize("Phase noise in dBc/Hz")
        assert "dbc/hz" in toks, "the printed unit string must be searchable verbatim"
        assert "dbc" in toks and "hz" in toks, "and by either half"

    @pytest.mark.parametrize("glyph", [OHM_TI, OHM_ADI])
    def test_each_ohm_glyph_is_its_own_token(self, glyph):
        assert tokenize(f"100 {glyph} balanced") == [glyph, "balanced"]

    def test_numerals_are_not_indexed(self):
        """Values have an exact path (`dsa query`); BM25 over them ranks nothing.

        Dropping them is most of why the index stays smaller than the text it
        indexes — see `_indexable`. A number glued to a word survives, so
        `12GSPS` and `VDD1P2` are still findable.
        """
        assert tokenize("Maximum 105 -40 1.2 4-1") == ["maximum"]
        assert tokenize("12GSPS VDD1P2") == ["12gsps", "vdd1p2"]

    def test_the_two_ohm_glyphs_never_collapse_onto_each_other(self):
        """`str.lower()` maps both onto U+03C9; ASCII-only folding does not."""
        assert OHM_TI.lower() == OHM_ADI.lower()  # the trap this avoids
        assert tokenize(OHM_TI) != tokenize(OHM_ADI)

    def test_greek_and_micro_glyphs_survive(self):
        assert tokenize(f"R{THETA}JA thermal resistance")[0] == f"r{THETA}ja"
        assert "µa" in tokenize("Input bias current 80 µA")

    def test_degree_celsius_stays_glued_to_its_degree_sign(self):
        assert "°c" in tokenize("105 °C maximum")

    def test_stopwords_never_eat_a_unit(self):
        """`a` (amperes) and `in` (inches) are units; no stopword may be one."""
        assert not any(len(w) == 1 for w in STOPWORDS)
        assert "a" not in STOPWORDS and "in" not in STOPWORDS
        assert "the" in STOPWORDS and "the" not in tokenize("the supply voltage")

    def test_provenance_comment_is_not_indexed(self):
        md = "# 4.5 DAC\n\n<!-- source: SBASA41E p.7-8 -->\n\nDAC resolution is 14 bits.\n"
        assert "sbasa41e" not in tokenize(body_text(md))
        assert "resolution" in tokenize(body_text(md))


class TestIndexIsWrittenAtPublish:
    def test_every_document_gets_a_versioned_index(self, part):
        data = json.loads(_index_path(part).read_text(encoding="utf-8"))
        assert data["schema_version"] == SEARCH_SCHEMA_VERSION
        assert data["doc_hash"] == DOC_HASH
        assert data["part_number"] == "TEST"
        assert len(data["sections"]) == 3
        assert data["avgdl"] > 0
        assert data["df"]["sysref"] == 1

    def test_index_covers_exactly_the_published_section_files(self, part):
        data = json.loads(_index_path(part).read_text(encoding="utf-8"))
        for entry in data["sections"]:
            assert (part / "docs" / DOC / entry["file"]).exists()
            assert entry["length"] > 0

    def test_manifest_records_per_section_token_counts_and_index_size(self, part):
        """Index economics are a recorded number in every manifest.

        The *ratio* is only meaningful on a real corpus (a three-paragraph
        fixture is all fixed overhead), so it is asserted on the four gate
        parts in `tests/integration/test_phase4_layout_gate.py`.
        """
        manifest = CorpusIndex.load(part).manifest
        assert all(s.search_tokens > 0 for s in manifest.sections)
        assert manifest.stats.search_index_bytes > 0
        assert manifest.stats.section_bytes > 0
        assert manifest.stats.search_index_bytes == _index_path(part).stat().st_size

    def test_rebuilds_are_byte_identical(self, tmp_path):
        """Determinism: no dict order, no filesystem order, no clock."""
        a = _build_part(tmp_path / "a" / "TEST")
        b = _build_part(tmp_path / "b" / "TEST")
        assert _index_path(a).read_bytes() == _index_path(b).read_bytes()

    def test_serialization_is_order_independent(self):
        """The same counts, inserted in opposite order, serialize identically."""
        forward = SearchIndex(
            schema_version=SEARCH_SCHEMA_VERSION,
            sections=[SearchSection(file="sections/a.md", length=2, tokens={"b": 1, "a": 1})],
            df={"b": 1, "a": 1},
        )
        backward = SearchIndex(
            schema_version=SEARCH_SCHEMA_VERSION,
            sections=[SearchSection(file="sections/a.md", length=2, tokens={"a": 1, "b": 1})],
            df={"a": 1, "b": 1},
        )
        assert dump_json(forward) == dump_json(backward)

    def test_empty_document_still_gets_an_index(self):
        index = build_search_index([], part_number="TEST", doc_hash=DOC_HASH)
        assert index.schema_version == SEARCH_SCHEMA_VERSION
        assert index.sections == [] and index.avgdl == 0.0


class TestPublishCacheKey:
    def test_a_current_index_is_what_makes_a_corpus_current(self, part):
        doc_dir = part / "docs" / DOC
        assert search_index_current(doc_dir)

        (doc_dir / INDEX_FILENAME).unlink()
        assert not search_index_current(doc_dir), "a missing index is not current"

    def test_an_older_schema_reads_as_not_current(self, part):
        doc_dir = part / "docs" / DOC
        data = json.loads((doc_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        data["schema_version"] = "0"
        (doc_dir / INDEX_FILENAME).write_text(json.dumps(data), encoding="utf-8")
        assert not search_index_current(doc_dir)

    def test_corrupt_index_reads_as_not_current(self, part):
        doc_dir = part / "docs" / DOC
        (doc_dir / INDEX_FILENAME).write_text("{ not json", encoding="utf-8")
        assert not search_index_current(doc_dir)


class TestBm25Ranking:
    def test_constants_are_the_plans_constants(self):
        assert (search_mod.K1, search_mod.B) == (1.2, 0.75)

    def test_top_hit_is_the_section_that_uses_the_term(self, retriever):
        hits = retriever.search("sysref setup")
        assert hits, "sysref must be findable"
        assert hits[0].section.number == "4.5"

    def test_a_term_in_no_section_returns_nothing(self, retriever):
        assert retriever.search("flux capacitor") == []

    def test_a_stopword_only_query_returns_nothing(self, retriever):
        assert retriever.search("the and of") == []

    def test_limit_caps_the_result_set(self, retriever):
        assert len(retriever.search("temperature voltage sysref", limit=1)) == 1

    def test_ties_break_on_the_corpus_path_not_on_input_order(self):
        """Two sections that score identically must always rank identically."""
        index = SearchIndex(
            schema_version=SEARCH_SCHEMA_VERSION,
            sections=[
                SearchSection(file="sections/b.md", length=4, tokens={"sysref": 1}),
                SearchSection(file="sections/a.md", length=4, tokens={"sysref": 1}),
            ],
            df={"sysref": 2},
            avgdl=4.0,
        )
        scored = score_sections([("datasheet-1", index)], "sysref")
        assert [s.file for s in scored] == ["sections/a.md", "sections/b.md"]
        assert scored[0].score == scored[1].score

    def test_ties_across_documents_break_on_the_document_name(self):
        section = SearchSection(file="sections/a.md", length=4, tokens={"sysref": 1})
        index = SearchIndex(
            schema_version=SEARCH_SCHEMA_VERSION,
            sections=[section],
            df={"sysref": 1},
            avgdl=4.0,
        )
        scored = score_sections([("errata-2", index), ("datasheet-1", index)], "sysref")
        assert [s.doc for s in scored] == ["datasheet-1", "errata-2"]

    def test_repeated_searches_are_stable(self, retriever):
        first = [(h.section.file, h.score) for h in retriever.search("temperature")]
        second = [(h.section.file, h.score) for h in retriever.search("temperature")]
        assert first == second

    def test_a_rarer_term_outranks_a_common_one(self, retriever):
        """IDF at work: the section holding both query terms must lead."""
        hits = retriever.search("sysref temperature")
        assert hits[0].section.number == "4.5"
        assert {h.section.number for h in hits} == {"4.5", "4.3"}


class TestGlyphsAreSearchableEndToEnd:
    @pytest.mark.parametrize(("glyph", "expected"), [(OHM_TI, "4.5"), (OHM_ADI, "4.3")])
    def test_each_ohm_glyph_finds_only_the_section_that_prints_it(self, retriever, glyph, expected):
        hits = retriever.search(glyph)
        assert [h.section.number for h in hits] == [expected]

    def test_unit_string_is_searchable_verbatim(self, retriever):
        assert retriever.search("dBc/Hz")[0].section.number == "4.5"

    def test_greek_symbol_is_searchable_verbatim(self, retriever):
        assert retriever.search(f"R{THETA}JA")[0].section.number == "4.3"


class TestHitsAreCitedByConstruction:
    def test_hit_carries_doc_section_pages_score_and_snippet(self, retriever):
        hit = retriever.search("sysref setup")[0]
        assert hit.citation.doc == DOC
        assert hit.citation.doc_hash == DOC_HASH
        assert hit.citation.section == "4.5"
        assert (hit.citation.page_start, hit.citation.page_end) == (7, 8)
        assert hit.citation.label == "§4.5, p.7-8"
        assert hit.score > 0
        assert "SYSREF setup time" in hit.snippet
        assert hit.matched_via == "fulltext"
        assert hit.confidence == "unknown"  # ticket 04 grades it

    def test_heading_is_a_field_not_a_prefix_on_the_snippet(self, retriever):
        hit = retriever.search("sysref setup")[0]
        assert hit.heading == "§4.5 Transmitter Electrical Characteristics"
        assert not hit.snippet.startswith("#")

    def test_page_range_comes_from_the_manifest_not_the_snippet(self, retriever):
        hit = retriever.search("junction temperature")[0]
        section = next(
            s for s in CorpusIndex.load(retriever.part_dir).sections if s.number == "4.3"
        )
        assert (hit.citation.page_start, hit.citation.page_end) == (
            section.page_start,
            section.page_end,
        )

    def test_json_shape_is_owned_by_the_hit(self, retriever):
        payload = retriever.search("sysref setup")[0].as_dict()
        assert payload["section"] == "4.5"
        assert payload["citation"] == "§4.5, p.7-8"
        assert payload["doc"] == DOC
        assert payload["page_start"] == 7 and payload["page_end"] == 8
        assert payload["score"] > 0 and payload["snippet"]
        assert payload["matched_via"] == "fulltext"


class TestSnippets:
    def _long_body(self) -> str:
        filler = "Padding sentence about supply rails and layout guidance. " * 12
        return (
            "# 9 Long Section\n\n<!-- source: REV1 p.20 -->\n\n"
            f"Opening sentence. {filler}"
            "The SYSREF capture window is programmable per converter. "
            f"{filler}Closing sentence."
        )

    def test_snippet_stays_within_the_radius_plus_its_slack(self):
        text = self._long_body()
        out = snippet(text, ("sysref",))
        assert len(out) <= 2 * (SNIPPET_RADIUS + SNIPPET_SLACK) + 2
        assert "SYSREF capture window" in out

    def test_snippet_is_expanded_to_sentence_boundaries(self):
        out = snippet(self._long_body(), ("sysref",))
        # both edges landed on real boundaries, so neither is elided
        assert not out.startswith("…") and not out.endswith("…")
        assert out.endswith(".")

    def test_a_cut_edge_is_marked(self):
        """No boundary within slack -> the cut is announced, never hidden."""
        body = "start " + ("wordwordword " * 200) + "needle " + ("wordwordword " * 200)
        out = snippet(body, ("needle",))
        assert out.startswith("…") and out.endswith("…")

    def test_short_section_needs_no_ellipsis(self, retriever):
        hit = retriever.search("quad rf sampling")[0]
        assert "…" not in hit.snippet

    def test_snippet_falls_back_to_the_head_when_the_term_is_a_subtoken(self):
        body = "Alpha beta gamma. Phase noise is specified in dBc/Hz at 100 kHz."
        # `hz` matched via the compound; the excerpt still locates it
        assert "dBc/Hz" in snippet(body, ("hz",))

    def test_empty_section_yields_an_empty_snippet(self):
        assert snippet("<!-- source: REV1 p.1 -->", ("anything",)) == ""


class TestHonestDegradation:
    def test_a_corpus_without_an_index_says_rebuild(self, part):
        (part / "docs" / DOC / INDEX_FILENAME).unlink()
        r = Retriever.for_part(part)
        assert r.search("sysref") == []
        reason = r.search_unavailable()
        assert "Rebuild to enable search" in reason
        assert "TEST" in reason

    def test_an_older_index_schema_says_rebuild(self, part):
        path = part / "docs" / DOC / INDEX_FILENAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = "0"
        path.write_text(json.dumps(data), encoding="utf-8")
        r = Retriever.for_part(part)
        assert r.search("sysref") == []
        assert "Rebuild to enable search" in r.search_unavailable()

    def test_a_searchable_corpus_reports_no_reason(self, retriever):
        assert retriever.search_unavailable() == ""

    def test_corrupt_index_warns_and_keeps_the_rest_of_the_part_alive(self, part, caplog):
        (part / "docs" / DOC / INDEX_FILENAME).write_text("{ not json", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            r = Retriever.for_part(part)
            assert r.search("sysref") == []
        assert "skipping unreadable search_index.json" in caplog.text
        # sections still resolve — one bad artifact never takes a part down
        assert r.sections(number="4.5")

    def test_missing_manifest_still_cites_honestly(self, part, caplog):
        """A damaged manifest costs the page range, never the whole answer."""
        (part / "manifest.json").write_text("{ not a manifest", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            hits = Retriever.for_part(part).search("sysref setup")
        assert hits and hits[0].citation.pages == "p.?"
        assert hits[0].section.file.startswith(f"docs/{DOC}/")


class TestSearchCli:
    @pytest.fixture
    def wired(self, part, monkeypatch) -> Path:
        settings = Settings(parts_dir=part.parent, cache_dir=part.parent / ".cache").resolve()
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        return part

    def test_search_prints_heading_citation_and_snippet(self, wired, capsys):
        assert cli.main(["search", "--part", "TEST", "sysref setup"]) == 0
        out = capsys.readouterr().out
        assert "§4.5 Transmitter Electrical Characteristics" in out
        assert "§4.5, p.7-8" in out
        assert "SYSREF setup time" in out

    def test_limit_is_honoured(self, wired, capsys):
        assert cli.main(["search", "--part", "TEST", "temperature sysref", "--limit", "1"]) == 0
        assert len(capsys.readouterr().out.strip().splitlines()) == 2  # hit + snippet

    def test_json_emits_the_hit_shape(self, wired, capsys):
        assert cli.main(["search", "--part", "TEST", "sysref setup", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["part"] == "TEST" and payload["query"] == "sysref setup"
        assert payload["hits"][0]["citation"] == "§4.5, p.7-8"

    def test_no_match_exits_1_without_pretending(self, wired, capsys):
        assert cli.main(["search", "--part", "TEST", "flux capacitor"]) == 1
        assert "No matching sections." in capsys.readouterr().out

    def test_unindexed_corpus_exits_2_with_the_rebuild_message(self, wired, capsys):
        (wired / "docs" / DOC / INDEX_FILENAME).unlink()
        assert cli.main(["search", "--part", "TEST", "sysref"]) == 2
        assert "Rebuild to enable search" in capsys.readouterr().err

    def test_unbuilt_part_exits_2(self, wired, capsys):
        assert cli.main(["search", "--part", "NOPE", "sysref"]) == 2
        assert "run `dsa build` first" in capsys.readouterr().err
