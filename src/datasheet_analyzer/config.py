"""Env-driven settings (pydantic-settings).

Custom settings use the ``DSA_`` prefix; the Anthropic key is the plain
``ANTHROPIC_API_KEY`` (matches the SDK). Importing this module has no
filesystem side effects; directories are created by the code that writes to
them, not at import time.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# "0.5.0": phase 6, ticket 05 routes `DocType.REGISTER_MAP` to `pdf_layout`
# instead of the paragraphs-only `pdf_text` backend (`vendor.select_backend`).
# The extraction cache is keyed by `(content_hash, backend)`, so the old entry
# is not *wrong* — it is a reading of the same bytes by a different backend,
# and it would keep being served to every part that already skipped. The bump
# is what makes `batch.skip_reason` rebuild those parts once so their register
# maps come back with tables in them. 0.4.0 is published (AFE7950, AFE7953).
PIPELINE_VERSION = "0.5.0"
# "2": phase 5, ticket 04 added the per-record `confidence` grade to every
# spec and plot record. The field is additive (an older file still loads,
# reading `unknown`), but a corpus published without it answers every query
# ungraded, so the version bump is what makes `batch.skip_reason` republish it
# once instead of skipping it forever — the same publish-cache-key rule
# `SEARCH_SCHEMA_VERSION` already carries for `search_index.json`.
# "3": phase 6, ticket 01 gave every spec record a stable, addressable `id`
# (`rec_s4.5-t2-r13`) and ticket 02 adds the parsed numeric layer beside the
# verbatim strings. A derived artifact cites a record by that id, so a
# `specs.json` published without one cannot be the target of a card's
# `source` — the bump is what republishes it once instead of leaving every
# citation on that part unresolvable.
# 4: a spec record id is keyed on the section's file stem, not its
# printed number, so records in unnumbered sections stop colliding
# (phase 6.5, ticket 08). Every id written before this changes.
SPECS_SCHEMA_VERSION = "4"
# "2" also carries the GUI change: `PlotRecord.file` is *library*-relative
# once a document is published into the shared store, not part-relative. A
# `plots.json` still at "1" predates both changes and must be republished
# rather than resolved against the wrong root.
PLOTS_SCHEMA_VERSION = "2"
SEARCH_SCHEMA_VERSION = "1"
# On-disk schema of one `<library_dir>/<content_hash>.json` record. Every
# `LibraryDocument` file carries it; a file with an unknown version is
# skipped with a warning rather than guessed at, the same rule the other
# schema versions carry.
LIBRARY_SCHEMA_VERSION = "1"
# Phase 6 derived artifacts, each gated the same way its extracted siblings
# are: `pins.json`, `registers.json` and `cards/<kind>.json` carry their
# schema version on disk, and a file at an older one republishes once rather
# than being served forever in a shape its reader no longer expects.
# The version of the *structure-stage* work that runs inside a cached
# extraction. `pipeline._extract_document` pins table pages and per-row pages
# (`structure/pagemap.py`) after the backend returns and before the result is
# written to `.cache/extract/<hash>__<backend>.json`, so that code's output
# lives inside the cached `RawDocument` while none of its identity did.
# Invariant 6 says a change that alters cached output must invalidate it, and
# a backend's `output_version` cannot speak for a producer that is not the
# backend: bumping `PdfLayoutBackend.output_version` to `tables-09` in phase
# 6.5 re-extracted every `pdf_layout` document and left every `ti_html` one
# served from a cache written before per-row pinning existed (measured:
# LMX1204's `0x5A` row still cited p.32 for a row printed on p.33, and only
# `dsa build --no-cache` produced a correct corpus).
#
# Bump this whenever a change under `structure/` alters what
# `_extract_document` stores. It is embedded in `RawDocument.structure_version`
# and checked beside `extractor_version`.
# "1": the field's first value. Every cache entry written before it carries
# "" and is re-extracted once.
# "2": `pagemap.reconcile_table_pages` — where a table's pinned page and its
# pinned rows disagree, the rows win and the table's page follows them. Three
# tables of 158 moved across the eleven built parts, and one of them
# (`Table 1-25. R24 Register Field Descriptions`) was the page eight published
# bit fields were citing.
STRUCTURE_STAGE_VERSION = "2"
PINS_SCHEMA_VERSION = "1"
# "2": a register record's id folds in the document it was printed in
# (`models.register_record_id`), because `(table_index, row_index)` is unique
# only inside one document and LMX1204 publishes two register maps printing
# the same 35 rows — 70 records that computed 35 ids. Every register id
# written before this changes; a record published without a `doc_key` keeps
# the old shape, so citations already written still resolve.
REGISTERS_SCHEMA_VERSION = "2"
# 2: cards carry `corpus_key`, so a document that moved between the part
# and the shared store invalidates the card that cited it (phase 6.5, 03).
CARDS_SCHEMA_VERSION = "2"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Directories (resolved to absolute against cwd in resolve())
    parts_dir: Path = Path("parts")
    cache_dir: Path = Path(".cache")
    # Projects: the noun above `part`. One directory per project, holding
    # `project.json` (the explicit part list) and `PROJECT_INDEX.md`.
    projects_dir: Path = Path("projects")
    # The Library: one `<content_hash>.json` per registered document, holding
    # its `SourceDocument`, its applicability and its user labels (ADR 0005).
    # This is the authoritative inventory; per-part `sources.json` is a
    # derived view regenerated at publish time.
    library_dir: Path = Path("library")
    # Saved conversations: one `<session_id>.json` each, so a week-old
    # question and the pages it cited survive a restart.
    sessions_dir: Path = Path("sessions")

    # LLM enrichment (INDEX.md descriptions). Without a key the pipeline
    # falls back to deterministic extractive descriptions and says so.
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    model: str = "claude-haiku-4-5"
    max_output_tokens: int = 4096
    llm_descriptions: bool = True

    # INDEX.md must stay small enough to live in an agent's context.
    index_token_budget: int = 3000

    # PROJECT_INDEX.md is the same promise one level up: the single
    # always-loadable file for a whole design. Bigger than a part's index
    # because it summarizes several, still hard-bounded.
    project_index_token_budget: int = Field(default=4000, ge=1)

    # `dsa ask` answer packs: the default token budget one pack may spend.
    # `--budget N` overrides per call; the pack announces any truncation and
    # names both this setting and the flag.
    ask_budget: int = Field(default=4000, ge=1)

    # `dsa serve --mcp`: the hard cap on every MCP tool response and every MCP
    # resource read. A client cannot bound a payload it did not build, so the
    # server bounds it and *says so* — truncation always carries a notice
    # naming this setting, never silent loss.
    mcp_max_tokens: int = Field(default=6000, ge=1)

    # TI document viewer fetching
    ti_base_url: str = "https://www.ti.com"
    http_timeout_s: int = 60
    http_delay_s: float = 0.25  # politeness between section fetches
    user_agent: str = "datasheet-analyzer/0.1 (research tooling)"

    # Plot pixel rendering (PDF fallback)
    plot_image_dpi: int = 150

    # Design cards (`DSA_CARD_VERSION`, phase 6). Not a schema version: it is
    # the version of the *derivation rules* — which records a card selects and
    # what pure functions it computes from them. It participates in the
    # publish cache key (`publish.writer.cards_current`, read by the batch
    # skip gate), so changing a selector or a margin rule forces regeneration
    # instead of silently leaving stale cards on disk. Bump it in the commit
    # that changes a rule; overriding it by env is how a rule change is tried
    # against a corpus without editing the source.
    card_version: str = "1"

    # `dsa batch` worker pool: --workers flag overrides; this env-backed
    # value is the default; 4 is the fallback.
    batch_workers: int = Field(default=4, ge=1)

    # --- `dsa serve` (the local GUI) ----------------------------------------
    # The chat agent's model. Deliberately *not* `model`: index writing is a
    # cheap per-section summarization job that `claude-haiku-4-5` does well,
    # and an agentic tool loop answering an engineer's question is not.
    chat_model: str = "claude-opus-5"
    # One assistant turn's output budget, and the cap one tool response may
    # spend inside that turn. The tool cap is *not* `mcp_max_tokens`: an MCP
    # response is capped for a model reading over a wire, and this consumer
    # renders full result sets in a browser.
    chat_max_tokens: int = Field(default=16000, ge=1)
    chat_tool_max_tokens: int = Field(default=8000, ge=1)
    # A local, single-user tool binds loopback. Listening on 0.0.0.0 would
    # publish an unauthenticated corpus browser to the network.
    serve_host: str = "127.0.0.1"
    serve_port: int = Field(default=8765, ge=1, le=65535)
    # Analyze-run worker pool, the same shape as `batch_workers`: the GUI's
    # background jobs and its directory scan are both bounded by it.
    analyze_workers: int = Field(default=4, ge=1)

    def resolve(self) -> Settings:
        self.parts_dir = self.parts_dir.resolve()
        self.cache_dir = self.cache_dir.resolve()
        self.projects_dir = self.projects_dir.resolve()
        self.library_dir = self.library_dir.resolve()
        self.sessions_dir = self.sessions_dir.resolve()
        return self

    @property
    def llm_available(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings().resolve()


def reset_settings_cache() -> None:
    """Test hook: drop the cached settings so env changes take effect."""
    get_settings.cache_clear()
