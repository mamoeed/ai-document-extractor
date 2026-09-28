import httpx
import openai
import pytest

from po_extractor import ConfigError, MasterDataError, Settings, process_file, validate_order
from po_extractor.schemas import ExtractedOrder, Meta

from .conftest import (
    CLEARLINE_ORDER,
    CUSTOMER_MASTER,
    ITEM_MASTER,
    NORTHBRIDGE_PNG_ORDER,
    NORTHBRIDGE_XLSX_ORDER,
    SAMPLE_CLEARLINE_PDF,
    SAMPLE_NORTHBRIDGE_PNG,
    SAMPLE_NORTHBRIDGE_XLSX,
    order_dict,
)


def _codes(result):
    return [issue.code for issue in result.issues]


def test_clearline_pdf_full_match(settings, fake_vlm):
    fake = fake_vlm(CLEARLINE_ORDER)
    result = process_file(SAMPLE_CLEARLINE_PDF, CUSTOMER_MASTER, ITEM_MASTER, settings)

    assert result.status == "CONFIDENT_MATCH"
    assert result.match_result == "FULL_MATCH"
    assert result.confidence_score == 0.95
    assert result.needs_human_review is False
    assert result.issues == []
    assert result.customer_match.matched
    assert result.customer_match.master_record["Customer master ID"] == "CM-10001"
    assert [m.matched for m in result.item_matches] == [True, True, True]
    assert result.summary.customer == "ClearLine Hygiene GmbH (48326)"
    assert result.summary.customer_matched is True
    assert (result.summary.items_matched, result.summary.items_total) == (3, 3)
    assert result.meta.file_name == SAMPLE_CLEARLINE_PDF.name
    assert result.meta.file_type == "pdf"
    assert result.meta.extraction_method == "pdf_text_vlm"
    assert result.meta.model_name == "test/vlm-model"
    assert result.meta.token_usage.total_tokens == 1200
    assert result.meta.llm_attempts == 1
    assert result.extraction_confidence == 0.95
    assert result.human_verified is False
    # the hybrid call carried both the page image and the text layer
    parts = fake.calls[0]["messages"][1]["content"]
    assert {p["type"] for p in parts} == {"text", "image_url"}


def test_northbridge_png_partial_match(settings, fake_vlm):
    fake_vlm(NORTHBRIDGE_PNG_ORDER)
    result = process_file(SAMPLE_NORTHBRIDGE_PNG, CUSTOMER_MASTER, ITEM_MASTER, settings)

    assert result.meta.extraction_method == "image_vlm"
    assert result.match_result == "PARTIAL_MATCH"
    assert result.status == "LOW_CONFIDENCE"
    assert _codes(result) == ["CUSTOMER_NOT_FOUND"]
    assert result.confidence_score == 0.57
    assert result.summary.customer == "Northbridge Catering Systems Ltd. (58264)"
    assert result.summary.customer_matched is False
    assert result.needs_human_review


def test_northbridge_xlsx_no_match(settings, fake_vlm):
    fake_vlm(NORTHBRIDGE_XLSX_ORDER)
    result = process_file(SAMPLE_NORTHBRIDGE_XLSX, CUSTOMER_MASTER, ITEM_MASTER, settings)

    assert result.meta.extraction_method == "excel_text_vlm"
    assert result.match_result == "NO_MATCH"
    assert result.status == "LOW_CONFIDENCE"
    assert _codes(result) == ["CUSTOMER_NOT_FOUND", "ITEM_NOT_FOUND"]
    assert "628450" in result.issues[1].message
    assert (result.summary.items_matched, result.summary.items_total) == (1, 2)


