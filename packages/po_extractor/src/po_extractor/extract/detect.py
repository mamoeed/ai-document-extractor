"""File type detection from magic bytes (content), with the extension only as a tie-breaker."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Literal, Optional

from ..errors import FileUnreadableError, UnsupportedFileTypeError

FileType = Literal["pdf", "png", "jpeg", "xlsx"]

SUPPORTED_EXTENSIONS: dict[str, FileType] = {
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".xlsx": "xlsx",
}

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .xls/.doc, encrypted .xlsx


def detect_file_type(path: str | Path) -> FileType:
    """Return the detected file type or raise.

    Raises ``UnsupportedFileTypeError`` for anything that is not PDF/PNG/JPEG/XLSX and
    ``FileUnreadableError`` when the extension claims a supported type but the content
    does not match (e.g. a corrupt or truncated file).
    """
    path = Path(path)
    try:
        with path.open("rb") as fh:
            head = fh.read(2048)
    except OSError as exc:
        raise FileUnreadableError(f"Cannot read file: {exc}") from exc

    extension = path.suffix.lower()
    if not head:
        if extension in SUPPORTED_EXTENSIONS:
            raise FileUnreadableError("File is empty")
        raise UnsupportedFileTypeError(_unsupported_message(extension))

    detected = _sniff(head, path)
    if detected:
        return detected

    if head.startswith(_OLE_MAGIC):
        if extension == ".xlsx":
            raise FileUnreadableError("Excel file is password-protected or in legacy format; save it as a plain .xlsx")
        raise UnsupportedFileTypeError("Legacy Office file (.xls/.doc) is not supported; save it as .xlsx or PDF")
    if extension in SUPPORTED_EXTENSIONS:
        kind = SUPPORTED_EXTENSIONS[extension].upper()
        raise FileUnreadableError(f"File has a {extension} extension but its content is not a valid {kind} file")
    raise UnsupportedFileTypeError(_unsupported_message(extension))


def _sniff(head: bytes, path: Path) -> Optional[FileType]:
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except (zipfile.BadZipFile, OSError):
            return None
        if "xl/workbook.xml" in names:
            return "xlsx"
    return None


def _unsupported_message(extension: str) -> str:
    shown = extension or "(no extension)"
    return f"Unsupported file type {shown}. Supported: PDF, PNG, JPG/JPEG, XLSX"
