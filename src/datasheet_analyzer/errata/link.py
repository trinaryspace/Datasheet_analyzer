"""Errata cross-linking — which published record an erratum invalidates.

Phase 7, ticket 04. An errata document already joins a part's corpus as a
`pdf_text` document; on its own that only makes it *greppable*. Linking each of
its items to the section, spec row, pin or register it invalidates is what turns
"any known issues with this part?" into an answer with a page number on it.

**Every rule matches a structured identifier, exactly.** A printed section
number the item cues (`Section 6.1`), a printed table caption, a printed symbol,
an alias phrase from `registry/aliases.yaml` resolved to a canonical symbol, a
pin name, a cued pin designator, a register name, a parsed register address.
There is no prose-similarity rung and there must never be one: an errata item
and a datasheet section are both written about the same device in the same
vocabulary, so *resemblance* between them is the null hypothesis, not evidence.
A link produced that way would read exactly like a real one and would put a
warning banner on a page the erratum was never about.

Three properties follow from that and are load-bearing:

- **Nothing is lost.** An item no rule could place is published under
  "unlinked errata" (`ErrataLinkSet.unlinked`) rather than dropped. That is the
  worst failure available to this module, so the set carries linked and
  unlinked items as two named lists and `n_items` is their sum.
- **Every link says what it matched on.** `ErrataTarget.rule` names the rule and
  `matched_on` quotes the identifier it fired on, so a wrong link is diagnosable
  from the file instead of by re-reading the PDF.
- **A rule that matched more than the lexicon's cap states how many.** A symbol
  printed on sixty rows affects sixty records; listing all sixty is unreadable
  and listing twenty-five silently is a lie, so the overflow becomes a note on
  the link.

No model call appears anywhere in this path (invariant 8), and every value on a
target is either a reference to a published record, a verbatim identifier the
errata document printed, or a structural label from a checked-in lexicon.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from datasheet_analyzer.config import ERRATA_SCHEMA_VERSION
from datasheet_analyzer.derive.provenance import (
    PINS_ARTIFACT,
    REGISTERS_ARTIFACT,
    SPECS_ARTIFACT,
)
from datasheet_analyzer.errata.lexicon import (
    RULE_ALIAS_PHRASE,
    RULE_PIN_DESIGNATOR,
    RULE_PIN_NAME,
    RULE_REGISTER_ADDRESS,
    RULE_REGISTER_NAME,
    RULE_SECTION_NUMBER,
    RULE_SPEC_SYMBOL,
    RULE_TABLE_CAPTION,
    ErrataLexicon,
    load_errata_lexicon,
)
from datasheet_analyzer.models import (
    ErrataItem,
    ErrataLink,
    ErrataLinkSet,
    ErrataTarget,
    ErrataTargetKind,
    PinRecord,
    RegisterRecord,
    SectionNode,
    SpecRecord,
    source_ref,
)
from datasheet_analyzer.structure.aliases import AliasLexicon, load_lexicon, padded

log = logging.getLogger(__name__)

#: Word characters, unicode-aware: `RθJA` and `IVDD1P8` are one token each.
_WORD = re.compile(r"\w+", re.UNICODE)

#: A hex word as a register map prints one. Decimal addresses are deliberately
#: not read here: a bare `25` in errata prose is a quantity far more often than
#: it is an address, and the register's *name* rule already reaches that row.
_HEX = re.compile(r"0[xX][0-9A-Fa-f]+")


@dataclass(frozen=True)
class TargetDoc:
    """One published document of a part, as a surface an erratum can point at.

    Only records the publisher actually **wrote** belong here. A reference into
    a `pins.json` the publisher declined to write (a rejected pin table) would
    resolve to nothing, and a link that resolves to nothing is worse than no
    link: it reads as a placed erratum.

    `sections` pairs each section with the corpus-relative file it was published
    as, because a section target is banner-able only if the banner has a file to
    go in.
    """

    name: str
    doc_hash: str = ""
    #: The prefix this document's record references hang off - `docs/<name>`
    #: under the part, `@library/docs/<name>` in the shared store (ADR 0008).
    #: Carried rather than composed from `name`, because a reference built for
    #: the wrong root resolves to nothing while looking exactly like one that
    #: resolves.
    ref_base: str = ""
    sections: tuple[tuple[SectionNode, str], ...] = ()
    specs: tuple[SpecRecord, ...] = ()
    pins: tuple[PinRecord, ...] = ()
    registers: tuple[RegisterRecord, ...] = ()

    @property
    def reference_base(self) -> str:
        """Where this document's record references hang off."""
        return self.ref_base or f"docs/{self.name}"


