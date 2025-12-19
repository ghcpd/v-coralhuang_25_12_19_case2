"""
Test Suite for Backward Compatibility Layer

Tests cover transformation from v2/v3 to v1, including edge cases.
"""

import unittest
from compatibility_layer import (
    detect_version, to_legacy, request_json, convert_currency,
    normalize_date, map_status_v2, map_status_v3, validate_price_v2,
    AuditTrail
)

class TestCompatibilityLayer(unittest.TestCase):

    def test_detect_version_v2(self):
        data = {"orderId": "123", "state": "PAID"}
        self.assertEqual(detect_version(data), 'v2')

    def test_detect_version_v3(self):
        data = {"data": [{"orderId": "123"}]}
        self.assertEqual(detect_version(data), 'v3')

    def test_convert_currency_usd(self):
        self.assertEqual(convert_currency(100, 'USD'), 100.0)

    def test_convert_currency_eur(self):
        self.assertAlmostEqual(convert_currency(100, 'EUR'), 110.0)

    def test_normalize_date(self):
        self.assertEqual(normalize_date('2023-12-19T10:00:00Z'), '2023-12-19')

    def test_map_status_v2_paid(self):
        self.assertEqual(map_status_v2('PAID'), 'PAID')

    def test_map_status_v2_fulfilled(self):
        self.assertEqual(map_status_v2('FULFILLED'), 'SHIPPED')

    def test_map_status_v3_fulfilled(self):
        data = {"trackingNumber": "123"}
        self.assertEqual(map_status_v3('FULFILLED', data), 'SHIPPED')

    def test_validate_price_v2_match(self):
        amount = {"value": 100, "currency": "USD"}
        items = [{"price": 50, "quantity": 2}]
        audit = AuditTrail()
        total = validate_price_v2(amount, items, audit)
        self.assertEqual(total, 100.0)
        self.assertEqual(len(audit.warnings), 0)

    def test_validate_price_v2_mismatch(self):
        amount = {"value": 90, "currency": "USD"}
        items = [{"price": 50, "quantity": 2}]
        audit = AuditTrail()
        total = validate_price_v2(amount, items, audit)
        self.assertEqual(total, 100.0)
        self.assertEqual(len(audit.warnings), 1)

    def test_to_legacy_v2(self):
        data = {
            "orderId": "order-123",
            "state": "PAID",
            "amount": {"value": 100.0, "currency": "USD"},
            "customer": {"id": "cust-456", "name": "John Doe"},
            "createdAt": "2023-12-19T10:00:00Z",
            "lineItems": [{"name": "Item 1", "price": 100.0, "quantity": 1}]
        }
        legacy, audit = to_legacy(data)
        self.assertEqual(legacy['orderId'], 'order-123')
        self.assertEqual(legacy['status'], 'PAID')
        self.assertEqual(legacy['totalPrice'], 100.0)
        self.assertEqual(legacy['customerId'], 'cust-456')
        self.assertEqual(legacy['customerName'], 'John Doe')
        self.assertEqual(legacy['createdAt'], '2023-12-19')

    def test_to_legacy_v3(self):
        data = {
            "data": [
                {
                    "orderId": "order-789",
                    "orderStatus": {"current": "FULFILLED", "history": []},
                    "pricing": {"subtotal": 200.0, "tax": 20.0, "discount": 10.0, "total": 210.0},
                    "customer": {"id": "cust-101", "name": "Jane Smith"},
                    "timestamps": {"created": "2023-12-19T10:00:00Z", "fulfilled": "2023-12-20T12:00:00Z"}
                }
            ]
        }
        legacy, audit = to_legacy(data)
        self.assertEqual(legacy['orderId'], 'order-789')
        self.assertEqual(legacy['status'], 'SHIPPED')
        self.assertEqual(legacy['totalPrice'], 210.0)
        self.assertEqual(legacy['customerId'], 'cust-101')
        self.assertEqual(legacy['customerName'], 'Jane Smith')
        self.assertEqual(legacy['createdAt'], '2023-12-19')

    def test_request_json_v2(self):
        status, body = request_json('GET', '/orders', {'version': 'v2'})
        self.assertEqual(status, 200)
        self.assertIn('orderId', body)

    def test_request_json_v3(self):
        status, body = request_json('GET', '/orders', {'version': 'v3'})
        self.assertEqual(status, 200)
        self.assertIn('data', body)

    # Edge cases
    def test_currency_conversion_jpy(self):
        self.assertAlmostEqual(convert_currency(1000, 'JPY'), 6.7, places=1)

    def test_normalize_date_with_timezone(self):
        self.assertEqual(normalize_date('2023-12-19T10:00:00+05:00'), '2023-12-19')

    def test_v2_price_mismatch_with_currency(self):
        amount = {"value": 100, "currency": "EUR"}  # 110 USD
        items = [{"price": 100, "quantity": 1}]  # 100 USD
        audit = AuditTrail()
        total = validate_price_v2(amount, items, audit)
        self.assertEqual(total, 100.0)  # Recalculated
        self.assertEqual(len(audit.warnings), 1)

if __name__ == '__main__':
    unittest.main()