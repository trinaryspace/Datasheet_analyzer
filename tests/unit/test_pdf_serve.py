"""Ticket 14 — `GET /api/pdf/{content_hash}` streams a source PDF safely.

Hermetic by construction: a synthetic PDF built in-test with `fitz`, a fake
`LibraryStore` holding it, a temp corpus tree, and no network, model,
subprocess or browser anywhere. The router is mounted on a bare `FastAPI()`
rather than through `create_app()` so this file tests ticket 14 and nothing
else — no other ticket's in-flight router can turn these assertions red.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import fitz
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

from datasheet_analyzer.app.deps import get_library, get_settings_dep
from datasheet_analyzer.app.routers import pdf as pdf_router
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.models import Applicability, LibraryDocument, SourceDocument

HASH = "a" * 64
OTHER_HASH = "b" * 64


# --- fakes and fixtures -------------------------------------------------------


class FakeLibrary:
    """Only what the router uses: `get()` by hash, and a record of the keys."""

    def __init__(self, documents: dict[str, LibraryDocument] | None = None) -> None:
        self.documents = documents or {}
        self.lookups: list[str] = []

    def get(self, content_hash: str) -> LibraryDocument | None:
        self.lookups.append(content_hash)
        return self.documents.get(content_hash)


def make_pdf(path: Path, pages: int = 6) -> Path:
    """A small real PDF with enough pages to be worth ranging over."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for n in range(pages):
        page = doc.new_page()
        page.insert_text(
            (72, 72),
            f"TEST9000 page {n + 1}. Absolute maximum ratings, supply voltage 1.2 V.",
        )
    doc.save(path)
    doc.close()
    return path


