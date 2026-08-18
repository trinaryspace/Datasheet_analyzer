"""Staleness — is this corpus still the current revision, and who is told?

Phase 7, ticket 02. Revisions have been *parsed* since phase 1 (`SBASA41E`,
`Rev. I`) and then never questioned, which means the tool would answer from a
superseded datasheet with full confidence and a valid page cite. This module
is the vocabulary that fixes that: one three-state reading of a part's
inventory, and one rendering of it per surface, so the four places a designer
could see the warning cannot say four different things.

Three rules are load-bearing.

- **`unknown` is the default and it is not `current`.** A corpus that has never
  run `dsa check-revisions` reads `unknown` and says "revision not checked"
  everywhere it is surfaced. Reading "nobody checked" as "still current" is the
  inversion this whole ticket exists to prevent — it is the difference between
  a designer knowing they are on their own and believing they were told.
- **A hash difference is never staleness.** Measured against the live TI
  servers (see the ticket, and `Reports/PHASE_7_LIVE_RUN.md`): TI regenerates a
  datasheet's package-materials addendum with the current date on every
  download, so the bytes of an *unchanged* revision differ daily. Staleness is
  decided by the parsed **revision identifier**; bytes that moved underneath an
  unchanged one are `content_drift`, worded as "regenerated", never "revised".
- **The warning is one text, rendered four ways.** `dsa status`, the `INDEX.md`
  banner, the `dsa audit` metric and the answer-pack footer all call
  `banner_text` here. A warning present in three surfaces and absent from the
  fourth is the failure mode the tests exist to catch, and the cheapest way to
  get there is four independently-written strings.

The state lives on the *inventory* (`sources.json`), not the manifest, because
a check happens after a build and must reach every surface without a rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from datasheet_analyzer.models import DocType, SourceDocument, Staleness

#: Markers around the `INDEX.md` banner block. `dsa check-revisions` rewrites
#: what is between them in a corpus that is already built, and the builder
#: emits the same block, so there is exactly one banner in a file however it
#: got there.
BANNER_BEGIN = "<!-- dsa:staleness -->"
BANNER_END = "<!-- /dsa:staleness -->"

#: Worst-first ordering. A part is only as fresh as its least fresh document:
#: a current datasheet beside an unchecked register map is not a current
#: corpus, because the register map is what a bring-up question answers from.
_SEVERITY = {Staleness.STALE: 0, Staleness.UNKNOWN: 1, Staleness.CURRENT: 2}

#: The command that fills the gap. Named in every `unknown` message — a warning
#: that does not say how to clear it trains the reader to ignore it.
CHECK_COMMAND = "dsa check-revisions"


@dataclass(frozen=True)
class CorpusStaleness:
    """One part's freshness reading, already resolved across its documents."""

    part: str = ""
    state: Staleness = Staleness.UNKNOWN
    built_revision: str = ""
    upstream_revision: str = ""
    checked_at: datetime | None = None
    content_drift: bool = False
    #: Why the state is what it is, when that needs saying (the reason a check
    #: could not run, or the drift note). Carried verbatim from the inventory.
    note: str = ""
    #: Which document decided the reading, so a two-document part can say
    #: *which* half is stale rather than tarring both.
    doc_type: str = ""

    @property
    def checked(self) -> bool:
        """True once a check has actually completed for the deciding document."""
        return self.checked_at is not None

    @property
    def warns(self) -> bool:
        """True when this reading is something a designer must be shown.

        `current` with drift still warns — quietly, and in words that do not
        claim a revision moved — because bytes changing under a hash a corpus
        was verified against is a fact the maintainer should know.
        """
        return self.state is not Staleness.CURRENT or self.content_drift


def document_staleness(source: SourceDocument, part: str = "") -> CorpusStaleness:
    """One document's reading, straight off its inventory record."""
    return CorpusStaleness(
        part=part or source.part_number,
        state=source.staleness,
        built_revision=source.revision,
        upstream_revision=source.upstream_revision,
        checked_at=source.revision_checked_at,
        content_drift=source.content_drift,
        note=source.revision_check_note,
        doc_type=source.doc_type.value,
    )


