"""Two corpora that differ in exactly the ways a family index must notice.

Not a test module — a fixture factory, like `mcp_corpus.py` beside it. That one
builds *one* shape for the MCP surface; a family needs several, differing one
axis at a time, because every claim the family index makes is a claim about a
difference:

- a section identical in both members (shared, listed once);
- a section whose body differs by exactly one printed value (divergent);
- a section one member does not print at all (partial);
- a section both print under different numbers and the same title (renumbered);
- a spec row both print with different values (a delta, with an SI number);
- a spec row only one member prints (`only-in`);
- a pin whose printed name moved, and one only one member prints;
- a register whose printed reset moved, and a bit field whose range moved.

Every knob is a printed cell, and every default is "the members agree", so a
test that flips one knob is testing exactly one rule.
"""

from __future__ import annotations

from pathlib import Path

from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.models import (
    BitRange,
    Confidence,
    DocType,
    PinRecord,
    PinSet,
    PinType,
    PlotSet,
    RawDocument,
    RegisterField,
    RegisterRecord,
    RegisterSet,
    RegisterWord,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecSet,
    SpecUnit,
)
from datasheet_analyzer.publish import write_corpus
from datasheet_analyzer.structure.corpus import build_section_plans

#: One doc hash per member: two members of a family are two documents, and a
#: shared hash would put both corpora in one document directory name.
HASHES = {
    "TEST9950": "aa" + "0" * 62,
    "TEST9953": "bb" + "0" * 62,
}


def doc_dir(part: str) -> str:
    return f"datasheet-{HASHES[part][:8]}"


def build_member(
    part_dir: Path,
    *,
    tj_max: str = "105",
    only_spec: str = "",
    thermal_title: str = "Thermal Information",
    thermal_body: str = "The junction-to-ambient thermal resistance is 12.3 °C/W.",
    back_matter_number: str = "6",
    drop_section: str = "",
    pin_name: str = "VSSA",
    only_pin: str = "",
    reset: str = "0x0211",
    field_bits: str = "2:0",
    field_hi: int = 2,
    field_lo: int = 0,
) -> Path:
    """One member corpus, every difference from its sibling passed in explicitly.

    Defaults are the *agreeing* member. `tj_max` is the one printed value the two
    reference members differ on out of the box (105 against 125 °C), which is the
    delta a family index exists to tabulate.
    """
    part = part_dir.name
    doc_hash = HASHES[part]
    source = SourceDocument(
        content_hash=doc_hash,
        path=f"pdfs/{part.lower()}.pdf",
        part_number=part,
        doc_type=DocType.DATASHEET,
        revision="SBASA41E" if part.endswith("50") else "SBASAN1A",
        page_count=140,
    )
    sections = [
        SectionNode(
            number="4.3",
            title="Recommended Operating Conditions",
            page_start=6,
            page_end=6,
            paragraphs=[
                "Operating junction temperature TJ is rated for this device.",
                "The 1.2 V rails accept 1.15 V minimum on every supply pin.",
            ],
        ),
        SectionNode(
            number="4.4",
            title=thermal_title,
            page_start=7,
            page_end=7,
            paragraphs=[thermal_body],
        ),
        SectionNode(
            number=f"{back_matter_number}.1",
            title="Support Resources",
            page_start=120,
            page_end=120,
            paragraphs=["TI E2E support forums are the fastest route to help."],
        ),
    ]
    sections = [s for s in sections if s.number != drop_section]
    raw = RawDocument(
        source=source,
        sections=sections,
        extractor="ti_html",
        extractor_version="test-1",
    )
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        f"# {part}\n\nSections: 4.3 Recommended Operating Conditions.\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        specsets=[
            _specs(part, doc_hash, tj_max=tj_max, only_spec=only_spec)
        ],
        plotsets=[PlotSet(schema_version="3", part_number=part, doc_hash=doc_hash)],
        pinsets=[_pins(part, doc_hash, pin_name=pin_name, only_pin=only_pin)],
        registersets=[
            _registers(
                part, doc_hash, reset=reset,
                field_bits=field_bits, field_hi=field_hi, field_lo=field_lo,
            )
        ],
    )
    return part_dir


