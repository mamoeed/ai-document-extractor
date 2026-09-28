import json

import httpx
import openai
import pytest

from po_extractor.errors import ExtractionSchemaError, ModelUnavailableError
from po_extractor.extract import ExtractionInput
from po_extractor.llm.client import VLMClient, parse_json_response

from .conftest import CLEARLINE_ORDER

TEXT_PAYLOAD = ExtractionInput(method="excel_text_vlm", file_type="xlsx", text="## Sheet: PO\nOrder\tOR1")
_REQUEST = httpx.Request("POST", "https://api.deepinfra.com/v1/openai/chat/completions")


def _status_error(cls, status: int, detail: str):
    return cls(detail, response=httpx.Response(status, request=_REQUEST), body={"detail": detail})


# ---------------------------------------------------------------- JSON parsing


def test_parse_plain_json():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_strips_code_fences():
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_response('```\n{"a": 1}\n```') == {"a": 1}


def test_parse_strips_reasoning_and_prose():
    raw = '<think>let me see {x}</think>\nHere you go: {"a": {"b": 2}} Hope this helps.'
    assert parse_json_response(raw) == {"a": {"b": 2}}


@pytest.mark.parametrize("raw", ["", "no json here", "[1, 2]", '{"a": '])
def test_parse_rejects_non_objects(raw):
    with pytest.raises(ValueError):
        parse_json_response(raw)


# ------------------------------------------------------------------ requests


def test_request_parameters(settings, fake_vlm):
    fake = fake_vlm(CLEARLINE_ORDER)
    output = VLMClient(settings).extract(TEXT_PAYLOAD)

    assert output.attempts == 1
    assert output.order.document.order_number == "OR2607421"
    assert output.usage.total_tokens == 1200
    call = fake.calls[0]
    assert call["model"] == "test/vlm-model"
    assert call["temperature"] == 0
    assert call["response_format"] == {"type": "json_object"}
    assert call["max_tokens"] == settings.vlm_max_tokens
    assert fake.client.init_kwargs["base_url"] == settings.deepinfra_base_url
    assert fake.client.init_kwargs["api_key"] == "test-key"
    assert fake.client.init_kwargs["timeout"] == settings.vlm_timeout_s


def test_json_mode_can_be_disabled(settings, fake_vlm):
    fake = fake_vlm(CLEARLINE_ORDER)
    VLMClient(settings.model_copy(update={"vlm_json_mode": False})).extract(TEXT_PAYLOAD)
    assert "response_format" not in fake.calls[0]


def test_retry_appends_validation_error(settings, fake_vlm):
    bad = dict(CLEARLINE_ORDER, field_confidence={"order_number": 7000})
    fake = fake_vlm("not json", bad, "```json\n" + json.dumps(CLEARLINE_ORDER) + "\n```")
    output = VLMClient(settings).extract(TEXT_PAYLOAD)

    assert output.attempts == 3
    assert output.usage.total_tokens == 3600  # summed over attempts
    second, third = fake.calls[1]["messages"], fake.calls[2]["messages"]
    assert second[-2] == {"role": "assistant", "content": "not json"}
    assert "Invalid JSON" in second[-1]["content"]
    assert "field_confidence.order_number" in third[-1]["content"]


def test_invalid_after_all_retries(settings, fake_vlm):
    fake = fake_vlm("nope", "still nope", '{"line_items": "not a list"}')
    with pytest.raises(ExtractionSchemaError) as excinfo:
        VLMClient(settings).extract(TEXT_PAYLOAD)
    assert len(fake.calls) == settings.vlm_max_retries + 1
    assert excinfo.value.attempts == 3
    assert excinfo.value.raw_output == '{"line_items": "not a list"}'


def test_timeout_is_model_unavailable(settings, fake_vlm):
    fake_vlm(openai.APITimeoutError(request=_REQUEST))
    with pytest.raises(ModelUnavailableError, match="timed out"):
        VLMClient(settings).extract(TEXT_PAYLOAD)


def test_bad_key_message(settings, fake_vlm):
    fake_vlm(_status_error(openai.AuthenticationError, 401, "invalid token"))
    with pytest.raises(ModelUnavailableError, match="DEEPINFRA_API_KEY"):
        VLMClient(settings).extract(TEXT_PAYLOAD)


def test_unknown_model_message(settings, fake_vlm):
    fake_vlm(_status_error(openai.NotFoundError, 404, "model not found"))
    with pytest.raises(ModelUnavailableError, match="VLM_MODEL"):
        VLMClient(settings).extract(TEXT_PAYLOAD)


def test_server_error_is_model_unavailable(settings, fake_vlm):
    fake_vlm(_status_error(openai.InternalServerError, 503, "overloaded"))
    with pytest.raises(ModelUnavailableError, match="503"):
        VLMClient(settings).extract(TEXT_PAYLOAD)


def test_connection_error_is_model_unavailable(settings, fake_vlm):
    fake_vlm(openai.APIConnectionError(request=_REQUEST))
    with pytest.raises(ModelUnavailableError, match="Cannot reach"):
        VLMClient(settings).extract(TEXT_PAYLOAD)
