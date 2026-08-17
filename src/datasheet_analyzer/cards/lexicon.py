"""The design-card lexicon — which printed rows belong on which card.

`registry/cards.yaml` is the data; this module only loads it and answers "does
this record belong to this group?". The split is the same one `structure/
aliases.py` makes: the lexicon knows *words*, the builder knows *records*.

Two rules the data carries, both load-bearing.

**A group's row predicates are OR'd; its `section_titles` are AND'd on top.**
`symbol_contains`, `name_contains` and `alias_symbols` each answer "is this row
the kind of parameter this group is about?", so any one of them claiming a row is
enough. `section_titles` answers a different question — "was it printed on the
right table?" — and a card that ignores it computes a supply rail out of an
absolute-maximum rating.

**Every match names itself.** `claims()` hands back the predicate that matched
(`symbol_contains:vdd`), which becomes the row's `selector` on the published
card: ADR 0005 (c) allows a structural label from a checked-in lexicon *and*
requires the derivation to be named, exactly as a pin publishes the phrase that
decided its type.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from datasheet_analyzer.models import PinType, SpecRecord
from datasheet_analyzer.structure.aliases import AliasLexicon, load_lexicon
from datasheet_analyzer.structure.quantities import SI_UNITS

log = logging.getLogger(__name__)

LEXICON_PATH = Path(__file__).resolve().parent.parent / "registry" / "cards.yaml"

#: The value-bearing roles a card group may publish, in printed order.
ROLES: tuple[str, ...] = ("min", "typ", "max", "value")

#: What a group is built from: printed spec rows, or the part's pin records.
KIND_SPEC = "spec"
KIND_PINS = "pins"

#: The only reduction a group may declare (see `CardGroup.reduce`).
REDUCE_MAX = "max"


@dataclass(frozen=True)
class CardGroup:
    """One table of one card: what it selects, and what it publishes."""

    id: str
    title: str = ""
    kind: str = KIND_SPEC
    roles: tuple[str, ...] = ROLES
    section_titles: tuple[str, ...] = ()
    unit_bases: tuple[str, ...] = ()
    alias_symbols: tuple[str, ...] = ()
    symbol_contains: tuple[str, ...] = ()
    name_contains: tuple[str, ...] = ()
    pin_types: tuple[PinType, ...] = ()
    reduce: str = ""

    @property
    def has_row_predicate(self) -> bool:
        """Whether anything in the data can claim a row for this group.

        A group with no predicate would claim every row of every table it is
        pointed at, which is how a card stops being task-shaped.
        """
        return bool(self.alias_symbols or self.symbol_contains or self.name_contains)

    def in_section(self, record: SpecRecord) -> bool:
        """Whether the row was printed on a table this group accepts.

        `True` when the group declares no `section_titles` — a group like
        `interface` genuinely spans a document, and requiring a title there
        would empty the card on every part that names its sections differently.
        A row whose section title is unknown ("" — a corpus published before
        `SpecRecord.section_title` existed) never satisfies a title restriction:
        an unknown table is not evidence of the right one.
        """
        if not self.section_titles:
            return True
        title = (record.section_title or "").lower()
        return bool(title) and any(phrase in title for phrase in self.section_titles)

    def in_unit(self, record: SpecRecord) -> bool:
        """Whether the row states the physical quantity this group is about.

        The discriminator the printed text cannot always give: AD9081 prints its
        rails and its rail *currents* on two tables inside one section, so a
        title cannot tell them apart and both name `AVDD2`. A volt is not an
        amp, and `SI_UNITS` already knows which base a printed unit scales to.

        A row whose unit the SI lexicon cannot scale never satisfies a
        `unit_bases` restriction: a rail is stated in volts, and a cell nobody
        can read the unit of is not evidence of one. Groups that declare no
        `unit_bases` (the interface card's timing and compliance rows, which mix
        picoseconds with the word `JESD204B`) are unaffected.
        """
        if not self.unit_bases:
            return True
        scaled = SI_UNITS.get(record.unit.canonical)
        return scaled is not None and scaled[0] in self.unit_bases

    def claims(self, record: SpecRecord, *, aliases: AliasLexicon) -> str:
        """The predicate that claims this row (`symbol_contains:vdd`), or `""`.

        Order is strongest evidence first — the alias lexicon's whole-phrase
        reading of what the row *is*, then the printed symbol, then the printed
        name — so the recorded selector names the most specific rule that
        applied rather than whichever happened to be checked first.
        """
        if not self.in_section(record) or not self.in_unit(record):
            return ""
        if self.alias_symbols:
            entry = aliases.entry_for(record.symbol, record.name)
            if entry is not None and entry.symbol in self.alias_symbols:
                return f"alias:{entry.symbol}"
        symbol = (record.symbol or "").lower()
        for phrase in self.symbol_contains:
            if phrase in symbol:
                return f"symbol_contains:{phrase}"
        name = (record.name or "").lower()
        for phrase in self.name_contains:
            if phrase in name:
                return f"name_contains:{phrase}"
        return ""

    def wanted(self) -> str:
        """One line naming what this group looked for — an empty card's reason."""
        parts: list[str] = []
        if self.alias_symbols:
            parts.append(f"alias symbols {', '.join(self.alias_symbols)}")
        if self.symbol_contains:
            parts.append(f"symbols containing {', '.join(repr(p) for p in self.symbol_contains)}")
        if self.name_contains:
            parts.append(f"names containing {', '.join(repr(p) for p in self.name_contains)}")
        if self.pin_types:
            parts.append(f"pins of type {', '.join(t.value for t in self.pin_types)}")
        where = (
            f" on a table under a section titled "
            f"{', '.join(repr(t) for t in self.section_titles)}"
            if self.section_titles
            else ""
        )
        if self.unit_bases:
            where += f", stated in {', '.join(self.unit_bases)}"
        return f"{self.id}: {'; '.join(parts) or 'nothing'}{where}"


