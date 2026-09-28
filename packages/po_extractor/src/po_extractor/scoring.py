"""Status, match result and confidence score (§3.7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from .schemas import ExtractedOrder, Issue, IssueCode, ItemMatch, MatchResult, Status

MATCH_FACTORS: dict[str, float] = {"FULL_MATCH": 1.0, "PARTIAL_MATCH": 0.6, "NO_MATCH": 0.3}
CONFIDENCE_FIELDS = ("order_number", "customer_number", "legal_name", "line_items")
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Score:
    status: Status
    match_result: Optional[MatchResult]
    confidence_score: float
    needs_human_review: bool
    extraction_confidence: Optional[float]
    issues: list[Issue] = field(default_factory=list)  # issues added by scoring


def compute_match_result(customer_matched: bool, item_matches: list[ItemMatch]) -> MatchResult:
    """FULL_MATCH: customer + all items; PARTIAL_MATCH: all items but not the customer;
    NO_MATCH: at least one item did not match."""
    if not item_matches or not all(m.matched for m in item_matches):
        return "NO_MATCH"
    return "FULL_MATCH" if customer_matched else "PARTIAL_MATCH"


def reported_confidence(order: ExtractedOrder) -> float:
    """Lowest field_confidence as reported by the model; an unreported value counts as 0."""
    values = [getattr(order.field_confidence, name) for name in CONFIDENCE_FIELDS]
    return min(0.0 if v is None else v for v in values)


def effective_confidences(order: ExtractedOrder, human_verified: bool) -> dict[str, float]:
    """Per-field confidence used for scoring.

    - A value the model did not report counts as 0 (we cannot claim confidence).
    - Values confirmed by a human count as 1.0.
    - A missing order number always counts as 0 (it is a required field).
    """
    values: dict[str, float] = {}
    for name in CONFIDENCE_FIELDS:
        reported = getattr(order.field_confidence, name)
        values[name] = 1.0 if human_verified else (0.0 if reported is None else float(reported))
    if not order.document.order_number:
        values["order_number"] = 0.0
    return values


def score(
    order: Optional[ExtractedOrder],
    *,
    customer_matched: bool,
    item_matches: list[ItemMatch],
    issues: list[Issue],
    threshold: float,
    human_verified: bool = False,
) -> Score:
    """Evaluate the rules in order: ERROR -> LOW_CONFIDENCE -> CONFIDENT_MATCH."""
    extraction_confidence = round2(reported_confidence(order)) if order is not None else None

    if order is None or any(issue.code in IssueCode.BLOCKING for issue in issues):
        return Score("ERROR", None, 0.0, True, extraction_confidence)

    match_result = compute_match_result(customer_matched, item_matches)
    confidences = effective_confidences(order, human_verified)
    min_confidence = min(confidences.values())

    added: list[Issue] = []
    if min_confidence < threshold:
        low = sorted((v, k) for k, v in confidences.items() if v < threshold)
        detail = ", ".join(
            "order_number missing" if (k == "order_number" and not order.document.order_number) else f"{k}={v:.2f}"
            for v, k in low
        )
        added.append(
            Issue(
                code=IssueCode.LOW_EXTRACTION_CONFIDENCE,
                severity="warning",
                message=f"Low extraction confidence: {detail} (threshold {threshold:.2f})",
                field=f"field_confidence.{low[0][1]}",
            )
        )

    has_sanity_issue = any(issue.code == IssueCode.SANITY_CHECK_FAILED for issue in issues)
    low_confidence = match_result != "FULL_MATCH" or has_sanity_issue or min_confidence < threshold
    status: Status = "LOW_CONFIDENCE" if low_confidence else "CONFIDENT_MATCH"
    confidence_score = round2(min_confidence * MATCH_FACTORS[match_result])
    return Score(
        status=status,
        match_result=match_result,
        confidence_score=confidence_score,
        needs_human_review=status != "CONFIDENT_MATCH",
        extraction_confidence=extraction_confidence,
        issues=added,
    )


def round2(value: float) -> float:
    """Round half-up to 2 decimals on the printed value (0.95 * 0.3 -> 0.29, not 0.28)."""
    return float(Decimal(repr(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sort_issues(issues: list[Issue]) -> list[Issue]:
    """Errors first, then warnings, then info (stable within a severity)."""
    return sorted(issues, key=lambda issue: _SEVERITY_ORDER.get(issue.severity, 9))
