"""
Test Suite for API Compatibility Layer

Tests cover:
- v2 price inconsistency and auto-repair
- v3 context-dependent status mapping
- Multi-currency conversion (EUR, JPY, GBP, CAD)
- Timezone normalization
- Error handling
- Edge cases
"""

import sys
import json
from decimal import Decimal
from typing import List, Dict, Any, Tuple
from datetime import datetime

from compatibility_layer import (
    register_test_data,
    request_json,
    detect_version,
    to_legacy,
    normalize_error_response,
    classify_response,
    convert_currency_to_usd,
    normalize_date,
    validate_price_consistency,
    map_status_v2_to_v1,
    AuditTrail,
)


class TestResult:
    """Track individual test results"""
    def __init__(self, name: str, passed: bool, message: str = ""):
        self.name = name
        self.passed = passed
        self.message = message
    
    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}" + (f" ({self.message})" if self.message else "")


class TestSuite:
    """Manages test execution and reporting"""
    def __init__(self):
        self.results: List[TestResult] = []
        self._setup_test_data()
    
    def _setup_test_data(self):
        """Register all test data scenarios"""
        
        # ===== V2 Test Cases =====
        
        # Case 1: V2 with consistent prices
        register_test_data("v2_price_consistent", 200, {
            "orderId": "ORD-V2-001",
            "state": "PAID",
            "amount": {"value": 150.00, "currency": "USD"},
            "customer": {"id": "CUST-001", "name": "Alice Johnson"},
            "createdAt": "2025-12-15T10:30:00Z",
            "lineItems": [
                {"name": "Widget A", "price": 50.00, "quantity": 1},
                {"name": "Widget B", "price": 50.00, "quantity": 2},
            ]
        })
        
        # Case 2: V2 with price mismatch (declared < calculated)
        register_test_data("v2_price_mismatch_undeclared", 200, {
            "orderId": "ORD-V2-002",
            "state": "PAID",
            "amount": {"value": 100.00, "currency": "USD"},  # Declared total
            "customer": {"id": "CUST-002", "name": "Bob Smith"},
            "createdAt": "2025-12-14T14:00:00+05:00",
            "lineItems": [
                {"name": "Premium Item", "price": 75.00, "quantity": 1},
                {"name": "Deluxe Item", "price": 50.00, "quantity": 1},
            ]
        })
        
        # Case 3: V2 with FULFILLED status and tracking → should map to SHIPPED
        register_test_data("v2_fulfilled_with_tracking", 200, {
            "orderId": "ORD-V2-003",
            "state": "FULFILLED",
            "amount": {"value": 250.00, "currency": "USD"},
            "customer": {"id": "CUST-003", "name": "Carol Davis"},
            "createdAt": "2025-12-10T08:15:30Z",
            "lineItems": [
                {"name": "Laptop", "price": 250.00, "quantity": 1},
            ],
            "trackingNumber": "TRK-123456789"
        })
        
        # Case 4: V2 with FULFILLED status without tracking → should map to SHIPPED
        register_test_data("v2_fulfilled_no_tracking", 200, {
            "orderId": "ORD-V2-004",
            "state": "FULFILLED",
            "amount": {"value": 99.99, "currency": "USD"},
            "customer": {"id": "CUST-004", "name": "David Wilson"},
            "createdAt": "2025-12-11T16:45:00Z",
            "lineItems": [
                {"name": "eBook", "price": 99.99, "quantity": 1},
            ]
        })
        
        # Case 5: V2 with EUR currency → convert to USD
        register_test_data("v2_currency_eur", 200, {
            "orderId": "ORD-V2-005",
            "state": "PAID",
            "amount": {"value": 100.00, "currency": "EUR"},
            "customer": {"id": "CUST-005", "name": "Eve Mueller"},
            "createdAt": "2025-12-13T12:00:00Z",
            "lineItems": []
        })
        
        # Case 6: V2 with JPY currency → convert to USD
        register_test_data("v2_currency_jpy", 200, {
            "orderId": "ORD-V2-006",
            "state": "CANCELLED",
            "amount": {"value": 10000.00, "currency": "JPY"},
            "customer": {"id": "CUST-006", "name": "Fujita Yuki"},
            "createdAt": "2025-12-12T09:30:00Z",
            "lineItems": []
        })
        
        # Case 7: V2 with CANCELLED status
        register_test_data("v2_cancelled_order", 200, {
            "orderId": "ORD-V2-007",
            "state": "CANCELLED",
            "amount": {"value": 75.50, "currency": "USD"},
            "customer": {"id": "CUST-007", "name": "Grace Lee"},
            "createdAt": "2025-12-08T11:20:00Z",
            "lineItems": [
                {"name": "Cancelled Item", "price": 75.50, "quantity": 1},
            ]
        })
        
        # ===== V3 Test Cases =====
        
        # Case 8: V3 basic order
        register_test_data("v3_basic_order", 200, {
            "data": [
                {
                    "orderId": "ORD-V3-001",
                    "orderStatus": {
                        "current": "PAID",
                        "history": []
                    },
                    "pricing": {
                        "subtotal": 100.00,
                        "tax": 10.00,
                        "discount": 0.00,
                        "total": 110.00,
                        "currency": "USD"
                    },
                    "customer": {
                        "id": "CUST-301",
                        "name": "Henry Chen"
                    },
                    "timestamps": {
                        "created": "2025-12-15T13:45:00Z",
                        "fulfilled": None
                    }
                }
            ]
        })
        
        # Case 9: V3 with FULFILLED status and tracking history
        register_test_data("v3_fulfilled_with_history", 200, {
            "data": [
                {
                    "orderId": "ORD-V3-002",
                    "orderStatus": {
                        "current": "FULFILLED",
                        "history": [
                            {"type": "ordered", "timestamp": "2025-12-14T10:00:00Z"},
                            {"type": "shipped", "timestamp": "2025-12-15T14:00:00Z", "tracking": "FEDEX-987654321"}
                        ]
                    },
                    "pricing": {
                        "subtotal": 200.00,
                        "tax": 20.00,
                        "discount": 10.00,
                        "total": 210.00,
                        "currency": "USD"
                    },
                    "customer": {
                        "id": "CUST-302",
                        "name": "Iris Park"
                    },
                    "timestamps": {
                        "created": "2025-12-14T10:00:00Z",
                        "fulfilled": "2025-12-15T14:30:00Z"
                    }
                }
            ]
        })
        
        # Case 10: V3 with GBP currency
        register_test_data("v3_currency_gbp", 200, {
            "data": [
                {
                    "orderId": "ORD-V3-003",
                    "orderStatus": {
                        "current": "PAID",
                        "history": []
                    },
                    "pricing": {
                        "subtotal": 100.00,
                        "tax": 0.00,
                        "discount": 0.00,
                        "total": 100.00,
                        "currency": "GBP"
                    },
                    "customer": {
                        "id": "CUST-303",
                        "name": "James Thompson"
                    },
                    "timestamps": {
                        "created": "2025-12-15T08:00:00+00:00",
                        "fulfilled": None
                    }
                }
            ]
        })
        
        # Case 11: V3 with CAD currency
        register_test_data("v3_currency_cad", 200, {
            "data": [
                {
                    "orderId": "ORD-V3-004",
                    "orderStatus": {
                        "current": "SHIPPED",
                        "history": []
                    },
                    "pricing": {
                        "subtotal": 150.00,
                        "tax": 15.00,
                        "discount": 0.00,
                        "total": 165.00,
                        "currency": "CAD"
                    },
                    "customer": {
                        "id": "CUST-304",
                        "name": "Katherine Brown"
                    },
                    "timestamps": {
                        "created": "2025-12-14T15:30:00-05:00",
                        "fulfilled": None
                    }
                }
            ]
        })
        
        # Case 12: V3 CANCELLED order
        register_test_data("v3_cancelled_order", 200, {
            "data": [
                {
                    "orderId": "ORD-V3-005",
                    "orderStatus": {
                        "current": "CANCELLED",
                        "history": [
                            {"type": "cancelled", "timestamp": "2025-12-13T12:00:00Z"}
                        ]
                    },
                    "pricing": {
                        "subtotal": 50.00,
                        "tax": 5.00,
                        "discount": 0.00,
                        "total": 55.00,
                        "currency": "USD"
                    },
                    "customer": {
                        "id": "CUST-305",
                        "name": "Laura Martinez"
                    },
                    "timestamps": {
                        "created": "2025-12-13T11:00:00Z",
                        "fulfilled": None
                    }
                }
            ]
        })
        
        # ===== Error Cases =====
        
        # Case 13: 404 Not Found
        register_test_data("error_not_found", 404, {
            "error": "not_found",
            "message": "Order not found"
        })
        
        # Case 14: 400 Bad Request
        register_test_data("error_bad_request", 400, {
            "error": "invalid_request",
            "message": "Invalid order ID format"
        })
        
        # Case 15: 429 Too Many Requests (transient)
        register_test_data("error_rate_limit", 429, {
            "error": "rate_limited",
            "message": "Too many requests"
        })
        
        # Case 16: 503 Service Unavailable
        register_test_data("error_service_unavailable", 503, {
            "error": "service_unavailable",
            "message": "Temporary maintenance"
        })
        
        # Case 17: 410 Gone (deprecated)
        register_test_data("error_deprecated", 410, {
            "error": "gone",
            "message": "This API version is no longer supported"
        })
    
    def add_result(self, name: str, passed: bool, message: str = ""):
        """Add a test result"""
        self.results.append(TestResult(name, passed, message))
    
    def print_summary(self):
        """Print test summary"""
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        
        print("\n" + "="*70)
        print("TEST RESULTS")
        print("="*70)
        
        for result in self.results:
            # Use ASCII-safe output for compatibility
            status = "PASS" if result.passed else "FAIL"
            message = f" ({result.message})" if result.message else ""
            print(f"[{status}] {result.name}{message}")
        
        print("\n" + "-"*70)
        print(f"Summary: {passed}/{total} tests passed")
        print("="*70 + "\n")
        
        return passed == total


