"""`RevisionPair` — two revisions of one part, selected out of one corpus.

Phase 7, ticket 03. The fourth scope this package offers, beside one part
(`Retriever`), one design (`ProjectRetriever`) and an ad-hoc list of parts
(`PartComparison`): **two documents of the same part**.

Everything here is selection and loading; the derivation lives in `revdiff/`,
imported at call time exactly as `Retriever.card()` imports `derive/cards`.

Three rules the scope enforces before any diff runs.

**A side is selected by what a human would type**, in one order: the label the
document was filed under (`--rev F`), the revision identifier it printed
(`SBASA41F`), its document directory, then its content hash. Matching is
case-insensitive and a selector that matches more than one document is
**refused with both candidates named** — picking one would silently diff the
wrong pair, and every value in the report would still be perfectly cited.

**A default is only taken when there is exactly one.** With no selectors and
exactly two documents of the same type, the pair is those two in registration
order — the order they were filed is the order they arrived. Anything else is an
error that lists what the part actually holds, because guessing which two of
four documents a designer meant is a decision this tool has no basis for.

**Diffing a document against itself is allowed.** It is the determinism check
the ticket asks for, it produces an empty diff by construction, and the diff
says so in words rather than reading as "these two revisions are identical".

## What a pair can be on this branch

A part here is a **view** of the Library, and `acquire.inventory.single_datasheet`
reduces that view to one datasheet per part — "a part is one device, and its
datasheet is one document". So a pair found under one part is a pair of
*companions*: two register maps, two errata sheets, two application notes. Two
revisions of a **datasheet** do not coexist under one part, and this module does
not pretend otherwise — `_too_few` names the rule that is in the way and what to
do instead, rather than a flag that cannot produce a second buildable document.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import (
    LibraryDocument,
    RevisionDiff,
    SourceDocument,
    Staleness,
)
from datasheet_analyzer.retrieve.index import CorpusIndex, IndexedDoc


@dataclass(frozen=True)
class RevisionDoc:
    """One selectable document of a part: its Library record and its records.

    `library` is the acquire-time record (filing label, printed revision, hash,
    and what the last revision check found) and `doc` the loaded corpus
    directory. Both, because the two answer different halves of "which revision
    is this?" — what it was filed as, and what it publishes.

    The record comes from the **Library**, not from `sources.json`: the filing
    label and the revision state live there, and `sources.json` is a derived
    view regenerated at publish (ADR 0005) that carries neither.
    """

    library: LibraryDocument
    doc: IndexedDoc
    #: Where this document's record references hang off (`docs/<doc>` under the
    #: part, `@library/docs/<doc>` in the shared store). Read off the manifest
    #: rather than composed, because a composed one would be right for a
    #: self-contained corpus and silently wrong for a shared one.
    ref_base: str = ""

    @property
    def source(self) -> SourceDocument:
        """The document's acquire-time record."""
        return self.library.source

    @property
    def revision_label(self) -> str:
        """The name a human filed this copy under (`dsa build --rev F`)."""
        return self.library.revision_label

    @property
    def label(self) -> str:
        """How this side is named: its filing label, else its printed revision."""
        return self.revision_label or self.source.revision or self.doc.name

    @property
    def selectors(self) -> tuple[str, ...]:
        """Every string that selects this document, in preference order."""
        return tuple(
            value
            for value in (
                self.revision_label,
                self.source.revision,
                self.doc.name,
                self.source.content_hash,
            )
            if value
        )

    def revision_note(self) -> str:
        """What the last revision check found about this document; `""` when nothing.

        This is where `RevisionState.content_drift` and `upstream_sha256` reach
        a reader: ticket 02 recorded them and named this command as their
        consumer. A revision diff compares two documents **on disk**, which is a
        different claim from one about what upstream serves today — so a side
        whose upstream bytes have moved, or whose revision has been superseded,
        says so on the diff's own notes rather than letting the report read as
        current.
        """
        state = self.library.revision_state
        if state.staleness == Staleness.STALE:
            upstream = state.upstream_revision or "an unread revision"
            return (
                f"superseded upstream ({upstream} was found by the last "
                f"`dsa check-revisions`); this diff compares what is on disk, "
                f"not what upstream now serves"
            )
        if state.content_drift:
            digest = state.upstream_sha256[:12] or "(unrecorded)"
            return (
                f"upstream has regenerated this document under an unchanged "
                f"revision identifier (upstream sha256 {digest}); the bytes "
                f"moved, the revision did not, so nothing below is evidence of "
                f"a new revision"
            )
        if state.staleness == Staleness.UNKNOWN:
            return (
                "this side's revision has never been checked against upstream - "
                "run `dsa check-revisions` before trusting the pair to be the "
                "two revisions you meant"
            )
        return ""

    def describe(self) -> str:
        """One line for an error message: what this document is and what selects it."""
        label = self.revision_label or "(no --rev label)"
        revision = self.source.revision or "(no printed revision)"
        return (
            f"{self.doc.name} — label {label}, printed revision {revision}, "
            f"{self.source.doc_type.value}"
        )


