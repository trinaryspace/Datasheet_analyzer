"""The category taxonomy, and which category each Part sits in.

A flat Library is a fine record and a poor place to *find* anything: pulling a
part you used two years ago into a new project should not mean reading every
row. So parts are filed by function — amplifiers, mixers, passives — the way a
component library is.

Two things live here, and they are deliberately separate files.

**The taxonomy** is the list of categories. Seeded with a sensible RF and
embedded set and then yours: renamed, added to, merged. A fixed list in code
would be wrong the first time somebody buys a circulator, and a free-form
string per part is how one shelf ends up holding `amplifier`, `Amplifiers` and
`RF amps`. The model chooses *from this list*; "none of these" is a real
answer and lands in `uncategorized`.

**The part record** is which category a part is in — and it is stored here
rather than in `CorpusManifest` because **the build rewrites the manifest
every time**. A category recorded there would die at the next rebuild, which
is exactly the trap Labels were designed around: a build may propose, only a
person disposes. The manifest keeps the machine's guess so a fresh build
always has one; this file keeps the human's answer and always wins.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from datasheet_analyzer.config import Settings, get_settings

log = logging.getLogger(__name__)

CATEGORIES_FILE = "categories.json"
PARTS_FILE = "parts.json"

#: The slot for a part whose category is unknown or genuinely none of them.
#: A real answer, not a failure — and never inferred away silently.
UNCATEGORIZED = "uncategorized"

#: What a new shelf starts with. RF and embedded, because that is the work
#: this tool is for; entirely editable afterwards.
SEED_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("amplifiers", "Amplifiers"),
    ("mixers", "Mixers"),
    ("passives", "Passives"),
    ("transformers", "Transformers & baluns"),
    ("opamps", "Op-amps & comparators"),
    ("data-converters", "Data converters"),
    ("filters", "Filters"),
    ("oscillators", "Oscillators, PLLs & synthesizers"),
    ("switches", "Switches & attenuators"),
    ("power", "Power & regulators"),
    ("interfaces", "Interfaces & transceivers"),
    ("processors", "Processors & MCUs"),
    (UNCATEGORIZED, "Uncategorized"),
)

_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def slugify(name: str) -> str:
    """A display name as a category id. Mirrors the project-name rule."""
    lowered = (name or "").strip().lower()
    kept = [ch if (ch.isalnum() or ch in "._-") else "-" for ch in lowered]
    slug = re.sub(r"-{2,}", "-", "".join(kept)).strip("-.")
    while slug and not slug[0].isalnum():
        slug = slug[1:]
    return slug or UNCATEGORIZED


@dataclass(frozen=True)
class Category:
    """One slot in the taxonomy. `id` is stable; `name` is what you read."""

    id: str
    name: str


@dataclass
class PartRecord:
    """What a person decided about a Part, as opposed to what a build found.

    `category_evidence` exists for the same reason every other inferred value
    in this codebase carries evidence: a guess that cannot say why it guessed
    is not correctable by a human. `confirmed` separates "the model put it
    here" from "a person agreed", which is what lets the review sort the
    doubtful to the top.
    """

    part_number: str
    category: str = UNCATEGORIZED
    category_evidence: str = ""
    confirmed: bool = False
    labels: list[str] = field(default_factory=list)


class CategoryStore:
    """The taxonomy and the per-part records, on disk beside the Library.

    Every read degrades rather than raising: a corrupt or absent file reads as
    the seed taxonomy and no part records. Losing a categorisation is a
    nuisance; refusing to open the Library because one JSON file is malformed
    is worse.
    """

    def __init__(self, library_dir: Path | str) -> None:
        self.root = Path(library_dir)

    @classmethod
    def for_settings(cls, settings: Settings | None = None) -> CategoryStore:
        return cls((settings or get_settings()).library_dir)

    # --- the taxonomy ---------------------------------------------------------

    def categories(self) -> list[Category]:
        """Every category, seeded on first read. `uncategorized` is always last."""
        raw = _read_json(self.root / CATEGORIES_FILE)
        rows = raw.get("categories") if isinstance(raw, dict) else None
        if not rows:
            return [Category(id=cid, name=name) for cid, name in SEED_CATEGORIES]
        found = [
            Category(
                id=str(row.get("id", "")),
                name=str(row.get("name", "")) or str(row.get("id", "")),
            )
            for row in rows
            if isinstance(row, dict) and _SLUG_OK.match(str(row.get("id", "")))
        ]
        if not any(c.id == UNCATEGORIZED for c in found):
            found.append(Category(id=UNCATEGORIZED, name="Uncategorized"))
        return _uncategorized_last(found)

    def add_category(self, name: str) -> Category:
        """Add a category, or return the existing one with that id."""
        made = Category(id=slugify(name), name=(name or "").strip() or slugify(name))
        current = self.categories()
        for existing in current:
            if existing.id == made.id:
                return existing
        self._write_categories([*current, made])
        return made

    def rename_category(self, category_id: str, name: str) -> list[Category]:
        """Change a category's display name.

        The id — and so every part filed under it — is untouched, which is the
        whole reason a category has an id separate from its name.
        """
        rows = [
            Category(id=c.id, name=(name or "").strip() or c.name) if c.id == category_id else c
            for c in self.categories()
        ]
        self._write_categories(rows)
        return rows

    def remove_category(self, category_id: str) -> list[Category]:
        """Delete a category; its parts fall back to `uncategorized`.

        Never silently orphans a part: the fallback is explicit and visible in
        the tree, rather than leaving rows pointing at a category that is gone.
        """
        if category_id == UNCATEGORIZED:
            return self.categories()
        rows = [c for c in self.categories() if c.id != category_id]
        self._write_categories(rows)
        for record in list(self._records().values()):
            if record.category != category_id:
                continue
            record.category = UNCATEGORIZED
            record.category_evidence = f"category {category_id!r} was removed"
            self.put_part(record)
        return rows

    # --- part records ---------------------------------------------------------

    def part(self, part_number: str) -> PartRecord:
        """This part's record, or a fresh uncategorized one."""
        found = self._records().get(_key(part_number))
        return found if found is not None else PartRecord(part_number=part_number)

    def parts(self) -> dict[str, PartRecord]:
        """Every recorded part, keyed by upper-case part number."""
        return self._records()

    def category_of(self, part_number: str) -> str:
        """Which category this part is in; `uncategorized` when unrecorded."""
        return self.part(part_number).category or UNCATEGORIZED

    def put_part(self, record: PartRecord) -> PartRecord:
        """Write one part record, leaving every other one untouched."""
        records = self._records()
        records[_key(record.part_number)] = record
        self._write_parts(records)
        return record

    def set_category(
        self, part_number: str, category: str, *, evidence: str = "", confirmed: bool = True
    ) -> PartRecord:
        """File a part. `confirmed=False` records a proposal, not an answer."""
        record = self.part(part_number)
        record.part_number = part_number
        record.category = category or UNCATEGORIZED
        record.category_evidence = evidence
        record.confirmed = confirmed
        return self.put_part(record)

    def propose_category(self, part_number: str, category: str, *, evidence: str) -> PartRecord:
        """Record a machine guess — and never overwrite a person's answer.

        The reason these records live outside `CorpusManifest` at all is that a
        rebuild must not erase a human decision. That guarantee is this method.
        """
        record = self.part(part_number)
        if record.confirmed:
            return record
        return self.set_category(part_number, category, evidence=evidence, confirmed=False)

    # --- disk -----------------------------------------------------------------

    def _records(self) -> dict[str, PartRecord]:
        raw = _read_json(self.root / PARTS_FILE)
        rows = raw.get("parts") if isinstance(raw, dict) else None
        out: dict[str, PartRecord] = {}
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("part_number"):
                continue
            number = str(row["part_number"])
            out[_key(number)] = PartRecord(
                part_number=number,
                category=str(row.get("category") or UNCATEGORIZED),
                category_evidence=str(row.get("category_evidence") or ""),
                confirmed=bool(row.get("confirmed")),
                labels=[str(x) for x in row.get("labels") or []],
            )
        return out

    def _write_categories(self, rows: list[Category]) -> None:
        payload = {"categories": [{"id": c.id, "name": c.name} for c in _uncategorized_last(rows)]}
        _write_json(self.root / CATEGORIES_FILE, payload)

    def _write_parts(self, records: dict[str, PartRecord]) -> None:
        payload = {
            "parts": [
                {
                    "part_number": record.part_number,
                    "category": record.category,
                    "category_evidence": record.category_evidence,
                    "confirmed": record.confirmed,
                    "labels": record.labels,
                }
                for _, record in sorted(records.items())
            ]
        }
        _write_json(self.root / PARTS_FILE, payload)


def _key(part_number: str) -> str:
    """Part numbers are printed both ways; the record is keyed one way."""
    return (part_number or "").strip().upper()


def _uncategorized_last(rows: list[Category]) -> list[Category]:
    """`uncategorized` is a real slot, and it belongs at the bottom of a list."""
    named = [c for c in rows if c.id != UNCATEGORIZED]
    tail = [c for c in rows if c.id == UNCATEGORIZED]
    return [*named, *tail]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("could not write %s: %s", path, exc)
