"""Revision awareness + staleness surfacing (phase 7, ticket 02).

This file grows with the ticket. What is proven here so far:

- **the revision parser is tight enough to read a literature number** -
  `sniff_revision` returns `SNAS800B` for `lmx1204.pdf` rather than the page-1
  pin name `SYSREFOUT0`, and reads nothing at all off the three Mini-Circuits
  datasheets whose heading word `SPECIFICATIONS1` used to pass for one. Every
  document in this checkout is asserted, so tightening the shape cannot quietly
  cost a reading that already worked;
- **one lexicon, two doors** - a document on disk and a document that only
  exists as downloaded bytes read through the same rules, which is what lets
  `dsa check-revisions` compare an upstream document it never writes down.

Hermetic by construction (invariant 4): nothing here opens a socket, and the
synthetic PDFs are built in-test with `fitz`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.acquire.inventory import library_view
from datasheet_analyzer.acquire.registry import (
    DocumentRegistry,
    RegistryDocument,
    RegistryEntry,
    registry_path,
    save_registry,
)
from datasheet_analyzer.acquire.revisions import (
    CHECKED,
    ERROR,
    NO_URL,
    check_all,
    check_part,
    compare,
    registry_document_for,
)
from datasheet_analyzer.config import Settings
from datasheet_analyzer.extract.http import ReplayBinaryFetcher, binary_cache_name
from datasheet_analyzer.extract.pdf_structure import (
    revision_from_texts,
    sniff_revision,
    sniff_revision_bytes,
)
from datasheet_analyzer.library import LibraryStore, clear_library_cache
from datasheet_analyzer.models import (
    DocType,
    LibraryDocument,
    RevisionState,
    SourceDocument,
    Staleness,
)
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.retrieve import clear_index_cache
from datasheet_analyzer.staleness import (
    BANNER_BEGIN,
    apply_index_banner,
    corpus_staleness,
    index_banner,
    pack_footer,
    project_staleness,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Every PDF this checkout can hold, with the revision the shared lexicon must
#: read off it. The first two are the readings the ticket moved; the rest are
#: the regression guard. Repo-root working copies are skip-guarded because they
#: are not all tracked - `lmx1204.pdf` and `LMX1204_registermap.pdf` in
#: particular are working files on this branch, not committed documents.
COMMITTED_DOCUMENTS = [
    ("lmx1204.pdf", "SNAS800B"),
    ("tests/fixtures/pdf/LHA-83W+.pdf", ""),
    ("tests/fixtures/pdf/PMA1-14LN+.pdf", ""),
    ("tests/fixtures/pdf/PSA-8A+.pdf", ""),
    ("tests/fixtures/pdf/ZX10R-2-183-S+.pdf", ""),
    ("LMX1204_registermap.pdf", "SNAU269A"),
    ("tests/fixtures/pdf/lm741.pdf", "SNOSC25D"),
    ("tests/fixtures/pdf/ad9081.pdf", "Rev. 0"),
    ("tests/fixtures/pdf/hmc520a.pdf", "Rev. A"),
    ("tests/fixtures/pdf/QPA1003P.pdf", "Rev. I"),
    ("afe7950.pdf", "SBASA41E"),
    ("afe7953.pdf", "SBASAN1A"),
]


def _make_pdf(path: Path, revision: str, marker: str = "") -> bytes:
    """A tiny, readable datasheet-shaped PDF with a sniffable revision.

    `marker` changes the bytes without changing the revision - which is exactly
    the upstream behaviour the ticket measured (a package-materials addendum
    regenerated with the current date) and the case that must NOT read stale.
    """
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), f"TEST9100 Quad RF transceiver. {marker}")
    p1.insert_text((72, 700), f"Rev. {revision}")
    p2 = doc.new_page()
    p2.insert_text(
        (72, 72),
        "4.1 Absolute Maximum Ratings VDD1P2 Supply voltage 1.2V -0.3 1.4 V TJ 150 C",
    )
    doc.set_toc([[1, "1 Features", 1], [1, "4.1 Absolute Maximum Ratings", 2]])
    doc.save(path)
    doc.close()
    return path.read_bytes()


class TestRevisionParser:
    def test_lmx1204_reads_its_own_literature_number(self):
        """The ticket headline defect: a pin name won over the real id."""
        pdf = REPO_ROOT / "lmx1204.pdf"
        if not pdf.exists():
            pytest.skip("lmx1204.pdf is not present in this checkout")
        assert sniff_revision(pdf) == "SNAS800B"

    @pytest.mark.parametrize("rel,expected", COMMITTED_DOCUMENTS)
    def test_every_document_in_this_checkout_still_reads_its_revision(self, rel, expected):
        path = REPO_ROOT / rel
        if not path.exists():  # the repo-root working copies are skip-guarded
            pytest.skip(f"{rel} is not present in this checkout")
        assert sniff_revision(path) == expected

    def test_a_signal_name_is_not_a_document_id(self):
        """The exact page-1 token order measured on LMX1204."""
        page = "SYSREFOUT0 SYSREFOUT1 SYSREFOUT2 SYSREFOUT3 ... SNAS800B"
        assert revision_from_texts([page]) == "SNAS800B"

    @pytest.mark.parametrize(
        "text",
        [
            "SUPPORT",  # all letters: no digit in the tail
            "SYSREF1",  # ends in a digit, not a revision letter
            "SYSREFOUT0",  # too long to be a literature number
            "SPI SDI SDO",  # ordinary three-letter signal names
            "SPECIFICATIONS1",  # the Mini-Circuits heading word, measured here
        ],
    )
    def test_shapes_that_are_not_literature_numbers_read_as_nothing(self, text):
        assert revision_from_texts([text]) == ""

    def test_a_rev_token_still_wins_within_a_page(self):
        assert revision_from_texts(["SNAS800B and Rev. C"]) == "Rev. C"

    def test_bytes_and_paths_read_the_same_lexicon(self, tmp_path):
        payload = _make_pdf(tmp_path / "x.pdf", "C")
        assert sniff_revision_bytes(payload) == "Rev. C"
        assert sniff_revision(tmp_path / "x.pdf") == "Rev. C"

    def test_unreadable_bytes_are_an_honest_miss_not_a_crash(self):
        assert sniff_revision_bytes(b"<html>document not found</html>") == ""


# --- fixtures for the check itself -------------------------------------------

URL = "https://example.invalid/test9100/test9100.pdf"
FROZEN = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A wholly private tree: parts, cache, Library and document registry.

    `library_dir` is named explicitly even though `tests/conftest.py`'s autouse
    `isolated_library` already points `DSA_LIBRARY_DIR` here, because that is
    where a revision check writes its finding: an escape to the repo's own
    shelf would have this suite rewriting checked-in records.
    """
    return Settings(
        parts_dir=tmp_path / "parts",
        projects_dir=tmp_path / "projects",
        cache_dir=tmp_path / ".cache",
        library_dir=tmp_path / "library",
        registry_dir=tmp_path / "registry",
    ).resolve()


