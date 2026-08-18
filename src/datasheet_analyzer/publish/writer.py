"""Corpus writer: sections/, tables/, INDEX.md, manifest.json on disk.

Layout per part:
    parts/<PART>/
      INDEX.md
      REVISION_DIFF.md        (written by `dsa diff-rev`, not by a build)
      sources.json            (written by acquire)
      manifest.json
      docs/<doc_type>-<hash8>[-rev<label>]/   (the suffix only for a document
                              filed with `dsa build --rev`)
        sections/*.md
        tables/*.csv
        specs.json / plots.json / pins.json / registers.json  (when there is one)
        search_index.json
      errata_links.json + ERRATA.md   (only for a part that registers an errata
                              document — phase 7, ticket 04)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace as dc_replace
from pathlib import Path

from datasheet_analyzer.cards import CardDoc, build_cards, render_card
from datasheet_analyzer.config import (
    CARD_VERSION,
    CARDS_SCHEMA_VERSION,
    ERRATA_SCHEMA_VERSION,
    PINS_SCHEMA_VERSION,
    PLOTS_SCHEMA_VERSION,
    REGISTERS_SCHEMA_VERSION,
    SPECS_SCHEMA_VERSION,
)
from datasheet_analyzer.errata import (
    ERRATA_LINKS_FILENAME,
    ERRATA_MARKDOWN_FILENAME,
    SectionBanner,
    TargetDoc,
    build_errata_links,
    build_items,
    insert_banner,
    is_errata,
    render_errata,
    section_banner,
    sections_to_banner,
)
from datasheet_analyzer.models import (
    CorpusManifest,
    CorpusStats,
    DesignCard,
    DocType,
    ErrataLinkSet,
    ExtractionStats,
    PinRecord,
    PinSet,
    PlotRecord,
    PlotSet,
    RawDocument,
    RegisterRecord,
    RegisterSet,
    SectionFile,
    SourceDocument,
    SpecRecord,
    SpecSet,
)
from datasheet_analyzer.protocol import build_part_agent_markdown, write_agent_doc
from datasheet_analyzer.publish.search_index import build_search_index, write_search_index
from datasheet_analyzer.revdiff.render import REVISION_DIFF_FILENAME
from datasheet_analyzer.structure.confidence import mix as confidence_mix
from datasheet_analyzer.structure.corpus import SectionPlan
from datasheet_analyzer.tokens import count_tokens

log = logging.getLogger(__name__)

#: Design cards live at the *part* level, beside `INDEX.md`: a card joins rows
#: from every document of the part (and a limits margin joins two tables that
#: may not even be in the same one), so a per-document card would be a view of
#: half a device.
CARDS_DIRNAME = "cards"


#: What a revision label contributes to a document directory name, once
#: slugged: `datasheet-a1b2c3d4-revf`. Phase 7, ticket 03.
REV_DIR_MARKER = "-rev"


def revision_slug(label: str) -> str:
    """A revision label as a directory-name fragment; `""` when it has none.

    Lowercased and reduced to `[a-z0-9-]`, because this becomes a path segment
    on three filesystems and a segment of every `source` reference the document's
    records carry. A label of only punctuation slugs to nothing and is therefore
    *not* a label — the caller registers the document unlabelled rather than
    under a directory named for a stray character.
    """
    return re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")


def doc_dir_name_for_source(source: SourceDocument) -> str:
    """Corpus directory name of one source document (`datasheet-a1b2c3d4`).

    Takes the `SourceDocument` rather than the `RawDocument` so a reader that
    only has a manifest — the batch skip gate, say — can name the same
    directory the publisher wrote, without re-extracting.

    A document filed under a revision label (`dsa build --rev F`, phase 7 ticket
    03) gains a `-revf` suffix. The content hash already guarantees two
    revisions cannot collide — that is what makes them coexist under one part —
    so the suffix buys **legibility**, not uniqueness: a reader listing `docs/`
    can tell which directory is which revision without opening a file, and so
    can every citation those records carry. It is strictly additive: a document
    with no label is named exactly as it always was, so no built corpus moves.
    """
    slug = revision_slug(source.revision_label)
    suffix = f"{REV_DIR_MARKER}{slug}" if slug else ""
    return f"{source.doc_type.value}-{source.content_hash[:8]}{suffix}"


def doc_dir_name(raw: RawDocument) -> str:
    return doc_dir_name_for_source(raw.source)


def _artifact_schema_current(doc_dir: Path, filename: str, version: str) -> bool:
    """Whether a published JSON artifact carries the current schema version.

    A *missing* file reads as current here, unlike `search_index_current`, and
    the asymmetry is deliberate: `search_index.json` is written for every
    published document, so its absence is always staleness, while
    `specs.json` / `plots.json` are only written for documents that have
    trusted tables at all — a `pdf_text` register map legitimately has
    neither, and demanding one would put that part in a rebuild loop. What is
    checked is the version of a file that *is* there. Anything unreadable
    reads as stale, which is the safe direction: rebuild.
    """
    path = doc_dir / filename
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("schema_version") == version


def specs_current(doc_dir: Path) -> bool:
    """Whether `doc_dir`'s `specs.json` is of the current schema (or absent).

    The publish-cache-key check for spec records, called by the batch skip
    gate. `SPECS_SCHEMA_VERSION` is bumped whenever a published spec record
    gains or changes a field, so a corpus written before that field existed
    republishes once instead of serving it forever without.
    """
    return _artifact_schema_current(doc_dir, "specs.json", SPECS_SCHEMA_VERSION)


def plots_current(doc_dir: Path) -> bool:
    """`plots.json`'s twin of `specs_current`, keyed on `PLOTS_SCHEMA_VERSION`."""
    return _artifact_schema_current(doc_dir, "plots.json", PLOTS_SCHEMA_VERSION)