@dataclass(frozen=True)
class LimitsJoin:
    """The two tables the limits card joins, and the column it compares."""

    role: str = "max"
    abs_max_titles: tuple[str, ...] = ()
    recommended_titles: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return bool(self.abs_max_titles and self.recommended_titles)

    def side(self, record: SpecRecord, *, abs_max: bool) -> bool:
        """Whether the row was printed on the abs-max / recommended table."""
        title = (record.section_title or "").lower()
        titles = self.abs_max_titles if abs_max else self.recommended_titles
        return bool(title) and any(phrase in title for phrase in titles)


@dataclass(frozen=True)
class CardSpec:
    """One card as the lexicon declares it."""

    name: str
    title: str = ""
    purpose: str = ""
    groups: tuple[CardGroup, ...] = ()
    join: LimitsJoin | None = None


@dataclass(frozen=True)
class CardLexicon:
    """The loaded `cards.yaml`, in file order."""

    cards: tuple[CardSpec, ...] = ()
    aliases: AliasLexicon = field(default_factory=AliasLexicon)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.cards)

    def card(self, name: str) -> CardSpec | None:
        key = (name or "").strip().lower()
        return next((c for c in self.cards if c.name == key), None)

    @classmethod
    def from_mapping(cls, data: dict | None, *, aliases: AliasLexicon | None = None) -> CardLexicon:
        """Build from parsed YAML; a malformed card warns and is skipped.

        One bad card must not take the other three with it — the same stance
        `aliases.py`, `pins.py` and `device_tables.py` take on their lexicons.
        """
        cards: list[CardSpec] = []
        for name, body in (data or {}).items():
            if not isinstance(body, dict):
                log.warning("skipping malformed card entry %r: not a mapping", name)
                continue
            groups = tuple(
                g
                for g in (_group(raw, card=str(name)) for raw in body.get("groups") or [])
                if g is not None
            )
            join = _join(body.get("join"), card=str(name))
            if not groups and join is None:
                log.warning("skipping card %r: it declares neither a group nor a join", name)
                continue
            cards.append(
                CardSpec(
                    name=str(name).strip().lower(),
                    title=str(body.get("title") or name),
                    purpose=" ".join(str(body.get("purpose") or "").split()),
                    groups=groups,
                    join=join,
                )
            )
        return cls(cards=tuple(cards), aliases=aliases or load_lexicon())

    @classmethod
    def read(cls, path: Path | None = None) -> CardLexicon:
        """Parse a lexicon file; an unreadable one degrades to an empty one.

        An empty lexicon publishes no cards at all, which is the honest
        degradation: no card rather than rows selected by a rule nobody can read.
        """
        path = Path(path) if path else LEXICON_PATH
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            log.warning("card lexicon unavailable (%s: %s) — no cards", path, exc)
            return cls()
        return cls.from_mapping(data)


