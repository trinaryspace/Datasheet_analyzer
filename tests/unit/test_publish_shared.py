"""Pain point: a document that applies to forty parts was published forty
times, figures and all. Ticket 04 publishes it once into a shared store and
has every part's manifest reference that one copy.

What these tests hold onto:

* the historical per-part layout is unchanged, byte for byte, when
  `shared_docs_dir` is not given (a golden directory listing);
* the shared layout really is *one* copy, referenced by every part, and every
  reference resolves to a file that exists;
* a figure path is anchored at the root its own `plots.json` sits under, and
  a `plots.json` from before that rule is refused rather than resolved
  against the wrong root;
* republishing is a no-op and two parts publishing the same document at once
  leave one intact copy and no debris.

Hermetic: synthetic PDFs via `fitz`, a fake byte fetcher, `Settings` pointed
at `tmp_path`, no network and no model.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer.config import (
    PLOTS_SCHEMA_VERSION,
    SPECS_SCHEMA_VERSION,
    Settings,
    reset_settings_cache,
)
from datasheet_analyzer.models import (
    CorpusManifest,
    DocType,
    PlotRecord,
    PlotSet,
    RawDocument,
    SectionNode,
    SourceDocument,
    SpecRecord,
    SpecSet,
    TableBlock,
)
from datasheet_analyzer.publish.plots import (
    StalePlotsSchemaError,
    artifact_root,
    fetch_plot_images,
    load_plotset,
    render_figure_regions,
    resolve_plot_file,
)
from datasheet_analyzer.publish.writer import (
    LIBRARY_REF_PREFIX,
    is_library_ref,
    manifest_artifacts,
    missing_artifacts,
    read_manifest,
    resolve_artifact_ref,
    write_corpus,
)
from datasheet_analyzer.structure.corpus import build_section_plans

DOC_HASH = "a" * 64
DOC_DIR = "app_note-aaaaaaaa"


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """`Settings` pointed entirely at `tmp_path` (AGENTS.md invariant 4)."""
    reset_settings_cache()
    s = Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        library_dir=tmp_path / "library",
        anthropic_api_key="",
    ).resolve()
    yield s
    reset_settings_cache()


def _raw(hash_char: str = "a", dtype: str = "app_note") -> RawDocument:
    return RawDocument(
        source=SourceDocument(
            content_hash=hash_char * 64,
            path="note.pdf",
            revision="REVA",
            doc_type=DocType(dtype),
            page_count=12,
        ),
        sections=[
            SectionNode(
                number="1",
                title="Features",
                level=1,
                page_start=1,
                page_end=1,
                paragraphs=["Feature one."],
            ),
            SectionNode(
                number="4.5",
                title="TX",
                level=2,
                page_start=7,
                page_end=8,
                tables=[TableBlock(headers=["P", "V"], grid=[["A", "1"]])],
            ),
        ],
        extractor="test",
    )


def _specset(doc_hash: str, part: str) -> SpecSet:
    return SpecSet(
        schema_version=SPECS_SCHEMA_VERSION,
        part_number=part,
        doc_hash=doc_hash,
        records=[SpecRecord(section="4.5", name="TX gain", typ="12", page=7)],
    )


def _plotset(doc_hash: str, part: str, *, with_url: bool = True) -> PlotSet:
    return PlotSet(
        schema_version=PLOTS_SCHEMA_VERSION,
        part_number=part,
        doc_hash=doc_hash,
        plots=[
            PlotRecord(
                id="4.5-f001",
                section="4.5",
                caption="Figure 4-1. TX Output",
                page_start=1,
                page_end=1,
                image_url="https://www.ti.com/img/GUID-low.gif" if with_url else "",
            )
        ],
    )


def _fake_fetcher(_url: str) -> bytes:
    return b"GIF89a\x01\x00\x01\x00\x00\x00\x00!"


def _publish(
    part_dir: Path,
    raw: RawDocument,
    *,
    shared_docs_dir: Path | None = None,
    plotset: PlotSet | None = None,
    specset: SpecSet | None = None,
) -> CorpusManifest:
    plans = build_section_plans(raw)
    return write_corpus(
        part_dir,
        [(raw, plans, {})],
        "# INDEX\n",
        pipeline_version="0.4.0",
        vendor="ti",
        specsets=[specset] if specset else None,
        plotsets=[plotset] if plotset else None,
        shared_docs_dir=shared_docs_dir,
    )


def _listing(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# --- the unshared layout is untouched --------------------------------------


def test_none_mode_writes_the_golden_per_part_listing(settings: Settings) -> None:
    """Criterion 1: `shared_docs_dir=None` is exactly today's layout."""
    part = settings.parts_dir / "AD9081"
    raw = _raw()
    _publish(
        part,
        raw,
        specset=_specset(DOC_HASH, "AD9081"),
        plotset=_plotset(DOC_HASH, "AD9081", with_url=False),
    )

    assert _listing(part) == [
        "AGENT.md",
        "INDEX.md",
        f"docs/{DOC_DIR}/plots.json",
        f"docs/{DOC_DIR}/search_index.json",
        f"docs/{DOC_DIR}/sections/1-features.md",
        f"docs/{DOC_DIR}/sections/4-5-tx.md",
        f"docs/{DOC_DIR}/specs.json",
        f"docs/{DOC_DIR}/tables/4-5-tx-t01.csv",
        "manifest.json",
    ]
    # references stay part-relative, and nothing is marked shared
    manifest = read_manifest(part)
    assert manifest is not None
    assert [s.file for s in manifest.sections] == [
        f"docs/{DOC_DIR}/sections/1-features.md",
        f"docs/{DOC_DIR}/sections/4-5-tx.md",
    ]
    assert not any(is_library_ref(s.file) for s in manifest.sections)
    for section in manifest.sections:
        assert (part / section.file).is_file()
    # the artifacts still carry the publishing part's number
    assert json.loads((part / f"docs/{DOC_DIR}/specs.json").read_text())["part_number"] == "AD9081"


