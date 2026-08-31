"""Infer a document's part number and the parts it applies to (ticket 02).

**Signature frozen by ticket 00; the body is ticket 02's.**

Nothing in the repo does this today: the part number has always been supplied
by the caller (`dsa build --part`) or taken from the filename stem, which is
wrong for `sbas123e.pdf` — a document ID, not a device.

`infer()` runs deterministic-first, in two stages:

1. **Sweep** the title block for a part token (letters + digits, 4–12 chars,
   at least two digits: `AD9081`, `AFE7950`, `LM741`) and a family token (the
   same with a trailing `xx`/`x` wildcard: `AFE79xx`). Rank by position — a
   datasheet names its part in the first lines — and by presence in
   `known_parts`.
2. **Classify** only when the sweep is ambiguous. Exactly one part token and
   no family token returns immediately with **no model call**. Otherwise ask
   `client` for one structured judgement; a `None` client, a raised error, or
   malformed JSON falls back to the sweep, and to `Applicability(kind="all")`
   when the sweep found nothing.

`evidence` is never blank. It records how the decision was reached — the
matched line and its page, `llm:<model>`, or `fallback: no part token found` —
the same discipline `SourceDocument.vendor_evidence` carries: an inferred
value that cannot say why cannot be corrected by a human.

Inference **never writes**. It returns a proposal; ticket 08 shows it on the
review screen and ticket 03 persists only what came back confirmed.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from datasheet_analyzer.app.contracts import DocProposal
from datasheet_analyzer.enrich.llm import LLMClient
from datasheet_analyzer.models import Applicability

log = logging.getLogger(__name__)

__all__ = ["infer"]

# A part-number *shape*: starts with a letter, 4–12 characters of letters and
# digits. The two-digit floor below does the rest of the filtering — it is
# what keeps `Features`, `Table`, `DDR4` and a bare year out of the sweep.
_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z0-9]{3,11}\b")
_MIN_DIGITS = 2
# A family token is the same shape with a trailing run of `x`/`X`
# (`AFE79xx`). Only the *trailing* form is ever proposed; `Applicability.
# covers()` additionally understands embedded wildcards (`AD90x1`), but a
# sweep cannot tell an embedded `x` from a letter in a real part number.
_TRAILING_WILDCARD = re.compile(r"[xX]+$")

# Literature numbers are document IDs, not devices: `sbas123e.pdf` is the
# datasheet *of* AFE7950. `inventory._HINTS` already reads these prefixes as
# document identifiers when it routes doc types; the sweep drops them so a
# footer or a cover page printing the doc ID can never outrank the title
# block. Four letters then three digits (`SBAS123`, `SWRA486`, `ZHCA123`) —
# a real part number puts a digit inside the first four characters
# (`SN74LVC`, `STM32F4`), so it does not collide.
_DOC_ID = re.compile(r"^(?:S[A-Z]{3}|ZHC[A-Z]|TID[AU])\d{3}", re.IGNORECASE)
# Interface standards that pass the shape test and are never a part number:
# `JESD204C`, `RS485`, `USB3`. Excluding one costs at worst a fallback to
# another token; keeping one puts a bus name on the review screen as a device.
_STANDARD = re.compile(r"^(?:JESD|IEEE|RS|USB|PCIE|SATA|LPDDR|DDR)\d", re.IGNORECASE)

# The first page *is* the title block for ranking purposes, but a text layer
# can be pathological; bound both the scan and what evidence quotes.
_MAX_LINES = 200
_MAX_EVIDENCE_LINE = 120
_MAX_PROMPT_CHARS = 4000
_CLASSIFY_MAX_TOKENS = 400

_NO_TOKEN = "fallback: no part token found"

_SYSTEM = (
    "You identify which semiconductor parts a datasheet or application note is "
    "about, from its first page. Answer with one JSON object and nothing else."
)


@dataclass(frozen=True)
class _Hit:
    """One part-number-shaped token found in the title block."""

    token: str  # normalized: `AFE7950`, or `AFE79xx` for a family
    is_family: bool
    line: str
    line_no: int
    col: int
    known: bool

    @property
    def rank(self) -> tuple[int, int, int]:
        """Lower sorts first: a known part beats an unknown one, then position."""
        return (0 if self.known else 1, self.line_no, self.col)

    @property
    def evidence(self) -> str:
        """The matched line and its page — what a human needs to judge the guess."""
        return f'page 1: "{self.line}"'


@dataclass
class _Sweep:
    parts: list[_Hit] = field(default_factory=list)
    families: list[_Hit] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.parts and not self.families

    @property
    def best(self) -> _Hit | None:
        """The top-ranked hit of either kind — the deterministic fallback."""
        hits = self.parts + self.families
        return min(hits, key=lambda h: h.rank) if hits else None

    @property
    def best_part(self) -> _Hit | None:
        return min(self.parts, key=lambda h: h.rank) if self.parts else None


#: A filename stem that is a document number rather than a part number.
#: TI ships `sbas123e.pdf`, ADI ships `AD9081.pdf`, Mini-Circuits ships
#: `PMA1-14LN+.pdf`. Only the first is useless, and it is recognisable: a
#: vendor doc-number prefix followed by digits and an optional revision letter.
_DOC_NUMBER = re.compile(
    r"^(sbas|slas|snas|sbos|slos|sllс|sprs|swra|swaa|sboa|slva|snva|an|ug|tidu)"
    r"[a-z]*\d+[a-z]?$",
    re.IGNORECASE,
)


def filename_candidate(path: Path) -> str:
    """The filename stem as a part-number candidate, or `""`.

    Vendors split two ways: Mini-Circuits, Qorvo and ADI name the file after
    the part (`PMA1-14LN+.pdf`), while TI names it after the document
    (`sbas123e.pdf`). Reading only the text got `LHA-83W+.pdf` filed as
    `DQ1225`; reading only the filename would file `sbas123e.pdf` as
    `SBAS123E`, which SPEC user story #2 exists to prevent. So the filename is
    a *candidate*, and `corroborate` decides.
    """
    stem = (path.stem or "").strip()
    if len(stem) < 3 or _DOC_NUMBER.match(stem):
        return ""
    # A part number carries at least one digit; a title does not.
    if not any(ch.isdigit() for ch in stem):
        return ""
    return stem.upper()


def corroborate(filename: str, text: str, sweep_tokens: list[str]) -> tuple[str, str] | None:
    """The part number the filename and the page agree on, with why.

    Agreement is the whole idea: a filename that also appears in the document's
    own text is far stronger evidence than either alone, and it is exactly the
    case both single-source rules got wrong.
    """
    if not filename:
        return None
    haystack = (text or "").upper()
    if any(filename == token.strip().upper() for token in sweep_tokens):
        return filename, f'filename "{filename}" is also named in the document text'
    if filename in haystack:
        return filename, f'filename "{filename}" appears on the first page'
    return None


def infer(
    pdf_path: Path,
    *,
    first_page_text: str = "",
    known_parts: list[str] | None = None,
    client: LLMClient | None = None,
) -> DocProposal:
    """Propose the part number and applicability for one PDF.

    `first_page_text` is passed in rather than read here so a caller that has
    already opened the file (the scan endpoint reads the first page and the
    page count in one pass) does not open it twice. `known_parts` is the
    built-part list; a token that names an existing part outranks one that
    does not. `client` is optional — every path must fall back
    deterministically without it.
    """
    path = Path(pdf_path)
    known = {p.strip().upper() for p in (known_parts or []) if p and p.strip()}
    text = first_page_text or ""
    page_count = 0
    if not text.strip():
        # Only the caller-didn't-read-it path opens the file, and it opens it
        # once — the page count comes back from the same open.
        text, page_count = _read_first_page(path)

    sweep = _sweep(text, known)
    proposal = DocProposal(pdf_path=str(path), filename=path.name, page_count=page_count)

    # --- stage 0: corroboration ----------------------------------------------
    # Before anything else, ask whether the filename and the page agree. When
    # they do, that is the strongest evidence available and it settles the part
    # number outright — which is what makes `PMA1-14LN+.pdf` and `sbas123e.pdf`
    # both come out right instead of trading one for the other.
    agreed = corroborate(filename_candidate(path), text, [hit.token for hit in sweep.parts])
    if agreed is not None and not sweep.families:
        token, why = agreed
        proposal.part_number = token
        proposal.evidence = why
        proposal.applicability = Applicability.for_parts([token], evidence=why)
        return proposal

    # --- stage 1: deterministic ---------------------------------------------
    if sweep.empty:
        # Nothing named a part. Degrade to every part (ADR 0005's honest
        # default) and fall back to the filename stem for a display name,
        # saying in `evidence` that that is what happened.
        stem = path.stem.strip()
        proposal.part_number = stem.upper()
        proposal.evidence = f'{_NO_TOKEN}; filename stem "{stem}"' if stem else _NO_TOKEN
        proposal.applicability = Applicability.for_all(evidence=_NO_TOKEN)
        return proposal

    if len(sweep.parts) == 1 and not sweep.families:
        hit = sweep.parts[0]
        proposal.part_number = hit.token
        proposal.evidence = hit.evidence
        proposal.applicability = Applicability.for_parts([hit.token], evidence=hit.evidence)
        return proposal

    # --- stage 2: classify ---------------------------------------------------
    if client is None:
        return _from_sweep(proposal, sweep, "no classifier available")
    try:
        raw = client.complete(
            _SYSTEM, _build_prompt(path, text, sweep, known), _CLASSIFY_MAX_TOKENS
        )
    except Exception as exc:  # noqa: BLE001 - a classifier is never load-bearing
        log.warning("applicability classifier failed for %s: %s", path.name, exc)
        return _from_sweep(proposal, sweep, f"classifier error ({type(exc).__name__})")

    verdict = _parse_verdict(raw)
    if verdict is None:
        log.warning("applicability classifier returned unusable JSON for %s", path.name)
        return _from_sweep(proposal, sweep, "classifier returned malformed JSON")

    applicability, part_number, reason = verdict
    model = getattr(client, "model", "") or "unknown"
    evidence = f"llm:{model}" + (f" — {reason}" if reason else "")
    applicability.evidence = evidence
    proposal.applicability = applicability
    proposal.evidence = evidence
    if not part_number:
        best = sweep.best_part or sweep.best
        part_number = best.token if best else path.stem.upper()
    proposal.part_number = part_number
    return proposal


# --- stage 1 -----------------------------------------------------------------


def _read_first_page(path: Path) -> tuple[str, int]:
    """First page text and page count, or `("", 0)` for anything unreadable."""
    try:
        with fitz.open(path) as doc:
            count = doc.page_count
            text = doc[0].get_text() if count else ""
        return text, count
    except Exception as exc:  # noqa: BLE001 - an unreadable PDF is a blank sweep
        log.warning("could not read first page of %s: %s", path, exc)
        return "", 0


def _sweep(text: str, known: set[str]) -> _Sweep:
    """Regex the title block for part and family tokens, deduped, ranked."""
    sweep = _Sweep()
    seen: set[str] = set()
    for line_no, raw_line in enumerate(text.splitlines()[:_MAX_LINES]):
        line = _tidy(raw_line)
        if not line:
            continue
        for match in _TOKEN.finditer(raw_line):
            token, is_family = _classify_token(match.group(0))
            if not token or token.upper() in seen:
                continue
            seen.add(token.upper())
            hit = _Hit(
                token=token,
                is_family=is_family,
                line=line,
                line_no=line_no,
                col=match.start(),
                known=token.upper() in known,
            )
            (sweep.families if is_family else sweep.parts).append(hit)
    sweep.parts.sort(key=lambda h: h.rank)
    sweep.families.sort(key=lambda h: h.rank)
    return sweep


def _classify_token(raw: str) -> tuple[str, bool]:
    """`(normalized token, is_family)`, or `("", False)` when it is not one.

    Part numbers normalize to upper case (`afe7950` and `AFE7950` are one
    device); a family keeps its wildcard run lower case because `AFE79xx` is
    how a vendor prints it and how the review screen should show it back.
    """
    upper = raw.upper()
    if _DOC_ID.match(upper) or _STANDARD.match(upper):
        return "", False
    wildcard = _TRAILING_WILDCARD.search(raw)
    if wildcard:
        stem = raw[: wildcard.start()]
        if len(stem) >= 2 and sum(c.isdigit() for c in stem) >= _MIN_DIGITS:
            return stem.upper() + "x" * len(wildcard.group(0)), True
        return "", False
    if sum(c.isdigit() for c in raw) >= _MIN_DIGITS:
        return upper, False
    return "", False


def _tidy(line: str) -> str:
    collapsed = " ".join(line.split())
    if len(collapsed) > _MAX_EVIDENCE_LINE:
        collapsed = collapsed[: _MAX_EVIDENCE_LINE - 1].rstrip() + "…"
    return collapsed


def _from_sweep(proposal: DocProposal, sweep: _Sweep, reason: str) -> DocProposal:
    """The deterministic fallback: the sweep's best guess, saying it was one."""
    best = sweep.best
    if best is None:  # unreachable — callers check `sweep.empty` first
        proposal.evidence = _NO_TOKEN
        proposal.applicability = Applicability.for_all(evidence=_NO_TOKEN)
        return proposal
    evidence = f"fallback: {reason}; {best.evidence}"
    if best.is_family:
        proposal.applicability = Applicability.for_family(best.token, evidence=evidence)
        part = sweep.best_part
        proposal.part_number = part.token if part else best.token
    else:
        proposal.applicability = Applicability.for_parts([best.token], evidence=evidence)
        proposal.part_number = best.token
    proposal.evidence = evidence
    return proposal


