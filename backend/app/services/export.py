"""Compact JSON export of selected files.

Uses the latest data per file: the human-reviewed version if there is one, otherwise the AI
extraction. Files that cannot be exported are listed under ``skipped`` with a reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProcessedFile


def export_files(db: Session, ids: list[uuid.UUID]) -> dict[str, Any]:
    rows = {row.id: row for row in db.scalars(select(ProcessedFile).where(ProcessedFile.id.in_(ids)))}
    orders: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for file_id in dict.fromkeys(ids):  # keep the requested order, drop duplicates
        row = rows.get(file_id)
        if row is None:
            skipped.append({"file_id": str(file_id), "file_name": None, "reason": "not found"})
        elif row.status == "PROCESSING":
            skipped.append({"file_id": str(file_id), "file_name": row.original_filename, "reason": "still processing"})
        elif not (row.reviewed_json or row.extracted_json):
            skipped.append(
                {"file_id": str(file_id), "file_name": row.original_filename, "reason": "no extracted data (processing failed)"}
            )
        else:
            orders.append(_compact_order(row))
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(orders),
        "orders": orders,
        "skipped": skipped,
    }


def _compact_order(row: ProcessedFile) -> dict[str, Any]:
    reviewed = row.reviewed_json is not None
    data = (row.reviewed_json if reviewed else row.extracted_json) or {}
    result = (row.reviewed_result_json if reviewed else row.result_json) or {}
    item_matched = {m.get("line_index"): bool(m.get("matched")) for m in result.get("item_matches") or []}
    document = data.get("document") or {}
    customer = data.get("customer") or {}
    return {
        "file_id": str(row.id),
        "file_name": row.original_filename,
        "data_source": "human_reviewed" if reviewed else "ai_extraction",
        "status": row.status,
        "match_result": row.match_result,
        "order_number": document.get("order_number"),
        "order_date": document.get("order_date"),
        "customer": {
            "customer_number": customer.get("customer_number"),
            "legal_name": customer.get("legal_name"),
            "matched": bool(row.customer_matched),
        },
        "items": [
            {
                "position": line.get("position"),
                "item_number": line.get("item_number"),
                "description": line.get("description"),
                "quantity": line.get("quantity"),
                "unit": line.get("unit"),
                "matched": item_matched.get(index, False),
            }
            for index, line in enumerate(data.get("line_items") or [])
        ],
    }
