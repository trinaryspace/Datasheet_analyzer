"""Settings for the batch runner: parallel-worker default and its env hook.

`--workers N` on the CLI is the explicit override; `DSA_BATCH_WORKERS` is
the default when the flag is absent; 4 is the fallback. Bad values (below 1)
are rejected at the settings boundary so the runner never meets a
zero-width pool.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from datasheet_analyzer.config import Settings


def test_batch_workers_defaults_to_four(monkeypatch):
    monkeypatch.delenv("DSA_BATCH_WORKERS", raising=False)
    assert Settings().batch_workers == 4


def test_batch_workers_reads_dsa_env_var(monkeypatch):
    monkeypatch.setenv("DSA_BATCH_WORKERS", "2")
    assert Settings().batch_workers == 2


def test_batch_workers_explicit_field_wins_over_env(monkeypatch):
    monkeypatch.setenv("DSA_BATCH_WORKERS", "2")
    assert Settings(batch_workers=3).batch_workers == 3


def test_batch_workers_rejects_below_one(monkeypatch):
    monkeypatch.setenv("DSA_BATCH_WORKERS", "0")
    with pytest.raises(ValidationError):
        Settings()
