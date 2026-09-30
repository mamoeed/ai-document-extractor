import json

import httpx
import openai
import pytest

from po_extractor.errors import ExtractionSchemaError, ModelUnavailableError
from po_extractor.extract import ExtractionInput
from types import SimpleNamespace

from openai.types import CompletionUsage

from po_extractor.llm.client import VLMClient, estimated_cost, parse_json_response

from .conftest import CLEARLINE_ORDER, StreamReply

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
    assert output.usage.estimated_cost_usd == pytest.approx(0.0004)
    call = fake.calls[0]
    assert call["stream"] is True
    assert call["stream_options"] == {"include_usage": True}
    assert fake.client.init_kwargs["max_retries"] == 0  # timeouts must not be re-sent
    assert fake.client.completions.streams[0].closed
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
    assert output.usage.estimated_cost_usd == pytest.approx(0.0012)
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
    with pytest.raises(ModelUnavailableError, match=r"did not start answering within 120s \(VLM_TIMEOUT_S\)"):
        VLMClient(settings).extract(TEXT_PAYLOAD)


def test_bad_key_message(settings, fake_vlm):
    fake_vlm(_status_error(openai.AuthenticationError, 401, "invalid token"))
    with pytest.raises(ModelUnavailableError, match="DEEPINFRA_API_KEY"):
        VLMClient(settings).extract(TEXT_PAYLOAD)


def test_unknown_model_message(settings, fake_vlm):
    fake_vlm(_status_error(openai.NotFoundError, 404, "model not found"))
    with pytest.raises(ModelUnavailableError, match="VLM_MODEL"):
        VLMClient(settings).extract(TEXT_PAYLOAD)


def test_server_error_retried_once_then_unavailable(settings, fake_vlm):
    fake = fake_vlm(_status_error(openai.InternalServerError, 503, "overloaded"),
                    _status_error(openai.InternalServerError, 503, "overloaded"))
    with pytest.raises(ModelUnavailableError, match="503"):
        VLMClient(settings).extract(TEXT_PAYLOAD)
    assert len(fake.calls) == 2


def test_transient_error_then_success(settings, fake_vlm):
    fake = fake_vlm(_status_error(openai.RateLimitError, 429, "slow down"), CLEARLINE_ORDER)
    output = VLMClient(settings).extract(TEXT_PAYLOAD)
    assert output.order.document.order_number == "OR2607421"
    assert len(fake.calls) == 2


def test_connection_error_is_model_unavailable(settings, fake_vlm):
    fake_vlm(openai.APIConnectionError(request=_REQUEST), openai.APIConnectionError(request=_REQUEST))
    with pytest.raises(ModelUnavailableError, match="Cannot reach"):
        VLMClient(settings).extract(TEXT_PAYLOAD)


def test_estimated_cost_from_deepinfra_usage():
    # The real SDK type keeps DeepInfra's extra field.
    real = CompletionUsage.model_validate(
        {"prompt_tokens": 1865, "completion_tokens": 533, "total_tokens": 2398, "estimated_cost": 0.00084}
    )
    assert estimated_cost(real) == pytest.approx(0.00084)
    assert estimated_cost(SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)) is None
    assert estimated_cost(None) is None


# ------------------------------------------------------------------ streaming


def test_timeout_is_not_retried(settings, fake_vlm):
    fake = fake_vlm(openai.APITimeoutError(request=_REQUEST), CLEARLINE_ORDER)
    with pytest.raises(ModelUnavailableError):
        VLMClient(settings).extract(TEXT_PAYLOAD)
    assert len(fake.calls) == 1


def test_stream_goes_silent(settings, fake_vlm):
    fake = fake_vlm(StreamReply(json.dumps(CLEARLINE_ORDER), fail_after_first_chunk=httpx.ReadTimeout("read")))
    with pytest.raises(ModelUnavailableError, match=r"stopped sending data for 120s \(VLM_TIMEOUT_S\)"):
        VLMClient(settings).extract(TEXT_PAYLOAD)
    assert fake.client.completions.streams[0].closed


def test_stream_connection_breaks(settings, fake_vlm):
    fake_vlm(StreamReply(json.dumps(CLEARLINE_ORDER), fail_after_first_chunk=httpx.RemoteProtocolError("peer closed")))
    with pytest.raises(ModelUnavailableError, match="broke"):
        VLMClient(settings).extract(TEXT_PAYLOAD)


def test_total_timeout(settings, fake_vlm):
    fake_vlm(CLEARLINE_ORDER)
    with pytest.raises(ModelUnavailableError, match="VLM_TOTAL_TIMEOUT_S=0s"):
        VLMClient(settings.model_copy(update={"vlm_total_timeout_s": 0})).extract(TEXT_PAYLOAD)


def test_output_cut_off_is_not_retried(settings, fake_vlm):
    fake = fake_vlm(StreamReply('{"document": {"order_number": "OR26', finish_reason="length"))
    with pytest.raises(ExtractionSchemaError, match="VLM_MAX_TOKENS=4096"):
        VLMClient(settings).extract(TEXT_PAYLOAD)
    assert len(fake.calls) == 1


def test_stream_chunks_are_joined(settings, fake_vlm):
    text = json.dumps(CLEARLINE_ORDER, separators=(",", ":"))  # compact, as the prompt asks
    fake_vlm(StreamReply(text))
    output = VLMClient(settings).extract(TEXT_PAYLOAD)
    assert output.raw_output == text
    assert len(output.order.line_items) == 3
