"""Revision awareness + staleness surfacing (phase 7, ticket 02).

What these prove, criterion by criterion:

- **the revision parser is fixed for LMX1204** — `sniff_revision` returns
  `SNAS800B` rather than the page-1 pin name `SYSREFOUT0`, with the other
  seven committed documents asserted unchanged as a regression guard;
- **staleness is decided by the parsed revision identifier, never by a hash** —
  a fixture whose bytes differ under an *unchanged* revision must read
  `current`, and its content drift is reported distinctly, in words that never
  imply a new revision exists;
- **`dsa check-revisions` finds a stale corpus** against a recorded fixture and
  records `upstream_revision` + `revision_checked_at` on the inventory;
- **`build` performs no network revision check**, asserted two ways: the
  pipeline does not reference the module at all, and a build over a registry
  that *does* carry a URL still leaves the corpus `unknown`;
- **all four surfaces carry the warning** — `INDEX.md`, `dsa status`, the
  `dsa audit` metric and the answer-pack footer — each asserted separately and
  then all four together, because a warning present in three of them is the
  failure mode these tests exist to catch;
- **a never-checked corpus reads `unknown`, distinct from `current`**, and the
  answer footer says "revision not checked" rather than implying currency;
- **MCP responses carry the state** so a remote agent sees it too;
- **the check degrades honestly with no network**: the recorded state is left
  exactly as it was, a reason is recorded, nothing crashes, and no failed check
  can ever move a corpus from `stale` to `current`.

Hermetic by construction (invariant 4): every upstream response is a synthetic
PDF built in-test with `fitz` and served through the existing
`ReplayBinaryFetcher` seam under `example.invalid` URLs. No fixture here claims
to be a recorded response from a real vendor, because none was recorded — the
live steps are deferred to `Reports/PHASE_7_LIVE_RUN.md`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.acquire.inventory import load_inventory, save_inventory
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
from datasheet_analyzer.models import DocType, SourceDocument, Staleness
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.retrieve import Retriever, clear_index_cache
from datasheet_analyzer.staleness import (
    BANNER_BEGIN,
    apply_index_banner,
    audit_metric,
    corpus_staleness,
    index_banner,
    pack_footer,
    project_staleness,
    status_lines,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
URL = "https://example.invalid/test9100/test9100.pdf"
FROZEN = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)

#: Every document physically committed to this repo, with the revision the
#: shared lexicon must read off it. LMX1204's datasheet is the one the ticket
#: named; the other seven are the regression guard, so tightening the shape
#: cannot quietly cost a reading that already worked.
COMMITTED_DOCUMENTS = [
    ("tests/fixtures/pdf/lmx1204.pdf", "SNAS800B"),
    ("tests/fixtures/pdf/LMX1204_registermap.pdf", "SNAU269A"),
    ("tests/fixtures/pdf/lm741.pdf", "SNOSC25D"),
    ("tests/fixtures/pdf/ad9081.pdf", "Rev. 0"),
    ("tests/fixtures/pdf/hmc520a.pdf", "Rev. A"),
    ("tests/fixtures/pdf/QPA1003P.pdf", "Rev. I"),
    ("afe7950.pdf", "SBASA41E"),
    ("afe7953.pdf", "SBASAN1A"),
]


# --- fixtures ---------------------------------------------------------------


def _make_pdf(path: Path, revision: str, marker: str = "") -> bytes:
    """A tiny, readable datasheet-shaped PDF with a sniffable revision.

    `marker` changes the bytes without changing the revision — which is exactly
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


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        parts_dir=tmp_path / "parts",
        projects_dir=tmp_path / "projects",
        cache_dir=tmp_path / ".cache",
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
            document=RegistryDocument(
                doc_type=DocType.DATASHEET, url=url, revision=revision
            ),
        )
    )
    dest = registry_path(settings.registry_dir)
    save_registry(registry, dest)
    return dest


