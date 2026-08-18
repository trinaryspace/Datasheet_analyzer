"""Ticket 13 — deriving highlight geometry on demand.

Every PDF here is built in-process with `fitz` at known coordinates, so the
assertions are about *our* geometry (the row band, the ordering, the honest
miss) and never about PyMuPDF's search algorithm. No network, no model, no
subprocess, no browser.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.app.locate import (
    MAX_NEEDLE_CHARS,
    locate,
    needle_for_spec_row,
    needle_for_table,
    needle_for_text,
    normalize_needle,
)
from datasheet_analyzer.app.routers import locate as locate_router
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.models import (
    CorpusManifest,
    SourceDocument,
    SpecRecord,
    TableBlock,
)

# Text is placed by baseline; a glyph box extends a few points above and
# below it, so coordinate assertions carry a tolerance rather than pretending
# to know the font metrics.
TOL = 14.0

ROW_NAME = "OPERATING JUNCTION TEMPERATURE"
DOC_HASH = "a" * 64


@pytest.fixture(autouse=True)
def _clean_settings_cache():
    reset_settings_cache()
    yield
    reset_settings_cache()


def _write_pdf(path: Path, pages: list[list[tuple[float, float, str]]]) -> Path:
    """A PDF whose every string sits at a coordinate the test chose."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        for x, y, text in lines:
            page.insert_text((x, y), text)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def spec_page(tmp_path: Path) -> Path:
    """One page holding a parametric row plus other rows above and below."""
    return _write_pdf(
        tmp_path / "specs.pdf",
        [
            [
                (60.0, 100.0, "4.1 Absolute Maximum Ratings"),
                (60.0, 200.0, "TJ"),
                (200.0, 200.0, ROW_NAME),
                (480.0, 200.0, "150"),
                (60.0, 300.0, "VDD1P2 Supply voltage 1.2 V"),
            ]
        ],
    )


# --- the search ---------------------------------------------------------------


def test_single_hit_returns_one_rect(spec_page: Path):
    """A needle appearing exactly once is found, with one rectangle."""
    out = locate(spec_page, 1, ROW_NAME)

    assert out.found is True
    assert out.reason == ""
    assert out.page == 1
    assert len(out.rects) == 1
    rect = out.rects[0]
    # The matched vertical band is the printed line's, near baseline y=200.
    assert rect.y0 < 200.0 < rect.y1
    assert rect.height < 30.0


def test_repeated_needle_returns_every_hit_top_to_bottom(tmp_path: Path):
    """Three printed occurrences produce three rects, ordered top to bottom."""
    pdf = _write_pdf(
        tmp_path / "repeat.pdf",
        [
            [
                (60.0, 120.0, f"{ROW_NAME} first"),
                (60.0, 400.0, f"{ROW_NAME} second"),
                (60.0, 700.0, f"{ROW_NAME} third"),
            ]
        ],
    )

    out = locate(pdf, 1, ROW_NAME)

    assert out.found is True
    assert len(out.rects) == 3
    ys = [r.y0 for r in out.rects]
    assert ys == sorted(ys)
    assert ys[0] < 120.0 and ys[1] < 400.0 and ys[2] < 700.0


def test_absent_needle_is_an_honest_miss(spec_page: Path):
    """No hit means no rect and a reason — never a box around the wrong row."""
    out = locate(spec_page, 1, "STORAGE TEMPERATURE RANGE")

    assert out.found is False
    assert out.rects == []
    assert out.reason
    assert "does not appear" in out.reason
    assert out.page == 1


def test_page_outside_the_document_is_a_miss_not_an_exception(spec_page: Path):
    """Page 99 of a one-page PDF is answered, not raised."""
    out = locate(spec_page, 99, ROW_NAME)

    assert out.found is False
    assert out.rects == []
    assert "page 99" in out.reason
    assert "1 page" in out.reason


def test_page_zero_is_a_miss(spec_page: Path):
    out = locate(spec_page, 0, ROW_NAME)

    assert out.found is False
    assert out.reason


def test_missing_pdf_is_a_miss(tmp_path: Path):
    out = locate(tmp_path / "nope.pdf", 1, ROW_NAME)

    assert out.found is False
    assert out.rects == []
    assert "no readable PDF" in out.reason


