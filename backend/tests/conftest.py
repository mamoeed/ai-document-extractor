"""Backend tests: SQLite instead of Postgres, and process_file replaced by a fake that runs the
real deterministic validation on canned extractions (no model calls)."""

from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_TMP = Path(tempfile.mkdtemp(prefix="po-backend-tests-"))


def _master(env_var: str, name: str) -> str:
    from_env = os.environ.get(env_var)
    if from_env and Path(from_env).is_file():
        return from_env
    return str(REPO_ROOT / "data" / "master" / name)


os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
        "APP_USERNAME": "admin",
        "APP_PASSWORD": "secret-pw",
        "JWT_SECRET": "test-secret-" + "x" * 40,
        "JWT_EXPIRE_MINUTES": "60",
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "MAX_UPLOAD_MB": "20",
        "CUSTOMER_MASTER_PATH": _master("CUSTOMER_MASTER_PATH", "fictional_customer_master.xlsx"),
        "ITEM_MASTER_PATH": _master("ITEM_MASTER_PATH", "fictional_item_master.xlsx"),
        "DEEPINFRA_API_KEY": "test-key",
        "VLM_MODEL": "test/vlm-model",
        "DEBUG": "true",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import processing  # noqa: E402
from po_extractor import Meta, validate_order  # noqa: E402

SAMPLES = REPO_ROOT / "samples"
HIGH = {"order_number": 0.98, "customer_number": 0.97, "legal_name": 0.95, "line_items": 0.96}

CLEARLINE = {
    "document": {"order_number": "OR2607421", "order_date": "2026-08-18", "currency": "EUR"},
    "customer": {"customer_number": "48326", "legal_name": "Clearline Hygiene GmbH"},
    "line_items": [
        {"position": "001", "item_number": "845271", "quantity": 40, "unit": "canisters"},
        {"position": "002", "item_number": "725904", "quantity": 50, "unit": "pcs"},
        {"position": "003", "item_number": "725918", "quantity": 50, "unit": "pcs"},
    ],
    "field_confidence": HIGH,
}
NORTHBRIDGE_PNG = {
    "document": {"order_number": "PO-7642091", "order_date": "2026-08-18"},
    "customer": {"customer_number": "58264", "legal_name": "Northbridge Catering Systems Ltd."},
    "line_items": [{"position": "1", "item_number": "7842136", "reference_number": "628450", "quantity": 5,
                    "unit": "Stk"}],
    "field_confidence": {**HIGH, "legal_name": 0.7},
}
NORTHBRIDGE_XLSX = {
    **NORTHBRIDGE_PNG,
    "line_items": [{"position": "1", "item_number": "7842136", "quantity": 5, "unit": "pcs"},
                   {"position": "2", "item_number": "628450", "quantity": 5, "unit": "sets"}],
    "field_confidence": HIGH,
}
CANNED = {
    "purchase_order_clearline_en_example_1.pdf": (CLEARLINE, "pdf", "pdf_text_vlm"),
    "Order example 4.png": (NORTHBRIDGE_PNG, "png", "image_vlm"),
    "purchase_order_northbridge.xlsx": (NORTHBRIDGE_XLSX, "xlsx", "excel_text_vlm"),
}


def fake_process_file(file_path, customer_master_path, item_master_path, settings=None):
    order, file_type, method = CANNED[Path(file_path).name]
    meta = Meta(file_name=Path(file_path).name, file_type=file_type, extraction_method=method,
                model_name="test/vlm-model", duration_ms=1234)
    result = validate_order(copy.deepcopy(order), customer_master_path, item_master_path, settings, meta=meta)
    result.meta.duration_ms = 1234
    return result


Base.metadata.create_all(get_engine())


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth(client) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "secret-pw"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def fake_processing(monkeypatch):
    monkeypatch.setattr(processing, "process_file", fake_process_file)


def upload(client, auth, sample_name: str):
    path = SAMPLES / sample_name
    with path.open("rb") as fh:
        return client.post("/api/files", headers=auth, files={"file": (sample_name, fh)})
