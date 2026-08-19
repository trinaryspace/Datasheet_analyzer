"""The phase-6 derived-artifact contract: invariant 8, made checkable.

Nine tickets are written in parallel against what ticket 01 froze, so this
file guards the *contract* rather than any one artifact's behaviour: the
provenance envelope's field set, the stable record ids a `source` points at,
the resolver that turns one back into a record and a printed page, the
checker every derived artifact must pass, the publish cache key that
regenerates a card when its derivation rules change, and the four CLI
subcommands whose flags are frozen here and whose behaviour lands elsewhere.

Two things here are load-bearing beyond their size:

- **Ids must survive a rebuild.** A card written last week points at
  `specs.json#rec_s1-t0-r2`; if a rebuild renumbers that row, every citation
  on the card silently moves to a different specification. The test builds
  the *same PDF bytes* twice, into two independent parts and caches, and
  compares.
- **`check_provenance` is the invariant-8 test the whole phase shares.** It
  is exercised here against a real published corpus — a card whose sources
  resolve passes, one that cites a page the record is not printed on fails —
  so later tickets inherit a checker that has been shown to catch something.

Hermetic per invariant 4: synthetic PDFs built in-test with fitz, temp
`parts_dir` / `cache_dir`, no network, no model, no subprocess, no browser.
"""

from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.batch import BatchJob, skip_reason
from datasheet_analyzer.config import (
    CARDS_SCHEMA_VERSION,
    PINS_SCHEMA_VERSION,
    REGISTERS_SCHEMA_VERSION,
    SPECS_SCHEMA_VERSION,
    Settings,
    reset_settings_cache,
)
from datasheet_analyzer.derive.provenance import (
    CARDS_DIRNAME,
    PINS_ARTIFACT,
    REGISTERS_ARTIFACT,
    SPECS_ARTIFACT,
    check_provenance,
    describe_problems,
    is_derivation_rule,
    iter_derived_values,
    parse_source,
    resolve_source,
)
from datasheet_analyzer.models import (
    CARD_KINDS,
    DERIVATION_LEXICON,
    DERIVATION_VERBATIM,
    PIN_TYPES,
    VALUE_KINDS,
    BitField,
    BitRange,
    Card,
    CardRow,
    Confidence,
    DerivedValue,
    ParseConfidence,
    PinRecord,
    PinSet,
    PlotRecord,
    RegisterRecord,
    RegisterSet,
    RegisterValue,
    SourceDocument,
    SpecRecord,
    bit_field_id,
    pin_record_id,
    register_record_id,
    source_ref,
    spec_record_id,
)
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.publish import cards_current, document_dirs

REPO_ROOT = Path(__file__).resolve().parents[2]

PAGE_W, PAGE_H = 612.0, 792.0
# AD9081-style column left edges, the geometry `test_pdf_layout_tables.py`
# established as a table the layout engine actually accepts.
X = {"param": 56.0, "conditions": 222.0, "min": 435.0, "typ": 460.0, "max": 515.0, "unit": 548.0}
PITCH = 13.0
CAP_Y = 140.0
HDR_Y = 153.0


