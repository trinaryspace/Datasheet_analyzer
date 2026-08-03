"""Batch runner (serial) — external behavior only.

Given a directory of synthetic PDFs and temp-dir settings, assert the
observable outcomes: which parts exist, which jobs are done/failed, the
mapping/summary output, and exit semantics. No assertions on internals.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.batch import STATUS_DONE, STATUS_FAILED, BatchError, run_batch
from datasheet_analyzer.config import Settings

SYN = Path(__file__).parent.parent / "fixtures" / "synthetic"


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