def make_document(path: str | Path, content_hash: str = HASH) -> LibraryDocument:
    return LibraryDocument(
        source=SourceDocument(
            content_hash=content_hash,
            path=str(path),
            part_number="TEST9000",
            page_count=6,
        ),
        applicability=Applicability(),
    )


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp corpus tree that is the *only* place documents may live.

    `tmp_path` itself is deliberately **not** a root: `tmp_path/"outside"` is
    what the outside-the-roots test points at. The user's home is redirected
    inside the corpus for the same reason — on Windows the real temp directory
    lives under the real home, which would otherwise make every path allowed.
    """
    corpus_dir = tmp_path / "corpus"
    (corpus_dir / "home").mkdir(parents=True)
    monkeypatch.chdir(corpus_dir)
    monkeypatch.setattr(pdf_router, "_user_home", lambda: corpus_dir / "home")
    monkeypatch.delenv(pdf_router.PDF_ROOTS_ENV, raising=False)
    reset_settings_cache()
    yield corpus_dir
    reset_settings_cache()


@pytest.fixture
def settings(corpus: Path) -> Settings:
    return Settings(
        parts_dir=corpus / "parts",
        cache_dir=corpus / ".cache",
        projects_dir=corpus / "projects",
        library_dir=corpus / "library",
        sessions_dir=corpus / "sessions",
    ).resolve()


@pytest.fixture
def pdf_path(corpus: Path) -> Path:
    return make_pdf(corpus / "docs" / "test9000.pdf")


@pytest.fixture
def library(pdf_path: Path) -> FakeLibrary:
    return FakeLibrary({HASH: make_document(pdf_path)})


@pytest.fixture
def client(library: FakeLibrary, settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(pdf_router.router)
    app.dependency_overrides[get_library] = lambda: library
    app.dependency_overrides[get_settings_dep] = lambda: settings
    return TestClient(app)


def make_request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": f"/api/pdf/{HASH}",
            "raw_path": f"/api/pdf/{HASH}".encode(),
            "query_string": b"",
            "root_path": "",
            "headers": raw,
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


# --- the happy path -----------------------------------------------------------


def test_known_hash_returns_the_pdf(client: TestClient, pdf_path: Path) -> None:
    """A known `content_hash` returns the PDF with the right content type."""
    response = client.get(f"/api/pdf/{HASH}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == pdf_path.read_bytes()
    assert response.content.startswith(b"%PDF")
    assert response.headers["accept-ranges"] == "bytes"


def test_no_range_returns_200_and_the_whole_file(client: TestClient, pdf_path: Path) -> None:
    size = pdf_path.stat().st_size
    response = client.get(f"/api/pdf/{HASH}")

    assert response.status_code == 200
    assert "content-range" not in response.headers
    assert len(response.content) == size
    assert response.headers["content-length"] == str(size)


def test_content_disposition_is_inline_with_the_filename(client: TestClient) -> None:
    """Inline so the browser renders the PDF rather than downloading it."""
    disposition = client.get(f"/api/pdf/{HASH}").headers["content-disposition"]

    assert disposition.startswith("inline")
    assert "test9000.pdf" in disposition


def test_etag_is_the_content_hash(client: TestClient) -> None:
    assert client.get(f"/api/pdf/{HASH}").headers["etag"] == f'"{HASH}"'


# --- missing documents and moved files ---------------------------------------


def test_unknown_hash_is_404(client: TestClient, library: FakeLibrary) -> None:
    response = client.get(f"/api/pdf/{OTHER_HASH}")

    assert response.status_code == 404
    assert OTHER_HASH in response.json()["detail"]
    assert library.lookups == [OTHER_HASH]


def test_moved_file_is_404_naming_the_recorded_path(
    client: TestClient, pdf_path: Path, library: FakeLibrary
) -> None:
    """A user who reorganized folders needs to know which file went missing."""
    recorded = library.documents[HASH].source.path
    pdf_path.unlink()

    response = client.get(f"/api/pdf/{HASH}")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert recorded in detail
    assert "no longer exists" in detail


def test_directory_at_the_recorded_path_is_404(
    client: TestClient, library: FakeLibrary, corpus: Path
) -> None:
    """A recorded path that is not a regular file is refused, not opened."""
    folder = corpus / "docs" / "a-folder.pdf"
    folder.mkdir(parents=True)
    library.documents[HASH] = make_document(folder)

    response = client.get(f"/api/pdf/{HASH}")

    assert response.status_code == 404
    assert "not a regular file" in response.json()["detail"]


def test_relative_recorded_path_resolves_against_the_working_directory(
    client: TestClient, corpus: Path, library: FakeLibrary, pdf_path: Path
) -> None:
    """`SourceDocument.path` is often relative — `"docs/test9000.pdf"`."""
    library.documents[HASH] = make_document("docs/test9000.pdf")

    response = client.get(f"/api/pdf/{HASH}")

    assert response.status_code == 200
    assert response.content == pdf_path.read_bytes()


# --- path safety --------------------------------------------------------------


def test_path_outside_the_roots_is_refused(
    client: TestClient, tmp_path: Path, library: FakeLibrary
) -> None:
    """The file exists and is readable; it is refused for *where* it is."""
    outside = make_pdf(tmp_path / "outside" / "secret.pdf")
    assert outside.is_file()
    library.documents[HASH] = make_document(outside)

    response = client.get(f"/api/pdf/{HASH}")

    assert response.status_code == 403
    assert "outside the document roots" in response.json()["detail"]
    assert str(outside) in response.json()["detail"]


def test_traversal_escape_from_inside_a_root_is_refused(
    client: TestClient, corpus: Path, tmp_path: Path, library: FakeLibrary
) -> None:
    """A record whose path climbs out of a root is refused after resolution."""
    make_pdf(tmp_path / "outside" / "secret.pdf")
    library.documents[HASH] = make_document(Path("docs") / ".." / ".." / "outside" / "secret.pdf")

    assert client.get(f"/api/pdf/{HASH}").status_code == 403


def test_extra_root_from_the_environment_is_allowed(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`DSA_PDF_ROOTS` is how a folder outside the corpus is declared servable."""
    outside = make_pdf(tmp_path / "share" / "test9000.pdf")
    monkeypatch.setenv(pdf_router.PDF_ROOTS_ENV, str(tmp_path / "share"))
    library = FakeLibrary({HASH: make_document(outside)})
    app = FastAPI()
    app.include_router(pdf_router.router)
    app.dependency_overrides[get_library] = lambda: library
    app.dependency_overrides[get_settings_dep] = lambda: settings

    response = TestClient(app).get(f"/api/pdf/{HASH}")

    assert response.status_code == 200
    assert response.content == outside.read_bytes()


