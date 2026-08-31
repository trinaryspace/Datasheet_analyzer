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
from datasheet_analyzer.app import proposalcache
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
from datasheet_analyzer.extract.pdf_structure import compute_content_hash
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


#: How deep the walk goes before it stops descending. A shelf nested deeper
#: than this is almost certainly a checkout or an archive that was dropped in
#: by accident, and walking it costs minutes.
MAX_SCAN_DEPTH = 8

#: Directory names never descended into. The first three are the tool's own
#: output — a folder that *contains* a corpus would otherwise offer to rebuild
#: from the PDFs it already published. The rest are dependency and VCS trees
#: that hold nothing a person put there to be read.
SKIP_DIRS = frozenset(
    {"parts", "library", "projects", ".cache", "node_modules", "__pycache__", ".venv"}
)


def _skip_reason_for(entry: Path, depth: int) -> str:
    """Why this directory is not descended into, or `""` to descend."""
    if entry.name.startswith("."):
        return "hidden directory"
    if entry.name in SKIP_DIRS:
        return "not a source directory"
    if entry.is_symlink():
        # Never followed: a symlink into a parent is an infinite walk, and
        # resolving them would also let a scan reach outside the folder the
        # user actually opened.
        return "symlink"
    if depth >= MAX_SCAN_DEPTH:
        return f"deeper than {MAX_SCAN_DEPTH} levels"
    return ""


def _pdfs_in(directory: Path) -> tuple[list[Path], list[str]]:
    """Every `*.pdf` under `directory`, and the directories deliberately skipped.

    Recursive, unlike `batch.discover_jobs`, which reads direct children only.
    A person points the workbench at the folder their design lives in, and the
    datasheets are somewhere inside it — often in a `datasheets/` beside the
    schematic rather than at the top.

    Skips are *returned*, never swallowed: a scan that quietly ignored half a
    shelf looks identical to one that found everything, and the user has no
    way to tell which happened.

    Sorted by path so the review reads in folder order, and so two runs over
    an unchanged tree produce the same list.
    """
    found: list[Path] = []
    skipped: list[str] = []

    def walk(here: Path, depth: int) -> None:
        try:
            entries = sorted(here.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:  # unreadable directory is a skip, not a crash
            skipped.append(f"{here.name or here}: {exc.strerror or 'unreadable'}")
            return
        for entry in entries:
            if entry.is_dir():
                reason = _skip_reason_for(entry, depth + 1)
                if reason:
                    skipped.append(f"{_relative(entry, directory)} ({reason})")
                else:
                    walk(entry, depth + 1)
            # `is_file()` also disposes of a *directory* named `something.pdf`,
            # which is neither a PDF nor a thing to descend into.
            elif entry.is_file() and entry.suffix.lower() == ".pdf":
                found.append(entry)

    walk(directory, 0)
    found.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))
    return found, skipped


def _relative(path: Path, root: Path) -> str:
    """`path` as the user would name it: relative to the folder they opened.

    The root itself is `""`, not `"."` — the review groups on this string and
    a group headed "." reads as a directory that does not exist.
    """
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
    return "" if rel == "." else rel


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


#: Words that appear on the first page of almost every source document and
#: almost no purchase order. Deliberately generic: this decides only whether a
#: row starts ticked, so a false negative costs one click and a false positive
#: costs a wasted build — neither is worth a model call to avoid.
_SOURCE_DOCUMENT_HINTS = (
    "datasheet",
    "data sheet",
    "specification",
    "electrical characteristics",
    "absolute maximum",
    "pin configuration",
    "features",
    "application note",
    "errata",
    "register map",
    "user guide",
    "reference manual",
    "typical performance",
    "ordering information",
)


def looks_like_source_document(proposal: DocProposal, first_page_text: str) -> bool:
    """Whether this reads like something the pipeline should build.

    A recursive walk reaches purchase orders, mechanical drawings and meeting
    notes that happen to live beside the datasheets. Those start unticked
    rather than hidden — the user confirms rather than hunts, and a wrong
    guess here is one click to undo.

    Deliberately a text heuristic and not a model call. The classification
    pass has already run by this point and is about *applicability*, not about
    whether the file belongs at all; asking a second question of the model
    would double the cost of the thing this change exists to make cheap.
    """
    haystack = f"{first_page_text} {proposal.filename}".lower()
    if any(hint in haystack for hint in _SOURCE_DOCUMENT_HINTS):
        return True
    # No hint, but inference found a part number in the text: that is evidence
    # enough, and it is how an unusual vendor's layout still gets through.
    return bool(proposal.part_number.strip()) and "fallback" not in proposal.evidence.lower()


def _propose(
    pdf_path: Path,
    *,
    known_parts: list[str],
    client: LLMClient | None,
    settings: Settings,
) -> DocProposal:
    """One PDF's proposal. Never raises — a failure becomes its `evidence`."""
    # Hashing the bytes costs milliseconds; inferring costs a model call. A
    # document whose bytes we have already classified needs neither the read
    # below nor the call after it, which is what makes reopening a folder of
    # two hundred PDFs a directory walk rather than two hundred requests.
    try:
        content_hash = compute_content_hash(pdf_path)
    except OSError as exc:
        log.warning("scan: cannot hash %s: %s", pdf_path, exc)
        return _failed_proposal(pdf_path, f"unreadable pdf: {type(exc).__name__}: {exc}")

    cached = proposalcache.get(content_hash, settings=settings)
    if cached is not None:
        return proposalcache.merge(cached, pdf_path=pdf_path, page_count=cached.page_count)

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
    fresh = proposal.model_copy(
        update={
            "pdf_path": str(pdf_path),
            "filename": pdf_path.name,
            "page_count": page_count,
            "content_hash": proposal.content_hash or content_hash,
            "evidence": proposal.evidence or "inference recorded no evidence",
            "is_datasheet": looks_like_source_document(proposal, first_page_text),
        }
    )
    proposalcache.put(fresh, settings=settings)
    return fresh


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
    pdfs, skipped = _pdfs_in(path)
    if not pdfs:
        raise HTTPException(status_code=400, detail=f"no PDF files anywhere under directory: {raw}")

    known_parts = [d.name for d in discover_parts(settings.parts_dir)]
    client = _llm_client(settings)

    def one(pdf_path: Path) -> DocProposal:
        proposal = _propose(pdf_path, known_parts=known_parts, client=client, settings=settings)
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
        # Where it sits under the folder the user opened, so the review can
        # group by subdirectory and two files both called `datasheet.pdf` are
        # distinguishable.
        proposal.relative_dir = _relative(pdf_path.parent, path)
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
        skipped=skipped,
    )


@router.post("/scan", response_model=ScanOut)
def scan(payload: ScanIn, settings: SettingsDep) -> ScanOut:
    """Propose one `DocProposal` per PDF in `payload.directory`. Writes nothing."""
    return scan_directory(payload.directory, settings)