def pins_current(doc_dir: Path) -> bool:
    """`pins.json`'s twin, keyed on `PINS_SCHEMA_VERSION`.

    A *missing* file reads as current, exactly as for its siblings and for the
    same reason: most datasheets in this corpus print no pin table at all, and
    demanding a file they cannot produce would put those parts in a rebuild
    loop forever.
    """
    return _artifact_schema_current(doc_dir, "pins.json", PINS_SCHEMA_VERSION)


def cards_current(part_dir: Path, card_version: str = CARD_VERSION) -> bool:
    """Whether the part's `cards/` hold current, current-rule design cards.

    The one publish-artifact gate where a **missing** file is staleness rather
    than a legitimate absence, and the asymmetry follows from what a card is:
    every published part gets all four, an honestly empty one included (ADR
    0005: "an empty card is a valid card, not a missing file that reads as *not
    yet built*"). So no cards means a corpus published before cards existed, and
    a card stamped with another `card_version` means one derived under rules this
    build no longer uses — both republish once and then skip again.
    """
    cards_dir = part_dir / CARDS_DIRNAME
    if not cards_dir.is_dir():
        return False
    files = sorted(cards_dir.glob("*.json"))
    if not files:
        return False
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        if data.get("schema_version") != CARDS_SCHEMA_VERSION:
            return False
        if data.get("card_version") != card_version:
            return False
    return True


def write_cards(part_dir: Path, cards: list[DesignCard]) -> list[Path]:
    """Write `cards/<name>.json` + `cards/<name>.md`; return what was written.

    Both forms, always: the JSON is what a machine walks (every value in its
    provenance envelope, which is what the invariant-8 test resolves) and the
    markdown is what a person or an agent reads. The markdown comes from
    `cards.render`, the same function `dsa card` prints, so the file on disk and
    the command's output cannot drift.

    A card with no rows is written exactly like one with rows. That is ADR 0005's
    "an empty card is a valid card": the file states what it looked for and did
    not find, where a missing file would read as "this part has not been built
    yet".
    """
    cards_dir = part_dir / CARDS_DIRNAME
    cards_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for card in cards:
        json_path = cards_dir / f"{card.card}.json"
        json_path.write_text(card.model_dump_json(indent=2), encoding="utf-8")
        md_path = cards_dir / f"{card.card}.md"
        md_path.write_text(render_card(card), encoding="utf-8")
        written += [json_path, md_path]
    # A card the lexicon no longer declares must not linger: a stale card is a
    # derived artifact nobody can regenerate, which is the failure `card_version`
    # exists to prevent.
    for path in sorted(cards_dir.iterdir()):
        if path.is_file() and path not in written:
            path.unlink(missing_ok=True)
    return written


