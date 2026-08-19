"""The category taxonomy, the per-part records, and the endpoints over them.

Hermetic: `tmp_path` only, no network, no model. The classifier is never
constructed — every test here runs the keyword path, which is the fallback the
design requires to work without a key.

The assertion that matters most is the last one in `TestPartRecords`: a build
proposing a category must never overwrite a person's answer. That guarantee is
the entire reason these records live outside `CorpusManifest`, which a rebuild
rewrites wholesale.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from datasheet_analyzer.acquire.categorize import categorize, keyword_guess
from datasheet_analyzer.acquire.inventory import resolve_documents
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.app.routers import categories as categories_router
from datasheet_analyzer.config import Settings, reset_settings_cache
from datasheet_analyzer.library.categories import (
    SEED_CATEGORIES,
    UNCATEGORIZED,
    Category,
    CategoryStore,
    slugify,
)
from datasheet_analyzer.library.store import LibraryStore
from datasheet_analyzer.models import Applicability, LibraryDocument, SourceDocument


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


@pytest.fixture
def store(settings: Settings) -> CategoryStore:
    return CategoryStore(settings.library_dir)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(categories_router.router)
    app.dependency_overrides[get_settings_dep] = lambda: settings
    return TestClient(app)


class TestTaxonomy:
    def test_a_new_shelf_is_seeded_with_an_rf_set(self, store: CategoryStore) -> None:
        ids = [c.id for c in store.categories()]
        assert "amplifiers" in ids
        assert "mixers" in ids
        assert "data-converters" in ids

    def test_uncategorized_is_always_last(self, store: CategoryStore) -> None:
        """It is a real slot, and it belongs at the bottom of a list."""
        assert store.categories()[-1].id == UNCATEGORIZED

    def test_a_category_can_be_added_and_survives_a_reread(self, store: CategoryStore) -> None:
        store.add_category("Circulators")
        assert "circulators" in [c.id for c in CategoryStore(store.root).categories()]

    def test_adding_one_that_exists_returns_it_rather_than_duplicating(
        self, store: CategoryStore
    ) -> None:
        first = store.add_category("Amplifiers")
        before = len(store.categories())
        again = store.add_category("amplifiers")
        assert first.id == again.id
        assert len(store.categories()) == before

    def test_renaming_keeps_the_id_so_parts_stay_filed(self, store: CategoryStore) -> None:
        """The whole reason a category has an id separate from its name."""
        store.set_category("PMA1-14LN+", "amplifiers")
        store.rename_category("amplifiers", "RF gain blocks")

        assert store.category_of("PMA1-14LN+") == "amplifiers"
        renamed = next(c for c in store.categories() if c.id == "amplifiers")
        assert renamed.name == "RF gain blocks"

    def test_removing_a_category_reshelves_its_parts_rather_than_orphaning_them(
        self, store: CategoryStore
    ) -> None:
        store.set_category("PMA1-14LN+", "amplifiers")
        store.remove_category("amplifiers")

        assert "amplifiers" not in [c.id for c in store.categories()]
        assert store.category_of("PMA1-14LN+") == UNCATEGORIZED

    def test_uncategorized_cannot_be_removed(self, store: CategoryStore) -> None:
        store.remove_category(UNCATEGORIZED)
        assert UNCATEGORIZED in [c.id for c in store.categories()]

    def test_a_corrupt_taxonomy_reads_as_the_seed_rather_than_failing(
        self, store: CategoryStore
    ) -> None:
        """Losing a categorisation is a nuisance; an unopenable Library is worse."""
        store.root.mkdir(parents=True, exist_ok=True)
        (store.root / "categories.json").write_text("{ not json", encoding="utf-8")
        assert len(store.categories()) == len(SEED_CATEGORIES)

    def test_slugify_turns_a_display_name_into_an_id(self) -> None:
        assert slugify("RF Amps & Gain Blocks") == "rf-amps-gain-blocks"
        assert slugify("   ") == UNCATEGORIZED


class TestPartRecords:
    def test_an_unrecorded_part_is_uncategorized(self, store: CategoryStore) -> None:
        assert store.category_of("NEVER-SEEN") == UNCATEGORIZED

    def test_part_numbers_are_matched_case_insensitively(self, store: CategoryStore) -> None:
        store.set_category("ad9081", "data-converters")
        assert store.category_of("AD9081") == "data-converters"

    def test_a_build_proposal_never_overwrites_a_persons_answer(self, store: CategoryStore) -> None:
        """The guarantee these records exist for.

        `CorpusManifest` is rewritten by every build, so a category stored
        there would die at the next rebuild. Here, a later guess is ignored.
        """
        store.set_category("PMA1-14LN+", "mixers", evidence="the user said so")
        store.propose_category("PMA1-14LN+", "amplifiers", evidence="llm guessed")

        assert store.category_of("PMA1-14LN+") == "mixers"
        assert store.part("PMA1-14LN+").confirmed is True

    def test_a_proposal_does_overwrite_an_earlier_proposal(self, store: CategoryStore) -> None:
        """A rebuild may improve on its own guess; it just may not overrule a human."""
        store.propose_category("X1", "mixers", evidence="first")
        store.propose_category("X1", "amplifiers", evidence="second")
        assert store.category_of("X1") == "amplifiers"
        assert store.part("X1").confirmed is False

    def test_one_record_is_written_without_disturbing_the_others(
        self, store: CategoryStore
    ) -> None:
        store.set_category("A1", "amplifiers")
        store.set_category("B2", "mixers")
        store.set_category("A1", "filters")

        assert store.category_of("B2") == "mixers"
        assert store.category_of("A1") == "filters"


class TestCategoryEndpoints:
    def test_the_taxonomy_is_served_with_per_category_counts(
        self, client: TestClient, store: CategoryStore
    ) -> None:
        store.set_category("AD9081", "data-converters")
        store.set_category("AFE7950", "data-converters")

        rows = client.get("/api/categories").json()["categories"]
        converters = next(r for r in rows if r["id"] == "data-converters")
        assert converters["count"] == 2

    def test_the_taxonomy_also_says_where_every_recorded_part_is_filed(
        self, client: TestClient, store: CategoryStore
    ) -> None:
        """One source for the count and for the contents.

        The Library groups its documents by this map. Deriving the grouping
        from the built-parts catalog instead let a category read "3" and then
        open empty, because that catalog knows only what is built — and a
        filed part is filed whether or not it has been rebuilt since.
        """
        store.set_category("PMA1-14LN+", "amplifiers")
        store.set_category("AD9081", "data-converters")

        body = client.get("/api/categories").json()
        assert body["parts"] == {"PMA1-14LN+": "amplifiers", "AD9081": "data-converters"}

        counted = sum(c["count"] for c in body["categories"])
        assert counted == len(body["parts"])

    def test_filing_a_part_by_hand_marks_it_confirmed(self, client: TestClient) -> None:
        out = client.post("/api/parts/PMA1-14LN+/category", json={"category": "amplifiers"}).json()
        assert out["category"] == "amplifiers"
        assert out["confirmed"] is True

    def test_filing_into_a_category_that_does_not_exist_is_refused(
        self, client: TestClient
    ) -> None:
        """The taxonomy is the user's; an API call does not get to extend it."""
        response = client.post("/api/parts/X1/category", json={"category": "nonsense"})
        assert response.status_code == 400
        assert "not a category" in response.json()["detail"]

    def test_removing_uncategorized_is_refused_with_the_reason(self, client: TestClient) -> None:
        response = client.delete(f"/api/categories/{UNCATEGORIZED}")
        assert response.status_code == 400
        assert "cannot be removed" in response.json()["detail"]

    def test_renaming_an_unknown_category_is_a_404(self, client: TestClient) -> None:
        assert client.patch("/api/categories/nope", json={"name": "x"}).status_code == 404

    def test_categorize_leaves_a_confirmed_part_alone(
        self, client: TestClient, store: CategoryStore
    ) -> None:
        """A person already answered; the classifier is not asked at all."""
        store.set_category("PMA1-14LN+", "mixers", evidence="the user said so")

        rows = client.post("/api/categorize", json={"parts": ["PMA1-14LN+"]}).json()["parts"]
        assert rows[0]["category"] == "mixers"
        assert rows[0]["confirmed"] is True

    def test_categorize_reports_a_part_with_no_corpus_honestly(self, client: TestClient) -> None:
        rows = client.post("/api/categorize", json={"parts": ["NO-SUCH-PART"]}).json()["parts"]
        assert rows[0]["category"] == UNCATEGORIZED
        assert rows[0]["confident"] is False

    def test_a_part_record_written_before_this_feature_still_loads(
        self, client: TestClient, settings: Settings
    ) -> None:
        settings.library_dir.mkdir(parents=True, exist_ok=True)
        (settings.library_dir / "parts.json").write_text(
            json.dumps({"parts": [{"part_number": "OLD1"}]}), encoding="utf-8"
        )
        out = client.get("/api/parts/OLD1/category").json()
        assert out["category"] == UNCATEGORIZED
        assert out["confirmed"] is False


