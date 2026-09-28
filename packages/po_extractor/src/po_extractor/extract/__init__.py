"""Step 1a: turn a file into VLM input (text and/or images). No model calls here."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from ..config import Settings
from .detect import SUPPORTED_EXTENSIONS, FileType, detect_file_type
from .excel import excel_to_text
from .image import EncodedImage, load_image
from .pdf import read_pdf

ExtractionMethod = Literal["pdf_text_vlm", "pdf_image_vlm", "image_vlm", "excel_text_vlm"]


@dataclass
class ExtractionInput:
    method: ExtractionMethod
    file_type: FileType
    text: Optional[str] = None
    images: list[EncodedImage] = field(default_factory=list)
    pages_total: Optional[int] = None
    notes: list[str] = field(default_factory=list)

    @property
    def pages_sent(self) -> Optional[int]:
        return len(self.images) if self.file_type == "pdf" else None


def build_extraction_input(path: str | Path, file_type: FileType, settings: Settings) -> ExtractionInput:
    """Extract raw content locally according to §3.3."""
    if file_type == "pdf":
        pdf = read_pdf(
            path,
            min_chars_per_page=settings.pdf_min_text_chars_per_page,
            render_dpi=settings.pdf_render_dpi,
            max_pages=settings.max_pdf_pages,
            max_edge_px=settings.image_max_edge_px,
            max_text_chars=settings.max_text_chars,
        )
        notes = [f"Text characters per page: {pdf.page_char_counts}"]
        if pdf.page_count > settings.max_pdf_pages:
            notes.append(f"Only the first {settings.max_pdf_pages} of {pdf.page_count} pages were sent as images")
        if pdf.readable:
            return ExtractionInput("pdf_text_vlm", "pdf", pdf.text, pdf.images, pdf.page_count, notes)
        notes.append(
            f"No usable text layer on every page (threshold {settings.pdf_min_text_chars_per_page} chars) - image only"
        )
        return ExtractionInput("pdf_image_vlm", "pdf", None, pdf.images, pdf.page_count, notes)

    if file_type in ("png", "jpeg"):
        image = load_image(path, settings.image_max_edge_px)
        return ExtractionInput("image_vlm", file_type, images=[image], notes=[f"Image sent at {image.width}x{image.height}px"])

    if file_type == "xlsx":
        text, sheets = excel_to_text(path, settings.max_text_chars)
        return ExtractionInput("excel_text_vlm", "xlsx", text=text, notes=[f"{sheets} sheet(s) read"])

    raise ValueError(f"unhandled file type {file_type!r}")  # pragma: no cover


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "ExtractionInput",
    "ExtractionMethod",
    "FileType",
    "build_extraction_input",
    "detect_file_type",
]
