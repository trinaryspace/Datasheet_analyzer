"""The derived-artifact contract (ADR 0005 / invariant 8), phase 6 ticket 01.

Nothing derived exists yet — that is the point. The envelope, the stable
record ids and the resolver land *before* the first card, so every later
ticket has something to conform to and a mechanical way to be checked. What is
asserted here is exactly what invariant 8 promises:

- a `DerivedValue` that cannot fill a field leaves it null rather than
  defaulting to a plausible number;
- every published spec record has an addressable id, and a rebuild of
  identical input reproduces every one of them;
- a `source` string resolves back to its record and its printed page — and
  resolves to *nothing*, loudly, when it is malformed, unknown or ambiguous,
  because a reference that quietly lands on the wrong row is the failure this
  whole contract exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import (
    Confidence,
    CorpusManifest,
    DerivedValue,
    PlotRecord,
    PlotSet,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.provenance import (
    PLOTS_ARTIFACT,
    SPECS_ARTIFACT,
    SourceRef,
    parse_source,
    resolve_source,
    source_ref,
    spec_record_id,
)
from datasheet_analyzer.structure.specs import build_specset

SYN = Path(__file__).parent.parent / "fixtures" / "synthetic"

DOC = "datasheet-aaaaaaaa"
OTHER_DOC = "register_map-bbbbbbbb"
DOC_HASH = "a" * 64
OTHER_HASH = "b" * 64


def _write_doc(part_dir: Path, doc: str, doc_hash: str) -> Path:
    """One document directory carrying two spec records and one plot record."""
    doc_dir = part_dir / "docs" / doc
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "specs.json").write_text(
        SpecSet(
            schema_version="3",
            part_number="TEST",
            doc_hash=doc_hash,
            records=[
                SpecRecord(
                    id=spec_record_id(0),
                    section="4.3",
                    symbol="IDD1P8",
                    name="1.8V supply current",
                    max="1350",
                    unit=SpecUnit(verbatim="mA", canonical="mA"),
                    page=21,
                    confidence=Confidence.HIGH,
                ),
                SpecRecord(
                    id=spec_record_id(1),
                    section="4.3",
                    symbol="TJ",
                    name="Junction temperature",
                    max="105",
                    unit=SpecUnit(verbatim="°C", canonical="°C"),
                    # deliberately unpinned: the resolver must report the
                    # record's honest `None` page, never invent one.
                    page=None,
                ),
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    (doc_dir / "plots.json").write_text(
        PlotSet(
            schema_version="2",
            part_number="TEST",
            doc_hash=doc_hash,
            plots=[
                PlotRecord(
                    id="4.12.1-f001",
                    section="4.12.1",
                    caption="Figure 4-1 TX Output Fullscale",
                    page_start=29,
                    page_end=37,
                )
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    return doc_dir


@pytest.fixture
def part(tmp_path: Path) -> Path:
    """A one-document built part: the case a `source` shorthand is safe in."""
    part_dir = tmp_path / "parts" / "TEST"
    _write_doc(part_dir, DOC, DOC_HASH)
    (part_dir / "manifest.json").write_text(
        CorpusManifest(part_number="TEST", pipeline_version="0.4.0").model_dump_json(),
        encoding="utf-8",
    )
    return part_dir


@pytest.fixture
def two_doc_part(tmp_path: Path) -> Path:
    """A two-document part: the case the shorthand is ambiguous in."""
    part_dir = tmp_path / "parts" / "TWO"
    _write_doc(part_dir, DOC, DOC_HASH)
    _write_doc(part_dir, OTHER_DOC, OTHER_HASH)
    (part_dir / "manifest.json").write_text(
        CorpusManifest(part_number="TWO", pipeline_version="0.4.0").model_dump_json(),
        encoding="utf-8",
    )
    return part_dir


class TestDerivedValueEnvelope:
    """The provenance envelope every derived field ships in."""

    def test_carries_verbatim_number_source_page_rule_and_grade(self):
        value = DerivedValue(
            verbatim="1350 mA",
            value_si=1.35,
            unit_si="A",
            source=f"docs/{DOC}/specs.json#rec_1",
            page=21,
            derivation="parse_quantity+si_normalize",
            confidence=Confidence.HIGH,
        )
        assert value.verbatim == "1350 mA"
        assert value.value_si == 1.35 and value.unit_si == "A"
        assert value.page == 21
        assert value.derivation == "parse_quantity+si_normalize"
        assert value.confidence is Confidence.HIGH
        assert DerivedValue.model_validate_json(value.model_dump_json()) == value

    def test_unfillable_numeric_fields_stay_null_not_zero(self):
        """`None` is the honest outcome; 0.0 would be a fabricated number."""
        value = DerivedValue(
            verbatim="See Figure 7",
            source=f"docs/{DOC}/specs.json#rec_1",
            page=21,
            derivation="parse_quantity",
        )
        assert value.value_si is None
        assert value.unit_si == ""
        on_disk = json.loads(value.model_dump_json())
        assert on_disk["value_si"] is None  # null on disk, not 0.0

    def test_ungraded_by_default_never_optimistically_high(self):
        assert DerivedValue().confidence is Confidence.UNKNOWN
        assert DerivedValue().page is None


class TestSpecRecordIds:
    """Stable, addressable ids — the thing a `source` points at."""

    def test_every_published_record_is_addressable(self, ti_sec_4_5_html):
        specset = build_specset(_raw_from(ti_sec_4_5_html), "AFE7950")
        ids = [r.id for r in specset.records]
        assert specset.records
        assert all(ids), "a record with no id can never be cited by a card"
        assert len(set(ids)) == len(ids), "ids must be unique within a document"
        assert ids[0] == "rec_1" and ids[-1] == f"rec_{len(ids)}"

    def test_ids_survive_the_published_round_trip(self, ti_sec_4_5_html):
        specset = build_specset(_raw_from(ti_sec_4_5_html), "AFE7950")
        again = SpecSet.model_validate_json(specset.model_dump_json())
        assert [r.id for r in again.records] == [r.id for r in specset.records]

    def test_id_format_is_minted_in_one_place(self):
        assert spec_record_id(0) == "rec_1"
        assert spec_record_id(411) == "rec_412"


class TestSourceRefFormat:
    def test_qualified_ref_names_its_document(self):
        assert source_ref("rec_412", doc=DOC) == f"docs/{DOC}/specs.json#rec_412"

    def test_unqualified_ref_is_the_adr_shorthand(self):
        assert source_ref("rec_412") == "specs.json#rec_412"
        assert source_ref("4.12.1-f001", artifact=PLOTS_ARTIFACT) == (
            "plots.json#4.12.1-f001"
        )

    def test_part_qualified_ref_names_its_corpus(self):
        """Phase 6, ticket 09 — the additive third form.

        A design card's values all come from one part, so its references leave
        the part implicit. A cross-part comparison's delta cites one record in
        each of two corpora, and `rec_412` exists in nearly every corpus, so a
        reference that does not name its part resolves to a confident, wrong
        record. This form is what makes such a value walkable by a caller who
        does *not* already know the answer.
        """
        assert source_ref("rec_412", doc=DOC, part="AFE7950") == (
            f"parts/AFE7950/docs/{DOC}/specs.json#rec_412"
        )

    def test_parse_round_trips_all_three_forms(self):
        for ref in (
            SourceRef(artifact=SPECS_ARTIFACT, record_id="rec_412", doc=DOC),
            SourceRef(artifact=PLOTS_ARTIFACT, record_id="4.12.1-f001"),
            SourceRef(
                artifact=SPECS_ARTIFACT, record_id="rec_412", doc=DOC, part="AFE7950"
            ),
        ):
            assert parse_source(str(ref)) == ref

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "specs.json",  # no record
            "specs.json#",  # empty record id
            "#rec_1",  # no artifact
            "specs.json#rec_1#rec_2",  # two fragments
            "sections/4-5.md#rec_1",  # not an addressable artifact
            "INDEX.md#rec_1",
            f"docs/{DOC}/specs.json#rec 1",  # whitespace in the id
            "docs/specs.json#rec_1",  # no document name
            "docs//specs.json#rec_1",
            # The part-qualified form (ticket 09) is exact too: it is
            # `parts/<PART>/docs/<doc>/<artifact>`, and every near miss is
            # refused rather than read as one of the shorter forms.
            f"parts//docs/{DOC}/specs.json#rec_1",  # no part name
            "parts/TEST/specs.json#rec_1",  # no document
            f"parts/TEST/{DOC}/specs.json#rec_1",  # no `docs/` segment
            f"corpus/TEST/docs/{DOC}/specs.json#rec_1",  # not the layout
        ],
    )
    def test_malformed_references_are_refused_not_repaired(self, bad):
        assert parse_source(bad) is None


class TestResolveSource:
    """The round trip that makes invariant 8 checkable rather than asserted."""

    def test_resolves_to_the_record_and_its_printed_page(self, part, resolve_source):
        found = resolve_source(part, f"docs/{DOC}/specs.json#rec_1")
        assert found is not None
        assert found.doc == DOC
        assert found.record.symbol == "IDD1P8"
        assert found.page == 21

    def test_page_is_the_records_own_and_stays_none_when_unpinned(self, part):
        found = resolve_source(part, f"docs/{DOC}/specs.json#rec_2")
        assert found is not None and found.record.symbol == "TJ"
        assert found.page is None  # honestly unpinned, never guessed

    def test_resolves_a_plot_record_by_its_section_page(self, part):
        found = resolve_source(part, f"docs/{DOC}/plots.json#4.12.1-f001")
        assert found is not None
        assert found.artifact == PLOTS_ARTIFACT
        assert found.page == 29

    def test_shorthand_resolves_when_one_document_leaves_no_doubt(self, part):
        found = resolve_source(part, "specs.json#rec_1")
        assert found is not None and found.doc == DOC

    def test_shorthand_refuses_to_guess_across_two_documents(self, two_doc_part, caplog):
        with caplog.at_level("WARNING"):
            assert resolve_source(two_doc_part, "specs.json#rec_1") is None
        assert "ambiguous" in caplog.text
        # ...while the qualified form still resolves, per document
        one = resolve_source(two_doc_part, f"docs/{OTHER_DOC}/specs.json#rec_1")
        assert one is not None and one.doc == OTHER_DOC

    def test_unknown_record_resolves_to_nothing(self, part):
        assert resolve_source(part, f"docs/{DOC}/specs.json#rec_999") is None

    def test_unknown_document_resolves_to_nothing(self, part):
        assert resolve_source(part, "docs/datasheet-99999999/specs.json#rec_1") is None

    def test_malformed_reference_resolves_to_nothing(self, part):
        assert resolve_source(part, "rec_1") is None

    def test_record_with_no_id_is_unaddressable_not_its_neighbour(self, tmp_path):
        """A corpus published before ADR 0005 carries no ids. Nothing on it may
        resolve — least of all to the record that happens to sit nearby."""
        part_dir = tmp_path / "parts" / "OLD"
        doc_dir = part_dir / "docs" / DOC
        doc_dir.mkdir(parents=True)
        (doc_dir / "specs.json").write_text(
            SpecSet(
                schema_version="2",
                part_number="OLD",
                doc_hash=DOC_HASH,
                records=[SpecRecord(symbol="IDD1P8", page=21)],
            ).model_dump_json(),
            encoding="utf-8",
        )
        assert resolve_source(part_dir, f"docs/{DOC}/specs.json#rec_1") is None
        assert resolve_source(part_dir, "specs.json#") is None

    def test_unbuilt_part_resolves_to_nothing_without_raising(self, tmp_path):
        assert resolve_source(tmp_path / "nope", "specs.json#rec_1") is None


def _raw_from(html: str):
    """Section 4.5 of the recorded AFE7950 page, as a one-section document."""
    from datasheet_analyzer.extract.ti_html import parse_section
    from datasheet_analyzer.models import RawDocument, SourceDocument

    sec = parse_section(
        html,
        "https://www.ti.com/document-viewer/AFE7950/datasheet/GUID-X#GUID-Y",
        number="4.5",
        title="Transmitter Electrical Characteristics",
    )
    sec.page_start, sec.page_end = 7, 13
    return RawDocument(
        source=SourceDocument(content_hash=DOC_HASH, path="afe7950.pdf"),
        sections=[sec],
        extractor="ti_html",
    )


class TestIdsAreStableAcrossARebuild:
    """The promise that makes an id worth storing in a card."""

    @pytest.fixture
    def synthetic_env(self, tmp_path, monkeypatch, make_synthetic_pdf):
        """The pipeline test's replayed-TI environment: a real build, offline.

        Duplicated from `test_pipeline.py` on purpose — this module asserts a
        property *of a rebuild*, so it needs to run two of them.
        """
        from datasheet_analyzer.extract import get_backend
        from datasheet_analyzer.extract.http import MappingFetcher

        pdf = tmp_path / "test9000.pdf"
        make_synthetic_pdf(pdf)
        settings = Settings(
            parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache"
        ).resolve()
        base = "https://www.ti.com/document-viewer/TEST9000/datasheet"
        mapping = {
            base: (SYN / "ti_main.html").read_text(encoding="utf-8"),
            f"{base}/GUID-AAAA1111-0000-0000-0000-000000000001#TITLE-X1": (
                SYN / "ti_sec_features.html"
            ).read_text(encoding="utf-8"),
            f"{base}/GUID-BBBB2222-0000-0000-0000-000000000002#TITLE-X2": (
                SYN / "ti_sec_absmax.html"
            ).read_text(encoding="utf-8"),
        }
        backend = get_backend("ti_html")
        backend.fetcher = MappingFetcher(mapping)
        monkeypatch.setattr(
            "datasheet_analyzer.pipeline.get_backend", lambda name: backend
        )
        return pdf, settings

    def _specs_on_disk(self, part_dir: Path) -> list[dict]:
        paths = sorted((part_dir / "docs").glob("*/specs.json"))
        assert paths, "the build published no specs.json — the test would be vacuous"
        return [json.loads(p.read_text(encoding="utf-8")) for p in paths]

    def test_rebuild_of_identical_input_reproduces_every_id(self, synthetic_env):
        pdf, settings = synthetic_env
        first = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        before = self._specs_on_disk(first.part_dir)
        ids = [r["id"] for doc in before for r in doc["records"]]
        assert ids and all(ids)

        # use_cache=False: re-extract from the PDF + replayed HTML, so the ids
        # are re-derived rather than read back out of the extraction cache.
        second = build_part(
            pdf, part_number="TEST9000", settings=settings,
            use_cache=False, use_llm=False,
        )
        assert not second.cached_extraction
        assert self._specs_on_disk(second.part_dir) == before

    def test_published_records_are_addressable_from_the_manifest_side(
        self, synthetic_env, resolve_source
    ):
        """The end-to-end shape a card will use: doc dir + id -> record + page."""
        from datasheet_analyzer.publish import doc_dir_name_for_source

        pdf, settings = synthetic_env
        result = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        doc = doc_dir_name_for_source(result.manifest.documents[0])
        records = self._specs_on_disk(result.part_dir)[0]["records"]
        for record in records:
            found = resolve_source(
                result.part_dir, source_ref(record["id"], doc=doc)
            )
            assert found is not None, record["id"]
            assert found.page == record["page"]

    def test_manifest_records_the_derivation_rule_version(self, synthetic_env):
        pdf, settings = synthetic_env
        result = build_part(pdf, part_number="TEST9000", settings=settings, use_llm=False)
        assert result.manifest.card_version == settings.card_version
        on_disk = json.loads(
            (result.part_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert on_disk["card_version"] == settings.card_version
