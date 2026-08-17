"""`Retriever` — every corpus lookup, returning typed hits.

One instance wraps one `CorpusIndex`, so a session that asks a part twenty
questions parses its JSON once. Each hit says *how* it matched
(`matched_via`) and carries a `Citation` instead of leaving the caller to
build one.

Spec lookups run the **alias ladder** (ticket 02), first non-empty rung wins:

| # | Rung | `matched_via` |
|---|---|---|
| 1 | exact symbol (plus its materialized child rows) | `symbol` |
| 2 | alias phrase from `registry/aliases.yaml` | `alias:<phrase>` |
| 3 | alias prefix family (`IDD` → `IVDD1P8`, …) | `alias-prefix:<prefix>` |
| 4 | symbol / name substring (the pre-ticket-02 behaviour) | `symbol-substring`, `name-substring` |
| 5 | token-overlap fuzzy over the record name | `fuzzy` |

`expect_unit` never removes a candidate — it only sorts the ones a rung
already returned, so a record whose unit is missing still answers. Nothing
matches at all → an empty list plus `suggest_specs()` for the nearest
candidates, never a rung-6 guess.

`pins()` (phase 6, ticket 04) is the pin table as a lookup: exact designator,
name or description substring, or lexicon type. It is deliberately *not* a
ladder — a pin designator is an exact thing and a near-miss on one is a wiring
error — and `pin_gap()` is its honest-absence half, the twin of
`search_unavailable()`: a part with no pin table must not answer "no such pin".

`search()` (ticket 03) is the second retrieval path: BM25 over the
`search_index.json` built at publish, returning section hits cited from the
manifest. A corpus built before the index existed does not crash and does not
silently answer nothing — `search_unavailable()` says to rebuild.

`card()` (phase 6, ticket 07) is the design cards, derived live from the same
records by `cards/` — the corpus's `cards/*.json` are that function's output too,
so a front end and a file can never disagree about what a card says.

`ask()` (ticket 05) composes all of it: one question in, one cited,
budget-bounded `AnswerPack` out. The routing and the budget arithmetic live in
`retrieve/pack.py`; this class stays the place lookups happen.

Every spec and plot hit also carries the record's own `confidence` (ticket 04),
read off the record — never recomputed here, and never used to drop, hide or
reorder a hit. Grading is metadata; retrieval order stays the ladder's.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from datasheet_analyzer.config import SEARCH_SCHEMA_VERSION
from datasheet_analyzer.models import (
    DesignCard,
    PinRecord,
    PlotRecord,
    RegisterRecord,
    SearchIndex,
    SectionFile,
    SpecRecord,
)
from datasheet_analyzer.retrieve.index import CorpusIndex, IndexedDoc
from datasheet_analyzer.retrieve.results import (
    Citation,
    PinHit,
    PlotHit,
    RegisterHit,
    SearchHit,
    SectionHit,
    SpecHit,
    record_confidence,
)
from datasheet_analyzer.retrieve.search import ScoredSection, score_sections, snippet
from datasheet_analyzer.structure.aliases import (
    FUZZY_MIN_TOKENS,
    FUZZY_THRESHOLD,
    AliasEntry,
    AliasLexicon,
    load_lexicon,
    normalize,
    padded,
    similarity,
    token_overlap,
    tokens,
)
from datasheet_analyzer.structure.plot_axes import axis_population
from datasheet_analyzer.structure.quantities import SI_UNITS, Quantity, parse_quantity
from datasheet_analyzer.structure.registers import parse_register_word
from datasheet_analyzer.structure.units import canonical_unit

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from datasheet_analyzer.retrieve.pack import AnswerPack

# The words a designer uses to say "I want a picture". `retrieve.pack` routes
# on this constant and `plots_for_terms` ranks with it, so the router and the
# ranker cannot disagree about what plot vocabulary is. `diagram` is the
# plan's list plus one measured addition: "where is the functional block
# diagram?" is a figure question by any reading, and QPA1003P's golden asks it
# in exactly those words.
PLOT_VOCABULARY = re.compile(
    r"\b(plots?|curves?|vs\.?|versus|graphs?|figures?|diagrams?)\b", re.IGNORECASE
)
# The subset that is *dead weight when ranking*: every caption in a plot
# gallery says "vs." and every AFE7950 caption starts "Figure N", so scoring
# on them ranks nothing and would let every figure match. `diagram` is
# deliberately not here — it names a figure rather than describing all of them.
_PLOT_WORDS = frozenset(
    {"plot", "plots", "curve", "curves", "vs", "versus", "graph", "graphs",
     "figure", "figures", "show", "shows", "showing"}
)

# The words a designer uses to say "I am asking about the pin table", and the
# words a firmware engineer uses to say "I am asking about the register map".
# Same contract as `PLOT_VOCABULARY`: `retrieve.pack` routes on these constants
# and the two `*_for_terms` lookups below read with them, so the router and the
# lookup cannot disagree about what a pin question or a register question is.
PIN_VOCABULARY = re.compile(r"\b(pins?|balls?|pinouts?|terminals?)\b", re.IGNORECASE)
REGISTER_VOCABULARY = re.compile(
    r"\b(registers?|regmap|bit ?fields?|address(?:es)?|offsets?|resets?)\b",
    re.IGNORECASE,
)
# The subset of each that is *dead weight when looking up*: every pin record in
# a pin table is a pin and every register in a register map has an address, so
# matching on those words would return the whole table rather than the entry the
# question named. Dropped before the rungs run, exactly as `_PLOT_WORDS` is.
_PIN_WORDS = frozenset(
    {"pin", "pins", "ball", "balls", "pinout", "pinouts", "terminal", "terminals",
     "list", "lists", "name", "named"}
)
_REGISTER_WORDS = frozenset(
    {"register", "registers", "regmap", "bit", "bits", "bitfield", "bitfields",
     "field", "fields", "address", "addresses", "offset", "offsets", "reset",
     "resets", "value", "values", "default", "defaults", "list", "lists"}
)
#: A token a document would print *as an address*: an explicit `0x` prefix or an
#: `h` suffix, the same two markers `parse_register_word` recognises. A bare
#: number in a sentence is a number — `dsa regs --addr 6660` may declare one
#: because the caller said so, but a question may not, or "what resets to 0?"
#: would silently become a lookup of register 0.
_ADDRESS_LITERAL = re.compile(r"(?:0x[0-9a-f]+|[0-9a-f]+h)\Z", re.IGNORECASE)

# One candidate record on its way to becoming a hit: the document it came
# from, the record, the alias entry (if any) that vouched for it — the entry
# is what carries `expect_unit` into the tie-break — and the rung label this
# candidate earned. The label is per candidate, not per rung, because two
# alias entries can tie on one rung and each hit should still name the phrase
# that found it.
_Candidate = tuple[IndexedDoc, SpecRecord, AliasEntry | None, str]


@dataclass(frozen=True)
class Retriever:
    """Lookups over one loaded part corpus."""

    index: CorpusIndex

    @classmethod
    def for_part(cls, part_dir: Path | str) -> Retriever:
        """Retriever over `part_dir`, reusing its cached index when current."""
        return cls(CorpusIndex.load(part_dir))

    @property
    def part_dir(self) -> Path:
        return self.index.part_dir

    @property
    def part(self) -> str:
        """The part number every hit from this retriever is cited under.

        Falls back to the corpus directory name so an unbuilt or
        manifest-less part still names *something* — a hit that cannot say
        which datasheet it came from is not cited (see `Citation.part`).
        """
        return self.index.part_number or self.index.part_dir.name

    @property
    def lexicon(self) -> AliasLexicon:
        return load_lexicon()

    def specs(
        self,
        *,
        symbol: str = "",
        name: str = "",
        section: str = "",
    ) -> list[SpecHit]:
        """Resolve a spec query through the alias ladder (see module docs).

        `symbol` and `name` are both just a designer's term; whichever is given
        drives the ladder. When both are given they still AND, as they always
        did — the unused one stays a filter on every rung.
        """
        pool = [
            (doc, rec)
            for doc in self.index.docs
            for rec in doc.specs
            if _passes(rec, section=section, also_name=name if (symbol and name) else "")
        ]
        term = (symbol or name).strip()
        if not term:
            label = "section" if section else "all"
            return _build_hits([(d, r, None, label) for d, r in pool], part=self.part)

        for candidates in self._spec_ladder(term, from_symbol=bool(symbol), pool=pool):
            if candidates:
                return _build_hits(candidates, part=self.part)
        return []

    def suggest_specs(self, term: str, limit: int = 5) -> list[str]:
        """Nearest candidate terms for a query that matched nothing.

        Drawn from the part's own symbols and names first — advice a caller can
        act on in this corpus — then topped up from the alias lexicon. An
        honest "no match, did you mean…" beats a fuzzy guess presented as an
        answer.
        """
        if not term.strip():
            return []
        pool: dict[str, str] = {}
        for doc in self.index.docs:
            for rec in doc.specs:
                for text in (rec.symbol, rec.name):
                    if text:
                        pool.setdefault(text.lower(), text)
        scored = [(similarity(term, label), label) for label in pool.values()]
        scored = [s for s in scored if s[0] > 0.0]
        scored.sort(key=lambda s: (-s[0], s[1]))
        out = [label for _score, label in scored[:limit]]
        for label in self.lexicon.nearest_names(term, limit):
            if len(out) >= limit:
                break
            if label not in out:
                out.append(label)
        return out[:limit]

    def _spec_ladder(
        self, term: str, *, from_symbol: bool, pool: list[tuple[IndexedDoc, SpecRecord]]
    ) -> Iterator[list[_Candidate]]:
        """Yield one candidate list per rung, strongest rung first."""
        lex = self.lexicon
        own = lex.by_symbol(term)

        # 1 — exact symbol, plus its materialized children. A rowspan child
        # (ticket 09) carries its parent's symbol with its own label appended,
        # so `Full-Scale Output Current Range` must still reach `… AC
        # Coupling`. The children only come along when the parent row itself
        # matched exactly; without that guard this rung would quietly become a
        # prefix search and shadow the alias rungs below it.
        low = term.lower()
        exact = [(doc, rec) for doc, rec in pool if rec.symbol.lower() == low]
        if exact:
            children = [
                (doc, rec) for doc, rec in pool if rec.symbol.lower().startswith(low + " ")
            ]
            # pool order, not exact-then-children order: the parent row still
            # prints before its children as the table printed them.
            keep = {id(rec) for _doc, rec in exact} | {id(rec) for _doc, rec in children}
            yield [(doc, rec, own, "symbol") for doc, rec in pool if id(rec) in keep]
        else:
            yield []

        # 2 — alias phrase. Candidates are the entry's canonical symbol *and*
        # any record whose own printed identity uses one of its phrases (see
        # `_printed_as`), because the layout floor records `Junction
        # temperature` as the symbol where TI records `TJ`. Entries whose
        # matched phrase is the same length tie on this rung and are offered
        # together, for `expect_unit` to separate.
        for group in _by_phrase_length(lex.phrase_hits(term)):
            candidates: list[_Candidate] = []
            claimed: set[tuple[int, int]] = set()
            for entry, phrase in group:
                entry_low = entry.symbol.lower()
                for doc, rec in pool:
                    if not (
                        rec.symbol.lower() == entry_low
                        or _in_family(rec, entry)
                        or entry.describes(_printed_as(rec))
                    ):
                        continue
                    key = (id(doc), id(rec))
                    if key in claimed:
                        continue
                    claimed.add(key)
                    candidates.append((doc, rec, entry, f"alias:{phrase}"))
            yield candidates

        # 3 — alias prefix family. Naming any one prefix (`IDD`) opens the
        # whole family (`IVDD1P8`, `IVDD1P2`, …); every family the term names
        # ties on this rung.
        prefix_hits = lex.prefix_hits(term)
        if prefix_hits:
            candidates = []
            claimed = set()
            for entry, prefix in prefix_hits:
                for doc, rec in pool:
                    if not _in_family(rec, entry):
                        continue
                    key = (id(doc), id(rec))
                    if key in claimed:
                        continue
                    claimed.add(key)
                    candidates.append((doc, rec, entry, f"alias-prefix:{prefix}"))
            yield candidates

        # 4 — substring, exactly as it behaved before the ladder existed.
        if from_symbol:
            yield [
                (doc, rec, own, "symbol-substring")
                for doc, rec in pool
                if low in rec.symbol.lower()
            ]
        else:
            yield [
                (doc, rec, own, "name-substring") for doc, rec in pool if low in rec.name.lower()
            ]

        # 5 — fuzzy, and only then. A single-token term never gets here.
        if len(tokens(term)) >= FUZZY_MIN_TOKENS:
            yield [
                (doc, rec, own, "fuzzy")
                for doc, rec in pool
                if token_overlap(term, rec.name) >= FUZZY_THRESHOLD
            ]

    def pins(
        self,
        *,
        pin: str = "",
        name: str = "",
        # `type` shadows the builtin deliberately: it is the record's own
        # field name, and a lookup that spells its filters differently from
        # the data it filters is a second vocabulary to learn.
        type: str = "",
        q: str = "",
    ) -> list[PinHit]:
        """Pins of this part, ANDed across the filters given (ticket 04).

        `pin` is an **exact** designator match, case-folded: a designer typing
        `A1` means ball A1 and not A10 to A19 as well. Everything else is a
        substring: `name` against the printed pin name, `q` against name and
        description together, and `type` against the lexicon label — where
        `unknown` is a legitimate value to ask for, because "which pins does
        this corpus not understand?" is a real question about the extraction.

        No filters at all returns the whole pin table, in printed order.
        """
        wanted_type = type.strip().lower()
        hits: list[PinHit] = []
        for doc in self.index.docs:
            for rec in doc.pins:
                if pin and rec.pin.casefold() != pin.strip().casefold():
                    continue
                if name and name.lower() not in rec.name.lower():
                    continue
                if wanted_type and rec.type.value != wanted_type:
                    continue
                if q and q.lower() not in f"{rec.name} {rec.description}".lower():
                    continue
                hits.append(
                    PinHit(
                        record=rec,
                        citation=Citation.for_pin(
                            rec, doc=doc.name, doc_hash=doc.doc_hash, part=self.part
                        ),
                        matched_via=_pin_matched_via(pin, name, wanted_type, q),
                        confidence=record_confidence(rec),
                    )
                )
        return hits

    def pin_gap(self) -> str:
        """`""` when this part has pins, else why a pin lookup found none.

        The same distinction `search_unavailable()` draws, for the same reason:
        an empty pin result means either "no pin matches that" or "this corpus
        has no pin table at all", and reading the second as the first would put
        a claim about the datasheet behind a gap in the extraction. Whether the
        pin table was rejected or never printed is a *document* finding and
        lives in the manifest's rejection reasons; what a caller needs here is
        that absence establishes nothing.
        """
        if any(doc.pins for doc in self.index.docs):
            return ""
        return (
            f"no pin table in the corpus for part {self.part} — this datasheet "
            f"prints none, or the one it prints was rejected (see `dsa status` "
            f"for the recorded reason). A pin lookup here establishes nothing."
        )

    def pins_for_terms(self, text: str, *, limit: int = 6) -> list[PinHit]:
        """Pins a question *names*, by exact rungs — never by resemblance.

        `plots_for_terms` ranks a catalog by overlap because a caption is prose.
        A pin is not prose: `A1` is not a near-miss for `A10`, and a designer
        handed the wrong pin has a wiring error rather than a disappointing
        search result. So this is a ladder of **exact token** rungs over the
        question's own words, first non-empty rung winning, and nothing at all
        when the question names no pin:

        | # | Rung | `matched_via` |
        |---|---|---|
        | 1 | a token that is a printed designator (`A1`) | `designator-terms` |
        | 2 | a token that is a printed pin name (`CLKIN`) | `name-terms` |
        | 3 | a token that is a lexicon pin type (`ground`) | `type-terms` |

        Rung 3 is what answers "which pins are ground?". It selects on a
        **derived** label, which is legitimate under ADR 0005 (c) precisely
        because the label is a checked-in lexicon one and every record publishes
        the phrase that decided it — an agent can check the classification
        instead of trusting it.

        Deterministic throughout (rung, then the pin table's printed order), and
        `[]` is an honest outcome the caller answers with `pin_gap()` rather
        than reading absence into.
        """
        terms = {t for t in tokens(text) if t not in _PIN_WORDS}
        if not terms:
            return []
        pool = self.pins()
        rungs: tuple[tuple[str, Callable[[PinRecord], set[str]]], ...] = (
            ("designator-terms", lambda rec: {normalize(rec.pin)}),
            ("name-terms", lambda rec: {normalize(rec.name)}),
            ("type-terms", lambda rec: {rec.type.value}),
        )
        for label, key in rungs:
            hits = [hit for hit in pool if key(hit.record) & terms]
            if hits:
                return [
                    replace(hit, matched_via=label)
                    for hit in (hits[:limit] if limit > 0 else hits)
                ]
        return []

    def registers_for_terms(self, text: str, *, limit: int = 4) -> list[RegisterHit]:
        """Registers a question *names*, by exact rungs — `pins_for_terms`' twin.

        Same reasoning one noun over, and with more at stake: a firmware
        engineer handed the neighbouring register writes the wrong word to
        silicon. The rungs, first non-empty one winning:

        | # | Rung | `matched_via` |
        |---|---|---|
        | 1 | a token printed *as an address* (`0x19`, `19h`) | `address-terms` |
        | 2 | a token that is a printed acronym (`R25`) | `name-terms` |
        | 3 | a token that is a published bit-field name (`CLK_MUX`) | `field-terms` |

        Rung 1 deliberately requires the document's own hex marker
        (`_ADDRESS_LITERAL`): `dsa regs --addr 6660` may declare a bare number to
        be an address because the caller said so, but a bare number inside a
        sentence is a number, and reading it as one would turn "what resets to 0?"
        into a lookup of register 0. Rung 3 selects on a *published* field set,
        which is why a caller reports `register_field_gap()` beside it.
        """
        terms = {t for t in tokens(text) if t not in _REGISTER_WORDS}
        if not terms:
            return []
        addresses = {t: parse_register_word(t) for t in terms if _ADDRESS_LITERAL.match(t)}
        pool = self.registers()
        by_address = [
            hit
            for hit in pool
            if any(
                _register_addr_matches(hit.record, value, printed)
                for printed, value in addresses.items()
            )
        ]
        rungs: tuple[tuple[str, list[RegisterHit]], ...] = (
            ("address-terms", by_address),
            ("name-terms", [h for h in pool if normalize(h.record.name) in terms]),
            (
                "field-terms",
                [
                    h for h in pool
                    if any(normalize(f.name) in terms for f in h.record.fields)
                ],
            ),
        )
        for label, hits in rungs:
            if hits:
                return [
                    replace(hit, matched_via=label)
                    for hit in (hits[:limit] if limit > 0 else hits)
                ]
        return []

    def registers(
        self,
        *,
        addr: str = "",
        name: str = "",
        field: str = "",
        q: str = "",
    ) -> list[RegisterHit]:
        """Registers of this part, ANDed across the filters given (ticket 05).

        `addr` resolves by **parsed value** wherever both sides parse, so
        `0x1A04`, `0x1a04` and `6660` are one question — that equivalence is
        the whole reason a register record carries an integer beside its
        printed string. An address the grammar cannot read falls back to an
        exact, case-folded match on the printed text, so a register whose cell
        never parsed is still reachable by typing what the page shows.

        `name` is an exact, case-folded match on the printed acronym: `R1` is
        register 1 and not R11 through R19 as well, the same reason
        `pins(pin=...)` is exact. `field` is the **bit-field** filter (ticket
        06) — a substring over the published field names, because a firmware
        engineer knows `NCO_EN` and wants the register it lives in, and it
        matches nothing at all on a register whose field set was refused rather
        than pretending the field is absent from the device. `q` is the loose
        one — a substring over the name and the description together.

        No filters at all returns the whole register map, in printed order.
        """
        wanted = parse_register_word(addr) if addr else None
        low_addr = addr.strip().casefold()
        low_name = name.strip().casefold()
        low_field = field.strip().casefold()
        hits: list[RegisterHit] = []
        for doc in self.index.docs:
            for rec in doc.registers:
                if addr and not _register_addr_matches(rec, wanted, low_addr):
                    continue
                if name and rec.name.casefold() != low_name:
                    continue
                if low_field and not any(
                    low_field in f.name.casefold() for f in rec.fields
                ):
                    continue
                if q and q.lower() not in f"{rec.name} {rec.description}".lower():
                    continue
                hits.append(
                    RegisterHit(
                        record=rec,
                        citation=Citation.for_register(
                            rec, doc=doc.name, doc_hash=doc.doc_hash, part=self.part
                        ),
                        matched_via=_register_matched_via(addr, name, field, q),
                        confidence=record_confidence(rec),
                    )
                )
        return hits

    def register_gap(self) -> str:
        """`""` when this part has registers, else why a lookup found none.

        `pin_gap()`'s twin, for the same reason: an empty register result means
        either "no register matches that" or "this corpus holds no register map
        at all", and reading the second as the first would tell a firmware
        engineer that a register does not exist when nobody ever looked.
        """
        if any(doc.registers for doc in self.index.docs):
            return ""
        return (
            f"no register summary in the corpus for part {self.part} — no "
            f"document of this part prints one, or the one it prints was "
            f"rejected (see `dsa status` for the recorded reason). A register "
            f"lookup here establishes nothing."
        )

    def register_field_gap(self) -> str:
        """`""` when every register here publishes bit fields, else what is missing.

        Invariant 8's honesty clause for the one filter that *selects* on a
        derived value: `registers(field=...)` can only match a register whose
        field set was published, so a caller filtering on a field name has an
        unconsidered population and must be told its size. Unlike
        `register_gap()` this is not an unavailability — the register map is
        there and answers by address and name — it is the note that goes beside
        a field result, which is why it names the count instead of refusing.
        """
        registers = [rec for doc in self.index.docs for rec in doc.registers]
        without = [rec for rec in registers if not rec.fields]
        if not registers or not without:
            return ""
        return (
            f"{len(without)} of {len(registers)} registers in the corpus for part "
            f"{self.part} publish no bit fields ({', '.join(r.name or r.address.verbatim for r in without[:6])}"
            f"{', …' if len(without) > 6 else ''}); each says why in its own "
            f"`fields_reason`. A bit-field lookup here cannot establish that a "
            f"field does not exist."
        )

    def plots(
        self,
        *,
        q: str = "",
        caption: str = "",
        conditions: str = "",
        section: str = "",
        tags: list[str] | None = None,
        x_label: str = "",
        y_label: str = "",
        near_x: str = "",
    ) -> list[PlotHit]:
        """AND-match caption/conditions text, exact section number, and tags.

        `q` searches the combined caption + conditions text; `caption` and
        `conditions` restrict those fields independently.

        `x_label` / `y_label` / `near_x` (phase 6, ticket 08) filter on the
        **axis catalog** — substring over the printed axis title, and "the x axis
        covers this quantity" for `near_x`, which is a printed value the numeric
        layer parses ("3.5GHz") compared against the axis's printed tick range in
        the same SI base. They are AND clauses like every other filter here, and
        they are deliberately *narrowing only*: a figure whose axes could not be
        read is excluded from an axis-filtered result and counted by
        `plot_axis_gap()`, because a filter on a derived value owes its caller
        the population it could not consider (invariant 8).
        """
        tags = tags or []
        want = parse_quantity(near_x) if near_x.strip() else None
        hits: list[PlotHit] = []
        for doc in self.index.docs:
            for rec in doc.plots:
                haystack = (rec.caption + " " + rec.conditions).lower()
                if q and q.lower() not in haystack:
                    continue
                if caption and caption.lower() not in rec.caption.lower():
                    continue
                if conditions and conditions.lower() not in rec.conditions.lower():
                    continue
                if section and section != rec.section:
                    continue
                if tags and not all(t.lower() in (rec.tags or []) for t in tags):
                    continue
                if x_label and x_label.lower() not in rec.x_label.lower():
                    continue
                if y_label and y_label.lower() not in rec.y_label.lower():
                    continue
                if near_x.strip() and not _axis_covers(rec, want):
                    continue
                hits.append(
                    PlotHit(
                        record=rec,
                        citation=Citation.for_plot(
                            rec, doc=doc.name, doc_hash=doc.doc_hash, part=self.part
                        ),
                        matched_via=_plot_matched_via(
                            rec, q, caption, conditions, section, tags,
                            x_label, y_label, near_x,
                        ),
                        confidence=record_confidence(rec),
                    )
                )
        return hits

    def plot_axis_gap(self, *, axis: str = "x") -> str:
        """What an axis-filtered figure lookup could not consider, in one line.

        `register_field_gap()`'s twin, for the same reason and with the same
        force: `--x-label` / `--near-x` select on a **derived** value, so an
        empty result must never read as "this part prints no such figure" when
        the truth is "these figures print their axes as pixels" (measured:
        AD9081's 100 plots are raster images and publish no axes at all). It is a
        note, not a refusal — the caption and conditions paths still answer.
        """
        records = [rec for doc in self.index.docs for rec in doc.plots]
        population = axis_population(records, axis=axis)
        if not population.total or not population.unreadable:
            return ""
        return (
            f"{population.describe()} in the corpus for part {self.part}; each "
            f"says so with `axis_confidence` and null axis fields. An "
            f"axis-filtered figure lookup here cannot establish that no such "
            f"figure exists."
        )

    def plot_axis_gap_for(
        self, *, x_label: str = "", y_label: str = "", near_x: str = ""
    ) -> str:
        """The gap one `plots()` call owes its caller — `""` when it filtered on
        no axis at all.

        Which axis to report is a decision, so it lives here and not in a front
        end: `dsa plots` and the MCP `find_plots` tool must never print different
        populations for the same query. `--near-x` asks about the x axis; a bare
        `--y-label` asks about the y one.
        """
        axis = gap_axis(x_label=x_label, y_label=y_label, near_x=near_x)
        return self.plot_axis_gap(axis=axis) if axis else ""

    def plots_for_terms(self, text: str, *, limit: int = 5) -> list[PlotHit]:
        """Rank the plot catalog by how much of `text`'s vocabulary it uses.

        `plots()` is exact — a caller must already know a caption substring.
        A designer asking "which figure shows TX output fullscale vs
        frequency?" knows no such thing, so the terms are matched
        individually against caption + conditions and the figures using most
        of them lead. Plot vocabulary itself is dropped first: every caption
        in a gallery says "vs.", so scoring on it ranks nothing and would let
        every figure match.

        Deterministic throughout — score, then the record's own id — so the
        same catalog answers the same question identically on any machine.
        """
        terms = [t for t in tokens(text) if t not in _PLOT_WORDS]
        if not terms:
            return []
        scored: list[tuple[int, str, PlotHit]] = []
        for hit in self.plots():
            rec = hit.record
            haystack = padded(f"{rec.caption} {rec.conditions} {' '.join(rec.tags or [])}")
            matched = sum(1 for t in terms if f" {t} " in haystack)
            if matched:
                scored.append((matched, rec.id, hit))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [
            replace(hit, matched_via="caption-terms")
            for _matched, _id, hit in (scored[:limit] if limit > 0 else scored)
        ]

    def card(self, name: str) -> DesignCard | None:
        """One design card for this part, or `None` when no such card exists.

        Derived **live** from the records this index already holds, by the same
        `cards.build_card` the publisher calls — so `dsa card` can never print a
        card the corpus does not contain, and a corpus published under older
        derivation rules is re-derived under today's rather than served stale.
        The `cards/*.json` on disk are the same function's output for machines
        that read files instead of calling this.

        `None` means "there is no card by that name" — a caller must be able to
        tell a typo from an empty card, which is a `DesignCard` carrying an
        `empty_reason`.

        Imported at call time: `cards.render` imports `retrieve.results` for the
        one citation format, so a module-level import here would be a cycle.
        """
        from datasheet_analyzer.cards import build_card, card_docs

        return build_card(name, self.part, card_docs(self.index))

    def cards(self) -> list[DesignCard]:
        """Every declared design card for this part, in lexicon order."""
        from datasheet_analyzer.cards import build_cards, card_docs

        return build_cards(self.part, card_docs(self.index))

    def card_names(self) -> list[str]:
        """The cards this build declares — what a front end may offer."""
        from datasheet_analyzer.cards import load_card_lexicon

        return list(load_card_lexicon().names)

    def ask(self, question: str, *, budget: int = 0) -> AnswerPack:
        """One cited, budget-bounded answer pack (ticket 05; see `pack.py`).

        Imported at call time only: `retrieve.pack` composes this class, so a
        module-level import here would be a cycle.
        """
        from datasheet_analyzer.retrieve.pack import build_pack

        return build_pack(self, question, budget=budget)

    def sections(
        self,
        *,
        number: str = "",
        title: str = "",
        page: int | None = None,
    ) -> list[SectionHit]:
        """Manifest section entries by number, title substring, or covered page.

        `page` is the provenance path an agent needs most: "which section do I
        open to check the printed page this answer cites?".
        """
        hits: list[SectionHit] = []
        for sec in self.index.sections:
            if number and number.lower() not in sec.number.lower():
                continue
            if title and title.lower() not in sec.title.lower():
                continue
            if page is not None and not _covers_page(sec, page):
                continue
            hits.append(
                SectionHit(
                    section=sec,
                    citation=Citation.for_section(sec, part=self.part),
                    matched_via=_section_matched_via(sec, number, title, page),
                )
            )
        return hits

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        """Rank the part's sections against `query` with BM25 (see `search.py`).

        Every hit is cited from the manifest entry of the section it names, so
        the caller never attributes a page. A part with no usable index
        returns `[]`; ask `search_unavailable()` for the reason rather than
        reading an empty list as "nothing matched".
        """
        indexes = self._search_indexes()
        if not indexes:
            return []
        sections_by_file = {sec.file: sec for sec in self.index.sections}
        hits: list[SearchHit] = []
        for scored in score_sections(indexes, query, limit=limit):
            section = sections_by_file.get(scored.section_file) or _orphan_section(
                scored, self.index
            )
            hits.append(
                SearchHit(
                    section=section,
                    citation=Citation.for_section(section, part=self.part),
                    score=scored.score,
                    snippet=snippet(self.index.section_text(section), scored.terms),
                    terms=scored.terms,
                )
            )
        return hits

    def search_unavailable(self) -> str:
        """`""` when the part is searchable, else why it is not.

        An older corpus predates `search_index.json` entirely, and one built
        against a superseded schema cannot be scored honestly either. Both say
        so, naming the fix, instead of returning zero hits that read like "the
        datasheet does not mention that".
        """
        if self._search_indexes():
            return ""
        part = self.index.part_number or self.index.part_dir.name
        return (
            f"no full-text index for part {part} — this corpus predates search "
            f"(or was built against an older index schema). Rebuild to enable "
            f"search: dsa build <pdf> --part {part}"
        )

    def _search_indexes(self) -> list[tuple[str, SearchIndex]]:
        """`(doc dir name, index)` for every document with a current index."""
        return [
            (doc.name, doc.search)
            for doc in self.index.docs
            if doc.search is not None
            and doc.search.schema_version == SEARCH_SCHEMA_VERSION
        ]

    def section_text(self, section: SectionFile) -> str:
        """Markdown body of a section file (lazily read, then cached)."""
        return self.index.section_text(section)

    def index_markdown(self) -> str:
        """The part's `INDEX.md`; `""` when the corpus has none yet."""
        return self.index.index_markdown()

    def corpus_path(self, rel: str) -> Path | None:
        """A corpus-relative file as an absolute path, or None when it escapes.

        Path safety belongs to the core for the same reason citations do: the
        CLI and the MCP server must not each invent a rule for what counts as
        a file of this part. See `CorpusIndex.corpus_path`.
        """
        return self.index.corpus_path(rel)

    def resolve_section(self, ref: str) -> SectionHit | None:
        """One section from a caller's reference; None when nothing matches.

        `sections()` is a filter and may return twenty entries; a caller that
        says "read §4.3" means exactly one. The rungs are ordered so the most
        literal reading wins — exact section number, then the corpus-relative
        file (or its basename), then a number prefix, then a title substring —
        with manifest order underneath, so one reference always resolves to
        the same section on any machine.
        """
        ref = (ref or "").strip()
        if not ref:
            return None
        low = ref.lower()
        norm = low.replace("\\", "/")
        rungs = (
            (lambda s: s.number.lower() == low, "number"),
            (lambda s: _file_matches(s, norm), "file"),
            (lambda s: bool(s.number) and s.number.lower().startswith(low), "number"),
            (lambda s: low in s.title.lower(), "title"),
        )
        for matches, via in rungs:
            for sec in self.index.sections:
                if matches(sec):
                    return SectionHit(
                        section=sec,
                        citation=Citation.for_section(sec, part=self.part),
                        matched_via=via,
                    )
        return None

    def plot_for_file(self, file: str) -> PlotHit | None:
        """The cataloged figure whose image is `file`, or None.

        The reverse of a plot hit's `file`: an agent narrows the catalog with
        `plots()` and then asks for one image, and it is the *record* that
        carries the citation and the grade that image must be presented with.
        A loose image in `figures/` that no record claims therefore resolves
        to nothing here — an uncited picture is not an answer.
        """
        norm = (file or "").strip().replace("\\", "/").lower()
        if not norm:
            return None
        for hit in self.plots():
            if hit.record.file.replace("\\", "/").lower() == norm:
                return hit
        return None


def _orphan_section(scored: ScoredSection, index: CorpusIndex) -> SectionFile:
    """A stand-in entry for an indexed section the manifest does not list.

    Only reachable when `manifest.json` is unreadable or out of step with the
    documents on disk. The hit still points at a real file and still cites —
    honestly as `p.?`, because no page range survives to quote.
    """
    doc = next((d for d in index.docs if d.name == scored.doc), None)
    return SectionFile(
        number="",
        title=Path(scored.file).stem,
        file=scored.section_file,
        doc_hash=doc.doc_hash if doc else "",
    )


def _file_matches(sec: SectionFile, norm: str) -> bool:
    """Whole corpus-relative path or bare filename, slash-normalized."""
    path = sec.file.replace("\\", "/").lower()
    return path == norm or path.rsplit("/", 1)[-1] == norm


def _passes(rec: SpecRecord, *, section: str, also_name: str) -> bool:
    """Filters that apply on every rung, not just the one that matched."""
    if section and section.lower() not in rec.section.lower():
        return False
    return not (also_name and also_name.lower() not in rec.name.lower())


def _printed_as(rec: SpecRecord) -> str:
    """The record's identity as the table printed it — symbol *then* name.

    An alias phrase is a designer's phrase, and a datasheet does not promise
    to keep one inside a single cell: LM741 prints `Supply` in the symbol
    column and `voltage` in the parameter column, so `supply voltage` exists
    only across the boundary. Matching each cell alone would make that record
    unreachable by the words that describe it, which is why the ladder asks
    the joined text — the same join `pack._head` renders back to the caller.

    `AliasLexicon.entry_for` deliberately keeps its per-cell test: it answers
    a different question ("does the lexicon know this record at all?"), and it
    is what `structure/confidence.py` grades by — a grade already frozen into
    every published corpus. Retrieval may widen; the rule a corpus was graded
    under may not, not without a rebuild. Keeping the widening on this side of
    the seam is what makes it provably grade-neutral.
    """
    return f"{rec.symbol} {rec.name}"


def _in_family(rec: SpecRecord, entry: AliasEntry) -> bool:
    """True when the record's symbol starts with one of the family prefixes."""
    symbol = rec.symbol.lower()
    return any(symbol.startswith(p.lower()) for p in entry.match_prefixes)


def _by_phrase_length(
    hits: list[tuple[AliasEntry, str]],
) -> Iterator[list[tuple[AliasEntry, str]]]:
    """Group `(entry, phrase)` hits into ties — same phrase length, one rung."""
    group: list[tuple[AliasEntry, str]] = []
    for entry, phrase in hits:  # already sorted longest phrase first
        if group and len(phrase) != len(group[0][1]):
            yield group
            group = []
        group.append((entry, phrase))
    if group:
        yield group


def _build_hits(candidates: list[_Candidate], *, part: str = "") -> list[SpecHit]:
    """Order by the `expect_unit` tie-break, then wrap in typed hits.

    The sort is stable and the key is binary, so document order survives and a
    record whose unit is missing keeps its place in the list — `expect_unit`
    promotes, it never suppresses.
    """
    ordered = sorted(candidates, key=lambda c: _unit_rank(c[1], c[2]))
    return [
        SpecHit(
            record=rec,
            citation=Citation.for_spec(
                rec, doc=doc.name, doc_hash=doc.doc_hash, part=part
            ),
            matched_via=matched_via,
            confidence=record_confidence(rec),
        )
        for doc, rec, _entry, matched_via in ordered
    ]


def _unit_rank(rec: SpecRecord, entry: AliasEntry | None) -> int:
    """0 for a record whose canonical unit is the one the alias expected."""
    if entry is None or not entry.expect_unit:
        return 0
    return 0 if rec.unit.canonical == entry.expect_unit else 1


def _covers_page(sec: SectionFile, page: int) -> bool:
    if sec.page_start is None:
        return False
    return sec.page_start <= page <= (sec.page_end or sec.page_start)


def _register_addr_matches(
    record: RegisterRecord, wanted: int | None, printed: str
) -> bool:
    """Whether one register answers an `--addr` filter.

    By parsed value when both sides parsed — that is what makes `0x1A04`,
    `0x1a04` and `6660` the same question — and by the printed string
    otherwise, so a register whose address cell never parsed is still reachable
    by typing exactly what the page shows. The two are never mixed: a caller's
    unparseable string is not compared against a record's integer.
    """
    if wanted is not None and record.address.value is not None:
        return record.address.value == wanted
    return record.address.verbatim.strip().casefold() == printed


def _register_matched_via(addr: str, name: str, field: str, q: str) -> str:
    """Which filter produced a register hit, strongest first."""
    if addr:
        return "address"
    if name:
        return "name"
    if field:
        return "field"
    if q:
        return "text"
    return "all"


def _pin_matched_via(pin: str, name: str, pin_type: str, q: str) -> str:
    """Which filter produced a pin hit, strongest first."""
    if pin:
        return "pin"
    if name:
        return "name"
    if q:
        return "text"
    if pin_type:
        return "type"
    return "all"


def gap_axis(*, x_label: str = "", y_label: str = "", near_x: str = "") -> str:
    """Which axis population an axis-filtered figure lookup must report.

    `"x"`, `"y"`, or `""` for a lookup that filtered on no axis and therefore
    owes no gap. One place decides, because two front ends ask (see
    `Retriever.plot_axis_gap_for`).
    """
    if not (x_label or y_label or near_x):
        return ""
    return "y" if (y_label and not (x_label or near_x)) else "x"


def _axis_covers(rec: PlotRecord, want: Quantity | None) -> bool:
    """True when the figure's printed x-tick range covers `want`.

    Both sides are taken to their SI base before they are compared — the caller
    types `3.5GHz` and the axis printed `MHz` — through the very lexicon the
    numeric layer scales spec values with, so an axis unit that lexicon cannot
    scale makes the figure *unmatchable* rather than matched at face value. That
    is the same refusal `quantities._si` makes, for the same reason: a dropped
    factor of 1000 here would hand back the wrong figure with a valid citation.

    A `None` want (the caller's value did not parse) matches nothing; the caller
    is told by the filter's own gap line rather than handed the whole catalog.
    """
    if want is None:
        return False
    if rec.x_min is None or rec.x_max is None:
        return False
    scale = SI_UNITS.get(canonical_unit(rec.x_unit).canonical)
    if scale is None:
        return False
    base, factor = scale
    if base != want.unit_si:
        return False
    low, high = want.span
    target = want.value_si if want.value_si is not None else low if low is not None else high
    if target is None:
        return False
    lo, hi = sorted((rec.x_min * factor, rec.x_max * factor))
    return lo <= target <= hi


def _plot_matched_via(
    rec: PlotRecord,
    q: str,
    caption: str,
    conditions: str,
    section: str,
    tags: list[str],
    x_label: str = "",
    y_label: str = "",
    near_x: str = "",
) -> str:
    if caption or (q and q.lower() in rec.caption.lower()):
        return "caption"
    if conditions or q:
        return "conditions"
    if section:
        return "section"
    if tags:
        return "tag"
    # Axis rungs name themselves like every other rung, so a caller can tell a
    # figure found by its printed axis from one found by its caption.
    if near_x.strip():
        return "axis-range"
    if x_label or y_label:
        return "axis-label"
    return "all"


def _section_matched_via(sec: SectionFile, number: str, title: str, page: int | None) -> str:
    if number:
        return "number"
    if title:
        return "title"
    if page is not None:
        return "page"
    return "all"