# ============================================================================
# Test Functions
# ============================================================================

def test_version_detection(suite: TestSuite):
    """Test automatic version detection from response structure"""
    
    # Test v2 detection
    v2_data = {
        "orderId": "ORD-001",
        "state": "PAID",
        "amount": {"value": 100, "currency": "USD"},
        "customer": {"id": "C1", "name": "Test"}
    }
    try:
        version = detect_version(v2_data)
        suite.add_result("version_detection_v2", version == "v2", f"Got {version}")
    except Exception as e:
        suite.add_result("version_detection_v2", False, str(e))
    
    # Test v3 detection
    v3_data = {
        "data": [
            {
                "orderId": "ORD-001",
                "orderStatus": {"current": "PAID"},
                "pricing": {"total": 100}
            }
        ]
    }
    try:
        version = detect_version(v3_data)
        suite.add_result("version_detection_v3", version == "v3", f"Got {version}")
    except Exception as e:
        suite.add_result("version_detection_v3", False, str(e))


def test_currency_conversion(suite: TestSuite):
    """Test multi-currency conversion to USD"""
    
    test_cases = [
        ("EUR", Decimal("100"), Decimal("110.00"), "EUR → USD"),
        ("JPY", Decimal("10000"), Decimal("67.00"), "JPY → USD"),
        ("GBP", Decimal("100"), Decimal("127.00"), "GBP → USD"),
        ("CAD", Decimal("150"), Decimal("109.50"), "CAD → USD"),
        ("USD", Decimal("100"), Decimal("100.00"), "USD → USD (identity)"),
    ]
    
    for currency, amount, expected, description in test_cases:
        try:
            result = convert_currency_to_usd(amount, currency)
            passed = result == expected
            suite.add_result(
                f"currency_conversion_{currency}",
                passed,
                f"{amount} {currency} → ${result} (expected ${expected})"
            )
        except Exception as e:
            suite.add_result(f"currency_conversion_{currency}", False, str(e))


