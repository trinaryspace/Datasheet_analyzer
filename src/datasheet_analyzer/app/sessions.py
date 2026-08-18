"""`SessionStore` — conversations that survive a restart (ticket 15).

**Signatures frozen by ticket 00; bodies are ticket 15's.**

One JSON file per `ChatSession` under `settings.sessions_dir`, holding its
messages, their citations and the scope each answer was drawn under. Ticket
12 appends to it; this module owns the storage and the two exports.

Export is the point, not a convenience:

- `export_markdown()` is what a user pastes into a design review — the claim,
  its citation in the repo's own `§4.5, p.7` form (from `Citation.label`,
  never re-formatted here), and the part it was answered under. `label`
  deliberately omits the part because printing it is a front end's job, so
  the exporter is the thing that adds it back.
- `export_golden()` is the second payoff. AGENTS.md invariant 5 makes golden
  Q&A the objective function, and a confirmed answer is nearly a
  `tests/fixtures/golden_qa_<PART>.yaml` entry already: a question, expected
  substrings, and the pages it must cite.

Writes are atomic and Windows-safe (temp then `.replace()` with a
`PermissionError` retry), matching `pipeline.py`. Session ids are opaque and
generated server-side: **a client-supplied id is never used as a filename.**

Three rules the rest of the system depends on:

- **A bad file is skipped, never fatal.** Malformed JSON, or a transcript
  that no longer validates, is logged and skipped so `list()` still returns
  the readable rest of the shelf — the same honest-degradation rule
  `library/store.py` follows.
- **Appending never rewrites history.** `append()` is a read-modify-write
  that adds one message and bumps `updated_at`; the earlier messages, their
  citations and `created_at` come back out of the copy untouched.
- **The golden export is a draft, not a verdict.** It carries the answer's
  own values as `expected_substrings` and the pages its citations actually
  pinned, and says in its header that a human confirms it before it becomes
  a fixture. An unpinned citation contributes no page rather than a guessed
  one.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from datasheet_analyzer.config import Settings, get_settings
from datasheet_analyzer.models import ChatMessage, ChatSession, CitationOut, ScopeRef

log = logging.getLogger(__name__)

__all__ = ["SessionStore", "new_session_id", "render_golden", "render_markdown"]

# A session id is a filename. Anything that is not a plain token could walk
# out of `sessions_dir`, so it is refused rather than joined onto a path —
# the same guard `library/store.py` puts on a content hash.
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")

#: A citation as *printed* (`§6.5, p.7`, `p.29-37`). Stripped out of an
#: answer before values are harvested for the golden export, so a page number
#: in a citation never becomes an expected substring.
_CITATION_NOISE = re.compile(r"§[^\s,;)]+|p\.\s?\d+(?:\s?-\s?\d+)?", re.IGNORECASE)

#: A number, optionally signed and optionally carrying a unit — the shape of
#: the thing a datasheet answer is actually judged on ("±22 V", "500 mW").
_VALUE = re.compile(r"[±+-]?\d+(?:\.\d+)?(?:\s?[A-Za-zµμΩ°%][A-Za-zµμΩ°%/]{0,4})?")

#: Words that look like a unit to the regex and are not one. Without this,
#: "1 and" and "3 of" become expected substrings.
_UNIT_STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "by", "for", "in", "is", "of", "on", "or", "the", "to"}
)

#: Cap on the values one answer contributes, and on the characters of the
#: fallback sentence when it contributes none.
_MAX_SUBSTRINGS = 4
_MAX_FALLBACK_CHARS = 120

#: A citation claiming a range wider than this is treated as a mistake and
#: contributes only its first page: a golden entry naming 300 pages is not
#: ground truth.
_MAX_PAGE_SPAN = 50


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_session_id() -> str:
    """An opaque, filename-safe id generated **server-side, always**.

    Opaque on purpose: a client that could choose this string would be
    choosing a path under `sessions_dir`.
    """
    return uuid.uuid4().hex


class SessionStore:
    """Saved conversations, one JSON file each, newest-first on listing."""

    def __init__(self, sessions_dir: Path | str) -> None:
        """Bind the store to a directory; no filesystem side effects here."""
        self.sessions_dir = Path(sessions_dir)

    @classmethod
    def for_settings(cls, settings: Settings | None = None) -> SessionStore:
        """The store for `settings.sessions_dir` (cached settings by default)."""
        return cls((settings or get_settings()).sessions_dir)

    # --- reads ----------------------------------------------------------------

    def get(self, session_id: str) -> ChatSession | None:
        """The full transcript, or `None` for an unknown id (the router 404s).

        An id that is not a plain token is `None` too, not an exception and
        never a path join: this is the only place a caller-supplied string
        meets the filesystem.
        """
        path = self._path_for(session_id)
        if path is None:
            return None
        return _read_session(path)

    def list(self) -> list[ChatSession]:
        """Every readable session, newest first; a malformed file is skipped.

        Newest is by `updated_at` — the last time the conversation was
        *touched*, which is what a user is looking for — with the id as a
        tie-break so two sessions saved in the same clock tick still order
        deterministically.
        """
        try:
            entries = sorted(self.sessions_dir.glob("*.json"))
        except OSError:  # sessions_dir missing or unreadable: nothing saved yet
            return []
        sessions = [s for s in (_read_session(path) for path in entries) if s is not None]
        sessions.sort(key=lambda s: (s.updated_at, s.id), reverse=True)
        return sessions

    # --- writes ---------------------------------------------------------------

    def create(self, *, title: str = "", scope: ScopeRef | None = None) -> ChatSession:
        """Create and persist a session with a server-generated opaque id."""
        now = _utcnow()
        session = ChatSession(
            id=new_session_id(),
            title=title,
            scope=scope or ScopeRef(),
            messages=[],
            created_at=now,
            updated_at=now,
        )
        return self.save(session)

    def save(self, session: ChatSession) -> ChatSession:
        """Persist a whole session atomically, under its own id.

        Additive to the frozen surface (ticket 12 needs a way to record a
        scope or a title decided after the session was created); `create()`
        and `append()` are both written in terms of it, so there is exactly
        one path that writes a session file.
        """
        _atomic_write_text(self._require_path(session.id), session.model_dump_json(indent=2))
        return session

    def append(self, session_id: str, message: ChatMessage) -> ChatSession:
        """Append one turn, bump `updated_at`, leave earlier messages untouched."""
        session = self._require(session_id)
        updated = session.model_copy(
            update={
                "messages": [*session.messages, message],
                "updated_at": _utcnow(),
            }
        )
        return self.save(updated)

    # --- exports --------------------------------------------------------------

    def export_markdown(self, session_id: str) -> str:
        """The transcript as markdown: claims, `Citation.label`s, and the part."""
        return render_markdown(self._require(session_id))

    def export_golden(self, session_id: str) -> str:
        """The same answers as `golden_qa_<PART>.yaml` entries.

        `id`, `question`, `expected_substrings` and `pages`, matching the
        existing fixture schema so the file drops into `tests/fixtures/`.
        """
        return render_golden(self._require(session_id))

    # --- internals ------------------------------------------------------------

    def _require(self, session_id: str) -> ChatSession:
        """The session, or `KeyError` — the router turns that into a 404."""
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"no session with id {session_id!r}")
        return session

    def _path_for(self, session_id: str) -> Path | None:
        if not _SAFE_ID.match(session_id or ""):
            return None
        return self.sessions_dir / f"{session_id}.json"

    def _require_path(self, session_id: str) -> Path:
        path = self._path_for(session_id)
        if path is None:
            raise ValueError(f"not a usable session id: {session_id!r}")
        return path


# --- markdown export ----------------------------------------------------------


def render_markdown(session: ChatSession) -> str:
    """One conversation as the markdown a user pastes into a design review.

    Every answer carries the part it was answered under, because a claim
    without the datasheet it came from is not verifiable — and the citation
    itself is `Citation.label` verbatim, so this exporter cannot be the place
    the `§4.5, p.7` format drifts.
    """
    header = [
        f"# {session.title or f'Session {session.id}'}",
        "",
        f"- **Scope:** {session.scope.label or '(unscoped)'}",
        f"- **Session:** `{session.id}`",
        f"- **Created:** {_stamp(session.created_at)}",
        f"- **Updated:** {_stamp(session.updated_at)}",
        "",
    ]
    answers = _answers(session)
    if not answers:
        # A conversation with no answer yet is an empty document, not an
        # error: exporting one is how a user finds out there is nothing in it.
        return "\n".join([*header, "_No answers recorded in this session yet._", ""])

    lines = list(header)
    for n, (question, answer) in enumerate(answers, 1):
        lines += [
            f"## Q{n}. {question or '(no question recorded)'}",
            "",
            answer.text.strip() or "_(empty answer)_",
            "",
        ]
        if answer.citations:
            lines += ["**Citations**", ""]
            lines += [f"- {_citation_line(c, session.scope)}" for c in answer.citations]
            lines.append("")
        else:
            lines += ["_No citations — this answer is unverified._", ""]
    return "\n".join(lines)


def _citation_line(citation: CitationOut, scope: ScopeRef) -> str:
    """`AD9081 — §4.5, p.7 — ad9081.pdf`: the part, the label, the document.

    The part comes from the citation when the retrieval core filled it in
    (under a project scope each hit names its own part) and falls back to the
    session's scope only when the scope *is* a part.
    """
    part = citation.part or (scope.name if scope.kind == "part" else "")
    label = citation.label or citation.pages or "p.?"
    pieces = [piece for piece in (part, label, citation.doc) if piece]
    return " — ".join(pieces)


def _stamp(moment: datetime | None) -> str:
    return moment.isoformat() if moment is not None else "unknown"


# --- golden-Q&A export --------------------------------------------------------


def render_golden(session: ChatSession) -> str:
    """The session's answers as `tests/fixtures/golden_qa_<PART>.yaml` entries.

    A draft regression test, and the header says so: the values are harvested
    from the answer's own text and the pages from the citations the runner
    actually produced, so a human confirms both before this becomes part of
    the objective function.
    """
    part = session.scope.name or "PART"
    entries = [
        {
            "id": f"q{n:02d}-{_slug(question or answer.text)}",
            "question": question or "(no question recorded)",
            "expected_substrings": _expected_substrings(answer.text),
            "pages": _cited_pages(answer.citations),
            "kind": "direct",
            "notes": (
                f"exported from session {session.id}; confirm the expected "
                "substrings and pages against the printed page before committing"
            ),
        }
        for n, (question, answer) in enumerate(_answers(session), 1)
    ]
    titled = f" ({session.title})" if session.title else ""
    destination = f"tests/fixtures/golden_qa_{part}.yaml"
    header = "\n".join(
        [
            f"# Golden Q&A exported from session {session.id}{titled}",
            f"# Scope: {session.scope.label or '(unscoped)'}. Drop into {destination} once verified.",
            "# Exported answers are a draft: every expected_substring and every",
            "# page below must be checked against the printed page first.",
        ]
    )
    body = yaml.safe_dump(
        {"questions": entries},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
    return f"{header}\n{body}"


def _expected_substrings(text: str) -> list[str]:
    """The answer's own values — what a correct answer must still contain.

    Citations are stripped before harvesting, so `p.7` never contributes a
    `7`. When an answer carries no value at all (a qualitative claim), the
    opening of the sentence stands in, which is what the hand-written
    `q01`-style entries in the existing fixtures do.
    """
    cleaned = _CITATION_NOISE.sub(" ", text or "")
    found: list[str] = []
    for match in _VALUE.finditer(cleaned):
        token = " ".join(match.group(0).split())
        unit = token.lstrip("±+-0123456789. ").strip()
        if unit and unit.lower() in _UNIT_STOPWORDS:
            token = token[: len(token) - len(unit)].strip()
        if not token or not any(ch.isdigit() for ch in token) or token in found:
            continue
        found.append(token)
        if len(found) >= _MAX_SUBSTRINGS:
            break
    if found:
        return found
    sentence = " ".join(cleaned.split())
    if not sentence:
        return []
    return [sentence[:_MAX_FALLBACK_CHARS].strip()]


def _cited_pages(citations: list[CitationOut]) -> list[int]:
    """Every page the answer's citations pinned, sorted and de-duplicated.

    An unpinned citation (`page_start is None`) contributes nothing: leaving
    it out is the same honest-`None` rule `pin_table_pages()` follows, and a
    guessed page in a golden entry would be a lie the suite then enforces.
    """
    pages: set[int] = set()
    for citation in citations:
        start = citation.page_start
        if start is None:
            continue
        end = citation.page_end if citation.page_end is not None else start
        if end < start or end - start > _MAX_PAGE_SPAN:
            end = start
        pages.update(range(start, end + 1))
    return sorted(pages)


def _slug(text: str, *, limit: int = 40) -> str:
    """`what-is-the-supply-voltage` — a stable, readable golden-entry id."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(slug) > limit:
        slug = slug[:limit].rsplit("-", 1)[0] or slug[:limit]
    return slug.strip("-") or "answer"