def _build(tmp_path: Path, settings: Settings, revision: str = "A") -> Path:
    """A real built corpus for TEST9100 — inventory, INDEX.md and all."""
    pdf = settings.parts_dir / "TEST9100" / "documents" / "test9100.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    _make_pdf(pdf, revision)
    build_part(pdf, part_number="TEST9100", settings=settings,
               vendor="unknown", use_llm=False)
    clear_index_cache()
    return settings.parts_dir / "TEST9100"


# --- the blocking prerequisite: the revision parser --------------------------


class TestRevisionParser:
    def test_lmx1204_reads_its_own_literature_number(self):
        """The ticket's headline defect: a pin name won over the real id."""
        assert sniff_revision(REPO_ROOT / "tests/fixtures/pdf/lmx1204.pdf") == "SNAS800B"

    @pytest.mark.parametrize("rel,expected", COMMITTED_DOCUMENTS)
    def test_every_committed_document_still_reads_its_revision(self, rel, expected):
        path = REPO_ROOT / rel
        if not path.exists():  # the two repo-root working copies are skip-guarded
            pytest.skip(f"{rel} is not present in this checkout")
        assert sniff_revision(path) == expected

    def test_a_signal_name_is_not_a_document_id(self):
        """The exact page-1 token order the ticket measured on LMX1204."""
        page = "SYSREFOUT0 SYSREFOUT1 SYSREFOUT2 SYSREFOUT3 ... SNAS800B"
        assert revision_from_texts([page]) == "SNAS800B"

    @pytest.mark.parametrize(
        "text",
        [
            "SUPPORT",       # all letters: no digit in the tail
            "SYSREF1",       # ends in a digit, not a revision letter
            "SYSREFOUT0",    # too long to be a literature number
            "SPI SDI SDO",   # ordinary three-letter signal names
        ],
    )
    def test_shapes_that_are_not_literature_numbers_read_as_nothing(self, text):
        assert revision_from_texts([text]) == ""

    def test_bytes_and_paths_read_the_same_lexicon(self, tmp_path):
        payload = _make_pdf(tmp_path / "x.pdf", "C")
        assert sniff_revision_bytes(payload) == "Rev. C"
        assert sniff_revision(tmp_path / "x.pdf") == "Rev. C"

    def test_unreadable_bytes_are_an_honest_miss_not_a_crash(self):
        assert sniff_revision_bytes(b"<html>document not found</html>") == ""


# --- the comparison rule -----------------------------------------------------


class TestComparisonIsRevisionFirst:
    def _source(self, revision: str, content_hash: str = "aa" * 32) -> SourceDocument:
        return SourceDocument(
            content_hash=content_hash,
            path="parts/TEST9100/documents/test9100.pdf",
            part_number="TEST9100",
            doc_type=DocType.DATASHEET,
            revision=revision,
        )

    def test_a_different_revision_is_stale(self, tmp_path):
        upstream = _make_pdf(tmp_path / "up.pdf", "B")
        check = compare(self._source("Rev. A"), upstream, now=FROZEN)
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
        check = compare(self._source("Rev. A"), upstream, now=FROZEN)
        assert check.state is Staleness.CURRENT
        assert check.content_drift is True
        assert check.upstream_sha256 != check.local_sha256

    def test_content_drift_is_worded_so_it_cannot_read_as_a_new_revision(self, tmp_path):
        upstream = _make_pdf(tmp_path / "up.pdf", "A", marker="regenerated")
        check = compare(self._source("Rev. A"), upstream, now=FROZEN)
        assert "regenerated, not revised" in check.message
        for forbidden in ("new revision", "available upstream", "superseded"):
            assert forbidden not in check.message

    def test_identical_bytes_are_current_with_no_drift(self, tmp_path):
        import hashlib

        upstream = _make_pdf(tmp_path / "up.pdf", "A")
        source = self._source("Rev. A", hashlib.sha256(upstream).hexdigest())
        check = compare(source, upstream, now=FROZEN)
        assert check.state is Staleness.CURRENT and check.content_drift is False

    def test_an_unreadable_upstream_document_is_unknown_not_current(self):
        check = compare(self._source("Rev. A"), b"not a pdf at all", now=FROZEN)
        assert check.state is Staleness.UNKNOWN
        assert "inconclusive" in check.message

    def test_a_corpus_with_no_revision_cannot_be_compared(self, tmp_path):
        upstream = _make_pdf(tmp_path / "up.pdf", "A")
        check = compare(self._source(""), upstream, now=FROZEN)
        assert check.state is Staleness.UNKNOWN
        assert "no revision identifier to compare" in check.message


