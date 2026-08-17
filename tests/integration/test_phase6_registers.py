"""Phase 6, ticket 05 gate: LMX1204 + its programmer's guide, built offline.

The register-summary claim is *"the corpus answers bring-up questions, and
every register traces to a printed page"*, and this module is where it is
measured against a real document rather than a synthetic one. The fixture is
the honest one the ticket asks for: the LMX1204 **datasheet**
(`tests/fixtures/pdf/lmx1204.pdf`) built as the part, with the LMX1204
**register map** (`tests/fixtures/pdf/LMX1204_registermap.pdf`, SNAU269A)
attached as a `register_map` companion — the same two documents a designer
would actually have, rather than a register map bolted onto an unrelated part.

The datasheet is pinned `--vendor unknown`, which is the LM741 precedent
recorded as cli-override evidence: LMX1204 is a TI part, so detection would
pin `ti` and prefer the `ti_html` backend, that backend needs the network, and
this repo holds no recorded document-viewer pages for LMX1204 — a `ti`-routed
build simply cannot run in a hermetic suite. `unknown` routes it through the
offline `pdf_layout` floor. The **companion needs no such pin**: this ticket
routes every `register_map` to the layout floor whatever its vendor, and the
build below asserts that the companion really was detected as `ti` and routed
to `pdf_layout` anyway — which is the routing change, measured.

What is asserted here, and nowhere else:

- both documents publish a `registers.json` whose records carry an address in
  both forms, a name, a reset and a printed page;
- `dsa regs --addr` resolves by value across every notation the two documents
  and a caller can print;
- every register's reset traces back to text printed on the page it cites;
- the golden set verifies at 100% on all four of its tables.

**Ticket 06's accuracy gate lives here too** (`TestBitFieldAccuracy` onward),
against the same two documents, because it is the same corpus and the fields
are published on the very records above. That gate is the one this phase was
least willing to fake: it hand-verifies five registers field by field off the
printed pages, and then walks **every** published field of both documents and
requires its printed quartet — bit range, name, access, reset — to appear on the
page the field cites. A wrong bit range cannot survive that walk, which is the
whole point: the ticket's instruction was to ship nothing rather than something
approximate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.acquire import append_to_inventory, register_source
from datasheet_analyzer.config import Settings
from datasheet_analyzer.models import DocType
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.retrieve import CorpusIndex, Retriever
from datasheet_analyzer.structure.registers import RESET_HEADING_DERIVATION

FIXTURES = Path(__file__).parent.parent / "fixtures"
GATE_PDFS = FIXTURES / "pdf"
DATASHEET = GATE_PDFS / "lmx1204.pdf"
REGISTER_MAP = GATE_PDFS / "LMX1204_registermap.pdf"
GOLDEN = FIXTURES / "golden_qa_LMX1204.yaml"

PART = "LMX1204"

#: Measured on both printed summaries (Table 1-1 of SNAU269A, Table 7-1 of
#: SNAS800B): the same 35 registers, 0x0 through 0x5A.
N_REGISTERS = 35

#: Measured, ticket 06, identically in both documents: 28 of the 35 registers
#: publish a validated bit-field set, 116 fields in all. Of the seven that do
#: not, six print a field table the layout floor's reconstruction gate rejected
#: (R7, R8, R9, R16, R72, R86) and one — R90 — prints a field table whose own
#: ranges overlap, which is a typo in the document and a refusal here.
N_FIELD_SETS = 28
N_FIELDS = 116
NO_FIELDS = ("R7", "R8", "R9", "R16", "R72", "R86", "R90")

#: Hand-verified against the printed pages of SNAU269A — the ticket's accuracy
#: sample, read cell by cell off pp. 4, 5 and 19 and reproduced here as
#: `(bit range, field name, access, reset)` in printed order. Every field of
#: every one of these registers must match **exactly**: no partial credit.
#:
#: `R25`'s 5:3 name is two printed lines (`CLK_DIV` over `CLK_MULT`, aliases for
#: one field), which extraction glues with a space — the convention this repo
#: applies to every wrapped cell, and deliberately not "fixed" here.
HAND_VERIFIED = {
    "R0": [  # p.4
        ("15:3", "RESERVED", "R", "0x0000"),
        ("2", "POWERDOWN", "R/W", "0x0"),
        ("1", "RESERVED", "R/W", "0x0"),
        ("0", "RESET", "R/W", "0x0"),
    ],
    "R2": [  # p.4
        ("15:11", "RESERVED", "R", "0x00"),
        ("10", "RESERVED", "R/W", "0x0"),
        ("9:6", "SMCLK_DIV_PRE", "R/W", "0x8"),
        ("5", "SMCLK_EN", "R/W", "0x1"),
        ("4:0", "RESERVED", "R/W", "0x03"),
    ],
    "R3": [  # p.5
        ("15", "CH3_EN", "R/W", "0x1"),
        ("14", "CH2_EN", "R/W", "0x1"),
        ("13", "CH1_EN", "R/W", "0x1"),
        ("12", "CH0_EN", "R/W", "0x1"),
        ("11", "LOGIC_MUTE_CAL", "R/W", "0x1"),
        ("10", "CH3_MUTE_CAL", "R/W", "0x1"),
        ("9", "CH2_MUTE_CAL", "R/W", "0x1"),
        ("8", "CH1_MUTE_CAL", "R/W", "0x1"),
        ("7", "CH0_MUTE_CAL", "R/W", "0x1"),
        ("6:3", "RESERVED", "R/W", "0x0"),
        ("2:0", "SMCLK_DIV", "R/W", "0x6"),
    ],
    "R24": [  # p.19
        ("15:14", "RESERVED", "R", "0x0"),
        ("13:12", "RESERVED", "R/W", "0x0"),
        ("11:1", "rb_TEMPSENSE", "R", "0x7FF"),
        ("0", "EN_TS_COUNT", "R/W", "0x0"),
    ],
    "R25": [  # p.19
        ("15:7", "RESERVED", "R/W", "0x004"),
        ("6", "CLK_DIV_RST", "R/W", "0x0"),
        ("5:3", "CLK_DIV CLK_MULT", "R/W", "0x2"),
        ("2:0", "CLK_MUX", "R/W", "0x1"),
    ],
}


@pytest.fixture(scope="module")
def gate(tmp_path_factory):
    """The two-document LMX1204 corpus, built exactly as a user would build it.

    `dsa build` first (the datasheet, pinned), then `dsa add-doc` for the
    companion, then `dsa build` again — the second build is what extracts the
    register map, because `build_part` extracts every document in the
    inventory.
    """
    assert DATASHEET.exists(), f"gate fixture missing: {DATASHEET}"
    assert REGISTER_MAP.exists(), f"gate fixture missing: {REGISTER_MAP}"
    tmp = tmp_path_factory.mktemp("gate-LMX1204")
    settings = Settings(parts_dir=tmp / "parts", cache_dir=tmp / ".cache").resolve()
    build_part(DATASHEET, part_number=PART, settings=settings,
               vendor="unknown", use_llm=False)
    companion = register_source(REGISTER_MAP, part_number=PART,
                                doc_type=DocType.REGISTER_MAP)
    append_to_inventory([companion], settings.parts_dir / PART)
    return build_part(DATASHEET, part_number=PART, settings=settings,
                      vendor="unknown", use_llm=False)


def _docs(gate) -> dict[str, dict]:
    """`{doc dir name: extraction stats}` for the part's two documents."""
    return {
        f"{doc.doc_type.value}-{doc.content_hash[:8]}":
            gate.manifest.extraction_stats[doc.content_hash]
        for doc in gate.manifest.documents
    }