@dataclass
class _Match:
    """One rule's output before it becomes a target: what, and on what."""

    target: ErrataTarget
    order: int = 0


@dataclass
class _RuleOutput:
    matches: list[_Match] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_errata_links(
    part_number: str,
    items: list[ErrataItem],
    targets: list[TargetDoc],
    *,
    lexicon: ErrataLexicon | None = None,
    aliases: AliasLexicon | None = None,
    errata_docs: list[str] | None = None,
) -> ErrataLinkSet:
    """Link every errata item against every published document of the part.

    Returns the set even when it links nothing: the items are the product, the
    links are the value added, and an item with no target is still published.
    """
    lexicon = lexicon or load_errata_lexicon()
    aliases = aliases or load_lexicon()

    linked: list[ErrataLink] = []
    unlinked: list[ErrataLink] = []
    for item in items:
        link = _link_item(item, targets, lexicon, aliases)
        (linked if link.targets else unlinked).append(link)

    notes: list[str] = []
    if unlinked:
        notes.append(
            f"{len(unlinked)} of {len(linked) + len(unlinked)} errata items could not "
            f"be placed against a published record; they are published in full under "
            f"`unlinked` and must be read by hand."
        )
    if not targets:
        notes.append(
            "this part published no document for an erratum to point at, so no item could be linked"
        )
    empty_reason = ""
    if not items:
        empty_reason = (
            "the part registers an errata document, but no readable item could be "
            "segmented out of it — the document may be image-only, or it may print "
            "no item heading this lexicon knows (`registry/errata.yaml`)"
        )
    return ErrataLinkSet(
        schema_version=ERRATA_SCHEMA_VERSION,
        part_number=part_number,
        errata_docs=list(errata_docs or []),
        links=linked,
        unlinked=unlinked,
        notes=notes,
        empty_reason=empty_reason,
    )


def _link_item(
    item: ErrataItem,
    targets: list[TargetDoc],
    lexicon: ErrataLexicon,
    aliases: AliasLexicon,
) -> ErrataLink:
    """One item against every document — rules in order, strongest id first."""
    tokens = frozenset(_WORD.findall(item.text))
    haystack = padded(item.text)
    seen: set[tuple] = set()
    out: list[ErrataTarget] = []
    notes: list[str] = []
    rules = (
        _section_number_rule,
        _table_caption_rule,
        _spec_symbol_rule,
        _alias_phrase_rule,
        _pin_name_rule,
        _pin_designator_rule,
        _register_name_rule,
        _register_address_rule,
    )
    for rule in rules:
        for doc in targets:
            result = rule(item, doc, lexicon, aliases, tokens, haystack)
            kept, overflow = 0, 0
            for match in result.matches:
                key = _dedupe_key(match.target)
                if key in seen:
                    # Already linked by a stronger rule (the order above is
                    # strongest first), so the target keeps the `matched_on`
                    # that carries the most evidence.
                    continue
                if kept >= lexicon.max_targets_per_rule:
                    overflow += 1
                    continue
                seen.add(key)
                out.append(match.target)
                kept += 1
            if overflow:
                notes.append(
                    f"{result.matches[0].target.rule} matched "
                    f"{len(result.matches)} records in {doc.name}; the first "
                    f"{kept} are listed and {overflow} more are not "
                    f"(cap: max_targets_per_rule = {lexicon.max_targets_per_rule})"
                )
            notes.extend(result.notes)
    return ErrataLink(errata_item_id=item.id, item=item, targets=out, notes=notes)


