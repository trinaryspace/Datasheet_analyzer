"""Question -> exactly one Part or Project scope (ticket 10).

**Signature frozen by ticket 00; the body is ticket 10's.**

This is the mechanism ADR 0006 rests on. Retrieval refuses an "all parts"
scope on purpose; the GUI honours that not by making the user pick a scope
but by resolving one and *showing* it.

Deterministic — **no model call**. Part numbers are distinctive strings and
the candidate list is already enumerable via `discover_parts()`, so this is
matching, not inference. The order:

1. Exact, case-insensitive, whole-token match of a known part or project
   name. Exactly one match -> confident.
2. Prefix or family match (`AFE795` against `AFE7950`; `AFE79xx` against
   both) -> candidates, not confident.
3. Several matches at the same strength -> candidates, not confident.
4. No match -> `scope=None`, `candidates=[]`, and a `question` asking which
   part is meant.

Never widen. There is no "search everything" tier, and a single built part is
**not** a safe default: answering from the only part that happens to exist is
exactly the implicit scope the invariant forbids.

Matching is word-boundary over a normalized question, so `AD908` never
matches a question mentioning `AD9081` and `LM741` never matches `LM7410`,
while adjacent punctuation (`AD9081,`, `(AD9081)`, `AD9081's`) still does.
"""

from __future__ import annotations

import re
from typing import Literal

from datasheet_analyzer.app.contracts import ScopeResolution
from datasheet_analyzer.models import ScopeRef

__all__ = ["resolve"]

# A token boundary is anything that is not part of an identifier. Punctuation
# and whitespace are boundaries (`AD9081,`, `(AD9081)`, `AD9081's` all match);
# letters, digits and `_` are not, so a name never fires from inside a longer
# identifier (`AD908` never matches `AD9081`, `LM741` never matches `LM7410`).
_IDENT = "0-9a-z_"

# Words the prefix tier may consider. Part numbers carry a digit and are at
# least this long; without the guard, "rx" would family-match `rx-frontend`
# out of any RF question and every English word would be a candidate.
_TOKEN_RE = re.compile(r"[0-9a-z_]+")
_MIN_PREFIX_LEN = 3

# `AFE79xx` — a stem ending in a digit followed by explicit `x` wildcards.
_FAMILY_RE = re.compile(r"^([0-9a-z_]*[0-9])(x{1,4})$")

# The most known names a no-match question will recite back to the user.
_MAX_LISTED = 8


def _normalize(question: str) -> str:
    """Lowercase, with runs of whitespace collapsed to a single space."""
    return re.sub(r"\s+", " ", question.lower()).strip()


def _refs(kind: Literal["part", "project"], names: list[str]) -> list[ScopeRef]:
    """`names` as scope refs, blank and duplicate names dropped."""
    seen: set[str] = set()
    refs: list[ScopeRef] = []
    for name in names:
        cleaned = (name or "").strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        refs.append(ScopeRef(kind=kind, name=cleaned))
    return refs


def _known(parts: list[str], projects: list[str]) -> list[ScopeRef]:
    """Every candidate scope, parts before projects, each name-ordered."""
    return sorted(_refs("part", parts), key=lambda ref: ref.name.lower()) + sorted(
        _refs("project", projects), key=lambda ref: ref.name.lower()
    )


def _appears(name: str, normalized: str) -> bool:
    """True when `name` occurs in `normalized` as a whole token."""
    pattern = rf"(?<![{_IDENT}]){re.escape(name.lower())}(?![{_IDENT}])"
    return re.search(pattern, normalized) is not None


def _prefix_tokens(normalized: str) -> list[str]:
    """Question tokens long and distinctive enough to prefix-match a name."""
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(normalized):
        if len(token) < _MIN_PREFIX_LEN or not any(char.isdigit() for char in token):
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _family_matches(token: str, name: str) -> bool:
    """`AFE79xx` against `AFE7950` — one wildcard character per `x`."""
    family = _FAMILY_RE.match(token)
    if family is None:
        return False
    stem, wildcards = family.groups()
    return re.fullmatch(rf"{re.escape(stem)}.{{{len(wildcards)}}}", name.lower()) is not None


def _join(labels: list[str]) -> str:
    """`a`, `a or b`, `a, b or c`."""
    if len(labels) <= 1:
        return labels[0] if labels else ""
    return f"{', '.join(labels[:-1])} or {labels[-1]}"


def _ask_which(candidates: list[ScopeRef]) -> str:
    return f"Which did you mean — {_join([ref.label for ref in candidates])}?"


def _ask_unknown(known: list[ScopeRef]) -> str:
    """The no-match question. Never a guess, and never a widening."""
    if not known:
        return (
            "Which part is this question about? Nothing has been built yet — "
            "analyze a datasheet first."
        )
    listed = [ref.label for ref in known[:_MAX_LISTED]]
    more = "" if len(known) <= _MAX_LISTED else f", and {len(known) - _MAX_LISTED} more"
    return f"Which part is this question about? Known: {', '.join(listed)}{more}."


def resolve(question: str, *, parts: list[str], projects: list[str]) -> ScopeResolution:
    """Resolve `question` against the known part and project names.

    `parts` and `projects` are passed in: this function makes no filesystem
    access and no model call, which is what makes it trivially testable and
    what keeps scope resolution off every derivation path.
    """
    known = _known(parts, projects)
    normalized = _normalize(question)

    # 1. Exact whole-token match. Exactly one -> confident; several -> ask.
    exact = [ref for ref in known if _appears(ref.name, normalized)]
    if len(exact) == 1:
        return ScopeResolution(scope=exact[0], confident=True, matched_via="exact")
    if exact:
        return ScopeResolution(
            candidates=exact,
            question=_ask_which(exact),
            matched_via="exact-ambiguous",
        )

    # 2. Prefix or family match. Never confident, however few it finds: a
    #    partial name is a lead, not an identification.
    hits: list[ScopeRef] = []
    vias: list[str] = []
    for token in _prefix_tokens(normalized):
        for ref in known:
            lowered = ref.name.lower()
            if len(token) < len(lowered) and lowered.startswith(token):
                rung = "prefix"
            elif _family_matches(token, ref.name):
                rung = "family"
            else:
                continue
            if ref not in hits:
                hits.append(ref)
            via = f"{rung}:{token}"
            if via not in vias:
                vias.append(via)
    if hits:
        return ScopeResolution(
            candidates=hits,
            question=_ask_which(hits),
            matched_via=",".join(vias),
        )

    # 3. Nothing matched. Ask — do not widen, and do not fall back on the only
    #    part that happens to exist (ADR 0006).
    return ScopeResolution(question=_ask_unknown(known), matched_via="none")