def test_none_mode_artifact_bytes_survive_a_republish(settings: Settings) -> None:
    part = settings.parts_dir / "AD9081"
    raw = _raw()
    _publish(part, raw)
    before = {p: p.read_bytes() for p in part.rglob("*") if p.is_file()}
    _publish(part, raw)
    after = {p: p.read_bytes() for p in part.rglob("*") if p.is_file()}
    assert set(before) == set(after)
    for path, data in before.items():
        if path.name == "manifest.json":
            continue  # carries `generated_at`; rewritten by design
        assert after[path] == data, path


# --- publish once, reference many ------------------------------------------


def test_one_document_three_parts_is_one_copy_of_each_artifact(
    settings: Settings,
) -> None:
    """Criterion 2 and 3."""
    shared = settings.library_dir / "docs"
    raw = _raw()
    parts = ["AD9081", "AD9082", "AD9986"]
    manifests = []
    for part_number in parts:
        plotset = _plotset(DOC_HASH, part_number)
        fetch_plot_images(plotset, shared / DOC_DIR, fetcher=_fake_fetcher)
        manifests.append(
            _publish(
                settings.parts_dir / part_number,
                raw,
                shared_docs_dir=shared,
                plotset=plotset,
                specset=_specset(DOC_HASH, part_number),
            )
        )

    # exactly one copy of every artifact, figures included
    assert _listing(settings.library_dir) == [
        f"docs/{DOC_DIR}/figures/4-5/4.5-f001.gif",
        f"docs/{DOC_DIR}/plots.json",
        f"docs/{DOC_DIR}/search_index.json",
        f"docs/{DOC_DIR}/sections/1-features.md",
        f"docs/{DOC_DIR}/sections/4-5-tx.md",
        f"docs/{DOC_DIR}/specs.json",
        f"docs/{DOC_DIR}/tables/4-5-tx-t01.csv",
    ]
    # and no part holds one
    for part_number in parts:
        assert _listing(settings.parts_dir / part_number) == [
            "AGENT.md",
            "INDEX.md",
            "manifest.json",
        ]

    # every part's manifest references the shared location and resolves
    for part_number, manifest in zip(parts, manifests, strict=True):
        part_dir = settings.parts_dir / part_number
        on_disk = read_manifest(part_dir)
        assert on_disk is not None
        assert [s.file for s in on_disk.sections] == [s.file for s in manifest.sections]
        assert on_disk.sections, "a shared publish still lists its sections"
        for section in on_disk.sections:
            assert section.file.startswith(f"{LIBRARY_REF_PREFIX}docs/{DOC_DIR}/")
            resolved = resolve_artifact_ref(
                section.file, part_dir=part_dir, library_dir=settings.library_dir
            )
            assert resolved.is_file(), section.file
            assert resolved.parent.parent == settings.library_dir / "docs" / DOC_DIR