# --- dsa check-revisions -----------------------------------------------------


class TestCheckRevisions:
    def test_a_stale_corpus_is_detected_and_recorded(self, tmp_path, settings, recorded):
        part_dir = _build(tmp_path, settings, revision="A")
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
        [source] = load_inventory(part_dir)
        assert source.staleness is Staleness.STALE
        assert source.upstream_revision == "Rev. B"
        assert source.revision_checked_at == FROZEN
        assert source.upstream_sha256

    def test_a_regenerated_document_is_current_with_drift_recorded(
        self, tmp_path, settings, recorded
    ):
        part_dir = _build(tmp_path, settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "A", marker="regenerated"))

        report = check_part(
            "TEST9100", fetcher=ReplayBinaryFetcher(recorded), settings=settings,
            registry_file=reg_file, now=FROZEN,
        )
        assert not report.stale and len(report.drifted) == 1
        [source] = load_inventory(part_dir)
        assert source.staleness is Staleness.CURRENT
        assert source.content_drift is True

    def test_an_entry_with_no_url_leaves_the_recorded_state_alone(
        self, tmp_path, settings, recorded
    ):
        part_dir = _build(tmp_path, settings, revision="A")
        reg_file = _register(settings, revision="Rev. A", url=None)
        report = check_part(
            "TEST9100", fetcher=ReplayBinaryFetcher(recorded), settings=settings,
            registry_file=reg_file, now=FROZEN,
        )
        [check] = report.checks
        assert check.status == NO_URL and "--url" in check.message
        [source] = load_inventory(part_dir)
        assert source.staleness is Staleness.UNKNOWN
        assert source.revision_checked_at is None

    def test_no_network_degrades_honestly_and_never_upgrades_a_stale_corpus(
        self, tmp_path, settings, recorded
    ):
        """The offline path: `unknown`, a warning, no crash, no transition."""
        part_dir = _build(tmp_path, settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")
        # Pin the corpus as already-known-stale, then fail the fetch.
        sources = load_inventory(part_dir)
        sources[0].staleness = Staleness.STALE
        sources[0].upstream_revision = "Rev. B"
        sources[0].revision_checked_at = FROZEN
        save_inventory(sources, part_dir)

        def offline(url: str) -> bytes:
            raise OSError("getaddrinfo failed")

        report = check_part(
            "TEST9100", fetcher=offline, settings=settings,
            registry_file=reg_file, now=FROZEN,
        )
        [check] = report.checks
        assert check.status == ERROR and "getaddrinfo failed" in check.message
        assert not report.ok
        after = load_inventory(part_dir)[0]
        assert after.staleness is Staleness.STALE, "a failed check must not clear a warning"
        assert after.upstream_revision == "Rev. B"
        assert "unchanged" in after.revision_check_note

    def test_an_unknown_corpus_stays_unknown_when_the_check_fails(
        self, tmp_path, settings, recorded
    ):
        part_dir = _build(tmp_path, settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")

        def offline(url: str) -> bytes:
            raise OSError("network unreachable")

        check_part("TEST9100", fetcher=offline, settings=settings,
                   registry_file=reg_file, now=FROZEN)
        assert load_inventory(part_dir)[0].staleness is Staleness.UNKNOWN

    def test_a_part_with_no_documents_is_a_finding_not_a_crash(self, settings, recorded):
        (settings.parts_dir / "EMPTY").mkdir(parents=True)
        report = check_part(
            "EMPTY", fetcher=ReplayBinaryFetcher(recorded), settings=settings,
            registry_file=registry_path(settings.registry_dir), now=FROZEN,
        )
        assert report.failed and "nothing to" in report.checks[0].message

    def test_check_all_walks_every_part(self, tmp_path, settings, recorded):
        _build(tmp_path, settings, revision="A")
        (settings.parts_dir / "OTHER").mkdir(parents=True)
        reg_file = _register(settings, revision="Rev. A")
        _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "B"))
        report = check_all(
            fetcher=ReplayBinaryFetcher(recorded), settings=settings,
            registry_file=reg_file, now=FROZEN,
        )
        parts = {c.part_number for c in report.checks}
        assert parts == {"TEST9100", "OTHER"}

    def test_an_unrecorded_url_is_a_hard_error_in_tests(self, tmp_path, settings, recorded):
        """Invariant 4: the replay seam never silently reaches the network."""
        _build(tmp_path, settings, revision="A")
        reg_file = _register(settings, revision="Rev. A")  # nothing recorded
        report = check_part(
            "TEST9100", fetcher=ReplayBinaryFetcher(recorded), settings=settings,
            registry_file=reg_file, now=FROZEN,
        )
        assert report.checks[0].status == ERROR
        assert "no recorded binary response" in report.checks[0].message

    def test_a_document_is_paired_with_its_registry_entry_by_identity(self):
        entry = RegistryEntry(
            part_number="P",
            document=RegistryDocument(doc_type=DocType.DATASHEET, sha256="bb" * 32),
            companions=[RegistryDocument(doc_type=DocType.REGISTER_MAP, sha256="cc" * 32)],
        )
        source = SourceDocument(
            content_hash="cc" * 32, path="x.pdf", doc_type=DocType.REGISTER_MAP
        )
        assert registry_document_for(entry, source).doc_type == DocType.REGISTER_MAP