# --- reading the links back --------------------------------------------------


def links_by_target(link_set: ErrataLinkSet) -> dict[str, list[ErrataLink]]:
    """Every link, indexed by the reference each of its targets carries.

    The lookup a *consumer* needs: an answer pack holds a record's id, and this
    says whether an erratum named it. Unlinked items deliberately do not appear
    — they name nothing, which is exactly why they are published under their own
    heading instead.
    """
    out: dict[str, list[ErrataLink]] = {}
    for link in link_set.links:
        for target in link.targets:
            if not target.id:
                continue
            bucket = out.setdefault(target.id, [])
            if link not in bucket:
                bucket.append(link)
    return out


@dataclass(frozen=True)
class SectionBanner:
    """What one section file's warning banner has to say.

    `links` is every item that named this section — directly by its printed
    number or caption, or through a record printed in it — and `targets` maps
    each of those items to the target that selected the section, so the banner
    can quote what it matched on.
    """

    file: str
    links: tuple[ErrataLink, ...] = ()
    targets: dict[str, ErrataTarget] = field(default_factory=dict)


def sections_to_banner(
    link_set: ErrataLinkSet, targets: list[TargetDoc]
) -> dict[str, SectionBanner]:
    """Which published section files must carry a banner, and why.

    A section is bannered when an item named it **or** when an item named a
    record the section printed. The second half is what makes the banner useful:
    an erratum that corrects one row of the absolute-maximum table has to warn
    whoever opens that table, and the row's own record is not what a reader
    opens.
    """
    by_number: dict[tuple[str, str], str] = {}
    for doc in targets:
        for section, file in doc.sections:
            if section.number:
                by_number[(doc.name, section.number)] = file
    out: dict[str, SectionBanner] = {}

    def add(file: str, link: ErrataLink, target: ErrataTarget) -> None:
        banner = out.get(file)
        if banner is None:
            banner = SectionBanner(file=file)
            out[file] = banner
        if link not in banner.links:
            out[file] = SectionBanner(
                file=file, links=banner.links + (link,), targets=banner.targets
            )
            out[file].targets[link.item.id] = target

    for link in link_set.links:
        for target in link.targets:
            if target.kind == ErrataTargetKind.SECTION:
                add(target.id, link, target)
            elif target.section:
                file = by_number.get((target.doc, target.section))
                if file:
                    add(file, link, target)
    return out


# --- the rules ---------------------------------------------------------------
#
# Each takes the item, one document, both lexicons and two precomputed views of
# the item's text (its word tokens, case-sensitive; and its space-fenced
# normalized form for phrase containment), and returns the targets it found.


def _section_number_rule(
    item: ErrataItem,
    doc: TargetDoc,
    lexicon: ErrataLexicon,
    aliases: AliasLexicon,
    tokens: frozenset[str],
    haystack: str,
) -> _RuleOutput:
    """`Section 6.1` -> the section published under printed number `6.1`.

    The cue word is mandatory (`registry/errata.yaml`'s `section_cues`): an
    uncued `6.1` in errata prose is a supply voltage far more often than it is a
    section, and this rule's output is what puts a warning banner on a page.
    """
    out = _RuleOutput()
    pattern = lexicon.section_cue_pattern
    if pattern is None:
        return out
    by_number = {
        section.number: (section, file) for section, file in doc.sections if section.number
    }
    for match in pattern.finditer(item.text):
        number = match.group("number")
        found = by_number.get(number)
        if found is None:
            continue
        section, file = found
        out.matches.append(
            _Match(
                _section_target(
                    doc,
                    section,
                    file,
                    rule=RULE_SECTION_NUMBER,
                    matched_on=(f'section number "{number}" (cued by "{match.group("cue")}")'),
                    lexicon=lexicon,
                )
            )
        )
    return out


