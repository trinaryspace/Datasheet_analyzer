"""A spec record id is unique inside its document.

Phase 6.5, ticket 08. `spec_record_id` was a pure function of `(section,
table_index, row_index)`, and `build_specset` numbers tables *within* a
section — so a document whose sections carry no printed number restarted
`table_index` at 0 in every one of them and several records computed one id.

Measured before the fix: **AD9081 published 549 spec records carrying 259
distinct ids**, `rec_s-t0-r0` alone carried by 14. Every datasheet read
without a numbered table of contents had it — every non-TI part in the corpus.

The consequence was never corruption, because phase 6 chose refusal: a card
cites the first record carrying an id and refuses the rest. But the cost was
large and visible — AD9081's interface card kept 1 row of the 21 its selectors
matched.

The fix keys the id on the section's **published file stem**, which is already
unique per section (two sections sharing it would collide on disk first). The
alternative — numbering tables document-globally — was rejected for a concrete
reason asserted below: `table_index` is a position *within* a section, read as
one by the CSV twin names and by every lookup back into `section.tables`.
"""

from __future__ import annotations

from datasheet_analyzer.config import SPECS_SCHEMA_VERSION
from datasheet_analyzer.models import (
    RawDocument,
    SectionNode,
    SourceDocument,
    SpecRecord,
    TableBlock,
    spec_record_id,
)
from datasheet_analyzer.structure.corpus import section_stem
from datasheet_analyzer.structure.specs import build_specset

HEADERS = ["Parameter", "Min", "Typ", "Max", "Unit"]


def _table(caption: str, rows) -> TableBlock:
    return TableBlock(caption=caption, headers=list(HEADERS), grid=[list(r) for r in rows], page=4)


def _unnumbered_document() -> RawDocument:
    """An ADI-shaped datasheet: real section titles, no printed numbers.

    Two sections, each with one table, each table's first row — the exact
    shape that computed `rec_s-t0-r0` three times.
    """
    sections = [
        SectionNode(
            number="",
            title="Recommended Operating Conditions",
            page_start=4,
            page_end=4,
            tables=[_table("Table 1.", [["AVDD2", "1.9", "2.0", "2.1", "V"]])],
        ),
        SectionNode(
            number="",
            title="Absolute Maximum Ratings",
            page_start=6,
            page_end=6,
            tables=[_table("Table 2.", [["TJ", "", "", "150", "degC"]])],
        ),
        SectionNode(
            number="",
            title="Thermal Resistance",
            page_start=7,
            page_end=7,
            tables=[_table("Table 3.", [["theta-JA", "", "18.2", "", "degC/W"]])],
        ),
    ]
    return RawDocument(
        source=SourceDocument(content_hash="a" * 64, path="x.pdf", doc_type="datasheet"),
        sections=sections,
        extractor="pdf_layout",
        extractor_version="test-1",
    )


class TestTheCollisionIsGone:
    def test_every_record_in_an_unnumbered_document_has_its_own_id(self):
        specs = build_specset(_unnumbered_document(), "ADI9000")
        ids = [r.id for r in specs.records]

        assert len(ids) == 3
        assert len(set(ids)) == 3, f"ids collided: {ids}"

    def test_the_id_names_the_section_it_came_from(self):
        specs = build_specset(_unnumbered_document(), "ADI9000")
        assert specs.records[0].id.startswith("rec_srecommended_operating_conditions-t0-r0")

    def test_a_numbered_document_still_keys_on_its_number(self):
        """`section_stem` puts the number first, so reading order survives."""
        section = SectionNode(number="4.5", title="Transmitter", page_start=7)
        assert section_stem(section).startswith("4-5-")


class TestTheIdIsStable:
    def test_the_same_input_computes_the_same_id(self):
        first = build_specset(_unnumbered_document(), "ADI9000")
        second = build_specset(_unnumbered_document(), "ADI9000")
        assert [r.id for r in first.records] == [r.id for r in second.records]

    def test_a_new_section_does_not_renumber_the_others(self):
        """Why the section stem beats document-global table numbering.

        Ids appear in citations that are already published. Numbering tables
        across the document would shift every table after an inserted one, so
        a revision that adds a section silently moves every citation below it.
        Keying on the section leaves its neighbours alone.
        """
        before = build_specset(_unnumbered_document(), "ADI9000")
        grown = _unnumbered_document()
        grown.sections.insert(
            1,
            SectionNode(
                number="",
                title="Electrical Characteristics",
                page_start=5,
                page_end=5,
                tables=[_table("Table 1b.", [["IDD", "", "1350", "1500", "mA"]])],
            ),
        )
        after = build_specset(grown, "ADI9000")

        kept = {r.id for r in before.records} & {r.id for r in after.records}
        assert len(kept) == 3, "every pre-existing record must keep its id"


class TestWhatTableIndexMeans:
    def test_table_index_still_indexes_into_its_section(self):
        """The reason document-global numbering was rejected, asserted.

        `table_index` is a position inside `section.tables`; the CSV twin
        names and every lookup back into the section read it as one.
        """
        document = _unnumbered_document()
        document.sections[0].tables.append(_table("Table 1b.", [["IDD", "", "1350", "", "mA"]]))
        specs = build_specset(document, "ADI9000")

        for record in specs.records:
            section = next(
                s
                for s in document.sections
                if s.number == record.section and section_stem(s) == record.section_key
            )
            assert record.table_index < len(section.tables)


class TestOlderRecordsStillResolve:
    def test_a_record_without_a_section_key_falls_back_to_its_number(self):
        """A `specs.json` written before this ticket stays addressable."""
        record = SpecRecord.model_validate(
            {"section": "4.5", "table_index": 2, "row_index": 13, "symbol": "ATTstep"}
        )
        assert record.id == spec_record_id("4.5", 2, 13) == "rec_s4.5-t2-r13"

    def test_the_schema_version_records_the_change(self):
        assert SPECS_SCHEMA_VERSION == "4"