@dataclass(frozen=True)
class RevisionPair:
    """The two documents a diff is being made over, plus the corpus they came from."""

    index: CorpusIndex
    before: RevisionDoc
    after: RevisionDoc

    @classmethod
    def for_part(
        cls, part_dir: Path | str, *, before: str = "", after: str = ""
    ) -> tuple[RevisionPair | None, str]:
        """`(pair, error)` — the two revisions to diff, or why they cannot be chosen.

        Takes a directory rather than a part number for the same reason
        `Comparison.for_parts` does: resolving a name to a corpus belongs to the
        caller's settings, and keeping it there is what lets this package stay
        unaware of where parts live.
        """
        index = CorpusIndex.load(Path(part_dir))
        documents = revision_documents(index)
        if len(documents) < 2:
            return None, _too_few(index, documents)
        if not before and not after:
            chosen, error = _default_pair(index, documents)
            if chosen is None:
                return None, error
            return cls(index=index, before=chosen[0], after=chosen[1]), ""
        if not before or not after:
            return None, (
                "name both sides of a revision diff: `--from <revision> --to "
                "<revision>` (or neither, when the part holds exactly two "
                f"documents of one type). This part holds: {_listing(documents)}"
            )
        first, error = select_revision(documents, before)
        if first is None:
            return None, error
        second, error = select_revision(documents, after)
        if second is None:
            return None, error
        return cls(index=index, before=first, after=second), ""

    def diff(self) -> RevisionDiff:
        """Derive the diff of these two sides — the whole point of the scope."""
        from datasheet_analyzer.revdiff import build_revision_diff

        return build_revision_diff(self._side(self.before), self._side(self.after))

    def _side(self, chosen: RevisionDoc):
        """One selected document as the pure derivation consumes it.

        `pins.json` and `registers.json` are read here rather than carried on
        `IndexedDoc`: the index loads what every answer needs, and a pin table
        is not that. They are read through the same loaders `dsa pins` and
        `dsa regs` use, so a diff and a lookup can never disagree about what a
        document published.
        """
        from datasheet_analyzer.derive.pins import load_pinset
        from datasheet_analyzer.derive.registers import load_registerset
        from datasheet_analyzer.revdiff import RevisionSide

        directory = chosen.doc.directory
        pinset = load_pinset(directory) if directory is not None else None
        registerset = load_registerset(directory) if directory is not None else None
        return RevisionSide(
            part_number=self.index.part_number,
            label=chosen.label,
            doc=chosen.doc.name,
            ref_base=chosen.ref_base or f"docs/{chosen.doc.name}",
            revision=chosen.source.revision,
            revision_note=chosen.revision_note(),
            specs=chosen.doc.specs,
            sections=tuple(
                section
                for section in self.index.sections
                if section.doc_hash == chosen.source.content_hash
            ),
            pins=tuple(pinset.pins) if pinset is not None else (),
            registers=tuple(registerset.registers) if registerset is not None else (),
        )