class TestRoutingChange:
    """`REGISTER_MAP` now routes to the layout floor — measured, not asserted."""

    def test_the_companion_is_routed_to_the_layout_floor(self, gate):
        sources = json.loads(
            (gate.part_dir / "sources.json").read_text(encoding="utf-8")
        )
        companion = next(s for s in sources if s["doc_type"] == "register_map")
        # The routing change is about *doc type*, not vendor: this companion is
        # pinned `unknown` (the part's `--vendor` override applies to the whole
        # inventory) and still routes to the layout floor. The vendor-neutrality
        # of that is asserted per profile in `tests/unit/test_registers.py`.
        assert companion["vendor"] == "unknown"

        stats = _docs(gate)
        register_map = next(k for k in stats if k.startswith("register_map-"))
        assert stats[register_map].backend == "pdf_layout", (
            "before ticket 05 this was pdf_text and the register map carried no "
            "tables at all"
        )

    def test_the_layout_floor_actually_reconstructed_its_tables(self, gate):
        stats = _docs(gate)
        register_map = next(k for k in stats if k.startswith("register_map-"))
        assert stats[register_map].tables_accepted >= 25, (
            "the whole point of the routing change is that the register map's "
            "tables exist"
        )


class TestRegistersArePublished:
    def test_both_documents_publish_a_register_map_of_the_same_35_registers(self, gate):
        index = CorpusIndex.load(gate.part_dir)
        by_doc = {doc.name: doc.registers for doc in index.docs if doc.registers}
        assert len(by_doc) == 2, sorted(by_doc)
        for name, registers in by_doc.items():
            assert len(registers) == N_REGISTERS, name
            printed = [r.address.verbatim for r in registers]
            assert printed[0] == "0x0"
            assert printed[-1] == "0x5A"
        assert gate.manifest.stats.n_registers == 2 * N_REGISTERS

    def test_every_register_carries_both_address_forms_a_name_and_a_page(self, gate):
        for doc in CorpusIndex.load(gate.part_dir).docs:
            for record in doc.registers:
                assert record.address.verbatim.startswith("0x"), record
                assert record.address.value is not None, record
                assert record.name.startswith("R"), record
                assert record.page is not None, record
                assert record.id.startswith("reg_"), record

    def test_the_addresses_are_the_ones_the_page_prints(self, gate):
        """Spot values read by hand off Table 1-1 (SNAU269A p.2)."""
        registers = {
            r.name: r
            for doc in CorpusIndex.load(gate.part_dir).docs
            for r in doc.registers
            if doc.name.startswith("register_map-")
        }
        assert registers["R0"].address.value == 0
        assert registers["R11"].address.verbatim == "0xB"
        assert registers["R11"].address.value == 11
        assert registers["R23"].description.startswith("Temperature Sensor")
        assert registers["R90"].address.value == 0x5A

    def test_every_register_grades_high(self, gate):
        """Both summaries reconstruct from their own declared headers and pin an
        exact page, which is what `high` means (`structure/confidence.py`)."""
        assert gate.manifest.stats.register_confidence == {
            "high": 2 * N_REGISTERS, "medium": 0, "low": 0
        }


