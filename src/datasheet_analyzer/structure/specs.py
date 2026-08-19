"""RawDocument -> specs.json: normalized, machine-queryable spec records.

A pure transform over Phase 1's span-expanded TableBlocks. No new extraction,
no LLM, no network.
"""

from __future__ import annotations

import re

from datasheet_analyzer.config import SPECS_SCHEMA_VERSION
from datasheet_analyzer.models import RawDocument, SectionNode, SpecRecord, SpecSet, SpecTableInfo
from datasheet_analyzer.structure.aliases import load_lexicon
from datasheet_analyzer.structure.confidence import grade_spec_record
from datasheet_analyzer.structure.corpus import section_stem
from datasheet_analyzer.structure.quantities import annotate_record
from datasheet_analyzer.structure.roles import assign_roles, classify_table
from datasheet_analyzer.structure.units import canonical_unit, normalize_text

_MARKER_RE = re.compile(r"\(\d+\)")


def _cell_for_role(row: list[str], roles: list[str], role: str) -> str:
    """Return the first non-empty cell whose role matches, or ''."""
    for cell, r in zip(row, roles):
        if r == role and cell.strip():
            return cell
    return ""


def table_to_records(
    section: SectionNode, table, table_index: int
) -> tuple[list[SpecRecord], SpecTableInfo]:
    """Convert one TableBlock into SpecRecords + metadata."""
    roles, unmapped_headers = assign_roles(table.headers)
    kind = classify_table(table.headers, roles)
    unknown_units: set[str] = set()
    # One lexicon for the whole table: the confidence rule asks it once per
    # row whether a unit was expected (`structure/confidence.py`).
    lexicon = load_lexicon()

    records: list[SpecRecord] = []
    for row_index, row in enumerate(table.grid):
        if not any(cell.strip() for cell in row):
            continue
        row_text = " ".join(row)
        cited = [m for m in table.cited_markers if m in row_text]
        # Also catch any parenthesized numbers that the HTML sup parser missed.
        cited += [m for m in _MARKER_RE.findall(row_text) if m not in cited]

        unit_text = _cell_for_role(row, roles, "unit")
        # ticket 09: a merged multi-page grid carries per-row pages; a row's
        # own printed page beats the table's caption page, so continuation
        # rows are never cited by a page they do not appear on.
        row_page = table.row_pages[row_index] if len(table.row_pages) > row_index \
            else None
        record = SpecRecord(
            section=section.number,
            section_key=section_stem(section),
            table_index=table_index,
            row_index=row_index,
            symbol=normalize_text(_cell_for_role(row, roles, "symbol")),
            name=normalize_text(_cell_for_role(row, roles, "name")),
            conditions=normalize_text(_cell_for_role(row, roles, "conditions")),
            table_conditions=normalize_text(table.conditions),
            min=normalize_text(_cell_for_role(row, roles, "min")),
            typ=normalize_text(_cell_for_role(row, roles, "typ")),
            max=normalize_text(_cell_for_role(row, roles, "max")),
            value=normalize_text(_cell_for_role(row, roles, "value")),
            unit=canonical_unit(unit_text, unknown=unknown_units),
            footnotes=table.footnotes,
            cited_markers=cited,
            page=row_page if row_page is not None
            else (table.page if table.page is not None else section.page_start),
            row_verbatim=list(row),
        )
        # Graded here, where the evidence still exists: the table's
        # reconstruction provenance, its page pinning and the row's own cells
        # are all gone by the time a record reaches `retrieve/`.
        record.confidence = grade_spec_record(record, table, section, lexicon=lexicon)
        # Phase 6, ticket 02: the parsed numeric layer, filled here for the
        # same reason the grade is - additively, beside the verbatim strings,
        # which it never touches. A cell that is not a quantity leaves
        # `parse_confidence: none` and no number at all.
        annotate_record(record)
        records.append(record)

    info = SpecTableInfo(
        section=section.number,
        table_index=table_index,
        kind=kind,
        n_records=len(records),
        unmapped_headers=unmapped_headers,
    )
    return records, info


def build_specset(raw: RawDocument, part_number: str) -> SpecSet | None:
    """Build a SpecSet from every table in a RawDocument."""
    # pdf_text documents are explicitly degraded: no trusted tables, no specs.
    if raw.extractor == "pdf_text":
        return None
    records: list[SpecRecord] = []
    tables: list[SpecTableInfo] = []
    for section in raw.sections:
        for i, table in enumerate(section.tables):
            recs, info = table_to_records(section, table, i)
            records.extend(recs)
            tables.append(info)

    return SpecSet(
        schema_version=SPECS_SCHEMA_VERSION,
        part_number=part_number,
        doc_hash=raw.source.content_hash,
        records=records,
        tables=tables,
    )
