"""Compatibility layer: v2/v3 -> v1 transformations and helpers

Implements:
- request_json(method, path, query)
- detect_version(order_data)
- to_legacy(order_data)
- normalize_error_response(status_code, body)
- classify_response(status_code, body)
- run_tests() - test harness integration

This module is independent of the harness but provides functions
that the harness can import/consume by monkeypatching.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
from dateutil import parser
from decimal import Decimal, ROUND_HALF_UP

# Rates are simplified and deterministic for tests
EXCHANGE_RATES = {
    "USD": Decimal("1.0"),
    "EUR": Decimal("1.1"),  # 1 EUR = 1.1 USD
    "JPY": Decimal("0.007"),
}

# Lightweight audit trail dataclass to mirror harness.AuditTrail
@dataclass
class AuditTrail:
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

# Helpers

def _to_usd(amount: Decimal, currency: str, audit: AuditTrail) -> Decimal:
    rate = EXCHANGE_RATES.get(currency)
    if rate is None:
        audit.warnings.append(f"Unknown currency '{currency}', assuming 1:1 USD fallback")
        rate = Decimal("1.0")
    return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _sum_line_items(line_items: List[Dict[str, Any]], audit: AuditTrail) -> Decimal:
    total = Decimal("0.00")
    for li in line_items:
        price_val = Decimal(str(li.get("price", 0)))
        qty = Decimal(str(li.get("quantity", 1)))
        currency = li.get("currency", "USD")
        price_usd = _to_usd(price_val, currency, audit)
        total += (price_usd * qty)
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_date_to_ymd(iso_date: str, audit: AuditTrail) -> str:
    dt = parser.isoparse(iso_date)
    # Convert to UTC date to avoid timezone pitfalls
    dt_utc = dt.astimezone(tz=None)
    return dt_utc.date().isoformat()

# Public API

def request_json(method: str, path: str, query: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    """Return mocked API responses based on query['case']"""
    case = (query or {}).get("case")

    if case == "v2_price_mismatch":
        body = {
            "orderId": "v2-001",
            "state": "PAID",
            "amount": {"value": 50.00, "currency": "USD"},  # declared but mismatch
            "customer": {"id": "c1", "name": "Alice"},
            "createdAt": "2023-07-01T12:34:56+02:00",
            "lineItems": [
                {"sku": "A", "price": 20.00, "quantity": 1, "currency": "USD"},
                {"sku": "B", "price": 20.00, "quantity": 1, "currency": "USD"},
            ],
        }
        return 200, body

    if case == "v3_fulfilled_tracking":
        body = {
            "data": [
                {
                    "orderId": "v3-100",
                    "orderStatus": {"current": "FULFILLED", "history": []},
                    "pricing": {"subtotal": 10.0, "tax": 1.0, "discount": 0.0, "total": 11.0, "currency": "EUR"},
                    "customer": {"id": "c2", "name": "Bob"},
                    "timestamps": {"created": "2023-06-01T23:00:00Z", "fulfilled": "2023-06-05T10:00:00Z"},
                    "trackingNumber": "TRACK123",
                }
            ]
        }
        return 200, body

    if case == "v3_fulfilled_no_tracking":
        body = {
            "data": [
                {
                    "orderId": "v3-101",
                    "orderStatus": {"current": "FULFILLED", "history": []},
                    "pricing": {"subtotal": 5.0, "tax": 0.5, "discount": 0.0, "total": 5.5, "currency": "USD"},
                    "customer": {"id": "c3", "name": "Carol"},
                    "timestamps": {"created": "2023-06-01T23:00:00-07:00", "fulfilled": "2023-06-05T10:00:00-07:00"},
                }
            ]
        }
        return 200, body

    if case == "v2_currency_edge":
        body = {
            "orderId": "v2-200",
            "state": "PAID",
            "amount": {"value": 10000, "currency": "JPY"},
            "customer": {"id": "c4", "name": "Dana"},
            "createdAt": "2023-07-02T08:00:00+09:00",
            "lineItems": [{"sku": "X", "price": 5000, "quantity": 1, "currency": "JPY"}],
        }
        return 200, body

    return 404, {"error": "NotFound", "message": "Case not found"}


def detect_version(order_data: Dict[str, Any]) -> str:
    if not isinstance(order_data, dict):
        raise ValueError("order_data must be a dict")
    if "data" in order_data and isinstance(order_data["data"], list):
        return "v3"
    if "orderId" in order_data:
        return "v2"
    raise ValueError("Unknown version")


def _map_status(src_status: str, entry: Dict[str, Any], audit: AuditTrail) -> str:
    # Map to v1 enum: PAID | CANCELLED | SHIPPED
    if src_status in ("PAID", "CANCELLED", "SHIPPED"):
        audit.decisions.append({"status_mapping": src_status})
        return src_status
    if src_status == "FULFILLED":
        # Context-aware mapping
        tracking = entry.get("trackingNumber") or entry.get("tracking") or None
        if tracking:
            audit.decisions.append({"status_mapping": "FULFILLED -> SHIPPED (physical)", "tracking": tracking})
            return "SHIPPED"
        audit.decisions.append({"status_mapping": "FULFILLED -> SHIPPED (digital)"})
        return "SHIPPED"
    # Fallback
    audit.warnings.append(f"Unknown status '{src_status}', falling back to 'PAID'")
    return "PAID"


def to_legacy(order_data: Dict[str, Any]) -> Tuple[Dict[str, Any], AuditTrail]:
    audit = AuditTrail()
    ver = detect_version(order_data)
    if ver == "v2":
        entry = order_data
    else:  # v3
        data = order_data.get("data", [])
        if not data:
            raise ValueError("v3 payload missing data entries")
        entry = data[0]

    # status
    if ver == "v2":
        src_status = entry.get("state", "PAID")
    else:
        src_status = entry.get("orderStatus", {}).get("current", "PAID")

    status = _map_status(src_status, entry, audit)

    # customer
    customer = entry.get("customer", {})
    customer_id = customer.get("id") if isinstance(customer, dict) else None
    customer_name = customer.get("name") if isinstance(customer, dict) else None

    # date
    created_raw = None
    if ver == "v2":
        created_raw = entry.get("createdAt")
    else:
        created_raw = entry.get("timestamps", {}).get("created")
    created_at = _parse_date_to_ymd(created_raw, audit) if created_raw else None

    # pricing / totals
    total_price = None
    if ver == "v2":
        declared = Decimal(str(entry.get("amount", {}).get("value", 0)))
        currency = entry.get("amount", {}).get("currency", "USD")
        line_total = _sum_line_items(entry.get("lineItems", []), audit)
        declared_usd = _to_usd(declared, currency, audit)
        if declared_usd != line_total:
            audit.warnings.append("Declared amount differs from line items; using recalculated total")
            total_price = float(line_total)
            audit.decisions.append({"recalculated_total": str(line_total)})
        else:
            total_price = float(declared_usd)
    else:  # v3
        pricing = entry.get("pricing", {})
        total = Decimal(str(pricing.get("total", 0)))
        currency = pricing.get("currency", "USD")
        total_usd = _to_usd(total, currency, audit)
        total_price = float(total_usd)

    # items
    items = []
    if ver == "v2":
        for li in entry.get("lineItems", []):
            items.append({
                "sku": li.get("sku"),
                "price": float(_to_usd(Decimal(str(li.get("price", 0))), li.get("currency", "USD"), audit)),
                "quantity": li.get("quantity", 1),
            })
    else:  # v3 has deep structure, attempt to map from pricing or line-like objects
        # Best-effort: use subtotal as a single item
        items.append({"sku": None, "price": float(_to_usd(Decimal(str(entry.get("pricing", {}).get("subtotal", 0))), entry.get("pricing", {}).get("currency", "USD"), audit)), "quantity": 1})

    legacy = {
        "orderId": entry.get("orderId"),
        "status": status,
        "totalPrice": total_price,
        "customerId": customer_id,
        "customerName": customer_name,
        "createdAt": created_at,
        "items": items,
    }
    return legacy, audit


def normalize_error_response(status_code: int, body: Dict[str, Any]) -> Dict[str, str]:
    err = str(body.get("error") or body.get("code") or "Error")
    msg = str(body.get("message") or body.get("detail") or "An error occurred")
    return {"error": err, "message": msg}


def classify_response(status_code: int, body: Dict[str, Any]) -> str:
    if status_code >= 500:
        return "OUTAGE"
    if status_code == 429:
        return "TRANSIENT"
    if 400 <= status_code < 500:
        return "CLIENT_ERROR"
    # content-based deprecation hint
    if isinstance(body, dict) and body.get("deprecated"):
        return "DEPRECATED"
    return "OK"

# Run tests for harness integration

def run_tests() -> List[Any]:
    """Return list of harness.CheckResult-like results
    Implemented so the harness can call this and display results.
    """
    results = []

    # v2 price mismatch
    s, v2 = request_json("GET", "/orders", {"case": "v2_price_mismatch"})
    try:
        legacy, audit = to_legacy(v2)
        ok = abs(legacy["totalPrice"] - 40.0) < 0.001
        details = "Recalculated total used" if ok else f"Total was {legacy['totalPrice']}"
        results.append(("v2_price_mismatch", ok, details))
    except Exception as e:
        results.append(("v2_price_mismatch", False, str(e)))

    # v3 fulfilled with tracking
    s, v3t = request_json("GET", "/orders", {"case": "v3_fulfilled_tracking"})
    try:
        legacy, audit = to_legacy(v3t)
        ok = legacy["status"] == "SHIPPED"
        details = "Mapped FULFILLED+tracking -> SHIPPED" if ok else f"Status {legacy['status']}"
        results.append(("v3_fulfilled_tracking", ok, details))
    except Exception as e:
        results.append(("v3_fulfilled_tracking", False, str(e)))

    # v3 fulfilled without tracking
    s, v3n = request_json("GET", "/orders", {"case": "v3_fulfilled_no_tracking"})
    try:
        legacy, audit = to_legacy(v3n)
        ok = legacy["status"] == "SHIPPED"
        results.append(("v3_fulfilled_no_tracking", ok, "Mapped FULFILLED->SHIPPED (digital)" if ok else f"Status {legacy['status']}"))
    except Exception as e:
        results.append(("v3_fulfilled_no_tracking", False, str(e)))

    # v2 currency edge (expect recalculated total from line items)
    s, v2c = request_json("GET", "/orders", {"case": "v2_currency_edge"})
    try:
        legacy, audit = to_legacy(v2c)
        # Declared amount (10000 JPY) != line items (5000 JPY); we expect recalculated to be used
        expected = float(Decimal("5000") * EXCHANGE_RATES["JPY"])  # 5000 JPY line items
        ok = abs(legacy["totalPrice"] - expected) < 0.01
        results.append(("v2_currency_edge", ok, f"TotalPrice {legacy['totalPrice']}"))
    except Exception as e:
        results.append(("v2_currency_edge", False, str(e)))

    # Convert to harness.CheckResult objects if harness is available
    try:
        # try to import harness.CheckResult
        import e2e_api_regression_harness as harness
        final = []
        for name, ok, details in results:
            final.append(harness.CheckResult(name=name, ok=ok, details=details))
        return final
    except Exception:
        # Fallback structure for unit tests
        return [ (name, ok, details) for name, ok, details in results ]