@pytest.fixture
def recorded(tmp_path: Path) -> Path:
    cache = tmp_path / "recorded_http_bin"
    cache.mkdir()
    return cache


def _record(cache: Path, url: str, payload: bytes) -> None:
    (cache / binary_cache_name(url)).write_bytes(payload)


def _register(settings: Settings, *, revision: str, url: str | None = URL) -> Path:
    """A registry naming TEST9100's one datasheet."""
    registry = DocumentRegistry()
    registry.put(
        RegistryEntry(
            part_number="TEST9100",
            vendor="unknown",
            document=RegistryDocument(doc_type=DocType.DATASHEET, url=url, revision=revision),
        )
    )
    dest = registry_path(settings.registry_dir)
    save_registry(registry, dest)
    return dest


def _build(settings: Settings, revision: str = "A") -> Path:
    """A real built corpus for TEST9100 - Library record, INDEX.md and all."""
    pdf = settings.parts_dir / "TEST9100" / "documents" / "test9100.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    _make_pdf(pdf, revision)
    build_part(pdf, part_number="TEST9100", settings=settings, vendor="unknown", use_llm=False)
    clear_index_cache()
    clear_library_cache()
    return settings.parts_dir / "TEST9100"


def _documents(settings: Settings, part: str = "TEST9100") -> list[LibraryDocument]:
    clear_library_cache()
    return library_view(settings.parts_dir / part, store=LibraryStore.for_settings(settings))


def _wrap(revision: str, content_hash: str = "aa" * 32, **kw) -> LibraryDocument:
    """A Library record for a document that need not exist on disk."""
    return LibraryDocument(
        source=SourceDocument(
            content_hash=content_hash,
            path="parts/TEST9100/documents/test9100.pdf",
            part_number="TEST9100",
            doc_type=kw.pop("doc_type", DocType.DATASHEET),
            revision=revision,
        ),
        revision_state=RevisionState(**kw),
    )


# --- the comparison rule -----------------------------------------------------