def test_unreadable_pdf_is_a_miss(tmp_path: Path):
    """A file that is not a PDF is reported, not raised."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nthis is not a document\n")

    out = locate(broken, 1, ROW_NAME)

    assert out.found is False
    assert out.rects == []
    assert out.reason


def test_empty_needle_is_a_miss(spec_page: Path):
    out = locate(spec_page, 1, "   ")

    assert out.found is False
    assert out.reason


def test_too_short_needle_is_refused_rather_than_guessed(spec_page: Path):
    out = locate(spec_page, 1, "T")

    assert out.found is False
    assert "too short" in out.reason


# --- geometry -----------------------------------------------------------------


def test_row_rect_is_widened_to_the_text_extent(spec_page: Path):
    """The highlight spans the row, keeping the matched vertical band."""
    raw = fitz.open(spec_page)
    page = raw.load_page(0)
    match = page.search_for(ROW_NAME)[0]
    row_blocks = [
        b for b in page.get_text("blocks") if b[6] == 0 and b[1] < match.y1 and b[3] > match.y0
    ]
    left = min(b[0] for b in row_blocks)
    right = max(b[2] for b in row_blocks)
    raw.close()

    rect = locate(spec_page, 1, ROW_NAME).rects[0]

    # Widened horizontally past the matched cell, out to the row's text.
    assert rect.x0 == pytest.approx(left, abs=1.0)
    assert rect.x1 == pytest.approx(right, abs=1.0)
    assert rect.x0 < match.x0 and rect.x1 > match.x1
    # ...and the vertical band is untouched.
    assert rect.y0 == pytest.approx(match.y0, abs=0.01)
    assert rect.y1 == pytest.approx(match.y1, abs=0.01)


def test_row_rect_does_not_swallow_unrelated_lines(spec_page: Path):
    """Widening is horizontal only: another line's band is never covered."""
    rect = locate(spec_page, 1, ROW_NAME).rects[0]

    assert rect.y1 < 300.0 - TOL  # the VDD1P2 line below is untouched
    assert rect.y0 > 100.0 + TOL  # so is the heading above


def test_coordinates_are_top_left_origin_pdf_points(tmp_path: Path):
    """y grows *down* from the page top, as `RectOut` documents."""
    pdf = _write_pdf(tmp_path / "top.pdf", [[(60.0, 72.0, ROW_NAME)]])

    out = locate(pdf, 1, ROW_NAME)

    assert out.found is True
    assert out.page_height == pytest.approx(842.0, abs=1.0)
    assert out.page_width == pytest.approx(595.0, abs=1.0)
    assert out.rotation == 0
    rect = out.rects[0]
    # Printed near the top: a top-left origin puts it at a small y. A
    # bottom-left origin would report ~770 for the same glyphs.
    assert rect.y0 < 100.0
    assert 0.0 <= rect.x0 <= rect.x1 <= out.page_width


def test_hit_on_a_later_page_is_located_there(tmp_path: Path):
    pdf = _write_pdf(
        tmp_path / "two.pdf",
        [
            [(60.0, 100.0, "Features page")],
            [(60.0, 100.0, ROW_NAME)],
        ],
    )

    assert locate(pdf, 1, ROW_NAME).found is False
    out = locate(pdf, 2, ROW_NAME)
    assert out.found is True
    assert out.page == 2


# --- normalization ------------------------------------------------------------


def test_normalize_needle_folds_ligatures_soft_hyphens_and_nbsp():
    assert normalize_needle("speciﬁcation") == "specification"
    assert normalize_needle("TEMPER­ATURE") == "TEMPERATURE"
    assert normalize_needle("JUNCTION TEMPERATURE") == "JUNCTION TEMPERATURE"
    assert normalize_needle("  two   spaces  ") == "two spaces"


@pytest.mark.parametrize(
    "needle",
    [
        "OPERATING JUNCTION TEMPERATURE",  # non-breaking spaces
        "OPERATING JUNC­TION TEMPERATURE",  # soft hyphen
        "OPERATING JUNCTION TEMPERATURE\u200b",  # zero-width space
    ],
)
def test_needle_is_normalized_before_searching(spec_page: Path, needle: str):
    out = locate(spec_page, 1, needle)

    assert out.found is True, out.reason
    assert out.needle == ROW_NAME


def test_ligature_in_the_needle_matches_plain_printed_text(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "lig.pdf", [[(60.0, 100.0, "Amplifier configuration")]])

    out = locate(pdf, 1, "conﬁguration")

    assert out.found is True
    assert out.needle == "configuration"