def corpus_staleness(
    sources: list[SourceDocument] | tuple[SourceDocument, ...], part: str = ""
) -> CorpusStaleness:
    """The part's reading: its least fresh document, datasheet breaking ties.

    A part with no registered documents is `unknown` **with the reason**, not
    an absent reading: "there is nothing here to be stale" and "nobody has
    checked" are different findings, and only one of them is about the corpus.
    """
    if not sources:
        return CorpusStaleness(
            part=part,
            state=Staleness.UNKNOWN,
            note="no documents are registered for this part",
        )

    def rank(src: SourceDocument) -> tuple[int, int]:
        # Same state: the datasheet speaks for the part.
        return (_SEVERITY[src.staleness], 0 if src.doc_type == DocType.DATASHEET else 1)

    return document_staleness(min(sources, key=rank), part)


def load_corpus_staleness(part_dir) -> CorpusStaleness:
    """`corpus_staleness` over a part directory's `sources.json`."""
    from pathlib import Path

    from datasheet_analyzer.acquire.inventory import load_inventory

    part_dir = Path(part_dir)
    return corpus_staleness(load_inventory(part_dir), part_dir.name)


def _checked_on(st: CorpusStaleness) -> str:
    return st.checked_at.date().isoformat() if st.checked_at else ""


def _built_as(st: CorpusStaleness) -> str:
    return (
        f"built from {st.built_revision}"
        if st.built_revision
        else "built from a document that prints no revision identifier"
    )


def _drift_sentence(st: CorpusStaleness) -> str:
    """The content-drift note — worded so it can never read as a new revision."""
    rev = st.built_revision or "the recorded revision"
    return (
        f"The upstream document's bytes differ but its revision identifier is "
        f"still {rev}: the document was regenerated, not revised — this is not "
        f"evidence of a new revision."
    )


def banner_text(st: CorpusStaleness) -> str:
    """The one sentence every surface renders. Never empty.

    `stale` is the wording the phase plan specifies verbatim; `unknown` says
    "revision not checked" and names the command that clears it; `current`
    states the revision it was confirmed against and the date, so "current" is
    always a claim with a date attached rather than an unqualified reassurance.
    """
    part = f" --part {st.part}" if st.part else ""
    if st.state is Staleness.STALE:
        upstream = st.upstream_revision or "a different revision"
        checked = f" (checked {_checked_on(st)})" if st.checked else ""
        return (
            f"This corpus is {_built_as(st)}; {upstream} is available upstream"
            f"{checked}. Verify before committing to silicon."
        )
    if st.state is Staleness.CURRENT:
        checked = f" (checked {_checked_on(st)})" if st.checked else ""
        rev = st.built_revision or "the built revision"
        text = f"Revision current: {rev} confirmed against upstream{checked}."
        return f"{text} {_drift_sentence(st)}" if st.content_drift else text
    reason = f" — {st.note}" if st.note else ""
    return (
        f"Revision not checked: this corpus is {_built_as(st)} and has not been "
        f"confirmed against upstream{reason}. Run `{CHECK_COMMAND}{part}` before "
        f"relying on it for a design decision."
    )


def marker(st: CorpusStaleness) -> str:
    """The glyph that opens the line: a warning, or a confirmation."""
    return "⚠" if st.warns else "✓"


def one_line(st: CorpusStaleness) -> str:
    """Marker + sentence: the compact form for a terminal or a pack footer."""
    return f"{marker(st)} {banner_text(st)}"


def index_banner(st: CorpusStaleness) -> str:
    """The `INDEX.md` block, marker-delimited so it can be refreshed in place.

    A blockquote at the very top of the file: `INDEX.md` is the one artifact an
    agent is told to read first, so a staleness warning that appeared anywhere
    below the section map would be read after the answer was already formed.
    """
    return f"{BANNER_BEGIN}\n> {one_line(st)}\n{BANNER_END}"


def apply_index_banner(markdown: str, banner: str) -> str:
    """Insert or replace the banner block in an already-written `INDEX.md`.

    Pure and idempotent: applying it twice leaves one banner, and applying a
    fresh reading over an old one replaces the block rather than stacking
    warnings. Used by `dsa check-revisions` so a corpus does not have to be
    rebuilt for the new reading to reach the file the agent reads first.
    """
    begin = markdown.find(BANNER_BEGIN)
    if begin != -1:
        end = markdown.find(BANNER_END, begin)
        if end != -1:
            tail = markdown[end + len(BANNER_END):].lstrip("\n")
            return f"{markdown[:begin]}{banner}\n\n{tail}" if tail else f"{markdown[:begin]}{banner}\n"
    return f"{banner}\n\n{markdown}" if markdown else f"{banner}\n"