def test_date_normalization(suite: TestSuite):
    """Test timezone-safe date normalization"""
    
    test_cases = [
        ("2025-12-15T10:30:00Z", "2025-12-15", "ISO-8601 with Z"),
        ("2025-12-14T14:00:00+05:00", "2025-12-14", "ISO-8601 with +05:00"),
        ("2025-12-12T09:30:00-05:00", "2025-12-12", "ISO-8601 with -05:00"),
        ("2025-12-15", "2025-12-15", "Already YYYY-MM-DD"),
    ]
    
    for input_date, expected, description in test_cases:
        try:
            result = normalize_date(input_date)
            passed = result == expected
            suite.add_result(
                f"date_normalization_{description.replace(' ', '_')}",
                passed,
                f"{input_date} → {result} (expected {expected})"
            )
        except Exception as e:
            suite.add_result(f"date_normalization_{description.replace(' ', '_')}", False, str(e))


def test_price_validation(suite: TestSuite):
    """Test price consistency validation and auto-repair"""
    
    # Case 1: Consistent prices
    line_items_consistent = [
        {"name": "Item A", "price": 50.00, "quantity": 1},
        {"name": "Item B", "price": 50.00, "quantity": 2},
    ]
    declared = Decimal("150.00")
    total, audit = validate_price_consistency(line_items_consistent, declared)
    suite.add_result(
        "price_validation_consistent",
        total == declared and len(audit.warnings) == 0,
        f"Total: {total}, Warnings: {len(audit.warnings)}"
    )
    
    # Case 2: Inconsistent prices (should detect and use calculated)
    line_items_inconsistent = [
        {"name": "Item A", "price": 75.00, "quantity": 1},
        {"name": "Item B", "price": 50.00, "quantity": 1},
    ]
    declared = Decimal("100.00")
    total, audit = validate_price_consistency(line_items_inconsistent, declared)
    expected = Decimal("125.00")
    suite.add_result(
        "price_validation_mismatch_detected",
        total == expected and len(audit.warnings) > 0,
        f"Total: {total} (expected {expected}), Warnings: {len(audit.warnings)}"
    )


