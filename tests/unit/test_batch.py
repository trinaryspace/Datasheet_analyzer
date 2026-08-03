"""Batch runner (serial) — external behavior only.

Given a directory of synthetic PDFs and temp-dir settings, assert the
observable outcomes: which parts exist, which jobs are done/skipped/failed,
the mapping/summary output, and exit semantics. No assertions on internals.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.batch import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED,
    BatchError,
    run_batch,
)
from datasheet_analyzer.config import Settings

SYN = Path(__file__).parent.parent / "fixtures" / "synthetic"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_failed_rebuild_is_not_skipped_on_rerun(batch_env, monkeypatch, make_synthetic_pdf):
    """A rebuild run that fails must not arm the skip for the stale corpus."""
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    import datasheet_analyzer.pipeline as pipeline_mod
    from datasheet_analyzer.extract.http import MappingFetcher

    make_synthetic_pdf(pdfs / "test9000.pdf", marker=" REVISION 1")
    # the rebuild run fails (network): nothing may be assumed rebuilt
    pipeline_mod.get_backend("ti_html").fetcher = MappingFetcher({})
    report = run_batch(pdfs, settings=settings, use_llm=False)
    by_part = {j.part: j for j in report.jobs}
    assert by_part["TEST9000"].status == STATUS_FAILED

    # restore the fetcher and rerun: TEST9000 must rebuild, not skip
    pipeline_mod.get_backend("ti_html").fetcher = MappingFetcher(
        _mapping_for("TEST9000")
    )
    report = run_batch(pdfs, settings=settings, use_llm=False)
    by_part = {j.part: j for j in report.jobs}
    assert by_part["TEST9000"].status == STATUS_DONE
    assert by_part["PLAIN"].status == STATUS_SKIPPED

    # and only after the successful rebuild does a rerun skip it
    report = run_batch(pdfs, settings=settings, use_llm=False)
    assert report.counts == {STATUS_DONE: 0, STATUS_FAILED: 0, STATUS_SKIPPED: 3}


def test_skip_gate_survives_path_spelling_change(batch_env, make_synthetic_pdf):
    """The changed-PDF refresh must match the recorded path regardless of how
    the CLI spelled the directory (relative vs absolute, separators, case)."""
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    make_synthetic_pdf(pdfs / "test9000.pdf", marker=" REVISION 1")
    relative = Path(os.path.relpath(pdfs))
    report = run_batch(relative, settings=settings, use_llm=False)
    by_part = {j.part: j for j in report.jobs}
    assert by_part["TEST9000"].status == STATUS_DONE  # rebuilt...

    # ...and the rerun (different spelling) skips it: refresh matched by path
    report = run_batch(relative, settings=settings, use_llm=False)
    assert report.counts == {STATUS_DONE: 0, STATUS_FAILED: 0, STATUS_SKIPPED: 3}


def test_corrupt_inventory_fails_that_part_isolated(batch_env):
    """An unreadable inventory cannot be verified: the job fails alone and the
    rest of the batch carries on (SPEC: failure isolation)."""
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok
    (settings.parts_dir / "PLAIN" / "sources.json").write_text(
        "{ not valid json", encoding="utf-8"
    )

    report = run_batch(pdfs, settings=settings, use_llm=False)
    by_part = {j.part: j for j in report.jobs}
    assert by_part["PLAIN"].status == STATUS_FAILED
    assert by_part["PLAIN"].error
    assert by_part["TEST9000"].status == STATUS_SKIPPED
    assert by_part["TEST9001"].status == STATUS_SKIPPED
    assert not report.ok


def _wire_ti_backend(monkeypatch, mapping: dict[str, str]) -> None:
    """Replay `mapping` through the ti_html backend the pipeline resolves to.

    get_backend builds a fresh backend per call, so the pipeline symbol is
    patched to return one pre-wired instance (same shape as test_pipeline).
    """
    from datasheet_analyzer.extract import get_backend
    from datasheet_analyzer.extract.http import MappingFetcher

    backend = get_backend("ti_html")
    backend.fetcher = MappingFetcher(mapping)
    monkeypatch.setattr("datasheet_analyzer.pipeline.get_backend", lambda name: backend)


def _mapping_for(part: str) -> dict[str, str]:
    root = "https://www.ti.com/document-viewer" + f"/{part}/datasheet"
    return {
        root: (SYN / "ti_main.html").read_text(encoding="utf-8"),
        root + "/GUID-AAAA1111-0000-0000-0000-000000000001#TITLE-X1": (
            SYN / "ti_sec_features.html"
        ).read_text(encoding="utf-8"),
        root + "/GUID-BBBB2222-0000-0000-0000-000000000002#TITLE-X2": (
            SYN / "ti_sec_absmax.html"
        ).read_text(encoding="utf-8"),
    }


@pytest.fixture
def batch_env(tmp_path, monkeypatch, make_synthetic_pdf):
    """A flat directory of synthetic PDFs; ti_html replays a per-part mapping."""
    pdfs = tmp_path / "datasheets"
    pdfs.mkdir()
    for name in ("test9000.pdf", "test9001.pdf", "plain.PDF"):
        make_synthetic_pdf(pdfs / name)

    mapping: dict[str, str] = {}
    for part in ("TEST9000", "TEST9001", "PLAIN"):
        mapping.update(_mapping_for(part))
    _wire_ti_backend(monkeypatch, mapping)

    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    return pdfs, settings


def test_batch_builds_each_pdf_as_its_own_part(batch_env, capsys):
    pdfs, settings = batch_env
    report = run_batch(pdfs, settings=settings, use_llm=False)

    assert report.ok
    assert [j.status for j in report.jobs] == [STATUS_DONE] * 3
    # sorted filename order, part = uppercased stem (case-insensitive .pdf)
    assert [(j.part, Path(j.pdf_path).name) for j in report.jobs] == [
        ("PLAIN", "plain.PDF"),
        ("TEST9000", "test9000.pdf"),
        ("TEST9001", "test9001.pdf"),
    ]
    for part in ("PLAIN", "TEST9000", "TEST9001"):
        part_dir = settings.parts_dir / part
        assert (part_dir / "INDEX.md").exists()
        assert (part_dir / "manifest.json").exists()
        assert (part_dir / "sources.json").exists()
    for job in report.jobs:
        assert job.stats is not None
        assert job.stats.n_sections == 2
        assert not job.error

    out = capsys.readouterr().out
    # the full file -> part mapping is printed before any build work starts
    assert "test9000.pdf -> TEST9000" in out
    assert "plain.PDF -> PLAIN" in out
    assert out.index("plain.PDF -> PLAIN") < out.index("building PLAIN")
    # summary table lists every job with its outcome
    assert "Batch summary" in out
    assert "3 jobs: 3 done, 0 failed" in out
    assert "| PLAIN | done |" in out
    assert "| TEST9001 | done |" in out


def test_batch_ignores_non_pdf_files(tmp_path, monkeypatch, make_synthetic_pdf):
    pdfs = tmp_path / "datasheets"
    pdfs.mkdir()
    make_synthetic_pdf(pdfs / "test9000.pdf")
    (pdfs / "README.md").write_text("not a datasheet", encoding="utf-8")
    nested = pdfs / "notes"
    nested.mkdir()
    make_synthetic_pdf(nested / "sneaky.pdf")  # direct children only

    _wire_ti_backend(monkeypatch, _mapping_for("TEST9000"))
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()

    report = run_batch(pdfs, settings=settings, use_llm=False)

    assert report.ok
    assert [j.part for j in report.jobs] == ["TEST9000"]
    assert (settings.parts_dir / "TEST9000" / "INDEX.md").exists()
    assert not (settings.parts_dir / "SNEAKY").exists()


def test_failed_job_is_isolated_and_batch_continues(batch_env, capsys):
    pdfs, settings = batch_env
    (pdfs / "broken.pdf").write_bytes(b"%PDF-1.4 corrupt nonsense bytes")
    report = run_batch(pdfs, settings=settings, use_llm=False)

    assert not report.ok
    by_part = {j.part: j for j in report.jobs}
    assert [j.status for j in report.jobs] == [
        STATUS_FAILED,
        STATUS_DONE,
        STATUS_DONE,
        STATUS_DONE,
    ]
    broken = by_part["BROKEN"]
    assert broken.error  # captured message, not a stack trace
    assert "\n" not in broken.error  # one-line summary, no traceback in the table
    # the rest of the batch completed regardless
    for part in ("PLAIN", "TEST9000", "TEST9001"):
        assert by_part[part].status == STATUS_DONE
        assert (settings.parts_dir / part / "INDEX.md").exists()

    out = capsys.readouterr().out
    assert "| BROKEN | failed |" in out
    assert "4 jobs: 3 done, 1 failed" in out


def test_rerun_skips_already_built_parts(batch_env, monkeypatch, capsys):
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    # any fetch from here on is a hard error: skipped jobs must not extract.
    # A second run over the unchanged directory must never touch the fetcher.
    import datasheet_analyzer.pipeline as pipeline_mod
    from datasheet_analyzer.extract.http import MappingFetcher

    pipeline_mod.get_backend("ti_html").fetcher = MappingFetcher({})
    report = run_batch(pdfs, settings=settings, use_llm=False)

    assert report.ok  # skips count toward success
    assert report.counts == {STATUS_DONE: 0, STATUS_FAILED: 0, STATUS_SKIPPED: 3}
    assert all(j.status == STATUS_SKIPPED for j in report.jobs)
    assert all(j.error for j in report.jobs)  # every skip carries its reason

    out = capsys.readouterr().out
    assert "3 jobs: 0 done, 0 failed, 3 skipped" in out
    assert "| TEST9000 | skipped | already built" in out


def test_changed_pdf_rebuilds_exactly_that_part_and_reregisters(batch_env, make_synthetic_pdf):
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    target = pdfs / "test9000.pdf"
    make_synthetic_pdf(target, marker=" REVISION 1")
    variant_hash = _sha256(target)

    report = run_batch(pdfs, settings=settings, use_llm=False)
    by_part = {j.part: j for j in report.jobs}
    assert by_part["TEST9000"].status == STATUS_DONE
    assert by_part["TEST9000"].error == ""
    assert by_part["PLAIN"].status == STATUS_SKIPPED
    assert by_part["TEST9001"].status == STATUS_SKIPPED

    # the rebuilt part is keyed on the new identity (hash is identity)...
    from datasheet_analyzer.acquire.inventory import load_inventory

    assert [s.content_hash for s in load_inventory(settings.parts_dir / "TEST9000")] == [
        variant_hash
    ]
    # ...so the next run skips it instead of rebuilding forever
    report = run_batch(pdfs, settings=settings, use_llm=False)
    assert report.counts == {STATUS_DONE: 0, STATUS_FAILED: 0, STATUS_SKIPPED: 3}


def test_new_pdf_builds_while_existing_parts_skip(batch_env, make_synthetic_pdf):
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    import datasheet_analyzer.pipeline as pipeline_mod
    from datasheet_analyzer.extract.http import MappingFetcher

    make_synthetic_pdf(pdfs / "test9002.pdf")
    pipeline_mod.get_backend("ti_html").fetcher = MappingFetcher(
        _mapping_for("TEST9002")
    )
    report = run_batch(pdfs, settings=settings, use_llm=False)
    by_part = {j.part: j for j in report.jobs}
    assert by_part["TEST9002"].status == STATUS_DONE
    assert (settings.parts_dir / "TEST9002" / "INDEX.md").exists()
    assert by_part["TEST9000"].status == STATUS_SKIPPED


def test_missing_manifest_rebuilds_part(batch_env):
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok
    (settings.parts_dir / "PLAIN" / "manifest.json").unlink()

    report = run_batch(pdfs, settings=settings, use_llm=False)
    by_part = {j.part: j for j in report.jobs}
    assert by_part["PLAIN"].status == STATUS_DONE  # rebuilt, not skipped
    assert by_part["TEST9000"].status == STATUS_SKIPPED


def test_corrupt_manifest_rebuilds_part(batch_env):
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok
    path = settings.parts_dir / "PLAIN" / "manifest.json"
    path.write_text("{ not valid json", encoding="utf-8")

    report = run_batch(pdfs, settings=settings, use_llm=False)
    by_part = {j.part: j for j in report.jobs}
    assert by_part["PLAIN"].status == STATUS_DONE
    assert by_part["TEST9000"].status == STATUS_SKIPPED
    # the failed publish left no valid manifest; the rebuild restored one
    assert (settings.parts_dir / "PLAIN" / "manifest.json").read_text(
        encoding="utf-8"
    ).startswith("{")


def test_pipeline_version_bump_forces_rebuild(batch_env, monkeypatch):
    import datasheet_analyzer.batch as batch_mod
    import datasheet_analyzer.pipeline as pipeline_mod

    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    monkeypatch.setattr(batch_mod, "PIPELINE_VERSION", "9.9.9")
    monkeypatch.setattr(pipeline_mod, "PIPELINE_VERSION", "9.9.9")
    report = run_batch(pdfs, settings=settings, use_llm=False)
    assert report.counts == {STATUS_DONE: 3, STATUS_FAILED: 0, STATUS_SKIPPED: 0}


def test_skip_uses_hash_not_mtime(batch_env):
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    future = time.time() + 10000
    for p in pdfs.iterdir():
        if p.is_file() and p.suffix.lower() == ".pdf":
            os.utime(p, (future, future))

    report = run_batch(pdfs, settings=settings, use_llm=False)
    assert report.counts == {STATUS_DONE: 0, STATUS_FAILED: 0, STATUS_SKIPPED: 3}


def test_force_rebuilds_even_when_up_to_date(batch_env):
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    report = run_batch(pdfs, settings=settings, force=True, use_llm=False)
    assert report.counts == {STATUS_DONE: 3, STATUS_FAILED: 0, STATUS_SKIPPED: 0}
    for job in report.jobs:
        assert job.stats is not None


def test_no_cache_disables_skip(batch_env):
    """--no-cache means a full redo, exactly like `dsa build --no-cache`."""
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    report = run_batch(pdfs, settings=settings, use_cache=False, use_llm=False)
    assert report.counts == {STATUS_DONE: 3, STATUS_FAILED: 0, STATUS_SKIPPED: 0}


def test_cli_batch_force_rebuilds(batch_env, monkeypatch, capsys):
    pdfs, settings = batch_env
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    assert cli.main(["batch", str(pdfs), "--no-llm"]) == 0
    capsys.readouterr()

    code = cli.main(["batch", str(pdfs), "--no-llm", "--force"])
    out = capsys.readouterr().out
    assert code == 0
    assert "3 jobs: 3 done, 0 failed, 0 skipped" in out


def test_missing_directory_is_an_error(tmp_path):
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    with pytest.raises(BatchError):
        run_batch(tmp_path / "nope", settings=settings, use_llm=False)


def test_empty_directory_is_an_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    with pytest.raises(BatchError, match="no PDF"):
        run_batch(empty, settings=settings, use_llm=False)


def test_rerun_reuses_extraction_cache(batch_env, monkeypatch):
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    # any fetch from here on is a hard error: the extraction cache must make
    # a re-run fetch-free (this is what skip-if-up-to-date builds on). The
    # backend instance is resolved through the patched pipeline symbol so we
    # mutate the exact instance the jobs use (get_backend builds fresh ones).
    import datasheet_analyzer.pipeline as pipeline_mod
    from datasheet_analyzer.extract.http import MappingFetcher

    backend = pipeline_mod.get_backend("ti_html")
    backend.fetcher = MappingFetcher({})
    report = run_batch(pdfs, settings=settings, use_llm=False)
    assert report.ok


def test_no_cache_forces_reextract(batch_env):
    pdfs, settings = batch_env
    assert run_batch(pdfs, settings=settings, use_llm=False).ok

    import datasheet_analyzer.pipeline as pipeline_mod
    from datasheet_analyzer.extract.http import MappingFetcher

    backend = pipeline_mod.get_backend("ti_html")
    backend.fetcher = MappingFetcher({})
    report = run_batch(pdfs, settings=settings, use_cache=False, use_llm=False)
    assert not report.ok
    assert all(j.status == STATUS_FAILED for j in report.jobs)
    assert all("unexpected network request" in j.error for j in report.jobs)


def test_cli_batch_command(batch_env, monkeypatch, capsys):
    pdfs, settings = batch_env
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    code = cli.main(["batch", str(pdfs), "--no-llm"])
    out = capsys.readouterr().out
    assert code == 0
    assert "test9000.pdf -> TEST9000" in out
    assert "Batch summary" in out
    assert "# TEST9000" in (settings.parts_dir / "TEST9000" / "INDEX.md").read_text(
        encoding="utf-8"
    )


def test_cli_batch_failure_exits_1(batch_env, monkeypatch, capsys):
    pdfs, settings = batch_env
    (pdfs / "broken.pdf").write_bytes(b"%PDF-1.4 corrupt nonsense bytes")
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    code = cli.main(["batch", str(pdfs), "--no-llm"])
    capsys.readouterr()  # discard output; exit code is the contract
    assert code == 1


def test_cli_batch_missing_dir_exits_2(tmp_path, monkeypatch, capsys):
    settings = Settings(parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache").resolve()
    monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
    code = cli.main(["batch", str(tmp_path / "nope")])
    err = capsys.readouterr().err
    assert code == 2
    assert "batch error" in err
