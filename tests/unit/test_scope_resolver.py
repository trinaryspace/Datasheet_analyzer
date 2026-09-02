"""Ticket 10 — a question resolves to exactly one Part or Project, or asks.

The behaviour under test is ADR 0006's mechanism: retrieval refuses an "all
parts" scope on purpose, so the GUI resolves one and shows it. Everything here
is pure — `resolve` is handed the candidate names, so these tests need no
`parts_dir`, no PDF, no model and no network, and two of them assert exactly
that (`test_resolve_touches_no_filesystem`, `test_resolve_imports_no_client`).
"""

from __future__ import annotations

import ast
import inspect
import os
import pathlib
import socket
from typing import Any

import pytest

from datasheet_analyzer.app import scope_resolver
from datasheet_analyzer.app.contracts import ScopeResolution
from datasheet_analyzer.models import ScopeRef

# --- helpers ------------------------------------------------------------------


def resolve(
    question: str,
    parts: list[str] | None = None,
    projects: list[str] | None = None,
    families: list[str] | None = None,
):
    """Call `resolve` and assert the contract holds for whatever comes back.

    Every scenario in this file goes through here, so "every returned
    `ScopeResolution` validates against the contract model" is checked once per
    case rather than in a single token test. `families` are the names declared
    in `registry/families.yaml`; passing an undeclared one would be the test
    inventing a grouping, which is the thing the noun forbids.
    """
    result = scope_resolver.resolve(
        question,
        parts=list(parts or []),
        projects=list(projects or []),
        families=list(families) if families is not None else None,
    )
    assert isinstance(result, ScopeResolution)
    # Round-trips through the frozen model: no extra state, no wrong types.
    assert ScopeResolution.model_validate(result.model_dump()) == result
    # The three representable states, and only those three.
    if result.confident:
        assert result.scope is not None
        assert result.candidates == []
        assert result.question == ""
    else:
        assert result.scope is None
        assert result.question != "", "a non-confident resolution must ask something"
    assert result.ambiguous == (result.scope is None and bool(result.candidates))
    return result


def names(result: ScopeResolution) -> list[str]:
    return [ref.name for ref in result.candidates]


# --- the confident tier -------------------------------------------------------


def test_named_part_resolves_confidently():
    result = resolve("what is the max TJ of the AD9081?", parts=["AD9081", "LM741"])

    assert result.confident is True
    assert result.scope == ScopeRef(kind="part", name="AD9081")
    assert result.candidates == []
    assert result.matched_via == "exact"


def test_named_project_resolves_confidently():
    result = resolve(
        "which parts does rx-frontend use?",
        parts=["AD9081"],
        projects=["rx-frontend"],
    )

    assert result.confident is True
    assert result.scope == ScopeRef(kind="project", name="rx-frontend")
    assert result.scope.label == "project: rx-frontend"


def test_confident_scope_keeps_the_canonical_spelling():
    """The ref carries the name as the caller knows it, not as typed."""
    result = resolve("max tj of the ad9081?", parts=["AD9081"])

    assert result.confident is True
    assert result.scope is not None
    assert result.scope.name == "AD9081"


@pytest.mark.parametrize(
    "question",
    [
        "max TJ of the AD9081?",
        "max TJ of the ad9081?",
        "max TJ of the Ad9081?",
        "MAX TJ OF THE AD9081?",
    ],
)
def test_matching_is_case_insensitive(question: str):
    result = resolve(question, parts=["AD9081"])

    assert result.confident is True
    assert result.scope == ScopeRef(kind="part", name="AD9081")


def test_case_insensitive_in_the_other_direction():
    """A lowercased part directory still matches an upper-cased question."""
    result = resolve("supply range for AD9081", parts=["ad9081"])

    assert result.confident is True
    assert result.scope is not None
    assert result.scope.name == "ad9081"


@pytest.mark.parametrize(
    "question",
    [
        "compare the AD9081, then stop",
        "what about (AD9081) here",
        "the AD9081's supply range",
        "spec for AD9081.",
        "an AD9081-based receiver",
        "AD9081",
        "  AD9081  ",
    ],
)
def test_adjacent_punctuation_still_matches(question: str):
    result = resolve(question, parts=["AD9081"])

    assert result.confident is True, question
    assert result.scope == ScopeRef(kind="part", name="AD9081")


# --- the ambiguous tier -------------------------------------------------------


def test_a_part_and_a_project_together_are_candidates():
    result = resolve(
        "does rx-frontend use the AD9081?",
        parts=["AD9081"],
        projects=["rx-frontend"],
    )

    assert result.confident is False
    assert result.scope is None
    assert result.ambiguous is True
    assert result.candidates == [
        ScopeRef(kind="part", name="AD9081"),
        ScopeRef(kind="project", name="rx-frontend"),
    ]
    assert "AD9081" in result.question
    assert "project: rx-frontend" in result.question
    assert result.matched_via == "exact-ambiguous"


