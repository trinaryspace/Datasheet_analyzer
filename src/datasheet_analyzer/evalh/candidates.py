"""The two files `dsa golden suggest|confirm` own, and the rules about them.

Phase 7, ticket 06. Invariant 5 says the golden set is the objective function
and that it is hand-verified. That survives sixty parts only if the *typing* is
removed while the *judgment* stays, which is exactly what these two files are:

- `golden_qa_<PART>.candidate.yaml` - generated proposals, every one of them
  written `confirmed: false`;
- `golden_qa_<PART>.rejected.yaml` - the ledger of candidates a human turned
  down, so the same bad candidate is not re-suggested next run.

Neither is the benchmark. `golden_qa_<PART>.yaml` is, and the three names are
deliberately siblings: `dsa verify` resolves the benchmark by
`evalh.golden.default_golden_path`, which is a different filename, so a
candidate file cannot reach the verifier by discovery. `load_golden` refuses a
candidate file by name on top of that, because "the objective function was
quietly replaced by generated questions" is the one failure this ticket could
introduce that nothing downstream would notice.

Where all three live is `evalh.golden.golden_dir()`, which honours
`DSA_GOLDEN_DIR`. That indirection is not decoration: `confirm` **writes** a
benchmark, and without a settable root every test run - and every prototype run
outside pytest that inherited default settings - would edit this repository's
own `tests/fixtures/golden_qa_<PART>.yaml`.

Everything here is deterministic: no timestamps are written into either file,
so regenerating over an unchanged corpus reproduces the bytes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from datasheet_analyzer.config import GOLDEN_CANDIDATE_SCHEMA_VERSION
from datasheet_analyzer.models import (
    GoldenCandidate,
    GoldenCandidateSet,
    GoldenQuestion,
    GoldenRejection,
    GoldenRejectionLedger,
)

#: Suffix of the generated-candidate file, beside `golden_qa_<PART>.yaml`.
CANDIDATE_SUFFIX = ".candidate.yaml"

#: Suffix of the rejection ledger.
REJECTED_SUFFIX = ".rejected.yaml"

#: The order a golden question's fields are written in, so a merged file reads
#: like the hand-written ones it is merged into rather than like a dump.
#:
#: This is `GoldenQuestion` as *this branch* carries it: there is no
#: `pin_query`, `reg_query` or `card_query` here. A pin or register golden is
#: an `ask_query` naming the route the pack must take, and a card golden is its
#: own question type in the file's own `cards:` block.
QUESTION_FIELDS: tuple[str, ...] = (
    "id",
    "question",
    "expected_substrings",
    "pages",
    "section",
    "kind",
    "spec_query",
    "plot_query",
    "ask_query",
    "search_query",
    "notes",
)


class GoldenAssistError(Exception):
    """A suggest/confirm run that must stop rather than guess.

    Raised for the cases where continuing would produce a wrong benchmark: no
    built corpus to template from, a decision naming a candidate that is not in
    the file, an accepted question whose id already exists in the golden set.
    """


def candidate_path(golden: Path) -> Path:
    """`golden_qa_<PART>.candidate.yaml` beside `golden_qa_<PART>.yaml`."""
    golden = Path(golden)
    return golden.with_name(golden.name.removesuffix(".yaml") + CANDIDATE_SUFFIX)


def rejected_path(golden: Path) -> Path:
    """`golden_qa_<PART>.rejected.yaml` beside `golden_qa_<PART>.yaml`."""
    golden = Path(golden)
    return golden.with_name(golden.name.removesuffix(".yaml") + REJECTED_SUFFIX)


def candidate_key(source: str, template: str) -> str:
    """The identity a candidate keeps across generation runs.

    `<record reference>|<template>`. Record ids are reproduced exactly by a
    rebuild of identical input (`derive.provenance`), so this key is stable -
    which is the whole reason a rejection can be remembered at all.
    """
    return f"{source}|{template}"


def question_to_dict(question: GoldenQuestion) -> dict:
    """One golden question as the dict a YAML file holds.

    Empty strings, empty lists and absent path markers are dropped: a merged
    file must read like the hand-written questions beside it, and a wall of
    `spec_query: null` would obscure the two lines a reviewer actually reads.
    """
    dumped = question.model_dump(mode="json")
    out: dict = {}
    for name in QUESTION_FIELDS:
        value = dumped.get(name)
        if value in (None, "", []):
            continue
        out[name] = value
    return out


def dump_yaml(payload: dict) -> str:
    """Deterministic YAML for either of this module's files."""
    return yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, default_flow_style=False, width=88
    )


