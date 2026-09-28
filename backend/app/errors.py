"""Error responses and request logging.

Every error response has the same JSON shape so the frontend can show it:
``{"detail", "error_type", "request_id", "errors"?, "traceback"? (DEBUG only), "file"?}``
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .logging_setup import request_id_var

log = logging.getLogger("app.errors")


class AppError(Exception):
    """An error with a user-facing message; optionally carries the affected file row."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        error_type: Optional[str] = None,
        file: Optional[dict[str, Any]] = None,
        errors: Optional[list[dict[str, Any]]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.error_type = error_type or (type(cause).__name__ if cause else "AppError")
        self.file = file
        self.errors = errors
        self.cause = cause


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def error_body(
    detail: Any,
    *,
    error_type: str,
    exc: Optional[BaseException] = None,
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {"detail": detail, "error_type": error_type, "request_id": request_id_var.get()}
    body.update({k: v for k, v in extra.items() if v is not None})
    if exc is not None and get_settings().debug:
        body["traceback"] = format_exception(exc)
    return body


def validation_errors(errors: list[dict[str, Any]], prefix: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Normalize pydantic/FastAPI errors to [{loc: 'a.b[0].c', msg, type}]."""
    out = []
    for err in errors:
        loc = ""
        for part in [*prefix, *err.get("loc", ())]:
            loc += f"[{part}]" if isinstance(part, int) else (f".{part}" if loc else str(part))
        out.append({"loc": loc, "msg": err.get("msg", ""), "type": err.get("type", "")})
    return out


def install_error_handling(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            error_body(
                exc.detail, error_type=exc.error_type, exc=exc.cause, file=exc.file, errors=exc.errors
            ),
            status_code=exc.status_code,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            error_body(exc.detail, error_type=f"HTTP {exc.status_code}"),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = validation_errors(list(exc.errors()))
        first = f"{errors[0]['loc']}: {errors[0]['msg']}" if errors else "invalid request"
        log.info("Request validation failed: %s", errors)
        return JSONResponse(
            error_body(f"Validation failed - {first}", error_type="ValidationError", errors=errors),
            status_code=422,
        )

    @app.middleware("http")
    async def _request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception as exc:  # anything not handled above -> JSON 500 with details
                log.exception("Unhandled error on %s %s", request.method, request.url.path)
                response = JSONResponse(
                    error_body(
                        f"Internal server error: {type(exc).__name__}: {exc}"
                        if get_settings().debug
                        else "Internal server error",
                        error_type=type(exc).__name__,
                        exc=exc,
                    ),
                    status_code=500,
                )
            elapsed_ms = (time.perf_counter() - started) * 1000
            level = logging.WARNING if response.status_code >= 400 else logging.INFO
            if request.url.path == "/api/health" and response.status_code < 400:
                level = logging.DEBUG  # docker healthcheck every few seconds
            log.log(level, "%s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code, elapsed_ms)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)