def _write_spec_pdf(path: Path) -> None:
    """A two-page PDF holding one real, acceptable parametric table."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    lines = [
        (56.0, 112.0, "Nominal supplies with DAC output current = 26 mA, unless noted."),
        (56.0, CAP_Y, "Table 3. DAC DC Specifications"),
        (X["param"], HDR_Y, "Parameter"),
        (X["conditions"], HDR_Y, "Test Conditions/Comments"),
        (X["min"], HDR_Y, "Min"),
        (X["typ"], HDR_Y, "Typ"),
        (X["max"], HDR_Y, "Max"),
        (X["unit"], HDR_Y, "Unit"),
        (56.0, HDR_Y + PITCH, "DAC RESOLUTION"),
        (X["min"], HDR_Y + PITCH, "16"),
        (X["unit"], HDR_Y + PITCH, "Bit"),
        (62.4, HDR_Y + 2 * PITCH, "Gain Error"),
        (X["typ"], HDR_Y + 2 * PITCH, "1.5"),
        (X["unit"], HDR_Y + 2 * PITCH, "% FSR"),
        (56.0, HDR_Y + 3 * PITCH, "Supply Current"),
        (X["conditions"], HDR_Y + 3 * PITCH, "Shuffling disabled"),
        (X["typ"], HDR_Y + 3 * PITCH, "1350"),
        (X["max"], HDR_Y + 3 * PITCH, "1500"),
        (X["unit"], HDR_Y + 3 * PITCH, "mA"),
    ]
    for x, y, text in lines:
        page.insert_text((x, y), text)
    doc.set_toc([[1, "1 Specifications", 1]])
    doc.save(str(path))
    doc.close()


def _build(root: Path, pdf: Path, part: str = "P1"):
    settings = Settings(
        parts_dir=root / "parts", cache_dir=root / ".cache", library_dir=root / "library"
    ).resolve()
    result = build_part(pdf, part_number=part, settings=settings, vendor="unknown", use_llm=False)
    return result, settings


def _doc_dir(result) -> Path:
    return document_dirs(result.manifest, part_dir=result.part_dir)[
        result.manifest.documents[0].content_hash
    ]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One published corpus with real spec records, built once for this module."""
    root = tmp_path_factory.mktemp("derived-contract")
    pdf = root / "spec.pdf"
    _write_spec_pdf(pdf)
    result, settings = _build(root / "a", pdf)
    doc_dir = _doc_dir(result)
    records = json.loads((doc_dir / SPECS_ARTIFACT).read_text(encoding="utf-8"))["records"]
    assert records, "the synthetic table produced no spec records to cite"
    return {
        "root": root,
        "pdf": pdf,
        "result": result,
        "settings": settings,
        "part_dir": result.part_dir,
        "doc_dir": doc_dir,
        "records": records,
    }


# --- The provenance envelope ------------------------------------------------


class TestDerivedValue:
    """`DerivedValue` is the one shape every derived field ships in."""

    def test_carries_every_contract_field_with_a_default(self):
        value = DerivedValue()
        for name in (
            "verbatim",
            "value_si",
            "unit_si",
            "source",
            "page",
            "derivation",
            "confidence",
        ):
            assert name in DerivedValue.model_fields, f"{name} missing from the envelope"
        assert value.verbatim == ""
        assert value.value_si is None
        assert value.unit_si == ""
        assert value.source == ""
        assert value.page is None
        assert value.derivation == ""
        assert value.confidence is Confidence.UNKNOWN
        # The "and says so" half of the invariant lives here.
        assert value.null_reason == ""
        assert value.filled is False

    def test_a_null_value_with_no_reason_is_a_violation(self):
        problems = check_provenance(DerivedValue())
        assert problems == ["<value>: null value carries no null_reason"]

    def test_missing_builds_the_honest_empty_value(self):
        value = DerivedValue.missing("no recommended maximum printed")
        assert value.filled is False
        assert value.null_reason == "no recommended maximum printed"
        assert check_provenance(value) == []

    def test_copied_and_labeled_name_their_clause(self):
        copied = DerivedValue.copied("1350 mA", source="specs.json#rec_s1-t0-r2", page=5)
        assert copied.derivation == DERIVATION_VERBATIM
        assert check_provenance(copied) == []

        labeled = DerivedValue.labeled("ground", source="pins.json#pin_t0-r3-A1", page=4)
        assert labeled.derivation == DERIVATION_LEXICON
        assert check_provenance(labeled) == []

    def test_a_filled_value_must_carry_a_source_a_page_and_a_rule(self):
        problems = check_provenance(DerivedValue(verbatim="1350 mA"))
        joined = " | ".join(problems)
        assert "derivation" in joined
        assert "source" in joined
        assert "no page" in joined

    def test_derivation_must_be_a_rule_name_not_prose(self):
        assert is_derivation_rule("verbatim_copy")
        assert is_derivation_rule("parse_quantity+si_normalize")
        assert not is_derivation_rule("")
        assert not is_derivation_rule("estimated from the plot")
        assert not is_derivation_rule("ParseQuantity")

        value = DerivedValue(
            verbatim="1.35",
            source="specs.json#rec_s1-t0-r2",
            page=5,
            derivation="read off figure 7 by eye",
        )
        assert any("is not a rule name" in p for p in check_provenance(value))

    def test_value_kind_comes_from_the_frozen_vocabulary(self):
        assert VALUE_KINDS == ("point", "range", "bound", "tolerance")
        value = DerivedValue(
            verbatim="-40 to +85",
            source="specs.json#rec_s1-t0-r2",
            page=5,
            derivation=DERIVATION_VERBATIM,
            value_kind="interval",
        )
        assert any("value_kind" in p for p in check_provenance(value))

    def test_a_page_below_one_is_not_a_printed_page(self):
        value = DerivedValue(
            verbatim="16",
            source="specs.json#rec_s1-t0-r0",
            page=0,
            derivation=DERIVATION_VERBATIM,
        )
        assert any("not a printed page" in p for p in check_provenance(value))


