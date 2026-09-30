"""Pydantic models: the extraction schema (§3.2) and the processing result (§3.6)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from .validate.normalize import normalize_id, parse_date, parse_number

# --------------------------------------------------------------------- coercion


def _to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return normalize_id(value)
    if isinstance(value, (list, dict)):
        raise ValueError("expected a string")
    text = str(value).strip()
    return text or None


def _to_id(value: Any) -> Optional[str]:
    if isinstance(value, (list, dict)):
        raise ValueError("expected a string or number")
    return normalize_id(value)


def _to_confidence(value: Any) -> Optional[float]:
    number = parse_number(value)
    if number is not None and 1 < number <= 100:  # model answered in percent
        number = number / 100
    return number


def _to_currency(value: Any) -> Optional[str]:
    text = _to_str(value)
    if text is None:
        return None
    return {"€": "EUR", "$": "USD", "£": "GBP"}.get(text, text.upper() if len(text) == 3 else text)


Str = Annotated[Optional[str], BeforeValidator(_to_str)]
IdStr = Annotated[Optional[str], BeforeValidator(_to_id)]
Number = Annotated[Optional[float], BeforeValidator(parse_number)]
IsoDate = Annotated[Optional[date], BeforeValidator(parse_date)]
Confidence = Annotated[Optional[Annotated[float, Field(ge=0, le=1)]], BeforeValidator(_to_confidence)]
Currency = Annotated[Optional[str], BeforeValidator(_to_currency)]


class _Model(BaseModel):
    # The VLM (and human editors) may add keys we do not know; ignore them.
    model_config = ConfigDict(extra="ignore")


# ------------------------------------------------------------ ExtractedOrder §3.2


class Document(_Model):
    order_number: IdStr = None
    order_date: IsoDate = None
    requested_delivery_date: IsoDate = None
    currency: Currency = None


class Customer(_Model):
    customer_number: IdStr = None
    legal_name: Str = None
    street: Str = None
    postcode: IdStr = None
    city: Str = None
    country: Str = None
    contact_name: Str = None
    email: Str = None
    phone: Str = None


class DeliveryAddress(_Model):
    name: Str = None
    street: Str = None
    postcode: IdStr = None
    city: Str = None
    country: Str = None


class LineItem(_Model):
    position: IdStr = None
    item_number: IdStr = None
    reference_number: IdStr = None
    description: Str = None
    quantity: Number = None
    unit: Str = None
    unit_price: Number = None
    discount_percent: Number = None
    line_net_amount: Number = None


class Totals(_Model):
    net_amount: Number = None
    vat_percent: Number = None
    vat_amount: Number = None
    gross_amount: Number = None


class FieldConfidence(_Model):
    order_number: Confidence = None
    customer_number: Confidence = None
    legal_name: Confidence = None
    line_items: Confidence = None


class ExtractedOrder(_Model):
    """The order as read from the document. Required-by-business fields are nullable here;
    missing values are reported as issues by the deterministic validation instead."""

    document: Document = Field(default_factory=Document)
    customer: Customer = Field(default_factory=Customer)
    delivery_address: DeliveryAddress = Field(default_factory=DeliveryAddress)
    line_items: list[LineItem] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    field_confidence: FieldConfidence = Field(default_factory=FieldConfidence)
    extraction_notes: Str = None

    @model_validator(mode="before")
    @classmethod
    def _nulls_to_empty(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for key in ("document", "customer", "delivery_address", "totals", "field_confidence"):
            if data.get(key) is None:
                data.pop(key, None)
        items = data.get("line_items")
        if items is None:
            data.pop("line_items", None)
        elif isinstance(items, list):
            data["line_items"] = [item for item in items if item is not None]
        return data


# --------------------------------------------------------- ProcessingResult §3.6

Status = Literal["CONFIDENT_MATCH", "LOW_CONFIDENCE", "ERROR"]
MatchResult = Literal["FULL_MATCH", "PARTIAL_MATCH", "NO_MATCH"]
Severity = Literal["error", "warning", "info"]


class IssueCode:
    # Errors (blocking)
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_UNREADABLE = "FILE_UNREADABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    EXTRACTION_SCHEMA_INVALID = "EXTRACTION_SCHEMA_INVALID"
    NO_LINE_ITEMS = "NO_LINE_ITEMS"
    # Match issues
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
    CUSTOMER_NAME_MISMATCH = "CUSTOMER_NAME_MISMATCH"
    CUSTOMER_FIELDS_MISSING = "CUSTOMER_FIELDS_MISSING"
    ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
    ITEM_INACTIVE = "ITEM_INACTIVE"
    # Quality issues
    LOW_EXTRACTION_CONFIDENCE = "LOW_EXTRACTION_CONFIDENCE"
    SANITY_CHECK_FAILED = "SANITY_CHECK_FAILED"

    BLOCKING = frozenset(
        {UNSUPPORTED_FILE_TYPE, FILE_UNREADABLE, MODEL_UNAVAILABLE, EXTRACTION_SCHEMA_INVALID, NO_LINE_ITEMS}
    )


class Issue(BaseModel):
    code: str
    severity: Severity
    message: str
    field: Optional[str] = None


class CustomerMatch(BaseModel):
    matched: bool = False
    master_record: Optional[dict[str, Any]] = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class ItemMatch(BaseModel):
    line_index: int
    item_number: Optional[str] = None
    matched: bool = False
    master_record: Optional[dict[str, Any]] = None
    reason: Optional[str] = None  # issue code when not matched


class Summary(BaseModel):
    customer: Optional[str] = None
    customer_matched: bool = False
    items_matched: int = 0
    items_total: int = 0


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # DeepInfra's usage.estimated_cost, summed over attempts; None if the provider did not report it.
    estimated_cost_usd: Optional[float] = None


class Meta(BaseModel):
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    extraction_method: Optional[str] = None
    model_name: Optional[str] = None
    duration_ms: int = 0
    token_usage: Optional[TokenUsage] = None
    llm_attempts: int = 0
    pages_total: Optional[int] = None
    pages_sent: Optional[int] = None
    notes: list[str] = Field(default_factory=list)
    # Diagnostic details for failed runs (exception type, last raw model output, ...).
    debug: Optional[dict[str, Any]] = None


class ProcessingResult(BaseModel):
    status: Status
    match_result: Optional[MatchResult] = None
    confidence_score: float = 0.0
    needs_human_review: bool = True
    issues: list[Issue] = Field(default_factory=list)
    extracted: Optional[ExtractedOrder] = None
    customer_match: CustomerMatch = Field(default_factory=CustomerMatch)
    item_matches: list[ItemMatch] = Field(default_factory=list)
    summary: Summary = Field(default_factory=Summary)
    meta: Meta = Field(default_factory=Meta)
    # Lowest field_confidence as reported by the model (None if not applicable).
    extraction_confidence: Optional[float] = None
    # True when the order values were confirmed by a human (validate_order(human_verified=True)).
    human_verified: bool = False