def test_shared_artifacts_are_part_neutral(settings: Settings) -> None:
    """Three publishers must agree on the bytes, so no part stamps its name."""
    shared = settings.library_dir / "docs"
    raw = _raw()
    for part_number in ("AD9081", "AD9082"):
        _publish(
            settings.parts_dir / part_number,
            raw,
            shared_docs_dir=shared,
            specset=_specset(DOC_HASH, part_number),
            plotset=_plotset(DOC_HASH, part_number, with_url=False),
        )
    for filename in ("specs.json", "plots.json", "search_index.json"):
        data = json.loads((shared / DOC_DIR / filename).read_text(encoding="utf-8"))
        assert data["part_number"] == "", filename
        assert data["doc_hash"] == DOC_HASH
    # the part identity is still recoverable — from the manifest, as always
    assert read_manifest(settings.parts_dir / "AD9082").part_number == "AD9082"


def test_a_shared_reference_cannot_be_resolved_against_the_part_dir(
    settings: Settings,
) -> None:
    ref = f"{LIBRARY_REF_PREFIX}docs/{DOC_DIR}/sections/1-features.md"
    with pytest.raises(ValueError, match="shared document store"):
        resolve_artifact_ref(ref, part_dir=settings.parts_dir / "AD9081")


# --- figure paths are anchored at their own root ---------------------------


def test_plot_record_file_is_library_relative_at_schema_2(settings: Settings) -> None:
    """Criterion 4."""
    shared = settings.library_dir / "docs"
    doc_dir = shared / DOC_DIR
    plotset = _plotset(DOC_HASH, "AD9081")
    assert fetch_plot_images(plotset, doc_dir, fetcher=_fake_fetcher) == 1
    record = plotset.plots[0]

    assert artifact_root(doc_dir) == settings.library_dir
    assert record.file == f"docs/{DOC_DIR}/figures/4-5/4.5-f001.gif"
    assert (settings.library_dir / record.file).is_file()
    assert not (settings.parts_dir / "AD9081" / record.file).exists()

    _publish(settings.parts_dir / "AD9081", _raw(), shared_docs_dir=shared, plotset=plotset)
    on_disk = load_plotset(doc_dir)
    assert on_disk is not None
    assert on_disk.schema_version == PLOTS_SCHEMA_VERSION == "2"
    assert resolve_plot_file(on_disk.plots[0], doc_dir=doc_dir) == (
        settings.library_dir / record.file
    )


def test_unshared_plot_record_file_stays_part_relative(settings: Settings) -> None:
    """The same string, anchored at the part — which is where the file is."""
    part = settings.parts_dir / "AD9081"
    doc_dir = part / "docs" / DOC_DIR
    plotset = _plotset(DOC_HASH, "AD9081")
    fetch_plot_images(plotset, doc_dir, fetcher=_fake_fetcher)
    assert plotset.plots[0].file == f"docs/{DOC_DIR}/figures/4-5/4.5-f001.gif"
    assert artifact_root(doc_dir) == part
    assert resolve_plot_file(plotset.plots[0], doc_dir=doc_dir) == (part / plotset.plots[0].file)


