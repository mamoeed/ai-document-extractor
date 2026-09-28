"""Logging: one stdout handler, request id on every line, noisy libraries silenced."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] [req=%(request_id)s] %(message)s"

# These log request bodies (base64 images!) or are very chatty at DEBUG level.
_QUIET_LOGGERS = ("openai", "httpx", "httpcore", "multipart", "python_multipart", "PIL", "sqlalchemy.engine",
                  "asyncio", "watchfiles")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # Route uvicorn's own loggers through our handler/format; our middleware logs requests.
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
