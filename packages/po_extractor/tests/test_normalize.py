from datetime import date

import pytest

from po_extractor.schemas import ExtractedOrder
from po_extractor.validate.normalize import (
    UNIT_MAP,
    is_active,
    normalize_id,
    normalize_name,
    normalize_unit,
    parse_date,
    parse_number,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.118,00", 1118.0),
        ("5,00", 5.0),
        ("2.507,00", 2507.0),
        ("223,60", 223.6),
        ("1.234.567", 1234567.0),
        ("1,118.00", 1118.0),
        ("1118.00", 1118.0),
        ("19 %", 19.0),
        ("€ 1.118,00", 1118.0),
        ("40,0", 40.0),
        (40, 40.0),
        (56.25, 56.25),
        (None, None),
        ("", None),
    ],
)
def test_parse_number_german_and_english(raw, expected):
    assert parse_number(raw) == expected


def test_parse_number_rejects_text():
    with pytest.raises(ValueError):
        parse_number("abc")


@pytest.mark.parametrize(
    "raw, expected",
    [
        (58264.0, "58264"),
        ("58264.0", "58264"),
        (58264, "58264"),
        (" 7842136 ", "7842136"),
        ("NTH-481732", "NTH-481732"),
        ("01067", "01067"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_id(raw, expected):
    assert normalize_id(raw) == expected


def test_normalize_name_casefold_whitespace_nfkc():
    assert normalize_name("ClearLine Hygiene GmbH") == normalize_name("Clearline   Hygiene GmbH ")
    assert normalize_name("ＣｌｅａｒＬｉｎｅ Hygiene GmbH") == "clearline hygiene gmbh"  # full-width -> NFKC
    assert normalize_name("Straße") == normalize_name("STRASSE")


def test_normalize_name_ignores_punctuation():
    assert normalize_name("Northbridge Catering Systems Ltd.") == normalize_name("Northbridge Catering Systems Ltd")
    assert normalize_name("Muster GmbH & Co. KG") == normalize_name("Muster GmbH & Co KG")
    assert normalize_name("Clearline Hygiene GmbH") != normalize_name("Northstar Commercial Kitchens Ltd.")
    assert normalize_name(None) is None
    assert normalize_name("  ") is None


@pytest.mark.parametrize(
    "raw, expected",
    [("Stk", "pc"), ("Stück", "pc"), ("pcs", "pc"), ("pc", "pc"), ("PCS.", "pc"),
     ("canisters", "canister"), ("sets", "set"), ("Box", "box"), (None, None)],
)
def test_normalize_unit(raw, expected):
    assert normalize_unit(raw) == expected


def test_unit_map_is_extendable(monkeypatch):
    monkeypatch.setitem(UNIT_MAP, "karton", "box")
    assert normalize_unit("Karton") == "box"


def test_parse_date():
    assert parse_date("18.08.2026") == date(2026, 8, 18)
    assert parse_date("2026-08-18") == date(2026, 8, 18)
    assert parse_date("2026-08-18T10:00:00") == date(2026, 8, 18)
    assert parse_date(None) is None
    with pytest.raises(ValueError):
        parse_date("34 / 2026")


def test_is_active():
    assert is_active("Yes") and is_active("yes") and is_active(" YES ")
    assert not is_active("No") and not is_active(None) and not is_active("")


def test_extracted_order_coercion():
    order = ExtractedOrder.model_validate(
        {
            "document": {"order_number": 2607421.0, "order_date": "18.08.2026", "currency": "eur"},
            "customer": {"customer_number": 58264.0, "legal_name": "  ACME GmbH ", "postcode": 86156},
            "delivery_address": None,
            "line_items": [{"item_number": 7842136, "quantity": "5,00", "unit_price": "1.118,00"}, None],
            "totals": None,
            "field_confidence": {"order_number": 95, "line_items": "0.9"},
            "unknown_key": "ignored",
        }
    )
    assert order.document.order_number == "2607421"
    assert order.document.order_date == date(2026, 8, 18)
    assert order.document.currency == "EUR"
    assert order.customer.customer_number == "58264"
    assert order.customer.legal_name == "ACME GmbH"
    assert order.customer.postcode == "86156"
    assert len(order.line_items) == 1
    assert order.line_items[0].item_number == "7842136"
    assert order.line_items[0].quantity == 5.0
    assert order.line_items[0].unit_price == 1118.0
    assert order.field_confidence.order_number == 0.95
    assert order.field_confidence.line_items == 0.9
    assert order.model_dump(mode="json")["document"]["order_date"] == "2026-08-18"


def test_extracted_order_rejects_bad_confidence():
    with pytest.raises(ValueError):
        ExtractedOrder.model_validate({"field_confidence": {"order_number": 150}})