def test_schema_1_plots_json_is_rejected_not_resolved(settings: Settings) -> None:
    """Criterion 5: never silently resolved against the wrong root."""
    doc_dir = settings.library_dir / "docs" / DOC_DIR
    doc_dir.mkdir(parents=True)
    legacy = _plotset(DOC_HASH, "AD9081", with_url=False).model_copy(update={"schema_version": "1"})
    legacy.plots[0].file = f"docs/{DOC_DIR}/figures/4-5/4.5-f001.gif"
    (doc_dir / "plots.json").write_text(legacy.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(StalePlotsSchemaError) as excinfo:
        load_plotset(doc_dir)
    message = str(excinfo.value)
    assert "plots.json" in message
    assert "schema 1" in message and PLOTS_SCHEMA_VERSION in message
    assert "wrong root" in message and "republish" in message

    with pytest.raises(StalePlotsSchemaError):
        resolve_plot_file(legacy.plots[0], doc_dir=doc_dir, schema_version="1")


def test_a_figure_path_escaping_its_root_resolves_to_nothing(
    settings: Settings,
) -> None:
    doc_dir = settings.library_dir / "docs" / DOC_DIR
    record = PlotRecord(id="x", section="4.5", file="../../../../secrets.png")
    assert resolve_plot_file(record, doc_dir=doc_dir) is None


# --- idempotence and concurrency -------------------------------------------


def test_republishing_a_shared_document_touches_nothing(settings: Settings) -> None:
    """Criterion 6: the second publish leaves every mtime alone."""
    shared = settings.library_dir / "docs"
    raw = _raw()
    args = {
        "shared_docs_dir": shared,
        "specset": _specset(DOC_HASH, "AD9081"),
        "plotset": _plotset(DOC_HASH, "AD9081", with_url=False),
    }
    _publish(settings.parts_dir / "AD9081", raw, **args)
    before = {p: p.stat().st_mtime_ns for p in shared.rglob("*") if p.is_file()}
    assert before

    _publish(settings.parts_dir / "AD9081", raw, **args)
    after = {p: p.stat().st_mtime_ns for p in shared.rglob("*") if p.is_file()}
    assert after == before

    # and a *second part* publishing the same document is equally a no-op —
    # including the spec set, which arrives stamped with the other part
    _publish(
        settings.parts_dir / "AD9082",
        raw,
        **{**args, "specset": _specset(DOC_HASH, "AD9082")},
    )
    assert {p: p.stat().st_mtime_ns for p in shared.rglob("*") if p.is_file()} == before


def test_concurrent_publishes_leave_one_intact_copy(settings: Settings) -> None:
    """Criterion 7: no torn file, no `.tmp` debris, one copy."""
    shared = settings.library_dir / "docs"
    raw = _raw()
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def publish(part_number: str) -> None:
        try:
            barrier.wait(timeout=10)
            _publish(
                settings.parts_dir / part_number,
                raw,
                shared_docs_dir=shared,
                specset=_specset(DOC_HASH, part_number),
                plotset=_plotset(DOC_HASH, part_number, with_url=False),
            )
        except BaseException as exc:  # noqa: BLE001 — surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=publish, args=(f"AD908{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors

    assert [p.name for p in shared.rglob("*.tmp")] == []
    assert _listing(settings.library_dir) == [
        f"docs/{DOC_DIR}/plots.json",
        f"docs/{DOC_DIR}/search_index.json",
        f"docs/{DOC_DIR}/sections/1-features.md",
        f"docs/{DOC_DIR}/sections/4-5-tx.md",
        f"docs/{DOC_DIR}/specs.json",
        f"docs/{DOC_DIR}/tables/4-5-tx-t01.csv",
    ]
    # every artifact is whole
    for name in ("specs.json", "plots.json", "search_index.json"):
        assert json.loads((shared / DOC_DIR / name).read_text(encoding="utf-8"))
    assert (
        (shared / DOC_DIR / "sections" / "1-features.md")
        .read_text(encoding="utf-8")
        .startswith("#")
    )
    for n in range(4):
        assert read_manifest(settings.parts_dir / f"AD908{n}") is not None


# --- stats keep their meaning ----------------------------------------------


def test_n_plot_files_counts_referenced_figures_in_both_modes(
    settings: Settings,
) -> None:
    """Criterion 8: a shared figure still counts for the part that cites it."""
    raw = _raw()
    local_part = settings.parts_dir / "LOCAL"
    local_plots = _plotset(DOC_HASH, "LOCAL")
    fetch_plot_images(local_plots, local_part / "docs" / DOC_DIR, fetcher=_fake_fetcher)
    local = _publish(local_part, raw, plotset=local_plots)

    shared = settings.library_dir / "docs"
    shared_plots = _plotset(DOC_HASH, "SHARED")
    fetch_plot_images(shared_plots, shared / DOC_DIR, fetcher=_fake_fetcher)
    remote = _publish(
        settings.parts_dir / "SHARED", raw, shared_docs_dir=shared, plotset=shared_plots
    )

    assert local.stats.n_plot_files == 1
    assert remote.stats.n_plot_files == local.stats.n_plot_files
    assert remote.stats.n_sections == local.stats.n_sections == 2
    assert remote.stats.n_tables == local.stats.n_tables == 1
    assert remote.stats.section_bytes == local.stats.section_bytes
    assert remote.stats.search_index_bytes > 0
    assert remote.stats.plot_confidence == local.stats.plot_confidence


# --- reading a manifest whose store has lost a file ------------------------


def test_a_removed_shared_figure_is_reported_not_crashed(settings: Settings) -> None:
    """Criterion 9."""
    shared = settings.library_dir / "docs"
    plotset = _plotset(DOC_HASH, "AD9081")
    fetch_plot_images(plotset, shared / DOC_DIR, fetcher=_fake_fetcher)
    part_dir = settings.parts_dir / "AD9081"
    _publish(
        part_dir,
        _raw(),
        shared_docs_dir=shared,
        plotset=plotset,
        specset=_specset(DOC_HASH, "AD9081"),
    )

    manifest = read_manifest(part_dir)
    assert manifest is not None
    intact = manifest_artifacts(manifest, part_dir=part_dir, library_dir=settings.library_dir)
    assert all(a.exists for a in intact), [a for a in intact if not a.exists]
    assert {a.kind for a in intact} == {"section", "specs", "plots", "search_index", "figure"}
    assert all(a.shared for a in intact)

    (settings.library_dir / plotset.plots[0].file).unlink()

    gone = missing_artifacts(manifest, part_dir=part_dir, library_dir=settings.library_dir)
    assert [a.kind for a in gone] == ["figure"]
    assert gone[0].ref == plotset.plots[0].file
    assert "not on disk" in gone[0].detail
    assert gone[0].shared is True


def test_a_stale_shared_plots_json_is_reported_not_raised(settings: Settings) -> None:
    shared = settings.library_dir / "docs"
    part_dir = settings.parts_dir / "AD9081"
    _publish(
        part_dir,
        _raw(),
        shared_docs_dir=shared,
        plotset=_plotset(DOC_HASH, "AD9081", with_url=False),
    )
    legacy = load_plotset(shared / DOC_DIR).model_copy(update={"schema_version": "1"})
    (shared / DOC_DIR / "plots.json").write_text(legacy.model_dump_json(indent=2), encoding="utf-8")

    manifest = read_manifest(part_dir)
    gone = missing_artifacts(manifest, part_dir=part_dir, library_dir=settings.library_dir)
    assert [a.kind for a in gone] == ["plots"]
    assert "expected 2" in gone[0].detail


# --- the renderers still write where their records point -------------------


def test_render_figure_regions_writes_into_the_shared_store(
    settings: Settings, tmp_path: Path
) -> None:
    """Criterion 10, clip-render half."""
    pdf_path = tmp_path / "note.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 200), "TX output trace")
    page.insert_text((72, 400), "Figure 4-1. TX Output")
    doc.save(str(pdf_path))
    doc.close()

    doc_dir = settings.library_dir / "docs" / DOC_DIR
    plotset = _plotset(DOC_HASH, "AD9081", with_url=False)
    assert render_figure_regions(plotset, doc_dir, pdf_path, dpi=72) == 1

    record = plotset.plots[0]
    assert record.file == f"docs/{DOC_DIR}/figures/4-5/4.5-f001.png"
    written = resolve_plot_file(record, doc_dir=doc_dir)
    assert written == doc_dir / "figures" / "4-5" / "4.5-f001.png"
    assert written.read_bytes().startswith(b"\x89PNG")


def test_fetch_plot_images_writes_where_the_record_points(
    settings: Settings,
) -> None:
    """Criterion 10, download half."""
    doc_dir = settings.library_dir / "docs" / DOC_DIR
    plotset = _plotset(DOC_HASH, "AD9081")
    assert fetch_plot_images(plotset, doc_dir, fetcher=_fake_fetcher) == 1
    record = plotset.plots[0]
    assert resolve_plot_file(record, doc_dir=doc_dir) == (settings.library_dir / record.file)
    assert (
        os.path.relpath(settings.library_dir / record.file, doc_dir).replace("\\", "/")
        == "figures/4-5/4.5-f001.gif"
    )
