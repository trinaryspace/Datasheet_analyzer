"""Guess which category a built part belongs in.

Runs *after* a build, not during the scan, and that is deliberate: a model
reading the whole published corpus — the index, the section titles, the spec
symbols — guesses far better than one reading the first page. The cost is a
second confirmation moment, and the user accepted that trade for the better
guess.

Two rules keep this honest.

**It chooses from the user's taxonomy.** A free-form answer is how one shelf
ends up with `amplifier`, `Amplifiers` and `RF amps`. The prompt is given the
list; anything outside it becomes `uncategorized`, which is a real answer and
not a failure.

**It proposes, it never decides.** `CategoryStore.propose_category` refuses to
overwrite a confirmed record, so re-running a build cannot undo a person's
correction. That guarantee is the reason the record lives outside
`CorpusManifest` at all.

There is no model call in a derivation path here: the category is metadata for
navigation, never an input to retrieval or to an answer. Without a client the
deterministic keyword pass still produces something usable.
"""

from __future__ import annotations

import json
import logging
import re

from datasheet_analyzer.library.categories import UNCATEGORIZED, Category

log = logging.getLogger(__name__)

_MAX_TOKENS = 200

#: Deterministic hints, tried before any model call and used as the fallback
#: when there is no client. Ordered: the first category whose pattern matches
#: wins, so the more specific ones come first.
_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("data-converters", ("adc", "dac", "analog-to-digital", "digital-to-analog", "sampling")),
    ("oscillators", ("pll", "vco", "synthesizer", "oscillator", "clock generator")),
    ("transformers", ("balun", "transformer", "impedance ratio")),
    ("mixers", ("mixer", "downconvert", "upconvert", "if port", "lo port")),
    ("amplifiers", ("amplifier", "lna", "gain block", "noise figure", "p1db")),
    ("filters", ("filter", "passband", "stopband", "insertion loss")),
    ("switches", ("switch", "attenuator", "spdt", "sp4t")),
    ("opamps", ("operational amplifier", "op-amp", "opamp", "comparator", "slew rate")),
    ("power", ("regulator", "ldo", "buck", "boost", "power management")),
    ("interfaces", ("transceiver", "uart", "usb", "ethernet", "jesd204", "serdes")),
    ("processors", ("microcontroller", "mcu", "processor", "fpga", "dsp core")),
    ("passives", ("resistor", "capacitor", "inductor", "coupler", "splitter", "terminator")),
)


def keyword_guess(text: str, allowed: set[str]) -> tuple[str, str]:
    """A category from plain keyword matching, with the phrase that decided it."""
    haystack = (text or "").lower()
    for category, needles in _HINTS:
        if category not in allowed:
            continue
        for needle in needles:
            if re.search(rf"\b{re.escape(needle)}\b", haystack):
                return category, f'the corpus says "{needle}"'
    return UNCATEGORIZED, "no category keyword found in the corpus"


def corpus_digest(index, limit: int = 40, sample_chars: int = 900) -> str:
    """The part of a corpus worth showing a classifier.

    Section titles first, because what a device *is* usually shows in what its
    sections are called. But a document whose headings were never detected has
    sections titled `Page 1`, `Page 2` — the same failure that put highlights
    on the footer — and for those the titles say nothing at all. So a sample of
    real body text is included too, which is what makes the Mini-Circuits and
    Qorvo shelf classifiable rather than uniformly `uncategorized`.

    Bounded on purpose: a whole datasheet costs more tokens than the answer is
    worth, and the first page of each of the first few sections is where a
    device describes itself.
    """
    manifest = getattr(index, "manifest", None)
    if manifest is None:
        return ""

    lines = [f"part: {getattr(manifest, 'part_number', '')}"]
    sections = list(getattr(manifest, "sections", []))[:limit]
    titles = [s.title for s in sections if s.title]
    if titles:
        lines.append("sections: " + "; ".join(titles))

    budget = sample_chars
    for section in sections[:4]:
        if budget <= 0:
            break
        text = _section_text(index, section)
        if not text:
            continue
        lines.append(text[:budget])
        budget -= len(text[:budget])
    return "\n".join(lines)


def _section_text(index, section) -> str:
    """A section's markdown as flat text; `""` when it cannot be read."""
    from pathlib import Path

    try:
        raw = Path(index.corpus_path(section.file)).read_text(encoding="utf-8")
    except (OSError, ValueError, AttributeError):
        return ""
    kept = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "<!--", "|"))
    ]
    return " ".join(kept)


def categorize(
    part_number: str,
    digest: str,
    categories: list[Category],
    *,
    client=None,
) -> tuple[str, str, bool]:
    """`(category_id, evidence, confident)` for one built part.

    `confident` drives the review's ordering — the doubtful sort to the top —
    and is False whenever the answer came from a fallback rather than from the
    classifier agreeing with something concrete.
    """
    allowed = {c.id for c in categories}
    guessed, why = keyword_guess(digest, allowed)

    if client is None:
        # Never confident. A single keyword is weak evidence: `ZX10R-2-183-S+`
        # is a splitter whose text mentions an amplifier once, and the keyword
        # pass files it under amplifiers without hesitating. Marking that
        # doubtful is what puts it at the top of the review instead of sliding
        # past as settled.
        return guessed, f"{why} (keyword match only, no classifier)", False

    try:
        raw = client.complete(_SYSTEM, _prompt(part_number, digest, categories), _MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 - a classifier is never load-bearing
        log.warning("category classifier failed for %s: %s", part_number, exc)
        return guessed, f"{why} (classifier error: {type(exc).__name__})", False

    chosen = _parse(raw, allowed)
    if chosen is None:
        log.warning("category classifier returned unusable output for %s", part_number)
        return guessed, f"{why} (classifier returned malformed output)", False

    category, reason = chosen
    model = getattr(client, "model", "") or "unknown"
    evidence = f"llm:{model}" + (f" — {reason}" if reason else "")
    # Confident when the model and the keywords agree, or when the keywords had
    # nothing to say and the model committed to a real category. A model that
    # contradicts a clear keyword hit is exactly the case worth a human glance.
    confident = category != UNCATEGORIZED and (
        guessed == UNCATEGORIZED or guessed == category
    )
    if guessed not in (UNCATEGORIZED, category):
        evidence += f" (keywords suggested {guessed})"
    return category, evidence, confident


_SYSTEM = (
    "You file electronic components into a fixed library taxonomy. "
    "You are given a part number and the section titles of its datasheet. "
    "Answer with JSON only."
)


def _prompt(part_number: str, digest: str, categories: list[Category]) -> str:
    listing = "\n".join(f"- {c.id}: {c.name}" for c in categories)
    return (
        f"Part: {part_number}\n\n"
        f"Corpus:\n{digest}\n\n"
        f"Categories (choose exactly one id from this list):\n{listing}\n\n"
        'Reply as {"category": "<id>", "reason": "<a short phrase from the corpus>"}. '
        f'Use "{UNCATEGORIZED}" only when none of them genuinely fits.'
    )


def _parse(raw: str, allowed: set[str]) -> tuple[str, str] | None:
    """The classifier's answer, or `None` when it is unusable.

    An id outside the taxonomy is treated as no answer rather than added:
    the taxonomy is the user's, and a classifier does not get to extend it.
    """
    text = (raw or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    category = str(data.get("category", "")).strip().lower()
    if category not in allowed:
        return None
    return category, str(data.get("reason", "")).strip()
