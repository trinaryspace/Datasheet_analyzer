"""Extract stage: SourceDocument -> RawDocument via pluggable backends."""

from datasheet_analyzer.extract.base import (
    BackendUnavailableError,
    ExtractionBackend,
    available_backends,
    get_backend,
    register,
)
from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.extract.pdf_text import PdfTextBackend
from datasheet_analyzer.extract.ti_html import TiHtmlBackend

register(TiHtmlBackend.name, TiHtmlBackend)
register(PdfTextBackend.name, PdfTextBackend)
register(PdfLayoutBackend.name, PdfLayoutBackend)

DEFAULT_BACKEND = TiHtmlBackend.name

__all__ = [
    "DEFAULT_BACKEND",
    "BackendUnavailableError",
    "ExtractionBackend",
    "PdfLayoutBackend",
    "PdfTextBackend",
    "TiHtmlBackend",
    "available_backends",
    "get_backend",
    "register",
]