def test_v2_price_inconsistency(suite: TestSuite):
    """Test v2 price mismatch scenario from test data"""
    
    try:
        status_code, response = request_json("GET", "/orders", {"test_case": "v2_price_mismatch_undeclared"})
        v1_order, audit = to_legacy(response)
        
        # Should have warning about price mismatch
        has_warning = any("mismatch" in w.lower() for w in audit.warnings)
        # Should use calculated price (125.00) not declared (100.00)
        correct_total = v1_order["totalPrice"] == 125.00
        
        suite.add_result(
            "v2_price_mismatch_handling",
            has_warning and correct_total,
            f"Total: {v1_order['totalPrice']}, Warnings: {len(audit.warnings)}"
        )
    except Exception as e:
        suite.add_result("v2_price_mismatch_handling", False, str(e))


def test_v2_status_mapping(suite: TestSuite):
    """Test v2 status mapping logic"""
    
    test_cases = [
        ("PAID", None, "PAID", "PAID maps to PAID"),
        ("CANCELLED", None, "CANCELLED", "CANCELLED maps to CANCELLED"),
        ("FULFILLED", "TRK-123", "SHIPPED", "FULFILLED with tracking → SHIPPED"),
        ("FULFILLED", None, "SHIPPED", "FULFILLED without tracking → SHIPPED"),
    ]
    
    for v2_state, tracking, expected_v1, description in test_cases:
        try:
            v1_status, reason = map_status_v2_to_v1(v2_state, tracking)
            suite.add_result(
                f"v2_status_mapping_{v2_state}",
                v1_status == expected_v1,
                f"{description}: {v1_status} (expected {expected_v1})"
            )
        except Exception as e:
            suite.add_result(f"v2_status_mapping_{v2_state}", False, str(e))


def test_v2_to_v1_transformation(suite: TestSuite):
    """Test complete v2 to v1 transformation"""
    
    test_cases = [
        ("v2_price_consistent", "ORD-V2-001", 150.00, "PAID"),
        ("v2_fulfilled_with_tracking", "ORD-V2-003", 250.00, "SHIPPED"),
        ("v2_fulfilled_no_tracking", "ORD-V2-004", 99.99, "SHIPPED"),
        ("v2_cancelled_order", "ORD-V2-007", 75.50, "CANCELLED"),
    ]
    
    for test_case, expected_id, expected_price, expected_status in test_cases:
        try:
            status_code, response = request_json("GET", "/orders", {"test_case": test_case})
            v1_order, audit = to_legacy(response)
            
            id_match = v1_order["orderId"] == expected_id
            price_match = abs(v1_order["totalPrice"] - expected_price) < 0.01
            status_match = v1_order["status"] == expected_status
            has_customer = v1_order.get("customerName") and v1_order.get("customerId")
            has_date = v1_order.get("createdAt") and v1_order["createdAt"] != "UNKNOWN"
            
            passed = id_match and price_match and status_match and has_customer and has_date
            suite.add_result(
                f"v2_to_v1_transformation_{test_case}",
                passed,
                f"ID: {id_match}, Price: {price_match}, Status: {status_match}, Customer: {has_customer}, Date: {has_date}"
            )
        except Exception as e:
            suite.add_result(f"v2_to_v1_transformation_{test_case}", False, str(e))


