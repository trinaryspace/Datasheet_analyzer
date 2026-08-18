"""Ticket 26 — why a scanned PDF will or will not be rebuilt.

Hermetic: synthetic PDFs built in-test with fitz, `Settings` pointed at
`tmp_path`, no network and no model. The corpora are built by the real
pipeline with `use_llm=False`, because the whole point of the classifier is
to agree with the real gate — a hand-written manifest would only prove the
classifier agrees with the fixture.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from datasheet_analyzer.app.buildstate import classify
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.extract.pdf_structure import compute_content_hash
from datasheet_analyzer.pipeline import build_part


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    reset_settings_cache()
    made = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / "cache",
        projects_dir=tmp_path / "projects",
        library_dir=tmp_path / "library",
        sessions_dir=tmp_path / "sessions",
    ).resolve()
    yield made
    reset_settings_cache()


def make_pdf(path: Path, body: str) -> Path:
    """A two-page PDF with a title block and a spec table's worth of text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "ACME1234 Precision Amplifier", fontsize=16)
    page.insert_text((72, 120), body, fontsize=11)
    second = doc.new_page()
    second.insert_text((72, 72), "6 Specifications", fontsize=14)
    second.insert_text((72, 100), "Supply voltage  1.8  3.3  3.6  V", fontsize=10)
    doc.save(path)
    doc.close()
    return path


def build(pdf: Path, part: str, settings: Settings) -> None:
    """Build through the real pipeline, offline.

    `vendor="unknown"` pins routing to the layout backend, which is what keeps
    this hermetic: left to infer, a title block reading like a real part sends
    vendor routing to fetch the vendor's HTML datasheet over the network.
    """
    build_part(
        pdf,
        part_number=part,
        settings=settings,
        vendor="unknown",
        use_cache=True,
        use_llm=False,
    )


def state_of(pdf: Path, part: str, settings: Settings) -> tuple[str, str]:
    return classify(pdf, part, compute_content_hash(pdf), settings=settings)


def test_a_pdf_never_seen_is_new(tmp_path: Path, settings: Settings) -> None:
    pdf = make_pdf(tmp_path / "in" / "acme.pdf", "first revision")
    state, reason = state_of(pdf, "ACME1234", settings)
    assert state == "new"
    assert "ACME1234" in reason


def test_a_freshly_built_pdf_is_current_and_carries_the_gates_own_reason(
    tmp_path: Path, settings: Settings
) -> None:
    pdf = make_pdf(tmp_path / "in" / "acme.pdf", "first revision")
    build(pdf, "ACME1234", settings)

    state, reason = state_of(pdf, "ACME1234", settings)
    assert state == "current"
    # Verbatim from `batch.skip_reason` — not a second wording of it.
    assert "already built" in reason


def test_a_renamed_file_rebuilds_and_says_it_is_the_path(
    tmp_path: Path, settings: Settings
) -> None:
    """Renaming *does* rebuild, and the reason must not blame the extractor.

    `batch.skip_reason` matches an inventory entry by path and only then by
    hash, so the same bytes under a new name are not recognised as already
    built. That is the engine's behaviour, conservative and safe; what this
    pins is that the classifier explains it correctly rather than reporting a
    version problem the user would go looking for and never find.
    """
    pdf = make_pdf(tmp_path / "in" / "acme.pdf", "first revision")
    build(pdf, "ACME1234", settings)

    renamed = pdf.parent / "renamed-by-the-user.pdf"
    pdf.rename(renamed)
    state, reason = state_of(renamed, "ACME1234", settings)
    assert state == "stale"
    assert "different path" in reason
    assert "extractor" not in reason


def test_editing_the_pdf_is_changed_not_stale(tmp_path: Path, settings: Settings) -> None:
    pdf = make_pdf(tmp_path / "in" / "acme.pdf", "first revision")
    build(pdf, "ACME1234", settings)
    make_pdf(pdf, "second revision, materially different text")

    state, reason = state_of(pdf, "ACME1234", settings)
    assert state == "changed"
    assert "differ" in reason


def test_a_corpus_from_an_older_pipeline_is_stale_and_names_the_move(
    tmp_path: Path, settings: Settings
) -> None:
    pdf = make_pdf(tmp_path / "in" / "acme.pdf", "first revision")
    build(pdf, "ACME1234", settings)

    manifest_path = settings.parts_dir / "ACME1234" / "manifest.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            '"pipeline_version"', '"pipeline_version"', 1
        ),
        encoding="utf-8",
    )
    import json

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["pipeline_version"] = "0.0.1-ancient"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    state, reason = state_of(pdf, "ACME1234", settings)
    assert state == "stale"
    assert "0.0.1-ancient" in reason


def test_an_unreadable_manifest_promises_work_rather_than_promising_none(
    tmp_path: Path, settings: Settings
) -> None:
    """The gate's contract: whatever cannot be verified must build."""
    pdf = make_pdf(tmp_path / "in" / "acme.pdf", "first revision")
    build(pdf, "ACME1234", settings)
    (settings.parts_dir / "ACME1234" / "manifest.json").write_text("{ not json", encoding="utf-8")

    state, _ = state_of(pdf, "ACME1234", settings)
    assert state != "current"


def test_classifying_writes_nothing(tmp_path: Path, settings: Settings) -> None:
    """A scan must leave parts, library and cache byte-identical."""
    pdf = make_pdf(tmp_path / "in" / "acme.pdf", "first revision")
    build(pdf, "ACME1234", settings)

    def snapshot() -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for root in (settings.parts_dir, settings.library_dir, settings.cache_dir):
            for f in sorted(root.rglob("*")):
                if f.is_file():
                    out[str(f)] = f.read_bytes()
        return out

    before = snapshot()
    for _ in range(3):
        state_of(pdf, "ACME1234", settings)
    assert snapshot() == before
