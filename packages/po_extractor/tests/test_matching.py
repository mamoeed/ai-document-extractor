import openpyxl
import pytest

from po_extractor.schemas import Customer, IssueCode, LineItem
from po_extractor.validate.master_data import load_customer_master, load_item_master
from po_extractor.validate.matching import match_customer, match_items

from .conftest import CUSTOMER_MASTER, ITEM_MASTER


@pytest.fixture(scope="module")
def customers():
    return load_customer_master(CUSTOMER_MASTER)


@pytest.fixture(scope="module")
def items():
    return load_item_master(ITEM_MASTER)


# ------------------------------------------------------------------ customers


def test_48326_clearline_matches(customers):
    match, issues = match_customer(Customer(customer_number="48326", legal_name="ClearLine Hygiene GmbH"), customers)
    assert match.matched and not issues
    assert match.master_record["Customer master ID"] == "CM-10001"


def test_48326_clearline_matches_despite_case_and_punctuation(customers):
    match, _ = match_customer(Customer(customer_number=48326.0, legal_name="clearline hygiene gmbh."), customers)
    assert match.matched
    assert match.master_record["Customer master ID"] == "CM-10001"


def test_48326_northstar_matches_a_different_row(customers):
    clearline, _ = match_customer(Customer(customer_number="48326", legal_name="ClearLine Hygiene GmbH"), customers)
    northstar, issues = match_customer(
        Customer(customer_number="48326", legal_name="Northstar Commercial Kitchens Ltd."), customers
    )
    assert northstar.matched and not issues
    assert northstar.master_record["Customer master ID"] == "CM-10010"
    assert northstar.master_record != clearline.master_record


def test_48326_other_name_is_name_mismatch(customers):
    match, issues = match_customer(Customer(customer_number="48326", legal_name="Some Other GmbH"), customers)
    assert not match.matched
    assert [i.code for i in issues] == [IssueCode.CUSTOMER_NAME_MISMATCH]
    assert "ClearLine Hygiene GmbH" in issues[0].message
    assert "Northstar Commercial Kitchens Ltd." in issues[0].message
    assert len(match.candidates) == 2


def test_58264_not_found(customers):
    match, issues = match_customer(
        Customer(customer_number="58264", legal_name="Northbridge Catering Systems Ltd."), customers
    )
    assert not match.matched
    assert [i.code for i in issues] == [IssueCode.CUSTOMER_NOT_FOUND]
    assert issues[0].field == "customer.customer_number"


def test_customer_not_found_hints_same_name_other_number(customers):
    match, issues = match_customer(Customer(customer_number="99999", legal_name="ClearLine Hygiene GmbH"), customers)
    assert issues[0].code == IssueCode.CUSTOMER_NOT_FOUND
    assert "48326" in issues[0].message
    assert match.candidates


@pytest.mark.parametrize(
    "customer",
    [Customer(customer_number="48326"), Customer(legal_name="ClearLine Hygiene GmbH"), Customer()],
)
def test_missing_customer_fields(customers, customer):
    match, issues = match_customer(customer, customers)
    assert not match.matched
    assert [i.code for i in issues] == [IssueCode.CUSTOMER_FIELDS_MISSING]


# ---------------------------------------------------------------------- items


@pytest.mark.parametrize("number", ["845271", "725904", "725918", "7842136"])
def test_known_items_found(items, number):
    matches, issues = match_items([LineItem(item_number=number)], items)
    assert matches[0].matched and not issues
    assert matches[0].master_record["Source item no."] == number


def test_628450_not_found(items):
    matches, issues = match_items([LineItem(item_number="7842136"), LineItem(item_number="628450")], items)
    assert [m.matched for m in matches] == [True, False]
    assert [i.code for i in issues] == [IssueCode.ITEM_NOT_FOUND]
    assert issues[0].message == "Item 628450 (line 2) not found in item master"
    assert issues[0].field == "line_items[1].item_number"
    assert matches[1].reason == IssueCode.ITEM_NOT_FOUND


def test_missing_item_number_is_not_found(items):
    matches, issues = match_items([LineItem(description="no number")], items)
    assert not matches[0].matched
    assert issues[0].code == IssueCode.ITEM_NOT_FOUND


def test_inactive_item(tmp_path):
    path = tmp_path / "items.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Item Master"
    sheet.append(["Fictional Item Master"])
    sheet.append(["Source item no.", "Description", "Base UoM", "Net price EUR", "Active"])
    sheet.append(["111", "Active thing", "pc", 1.0, "Yes"])
    sheet.append(["222", "Retired thing", "pc", 2.0, "No"])
    sheet.append(["333", "Case thing", "pc", 3.0, "yes"])
    workbook.save(path)
    master = load_item_master(path)

    matches, issues = match_items(
        [LineItem(item_number="111"), LineItem(item_number="222"), LineItem(item_number="333")], master
    )
    assert [m.matched for m in matches] == [True, False, True]
    assert [i.code for i in issues] == [IssueCode.ITEM_INACTIVE]
    assert matches[1].reason == IssueCode.ITEM_INACTIVE
    assert matches[1].master_record["Description"] == "Retired thing"