class TestResetTracesToAPrintedPage:
    def test_every_register_states_a_reset_read_from_its_declaration(self, gate):
        """All 35 in both documents, each naming the line it was read from.

        Not every one of them can cite a *page*: a declaration the layout floor
        left as a paragraph has no page of its own, and it only gains one when
        the register's own field-description table was pinned (measured: 29 of
        35 in each document). The other six publish `page: null` rather than
        the section's 22-page range — an unpinned citation is honest, an
        invented one is not.
        """
        for doc in CorpusIndex.load(gate.part_dir).docs:
            if not doc.registers:
                continue
            for record in doc.registers:
                assert record.reset is not None, record.name
                assert record.reset.value is not None, record.name
                # invariant 8: a value read from somewhere other than the row
                # names the printed text it came from. A reset column on the
                # row itself needs no evidence beyond the record — neither of
                # these documents prints one, so all 70 take the first branch.
                assert record.reset.derivation == RESET_HEADING_DERIVATION
                assert record.name in record.reset.evidence, record.name
            pinned = [r for r in doc.registers if r.reset.page is not None]
            assert len(pinned) >= 29, (doc.name, len(pinned))

    def test_a_reset_is_the_value_the_declaration_heading_printed(self, gate):
        registers = {
            r.name: r
            for doc in CorpusIndex.load(gate.part_dir).docs
            for r in doc.registers
            if doc.name.startswith("register_map-")
        }
        # read by hand off SNAU269A: §1.1 p.4, §1.3 p.5, §1.11 p.11
        assert registers["R0"].reset.verbatim == "0x0000"
        assert registers["R0"].reset.page == 4
        assert registers["R3"].reset.verbatim == "0xFF86"
        assert registers["R3"].reset.page == 5
        assert registers["R12"].reset.verbatim == "0xFFFF"
        assert registers["R12"].reset.value == 0xFFFF
        assert registers["R12"].reset.page == 11

    def test_the_reset_evidence_appears_on_the_page_it_cites(self, gate):
        """The invariant-8 walk for this artifact: every derived reset names a
        printed line, and that line really is on the page the value cites."""
        from datasheet_analyzer.extract.pdf_structure import page_texts

        pages = {"register_map-": page_texts(REGISTER_MAP),
                 "datasheet-": page_texts(DATASHEET)}
        for doc in CorpusIndex.load(gate.part_dir).docs:
            prefix = next((p for p in pages if doc.name.startswith(p)), "")
            if not prefix or not doc.registers:
                continue
            texts = pages[prefix]
            checked = 0
            for record in doc.registers:
                page = record.reset.page
                if page is None:
                    continue  # honestly unpinned; nothing to check it against
                assert 0 < page <= len(texts), record.name
                checked += 1
                printed = " ".join(texts[page - 1].split())
                assert " ".join(record.reset.evidence.split()) in printed, (
                    f"{doc.name}/{record.name}: reset evidence is not on p.{page}"
                )
            assert checked >= 29, (doc.name, checked)