def _table_caption_rule(
    item: ErrataItem,
    doc: TargetDoc,
    lexicon: ErrataLexicon,
    aliases: AliasLexicon,
    tokens: frozenset[str],
    haystack: str,
) -> _RuleOutput:
    """A printed table caption quoted in the item -> the section that holds it.

    The caption is compared as the whole printed string, normalized and
    space-fenced, so this is containment of an identifier the document itself
    printed — not resemblance. Short captions are excluded by the lexicon's
    `min_caption_chars`, because a caption of one common word turns up in errata
    prose by accident.
    """
    out = _RuleOutput()
    for section, file in doc.sections:
        for table in section.tables:
            caption = (table.caption or "").strip()
            if len(caption) < lexicon.min_caption_chars:
                continue
            needle = padded(caption)
            if needle.strip() and needle in haystack:
                out.matches.append(
                    _Match(
                        _section_target(
                            doc,
                            section,
                            file,
                            rule=RULE_TABLE_CAPTION,
                            matched_on=f'table caption "{caption}"',
                            lexicon=lexicon,
                        )
                    )
                )
                break  # one target per section; the section is what banners
    return out


def _spec_symbol_rule(
    item: ErrataItem,
    doc: TargetDoc,
    lexicon: ErrataLexicon,
    aliases: AliasLexicon,
    tokens: frozenset[str],
    haystack: str,
) -> _RuleOutput:
    """A printed symbol quoted verbatim in the item -> every row that prints it.

    Case-sensitive and whole-token, and only for symbols that *look like*
    symbols (`_is_identifier`): the layout floor records `Junction temperature`
    or `Supply` in the symbol column for datasheets with no symbol column at
    all, and matching those would link on an ordinary English word. Those rows
    are reachable — through the alias rule below, which requires the lexicon to
    vouch for the phrase at both ends.
    """
    out = _RuleOutput()
    for record in doc.specs:
        symbol = record.symbol.strip()
        if symbol in tokens and _is_identifier(symbol, lexicon.min_identifier_chars):
            out.matches.append(
                _Match(
                    _spec_target(
                        doc,
                        record,
                        rule=RULE_SPEC_SYMBOL,
                        matched_on=f'spec symbol "{symbol}"',
                        lexicon=lexicon,
                    )
                )
            )
    return out


def _alias_phrase_rule(
    item: ErrataItem,
    doc: TargetDoc,
    lexicon: ErrataLexicon,
    aliases: AliasLexicon,
    tokens: frozenset[str],
    haystack: str,
) -> _RuleOutput:
    """A designer's phrase in the item -> the rows the alias lexicon claims.

    Both ends go through `registry/aliases.yaml`: the phrase must be one the
    lexicon declares for a canonical symbol, and the record must be one that
    same entry claims (by carrying the symbol, or by printing one of the entry's
    phrases in its own symbol or name). That is two exact containments against
    checked-in data, which is why it links `the junction temperature limit` to a
    row whose printed symbol is `Junction temperature` without any notion of
    similarity — and why it is graded `medium`: the link came through a second
    artifact rather than off the page.
    """
    out = _RuleOutput()
    for entry, phrase in aliases.phrase_hits(item.text):
        for record in doc.specs:
            claimed = (
                record.symbol.strip().lower() == entry.symbol.lower()
                or entry.describes(record.symbol)
                or entry.describes(record.name)
            )
            if not claimed:
                continue
            out.matches.append(
                _Match(
                    _spec_target(
                        doc,
                        record,
                        rule=RULE_ALIAS_PHRASE,
                        matched_on=f'alias phrase "{phrase}" -> {entry.symbol}',
                        lexicon=lexicon,
                    )
                )
            )
    return out


