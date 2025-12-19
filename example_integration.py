"""
Integration Example: Using the Compatibility Layer

This example demonstrates how to use the compatibility layer
to support legacy v1 clients while serving v2/v3 APIs.
"""

from compatibility_layer import (
    to_legacy,
    classify_response,
    normalize_error_response,
    register_test_data,
)
import json

# Example 1: Transform a v2 response to v1
print("="*70)
print("EXAMPLE 1: Transform v2 response to v1")
print("="*70)

v2_response = {
    "orderId": "ORD-12345",
    "state": "PAID",
    "amount": {"value": 99.99, "currency": "USD"},
    "customer": {"id": "CUST-001", "name": "Alice Smith"},
    "createdAt": "2025-12-15T10:30:00Z",
    "lineItems": [
        {"name": "Widget", "price": 99.99, "quantity": 1}
    ]
}

v1_order, audit_trail = to_legacy(v2_response)

print("\nInput (v2 format):")
print(json.dumps(v2_response, indent=2))

print("\nOutput (v1 format):")
print(json.dumps(v1_order, indent=2))

print("\nAudit Trail:")
print(f"  Decisions: {len(audit_trail.decisions)}")
for decision in audit_trail.decisions:
    print(f"    - {decision}")
print(f"  Warnings: {len(audit_trail.warnings)}")
for warning in audit_trail.warnings:
    print(f"    - {warning}")


# Example 2: Transform a v3 response to v1
print("\n" + "="*70)
print("EXAMPLE 2: Transform v3 response to v1")
print("="*70)

v3_response = {
    "data": [
        {
            "orderId": "ORD-67890",
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
            "customer": {"id": "CUST-002", "name": "Bob Johnson"},
            "timestamps": {"created": "2025-12-14T10:00:00Z", "fulfilled": "2025-12-15T14:30:00Z"}
        }
    ]
}

v1_order, audit_trail = to_legacy(v3_response)

print("\nInput (v3 format):")
print(json.dumps(v3_response, indent=2)[:500] + "...")

print("\nOutput (v1 format):")
print(json.dumps(v1_order, indent=2))

print("\nAudit Trail:")
print(f"  Decisions: {len(audit_trail.decisions)}")
for decision in audit_trail.decisions:
    print(f"    - {decision}")


# Example 3: Handle errors
print("\n" + "="*70)
print("EXAMPLE 3: Error handling and classification")
print("="*70)

error_cases = [
    (404, {"error": "not_found", "message": "Order not found"}),
    (429, {"error": "rate_limited", "message": "Too many requests"}),
    (503, {"error": "service_unavailable", "message": "Maintenance"}),
]

for status_code, error_body in error_cases:
    normalized = normalize_error_response(status_code, error_body)
    classification = classify_response(status_code, error_body)
    print(f"\nStatus {status_code}:")
    print(f"  Normalized: {normalized}")
    print(f"  Classification: {classification}")


# Example 4: Use in a middleware/proxy layer
print("\n" + "="*70)
print("EXAMPLE 4: Middleware pattern")
print("="*70)

def compatibility_middleware(status_code, response_body):
    """
    Example middleware that handles v2/v3 responses for legacy clients
    """
    # Check if error
    if not (200 <= status_code < 300):
        classification = classify_response(status_code, response_body)
        print(f"Error: {classification}")
        return None
    
    # Transform to v1
    try:
        v1_order, audit_trail = to_legacy(response_body)
        
        # In production, log audit trail to observability system
        print(f"Transformation complete. Audit: {len(audit_trail.decisions)} decisions, {len(audit_trail.warnings)} warnings")
        
        return v1_order
    except Exception as e:
        print(f"Transformation failed: {e}")
        return None


# Test the middleware
print("\nTesting middleware with v2 response:")
result = compatibility_middleware(200, v2_response)
print(f"Result orderId: {result['orderId']}")

print("\nTesting middleware with error response:")
result = compatibility_middleware(404, {"error": "not_found", "message": "Not found"})
print(f"Result: {result}")


print("\n" + "="*70)
print("Examples complete!")
print("="*70)
