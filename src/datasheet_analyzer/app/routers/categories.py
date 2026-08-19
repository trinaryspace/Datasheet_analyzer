"""The taxonomy, and where each part sits in it.

Reads and writes `library/categories.json` and `library/parts.json` through
`CategoryStore`. Nothing here builds anything: filing a part is metadata about
navigation, and the corpus it describes is untouched by every route below.

The one rule worth stating twice: **a build proposes, a person disposes.**
`POST /api/parts/{part}/category` is the person, and it sets `confirmed`.
`propose_category` is the build, and it will not overwrite a confirmed record.
That is the whole reason these records live outside `CorpusManifest`, which a
rebuild rewrites wholesale.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from datasheet_analyzer.acquire.categorize import categorize, corpus_digest
from datasheet_analyzer.app.contracts import (
    API_PREFIX,
    CategoriesOut,
    CategorizeIn,
    CategorizeOut,
    CategoryCreateIn,
    CategoryOut,
    CategoryRenameIn,
    PartCategoryIn,
    PartCategoryOut,
)
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.config import Settings
from datasheet_analyzer.library.categories import UNCATEGORIZED, CategoryStore
from datasheet_analyzer.retrieve import Retriever

log = logging.getLogger(__name__)

router = APIRouter(prefix=API_PREFIX, tags=["categories"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


@router.get("/categories", response_model=CategoriesOut)
def get_categories(settings: SettingsDep) -> CategoriesOut:
    """The taxonomy, with how many parts sit in each.

    Counts come from the part records rather than from `parts_dir`, because a
    category is a fact about what a person filed, not about what happens to be
    built — a part filed under amplifiers and not yet rebuilt is still an
    amplifier.
    """
    store = CategoryStore.for_settings(settings)
    counts: dict[str, int] = {}
    filed: dict[str, str] = {}
    for record in store.parts().values():
        counts[record.category] = counts.get(record.category, 0) + 1
        filed[record.part_number] = record.category
    return CategoriesOut(
        categories=[
            CategoryOut(id=c.id, name=c.name, count=counts.get(c.id, 0))
            for c in store.categories()
        ],
        # The same records the counts come from. The Library groups by this,
        # so a category's number and its contents can never disagree.
        parts=filed,
    )


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryCreateIn, settings: SettingsDep) -> CategoryOut:
    """Add a category. Adding one that exists returns it rather than failing."""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="a category needs a name")
    made = CategoryStore.for_settings(settings).add_category(name)
    return CategoryOut(id=made.id, name=made.name, count=0)


@router.patch("/categories/{category_id}", response_model=CategoriesOut)
def rename_category(
    category_id: str, body: CategoryRenameIn, settings: SettingsDep
) -> CategoriesOut:
    """Rename a category. Its id, and every part filed under it, is untouched."""
    store = CategoryStore.for_settings(settings)
    if not any(c.id == category_id for c in store.categories()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no category {category_id!r}")
    store.rename_category(category_id, body.name)
    return get_categories(settings)


@router.delete("/categories/{category_id}", response_model=CategoriesOut)
def remove_category(category_id: str, settings: SettingsDep) -> CategoriesOut:
    """Remove a category; its parts fall back to `uncategorized`.

    `uncategorized` itself cannot be removed — it is where everything else
    lands, and a shelf with nowhere to put an unfiled part would have to
    invent one.
    """
    if category_id == UNCATEGORIZED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="uncategorized is where unfiled parts go and cannot be removed",
        )
    store = CategoryStore.for_settings(settings)
    if not any(c.id == category_id for c in store.categories()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no category {category_id!r}")
    store.remove_category(category_id)
    return get_categories(settings)


@router.get("/parts/{part_number}/category", response_model=PartCategoryOut)
def get_part_category(part_number: str, settings: SettingsDep) -> PartCategoryOut:
    """Where this part is filed, and whether a person put it there."""
    record = CategoryStore.for_settings(settings).part(part_number)
    return PartCategoryOut(
        part_number=record.part_number or part_number,
        category=record.category,
        evidence=record.category_evidence,
        confirmed=record.confirmed,
    )


@router.post("/parts/{part_number}/category", response_model=PartCategoryOut)
def set_part_category(
    part_number: str, body: PartCategoryIn, settings: SettingsDep
) -> PartCategoryOut:
    """File a part, as a person. This is the answer a rebuild must not undo."""
    store = CategoryStore.for_settings(settings)
    category = (body.category or UNCATEGORIZED).strip()
    if not any(c.id == category for c in store.categories()):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{category!r} is not a category; add it before filing a part in it",
        )
    record = store.set_category(
        part_number, category, evidence=body.evidence or "set by hand", confirmed=True
    )
    return PartCategoryOut(
        part_number=record.part_number,
        category=record.category,
        evidence=record.category_evidence,
        confirmed=record.confirmed,
    )


@router.post("/categorize", response_model=CategorizeOut)
def categorize_parts(body: CategorizeIn, settings: SettingsDep) -> CategorizeOut:
    """Propose a category for each named part, reading its built corpus.

    On demand rather than inside the build loop, and that placement matters:
    running it per job made every build wait on a classifier, cost a model call
    per part whether or not anyone looked, and put a network dependency in the
    middle of a pipeline that is otherwise offline. The categorise screen asks
    for these when it opens, which is the only moment they are wanted.

    Parts a person has already filed come back untouched and `confirmed`; the
    classifier is not asked about them at all.
    """
    store = CategoryStore.for_settings(settings)
    categories = store.categories()
    client = _category_client(settings)

    rows: list[PartCategoryOut] = []
    for part_number in body.parts:
        record = store.part(part_number)
        if record.confirmed:
            rows.append(
                PartCategoryOut(
                    part_number=part_number,
                    category=record.category,
                    evidence=record.category_evidence,
                    confirmed=True,
                    confident=True,
                )
            )
            continue
        category, evidence, confident = _propose(part_number, categories, client, settings, store)
        rows.append(
            PartCategoryOut(
                part_number=part_number,
                category=category,
                evidence=evidence,
                confirmed=False,
                confident=confident,
            )
        )
    # Doubtful first: those are the rows worth a human glance, and a review
    # sorted any other way buries them under the ones that were fine.
    rows.sort(key=lambda r: (r.confirmed, r.confident, r.part_number))
    return CategorizeOut(parts=rows)


def _propose(part_number, categories, client, settings, store):
    """One part's guess, recorded as a proposal. Never raises."""
    try:
        index = Retriever.for_part(Path(settings.parts_dir) / part_number).index
        category, evidence, confident = categorize(
            part_number, corpus_digest(index), categories, client=client
        )
    except Exception as exc:  # noqa: BLE001 - a guess is never load-bearing
        log.warning("could not categorise %s: %s", part_number, exc)
        return UNCATEGORIZED, f"could not read the corpus: {type(exc).__name__}", False
    store.propose_category(part_number, category, evidence=evidence)
    return category, evidence, confident


def _category_client(settings: Settings):
    """The classifier, or `None` when no key is set.

    A missing key is a normal mode, not an error: the keyword pass still
    produces something usable, and it is marked not-confident so the review
    puts it in front of a person.
    """
    if not settings.llm_available:
        return None
    try:
        from datasheet_analyzer.enrich.llm import AnthropicClient

        return AnthropicClient(api_key=settings.anthropic_api_key, model=settings.model)
    except Exception as exc:  # noqa: BLE001 - never load-bearing
        log.warning("no category classifier available: %s", exc)
        return None