def test_v2_currency_conversion(suite: TestSuite):
    """Test v2 multi-currency transformation"""
    
    test_cases = [
        ("v2_currency_eur", "ORD-V2-005", 110.00, "EUR to USD"),
        ("v2_currency_jpy", "ORD-V2-006", 67.00, "JPY to USD"),
    ]
    
    for test_case, expected_id, expected_usd_price, description in test_cases:
        try:
            status_code, response = request_json("GET", "/orders", {"test_case": test_case})
            v1_order, audit = to_legacy(response)
            
            id_match = v1_order["orderId"] == expected_id
            price_match = abs(v1_order["totalPrice"] - expected_usd_price) < 0.01
            has_conversion = any("currency_conversion" in str(d) for d in audit.decisions)
            
            passed = id_match and price_match and has_conversion
            suite.add_result(
                f"v2_currency_conversion_{description.replace(' ', '_')}",
                passed,
                f"Price: ${v1_order['totalPrice']} (expected ${expected_usd_price})"
            )
        except Exception as e:
            suite.add_result(f"v2_currency_conversion_{description.replace(' ', '_')}", False, str(e))


def test_v3_to_v1_transformation(suite: TestSuite):
    """Test complete v3 to v1 transformation"""
    
    test_cases = [
        ("v3_basic_order", "ORD-V3-001", 110.00, "PAID"),
        ("v3_fulfilled_with_history", "ORD-V3-002", 210.00, "SHIPPED"),
        ("v3_cancelled_order", "ORD-V3-005", 55.00, "CANCELLED"),
    ]
    
    for test_case, expected_id, expected_price, expected_status in test_cases:
        try:
            status_code, response = request_json("GET", "/orders", {"test_case": test_case})
            v1_order, audit = to_legacy(response)
            
            id_match = v1_order["orderId"] == expected_id
            price_match = abs(v1_order["totalPrice"] - expected_price) < 0.01
            status_match = v1_order["status"] == expected_status
            has_customer = v1_order.get("customerName") and v1_order.get("customerId")
            
            passed = id_match and price_match and status_match and has_customer
            suite.add_result(
                f"v3_to_v1_transformation_{test_case}",
                passed,
                f"ID: {id_match}, Price: {price_match}, Status: {status_match}, Customer: {has_customer}"
            )
        except Exception as e:
            suite.add_result(f"v3_to_v1_transformation_{test_case}", False, str(e))


def test_v3_currency_conversion(suite: TestSuite):
    """Test v3 multi-currency transformation"""
    
    test_cases = [
        ("v3_currency_gbp", "ORD-V3-003", 127.00, "GBP to USD"),
        ("v3_currency_cad", "ORD-V3-004", 120.45, "CAD to USD"),
    ]
    
    for test_case, expected_id, expected_usd_price, description in test_cases:
        try:
            status_code, response = request_json("GET", "/orders", {"test_case": test_case})
            v1_order, audit = to_legacy(response)
            
            id_match = v1_order["orderId"] == expected_id
            price_match = abs(v1_order["totalPrice"] - expected_usd_price) < 0.01
            
            passed = id_match and price_match
            suite.add_result(
                f"v3_currency_conversion_{description.replace(' ', '_')}",
                passed,
                f"Price: ${v1_order['totalPrice']} (expected ${expected_usd_price})"
            )
        except Exception as e:
            suite.add_result(f"v3_currency_conversion_{description.replace(' ', '_')}", False, str(e))


def test_v3_status_from_history(suite: TestSuite):
    """Test v3 status mapping using history"""
    
    try:
        status_code, response = request_json("GET", "/orders", {"test_case": "v3_fulfilled_with_history"})
        v1_order, audit = to_legacy(response)
        
        # FULFILLED in v3 should map to SHIPPED (status mapping)
        # With tracking in history, should be SHIPPED
        passed = v1_order["status"] == "SHIPPED"
        has_tracking_decision = any("tracking" in str(d).lower() for d in audit.decisions)
        
        suite.add_result(
            "v3_status_mapping_from_history",
            passed and has_tracking_decision,
            f"Status: {v1_order['status']}, Has tracking decision: {has_tracking_decision}"
        )
    except Exception as e:
        suite.add_result("v3_status_mapping_from_history", False, str(e))


