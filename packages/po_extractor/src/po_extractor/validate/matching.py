"""Customer and item matching against the master data (deterministic, no model calls)."""

from __future__ import annotations

from ..schemas import Customer, CustomerMatch, Issue, IssueCode, ItemMatch, LineItem
from .master_data import CustomerMaster, ItemMaster
from .normalize import is_active, normalize_id, normalize_name


def match_customer(customer: Customer, master: CustomerMaster) -> tuple[CustomerMatch, list[Issue]]:
    """Match on (customer_number, normalized legal_name) together.

    The number alone is never enough: customer no. 48326 exists twice in the master
    (ClearLine and Northstar) on purpose.
    """
    number = normalize_id(customer.customer_number)
    name = normalize_name(customer.legal_name)

    if not number or not name:
        missing = [label for label, value in (("customer number", number), ("legal name", name)) if not value]
        field = "customer.customer_number" if not number else "customer.legal_name"
        return CustomerMatch(matched=False), [
            Issue(
                code=IssueCode.CUSTOMER_FIELDS_MISSING,
                severity="error",
                message=f"Customer {' and '.join(missing)} not extracted - cannot match the customer",
                field=field,
            )
        ]

    rows = master.by_number(number)
    if not rows:
        # Hint only: a customer with the same name under a different number.
        same_name = master.by_name(customer.legal_name)
        message = f"Customer {number} not found in customer master"
        if same_name:
            others = ", ".join(f"{r.get('Legal name')} ({r.get('Customer no.')})" for r in same_name)
            message += f"; a customer with this name exists under another number: {others}"
        return CustomerMatch(matched=False, candidates=same_name), [
            Issue(
                code=IssueCode.CUSTOMER_NOT_FOUND,
                severity="error",
                message=message,
                field="customer.customer_number",
            )
        ]

    for row in rows:
        if normalize_name(row.get("Legal name")) == name:
            # TODO: decide whether an inactive customer ('Active' != Yes) should still match.
            return CustomerMatch(matched=True, master_record=row), []

    master_names = ", ".join(f"'{r.get('Legal name')}'" for r in rows)
    return CustomerMatch(matched=False, candidates=rows), [
        Issue(
            code=IssueCode.CUSTOMER_NAME_MISMATCH,
            severity="error",
            message=(
                f"Customer {number}: extracted name '{customer.legal_name}' does not match "
                f"the master name(s) for this number: {master_names}"
            ),
            field="customer.legal_name",
        )
    ]


def match_items(line_items: list[LineItem], master: ItemMaster) -> tuple[list[ItemMatch], list[Issue]]:
    """Look up each line's item_number in 'Source item no.' and require Active == Yes."""
    matches: list[ItemMatch] = []
    issues: list[Issue] = []
    for index, line in enumerate(line_items):
        number = normalize_id(line.item_number)
        field = f"line_items[{index}].item_number"
        label = f"line {index + 1}"

        if not number:
            matches.append(ItemMatch(line_index=index, item_number=None, reason=IssueCode.ITEM_NOT_FOUND))
            issues.append(
                Issue(
                    code=IssueCode.ITEM_NOT_FOUND,
                    severity="error",
                    message=f"No item number extracted for {label}",
                    field=field,
                )
            )
            continue

        rows = master.by_item_no(number)
        if not rows:
            matches.append(ItemMatch(line_index=index, item_number=number, reason=IssueCode.ITEM_NOT_FOUND))
            issues.append(
                Issue(
                    code=IssueCode.ITEM_NOT_FOUND,
                    severity="error",
                    message=f"Item {number} ({label}) not found in item master",
                    field=field,
                )
            )
            continue

        active = [row for row in rows if is_active(row.get("Active"))]
        if not active:
            matches.append(
                ItemMatch(
                    line_index=index,
                    item_number=number,
                    master_record=rows[0],
                    reason=IssueCode.ITEM_INACTIVE,
                )
            )
            issues.append(
                Issue(
                    code=IssueCode.ITEM_INACTIVE,
                    severity="error",
                    message=f"Item {number} ({label}) is inactive in item master",
                    field=field,
                )
            )
            continue

        # TODO(out of scope): compare unit_price with 'Net price EUR' and
        # normalize_unit(line.unit) with 'Base UoM'; emit warnings on mismatch.
        matches.append(ItemMatch(line_index=index, item_number=number, matched=True, master_record=active[0]))
    return matches, issues