# --- build stays offline -----------------------------------------------------


class TestBuildChecksNothing:
    def test_the_pipeline_never_reaches_the_revision_check(self):
        """The property that keeps a build offline by construction.

        Same shape as `test_fetch.py::TestBuildAcquiresNothing`: the build path
        may not reach the network seam directly or by importing the module that
        holds it. (A prose mention in a comment is not a call, so the guard is
        on the import and the call names.)
        """
        source = (REPO_ROOT / "src/datasheet_analyzer/pipeline.py").read_text(
            encoding="utf-8"
        )
        assert "acquire.revisions" not in source
        assert "check_part" not in source and "check_all" not in source

    def test_importing_the_acquire_package_does_not_pull_in_the_check(self):
        import importlib
        import sys

        for name in [m for m in sys.modules if m.startswith("datasheet_analyzer.acquire")]:
            del sys.modules[name]
        importlib.import_module("datasheet_analyzer.acquire")
        assert "datasheet_analyzer.acquire.revisions" not in sys.modules

    def test_a_build_leaves_the_corpus_unknown_even_with_a_registry_url(
        self, tmp_path, settings
    ):
        _register(settings, revision="Rev. A")
        part_dir = _build(tmp_path, settings, revision="A")
        [source] = load_inventory(part_dir)
        assert source.staleness is Staleness.UNKNOWN
        assert source.revision_checked_at is None
        assert source.upstream_revision == ""


# --- unknown is not current --------------------------------------------------


class TestUnknownIsNotCurrent:
    def test_a_fresh_source_document_defaults_to_unknown(self):
        assert SourceDocument(content_hash="a", path="x").staleness is Staleness.UNKNOWN

    def test_the_footer_says_not_checked_rather_than_implying_currency(self, tmp_path):
        st = corpus_staleness([SourceDocument(content_hash="a", path="x.pdf")], "P")
        footer = pack_footer(st)
        assert "not checked" in footer
        assert "current" not in footer.lower()
        assert "check-revisions" in footer

    def test_a_part_is_only_as_fresh_as_its_least_fresh_document(self):
        fresh = SourceDocument(
            content_hash="a", path="a.pdf", doc_type=DocType.DATASHEET,
            staleness=Staleness.CURRENT,
        )
        unchecked = SourceDocument(
            content_hash="b", path="b.pdf", doc_type=DocType.REGISTER_MAP
        )
        assert corpus_staleness([fresh, unchecked], "P").state is Staleness.UNKNOWN

    def test_a_project_reads_as_its_worst_member_and_names_it(self):
        current = corpus_staleness(
            [SourceDocument(content_hash="a", path="a.pdf", staleness=Staleness.CURRENT)],
            "GOOD",
        )
        stale = corpus_staleness(
            [SourceDocument(content_hash="b", path="b.pdf", staleness=Staleness.STALE)],
            "BAD",
        )
        worst = project_staleness([current, stale])
        assert worst.state is Staleness.STALE and worst.part == "BAD"