# --- Stable, addressable record ids -----------------------------------------


class TestRecordIds:
    def test_a_spec_id_is_a_pure_function_of_its_coordinates(self):
        record = SpecRecord(section="4.5", table_index=2, row_index=13)
        assert record.id == "rec_s4.5-t2-r13"
        assert record.id == spec_record_id("4.5", 2, 13)
        # Same coordinates, different contents -> same id.
        other = SpecRecord(section="4.5", table_index=2, row_index=13, symbol="TJ")
        assert other.id == record.id

    def test_an_unnumbered_section_still_yields_a_usable_id(self):
        assert SpecRecord(section="", table_index=0, row_index=0).id == "rec_s-t0-r0"

    def test_a_pin_id_distinguishes_the_pins_an_expanded_row_became(self):
        row = [
            PinRecord(table_index=2, row_index=0, pin=p, name="VSSA") for p in ("A1", "A2", "B1")
        ]
        assert [r.id for r in row] == ["pin_t2-r0-A1", "pin_t2-r0-A2", "pin_t2-r0-B1"]
        assert len({r.id for r in row}) == 3
        assert row[0].id == pin_record_id(2, 0, "A1")

    def test_a_register_id_and_its_bit_field_ids_nest(self):
        register = RegisterRecord(table_index=0, row_index=5, name="TXDIG_CTRL0")
        assert register.id == register_record_id(0, 5) == "reg_t0-r5"
        assert bit_field_id(register.id, 3) == "reg_t0-r5.f3"

    def test_source_ref_is_the_one_way_a_source_string_is_built(self):
        record = SpecRecord(section="4.9", table_index=0, row_index=12)
        assert source_ref(SPECS_ARTIFACT, record.id) == "specs.json#rec_s4.9-t0-r12"
        assert parse_source(source_ref(SPECS_ARTIFACT, record.id)) == (
            SPECS_ARTIFACT,
            record.id,
        )

    def test_ids_are_serialized_into_specs_json(self, built):
        for record in built["records"]:
            assert record["id"].startswith("rec_s")
        assert len({r["id"] for r in built["records"]}) == len(built["records"])

    def test_ids_are_stable_across_a_rebuild_of_identical_input(self, built, tmp_path):
        """The same PDF bytes, built again into a fresh part and cache.

        This is the property every derived artifact leans on: a card written
        against `rec_s1-t0-r2` must still be pointing at that specification
        after a rebuild, or every citation on it has silently moved.
        """
        second_pdf = tmp_path / "spec.pdf"
        shutil.copyfile(built["pdf"], second_pdf)
        assert second_pdf.read_bytes() == built["pdf"].read_bytes()

        result, _ = _build(tmp_path / "b", second_pdf, part="P2")
        rebuilt = json.loads((_doc_dir(result) / SPECS_ARTIFACT).read_text(encoding="utf-8"))[
            "records"
        ]
        assert [r["id"] for r in rebuilt] == [r["id"] for r in built["records"]]

    def test_ids_are_unique_within_a_document(self, built):
        ids = [r["id"] for r in built["records"]]
        assert len(set(ids)) == len(ids)


