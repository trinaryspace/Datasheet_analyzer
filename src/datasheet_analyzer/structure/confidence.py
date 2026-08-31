"""Per-record confidence — how far one row can be trusted on its own.

`ExtractionStats` grades a whole *document*: how many tables the layout engine
detected, accepted and rejected. An answer needs the grade per *record*, so an
agent can say "this value is `low` confidence — open p.47 to confirm" instead
of asserting a shaky number. This module is that rule, and it is computed at
**structure time**, where the table, its reconstruction provenance, its page
pinning and the row's own cells are all still in hand; by the time a record
reaches `retrieve/` the evidence is gone.

The spec rule, evaluated worst-first (also in `AGENTS.md`):

| Grade | Rule |
|---|---|
| `high` | table pinned to an exact page **and** the reconstruction gate passed first try **and** the row's value cells are non-empty |
| `medium` | the page is section-range only, **or** the row's min/typ/max cells are empty |
| `low` | the grid was rescued by the retry ladder, **or** the unit is missing where the alias lexicon expected one |

Three notes on what the rule deliberately does *not* say:

- **"The row's value cells are non-empty" is read as "the row prints a value
  at all"**, and its `medium` twin as "the row's min/typ/max cells are *all*
  empty" — a row that prints only a maximum is a normal datasheet row, not a
  damaged one. The strict reading (every declared min/typ/max cell filled) was
  measured before it was rejected: **0 of AD9081's 549 spec rows** fill min,
  typ and max together, because a datasheet prints min/max *or* typ, so that
  reading grades every real corpus 0% `high` and carries no signal at all.
  What does carry signal is a row whose parameter survived but whose numbers
  did not — that is the empty-cell case this grade flags.
- **A row with no page at all stays `medium`**, not `low`. The rule table
  above is the contract, and the citation already degrades honestly on its own
  (`Citation.pages` renders `p.?`), so the gap is visible without inventing a
  fourth rule here.
- **The unit check never removes anything.** It is the same `expect_unit` the
  alias lexicon uses as a ranker: here it lowers a grade, and nowhere does it
  suppress a record. A printed value with no unit is still an answer.

Plots carry no grid to reconstruct, so their rule is about how precisely the
figure can be cited and identified: an exact printed page and a caption is
`high`, a section-range page or a captionless figure is `medium`, no page at
all is `low` — there is nothing to open, and unlike a spec row a plot has no
printed value that could stand on its own without one.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from datasheet_analyzer.models import (
    RECONSTRUCTION_RESCUED,
    Confidence,
    PlotRecord,
    SectionNode,
    SpecRecord,
    TableBlock,
)
from datasheet_analyzer.structure.aliases import AliasLexicon, load_lexicon

# The value-bearing roles of a parametric table, in the order they are printed.
VALUE_ROLES: tuple[str, ...] = ("min", "typ", "max", "value")

# The grades a mix always reports, in descending trust order.
GRADES: tuple[Confidence, ...] = (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW)


def grade_spec_record(
    record: SpecRecord,
    table: TableBlock,
    section: SectionNode,
    *,
    lexicon: AliasLexicon | None = None,
) -> Confidence:
    """Grade one spec row against the rule in this module's docstring."""
    if table.reconstruction == RECONSTRUCTION_RESCUED:
        return Confidence.LOW
    if unit_expected_but_missing(record, lexicon):
        return Confidence.LOW
    if not page_is_exact(record, table, section):
        return Confidence.MEDIUM
    if not has_value(record):
        return Confidence.MEDIUM
    return Confidence.HIGH


def grade_plot_record(record: PlotRecord) -> Confidence:
    """Grade one cataloged plot on citation precision + identification."""
    if record.page_start is None:
        return Confidence.LOW
    if not record.caption.strip():
        return Confidence.MEDIUM
    if (record.page_end or record.page_start) != record.page_start:
        return Confidence.MEDIUM
    return Confidence.HIGH


def page_is_exact(record: SpecRecord, table: TableBlock, section: SectionNode) -> bool:
    """True when the row cites one printed page rather than a section's range.

    Exact means the page was *pinned*: the row's own page on a merged
    multi-page grid, or the table's pinned page. The one other case that pins a
    row unambiguously is a section that occupies a single page — there the
    range and the printed page are the same number.
    """
    if record.page is None:
        return False
    row_pages = table.row_pages
    if len(row_pages) > record.row_index and row_pages[record.row_index] is not None:
        return True
    if table.page is not None:
        return True
    if section.page_start is None:
        return False
    return (section.page_end or section.page_start) == section.page_start


def has_value(record: SpecRecord) -> bool:
    """True when the row prints a value in one of its declared columns.

    A record's `min` / `typ` / `max` / `value` are only ever filled for columns
    the table declares, so "any of them is non-empty" *is* "the row's value
    cells are non-empty". A row with none — a band header like `ANALOG SUPPLY
    VOLTAGE RANGE`, or a parameter whose numbers the reconstruction lost — has
    nothing for the grade to be confident about.
    """
    return any(getattr(record, role).strip() for role in VALUE_ROLES)


def unit_expected_but_missing(record: SpecRecord, lexicon: AliasLexicon | None = None) -> bool:
    """True when the record prints no unit but its alias family expects one.

    A row with no value has no unit to lose — a band header like `ANALOG
    SUPPLY VOLTAGE RANGE` is not a measurement whose unit went missing — so
    the clause only ever applies to a row that actually prints a number.
    """
    if not has_value(record):
        return False
    if record.unit.verbatim.strip() or record.unit.canonical.strip():
        return False
    lexicon = load_lexicon() if lexicon is None else lexicon
    entry = lexicon.entry_for(record.symbol, record.name)
    return bool(entry and entry.expect_unit)


def grade_of(record: object) -> Confidence:
    """The record's grade, defensively — an ungraded record reads `UNKNOWN`."""
    value = getattr(record, "confidence", "")
    try:
        return Confidence(getattr(value, "value", value) or Confidence.UNKNOWN)
    except ValueError:  # a grade this build does not know: honestly ungraded
        return Confidence.UNKNOWN


def mix(records: Iterable[object]) -> dict[str, int]:
    """Counts by grade, e.g. `{"high": 412, "medium": 190, "low": 17}`.

    The three grades are always present (a zero is information too); `unknown`
    appears only when something really is ungraded, so its presence in a
    manifest is a signal rather than noise.
    """
    counts = Counter(grade_of(rec) for rec in records)
    out = {grade.value: counts.get(grade, 0) for grade in GRADES}
    if counts.get(Confidence.UNKNOWN):
        out[Confidence.UNKNOWN.value] = counts[Confidence.UNKNOWN]
    return out
