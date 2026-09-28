"""Exception types.

Document problems (``DocumentError``, model errors) are turned into ``status="ERROR"``
results by ``process_file``. ``ConfigError`` and ``MasterDataError`` propagate to the
caller because they are operator/programmer errors, not problems with one document.
"""

from __future__ import annotations

from typing import Any, Optional

from .config import ConfigError  # noqa: F401  (re-export)


class PoExtractorError(Exception):
    """Base class for all package errors."""


class MasterDataError(PoExtractorError):
    """A master data file is missing, unreadable, or lacks required columns."""


class DocumentError(PoExtractorError):
    """The uploaded document cannot be processed."""


class UnsupportedFileTypeError(DocumentError):
    pass


class FileUnreadableError(DocumentError):
    pass


class ModelUnavailableError(PoExtractorError):
    """Timeout, network or HTTP error when calling the VLM."""


class ExtractionSchemaError(PoExtractorError):
    """The VLM kept returning output that is not valid JSON for the schema."""

    def __init__(
        self,
        message: str,
        *,
        raw_output: Optional[str] = None,
        attempts: int = 0,
        usage: Any = None,
    ) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.attempts = attempts
        self.usage = usage
