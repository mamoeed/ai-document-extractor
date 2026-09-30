from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, Union

import pytest

from po_extractor import Settings
from po_extractor.llm import client as client_module

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLES = REPO_ROOT / "samples"


def _master_path(env_var: str, file_name: str) -> Path:
    from_env = os.environ.get(env_var)
    if from_env and Path(from_env).is_file():
        return Path(from_env)
    return REPO_ROOT / "data" / "master" / file_name


CUSTOMER_MASTER = _master_path("CUSTOMER_MASTER_PATH", "fictional_customer_master.xlsx")
ITEM_MASTER = _master_path("ITEM_MASTER_PATH", "fictional_item_master.xlsx")

SAMPLE_CLEARLINE_PDF = SAMPLES / "purchase_order_clearline_en_example_1.pdf"
SAMPLE_NORTHBRIDGE_PNG = SAMPLES / "Order example 4.png"
SAMPLE_NORTHBRIDGE_XLSX = SAMPLES / "purchase_order_northbridge.xlsx"
SAMPLE_NORTHBRIDGE_PDF = SAMPLES / "purchase_order_northbridge_en_example3.pdf"
SAMPLE_NORTHSTAR_PDF = SAMPLES / "purchase_order_northstar_en_example2.pdf"
SAMPLE_NORTHSTAR_XLSX = SAMPLES / "purchase_order_northstar.xlsx"

HIGH_CONFIDENCE = {"order_number": 0.98, "customer_number": 0.97, "legal_name": 0.95, "line_items": 0.96}

CLEARLINE_ORDER: dict[str, Any] = {
    "document": {
        "order_number": "OR2607421",
        "order_date": "2026-08-18",
        "requested_delivery_date": "2026-08-22",
        "currency": "EUR",
    },
    "customer": {
        "customer_number": "48326",
        "legal_name": "Clearline Hygiene GmbH",  # casing differs from master on purpose
        "street": "Example Park 9",
        "postcode": "86156",
        "city": "Augsburg",
        "country": None,
        "contact_name": "Alex Morgan",
        "email": None,
        "phone": "+49 30 5550 2400",
    },
    "delivery_address": {"name": None, "street": None, "postcode": None, "city": None, "country": None},
    "line_items": [
        {"position": "001", "item_number": "845271", "reference_number": "PX803174",
         "description": "CONVOClean forte, 10 litres UN 1814", "quantity": 40, "unit": "canisters",
         "unit_price": 56.25, "discount_percent": None, "line_net_amount": 2250.0},
        {"position": "002", "item_number": "725904", "reference_number": "725904",
         "description": "Container filter hose, 4 mm", "quantity": 50, "unit": "pcs",
         "unit_price": 3.33, "discount_percent": None, "line_net_amount": 166.5},
        {"position": "003", "item_number": "725918", "reference_number": "725918",
         "description": "Filter weight, ID 7 mm, OD 15 mm, L 20 mm", "quantity": 50, "unit": "pcs",
         "unit_price": 1.81, "discount_percent": None, "line_net_amount": 90.5},
    ],
    "totals": {"net_amount": 2507.0, "vat_percent": 19, "vat_amount": 476.33, "gross_amount": 2983.33},
    "field_confidence": HIGH_CONFIDENCE,
    "extraction_notes": None,
}

NORTHBRIDGE_PNG_ORDER: dict[str, Any] = {
    "document": {"order_number": "PO-7642091", "order_date": "2026-08-18", "requested_delivery_date": "2026-08-18",
                 "currency": "EUR"},
    "customer": {"customer_number": "58264", "legal_name": "Northbridge Catering Systems Ltd.",
                 "street": "Example Quay 16", "postcode": "00000", "city": "Sampletown", "country": "Germany",
                 "contact_name": "Reed, Morgan", "email": "procurement@northbridge-example.com",
                 "phone": "+49 40 5550-4311"},
    "delivery_address": {"name": "Northbridge Catering Systems Ltd.", "street": "Example Quay 16",
                         "postcode": "00000", "city": "Sampletown", "country": "Germany"},
    "line_items": [
        {"position": "1", "item_number": "7842136", "reference_number": "628450; DR-84.7315.204",
         "description": "RHK 6000 W 400/415", "quantity": 5, "unit": "Stk", "unit_price": 223.6,
         "discount_percent": None, "line_net_amount": 1118.0},
    ],
    "totals": {"net_amount": 1118.0, "vat_percent": None, "vat_amount": None, "gross_amount": None},
    "field_confidence": HIGH_CONFIDENCE,
    "extraction_notes": None,
}

