"""Shared fixtures and helpers.

Layout:
- tests/fixtures/pdf/       the four real phase-4 gate PDFs plus the four
                            brand-less Mini-Circuits datasheets (ungated —
                            committed fixtures, pdf_layout never touches
                            the network)
- tests/fixtures/ti_html/   recorded real TI document-viewer pages (no network in tests)
- tests/fixtures/synthetic/ hand-built edge-case HTML
- tests/fixtures/golden_qa_<PART>.yaml  per-part golden Q&A eval sets
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TI_HTML = FIXTURES / "ti_html"
SYNTHETIC = FIXTURES / "synthetic"
GATE_PDFS = FIXTURES / "pdf"
REPO_ROOT = Path(__file__).parent.parent
AFE7950_PDF = REPO_ROOT / "afe7950.pdf"
AFE7953_PDF = REPO_ROOT / "afe7953.pdf"
# Phase 4 gate: real PDFs under tests/fixtures/pdf, ungated by
# construction (committed fixtures; pdf_layout never touches the
# network). AFE7950_PDF above stays skip-guarded like the TI path.
AD9081_PDF = GATE_PDFS / "ad9081.pdf"
LM741_PDF = GATE_PDFS / "lm741.pdf"
QPA1003P_PDF = GATE_PDFS / "QPA1003P.pdf"
HMC520A_PDF = GATE_PDFS / "hmc520a.pdf"
#: Four real Mini-Circuits datasheets: no brand word on page 1, no publisher
#: in their metadata, no brand in their filenames. They are the evidence-free
#: case vendor detection used to answer with a guess (`ti`, which routed them
#: to `ti_html` and 404'd against ti.com). Ungated like the gate PDFs above.
BRANDLESS_PDFS = (
    GATE_PDFS / "LHA-83W+.pdf",
    GATE_PDFS / "PMA1-14LN+.pdf",
    GATE_PDFS / "PSA-8A+.pdf",
    GATE_PDFS / "ZX10R-2-183-S+.pdf",
)


def _repo_families_listing() -> frozenset[str]:
    """Every path under the repository's own `families/`, relative to it."""
    root = REPO_ROOT / "families"
    if not root.exists():
        return frozenset()
    return frozenset(str(p.relative_to(root)) for p in root.rglob("*"))


#: What the repository's own `families/` directory held when this session
#: started, captured at collection time.
#:
#: `git status` used to be the detector for a test that builds a family index
#: into the working tree, and it stopped being one when `/families/` was
#: gitignored: a family directory is derived in full from tracked records, so
#: it is a cache, and an ignored path reports nothing. This snapshot is the
#: detector instead — and it is the better one, because it distinguishes the
#: thing that matters. A *user's* `dsa family build` is legitimate and is
#: already here when the run starts; only a change **during** the run is a
#: test writing into the repository it is asserting against.
REPO_FAMILIES_AT_START = _repo_families_listing()


@pytest.fixture(scope="session")
def repo_families_guard():
    """`(listing at session start, a callable that lists it now)`.

    Handed over as a fixture rather than imported, because `tests/` is not a
    package: `from tests.conftest import ...` resolves only while the working
    directory happens to be on `sys.path`, which is true for
    `python -m pytest` and not for every way this suite is run.
    """
    return REPO_FAMILIES_AT_START, _repo_families_listing


@pytest.fixture(autouse=True)
def fresh_retrieval_cache():
    """Hermetic per invariant #4: the retrieval core caches a loaded corpus
    in-process, so one test's part must never be visible to the next."""
    from datasheet_analyzer.retrieve import clear_index_cache

    clear_index_cache()
    yield
    clear_index_cache()


def _point_dsa_at(root: Path):
    """Point the Library, sessions and corpus at `root`, undoing on exit.

    `DSA_PARTS_DIR` is here because "tests pass `parts_dir` explicitly" was
    only *nearly* true: a handful reach `get_settings()` instead, and those
    built into the repository's own `parts/` — silently rewriting the two
    committed reference corpora and breaking the test that depends on
    AFE7953 predating full-text search. A suite that edits the fixtures it
    asserts against fails in a way that looks like a code regression.

    `DSA_CACHE_DIR` is deliberately *not* redirected: `.cache/extract` and
    `.cache/http-bin` are committed recorded fixtures, and pointing the cache
    at a temporary directory would send the integration builds to the network
    for pages that are already on disk.

    `DSA_GOLDEN_DIR` is here for the same reason `DSA_PARTS_DIR` is, one step
    sharper: `dsa golden confirm` **writes** `golden_qa_<PART>.yaml`, which is
    invariant 5's objective function and the file that gates every other test
    in this suite. Without this, a confirm run reaching `get_settings()` would
    resolve `evalh.golden.GOLDEN_DIR` - the repository's real `tests/fixtures`
    - and edit the benchmark it is being measured against. Tests that want to
    *read* the committed benchmarks name their paths explicitly (`conftest.FIXTURES`),
    which is unaffected; only the settings-resolved default moves.

    `DSA_FAMILIES_DIR` is here for the same reason once more (phase 7,
    ticket 07): `dsa family build` **writes** `families/<NAME>/`, and a test
    that reached `get_settings()` without naming a families directory built
    one into the repository's own working tree. Observed exactly once, from
    `test_cli_json.py`'s `family build --json` invocation.
    """
    from _pytest.monkeypatch import MonkeyPatch

    from datasheet_analyzer.config import reset_settings_cache

    mp = MonkeyPatch()
    mp.setenv("DSA_LIBRARY_DIR", str(root / "library"))
    mp.setenv("DSA_SESSIONS_DIR", str(root / "sessions"))
    mp.setenv("DSA_PARTS_DIR", str(root / "parts"))
    mp.setenv("DSA_GOLDEN_DIR", str(root / "golden"))
    mp.setenv("DSA_FAMILIES_DIR", str(root / "families"))
    reset_settings_cache()
    yield root
    mp.undo()
    reset_settings_cache()