def candidate_set_payload(candidates: GoldenCandidateSet) -> dict:
    """The candidate file's dict, with each question rendered as it will merge."""
    payload = candidates.model_dump(mode="json")
    payload["candidates"] = [
        {**candidate.model_dump(mode="json"), "question": question_to_dict(candidate.question)}
        for candidate in candidates.candidates
    ]
    return payload


def write_candidates(path: Path, candidates: GoldenCandidateSet) -> Path:
    """Write the candidate file, header and all. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Generated golden candidates for {candidates.part} "
        "(`dsa golden suggest`).\n"
        "#\n"
        "# NOT the benchmark. Every candidate is `confirmed: false` and nothing\n"
        "# reads this file into `dsa verify` - the objective function is\n"
        f"# golden_qa_{candidates.part}.yaml and only a human decision moves a\n"
        "# question into it (`dsa golden confirm`). Each candidate was templated\n"
        "# from one published record: `source` is that record, `page` is the page\n"
        "# it was printed on, `verbatim` the cells the answer was taken from, and\n"
        "# `template` the named rule. Check the page before you accept.\n"
        "#\n"
        "# `refused` is the population this run did NOT template, per artifact\n"
        "# and per reason. Read it before reading the candidates: it is what\n"
        "# tells a stale corpus apart from a broken generator.\n"
    )
    path.write_text(header + dump_yaml(candidate_set_payload(candidates)), encoding="utf-8")
    return path


def read_candidates(path: Path) -> GoldenCandidateSet:
    """Load a candidate file; a clear error when it is absent or malformed."""
    path = Path(path)
    if not path.exists():
        raise GoldenAssistError(
            f"no candidate file at {path} - generate one first: `dsa golden suggest --part <PART>`"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "candidates" not in data:
        raise GoldenAssistError(f"{path} is not a candidate file (no top-level `candidates:` key)")
    return GoldenCandidateSet.model_validate(data)


def read_rejections(path: Path) -> GoldenRejectionLedger:
    """Load the rejection ledger; an empty one when the file does not exist.

    An absent ledger is a legitimate state (nothing has been rejected yet), so
    it degrades to empty rather than erroring - unlike an absent *candidate*
    file, which means the caller asked to confirm something never generated.
    """
    path = Path(path)
    if not path.exists():
        return GoldenRejectionLedger(schema_version=GOLDEN_CANDIDATE_SCHEMA_VERSION)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise GoldenAssistError(f"{path} is not a rejection ledger")
    return GoldenRejectionLedger.model_validate(data)


def write_rejections(
    path: Path, part: str, rejections: list[GoldenRejection]
) -> GoldenRejectionLedger:
    """Merge `rejections` into the ledger at `path` and write it back.

    Deduplicated by `key` - the newest decision for a key wins, because a
    maintainer who rejects the same candidate twice with a better reason meant
    the better reason. Sorted by key on the way out, so the file is a function
    of its contents rather than of the order decisions arrived in.
    """
    path = Path(path)
    ledger = read_rejections(path)
    by_key = {entry.key: entry for entry in ledger.rejected}
    for entry in rejections:
        by_key[entry.key] = entry
    ledger = GoldenRejectionLedger(
        schema_version=GOLDEN_CANDIDATE_SCHEMA_VERSION,
        part=part or ledger.part,
        rejected=[by_key[key] for key in sorted(by_key)],
    )
    header = (
        f"# Golden candidates rejected by hand for {ledger.part} "
        "(`dsa golden confirm`).\n"
        "#\n"
        "# Keyed by `<record reference>|<template>`, which the generator\n"
        "# reproduces exactly over an unchanged corpus - so a candidate listed\n"
        "# here is never suggested again. Delete a row to let it come back.\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + dump_yaml(ledger.model_dump(mode="json")), encoding="utf-8")
    return ledger


def rejected_keys(path: Path) -> set[str]:
    """Every key the ledger at `path` holds; empty when there is no ledger."""
    return {entry.key for entry in read_rejections(path).rejected}


def existing_question_ids(golden: Path) -> set[str]:
    """The ids the real golden file already holds; empty when it has none.

    Read with `yaml.safe_load` rather than through `load_golden` so a benchmark
    that fails validation still blocks a duplicate id: the generator's job here
    is not to judge the golden file, only to avoid colliding with it.
    """
    golden = Path(golden)
    if not golden.exists():
        return set()
    data = yaml.safe_load(golden.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return set()
    return {
        str(item.get("id", ""))
        for item in (data.get("questions") or [])
        if isinstance(item, dict) and item.get("id")
    }


def candidate_by_id(candidates: GoldenCandidateSet, question_id: str) -> GoldenCandidate | None:
    """The candidate whose question carries `question_id`, or None."""
    for candidate in candidates.candidates:
        if candidate.question.id == question_id:
            return candidate
    return None
