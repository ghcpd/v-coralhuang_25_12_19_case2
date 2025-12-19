import pytest
from compat_layer import request_json, detect_version, to_legacy, normalize_error_response, classify_response


def test_v2_price_mismatch_recalculates_and_warns():
    status, body = request_json("GET", "/orders", {"case": "v2_price_mismatch"})
    assert status == 200
    assert detect_version(body) == "v2"
    legacy, audit = to_legacy(body)

    # declared 50 USD but line items sum to 40 USD -> use calculated 40
    assert legacy["totalPrice"] == 40.0
    assert any("Price mismatch" in w for w in audit.warnings)
    # legacy schema fields present
    assert set(["orderId", "status", "totalPrice", "customerId", "customerName", "createdAt", "items"]) <= set(legacy.keys())


def test_v3_fulfilled_physical_status_mapping_and_date():
    status, body = request_json("GET", "/orders", {"case": "v3_fulfilled_physical"})
    assert status == 200
    assert detect_version(body) == "v3"
    legacy, audit = to_legacy(body)

    assert legacy["status"] == "SHIPPED"
    assert any(d.get("context") == "physical" for d in audit.decisions if d.get("step") == "status_mapping")
    # date normalized to YYYY-MM-DD (UTC)
    assert legacy["createdAt"] == "2021-03-10"


def test_v3_fulfilled_digital_status_mapping():
    status, body = request_json("GET", "/orders", {"case": "v3_fulfilled_digital"})
    legacy, audit = to_legacy(body)
    assert legacy["status"] == "SHIPPED"
    assert any(d.get("context") == "digital" for d in audit.decisions if d.get("step") == "status_mapping")


def test_v2_currency_conversion_eur():
    status, body = request_json("GET", "/orders", {"case": "v2_currency_eur"})
    legacy, audit = to_legacy(body)
    # 100 EUR -> 110 USD
    assert legacy["totalPrice"] == 110.0


def test_v3_timezone_conversion():
    status, body = request_json("GET", "/orders", {"case": "v3_timezone"})
    legacy, audit = to_legacy(body)
    # created 2022-01-01T23:30:00-05:00 -> UTC 2022-01-02
    assert legacy["createdAt"] == "2022-01-02"


def test_error_normalization_and_classification():
    status, body = request_json("GET", "/orders", {"case": "v2_error"})
    assert status == 404
    ne = normalize_error_response(status, body)
    assert ne["error"] == "ORDER_NOT_FOUND"
    assert ne["message"] == "Order 404"
    assert classify_response(status, body) == "CLIENT_ERROR"


def test_detect_version_unknown():
    assert detect_version({}) == "unknown"
