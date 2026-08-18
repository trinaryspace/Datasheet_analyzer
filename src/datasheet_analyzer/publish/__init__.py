"""Publish stage: write the on-disk corpus + machine-readable manifest."""

from datasheet_analyzer.publish.search_index import (
    INDEX_FILENAME,
    build_search_index,
    search_index_current,
)
from datasheet_analyzer.publish.writer import (
    CARDS_DIRNAME,
    REV_DIR_MARKER,
    REVISION_DIFF_FILENAME,
    cards_current,
    doc_dir_name,
    doc_dir_name_for_source,
    errata_current,
    pins_current,
    plots_current,
    registers_current,
    revision_slug,
    specs_current,
    write_cards,
    write_corpus,
    write_errata,
    write_revision_diff,
)

__all__ = [
    "CARDS_DIRNAME",
    "INDEX_FILENAME",
    "REVISION_DIFF_FILENAME",
    "REV_DIR_MARKER",
    "build_search_index",
    "cards_current",
    "doc_dir_name",
    "doc_dir_name_for_source",
    "errata_current",
    "pins_current",
    "plots_current",
    "registers_current",
    "revision_slug",
    "search_index_current",
    "specs_current",
    "write_cards",
    "write_corpus",
    "write_errata",
    "write_revision_diff",
]
