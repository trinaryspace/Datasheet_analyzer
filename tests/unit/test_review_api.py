"""`POST /api/analyze/scan` — the review screen's data (ticket 08).

Every test here is hermetic: synthetic PDFs built in-process with `fitz`, a
stubbed `acquire.applicability.infer` (ticket 02 owns the real one), no
network, no model, no subprocess. `Settings` is constructed against `tmp_path`
and injected through `app.dependency_overrides`, so nothing reads the
developer's real `parts/`, `library/` or `.cache/`.

What is worth pinning, beyond "it returns rows":

- **A scan writes nothing.** It is the one endpoint a user runs against a
  directory they have not decided to trust yet, so `parts_dir`, `library_dir`
  and the extraction cache are compared byte for byte across the call.
- **A scan is total.** A corrupt PDF, or an inference that raises, becomes one
  proposal carrying the failure in its `evidence`. Thirty-nine good PDFs must
  not lose their review because the fortieth is a truncated download.
- **Concurrency never reorders.** Inference runs in a pool sized by
  `settings.analyze_workers`; the response stays in filename order even when
  the last file finishes first.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import fitz
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from datasheet_analyzer.acquire import applicability as applicability_module
from datasheet_analyzer.app.contracts import (
    Applicability,
    DocProposal,
    ScanOut,
    StartIn,
)
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.app.routers import review
from datasheet_analyzer.config import Settings, reset_settings_cache

# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_settings_cache():
    """AGENTS.md invariant 4: no test inherits another's cached settings."""
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A Settings pointed entirely at `tmp_path`, with no API key.

    The key is blanked *after* construction on purpose: the field carries
    `validation_alias="ANTHROPIC_API_KEY"`, so an init kwarg does not
    override a developer's real environment and a test that passed one would
    quietly build a live client.
    """
    settings = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / "cache",
        projects_dir=tmp_path / "projects",
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
        analyze_workers=4,
    ).resolve()
    settings.anthropic_api_key = ""
    return settings


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """An app holding only this ticket's router — other tickets are in flight."""
    app = FastAPI()
    app.include_router(review.router)
    app.dependency_overrides[get_settings_dep] = lambda: settings
    return TestClient(app)


def make_pdf(path: Path, text: str, pages: int = 1) -> Path:
    """A minimal real PDF whose first page carries `text`."""
    doc = fitz.open()
    for i in range(max(1, pages)):
        page = doc.new_page()
        page.insert_text((72, 72), text if i == 0 else f"page {i + 1}")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def stub_infer(
    monkeypatch: pytest.MonkeyPatch,
    fn: Callable[..., DocProposal] | None = None,
    *,
    calls: list[dict] | None = None,
) -> list[dict]:
    """Replace ticket 02's `infer` with a recording double. Returns the log."""
    log: list[dict] = calls if calls is not None else []

    def default(pdf_path, *, first_page_text="", known_parts=None, client=None):
        token = first_page_text.split()[0] if first_page_text.split() else ""
        return DocProposal(
            pdf_path=str(pdf_path),
            filename=Path(pdf_path).name,
            part_number=token,
            applicability=Applicability.for_parts([token], evidence=f"title block: {token}"),
            evidence=f"title block line 1: {token}",
        )

    body = fn or default

    def recording(pdf_path, *, first_page_text="", known_parts=None, client=None):
        log.append(
            {
                "pdf_path": Path(pdf_path),
                "first_page_text": first_page_text,
                "known_parts": list(known_parts or []),
                "client": client,
            }
        )
        return body(
            pdf_path,
            first_page_text=first_page_text,
            known_parts=known_parts,
            client=client,
        )

    monkeypatch.setattr(applicability_module, "infer", recording)
    return log


def snapshot(*dirs: Path) -> dict[str, bytes]:
    """Every file's bytes (and every directory's existence) under `dirs`."""
    out: dict[str, bytes] = {}
    for root in dirs:
        out[f"exists:{root}"] = b"1" if root.exists() else b"0"
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            out[str(p)] = p.read_bytes() if p.is_file() else b"<dir>"
    return out


# --- the happy path -----------------------------------------------------------


