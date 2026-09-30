import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import AppSettings, get_settings
from ..db import get_db
from ..schemas import ExportRequest, FileDetail, FileSummary, ReviewRequest, to_detail, to_summary
from ..services import export, processing

router = APIRouter(prefix="/api/files", tags=["files"])

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.post("", response_model=FileDetail)
async def upload_file(
    file: UploadFile = File(...),
    user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: AppSettings = Depends(get_settings),
) -> FileDetail:
    """Upload ONE file; it is processed synchronously and the stored row is returned."""
    row = await processing.handle_upload(file, user, db, settings)
    return to_detail(row)


@router.post("/export")
def export_selected(
    body: ExportRequest, _: str = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """Compact JSON of the selected files: order number, customer (number, legal name) and items.
    Uses the human-reviewed version where one exists, otherwise the AI extraction."""
    return export.export_files(db, body.ids)


@router.get("", response_model=list[FileSummary])
def list_files(_: str = Depends(get_current_user), db: Session = Depends(get_db)) -> list[FileSummary]:
    """All rows, newest first, without the large JSON columns."""
    return [to_summary(row) for row in processing.list_files(db)]


@router.get("/{file_id}", response_model=FileDetail)
def get_file(file_id: uuid.UUID, _: str = Depends(get_current_user), db: Session = Depends(get_db)) -> FileDetail:
    return to_detail(processing.get_file_or_404(db, file_id))


@router.get("/{file_id}/original")
def get_original(file_id: uuid.UUID, _: str = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    row = processing.get_file_or_404(db, file_id)
    path = Path(row.stored_path)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The original file is no longer on disk")
    media_type = _MEDIA_TYPES.get(row.file_type or "", "application/octet-stream")
    inline = row.file_type in ("pdf", "png", "jpeg")
    return FileResponse(
        path,
        media_type=media_type,
        filename=row.original_filename,
        content_disposition_type="inline" if inline else "attachment",
    )


@router.put("/{file_id}/review", response_model=FileDetail)
async def review_file(
    file_id: uuid.UUID,
    body: ReviewRequest,
    user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: AppSettings = Depends(get_settings),
) -> FileDetail:
    """Save the human-edited order, re-validate it (no model call) and mark the row reviewed."""
    row = await processing.handle_review(file_id, body.order, user, db, settings)
    return to_detail(row)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    file_id: uuid.UUID,
    user: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: AppSettings = Depends(get_settings),
) -> Response:
    """Delete the row (including any review) and the stored original file. Cannot be undone."""
    processing.delete_file(db, file_id, user, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