NORTHBRIDGE_XLSX_ORDER: dict[str, Any] = copy.deepcopy(NORTHBRIDGE_PNG_ORDER)
NORTHBRIDGE_XLSX_ORDER["line_items"] = [
    {"position": "1", "item_number": "7842136", "reference_number": None,
     "description": "Tubular heating element, 6,000 W, 400/415 V", "quantity": 5, "unit": "pcs",
     "unit_price": 223.6, "discount_percent": 0, "line_net_amount": 1118.0},
    {"position": "2", "item_number": "628450", "reference_number": None,
     "description": "Mounting kit for heating element", "quantity": 5, "unit": "sets",
     "unit_price": 18.4, "discount_percent": 0, "line_net_amount": 92.0},
]


def order_dict(template: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    data = copy.deepcopy(template)
    for dotted, value in overrides.items():
        target = data
        *parents, leaf = dotted.split("__")
        for key in parents:
            target = target[key]
        target[leaf] = value
    return data


# ------------------------------------------------------------------ fake VLM

@dataclass
class StreamReply:
    """A streamed answer; ``fail_after_first_chunk`` is raised while the stream is being read."""

    content: str
    finish_reason: str = "stop"
    fail_after_first_chunk: Optional[Exception] = None


Reply = Union[str, dict, Exception, StreamReply]


def _usage(cost: Optional[float]) -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=1000, completion_tokens=200, total_tokens=1200, estimated_cost=cost)


def _chunk(content: Optional[str] = None, finish: Optional[str] = None, usage: Any = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)], usage=usage)


class FakeStream:
    """Mimics DeepInfra: content chunks, a finish chunk with usage (no cost), then a usage-only chunk with cost."""

    def __init__(self, reply: StreamReply) -> None:
        self.reply = reply
        self.closed = False

    def __iter__(self):
        text = self.reply.content
        size = max(1, len(text) // 3)
        for index, start in enumerate(range(0, len(text), size)):
            yield _chunk(content=text[start : start + size])
            if index == 0 and self.reply.fail_after_first_chunk is not None:
                raise self.reply.fail_after_first_chunk
        yield _chunk(finish=self.reply.finish_reason, usage=_usage(None))
        yield SimpleNamespace(choices=[], usage=_usage(0.0004))

    def close(self) -> None:
        self.closed = True


class FakeCompletions:
    def __init__(self, replies: list[Reply]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.streams: list[FakeStream] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(copy.deepcopy(kwargs))
        if not self.replies:
            raise AssertionError("FakeOpenAI: no more replies queued")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if not isinstance(reply, StreamReply):
            reply = StreamReply(reply if isinstance(reply, str) else json.dumps(reply))
        assert kwargs.get("stream") is True, "the client must stream"
        self.streams.append(FakeStream(reply))
        return self.streams[-1]


class FakeOpenAI:
    """Stands in for openai.OpenAI; records constructor kwargs and calls."""

    last: "FakeOpenAI | None" = None

    def __init__(self, replies: list[Reply], **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.completions = FakeCompletions(replies)
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.fixture
def fake_vlm(monkeypatch):
    """Usage: ``fake = fake_vlm(reply1, reply2, ...)``; replies are dicts, strings or exceptions."""

    def install(*replies: Reply) -> FakeOpenAI:
        holder: dict[str, FakeOpenAI] = {}

        def factory(**kwargs: Any) -> FakeOpenAI:
            holder["client"] = FakeOpenAI(list(replies), **kwargs)
            return holder["client"]

        monkeypatch.setattr(client_module, "OpenAI", factory)

        class Handle:
            @property
            def client(self) -> FakeOpenAI:
                return holder["client"]

            @property
            def calls(self) -> list[dict[str, Any]]:
                return holder["client"].completions.calls if "client" in holder else []

        return Handle()  # type: ignore[return-value]

    return install


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    monkeypatch.setattr(client_module, "_RETRY_DELAY_S", 0)


@pytest.fixture
def settings() -> Settings:
    return Settings(deepinfra_api_key="test-key", vlm_model="test/vlm-model", vlm_max_retries=2,
                    sanity_checks_mode="mock", confidence_threshold=0.8)


@pytest.fixture
def masters() -> tuple[Path, Path]:
    return CUSTOMER_MASTER, ITEM_MASTER
