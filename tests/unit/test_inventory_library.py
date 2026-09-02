"""Library-backed acquire: the Library says what a part is built from.

External behaviour only (ticket 03). A build resolves its documents through
`LibraryStore.for_part()`, `parts/<PART>/sources.json` becomes a derived,
byte-stable view nobody reads back, and a corpus built before the Library
existed migrates itself in on first touch.

Hermetic: synthetic PDFs built with fitz, a fake `LibraryStore` (so this
ticket is verifiable before ticket 01 lands), `Settings(parts_dir=tmp,
cache_dir=tmp, library_dir=tmp)`, no network and no model. Every build pins
`--vendor adi`, which routes to the offline `pdf_layout` backend; companions
route to `pdf_text`.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from datasheet_analyzer import cli
from datasheet_analyzer.acquire.inventory import (
    GENERATED_NOTE,
    MIGRATION_EVIDENCE,
    load_inventory,
    read_sources_file,
    register_into_library,
    register_source,
    resolve_documents,
    save_inventory,
)
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.models import Applicability, DocType, LibraryDocument, SourceDocument
from datasheet_analyzer.pipeline import build_part

# --- a fake LibraryStore ---------------------------------------------------


class FakeLibraryStore:
    """In-memory `LibraryStore`, honouring the contract frozen by ticket 00.

    Deliberately not ticket 01's implementation: this ticket is the *caller*,
    and it has to be verifiable on its own.
    """

    def __init__(self) -> None:
        self.docs: dict[str, LibraryDocument] = {}
        self.puts = 0

    def get(self, content_hash: str) -> LibraryDocument | None:
        return self.docs.get(content_hash)

    def put(self, doc: LibraryDocument) -> None:
        self.puts += 1
        existing = self.docs.get(doc.content_hash)
        if existing is not None and existing.labels and not doc.labels:
            doc = doc.model_copy(update={"labels": list(existing.labels)})
        self.docs[doc.content_hash] = doc

    def all(self) -> list[LibraryDocument]:
        return [self.docs[h] for h in sorted(self.docs)]

    def for_part(self, part_number: str) -> list[LibraryDocument]:
        return [d for d in self.all() if d.covers(part_number)]

    def set_applicability(self, content_hash: str, applicability: Applicability):
        doc = self.docs[content_hash].model_copy(update={"applicability": applicability})
        self.docs[content_hash] = doc
        return doc

    def set_labels(self, content_hash: str, labels: list[str]):
        doc = self.docs[content_hash].model_copy(update={"labels": list(labels)})
        self.docs[content_hash] = doc
        return doc


# --- synthetic corpus ------------------------------------------------------


def _pdf(path: Path, pages: list[str], toc: list[list] | None = None) -> Path:
    doc = fitz.open()
    for i, text in enumerate(pages):
        page = doc.new_page()
        page.insert_text((72, 72), text)
        page.insert_text((300, 750), str(i + 1))
    doc.set_toc(toc or [[1, f"1 {path.stem.title()}", 1]])
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture(autouse=True)
def _hermetic_settings(tmp_path, monkeypatch):
    """No settings leak from the developer's environment (AGENTS.md #4)."""
    monkeypatch.setenv("DSA_PARTS_DIR", str(tmp_path / "parts"))
    monkeypatch.setenv("DSA_CACHE_DIR", str(tmp_path / ".cache"))
    monkeypatch.setenv("DSA_LIBRARY_DIR", str(tmp_path / "library"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        parts_dir=tmp_path / "parts",
        cache_dir=tmp_path / ".cache",
        library_dir=tmp_path / "library",
    ).resolve()


@pytest.fixture
def corpus(tmp_path):
    """Three PDFs: an ADI datasheet, an all-parts note, an AFE79xx note."""
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    return {
        "datasheet": _pdf(
            pdfs / "ad9081_datasheet.pdf",
            [
                "Analog Devices AD9081 Quad DAC datasheet page one.",
                "4.1 Absolute Maximum Ratings VDD1P2 supply voltage 1.2 V.",
            ],
            toc=[[1, "1 Overview", 1], [1, "4.1 Absolute Maximum Ratings", 2]],
        ),
        "all": _pdf(
            pdfs / "thermal_note.pdf",
            ["Thermal design guidance applying to every device in the shelf."],
        ),
        "family": _pdf(
            pdfs / "afe79xx_jesd_note.pdf",
            ["AFE79xx JESD204C interface guide for the AFE79xx family."],
        ),
    }


@pytest.fixture
def store(corpus) -> FakeLibraryStore:
    """A stocked Library: one part-scoped datasheet, one all, one family."""
    fake = FakeLibraryStore()
    register_into_library(
        corpus["datasheet"],
        applicability=Applicability.for_parts(["AD9081"], evidence="title block: AD9081"),
        doc_type=DocType.DATASHEET,
        vendor="adi",
        store=fake,
        part_number="AD9081",
    )
    register_into_library(
        corpus["all"],
        applicability=Applicability.for_all(evidence="fallback: no part token found"),
        doc_type=DocType.APP_NOTE,
        store=fake,
    )
    register_into_library(
        corpus["family"],
        applicability=Applicability.for_family("AFE79xx", evidence="title: AFE79xx"),
        doc_type=DocType.APP_NOTE,
        store=fake,
    )
    return fake


def _hashes(result) -> set[str]:
    return {d.content_hash for d in result.manifest.documents}


def _hash_of(store: FakeLibraryStore, pdf: Path) -> str:
    (doc,) = [d for d in store.all() if Path(d.source.path).name == pdf.name]
    return doc.content_hash


# --- resolution ------------------------------------------------------------


class TestLibraryResolution:
    def test_build_resolves_documents_from_the_library(self, settings, store, corpus):
        """The part is the *view* of what covers it, not a folder listing."""
        result = build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert _hashes(result) == {
            _hash_of(store, corpus["datasheet"]),
            _hash_of(store, corpus["all"]),
        }

    def test_sources_json_is_not_the_source_of_truth(self, settings, store, corpus):
        """A library document absent from sources.json is still built."""
        part_dir = settings.parts_dir / "AD9081"
        part_dir.mkdir(parents=True)
        # a stale derived view naming only the datasheet
        save_inventory([store.get(_hash_of(store, corpus["datasheet"])).source], part_dir)
        result = build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert _hash_of(store, corpus["all"]) in _hashes(result)

    def test_all_applicability_is_in_every_parts_build(self, settings, store, corpus):
        note = _hash_of(store, corpus["all"])
        for part in ("AD9081", "AFE7950"):
            result = build_part(
                corpus["datasheet"],
                part_number=part,
                settings=settings,
                vendor="adi",
                use_llm=False,
                store=store,
            )
            assert note in _hashes(result), part

    def test_family_document_covers_afe7950_and_not_ad9081(self, settings, store, corpus):
        fam = _hash_of(store, corpus["family"])
        afe = build_part(
            corpus["family"],
            part_number="AFE7950",
            settings=settings,
            use_llm=False,
            store=store,
        )
        ad = build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert fam in _hashes(afe)
        assert fam not in _hashes(ad)

    def test_part_no_document_covers_bootstraps_from_the_named_pdf(self, settings, corpus):
        empty = FakeLibraryStore()
        result = build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=empty,
        )
        assert len(result.manifest.documents) == 1
        (doc,) = empty.for_part("AD9081")
        assert doc.applicability.kind == "parts"
        assert doc.applicability.parts == ["AD9081"]
        assert doc.applicability.evidence  # never a silent inference