def test_minus_sign_and_hyphen_are_the_same_cell(tmp_path: Path):
    """`−40` stored, `-40` printed: the same number, so the same match."""
    pdf = _write_pdf(tmp_path / "dash.pdf", [[(60.0, 100.0, "TA range -40 to 125 degC")]])

    out = locate(pdf, 1, "−40 to 125")

    assert out.found is True, out.reason
    assert len(out.rects) == 1


# --- needle selection ---------------------------------------------------------


def test_spec_row_needle_prefers_the_name_over_a_bare_number():
    record = SpecRecord(
        symbol="TJ",
        name="Operating junction temperature",
        row_verbatim=["TJ", ROW_NAME, "-40", "150", "degC"],
    )

    assert needle_for_spec_row(record) == ROW_NAME


def test_spec_row_needle_prefers_the_symbol_over_a_bare_number():
    """With no name cell, the symbol still beats every numeric cell."""
    record = SpecRecord(symbol="ATTstep", row_verbatim=["ATTstep", "-40", "0.5", "150", "1.0"])

    assert needle_for_spec_row(record) == "ATTstep"


def test_spec_row_needle_falls_back_to_the_record_when_the_row_is_all_numbers():
    record = SpecRecord(
        symbol="TJ",
        name="Operating junction temperature",
        row_verbatim=["-40", "25", "150"],
    )

    assert needle_for_spec_row(record) == "Operating junction temperature"


def test_spec_row_needle_is_empty_when_nothing_is_distinctive():
    assert needle_for_spec_row(SpecRecord(row_verbatim=["", " ", "5"])) == ""


def test_spec_row_needle_is_truncated_to_one_line():
    long_cell = "Operating junction temperature under continuous maximum rated load conditions"
    record = SpecRecord(row_verbatim=["TJ", long_cell])

    needle = needle_for_spec_row(record)

    assert len(needle) <= MAX_NEEDLE_CHARS
    assert long_cell.startswith(needle)
    assert not needle.endswith(" ")


def test_table_needle_is_the_caption():
    table = TableBlock(caption="Table 4-1. Absolute Maximum Ratings", grid=[["TJ", "150"]])

    assert needle_for_table(table) == "Table 4-1. Absolute Maximum Ratings"


def test_table_needle_falls_back_to_a_distinctive_cell():
    table = TableBlock(headers=["PARAMETER", "MIN"], grid=[["ATTstep", "-40"]])

    assert needle_for_table(table) == "PARAMETER"


def test_text_needle_truncates_at_a_word_boundary():
    paragraph = (
        "The device supports JESD204C subclass 1 deterministic latency across "
        "all four transmit channels."
    )

    needle = needle_for_text(paragraph)

    assert len(needle) <= MAX_NEEDLE_CHARS
    assert paragraph.startswith(needle)
    assert not needle.endswith(" ")
    assert needle.split()[-1] in paragraph.split()


def test_selected_needle_actually_locates_the_row(spec_page: Path):
    """The two halves compose: the chosen needle finds the printed row."""
    record = SpecRecord(symbol="TJ", name="Operating junction temperature", row_verbatim=[ROW_NAME])

    out = locate(spec_page, 1, needle_for_spec_row(record))

    assert out.found is True
    assert len(out.rects) == 1


# --- the endpoint -------------------------------------------------------------


def _client(tmp_path: Path, *, documents: list[SourceDocument], part: str = "TEST9000"):
    parts_dir = tmp_path / "parts"
    (parts_dir / part).mkdir(parents=True, exist_ok=True)
    manifest = CorpusManifest(part_number=part, documents=documents)
    (parts_dir / part / "manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    settings = Settings(
        parts_dir=parts_dir,
        cache_dir=tmp_path / "cache",
        projects_dir=tmp_path / "projects",
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
        anthropic_api_key="",
    ).resolve()
    app = FastAPI()
    app.include_router(locate_router.router)
    app.dependency_overrides[get_settings_dep] = lambda: settings
    return TestClient(app)