class TestRegisterLookup:
    def test_one_register_answers_to_every_notation_of_its_address(self, gate):
        """The ticket's own criterion, on the real document: `0x19`, `0x19` in
        lower case, `19h` and the decimal `25` all reach R25."""
        retriever = Retriever.for_part(gate.part_dir)
        for spelling in ("0x19", "0x19".lower(), "19h", "25"):
            hits = retriever.registers(addr=spelling)
            assert hits, spelling
            assert {h.record.name for h in hits} == {"R25"}, spelling
            # both documents print it, and each hit cites its own
            assert len({h.citation.doc for h in hits}) == 2, spelling

    def test_the_summary_table_lookup_carries_a_page_citation(self, gate):
        retriever = Retriever.for_part(gate.part_dir)
        hits = retriever.registers(name="R23")
        assert hits
        for hit in hits:
            assert hit.matched_via == "name"
            assert hit.citation.pages.startswith("p."), hit.citation.pages
            assert hit.confidence == "high"

    def test_absence_is_never_read_into_this_corpus(self, gate):
        assert Retriever.for_part(gate.part_dir).register_gap() == ""


def _by_name(gate, prefix: str = "register_map-") -> dict:
    """`{acronym: record}` for one of the part's two documents."""
    return {
        r.name: r
        for doc in CorpusIndex.load(gate.part_dir).docs
        for r in doc.registers
        if doc.name.startswith(prefix)
    }