def test_no_line_items_is_error(settings, fake_vlm):
    fake_vlm(order_dict(CLEARLINE_ORDER, line_items=[]))
    result = process_file(SAMPLE_CLEARLINE_PDF, CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert result.status == "ERROR"
    assert result.match_result is None
    assert "NO_LINE_ITEMS" in _codes(result)
    assert result.extracted is not None  # still returned for human review


def test_low_field_confidence(settings, fake_vlm):
    fake_vlm(order_dict(CLEARLINE_ORDER, field_confidence__line_items=0.5))
    result = process_file(SAMPLE_CLEARLINE_PDF, CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert result.match_result == "FULL_MATCH"
    assert result.status == "LOW_CONFIDENCE"
    assert _codes(result) == ["LOW_EXTRACTION_CONFIDENCE"]
    assert result.confidence_score == 0.5


def test_model_timeout_is_error(settings, fake_vlm):
    fake_vlm(openai.APITimeoutError(request=httpx.Request("POST", "https://x")))
    result = process_file(SAMPLE_CLEARLINE_PDF, CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert result.status == "ERROR"
    assert _codes(result) == ["MODEL_UNAVAILABLE"]
    assert result.meta.extraction_method == "pdf_text_vlm"


def test_schema_invalid_is_error(settings, fake_vlm):
    fake_vlm("x", "y", "z")
    result = process_file(SAMPLE_NORTHBRIDGE_XLSX, CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert result.status == "ERROR"
    assert _codes(result) == ["EXTRACTION_SCHEMA_INVALID"]
    assert result.meta.llm_attempts == 3
    assert result.meta.token_usage.total_tokens == 3600
    assert result.meta.debug["last_raw_output"] == "z"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="DEEPINFRA_API_KEY"):
        process_file(SAMPLE_CLEARLINE_PDF, CUSTOMER_MASTER, ITEM_MASTER, Settings(vlm_model="m"))
    with pytest.raises(ConfigError, match="DEEPINFRA_API_KEY"):
        process_file(SAMPLE_CLEARLINE_PDF, CUSTOMER_MASTER, ITEM_MASTER,
                     Settings(deepinfra_api_key="changeme", vlm_model="m"))


def test_missing_model_raises(monkeypatch):
    monkeypatch.delenv("VLM_MODEL", raising=False)
    with pytest.raises(ConfigError, match="VLM_MODEL"):
        process_file(SAMPLE_CLEARLINE_PDF, CUSTOMER_MASTER, ITEM_MASTER, Settings(deepinfra_api_key="k"))


def test_missing_master_raises(settings, tmp_path):
    with pytest.raises(MasterDataError):
        process_file(SAMPLE_CLEARLINE_PDF, tmp_path / "missing.xlsx", ITEM_MASTER, settings)


# ----------------------------------------------------------------- validate_order


def test_validate_order_without_model(settings, fake_vlm):
    fake = fake_vlm()
    order = ExtractedOrder.model_validate(CLEARLINE_ORDER)
    result = validate_order(order, CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert result.status == "CONFIDENT_MATCH"
    assert fake.calls == []


def test_validate_order_accepts_dict_and_keeps_meta(settings):
    meta = Meta(file_name="x.png", file_type="png", extraction_method="image_vlm", model_name="m")
    result = validate_order(NORTHBRIDGE_PNG_ORDER, CUSTOMER_MASTER, ITEM_MASTER, settings, meta=meta)
    assert result.match_result == "PARTIAL_MATCH"
    assert result.meta.file_name == "x.png"
    assert result.meta.extraction_method == "image_vlm"


def test_validate_order_human_verified(settings):
    edited = order_dict(CLEARLINE_ORDER, field_confidence__legal_name=0.4)
    plain = validate_order(edited, CUSTOMER_MASTER, ITEM_MASTER, settings)
    assert plain.status == "LOW_CONFIDENCE"
    assert _codes(plain) == ["LOW_EXTRACTION_CONFIDENCE"]

    verified = validate_order(edited, CUSTOMER_MASTER, ITEM_MASTER, settings, human_verified=True)
    assert verified.status == "CONFIDENT_MATCH"
    assert verified.human_verified is True
    assert verified.confidence_score == 1.0
    assert verified.extraction_confidence == 0.4
    assert verified.issues == []


def test_human_fix_of_customer_turns_partial_into_full(settings):
    # A reviewer corrects the customer to a known master customer -> FULL_MATCH.
    edited = order_dict(
        NORTHBRIDGE_PNG_ORDER,
        customer__customer_number="48326",
        customer__legal_name="Northstar Commercial Kitchens Ltd.",
    )
    result = validate_order(edited, CUSTOMER_MASTER, ITEM_MASTER, settings, human_verified=True)
    assert result.match_result == "FULL_MATCH"
    assert result.status == "CONFIDENT_MATCH"