def status_lines(st: CorpusStaleness, indent: str = "    ") -> list[str]:
    """`dsa status`'s rendering: one labelled line, plus the drift note."""
    lines = [f"{indent}revision: {st.state.value} — {one_line(st)}"]
    if st.content_drift and st.state is not Staleness.CURRENT:
        lines.append(f"{indent}  content-drift: {_drift_sentence(st)}")
    return lines


def pack_footer(st: CorpusStaleness) -> str:
    """The answer-pack footer line — the surface that protects a decision.

    Part of the pack's *reserved tail*: it is laid down with the header and the
    verify footer, before anything discretionary, so a tight budget can never
    be what removes the warning that an answer came from a superseded document.

    Deliberately **terser than the other surfaces, and terser the less
    dangerous the finding is**. This is the one rendering every answer pays for
    on every call, and it is paid out of the same budget as the answer itself:

    - `stale` carries the full sentence, because it is the finding that changes
      a design decision and the reader needs both revisions and the date;
    - `unknown` — the state of every corpus nobody has checked, so the common
      case — says "revision not checked" and names the command, and nothing
      more; the full reasoning is one `dsa status` away;
    - `current` states the revision and the date in one short clause.

    A longer default would spend an answer's budget restating, on every call,
    a fact the reader already acted on the first time.
    """
    if st.state is Staleness.STALE:
        upstream = st.upstream_revision or "a different revision"
        checked = f" (checked {_checked_on(st)})" if st.checked else ""
        built = st.built_revision or "an unidentified revision"
        return (
            f"⚠ Built from {built}; {upstream} is available upstream{checked}. "
            f"Verify before committing to silicon."
        )
    if st.state is Staleness.CURRENT:
        checked = f", checked {_checked_on(st)}" if st.checked else ""
        rev = st.built_revision or "the built revision"
        text = f"✓ Revision current: {rev}{checked}."
        return f"{text} Regenerated upstream, not revised." if st.content_drift else text
    return "⚠ Revision not checked — run `dsa check-revisions`."


def audit_metric(st: CorpusStaleness) -> dict:
    """The `revision freshness` row of the `dsa audit` scorecard (ticket 05).

    The metric is published here, with the rest of the vocabulary, so the audit
    command renders a reading it did not compute — the same rule the CLI
    follows for every other number it prints. `grade_input` is what the
    checked-in rubric grades: a corpus nobody has checked scores as an unknown,
    never as a pass.
    """
    return {
        "metric": "revision freshness",
        "part": st.part,
        "state": st.state.value,
        "grade_input": st.state.value,
        "built_revision": st.built_revision,
        "upstream_revision": st.upstream_revision,
        "checked_at": st.checked_at.isoformat() if st.checked_at else None,
        "content_drift": st.content_drift,
        "note": st.note,
        "banner": one_line(st),
    }


def as_dict(st: CorpusStaleness) -> dict:
    """The wire shape every front end (CLI `--json`, MCP) reports.

    Deliberately the same keys in both, because a remote agent and a local one
    must not be able to reach different conclusions about the same corpus.
    """
    return {
        "state": st.state.value,
        "built_revision": st.built_revision,
        "upstream_revision": st.upstream_revision,
        "checked_at": st.checked_at.isoformat() if st.checked_at else None,
        "content_drift": st.content_drift,
        "note": st.note,
        "banner": one_line(st),
    }


def project_staleness(
    readings: list[CorpusStaleness] | tuple[CorpusStaleness, ...],
) -> CorpusStaleness:
    """One reading for a whole design: its least fresh member.

    A project answer draws on several corpora, so the footer has to speak for
    the worst of them and *name* it — "something in this design is stale" with
    no part number is a warning a designer cannot act on.
    """
    if not readings:
        return CorpusStaleness(note="this project has no member corpora")
    return min(readings, key=lambda st: _SEVERITY[st.state])
