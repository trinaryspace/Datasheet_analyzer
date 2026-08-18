"""Document registry + `dsa fetch` (phase 7, ticket 01).

What these prove, criterion by criterion:

- `dsa fetch PART` resolves the registry, downloads, **verifies sha256**,
  registers into the part's `sources.json`, and the result builds — the last
  step is asserted by actually running `build_part` on what was fetched, so
  "ready for `dsa build`" is measured rather than claimed;
- a sha256 mismatch **warns loudly and stops**: no file is written, nothing is
  registered, the registry is untouched, and the message names the likely
  cause (a new upstream revision, with both revisions in it).
  `--accept-new-revision` is the reviewed path and records the new hash *and*
  the revision the new bytes actually report;
- a registry miss errors with a message naming `--url`, and nothing in the
  module composes a URL out of a part number;
- `--url` writes a well-formed entry carrying the **fetched** revision and
  hash, `url_verified: true` (bytes arrived) and a real `retrieved_at`;
- `--project` fetches only what is missing and reports every skip;
- every test drives the *existing* `ReplayBinaryFetcher` seam, and an
  unrecorded URL is a hard error (invariant 4);
- the checked-in seed registry ships non-empty, agrees byte for byte with
  `scripts/seed_datasheet_registry.py`, and every sha256 in it still matches
  the repo file it names — so the registry can never drift away from the
  bytes it describes;
- **`dsa build` acquires nothing**: the pipeline does not reference the fetch
  module at all, which is the one property that keeps builds offline by
  construction.

Hermetic by construction: the replay cache is built in-test from synthetic
PDFs (invariant 4's `fitz` clause) under URLs on `example.invalid`. No fixture
here claims to be a recorded response from a real vendor, because no such
response was recorded — see `Reports/PHASE_7_LIVE_RUN.md` for the live steps
this defers to the repo owner.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.acquire.fetch import (
    ERROR,
    FETCHED,
    MISMATCH,
    NO_URL,
    SKIPPED,
    destination_name,
    fetch_part,
    fetch_project,
)
from datasheet_analyzer.acquire.inventory import load_inventory
from datasheet_analyzer.acquire.registry import (
    DocumentRegistry,
    RegistryDocument,
    RegistryEntry,
    RegistryMiss,
    load_registry,
    registry_path,
    registry_yaml,
    resolve,
    save_registry,
    ti_lit_url,
)
from datasheet_analyzer.config import Settings
from datasheet_analyzer.extract.http import ReplayBinaryFetcher, binary_cache_name
from datasheet_analyzer.models import DocType

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

URL_A = "https://example.invalid/test9000/test9000.pdf"
URL_B = "https://example.invalid/test9001/test9001.pdf"
FROZEN = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)


def _make_pdf(path: Path, revision: str, marker: str = "") -> bytes:
    """A tiny, readable datasheet-shaped PDF with a sniffable revision."""
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), f"TEST9000 Quad RF transceiver. {marker}")
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
def recorded(tmp_path: Path) -> Path:
    """A replay cache in the on-disk format `ReplayBinaryFetcher` reads.

    Same mechanism as `tests/fixtures/recorded_http_bin/`, populated in-test so
    no fabricated vendor response is ever committed.
    """
    cache = tmp_path / "recorded_http_bin"
    cache.mkdir()
    return cache


def _record(cache: Path, url: str, payload: bytes) -> str:
    (cache / binary_cache_name(url)).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        parts_dir=tmp_path / "parts",
        projects_dir=tmp_path / "projects",
        cache_dir=tmp_path / ".cache",
        registry_dir=tmp_path / "registry",
    ).resolve()


@pytest.fixture
def reg_file(settings: Settings) -> Path:
    return registry_path(settings.registry_dir)


class TestRegistryFile:
    def test_missing_file_is_an_empty_registry_not_an_error(self, tmp_path):
        assert load_registry(tmp_path / "nope.yaml").parts == {}

    def test_round_trip_is_deterministic(self, reg_file):
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="ZZZ1",
                vendor="ti",
                document=RegistryDocument(url=URL_A, revision="Rev. A", sha256="ab" * 32),
            )
        )
        registry.put(RegistryEntry(part_number="AAA1", vendor="adi"))
        save_registry(registry, reg_file)
        first = reg_file.read_text(encoding="utf-8")
        reloaded = load_registry(reg_file)
        assert registry_yaml(reloaded) == first
        # sorted by part, so a fetch on two machines produces the same diff
        assert first.index("AAA1") < first.index("ZZZ1")

    def test_absent_url_is_null_with_a_reason_not_an_empty_string(self, reg_file):
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="AAA1",
                document=RegistryDocument(url=None, url_reason="nobody supplied one"),
            )
        )
        save_registry(registry, reg_file)
        text = reg_file.read_text(encoding="utf-8")
        assert "url: null" in text
        assert "nobody supplied one" in text

    def test_ti_lit_url_needs_a_literature_number(self):
        assert ti_lit_url("SBASA41E") == "https://www.ti.com/lit/ds/sbasa41e/sbasa41e.pdf"
        with pytest.raises(ValueError):
            ti_lit_url("   ")


class TestRegistryMiss:
    def test_resolve_miss_names_the_url_flag(self):
        with pytest.raises(RegistryMiss) as exc:
            resolve(DocumentRegistry(), "NOSUCHPART")
        message = str(exc.value)
        assert "--url" in message
        assert "NOSUCHPART" in message
        assert "never guesses" in message

    def test_miss_never_invents_a_url(self):
        """The failure path must produce no URL at all — not even a plausible one."""
        with pytest.raises(RegistryMiss) as exc:
            resolve(DocumentRegistry(), "AFE9999")
        assert "http" not in str(exc.value).replace("<URL>", "")

    def test_known_part_unknown_doc_type_is_also_a_miss(self):
        registry = DocumentRegistry()
        registry.put(RegistryEntry(part_number="P1", document=RegistryDocument(url=URL_A)))
        with pytest.raises(RegistryMiss) as exc:
            resolve(registry, "P1", doc_type=DocType.ERRATA)
        assert "--url" in str(exc.value)
        assert "--doc-type errata" in str(exc.value)

    def test_fetch_part_miss_raises_rather_than_fetching_anything(
        self, settings, recorded, reg_file
    ):
        fetcher = ReplayBinaryFetcher(recorded)
        with pytest.raises(RegistryMiss):
            fetch_part("NOSUCHPART", fetcher=fetcher, settings=settings, registry_file=reg_file)


class TestFetchHappyPath:
    def test_fetch_verifies_registers_and_is_ready_to_build(
        self, tmp_path, settings, recorded, reg_file
    ):
        payload = _make_pdf(tmp_path / "src.pdf", "A")
        sha = _record(recorded, URL_A, payload)
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000",
                vendor="unknown",
                document=RegistryDocument(
                    url=URL_A, revision="Rev. A", sha256=sha, sha256_origin="local_file:x"
                ),
            )
        )
        save_registry(registry, reg_file)

        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            vendor="unknown",
            now=FROZEN,
        )
        assert report.ok
        [doc] = report.documents
        assert doc.status == FETCHED
        assert doc.sha256 == sha and doc.expected_sha256 == sha
        assert doc.revision == "Rev. A"
        assert doc.path == settings.parts_dir / "TEST9000" / "documents" / "test9000.pdf"
        assert doc.path.read_bytes() == payload

        inventory = load_inventory(settings.parts_dir / "TEST9000")
        assert [s.content_hash for s in inventory] == [sha]
        assert Path(inventory[0].path) == doc.path
        assert inventory[0].doc_type == DocType.DATASHEET

        # "ready for dsa build" — measured, not asserted.
        from datasheet_analyzer.pipeline import build_part

        result = build_part(
            doc.path, part_number="TEST9000", settings=settings, use_llm=False
        )
        assert (result.part_dir / "INDEX.md").exists()

    def test_fetch_records_what_happened_in_the_registry(
        self, tmp_path, settings, recorded, reg_file
    ):
        payload = _make_pdf(tmp_path / "src.pdf", "A")
        sha = _record(recorded, URL_A, payload)
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000",
                document=RegistryDocument(url=URL_A, url_verified=False, sha256=sha),
            )
        )
        save_registry(registry, reg_file)

        fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        entry = load_registry(reg_file).get("TEST9000")
        assert entry.document.url_verified is True  # bytes actually arrived
        assert entry.document.retrieved_at == FROZEN
        assert entry.document.sha256_origin == f"fetch:{URL_A}"
        assert entry.document.filename == "test9000.pdf"

    def test_an_entry_with_no_url_reports_its_reason_and_the_flag(
        self, settings, recorded, reg_file
    ):
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="HMC520A",
                document=RegistryDocument(
                    url=None, url_reason="no adi document-URL pattern is encoded here"
                ),
            )
        )
        save_registry(registry, reg_file)
        report = fetch_part(
            "HMC520A",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
        )
        assert not report.ok
        [doc] = report.documents
        assert doc.status == NO_URL
        assert "no adi document-URL pattern is encoded here" in doc.message
        assert "--url" in doc.message

    def test_a_part_with_companions_fetches_both(
        self, tmp_path, settings, recorded, reg_file
    ):
        main = _make_pdf(tmp_path / "main.pdf", "A")
        comp = _make_pdf(tmp_path / "comp.pdf", "B", marker="register map")
        sha_main = _record(recorded, URL_A, main)
        sha_comp = _record(recorded, URL_B, comp)
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000",
                document=RegistryDocument(url=URL_A, sha256=sha_main),
                companions=[
                    RegistryDocument(
                        doc_type=DocType.REGISTER_MAP, url=URL_B, sha256=sha_comp
                    )
                ],
            )
        )
        save_registry(registry, reg_file)
        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        assert report.ok and len(report.fetched) == 2
        kinds = {s.doc_type for s in load_inventory(settings.parts_dir / "TEST9000")}
        assert kinds == {DocType.DATASHEET, DocType.REGISTER_MAP}


class TestHashMismatch:
    @pytest.fixture
    def drifted(self, tmp_path, settings, recorded, reg_file):
        """The registry records revision A's hash; the URL now serves revision B."""
        _make_pdf(tmp_path / "a.pdf", "A")
        old_sha = hashlib.sha256((tmp_path / "a.pdf").read_bytes()).hexdigest()
        new_payload = _make_pdf(tmp_path / "b.pdf", "B", marker="new silicon")
        new_sha = _record(recorded, URL_A, new_payload)
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000",
                document=RegistryDocument(
                    url=URL_A,
                    revision="Rev. A",
                    sha256=old_sha,
                    sha256_origin="local_file:a.pdf",
                ),
            )
        )
        save_registry(registry, reg_file)
        return old_sha, new_sha

    def test_mismatch_warns_loudly_and_stops(self, drifted, settings, recorded, reg_file):
        old_sha, new_sha = drifted
        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        assert not report.ok
        [doc] = report.documents
        assert doc.status == MISMATCH
        assert doc.expected_sha256 == old_sha and doc.sha256 == new_sha
        # names the likely cause, in the document's own words
        assert "NEW UPSTREAM REVISION" in doc.message
        assert "Rev. A" in doc.message and "Rev. B" in doc.message
        assert "--accept-new-revision" in doc.message

    def test_mismatch_writes_nothing_and_registers_nothing(
        self, drifted, settings, recorded, reg_file
    ):
        old_sha, _ = drifted
        before = reg_file.read_text(encoding="utf-8")
        fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        docs_dir = settings.parts_dir / "TEST9000" / "documents"
        assert list(docs_dir.glob("*")) == []  # not even a staged leftover
        assert load_inventory(settings.parts_dir / "TEST9000") == []
        assert reg_file.read_text(encoding="utf-8") == before
        assert load_registry(reg_file).get("TEST9000").document.sha256 == old_sha

    def test_accept_new_revision_records_the_new_hash_and_revision(
        self, drifted, settings, recorded, reg_file
    ):
        _old_sha, new_sha = drifted
        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            accept_new_revision=True,
            now=FROZEN,
        )
        assert report.ok
        [doc] = report.documents
        assert doc.status == FETCHED
        assert "a new upstream revision" in doc.message
        entry = load_registry(reg_file).get("TEST9000")
        assert entry.document.sha256 == new_sha
        assert entry.document.revision == "Rev. B"  # what the new bytes report
        assert entry.document.retrieved_at == FROZEN
        assert doc.path.exists()

    def test_an_unchanged_revision_is_never_reported_as_a_new_one(
        self, tmp_path, settings, recorded, reg_file
    ):
        """The measured TI case (ticket note, repo owner, with network): a
        vendor regenerates the package-materials addendum on every download, so
        the bytes move daily while the revision identifier does not. Asserting
        a new revision there sends a designer looking for a changelog that does
        not exist — and trains them to click past the warning that matters."""
        _make_pdf(tmp_path / "a.pdf", "A")
        old_sha = hashlib.sha256((tmp_path / "a.pdf").read_bytes()).hexdigest()
        # Same printed revision, different bytes.
        _record(recorded, URL_A, _make_pdf(tmp_path / "b.pdf", "A", marker="regenerated"))
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000",
                document=RegistryDocument(
                    url=URL_A,
                    revision="Rev. A",
                    sha256=old_sha,
                    sha256_origin="local_file:a.pdf",
                ),
            )
        )
        save_registry(registry, reg_file)
        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        [doc] = report.documents
        assert doc.status == MISMATCH
        assert "NOT evidence of a new revision" in doc.message
        assert "NEW UPSTREAM REVISION" not in doc.message
        assert "regenerates" in doc.message  # names the cause it can support

    def test_accepting_an_unchanged_revision_says_the_revision_did_not_move(
        self, tmp_path, settings, recorded, reg_file
    ):
        _make_pdf(tmp_path / "a.pdf", "A")
        old_sha = hashlib.sha256((tmp_path / "a.pdf").read_bytes()).hexdigest()
        _record(recorded, URL_A, _make_pdf(tmp_path / "b.pdf", "A", marker="regenerated"))
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000",
                document=RegistryDocument(url=URL_A, revision="Rev. A", sha256=old_sha),
            )
        )
        save_registry(registry, reg_file)
        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            accept_new_revision=True,
            now=FROZEN,
        )
        [doc] = report.documents
        assert doc.status == FETCHED
        assert "revision identifier is unchanged" in doc.message
        assert load_registry(reg_file).get("TEST9000").document.revision == "Rev. A"

    def test_an_unknown_recorded_revision_asserts_nothing(
        self, tmp_path, settings, recorded, reg_file
    ):
        _record(recorded, URL_A, _make_pdf(tmp_path / "b.pdf", "B"))
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000",
                document=RegistryDocument(url=URL_A, revision="", sha256="ab" * 32),
            )
        )
        save_registry(registry, reg_file)
        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        [doc] = report.documents
        assert doc.status == MISMATCH
        assert "nothing here says whether the revision moved" in doc.message
        assert "NEW UPSTREAM REVISION" not in doc.message

    def test_a_matching_hash_is_never_reported_as_accepted(
        self, tmp_path, settings, recorded, reg_file
    ):
        payload = _make_pdf(tmp_path / "src.pdf", "A")
        sha = _record(recorded, URL_A, payload)
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000", document=RegistryDocument(url=URL_A, sha256=sha)
            )
        )
        save_registry(registry, reg_file)
        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            accept_new_revision=True,
            now=FROZEN,
        )
        assert report.documents[0].message == ""