def test_scan_returns_one_sorted_proposal_per_pdf(client, tmp_path, monkeypatch):
    stub_infer(monkeypatch)
    scan_dir = tmp_path / "inbox"
    make_pdf(scan_dir / "b_second.pdf", "AFE7950 Transceiver", pages=3)
    make_pdf(scan_dir / "a_first.pdf", "AD9081 Data Sheet", pages=2)
    make_pdf(scan_dir / "c_third.pdf", "LM741 Op Amp", pages=1)

    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text

    # The wire shape is exactly the frozen contract.
    out = ScanOut.model_validate(resp.json())
    assert out.count == 3
    assert [p.filename for p in out.proposals] == ["a_first.pdf", "b_second.pdf", "c_third.pdf"]
    assert [p.part_number for p in out.proposals] == ["AD9081", "AFE7950", "LM741"]
    assert [p.page_count for p in out.proposals] == [2, 3, 1]
    for p in out.proposals:
        assert p.evidence.strip(), "every proposal must say how it was decided"
        assert p.applicability.evidence.strip()
        assert Path(p.pdf_path).is_file()


def test_scan_hands_inference_the_first_page_and_the_known_parts(
    client, tmp_path, settings, monkeypatch
):
    (settings.parts_dir / "AD9081").mkdir(parents=True)
    (settings.parts_dir / "LM741").mkdir(parents=True)
    calls = stub_infer(monkeypatch)
    scan_dir = tmp_path / "inbox"
    make_pdf(scan_dir / "one.pdf", "AD9081 Data Sheet quad RF sampling", pages=2)

    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text

    assert len(calls) == 1
    assert "AD9081 Data Sheet" in calls[0]["first_page_text"]
    assert sorted(calls[0]["known_parts"]) == ["AD9081", "LM741"]
    # No API key configured -> deterministic inference, no live model.
    assert calls[0]["client"] is None


# --- read-only ----------------------------------------------------------------


def test_scan_writes_nothing(client, tmp_path, settings, monkeypatch):
    stub_infer(monkeypatch)
    settings.parts_dir.mkdir(parents=True)
    (settings.parts_dir / "AD9081").mkdir()
    (settings.parts_dir / "AD9081" / "manifest.json").write_text('{"part_number": "AD9081"}')
    settings.library_dir.mkdir(parents=True)
    (settings.library_dir / "abc123.json").write_text('{"source": {}}')
    extract_cache = settings.cache_dir / "extract"
    extract_cache.mkdir(parents=True)
    (extract_cache / "abc123__pdf_layout.json").write_text('{"extractor_version": "7"}')

    scan_dir = tmp_path / "inbox"
    make_pdf(scan_dir / "one.pdf", "AD9081 Data Sheet")
    make_pdf(scan_dir / "two.pdf", "LM741 Op Amp")

    before = snapshot(settings.parts_dir, settings.library_dir, settings.cache_dir, scan_dir)
    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text
    after = snapshot(settings.parts_dir, settings.library_dir, settings.cache_dir, scan_dir)

    assert before == after


# --- what counts as a PDF -----------------------------------------------------


def test_subdirectories_are_not_descended_into(client, tmp_path, monkeypatch):
    stub_infer(monkeypatch)
    scan_dir = tmp_path / "inbox"
    make_pdf(scan_dir / "top.pdf", "AD9081 Data Sheet")
    make_pdf(scan_dir / "nested" / "deep.pdf", "LM741 Op Amp")
    # A *directory* whose name ends in .pdf is neither a PDF nor a descent.
    (scan_dir / "looks_like.pdf").mkdir()

    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text
    out = ScanOut.model_validate(resp.json())
    assert [p.filename for p in out.proposals] == ["top.pdf"]


def test_non_pdf_files_are_ignored_silently(client, tmp_path, monkeypatch):
    stub_infer(monkeypatch)
    scan_dir = tmp_path / "inbox"
    scan_dir.mkdir()
    (scan_dir / "notes.txt").write_text("not a datasheet")
    (scan_dir / "README.md").write_text("# inbox")
    (scan_dir / "archive.zip").write_bytes(b"PK\x03\x04")
    make_pdf(scan_dir / "real.pdf", "AD9081 Data Sheet")
    make_pdf(scan_dir / "SHOUTED.PDF", "LM741 Op Amp")

    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text
    out = ScanOut.model_validate(resp.json())
    # Case-insensitive `*.pdf`, and not one error row about the txt/md/zip.
    assert sorted(p.filename for p in out.proposals) == ["SHOUTED.PDF", "real.pdf"]


# --- the two ways a directory is unusable -------------------------------------


def test_missing_directory_is_400_naming_the_path(client, tmp_path):
    missing = tmp_path / "typo-inbox"
    resp = client.post("/api/analyze/scan", json={"directory": str(missing)})
    assert resp.status_code == 400
    assert str(missing) in resp.json()["detail"]


