"""The errata lexicon — the words an errata document uses, as data.

`registry/errata.yaml` is the data; this module only loads it and answers three
questions: does this printed line start an item, does this phrase cue a section
number or a pin designator, and what grade does a named rule carry. The split is
the one `structure/aliases.py` and `cards/lexicon.py` already make: the lexicon
knows *words*, the linker knows *records*.

What is deliberately **not** here is any notion of similarity. Every rule in
`errata/link.py` compares a printed identifier to a published one exactly, so
there is no threshold in this file to loosen — the one knob that could turn a
coincidence into a link does not exist.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from datasheet_analyzer.models import Confidence

log = logging.getLogger(__name__)

LEXICON_PATH = Path(__file__).resolve().parent.parent / "registry" / "errata.yaml"

#: The named rules a link may be produced by. They are the keys of the
#: lexicon's `rules` block, and a rule the lexicon does not grade falls back to
#: `Confidence.UNKNOWN` — honestly ungraded, never optimistically high.
RULE_SECTION_NUMBER = "section-number"
RULE_TABLE_CAPTION = "table-caption"
RULE_SPEC_SYMBOL = "spec-symbol"
RULE_ALIAS_PHRASE = "alias-phrase"
RULE_PIN_NAME = "pin-name"
RULE_PIN_DESIGNATOR = "pin-designator"
RULE_REGISTER_NAME = "register-name"
RULE_REGISTER_ADDRESS = "register-address"
RULES: tuple[str, ...] = (
    RULE_SECTION_NUMBER,
    RULE_TABLE_CAPTION,
    RULE_SPEC_SYMBOL,
    RULE_ALIAS_PHRASE,
    RULE_PIN_NAME,
    RULE_PIN_DESIGNATOR,
    RULE_REGISTER_NAME,
    RULE_REGISTER_ADDRESS,
)

#: An item marker is `<word> <identifier>` — "Advisory 3", "Erratum 12b",
#: "Issue A". The identifier half is required: a paragraph that merely opens
#: with the word "Item" is prose, not a heading.
#:
#: Case is handled per-piece rather than with a whole-pattern `IGNORECASE`, and
#: that is load-bearing: a case-insensitive single-letter identifier turns
#: "Item numbers are listed below" into a heading, because `[A-Z]` then matches
#: the `s` of "numbers". The marker word and the optional `no.` are matched
#: case-insensitively; the bare-letter identifier stays capital-only.
_MARKER_TAIL = r"\s*(?:(?i:no\.?|number|#))?\s*(?:[0-9]+[A-Za-z]?|[A-Z])\b"

#: An ordinal item opener — "3.", "3)" — used only when a document declares no
#: marker word at all (see `ErrataLexicon.item_start`).
_ORDINAL = re.compile(r"^\s*([0-9]{1,3})\s*[.)]\s+\S")


@dataclass(frozen=True)
class ErrataLexicon:
    """The loaded `errata.yaml`."""

    item_markers: tuple[str, ...] = ()
    numbered_items: bool = True
    section_cues: tuple[str, ...] = ()
    pin_cues: tuple[str, ...] = ()
    min_identifier_chars: int = 2
    min_caption_chars: int = 8
    max_targets_per_rule: int = 25
    rules: tuple[tuple[str, str], ...] = ()

    def grade(self, rule: str) -> Confidence:
        """The grade the data gives one named rule; `UNKNOWN` when it grades none."""
        for name, value in self.rules:
            if name == rule:
                try:
                    return Confidence(value)
                except ValueError:
                    log.warning(
                        "errata lexicon grades rule %r as %r, which is not a "
                        "confidence — reading it as unknown",
                        rule,
                        value,
                    )
                    return Confidence.UNKNOWN
        return Confidence.UNKNOWN

    def marker_start(self, line: str) -> str:
        """The marker this line opens with (`Advisory 3`), or `""`.

        Longest marker phrase wins, so a lexicon declaring both `item` and
        `errata item` reads "Errata item 4" as the more specific one.
        """
        best = ""
        for word in self.item_markers:
            match = re.match(rf"^\s*((?i:{re.escape(word)}){_MARKER_TAIL})", line)
            if match and len(match.group(1)) > len(best):
                best = match.group(1)
        return best.strip()

    def ordinal_start(self, line: str) -> str:
        """The ordinal this line opens with (`3.`), or `""` when disabled/absent."""
        if not self.numbered_items:
            return ""
        match = _ORDINAL.match(line)
        return f"{match.group(1)}." if match else ""

    @property
    def section_cue_pattern(self) -> re.Pattern[str] | None:
        """`(?:Section|§)\\s*7.3.2` — the only way a section number is read.

        A bare dotted number in errata prose is far more often a voltage than a
        section, so the cue is mandatory. `None` when the lexicon declares no
        cues, which disables the rule rather than loosening it.
        """
        if not self.section_cues:
            return None
        alts = "|".join(re.escape(cue) for cue in self.section_cues)
        return re.compile(rf"(?P<cue>{alts})\s*(?P<number>[0-9]+(?:\.[0-9]+)*)", re.IGNORECASE)

    @property
    def pin_cue_pattern(self) -> re.Pattern[str] | None:
        """`(?:pin|ball)\\s*A1` — the only way a pin designator is read."""
        if not self.pin_cues:
            return None
        alts = "|".join(re.escape(cue) for cue in self.pin_cues)
        return re.compile(
            rf"(?P<cue>{alts})\s+(?P<pin>[A-Za-z]{{0,2}}[0-9]{{1,3}}|[A-Za-z][0-9]+)\b",
            re.IGNORECASE,
        )

    @classmethod
    def from_mapping(cls, data: dict | None) -> ErrataLexicon:
        """Build from parsed YAML; a malformed key degrades to its default."""
        data = data or {}

        def words(key: str) -> tuple[str, ...]:
            raw = data.get(key) or []
            if isinstance(raw, str):
                raw = [raw]
            if not isinstance(raw, list):
                log.warning("errata lexicon: %r is not a list — ignoring it", key)
                return ()
            return tuple(str(w) for w in raw if str(w).strip())

        def number(key: str, default: int) -> int:
            raw = data.get(key, default)
            try:
                return int(raw)
            except (TypeError, ValueError):
                log.warning(
                    "errata lexicon: %r is not a number (%r) — using %d",
                    key,
                    raw,
                    default,
                )
                return default

        rules = data.get("rules") or {}
        if not isinstance(rules, dict):
            log.warning("errata lexicon: `rules` is not a mapping — no rule is graded")
            rules = {}
        return cls(
            item_markers=words("item_markers"),
            numbered_items=bool(data.get("numbered_items", True)),
            section_cues=words("section_cues"),
            pin_cues=words("pin_cues"),
            min_identifier_chars=number("min_identifier_chars", 2),
            min_caption_chars=number("min_caption_chars", 8),
            max_targets_per_rule=number("max_targets_per_rule", 25),
            rules=tuple((str(k), str(v)) for k, v in rules.items()),
        )

    @classmethod
    def read(cls, path: Path | None = None) -> ErrataLexicon:
        """Parse a lexicon file; an unreadable one degrades to an empty one.

        An empty lexicon declares no markers and no cues, so it segments an
        errata document by section and links nothing — honest degradation
        (invariant 7): every item is still published, under "unlinked errata".
        """
        path = Path(path) if path else LEXICON_PATH
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            log.warning(
                "errata lexicon unavailable (%s: %s) — every item publishes unlinked",
                path,
                exc,
            )
            return cls(item_markers=(), section_cues=(), pin_cues=(), rules=())
        return cls.from_mapping(data)


@cache
def load_errata_lexicon(path: Path | None = None) -> ErrataLexicon:
    """The shipped lexicon, parsed once per process (or one at `path`)."""
    return ErrataLexicon.read(path)


def clear_errata_lexicon_cache() -> None:
    """Test hook: re-read the lexicon file on the next `load_errata_lexicon`."""
    load_errata_lexicon.cache_clear()