class TestComparisonIsRevisionFirst:
    def test_a_different_revision_is_stale(self, tmp_path):
        upstream = _make_pdf(tmp_path / "up.pdf", "B")
        check = compare(_wrap("Rev. A"), upstream, now=FROZEN)
        assert check.state is Staleness.STALE
        assert check.upstream_revision == "Rev. B"
        assert check.checked_at == FROZEN

    def test_a_hash_difference_under_one_revision_is_not_stale(self, tmp_path):
        """The measured TI behaviour: regenerated bytes, same revision.

        A design that reads this as staleness raises a false alarm on every TI
        part every day, which trains the user to ignore the one warning here
        that protects a design decision.
        """
        upstream = _make_pdf(tmp_path / "up.pdf", "A", marker="regenerated 10-Aug-2026")
        check = compare(_wrap("Rev. A"), upstream, now=FROZEN)
        assert check.state is Staleness.CURRENT
        assert check.content_drift is True
        assert check.upstream_sha256 != check.local_sha256

    def test_content_drift_is_worded_so_it_cannot_read_as_a_new_revision(self, tmp_path):
        upstream = _make_pdf(tmp_path / "up.pdf", "A", marker="regenerated")
        check = compare(_wrap("Rev. A"), upstream, now=FROZEN)
        assert "regenerated, not revised" in check.message
        for forbidden in ("new revision", "available upstream", "superseded"):
            assert forbidden not in check.message

    def test_identical_bytes_are_current_with_no_drift(self, tmp_path):
        import hashlib

        upstream = _make_pdf(tmp_path / "up.pdf", "A")
        doc = _wrap("Rev. A", hashlib.sha256(upstream).hexdigest())
        check = compare(doc, upstream, now=FROZEN)
        assert check.state is Staleness.CURRENT and check.content_drift is False

    def test_an_unreadable_upstream_document_is_unknown_not_current(self):
        check = compare(_wrap("Rev. A"), b"not a pdf at all", now=FROZEN)
        assert check.state is Staleness.UNKNOWN
        assert "inconclusive" in check.message

    def test_a_corpus_with_no_revision_cannot_be_compared(self, tmp_path):
        upstream = _make_pdf(tmp_path / "up.pdf", "A")
        check = compare(_wrap(""), upstream, now=FROZEN)
        assert check.state is Staleness.UNKNOWN
        assert "no revision identifier to compare" in check.message


# --- dsa check-revisions -----------------------------------------------------


