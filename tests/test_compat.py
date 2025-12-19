import sys
import pytest
from decimal import Decimal

import compat.compat as compat


def test_detect_version_v2():
    s, body = compat.request_json("GET", "/", {"case": "v2_price_mismatch"})
    assert compat.detect_version(body) == "v2"


def test_detect_version_v3():
    s, body = compat.request_json("GET", "/", {"case": "v3_fulfilled_tracking"})
    assert compat.detect_version(body) == "v3"


def test_v2_price_mismatch_recalculation_and_warning():
    s, body = compat.request_json("GET", "/", {"case": "v2_price_mismatch"})
    legacy, audit = compat.to_legacy(body)
    assert legacy["totalPrice"] == pytest.approx(40.00, abs=1e-6)
    # Ensure a warning about recalculation exists
    assert any("recalculated" in d.get("recalculated_total", "") or "recalculated" in w for d in audit.decisions for w in audit.warnings) or any("Declared amount differs" in w for w in audit.warnings)


def test_v3_fulfilled_with_tracking_maps_to_shipped_and_physical():
    s, body = compat.request_json("GET", "/", {"case": "v3_fulfilled_tracking"})
    legacy, audit = compat.to_legacy(body)
    assert legacy["status"] == "SHIPPED"
    assert any("physical" in str(d).lower() for d in audit.decisions)


def test_v3_fulfilled_without_tracking_maps_to_shipped_digital():
    s, body = compat.request_json("GET", "/", {"case": "v3_fulfilled_no_tracking"})
    legacy, audit = compat.to_legacy(body)
    assert legacy["status"] == "SHIPPED"
    assert any("digital" in str(d).lower() for d in audit.decisions)


def test_currency_conversion_jpy_edge():
    s, body = compat.request_json("GET", "/", {"case": "v2_currency_edge"})
    legacy, audit = compat.to_legacy(body)
    # Declared amount (10000 JPY) != line items (5000 JPY); validation requires recalculation
    expected = float(Decimal("5000") * compat.EXCHANGE_RATES["JPY"])  # recalculated from lineItems
    assert legacy["totalPrice"] == pytest.approx(expected, rel=1e-3)


def test_date_normalization_timezone_safe():
    s, body = compat.request_json("GET", "/", {"case": "v2_price_mismatch"})
    legacy, audit = compat.to_legacy(body)
    assert legacy["createdAt"] == "2023-07-01"


def test_error_normalization_and_classification():
    err = compat.normalize_error_response(404, {"error": "NotFound", "message": "missing"})
    assert err["error"] == "NotFound"
    assert err["message"] == "missing"
    assert compat.classify_response(500, {}) == "OUTAGE"
    assert compat.classify_response(429, {}) == "TRANSIENT"
    assert compat.classify_response(400, {}) == "CLIENT_ERROR"


def test_harness_integration(monkeypatch):
    import e2e_api_regression_harness as harness
    # Patch harness functions with compat implementations
    monkeypatch.setattr(harness, "request_json", compat.request_json)
    monkeypatch.setattr(harness, "detect_version", compat.detect_version)
    monkeypatch.setattr(harness, "to_legacy", compat.to_legacy)
    monkeypatch.setattr(harness, "normalize_error_response", compat.normalize_error_response)
    monkeypatch.setattr(harness, "classify_response", compat.classify_response)
    monkeypatch.setattr(harness, "run_tests", compat.run_tests)

    # Run harness main and expect SystemExit with code 0 (all tests pass)
    with pytest.raises(SystemExit) as excinfo:
        harness.main()
    assert excinfo.value.code == 0