# --- the four surfaces -------------------------------------------------------


def _make_stale(part_dir: Path, settings: Settings, recorded: Path, tmp_path: Path):
    """Run a real check that finds the corpus stale, and return its reading."""
    reg_file = _register(settings, revision="Rev. A")
    _record(recorded, URL, _make_pdf(tmp_path / "up.pdf", "B"))
    check_part("TEST9100", fetcher=ReplayBinaryFetcher(recorded), settings=settings,
               registry_file=reg_file, now=FROZEN)
    clear_index_cache()
    return corpus_staleness(load_inventory(part_dir), "TEST9100")


class TestTheFourSurfaces:
    """One warning, four places. A test per surface, then all four at once."""

    def test_index_md_carries_the_banner(self, tmp_path, settings, recorded):
        part_dir = _build(tmp_path, settings, revision="A")
        assert "Revision not checked" in (part_dir / "INDEX.md").read_text(encoding="utf-8")
        _make_stale(part_dir, settings, recorded, tmp_path)
        text = (part_dir / "INDEX.md").read_text(encoding="utf-8")
        assert "Rev. B is available upstream" in text
        assert "Verify before committing to silicon" in text
        assert text.count(BANNER_BEGIN) == 1, "a refresh replaces, never stacks"

    def test_dsa_status_reports_it(self, tmp_path, settings, recorded, monkeypatch, capsys):
        part_dir = _build(tmp_path, settings, revision="A")
        _make_stale(part_dir, settings, recorded, tmp_path)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        assert cli.main(["status"]) == 0
        out = capsys.readouterr().out
        assert "revision: stale" in out
        assert "Rev. B is available upstream" in out

    def test_the_audit_metric_carries_it(self, tmp_path, settings, recorded):
        """`dsa audit` (ticket 05) renders this metric; the field lands here."""
        part_dir = _build(tmp_path, settings, revision="A")
        st = _make_stale(part_dir, settings, recorded, tmp_path)
        metric = audit_metric(st)
        assert metric["metric"] == "revision freshness"
        assert metric["state"] == "stale" and metric["grade_input"] == "stale"
        assert metric["upstream_revision"] == "Rev. B"
        assert metric["checked_at"] == FROZEN.isoformat()
        assert "available upstream" in metric["banner"]

    def test_the_answer_pack_footer_carries_it(self, tmp_path, settings, recorded):
        part_dir = _build(tmp_path, settings, revision="A")
        _make_stale(part_dir, settings, recorded, tmp_path)
        pack = Retriever.for_part(part_dir).ask("supply voltage", budget=3000)
        assert pack.staleness == "stale"
        assert "Rev. B is available upstream" in pack.markdown
        assert "Verify before committing to silicon" in pack.markdown
        assert pack.as_dict()["staleness"] == "stale"

    def test_all_four_surfaces_at_once(self, tmp_path, settings, recorded, monkeypatch, capsys):
        """The catcher: a warning present in only three of four is the defect."""
        part_dir = _build(tmp_path, settings, revision="A")
        st = _make_stale(part_dir, settings, recorded, tmp_path)
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        cli.main(["status"])
        surfaces = {
            "INDEX.md": (part_dir / "INDEX.md").read_text(encoding="utf-8"),
            "dsa status": capsys.readouterr().out,
            "dsa audit": audit_metric(st)["banner"],
            "answer pack": Retriever.for_part(part_dir).ask("supply", budget=3000).markdown,
        }
        missing = [name for name, text in surfaces.items() if "Rev. B" not in text]
        assert not missing, f"staleness missing from: {missing}"

    def test_an_unchecked_corpus_says_so_on_every_surface(self, tmp_path, settings):
        part_dir = _build(tmp_path, settings, revision="A")
        st = corpus_staleness(load_inventory(part_dir), "TEST9100")
        pack = Retriever.for_part(part_dir).ask("supply voltage", budget=3000)
        texts = [
            (part_dir / "INDEX.md").read_text(encoding="utf-8"),
            "\n".join(status_lines(st)),
            audit_metric(st)["banner"],
            pack.markdown,
        ]
        assert all("not checked" in t for t in texts)
        assert st.state is Staleness.UNKNOWN and pack.staleness == "unknown"


