"""
E2E API Migration Regression Test Harness

Task: Implement v1→v2→v3 API compatibility layer with:
- Context-aware status mapping
- Multi-currency conversion
- Price consistency validation
- Timezone handling
- State machine validation

Test modes: RAW_V2, RAW_V3, COMPAT

Implement all TODO functions to pass tests.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

# Import compatibility layer implementation
from compatibility_layer import (
    request_json as compat_request_json,
    detect_version,
    to_legacy as compat_to_legacy,
    normalize_error_response,
    classify_response,
    AuditTrail,
)

TEST_MODE = os.environ.get("TEST_MODE", "COMPAT")

# Test data is now managed in compatibility_layer.py via register_test_data()
# The compatibility layer provides all necessary functions for v2/v3 → v1 transformation
CASES = []

@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str = ""

# ======================================================================
# TODO: Implement these core functions
# ======================================================================

def request_json(method: str, path: str, query: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    """
    Mocked API response provider - delegates to compatibility layer.
    
    Returns: (status_code, response_body)
    """
    return compat_request_json(method, path, query)

def detect_version(order_data: Dict[str, Any]) -> str:
    """
    TODO: Auto-detect API version from response structure
    - v3: has 'data' array at top level
    - v2: has 'orderId' at top level
    """
    raise NotImplementedError("TODO: detect_version")

def to_legacy(order_data: Dict[str, Any]) -> Tuple[Dict[str, Any], AuditTrail]:
    """
    Transform v2/v3 order to v1 format - delegates to compatibility layer.
    
    Key requirements:
    1. Detect version
    2. Map status contextually (FULFILLED → SHIPPED if has tracking, else SHIPPED)
    3. Validate price consistency
    4. Convert currency to USD
    5. Handle timezone conversion
    6. Record decisions in audit trail
    
    Returns: (legacy_order, audit_trail)
    """
    return compat_to_legacy(order_data)

def normalize_error_response(status_code: int, body: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize v2/v3 errors to v1 format {error, message} - delegates to compatibility layer.
    """
    from compatibility_layer import normalize_error_response as compat_normalize_error_response
    return compat_normalize_error_response(status_code, body)

def classify_response(status_code: int, body: Dict[str, Any]) -> str:
    """
    Classify response type - delegates to compatibility layer.
    Returns: "DEPRECATED" | "TRANSIENT" | "CLIENT_ERROR" | "OUTAGE" | "OK"
    """
    from compatibility_layer import classify_response as compat_classify_response
    return compat_classify_response(status_code, body)

# ======================================================================
# TODO: Design and implement your own test suite
# ======================================================================

def run_tests() -> List[CheckResult]:
    """
    Run compatibility layer tests and return results.
    
    Tests verify:
    - Price consistency validation and auto-repair
    - Context-aware status mapping (FULFILLED → SHIPPED logic)
    - Currency conversion (if applicable)
    - Timezone conversion (ISO 8601 → YYYY-MM-DD)
    - Error handling
    - Edge cases
    
    Return: List of CheckResult(name, ok, details)
    """
    from test_suite import run_all_tests
    
    # Run the full test suite
    all_passed = run_all_tests()
    
    # For the harness, we return a list of CheckResults
    # The actual test results are printed by run_all_tests()
    return [CheckResult("All Compatibility Layer Tests", all_passed, "See detailed output above")]

def main() -> None:
    print(f"\nTest Mode: {TEST_MODE}\n")
    
    try:
        results = run_tests()
    except NotImplementedError as e:
        print(f"Error: {e}")
        print("\nYou need to implement:")
        print("1. Test data generation (populate CASES or mock in request_json)")
        print("2. Core transformation functions (detect_version, to_legacy, etc.)")
        print("3. Test suite (run_tests function with your test cases)")
        sys.exit(1)
    
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    
    for r in results:
        status = "[PASS]" if r.ok else "[FAIL]"
        print(f"{status} {r.name}: {r.details}")
    
    print(f"\nSummary: {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)

if __name__ == "__main__":
    main()
