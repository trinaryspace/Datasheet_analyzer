"""The built corpus the two MCP test modules share (Phase 5, ticket 07).

Not a test module — a fixture factory. It lives on its own because the MCP
surface is tested from two sides and only one of them may import the SDK:

- `test_mcp_responses.py` — the SDK-free half (the declared schemas, the
  path-safety refusal, the install hint). Runs on a **core** install.
- `test_mcp_server.py` — the session-driven half, behind
  `pytest.importorskip("mcp")`.

Both need the same structurally real corpus, and duplicating it would let the
two halves drift apart about what they are testing against.
"""

from __future__ import annotations

from pathlib import Path

from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.models import (
    AxisScale,
    BitRange,
    Confidence,
    DocType,
    PinRecord,
    PinSet,
    PinType,
    PlotRecord,
    PlotSet,
    Project,
    ProjectMember,
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
from datasheet_analyzer.projects import save_project, write_project_index
from datasheet_analyzer.publish import write_corpus
from datasheet_analyzer.structure.corpus import build_section_plans
from datasheet_analyzer.structure.plot_axes import DERIVATION as AXIS_DERIVATION

DOC_HASH = "a1b2c3d4" + "0" * 56
DOC = f"datasheet-{DOC_HASH[:8]}"
FIGURE = f"docs/{DOC}/figures/4.12.1-f001.png"
#: A real 1x1 PNG — small enough to commit inline, valid enough that the
#: content block a client receives is genuinely an image.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def _sections() -> list[SectionNode]:
    return [
        SectionNode(
            number="4.3",
            title="Recommended Operating Conditions",
            page_start=6,
            page_end=6,
            paragraphs=[
                "Operating junction temperature TJ ranges from -40 to 105 °C.",
                "The 1.2 V rails accept 1.15 V minimum on every supply pin.",
            ],
        ),
        SectionNode(
            number="4.5",
            title="Transmitter Electrical Characteristics",
            page_start=7,
            page_end=8,
            paragraphs=[
                (
                    "SYSREF setup time must be met for deterministic latency. "
                    "The SYSREF capture window is programmable per converter."
                ),
                "The transmit DAC resolution is 14 bits across every channel.",
            ],
        ),
    ]


def _specs(part: str) -> SpecSet:
    """The document's spec records, addressable and part-dependent in one cell.

    Every record carries the stable id `structure/specs.py` mints (ADR 0005), so
    a derived artifact built over this corpus can cite it — a record with no id
    is honestly unaddressable and no card or comparison may publish it.

    The two built parts print the **same** table except for one value: TEST is
    rated to 105 °C and OTHER to 125 °C. That one difference is what gives the
    cross-part comparison (phase 6, ticket 09) something real to subtract, and
    keeping the rest identical keeps every other test reading the same corpus it
    always did.
    """
    return SpecSet(
        schema_version="2",
        part_number=part,
        doc_hash=DOC_HASH,
        records=[
            SpecRecord(
                id="rec_1",
                section="4.3", table_index=0, row_index=0, symbol="TJ",
                name="Operating junction temperature",
                max="125" if part == "OTHER" else "105",
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
            SpecRecord(
                id="rec_3",
                section="4.5", table_index=0, row_index=0, symbol="DACRES",
                name="DAC resolution", typ="14",
                unit=SpecUnit(verbatim="bits", canonical="bits"), page=7,
                confidence=Confidence.LOW,
            ),
        ],
    )


def _plots(part: str) -> PlotSet:
    return PlotSet(
        schema_version="2",
        part_number=part,
        doc_hash=DOC_HASH,
        plots=[
            # One figure carries an axis catalog and one does not (phase 6,
            # ticket 08), which is the pair every axis filter must separate and
            # the pair that exercises both branches of
            # `PlotHit.as_dict()["axes"]` — the block and the honest `null`.
            # Figure 4-1 is the raster case: a precisely cited figure whose plot
            # is pixels, so its own grade stays `high` while its axis grade is
            # `low`. The two grades are independent on purpose.
            PlotRecord(
                id="4.12.1-f001", section="4.12.1",
                caption="Figure 4-1 TX Output Fullscale vs Output Frequency",
                conditions="DSA = 0", page_start=29, page_end=29, file=FIGURE,
                tags=["tx", "fullscale"], confidence=Confidence.HIGH,
                axis_confidence=Confidence.LOW,
            ),
            # Figure 4-2's axes are AFE7950's own p.29 vocabulary: the DSA sweep
            # printed `DSA (dB)` 0…40 against a gain-error axis in dB.
            PlotRecord(
                id="4.12.1-f002", section="4.12.1",
                caption="Figure 4-2 TX Calibrated Gain Error vs DSA Setting",
                page_start=30, page_end=30, tags=["tx"],
                confidence=Confidence.MEDIUM,
                x_label="DSA", x_unit="dB",
                x_min=0.0, x_max=40.0, x_scale=AxisScale.LINEAR,
                y_label="Gain Error", y_unit="dB",
                y_min=-0.5, y_max=0.5, y_scale=AxisScale.LINEAR,
                axis_confidence=Confidence.HIGH, axis_page=30,
                axis_derivation=AXIS_DERIVATION,
            ),
        ],
    )


def _pins(part: str) -> PinSet:
    """A three-pin table: one ground, one supply, one clock (ticket 10).

    Small on purpose and shaped for the two things a pin lookup must separate —
    an exact designator (`A1` is not `A10`) and a lexicon **type** (`ground`) —
    with `type_evidence` on every classified record, because `type` is the one
    derived field a pin has and invariant 8 says a derived value names its rule.
    `B1` is deliberately typed `unknown` with no evidence: a pin the lexicon did
    not understand must never read as a supply.
    """
    return PinSet(
        schema_version="1",
        part_number=part,
        doc_hash=DOC_HASH,
        pins=[
            PinRecord(
                id="pin_1", pin="A1", pin_verbatim="A1, A10", name="VSSA",
                type=PinType.GROUND, type_evidence="ground", direction="—",
                description="Analog ground", section="4.3", page=6,
                row_verbatim=["A1, A10", "VSSA", "—", "Analog ground"],
                confidence=Confidence.HIGH,
            ),
            PinRecord(
                id="pin_2", pin="A10", pin_verbatim="A1, A10", name="VSSA",
                type=PinType.GROUND, type_evidence="ground", direction="—",
                description="Analog ground", section="4.3", page=6,
                row_verbatim=["A1, A10", "VSSA", "—", "Analog ground"],
                confidence=Confidence.HIGH,
            ),
            PinRecord(
                id="pin_3", pin="B1", pin_verbatim="B1", name="VDD1P8",
                type=PinType.POWER, type_evidence="1.8v supply", direction="I",
                description="1.8 V supply input", section="4.3", page=6,
                row_verbatim=["B1", "VDD1P8", "I", "1.8 V supply input"],
                confidence=Confidence.MEDIUM,
            ),
        ],
        stated_count=3,
    )


def _registers(part: str) -> RegisterSet:
    """A two-register map, one of them carrying a validated bit-field set.

    R25 states a reset and publishes fields; R0 states neither, which is the
    pair every honesty rule here needs: `reset: null` rather than a plausible
    zero, and a `fields_reason` a caller can tell apart from "this device has no
    such field".
    """
    return RegisterSet(
        schema_version="2",
        part_number=part,
        doc_hash=DOC_HASH,
        registers=[
            RegisterRecord(
                id="reg_1", address=RegisterWord(verbatim="0x00", value=0),
                name="R0", description="Soft reset", section="4.3", page=6,
                confidence=Confidence.HIGH,
                fields_reason="no field table is printed for this register",
                fields_confidence=Confidence.UNKNOWN,
            ),
            RegisterRecord(
                id="reg_2", address=RegisterWord(verbatim="0x19", value=25),
                name="R25", description="Clock mux control", section="4.3", page=6,
                confidence=Confidence.HIGH,
                reset=RegisterWord(
                    verbatim="0x0211", value=529, page=6,
                    evidence="R25 Register (Offset = 0x19) [Reset = 0x0211]",
                    derivation="declaration_heading",
                ),
                width=16, width_evidence="0x0211", width_derivation="register_width",
                fields=[
                    RegisterField(
                        name="CLK_MUX",
                        bits=BitRange(verbatim="2:0", hi=2, lo=0,
                                      derivation="parse_bit_range"),
                        access="R/W", reset="0x1", description="Clock mux select",
                        page=6,
                    )
                ],
                unaccounted_bits=["15:3"],
                fields_route="column",
                fields_confidence=Confidence.MEDIUM,
            ),
        ],
        n_reset_stated=1,
        n_field_sets=1,
    )


def build_part(
    part_dir: Path, *, with_figure: bool = True, with_device_tables: bool = True
) -> Path:
    """A structurally real corpus: sections, specs, plots, pins, registers, index.

    `with_device_tables=False` is the part whose datasheet prints no pin table
    and no register map — the case a pin or register lookup must refuse rather
    than answer with an empty list, since the corpus never looked.
    """
    part = part_dir.name
    source = SourceDocument(
        content_hash=DOC_HASH, path="pdfs/afe7950.pdf", part_number=part,
        doc_type=DocType.DATASHEET, revision="SBASA41E", page_count=146,
    )
    raw = RawDocument(
        source=source, sections=_sections(), extractor="ti_html",
        extractor_version="test-1",
    )
    write_corpus(
        part_dir,
        [(raw, build_section_plans(raw), {})],
        f"# {part}\n\nSections: 4.3 Recommended Operating Conditions, 4.5 "
        "Transmitter Electrical Characteristics.\n",
        pipeline_version=PIPELINE_VERSION,
        vendor="ti",
        specsets=[_specs(part)],
        plotsets=[_plots(part)],
        pinsets=[_pins(part)] if with_device_tables else None,
        registersets=[_registers(part)] if with_device_tables else None,
    )
    if with_figure:
        figures = part_dir / "docs" / DOC / "figures"
        figures.mkdir(parents=True, exist_ok=True)
        (figures / "4.12.1-f001.png").write_bytes(PNG_BYTES)
    return part_dir


def built_settings(tmp_path: Path) -> Settings:
    """Settings pointed at two built parts and one project over both."""
    build_part(tmp_path / "parts" / "TEST")
    build_part(tmp_path / "parts" / "OTHER")
    resolved = empty_settings(tmp_path)
    project = Project(
        name="rf-frontend",
        parts=[
            ProjectMember(part_number="TEST", role="quad RF transceiver"),
            ProjectMember(part_number="OTHER", role="digital step attenuator"),
        ],
        interfaces="TEST TX -> OTHER DSA",
    )
    save_project(project, resolved.projects_dir)
    write_project_index(
        project,
        parts_dir=resolved.parts_dir,
        projects_dir=resolved.projects_dir,
        token_budget=resolved.project_index_token_budget,
    )
    return resolved


def empty_settings(tmp_path: Path) -> Settings:
    """Settings for a machine where nothing has been built yet."""
    return Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        projects_dir=tmp_path / "projects",
    ).resolve()