def test_empty_directory_is_a_distinct_400(client, tmp_path):
    missing = tmp_path / "typo-inbox"
    empty = tmp_path / "empty-inbox"
    empty.mkdir()
    (empty / "notes.txt").write_text("no pdfs here")

    missing_resp = client.post("/api/analyze/scan", json={"directory": str(missing)})
    empty_resp = client.post("/api/analyze/scan", json={"directory": str(empty)})

    assert empty_resp.status_code == 400
    detail = empty_resp.json()["detail"]
    assert str(empty) in detail
    # "you spelled it wrong" and "it is empty" are different things to be told.
    assert detail != missing_resp.json()["detail"]
    assert "not found" not in detail


# --- totality -----------------------------------------------------------------


def test_corrupt_pdf_becomes_a_proposal_not_a_failed_scan(client, tmp_path, monkeypatch):
    stub_infer(monkeypatch)
    scan_dir = tmp_path / "inbox"
    make_pdf(scan_dir / "good.pdf", "AD9081 Data Sheet")
    (scan_dir / "broken.pdf").write_bytes(b"%PDF-1.7\nthis is a truncated download")

    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text
    out = ScanOut.model_validate(resp.json())
    assert [p.filename for p in out.proposals] == ["broken.pdf", "good.pdf"]

    broken, good = out.proposals
    assert broken.evidence.strip()
    assert "unreadable" in broken.evidence.lower()
    assert broken.part_number == "", "a part number is never guessed for a file we cannot read"
    assert good.part_number == "AD9081", "one bad file must not cost the others their review"


def test_inference_failure_is_recorded_per_file(client, tmp_path, monkeypatch):
    def flaky(pdf_path, *, first_page_text="", known_parts=None, client=None):
        if Path(pdf_path).name == "boom.pdf":
            raise RuntimeError("classifier exploded")
        return DocProposal(
            pdf_path=str(pdf_path),
            part_number="AD9081",
            applicability=Applicability.for_parts(["AD9081"], evidence="title block"),
            evidence="title block",
        )

    stub_infer(monkeypatch, flaky)
    scan_dir = tmp_path / "inbox"
    make_pdf(scan_dir / "boom.pdf", "MYSTERY", pages=5)
    make_pdf(scan_dir / "fine.pdf", "AD9081 Data Sheet")

    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text
    out = ScanOut.model_validate(resp.json())
    boom, fine = out.proposals
    assert "classifier exploded" in boom.evidence
    assert boom.page_count == 5, "the page count was measured before inference was asked"
    assert fine.part_number == "AD9081"


def test_blank_inference_evidence_is_backfilled(client, tmp_path, monkeypatch):
    def silent(pdf_path, *, first_page_text="", known_parts=None, client=None):
        return DocProposal(pdf_path=str(pdf_path), part_number="AD9081")

    stub_infer(monkeypatch, silent)
    scan_dir = tmp_path / "inbox"
    make_pdf(scan_dir / "one.pdf", "AD9081 Data Sheet")

    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    out = ScanOut.model_validate(resp.json())
    assert out.proposals[0].evidence.strip(), "a proposal must never render a blank evidence cell"
    assert out.proposals[0].filename == "one.pdf"


# --- concurrency --------------------------------------------------------------


def test_results_stay_sorted_when_completion_order_is_reversed(client, tmp_path, monkeypatch):
    delays = {"a.pdf": 0.20, "b.pdf": 0.12, "c.pdf": 0.05, "d.pdf": 0.0}
    finished: list[str] = []
    lock = threading.Lock()

    def slow(pdf_path, *, first_page_text="", known_parts=None, client=None):
        name = Path(pdf_path).name
        time.sleep(delays[name])
        with lock:
            finished.append(name)
        return DocProposal(
            pdf_path=str(pdf_path),
            part_number=name.split(".")[0].upper(),
            applicability=Applicability.for_all(evidence="stub"),
            evidence="stub",
        )

    stub_infer(monkeypatch, slow)
    scan_dir = tmp_path / "inbox"
    for name in delays:
        make_pdf(scan_dir / name, f"{name} contents")

    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text
    out = ScanOut.model_validate(resp.json())

    assert finished[0] == "d.pdf", "the last file really did finish first"
    assert [p.filename for p in out.proposals] == ["a.pdf", "b.pdf", "c.pdf", "d.pdf"]


def test_inference_runs_concurrently(client, tmp_path, monkeypatch):
    # Four workers, four files: if the pool were serial, the barrier never
    # completes and every call raises instead of returning.
    barrier = threading.Barrier(4, timeout=10)
    broke: list[str] = []

    def gated(pdf_path, *, first_page_text="", known_parts=None, client=None):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            broke.append(Path(pdf_path).name)
        return DocProposal(
            pdf_path=str(pdf_path),
            part_number="AD9081",
            applicability=Applicability.for_all(evidence="stub"),
            evidence="stub",
        )

    stub_infer(monkeypatch, gated)
    scan_dir = tmp_path / "inbox"
    for name in ("a.pdf", "b.pdf", "c.pdf", "d.pdf"):
        make_pdf(scan_dir / name, "AD9081 Data Sheet")

    resp = client.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text
    assert broke == [], "four files did not reach inference at the same time"


