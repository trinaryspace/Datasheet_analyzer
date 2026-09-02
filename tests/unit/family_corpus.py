"""Two corpora that differ in exactly the ways a family index must notice.

Not a test module - a fixture factory, like `mcp_corpus.py` beside it. That one
builds *one* shape for the MCP surface; a family needs several, differing one
axis at a time, because every claim the family index makes is a claim about a
difference:

- a section identical in both members (shared, listed once);
- a section whose body differs by exactly one printed value (divergent);
- a section one member does not print at all (partial);
- a section both print under different numbers and the same title (renumbered);
- a spec row both print with different values (a delta, with an SI number);
- a spec row only one member prints (only in one member);
- a pin whose printed name moved, and one only one member prints;
- a register whose printed reset moved, and a bit field whose range moved.

Every knob is a printed cell, and every default is "the members agree", so a
test that flips one knob is testing exactly one rule.
"""

from __future__ import annotations

from pathlib import Path

from datasheet_analyzer.config import (
    PINS_SCHEMA_VERSION,
    PIPELINE_VERSION,
    REGISTERS_SCHEMA_VERSION,
    SPECS_SCHEMA_VERSION,
    Settings,
)
from datasheet_analyzer.derive.pins import write_pinset
from datasheet_analyzer.derive.registers import write_registerset
from datasheet_analyzer.models import (
    BitField,
    BitRange,
    Confidence,
    DocType,
    PinRecord,
    PinSet,
    PlotSet,
    RawDocument,
    RegisterRecord,
    RegisterSet,
    RegisterValue,
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
    thermal_body: str = "The junction-to-ambient thermal resistance is 12.3 degC/W.",
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
    reference members differ on out of the box (105 against 125 degC), which is
    the delta a family index exists to tabulate.
    """
    part_dir.mkdir(parents=True, exist_ok=True)
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
        specsets=[_specs(part, doc_hash, tj_max=tj_max, only_spec=only_spec)],
        plotsets=[PlotSet(schema_version="3", part_number=part, doc_hash=doc_hash)],
    )
    docs = part_dir / "docs" / doc_dir(part)
    write_pinset(docs, _pins(part, doc_hash, pin_name=pin_name, only_pin=only_pin))
    write_registerset(
        docs,
        _registers(
            part,
            doc_hash,
            reset=reset,
            field_bits=field_bits,
            field_hi=field_hi,
            field_lo=field_lo,
        ),
    )
    return part_dir


def _specs(part: str, doc_hash: str, *, tj_max: str, only_spec: str) -> SpecSet:
    records = [
        SpecRecord(
            section="4.3",
            table_index=0,
            row_index=0,
            symbol="TJ",
            name="Operating junction temperature",
            max=tj_max,
            unit=SpecUnit(verbatim="degC", canonical="degC"),
            page=6,
            confidence=Confidence.HIGH,
        ),
        SpecRecord(
            section="4.3",
            table_index=0,
            row_index=1,
            symbol="VDD1P8",
            name="1.8V supply",
            min="1.75",
            typ="1.8",
            unit=SpecUnit(verbatim="V", canonical="V"),
            page=6,
            confidence=Confidence.MEDIUM,
        ),
    ]
    if only_spec:
        records.append(
            SpecRecord(
                section="4.3",
                table_index=0,
                row_index=2,
                symbol=only_spec,
                name="Second band supply",
                typ="0.9",
                unit=SpecUnit(verbatim="V", canonical="V"),
                page=6,
                confidence=Confidence.MEDIUM,
            )
        )
    return SpecSet(
        schema_version=SPECS_SCHEMA_VERSION,
        part_number=part,
        doc_hash=doc_hash,
        records=records,
    )


def _pins(part: str, doc_hash: str, *, pin_name: str, only_pin: str) -> PinSet:
    pins = [
        PinRecord(
            pin="A1",
            name=pin_name,
            type="ground",
            direction="-",
            description="Analog ground",
            section="4.3",
            table_index=2,
            row_index=0,
            page=6,
            type_evidence="name:*vss*",
            confidence=Confidence.HIGH,
        ),
    ]
    if only_pin:
        pins.append(
            PinRecord(
                pin=only_pin,
                name="VDD0P9",
                type="power",
                direction="I",
                description="0.9 V supply input",
                section="4.3",
                table_index=2,
                row_index=1,
                page=6,
                type_evidence="name:*vdd*",
                confidence=Confidence.MEDIUM,
            )
        )
    return PinSet(
        schema_version=PINS_SCHEMA_VERSION,
        part_number=part,
        doc_hash=doc_hash,
        pins=pins,
        declared_pin_count=len(pins),
    )


def _registers(
    part: str,
    doc_hash: str,
    *,
    reset: str,
    field_bits: str,
    field_hi: int,
    field_lo: int,
) -> RegisterSet:
    return RegisterSet(
        schema_version=REGISTERS_SCHEMA_VERSION,
        part_number=part,
        doc_hash=doc_hash,
        registers=[
            RegisterRecord(
                name="R25",
                address=RegisterValue(verbatim="0x19", value=25),
                reset=RegisterValue(verbatim=reset, value=int(reset, 16)),
                access="R/W",
                width=16,
                section="4.3",
                table_index=0,
                row_index=0,
                doc_key=doc_hash[:8],
                page=6,
                confidence=Confidence.HIGH,
                fields=[
                    BitField(
                        name="CLK_MUX",
                        bits=BitRange(verbatim=field_bits, hi=field_hi, lo=field_lo),
                        access="R/W",
                        reset="0x1",
                        description="Clock mux select",
                        page=6,
                        confidence=Confidence.HIGH,
                    )
                ],
            ),
        ],
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
