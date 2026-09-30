"""OpenAI-compatible client pointed at DeepInfra: one model for image and text input."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
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


# Retry once, after a short pause, when the request could not be started (429/5xx/connection reset).
# A request that timed out is NOT retried: it would only double the wait.
_RETRY_DELAY_S = 2.0
_PROGRESS_LOG_EVERY_S = 30.0


class VLMClient:
    """Streams the model's answer: VLM_TIMEOUT_S is the longest allowed silence between received
    chunks, VLM_TOTAL_TIMEOUT_S caps all model calls for one file (retries included)."""

    def __init__(self, settings: Settings) -> None:
        settings.require_llm()
        self.settings = settings
        self._client = OpenAI(
            base_url=settings.deepinfra_base_url,
            api_key=settings.deepinfra_api_key.get_secret_value(),  # type: ignore[union-attr]
            timeout=settings.vlm_timeout_s,  # per read: with streaming this is an inactivity timeout
            max_retries=0,  # retries are handled in _open_stream (never for timeouts)
        )

    def extract(self, payload: ExtractionInput) -> ExtractionOutput:
        """Call the VLM, validate against ``ExtractedOrder``, retry with the error on failure."""
        messages = build_messages(payload)
        usage = TokenUsage()
        max_attempts = self.settings.vlm_max_retries + 1
        deadline = time.perf_counter() + self.settings.vlm_total_timeout_s
        last_error, raw = "", ""
        for attempt in range(1, max_attempts + 1):
            raw, finish = self._complete(messages, usage, attempt, deadline)
            try:
                order = ExtractedOrder.model_validate(parse_json_response(raw))
            except (ValueError, ValidationError) as exc:  # JSONDecodeError is a ValueError
                if finish == "length":
                    # Retrying would be cut off at the same place.
                    raise ExtractionSchemaError(
                        f"Model output was cut off at VLM_MAX_TOKENS={self.settings.vlm_max_tokens} tokens "
                        "(order too long for the limit) - raise VLM_MAX_TOKENS in .env",
                        raw_output=raw,
                        attempts=attempt,
                        usage=usage,
                    ) from exc
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

    def _complete(
        self, messages: list[dict[str, Any]], usage: TokenUsage, attempt: int, deadline: float
    ) -> tuple[str, Optional[str]]:
        """One streamed completion. Returns (content, finish_reason) and adds to ``usage``."""
        settings = self.settings
        kwargs: dict[str, Any] = {
            "model": settings.vlm_model,
            "messages": messages,
            "temperature": settings.vlm_temperature,
            "max_tokens": settings.vlm_max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if settings.vlm_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        log.info("Calling VLM %s (attempt %d, streaming)", settings.vlm_model, attempt)
        stream = self._open_stream(kwargs)

        parts: list[str] = []
        finish: Optional[str] = None
        last_usage: Any = None
        next_progress_log = started + _PROGRESS_LOG_EVERY_S
        try:
            for chunk in stream:
                if chunk.usage is not None:
                    last_usage = chunk.usage  # DeepInfra repeats usage; the last copy carries estimated_cost
                for choice in chunk.choices or []:
                    if choice.delta is not None and choice.delta.content:
                        parts.append(choice.delta.content)
                    if choice.finish_reason:
                        finish = choice.finish_reason
                now = time.perf_counter()
                if now > deadline:
                    raise ModelUnavailableError(
                        f"VLM did not finish within VLM_TOTAL_TIMEOUT_S={settings.vlm_total_timeout_s:g}s "
                        f"({sum(map(len, parts))} characters received)"
                    )
                if now >= next_progress_log:
                    log.info("VLM still generating: %d characters after %.0fs", sum(map(len, parts)), now - started)
                    next_progress_log += _PROGRESS_LOG_EVERY_S
        except httpx.TimeoutException as exc:
            raise ModelUnavailableError(
                f"VLM stopped sending data for {settings.vlm_timeout_s:g}s (VLM_TIMEOUT_S) after "
                f"{time.perf_counter() - started:.0f}s and {sum(map(len, parts))} characters"
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailableError(
                f"Connection to the VLM broke after {time.perf_counter() - started:.0f}s: {type(exc).__name__}: {exc}"
            ) from exc
        except openai.APIError as exc:  # error event sent inside the stream
            raise ModelUnavailableError(f"VLM reported an error mid-response: {exc}") from exc
        finally:
            stream.close()

        content = "".join(parts)
        cost = estimated_cost(last_usage)
        if last_usage is not None:
            usage.prompt_tokens += last_usage.prompt_tokens or 0
            usage.completion_tokens += last_usage.completion_tokens or 0
            usage.total_tokens += last_usage.total_tokens or 0
            if cost is not None:
                usage.estimated_cost_usd = (usage.estimated_cost_usd or 0.0) + cost
        log.info(
            "VLM answered in %.1fs (finish=%s, prompt_tokens=%s, completion_tokens=%s, estimated_cost=%s)",
            time.perf_counter() - started,
            finish,
            last_usage.prompt_tokens if last_usage is not None else "?",
            last_usage.completion_tokens if last_usage is not None else "?",
            f"${cost:.6f}" if cost is not None else "n/a",
        )
        if finish == "length":
            log.warning("VLM output was cut off at VLM_MAX_TOKENS=%d", settings.vlm_max_tokens)
        log.debug("VLM raw output (truncated): %.3000s", content)
        return content, finish

    def _open_stream(self, kwargs: dict[str, Any]) -> Any:
        settings = self.settings
        for try_number in (1, 2):
            try:
                return self._client.chat.completions.create(**kwargs)
            except openai.APITimeoutError as exc:  # before APIConnectionError: it is a subclass
                raise ModelUnavailableError(
                    f"VLM did not start answering within {settings.vlm_timeout_s:g}s (VLM_TIMEOUT_S)"
                ) from exc
            except openai.AuthenticationError as exc:
                raise ModelUnavailableError(
                    f"DeepInfra rejected the API key (HTTP 401) - check DEEPINFRA_API_KEY. {_api_message(exc)}"
                ) from exc
            except openai.NotFoundError as exc:
                raise ModelUnavailableError(
                    f"Model '{settings.vlm_model}' not found (HTTP 404) - check VLM_MODEL. {_api_message(exc)}"
                ) from exc
            except (openai.RateLimitError, openai.InternalServerError) as exc:
                if try_number == 1:
                    log.warning("VLM returned HTTP %d, retrying once in %gs", exc.status_code, _RETRY_DELAY_S)
                    time.sleep(_RETRY_DELAY_S)
                    continue
                raise ModelUnavailableError(f"VLM returned HTTP {exc.status_code}: {_api_message(exc)}") from exc
            except openai.APIStatusError as exc:
                raise ModelUnavailableError(f"VLM returned HTTP {exc.status_code}: {_api_message(exc)}") from exc
            except openai.APIConnectionError as exc:
                if try_number == 1:
                    log.warning("Cannot reach the VLM (%s), retrying once in %gs", exc.__cause__ or exc, _RETRY_DELAY_S)
                    time.sleep(_RETRY_DELAY_S)
                    continue
                raise ModelUnavailableError(
                    f"Cannot reach the VLM at {settings.deepinfra_base_url}: {exc.__cause__ or exc}"
                ) from exc
        raise AssertionError("unreachable")  # pragma: no cover


def estimated_cost(usage: Any) -> Optional[float]:
    """DeepInfra adds ``estimated_cost`` (USD) to the OpenAI ``usage`` object; the SDK keeps it as an extra field."""
    if usage is None:
        return None
    value = getattr(usage, "estimated_cost", None)
    if value is None:
        value = (getattr(usage, "model_extra", None) or {}).get("estimated_cost")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _api_message(exc: openai.APIStatusError) -> str:
    body = exc.body
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("error") or body.get("message")
        if detail:
            return str(detail)[:500]
    return str(exc.message)[:500]