class TestCheckRevisions:
    def test_a_stale_corpus_is_detected_and_recorded(self, tmp_path, settings, recorded):
        _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "B"))

        report = check_part(
            "TEST9100",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        assert not report.ok and len(report.stale) == 1
        [doc] = _documents(settings)
        assert doc.revision_state.staleness is Staleness.STALE
        assert doc.revision_state.upstream_revision == "Rev. B"
        assert doc.revision_state.checked_at == FROZEN
        assert doc.revision_state.upstream_sha256

    def test_the_reading_survives_a_rebuild(self, tmp_path, settings, recorded):
        """The reason the state is on the Library record and not `sources.json`.

        `sources.json` is regenerated from the Library at publish time, so a
        state written there would be erased by the next build - and a rebuild
        quietly clearing a `stale` warning is the failure this placement exists
        to prevent.
        """
        _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "B"))
        check_part(
            "TEST9100",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        pdf = settings.parts_dir / "TEST9100" / "documents" / "test9100.pdf"
        build_part(pdf, part_number="TEST9100", settings=settings, vendor="unknown", use_llm=False)
        [doc] = _documents(settings)
        assert doc.revision_state.staleness is Staleness.STALE
        assert doc.revision_state.upstream_revision == "Rev. B"

    def test_a_regenerated_document_is_current_with_drift_recorded(
        self, tmp_path, settings, recorded
    ):
        _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "A", marker="regenerated"))

        report = check_part(
            "TEST9100",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        assert not report.stale and len(report.drifted) == 1
        [doc] = _documents(settings)
        assert doc.revision_state.staleness is Staleness.CURRENT
        assert doc.revision_state.content_drift is True

    def test_an_entry_with_no_url_leaves_the_recorded_state_alone(
        self, tmp_path, settings, recorded
    ):
        _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A", url=None)
        report = check_part(
            "TEST9100",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        [check] = report.checks
        assert check.status == NO_URL and "--url" in check.message
        [doc] = _documents(settings)
        assert doc.revision_state.staleness is Staleness.UNKNOWN
        assert doc.revision_state.checked_at is None

    def test_no_network_degrades_honestly_and_never_upgrades_a_stale_corpus(
        self, settings, recorded
    ):
        """The offline path: a warning, no crash, and no state transition."""
        _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        store = LibraryStore.for_settings(settings)
        [doc] = _documents(settings)
        store.set_revision_state(
            doc.content_hash,
            RevisionState(staleness=Staleness.STALE, upstream_revision="Rev. B", checked_at=FROZEN),
        )

        def offline(url: str) -> bytes:
            raise OSError("getaddrinfo failed")

        report = check_part(
            "TEST9100",
            fetcher=offline,
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        [check] = report.checks
        assert check.status == ERROR and "getaddrinfo failed" in check.message
        assert not report.ok
        [after] = _documents(settings)
        assert after.revision_state.staleness is Staleness.STALE, (
            "a failed check must not clear a warning"
        )
        assert after.revision_state.upstream_revision == "Rev. B"
        assert after.revision_state.checked_at == FROZEN
        assert "unchanged" in after.revision_state.note

    def test_an_unknown_corpus_stays_unknown_when_the_check_fails(self, settings):
        _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")

        def offline(url: str) -> bytes:
            raise OSError("network unreachable")

        check_part(
            "TEST9100", fetcher=offline, settings=settings, registry_file=reg_file, now=FROZEN
        )
        assert _documents(settings)[0].revision_state.staleness is Staleness.UNKNOWN

    def test_a_part_with_no_documents_is_a_finding_not_a_crash(self, settings, recorded):
        (settings.parts_dir / "EMPTY").mkdir(parents=True)
        report = check_part(
            "EMPTY",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=registry_path(settings.registry_dir),
            now=FROZEN,
        )
        assert report.failed and "nothing to" in report.checks[0].message

    def test_check_all_walks_every_part(self, tmp_path, settings, recorded):
        _build(settings, revision="A")
        (settings.parts_dir / "OTHER").mkdir(parents=True)
        reg_file = _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "B"))
        report = check_all(
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        assert {c.part_number for c in report.checks} == {"TEST9100", "OTHER"}

    def test_an_unrecorded_url_is_a_hard_error_in_tests(self, settings, recorded):
        """Invariant 4: the replay seam never silently reaches the network."""
        _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")  # nothing recorded
        report = check_part(
            "TEST9100",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        assert report.checks[0].status == ERROR
        assert "no recorded binary response" in report.checks[0].message

    def test_the_registry_is_never_rewritten_by_a_check(self, tmp_path, settings, recorded):
        """Asking what is upstream is not the act that verifies a URL."""
        _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        before = reg_file.read_text(encoding="utf-8")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "B"))
        check_part(
            "TEST9100",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        assert reg_file.read_text(encoding="utf-8") == before

    def test_nothing_is_written_into_the_part_document_directory(
        self, tmp_path, settings, recorded
    ):
        """The upstream bytes are read in memory and never staged on disk."""
        part_dir = _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "B"))
        before = sorted(p.name for p in (part_dir / "documents").iterdir())
        check_part(
            "TEST9100",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        assert sorted(p.name for p in (part_dir / "documents").iterdir()) == before

    def test_a_document_is_paired_with_its_registry_entry_by_identity(self):
        entry = RegistryEntry(
            part_number="P",
            document=RegistryDocument(doc_type=DocType.DATASHEET, sha256="bb" * 32),
            companions=[RegistryDocument(doc_type=DocType.REGISTER_MAP, sha256="cc" * 32)],
        )
        doc = _wrap("Rev. A", "cc" * 32, doc_type=DocType.REGISTER_MAP)
        assert registry_document_for(entry, doc).doc_type == DocType.REGISTER_MAP


# --- build stays offline -----------------------------------------------------


class TestBuildChecksNothing:
    def test_the_pipeline_never_reaches_the_revision_check(self):
        """The property that keeps a build offline by construction.

        Same shape as `test_fetch.py::TestBuildAcquiresNothing`: the build path
        may not reach the network seam directly or by importing the module that
        holds it. (A prose mention in a comment is not a call, so the guard is
        on the import and the call names.)
        """
        source = (REPO_ROOT / "src/datasheet_analyzer/pipeline.py").read_text(encoding="utf-8")
        assert "acquire.revisions" not in source
        assert "check_part" not in source and "check_all" not in source

    def test_importing_the_acquire_package_does_not_pull_in_the_check(self):
        import importlib
        import sys

        for name in [m for m in sys.modules if m.startswith("datasheet_analyzer.acquire")]:
            del sys.modules[name]
        importlib.import_module("datasheet_analyzer.acquire")
        assert "datasheet_analyzer.acquire.revisions" not in sys.modules

    def test_a_build_leaves_the_corpus_unknown_even_with_a_registry_url(self, settings):
        _register(settings, revision="Rev. A")
        _build(settings, revision="A")
        [doc] = _documents(settings)
        assert doc.revision_state.staleness is Staleness.UNKNOWN
        assert doc.revision_state.checked_at is None
        assert doc.revision_state.upstream_revision == ""


# --- unknown is not current --------------------------------------------------


class TestUnknownIsNotCurrent:
    def test_a_fresh_library_document_defaults_to_unknown(self):
        doc = LibraryDocument(source=SourceDocument(content_hash="a", path="x"))
        assert doc.revision_state.staleness is Staleness.UNKNOWN

    def test_the_footer_says_not_checked_rather_than_implying_currency(self):
        st = corpus_staleness([_wrap("Rev. A")], "P")
        footer = pack_footer(st)
        assert "not checked" in footer
        assert "current" not in footer.lower()
        assert "check-revisions" in footer

    def test_a_part_is_only_as_fresh_as_its_least_fresh_document(self):
        fresh = _wrap("Rev. A", "aa" * 32, staleness=Staleness.CURRENT)
        unchecked = _wrap("SNAU269A", "bb" * 32, doc_type=DocType.REGISTER_MAP)
        assert corpus_staleness([fresh, unchecked], "P").state is Staleness.UNKNOWN

    def test_a_part_with_no_documents_says_there_is_nothing_to_check(self):
        st = corpus_staleness([], "P")
        assert st.state is Staleness.UNKNOWN
        assert "no documents are registered" in st.note

    def test_a_project_reads_as_its_worst_member_and_names_it(self):
        good = corpus_staleness([_wrap("Rev. A", staleness=Staleness.CURRENT)], "GOOD")
        bad = corpus_staleness([_wrap("Rev. A", staleness=Staleness.STALE)], "BAD")
        worst = project_staleness([good, bad])
        assert worst.state is Staleness.STALE and worst.part == "BAD"


# --- the banner block --------------------------------------------------------


class TestTheBannerBlock:
    def test_applying_a_banner_twice_leaves_one(self):
        text = "# P - datasheet corpus\n\nbody\n"
        once = apply_index_banner(text, index_banner(corpus_staleness([], "P")))
        twice = apply_index_banner(once, index_banner(corpus_staleness([], "P")))
        assert twice.count(BANNER_BEGIN) == 1
        assert "body" in twice

    def test_a_refresh_replaces_the_previous_reading(self):
        stale = corpus_staleness(
            [_wrap("Rev. A", staleness=Staleness.STALE, upstream_revision="Rev. B")], "P"
        )
        text = apply_index_banner("# P\n", index_banner(corpus_staleness([], "P")))
        refreshed = apply_index_banner(text, index_banner(stale))
        assert "Rev. B is available upstream" in refreshed
        assert "not checked" not in refreshed

    def test_the_check_refreshes_a_built_index_in_place(self, tmp_path, settings, recorded):
        part_dir = _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "B"))
        check_part(
            "TEST9100",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        text = (part_dir / "INDEX.md").read_text(encoding="utf-8")
        assert "Rev. B is available upstream" in text
        assert "Verify before committing to silicon" in text
        assert text.count(BANNER_BEGIN) == 1, "a refresh replaces, never stacks"


# --- the CLI command ---------------------------------------------------------


class TestCheckRevisionsCli:
    def test_it_refuses_an_invocation_that_names_nothing(self, capsys):
        assert cli.main(["check-revisions"]) == 2
        assert "either a part" in capsys.readouterr().err

    def test_it_reports_a_stale_corpus_and_exits_nonzero(
        self, tmp_path, settings, recorded, monkeypatch, capsys
    ):
        _build(settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "B"))
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        monkeypatch.setattr(
            "datasheet_analyzer.extract.http.DirectBinaryFetcher",
            lambda **kw: ReplayBinaryFetcher(recorded),
        )
        assert cli.main(["check-revisions", "TEST9100"]) == 1
        captured = capsys.readouterr()
        assert "STALE" in captured.err
        assert "1 stale" in captured.out
        assert reg_file.exists()

    def test_json_output_is_machine_readable(
        self, tmp_path, settings, recorded, monkeypatch, capsys
    ):
        import json

        _build(settings, revision="A")
        _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "A"))
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        monkeypatch.setattr(
            "datasheet_analyzer.extract.http.DirectBinaryFetcher",
            lambda **kw: ReplayBinaryFetcher(recorded),
        )
        assert cli.main(["check-revisions", "--all", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["n_checked"] == 1 and payload["n_stale"] == 0
        assert payload["checks"][0]["staleness"] == "current"
        assert payload["checks"][0]["status"] == CHECKED