class TestTheFooterIsReservedTail:
    def test_a_tiny_budget_never_removes_the_staleness_warning(
        self, tmp_path, settings, recorded
    ):
        """A budget may cost rows and prose; it may not cost this warning."""
        part_dir = _build(tmp_path, settings, revision="A")
        _make_stale(part_dir, settings, recorded, tmp_path)
        retriever = Retriever.for_part(part_dir)
        for budget in (20, 60, 200, 3000):
            pack = retriever.ask("supply voltage", budget=budget)
            assert "available upstream" in pack.markdown, budget


class TestTheBannerBlock:
    def test_applying_a_banner_twice_leaves_one(self):
        text = "# P — datasheet corpus\n\nbody\n"
        once = apply_index_banner(text, index_banner(corpus_staleness([], "P")))
        twice = apply_index_banner(once, index_banner(corpus_staleness([], "P")))
        assert twice.count(BANNER_BEGIN) == 1
        assert "body" in twice

    def test_a_refresh_replaces_the_previous_reading(self):
        stale = corpus_staleness(
            [SourceDocument(content_hash="a", path="a.pdf", staleness=Staleness.STALE,
                            revision="Rev. A", upstream_revision="Rev. B")],
            "P",
        )
        text = apply_index_banner("# P\n", index_banner(corpus_staleness([], "P")))
        refreshed = apply_index_banner(text, index_banner(stale))
        assert "Rev. B is available upstream" in refreshed
        assert "not checked" not in refreshed


# --- the CLI command ---------------------------------------------------------


class TestCheckRevisionsCli:
    def test_it_refuses_an_invocation_that_names_nothing(self, capsys):
        assert cli.main(["check-revisions"]) == 2
        assert "either a part" in capsys.readouterr().err

    def test_it_reports_a_stale_corpus_and_exits_nonzero(
        self, tmp_path, settings, recorded, monkeypatch, capsys
    ):
        _build(tmp_path, settings, revision="A")
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

        _build(tmp_path, settings, revision="A")
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


# --- MCP ---------------------------------------------------------------------


class TestMcpCarriesStaleness:
    def test_every_response_envelope_declares_the_state(self):
        """SDK-free: the declared contract itself must carry the field."""
        from datasheet_analyzer.mcp_server.responses import SCHEMAS, envelope

        for tool, schema in SCHEMAS.items():
            assert "staleness" in schema["required"], tool
            assert schema["properties"]["staleness"]["enum"] == [
                "current", "stale", "unknown", "",
            ]
        assert envelope("ask", max_tokens=100)["staleness"] == ""
        assert envelope("ask", max_tokens=100, staleness="stale")["staleness"] == "stale"

    def test_a_scoped_response_reports_the_corpus_state(self, tmp_path, settings, recorded):
        pytest.importorskip("mcp", reason="needs the optional [mcp] extra")
        from mcp_session import call, payload_of

        from datasheet_analyzer.mcp_server import server as S

        part_dir = _build(tmp_path, settings, revision="A")
        _make_stale(part_dir, settings, recorded, tmp_path)
        server = S.build_server(settings)
        assert payload_of(call(server, "get_index", part="TEST9100"))["staleness"] == "stale"
        found = payload_of(call(server, "find_spec", part="TEST9100", symbol="TJ"))
        assert found["staleness"] == "stale"
        listed = payload_of(call(server, "list_parts"))
        assert listed["parts"][0]["staleness"] == "stale"