# --- Resolving a source back to its record and page -------------------------


class TestResolveSource:
    def test_parse_source_reads_both_bare_and_corpus_relative_forms(self):
        assert parse_source("specs.json#rec_s1-t0-r2") == (
            "specs.json",
            "rec_s1-t0-r2",
        )
        assert parse_source("docs/datasheet-1f2e3d4c/specs.json#rec_s1-t0-r2") == (
            "docs/datasheet-1f2e3d4c/specs.json",
            "rec_s1-t0-r2",
        )
        assert parse_source(r"docs\d\specs.json#rec_s1-t0-r2")[0] == "docs/d/specs.json"
        for bad in ("", "specs.json", "#rec_s1-t0-r2", "specs.json#"):
            assert parse_source(bad) is None

    def test_resolves_a_real_record_and_its_printed_page(self, built):
        record = built["records"][0]
        resolved = resolve_source(source_ref(SPECS_ARTIFACT, record["id"]), roots=built["doc_dir"])
        assert resolved is not None
        assert resolved.record_id == record["id"]
        assert resolved.record["row_verbatim"] == record["row_verbatim"]
        assert resolved.page == record["page"]
        assert resolved.path == built["doc_dir"] / SPECS_ARTIFACT

    def test_resolves_a_corpus_relative_source_against_a_part_directory(self, tmp_path):
        part_dir = tmp_path / "P1"
        doc_dir = part_dir / "docs" / "datasheet-1f2e3d4c"
        doc_dir.mkdir(parents=True)
        record = SpecRecord(section="4.5", table_index=0, row_index=1, typ="1350", page=21)
        (doc_dir / SPECS_ARTIFACT).write_text(
            json.dumps({"records": [json.loads(record.model_dump_json())]}),
            encoding="utf-8",
        )
        resolved = resolve_source(
            f"docs/datasheet-1f2e3d4c/{SPECS_ARTIFACT}#{record.id}", roots=part_dir
        )
        assert resolved is not None and resolved.record_id == record.id
        assert resolved.page == 21

    def test_resolves_a_shared_library_source_with_its_library_root(self, built):
        """A document published once into the shared store, cited from a part."""
        from datasheet_analyzer.publish import library_root_of

        library_dir = library_root_of(built["result"].manifest, built["part_dir"])
        assert library_dir is not None, "this build published into the shared store"
        record = built["records"][0]
        relative = built["doc_dir"].resolve().relative_to(library_dir).as_posix()
        resolved = resolve_source(
            f"@library/{relative}/{SPECS_ARTIFACT}#{record['id']}",
            roots=built["part_dir"],
            library_dir=library_dir,
        )
        assert resolved is not None and resolved.record_id == record["id"]

    def test_resolves_against_a_specs_json_published_before_ids_existed(self, built, tmp_path):
        """Ids are reconstructions, not lookups, so a pre-phase-6 file resolves.

        The `SPECS_SCHEMA_VERSION` bump republishes those files eventually;
        until it does, a card must not be unresolvable against a corpus
        nobody has rebuilt.
        """
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        data = json.loads((built["doc_dir"] / SPECS_ARTIFACT).read_text(encoding="utf-8"))
        for record in data["records"]:
            record.pop("id")
        (legacy_dir / SPECS_ARTIFACT).write_text(json.dumps(data), encoding="utf-8")

        wanted = built["records"][0]["id"]
        resolved = resolve_source(f"{SPECS_ARTIFACT}#{wanted}", roots=legacy_dir)
        assert resolved is not None
        assert resolved.page == built["records"][0]["page"]

    def test_a_broken_citation_resolves_to_none_and_never_raises(self, built):
        assert resolve_source("specs.json#rec_s9.9-t9-r9", roots=built["doc_dir"]) is None
        assert resolve_source("nope.json#rec_s1-t0-r0", roots=built["doc_dir"]) is None
        assert resolve_source("not a source", roots=built["doc_dir"]) is None
        assert resolve_source("specs.json#rec_s1-t0-r0", roots=()) is None

    def test_a_shared_library_source_without_a_library_root_resolves_to_none(self, built):
        record = built["records"][0]
        assert (
            resolve_source(f"@library/docs/d/specs.json#{record['id']}", roots=built["part_dir"])
            is None
        )

    def test_a_nested_bit_field_inherits_its_registers_printed_page(self, tmp_path):
        register = RegisterRecord(
            table_index=0,
            row_index=5,
            name="TXDIG_CTRL0",
            address=RegisterValue(verbatim="0x1A04", value=6660),
            page=212,
            fields=[BitField(name="NCO_EN", bits=BitRange(verbatim="[3]", hi=3, lo=3))],
        )
        payload = json.loads(
            RegisterSet(
                schema_version=REGISTERS_SCHEMA_VERSION, registers=[register]
            ).model_dump_json()
        )
        # A bit field has no id of its own on the model; the artifact writer
        # hangs one off its register, which is what `source` points at.
        payload["registers"][0]["fields"][0]["id"] = bit_field_id(register.id, 0)
        (tmp_path / REGISTERS_ARTIFACT).write_text(json.dumps(payload), encoding="utf-8")

        resolved = resolve_source(
            f"{REGISTERS_ARTIFACT}#{bit_field_id(register.id, 0)}", roots=tmp_path
        )
        assert resolved is not None
        assert resolved.record["name"] == "NCO_EN"
        assert resolved.page == 212

    def test_a_pin_source_resolves_by_its_expanded_designator(self, tmp_path):
        pins = PinSet(
            schema_version=PINS_SCHEMA_VERSION,
            pins=[
                PinRecord(table_index=0, row_index=3, pin=p, name="VSSA", page=4)
                for p in ("A1", "A2")
            ],
        )
        (tmp_path / PINS_ARTIFACT).write_text(pins.model_dump_json(), encoding="utf-8")
        resolved = resolve_source(f"{PINS_ARTIFACT}#pin_t0-r3-A2", roots=tmp_path)
        assert resolved is not None and resolved.record["pin"] == "A2"
        assert resolved.page == 4


