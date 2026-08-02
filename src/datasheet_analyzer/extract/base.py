"""Extraction backend interface + registry (thin and swappable).

A backend turns a SourceDocument into a RawDocument. Backends are
registered by name; the pipeline picks one via `select_backend`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from datasheet_analyzer.models import RawDocument, SourceDocument, TOCEntry


class BackendUnavailableError(RuntimeError):
    pass


class ExtractionBackend(Protocol):
    name: str

    def is_available(self) -> tuple[bool, str]: ...

    def extract(
        self,
        source: SourceDocument,
        *,
        pdf_toc: list[TOCEntry] | None = None,
    ) -> RawDocument: ...


_REGISTRY: dict[str, Callable[[], ExtractionBackend]] = {}


def register(name: str, factory: Callable[[], ExtractionBackend]) -> None:
    _REGISTRY[name] = factory


def get_backend(name: str) -> ExtractionBackend:
    if name not in _REGISTRY:
        raise KeyError(f"unknown extraction backend: {name!r} (have: {sorted(_REGISTRY)})")
    return _REGISTRY[name]()


def available_backends() -> list[str]:
    return sorted(_REGISTRY)