def _specs(part: str, doc_hash: str, *, tj_max: str, only_spec: str) -> SpecSet:
    records = [
        SpecRecord(
            id="rec_1",
            section="4.3", table_index=0, row_index=0, symbol="TJ",
            name="Operating junction temperature", max=tj_max,
            unit=SpecUnit(verbatim="°C", canonical="°C"), page=6,
            confidence=Confidence.HIGH,
        ),
        SpecRecord(
            id="rec_2",
            section="4.3", table_index=0, row_index=1, symbol="VDD1P8",
            name="1.8V supply", min="1.75", typ="1.8",
            unit=SpecUnit(verbatim="V", canonical="V"), page=6,
            confidence=Confidence.MEDIUM,
        ),
    ]
    if only_spec:
        records.append(
            SpecRecord(
                id="rec_3",
                section="4.3", table_index=0, row_index=2, symbol=only_spec,
                name="Second band supply", typ="0.9",
                unit=SpecUnit(verbatim="V", canonical="V"), page=6,
                confidence=Confidence.MEDIUM,
            )
        )
    return SpecSet(
        schema_version="5", part_number=part, doc_hash=doc_hash, records=records
    )


def _pins(part: str, doc_hash: str, *, pin_name: str, only_pin: str) -> PinSet:
    pins = [
        PinRecord(
            id="pin_1", pin="A1", pin_verbatim="A1", name=pin_name,
            type=PinType.GROUND, type_evidence="ground", direction="—",
            description="Analog ground", section="4.3", page=6,
            row_verbatim=["A1", pin_name, "—", "Analog ground"],
            confidence=Confidence.HIGH,
        ),
    ]
    if only_pin:
        pins.append(
            PinRecord(
                id="pin_2", pin=only_pin, pin_verbatim=only_pin, name="VDD0P9",
                type=PinType.POWER, type_evidence="supply", direction="I",
                description="0.9 V supply input", section="4.3", page=6,
                row_verbatim=[only_pin, "VDD0P9", "I", "0.9 V supply input"],
                confidence=Confidence.MEDIUM,
            )
        )
    return PinSet(
        schema_version="1", part_number=part, doc_hash=doc_hash, pins=pins,
        stated_count=len(pins),
    )


def _registers(
    part: str, doc_hash: str, *, reset: str, field_bits: str, field_hi: int,
    field_lo: int,
) -> RegisterSet:
    return RegisterSet(
        schema_version="2",
        part_number=part,
        doc_hash=doc_hash,
        registers=[
            RegisterRecord(
                id="reg_1", address=RegisterWord(verbatim="0x19", value=25),
                name="R25", description="Clock mux control", section="4.3", page=6,
                confidence=Confidence.HIGH,
                reset=RegisterWord(
                    verbatim=reset, value=int(reset, 16), page=6,
                    evidence=f"R25 Register (Offset = 0x19) [Reset = {reset}]",
                    derivation="declaration_heading",
                ),
                width=16, width_evidence=reset, width_derivation="register_width",
                fields=[
                    RegisterField(
                        name="CLK_MUX",
                        bits=BitRange(
                            verbatim=field_bits, hi=field_hi, lo=field_lo,
                            derivation="parse_bit_range",
                        ),
                        access="R/W", reset="0x1", description="Clock mux select",
                        page=6,
                    )
                ],
                fields_confidence=Confidence.HIGH,
            ),
        ],
        n_reset_stated=1,
        n_field_sets=1,
    )


def family_settings(tmp_path: Path, **kwargs) -> Settings:
    """Two members under one parts dir, plus a registry dir a test may write to."""
    build_member(tmp_path / "parts" / "TEST9950")
    build_member(tmp_path / "parts" / "TEST9953", **kwargs)
    registry = tmp_path / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    return Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        projects_dir=tmp_path / "projects",
        families_dir=tmp_path / "families",
        registry_dir=registry,
    ).resolve()