# --- The invariant-8 walk over a whole derived artifact ---------------------


def _card_from(built, *, page_shift: int = 0) -> Card:
    """A `power` card citing the first two records of the built corpus."""
    rows = []
    for record in built["records"][:2]:
        source = source_ref(SPECS_ARTIFACT, record["id"])
        page = (record["page"] or 1) + page_shift
        rows.append(
            CardRow(
                label=record["name"] or record["symbol"] or "parameter",
                values={
                    "typ": DerivedValue.copied(
                        record["typ"] or record["min"] or "—",
                        source=source,
                        page=page,
                        confidence=Confidence(record["confidence"]),
                    ),
                    "max": DerivedValue.missing("no maximum printed", source=source),
                },
            )
        )
    return Card(
        part_number=built["part_dir"].name,
        card="power",
        schema_version=CARDS_SCHEMA_VERSION,
        card_version="1",
        rows=rows,
        sources=[SPECS_ARTIFACT],
    )


class TestInvariantEight:
    def test_iter_derived_values_walks_a_card_to_any_depth(self, built):
        card = _card_from(built)
        found = dict(iter_derived_values(card))
        assert "rows[0].values[typ]" in found
        assert "rows[1].values[max]" in found
        assert len(found) == 4

    def test_a_card_whose_sources_resolve_passes(self, built):
        card = _card_from(built)
        problems = check_provenance(card, roots=[built["doc_dir"], built["part_dir"]])
        assert problems == [], describe_problems(problems, subject="power card")

    def test_a_card_citing_the_wrong_page_is_caught(self, built):
        card = _card_from(built, page_shift=1)
        problems = check_provenance(card, roots=built["doc_dir"])
        assert problems, "a card citing the wrong page must not pass"
        assert all("is printed on p." in p for p in problems)

    def test_a_card_citing_a_record_that_does_not_exist_is_caught(self, built):
        card = _card_from(built)
        card.rows[0].values["typ"].source = "specs.json#rec_s9.9-t9-r9"
        problems = check_provenance(card, roots=built["doc_dir"])
        assert any("resolves to no record on disk" in p for p in problems)

    def test_the_structural_check_needs_no_corpus(self, built):
        """Without `roots` the shape is still checked — what a unit test uses."""
        card = _card_from(built)
        assert check_provenance(card) == []
        card.rows[0].values["max"].null_reason = ""
        assert check_provenance(card) == ["rows[0].values[max]: null value carries no null_reason"]

    def test_describe_problems_names_every_violation(self):
        assert "provenance intact" in describe_problems([])
        message = describe_problems(["a: broke", "b: broke"], subject="power card")
        assert "power card: 2 provenance violation(s)" in message
        assert "  - a: broke" in message