#: The seed taxonomy as the classifier receives it.
CATEGORIES = [Category(id=i, name=n) for i, n in SEED_CATEGORIES]


class TestGuessing:

    def test_keywords_find_the_obvious_ones(self) -> None:
        allowed = {c.id for c in CATEGORIES}
        assert keyword_guess("a low noise amplifier for L-band", allowed)[0] == "amplifiers"
        assert keyword_guess("14-bit ADC with JESD204B", allowed)[0] == "data-converters"
        assert keyword_guess("nothing recognisable here", allowed)[0] == UNCATEGORIZED

    def test_a_keyword_only_guess_is_never_confident(self) -> None:
        """A single keyword is weak evidence.

        `ZX10R-2-183-S+` is a splitter whose text mentions an amplifier once,
        and the keyword pass files it under amplifiers without hesitating.
        Marking that doubtful is what puts it at the top of the review.
        """
        _category, _why, confident = categorize(
            "ZX10R", "a splitter, mentioned alongside an amplifier", CATEGORIES
        )
        assert confident is False

    def test_the_classifier_may_not_invent_a_category(self) -> None:
        """An id outside the taxonomy is no answer, not a new slot."""

        class Rogue:
            model = "fake"

            def complete(self, *_args: object, **_kwargs: object) -> str:
                return '{"category": "flux-capacitors", "reason": "why not"}'

        category, evidence, confident = categorize(
            "X1", "an amplifier datasheet", CATEGORIES, client=Rogue()
        )
        assert category == "amplifiers"  # fell back to the keyword pass
        assert "malformed" in evidence
        assert confident is False


