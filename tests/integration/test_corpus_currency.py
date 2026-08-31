"""ADR 0008 — a tracked corpus is current, and self-contained.

Two claims, and they are the two halves of what "tracked corpus" means here.

A corpus committed to this repository is a *fixture*: something a gate reads
in order to make a claim about the pipeline. A fixture built by an older
pipeline has quietly stopped testing what it says it tests, and a fixture that
references a gitignored shared store cannot be read on a fresh clone at all —
which is what commit `c1d6180` shipped and `a8f93f8` reverted.

Neither assertion can be skipped: its inputs are committed, so it runs
everywhere. That is deliberate. ADR 0008 lets a corpus-*reading* gate skip when
its corpus is stale, naming the version in the reason; this module is the
"assert elsewhere that at least one corpus is current" half of that bargain, so
skipping cannot hide the regression.

The third class proves the mode the rule depends on: `--self-contained` really
does put every artifact under the part, and the default really does publish
into the shared store. It builds a real gate PDF offline through the same seam
a user runs, into a temp directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datasheet_analyzer.config import PIPELINE_VERSION, Settings
from datasheet_analyzer.corpus_ref import LIBRARY_REF_PREFIX
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.publish import read_manifest

REPO = Path(__file__).resolve().parents[2]
PARTS = REPO / "parts"

#: The corpora this repository commits. They are the substrate for the AFE7950
#: and AFE7953 golden benchmarks, and AFE7953's ground truth cannot be checked
#: against a fresh build (no recorded TI document-viewer pages exist for it),
#: so the committed bytes are the only thing its 13 questions have.
TRACKED = ("AFE7950", "AFE7953")

GATE_PDF = REPO / "tests" / "fixtures" / "pdf" / "QPA1003P.pdf"


def _manifest(part: str):
    manifest = read_manifest(PARTS / part)
    assert manifest is not None, (
        f"{part} is tracked in this repository but has no readable manifest at "
        f"{PARTS / part}; a tracked corpus is a committed fixture, not local state"
    )
    return manifest


class TestATrackedCorpusIsCurrent:
    """ADR 0008 §1: the fixture is built by the pipeline it tests."""

    @pytest.mark.parametrize("part", TRACKED)
    def test_it_is_published_at_the_current_pipeline_version(self, part):
        manifest = _manifest(part)
        assert manifest.pipeline_version == PIPELINE_VERSION, (
            f"{part} is committed at pipeline {manifest.pipeline_version} against code at "
            f"{PIPELINE_VERSION}. A version bump that changes published output owns the "
            f"rebuild of the tracked corpora (ADR 0008): "
            f"dsa build {part.lower()}.pdf --part {part} --self-contained"
        )


class TestATrackedCorpusIsSelfContained:
    """ADR 0008 §2: nothing in it points at the gitignored shared store."""

    @pytest.mark.parametrize("part", TRACKED)
    def test_no_manifest_reference_needs_a_library_to_resolve(self, part):
        manifest = _manifest(part)
        assert manifest.library_root == "", (
            f"{part} records a library root; a committed corpus must resolve from its own "
            f"directory, because /library/ is gitignored local shelf state"
        )
        offenders = [
            s.file for s in manifest.sections if str(s.file).startswith(LIBRARY_REF_PREFIX)
        ]
        assert offenders == [], offenders[:5]

    @pytest.mark.parametrize("part", TRACKED)
    def test_every_referenced_section_file_is_present_under_the_part(self, part):
        manifest = _manifest(part)
        missing = [s.file for s in manifest.sections if not (PARTS / part / s.file).is_file()]
        assert missing == [], (
            f"{part}: {len(missing)} section file(s) referenced by the manifest are not in the "
            f"part directory — a fresh clone reads this corpus as empty. First: {missing[:3]}"
        )

    @pytest.mark.parametrize("part", TRACKED)
    def test_the_full_text_index_a_clone_needs_is_published_too(self, part):
        """The gap ADR 0008 closes: without it `dsa search` cannot run at all."""
        indexes = sorted((PARTS / part / "docs").glob("*/search_index.json"))
        assert indexes, f"{part} publishes no search_index.json; the full-text path cannot run"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One offline QPA1003P build in each publish mode, into temp roots."""
    assert GATE_PDF.is_file(), f"gate fixture missing: {GATE_PDF}"
    out = {}
    for mode in (True, False):
        tmp = tmp_path_factory.mktemp("self-contained" if mode else "shared")
        settings = Settings(
            parts_dir=tmp / "parts",
            cache_dir=tmp / ".cache",
            library_dir=tmp / "library",
            sessions_dir=tmp / "sessions",
        ).resolve()
        result = build_part(
            GATE_PDF,
            part_number="QPA1003P",
            settings=settings,
            vendor="qorvo",
            use_llm=False,
            self_contained=mode,
        )
        out[mode] = (result, settings)
    return out


class TestTheSelfContainedModeDoesWhatItSays:
    """The mechanism the rule depends on, proved on a real PDF, offline."""

    def test_self_contained_writes_every_artifact_under_the_part(self, built):
        result, settings = built[True]
        manifest = result.manifest
        assert manifest.library_root == ""
        assert not any(str(s.file).startswith(LIBRARY_REF_PREFIX) for s in manifest.sections)
        for section in manifest.sections:
            assert (result.part_dir / section.file).is_file(), section.file
        assert not (settings.library_dir / "docs").exists(), (
            "a self-contained build wrote into the shared store"
        )

    def test_the_default_still_publishes_once_into_the_shared_store(self, built):
        result, settings = built[False]
        manifest = result.manifest
        assert manifest.library_root
        assert all(str(s.file).startswith(LIBRARY_REF_PREFIX) for s in manifest.sections)
        assert sorted(p.name for p in (settings.library_dir / "docs").iterdir())

    def test_both_modes_publish_the_same_corpus(self, built):
        """The mode moves bytes; it must not change what they say."""
        contained, shared = built[True][0].manifest, built[False][0].manifest
        assert contained.stats.n_sections == shared.stats.n_sections
        assert contained.stats.n_specs == shared.stats.n_specs
        assert [s.number for s in contained.sections] == [s.number for s in shared.sections]
        # Everything but the index size, which counts the document-reference
        # strings it indexes and those carry the `@library/` marker in one mode.
        left = json.loads(contained.model_dump_json())["stats"]
        right = json.loads(shared.model_dump_json())["stats"]
        assert left.pop("search_index_bytes") > 0 and right.pop("search_index_bytes") > 0
        assert left == right