# --- DSA_CARD_VERSION and the publish cache key -----------------------------


class TestCardVersion:
    def test_card_version_is_env_driven_with_a_default(self, monkeypatch):
        assert Settings().card_version == "1"
        monkeypatch.setenv("DSA_CARD_VERSION", "7")
        reset_settings_cache()
        try:
            from datasheet_analyzer.config import get_settings

            assert get_settings().card_version == "7"
        finally:
            monkeypatch.delenv("DSA_CARD_VERSION", raising=False)
            reset_settings_cache()

    def test_a_part_with_no_cards_is_current(self, tmp_path):
        assert cards_current(tmp_path, "1") is True
        (tmp_path / CARDS_DIRNAME).mkdir()
        assert cards_current(tmp_path, "1") is True

    def test_a_card_built_by_older_rules_is_stale(self, tmp_path):
        from datasheet_analyzer.derive.cards import part_corpus_key

        cards = tmp_path / CARDS_DIRNAME
        cards.mkdir()
        # Phase 6.5 ticket 03 added a third term to the key. This test is
        # about the `card_version` term, so the other two must agree —
        # otherwise it would pass for the wrong reason.
        card = Card(
            card="power",
            schema_version=CARDS_SCHEMA_VERSION,
            card_version="1",
            corpus_key=part_corpus_key(tmp_path),
        )
        (cards / "power.json").write_text(card.model_dump_json(), encoding="utf-8")
        assert cards_current(tmp_path, "1") is True
        assert cards_current(tmp_path, "2") is False

    def test_an_unreadable_card_is_stale_not_a_crash(self, tmp_path):
        cards = tmp_path / CARDS_DIRNAME
        cards.mkdir()
        (cards / "power.json").write_text("{ not json", encoding="utf-8")
        assert cards_current(tmp_path, "1") is False

    def test_the_batch_skip_gate_republishes_when_card_version_moves(self, built):
        """The wiring, end to end: a stale card unskips an otherwise-current part."""
        settings = built["settings"]
        job = BatchJob(pdf_path=built["pdf"], part=built["part_dir"].name)
        assert skip_reason(job, settings=settings), "a freshly built part must skip"

        cards = built["part_dir"] / CARDS_DIRNAME
        cards.mkdir(exist_ok=True)
        stale = Card(card="power", schema_version=CARDS_SCHEMA_VERSION, card_version="0")
        (cards / "power.json").write_text(stale.model_dump_json(), encoding="utf-8")
        try:
            assert skip_reason(job, settings=settings) == ""
        finally:
            shutil.rmtree(cards)
        assert skip_reason(job, settings=settings)


# --- Additive only: nothing here may invalidate the extraction cache --------


