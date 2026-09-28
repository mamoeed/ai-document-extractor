"""ORM model for the processed_files table (see alembic/versions/0001_initial.py)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, Numeric, Text, Uuid, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on Postgres, plain JSON elsewhere (SQLite in tests). Python None -> SQL NULL.
JsonType = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ProcessedFile(Base):
    __tablename__ = "processed_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    original_filename: Mapped[str] = mapped_column(Text)
    stored_path: Mapped[str] = mapped_column(Text)
    file_type: Mapped[Optional[str]] = mapped_column(Text)
    file_sha256: Mapped[Optional[str]] = mapped_column(Text)  # display only, no dedup
    uploaded_by: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )

    # Current state (after human review, the re-validated result).
    status: Mapped[str] = mapped_column(Text, default="PROCESSING")
    match_result: Mapped[Optional[str]] = mapped_column(Text)
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=True)
    human_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Addendum A3: did the reviewer change any value, and what the AI said originally.
    human_corrected: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    ai_status: Mapped[Optional[str]] = mapped_column(Text)
    ai_confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))

    # Denormalized for the table view.
    order_number: Mapped[Optional[str]] = mapped_column(Text)
    customer_label: Mapped[Optional[str]] = mapped_column(Text)
    customer_matched: Mapped[Optional[bool]] = mapped_column(Boolean)
    items_matched: Mapped[Optional[int]] = mapped_column(Integer)
    items_total: Mapped[Optional[int]] = mapped_column(Integer)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)

    extracted_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType)  # model output, never overwritten
    result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType)  # first-run ProcessingResult
    reviewed_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType)  # human-edited ExtractedOrder
    reviewed_result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType)
    review_changes: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JsonType)  # [{path, before, after}]
    reviewed_by: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    extraction_method: Mapped[Optional[str]] = mapped_column(Text)
    model_name: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
