from datetime import timedelta

from app.config import get_settings
from app.db import new_session
from app.models import ProcessedFile, utcnow
from app.services import processing
from po_extractor import MasterDataError

from .conftest import NORTHBRIDGE_PNG, SAMPLES, upload

# ------------------------------------------------------------------- auth


def test_login_and_wrong_password(client):
    ok = client.post("/api/auth/login", json={"username": "admin", "password": "secret-pw"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    body = bad.json()
    assert body["detail"] == "Invalid username or password"
    assert body["request_id"] == bad.headers["X-Request-ID"]


def test_endpoints_require_token(client):
    assert client.get("/api/files").status_code == 401
    assert client.get("/api/files", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.post("/api/files").status_code == 401


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["db"] and body["master_data"]
    assert "10 customers, 34 items" in body["details"]["master_data"]


# ---------------------------------------------------------------- uploads


def test_upload_clearline_full_match(client, auth, fake_processing):
    response = upload(client, auth, "purchase_order_clearline_en_example_1.pdf")
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["status"] == "CONFIDENT_MATCH"
    assert row["match_result"] == "FULL_MATCH"
    assert row["confidence_score"] == 0.95
    assert row["needs_human_review"] is False
    assert row["customer_label"] == "ClearLine Hygiene GmbH (48326)"
    assert row["customer_matched"] is True
    assert (row["items_matched"], row["items_total"]) == (3, 3)
    assert row["order_number"] == "OR2607421"
    assert row["ai_status"] == "CONFIDENT_MATCH"
    assert row["extraction_method"] == "pdf_text_vlm"
    assert row["uploaded_by"] == "admin"
    assert len(row["file_sha256"]) == 64
    assert row["extracted_json"]["document"]["order_number"] == "OR2607421"
    assert row["result_json"]["status"] == "CONFIDENT_MATCH"

    # list: newest first, without large JSON columns
    listing = client.get("/api/files", headers=auth).json()
    assert listing[0]["id"] == row["id"]
    assert "extracted_json" not in listing[0]
    assert "result_json" not in listing[0]

    # detail + original file
    detail = client.get(f"/api/files/{row['id']}", headers=auth).json()
    assert detail["extracted_json"] == row["extracted_json"]
    original = client.get(f"/api/files/{row['id']}/original", headers=auth)
    assert original.status_code == 200
    assert original.content == (SAMPLES / "purchase_order_clearline_en_example_1.pdf").read_bytes()
    assert original.headers["content-type"] == "application/pdf"
    assert original.headers["content-disposition"].startswith("inline")


def test_upload_northbridge_xlsx_no_match(client, auth, fake_processing):
    row = upload(client, auth, "purchase_order_northbridge.xlsx").json()
    assert row["status"] == "LOW_CONFIDENCE"
    assert row["match_result"] == "NO_MATCH"
    assert [i["code"] for i in row["issues"]] == ["CUSTOMER_NOT_FOUND", "ITEM_NOT_FOUND"]
    assert row["main_issue"].startswith("Customer 58264 not found")
    assert row["issue_count"] == 2
    assert row["customer_matched"] is False
    assert row["needs_human_review"] is True


def test_unsupported_file_goes_through_real_pipeline(client, auth):
    response = client.post("/api/files", headers=auth, files={"file": ("notes.txt", b"hello")})
    assert response.status_code == 200
    row = response.json()
    assert row["status"] == "ERROR"
    assert row["issues"][0]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert row["needs_human_review"] is True
    assert row["match_result"] is None


def test_upload_too_large(client, auth, fake_processing, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    response = upload(client, auth, "Order example 4.png")
    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


def test_unexpected_error_marks_row_and_returns_details(client, auth, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("kaboom in the pipeline")

    monkeypatch.setattr(processing, "process_file", boom)
    response = upload(client, auth, "Order example 4.png")
    assert response.status_code == 500
    body = response.json()
    assert "kaboom in the pipeline" in body["detail"]
    assert body["error_type"] == "RuntimeError"
    assert "Traceback" in body["traceback"]  # DEBUG=true in tests
    assert body["file"]["status"] == "ERROR"
    assert "kaboom" in body["file"]["error_message"]

    listed = next(r for r in client.get("/api/files", headers=auth).json() if r["id"] == body["file"]["id"])
    assert listed["status"] == "ERROR"
    assert "kaboom" in listed["main_issue"]


def test_master_data_error_is_500(client, auth, monkeypatch):
    def broken(*args, **kwargs):
        raise MasterDataError("required column(s) ['Active'] not found")

    monkeypatch.setattr(processing, "process_file", broken)
    response = upload(client, auth, "Order example 4.png")
    assert response.status_code == 500
    assert response.json()["detail"].startswith("Master data error:")


# ----------------------------------------------------------------- review


def test_review_with_correction(client, auth, fake_processing):
    row = upload(client, auth, "Order example 4.png").json()
    assert row["status"] == "LOW_CONFIDENCE"
    assert row["match_result"] == "PARTIAL_MATCH"
    original_extraction = row["extracted_json"]

    edited = dict(row["extracted_json"])
    edited["customer"] = {**edited["customer"], "customer_number": "48326",
                          "legal_name": "Northstar Commercial Kitchens Ltd."}
    response = client.put(f"/api/files/{row['id']}/review", headers=auth, json={"order": edited})
    assert response.status_code == 200, response.text
    reviewed = response.json()

    assert reviewed["human_reviewed"] is True
    assert reviewed["needs_human_review"] is False
    assert reviewed["human_corrected"] is True
    assert reviewed["reviewed_by"] == "admin"
    assert reviewed["reviewed_at"]
    assert reviewed["status"] == "CONFIDENT_MATCH"  # re-validated: now a full match
    assert reviewed["match_result"] == "FULL_MATCH"
    assert reviewed["ai_status"] == "LOW_CONFIDENCE"  # what the AI said stays visible
    assert reviewed["reviewed_result_json"]["human_verified"] is True
    assert reviewed["extracted_json"] == original_extraction  # never overwritten
    assert reviewed["reviewed_json"]["customer"]["legal_name"] == "Northstar Commercial Kitchens Ltd."
    paths = {c["path"] for c in reviewed["review_changes"]}
    assert paths == {"customer.customer_number", "customer.legal_name"}


def test_review_confirm_without_changes(client, auth, fake_processing):
    row = upload(client, auth, "Order example 4.png").json()
    response = client.put(f"/api/files/{row['id']}/review", headers=auth, json={"order": row["extracted_json"]})
    reviewed = response.json()
    assert reviewed["human_reviewed"] is True
    assert reviewed["human_corrected"] is False
    assert reviewed["review_changes"] == []
    assert reviewed["needs_human_review"] is False
    # customer 58264 is still not in the master -> still a partial match, but confirmed by a human
    assert reviewed["status"] == "LOW_CONFIDENCE"
    assert reviewed["confidence_score"] == 0.6
    assert reviewed["ai_confidence_score"] == 0.42  # 0.7 * 0.6


def test_review_invalid_json_is_422(client, auth, fake_processing):
    row = upload(client, auth, "Order example 4.png").json()
    bad = {**NORTHBRIDGE_PNG, "document": {"order_date": "not a date"}}
    response = client.put(f"/api/files/{row['id']}/review", headers=auth, json={"order": bad})
    assert response.status_code == 422
    body = response.json()
    assert body["errors"][0]["loc"] == "order.document.order_date"
    assert "not a valid order" in body["detail"]

    typo = {**NORTHBRIDGE_PNG, "customer": {"custmer_number": "1"}}
    response = client.put(f"/api/files/{row['id']}/review", headers=auth, json={"order": typo})
    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == "order.customer.custmer_number"

    # nothing was stored
    detail = client.get(f"/api/files/{row['id']}", headers=auth).json()
    assert detail["human_reviewed"] is False and detail["reviewed_json"] is None


def test_review_unknown_file_404(client, auth):
    response = client.put("/api/files/00000000-0000-0000-0000-000000000000/review", headers=auth,
                          json={"order": {}})
    assert response.status_code == 404


def test_review_of_error_row_without_extraction(client, auth):
    row = client.post("/api/files", headers=auth, files={"file": ("x.txt", b"x")}).json()
    response = client.put(f"/api/files/{row['id']}/review", headers=auth, json={"order": NORTHBRIDGE_PNG})
    reviewed = response.json()
    assert reviewed["human_reviewed"] and reviewed["human_corrected"]
    assert reviewed["match_result"] == "PARTIAL_MATCH"
    assert reviewed["extracted_json"] is None


# ------------------------------------------------------------ startup logic


def test_stale_processing_rows_marked_interrupted():
    with new_session() as db:
        old = ProcessedFile(original_filename="old.pdf", stored_path="/x", uploaded_by="admin", status="PROCESSING",
                            needs_human_review=False, uploaded_at=utcnow() - timedelta(minutes=20), issues=[])
        fresh = ProcessedFile(original_filename="new.pdf", stored_path="/x", uploaded_by="admin",
                              status="PROCESSING", needs_human_review=False, issues=[])
        db.add_all([old, fresh])
        db.commit()
        assert processing.mark_stale_processing_rows(db) >= 1
        db.refresh(old)
        db.refresh(fresh)
        assert (old.status, old.error_message) == ("ERROR", "interrupted")
        assert fresh.status == "PROCESSING"


# ----------------------------------------------------------------- delete


def test_delete_removes_row_and_file(client, auth, fake_processing):
    row = upload(client, auth, "Order example 4.png").json()
    folder = get_settings().upload_dir / row["id"]
    assert folder.is_dir()

    assert client.delete(f"/api/files/{row['id']}").status_code == 401  # needs a token
    response = client.delete(f"/api/files/{row['id']}", headers=auth)
    assert response.status_code == 204
    assert not folder.exists()
    assert client.get(f"/api/files/{row['id']}", headers=auth).status_code == 404
    assert row["id"] not in {r["id"] for r in client.get("/api/files", headers=auth).json()}
    assert client.delete(f"/api/files/{row['id']}", headers=auth).status_code == 404


def test_delete_reviewed_row(client, auth, fake_processing):
    row = upload(client, auth, "Order example 4.png").json()
    client.put(f"/api/files/{row['id']}/review", headers=auth, json={"order": row["extracted_json"]})
    assert client.delete(f"/api/files/{row['id']}", headers=auth).status_code == 204


def test_delete_processing_row_only_when_stale(client, auth):
    with new_session() as db:
        fresh = ProcessedFile(original_filename="busy.pdf", stored_path="/nowhere/x/busy.pdf", uploaded_by="admin",
                              status="PROCESSING", needs_human_review=False, issues=[])
        stuck = ProcessedFile(original_filename="stuck.pdf", stored_path="/nowhere/y/stuck.pdf", uploaded_by="admin",
                              status="PROCESSING", needs_human_review=False, issues=[],
                              uploaded_at=utcnow() - timedelta(minutes=30))
        db.add_all([fresh, stuck])
        db.commit()
        fresh_id, stuck_id = str(fresh.id), str(stuck.id)

    assert client.delete(f"/api/files/{fresh_id}", headers=auth).status_code == 409
    # stored_path is outside UPLOAD_DIR: the row is deleted, nothing on disk is touched
    assert client.delete(f"/api/files/{stuck_id}", headers=auth).status_code == 204


# ----------------------------------------------------------------- export


def test_export_selected_files(client, auth, fake_processing):
    ai = upload(client, auth, "purchase_order_northbridge.xlsx").json()
    reviewed = upload(client, auth, "Order example 4.png").json()
    edited = dict(reviewed["extracted_json"])
    edited["customer"] = {**edited["customer"], "legal_name": "Northbridge Catering Systems Limited"}
    client.put(f"/api/files/{reviewed['id']}/review", headers=auth, json={"order": edited})
    # the fake processor has no canned answer for this file -> 500, row stored as ERROR without extraction
    failed = client.post("/api/files", headers=auth, files={"file": ("x.txt", b"x")}).json()["file"]
    missing = "00000000-0000-0000-0000-000000000000"

    assert client.post("/api/files/export", json={"ids": [ai["id"]]}).status_code == 401
    assert client.post("/api/files/export", headers=auth, json={"ids": []}).status_code == 422

    response = client.post("/api/files/export", headers=auth,
                           json={"ids": [reviewed["id"], ai["id"], failed["id"], missing, ai["id"]]})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    first, second = body["orders"]  # requested order kept, duplicate dropped

    assert first["file_id"] == reviewed["id"]
    assert first["data_source"] == "human_reviewed"
    assert first["customer"] == {"customer_number": "58264", "legal_name": "Northbridge Catering Systems Limited",
                                 "matched": False}
    assert first["order_number"] == "PO-7642091"
    assert [i["item_number"] for i in first["items"]] == ["7842136"]

    assert second["data_source"] == "ai_extraction"
    assert second["match_result"] == "NO_MATCH"
    assert [(i["item_number"], i["matched"], i["quantity"], i["unit"]) for i in second["items"]] == [
        ("7842136", True, 5.0, "pcs"), ("628450", False, 5.0, "sets")]

    assert {s["reason"] for s in body["skipped"]} == {"not found", "no extracted data (processing failed)"}