class TestAdditiveOnly:
    def test_every_phase_6_model_constructs_with_no_arguments(self):
        for model in (
            DerivedValue,
            PinRecord,
            PinSet,
            RegisterValue,
            BitRange,
            BitField,
            RegisterRecord,
            RegisterSet,
            CardRow,
            Card,
        ):
            model()  # a required field here would break a reader of older JSON

    def test_source_document_keeps_its_shape(self):
        """`SourceDocument` is embedded in every cached `RawDocument`.

        A new required field here invalidates `.cache/extract/*.json` in every
        checkout, which is why phase 6's additions live on the records, never
        on this model.
        """
        required = {name for name, f in SourceDocument.model_fields.items() if f.is_required()}
        assert required == {"content_hash", "path"}

    def test_a_pre_phase_6_spec_record_loads_with_honest_defaults(self):
        record = SpecRecord.model_validate(
            {"section": "4.5", "table_index": 0, "row_index": 1, "typ": "1350 mA"}
        )
        assert record.value_si is None
        assert record.value_si_hi is None
        assert record.min_si is None and record.typ_si is None and record.max_si is None
        assert record.unit_si == ""
        assert record.value_kind == ""
        assert record.parse_confidence is ParseConfidence.NONE
        assert record.id == "rec_s4.5-t0-r1"

    def test_a_pre_phase_6_plot_record_loads_with_a_null_axis_catalog(self):
        plot = PlotRecord.model_validate({"id": "4.12.1-f007", "caption": "Gain"})
        assert plot.x_label == "" and plot.y_label == ""
        assert plot.x_min is None and plot.x_max is None
        assert plot.y_min is None and plot.y_max is None
        assert plot.axis_confidence is Confidence.UNKNOWN

    def test_the_parsed_layer_is_recorded_in_the_specs_schema_version(self):
        """The bump is what puts ids on disk for an already-built corpus.

        4 since phase 6.5 ticket 08: a record id is keyed on its section's
        file stem rather than its printed number, so every id written before
        that changes and every citation holding one has to be rewritten.
        """
        assert SPECS_SCHEMA_VERSION == "4"

    def test_a_pin_type_is_a_closed_vocabulary_with_an_honest_unknown(self):
        assert PinRecord().type == "unknown"
        assert "unknown" in PIN_TYPES
        assert set(PIN_TYPES) >= {"power", "ground", "analog", "digital", "clock", "rf"}


# --- The four CLI subcommands frozen for the rest of the phase --------------


class TestFrozenCommands:
    def test_all_four_are_registered_and_listed_in_help(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["--help"])
        out = capsys.readouterr().out
        for command in ("pins", "regs", "card", "compare"):
            assert command in out

    def test_card_choices_are_the_frozen_card_kinds(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["card", "--help"])
        out = capsys.readouterr().out
        for kind in CARD_KINDS:
            assert kind in out

    def test_pins_type_choices_are_the_frozen_lexicon_labels(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["pins", "--help"])
        out = capsys.readouterr().out
        for pin_type in PIN_TYPES:
            assert pin_type in out

    @pytest.mark.parametrize("command", sorted(cli.DERIVED_COMMANDS))
    def test_every_declared_command_now_has_its_implementation(self, command):
        """The phase closed: all four modules landed behind the frozen stubs.

        This assertion is the inverse of the one ticket 01 shipped, and
        deliberately so. While the modules were unwritten the contract's job
        was to fail *honestly* (exit 3, naming the entry point nobody had
        written yet); now that they exist, the contract's job is to prove the
        declared entry point resolves to a real callable with the frozen
        signature. The refusal path it replaces is still covered below,
        against a module that genuinely is not there.
        """
        import importlib

        module_path, func_name = cli.DERIVED_COMMANDS[command]
        entry = getattr(importlib.import_module(module_path), func_name)
        assert callable(entry)
        assert list(inspect.signature(entry).parameters) == ["args"]

    def test_a_command_whose_module_is_missing_still_fails_cleanly(
        self, monkeypatch, capsys
    ):
        """The refusal path, kept alive after its last real user landed.

        Exit 3 exists to be told apart from 1 (no match) and 2 (bad scope):
        "this tool cannot answer yet" is not "your corpus has no answer", and
        an agent that cannot tell them apart will report the wrong one.
        """
        monkeypatch.setitem(
            cli.DERIVED_COMMANDS, "pins", ("datasheet_analyzer.derive.nothing", "cli_pins")
        )
        assert cli.main(["pins", "--part", "P1"]) == cli.EXIT_NOT_IMPLEMENTED
        err = capsys.readouterr().err
        assert "datasheet_analyzer.derive.nothing.cli_pins()" in err
        assert "Nothing is missing from your corpus" in err

    def test_each_command_delegates_to_its_frozen_entry_point(self, monkeypatch):
        """The signature later tickets write against: `cli_x(args) -> int`."""
        import sys
        import types

        seen = {}
        for command, (module_path, func_name) in cli.DERIVED_COMMANDS.items():
            module = types.ModuleType(module_path)

            def _entry(args, _command=command):
                seen[_command] = args
                return 42

            setattr(module, func_name, _entry)
            monkeypatch.setitem(sys.modules, module_path, module)

        assert cli.main(["pins", "--part", "P1", "--type", "power"]) == 42
        assert seen["pins"].part == "P1" and seen["pins"].type == "power"
        assert cli.main(["regs", "--part", "P1", "--addr", "0x1A04"]) == 42
        assert seen["regs"].addr == "0x1A04"
        assert cli.main(["card", "--part", "P1", "--card", "limits"]) == 42
        assert seen["card"].card == "limits"
        assert cli.main(["compare", "P1", "P2", "--symbol", "Pdiss"]) == 42
        assert seen["compare"].parts == ["P1", "P2"]
        assert seen["compare"].symbol == "Pdiss"


