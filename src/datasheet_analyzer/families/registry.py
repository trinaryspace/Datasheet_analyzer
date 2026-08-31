"""`registry/families.yaml` — who is in a family, declared by a human.

Phase 7, ticket 07. A family is a claim that several devices are the *same
device with different options*, and a designer who reads a family index takes
that claim on trust: a shared section is read once, from the reference member,
and a spec that does not appear in the delta table is understood to be common to
every member. If membership were inferred, a wrong grouping would put another
part's number in front of a designer with no visible seam at all — the exact
failure ADR 0005 exists to prevent, one noun above the record.

So this module's whole job is to make membership **explicit**, and three rules
carry that:

- **`registry/families.yaml` is the only file `dsa family build` reads.** Its
  top-level key is `families`, and every entry it holds is confirmed by the fact
  that it is in that file.
- **A proposal lives somewhere else and says it is a proposal.**
  `dsa family suggest` writes `registry/families.candidate.yaml`, whose
  top-level key is `candidates` and whose every entry carries
  `confirmed: false`. `load_families` refuses that file **by name** — the same
  rule `evalh.golden.load_golden` applies to a golden candidate file, for the
  same reason and with the same shape — so pointing the loader at it is an
  error rather than a silent promotion.
- **An unconfirmed entry builds nothing even if it reaches the real file.**
  `FamilyEntry.confirmed` defaults to `True` for anything written under
  `families:` (being there *is* the confirmation), but a hand-copied entry that
  kept `confirmed: false` is refused by `resolve` with the command that fixes
  it. Belt and braces, because the failure mode is silent and expensive.

A miss names `dsa family suggest`, which is the growth path, exactly as a
document-registry miss names `--url`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger(__name__)

#: The packaged registry directory — the same one every other lexicon lives in.
PACKAGED_REGISTRY_DIR = Path(__file__).resolve().parent.parent / "registry"

FAMILIES_FILENAME = "families.yaml"
#: Where a *proposal* goes. Deliberately a different name, checked by
#: `load_families`, so a candidate file can never be read as the declaration.
CANDIDATES_FILENAME = "families.candidate.yaml"

#: "1": phase 7, ticket 07 — the first shape of this file.
FAMILIES_SCHEMA_VERSION = "1"

#: Top-level keys. Two names for two meanings: a declaration and a proposal.
FAMILIES_KEY = "families"
CANDIDATES_KEY = "candidates"

FILE_HEADER = """\
# Part families (phase 7, ticket 07). Membership is DECLARED, never inferred.
#
#   members     the part numbers, in order. The first is the reference every
#               delta is signed against.
#   confirmed   a human put this entry here. `dsa family build` refuses an
#               entry that says false.
#
# `dsa family suggest` PROPOSES groupings into families.candidate.yaml; nothing
# it writes builds anything until `dsa family confirm <NAME>` moves it here.
"""


#: Fields the file writes as `null` to mean "not stated" but the model holds as
#: `""`. YAML has one absence and pydantic has two, and reading `null` back as a
#: validation error would make the file this module *wrote* unreadable — the
#: same fix, for the same reason, as `acquire.registry._NULL_AS_EMPTY`.
_NULL_AS_EMPTY = ("title", "note", "proposed_by")


class FamilyEntry(BaseModel):
    """One declared family: a name, a human-readable title, and its members.

    `name` is the mapping key the file stores the entry under; `load_families`
    fills it in, so the file never carries the name twice and the two can never
    disagree — the same rule `acquire.registry.RegistryEntry` follows.
    """

    name: str = ""
    title: str = ""
    members: list[str] = Field(default_factory=list)
    #: A human's one-line reason this grouping is real. Free text, never parsed.
    note: str = ""
    #: What proposed it, when something did (`section-structure`, …). Kept so a
    #: confirmed entry still says whether a human typed it or reviewed it.
    proposed_by: str = ""
    #: True for anything under `families:`. A candidate file writes `false`, and
    #: `resolve` refuses an entry that carries it (see the module header).
    confirmed: bool = True

    @model_validator(mode="before")
    @classmethod
    def _null_reads_as_empty(cls, data):
        if isinstance(data, dict):
            data = {
                k: ("" if v is None and k in _NULL_AS_EMPTY else v)
                for k, v in data.items()
            }
        return data

    @property
    def reference(self) -> str:
        """The member every delta is measured against: the first one declared."""
        return self.members[0] if self.members else ""


class FamilyRegistry(BaseModel):
    """The whole file: `schema_version` plus one entry per family."""

    schema_version: str = FAMILIES_SCHEMA_VERSION
    families: dict[str, FamilyEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _entries_know_their_own_key(self) -> FamilyRegistry:
        for name, entry in self.families.items():
            entry.name = name
        return self

    def get(self, name: str) -> FamilyEntry | None:
        return self.families.get(name)

    def put(self, entry: FamilyEntry) -> None:
        self.families[entry.name] = entry

    @property
    def names(self) -> list[str]:
        return sorted(self.families)


class FamilyMiss(Exception):
    """A family name the registry does not declare.

    The message names `dsa family suggest`, because that is the growth path and
    a "not found" that does not say how to declare one turns a one-line YAML
    edit into a code-reading exercise.
    """


class FamilyUnconfirmed(Exception):
    """A family entry that exists but has not been confirmed by a human.

    Kept apart from `FamilyMiss`: "nobody has proposed this" and "somebody
    proposed this and nobody has checked it" are different facts, and only the
    second is a decision waiting on a person.
    """


def families_path(registry_dir: Path | None = None) -> Path:
    """`<registry_dir>/families.yaml`, defaulting to the packaged copy."""
    return Path(registry_dir or PACKAGED_REGISTRY_DIR) / FAMILIES_FILENAME


def candidates_path(registry_dir: Path | None = None) -> Path:
    """`<registry_dir>/families.candidate.yaml` — where a proposal is written."""
    return Path(registry_dir or PACKAGED_REGISTRY_DIR) / CANDIDATES_FILENAME


def is_candidate_path(path: Path | str) -> bool:
    """True for the proposal file, by **name**.

    Name, not content: the point is that a caller who aims the declaration
    loader at a proposal gets an error before anything is parsed, so the check
    cannot depend on the proposal being well-formed.
    """
    return Path(path).name == CANDIDATES_FILENAME


def load_families(path: Path | None = None) -> FamilyRegistry:
    """Read the declaration; a missing file is an *empty* registry, not an error.

    Pointing this at the candidate file raises: a proposal is not a declaration,
    and reading one as the other is precisely the silent promotion the ticket
    forbids.
    """
    dest = Path(path) if path is not None else families_path()
    if is_candidate_path(dest):
        raise FamilyUnconfirmed(candidate_file_message(dest))
    if not dest.exists():
        return FamilyRegistry()
    data = yaml.safe_load(dest.read_text(encoding="utf-8")) or {}
    return FamilyRegistry.model_validate(data)


def load_candidates(path: Path | None = None) -> list[FamilyEntry]:
    """Read the proposal file: entries under `candidates`, all unconfirmed.

    Returned as plain entries rather than a `FamilyRegistry` on purpose — a
    proposal has no schema-versioned identity to defend, and handing back the
    same container the declaration uses is how one gets mistaken for the other.
    """
    dest = Path(path) if path is not None else candidates_path()
    if not dest.exists():
        return []
    data = yaml.safe_load(dest.read_text(encoding="utf-8")) or {}
    raw = data.get(CANDIDATES_KEY) or {}
    out: list[FamilyEntry] = []
    for name, payload in sorted(raw.items()):
        entry = FamilyEntry.model_validate({**(payload or {}), "name": name})
        # A candidate is unconfirmed by definition, whatever the file says: the
        # file is machine-written, and honouring a `true` in it would let the
        # suggester confirm its own proposal.
        out.append(entry.model_copy(update={"confirmed": False}))
    return out


def _entry_yaml(entry: FamilyEntry) -> dict:
    out: dict = {"title": entry.title or None, "members": list(entry.members)}
    if entry.note:
        out["note"] = entry.note
    if entry.proposed_by:
        out["proposed_by"] = entry.proposed_by
    out["confirmed"] = entry.confirmed
    return out


def families_yaml(registry: FamilyRegistry) -> str:
    """Serialize deterministically: families sorted, block style, stable keys."""
    payload = {
        "schema_version": registry.schema_version,
        FAMILIES_KEY: {
            name: _entry_yaml(entry)
            for name, entry in sorted(registry.families.items())
        },
    }
    return FILE_HEADER + yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, width=100
    )


def candidates_yaml(entries: list[FamilyEntry]) -> str:
    """The proposal file, deterministically — and saying it is a proposal."""
    payload = {
        "schema_version": FAMILIES_SCHEMA_VERSION,
        CANDIDATES_KEY: {
            entry.name: {**_entry_yaml(entry), "confirmed": False}
            for entry in sorted(entries, key=lambda e: e.name)
        },
    }
    return CANDIDATE_HEADER + yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, width=100
    )


CANDIDATE_HEADER = """\
# PROPOSED part families — NOT a declaration. Nothing here builds anything.
#
# `dsa family suggest` wrote this by comparing what the built corpora print:
# their titles and their section structure. It is a starting point for a human,
# not a finding: two devices can share a section map and be different parts.
#
# Confirm one you have checked:   dsa family confirm <NAME>
# which moves it into families.yaml, where `dsa family build` will read it.
"""


def save_families(registry: FamilyRegistry, path: Path | None = None) -> Path:
    dest = Path(path) if path is not None else families_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(families_yaml(registry), encoding="utf-8")
    return dest


def save_candidates(entries: list[FamilyEntry], path: Path | None = None) -> Path:
    dest = Path(path) if path is not None else candidates_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(candidates_yaml(entries), encoding="utf-8")
    return dest


def resolve(registry: FamilyRegistry, name: str) -> FamilyEntry:
    """The declared family called `name`, or a refusal that says what to do.

    Two refusals, kept apart because they ask different things of the reader:
    a family nobody declared (`FamilyMiss`) and one somebody proposed but nobody
    confirmed (`FamilyUnconfirmed`).
    """
    entry = registry.get(name)
    if entry is None:
        raise FamilyMiss(miss_message(name, registry))
    if not entry.confirmed:
        raise FamilyUnconfirmed(unconfirmed_message(name))
    if not entry.members:
        raise FamilyMiss(no_members_message(name))
    return entry


def miss_message(name: str, registry: FamilyRegistry | None = None) -> str:
    """What a family miss says. It never guesses a grouping from a part number."""
    known = ", ".join(registry.names) if registry and registry.names else "(none)"
    return (
        f"no declared family {name!r} — a family is declared by a human, never "
        f"inferred from a part number. Declared families: {known}.\n"
        f"  dsa family suggest            # propose groupings from built corpora\n"
        f"  dsa family confirm {name}     # promote a proposal into families.yaml"
    )


def unconfirmed_message(name: str) -> str:
    return (
        f"family {name!r} is a proposal, not a declaration: it carries "
        f"`confirmed: false`, so it builds nothing. A wrong grouping would put "
        f"another part's numbers in front of a designer with no visible seam.\n"
        f"  dsa family confirm {name}"
    )


def candidate_file_message(path: Path) -> str:
    return (
        f"{path} is the *candidate* file — proposals, not declarations. "
        f"`dsa family build` reads {FAMILIES_FILENAME} only.\n"
        f"  dsa family confirm <NAME>     # move a proposal across"
    )


def no_members_message(name: str) -> str:
    return (
        f"family {name!r} declares no members — a family of nothing has nothing "
        f"to share and nothing to compare. Add part numbers to "
        f"{FAMILIES_FILENAME} under `{name}: members:`."
    )
