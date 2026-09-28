from app.services.review_diff import diff_orders


def test_no_changes():
    order = {"customer": {"legal_name": "A"}, "line_items": [{"item_number": "1"}]}
    assert diff_orders(order, order) == []


def test_changed_leaf_values():
    before = {"customer": {"legal_name": "Kitrnens Ltd.", "city": None}, "line_items": [{"quantity": 5.0}]}
    after = {"customer": {"legal_name": "Kitchens Ltd.", "city": "Köln"}, "line_items": [{"quantity": 6.0}]}
    assert diff_orders(before, after) == [
        {"path": "customer.city", "before": None, "after": "Köln"},
        {"path": "customer.legal_name", "before": "Kitrnens Ltd.", "after": "Kitchens Ltd."},
        {"path": "line_items[0].quantity", "before": 5.0, "after": 6.0},
    ]


def test_added_and_removed_lines():
    before = {"line_items": [{"item_number": "1"}, {"item_number": "2"}]}
    after = {"line_items": [{"item_number": "1"}]}
    assert diff_orders(before, after) == [{"path": "line_items[1]", "before": {"item_number": "2"}, "after": None}]
    assert diff_orders(after, before) == [{"path": "line_items[1]", "before": None, "after": {"item_number": "2"}}]


def test_confidence_and_notes_are_not_corrections():
    before = {"field_confidence": {"legal_name": 0.5}, "extraction_notes": "unclear"}
    after = {"field_confidence": {"legal_name": 1.0}, "extraction_notes": None}
    assert diff_orders(before, after) == []


def test_empty_string_equals_null():
    assert diff_orders({"customer": {"email": None}}, {"customer": {"email": ""}}) == []


def test_no_baseline():
    assert diff_orders(None, {"document": {"order_number": "X"}}) == [
        {"path": "document.order_number", "before": None, "after": "X"}
    ]