class TestUrlGrowsTheRegistry:
    def test_url_writes_a_well_formed_entry_with_the_fetched_revision_and_hash(
        self, tmp_path, settings, recorded, reg_file
    ):
        payload = _make_pdf(tmp_path / "src.pdf", "C")
        sha = _record(recorded, URL_A, payload)
        report = fetch_part(
            "NEWPART",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            url=URL_A,
            now=FROZEN,
        )
        assert report.ok
        entry = load_registry(reg_file).get("NEWPART")
        assert entry is not None
        assert entry.document.url == URL_A
        assert entry.document.url_verified is True
        assert entry.document.revision == "Rev. C"
        assert entry.document.sha256 == sha
        assert entry.document.sha256_origin == f"fetch:{URL_A}"
        assert entry.document.retrieved_at == FROZEN
        assert entry.document.doc_type == DocType.DATASHEET
        assert entry.vendor  # pinned from the document, not left blank

    def test_url_with_a_doc_type_lands_as_a_companion(
        self, tmp_path, settings, recorded, reg_file
    ):
        main = _make_pdf(tmp_path / "main.pdf", "A")
        comp = _make_pdf(tmp_path / "comp.pdf", "B", marker="regs")
        _record(recorded, URL_A, main)
        _record(recorded, URL_B, comp)
        fetch_part(
            "NEWPART",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            url=URL_A,
            now=FROZEN,
        )
        fetch_part(
            "NEWPART",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            url=URL_B,
            doc_type=DocType.REGISTER_MAP,
            now=FROZEN,
        )
        entry = load_registry(reg_file).get("NEWPART")
        assert entry.document.url == URL_A
        assert [c.url for c in entry.companions] == [URL_B]
        assert entry.companions[0].doc_type == DocType.REGISTER_MAP

    def test_a_failed_url_fetch_leaves_no_half_written_entry(
        self, settings, recorded, reg_file
    ):
        report = fetch_part(
            "NEWPART",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            url="https://example.invalid/never-recorded.pdf",
        )
        assert not report.ok
        assert report.documents[0].status == ERROR
        assert not reg_file.exists()