class TestSupportingDocumentsReachTheirCategory:
    """The end the fourth Applicability kind exists for.

    A supporting document is filed and never built into a part of its own.
    What makes it *useful* is the next line of the chain: a build resolves its
    documents from every library record covering the part, and a part in the
    category is covered. Without this, `category` applicability would be a
    label that changed nothing about retrieval.
    """

    def _shelf(self, settings: Settings) -> tuple[LibraryStore, CategoryStore, Path]:
        shelf = settings.library_dir.parent / "shelf"
        shelf.mkdir(parents=True, exist_ok=True)
        return LibraryStore(settings.library_dir), CategoryStore(settings.library_dir), shelf

    def _file(self, shelf: Path, name: str) -> Path:
        path = shelf / name
        path.write_bytes(b"%PDF-1.4\n")
        return path

    def _build_set(self, library: LibraryStore, settings: Settings) -> list[str]:
        return sorted(
            Path(d.path).name
            for d in resolve_documents(
                settings.parts_dir / "PMA1-14LN+", part_number="PMA1-14LN+", store=library
            )
        )

    def _document(self, path: Path, part_number: str, applicability: Applicability):
        return LibraryDocument(
            source=SourceDocument(
                content_hash=path.name.encode().hex()[:32] or "0",
                path=str(path),
                part_number=part_number,
                page_count=4,
            ),
            applicability=applicability,
        )

    def test_an_app_note_joins_every_part_filed_in_its_category(
        self, settings: Settings
    ) -> None:
        library, categories, shelf = self._shelf(settings)
        datasheet = self._file(shelf, "PMA1-14LN+.pdf")
        appnote = self._file(shelf, "AN-1285.pdf")
        library.put(self._document(datasheet, "PMA1-14LN+", Applicability.for_parts(["PMA1-14LN+"])))
        library.put(self._document(appnote, "", Applicability.for_category("amplifiers")))
        categories.set_category("PMA1-14LN+", "amplifiers")

        # Sorted, not positional: resolution order follows content hashes.
        built_from = self._build_set(library, settings)
        assert built_from == ["AN-1285.pdf", "PMA1-14LN+.pdf"]

    def test_refiling_the_part_takes_it_out_of_that_build(self, settings: Settings) -> None:
        """Filing is the only thing that binds them, so refiling unbinds them."""
        library, categories, shelf = self._shelf(settings)
        datasheet = self._file(shelf, "PMA1-14LN+.pdf")
        appnote = self._file(shelf, "AN-1285.pdf")
        library.put(self._document(datasheet, "PMA1-14LN+", Applicability.for_parts(["PMA1-14LN+"])))
        library.put(self._document(appnote, "", Applicability.for_category("amplifiers")))
        categories.set_category("PMA1-14LN+", "amplifiers")
        categories.set_category("PMA1-14LN+", "mixers")

        assert self._build_set(library, settings) == ["PMA1-14LN+.pdf"]
