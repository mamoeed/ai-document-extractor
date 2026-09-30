"""Upload -> process_file -> DB row, and human review -> validate_order -> DB row."""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, defer

from po_extractor import ExtractedOrder, MasterDataError, Meta, ProcessingResult, process_file, validate_order
from po_extractor.extract import SUPPORTED_EXTENSIONS

from ..config import AppSettings, get_po_settings
from ..errors import AppError, format_exception, validation_errors
from ..models import ProcessedFile, utcnow
from ..schemas import to_detail
from .review_diff import diff_orders
from .storage import safe_filename, save_upload

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=10)


# ------------------------------------------------------------------ upload


async def handle_upload(upload: UploadFile, user: str, db: Session, settings: AppSettings) -> ProcessedFile:
    file_id = uuid.uuid4()
    name = safe_filename(upload.filename)
    stored = await save_upload(upload, settings.upload_dir / str(file_id) / name, settings.max_upload_bytes)
    log.info("Upload %s saved (%d bytes, sha256=%s…) by %s", name, stored.size, stored.sha256[:12], user)

    # Insert first so a crash mid-processing still leaves a visible row.
    row = ProcessedFile(
        id=file_id,
        original_filename=name,
        stored_path=str(stored.path),
        file_type=SUPPORTED_EXTENSIONS.get(Path(name).suffix.lower(), Path(name).suffix.lower().lstrip(".") or None),
        file_sha256=stored.sha256,
        uploaded_by=user,
        status="PROCESSING",
        needs_human_review=False,
        issues=[],
    )
    db.add(row)
    db.commit()

    try:
        result: ProcessingResult = await run_in_threadpool(
            process_file,
            stored.path,
            settings.customer_master_path,
            settings.item_master_path,
            get_po_settings(),
        )
    except MasterDataError as exc:
        log.error("Master data error while processing %s: %s", name, exc)
        _mark_failed(db, row, f"Master data error: {exc}", exc, settings)
        raise AppError(500, f"Master data error: {exc}", file=_detail(row), cause=exc) from exc
    except Exception as exc:
        log.exception("Unexpected error while processing %s", name)
        _mark_failed(db, row, f"{type(exc).__name__}: {exc}", exc, settings)
        raise AppError(
            500, f"Unexpected error while processing '{name}': {type(exc).__name__}: {exc}", file=_detail(row), cause=exc
        ) from exc

    _apply_result(row, result, first_run=True)
    if result.status == "ERROR":
        log.warning("%s -> ERROR: %s", name, "; ".join(f"{i.code}: {i.message}" for i in result.issues))
    db.commit()
    return row


# ------------------------------------------------------------------ review


async def handle_review(
    file_id: uuid.UUID, order_payload: dict[str, Any], user: str, db: Session, settings: AppSettings
) -> ProcessedFile:
    row = get_file_or_404(db, file_id)
    if row.status == "PROCESSING":
        raise HTTPException(status.HTTP_409_CONFLICT, "File is still being processed")

    unknown = unknown_keys(order_payload, ExtractedOrder)
    if unknown:
        errors = [{"loc": f"order.{path}", "msg": "Unknown field", "type": "extra_forbidden"} for path in unknown]
        raise _review_validation_error(errors)
    try:
        order = ExtractedOrder.model_validate(order_payload)
    except ValidationError as exc:
        raise _review_validation_error(validation_errors(list(exc.errors()), prefix=("order",))) from exc

    meta = Meta.model_validate(row.result_json["meta"]) if row.result_json else Meta(file_name=row.original_filename)
    try:
        result: ProcessingResult = await run_in_threadpool(
            validate_order,
            order,
            settings.customer_master_path,
            settings.item_master_path,
            get_po_settings(),
            human_verified=True,
            meta=meta,
        )
    except MasterDataError as exc:
        log.error("Master data error during review of %s: %s", row.original_filename, exc)
        raise AppError(500, f"Master data error: {exc}", cause=exc) from exc

    baseline = row.extracted_json or ExtractedOrder().model_dump(mode="json")
    changes = diff_orders(baseline, result.extracted.model_dump(mode="json"))  # type: ignore[union-attr]
    _apply_result(row, result, first_run=False)
    row.human_reviewed = True
    row.needs_human_review = False
    row.human_corrected = bool(changes)
    row.review_changes = changes
    row.reviewed_by = user
    row.reviewed_at = utcnow()
    db.commit()
    log.info(
        "Review of %s by %s: %d change(s), status %s -> %s",
        row.original_filename,
        user,
        len(changes),
        row.ai_status,
        row.status,
    )
    return row


def _review_validation_error(errors: list[dict[str, Any]]) -> AppError:
    first = f"{errors[0]['loc']}: {errors[0]['msg']}" if errors else "invalid order"
    return AppError(
        422, f"The edited JSON is not a valid order - {first}", error_type="ValidationError", errors=errors
    )


