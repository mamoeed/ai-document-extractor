"""Orchestration: process_file (steps 1-4) and validate_order (steps 2-4)."""

from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path
from typing import Any, Optional, Union

from .config import Settings
from .errors import (
    ExtractionSchemaError,
    FileUnreadableError,
    ModelUnavailableError,
    UnsupportedFileTypeError,
)
from .extract import build_extraction_input, detect_file_type
from .llm.client import VLMClient
from .schemas import (
    ExtractedOrder,
    Issue,
    IssueCode,
    Meta,
    ProcessingResult,
    Summary,
    TokenUsage,
)
from .scoring import score, sort_issues
from .validate.master_data import CustomerMaster, ItemMaster, load_customer_master, load_item_master
from .validate.matching import match_customer, match_items
from .validate.sanity import run_sanity_checks

log = logging.getLogger(__name__)

PathLike = Union[str, Path]


def process_file(
    file_path: PathLike,
    customer_master_path: PathLike,
    item_master_path: PathLike,
    settings: Optional[Settings] = None,
) -> ProcessingResult:
    """Extract, sanity-check and match one purchase order file.

    Never raises for problems with the document (returns ``status="ERROR"`` with issues).
    Raises ``ConfigError`` (missing API key / model) and ``MasterDataError`` (master file
    missing or malformed).
    """
    settings = settings or Settings()
    settings.require_llm()
    started = time.perf_counter()
    customers = load_customer_master(customer_master_path)
    items = load_item_master(item_master_path)

    path = Path(file_path)
    meta = Meta(file_name=path.name, model_name=settings.vlm_model)
    log.info("Processing %s", path.name)

    # Step 1a: detect type and extract raw content locally.
    try:
        if not path.is_file():
            raise FileUnreadableError(f"File not found: {path}")
        file_type = detect_file_type(path)
        meta.file_type = file_type
        payload = build_extraction_input(path, file_type, settings)
    except UnsupportedFileTypeError as exc:
        log.info("%s: unsupported file type (%s)", path.name, exc)
        return _error_result(IssueCode.UNSUPPORTED_FILE_TYPE, str(exc), meta, started)
    except FileUnreadableError as exc:
        log.warning("%s: file unreadable (%s)", path.name, exc)
        return _error_result(IssueCode.FILE_UNREADABLE, str(exc), meta, started)
    except Exception as exc:  # a parser crashing on a malformed file is a document problem
        log.exception("%s: unexpected error while reading the file", path.name)
        return _error_result(
            IssueCode.FILE_UNREADABLE,
            f"Could not read the file: {type(exc).__name__}: {exc}",
            meta,
            started,
            debug={"exception": type(exc).__name__, "traceback": traceback.format_exc()},
        )

    meta.extraction_method = payload.method
    meta.pages_total = payload.pages_total
    meta.pages_sent = payload.pages_sent
    meta.notes.extend(payload.notes)
    log.info("%s: type=%s method=%s images=%d", path.name, file_type, payload.method, len(payload.images))

    # Step 1b: VLM extraction.
    try:
        output = VLMClient(settings).extract(payload)
    except ModelUnavailableError as exc:
        log.error("%s: model unavailable: %s", path.name, exc)
        return _error_result(IssueCode.MODEL_UNAVAILABLE, str(exc), meta, started)
    except ExtractionSchemaError as exc:
        log.error("%s: extraction schema invalid after %d attempt(s): %s", path.name, exc.attempts, exc)
        meta.llm_attempts = exc.attempts
        meta.token_usage = exc.usage if isinstance(exc.usage, TokenUsage) else None
        return _error_result(
            IssueCode.EXTRACTION_SCHEMA_INVALID,
            str(exc),
            meta,
            started,
            debug={"last_raw_output": (exc.raw_output or "")[:4000]},
        )

    meta.llm_attempts = output.attempts
    meta.token_usage = output.usage

    # Steps 2-4.
    result = _run_validation(output.order, customers, items, settings, meta, human_verified=False)
    result.meta.duration_ms = _elapsed_ms(started)
    log.info(
        "%s: status=%s match=%s confidence=%.2f issues=%s (%d ms)",
        path.name,
        result.status,
        result.match_result,
        result.confidence_score,
        [issue.code for issue in result.issues],
        result.meta.duration_ms,
    )
    return result


