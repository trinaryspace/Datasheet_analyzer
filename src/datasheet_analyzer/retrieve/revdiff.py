"""`RevisionPair` — two revisions of one part, selected out of one corpus.

Phase 7, ticket 03. The fourth scope this package offers, beside one part
(`Retriever`), one design (`ProjectRetriever`) and an ad-hoc list of parts
(`Comparison`): **two documents of the same part**, which is what `dsa build
--rev` makes possible by filing each revision under its own document directory.

Everything here is selection and loading; the derivation lives in `revdiff/`,
imported at call time exactly as `Retriever.card()` imports `cards/`.

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
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from datasheet_analyzer.models import RevisionDiff, SourceDocument
from datasheet_analyzer.retrieve.index import CorpusIndex, IndexedDoc


@dataclass(frozen=True)
class RevisionDoc:
    """One selectable document of a part: its inventory record and its records.

    `source` is the acquire-time entry (label, printed revision, hash) and `doc`
    the loaded corpus directory. Both, because the two answer different halves of
    "which revision is this?" — what it was filed as, and what it publishes.
    """

    source: SourceDocument
    doc: IndexedDoc

    @property
    def label(self) -> str:
        """How this side is named: its filing label, else its printed revision."""
        return self.source.revision_label or self.source.revision or self.doc.name

    @property
    def selectors(self) -> tuple[str, ...]:
        """Every string that selects this document, in preference order."""
        return tuple(
            value
            for value in (
                self.source.revision_label,
                self.source.revision,
                self.doc.name,
                self.source.content_hash,
            )
            if value
        )

    def describe(self) -> str:
        """One line for an error message: what this document is and what selects it."""
        label = self.source.revision_label or "(no --rev label)"
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
        """One selected document as the pure derivation consumes it."""
        from datasheet_analyzer.revdiff import RevisionSide

        return RevisionSide(
            part_number=self.index.part_number,
            label=chosen.label,
            doc=chosen.doc.name,
            revision=chosen.source.revision,
            specs=chosen.doc.specs,
            sections=tuple(
                section
                for section in self.index.sections
                if section.doc_hash == chosen.source.content_hash
            ),
            pins=chosen.doc.pins,
            registers=chosen.doc.registers,
        )


def revision_documents(index: CorpusIndex) -> list[RevisionDoc]:
    """Every document of a part that a diff could name, in registration order.

    Registration order, not directory order: the inventory records the sequence
    the documents were filed in, which is the sequence a reader means by "the
    older one". A document in the inventory with nothing published under it —
    registered but never built — is skipped, because a side with no records would
    read as a revision that deleted the whole datasheet.
    """
    documents: list[RevisionDoc] = []
    for source in index.sources:
        doc = index.doc_for_hash(source.content_hash)
        if doc is None:
            continue
        documents.append(RevisionDoc(source=source, doc=doc))
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
    exact = [
        doc
        for doc in documents
        if any(value.lower() == wanted for value in doc.selectors)
    ]
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, (
            f"{selector!r} names {len(exact)} documents of this part "
            f"({', '.join(doc.doc.name for doc in exact)}) — name the document "
            f"directory instead"
        )
    prefixed = [
        doc
        for doc in documents
        if any(value.lower().startswith(wanted) for value in doc.selectors)
    ]
    if len(prefixed) == 1:
        return prefixed[0], ""
    if len(prefixed) > 1:
        return None, (
            f"{selector!r} matches {len(prefixed)} documents of this part "
            f"({', '.join(doc.doc.name for doc in prefixed)}) — be more specific"
        )
    return None, (
        f"no document of this part matches {selector!r}. It holds: "
        f"{_listing(documents)}"
    )


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
    """Why a part cannot be diffed at all, with the command that fixes it."""
    part = index.part_number or index.part_dir.name
    if not documents:
        return (
            f"no built documents under {index.part_dir} — build a revision first: "
            f"`dsa build <pdf> --part {part} --rev <revision>`"
        )
    return (
        f"{part} holds one built document ({documents[0].doc.name}); a revision "
        f"diff needs two. Add the other revision with `dsa build <pdf> --part "
        f"{part} --rev <revision>`, which files it under its own document "
        f"directory so both coexist"
    )


def _listing(documents: Sequence[RevisionDoc]) -> str:
    return "; ".join(document.describe() for document in documents) or "(nothing)"


__all__ = [
    "RevisionDoc",
    "RevisionPair",
    "revision_documents",
    "select_revision",
]
