"""Saving uploads to UPLOAD_DIR/<uuid>/<original_name>."""

from __future__ import annotations

import hashlib
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

CHUNK_SIZE = 1024 * 1024
_UNSAFE = re.compile(r"[^\w.\- ()]+", re.UNICODE)


@dataclass
class StoredFile:
    path: Path
    sha256: str
    size: int


def safe_filename(name: str | None) -> str:
    """Keep the original name readable but strip directories and odd characters."""
    base = Path((name or "").replace("\\", "/")).name
    base = unicodedata.normalize("NFC", base).strip()
    base = _UNSAFE.sub("_", base).strip(" .")
    return base[:200] or "upload"


async def save_upload(upload: UploadFile, target: Path, max_bytes: int) -> StoredFile:
    """Stream the upload to ``target`` while hashing; 413 if it exceeds ``max_bytes``."""
    limit_mb = max_bytes // (1024 * 1024)
    if upload.size is not None and upload.size > max_bytes:
        raise HTTPException(413, f"File is larger than {limit_mb} MB")

    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"File is larger than {limit_mb} MB")
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        shutil.rmtree(target.parent, ignore_errors=True)
        raise
    return StoredFile(path=target, sha256=digest.hexdigest(), size=size)
