"""Purchase order extraction (VLM) and deterministic master-data matching.

Framework-free: no FastAPI / SQLAlchemy imports in this package.
"""

from .config import ConfigError, Settings
from .errors import MasterDataError
from .pipeline import process_file, validate_order
from .schemas import ExtractedOrder, Issue, IssueCode, Meta, ProcessingResult

__all__ = [
    "ConfigError",
    "ExtractedOrder",
    "Issue",
    "IssueCode",
    "MasterDataError",
    "Meta",
    "ProcessingResult",
    "Settings",
    "process_file",
    "validate_order",
]

__version__ = "0.1.0"