class TestTheNamedPdfIsAlwaysPartOfTheBuild:
    def test_a_moved_file_keeps_its_identity(self, settings, store, corpus, tmp_path):
        """Same bytes, new path: the record follows the file, no second doc."""
        moved = tmp_path / "moved" / corpus["datasheet"].name
        moved.parent.mkdir()
        moved.write_bytes(corpus["datasheet"].read_bytes())
        digest = _hash_of(store, corpus["datasheet"])

        result = build_part(
            moved,
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert digest in _hashes(result)
        assert len(store.all()) == 3  # nothing new was invented
        assert Path(store.get(digest).source.path) == moved

    def test_naming_a_document_for_another_part_widens_it(self, settings, store, corpus):
        """Applicability is appended to, never overwritten."""
        digest = _hash_of(store, corpus["datasheet"])
        result = build_part(
            corpus["datasheet"],
            part_number="AFE7950",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert digest in _hashes(result)
        app = store.get(digest).applicability
        assert app.parts == ["AD9081", "AFE7950"]
        assert "title block: AD9081" in app.evidence  # the original reason survives

    def test_a_superseded_datasheet_revision_is_not_rebuilt(
        self, settings, store, corpus, tmp_path
    ):
        """One part, one datasheet: the named revision, not both of them."""
        rev_b = _pdf(
            tmp_path / "pdfs" / "ad9081_datasheet_revb.pdf",
            ["Analog Devices AD9081 Quad DAC datasheet Rev. B page one."],
        )
        newer = register_into_library(
            rev_b,
            applicability=Applicability.for_parts(["AD9081"], evidence="title block: AD9081"),
            doc_type=DocType.DATASHEET,
            vendor="adi",
            store=store,
            part_number="AD9081",
        )
        result = build_part(
            rev_b,
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert newer.content_hash in _hashes(result)
        assert _hash_of(store, corpus["datasheet"]) not in _hashes(result)
        # superseded for this build, still a real document in the Library
        assert (
            len([d for d in store.for_part("AD9081") if d.source.doc_type == DocType.DATASHEET])
            == 2
        )

    def test_user_labels_survive_a_build(self, settings, store, corpus):
        digest = _hash_of(store, corpus["datasheet"])
        store.set_labels(digest, ["reviewed", "thermal"])
        build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert store.get(digest).labels == ["reviewed", "thermal"]


# --- the derived view ------------------------------------------------------


class TestDerivedSourcesJson:
    def test_written_with_the_generated_marker(self, settings, store, corpus):
        build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        path = settings.parts_dir / "AD9081" / "sources.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["generated"] is True
        assert data["note"] == GENERATED_NOTE
        assert "do not edit" in data["note"]
        assert len(data["sources"]) == 2

    def test_byte_stable_across_two_identical_builds(self, settings, store, corpus):
        path = settings.parts_dir / "AD9081" / "sources.json"
        build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        first = path.read_bytes()
        build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert path.read_bytes() == first

    def test_hand_editing_has_no_effect_on_the_next_build(self, settings, store, corpus):
        path = settings.parts_dir / "AD9081" / "sources.json"
        build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        pristine = path.read_bytes()

        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["generated"] = False
        for entry in tampered["sources"]:
            entry["vendor"] = "qorvo"
            entry["vendor_evidence"] = "hand edit"
        tampered["sources"] = tampered["sources"][:1]  # drop a document too
        path.write_text(json.dumps(tampered, indent=2), encoding="utf-8")

        result = build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert result.manifest.vendor == "adi"
        assert len(result.manifest.documents) == 2  # the dropped doc came back
        assert path.read_bytes() == pristine  # and the edit is gone

    def test_save_and_load_round_trip(self, tmp_path, corpus):
        src = register_source(corpus["datasheet"], part_number="AD9081")
        part_dir = tmp_path / "parts" / "AD9081"
        save_inventory([src], part_dir)
        assert load_inventory(part_dir) == [src]

    def test_legacy_bare_list_file_still_loads(self, tmp_path, corpus):
        src = register_source(corpus["datasheet"], part_number="AD9081")
        part_dir = tmp_path / "parts" / "AD9081"
        part_dir.mkdir(parents=True)
        (part_dir / "sources.json").write_text(
            json.dumps([src.model_dump(mode="json")], indent=2), encoding="utf-8"
        )
        assert read_sources_file(part_dir) == [src]
        assert load_inventory(part_dir) == [src]

    def test_load_inventory_prefers_the_library(self, tmp_path, store, corpus):
        """Same signature, library-backed answer."""
        part_dir = tmp_path / "parts" / "AD9081"
        part_dir.mkdir(parents=True)
        (part_dir / "sources.json").write_text("[]", encoding="utf-8")
        loaded = load_inventory(part_dir, store=store)
        assert {Path(s.path).name for s in loaded} == {
            corpus["datasheet"].name,
            corpus["all"].name,
        }


# --- legacy corpora --------------------------------------------------------


class TestLegacyMigration:
    def _legacy_part(self, settings, corpus) -> Path:
        """A part directory as the old code left it: sources.json, no Library."""
        part_dir = settings.parts_dir / "LEGACY9000"
        part_dir.mkdir(parents=True)
        src = register_source(
            corpus["datasheet"],
            part_number="LEGACY9000",
            doc_type=DocType.DATASHEET,
            vendor="adi",
        )
        (part_dir / "sources.json").write_text(
            json.dumps([src.model_dump(mode="json")], indent=2), encoding="utf-8"
        )
        return part_dir

    def test_legacy_part_builds_and_migrates(self, settings, corpus):
        part_dir = self._legacy_part(settings, corpus)
        empty = FakeLibraryStore()
        result = build_part(
            corpus["datasheet"],
            part_number="LEGACY9000",
            settings=settings,
            use_llm=False,
            store=empty,
        )
        assert len(result.manifest.documents) == 1
        (doc,) = empty.for_part("LEGACY9000")
        assert doc.applicability.kind == "parts"
        assert doc.applicability.parts == ["LEGACY9000"]
        assert doc.applicability.evidence == MIGRATION_EVIDENCE
        assert (part_dir / "sources.json").exists()

    def test_migration_is_idempotent(self, settings, corpus):
        self._legacy_part(settings, corpus)
        empty = FakeLibraryStore()
        for _ in range(2):
            build_part(
                corpus["datasheet"],
                part_number="LEGACY9000",
                settings=settings,
                use_llm=False,
                store=empty,
            )
        assert len(empty.all()) == 1
        assert len(empty.for_part("LEGACY9000")) == 1

    def test_a_shared_document_is_widened_by_migration_not_re_filed(self, settings, corpus):
        """One app note, two parts — and the second build must not steal it.

        Measured on TI's SNAA360, *Getting the Most of Your Data Converter
        Clocking System Using LMX1204*, which names both AFE7950 and LMX1204.
        `dsa fetch` had registered it against each part, so it sat in both
        parts' `sources.json`; migration then saw a hash the Library did not
        cover **for this part** and answered it with a brand-new single-part
        record, replacing the applicability the other part's build had written.
        Whichever part built second owned the document, and the first part
        silently lost it on its next build.

        "Not covered here" and "never seen" are different states, and only the
        second may be answered with a new record.
        """
        shared = corpus["family"]  # any companion PDF; its own applicability is unused here
        store = FakeLibraryStore()
        first = settings.parts_dir / "PART_A"
        second = settings.parts_dir / "PART_B"
        for part_dir, part in ((first, "PART_A"), (second, "PART_B")):
            part_dir.mkdir(parents=True)
            src = register_source(shared, part_number=part, doc_type=DocType.APP_NOTE, vendor="adi")
            save_inventory([src], part_dir)

        resolve_documents(first, part_number="PART_A", store=store)
        assert store.for_part("PART_A")

        resolve_documents(second, part_number="PART_B", store=store)
        (doc,) = store.all()
        assert doc.applicability.parts == ["PART_A", "PART_B"]
        assert MIGRATION_EVIDENCE in doc.applicability.evidence
        assert "named for PART_B" in doc.applicability.evidence
        # And the first part still resolves it — the regression itself.
        assert [d.content_hash for d in store.for_part("PART_A")] == [doc.content_hash]
        assert len(store.all()) == 1

    def test_resolve_documents_without_a_store_reads_the_file(self, settings, corpus):
        """No Library at all is still a working build path."""
        part_dir = self._legacy_part(settings, corpus)
        (src,) = resolve_documents(part_dir, part_number="LEGACY9000", store=None)
        assert Path(src.path).name == corpus["datasheet"].name

    def test_document_whose_file_vanished_is_skipped(self, settings, corpus, caplog):
        part_dir = settings.parts_dir / "GONE"
        part_dir.mkdir(parents=True)
        ghost = SourceDocument(
            content_hash="ab" * 32,
            path=str(settings.parts_dir / "nope.pdf"),
            part_number="GONE",
            doc_type=DocType.APP_NOTE,
        )
        save_inventory([ghost], part_dir)
        assert resolve_documents(part_dir, part_number="GONE", store=None) == []


# --- vendor, status, cache -------------------------------------------------


class TestVendorIsStillPinnedAtAcquire:
    def test_override_is_recorded_with_evidence(self, settings, store, corpus):
        result = build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert result.manifest.vendor == "adi"
        ds = store.get(_hash_of(store, corpus["datasheet"])).source
        assert ds.vendor == "adi"
        assert ds.vendor_evidence == "cli-override: --vendor adi"
        # and the derived view carries the same pinned record
        (written,) = [
            s
            for s in read_sources_file(settings.parts_dir / "AD9081")
            if s.doc_type == DocType.DATASHEET
        ]
        assert (written.vendor, written.vendor_evidence) == ("adi", "cli-override: --vendor adi")

    def test_legacy_record_without_evidence_is_backfilled(self, settings, corpus):
        part_dir = settings.parts_dir / "AD9081"
        part_dir.mkdir(parents=True)
        legacy = register_source(corpus["datasheet"], part_number="AD9081")
        legacy.vendor, legacy.vendor_evidence = "adi", ""  # pre-0.2.0 record
        save_inventory([legacy], part_dir)

        fake = FakeLibraryStore()
        build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            use_llm=False,
            store=fake,
        )
        (doc,) = fake.for_part("AD9081")
        assert doc.source.vendor == "adi"
        assert doc.source.vendor_evidence == 'brand:"analog devices" (p.1)'

    def test_vendor_is_never_guessed_at_runtime(self, settings, store, corpus):
        """The build reads the pinned record; it does not re-detect it."""
        pinned = store.get(_hash_of(store, corpus["datasheet"]))
        store.put(
            pinned.model_copy(
                update={
                    "source": pinned.source.model_copy(
                        update={"vendor": "adi", "vendor_evidence": "cli-override: --vendor adi"}
                    )
                }
            )
        )
        result = build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            use_llm=False,
            store=store,
        )
        assert result.manifest.vendor == "adi"
        assert store.get(_hash_of(store, corpus["datasheet"])).source.vendor_evidence == (
            "cli-override: --vendor adi"
        )


class TestStatusAndCache:
    def test_status_reports_vendor_and_extraction_stats(
        self, settings, store, corpus, monkeypatch, capsys
    ):
        build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        monkeypatch.setattr("datasheet_analyzer.cli.get_settings", lambda: settings)
        code = cli.main(["status"])
        out = capsys.readouterr().out
        assert code == 0
        assert "AD9081" in out
        assert "vendor: adi" in out
        assert "extraction: pdf_layout" in out

    def test_extraction_cache_is_hit_for_an_unchanged_pdf(self, settings, store, corpus):
        first = build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        second = build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=store,
        )
        assert first.cached_extraction is False
        assert second.cached_extraction is True
        assert _hashes(first) == _hashes(second)  # content_hash handling untouched