def write_revision_diff(part_dir: Path, markdown: str) -> Path:
    """Write `REVISION_DIFF.md` beside the part's `INDEX.md`; return the path.

    Takes the rendered markdown rather than the diff, so the publish stage never
    learns how a revision diff is laid out: `revdiff.render` owns that, and what
    `dsa diff-rev` prints and what lands on disk are then the same string by
    construction.

    Unlike every other file here it is written by a **command**, not by a build:
    it is a report of one comparison a person asked for, not a corpus artifact a
    rebuild must keep current — which is why no `*_current` gate reads it and why
    a stale one is simply overwritten by the next run.
    """
    part_dir = Path(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)
    path = part_dir / REVISION_DIFF_FILENAME
    path.write_text(markdown, encoding="utf-8")
    return path


def errata_current(part_dir: Path, manifest: CorpusManifest) -> bool:
    """Whether the part's errata links are present and of the current schema.

    Asymmetric like `cards_current` and for the same reason, but keyed on the
    *inventory* rather than on the file: a part that registers an errata document
    must publish `errata_links.json`, so a missing one is staleness (a corpus
    published before this ticket existed), while a part with no errata document
    must publish none at all, so a missing one is correct. Anything unreadable
    reads as stale, which is the safe direction: rebuild.
    """
    has_errata = any(doc.doc_type == DocType.ERRATA for doc in manifest.documents)
    path = Path(part_dir) / ERRATA_LINKS_FILENAME
    if not has_errata:
        return not path.exists()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("schema_version") == ERRATA_SCHEMA_VERSION