def validate_order(
    order: Union[ExtractedOrder, dict[str, Any]],
    customer_master_path: PathLike,
    item_master_path: PathLike,
    settings: Optional[Settings] = None,
    *,
    human_verified: bool = False,
    meta: Optional[Meta] = None,
) -> ProcessingResult:
    """Re-run steps 2-4 on an (edited) order without calling any model.

    ``human_verified=True`` marks the values as confirmed by a person: the model's
    field_confidence is then not used for scoring (it counts as 1.0), and the result
    carries ``human_verified=True``.
    """
    settings = settings or Settings()
    started = time.perf_counter()
    if not isinstance(order, ExtractedOrder):
        order = ExtractedOrder.model_validate(order)
    customers = load_customer_master(customer_master_path)
    items = load_item_master(item_master_path)
    result = _run_validation(
        order, customers, items, settings, meta.model_copy(deep=True) if meta else Meta(), human_verified
    )
    result.meta.duration_ms = _elapsed_ms(started)
    return result


def _run_validation(
    order: ExtractedOrder,
    customers: CustomerMaster,
    items: ItemMaster,
    settings: Settings,
    meta: Meta,
    human_verified: bool,
) -> ProcessingResult:
    issues: list[Issue] = []
    if not order.line_items:
        issues.append(
            Issue(
                code=IssueCode.NO_LINE_ITEMS,
                severity="error",
                message="No line items were extracted from the document",
                field="line_items",
            )
        )

    issues.extend(run_sanity_checks(order, settings))
    customer_match, customer_issues = match_customer(order.customer, customers)
    item_matches, item_issues = match_items(order.line_items, items)
    issues.extend(customer_issues)
    issues.extend(item_issues)

    outcome = score(
        order,
        customer_matched=customer_match.matched,
        item_matches=item_matches,
        issues=issues,
        threshold=settings.confidence_threshold,
        human_verified=human_verified,
    )
    issues.extend(outcome.issues)

    return ProcessingResult(
        status=outcome.status,
        match_result=outcome.match_result,
        confidence_score=outcome.confidence_score,
        needs_human_review=outcome.needs_human_review,
        issues=sort_issues(issues),
        extracted=order,
        customer_match=customer_match,
        item_matches=item_matches,
        summary=Summary(
            customer=_customer_label(order, customer_match.master_record),
            customer_matched=customer_match.matched,
            items_matched=sum(1 for m in item_matches if m.matched),
            items_total=len(item_matches),
        ),
        meta=meta,
        extraction_confidence=outcome.extraction_confidence,
        human_verified=human_verified,
    )


def _customer_label(order: ExtractedOrder, master_record: Optional[dict[str, Any]]) -> Optional[str]:
    if master_record:
        return f"{master_record.get('Legal name')} ({master_record.get('Customer no.')})"
    name, number = order.customer.legal_name, order.customer.customer_number
    if name and number:
        return f"{name} ({number})"
    return name or (f"Customer no. {number}" if number else None)


def _error_result(
    code: str,
    message: str,
    meta: Meta,
    started: float,
    debug: Optional[dict[str, Any]] = None,
) -> ProcessingResult:
    meta.duration_ms = _elapsed_ms(started)
    if debug:
        meta.debug = debug
    return ProcessingResult(
        status="ERROR",
        match_result=None,
        confidence_score=0.0,
        needs_human_review=True,
        issues=[Issue(code=code, severity="error", message=message)],
        meta=meta,
        summary=Summary(),
    )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