def test_two_named_parts_are_candidates():
    result = resolve("AD9081 vs LM741 noise", parts=["AD9081", "LM741"])

    assert result.confident is False
    assert names(result) == ["AD9081", "LM741"]


def test_prefix_returns_every_family_member_as_a_candidate():
    result = resolve("what is the AFE795 sample rate?", parts=["AFE7950", "AFE7952"])

    assert result.confident is False
    assert result.scope is None
    assert names(result) == ["AFE7950", "AFE7952"]
    assert result.matched_via == "prefix:afe795"


def test_family_wildcard_returns_both_members():
    result = resolve("AFE79xx sample rate?", parts=["AFE7950", "AFE7952"])

    assert result.confident is False
    assert names(result) == ["AFE7950", "AFE7952"]
    assert result.matched_via == "family:afe79xx"


def test_a_lone_prefix_match_is_still_not_confident():
    """A partial name is a lead, not an identification."""
    result = resolve("AFE795 sample rate?", parts=["AFE7950"])

    assert result.confident is False
    assert names(result) == ["AFE7950"]


def test_exact_match_beats_a_prefix_match_on_another_part():
    result = resolve("AFE7950 vs the rest", parts=["AFE7950", "AFE79501"])

    assert result.confident is True
    assert result.scope == ScopeRef(kind="part", name="AFE7950")


# --- the no-match tier: never widen, never default ----------------------------


def test_no_known_part_named_returns_a_question():
    result = resolve("what is the noise figure?", parts=["AD9081"], projects=["rx-frontend"])

    assert result.confident is False
    assert result.scope is None
    assert result.candidates == []
    assert result.ambiguous is False
    assert "which part" in result.question.lower()
    assert result.matched_via == "none"


def test_one_built_part_is_not_a_default():
    """The invariant this ticket exists for: no implicit scope, ever."""
    result = resolve("what is the maximum junction temperature?", parts=["AD9081"])

    assert result.confident is False
    assert result.scope is None
    assert result.candidates == []


def test_no_parts_at_all_still_asks():
    result = resolve("what is the noise figure?", parts=[], projects=[])

    assert result.confident is False
    assert result.scope is None
    assert result.candidates == []
    assert result.question != ""


def test_empty_question_asks():
    result = resolve("", parts=["AD9081"])

    assert result.confident is False
    assert result.scope is None


# --- word boundaries ----------------------------------------------------------


def test_short_part_does_not_match_a_longer_number_in_the_question():
    """`AD908` must not fire on a question mentioning `AD9081`."""
    result = resolve("max TJ of the AD9081?", parts=["AD908"])

    assert result.confident is False
    assert result.scope is None
    assert result.candidates == []


def test_lm741_does_not_match_lm7410():
    result = resolve("what is the LM7410 supply range?", parts=["LM741"])

    assert result.confident is False
    assert result.scope is None
    assert result.candidates == []


def test_the_reverse_direction_is_a_candidate_not_a_confident_match():
    """A question naming a prefix of a known part asks rather than guesses."""
    result = resolve("max TJ of the AD908?", parts=["AD9081"])

    assert result.confident is False
    assert result.scope is None


@pytest.mark.parametrize(
    "question",
    [
        "order code AD9081BBCAZ availability",
        "is XAD9081 the same die?",
        "see AD9081_rev2 for details",
        "the AD90810 variant",
    ],
)
def test_a_part_inside_a_longer_identifier_does_not_match(question: str):
    result = resolve(question, parts=["AD9081"])

    assert result.confident is False, question
    assert result.scope is None
    assert result.candidates == [], question


def test_a_common_word_never_prefix_matches_a_project():
    """The prefix tier needs a digit, so `rx` cannot pull in `rx-frontend`."""
    result = resolve("what is the rx noise figure?", projects=["rx-frontend"])

    assert result.confident is False
    assert result.candidates == []


# --- purity -------------------------------------------------------------------


def test_resolve_touches_no_filesystem_and_no_network(monkeypatch: pytest.MonkeyPatch):
    """Parts and projects are passed in — nothing is discovered or dialled."""

    def forbidden(*args: Any, **kwargs: Any):
        raise AssertionError(f"resolve() reached out: {args!r}")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(os, "listdir", forbidden)
    monkeypatch.setattr(os, "scandir", forbidden)
    monkeypatch.setattr(pathlib.Path, "open", forbidden)
    monkeypatch.setattr(pathlib.Path, "exists", forbidden)
    monkeypatch.setattr(pathlib.Path, "iterdir", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    result = scope_resolver.resolve(
        "max TJ of the AD9081?", parts=["AD9081", "AFE7950"], projects=["rx-frontend"]
    )

    assert result.confident is True


def test_resolve_imports_no_client_and_calls_no_model():
    """No model call in a derivation path: the module cannot make one.

    Read off the module's own source rather than mocked at runtime, so a
    future edit that reaches for the SDK fails here instead of silently
    putting inference on the resolution path.
    """
    source = inspect.getsource(scope_resolver)
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"__future__", "re", "typing", "datasheet_analyzer"}
    assert "anthropic" not in source.lower()
    assert "client" not in source.lower()


