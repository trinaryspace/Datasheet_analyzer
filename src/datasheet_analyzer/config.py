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

PIPELINE_VERSION = "0.1.0"
SPECS_SCHEMA_VERSION = "1"
PLOTS_SCHEMA_VERSION = "1"


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

    # LLM enrichment (INDEX.md descriptions). Without a key the pipeline
    # falls back to deterministic extractive descriptions and says so.
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    model: str = "claude-haiku-4-5"
    max_output_tokens: int = 4096
    llm_descriptions: bool = True

    # INDEX.md must stay small enough to live in an agent's context.
    index_token_budget: int = 3000

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