def test_settings_directories_are_roots(settings: Settings, corpus: Path) -> None:
    roots = pdf_router.allowed_roots(settings)

    assert settings.parts_dir in roots
    assert settings.library_dir in roots
    assert corpus.resolve() in roots  # the working directory
    assert (corpus / "home").resolve() in roots


@pytest.mark.parametrize(
    "hostile",
    [
        "%2E%2E%2F%2E%2E%2Fetc%2Fpasswd",
        "..%5C..%5CWindows%5Cwin.ini",
        "%2Fetc%2Fshadow",
        "C%3A%5CWindows%5Cwin.ini",
    ],
)
def test_no_request_parameter_can_influence_the_path(
    client: TestClient, library: FakeLibrary, hostile: str
) -> None:
    """The only input is a hash, and an unregistered hash never reaches disk."""
    response = client.get(f"/api/pdf/{hostile}")

    assert response.status_code == 404
    assert not response.content.startswith(b"%PDF")
    # If the string reached the router at all it was used as a library key —
    # never as a path — and it matched nothing.
    assert all(key not in library.documents for key in library.lookups)


def test_query_parameters_are_ignored(client: TestClient, pdf_path: Path) -> None:
    """No query parameter names a file; the served bytes are hash-determined."""
    response = client.get(
        f"/api/pdf/{HASH}",
        params={"path": "/etc/passwd", "file": "C:\\Windows\\win.ini", "page": "3"},
    )

    assert response.status_code == 200
    assert response.content == pdf_path.read_bytes()


def test_resolve_document_path_rejects_an_empty_recorded_path(settings: Settings) -> None:
    with pytest.raises(HTTPException) as excinfo:
        pdf_router.resolve_document_path("   ", settings)

    assert excinfo.value.status_code == 404


# --- range requests -----------------------------------------------------------


def test_range_returns_206_with_content_range_and_exact_bytes(
    client: TestClient, pdf_path: Path
) -> None:
    raw = pdf_path.read_bytes()
    size = len(raw)

    response = client.get(f"/api/pdf/{HASH}", headers={"Range": "bytes=10-99"})

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 10-99/{size}"
    assert response.headers["content-length"] == "90"
    assert response.content == raw[10:100]


def test_open_ended_range_runs_to_the_end_of_the_file(client: TestClient, pdf_path: Path) -> None:
    raw = pdf_path.read_bytes()
    size = len(raw)

    response = client.get(f"/api/pdf/{HASH}", headers={"Range": f"bytes={size - 20}-"})

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes {size - 20}-{size - 1}/{size}"
    assert response.content == raw[-20:]


def test_suffix_range_returns_the_last_bytes(client: TestClient, pdf_path: Path) -> None:
    """PDF.js opens a document by reading its trailer — `bytes=-N`."""
    raw = pdf_path.read_bytes()
    size = len(raw)

    response = client.get(f"/api/pdf/{HASH}", headers={"Range": "bytes=-64"})

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes {size - 64}-{size - 1}/{size}"
    assert response.content == raw[-64:]


def test_range_past_the_end_is_clamped(client: TestClient, pdf_path: Path) -> None:
    raw = pdf_path.read_bytes()
    size = len(raw)

    response = client.get(f"/api/pdf/{HASH}", headers={"Range": "bytes=0-99999999"})

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-{size - 1}/{size}"
    assert response.content == raw


def test_unsatisfiable_range_returns_416(client: TestClient, pdf_path: Path) -> None:
    size = pdf_path.stat().st_size

    response = client.get(f"/api/pdf/{HASH}", headers={"Range": f"bytes={size}-"})

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{size}"
    assert response.headers["content-length"] == "0"
    assert response.content == b""


def test_malformed_range_is_ignored(client: TestClient, pdf_path: Path) -> None:
    """RFC 9110: an unparsable `Range` is ignored, not an error."""
    for header in ("bytes=abc-def", "pages=1-2", "bytes=0-9,20-29", "bytes=99-10"):
        response = client.get(f"/api/pdf/{HASH}", headers={"Range": header})

        assert response.status_code == 200, header
        assert response.content == pdf_path.read_bytes()


def test_if_range_mismatch_sends_the_whole_body(client: TestClient, pdf_path: Path) -> None:
    response = client.get(
        f"/api/pdf/{HASH}",
        headers={"Range": "bytes=0-9", "If-Range": '"stale-etag"'},
    )

    assert response.status_code == 200
    assert response.content == pdf_path.read_bytes()