def unknown_keys(data: Any, model: type[BaseModel], prefix: str = "") -> list[str]:
    """Keys the model does not know (the model itself ignores them - catch typos in human edits)."""
    if not isinstance(data, dict):
        return []
    found: list[str] = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        field = model.model_fields.get(key)
        if field is None:
            found.append(path)
            continue
        nested = _nested_model(field.annotation)
        if nested is None:
            continue
        if isinstance(value, list):
            for index, item in enumerate(value):
                found.extend(unknown_keys(item, nested, f"{path}[{index}]"))
        else:
            found.extend(unknown_keys(value, nested, path))
    return found


def _nested_model(annotation: Any) -> Optional[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in getattr(annotation, "__args__", ()):
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    return None


# ------------------------------------------------------------------ helpers


# ------------------------------------------------------------------ delete


def delete_file(db: Session, file_id: uuid.UUID, user: str, settings: AppSettings) -> None:
    """Delete the database row and the stored upload folder UPLOAD_DIR/<id>/."""
    row = get_file_or_404(db, file_id)
    if row.status == "PROCESSING" and not _is_stale(row.uploaded_at):
        raise HTTPException(status.HTTP_409_CONFLICT, "File is still being processed; delete it when it has finished")

    name, folder = row.original_filename, Path(row.stored_path).parent
    db.delete(row)
    db.commit()

    # Only ever remove the per-file folder inside UPLOAD_DIR.
    upload_root = settings.upload_dir.resolve()
    target = folder.resolve()
    if target.parent != upload_root or target.name != str(file_id):
        log.warning("Row %s deleted; not removing %s because it is not UPLOAD_DIR/<id>", file_id, folder)
    else:
        try:
            shutil.rmtree(target)
        except FileNotFoundError:
            log.warning("Row %s deleted; upload folder %s was already gone", file_id, target)
        except OSError as exc:
            log.error("Row %s deleted but its upload folder %s could not be removed: %s", file_id, target, exc)
    log.info("Deleted %s (%s) by %s", name, file_id, user)


def _is_stale(uploaded_at: datetime) -> bool:
    if uploaded_at.tzinfo is None:  # SQLite returns naive UTC timestamps
        uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
    return uploaded_at < datetime.now(timezone.utc) - STALE_AFTER


def get_file_or_404(db: Session, file_id: uuid.UUID) -> ProcessedFile:
    row = db.get(ProcessedFile, file_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return row


def _apply_result(row: ProcessedFile, result: ProcessingResult, *, first_run: bool) -> None:
    data = result.model_dump(mode="json")
    has_order = result.extracted is not None
    row.status = result.status
    row.match_result = result.match_result
    row.confidence_score = result.confidence_score  # type: ignore[assignment]
    row.issues = data["issues"]
    row.order_number = result.extracted.document.order_number if has_order else None  # type: ignore[union-attr]
    row.customer_label = result.summary.customer
    row.customer_matched = result.summary.customer_matched if has_order else None
    row.items_matched = result.summary.items_matched if has_order else None
    row.items_total = result.summary.items_total if has_order else None
    if first_run:
        row.needs_human_review = result.needs_human_review
        row.extracted_json = data["extracted"]
        row.result_json = data
        row.ai_status = result.status
        row.ai_confidence_score = result.confidence_score  # type: ignore[assignment]
        row.file_type = result.meta.file_type or row.file_type
        row.extraction_method = result.meta.extraction_method
        row.model_name = result.meta.model_name
        row.duration_ms = result.meta.duration_ms
    else:
        row.reviewed_json = data["extracted"]
        row.reviewed_result_json = data


def _mark_failed(db: Session, row: ProcessedFile, message: str, exc: BaseException, settings: AppSettings) -> None:
    db.rollback()
    row.status = "ERROR"
    row.ai_status = "ERROR"
    row.needs_human_review = True
    row.error_message = f"{message}\n\n{format_exception(exc)}" if settings.debug else message
    db.commit()


def _detail(row: ProcessedFile) -> dict[str, Any]:
    return to_detail(row).model_dump(mode="json")


def mark_stale_processing_rows(db: Session) -> int:
    """On startup: PROCESSING rows older than 10 minutes were interrupted by a crash/restart."""
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    result = db.execute(
        update(ProcessedFile)
        .where(ProcessedFile.status == "PROCESSING", ProcessedFile.uploaded_at < cutoff)
        .values(status="ERROR", ai_status="ERROR", needs_human_review=True, error_message="interrupted")
    )
    db.commit()
    return result.rowcount or 0


def list_files(db: Session) -> list[ProcessedFile]:
    large = (
        ProcessedFile.extracted_json,
        ProcessedFile.result_json,
        ProcessedFile.reviewed_json,
        ProcessedFile.reviewed_result_json,
        ProcessedFile.review_changes,
    )
    query = select(ProcessedFile).options(*(defer(col) for col in large)).order_by(ProcessedFile.uploaded_at.desc())
    return list(db.scalars(query))
