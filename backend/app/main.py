"""FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from po_extractor import ConfigError
from po_extractor.validate.master_data import load_customer_master, load_item_master

from .config import DEFAULT_JWT_SECRET, get_po_settings, get_settings
from .db import new_session
from .errors import install_error_handling
from .logging_setup import configure_logging
from .routes import auth, files, health
from .services.processing import mark_stale_processing_rows

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    po_settings = get_po_settings()
    try:
        po_settings.require_llm()
    except ConfigError as exc:
        log.critical("Configuration error: %s", exc)
        raise

    log.info(
        "Starting: model=%s base_url=%s debug=%s log_level=%s",
        po_settings.vlm_model,
        po_settings.deepinfra_base_url,
        settings.debug,
        settings.effective_log_level,
    )
    if settings.debug:
        log.warning("DEBUG mode: error responses include tracebacks. Set DEBUG=false for shared deployments.")
    secret = settings.jwt_secret.get_secret_value()
    if secret == DEFAULT_JWT_SECRET or len(secret) < 32:
        log.warning("JWT_SECRET is the default or shorter than 32 characters - change it before deploying.")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        customers = load_customer_master(settings.customer_master_path)
        items = load_item_master(settings.item_master_path)
        log.info("Master data OK: %d customers, %d items", len(customers.records), len(items.records))
    except Exception as exc:  # reported by /api/health and per upload; do not block startup
        log.error("Master data could not be loaded: %s", exc)

    with new_session() as db:
        interrupted = mark_stale_processing_rows(db)
    if interrupted:
        log.warning("Marked %d stale PROCESSING row(s) as ERROR (interrupted)", interrupted)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.effective_log_level)
    app = FastAPI(
        title="PO Extractor API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    install_error_handling(app)
    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(files.router)
    return app


app = create_app()