class TestBitFieldAccuracy:
    """Ticket 06's gate: 100% on a hand-verified sample, or nothing ships."""

    @pytest.mark.parametrize("register", sorted(HAND_VERIFIED))
    def test_every_field_of_a_hand_verified_register_matches_exactly(
        self, gate, register
    ):
        """Name, bit range, access and reset, field for field, in printed order.

        No partial credit and no subset: the published list must be exactly the
        printed one, so a missing field fails as loudly as a wrong one.
        """
        record = _by_name(gate)[register]
        published = [
            (f.bits.verbatim, f.name, f.access, f.reset) for f in record.fields
        ]
        assert published == HAND_VERIFIED[register], register

    @pytest.mark.parametrize("register", sorted(HAND_VERIFIED))
    def test_the_parsed_endpoints_agree_with_the_printed_range(self, gate, register):
        for field in _by_name(gate)[register].fields:
            hi, lo = field.bits.hi, field.bits.lo
            assert hi is not None and lo is not None and hi >= lo, field
            printed = f"{hi}:{lo}" if hi != lo else f"{hi}"
            assert printed == field.bits.verbatim, field

    def test_the_same_registers_read_identically_out_of_the_datasheet(self, gate):
        """The two documents print the same register map, so the fields must be
        the same — read out of a 72-page datasheet and a 25-page programmer's
        guide by the same rules."""
        datasheet, regmap = _by_name(gate, "datasheet-"), _by_name(gate)
        for register in sorted(HAND_VERIFIED):
            assert [
                (f.bits.verbatim, f.name, f.access, f.reset)
                for f in datasheet[register].fields
            ] == HAND_VERIFIED[register], register
            assert datasheet[register].width == regmap[register].width == 16

    def test_every_published_field_is_printed_on_the_page_it_cites(self, gate):
        """The invariant-8 walk for bit fields, over **all** of them.

        For every published field of both documents, the quartet the page prints
        — bit range, field name, access, reset, in that order — must appear in
        the text of the page the field cites. That is what makes "no wrong bit
        ranges" a measurement rather than a hope: a range read off the wrong
        row, or a name paired with another row's access, cannot appear as a run
        of the printed page.
        """
        from datasheet_analyzer.extract.pdf_structure import page_texts

        pages = {"register_map-": page_texts(REGISTER_MAP),
                 "datasheet-": page_texts(DATASHEET)}
        checked = 0
        for doc in CorpusIndex.load(gate.part_dir).docs:
            prefix = next((p for p in pages if doc.name.startswith(p)), "")
            if not prefix:
                continue
            texts = pages[prefix]
            for record in doc.registers:
                for field in record.fields:
                    assert field.page is not None, (record.name, field.name)
                    assert 0 < field.page <= len(texts)
                    printed = " ".join(texts[field.page - 1].split())
                    quartet = " ".join(
                        part
                        for part in (
                            field.bits.verbatim, field.name, field.access, field.reset
                        )
                        if part
                    )
                    assert quartet in printed, (
                        f"{doc.name}/{record.name}: {quartet!r} is not printed on "
                        f"p.{field.page}"
                    )
                    checked += 1
        assert checked == 2 * N_FIELDS, checked


class TestBitFieldCoverageIsReported:
    def test_both_documents_publish_the_same_field_sets(self, gate):
        for prefix in ("register_map-", "datasheet-"):
            records = _by_name(gate, prefix)
            with_fields = [r for r in records.values() if r.fields]
            assert len(with_fields) == N_FIELD_SETS, prefix
            assert sum(len(r.fields) for r in with_fields) == N_FIELDS, prefix

    def test_every_published_set_tiles_its_register_with_no_gap(self, gate):
        """Coverage is checkable, and here it is checked: 16 bits, once each."""
        for record in _by_name(gate).values():
            if not record.fields:
                continue
            assert record.width == 16, record.name
            claimed = [
                bit
                for field in record.fields
                for bit in range(field.bits.lo, field.bits.hi + 1)
            ]
            assert sorted(claimed) == list(range(16)), record.name
            assert record.unaccounted_bits == [], record.name

    def test_a_register_with_no_readable_fields_is_kept_and_says_why(self, gate):
        records = _by_name(gate)
        assert set(NO_FIELDS) == {n for n, r in records.items() if not r.fields}
        for name in NO_FIELDS:
            record = records[name]
            assert record.fields_reason, name
            # ...and the register itself is intact: address, reset, page
            assert record.address.value is not None and record.reset is not None

    def test_the_documents_own_overlapping_table_is_refused(self, gate):
        """R90 prints `15:8` and then `15:0` (SNAU269A p.24) — a typo in the
        document. Publishing either field would be a guess about which range
        was meant, so the whole set is refused and the reason says so."""
        record = _by_name(gate)["R90"]
        assert record.fields == []
        assert "claim bit 8" in record.fields_reason
        assert "15:8" in record.fields_reason and "15:0" in record.fields_reason

    def test_the_set_says_out_loud_how_many_registers_publish_fields(self, gate):
        warnings = gate.manifest.derived_warnings
        assert any(
            f"bit fields published for {N_FIELD_SETS} of {N_REGISTERS} registers" in w
            for w in warnings
        ), warnings

    def test_every_field_set_grades_medium(self, gate):
        """Both documents' field tables only pass the layout floor's gate on a
        rescue split, and a rescued grid that nonetheless tiles the register is
        `medium`: program against it, and confirm on the printed page."""
        grades = {
            record.fields_confidence.value
            for record in _by_name(gate).values()
            if record.fields
        }
        assert grades == {"medium"}


