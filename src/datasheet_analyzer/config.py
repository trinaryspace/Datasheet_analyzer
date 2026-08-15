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

PIPELINE_VERSION = "0.4.0"
# "2": phase 5, ticket 04 added the per-record `confidence` grade to every
# spec and plot record. The field is additive (an older file still loads,
# reading `unknown`), but a corpus published without it answers every query
# ungraded, so the version bump is what makes `batch.skip_reason` republish it
# once instead of skipping it forever — the same publish-cache-key rule
# `SEARCH_SCHEMA_VERSION` already carries for `search_index.json`.
SPECS_SCHEMA_VERSION = "2"
PLOTS_SCHEMA_VERSION = "2"
SEARCH_SCHEMA_VERSION = "1"


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
