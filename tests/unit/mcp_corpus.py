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

from datasheet_analyzer.config import (
    PINS_SCHEMA_VERSION,
    PIPELINE_VERSION,
    REGISTERS_SCHEMA_VERSION,
    Settings,
)
from datasheet_analyzer.derive.pins import write_pinset
from datasheet_analyzer.derive.registers import write_registerset
from datasheet_analyzer.families.registry import (
    FamilyEntry,
    FamilyRegistry,
    families_path,
    save_families,
)
from datasheet_analyzer.models import (
    Confidence,
    DocType,
    PinRecord,
    PinSet,
    PlotRecord,
    PlotSet,
    Project,
    ProjectMember,
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
from datasheet_analyzer.projects import save_project, write_project_index
from datasheet_analyzer.publish import write_corpus
from datasheet_analyzer.structure.corpus import build_section_plans

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
    return SpecSet(
        schema_version="2",
        part_number=part,
        doc_hash=DOC_HASH,
        records=[
            SpecRecord(
                section="4.3",
                table_index=0,
                row_index=0,
                symbol="TJ",
                name="Operating junction temperature",
                max="105",
                unit=SpecUnit(verbatim="°C", canonical="°C"),
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
            SpecRecord(
                section="4.5",
                table_index=0,
                row_index=0,
                symbol="DACRES",
                name="DAC resolution",
                typ="14",
                unit=SpecUnit(verbatim="bits", canonical="bits"),
                page=7,
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
            PlotRecord(
                id="4.12.1-f001",
                section="4.12.1",
                caption="Figure 4-1 TX Output Fullscale vs Output Frequency",
                conditions="DSA = 0",
                page_start=29,
                page_end=29,
                file=FIGURE,
                tags=["tx", "fullscale"],
                confidence=Confidence.HIGH,
                # The axis catalog of ticket 08, as the annotator writes it:
                # both axes read, so `axis_confidence` is `high` and the
                # `find_plots` axis filters have something to narrow on.
                x_label="Output Frequency",
                x_unit="MHz",
                x_min=600.0,
                x_max=1500.0,
                y_label="Output Full Scale",
                y_unit="dBm",
                y_min=-2.0,
                y_max=7.0,
                axis_confidence=Confidence.HIGH,
            ),
            PlotRecord(
                id="4.12.1-f002",
                section="4.12.1",
                caption="Figure 4-2 TX Calibrated Gain Error vs DSA Setting",
                page_start=30,
                page_end=30,
                tags=["tx"],
                confidence=Confidence.MEDIUM,
            ),
        ],
    )


def _pins(part: str) -> PinSet:
    """A small, structurally real pin table (phase 6, ticket 04's shape).

    Two ground pins and one supply, so a type filter has something to filter
    and a designator lookup has a neighbour to not match.
    """
    return PinSet(
        schema_version=PINS_SCHEMA_VERSION,
        part_number=part,
        doc_hash=DOC_HASH,
        pins=[
            PinRecord(
                pin="A1",
                name="VSSA",
                type="ground",
                direction="—",
                description="Analog ground",
                section="4.3",
                table_index=2,
                row_index=0,
                page=6,
                type_evidence="name:*vss*",
                confidence=Confidence.HIGH,
            ),
            PinRecord(
                pin="A2",
                name="VSSA",
                type="ground",
                direction="—",
                description="Analog ground",
                section="4.3",
                table_index=2,
                row_index=0,
                page=6,
                expanded_from="A1, A2",
                type_evidence="name:*vss*",
                confidence=Confidence.HIGH,
            ),
            PinRecord(
                pin="B1",
                name="VDD1P8",
                type="power",
                direction="I",
                description="1.8 V supply",
                section="4.3",
                table_index=2,
                row_index=1,
                page=6,
                type_evidence="name:*vdd*",
                confidence=Confidence.MEDIUM,
            ),
        ],
        declared_pin_count=3,
    )


def _registers(part: str) -> RegisterSet:
    """One register summary row, addressable by value or by printed form."""
    return RegisterSet(
        schema_version=REGISTERS_SCHEMA_VERSION,
        part_number=part,
        doc_hash=DOC_HASH,
        registers=[
            RegisterRecord(
                name="TXDIG_CTRL0",
                address=RegisterValue(verbatim="0x1A04", value=6660),
                reset=RegisterValue(verbatim="0x00", value=0),
                access="R/W",
                width=8,
                section="4.5",
                table_index=0,
                row_index=0,
                page=7,
                confidence=Confidence.HIGH,
            ),
        ],
    )


def build_part(part_dir: Path, *, with_figure: bool = True) -> Path:
    """A structurally real corpus: sections, specs, plots, search index."""
    part = part_dir.name
    source = SourceDocument(
        content_hash=DOC_HASH,
        path="pdfs/afe7950.pdf",
        part_number=part,
        doc_type=DocType.DATASHEET,
        revision="SBASA41E",
        page_count=146,
    )
    raw = RawDocument(
        source=source,
        sections=_sections(),
        extractor="ti_html",
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
    )
    # The derived device tables (phase 6) are written beside the document's
    # other artifacts, exactly as `pipeline.build_part` writes them.
    write_pinset(part_dir / "docs" / DOC, _pins(part))
    write_registerset(part_dir / "docs" / DOC, _registers(part))
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
    # One declared family over the same two parts (phase 7, ticket 07). It is
    # written into the *tmp* registry, never the packaged one, for the reason
    # `registry_dir` is redirected at all: a test may not read or rewrite the
    # families this repository ships. Both members are built, so the family
    # tools exercise a real index rather than a refusal.
    save_families(
        FamilyRegistry(
            families={
                "TESTx": FamilyEntry(
                    name="TESTx",
                    title="TEST-series fixture devices",
                    members=["TEST", "OTHER"],
                    note="fixture family: two corpora built from the same template",
                    confirmed=True,
                )
            }
        ),
        families_path(resolved.registry_dir),
    )
    return resolved


def empty_settings(tmp_path: Path) -> Settings:
    """Settings for a machine where nothing has been built yet."""
    return Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        projects_dir=tmp_path / "projects",
        families_dir=tmp_path / "families",
        # The *document* registry only (phase 7, ticket 01) - the alias, card,
        # pin-type and device-table lexicons always read the packaged
        # directory. Pointed at tmp so `dsa fetch` and `dsa check-revisions`
        # can never read or rewrite the registry checked into this repo.
        registry_dir=tmp_path / "registry",
    ).resolve()