class TestHermeticFetchSeam:
    def test_an_unrecorded_url_is_a_hard_error(self, settings, recorded, reg_file):
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000",
                document=RegistryDocument(url="https://example.invalid/absent.pdf"),
            )
        )
        save_registry(registry, reg_file)
        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
        )
        assert report.documents[0].status == ERROR
        assert "no recorded binary response" in report.documents[0].message

    def test_unreadable_bytes_are_a_finding_not_a_corpus(
        self, settings, recorded, reg_file
    ):
        _record(recorded, URL_A, b"not a pdf at all")
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(part_number="TEST9000", document=RegistryDocument(url=URL_A))
        )
        save_registry(registry, reg_file)
        report = fetch_part(
            "TEST9000",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
        )
        assert report.documents[0].status == ERROR
        assert "not a readable PDF" in report.documents[0].message
        assert load_inventory(settings.parts_dir / "TEST9000") == []
        assert list((settings.parts_dir / "TEST9000" / "documents").glob("*")) == []


class TestDestinationNaming:
    def test_url_basename_wins_and_is_sanitized(self):
        doc = RegistryDocument(url="https://example.invalid/a b/../sbasa41e.pdf")
        assert destination_name(doc, "AFE7950") == "sbasa41e.pdf"

    def test_a_url_with_no_usable_basename_falls_back_to_the_part(self):
        doc = RegistryDocument(url="https://example.invalid/", doc_type=DocType.ERRATA)
        assert destination_name(doc, "AFE7950") == "AFE7950_errata.pdf"

    def test_a_non_pdf_basename_gains_the_suffix_every_backend_reads(self):
        doc = RegistryDocument(url="https://example.invalid/lit/gpn/afe7950")
        assert destination_name(doc, "AFE7950") == "afe7950.pdf"


