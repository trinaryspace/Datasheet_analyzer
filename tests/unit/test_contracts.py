"""The frozen contracts: models, settings, the HTTP surface, the stub seams.

Twenty-one tickets are written in parallel against what this ticket froze, so
these tests guard the *shape* of that surface rather than any behaviour:
field sets and defaults, the endpoint table's models, the exact signature of
every stubbed function, and the TypeScript mirror's exported names.

Two things here are load-bearing beyond their size:

- **`SourceDocument` must not change shape.** It is embedded in
  `RawDocument`, which is serialized into
  `.cache/extract/<hash>__<backend>.json`. A new required field there
  invalidates every cached extraction in every checkout, which is why
  applicability and labels live on `LibraryDocument` instead.
- **A stub's signature is the contract, not its body.** The
  `NotImplementedError` assertions detect a still-unimplemented stub from its
  own AST and skip a function its owning ticket has since filled in, so this
  file does not have to be rewritten as waves land.

Hermetic: no network, no LLM, no browser. The one subprocess is `npm run
typecheck` against the already-installed `web/node_modules`, skipped when the
scaffold has not been installed.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
import subprocess
import sys
import textwrap
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from datasheet_analyzer import models as models_module
from datasheet_analyzer.app import contracts
from datasheet_analyzer.app.contracts import (
    ChatEvent,
    DocProposal,
    ErrorOut,
    JobEvent,
    LibraryDocumentOut,
    LibraryOut,
    LibraryPatchIn,
    LocateOut,
    LocateQuery,
    MessageIn,
    PartOut,
    PartsOut,
    ProjectOut,
    ProjectPartOut,
    ProjectsOut,
    RectOut,
    ResolveIn,
    RunSnapshot,
    ScanIn,
    ScanOut,
    ScopeResolution,
    SessionCreateIn,
    SessionOut,
    SessionsOut,
    SessionSummary,
    StartIn,
    StartOut,
)
from datasheet_analyzer.config import (
    LIBRARY_SCHEMA_VERSION,
    PLOTS_SCHEMA_VERSION,
    Settings,
)
from datasheet_analyzer.models import (
    AnalyzeJob,
    Applicability,
    ChatMessage,
    ChatSession,
    CitationOut,
    DocType,
    JobState,
    LibraryDocument,
    RawDocument,
    ScopeRef,
    SourceDocument,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "web"
ROUTERS_DIR = REPO_ROOT / "src" / "datasheet_analyzer" / "app" / "routers"


# --- models -------------------------------------------------------------------


def _round_trip(model: BaseModel) -> BaseModel:
    """Serialize the way the API does and read it back — the real round trip."""
    return type(model).model_validate_json(model.model_dump_json())


def test_new_models_exist_and_round_trip():
    """Every model ticket 00 froze survives `model_dump_json` -> validation."""
    applicability = Applicability(
        kind="parts", parts=["AD9081"], evidence="title block, p.1: AD9081"
    )
    source = SourceDocument(content_hash="a" * 64, path="ad9081.pdf", part_number="AD9081")
    document = LibraryDocument(
        source=source,
        applicability=applicability,
        labels=["reviewed", "jesd204"],
        added_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        schema_version=LIBRARY_SCHEMA_VERSION,
    )
    job = AnalyzeJob(
        id="job-1",
        pdf_path="shelf/ad9081.pdf",
        part_number="AD9081",
        applicability=applicability,
        state=JobState.PUBLISHING,
    )
    citation = CitationOut(
        doc="datasheet-a1b2c3d4",
        doc_hash="a" * 64,
        section="4.5",
        page_start=7,
        page_end=7,
        part="AD9081",
        pages="p.7",
        label="§4.5, p.7",
    )
    message = ChatMessage(role="assistant", text="1.4 V maximum.", citations=[citation])
    session = ChatSession(
        id="s-1",
        title="AD9081 supply limits",
        scope=ScopeRef(kind="part", name="AD9081"),
        messages=[message],
    )

    for model in (applicability, document, job, message, session):
        assert _round_trip(model) == model

    assert _round_trip(document).labels == ["reviewed", "jesd204"]
    assert _round_trip(session).messages[0].citations[0].label == "§4.5, p.7"
    assert _round_trip(job).state is JobState.PUBLISHING


def test_job_state_values_and_terminality():
    """The eight states, their wire values, and which of them end a job."""
    assert [state.value for state in JobState] == [
        "queued",
        "extracting",
        "structuring",
        "enriching",
        "publishing",
        "done",
        "failed",
        "skipped",
    ]
    assert [s.value for s in models_module.JOB_STAGE_ORDER] == [
        "queued",
        "extracting",
        "structuring",
        "enriching",
        "publishing",
    ]
    assert set(models_module.JOB_TERMINAL_STATES) == {
        JobState.DONE,
        JobState.FAILED,
        JobState.SKIPPED,
    }
    assert JobState.DONE.terminal and JobState.FAILED.terminal and JobState.SKIPPED.terminal
    assert not JobState.EXTRACTING.terminal


def test_library_document_defaults_are_the_honest_ones():
    """A document registered with nothing said about it applies to everything."""
    document = LibraryDocument(source=SourceDocument(content_hash="b" * 64, path="note.pdf"))
    assert document.applicability.kind == "all"
    assert document.labels == []
    assert document.content_hash == "b" * 64
    assert document.filename == "note.pdf"
    assert isinstance(document.added_at, datetime)


def test_library_document_filename_handles_both_separators():
    """`SourceDocument.path` is whatever string the CLI was handed."""
    windows = LibraryDocument(
        source=SourceDocument(content_hash="c" * 64, path=r"C:\shelf\ad9081.pdf")
    )
    posix = LibraryDocument(source=SourceDocument(content_hash="d" * 64, path="/shelf/lm741.pdf"))
    assert windows.filename == "ad9081.pdf"
    assert posix.filename == "lm741.pdf"


# --- the hard constraint: SourceDocument has not moved ------------------------

#: `SourceDocument`'s field set as every `.cache/extract/*.json` on every
#: machine already carries it. Adding a field here is a cache-invalidating
#: change and must not happen for applicability or labels — those live on
#: `LibraryDocument`.
FROZEN_SOURCE_DOCUMENT_FIELDS = {
    "content_hash",
    "path",
    "part_number",
    "doc_type",
    "revision",
    "page_count",
    "nda",
    "vendor",
    "vendor_evidence",
    "registered_at",
}


def test_source_document_shape_is_unchanged():
    """No field added, none removed, and `content_hash` still the only required one."""
    assert set(SourceDocument.model_fields) == FROZEN_SOURCE_DOCUMENT_FIELDS
    required = {name for name, field in SourceDocument.model_fields.items() if field.is_required()}
    assert required == {"content_hash", "path"}
    assert not hasattr(SourceDocument, "applicability")
    assert "applicability" not in SourceDocument.model_fields
    assert "labels" not in SourceDocument.model_fields


def test_cached_extraction_still_deserializes(tmp_path: Path):
    """A `.cache/extract/<hash>__<backend>.json` written before this work loads.

    Hand-written rather than copied from `.cache/`, so the test is hermetic
    and still fails loudly the day `SourceDocument` grows a required field:
    this payload is exactly what the extractor wrote yesterday.
    """
    cached = {
        "source": {
            "content_hash": "e" * 64,
            "path": "ad9081.pdf",
            "part_number": "AD9081",
            "doc_type": "datasheet",
            "revision": "Rev. A",
            "page_count": 2,
            "nda": False,
            "vendor": "adi",
            "vendor_evidence": "brand match: Analog Devices",
            "registered_at": "2025-08-02T21:06:00+00:00",
        },
        "toc": [{"number": "4.1", "title": "Absolute Maximum Ratings", "level": 2, "page": 2}],
        "sections": [
            {
                "number": "4.1",
                "title": "Absolute Maximum Ratings",
                "level": 2,
                "page_start": 2,
                "page_end": 2,
                "paragraphs": ["VDD1P2 supply voltage 1.2 V"],
                "tables": [],
                "figures": [],
            }
        ],
        "extractor": "pdf_layout",
        "extractor_version": "tables-08",
        "extraction_stats": {
            "backend": "pdf_layout",
            "extractor_version": "tables-08",
            "tables_detected": 3,
            "tables_accepted": 3,
            "tables_rejected": 0,
            "rejection_reasons": [],
            "mean_fidelity": 0.97,
        },
        "extracted_at": "2025-08-02T21:06:01+00:00",
    }
    path = tmp_path / f"{'e' * 64}__pdf_layout.json"
    path.write_text(json.dumps(cached), encoding="utf-8")

    raw = RawDocument.model_validate_json(path.read_text(encoding="utf-8"))

    assert raw.source.content_hash == "e" * 64
    assert raw.source.doc_type is DocType.DATASHEET
    assert raw.extractor_version == "tables-08"
    assert raw.sections[0].page_start == 2


def test_pdf_layout_output_version_moves_only_on_a_deliberate_re_extraction():
    """It gates the whole extraction cache, so it changes on purpose or not at all.

    Highlighting derives geometry on demand precisely so this stays put.
    `tables-09` was phase 6.5's one permitted bump (wave 2, ticket 09).
    `tables-10` is the bit-field region fix: `_trim_outdented_tail` and the
    released bare-page-number cell both change what a table region contains,
    so every cached extraction of a PDF is stale and owns a re-extraction.
    Anything that moves it again owns the same rebuild.
    """
    from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend

    assert PdfLayoutBackend.output_version == "tables-10"


# --- applicability ------------------------------------------------------------


def test_covers_exact_part():
    applicability = Applicability(kind="parts", parts=["AD9081", "AD9082"])
    assert applicability.covers("AD9081")
    assert applicability.covers("ad9081"), "part numbers are printed both ways"
    assert not applicability.covers("AFE7950")


def test_covers_family_prefix_with_wildcards():
    """`AFE79xx` is the common case ADR 0005 exists for."""
    family = Applicability(kind="family", family="AFE79xx")
    assert family.covers("AFE7950")
    assert family.covers("AFE7952")
    assert family.covers("afe7950")
    assert family.covers("AFE7950A"), "a package suffix is still the same family"
    assert not family.covers("AFE795"), "the wildcard stands for a character, not for nothing"
    assert not family.covers("AD9081")

    single = Applicability(kind="family", family="AD90x1")
    assert single.covers("AD9081")
    assert single.covers("AD9091")
    assert not single.covers("AD9182")


def test_covers_all_parts():
    everything = Applicability(kind="all", evidence="fallback: no part token found")
    for part in ("AD9081", "AFE7950", "LM741", "QPA1003P"):
        assert everything.covers(part)
    assert not everything.covers(""), "a part is an identity; nothing applies to a nameless one"


def test_applicability_label_reads_like_a_human_wrote_it():
    assert Applicability(kind="parts", parts=["AD9081"]).label == "AD9081"
    assert Applicability(kind="parts", parts=["AD9081", "AD9082"]).label == "AD9081, AD9082"
    assert Applicability(kind="family", family="AFE79xx").label == "AFE79xx"
    assert Applicability(kind="all").label == "all parts"


def test_applicability_constructors_and_validity():
    assert Applicability.for_parts(["AD9081"], evidence="p.1").kind == "parts"
    assert Applicability.for_family("AFE79xx").family == "AFE79xx"
    assert Applicability.for_all().kind == "all"
    # The two shapes ticket 09 turns into a 400 rather than an inert write.
    assert not Applicability(kind="parts", parts=[]).is_valid
    assert not Applicability(kind="family", family="  ").is_valid
    assert Applicability(kind="all").is_valid


def test_applicability_kind_is_closed():
    with pytest.raises(ValidationError):
        Applicability(kind="everything")  # type: ignore[arg-type]


# --- settings -----------------------------------------------------------------

#: Every setting ticket 00 added: attribute, env var, default.
NEW_SETTINGS: list[tuple[str, str, Any]] = [
    ("library_dir", "DSA_LIBRARY_DIR", Path("library")),
    ("sessions_dir", "DSA_SESSIONS_DIR", Path("sessions")),
    ("chat_model", "DSA_CHAT_MODEL", "claude-opus-5"),
    ("chat_max_tokens", "DSA_CHAT_MAX_TOKENS", 16000),
    ("chat_tool_max_tokens", "DSA_CHAT_TOOL_MAX_TOKENS", 8000),
    ("serve_host", "DSA_SERVE_HOST", "127.0.0.1"),
    ("serve_port", "DSA_SERVE_PORT", 8765),
    ("analyze_workers", "DSA_ANALYZE_WORKERS", 4),
]


@pytest.mark.parametrize(("attr", "env", "default"), NEW_SETTINGS)
def test_setting_default(monkeypatch, attr: str, env: str, default: Any):
    monkeypatch.delenv(env, raising=False)
    assert getattr(Settings(), attr) == default


@pytest.mark.parametrize(("attr", "env", "default"), NEW_SETTINGS)
def test_setting_reads_its_env_var(monkeypatch, attr: str, env: str, default: Any):
    if isinstance(default, Path):
        override, expected = "custom-dir", Path("custom-dir")
    elif isinstance(default, bool):  # pragma: no cover - none yet, kept honest
        override, expected = "true", True
    elif isinstance(default, int):
        override, expected = "17", 17
    else:
        override, expected = "custom-value", "custom-value"
    monkeypatch.setenv(env, override)
    assert getattr(Settings(), attr) == expected


def test_serve_host_is_loopback_by_default(monkeypatch):
    """A local, single-user tool must not listen on every interface."""
    monkeypatch.delenv("DSA_SERVE_HOST", raising=False)
    assert Settings().serve_host == "127.0.0.1"


@pytest.mark.parametrize(
    ("env", "value"),
    [
        ("DSA_ANALYZE_WORKERS", "0"),
        ("DSA_CHAT_MAX_TOKENS", "0"),
        ("DSA_CHAT_TOOL_MAX_TOKENS", "0"),
        ("DSA_SERVE_PORT", "0"),
    ],
)
def test_bad_values_are_rejected_at_the_settings_boundary(monkeypatch, env: str, value: str):
    monkeypatch.setenv(env, value)
    with pytest.raises(ValidationError):
        Settings()


def test_resolve_absolutizes_the_two_new_directories(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    settings = Settings(library_dir=Path("library"), sessions_dir=Path("sessions")).resolve()
    assert settings.library_dir.is_absolute()
    assert settings.sessions_dir.is_absolute()
    assert settings.library_dir.name == "library"
    assert settings.sessions_dir.name == "sessions"
    # The three that were already absolutized still are.
    assert settings.parts_dir.is_absolute()
    assert settings.cache_dir.is_absolute()
    assert settings.projects_dir.is_absolute()


def test_schema_versions():
    assert PLOTS_SCHEMA_VERSION == "2"
    assert LIBRARY_SCHEMA_VERSION == "1"


# --- the HTTP surface ---------------------------------------------------------


def _table_models() -> set[str]:
    """Every `CamelCase` model named in the endpoint table in the docstring."""
    docstring = contracts.__doc__ or ""
    rows = [line for line in docstring.splitlines() if line.startswith("| ")]
    named: set[str] = set()
    for row in rows:
        for token in re.findall(r"`([A-Za-z][\w]*)`", row):
            if token[0].isupper():
                named.add(token)
    return named


def test_endpoint_table_names_only_models_that_exist():
    """The docstring table is the source of truth, so it may not name a ghost."""
    named = _table_models()
    assert named, "the endpoint table went missing from the module docstring"
    missing = sorted(name for name in named if not hasattr(contracts, name))
    assert missing == []


def test_every_endpoint_in_the_table_has_a_row():
    """The table documents every route the app actually mounts, and no more.

    Pinned against the running app rather than a hand-maintained count: the
    count drifts every time an endpoint is added and says nothing about
    *which* one is missing, whereas comparing the two sets names it. The table
    is the contract tickets 06-20 code against, so a route absent from it is
    undocumented and a row with no route is a promise nothing keeps.
    """
    from datasheet_analyzer.app.main import create_app

    docstring = contracts.__doc__ or ""
    documented = {path for path in re.findall(r"\| `(/api/[^`]+)` \|", docstring)}
    assert "/api/parts" in documented
    assert "/api/pdf/{content_hash}" in documented

    # The table abbreviates path parameters that FastAPI spells in full.
    aliases = {
        "/api/projects/{name}/parts/{part}": "/api/projects/{name}/parts/{part_number}",
        "/api/sessions/{id}": "/api/sessions/{session_id}",
        "/api/sessions/{id}/export": "/api/sessions/{session_id}/export",
        "/api/categories/{id}": "/api/categories/{category_id}",
        "/api/parts/{part}/category": "/api/parts/{part_number}/category",
    }
    documented = {aliases.get(path, path) for path in documented}
    mounted = {path for path in create_app().openapi()["paths"] if path.startswith("/api/")}

    assert sorted(mounted - documented) == [], "a mounted route is missing from the table"
    assert sorted(documented - mounted) == [], "the table promises a route that is not mounted"


#: One hand-written example per request/response model in the table.
CONTRACT_EXAMPLES: list[BaseModel] = [
    ErrorOut(detail="no such part: AD9081", kind="scope"),
    PartsOut(
        parts=[
            PartOut(
                part_number="AD9081",
                built=True,
                revision="Rev. A",
                vendor="adi",
                backends=["pdf_layout"],
                sections=42,
                specs=613,
                plots=100,
                tokens=180_000,
                searchable=True,
                spec_confidence={"high": 412, "medium": 190, "low": 11},
                plot_confidence={"high": 90, "low": 10},
            ),
            PartOut(part_number="AFE7952", built=False),
        ],
        count=2,
    ),
    ProjectsOut(
        projects=[
            ProjectOut(
                name="rx-frontend",
                parts=[ProjectPartOut(part_number="AD9081", role="the ADC", built=True)],
                interfaces="JESD204C, 8 lanes",
                notes="",
                built=True,
            )
        ],
        count=1,
    ),
    ScanIn(directory="C:/shelf"),
    ScanOut(
        directory="C:/shelf",
        proposals=[
            DocProposal(
                pdf_path="C:/shelf/sbas123e.pdf",
                filename="sbas123e.pdf",
                part_number="AFE7950",
                applicability=Applicability(
                    kind="family", family="AFE79xx", evidence="llm:claude-opus-5"
                ),
                evidence="title block, p.1: AFE7950 Quad RF Transceiver",
                page_count=412,
                doc_type="datasheet",
            )
        ],
        count=1,
    ),
    StartIn(
        directory="C:/shelf",
        proposals=[
            DocProposal(
                pdf_path="C:/shelf/ad9081.pdf",
                filename="ad9081.pdf",
                part_number="AD9081",
                applicability=Applicability.for_parts(["AD9081"], evidence="confirmed by user"),
                evidence="confirmed by user",
                page_count=204,
            )
        ],
    ),
    StartOut(run_id="run-7", n_jobs=3),
    JobEvent(
        run_id="run-7",
        job_id="job-1",
        part_number="AD9081",
        pdf_path="C:/shelf/ad9081.pdf",
        state=JobState.STRUCTURING,
        detail="42 sections",
    ),
    RunSnapshot(
        run_id="run-7",
        directory="C:/shelf",
        jobs=[AnalyzeJob(id="job-1", pdf_path="C:/shelf/ad9081.pdf", part_number="AD9081")],
        done=False,
    ),
    LibraryOut(
        documents=[
            LibraryDocumentOut(
                content_hash="f" * 64,
                path="C:/shelf/afe79xx-jesd.pdf",
                filename="afe79xx-jesd.pdf",
                part_number="AFE7950",
                doc_type="app_note",
                vendor="ti",
                page_count=18,
                applicability=Applicability(kind="family", family="AFE79xx", evidence="p.1"),
                labels=["reviewed"],
                parts_reached=["AFE7950", "AFE7952"],
                unbuilt_parts=["AFE7952"],
                rebuild_needed=["AFE7952"],
            )
        ],
        count=1,
        labels=["reviewed"],
    ),
    LibraryPatchIn(labels=["thermal"]),
    LibraryPatchIn(applicability=Applicability.for_parts(["AD9081"], evidence="hand-corrected")),
    ResolveIn(question="what is the maximum junction temperature of the AD9081?"),
    ScopeResolution(
        scope=ScopeRef(kind="part", name="AD9081"), confident=True, matched_via="exact-token"
    ),
    MessageIn(question="max TJ?", scope=ScopeRef(kind="part", name="AD9081")),
    ChatEvent.for_token("1.4 "),
    ChatEvent.for_tool("find_spec", "looking up TJ in AD9081"),
    SessionCreateIn(title="AD9081 supply limits", scope=ScopeRef(kind="part", name="AD9081")),
    SessionsOut(
        sessions=[
            SessionSummary(
                id="s-1",
                title="AD9081 supply limits",
                scope=ScopeRef(kind="part", name="AD9081"),
                n_messages=4,
            )
        ],
        count=1,
    ),
    SessionOut(
        id="s-1",
        title="AD9081 supply limits",
        scope=ScopeRef(kind="part", name="AD9081"),
        messages=[ChatMessage(role="user", text="max TJ?")],
        n_messages=1,
    ),
    LocateQuery(part="AD9081", doc_hash="f" * 64, page=47, needle="OPERATING JUNCTION TEMPERATURE"),
    LocateOut(
        found=True,
        page=47,
        rects=[RectOut(x0=72.0, y0=310.5, x1=523.2, y1=322.0)],
        needle="OPERATING JUNCTION TEMPERATURE",
        page_width=612.0,
        page_height=792.0,
    ),
]


@pytest.mark.parametrize("example", CONTRACT_EXAMPLES, ids=lambda e: type(e).__name__)
def test_contract_example_validates_and_round_trips(example: BaseModel):
    """Every request/response model validates a hand-written example."""
    assert _round_trip(example) == example
    dumped = example.model_dump(mode="json")
    assert isinstance(dumped, dict)
    assert type(example).model_validate(dumped) == example


def test_doc_proposal_is_importable_without_fastapi():
    """`acquire/applicability.py` returns one, and must work in a plain install."""
    source = Path(contracts.__file__).read_text(encoding="utf-8")
    assert "import fastapi" not in source
    assert "from fastapi" not in source


def test_scope_resolution_has_exactly_three_states():
    """Confident, ambiguous-with-candidates, and no-match — and no fourth."""
    confident = ScopeResolution(scope=ScopeRef(kind="part", name="AD9081"), confident=True)
    assert confident.confident and confident.candidates == [] and not confident.ambiguous

    ambiguous = ScopeResolution(
        candidates=[
            ScopeRef(kind="part", name="AFE7950"),
            ScopeRef(kind="part", name="AFE7952"),
        ],
        question="Which part did you mean?",
    )
    assert ambiguous.scope is None
    assert not ambiguous.confident
    assert ambiguous.ambiguous
    assert len(ambiguous.candidates) == 2

    no_match = ScopeResolution(question="Which part is this about?")
    assert no_match.scope is None
    assert not no_match.confident
    assert no_match.candidates == []
    assert not no_match.ambiguous
    assert no_match.question

    for resolution in (confident, ambiguous, no_match):
        assert _round_trip(resolution) == resolution


def test_locate_out_can_represent_an_honest_miss():
    """A box around the wrong row is worse than no box."""
    miss = LocateOut.miss("no distinctive text on p.47 matched the record", page=47)
    assert miss.found is False
    assert miss.rects == []
    assert miss.reason
    assert _round_trip(miss) == miss


def test_rect_is_documented_as_pdf_points():
    """Ticket 19 converts these; the origin has to be written down somewhere."""
    doc = RectOut.__doc__ or ""
    assert "PDF points" in doc
    assert "top-left" in doc
    rect = RectOut(x0=10.0, y0=20.0, x1=30.0, y1=25.0)
    assert rect.width == 20.0
    assert rect.height == 5.0


def test_chat_event_covers_every_frame_type():
    built = [
        ChatEvent.for_scope(ScopeResolution(scope=ScopeRef(name="AD9081"), confident=True)),
        ChatEvent.for_tool("search", "searching AD9081"),
        ChatEvent.for_token("1.4"),
        ChatEvent.for_citation(CitationOut(label="§4.5, p.7"), confidence="low"),
        ChatEvent.for_done(),
        ChatEvent.for_error("the model refused"),
    ]
    assert [event.type for event in built] == [
        "scope",
        "tool",
        "token",
        "citation",
        "done",
        "error",
    ]
    assert set(contracts.CHAT_EVENT_TYPES) == {event.type for event in built}
    for event in built:
        assert _round_trip(event) == event


def test_library_document_out_projects_a_stored_document():
    document = LibraryDocument(
        source=SourceDocument(
            content_hash="9" * 64,
            path="/shelf/afe79xx.pdf",
            part_number="AFE7950",
            doc_type=DocType.APP_NOTE,
            page_count=18,
        ),
        applicability=Applicability.for_family("AFE79xx", evidence="p.1"),
        labels=["reviewed"],
    )
    out = LibraryDocumentOut.from_document(
        document, parts_reached=["AFE7950", "AFE7952"], unbuilt_parts=["AFE7952"]
    )
    assert out.content_hash == "9" * 64
    assert out.filename == "afe79xx.pdf"
    assert out.doc_type == "app_note"
    assert out.labels == ["reviewed"]
    assert out.parts_reached == ["AFE7950", "AFE7952"]
    assert out.rebuild_needed == []


def test_session_out_projects_a_session():
    session = ChatSession(
        id="s-2",
        title="thermal",
        scope=ScopeRef(kind="project", name="rx-frontend"),
        messages=[ChatMessage(role="user", text="hi")],
    )
    out = SessionOut.from_session(session)
    assert out.n_messages == 1
    assert out.summary.scope.kind == "project"
    assert out.summary.id == "s-2"


def test_library_patch_distinguishes_omitted_from_cleared():
    """`labels: []` clears; an absent `labels` leaves them alone."""
    cleared = LibraryPatchIn.model_validate({"labels": []})
    untouched = LibraryPatchIn.model_validate({})
    assert cleared.labels == []
    assert untouched.labels is None
    assert untouched.applicability is None


# --- the stubbed seams --------------------------------------------------------


def _is_stub(func: Callable[..., Any]) -> bool:
    """True while the body is still `raise NotImplementedError`.

    Read off the function's own AST so this file survives its owning tickets
    filling the stubs in: an implemented function is skipped rather than
    asserted against.
    """
    try:
        source = textwrap.dedent(inspect.getsource(func))
    except OSError:  # pragma: no cover - source always available in-tree
        return False
    tree = ast.parse(source)
    node = tree.body[0]
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    body = [
        statement
        for statement in node.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Raise):
        return False
    exc = body[0].exc
    name = exc.func if isinstance(exc, ast.Call) else exc
    return isinstance(name, ast.Name) and name.id == "NotImplementedError"


def _frozen_seams() -> list[tuple[str, Callable[..., Any], dict[str, Any], list[str]]]:
    """`(label, callable, call kwargs, frozen parameter names)` for every seam."""
    from datasheet_analyzer.acquire import applicability as applicability_module
    from datasheet_analyzer.app import deps, locate, scope_resolver, sessions, tools
    from datasheet_analyzer.library import store as library_store

    library = library_store.LibraryStore(Path("library"))
    session_store = sessions.SessionStore(Path("sessions"))
    scope = ScopeRef(kind="part", name="AD9081")
    doc = LibraryDocument(source=SourceDocument(content_hash="0" * 64, path="x.pdf"))

    return [
        # library/store.py — ticket 01
        ("LibraryStore.for_settings", library_store.LibraryStore.for_settings, {}, ["settings"]),
        ("LibraryStore.get", library.get, {"content_hash": "0" * 64}, ["content_hash"]),
        ("LibraryStore.put", library.put, {"doc": doc}, ["doc"]),
        ("LibraryStore.all", library.all, {}, []),
        ("LibraryStore.for_part", library.for_part, {"part_number": "AD9081"}, ["part_number"]),
        (
            "LibraryStore.set_applicability",
            library.set_applicability,
            {"content_hash": "0" * 64, "applicability": Applicability()},
            ["content_hash", "applicability"],
        ),
        (
            "LibraryStore.set_labels",
            library.set_labels,
            {"content_hash": "0" * 64, "labels": ["reviewed"]},
            ["content_hash", "labels"],
        ),
        ("clear_library_cache", library_store.clear_library_cache, {}, []),
        # acquire/applicability.py — ticket 02
        (
            "applicability.infer",
            applicability_module.infer,
            {"pdf_path": Path("x.pdf"), "first_page_text": "AD9081", "known_parts": []},
            ["pdf_path", "first_page_text", "known_parts", "client"],
        ),
        # app/deps.py — ticket 06
        ("deps.get_settings_dep", deps.get_settings_dep, {}, []),
        ("deps.get_library", deps.get_library, {}, []),
        ("deps.get_retriever", deps.get_retriever, {"scope": scope}, ["scope"]),
        ("deps.get_job_registry", deps.get_job_registry, {}, []),
        ("deps.get_session_store", deps.get_session_store, {}, []),
        # app/scope_resolver.py — ticket 10
        (
            "scope_resolver.resolve",
            scope_resolver.resolve,
            {"question": "max TJ of the AD9081?", "parts": ["AD9081"], "projects": []},
            ["question", "parts", "projects"],
        ),
        # app/locate.py — ticket 13
        (
            "locate.locate",
            locate.locate,
            {"pdf_path": Path("x.pdf"), "page": 1, "needle": "TJ"},
            ["pdf_path", "page", "needle"],
        ),
        # app/tools.py — ticket 11
        ("tools.list_parts", tools.list_parts, {}, ["settings"]),
        ("tools.list_projects", tools.list_projects, {}, ["settings"]),
        ("tools.get_index", tools.get_index, {"scope": scope}, ["scope", "settings"]),
        (
            "tools.search",
            tools.search,
            {"scope": scope, "query": "sysref"},
            ["scope", "query", "limit", "settings"],
        ),
        (
            "tools.find_spec",
            tools.find_spec,
            {"scope": scope, "symbol": "TJ"},
            ["scope", "symbol", "name", "section", "settings"],
        ),
        (
            "tools.find_plots",
            tools.find_plots,
            {"scope": scope, "q": "phase noise"},
            ["scope", "q", "section", "tags", "settings"],
        ),
        (
            "tools.read_section",
            tools.read_section,
            {"scope": scope, "ref": "4.5"},
            ["scope", "ref", "max_tokens", "settings"],
        ),
        (
            "tools.get_figure",
            tools.get_figure,
            {"scope": scope, "file": "figures/f1.png"},
            ["scope", "file", "settings"],
        ),
        (
            "tools.ask",
            tools.ask,
            {"scope": scope, "question": "max TJ?"},
            ["scope", "question", "budget", "settings"],
        ),
        # app/sessions.py — ticket 15
        ("SessionStore.for_settings", sessions.SessionStore.for_settings, {}, ["settings"]),
        ("SessionStore.create", session_store.create, {"title": "t"}, ["title", "scope"]),
        ("SessionStore.get", session_store.get, {"session_id": "s-1"}, ["session_id"]),
        ("SessionStore.list", session_store.list, {}, []),
        (
            "SessionStore.append",
            session_store.append,
            {"session_id": "s-1", "message": ChatMessage(role="user", text="hi")},
            ["session_id", "message"],
        ),
        (
            "SessionStore.export_markdown",
            session_store.export_markdown,
            {"session_id": "s-1"},
            ["session_id"],
        ),
        (
            "SessionStore.export_golden",
            session_store.export_golden,
            {"session_id": "s-1"},
            ["session_id"],
        ),
    ]


SEAMS = _frozen_seams()


@pytest.mark.parametrize(
    ("label", "func", "kwargs", "params"), SEAMS, ids=[seam[0] for seam in SEAMS]
)
def test_frozen_signature(
    label: str, func: Callable[..., Any], kwargs: dict[str, Any], params: list[str]
):
    """Every frozen parameter is present, by name. Extras are allowed; losses are not."""
    signature = inspect.signature(func)
    missing = [name for name in params if name not in signature.parameters]
    assert missing == [], f"{label} lost frozen parameter(s) {missing}"


@pytest.mark.parametrize(
    ("label", "func", "kwargs", "params"), SEAMS, ids=[seam[0] for seam in SEAMS]
)
def test_stub_raises_not_implemented(
    label: str, func: Callable[..., Any], kwargs: dict[str, Any], params: list[str]
):
    """A stub raises `NotImplementedError`; an implemented seam is skipped."""
    if not _is_stub(func):
        pytest.skip(f"{label} has been implemented by its owning ticket")
    with pytest.raises(NotImplementedError):
        func(**kwargs)


def test_stub_modules_import_cleanly():
    """Twenty tickets import these on line one; none may need the others."""
    for name in (
        "datasheet_analyzer.app.contracts",
        "datasheet_analyzer.app.deps",
        "datasheet_analyzer.app.locate",
        "datasheet_analyzer.app.main",
        "datasheet_analyzer.app.scope_resolver",
        "datasheet_analyzer.app.sessions",
        "datasheet_analyzer.app.tools",
        "datasheet_analyzer.acquire.applicability",
        "datasheet_analyzer.library",
        "datasheet_analyzer.library.store",
    ):
        __import__(name)


def test_tool_surface_is_the_nine_mcp_tools():
    from datasheet_analyzer.app import tools

    assert tools.TOOL_NAMES == (
        "list_parts",
        "list_projects",
        "get_index",
        "search",
        "find_spec",
        "find_plots",
        "read_section",
        "get_figure",
        "ask",
    )
    assert set(tools.TOOLS) == set(tools.TOOL_NAMES)
    assert all(callable(tool) for tool in tools.TOOLS.values())
    assert set(tools.PART_ONLY_TOOLS) <= set(tools.TOOL_NAMES)


def test_app_tools_never_imports_the_mcp_server():
    """Two consumers with opposed token budgets; the shared logic is `retrieve/`."""
    from datasheet_analyzer.app import tools

    source = Path(tools.__file__).read_text(encoding="utf-8")
    assert "mcp_server" not in source.replace("`mcp_server/`", "")


def test_write_corpus_accepts_the_shared_docs_dir_keyword(tmp_path: Path):
    """Ticket 03 calls this before ticket 04 implements it; the keyword is frozen."""
    from datasheet_analyzer.publish.writer import write_corpus

    parameter = inspect.signature(write_corpus).parameters["shared_docs_dir"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None


# --- router auto-discovery ----------------------------------------------------

PROBE_ROUTER = '''\
"""Throwaway router dropped in by tests/unit/test_contracts.py."""

from fastapi import APIRouter

router = APIRouter()


@router.get("{path}")
def probe() -> dict:
    return {{"ok": True}}
'''


def _mounted_paths(app: Any) -> set[str]:
    """Every path the app actually serves.

    Read from the OpenAPI schema rather than `app.routes`: FastAPI includes a
    router lazily, so a freshly included group is one opaque `_IncludedRouter`
    entry until the schema (or a request) forces it open.
    """
    return set(app.openapi()["paths"])


def test_main_auto_discovers_a_router_dropped_into_the_package():
    """No later ticket edits `main.py`: a new endpoint group is a new file."""
    from fastapi.testclient import TestClient

    from datasheet_analyzer.app.main import create_app

    module_name = f"zzprobe{os.getpid()}"
    path = f"/api/_probe/{module_name}"
    probe = ROUTERS_DIR / f"{module_name}.py"
    probe.write_text(PROBE_ROUTER.format(path=path), encoding="utf-8")
    try:
        app = create_app()
        assert app.state.router_errors.get(module_name) is None
        assert path in _mounted_paths(app)
        response = TestClient(app).get(path)
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    finally:
        probe.unlink(missing_ok=True)
        sys.modules.pop(f"datasheet_analyzer.app.routers.{module_name}", None)

    # And it is gone again on the next build — discovery is a directory read,
    # not a registry that accumulates.
    assert path not in _mounted_paths(create_app())


def test_a_broken_router_does_not_take_the_application_down():
    """One half-written module is one broken endpoint group, not a dead server."""
    from datasheet_analyzer.app.main import create_app

    module_name = f"zzbroken{os.getpid()}"
    probe = ROUTERS_DIR / f"{module_name}.py"
    probe.write_text("raise RuntimeError('half-written')\n", encoding="utf-8")
    try:
        app = create_app()
        assert module_name in app.state.router_errors
        assert "RuntimeError" in app.state.router_errors[module_name]
    finally:
        probe.unlink(missing_ok=True)
        sys.modules.pop(f"datasheet_analyzer.app.routers.{module_name}", None)


def test_routers_package_is_empty_and_importable():
    from datasheet_analyzer.app import routers

    assert (ROUTERS_DIR / "__init__.py").read_text(encoding="utf-8").strip() == ""
    assert routers.__file__ is not None


# --- the frontend scaffold ----------------------------------------------------


def test_web_scaffold_files_exist():
    for relative in (
        "package.json",
        "tsconfig.json",
        "vite.config.ts",
        "index.html",
        "src/main.tsx",
        "src/App.tsx",
        "src/api/types.ts",
        "src/api/client.ts",
    ):
        assert (WEB_DIR / relative).is_file(), f"web/{relative} is missing"


def test_package_json_declares_the_four_scripts():
    package = json.loads((WEB_DIR / "package.json").read_text(encoding="utf-8"))
    assert set(package["scripts"]) >= {"dev", "build", "typecheck", "test"}
    # The frontend tickets own no configuration, so every runtime dependency
    # they need is declared here: PDF.js is bundled locally (no CDN), and the
    # router is what carries cross-pane state.
    assert {"react", "react-dom", "react-router-dom", "pdfjs-dist"} <= set(package["dependencies"])
    assert {"typescript", "vite", "vitest"} <= set(package["devDependencies"])


def test_app_discovers_routes_from_the_filesystem():
    """`App.tsx` is written once; a screen is a directory, not a registration."""
    source = (WEB_DIR / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "import.meta.glob" in source
    assert "./routes/*/route.tsx" in source


def test_client_exposes_one_function_per_endpoint_plus_sse():
    source = (WEB_DIR / "src" / "api" / "client.ts").read_text(encoding="utf-8")
    exported = set(re.findall(r"export (?:async )?function (\w+)", source))
    assert {
        "getParts",
        "getProjects",
        "scanDirectory",
        "startAnalyze",
        "openAnalyzeStream",
        "getLibrary",
        "patchLibraryDocument",
        "resolveScope",
        "openChatStream",
        "listSessions",
        "createSession",
        "getSession",
        "exportSession",
        "locate",
        "pdfUrl",
        "openSSE",
        "openSSEPost",
    } <= exported


#: One exported TypeScript name per contract model (plus the enums and the
#: shared-state constants the panes agree on).
REQUIRED_TS_EXPORTS = [
    "Applicability",
    "ApplicabilityKind",
    "ScopeKind",
    "ScopeRef",
    "CitationOut",
    "SourceDocument",
    "LibraryDocument",
    "JobState",
    "AnalyzeJob",
    "ChatMessage",
    "ChatSession",
    "ErrorOut",
    "PartOut",
    "PartsOut",
    "ProjectPartOut",
    "ProjectOut",
    "ProjectsOut",
    "DocProposal",
    "ScanIn",
    "ScanOut",
    "StartIn",
    "StartOut",
    "JobEvent",
    "RunSnapshot",
    "LibraryDocumentOut",
    "LibraryOut",
    "LibraryPatchIn",
    "ResolveIn",
    "ScopeResolution",
    "MessageIn",
    "ChatEventType",
    "ChatEvent",
    "SessionCreateIn",
    "SessionSummary",
    "SessionsOut",
    "SessionOut",
    "SessionExportFormat",
    "LocateQuery",
    "RectOut",
    "LocateOut",
    "PdfTarget",
]


def test_types_ts_mirrors_every_contract_model():
    source = (WEB_DIR / "src" / "api" / "types.ts").read_text(encoding="utf-8")
    exported = set(re.findall(r"export (?:interface|type|const|enum) (\w+)", source))
    missing = [name for name in REQUIRED_TS_EXPORTS if name not in exported]
    assert missing == [], f"web/src/api/types.ts is missing {missing}"


def test_every_contract_model_has_a_typescript_twin():
    """The Python side may not grow a model the frontend cannot name."""
    source = (WEB_DIR / "src" / "api" / "types.ts").read_text(encoding="utf-8")
    exported = set(re.findall(r"export (?:interface|type|const|enum) (\w+)", source))
    python_models = {
        name
        for name in contracts.__all__
        if isinstance(getattr(contracts, name, None), type)
        and issubclass(getattr(contracts, name), BaseModel)
    }
    # `JobRegistryLike` is a Protocol for Python callers, not a wire shape.
    untranslated = sorted(python_models - exported - {"JobRegistryLike"})
    assert untranslated == []


def test_web_scaffold_typechecks():
    """`npm run typecheck` — the gate the five frontend tickets build against.

    Skipped when the scaffold has not been installed (`npm install` in
    `web/`). A failure here is a TypeScript error anywhere under `web/src`,
    which may belong to a frontend ticket rather than to this one.
    """
    if not (WEB_DIR / "node_modules").is_dir():
        pytest.skip("web/node_modules is absent — run `npm install` in web/")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    result = subprocess.run(
        [npm, "run", "--silent", "typecheck"],
        cwd=WEB_DIR,
        capture_output=True,
        text=True,
        timeout=600,
        shell=False,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