def test_if_range_match_serves_the_range(client: TestClient, pdf_path: Path) -> None:
    response = client.get(
        f"/api/pdf/{HASH}",
        headers={"Range": "bytes=0-9", "If-Range": f'"{HASH}"'},
    )

    assert response.status_code == 206
    assert response.content == pdf_path.read_bytes()[:10]


def test_content_length_is_correct_for_200_206_and_416(client: TestClient, pdf_path: Path) -> None:
    size = pdf_path.stat().st_size

    whole = client.get(f"/api/pdf/{HASH}")
    partial = client.get(f"/api/pdf/{HASH}", headers={"Range": "bytes=5-14"})
    refused = client.get(f"/api/pdf/{HASH}", headers={"Range": f"bytes={size + 10}-"})

    assert whole.headers["content-length"] == str(size) == str(len(whole.content))
    assert partial.headers["content-length"] == "10" == str(len(partial.content))
    assert refused.headers["content-length"] == "0" == str(len(refused.content))


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("", None),
        ("bytes=0-9", pdf_router.ByteRange(0, 9)),
        ("bytes=0-", pdf_router.ByteRange(0, 999)),
        ("bytes=-10", pdf_router.ByteRange(990, 999)),
        ("bytes=-5000", pdf_router.ByteRange(0, 999)),
        ("bytes=1000-", pdf_router.UNSATISFIABLE),
        ("bytes=-0", pdf_router.UNSATISFIABLE),
        ("bytes=10-5", None),
        ("bytes=x-y", None),
        ("bits=0-9", None),
        ("bytes=0-9,50-59", None),
    ],
)
def test_parse_range_table(header: str | None, expected: pdf_router.ByteRange | None) -> None:
    assert pdf_router.parse_range(header, 1000) == expected


def test_parse_range_on_an_empty_file_is_unsatisfiable() -> None:
    assert pdf_router.parse_range("bytes=0-", 0) == pdf_router.UNSATISFIABLE


# --- streaming ----------------------------------------------------------------


def test_iter_file_range_streams_in_bounded_chunks(tmp_path: Path) -> None:
    """A large file is read in pieces — never one read of the whole body."""
    big = tmp_path / "big.bin"
    payload = bytes(range(256)) * 4096  # 1 MiB, deliberately > CHUNK_SIZE
    big.write_bytes(payload)

    chunks = list(pdf_router.iter_file_range(big, 0, len(payload) - 1))

    assert len(chunks) == math.ceil(len(payload) / pdf_router.CHUNK_SIZE) > 1
    assert max(len(chunk) for chunk in chunks) <= pdf_router.CHUNK_SIZE
    assert b"".join(chunks) == payload


def test_iter_file_range_opens_the_file_lazily_and_honours_bounds(tmp_path: Path) -> None:
    target = tmp_path / "slice.bin"
    target.write_bytes(b"0123456789")

    generator = pdf_router.iter_file_range(target, 3, 6, chunk_size=2)
    target_bytes = list(generator)

    assert target_bytes == [b"34", b"56"]
    assert list(pdf_router.iter_file_range(target, 5, 4)) == []


def test_response_is_a_stream_not_a_buffer(
    library: FakeLibrary, settings: Settings, monkeypatch: pytest.MonkeyPatch, pdf_path: Path
) -> None:
    """The endpoint hands back a `StreamingResponse` over a bounded iterator."""
    monkeypatch.setattr(pdf_router, "CHUNK_SIZE", 512)
    size = pdf_path.stat().st_size
    assert size > 512, "fixture PDF must be larger than the patched chunk size"

    async def call() -> tuple[object, list[bytes]]:
        response = await pdf_router.get_pdf(
            content_hash=HASH,
            request=make_request(),
            library=library,
            settings=settings,
        )
        assert isinstance(response, StreamingResponse)
        return response, [chunk async for chunk in response.body_iterator]

    response, chunks = asyncio.run(call())

    assert isinstance(response, StreamingResponse)
    assert len(chunks) > 1
    assert max(len(chunk) for chunk in chunks) <= 512
    assert b"".join(chunks) == pdf_path.read_bytes()