def _pin_name_rule(
    item: ErrataItem,
    doc: TargetDoc,
    lexicon: ErrataLexicon,
    aliases: AliasLexicon,
    tokens: frozenset[str],
    haystack: str,
) -> _RuleOutput:
    """A printed pin name quoted verbatim -> that pin's record(s)."""
    out = _RuleOutput()
    for record in doc.pins:
        name = record.name.strip()
        if name in tokens and _is_identifier(name, lexicon.min_identifier_chars):
            out.matches.append(
                _Match(
                    _record_target(
                        doc,
                        record,
                        artifact=PINS_ARTIFACT,
                        kind=ErrataTargetKind.PIN,
                        label=f"{record.pin} {record.name}".strip(),
                        rule=RULE_PIN_NAME,
                        matched_on=f'pin name "{name}"',
                        lexicon=lexicon,
                    )
                )
            )
    return out


def _pin_designator_rule(
    item: ErrataItem,
    doc: TargetDoc,
    lexicon: ErrataLexicon,
    aliases: AliasLexicon,
    tokens: frozenset[str],
    haystack: str,
) -> _RuleOutput:
    """`ball A1` -> the pin published under designator `A1`.

    Cued, for the same reason a section number is: `A1` on its own is a package
    variant, a note marker and a hundred other things.
    """
    out = _RuleOutput()
    pattern = lexicon.pin_cue_pattern
    if pattern is None:
        return out
    wanted = {m.group("pin").upper(): m.group("cue") for m in pattern.finditer(item.text)}
    if not wanted:
        return out
    for record in doc.pins:
        cue = wanted.get(record.pin.strip().upper())
        if cue is None:
            continue
        out.matches.append(
            _Match(
                _record_target(
                    doc,
                    record,
                    artifact=PINS_ARTIFACT,
                    kind=ErrataTargetKind.PIN,
                    label=f"{record.pin} {record.name}".strip(),
                    rule=RULE_PIN_DESIGNATOR,
                    matched_on=f'pin designator "{record.pin}" (cued by "{cue}")',
                    lexicon=lexicon,
                )
            )
        )
    return out


def _register_name_rule(
    item: ErrataItem,
    doc: TargetDoc,
    lexicon: ErrataLexicon,
    aliases: AliasLexicon,
    tokens: frozenset[str],
    haystack: str,
) -> _RuleOutput:
    """A printed register name quoted verbatim -> that register's record."""
    out = _RuleOutput()
    for record in doc.registers:
        name = record.name.strip()
        if name in tokens and _is_identifier(name, lexicon.min_identifier_chars):
            out.matches.append(
                _Match(
                    _record_target(
                        doc,
                        record,
                        artifact=REGISTERS_ARTIFACT,
                        kind=ErrataTargetKind.REGISTER,
                        label=f"{record.address.verbatim} {record.name}".strip(),
                        rule=RULE_REGISTER_NAME,
                        matched_on=f'register name "{name}"',
                        lexicon=lexicon,
                    )
                )
            )
    return out


def _register_address_rule(
    item: ErrataItem,
    doc: TargetDoc,
    lexicon: ErrataLexicon,
    aliases: AliasLexicon,
    tokens: frozenset[str],
    haystack: str,
) -> _RuleOutput:
    """`0x19` -> the register whose parsed address is that value.

    Compared as integers, exactly as `dsa regs --addr` resolves one, so `0x19`,
    `0x019` and `0X19` are the same register. A register whose printed address
    the grammar could not read carries no integer and is therefore unreachable
    here — honestly, rather than by a string comparison that would match the
    wrong notation.
    """
    out = _RuleOutput()
    values: dict[int, str] = {}
    for match in _HEX.finditer(item.text):
        try:
            values[int(match.group(0), 16)] = match.group(0)
        except ValueError:  # pragma: no cover - the pattern guarantees hex
            continue
    if not values:
        return out
    for record in doc.registers:
        parsed = record.address.value
        if parsed is None or parsed not in values:
            continue
        out.matches.append(
            _Match(
                _record_target(
                    doc,
                    record,
                    artifact=REGISTERS_ARTIFACT,
                    kind=ErrataTargetKind.REGISTER,
                    label=f"{record.address.verbatim} {record.name}".strip(),
                    rule=RULE_REGISTER_ADDRESS,
                    matched_on=f'register address "{values[parsed]}"',
                    lexicon=lexicon,
                )
            )
        )
    return out