# --- shared -------------------------------------------------------------------


def _answers(session: ChatSession) -> list[tuple[str, ChatMessage]]:
    """Every assistant turn paired with the question it answered.

    Both exports are answer-shaped, so the pairing lives in one place. A
    session with no assistant message yields `[]` — the empty export, not an
    error.
    """
    pairs: list[tuple[str, ChatMessage]] = []
    question = ""
    for message in session.messages:
        if message.role == "user":
            question = message.text.strip()
            continue
        pairs.append((question, message))
        question = ""
    return pairs


def _read_session(path: Path) -> ChatSession | None:
    """One session file, or None when it is absent or malformed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("skipping unreadable session %s: %s", path, exc)
        return None
    try:
        return ChatSession.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - any validation failure is a skip
        log.warning("skipping malformed session %s: %s", path, exc)
        return None


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically: unique temp file + rename.

    Copied in shape from ``pipeline.py::_atomic_write_text``: the temp name
    carries pid and thread id so concurrent writers never share it (Windows
    locks open files), and the rename is retried briefly on
    ``PermissionError`` because the destination is locked while another
    thread has it open for reading. A failed write removes its temp file and
    leaves the destination untouched, so no ``.tmp`` outlives a save.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows: destination briefly locked
                time.sleep(0.01 * (attempt + 1))
        else:
            os.replace(tmp, path)  # last try — surface the error if still contended
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