# --- The written contract ---------------------------------------------------


def _unwrapped(path: Path) -> str:
    """A document's prose with its line wrapping folded out.

    The contract is what the sentence says, not where the author's editor
    broke the line, so every assertion below runs against one long line.
    Blockquote markers go with the wrapping: the invariant is quoted in both
    documents, and `>` is punctuation of the container, not of the sentence.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    return " ".join(" ".join(line.lstrip().lstrip(">").split()) for line in lines).strip()


class TestWrittenContract:
    ADR = REPO_ROOT / "docs" / "adr" / "0007-deterministic-derived-artifacts.md"
    AGENTS = REPO_ROOT / "AGENTS.md"

    def test_the_adr_exists_at_0007_and_does_not_overwrite_its_neighbours(self):
        assert self.ADR.exists(), "ADR 0007 is the phase's contract document"
        adr_dir = self.ADR.parent
        assert (adr_dir / "0005-documents-apply-to-parts.md").exists()
        assert (adr_dir / "0006-auto-resolved-scope.md").exists()

    def test_the_adr_states_the_three_clauses_and_the_null_rule(self):
        text = _unwrapped(self.ADR)
        assert "copied verbatim" in text
        assert "documented pure function" in text
        assert "checked-in lexicon" in text
        assert "No model call may appear anywhere in the derivation path" in text
        assert "leaves it null and says so" in text
        assert "never emits a plausible default" in text
        assert "card_version" in text

    def test_the_adr_records_both_rejected_alternatives_with_reasons(self):
        text = self.ADR.read_text(encoding="utf-8")
        assert "## Alternatives rejected" in text
        rejected = text.split("## Alternatives rejected", 1)[1]
        # Each is rejected *for a reason*, not merely listed.
        for alternative, following in (
            ("LLM-assisted, verified", "LLM free-form"),
            ("LLM free-form", ""),
        ):
            assert alternative in rejected
            body = rejected.split(alternative, 1)[1]
            if following:
                body = body.split(following, 1)[0]
            assert "Rejected" in body, f"{alternative} is listed without a reason"

    def test_agents_md_carries_invariant_8(self):
        text = _unwrapped(self.AGENTS)
        eight = text.split("8. **Deterministic derived artifacts", 1)[1]
        eight = eight.split("## Conventions", 1)[0]
        assert "ADR 0007" in eight
        assert "No model call may appear anywhere in the derivation path" in eight
        assert "null and says so" in eight and "null_reason" in eight
        assert "derive/provenance.py" in eight
        assert "reports the unparsed population explicitly" in eight

    def test_the_module_map_names_the_contract_module(self):
        text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        assert "| `derive/provenance.py` |" in text
        assert "`DerivedValue`" in text
        assert "`DSA_CARD_VERSION`" in text