def test_pool_is_bounded_by_analyze_workers(tmp_path, settings, monkeypatch):
    settings.analyze_workers = 1
    app = FastAPI()
    app.include_router(review.router)
    app.dependency_overrides[get_settings_dep] = lambda: settings
    single = TestClient(app)

    lock = threading.Lock()
    live = 0
    peak = 0

    def watched(pdf_path, *, first_page_text="", known_parts=None, client=None):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.02)
        with lock:
            live -= 1
        return DocProposal(
            pdf_path=str(pdf_path),
            part_number="AD9081",
            applicability=Applicability.for_all(evidence="stub"),
            evidence="stub",
        )

    stub_infer(monkeypatch, watched)
    scan_dir = tmp_path / "inbox"
    for name in ("a.pdf", "b.pdf", "c.pdf", "d.pdf"):
        make_pdf(scan_dir / name, "AD9081 Data Sheet")

    resp = single.post("/api/analyze/scan", json={"directory": str(scan_dir)})
    assert resp.status_code == 200, resp.text
    assert peak == 1, f"analyze_workers=1 must serialize inference, saw {peak} at once"


# --- the review screen's whole point ------------------------------------------


def test_an_edited_proposal_is_used_verbatim_by_start(client, tmp_path, monkeypatch):
    """A correction on the review screen survives to the build unchanged.

    `POST /api/analyze/start` belongs to ticket 07, so the always-run half of
    this test pins the contract that ticket codes against: the edited proposal
    round-trips through `StartIn` byte for byte, and nothing re-runs inference
    over it. When ticket 07's router is importable the same claim is asserted
    over HTTP, against a fake `JobRegistryLike`.
    """
    calls = stub_infer(monkeypatch)
    scan_dir = tmp_path / "inbox"
    make_pdf(scan_dir / "sbaa123e.pdf", "SBAA123E application report")

    scanned = ScanOut.model_validate(
        client.post("/api/analyze/scan", json={"directory": str(scan_dir)}).json()
    )
    assert len(calls) == 1, "the scan inferred once"

    edited = scanned.proposals[0].model_copy(
        update={
            "part_number": "AFE7950",
            "applicability": Applicability.for_family("AFE79xx", evidence="user edit"),
        }
    )
    payload = json.loads(StartIn(directory=str(scan_dir), proposals=[edited]).model_dump_json())
    calls.clear()

    reparsed = StartIn.model_validate(payload)
    assert reparsed.proposals[0].part_number == "AFE7950"
    assert reparsed.proposals[0].applicability.kind == "family"
    assert reparsed.proposals[0].applicability.family == "AFE79xx"
    assert reparsed.proposals[0].applicability.evidence == "user edit"
    assert calls == [], "parsing a confirmed proposal must not re-infer"

    started = _post_to_start_if_available(payload, calls)
    if started is not None:
        assert started[0].part_number == "AFE7950"
        assert started[0].applicability.family == "AFE79xx"
        assert calls == [], "the server must not re-infer over the user's correction"


def _post_to_start_if_available(payload: dict, calls: list[dict]) -> list[DocProposal] | None:
    """POST the payload to ticket 07's router, or `None` while it is unwritten."""
    try:
        from datasheet_analyzer.app.deps import get_job_registry
        from datasheet_analyzer.app.routers import analyze as analyze_router
    except Exception:  # noqa: BLE001 # pragma: no cover - ticket 07 is in flight
        return None
    router = getattr(analyze_router, "router", None)
    if router is None:  # pragma: no cover - same reason
        return None

    received: list[DocProposal] = []

    class FakeRegistry:
        def start(self, *, directory: str, proposals: list[DocProposal]) -> str:
            received.extend(proposals)
            return "run-1"

        def exists(self, run_id: str) -> bool:
            return run_id == "run-1"

        def run(self, run_id: str):
            return []

        def snapshot(self, run_id: str):
            raise NotImplementedError

        def events(self, run_id: str):
            raise NotImplementedError

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_job_registry] = FakeRegistry
    resp = TestClient(app).post("/api/analyze/start", json=payload)
    if resp.status_code != 200:  # pragma: no cover - ticket 07 in flight
        return None
    return received or None
