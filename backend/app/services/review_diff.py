"""What did the human reviewer change compared with the AI extraction?"""

from __future__ import annotations

from typing import Any, Optional

# Not data corrections: editing these alone does not make an order "corrected by a human".
IGNORED_KEYS = frozenset({"field_confidence", "extraction_notes"})
MAX_CHANGES = 200


def diff_orders(before: Optional[dict[str, Any]], after: dict[str, Any]) -> list[dict[str, Any]]:
    """List of ``{path, before, after}`` for every changed leaf value, e.g.
    ``{"path": "customer.legal_name", "before": "Kitrnens Ltd.", "after": "Kitchens Ltd."}``."""
    changes: list[dict[str, Any]] = []
    _walk(before or {}, after, "", changes, top_level=True)
    return changes[:MAX_CHANGES]


def _walk(before: Any, after: Any, path: str, out: list[dict[str, Any]], top_level: bool = False) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            if top_level and key in IGNORED_KEYS:
                continue
            _walk(before.get(key), after.get(key), f"{path}.{key}" if path else key, out)
        return
    if isinstance(before, list) and isinstance(after, list):
        for index in range(max(len(before), len(after))):
            item_path = f"{path}[{index}]"
            if index >= len(before) or index >= len(after):
                # A whole line item added/removed: report it as one change.
                old = before[index] if index < len(before) else None
                new = after[index] if index < len(after) else None
                out.append({"path": item_path, "before": old, "after": new})
            else:
                _walk(before[index], after[index], item_path, out)
        return
    if isinstance(before, dict) and after is None:
        after = {}
    if isinstance(after, dict) and before is None:
        before = {}
    if isinstance(before, dict) and isinstance(after, dict):
        _walk(before, after, path, out)
        return
    if isinstance(before, list) and after is None:
        after = []
    if isinstance(after, list) and before is None:
        before = []
    if isinstance(before, list) and isinstance(after, list):
        _walk(before, after, path, out)
        return
    if _is_empty(before) and _is_empty(after):
        return
    if before != after:
        out.append({"path": path, "before": before, "after": after})


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
