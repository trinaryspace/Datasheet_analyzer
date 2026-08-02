"""Honest PDF-text backend for companion documents (register maps, errata,
app notes) that TI's HTML viewer does not serve.

Explicitly degraded:
- paragraphs only (the raw text of each TOC-section's page range),
- contextual boilerplate stripping (page numbers only),
- no trusted tables (tables=[]),
- no figures (figures=[]),
- extractor='pdf_text'.
"""

from __future__ import annotations

import logging
from pathlib import Path

from datasheet_analyzer.extract.pdf_structure import page_texts, read_toc
from datasheet_analyzer.models import RawDocument, SectionNode, SourceDocument, TOCEntry

log = logging.getLogger(__name__)


class PdfTextBackend:
    name = "pdf_text"

    def is_available(self) -> tuple[bool, str]:
        try:
            import fitz  # noqa: F401
            return True, ""
        except ImportError as exc:
            return False, str(exc)

    def extract(
        self,
        source: SourceDocument,
        *,
        pdf_toc: list[TOCEntry] | None = None,
    ) -> RawDocument:
        path = Path(source.path)
        toc = pdf_toc if pdf_toc is not None else read_toc(path)
        texts = page_texts(path)

        if not toc:
            # No TOC: one section per page.
            sections = [
                SectionNode(
                    number=str(i + 1),
                    title=f"Page {i + 1}",
                    level=1,
                    page_start=i + 1,
                    page_end=i + 1,
                    paragraphs=_strip_page_furniture(texts[i], i + 1),
                )
                for i in range(len(texts))
            ]
        else:
            sections = []
            for i, entry in enumerate(toc):
                start = entry.page
                if start is None:
                    continue
                # End is the page before the next entry at the same or higher
                # level, or the last page of the document.
                end = len(texts)
                for later in toc[i + 1 :]:
                    if later.page is not None and later.level <= entry.level:
                        end = later.page - 1
                        break
                end = max(start, end)
                paras: list[str] = []
                for p in range(start, end + 1):
                    if 1 <= p <= len(texts):
                        paras.extend(_strip_page_furniture(texts[p - 1], p))
                sections.append(
                    SectionNode(
                        number=entry.number,
                        title=entry.title,
                        level=entry.level,
                        page_start=start,
                        page_end=end,
                        paragraphs=paras,
                    )
                )

        return RawDocument(
            source=source,
            toc=toc,
            sections=sections,
            extractor=self.name,
        )


def _strip_page_furniture(page_text: str, page_number: int) -> list[str]:
    """Return non-empty paragraphs with contextual page-number stripping.

    A digits-only line is stripped ONLY when it equals this page's own printed
    number. All other lines are preserved.
    """
    out: list[str] = []
    for line in page_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Contextual rule: drop this page's own printed page number.
        if stripped == str(page_number):
            continue
        out.append(stripped)
    return out