def test_error_response_normalization(suite: TestSuite):
    """Test error response normalization"""
    
    test_cases = [
        ("error_not_found", 404, "not_found"),
        ("error_bad_request", 400, "invalid_request"),
    ]
    
    for test_case, expected_code, expected_error in test_cases:
        try:
            status_code, response = request_json("GET", "/orders", {"test_case": test_case})
            normalized = normalize_error_response(status_code, response)
            
            code_match = status_code == expected_code
            error_match = normalized.get("error") == expected_error
            has_message = normalized.get("message") and len(normalized.get("message")) > 0
            
            passed = code_match and error_match and has_message
            suite.add_result(
                f"error_normalization_{test_case}",
                passed,
                f"Error: {normalized.get('error')}, Message: {normalized.get('message')}"
            )
        except Exception as e:
            suite.add_result(f"error_normalization_{test_case}", False, str(e))


def test_response_classification(suite: TestSuite):
    """Test response classification for error handling"""
    
    test_cases = [
        (200, {"data": []}, "OK"),
        (404, {"error": "not_found"}, "CLIENT_ERROR"),
        (400, {"error": "bad_request"}, "CLIENT_ERROR"),
        (429, {"error": "rate_limited"}, "TRANSIENT"),
        (503, {"error": "unavailable"}, "OUTAGE"),
        (410, {"error": "gone"}, "DEPRECATED"),
        (500, {"error": "internal"}, "OUTAGE"),
    ]
    
    for status_code, body, expected_classification in test_cases:
        try:
            classification = classify_response(status_code, body)
            passed = classification == expected_classification
            suite.add_result(
                f"response_classification_{status_code}",
                passed,
                f"Got {classification} (expected {expected_classification})"
            )
        except Exception as e:
            suite.add_result(f"response_classification_{status_code}", False, str(e))


def test_audit_trail_tracking(suite: TestSuite):
    """Test that audit trails record transformation decisions"""
    
    try:
        status_code, response = request_json("GET", "/orders", {"test_case": "v2_currency_eur"})
        v1_order, audit = to_legacy(response)
        
        # Should have version detection decision
        has_version_detection = any(d.get("key") == "version_detection" for d in audit.decisions)
        # Should have status mapping decision
        has_status_mapping = any(d.get("key") == "status_mapping" for d in audit.decisions)
        # Should have currency conversion decision (since EUR)
        has_currency_decision = any("currency_conversion" in str(d) for d in audit.decisions)
        
        passed = has_version_detection and has_status_mapping and has_currency_decision
        suite.add_result(
            "audit_trail_tracking",
            passed,
            f"Version: {has_version_detection}, Status: {has_status_mapping}, Currency: {has_currency_decision}"
        )
    except Exception as e:
        suite.add_result("audit_trail_tracking", False, str(e))


def run_all_tests() -> bool:
    """Run complete test suite"""
    
    suite = TestSuite()
    
    print("\n" + "="*70)
    print("API COMPATIBILITY LAYER TEST SUITE")
    print("="*70 + "\n")
    
    # Run test groups
    print("Testing version detection...")
    test_version_detection(suite)
    
    print("Testing currency conversion...")
    test_currency_conversion(suite)
    
    print("Testing date normalization...")
    test_date_normalization(suite)
    
    print("Testing price validation...")
    test_price_validation(suite)
    
    print("Testing v2 price inconsistency handling...")
    test_v2_price_inconsistency(suite)
    
    print("Testing v2 status mapping...")
    test_v2_status_mapping(suite)
    
    print("Testing v2 to v1 transformation...")
    test_v2_to_v1_transformation(suite)
    
    print("Testing v2 currency conversion...")
    test_v2_currency_conversion(suite)
    
    print("Testing v3 to v1 transformation...")
    test_v3_to_v1_transformation(suite)
    
    print("Testing v3 currency conversion...")
    test_v3_currency_conversion(suite)
    
    print("Testing v3 status from history...")
    test_v3_status_from_history(suite)
    
    print("Testing error response normalization...")
    test_error_response_normalization(suite)
    
    print("Testing response classification...")
    test_response_classification(suite)
    
    print("Testing audit trail tracking...")
    test_audit_trail_tracking(suite)
    
    # Print results
    return suite.print_summary()


if __name__ == "__main__":
    all_passed = run_all_tests()
    sys.exit(0 if all_passed else 1)
