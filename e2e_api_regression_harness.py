"""
E2E API Migration Regression Harness - ADVANCED

Tests v1→v2→v3 API migration with compatibility layer.

Run modes (set TEST_MODE env var):
  RAW_V2  - Show v2 breaks legacy (tests SHOULD FAIL)
  RAW_V3  - Show v3 breaks legacy (tests SHOULD FAIL)
  COMPAT  - Verify compatibility layer works (tests SHOULD PASS)

Offline mode (no BASE_URL): Uses embedded test data
Online mode (BASE_URL set): Calls real API

Agent tasks:
1. request_json(): HTTP client with retry
2. detect_version(): Auto-detect v2 vs v3
3. v2_to_legacy(): Transform v2→v1
4. v3_to_legacy(): Transform v3→v1 (advanced)
5. to_legacy(): Unified mapper
6. classify_response(): Monitor classification
7. normalize_error_response(): Error aggregation
8. validate_idempotency(): Check idempotency
9. benchmark_transformation(): Performance test
"""

from __future__ import annotations
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from copy import deepcopy

# Test mode control
TEST_MODE = os.environ.get("TEST_MODE", "COMPAT")  # RAW_V2, RAW_V3, or COMPAT

# -------------------------
# Test vectors (embedded)
# -------------------------

CASES_JSON = r"""
{
  "error_cases": [
    {
      "id": "missing_includeItems_v2",
      "version": "v2",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "123" }
      },
      "response": {
        "statusCode": 200,
        "body": { 
          "orderId": "ORD-123", 
          "state": "PAID", 
          "amount": {"value": 199.99, "currency": "USD"},
          "customer": {"id": "C123", "name": "Alice", "email": "alice@example.com"},
          "createdAt": "2024-12-18T10:30:00Z"
        }
      }
    },
    {
      "id": "items_vs_lineItems_mismatch",
      "version": "v2",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "789", "includeItems": "true" }
      },
      "response": {
        "statusCode": 200,
        "body": {
          "orderId": "ORD-789",
          "state": "SHIPPED",
          "amount": {"value": 59.5, "currency": "USD"},
          "customer": {"id": "C789", "name": "Bob", "email": "bob@example.com"},
          "createdAt": "2024-12-17T15:45:30Z",
          "trackingNumber": "TRACK-789-XYZ",
          "lineItems": [
            { "name": "Pen", "quantity": 3, "unitPrice": 5.5, "tax": 0.8 },
            { "name": "Notebook", "quantity": 2, "unitPrice": 15.0, "tax": 2.0 }
          ]
        }
      }
    },
    {
      "id": "v3_complex_pricing_with_discount",
      "version": "v3",
      "request": {
        "method": "GET",
        "path": "/api/v3/orders",
        "query": { "userId": "456", "includeItems": "true" }
      },
      "response": {
        "statusCode": 200,
        "body": {
          "data": [{
            "orderId": "ORD-456",
            "orderStatus": {
              "current": "FULFILLED",
              "history": [
                {"status": "PAID", "timestamp": "2024-12-10T09:00:00Z", "reason": "Payment processed"},
                {"status": "SHIPPED", "timestamp": "2024-12-11T14:00:00Z", "reason": "Dispatched from warehouse"},
                {"status": "FULFILLED", "timestamp": "2024-12-13T10:30:00Z", "reason": "Delivered to customer"}
              ]
            },
            "pricing": {
              "subtotal": 150.0,
              "tax": 12.0,
              "discount": {"code": "SAVE20", "amount": 30.0},
              "total": 132.0,
              "currency": "USD"
            },
            "customer": {
              "id": "C456",
              "name": "Carol",
              "email": "carol@example.com",
              "address": {"street": "123 Main St", "city": "Springfield", "country": "USA", "postalCode": "12345"},
              "loyaltyTier": "GOLD"
            },
            "timestamps": {
              "created": "2024-12-10T08:45:00Z",
              "updated": "2024-12-13T10:30:00Z",
              "fulfilled": "2024-12-13T10:30:00Z"
            },
            "lineItems": [
              {
                "id": "ITEM-001",
                "name": "Premium Widget",
                "quantity": 5,
                "pricing": {"unit": 30.0, "tax": 2.4, "subtotal": 150.0},
                "variant": {"sku": "WIDGET-PREM-001", "attributes": {"color": "blue", "size": "large"}},
                "availability": {"stock": 25, "eta": null}
              }
            ],
            "shipment": {
              "carrier": "FastShip",
              "trackingNumber": "TRACK-456-ABC",
              "estimatedDelivery": "2024-12-13T00:00:00Z",
              "actualDelivery": "2024-12-13T10:30:00Z"
            }
          }],
          "pagination": {"page": 1, "size": 1, "total": 1, "hasMore": false},
          "metadata": {"version": "3.0", "cacheHint": 3600}
        }
      }
    },
    {
      "id": "v3_multi_currency_order",
      "version": "v3",
      "request": {
        "method": "GET",
        "path": "/api/v3/orders",
        "query": { "userId": "777" }
      },
      "response": {
        "statusCode": 200,
        "body": {
          "data": [{
            "orderId": "ORD-777",
            "orderStatus": {"current": "PAID", "history": [{"status": "PAID", "timestamp": "2024-12-18T12:00:00Z", "reason": "Payment received"}]},
            "pricing": {"subtotal": 100.0, "tax": 20.0, "total": 120.0, "currency": "EUR"},
            "customer": {"id": "C777", "name": "Diana", "email": "diana@example.com", "address": {"street": "456 Rue", "city": "Paris", "country": "France"}},
            "timestamps": {"created": "2024-12-18T12:00:00Z", "updated": "2024-12-18T12:00:00Z", "fulfilled": null}
          }],
          "pagination": {"page": 1, "size": 1, "total": 1, "hasMore": false}
        }
      }
    },
    {
      "id": "v3_deeply_nested_missing_optional",
      "version": "v3",
      "request": {
        "method": "GET",
        "path": "/api/v3/orders",
        "query": { "userId": "888" }
      },
      "response": {
        "statusCode": 200,
        "body": {
          "data": [{
            "orderId": "ORD-888",
            "orderStatus": {"current": "CANCELLED", "history": [{"status": "CANCELLED", "timestamp": "2024-12-15T12:00:00Z", "reason": "Customer request"}]},
            "pricing": {"subtotal": 0.0, "tax": 0.0, "total": 0.0, "currency": "USD"},
            "customer": {"id": "C888", "name": "Eve"},
            "timestamps": {"created": "2024-12-15T11:00:00Z", "updated": "2024-12-15T12:00:00Z", "fulfilled": null}
          }],
          "pagination": {"page": 1, "size": 1, "total": 1, "hasMore": false}
        }
      }
    },
    {
      "id": "deprecated_v1_monitored_as_outage",
      "version": "v1",
      "request": {
        "method": "GET",
        "path": "/api/v1/orders",
        "query": { "userId": "999" }
      },
      "response": {
        "statusCode": 410,
        "body": { "error": "API_VERSION_DEPRECATED", "message": "Please migrate to /api/v2/orders" }
      }
    },
    {
      "id": "new_state_enum_breaks_legacy_enum",
      "version": "v2",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "555", "includeItems": "false" }
      },
      "response": {
        "statusCode": 200,
        "body": { 
          "orderId": "ORD-555", 
          "state": "FULFILLED", 
          "amount": {"value": 120.0, "currency": "EUR"},
          "customer": {"id": "C555", "name": "Charlie"},
          "createdAt": "2024-12-16T08:20:15Z"
        }
      }
    },
    {
      "id": "v2_error_format_new_structure",
      "version": "v2",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "invalid" }
      },
      "response": {
        "statusCode": 400,
        "body": {
          "errors": [
            {"code": "INVALID_USER_ID", "message": "User ID must be numeric", "field": "userId"},
            {"code": "RATE_LIMIT", "message": "Too many requests", "field": null}
          ]
        }
      }
    },
    {
      "id": "v3_error_format_with_retry_hint",
      "version": "v3",
      "request": {
        "method": "GET",
        "path": "/api/v3/orders",
        "query": { "userId": "bad" }
      },
      "response": {
        "statusCode": 503,
        "body": {
          "errors": [
            {"code": "SERVICE_UNAVAILABLE", "message": "Database temporarily unavailable", "field": null, "metadata": {"retry_after": 60}}
          ],
          "requestId": "req-123-456",
          "timestamp": "2024-12-18T15:00:00Z",
          "retryable": true
        }
      }
    },
    {
      "id": "nested_customer_data_missing_email",
      "version": "v2",
      "request": {
        "method": "GET",
        "path": "/api/v2/orders",
        "query": { "userId": "888" }
      },
      "response": {
        "statusCode": 200,
        "body": {
          "orderId": "ORD-888",
          "state": "CANCELLED",
          "amount": {"value": 0.0, "currency": "USD"},
          "customer": {"id": "C888", "name": "Dave"},
          "createdAt": "2024-12-15T12:00:00Z"
        }
      }
    }
  ]
}
"""