# --- stage 2 -----------------------------------------------------------------


def _build_prompt(path: Path, text: str, sweep: _Sweep, known: set[str]) -> str:
    candidates = ", ".join(h.token for h in sweep.parts + sweep.families) or "none"
    return (
        f"Filename: {path.name}\n"
        f"Tokens swept from the first page: {candidates}\n"
        f"Parts already in the library: {', '.join(sorted(known)) or 'none'}\n\n"
        "First page text:\n"
        f"{text[:_MAX_PROMPT_CHARS]}\n\n"
        "Which parts does this document cover?\n"
        'Reply with exactly one JSON object: {"kind": "parts"|"family"|"all", '
        '"parts": ["AD9081"], "family": "AFE79xx", "part_number": "AD9081", '
        '"reason": "<short>"}\n'
        '- "parts": it names specific devices; list every one.\n'
        '- "family": it covers a wildcard family such as AFE79xx.\n'
        '- "all": it is generic and names no device.\n'
        '"part_number" is the single device the document is filed under '
        "(empty when there is none)."
    )


def _parse_verdict(raw: str) -> tuple[Applicability, str, str] | None:
    """Strict parse of the classifier's reply, or `None` for a failure.

    Malformed output is a *failure*, not something to read loosely: a reply
    the model did not shape as asked is a reply whose meaning is unknown, and
    guessing at it would put an unevidenced part number on the review screen.
    Only an exact JSON object — optionally inside one fenced code block — is
    accepted, and only with a kind the model was offered.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        # An exact unwrap of one fenced block, not a scan for braces.
        body = text[3:]
        if body[:4].lower() == "json":
            body = body[4:]
        if not body.rstrip().endswith("```"):
            return None
        text = body.rstrip()[:-3].strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    kind = payload.get("kind")
    if kind not in ("parts", "family", "all"):
        return None
    reason = payload.get("reason")
    reason = _tidy(reason) if isinstance(reason, str) else ""

    if kind == "parts":
        raw_parts = payload.get("parts")
        if not isinstance(raw_parts, list):
            return None
        parts: list[str] = []
        for item in raw_parts:
            if not isinstance(item, str) or not item.strip():
                continue
            token = item.strip().upper()
            if token not in parts:
                parts.append(token)
        applicability = Applicability.for_parts(parts)
    elif kind == "family":
        family = payload.get("family")
        if not isinstance(family, str):
            return None
        applicability = Applicability.for_family(family.strip())
    else:
        applicability = Applicability.for_all()

    if not applicability.is_valid:
        # `parts: []` and a blank family are inert writes, never stored.
        return None

    named = payload.get("part_number")
    part_number = named.strip().upper() if isinstance(named, str) else ""
    if not part_number and applicability.kind == "parts":
        part_number = applicability.parts[0]
    return applicability, part_number, reason
