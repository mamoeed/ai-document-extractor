import pytest

from po_extractor.schemas import ExtractedOrder, Issue, IssueCode, ItemMatch
from po_extractor.scoring import compute_match_result, score, sort_issues

from .conftest import CLEARLINE_ORDER, order_dict


def _order(**overrides) -> ExtractedOrder:
    return ExtractedOrder.model_validate(order_dict(CLEARLINE_ORDER, **overrides))


def _items(*matched: bool) -> list[ItemMatch]:
    return [ItemMatch(line_index=i, item_number=str(i), matched=m) for i, m in enumerate(matched)]


def _issue(code: str, severity: str = "error") -> Issue:
    return Issue(code=code, severity=severity, message=code)


@pytest.mark.parametrize(
    "customer_matched, items, expected",
    [
        (True, (True, True), "FULL_MATCH"),
        (False, (True, True), "PARTIAL_MATCH"),
        (True, (True, False), "NO_MATCH"),
        (False, (False,), "NO_MATCH"),
        (True, (), "NO_MATCH"),
    ],
)
def test_match_result(customer_matched, items, expected):
    assert compute_match_result(customer_matched, _items(*items)) == expected


@pytest.mark.parametrize("code", sorted(IssueCode.BLOCKING))
def test_blocking_error_gives_error_status(code):
    result = score(_order(), customer_matched=True, item_matches=_items(True), issues=[_issue(code)], threshold=0.8)
    assert result.status == "ERROR"
    assert result.match_result is None
    assert result.confidence_score == 0
    assert result.needs_human_review


def test_no_order_is_error():
    result = score(None, customer_matched=False, item_matches=[], issues=[], threshold=0.8)
    assert result.status == "ERROR" and result.extraction_confidence is None


def test_full_match_high_confidence_is_confident():
    result = score(_order(), customer_matched=True, item_matches=_items(True, True, True), issues=[], threshold=0.8)
    assert result.status == "CONFIDENT_MATCH"
    assert result.match_result == "FULL_MATCH"
    assert result.confidence_score == 0.95  # min(field_confidence) * 1.0
    assert not result.needs_human_review
    assert not result.issues


def test_partial_match_is_low_confidence_with_factor():
    result = score(_order(), customer_matched=False, item_matches=_items(True), issues=[], threshold=0.8)
    assert result.status == "LOW_CONFIDENCE"
    assert result.match_result == "PARTIAL_MATCH"
    assert result.confidence_score == 0.57  # 0.95 * 0.6
    assert result.needs_human_review


def test_no_match_factor():
    result = score(_order(), customer_matched=True, item_matches=_items(True, False), issues=[], threshold=0.8)
    assert result.status == "LOW_CONFIDENCE"
    assert result.match_result == "NO_MATCH"
    assert result.confidence_score == 0.29  # 0.95 * 0.3 = 0.285 -> 0.29


def test_low_field_confidence_adds_issue():
    order = _order(field_confidence__legal_name=0.6)
    result = score(order, customer_matched=True, item_matches=_items(True), issues=[], threshold=0.8)
    assert result.status == "LOW_CONFIDENCE"
    assert result.match_result == "FULL_MATCH"
    assert result.confidence_score == 0.6
    assert [i.code for i in result.issues] == [IssueCode.LOW_EXTRACTION_CONFIDENCE]
    assert result.issues[0].field == "field_confidence.legal_name"
    assert "legal_name=0.60" in result.issues[0].message


def test_threshold_is_inclusive():
    order = _order(field_confidence__legal_name=0.8)
    result = score(order, customer_matched=True, item_matches=_items(True), issues=[], threshold=0.8)
    assert result.status == "CONFIDENT_MATCH"


def test_unreported_confidence_counts_as_zero():
    order = _order(field_confidence__line_items=None)
    result = score(order, customer_matched=True, item_matches=_items(True), issues=[], threshold=0.8)
    assert result.status == "LOW_CONFIDENCE"
    assert result.confidence_score == 0
    assert result.issues[0].code == IssueCode.LOW_EXTRACTION_CONFIDENCE


def test_missing_order_number_counts_as_zero_confidence():
    order = _order(document__order_number=None)
    result = score(order, customer_matched=True, item_matches=_items(True), issues=[], threshold=0.8)
    assert result.status == "LOW_CONFIDENCE"
    assert "order_number missing" in result.issues[0].message


def test_sanity_issue_gives_low_confidence():
    issues = [_issue(IssueCode.SANITY_CHECK_FAILED, "warning")]
    result = score(_order(), customer_matched=True, item_matches=_items(True), issues=issues, threshold=0.8)
    assert result.status == "LOW_CONFIDENCE"
    assert result.match_result == "FULL_MATCH"
    assert result.confidence_score == 0.95


def test_human_verified_ignores_model_confidence():
    order = _order(field_confidence__legal_name=0.3)
    result = score(order, customer_matched=True, item_matches=_items(True), issues=[], threshold=0.8,
                   human_verified=True)
    assert result.status == "CONFIDENT_MATCH"
    assert result.confidence_score == 1.0
    assert result.extraction_confidence == 0.3  # what the model reported is still visible
    assert not result.issues


def test_human_verified_partial_match_still_low_confidence():
    result = score(_order(), customer_matched=False, item_matches=_items(True), issues=[], threshold=0.8,
                   human_verified=True)
    assert result.status == "LOW_CONFIDENCE"
    assert result.confidence_score == 0.6


def test_sort_issues_errors_first():
    issues = [_issue("A", "info"), _issue("B", "warning"), _issue("C", "error"), _issue("D", "error")]
    assert [i.code for i in sort_issues(issues)] == ["C", "D", "B", "A"]
