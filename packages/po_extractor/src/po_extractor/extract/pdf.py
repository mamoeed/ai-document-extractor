"""PDF handling with pypdfium2: text-layer check, text extraction, page rendering."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

from ..errors import FileUnreadableError
from .image import EncodedImage, encode_image, prepare_image

# PDFium is not thread-safe; the backend processes files in a thread pool.
_PDFIUM_LOCK = threading.Lock()


@dataclass
class PdfContent:
    page_count: int
    page_char_counts: list[int]
    readable: bool  # every page has a usable text layer
    text: str | None  # "## Page N" joined text (only when readable)
    images: list[EncodedImage] = field(default_factory=list)


def read_pdf(
    path: str | Path,
    *,
    min_chars_per_page: int,
    render_dpi: int,
    max_pages: int,
    max_edge_px: int,
    max_text_chars: int,
) -> PdfContent:
    """Open the PDF, decide whether it is programmatically readable, and render page images.

    A PDF is *readable* when every page has at least ``min_chars_per_page`` non-whitespace
    text characters. Page images (up to ``max_pages``) are always rendered: readable PDFs
    send text + images, scanned PDFs send images only.
    """
    with _PDFIUM_LOCK:
        try:
            document = pdfium.PdfDocument(str(path))
        except pdfium.PdfiumError as exc:
            raise FileUnreadableError(f"Cannot open PDF: {exc}") from exc
        try:
            page_count = len(document)
            if page_count == 0:
                raise FileUnreadableError("PDF has no pages")
            texts = [_page_text(document, index) for index in range(page_count)]
            images = [
                _render_page(document, index, render_dpi, max_edge_px) for index in range(min(page_count, max_pages))
            ]
        except FileUnreadableError:
            raise
        except Exception as exc:
            raise FileUnreadableError(f"Cannot read PDF: {type(exc).__name__}: {exc}") from exc
        finally:
            document.close()

    char_counts = [sum(1 for ch in text if not ch.isspace()) for text in texts]
    readable = all(count >= min_chars_per_page for count in char_counts)
    text = None
    if readable:
        text = "\n\n".join(f"## Page {index + 1}\n{page.strip()}" for index, page in enumerate(texts))
        if len(text) > max_text_chars:
            text = text[:max_text_chars] + "\n[... truncated ...]"
    return PdfContent(page_count, char_counts, readable, text, images)


def _page_text(document: pdfium.PdfDocument, index: int) -> str:
    page = document[index]
    try:
        textpage = page.get_textpage()
        try:
            text = textpage.get_text_range()
        finally:
            textpage.close()
    finally:
        page.close()
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("￾", "").replace("\x02", "")


def _render_page(document: pdfium.PdfDocument, index: int, dpi: int, max_edge_px: int) -> EncodedImage:
    page = document[index]
    try:
        bitmap = page.render(scale=dpi / 72)
        try:
            # to_pil() may share memory with the bitmap: encode before closing it.
            return encode_image(prepare_image(bitmap.to_pil(), max_edge_px), "png")
        finally:
            bitmap.close()
    finally:
        page.close()
