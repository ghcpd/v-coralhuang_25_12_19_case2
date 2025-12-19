"""Compatibility layer: transforms v2/v3 API responses into v1-compatible format.

Exports:
- request_json(method, path, query) -> (status_code, body)
- detect_version(order_data) -> 'v1'|'v2'|'v3'|'unknown'
- to_legacy(order_data) -> (legacy_order: dict, audit: AuditTrail)
- normalize_error_response(status_code, body) -> dict
- classify_response(status_code, body) -> str

Implementation uses deterministic currency rates and fixed parsing to keep tests repeatable.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
import math
import copy

from dateutil import parser as date_parser

# Deterministic currency rates to USD for tests
CURRENCY_RATES = {
    "USD": 1.0,
    "EUR": 1.1,   # 1 EUR = 1.1 USD
    "JPY": 0.0075,
    "GBP": 1.25,
}

@dataclass
class AuditTrail:
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ------------------ Test data provider ---------------------------------

def request_json(method: str, path: str, query: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    """Return deterministic mocked responses keyed by query['case'].

    Examples of case keys:
      - v2_price_mismatch
      - v3_fulfilled_physical
      - v3_fulfilled_digital
      - v2_currency_eur
      - v3_timezone
      - v2_error

    Returns (status_code, body)
    """
    case = query.get("case", "default")

    if case == "v2_price_mismatch":
        body = {
            "orderId": "v2-1001",
            "state": "PAID",
            "amount": {"value": 50.00, "currency": "USD"},  # declared
            "customer": {"id": "c1", "name": "Alice"},
            "createdAt": "2020-06-01T12:34:56Z",
            "lineItems": [
                {"sku": "A", "price": 20.0, "quantity": 1, "currency": "USD"},
                {"sku": "B", "price": 20.0, "quantity": 1, "currency": "USD"},
            ],
        }
        return 200, body

    if case == "v3_fulfilled_physical":
        return 200, {
            "data": [
                {
                    "orderId": "v3-2001",
                    "orderStatus": {"current": "FULFILLED", "history": []},
                    "pricing": {"subtotal": 100.0, "tax": 10.0, "discount": 0, "total": 110.0, "currency": "USD"},
                    "customer": {"id": "c2", "name": "Bob"},
                    "timestamps": {"created": "2021-03-10T09:00:00+02:00", "fulfilled": "2021-03-11T15:00:00+02:00"},
                    "trackingNumber": "TRACK-123",
                    "lineItems": [
                        {"sku": "A", "price": 50.0, "quantity": 2, "currency": "USD"},
                    ],
                }
            ]
        }

    if case == "v3_fulfilled_digital":
        return 200, {
            "data": [
                {
                    "orderId": "v3-2002",
                    "orderStatus": {"current": "FULFILLED", "history": []},
                    "pricing": {"subtotal": 0.0, "tax": 0.0, "discount": 0.0, "total": 9.99, "currency": "USD"},
                    "customer": {"id": "c3", "name": "Carol"},
                    "timestamps": {"created": "2021-05-01T10:00:00Z"},
                    "lineItems": [
                        {"sku": "DL1", "price": 9.99, "quantity": 1, "currency": "USD"},
                    ],
                }
            ]
        }

    if case == "v2_currency_eur":
        return 200, {
            "orderId": "v2-3001",
            "state": "PAID",
            "amount": {"value": 100.0, "currency": "EUR"},
            "customer": {"id": "c4", "name": "Dan"},
            "createdAt": "2021-12-01T23:00:00+01:00",
            "lineItems": [
                {"sku": "A", "price": 50.0, "quantity": 2, "currency": "EUR"},
            ],
        }

    if case == "v3_timezone":
        return 200, {
            "data": [
                {
                    "orderId": "v3-4001",
                    "orderStatus": {"current": "PAID", "history": []},
                    "pricing": {"subtotal": 20.0, "tax": 0.0, "discount": 0.0, "total": 20.0, "currency": "USD"},
                    "customer": {"id": "c5", "name": "Eve"},
                    "timestamps": {"created": "2022-01-01T23:30:00-05:00"},
                    "lineItems": [
                        {"sku": "A", "price": 20.0, "quantity": 1, "currency": "USD"},
                    ],
                }
            ]
        }

    if case == "v2_error":
        return 404, {"error_code": "ORDER_NOT_FOUND", "detail": "Order 404"}

    # default fallback: a simple v2 ok order
    return 200, {
        "orderId": "v2-default",
        "state": "PAID",
        "amount": {"value": 10.0, "currency": "USD"},
        "customer": {"id": "c0", "name": "Default"},
        "createdAt": "2020-01-01T00:00:00Z",
        "lineItems": [],
    }


# ------------------ Version detection ----------------------------------

def detect_version(order_data: Dict[str, Any]) -> str:
    if not isinstance(order_data, dict):
        return "unknown"
    if "data" in order_data and isinstance(order_data["data"], list):
        return "v3"
    if "orderId" in order_data and not ("data" in order_data):
        return "v2"
    # maybe already v1
    if all(k in order_data for k in ("orderId", "status", "totalPrice")):
        return "v1"
    return "unknown"


# ------------------ Helpers ---------------------------------------------

def _to_usd(amount: float, currency: str) -> float:
    rate = CURRENCY_RATES.get(currency, None)
    if rate is None:
        # unknown currency: treat as USD but warn by caller
        return amount
    return amount * rate


def _sum_line_items(line_items: List[Dict[str, Any]]) -> float:
    total = 0.0
    for it in line_items:
        price = float(it.get("price", 0.0))
        qty = int(it.get("quantity", 1))
        currency = it.get("currency", "USD")
        total += _to_usd(price, currency) * qty
    return total


def _iso_to_yyyy_mm_dd(iso_ts: str) -> str:
    # parse with dateutil for robust timezone handling
    dt = date_parser.isoparse(iso_ts)
    # convert to UTC then format date portion
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%d")


# ------------------ Core transformation ---------------------------------

def to_legacy(order_data: Dict[str, Any]) -> Tuple[Dict[str, Any], AuditTrail]:
    audit = AuditTrail()
    version = detect_version(order_data)
    audit.decisions.append({"step": "detect_version", "version": version})

    if version == "v2":
        src = order_data
    elif version == "v3":
        # v3 has data array; take the first item for single-order transform
        if not order_data.get("data"):
            raise ValueError("v3 payload missing data")
        src = order_data["data"][0]
    elif version == "v1":
        # already legacy — return a copy and an empty audit with a decision
        audit.decisions.append({"step": "noop", "reason": "already_v1"})
        return copy.deepcopy(order_data), audit
    else:
        raise ValueError("Unknown source version")

    legacy = {}

    # orderId
    legacy["orderId"] = src.get("orderId")

    # customer
    customer = src.get("customer", {})
    legacy["customerId"] = customer.get("id") if isinstance(customer, dict) else src.get("customerId")
    legacy["customerName"] = customer.get("name") if isinstance(customer, dict) else src.get("customerName")

    # status mapping
    status = None
    if version == "v2":
        state = src.get("state")
        # map directly; FULFILLED -> SHIPPED per spec; include context note
        if state == "FULFILLED":
            status = "SHIPPED"
            has_tracking = bool(src.get("trackingNumber") or src.get("tracking") )
            audit.decisions.append({"step": "status_mapping", "from": state, "to": status, "context": "physical" if has_tracking else "digital"})
        elif state in ("PAID", "CANCELLED", "SHIPPED"):
            status = state
            audit.decisions.append({"step": "status_mapping", "from": state, "to": state})
        else:
            status = "PAID"
            audit.warnings.append(f"Unrecognized state '{state}', defaulted to PAID")
    elif version == "v3":
        os = src.get("orderStatus", {})
        curr = os.get("current") if isinstance(os, dict) else None
        if curr == "FULFILLED":
            status = "SHIPPED"
            has_tracking = bool(src.get("trackingNumber"))
            audit.decisions.append({"step": "status_mapping", "from": curr, "to": status, "context": "physical" if has_tracking else "digital"})
        elif curr in ("PAID", "CANCELLED", "SHIPPED"):
            status = curr
            audit.decisions.append({"step": "status_mapping", "from": curr, "to": curr})
        else:
            status = "PAID"
            audit.warnings.append(f"Unrecognized orderStatus.current '{curr}', defaulted to PAID")

    legacy["status"] = status

    # line items and total price
    line_items = src.get("lineItems") or []

    # currency and declared total
    declared_total = None
    declared_currency = "USD"
    if version == "v2":
        amount = src.get("amount", {})
        declared_total = amount.get("value")
        declared_currency = amount.get("currency", "USD")
    elif version == "v3":
        pricing = src.get("pricing", {})
        declared_total = pricing.get("total")
        declared_currency = pricing.get("currency", "USD")

    # calculate sum of line items in USD
    calculated_total_usd = round(_sum_line_items(line_items), 2)

    if declared_total is None:
        # if no declared total, use calculated
        final_total_usd = calculated_total_usd
        audit.decisions.append({"step": "price", "action": "use_calculated", "calculated_usd": final_total_usd})
    else:
        declared_usd = round(_to_usd(float(declared_total), declared_currency), 2)
        if not math.isclose(declared_usd, calculated_total_usd, rel_tol=1e-9, abs_tol=0.01):
            # mismatch: prefer calculated and emit warning
            audit.warnings.append(f"Price mismatch: declared {declared_total} {declared_currency} ({declared_usd} USD) != calculated {calculated_total_usd} USD; using calculated")
            final_total_usd = calculated_total_usd
            audit.decisions.append({"step": "price", "action": "recalc", "declared_usd": declared_usd, "calculated_usd": calculated_total_usd})
        else:
            final_total_usd = declared_usd
            audit.decisions.append({"step": "price", "action": "use_declared", "declared_usd": declared_usd})

    legacy["totalPrice"] = float(round(final_total_usd, 2))

    # createdAt normalization
    created_raw = src.get("createdAt") or (src.get("timestamps", {}) or {}).get("created")
    if created_raw:
        try:
            legacy["createdAt"] = _iso_to_yyyy_mm_dd(created_raw)
            audit.decisions.append({"step": "date_normalize", "from": created_raw, "to": legacy["createdAt"]})
        except Exception as e:
            audit.warnings.append(f"Failed to parse date '{created_raw}': {e}")
            legacy["createdAt"] = created_raw
    else:
        legacy["createdAt"] = None
        audit.warnings.append("Missing createdAt; set to null")

    # items: convert line items to v1 items format
    items = []
    for it in line_items:
        item = {
            "sku": it.get("sku"),
            "price": float(round(_to_usd(float(it.get("price", 0.0)), it.get("currency", "USD")), 2)),
            "quantity": int(it.get("quantity", 1))
        }
        items.append(item)
    legacy["items"] = items

    return legacy, audit


# ------------------ Error normalization & classification ----------------

def normalize_error_response(status_code: int, body: Dict[str, Any]) -> Dict[str, str]:
    # Map common patterns
    if not isinstance(body, dict):
        return {"error": "UNKNOWN", "message": str(body)}
    if "error" in body and "message" in body:
        return {"error": body.get("error"), "message": body.get("message")}
    if "error_code" in body or "detail" in body:
        return {"error": body.get("error_code", "ERROR"), "message": body.get("detail", "")}
    # fallback
    return {"error": f"HTTP_{status_code}", "message": str(body)}


def classify_response(status_code: int, body: Dict[str, Any]) -> str:
    if 200 <= status_code < 300:
        return "OK"
    if status_code == 410:
        return "DEPRECATED"
    if status_code == 429 or status_code == 503:
        return "TRANSIENT"
    if 400 <= status_code < 500:
        return "CLIENT_ERROR"
    return "OUTAGE"