def write_errata(part_dir: Path, link_set: ErrataLinkSet | None) -> list[Path]:
    """Write (or remove) the part's errata artifacts; return what was written.

    Both forms, as for a design card: `errata_links.json` is what a machine
    walks — every target in its reference form, every item verbatim — and
    `ERRATA.md` is what a person reads, rendered by the same function nothing
    else may re-implement.

    `None` means the part registers no errata document, and then the *absence*
    of both files is the artifact: an empty errata file reads as "no known
    issues", which is a claim this corpus has no evidence for. A republish of a
    part whose errata document was removed therefore takes the old files with
    it, exactly as a pin table that no longer parses takes `pins.json` with it.
    """
    part_dir = Path(part_dir)
    json_path = part_dir / ERRATA_LINKS_FILENAME
    md_path = part_dir / ERRATA_MARKDOWN_FILENAME
    if link_set is None:
        json_path.unlink(missing_ok=True)
        md_path.unlink(missing_ok=True)
        return []
    part_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(link_set.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(render_errata(link_set), encoding="utf-8")
    return [json_path, md_path]


def registers_current(doc_dir: Path) -> bool:
    """`registers.json`'s twin, keyed on `REGISTERS_SCHEMA_VERSION`.

    A *missing* file reads as current, for the same reason as `pins_current`:
    almost no document prints a register summary, and demanding a file they
    cannot produce would rebuild those parts forever.
    """
    return _artifact_schema_current(doc_dir, "registers.json", REGISTERS_SCHEMA_VERSION)


def _errata_links(
    part_number: str,
    docs: list[tuple[RawDocument, list[SectionPlan], dict[str, str]]],
    specsets_by_hash: dict[str, SpecSet],
    pinsets_by_hash: dict[str, PinSet],
    registersets_by_hash: dict[str, RegisterSet],
) -> tuple[ErrataLinkSet | None, dict[str, SectionBanner]]:
    """Derive the part's errata links and the banners they imply.

    `(None, {})` for a part that registers no errata document — the case that
    must stay completely inert, so that a part with no errata gets no file and
    no banner and reads exactly as it did before this ticket.

    The target surface is deliberately narrow. An errata document is never its
    own target (an erratum does not invalidate itself), and only records the
    publisher is about to *write* are targetable: `pins.json` and
    `registers.json` are written only when they hold rows, so a link into a
    rejected pin table would resolve to nothing while reading as a placed
    erratum.
    """
    errata_docs = [(doc_dir_name(raw), raw) for raw, _plans, _d in docs if is_errata(raw)]
    if not errata_docs:
        return None, {}

    targets: list[TargetDoc] = []
    for raw, plans, _descriptions in docs:
        if is_errata(raw):
            continue
        doc_rel = f"docs/{doc_dir_name(raw)}"
        specset = specsets_by_hash.get(raw.source.content_hash)
        pinset = pinsets_by_hash.get(raw.source.content_hash)
        registerset = registersets_by_hash.get(raw.source.content_hash)
        targets.append(
            TargetDoc(
                name=doc_dir_name(raw),
                doc_hash=raw.source.content_hash,
                sections=tuple(
                    (plan.section, f"{doc_rel}/{plan.file}") for plan in plans
                ),
                specs=tuple(specset.records) if specset else (),
                pins=tuple(pinset.pins) if pinset and pinset.pins else (),
                registers=(
                    tuple(registerset.registers)
                    if registerset and registerset.registers
                    else ()
                ),
            )
        )

    items = build_items(errata_docs)
    link_set = build_errata_links(
        part_number, items, targets, errata_docs=[name for name, _raw in errata_docs]
    )
    return link_set, sections_to_banner(link_set, targets)


def _bannered_docs(
    docs: list[tuple[RawDocument, list[SectionPlan], dict[str, str]]],
    banners: dict[str, SectionBanner],
) -> list[tuple[RawDocument, list[SectionPlan], dict[str, str]]]:
    """The same plans, with a warning banner inserted where an erratum lands.

    Applied here — before the search index is built and before a byte is
    written — so the file on disk, the token count in the manifest and the text
    the BM25 index was built from are the same string. A corpus where "what is
    searchable is exactly what is readable" held only until an erratum arrived
    would be a quiet lie about the index.

    Nothing is mutated: each affected plan is replaced by a copy, so a caller
    that kept its own reference to the plans (the enrich stage does) still sees
    exactly what it produced.
    """
    if not banners:
        return docs
    out: list[tuple[RawDocument, list[SectionPlan], dict[str, str]]] = []
    for raw, plans, descriptions in docs:
        doc_rel = f"docs/{doc_dir_name(raw)}"
        new_plans: list[SectionPlan] = []
        for plan in plans:
            banner = banners.get(f"{doc_rel}/{plan.file}")
            if banner is None:
                new_plans.append(plan)
                continue
            markdown = insert_banner(
                plan.markdown,
                section_banner(list(banner.links), banner.targets),
            )
            new_plans.append(
                dc_replace(
                    plan, markdown=markdown, token_count=count_tokens(markdown)
                )
            )
        out.append((raw, new_plans, descriptions))
    return out


def write_corpus(
    part_dir: Path,
    docs: list[tuple[RawDocument, list[SectionPlan], dict[str, str]]],
    index_md: str,
    *,
    pipeline_version: str,
    vendor: str = "",
    specsets: list[SpecSet] | None = None,
    plotsets: list[PlotSet] | None = None,
    pinsets: list[PinSet] | None = None,
    registersets: list[RegisterSet] | None = None,
    card_version: str = CARD_VERSION,
) -> CorpusManifest:
    """Write all corpus artifacts; return the manifest.

    `docs` = list of (RawDocument, its section plans, section descriptions).
    `vendor` is the part's evidence-pinned vendor routing record. Per-document
    extraction stats are recorded (backend always; table counts by the layout
    engine). Optional `specsets` are written as `docs/<doc>/specs.json`.
    Optional `plotsets` are written as `docs/<doc>/plots.json`.
    Every document also gets `docs/<doc>/search_index.json` — the BM25 index
    over the section markdown written here, so what is searchable is exactly
    what is readable.

    Optional `pinsets` are written as `docs/<doc>/pins.json` **only when they
    hold pins**. A document whose pin table was rejected, or that prints none,
    gets no file rather than an empty or partial one: a designer who greps a
    half-published pin table for a pin, gets no hit and concludes it does not
    exist has been misled (ADR 0005). A set with no pins also *removes* any
    `pins.json` an earlier build left behind, because a corpus must never serve
    a superseded pin table — and because the skip gate reads that file's schema,
    so a stale one left on disk would rebuild the part forever. What such a set
    still contributes is its `warnings` — the package cross-check above all —
    which land in `CorpusManifest.derived_warnings`, because the ADR decided a
    mismatch is recorded rather than logged.

    Optional `registersets` follow the pin rule exactly, and for the same
    reason: `docs/<doc>/registers.json` is written **only when the set holds
    registers**, a set with none deletes any earlier file, and its `warnings`
    (how many of its registers the document states a reset for) travel into
    `CorpusManifest.derived_warnings` either way. A firmware engineer who greps
    a half-published register map for `0x1A04` and concludes the register does
    not exist has been misled in the most expensive way this corpus can manage.

    `card_version` is the derivation-rule version this corpus's derived
    artifacts were produced under (ADR 0005). It is stamped into the manifest
    because nothing else can carry it: derived values are computed from
    records, so a rule change moves no source byte and the extraction cache
    cannot see it. `batch.skip_reason` reads it back.
    """
    part_dir = Path(part_dir)
    part_dir.mkdir(parents=True, exist_ok=True)

    stats = CorpusStats(n_documents=len(docs))
    # Accumulated separately from `stats` so `CorpusStats.tables_pinned` can
    # stay `None` on corpora published before it existed: a local int always
    # counts, and it is assigned onto the manifest below.
    tables_pinned = 0
    manifest = CorpusManifest(
        part_number=part_dir.name,
        pipeline_version=pipeline_version,
        card_version=card_version,
        vendor=vendor,
    )
    specsets_by_hash = {s.doc_hash: s for s in (specsets or [])}
    plotsets_by_hash = {p.doc_hash: p for p in (plotsets or [])}
    pinsets_by_hash = {p.doc_hash: p for p in (pinsets or [])}
    registersets_by_hash = {r.doc_hash: r for r in (registersets or [])}
    # What the design cards are derived from: the very records written below,
    # per document, in publication order (ticket 07).
    card_docs: list[CardDoc] = []
    # Per-part confidence mix, accumulated across the part's documents so the
    # manifest carries one measured number per grade (ticket 04).
    graded_specs: list[SpecRecord] = []
    graded_plots: list[PlotRecord] = []
    graded_pins: list[PinRecord] = []
    graded_registers: list[RegisterRecord] = []

    doc_dirs: list[str] = []

    # Errata cross-links (phase 7, ticket 04). Derived *before* anything is
    # written, because the section files themselves change: a section an erratum
    # names carries a warning banner, and a banner added after the search index
    # was built would make the corpus searchable for text it no longer matches.
    # The link set is derived from the very records this function is about to
    # write — nothing may point into a `pins.json` the publisher declines to
    # write — which is why the target surface is assembled here rather than in
    # the structure stage.
    link_set, banners = _errata_links(
        part_dir.name, docs, specsets_by_hash, pinsets_by_hash, registersets_by_hash
    )
    docs = _bannered_docs(docs, banners)

    for raw, plans, descriptions in docs:
        doc_dirs.append(doc_dir_name(raw))
        doc_rel = f"docs/{doc_dir_name(raw)}"
        doc_abs = part_dir / doc_rel
        (doc_abs / "sections").mkdir(parents=True, exist_ok=True)
        if any(p.table_files for p in plans):
            (doc_abs / "tables").mkdir(parents=True, exist_ok=True)

        specset = specsets_by_hash.get(raw.source.content_hash)
        if specset is not None:
            (doc_abs / "specs.json").write_text(
                specset.model_dump_json(indent=2), encoding="utf-8"
            )
            stats.n_specs += len(specset.records)
            graded_specs.extend(specset.records)

        pinset = pinsets_by_hash.get(raw.source.content_hash)
        if pinset is not None:
            # The warnings travel even when the file does not: a rejected pin
            # table still has something to say about this part.
            manifest.derived_warnings.extend(pinset.warnings)
            pins_path = doc_abs / "pins.json"
            if pinset.pins:
                pins_path.write_text(
                    pinset.model_dump_json(indent=2), encoding="utf-8"
                )
                stats.n_pins += len(pinset.pins)
                graded_pins.extend(pinset.pins)
            else:
                # A republish that now yields no pins must take the old file
                # with it. Leaving it would serve a superseded — possibly
                # rejected — pin table forever, which is the opposite of "no
                # pins.json rather than a partial one", and would keep
                # `publish.pins_current` false so the part rebuilt on every
                # run (`batch.skip_reason`) without ever settling.
                pins_path.unlink(missing_ok=True)

        registerset = registersets_by_hash.get(raw.source.content_hash)
        if registerset is not None:
            # Same shape as pins: the warnings travel even when the file does
            # not, and a set with no registers takes the old file with it.
            manifest.derived_warnings.extend(registerset.warnings)
            registers_path = doc_abs / "registers.json"
            if registerset.registers:
                registers_path.write_text(
                    registerset.model_dump_json(indent=2), encoding="utf-8"
                )
                stats.n_registers += len(registerset.registers)
                graded_registers.extend(registerset.registers)
            else:
                registers_path.unlink(missing_ok=True)

        # Only records that were actually *written* feed a card: a card cites
        # `docs/<doc>/specs.json#rec_412`, and a reference into a file the
        # publisher declined to write would resolve to nothing.
        card_docs.append(
            CardDoc.of(
                doc_dir_name(raw),
                specset,
                pinset if pinset is not None and pinset.pins else None,
            )
        )

        plotset = plotsets_by_hash.get(raw.source.content_hash)
        if plotset is not None:
            (doc_abs / "plots.json").write_text(
                plotset.model_dump_json(indent=2), encoding="utf-8"
            )
            stats.n_plot_files += sum(1 for p in plotset.plots if p.file)
            graded_plots.extend(plotset.plots)

        manifest.documents.append(raw.source)
        extraction = raw.extraction_stats
        if extraction is None:
            extraction = ExtractionStats(backend=raw.extractor)
        # Stamp the extractor identity on every document, whatever produced
        # the stats: the batch skip gate reads it to detect a corpus built by
        # an older extractor output schema.
        extraction = extraction.model_copy(
            update={
                "backend": extraction.backend or raw.extractor,
                "extractor_version": raw.extractor_version,
            }
        )
        manifest.extraction_stats[raw.source.content_hash] = extraction
        stats.n_sections += len(plans)

        # Full-text index for this document, built from the very markdown the
        # loop below writes. Section token lengths come back out of it so the
        # manifest can budget a search hit without loading the index.
        search = build_search_index(
            plans, part_number=part_dir.name, doc_hash=raw.source.content_hash
        )
        stats.search_index_bytes += write_search_index(doc_abs, search)
        search_tokens = {s.file: s.length for s in search.sections}

        for plan in plans:
            (doc_abs / plan.file).write_text(plan.markdown, encoding="utf-8")
            stats.section_bytes += len(plan.markdown.encode("utf-8"))
            for tf in plan.table_files:
                (doc_abs / tf.name).write_text(tf.csv, encoding="utf-8")

            sec = plan.section
            stats.n_tables += len(sec.tables)
            # Phase 7, ticket 05: the builder-side half of `dsa audit`'s table
            # pin rate. Counted here because this is the last place the
            # `TableBlock` objects exist — `manifest.json` records the section's
            # page range, and a table's own pinned page survives nowhere else.
            # Accumulated into a local first so the manifest field stays `None`
            # only for corpora published before the field existed.
            tables_pinned += sum(1 for t in sec.tables if t.page is not None)
            stats.n_figures += len(sec.figures)
            stats.n_footnotes += sum(len(t.footnotes) for t in sec.tables)
            stats.total_tokens += plan.token_count
            stats.boilerplate_tokens_removed += plan.boilerplate_removed
            if sec.page_start is not None:
                stats.sections_with_pages += 1
            else:
                stats.sections_without_pages += 1

            manifest.sections.append(
                SectionFile(
                    number=sec.number,
                    title=sec.title,
                    file=f"{doc_rel}/{plan.file}",
                    doc_hash=raw.source.content_hash,
                    page_start=sec.page_start,
                    page_end=sec.page_end,
                    token_count=plan.token_count,
                    description=descriptions.get(sec.number or sec.title, ""),
                    n_tables=len(sec.tables),
                    n_figures=len(sec.figures),
                    search_tokens=search_tokens.get(plan.file, 0),
                )
            )

    (part_dir / "INDEX.md").write_text(index_md, encoding="utf-8")
    stats.index_tokens = count_tokens(index_md)

    # Design cards (ticket 07). Derived here rather than in the structure stage
    # because a card is a view over *published* records, ids and all — and
    # written for every part, empty ones included, because an empty card is a
    # finding and a missing file reads as "not built yet".
    cards = build_cards(part_dir.name, card_docs, card_version=card_version)
    write_cards(part_dir, cards)
    stats.n_cards = len(cards)
    stats.n_card_rows = sum(card.n_rows for card in cards)
    for card in cards:
        if card.empty_reason:
            # One line, not the card's full reason: the manifest is the audit
            # trail (`dsa status`, and `dsa audit` in phase 7) and the card file
            # is where the detail belongs. Recorded at all because "this part
            # has no power card" is exactly the kind of derived-artifact gap
            # ADR 0005 decided must be carried by the corpus rather than logged.
            manifest.derived_warnings.append(
                f"{card.card} card for {part_dir.name} has no rows — see "
                f"{CARDS_DIRNAME}/{card.card}.md for what it looked for"
            )

    # The table-pinning count is a *measured* fact about this publish, so it is
    # assigned unconditionally — including as 0 for a corpus whose tables could
    # none of them be pinned, which is a real finding rather than an absence.
    stats.tables_pinned = tables_pinned

    # Errata links (phase 7, ticket 04). Written — or deliberately removed —
    # here, after the records they point at exist on disk. The warnings are the
    # honest half: an item nobody could place is a finding about this part, and
    # it belongs in the manifest beside the empty-card warnings rather than in a
    # log line nobody reads.
    write_errata(part_dir, link_set)
    if link_set is not None:
        stats.n_errata_items = link_set.n_items
        stats.n_errata_linked = len(link_set.links)
        if link_set.unlinked:
            manifest.derived_warnings.append(
                f"{len(link_set.unlinked)} of {link_set.n_items} errata items for "
                f"{part_dir.name} could not be linked to a published record — they "
                f"are published under \"unlinked errata\" in "
                f"{ERRATA_MARKDOWN_FILENAME} and must be read by hand"
            )
        if link_set.empty_reason:
            manifest.derived_warnings.append(
                f"{part_dir.name} registers an errata document but published no "
                f"errata item: {link_set.empty_reason}"
            )

    # The retrieval protocol ships *with* the corpus (ticket 08): INDEX.md is
    # the map, AGENT.md is how to read it. Written here rather than by the
    # enrich stage because it is not enriched — it is fixed text plus the
    # facts this function already has.
    agent_md = build_part_agent_markdown(
        part_dir.name,
        revision=manifest.documents[0].revision if manifest.documents else "",
        doc_dirs=doc_dirs,
        n_sections=stats.n_sections,
        n_specs=stats.n_specs,
        n_plot_files=stats.n_plot_files,
    )
    write_agent_doc(part_dir, agent_md)
    stats.agent_doc_tokens = count_tokens(agent_md)

    if graded_specs:
        stats.spec_confidence = confidence_mix(graded_specs)
    if graded_plots:
        stats.plot_confidence = confidence_mix(graded_plots)
    if graded_pins:
        stats.pin_confidence = confidence_mix(graded_pins)
    if graded_registers:
        stats.register_confidence = confidence_mix(graded_registers)

    manifest.stats = stats
    (part_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    log.info(
        "corpus written: %s (%d sections, %d tables, %d spec records, %d tokens, "
        "index %d tokens, agent protocol %d tokens)",
        part_dir, stats.n_sections, stats.n_tables, stats.n_specs,
        stats.total_tokens, stats.index_tokens, stats.agent_doc_tokens,
    )
    log.info(
        "design cards: %d written (%d rows) at card_version %s",
        stats.n_cards, stats.n_card_rows, card_version,
    )
    if link_set is not None:
        log.info(
            "errata links: %d item(s), %d linked, %d unlinked (%d target(s))",
            link_set.n_items, len(link_set.links), len(link_set.unlinked),
            link_set.n_targets,
        )
    log.info(
        "confidence mix: specs %s; plots %s; pins %s; registers %s",
        stats.spec_confidence or "(none)", stats.plot_confidence or "(none)",
        stats.pin_confidence or "(none)", stats.register_confidence or "(none)",
    )
    for warning in manifest.derived_warnings:
        log.warning("derived-artifact warning recorded in the manifest: %s", warning)
    log.info(
        "search index: %d bytes over %d bytes of section markdown (%.0f%%)",
        stats.search_index_bytes, stats.section_bytes,
        100.0 * stats.search_index_bytes / stats.section_bytes if stats.section_bytes else 0.0,
    )
    return manifest
