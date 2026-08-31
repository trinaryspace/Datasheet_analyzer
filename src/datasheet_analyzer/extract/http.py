"""HTTP fetching with on-disk cache.

Every fetched page is stored under cache_dir/http/<sha1(url)>.html so:
- re-running the pipeline never re-hits the network for unchanged URLs,
- tests replay recorded fixtures instead of calling ti.com,
- the corpus build is reproducible and auditable.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Protocol

import requests

log = logging.getLogger(__name__)


class Fetcher(Protocol):
    """Callable URL -> HTML text. Injectable for tests."""

    def __call__(self, url: str) -> str: ...


def cache_name(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".html"


class CachingFetcher:
    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout_s: int = 60,
        delay_s: float = 0.25,
        user_agent: str = "datasheet-analyzer/0.1",
    ):
        self.cache_dir = Path(cache_dir)
        self.timeout_s = timeout_s
        self.delay_s = delay_s
        self.user_agent = user_agent
        self.n_fetches = 0
        self.n_cache_hits = 0

    def __call__(self, url: str) -> str:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached = self.cache_dir / cache_name(url)
        if cached.exists():
            self.n_cache_hits += 1
            return cached.read_text(encoding="utf-8")
        log.info("fetch: %s", url[:110])
        resp = requests.get(url, timeout=self.timeout_s, headers={"User-Agent": self.user_agent})
        resp.raise_for_status()
        cached.write_text(resp.text, encoding="utf-8")
        self.n_fetches += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        return resp.text


class MappingFetcher:
    """Test fetcher: replays a {url: html} mapping, fails loudly on misses."""

    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self.requested: list[str] = []

    def __call__(self, url: str) -> str:
        self.requested.append(url)
        if url not in self.mapping:
            raise AssertionError(f"unexpected network request in test: {url[:120]}")
        return self.mapping[url]


class ReplayFetcher:
    """Hermetic test fetcher: serves only pre-recorded cache files.

    Same on-disk format as CachingFetcher (sha1(url) names), but a cache
    miss is a hard error — tests using it can never touch the network.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        if not self.cache_dir.is_dir():
            raise FileNotFoundError(f"recorded cache not found: {self.cache_dir}")

    def __call__(self, url: str) -> str:
        cached = self.cache_dir / cache_name(url)
        if not cached.exists():
            raise AssertionError(f"no recorded response for: {url[:120]}")
        return cached.read_text(encoding="utf-8")


def binary_cache_name(url: str) -> str:
    """Cache filename for binary responses: sha1(url) + original extension."""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    p = Path(url)
    # Use the last path component's suffix if it looks like an image/binary ext.
    ext = p.suffix.lower()
    if ext not in {".gif", ".png", ".jpg", ".jpeg", ".bin", ".pdf", ".svg"}:
        ext = ".bin"
    return f"{h}{ext}"


class BinaryFetcher(Protocol):
    """Callable URL -> bytes. Injectable for tests."""

    def __call__(self, url: str) -> bytes: ...


class CachingBinaryFetcher:
    """Bytes variant of CachingFetcher: .cache/http-bin/<sha1(url)>.<ext>."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout_s: int = 60,
        delay_s: float = 0.25,
        user_agent: str = "datasheet-analyzer/0.1",
    ):
        self.cache_dir = Path(cache_dir)
        self.timeout_s = timeout_s
        self.delay_s = delay_s
        self.user_agent = user_agent
        self.n_fetches = 0
        self.n_cache_hits = 0

    def __call__(self, url: str) -> bytes:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached = self.cache_dir / binary_cache_name(url)
        if cached.exists():
            self.n_cache_hits += 1
            return cached.read_bytes()
        log.info("fetch binary: %s", url[:110])
        resp = requests.get(url, timeout=self.timeout_s, headers={"User-Agent": self.user_agent})
        resp.raise_for_status()
        cached.write_bytes(resp.content)
        self.n_fetches += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        return resp.content


class ReplayBinaryFetcher:
    """Hermetic test binary fetcher: serves only pre-recorded byte files.

    Same on-disk format as CachingBinaryFetcher (sha1(url) names), but a
    cache miss is a hard error unless `default` bytes are supplied.
    """

    def __init__(self, cache_dir: Path, default: bytes | None = None):
        self.cache_dir = Path(cache_dir)
        self.default = default
        if not self.cache_dir.is_dir() and self.default is None:
            raise FileNotFoundError(f"recorded binary cache not found: {self.cache_dir}")

    def __call__(self, url: str) -> bytes:
        cached = self.cache_dir / binary_cache_name(url)
        if cached.exists():
            return cached.read_bytes()
        if self.default is not None:
            return self.default
        raise AssertionError(f"no recorded binary response for: {url[:120]}")
