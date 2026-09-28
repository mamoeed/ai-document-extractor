"""Sanity checks on the extracted values (§3.5.1).

MOCK for now: with ``SANITY_CHECKS_MODE=mock`` (default) no checks run. The individual
checks below are TODO stubs; each should return ``SANITY_CHECK_FAILED`` issues
(severity ``warning``) pointing at the offending ``field``.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..config import Settings
from ..schemas import ExtractedOrder, Issue

TOLERANCE = 0.01


def run_sanity_checks(order: ExtractedOrder, settings: Optional[Settings] = None) -> list[Issue]:
    mode = (settings or Settings()).sanity_checks_mode
    if mode == "mock":
        return []
    issues: list[Issue] = []
    for check in CHECKS:
        issues.extend(check(order))
    return issues


def check_line_amounts(order: ExtractedOrder) -> list[Issue]:
    """TODO: for every line, quantity x unit_price (less discount_percent) must equal
    line_net_amount within ±0.01. Field: ``line_items[i].line_net_amount``."""
    return []


def check_lines_sum_to_net(order: ExtractedOrder) -> list[Issue]:
    """TODO: the sum of all line_net_amount values must equal totals.net_amount (±0.01)."""
    return []


def check_vat_amount(order: ExtractedOrder) -> list[Issue]:
    """TODO: totals.net_amount x totals.vat_percent / 100 must equal totals.vat_amount (±0.01)."""
    return []


def check_gross_amount(order: ExtractedOrder) -> list[Issue]:
    """TODO: totals.net_amount + totals.vat_amount must equal totals.gross_amount (±0.01)."""
    return []


def check_delivery_after_order(order: ExtractedOrder) -> list[Issue]:
    """TODO: document.requested_delivery_date must be on or after document.order_date."""
    return []


CHECKS: list[Callable[[ExtractedOrder], list[Issue]]] = [
    check_line_amounts,
    check_lines_sum_to_net,
    check_vat_amount,
    check_gross_amount,
    check_delivery_after_order,
]