# --- injection -------------------------------------------------------------


class TestStoreInjection:
    def test_injected_store_is_the_one_used(self, settings, corpus):
        fake = FakeLibraryStore()
        build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
            store=fake,
        )
        assert len(fake.for_part("AD9081")) == 1

    def test_default_path_constructs_a_store_from_settings(self, settings, corpus, monkeypatch):
        fake = FakeLibraryStore()
        seen: list[Settings | None] = []

        def _for_settings(cls, s=None):
            seen.append(s)
            return fake

        monkeypatch.setattr(
            "datasheet_analyzer.library.store.LibraryStore.for_settings",
            classmethod(_for_settings),
        )
        build_part(
            corpus["datasheet"],
            part_number="AD9081",
            settings=settings,
            vendor="adi",
            use_llm=False,
        )
        assert seen == [settings]
        assert len(fake.for_part("AD9081")) == 1

    def test_register_into_library_wraps_and_stores(self, corpus):
        fake = FakeLibraryStore()
        doc = register_into_library(
            corpus["family"],
            applicability=Applicability.for_family("AFE79xx", evidence="title"),
            doc_type=DocType.APP_NOTE,
            store=fake,
        )
        assert fake.get(doc.content_hash) is doc
        assert doc.source.doc_type == DocType.APP_NOTE
        assert doc.covers("AFE7950") and not doc.covers("AD9081")

    def test_register_into_library_without_a_store_still_registers(self, corpus):
        doc = register_into_library(
            corpus["all"],
            applicability=Applicability.for_all(evidence="fallback"),
            store=None,
        )
        assert doc.source.content_hash
        assert doc.applicability.kind == "all"