class TestBitFieldLookup:
    def test_a_field_name_finds_the_register_it_lives_in(self, gate):
        hits = Retriever.for_part(gate.part_dir).registers(field="CLK_MUX")
        assert {h.record.name for h in hits} == {"R25"}
        assert {h.matched_via for h in hits} == {"field"}
        # both documents print it, and each hit cites its own
        assert len({h.citation.doc for h in hits}) == 2

    def test_a_field_no_register_publishes_is_no_hit_rather_than_a_guess(self, gate):
        assert Retriever.for_part(gate.part_dir).registers(field="NCO_EN") == []

    def test_a_field_lookup_states_the_registers_it_could_not_consider(self, gate):
        """Invariant 8's honesty clause for a filter on a derived value: seven
        registers per document publish no fields, so a field lookup across this
        part's two documents cannot establish that a field does not exist."""
        gap = Retriever.for_part(gate.part_dir).register_field_gap()
        assert f"{2 * len(NO_FIELDS)} of {2 * N_REGISTERS} registers" in gap
        assert "cannot establish that a field does not exist" in gap

    def test_the_json_view_carries_the_bits_both_ways(self, gate):
        (hit, *_) = Retriever.for_part(gate.part_dir).registers(name="R25")
        payload = hit.as_dict()
        assert payload["width"] == 16
        assert payload["fields"][3]["name"] == "CLK_MUX"
        assert payload["fields"][3]["bits"] == {
            "verbatim": "2:0", "hi": 2, "lo": 0, "derivation": "parse_bit_range"
        }
        assert payload["fields_unaccounted_for"] == []


class TestGoldenSet:
    """The ticket's own gate: the golden questions verify at 100%."""

    def test_every_table_of_dsa_verify_passes(self, gate):
        from datasheet_analyzer.evalh.citations import (
            summarize,
            verify_ask_queries,
            verify_questions,
            verify_reg_queries,
            verify_search_queries,
        )
        from datasheet_analyzer.evalh.golden import (
            load_golden,
            render_reg_query_report,
            render_verification_report,
        )
        from datasheet_analyzer.extract.pdf_structure import page_texts

        questions = load_golden(GOLDEN)
        assert questions, "the gate part must carry a benchmark"

        results = verify_questions(questions, gate.part_dir, page_texts(REGISTER_MAP))
        summary = summarize(results)
        assert summary["failed"] == 0, render_verification_report(results)

        reg_results = verify_reg_queries(questions, gate.part_dir)
        assert len(reg_results) >= 4, (
            "address->name, decimal->name, name->reset, name->bit field"
        )
        assert [r.id for r in [q.question for q in reg_results if not q.ok]] == [], (
            render_reg_query_report(reg_results)
        )

        ask_results = verify_ask_queries(questions, gate.part_dir)
        assert ask_results and all(r.ok for r in ask_results)
        search_results = verify_search_queries(questions, gate.part_dir)
        assert search_results and all(r.ok for r in search_results)
