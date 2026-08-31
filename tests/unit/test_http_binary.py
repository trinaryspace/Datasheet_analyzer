"""Tests for binary HTTP fetchers."""

from __future__ import annotations

import pytest

from datasheet_analyzer.extract.http import (
    CachingBinaryFetcher,
    ReplayBinaryFetcher,
    binary_cache_name,
)


def test_binary_cache_name_preserves_known_extensions():
    assert binary_cache_name("https://ti.com/ods/images/SBASA41E/GUID-low.gif").endswith(".gif")
    assert binary_cache_name("https://ti.com/ods/images/SBASA41E/GUID.png").endswith(".png")
    assert binary_cache_name("https://ti.com/ods/images/SBASA41E/GUID.jpg").endswith(".jpg")
    assert binary_cache_name("https://ti.com/ods/images/SBASA41E/GUID").endswith(".bin")


def test_caching_binary_fetcher_roundtrip(tmp_path, monkeypatch):
    cache_dir = tmp_path / "bin_cache"
    url = "https://example.com/plot.gif"
    payload = b"GIF89a\x01\x00\x01\x00\x00\x00\x00!"

    calls: list[str] = []

    def fake_get(u, *, timeout, headers):
        calls.append(u)
        assert u == url

        class Resp:
            status_code = 200
            content = payload

            @staticmethod
            def raise_for_status():
                pass

        return Resp()

    monkeypatch.setattr("datasheet_analyzer.extract.http.requests.get", fake_get)

    fetcher = CachingBinaryFetcher(cache_dir)
    first = fetcher(url)
    assert first == payload
    assert fetcher.n_fetches == 1
    assert fetcher.n_cache_hits == 0

    second = fetcher(url)
    assert second == payload
    assert fetcher.n_fetches == 1
    assert fetcher.n_cache_hits == 1
    assert len(calls) == 1

    cached = cache_dir / binary_cache_name(url)
    assert cached.exists()
    assert cached.read_bytes() == payload


def test_replay_binary_fetcher_miss_raises(tmp_path):
    cache_dir = tmp_path / "empty"
    cache_dir.mkdir()
    fetcher = ReplayBinaryFetcher(cache_dir)
    with pytest.raises(AssertionError):
        fetcher("https://example.com/missing.gif")


def test_replay_binary_fetcher_default_stand_in(tmp_path):
    cache_dir = tmp_path / "empty"
    cache_dir.mkdir()
    default = b"GIF89a\x01\x00\x01\x00"
    fetcher = ReplayBinaryFetcher(cache_dir, default=default)
    assert fetcher("https://example.com/anything.gif") == default


def test_replay_binary_fetcher_serves_recorded_file(tmp_path):
    cache_dir = tmp_path / "rec"
    cache_dir.mkdir()
    url = "https://example.com/recorded.gif"
    payload = b"recorded-bytes"
    (cache_dir / binary_cache_name(url)).write_bytes(payload)
    fetcher = ReplayBinaryFetcher(cache_dir)
    assert fetcher(url) == payload
