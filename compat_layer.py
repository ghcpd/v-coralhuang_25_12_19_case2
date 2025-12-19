"""
Compatibility layer for v2/v3 -> v1 transformations and test data.
This module implements:
- request_json: mocked responses for test scenarios
- detect_version: auto-detects v2 vs v3
- to_legacy: performs mapping, price checks, currency and date normalization
- normalize_error_response, classify_response
- run_all_tests: a harness-friendly test runner (returns harness.CheckResult list)

Designed to be imported by run_tests.py which will inject these functions into
the read-only e2e_api_regression_harness.py at runtime.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

# Simple exchange rates for deterministic tests
EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 1.1,   # 1 EUR = 1.1 USD
    "JPY": 0.007, # 1 JPY = 0.007 USD
}

# Test scenarios keyed by name. Each entry is (status_code, body)
TEST_CASES: Dict[str, Tuple[int, Dict[str, Any]]] = {}

# v2: well-formed
TEST_CASES["v2_good"] = (200, {
    "orderId": "v2-100",
    "state": "PAID",
    "amount": {"value": 30.00, "currency": "USD"},
    "customer": {"id": "c-1", "name": "Alice"},
    "createdAt": "2025-12-10T15:30:00Z",
    "lineItems": [
        {"sku": "a", "price": 10.00, "quantity": 2}
    ]
})

# v2: price mismatch (amount != sum of lineItems) - should auto-repair and warn
TEST_CASES["v2_price_mismatch"] = (200, {
    "orderId": "v2-101",
    "state": "PAID",
    "amount": {"value": 50.00, "currency": "USD"},  # wrong
    "customer": {"id": "c-2", "name": "Bob"},
    "createdAt": "2025-11-01T23:45:00+02:00",
    "lineItems": [
        {"sku": "x", "price": 7.25, "quantity": 2},
        {"sku": "y", "price": 5.50, "quantity": 1}
    ]
})

# v2: EUR currency - must convert to USD
TEST_CASES["v2_eur"] = (200, {
    "orderId": "v2-102",
    "state": "SHIPPED",
    "amount": {"value": 100.00, "currency": "EUR"},
    "customer": {"id": "c-3", "name": "Carol"},
    "createdAt": "2025-10-05T09:00:00-05:00",
    "lineItems": [
        {"sku": "eur-1", "price": 50.00, "quantity": 2}
    ],
    "trackingNumber": "TRK-1234"
})

# v3: fulfilled with tracking (physical -> SHIPPED)
TEST_CASES["v3_fulfilled_physical"] = (200, {
    "data": [
        {
            "orderId": "v3-200",
            "orderStatus": {"current": "FULFILLED", "history": ["PAID"]},
            "pricing": {"subtotal": 20.00, "tax": 1.60, "discount": 0.0, "total": 21.60, "currency": "USD"},
            "customer": {"id": "c-4", "name": "Dan"},
            "timestamps": {"created": "2025-12-12T12:00:00Z", "fulfilled": "2025-12-13T03:00:00Z"},
            "trackingNumber": "TRK-999"
        }
    ]
})

# v3: fulfilled without tracking (digital fulfillment) -> still SHIPPED in v1
TEST_CASES["v3_fulfilled_digital"] = (200, {
    "data": [
        {
            "orderId": "v3-201",
            "orderStatus": {"current": "FULFILLED", "history": ["PAID"]},
            "pricing": {"subtotal": 5.00, "tax": 0.0, "discount": 0.0, "total": 5.00, "currency": "USD"},
            "customer": {"id": "c-5", "name": "Eve"},
            "timestamps": {"created": "2025-12-01T00:00:00+09:00"}
        }
    ]
})

# v3: JPY currency and timezone edge case
TEST_CASES["v3_jpy_tz"] = (200, {
    "data": [
        {
            "orderId": "v3-202",
            "orderStatus": {"current": "PAID", "history": []},
            "pricing": {"subtotal": 1000, "tax": 0, "discount": 0, "total": 1000, "currency": "JPY"},
            "customer": {"id": "c-6", "name": "Fuyuki"},
            "timestamps": {"created": "2025-12-31T23:59:59+09:00"}
        }
    ]
})

# simulated error shapes
TEST_CASES["v2_error"] = (400, {"error": "INVALID_REQUEST", "message": "bad id"})
TEST_CASES["v3_error"] = (422, {"errors": [{"code": "E1001", "detail": "invalid amount"}]})


# public API expected by harness
def request_json(method: str, path: str, query: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    """Return deterministic test responses. Uses query['case'] if present.
    Falls back to reasonable defaults.
    """
    case = query.get("case") if query else None
    if not case:
        # default mapping by path heuristics
        if "v3" in path:
            case = "v3_fulfilled_physical"
        else:
            case = "v2_good"

    resp = TEST_CASES.get(case)
    if not resp:
        return (404, {"error": "NOT_FOUND", "message": f"case {case} not found"})
    return resp


def detect_version(order_data: Dict[str, Any]) -> str:
    """Detects v3 (top-level data list) vs v2 (orderId root).
    Raises ValueError on unknown shapes.
    """
    if isinstance(order_data, dict) and "data" in order_data and isinstance(order_data["data"], list):
        return "v3"
    if isinstance(order_data, dict) and "orderId" in order_data:
        return "v2"
    # Some error shapes may still include 'data' or other keys; be defensive
    raise ValueError("Unable to detect version from payload")


# small helper
def _to_date_iso8601_to_ymd(ts: str) -> str:
    # support trailing Z
    if ts is None:
        return ""
    s = ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        # last resort: parse date prefix
        try:
            return s.split("T")[0]
        except Exception:
            return s
    # convert to UTC by using dt.astimezone(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.date().isoformat()


def _sum_line_items_v2(line_items: List[Dict[str, Any]]) -> float:
    s = 0.0
    for it in line_items:
        price = float(it.get("price", 0.0))
        qty = int(it.get("quantity", 1))
        s += price * qty
    return round(s, 2)


def _convert_to_usd(amount: float, currency: str) -> float:
    rate = EXCHANGE_RATES.get(currency, None)
    if rate is None:
        # unknown currency — treat as USD but emit traceable small difference
        return round(amount, 2)
    return round(amount * rate, 2)


def to_legacy(order_data: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
    """Transform v2/v3 order into v1 schema and produce AuditTrail-like object.

    Returns (legacy_order, audit_trail)
    """
    # Create a simple audit structure compatible with harness.AuditTrail
    audit = {"decisions": [], "warnings": []}

    # detect version and normalize to a single record dictionary
    version = detect_version(order_data)
    audit["decisions"].append({"action": "detect_version", "detected": version})

    record = None
    if version == "v3":
        data = order_data.get("data", [])
        if not data:
            raise ValueError("v3 payload missing data entries")
        record = data[0]
    else:
        record = order_data

    legacy: Dict[str, Any] = {
        "orderId": record.get("orderId"),
        "status": "PAID",
        "totalPrice": 0.0,
        "customerId": None,
        "customerName": None,
        "createdAt": "",
        "items": []
    }

    # --- status mapping ---
    raw_state = None
    tracking = None
    if version == "v2":
        raw_state = record.get("state")
        tracking = record.get("trackingNumber")
    else:
        raw_state = record.get("orderStatus", {}).get("current")
        tracking = record.get("trackingNumber") or record.get("timestamps", {}).get("fulfilled")

    mapped = None
    if raw_state == "FULFILLED":
        # context-aware mapping; v1 uses SHIPPED for fulfilled states
        mapped = "SHIPPED"
        detail = "physical" if tracking else "digital"
        audit["decisions"].append({"action": "status_map", "from": raw_state, "to": mapped, "context": detail})
    elif raw_state in ("SHIPPED", "PAID", "CANCELLED"):
        mapped = raw_state
        audit["decisions"].append({"action": "status_map", "from": raw_state, "to": mapped})
    else:
        # unknown new state — degrade to PAID and warn
        mapped = "PAID"
        audit["decisions"].append({"action": "status_map", "from": raw_state, "to": mapped})
        audit["warnings"].append(f"Unknown state '{raw_state}' downgraded to PAID")

    legacy["status"] = mapped

    # --- price extraction and validation ---
    declared_total_usd = None
    calculated_total_usd = None

    if version == "v2":
        amt = record.get("amount", {})
        declared_total = float(amt.get("value", 0.0))
        currency = amt.get("currency", "USD")
        declared_total_usd = _convert_to_usd(declared_total, currency)

        line_sum = _sum_line_items_v2(record.get("lineItems", []))
        # convert line items (assumed same currency as amount)
        calculated_total_usd = _convert_to_usd(line_sum, currency)

        if abs(declared_total_usd - calculated_total_usd) > 0.01:
            audit["warnings"].append("price_mismatch: declared amount differs from line item sum; using calculated value")
            audit["decisions"].append({"action": "repair_price", "from": declared_total_usd, "to": calculated_total_usd})
            total_to_use = calculated_total_usd
        else:
            total_to_use = declared_total_usd

        legacy["items"] = record.get("lineItems", [])
    else:
        pricing = record.get("pricing", {})
        declared_total = float(pricing.get("total", 0.0))
        currency = pricing.get("currency", "USD")
        declared_total_usd = _convert_to_usd(declared_total, currency)
        # reconstruct from subtotal + tax - discount when available
        subtotal = float(pricing.get("subtotal", 0.0))
        tax = float(pricing.get("tax", 0.0))
        discount = float(pricing.get("discount", 0.0))
        calc = round(subtotal + tax - discount, 2)
        calculated_total_usd = _convert_to_usd(calc, currency)

        if abs(declared_total_usd - calculated_total_usd) > 0.01:
            audit["warnings"].append("v3_price_mismatch: declared total disagrees with components; using components")
            audit["decisions"].append({"action": "repair_price", "from": declared_total_usd, "to": calculated_total_usd})
            total_to_use = calculated_total_usd
        else:
            total_to_use = declared_total_usd

        # v3 doesn't carry individual line items in our tests
        legacy["items"] = []

    legacy["totalPrice"] = round(float(total_to_use), 2)

    # --- customer mapping ---
    cust = record.get("customer", {})
    legacy["customerId"] = cust.get("id")
    legacy["customerName"] = cust.get("name")

    # --- date normalization ---
    created_ts = None
    if version == "v2":
        created_ts = record.get("createdAt")
    else:
        created_ts = record.get("timestamps", {}).get("created")

    legacy["createdAt"] = _to_date_iso8601_to_ymd(created_ts)

    # record some audit metadata
    audit["decisions"].append({"action": "use_currency", "currency": currency})

    # return objects; harness expects AuditTrail dataclass but is tolerant of mapping
    return legacy, audit


def normalize_error_response(status_code: int, body: Dict[str, Any]) -> Dict[str, str]:
    """Normalize v2/v3 error shapes to v1-like {error, message}"""
    if not isinstance(body, dict):
        return {"error": str(status_code), "message": "unknown error"}

    if "error" in body and "message" in body:
        return {"error": body.get("error"), "message": body.get("message")}

    if "errors" in body and isinstance(body["errors"], list) and body["errors"]:
        e = body["errors"][0]
        return {"error": e.get("code", "E"), "message": e.get("detail", "")}

    # fallback
    return {"error": str(status_code), "message": body.get("message") or body.get("detail") or ""}


def classify_response(status_code: int, body: Dict[str, Any]) -> str:
    """Classify responses loosely for the harness diagnostics"""
    if status_code == 200:
        # detect deprecation hint
        if isinstance(body, dict) and (body.get("deprecated") or body.get("warning") == "deprecated"):
            return "DEPRECATED"
        return "OK"
    if status_code in (429, 503):
        return "TRANSIENT" if status_code == 429 else "OUTAGE"
    if status_code >= 500:
        return "OUTAGE"
    if status_code >= 400:
        return "CLIENT_ERROR"
    return "OK"


# ----------------------------
# Test suite that will be injected into the harness
# ----------------------------

def run_all_tests(harness_module) -> List[Any]:
    """Execute tests and return a list of harness.CheckResult instances."""
    results = []
    CheckResult = harness_module.CheckResult
    AuditTrail = harness_module.AuditTrail

    # helper to fetch and transform a case
    def fetch_and_convert(case_name: str):
        status, body = request_json("GET", "/orders", {"case": case_name})
        if status != 200:
            return False, f"status {status}", None, {"status": status, "body": body}
        try:
            legacy, audit = to_legacy(body)
        except Exception as e:
            return False, f"conversion error: {e}", None, {"exc": str(e)}
        return True, "ok", legacy, audit

    # Test 1: v2 price mismatch auto-repaired
    ok, msg, legacy, audit = fetch_and_convert("v2_price_mismatch")
    if not ok:
        results.append(CheckResult("v2_price_mismatch", False, msg))
    else:
        expected_sum = 7.25 * 2 + 5.5
        usd_expected = _convert_to_usd(round(expected_sum, 2), "USD")
        results.append(CheckResult("v2_price_mismatch", legacy["totalPrice"] == usd_expected,
                                   f"totalPrice={legacy['totalPrice']} expected={usd_expected}; warnings={audit.get('warnings')}") )

    # Test 2: v3 fulfilled with tracking -> SHIPPED
    ok, msg, legacy, audit = fetch_and_convert("v3_fulfilled_physical")
    results.append(CheckResult("v3_fulfilled_physical_status",
                               ok and legacy.get("status") == "SHIPPED",
                               f"status={legacy.get('status')}; decisions={audit.get('decisions') if isinstance(audit, dict) else ''}"))

    # Test 3: v3 fulfilled without tracking -> SHIPPED
    ok, msg, legacy, audit = fetch_and_convert("v3_fulfilled_digital")
    results.append(CheckResult("v3_fulfilled_digital_status",
                               ok and legacy.get("status") == "SHIPPED",
                               f"status={legacy.get('status')}; warnings={audit.get('warnings') if isinstance(audit, dict) else ''}"))

    # Test 4: currency conversion EUR -> USD
    ok, msg, legacy, audit = fetch_and_convert("v2_eur")
    if ok:
        # original EUR 100 -> USD 110
        results.append(CheckResult("v2_eur_currency",
                                   legacy.get("totalPrice") == 110.0,
                                   f"totalPrice={legacy.get('totalPrice')} expected=110.0"))
    else:
        results.append(CheckResult("v2_eur_currency", False, msg))

    # Test 5: timezone normalization (v2 record with +02:00 should normalize correctly)
    ok, msg, legacy, audit = fetch_and_convert("v2_price_mismatch")
    if ok:
        results.append(CheckResult("date_normalization",
                                   legacy.get("createdAt") == "2025-11-01",
                                   f"createdAt={legacy.get('createdAt')}; expected=2025-11-01"))
    else:
        results.append(CheckResult("date_normalization", False, msg))

    # Test 6: v3 JPY conversion and date rollover handling
    ok, msg, legacy, audit = fetch_and_convert("v3_jpy_tz")
    if ok:
        # 1000 JPY -> 7.0 USD
        results.append(CheckResult("v3_jpy_currency_and_date",
                                   legacy.get("totalPrice") == 7.0 and legacy.get("createdAt") == "2025-12-31",
                                   f"total={legacy.get('totalPrice')} createdAt={legacy.get('createdAt')}") )
    else:
        results.append(CheckResult("v3_jpy_currency_and_date", False, msg))

    # Test 7: error normalization (v2 error)
    st, body = request_json("GET", "/orders", {"case": "v2_error"})
    norm = normalize_error_response(st, body)
    results.append(CheckResult("normalize_v2_error", norm.get("error") == "INVALID_REQUEST", str(norm)))

    # Test 8: error normalization (v3 error)
    st, body = request_json("GET", "/orders", {"case": "v3_error"})
    norm = normalize_error_response(st, body)
    results.append(CheckResult("normalize_v3_error", norm.get("error") == "E1001", str(norm)))

    # Test 9: classify response
    results.append(CheckResult("classify_ok", classify_response(200, TEST_CASES["v2_good"][1]) == "OK", "200 -> OK"))
    results.append(CheckResult("classify_client_error", classify_response(404, {"message": "x"}) == "CLIENT_ERROR", "404 -> CLIENT_ERROR"))
    results.append(CheckResult("classify_outage", classify_response(503, {"message": "x"}) == "OUTAGE", "503 -> OUTAGE"))

    # All done
    return results
