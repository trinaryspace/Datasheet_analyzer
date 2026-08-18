"""Publish stage: write the on-disk corpus + machine-readable manifest.

Ticket 04 gave a document two possible homes — under the part that references
it, or once in the shared store — so *reading a published corpus back* is now
part of this package's surface, not a path every caller can spell for itself.
`document_dirs()` answers "where did this manifest's documents actually land",
`resolve_artifact_ref()` resolves one reference, and `manifest_artifacts()` /
`missing_artifacts()` report the lot with existence checked. They are
re-exported here (integration, ticket 22) because the callers that need them
— the batch skip gate, the CLI, the workbench — import from the package.
"""

from datasheet_analyzer.publish.plots import (
    StalePlotsSchemaError,
    artifact_root,
    load_plotset,
    resolve_plot_file,
)
from datasheet_analyzer.publish.search_index import (
    INDEX_FILENAME,
    build_search_index,
    search_index_current,
)
from datasheet_analyzer.publish.writer import (
    LIBRARY_REF_PREFIX,
    ArtifactRef,
    doc_dir_name,
    doc_dir_name_for_source,
    document_dirs,
    is_library_ref,
    library_root_of,
    manifest_artifacts,
    missing_artifacts,
    plots_current,
    read_manifest,
    resolve_artifact_ref,
    specs_current,
    write_corpus,
)

__all__ = [
    "INDEX_FILENAME",
    "LIBRARY_REF_PREFIX",
    "ArtifactRef",
    "StalePlotsSchemaError",
    "artifact_root",
    "build_search_index",
    "doc_dir_name",
    "doc_dir_name_for_source",
    "document_dirs",
    "is_library_ref",
    "library_root_of",
    "load_plotset",
    "manifest_artifacts",
    "missing_artifacts",
    "plots_current",
    "read_manifest",
    "resolve_artifact_ref",
    "resolve_plot_file",
    "search_index_current",
    "specs_current",
    "write_corpus",
]
