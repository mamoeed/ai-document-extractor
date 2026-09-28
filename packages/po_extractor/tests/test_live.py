"""Integration tests against the real DeepInfra VLM.

Deselected by default (they cost tokens); skipped unless DEEPINFRA_API_KEY is set (in the
environment or the repo-root .env). Run with:  pytest -m live -v -s
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pytest

from po_extractor import ConfigError, Settings, process_file
from po_extractor.validate.normalize import normalize_name

from .conftest import (
    CUSTOMER_MASTER,
    ITEM_MASTER,
    REPO_ROOT,
    SAMPLE_CLEARLINE_PDF,
    SAMPLE_NORTHBRIDGE_PDF,
    SAMPLE_NORTHBRIDGE_PNG,
    SAMPLE_NORTHBRIDGE_XLSX,
    SAMPLE_NORTHSTAR_PDF,
    SAMPLE_NORTHSTAR_XLSX,
)


def _live_settings() -> Optional[Settings]:
    env_file = REPO_ROOT / ".env"
    settings = Settings(_env_file=env_file) if env_file.is_file() else Settings()  # type: ignore[call-arg]
    try:
        settings.require_llm()
    except ConfigError:
        return None
    return settings


LIVE_SETTINGS = _live_settings()
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(LIVE_SETTINGS is None, reason="DEEPINFRA_API_KEY not set"),
]


@dataclass
class Case:
    sample: Path
    method: str
    order_number: str
    customer_number: str
    legal_name: str
    item_numbers: list[str]
    match_result: str
    status: Optional[str] = None  # None: depends on the model's self-reported confidence
    issue_codes: set[str] = field(default_factory=set)
    reference_contains: Optional[str] = None


CASES = {
    # Acceptance criteria (§8)
    "clearline_pdf": Case(SAMPLE_CLEARLINE_PDF, "pdf_text_vlm", "OR2607421", "48326", "ClearLine Hygiene GmbH",
                          ["845271", "725904", "725918"], "FULL_MATCH", "CONFIDENT_MATCH"),
    "northbridge_png": Case(SAMPLE_NORTHBRIDGE_PNG, "image_vlm", "PO-7642091", "58264",
                            "Northbridge Catering Systems Ltd.", ["7842136"], "PARTIAL_MATCH", "LOW_CONFIDENCE",
                            {"CUSTOMER_NOT_FOUND"}, reference_contains="628450"),
    "northbridge_xlsx": Case(SAMPLE_NORTHBRIDGE_XLSX, "excel_text_vlm", "PO-7642091", "58264",
                             "Northbridge Catering Systems Ltd.", ["7842136", "628450"], "NO_MATCH",
                             "LOW_CONFIDENCE", {"CUSTOMER_NOT_FOUND", "ITEM_NOT_FOUND"}),
    # Extra scenarios from the master files' "Test Scenarios" sheet
    "northstar_pdf": Case(SAMPLE_NORTHSTAR_PDF, "pdf_text_vlm", "SR-482716-9", "48326",
                          "Northstar Commercial Kitchens Ltd.", ["NTH-481732"], "FULL_MATCH"),
    "northbridge_pdf": Case(SAMPLE_NORTHBRIDGE_PDF, "pdf_image_vlm", "PO-7642091", "58264",
                            "Northbridge Catering Systems Ltd.", ["7842136"], "PARTIAL_MATCH", "LOW_CONFIDENCE",
                            {"CUSTOMER_NOT_FOUND"}),
    "northstar_xlsx": Case(SAMPLE_NORTHSTAR_XLSX, "excel_text_vlm", "PO-SR-482716-9", "48326",
                           "Northstar Commercial Kitchens Ltd.", [], "FULL_MATCH"),
}


@pytest.mark.parametrize("name", list(CASES))
def test_live_sample(name):
    case = CASES[name]
    result = process_file(case.sample, CUSTOMER_MASTER, ITEM_MASTER, LIVE_SETTINGS)
    print(result.model_dump_json(indent=2, exclude={"customer_match", "item_matches"}))

    assert result.status != "ERROR", result.issues
    order = result.extracted
    assert result.meta.extraction_method == case.method
    assert order.document.order_number == case.order_number
    assert order.customer.customer_number == case.customer_number
    assert normalize_name(order.customer.legal_name) == normalize_name(case.legal_name)
    numbers = [line.item_number for line in order.line_items]
    if case.item_numbers:
        assert numbers == case.item_numbers
    else:
        assert len(numbers) == 22 and all(n.startswith("NTH-") for n in numbers)
    if case.reference_contains:
        assert case.reference_contains in (order.line_items[0].reference_number or "")
    assert result.match_result == case.match_result
    if case.status:
        assert result.status == case.status
    assert case.issue_codes <= {issue.code for issue in result.issues}