class TestFetchProject:
    @pytest.fixture
    def board(self, tmp_path, settings, recorded, reg_file):
        from datasheet_analyzer.models import Project, ProjectMember
        from datasheet_analyzer.projects import save_project

        present = _make_pdf(tmp_path / "present.pdf", "A")
        missing = _make_pdf(tmp_path / "missing.pdf", "B", marker="second part")
        sha_present = _record(recorded, URL_A, present)
        sha_missing = _record(recorded, URL_B, missing)

        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="PRESENT",
                document=RegistryDocument(url=URL_A, sha256=sha_present),
            )
        )
        registry.put(
            RegistryEntry(
                part_number="MISSING",
                document=RegistryDocument(url=URL_B, sha256=sha_missing),
            )
        )
        save_registry(registry, reg_file)

        save_project(
            Project(
                name="rf-frontend",
                parts=[
                    ProjectMember(part_number="PRESENT"),
                    ProjectMember(part_number="MISSING"),
                    ProjectMember(part_number="UNKNOWNPART"),
                ],
            ),
            settings.projects_dir,
        )
        # PRESENT is already onboarded.
        fetch_part(
            "PRESENT",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        return sha_present, sha_missing

    def test_project_fetches_only_what_is_missing_and_reports_the_skip(
        self, board, settings, recorded, reg_file
    ):
        report = fetch_project(
            "rf-frontend",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        by_part = {d.part_number: d for d in report.documents}
        assert by_part["PRESENT"].status == SKIPPED
        assert "already registered" in by_part["PRESENT"].message
        assert by_part["MISSING"].status == FETCHED
        assert by_part["MISSING"].path.exists()

    def test_a_part_the_registry_does_not_know_is_reported_not_fatal(
        self, board, settings, recorded, reg_file
    ):
        report = fetch_project(
            "rf-frontend",
            fetcher=ReplayBinaryFetcher(recorded),
            settings=settings,
            registry_file=reg_file,
            now=FROZEN,
        )
        by_part = {d.part_number: d for d in report.documents}
        assert by_part["UNKNOWNPART"].status == NO_URL
        assert "--url" in by_part["UNKNOWNPART"].message
        assert not report.ok  # the run still fails; it just does not abort
        assert by_part["MISSING"].status == FETCHED  # the others still arrived


@pytest.fixture(scope="module")
def seeded() -> DocumentRegistry:
    """The registry as it ships — the checked-in packaged file, not a tmp one."""
    return load_registry(registry_path())


class TestSeedRegistry:
    """The checked-in registry ships non-empty and describes real bytes."""

    def test_registry_ships_non_empty_and_covers_the_existing_parts(self, seeded):
        assert set(seeded.parts) >= {
            "AFE7950", "AFE7953", "AD9081", "LM741", "QPA1003P", "HMC520A",
        }

    def test_every_recorded_sha256_matches_the_file_it_names(self, seeded):
        checked = 0
        for part, entry in seeded.parts.items():
            for doc in entry.documents:
                assert doc.sha256, f"{part} {doc.doc_type.value} records no sha256"
                assert doc.sha256_origin.startswith("local_file:"), part
                rel = doc.sha256_origin.split(":", 1)[1]
                path = REPO_ROOT / rel
                assert path.exists(), f"{part}: {rel} is not in this repo"
                assert hashlib.sha256(path.read_bytes()).hexdigest() == doc.sha256
                checked += 1
        assert checked >= 7

    def test_no_seed_entry_claims_a_verified_url_or_a_retrieval_date(self, seeded):
        """Nothing was fetched to produce this file, so nothing may say it was."""
        for part, entry in seeded.parts.items():
            for doc in entry.documents:
                assert doc.url_verified is False, part
                assert doc.retrieved_at is None, part

    def test_every_url_is_derived_by_a_named_rule_from_a_parsed_literature_number(
        self, seeded
    ):
        for part, entry in seeded.parts.items():
            for doc in entry.documents:
                if doc.url is None:
                    continue
                assert doc.url_derivation.startswith("ti_lit_ds("), part
                lit = doc.url_derivation[len("ti_lit_ds("):-1]
                assert lit == doc.revision, part  # the number actually parsed
                assert doc.url == ti_lit_url(lit), part

    def test_every_missing_url_records_why(self, seeded):
        for part, entry in seeded.parts.items():
            for doc in entry.documents:
                if doc.url is None:
                    assert doc.url_reason, part

    def test_the_checked_in_file_is_what_the_seed_script_renders(self):
        import sys

        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        try:
            from seed_datasheet_registry import build_registry
        finally:
            sys.path.pop(0)
        rendered = registry_yaml(build_registry())
        assert registry_path().read_text(encoding="utf-8") == rendered


class TestBuildAcquiresNothing:
    def test_the_pipeline_never_reaches_the_fetch_module(self):
        """Builds stay offline by construction: `fetch` is the only command
        that may acquire a document, and nothing on the build path may reach
        it, directly or by importing the package that holds it."""
        source = (
            REPO_ROOT / "src" / "datasheet_analyzer" / "pipeline.py"
        ).read_text(encoding="utf-8")
        assert "acquire.fetch" not in source
        assert "fetch_part" not in source and "fetch_project" not in source

    def test_acquire_package_import_does_not_pull_in_the_fetch_seam(self):
        import importlib
        import sys

        for name in [m for m in sys.modules if m.startswith("datasheet_analyzer.acquire")]:
            del sys.modules[name]
        importlib.import_module("datasheet_analyzer.acquire")
        assert "datasheet_analyzer.acquire.fetch" not in sys.modules


class TestFetchCli:
    @pytest.fixture
    def wired(self, settings, monkeypatch) -> Settings:
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        return settings

    @pytest.fixture
    def wired_fetcher(self, recorded, monkeypatch):
        monkeypatch.setattr(
            "datasheet_analyzer.extract.http.CachingBinaryFetcher",
            lambda *a, **kw: ReplayBinaryFetcher(recorded),
        )

    def test_neither_part_nor_project_is_a_usage_error(self, wired, capsys):
        assert cli.main(["fetch"]) == 2
        assert "either a part" in capsys.readouterr().err

    def test_part_and_project_together_is_a_usage_error(self, wired, capsys):
        assert cli.main(["fetch", "AFE7950", "--project", "rf"]) == 2
        assert "not both" in capsys.readouterr().err

    def test_url_without_a_part_is_a_usage_error(self, wired, capsys):
        assert cli.main(["fetch", "--url", URL_A]) == 2
        assert "--part" in capsys.readouterr().err

    def test_registry_miss_exits_one_and_names_the_flag(
        self, wired, wired_fetcher, capsys
    ):
        assert cli.main(["fetch", "NOSUCHPART"]) == 1
        assert "--url" in capsys.readouterr().err

    def test_fetch_prints_the_build_command_it_enables(
        self, tmp_path, wired, wired_fetcher, recorded, reg_file, capsys
    ):
        payload = _make_pdf(tmp_path / "src.pdf", "A")
        sha = _record(recorded, URL_A, payload)
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000", document=RegistryDocument(url=URL_A, sha256=sha)
            )
        )
        save_registry(registry, reg_file)
        assert cli.main(["fetch", "TEST9000"]) == 0
        out = capsys.readouterr().out
        assert "fetched TEST9000" in out
        assert "dsa build" in out and "--part TEST9000" in out

    def test_mismatch_exits_one_and_shouts(
        self, tmp_path, wired, wired_fetcher, recorded, reg_file, capsys
    ):
        _make_pdf(tmp_path / "a.pdf", "A")
        old_sha = hashlib.sha256((tmp_path / "a.pdf").read_bytes()).hexdigest()
        _record(recorded, URL_A, _make_pdf(tmp_path / "b.pdf", "B", marker="drift"))
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000",
                document=RegistryDocument(url=URL_A, revision="Rev. A", sha256=old_sha),
            )
        )
        save_registry(registry, reg_file)
        assert cli.main(["fetch", "TEST9000"]) == 1
        err = capsys.readouterr().err
        assert "WARNING" in err and "sha256 MISMATCH" in err
        assert "--accept-new-revision" in err

    def test_json_output_is_machine_readable(
        self, tmp_path, wired, wired_fetcher, recorded, reg_file, capsys
    ):
        import json

        payload = _make_pdf(tmp_path / "src.pdf", "A")
        sha = _record(recorded, URL_A, payload)
        registry = DocumentRegistry()
        registry.put(
            RegistryEntry(
                part_number="TEST9000", document=RegistryDocument(url=URL_A, sha256=sha)
            )
        )
        save_registry(registry, reg_file)
        assert cli.main(["fetch", "TEST9000", "--json"]) == 0
        payload_out = json.loads(capsys.readouterr().out)
        assert payload_out["n_fetched"] == 1
        assert payload_out["documents"][0]["sha256"] == sha
