"""API request/response models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .models import ProcessedFile


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    expires_in_minutes: int


class ExportRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


class ReviewRequest(BaseModel):
    order: dict[str, Any]  # validated against po_extractor.ExtractedOrder in the service


class FileSummary(BaseModel):
    id: uuid.UUID
    original_filename: str
    file_type: Optional[str]
    file_sha256: Optional[str]
    uploaded_by: str
    uploaded_at: datetime
    status: str
    match_result: Optional[str]
    confidence_score: Optional[float]
    needs_human_review: bool
    human_reviewed: bool
    human_corrected: bool
    ai_status: Optional[str]
    ai_confidence_score: Optional[float]
    order_number: Optional[str]
    customer_label: Optional[str]
    customer_matched: Optional[bool]
    items_matched: Optional[int]
    items_total: Optional[int]
    main_issue: Optional[str]
    issue_count: int
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    extraction_method: Optional[str]
    model_name: Optional[str]
    duration_ms: Optional[int]


class FileDetail(FileSummary):
    issues: list[dict[str, Any]]
    extracted_json: Optional[dict[str, Any]]
    result_json: Optional[dict[str, Any]]
    reviewed_json: Optional[dict[str, Any]]
    reviewed_result_json: Optional[dict[str, Any]]
    review_changes: Optional[list[dict[str, Any]]]
    error_message: Optional[str]


def _float(value: Any) -> Optional[float]:
    return None if value is None else float(value)


def _summary_fields(row: ProcessedFile) -> dict[str, Any]:
    issues = row.issues or []
    main_issue = issues[0].get("message") if issues else None
    if main_issue is None and row.error_message:
        main_issue = row.error_message.strip().splitlines()[0][:300]
    return {
        "id": row.id,
        "original_filename": row.original_filename,
        "file_type": row.file_type,
        "file_sha256": row.file_sha256,
        "uploaded_by": row.uploaded_by,
        "uploaded_at": row.uploaded_at,
        "status": row.status,
        "match_result": row.match_result,
        "confidence_score": _float(row.confidence_score),
        "needs_human_review": bool(row.needs_human_review),
        "human_reviewed": bool(row.human_reviewed),
        "human_corrected": bool(row.human_corrected),
        "ai_status": row.ai_status,
        "ai_confidence_score": _float(row.ai_confidence_score),
        "order_number": row.order_number,
        "customer_label": row.customer_label,
        "customer_matched": row.customer_matched,
        "items_matched": row.items_matched,
        "items_total": row.items_total,
        "main_issue": main_issue,
        "issue_count": len(issues),
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "extraction_method": row.extraction_method,
        "model_name": row.model_name,
        "duration_ms": row.duration_ms,
    }


def to_summary(row: ProcessedFile) -> FileSummary:
    return FileSummary(**_summary_fields(row))


def to_detail(row: ProcessedFile) -> FileDetail:
    return FileDetail(
        **_summary_fields(row),
        issues=row.issues or [],
        extracted_json=row.extracted_json,
        result_json=row.result_json,
        reviewed_json=row.reviewed_json,
        reviewed_result_json=row.reviewed_result_json,
        review_changes=row.review_changes,
        error_message=row.error_message,
    )
