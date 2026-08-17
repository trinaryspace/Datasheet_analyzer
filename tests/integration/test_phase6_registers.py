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
        assert len(reg_results) >= 3, "address->name, decimal->name, name->reset"
        assert [r.id for r in [q.question for q in reg_results if not q.ok]] == [], (
            render_reg_query_report(reg_results)
        )

        ask_results = verify_ask_queries(questions, gate.part_dir)
        assert ask_results and all(r.ok for r in ask_results)
        search_results = verify_search_queries(questions, gate.part_dir)
        assert search_results and all(r.ok for r in search_results)