# --- target construction -----------------------------------------------------


def _dedupe_key(target: ErrataTarget) -> tuple:
    """What makes two targets of one item the same target.

    The reference, normally. A record published with **no** id (a corpus written
    before ADR 0005 minted them) has no reference to be identified by, so those
    fall back to what is still true about them — document, label, section, page
    — rather than collapsing into one another under a shared empty string.
    """
    if target.id:
        return (target.kind.value, target.id)
    return (target.kind.value, target.doc, target.label, target.section, target.page)


def _is_identifier(text: str, min_chars: int) -> bool:
    """Whether `text` reads as a printed *identifier* rather than as a word.

    An identifier is long enough to be specific and carries a mark no ordinary
    English word does: a digit, a second capital, or a non-ASCII letter (`RθJA`).
    `Supply`, `Input` and `Large` — all of which the layout floor really does
    record in the symbol column of datasheets that print no symbols — fail it, and
    that is the point: linking an erratum on the strength of the word "Input"
    would be a coincidence dressed as evidence.
    """
    text = text.strip()
    if len(text) < max(min_chars, 2):
        return False
    if not text.isascii():
        return True
    if any(ch.isdigit() for ch in text):
        return True
    return sum(1 for ch in text if ch.isupper()) >= 2


def _section_target(
    doc: TargetDoc,
    section: SectionNode,
    file: str,
    *,
    rule: str,
    matched_on: str,
    lexicon: ErrataLexicon,
) -> ErrataTarget:
    return ErrataTarget(
        kind=ErrataTargetKind.SECTION,
        id=file,
        doc=doc.name,
        label=section.full_title,
        section=section.number,
        page=section.page_start,
        confidence=lexicon.grade(rule),
        rule=rule,
        matched_on=matched_on,
    )


def _spec_target(
    doc: TargetDoc,
    record: SpecRecord,
    *,
    rule: str,
    matched_on: str,
    lexicon: ErrataLexicon,
) -> ErrataTarget:
    label = " ".join(part for part in (record.symbol, record.name) if part).strip()
    return _record_target(
        doc,
        record,
        artifact=SPECS_ARTIFACT,
        kind=ErrataTargetKind.SPEC,
        label=label,
        rule=rule,
        matched_on=matched_on,
        lexicon=lexicon,
    )


def _record_target(
    doc: TargetDoc,
    record,
    *,
    artifact: str,
    kind: ErrataTargetKind,
    label: str,
    rule: str,
    matched_on: str,
    lexicon: ErrataLexicon,
) -> ErrataTarget:
    """One record target, referenced the way ADR 0005 references a record.

    A record published without an id (a corpus written before ADR 0005) yields a
    reference that names no record. It is kept rather than dropped — the section
    and the page on it are still true, and the erratum is still placed — but the
    reference is honestly empty rather than pointing at a neighbouring row.
    """
    ref = source_ref(f"{doc.reference_base}/{artifact}", record.id) if record.id else ""
    return ErrataTarget(
        kind=kind,
        id=ref,
        doc=doc.name,
        label=label,
        section=record.section,
        page=record.page,
        confidence=lexicon.grade(rule),
        rule=rule,
        matched_on=matched_on,
    )