def _group(raw: object, *, card: str) -> CardGroup | None:
    """One `groups:` entry, or `None` when it is not usable."""
    if not isinstance(raw, dict) or not raw.get("id"):
        log.warning("skipping malformed group in card %r: %r", card, raw)
        return None
    kind = str(raw.get("kind") or KIND_SPEC).strip().lower()
    if kind not in (KIND_SPEC, KIND_PINS):
        log.warning("skipping group %r in card %r: unknown kind %r", raw.get("id"), card, kind)
        return None
    roles = tuple(r for r in _phrases(raw.get("roles"), lower=True) if r in ROLES) or ROLES
    reduce = str(raw.get("reduce") or "").strip().lower()
    if reduce and reduce != REDUCE_MAX:
        log.warning(
            "ignoring unknown reduce %r on group %r of card %r", reduce, raw.get("id"), card
        )
        reduce = ""
    group = CardGroup(
        id=str(raw["id"]).strip(),
        title=str(raw.get("title") or raw["id"]),
        kind=kind,
        roles=roles,
        section_titles=_phrases(raw.get("section_titles"), lower=True),
        # Unit bases keep their case: they are `SI_UNITS` bases (`V`, `A`, `W`).
        unit_bases=_phrases(raw.get("unit_bases")),
        # Alias symbols keep their printed case: they are keys of
        # `registry/aliases.yaml` (`TJ`, `t(SCLK)`), not free text.
        alias_symbols=_phrases(raw.get("alias_symbols")),
        symbol_contains=_phrases(raw.get("symbol_contains"), lower=True),
        name_contains=_phrases(raw.get("name_contains"), lower=True),
        pin_types=_pin_types(raw.get("pin_types"), card=card),
        reduce=reduce,
    )
    if group.kind == KIND_SPEC and not group.has_row_predicate:
        log.warning("skipping group %r in card %r: no row predicate", group.id, card)
        return None
    if group.kind == KIND_PINS and not group.pin_types:
        log.warning("skipping pin group %r in card %r: no pin types", group.id, card)
        return None
    return group


def _join(raw: object, *, card: str) -> LimitsJoin | None:
    """The `join:` block of the limits card, or `None`."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        log.warning("skipping malformed join in card %r: %r", card, raw)
        return None
    abs_max = raw.get("abs_max") if isinstance(raw.get("abs_max"), dict) else {}
    recommended = raw.get("recommended") if isinstance(raw.get("recommended"), dict) else {}
    role = str(raw.get("role") or "max").strip().lower()
    if role not in ROLES:
        log.warning("skipping join in card %r: unknown role %r", card, role)
        return None
    return LimitsJoin(
        role=role,
        abs_max_titles=_phrases(abs_max.get("section_titles"), lower=True),
        recommended_titles=_phrases(recommended.get("section_titles"), lower=True),
    )


def _pin_types(value: object, *, card: str) -> tuple[PinType, ...]:
    """`pin_types:` as lexicon labels; an unknown one warns and is dropped."""
    out: list[PinType] = []
    for name in _phrases(value, lower=True):
        try:
            out.append(PinType(name))
        except ValueError:
            log.warning("skipping unknown pin type %r in card %r", name, card)
    return tuple(out)


def _phrases(value: object, *, lower: bool = False) -> tuple[str, ...]:
    """A YAML string-or-list as a de-duplicated tuple in file order."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    cleaned = [str(v).strip() for v in value]
    cleaned = [v.lower() if lower else v for v in cleaned]
    return tuple(dict.fromkeys(v for v in cleaned if v))


@cache
def load_card_lexicon(path: Path | None = None) -> CardLexicon:
    """The shipped card lexicon, parsed once per process (or one at `path`)."""
    return CardLexicon.read(path)


def clear_card_lexicon_cache() -> None:
    """Test hook: re-read the lexicon file on the next `load_card_lexicon`."""
    load_card_lexicon.cache_clear()