def revision_documents(index: CorpusIndex) -> list[RevisionDoc]:
    """Every document of a part that a diff could name, in registration order.

    Registration order, not directory order: the Library records the sequence
    the documents were filed in, which is the sequence a reader means by "the
    older one". A document the Library knows about with nothing published under
    it — registered but never built — is skipped, because a side with no records
    would read as a revision that deleted the whole datasheet.
    """
    from datasheet_analyzer.acquire.inventory import library_view

    library = library_view(Path(index.part_dir), part_number=index.part_number)
    documents: list[RevisionDoc] = []
    for record in sorted(library, key=lambda d: (d.source.registered_at, d.content_hash)):
        doc = index.doc_for_hash(record.content_hash)
        if doc is None:
            continue
        documents.append(
            RevisionDoc(library=record, doc=doc, ref_base=index.reference_base(doc.name))
        )
    return documents


def select_revision(
    documents: Sequence[RevisionDoc], selector: str
) -> tuple[RevisionDoc | None, str]:
    """`(document, error)` for one caller-typed selector.

    Refuses rather than guesses on both failures a selector can have — nothing
    matched, or several did — and names the alternatives either way, because a
    diff of the wrong pair is fully cited and completely wrong.
    """
    wanted = selector.strip().lower()
    if not wanted:
        return None, "empty revision selector"
    exact = [doc for doc in documents if any(value.lower() == wanted for value in doc.selectors)]
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, (
            f"{selector!r} names {len(exact)} documents of this part "
            f"({', '.join(doc.doc.name for doc in exact)}) — name the document "
            f"directory instead"
        )
    prefixed = [
        doc for doc in documents if any(value.lower().startswith(wanted) for value in doc.selectors)
    ]
    if len(prefixed) == 1:
        return prefixed[0], ""
    if len(prefixed) > 1:
        return None, (
            f"{selector!r} matches {len(prefixed)} documents of this part "
            f"({', '.join(doc.doc.name for doc in prefixed)}) — be more specific"
        )
    return None, (f"no document of this part matches {selector!r}. It holds: {_listing(documents)}")


def _default_pair(
    index: CorpusIndex, documents: Sequence[RevisionDoc]
) -> tuple[tuple[RevisionDoc, RevisionDoc] | None, str]:
    """The two documents to diff when the caller named neither, or the refusal.

    Only ever taken when one document type has exactly two entries: a part with a
    datasheet and a register map holds two documents that are not two revisions
    of anything, and diffing them would produce a confident report about nothing.
    """
    by_type: dict[str, list[RevisionDoc]] = {}
    for document in documents:
        by_type.setdefault(document.source.doc_type.value, []).append(document)
    pairs = [group for group in by_type.values() if len(group) == 2]
    if len(pairs) == 1:
        group = pairs[0]
        return (group[0], group[1]), ""
    return None, (
        f"{index.part_number} holds no unambiguous revision pair — name both "
        f"sides with `--from` and `--to`. It holds: {_listing(documents)}"
    )


def _too_few(index: CorpusIndex, documents: Sequence[RevisionDoc]) -> str:
    """Why a part cannot be diffed at all, and what this branch allows instead.

    Deliberately does **not** name `--rev` as the fix. On this branch
    `acquire.inventory.single_datasheet` builds one datasheet per part, so a
    second datasheet filed against the same part is recorded in the Library and
    skipped by the build; telling a reader to add one would name a command that
    cannot produce the second side.
    """
    part = index.part_number or Path(index.part_dir).name
    if not documents:
        return (
            f"no built documents under {index.part_dir} — build the part first: "
            f"`dsa build <pdf> --part {part}`"
        )
    return (
        f"{part} holds one built document ({documents[0].doc.name}); a revision "
        f"diff needs two. A part builds one datasheet "
        f"(`acquire.inventory.single_datasheet`), so the second side is either a "
        f"companion document filed against this part (`dsa add-doc`) or the "
        f"other revision built under its own part number, which `dsa compare` "
        f"is the scope for"
    )


def _listing(documents: Sequence[RevisionDoc]) -> str:
    return "; ".join(document.describe() for document in documents) or "(nothing)"


__all__ = [
    "RevisionDoc",
    "RevisionPair",
    "revision_documents",
    "select_revision",
]
