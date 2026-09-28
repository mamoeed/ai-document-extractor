"""OpenAI-compatible client pointed at DeepInfra: one model for image and text input."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import openai
from openai import OpenAI
from pydantic import ValidationError

from ..config import Settings
from ..errors import ExtractionSchemaError, ModelUnavailableError
from ..extract import ExtractionInput
from ..schemas import ExtractedOrder, TokenUsage
from .prompts import CLOSING_INSTRUCTION, SYSTEM_PROMPT, build_retry_message, build_user_instruction

log = logging.getLogger(__name__)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCED = re.compile(r"```(?:json|JSON)?\s*(.*?)\s*```", re.DOTALL)
_MAX_ECHO_CHARS = 8000  # how much of a bad response is echoed back on retry


@dataclass
class ExtractionOutput:
    order: ExtractedOrder
    usage: TokenUsage
    attempts: int
    raw_output: str


def parse_json_response(raw: str) -> dict[str, Any]:
    """Strip reasoning blocks and code fences, then parse the JSON object."""
    text = _THINK_BLOCK.sub("", raw or "").strip()
    fenced = _FENCED.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("response contains no JSON object") from None
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return data


def build_messages(payload: ExtractionInput) -> list[dict[str, Any]]:
    instruction = build_user_instruction(
        payload.method, pages_total=payload.pages_total, pages_sent=len(payload.images) or None
    )
    if not payload.images:  # text-only message (Excel)
        content: Any = f"{instruction}\n\n{payload.text or ''}\n\n{CLOSING_INSTRUCTION}"
    else:
        content = [{"type": "text", "text": instruction}]
        for image in payload.images:
            content.append({"type": "image_url", "image_url": {"url": image.data_url()}})
        tail = CLOSING_INSTRUCTION
        if payload.text:
            tail = f"### PDF text layer\n{payload.text}\n\n{CLOSING_INSTRUCTION}"
        content.append({"type": "text", "text": tail})
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]


def _format_validation_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        lines = []
        for err in exc.errors()[:20]:
            loc = ".".join(str(part) for part in err["loc"])
            lines.append(f"- {loc}: {err['msg']} (got {err.get('input')!r:.80})")
        return "Schema validation failed:\n" + "\n".join(lines)
    return f"Invalid JSON: {exc}"


class VLMClient:
    def __init__(self, settings: Settings) -> None:
        settings.require_llm()
        self.settings = settings
        self._client = OpenAI(
            base_url=settings.deepinfra_base_url,
            api_key=settings.deepinfra_api_key.get_secret_value(),  # type: ignore[union-attr]
            timeout=settings.vlm_timeout_s,
            max_retries=1,  # one transport-level retry for 429/5xx/connection resets
        )

    def extract(self, payload: ExtractionInput) -> ExtractionOutput:
        """Call the VLM, validate against ``ExtractedOrder``, retry with the error on failure."""
        messages = build_messages(payload)
        usage = TokenUsage()
        max_attempts = self.settings.vlm_max_retries + 1
        last_error, raw = "", ""
        for attempt in range(1, max_attempts + 1):
            raw = self._complete(messages, usage, attempt)
            try:
                order = ExtractedOrder.model_validate(parse_json_response(raw))
            except (ValueError, ValidationError) as exc:  # JSONDecodeError is a ValueError
                last_error = _format_validation_error(exc)
                log.warning("VLM output invalid (attempt %d/%d): %s", attempt, max_attempts, last_error)
                log.debug("Invalid VLM output (truncated): %.2000s", raw)
                messages = messages + [
                    {"role": "assistant", "content": raw[:_MAX_ECHO_CHARS]},
                    {"role": "user", "content": build_retry_message(last_error)},
                ]
                continue
            return ExtractionOutput(order=order, usage=usage, attempts=attempt, raw_output=raw)
        raise ExtractionSchemaError(
            f"Model output still invalid after {max_attempts} attempt(s). {last_error}",
            raw_output=raw,
            attempts=max_attempts,
            usage=usage,
        )

    def _complete(self, messages: list[dict[str, Any]], usage: TokenUsage, attempt: int) -> str:
        settings = self.settings
        kwargs: dict[str, Any] = {
            "model": settings.vlm_model,
            "messages": messages,
            "temperature": settings.vlm_temperature,
            "max_tokens": settings.vlm_max_tokens,
        }
        if settings.vlm_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        log.info("Calling VLM %s (attempt %d)", settings.vlm_model, attempt)
        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:
            raise ModelUnavailableError(
                f"VLM request timed out after {settings.vlm_timeout_s:g}s (VLM_TIMEOUT_S)"
            ) from exc
        except openai.AuthenticationError as exc:
            raise ModelUnavailableError(
                f"DeepInfra rejected the API key (HTTP 401) - check DEEPINFRA_API_KEY. {_api_message(exc)}"
            ) from exc
        except openai.NotFoundError as exc:
            raise ModelUnavailableError(
                f"Model '{settings.vlm_model}' not found (HTTP 404) - check VLM_MODEL. {_api_message(exc)}"
            ) from exc
        except openai.APIStatusError as exc:
            raise ModelUnavailableError(f"VLM returned HTTP {exc.status_code}: {_api_message(exc)}") from exc
        except openai.APIConnectionError as exc:
            raise ModelUnavailableError(
                f"Cannot reach the VLM at {settings.deepinfra_base_url}: {exc.__cause__ or exc}"
            ) from exc

        elapsed = time.perf_counter() - started
        if response.usage:
            usage.prompt_tokens += response.usage.prompt_tokens or 0
            usage.completion_tokens += response.usage.completion_tokens or 0
            usage.total_tokens += response.usage.total_tokens or 0
        choice = response.choices[0] if response.choices else None
        content = (choice.message.content if choice and choice.message else None) or ""
        finish = choice.finish_reason if choice else None
        log.info(
            "VLM answered in %.1fs (finish=%s, prompt_tokens=%s, completion_tokens=%s)",
            elapsed,
            finish,
            response.usage.prompt_tokens if response.usage else "?",
            response.usage.completion_tokens if response.usage else "?",
        )
        if finish == "length":
            log.warning("VLM output was cut off at VLM_MAX_TOKENS=%d", settings.vlm_max_tokens)
        log.debug("VLM raw output (truncated): %.3000s", content)
        return content


def _api_message(exc: openai.APIStatusError) -> str:
    body = exc.body
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("error") or body.get("message")
        if detail:
            return str(detail)[:500]
    return str(exc.message)[:500]
