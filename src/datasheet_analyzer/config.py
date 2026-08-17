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
# instead of `pdf_text`. The extraction cache is keyed on
# `(content_hash, backend)` and would happily serve the paragraph-only reading
# of a register map forever, so the pipeline version moves to invalidate it —
# exactly the bump the phase plan reserved for this routing change (0.4.0 was
# spent earlier in the phase on the layout engine's own output schema).
PIPELINE_VERSION = "0.5.0"
# "2": phase 5, ticket 04 added the per-record `confidence` grade to every
# spec and plot record. The field is additive (an older file still loads,
# reading `unknown`), but a corpus published without it answers every query
# ungraded, so the version bump is what makes `batch.skip_reason` republish it
# once instead of skipping it forever — the same publish-cache-key rule
# `SEARCH_SCHEMA_VERSION` already carries for `search_index.json`.
# "3": phase 6, ticket 01 gave every published spec record a stable, addressable
# `id` (`rec_1`, `rec_2`, ...) so a derived value's `source` has something to
# point at (ADR 0005). A corpus published without ids answers every provenance
# lookup with nothing, so it republishes once rather than serving unaddressable
# records forever.
# "4": phase 6, ticket 02 added the numeric layer's additive fields (`value_si`,
# `value_low_si`, `value_high_si`, `unit_si`, `value_kind`, `parse_confidence`)
# to every published record. A corpus published without them answers every
# comparison and margin question unparsed, so it republishes once instead of
# looking like a part whose values simply do not parse.
# "5": phase 6, ticket 07 added `section_title` — the printed title of the
# section a row's table was printed under. It is the only identity a design card
# can select a table by on the captionless era of datasheets (where `section` is
# honestly "" for every section), so a corpus published without it yields empty
# limits and power cards on exactly the parts that need them most.
SPECS_SCHEMA_VERSION = "5"
PLOTS_SCHEMA_VERSION = "2"
SEARCH_SCHEMA_VERSION = "1"
# "1": phase 6, ticket 04 — `pins.json`, the pin table as individually citable
# records. New artifact, so version 1; it joins the publish cache key for the
# same reason its siblings did, and a *missing* file reads as current because a
# datasheet that prints no pin table legitimately publishes none.
PINS_SCHEMA_VERSION = "1"
# "1": phase 6, ticket 05 — `registers.json`, the register summary as
# individually citable records. New artifact, so version 1; it joins the
# publish cache key exactly as its siblings do, and a *missing* file reads as
# current because most documents print no register summary at all.
# "2": phase 6, ticket 06 added each register's **bit fields** (`fields`,
# `width`, `unaccounted_bits`, `fields_reason`, and their provenance). A corpus
# published at version 1 answers every bit-field question with nothing, and
# nothing about its source bytes changed, so it republishes once instead of
# reading as a part whose registers simply have no fields.
REGISTERS_SCHEMA_VERSION = "2"
# "1": phase 6, ticket 07 — `cards/<name>.json`, the design cards. New artifact,
# so version 1. Unlike its siblings it is *not* gated on a missing file reading
# as current: every published part gets all four cards, an honestly empty one
# included, so an absent card file really is staleness (`publish.cards_current`).
CARDS_SCHEMA_VERSION = "1"

# The version of the *derivation rules* (ADR 0005 / invariant 8). Derived
# artifacts — design cards and anything else computed from records by a named
# pure function — are not extracted, so nothing about the source bytes changes
# when a rule does: the extraction cache is keyed on (content_hash, backend)
# and cannot notice. This constant is therefore stamped into `manifest.json`
# and read by `batch.skip_reason`, so changing a derivation rule regenerates
# the derived artifacts instead of leaving stale ones behind. Bump it whenever
# a derivation rule changes what it produces.
# "2": phase 6, ticket 04 — `pins.json`, a wholly new derived artifact with a
# new derived field (`type`, from `registry/pin_types.yaml`) and a new derived
# warning (the package cross-check). Nothing else moves for it: no source byte
# changes, no extractor version bumps, and `pins_current` reads a *missing*
# file as current, so a part built before this ticket would skip forever and
# never gain a pin table it does print — after which `pin_gap()` would state
# something false about the datasheet.
# "3": phase 6, ticket 05 — `registers.json`, a second derived artifact, with
# two derived fields (`address.value`, the parsed integer a `--addr` lookup
# resolves by, and `reset`, read from the register's printed declaration
# heading) and a new derived warning (how many registers state a reset). Same
# reasoning as "2": nothing in the extraction gate notices a new derived
# artifact, so without the bump a part built one ticket earlier would skip
# forever and keep answering register questions with nothing.
# "4": phase 6, ticket 06 — register **bit fields**, with two more derived
# values per register (`bits`, from `parse_bit_range` or the geometric
# `bit_header_span`, and `width`, from the printed reset word) and a new derived
# warning (how many registers publish a field set). Same reasoning again: a part
# built at ticket 05 would skip forever and keep publishing registers with no
# fields, which reads as a document that prints none.
# "5": phase 6, ticket 07 — the design cards themselves, the artifact this
# constant was named for. Every value on them is derived (a selected cell, a
# reduction over rows, a computed margin, a pin count), the selectors live in
# `registry/cards.yaml`, and none of it is visible to any other gate: a part
# built at ticket 06 has no `cards/` directory at all and would keep skipping.
CARD_VERSION = "5"


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

    # `dsa batch` worker pool: --workers flag overrides; this env-backed
    # value is the default; 4 is the fallback.
    batch_workers: int = Field(default=4, ge=1)

    # Derived-artifact rule version (`DSA_CARD_VERSION`), stamped into every
    # manifest and part of the publish cache key. `CARD_VERSION` above is the
    # value this build ships; the env var exists so a derivation can be pinned
    # while a rule is in flight, exactly as `--force` exists for the hash gate.
    card_version: str = Field(default=CARD_VERSION, min_length=1)

    def resolve(self) -> Settings:
        self.parts_dir = self.parts_dir.resolve()
        self.cache_dir = self.cache_dir.resolve()
        self.projects_dir = self.projects_dir.resolve()
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