def test_resolve_is_deterministic_regardless_of_input_order():
    forward = resolve("AFE795 sample rate?", parts=["AFE7950", "AFE7952"])
    backward = resolve("AFE795 sample rate?", parts=["AFE7952", "AFE7950"])

    assert forward == backward


# --- declared families: offered, never chosen ---------------------------------
#
# A family scope reads each shared section once, from the reference member, and
# states that every member prints it. That claim is only true because a human
# wrote the membership down, so the resolver may *offer* a declared family and
# may never arrive at one on its own. Both halves are tested: the offer exists
# (otherwise no pane can present it) and there is no path to a confident family.

DECLARED = ["AFE795x"]
MEMBERS = ["AFE7950", "AFE7953"]


def test_declared_family_named_exactly_is_offered_as_a_candidate():
    result = resolve("what changes across the AFE795x?", parts=MEMBERS, families=DECLARED)

    assert result.confident is False
    assert result.scope is None
    assert result.candidates == [ScopeRef(kind="family", name="AFE795x")]
    assert result.matched_via == "family-declared"
    assert "declared family" in result.question
    # The sentence must hand the choice back rather than announce a decision.
    assert "never chosen for you" in result.question


def test_a_family_is_never_the_confident_scope():
    """The load-bearing negative: no input makes `resolve` pick a family.

    Swept over the shapes that would each be a plausible confident hit — the
    name alone, the name with nothing else declared, the name in a question
    with no parts at all — because "confident" is what would skip the pane.
    """
    for question in ("AFE795x", "AFE795x thermal limits?", "tell me about afe795x"):
        for parts in ([], MEMBERS):
            result = resolve(question, parts=parts, families=DECLARED)
            assert result.confident is False, question
            assert result.scope is None, question
            assert ScopeRef(kind="family", name="AFE795x") in result.candidates, question


def test_a_member_part_number_never_offers_its_family():
    """Membership is declared, not inferred — and not inferred backwards either."""
    result = resolve("max TJ of the AFE7950?", parts=MEMBERS, families=DECLARED)

    assert result.confident is True
    assert result.scope == ScopeRef(kind="part", name="AFE7950")
    assert result.candidates == []


def test_a_wildcard_pattern_is_not_the_family_noun():
    """`AFE79xx` matches part *numbers*; it does not name the declared family.

    The prefix tier's `AFE79xx` wildcard has existed since ticket 10 and is a
    string pattern over part numbers. Letting it reach a family would be
    exactly the inference the registry exists to prevent, so the candidates
    here are the two parts and nothing else.
    """
    result = resolve("what does the AFE79xx sample at?", parts=MEMBERS, families=DECLARED)

    assert names(result) == MEMBERS
    assert all(ref.kind == "part" for ref in result.candidates)


def test_a_prefix_of_a_family_name_does_not_offer_the_family():
    result = resolve("AFE795 sample rate?", parts=MEMBERS, families=DECLARED)

    assert all(ref.kind == "part" for ref in result.candidates)
    assert result.matched_via.startswith("prefix:")


def test_an_undeclared_family_name_matches_nothing():
    """The registry is the whole vocabulary: a name not in it is not a family."""
    result = resolve("compare the AFE79yz", parts=MEMBERS, families=DECLARED)

    assert result.candidates == []
    assert result.matched_via == "none"


def test_a_family_named_beside_a_part_asks_between_them():
    result = resolve("AFE7950 versus the AFE795x", parts=MEMBERS, families=DECLARED)

    assert result.candidates == [
        ScopeRef(kind="part", name="AFE7950"),
        ScopeRef(kind="family", name="AFE795x"),
    ]
    assert result.matched_via == "exact-ambiguous"
    # `ScopeRef.label` is what distinguishes the two in the question.
    assert "family: AFE795x" in result.question


def test_the_unknown_question_recites_declared_families_too():
    result = resolve("how do I bias this?", parts=["LM741"], families=DECLARED)

    assert result.matched_via == "none"
    assert "LM741" in result.question
    assert "family: AFE795x" in result.question


def test_omitting_families_resolves_exactly_as_before():
    """The parameter is additive: an old caller sees no change at all."""
    with_default = scope_resolver.resolve("AFE795x?", parts=MEMBERS, projects=[])
    with_none = scope_resolver.resolve("AFE795x?", parts=MEMBERS, projects=[], families=None)
    with_empty = scope_resolver.resolve("AFE795x?", parts=MEMBERS, projects=[], families=[])

    assert with_default == with_none == with_empty
    # `AFE795x` still reaches the two parts through the wildcard tier, which is
    # the pre-existing behaviour; what it must not reach is a family nobody
    # declared to this call.
    assert names(with_default) == MEMBERS
    assert all(ref.kind == "part" for ref in with_default.candidates)