@pytest.fixture(scope="module", autouse=True)
def isolated_library_for_module(tmp_path_factory, request):
    """A private Library per *module*, for corpora built by module fixtures.

    The Library is the authoritative inventory now (ADR 0005): a build for
    part `P` asks it which documents apply to `P` instead of reading a
    per-part `sources.json`. `Settings.library_dir` defaults to `./library`,
    so without this a test run would write into the working tree and every
    part in the suite would share one store.

    Two scopes are needed because pytest instantiates the higher one first: a
    module-scoped `built` fixture is created *before* any function-scoped
    fixture the test also asks for, so a function-scoped override alone would
    arrive too late and the module's build would land in the repo's real
    library. This fixture covers those builds; `isolated_library` below
    narrows it to one directory per test for everything else.
    """
    yield from _point_dsa_at(tmp_path_factory.mktemp(f"lib-{request.node.name[:24]}"))


@pytest.fixture(autouse=True)
def isolated_library(tmp_path):
    """A private Library and session store per test (ADR 0005, ticket 03).

    Narrower than the per-module fixture above, because within one module two
    tests routinely build the same part name from different PDFs — and with a
    shared store the second build would resolve *both* documents and publish
    them into one corpus. (Observed before this existed: "12 datasheet records
    apply to this part".)

    `parts_dir` and `cache_dir` are already per-test because tests pass them
    explicitly; `library_dir` and `sessions_dir` are not, because most tests
    construct `Settings` without naming them. Setting the environment covers
    both the explicit `Settings(...)` a test builds and the `get_settings()`
    a code path reaches for, which is why it is done here rather than at every
    call site. A corpus built under one of these roots stays readable
    afterwards regardless: `CorpusManifest.library_root` records which store a
    part was published against.
    """
    yield from _point_dsa_at(tmp_path)


@pytest.fixture
def committed_golden_dir(monkeypatch):
    """Point `DSA_GOLDEN_DIR` back at the benchmarks committed to this repo.

    For the handful of tests that exercise *discovery* - `dsa verify --part X`
    with no `--golden`, resolving `tests/fixtures/golden_qa_<PART>.yaml` by
    name. They only read. Every other test keeps the temporary directory
    `_point_dsa_at` sets, which is what stops `dsa golden confirm` from
    reaching the objective function.
    """
    from datasheet_analyzer.config import reset_settings_cache

    monkeypatch.setenv("DSA_GOLDEN_DIR", str(FIXTURES))
    reset_settings_cache()
    yield FIXTURES
    reset_settings_cache()


@pytest.fixture
def make_synthetic_pdf():
    """Factory for the shared synthetic part PDF: 2 pages, TOC with
    Features (p.1) + Absolute Maximum Ratings (p.2). One fixture so every
    pipeline-level test builds the same input bytes; ``marker`` (default "")
    appends to the page-1 text to produce deliberately different bytes while
    keeping the structural shape identical.

    It carries TI's document metadata because the parts built from it are
    *TI* parts — they replay recorded TI document-viewer HTML — and since
    detection stopped guessing (``vendor.detect_vendor``) a document with no
    brand mark anywhere is pinned ``unknown`` and routed to the layout floor.
    The real TI datasheets in this repo (afe7950, afe7953, lmx1204, lm741)
    carry exactly this author string and print no vendor word on page 1, so
    the fixture matches its subject; the metadata is invisible to text
    extraction, so nothing about the extracted document changes."""

    def _make(path: Path, marker: str = "") -> None:
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text(
            (72, 72),
            "TEST9000 Features page. Quad RF sampling 12GSPS transmit DACs." + marker,
        )
        p2 = doc.new_page()
        p2.insert_text(
            (72, 72),
            "4.1 Absolute Maximum Ratings VDD1P2 Supply voltage 1.2V –0.3 1.4 V TJ 150 °C",
        )
        doc.set_toc(
            [
                [1, "1 Features", 1],
                [1, "4 Specifications", 2],
                [2, "4.1 Absolute Maximum Ratings", 2],
            ]
        )
        doc.set_metadata({"author": "Texas Instruments, Incorporated"})
        doc.save(path)
        doc.close()

    return _make


@pytest.fixture
def ti_main_html() -> str:
    """Recorded TI document-viewer TOC page for AFE7950."""
    return (TI_HTML / "afe7950_main.html").read_text(encoding="utf-8")


@pytest.fixture
def ti_sec_4_5_html() -> str:
    """Recorded section 4.5 (Transmitter Electrical Characteristics)."""
    return (TI_HTML / "sec_4_5.html").read_text(encoding="utf-8")


@pytest.fixture
def ti_sec_4_12_1_html() -> str:
    """Recorded section 4.12.1 (TX Typical Characteristics 800 MHz, plots)."""
    return (TI_HTML / "sec_4_12_1.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def afe7950_pdf() -> Path:
    if not AFE7950_PDF.exists():
        pytest.skip("afe7950.pdf not present at repo root")
    return AFE7950_PDF


@pytest.fixture(scope="module")
def afe7953_pdf() -> Path:
    """The second reference PDF, skip-guarded like AFE7950's.

    Only the printed page *text* is ever read from it — the AFE7953 corpus
    itself is the one committed under `parts/`, because no recorded TI
    document-viewer pages exist for this part and the ti_html backend cannot
    be replayed offline for it.
    """
    if not AFE7953_PDF.exists():
        pytest.skip("afe7953.pdf not present at repo root")
    return AFE7953_PDF
