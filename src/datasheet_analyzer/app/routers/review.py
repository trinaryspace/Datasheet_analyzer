"""`POST /api/analyze/scan` — propose, never build (ticket 08).

The review screen exists so a wrong inference is caught in one glance rather
than discovered later inside a wrong answer. This router is what fills it: one
`DocProposal` per PDF in a directory, carrying the inferred part number, the
inferred applicability, and the evidence for both.

Three properties are load-bearing and are what the tests pin:

- **Read-only.** A scan opens each PDF exactly far enough to read the first
  page's text and the page count, then hands both to
  `acquire.applicability.infer()`. It never extracts, never publishes, never
  touches the library and never writes to the extraction cache — `parts_dir`,
  `library_dir` and `cache_dir` are byte-identical before and after.
- **Total.** A file that cannot be opened, or an inference that raises, yields
  a proposal whose `evidence` names the failure. One corrupt PDF in a
  directory of forty must not cost the other thirty-nine their review.
- **Ordered.** Inference runs in a pool bounded by `settings.analyze_workers`
  because forty PDFs is slow enough to notice, but the response is always in
  filename order — the row a user is reading must not move because another
  file finished first.

Directory handling copies `batch.discover_jobs()`: direct children only, no
recursion, `*.pdf` case-insensitive, sorted. Non-PDF files are ignored rather
than reported. A missing directory and an existing directory holding no PDFs
are two *different* 400s, both naming the path — a typo must never silently
scan nothing, and "you spelled it wrong" and "it is empty" are different
things to be told.

A proposal is a proposal: nothing here is authoritative. The user edits it and
`POST /api/analyze/start` (ticket 07) uses what came back verbatim, without
re-inferring over the correction.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated

import fitz
from fastapi import APIRouter, Depends, HTTPException

from datasheet_analyzer.acquire import applicability as applicability_module
from datasheet_analyzer.app.buildstate import classify
from datasheet_analyzer.app.contracts import (
    API_PREFIX,
    Applicability,
    DocProposal,
    ScanIn,
    ScanOut,
)
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.config import Settings
from datasheet_analyzer.enrich.llm import LLMClient
from datasheet_analyzer.retrieve.index import discover_parts

log = logging.getLogger(__name__)

__all__ = ["router", "scan_directory"]

router = APIRouter(prefix=f"{API_PREFIX}/analyze", tags=["analyze"])

#: Injected rather than read from the module: a test points one scan at a
#: temporary tree by overriding this dependency, never by editing the env.
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]

#: How many characters of the first page inference is given. A title block is
#: the first few lines; feeding a whole dense page is cost without signal.
FIRST_PAGE_CHARS = 4000


def _pdfs_in(directory: Path) -> list[Path]:
    """Direct-child `*.pdf` files, sorted by filename (`discover_jobs`'s rule).

    `is_file()` also disposes of the pathological case of a *directory* named
    `something.pdf`, which is neither a PDF nor a thing to descend into.
    """
    return sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
        key=lambda p: p.name,
    )


def _read_head(pdf_path: Path) -> tuple[str, int]:
    """First page's text and the document's page count, in one open.

    Raises whatever PyMuPDF raises for a file it cannot open; the caller turns
    that into a proposal rather than into a failed scan.
    """
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count
        text = doc[0].get_text() if page_count else ""
    return text[:FIRST_PAGE_CHARS], page_count


def _failed_proposal(pdf_path: Path, reason: str) -> DocProposal:
    """The honest proposal for a file inference could not speak about.

    `part_number` stays blank rather than falling back to the filename stem:
    `sbas123e.pdf` is a document ID, not a device, and a guessed part number
    on a review screen is exactly the wrong inference this screen exists to
    catch. `all` applicability is the same honest degrade the model documents.
    """
    return DocProposal(
        pdf_path=str(pdf_path),
        filename=pdf_path.name,
        part_number="",
        applicability=Applicability.for_all(evidence=reason),
        evidence=reason,
        page_count=0,
    )


def _llm_client(settings: Settings) -> LLMClient | None:
    """A client when a key is configured, `None` otherwise.

    Inference must fall back deterministically without one (ticket 02), so a
    missing key is a normal mode, not an error — and a test never has one.
    """
    if not settings.llm_available:
        return None
    try:
        from datasheet_analyzer.enrich.llm import AnthropicClient

        return AnthropicClient(settings.anthropic_api_key, settings.model)
    except Exception as exc:  # noqa: BLE001 - a client is an optimization here
        log.warning(
            "scan: no LLM client (%s: %s); inference stays deterministic", type(exc).__name__, exc
        )
        return None


def _propose(
    pdf_path: Path,
    *,
    known_parts: list[str],
    client: LLMClient | None,
) -> DocProposal:
    """One PDF's proposal. Never raises — a failure becomes its `evidence`."""
    try:
        first_page_text, page_count = _read_head(pdf_path)
    except Exception as exc:  # noqa: BLE001 - one bad file is not a bad scan
        log.warning("scan: cannot read %s: %s", pdf_path, exc)
        return _failed_proposal(pdf_path, f"unreadable pdf: {type(exc).__name__}: {exc}")

    try:
        proposal = applicability_module.infer(
            pdf_path,
            first_page_text=first_page_text,
            known_parts=known_parts,
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 - inference failure is reviewable
        log.warning("scan: inference failed for %s: %s", pdf_path, exc)
        failed = _failed_proposal(pdf_path, f"inference failed: {type(exc).__name__}: {exc}")
        return failed.model_copy(update={"page_count": page_count})

    # The scan owns the three facts it measured itself; inference owns the
    # rest. `evidence` is backfilled rather than left blank because an
    # inferred value that cannot say why cannot be corrected by a human.
    return proposal.model_copy(
        update={
            "pdf_path": str(pdf_path),
            "filename": pdf_path.name,
            "page_count": page_count,
            "evidence": proposal.evidence or "inference recorded no evidence",
        }
    )


def scan_directory(directory: str, settings: Settings) -> ScanOut:
    """Scan one directory into proposals. The endpoint is a thin wrapper.

    Raises `HTTPException(400)` for the two ways a directory is unusable, each
    naming the path exactly as the user typed it.
    """
    raw = (directory or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="scan directory not given")
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"scan directory not found: {raw}")
    pdfs = _pdfs_in(path)
    if not pdfs:
        raise HTTPException(status_code=400, detail=f"no PDF files in directory: {raw}")

    known_parts = [d.name for d in discover_parts(settings.parts_dir)]
    client = _llm_client(settings)

    def one(pdf_path: Path) -> DocProposal:
        proposal = _propose(pdf_path, known_parts=known_parts, client=client)
        # Classified here rather than on the client: it takes a manifest read
        # per part, and the browser has neither the manifests nor the gate.
        state, reason = classify(
            pdf_path,
            proposal.part_number,
            proposal.content_hash,
            settings=settings,
        )
        proposal.build_state = state
        proposal.build_reason = reason
        return proposal

    workers = max(1, min(int(settings.analyze_workers), len(pdfs)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dsa-scan") as pool:
        # `map` yields in *submission* order, so a file that finishes first
        # never overtakes the row above it.
        proposals = list(pool.map(one, pdfs))

    states: dict[str, int] = {}
    for proposal in proposals:
        states[proposal.build_state] = states.get(proposal.build_state, 0) + 1

    return ScanOut(
        directory=str(path),
        proposals=proposals,
        count=len(proposals),
        states=states,
    )


@router.post("/scan", response_model=ScanOut)
def scan(payload: ScanIn, settings: SettingsDep) -> ScanOut:
    """Propose one `DocProposal` per PDF in `payload.directory`. Writes nothing."""
    return scan_directory(payload.directory, settings)