CASES = json.loads(CASES_JSON)["error_cases"]

LEGACY_ENUM = {"PAID", "CANCELLED", "SHIPPED"}  # legacy known values


# -------------------------
# Minimal runner utilities
# -------------------------

@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str = ""


def _pass(name: str, details: str = "") -> CheckResult:
    return CheckResult(name=name, ok=True, details=details)


def _fail(name: str, details: str = "") -> CheckResult:
    return CheckResult(name=name, ok=False, details=details)


def print_report(results: List[CheckResult]) -> None:
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        line = f"{status} - {r.name}"
        if r.details:
            line += f" :: {r.details}"
        print(line)
    print(f"\nSummary: {passed}/{total} PASS")
    if passed != total:
        sys.exit(1)


# -------------------------
# TODO: Implement these 9 functions
# -------------------------

def request_json(method: str, path: str, query: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    """HTTP client with retry logic. Falls back to embedded test data if BASE_URL not set."""
    base_url = os.environ.get("BASE_URL", "").strip()
    if not base_url:
        for c in CASES:
            req = c["request"]
            if req["method"] == method and req["path"] == path and req["query"] == query:
                return c["response"]["statusCode"], c["response"]["body"]
        raise RuntimeError(f"No test data for {method} {path} {query}")
    # TODO: Implement HTTP call with 3 retries, exponential backoff
    raise NotImplementedError("TODO: HTTP client with retry")


def detect_version(order_data: Dict[str, Any]) -> str:
    """Auto-detect v2 vs v3. v3 has 'data' array, v2 doesn't. Returns 'v2' or 'v3'."""
    # TODO: Implement version detection
    raise NotImplementedError("TODO: detect_version")


def v2_to_legacy(order_v2: Dict[str, Any]) -> Dict[str, Any]:
    """Transform v2→v1: flatten customer, amount→totalPrice, ISO→YYYY-MM-DD, lineItems→items."""
    # TODO: Implement v2 mapping
    raise NotImplementedError("TODO: v2_to_legacy")


def v3_to_legacy(order_v3: Dict[str, Any]) -> Dict[str, Any]:
    """Transform v3→v1: unwrap pagination, orderStatus→status, pricing→totalPrice, timestamps→createdAt."""
    # TODO: Implement v3 advanced mapping
    raise NotImplementedError("TODO: v3_to_legacy")


def to_legacy(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """Unified mapper. Auto-detects version and routes to v2_to_legacy or v3_to_legacy."""
    if TEST_MODE in ("RAW_V2", "RAW_V3"):
        return order_data
    version = detect_version(order_data)
    return v2_to_legacy(order_data) if version == "v2" else v3_to_legacy(order_data)


def classify_response(status_code: int, body: Dict[str, Any]) -> str:
    """Classify response: DEPRECATED, TRANSIENT, CLIENT_ERROR, OUTAGE, OK."""
    # TODO: Implement classification
    raise NotImplementedError("TODO: classify_response")


def normalize_error_response(status_code: int, body: Dict[str, Any]) -> Dict[str, str]:
    """Normalize v2/v3 errors to v1 format. Aggregate multiple errors."""
    # TODO: Implement error normalization
    raise NotImplementedError("TODO: normalize_error_response")


def validate_idempotency(order_data: Dict[str, Any]) -> bool:
    """Verify to_legacy(to_legacy(x)) == to_legacy(x)."""
    # TODO: Implement idempotency check
    raise NotImplementedError("TODO: validate_idempotency")


def benchmark_transformation(order_data: Dict[str, Any], iterations: int = 1000) -> float:
    """Measure avg transformation time in ms."""
    # TODO: Implement benchmark
    raise NotImplementedError("TODO: benchmark_transformation")


# -------------------------
# Test checks
# -------------------------

def check_raw_v2_breaks_legacy_items_missing() -> CheckResult:
    if TEST_MODE == "RAW_V3":
        return _pass("skipped in RAW_V3 mode")
    status, body = request_json("GET", "/api/v2/orders", {"userId": "123"})
    if status != 200:
        return _fail("expected 200", f"got {status}")
    
    if TEST_MODE == "COMPAT":
        body = to_legacy(body)
    
    if TEST_MODE == "RAW_V2":
        return _pass("v2 missing items (DESIGNED TO FAIL)") if "items" not in body else _fail("unexpected items")
    else:
        return _pass("items present") if "items" in body and isinstance(body["items"], list) else _fail("missing items")


def check_raw_v2_breaks_legacy_enum_on_new_state() -> CheckResult:
    if TEST_MODE == "RAW_V3":
        return _pass("skipped")
    status, body = request_json("GET", "/api/v2/orders", {"userId": "555", "includeItems": "false"})
    if status != 200:
        return _fail("expected 200", f"got {status}")
    
    if TEST_MODE == "COMPAT":
        body = to_legacy(body)
    
    state = body.get("state") or body.get("status")
    if TEST_MODE == "RAW_V2":
        return _pass(f"new state {state} (DESIGNED TO FAIL)") if state not in LEGACY_ENUM else _fail("expected new state")
    else:
        return _pass(f"status={state}") if state in LEGACY_ENUM else _fail(f"invalid status={state}")


def check_raw_v3_breaks_with_pagination_wrapper() -> CheckResult:
    if TEST_MODE == "RAW_V2":
        return _pass("skipped")
    status, body = request_json("GET", "/api/v3/orders", {"userId": "456", "includeItems": "true"})
    if status != 200:
        return _fail("expected 200", f"got {status}")
    
    if TEST_MODE == "COMPAT":
        body = to_legacy(body)
    
    if TEST_MODE == "RAW_V3":
        return _pass("pagination wrapper (DESIGNED TO FAIL)") if "data" in body else _fail("no wrapper")
    else:
        return _pass("unwrapped") if "data" not in body and "orderId" in body else _fail("not unwrapped")


def check_raw_v3_breaks_with_complex_pricing() -> CheckResult:
    if TEST_MODE == "RAW_V2":
        return _pass("skipped")
    status, body = request_json("GET", "/api/v3/orders", {"userId": "456", "includeItems": "true"})
    if status != 200:
        return _fail("expected 200", f"got {status}")
    
    if TEST_MODE == "COMPAT":
        body = to_legacy(body)
    
    has_pricing = "pricing" in (body.get("data", [{}])[0] if "data" in body else body)
    if TEST_MODE == "RAW_V3":
        return _pass("complex pricing (DESIGNED TO FAIL)") if has_pricing else _fail("no pricing")
    else:
        has_total = isinstance(body.get("totalPrice"), (int, float))
        return _pass("converted to totalPrice") if has_total else _fail(f"totalPrice={body.get('totalPrice')}")


def check_compat_mapping_produces_legacy_shape() -> CheckResult:
    if TEST_MODE != "COMPAT":
        return _pass("skipped")
    
    status, body = request_json("GET", "/api/v2/orders", {"userId": "789", "includeItems": "true"})
    legacy = to_legacy(body) if status == 200 else {}

    required = {"orderId", "status", "totalPrice", "items", "customerId", "customerName", "createdAt"}
    missing = [k for k in required if k not in legacy]
    if missing:
        return _fail(f"missing fields: {missing}")

    import re
    checks = [
        (isinstance(legacy["items"], list) and len(legacy["items"]) > 0, "items non-empty list"),
        ("productName" in legacy["items"][0] and "qty" in legacy["items"][0], "items shape"),
        (legacy["status"] in LEGACY_ENUM, f"status enum: {legacy['status']}"),
        (isinstance(legacy["totalPrice"], (int, float)), "totalPrice numeric"),
        (re.match(r'^\d{4}-\d{2}-\d{2}$', legacy["createdAt"]), "createdAt YYYY-MM-DD")
    ]
    
    for check, desc in checks:
        if not check:
            return _fail(desc)
    
    return _pass("legacy shape OK")


def check_v3_advanced_features() -> CheckResult:
    if TEST_MODE != "COMPAT":
        return _pass("skipped")
    
    status, body = request_json("GET", "/api/v3/orders", {"userId": "456", "includeItems": "true"})
    legacy = to_legacy(body) if status == 200 else {}
    
    checks = [
        ("customer" not in legacy and "customerId" in legacy, "flattened customer"),
        ("orderStatus" not in legacy and "status" in legacy, "flattened status"),
        ("timestamps" not in legacy and "createdAt" in legacy, "flattened timestamps"),
    ]
    
    for check, desc in checks:
        if not check:
            return _fail(desc)
    
    return _pass("v3 advanced mapping OK")


def check_error_handling() -> CheckResult:
    if TEST_MODE != "COMPAT":
        return _pass("skipped")
    
    # v2 error
    status, body = request_json("GET", "/api/v2/orders", {"userId": "invalid"})
    norm = normalize_error_response(status, body)
    if "error" not in norm or "errors" in norm:
        return _fail("v2 error not normalized")
    
    # v3 error with retry
    status, body = request_json("GET", "/api/v3/orders", {"userId": "bad"})
    norm = normalize_error_response(status, body)
    if "error" not in norm or "retry" not in norm["message"].lower():
        return _fail("v3 retry hint missing")
    
    return _pass("error normalization OK")


def check_response_classification() -> CheckResult:
    tests = [
        (request_json("GET", "/api/v1/orders", {"userId": "999"}), "DEPRECATED"),
        (request_json("GET", "/api/v3/orders", {"userId": "bad"}), "TRANSIENT"),
    ]
    
    for (status, body), expected in tests:
        result = classify_response(status, body)
        if result != expected:
            return _fail(f"classification: expected {expected}, got {result}")
    
    return _pass("classification OK")


def check_idempotency() -> CheckResult:
    if TEST_MODE != "COMPAT":
        return _pass("skipped")
    
    for user_id in ["123", "456"]:
        path = "/api/v2/orders" if user_id == "123" else "/api/v3/orders"
        status, body = request_json("GET", path, {"userId": user_id, "includeItems": "true"})
        if status == 200 and not validate_idempotency(body):
            return _fail(f"not idempotent: userId={user_id}")
    
    return _pass("idempotency OK")


def check_performance() -> CheckResult:
    if TEST_MODE != "COMPAT":
        return _pass("skipped")
    
    status, body = request_json("GET", "/api/v2/orders", {"userId": "789", "includeItems": "true"})
    if status != 200:
        return _fail("expected 200")
    
    avg_ms = benchmark_transformation(body, iterations=100)
    return _pass(f"{avg_ms:.3f}ms avg") if avg_ms < 10.0 else _fail(f"too slow: {avg_ms:.3f}ms")


def main() -> None:
    mode = TEST_MODE
    print(f"\n{'='*60}\nTest Mode: {mode}\n{'='*60}\n")
    
    if mode == "RAW_V2":
        results = [
            check_raw_v2_breaks_legacy_items_missing(),
            check_raw_v2_breaks_legacy_enum_on_new_state(),
        ]
        print(f"\n{'='*60}\nRAW_V2: Tests SHOULD FAIL (show v2 breakage)\n{'='*60}")
    elif mode == "RAW_V3":
        results = [
            check_raw_v3_breaks_with_pagination_wrapper(),
            check_raw_v3_breaks_with_complex_pricing(),
        ]
        print(f"\n{'='*60}\nRAW_V3: Tests SHOULD FAIL (show v3 breakage)\n{'='*60}")
    elif mode == "COMPAT":
        results = [
            check_compat_mapping_produces_legacy_shape(),
            check_v3_advanced_features(),
            check_error_handling(),
            check_response_classification(),
            check_idempotency(),
            check_performance(),
        ]
        print(f"\n{'='*60}\nCOMPAT: Tests SHOULD PASS (mapping works)\n{'='*60}")
    else:
        print(f"Unknown TEST_MODE: {mode}")
        sys.exit(1)
    
    print_report(results)


if __name__ == "__main__":
    main()
