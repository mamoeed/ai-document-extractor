import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from po_extractor.validate.master_data import load_customer_master, load_item_master

from ..config import AppSettings, get_settings
from ..db import get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db), settings: AppSettings = Depends(get_settings)) -> JSONResponse:
    """DB reachable and both master files load. Does NOT call the VLM (no token cost)."""
    details: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        details["db"] = "ok"
    except Exception as exc:
        db_ok = False
        details["db"] = f"{type(exc).__name__}: {exc}"
        log.error("Health check: database error: %s", exc)
    try:
        customers = load_customer_master(settings.customer_master_path)
        items = load_item_master(settings.item_master_path)
        master_ok = True
        details["master_data"] = f"{len(customers.records)} customers, {len(items.records)} items"
    except Exception as exc:
        master_ok = False
        details["master_data"] = f"{type(exc).__name__}: {exc}"
        log.error("Health check: master data error: %s", exc)

    ok = db_ok and master_ok
    body = {"ok": ok, "db": db_ok, "master_data": master_ok, "details": details, "debug": settings.debug}
    return JSONResponse(body, status_code=200 if ok else 503)
