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

A plot's **axis catalog** (phase 6, ticket 08) is graded separately from the
plot, because it is read off different evidence: the plot's grade is citation
precision, the axis grade is how much of the axis pair the page's own text
stated. An axis is complete when it states a title, a printed tick range and a
spacing rule; both axes complete is `high`, one is `medium`, neither is `low` —
which is the honest reading of a plot drawn as a raster image, where the axes
exist only as pixels. `UNKNOWN` there means no reading was attempted at all.

Pins (phase 6, ticket 04) are read off a grid, so their rule is the spec rule
with the pin's own "did the row say anything" clause: a **rescued** grid is
`low`, because the columns a pin table is entirely made of were not the ones
the table declared; a pin whose row printed **no name** is `low` too, since a
designator with no signal on it is not something to wire; a section-range page
is `medium`; everything else is `high`. There is no unit clause — a pin has no
value and therefore no unit to be missing.

Registers (phase 6, ticket 05) are read off a grid too, so theirs is the pin
rule with one addition: an address the grammar could not read as an integer is
`medium`, because the printed string is still the answer while `dsa regs
--addr` cannot reach it.

A register's **bit-field set** (phase 6, ticket 06) is graded separately from
the register, because it is read off a different table, and its rule is the one
place where a rescued grid is *not* automatically `low`: a field set only
publishes at all once it tiles the register's width with no overlap and no
overflow (`structure/bitfields.py`), and a mis-split grid does not accidentally
tile a register. So: bits of the width that no field claims are `low` (the list
is incomplete and the page has to be opened to see what is missing), a
header-declared grid that covers the width is `high`, and a rescued grid that
covers it is `medium` — trustworthy enough to program against, with the
reconstruction still saying "confirm on the printed page".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from datasheet_analyzer.models import (
    RECONSTRUCTION_RESCUED,
    Confidence,
    PinRecord,
    PlotRecord,
    RegisterRecord,
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


def grade_pin_record(
    record: PinRecord, table: TableBlock, section: SectionNode
) -> Confidence:
    """Grade one pin row against the rule in this module's docstring."""
    if table.reconstruction == RECONSTRUCTION_RESCUED:
        return Confidence.LOW
    if not record.name.strip():
        return Confidence.LOW
    if not page_is_exact(record, table, section):
        return Confidence.MEDIUM
    return Confidence.HIGH


def grade_register_record(
    record: RegisterRecord, table: TableBlock, section: SectionNode
) -> Confidence:
    """Grade one register row against the rule in this module's docstring.

    The pin rule with the register's own "did the row say anything" clause: a
    **rescued** grid is `low`, a register whose row printed **no name** is
    `low` (an address with no acronym on it is not something to program), a
    section-range page is `medium`, and an address the grammar could not read
    as a number is `medium` — the printed string is still the answer, but
    `dsa regs --addr` cannot reach it, and a caller deserves to be told.
    """
    if table.reconstruction == RECONSTRUCTION_RESCUED:
        return Confidence.LOW
    if not record.name.strip():
        return Confidence.LOW
    if record.address.value is None:
        return Confidence.MEDIUM
    if not page_is_exact(record, table, section):
        return Confidence.MEDIUM
    return Confidence.HIGH


def grade_register_fields(record: RegisterRecord, table: TableBlock) -> Confidence:
    """Grade one register's published bit-field set (phase 6, ticket 06).

    `table` is the **field** table the set was read from, not the summary table
    the register came from. Only a validated set reaches this — an overlapping
    or overflowing one is refused whole and publishes no fields — so what is
    left to say is how completely it covers the register and how the grid that
    carried it was reconstructed.
    """
    if record.unaccounted_bits:
        return Confidence.LOW
    if table.reconstruction == RECONSTRUCTION_RESCUED:
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


def grade_plot_axes(record: PlotRecord) -> Confidence:
    """Grade a plot's **axis catalog**, separately from the plot (ticket 08).

    Deliberately its own grade: the record's `confidence` says how precisely the
    figure can be cited, which is true of a raster plot whose axes are pixels
    just as much as of a vector one. This grade says how far the *axis block* can
    be trusted, and its rule is the one in the docstring above.

    An axis is complete when it states a title, a printed tick range and a
    spacing rule — a range with no title cannot be filtered on by name, and a
    range with no scale may not be interpolated across. Both complete is `high`;
    one complete is `medium`, which is a real and useful state (a figure whose y
    axis reads and whose x tick labels the PDF laid out unreadably is still
    findable by `--y-label`); neither is `low`, with every field null, which is
    what a raster plot and a figure that is not a plot at all both honestly are.
    """
    x_complete = bool(record.x_label) and record.x_min is not None and record.x_scale
    y_complete = bool(record.y_label) and record.y_min is not None and record.y_scale
    if x_complete and y_complete:
        return Confidence.HIGH
    if x_complete or y_complete:
        return Confidence.MEDIUM
    return Confidence.LOW


def page_is_exact(
    record: SpecRecord | PinRecord | RegisterRecord,
    table: TableBlock,
    section: SectionNode,
) -> bool:
    """True when the row cites one printed page rather than a section's range.

    Exact means the page was *pinned*: the row's own page on a merged
    multi-page grid, or the table's pinned page. The one other case that pins a
    row unambiguously is a section that occupies a single page — there the
    range and the printed page are the same number.

    A negative `row_index` is a row read out of the block's *header* row
    (`device_tables.HEADER_ROW_INDEX`), which has no `row_pages` entry; the
    bounds check is what stops it indexing the list from the end and adopting
    the last row's page.
    """
    if record.page is None:
        return False
    row_pages = table.row_pages
    if 0 <= record.row_index < len(row_pages) and row_pages[record.row_index] is not None:
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


def unit_expected_but_missing(
    record: SpecRecord, lexicon: AliasLexicon | None = None
) -> bool:
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


def weakest(*grades: Confidence) -> Confidence:
    """The weakest of the grades a computed value rests on.

    A number computed from a `low` row is no better than that row, so grading it
    by the stronger operand would make the weaker one invisible — and a design
    card's margin and a cross-part delta (phase 6, tickets 07 and 09) are both
    exactly that kind of number. Still metadata, never a filter. `UNKNOWN` is the
    weakest of all: a corpus that never graded a row has not promised anything
    about it.
    """
    order = [*GRADES, Confidence.UNKNOWN]
    return max(grades, key=order.index) if grades else Confidence.UNKNOWN


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