def test_endpoint_resolves_the_pdf_through_the_manifest_join(tmp_path: Path, spec_page: Path):
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=str(spec_page), page_count=1)],
    )

    response = client.get(
        "/api/locate",
        params={"part": "TEST9000", "doc_hash": DOC_HASH, "page": 1, "needle": ROW_NAME},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert len(body["rects"]) == 1
    assert body["needle"] == ROW_NAME
    assert body["page_height"] > 0


def test_endpoint_finds_the_document_without_a_part_hint(tmp_path: Path, spec_page: Path):
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=str(spec_page), page_count=1)],
    )

    response = client.get(
        "/api/locate", params={"doc_hash": DOC_HASH, "page": 1, "needle": ROW_NAME}
    )

    assert response.status_code == 200
    assert response.json()["found"] is True


def test_endpoint_resolves_a_relative_recorded_path(
    tmp_path: Path, spec_page: Path, monkeypatch: pytest.MonkeyPatch
):
    """`SourceDocument.path` is often relative to the build's directory."""
    monkeypatch.chdir(spec_page.parent)
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=spec_page.name, page_count=1)],
    )

    response = client.get(
        "/api/locate", params={"doc_hash": DOC_HASH, "page": 1, "needle": ROW_NAME}
    )

    assert response.status_code == 200
    assert response.json()["found"] is True


def test_endpoint_miss_is_a_200_with_a_reason(tmp_path: Path, spec_page: Path):
    """A resolvable document whose text is absent is not an error."""
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=str(spec_page), page_count=1)],
    )

    response = client.get(
        "/api/locate",
        params={"doc_hash": DOC_HASH, "page": 1, "needle": "STORAGE TEMPERATURE"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert body["rects"] == []
    assert body["reason"]


def test_endpoint_404s_on_an_unknown_hash(tmp_path: Path, spec_page: Path):
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=str(spec_page), page_count=1)],
    )

    response = client.get(
        "/api/locate", params={"doc_hash": "b" * 64, "page": 1, "needle": ROW_NAME}
    )

    assert response.status_code == 404
    assert "b" * 64 in response.json()["detail"]


def test_endpoint_404s_on_an_unknown_part(tmp_path: Path, spec_page: Path):
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=str(spec_page), page_count=1)],
    )

    response = client.get(
        "/api/locate",
        params={"part": "NOSUCHPART", "doc_hash": DOC_HASH, "page": 1, "needle": ROW_NAME},
    )

    assert response.status_code == 404
    assert "NOSUCHPART" in response.json()["detail"]


def test_endpoint_404s_naming_the_recorded_path_when_the_pdf_moved(tmp_path: Path, spec_page: Path):
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=str(spec_page), page_count=1)],
    )
    spec_page.unlink()

    response = client.get(
        "/api/locate",
        params={"part": "TEST9000", "doc_hash": DOC_HASH, "page": 1, "needle": ROW_NAME},
    )

    assert response.status_code == 404
    assert spec_page.name in response.json()["detail"]


def test_endpoint_400s_without_a_doc_hash(tmp_path: Path, spec_page: Path):
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=str(spec_page), page_count=1)],
    )

    response = client.get("/api/locate", params={"page": 1, "needle": ROW_NAME})

    assert response.status_code == 400
    assert "doc_hash" in response.json()["detail"]


def test_endpoint_cannot_be_pointed_outside_the_parts_tree(tmp_path: Path, spec_page: Path):
    """`part` names a discovered directory; it is never joined onto a path."""
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=str(spec_page), page_count=1)],
    )

    response = client.get(
        "/api/locate",
        params={
            "part": "../../etc",
            "doc_hash": DOC_HASH,
            "page": 1,
            "needle": ROW_NAME,
        },
    )

    assert response.status_code == 404


def test_endpoint_page_out_of_range_is_a_200_miss(tmp_path: Path, spec_page: Path):
    client = _client(
        tmp_path,
        documents=[SourceDocument(content_hash=DOC_HASH, path=str(spec_page), page_count=1)],
    )

    response = client.get(
        "/api/locate", params={"doc_hash": DOC_HASH, "page": 99, "needle": ROW_NAME}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert "page 99" in body["reason"]


# --- the invariant this whole approach exists to protect ----------------------


def test_extraction_cache_stays_valid():
    """Ticket 13 derives geometry so `pdf_layout` never has to change."""
    from datasheet_analyzer.app import locate as locate_module
    from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend

    assert PdfLayoutBackend.output_version == "tables-08"
    source = Path(locate_module.__file__).read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert not [line for line in imports if "extract" in line or "pdf_layout" in line]
