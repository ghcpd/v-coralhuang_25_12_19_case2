"""
API Compatibility Layer: v2/v3 → v1 Transformation

Handles:
- Version auto-detection
- Context-aware status mapping
- Price validation and normalization
- Multi-currency conversion
- Timezone normalization
- Audit trail tracking
"""

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional
from decimal import Decimal, ROUND_HALF_UP

# Currency conversion rates to USD (simplified; in production use live rates)
EXCHANGE_RATES = {
    "USD": Decimal("1.0"),
    "EUR": Decimal("1.10"),  # 1 EUR = 1.10 USD
    "JPY": Decimal("0.0067"),  # 1 JPY = 0.0067 USD
    "GBP": Decimal("1.27"),  # 1 GBP = 1.27 USD
    "CAD": Decimal("0.73"),  # 1 CAD = 0.73 USD
}

# Test data store for mocked API responses
TEST_DATA_STORE = {}


@dataclass
class AuditTrail:
    """Track transformation decisions and data quality issues"""
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_decision(self, key: str, value: Any) -> None:
        """Record a transformation decision"""
        self.decisions.append({"key": key, "value": value})

    def add_warning(self, message: str) -> None:
        """Record a data quality warning"""
        self.warnings.append(message)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize audit trail"""
        return asdict(self)


def register_test_data(key: str, status_code: int, response: Dict[str, Any]) -> None:
    """Register test data that request_json will return"""
    TEST_DATA_STORE[key] = (status_code, response)


def request_json(method: str, path: str, query: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    """
    Mocked API response provider for test scenarios.
    
    Looks up responses from TEST_DATA_STORE based on query parameters.
    In a real scenario, this would make actual HTTP requests.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path
        query: Query parameters dict
    
    Returns:
        Tuple of (status_code, response_body)
    """
    # Construct lookup key from query parameters
    lookup_key = query.get("test_case", f"{method}:{path}")
    
    if lookup_key in TEST_DATA_STORE:
        return TEST_DATA_STORE[lookup_key]
    
    # Default: order not found
    return (404, {"error": "not_found", "message": "Order not found"})


def detect_version(order_data: Dict[str, Any]) -> str:
    """
    Auto-detect API version from response structure.
    
    - v3: top-level 'data' array
    - v2: 'orderId' at root + nested 'state' field
    - v1: 'orderId' at root + flat 'status' field
    
    Args:
        order_data: Response body from API
    
    Returns:
        "v1", "v2", or "v3"
    
    Raises:
        ValueError: If version cannot be determined
    """
    if isinstance(order_data, dict):
        # Check for v3 structure (pagination wrapper)
        if "data" in order_data and isinstance(order_data.get("data"), list):
            return "v3"
        
        # Check for v2 structure (nested customer, nested amount)
        if "orderId" in order_data:
            if "state" in order_data:
                return "v2"
            if "status" in order_data and isinstance(order_data.get("customer"), dict):
                # Could be v2 with status mapped, but let's check for nested structures
                return "v2" if "amount" in order_data or "customer" in order_data else "v1"
            if "status" in order_data:
                return "v1"
    
    raise ValueError(f"Cannot detect API version from data: {order_data}")


def convert_currency_to_usd(amount: Decimal, currency: str) -> Decimal:
    """
    Convert currency amount to USD.
    
    Args:
        amount: Numeric amount in source currency
        currency: ISO-4217 currency code (USD, EUR, JPY, etc.)
    
    Returns:
        Amount in USD (rounded to 2 decimal places)
    
    Raises:
        ValueError: If currency not supported
    """
    if currency not in EXCHANGE_RATES:
        raise ValueError(f"Unsupported currency: {currency}")
    
    rate = EXCHANGE_RATES[currency]
    usd_amount = amount * rate
    
    # Round to 2 decimal places
    return usd_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_date(date_str: str) -> str:
    """
    Normalize date to YYYY-MM-DD format (v1 format).
    
    Handles:
    - ISO-8601 timestamps with timezone info
    - YYYY-MM-DD naive dates
    - Various timestamp formats
    
    Args:
        date_str: Date string in any format
    
    Returns:
        Date in YYYY-MM-DD format
    
    Raises:
        ValueError: If date cannot be parsed
    """
    if not date_str:
        return None
    
    # Try ISO-8601 with timezone
    try:
        # Handle ISO format with Z or +/-HH:MM timezone
        if "T" in date_str:
            # Remove timezone info
            if "+" in date_str:
                date_str = date_str.split("+")[0]
            elif date_str.endswith("Z"):
                date_str = date_str[:-1]
            elif date_str.count("-") > 2:  # Date has - and timezone has -
                # Find the T and split from there
                parts = date_str.split("T")
                date_part = parts[0]
                time_part = parts[1].split("-")[-2] if "-" in parts[1].split(".")[0] else parts[1]
                date_str = f"{date_part}T{time_part}"
            
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%Y-%m-%d")
        
        # Try YYYY-MM-DD format
        if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
            datetime.strptime(date_str, "%Y-%m-%d")
            return date_str
    except (ValueError, AttributeError):
        pass
    
    raise ValueError(f"Cannot parse date: {date_str}")


def validate_price_consistency(line_items: List[Dict[str, Any]], 
                               declared_total: Decimal) -> Tuple[Decimal, AuditTrail]:
    """
    Validate price consistency between line items and declared total.
    
    If mismatch detected, recalculate from line items.
    
    Args:
        line_items: List of order line items, each with 'price' and 'quantity'
        declared_total: Total price from order header
    
    Returns:
        Tuple of (correct_total, audit_trail with decisions/warnings)
    """
    audit = AuditTrail()
    
    # Calculate total from line items
    calculated_total = Decimal("0")
    for item in line_items:
        try:
            price = Decimal(str(item.get("price", 0)))
            quantity = Decimal(str(item.get("quantity", 1)))
            calculated_total += price * quantity
        except (ValueError, TypeError):
            audit.add_warning(f"Invalid line item price: {item}")
    
    # Compare with declared total
    declared = Decimal(str(declared_total))
    tolerance = Decimal("0.01")  # Allow 1 cent difference
    
    if abs(calculated_total - declared) > tolerance:
        audit.add_warning(
            f"Price mismatch: declared ${declared}, calculated ${calculated_total}"
        )
        audit.add_decision("price_correction", {
            "declared": float(declared),
            "calculated": float(calculated_total),
            "using": "calculated"
        })
        return calculated_total, audit
    
    audit.add_decision("price_consistency", "valid")
    return declared, audit


def map_status_v2_to_v1(v2_state: str, tracking_number: Optional[str] = None) -> Tuple[str, str]:
    """
    Map v2 status to v1 status with context awareness.
    
    Mapping logic:
    - FULFILLED + trackingNumber → SHIPPED (physical)
    - FULFILLED without tracking → SHIPPED (digital)
    - PAID → PAID
    - CANCELLED → CANCELLED
    - Other → Keep as-is if in v1 enum
    
    Args:
        v2_state: v2 order state (PAID, CANCELLED, SHIPPED, FULFILLED)
        tracking_number: Optional tracking number
    
    Returns:
        Tuple of (v1_status, decision_reason)
    """
    v1_valid_states = {"PAID", "CANCELLED", "SHIPPED"}
    
    if v2_state == "FULFILLED":
        reason = f"FULFILLED (tracking: {tracking_number if tracking_number else 'none'}) → SHIPPED"
        return "SHIPPED", reason
    
    if v2_state in v1_valid_states:
        reason = f"{v2_state} (no mapping needed)"
        return v2_state, reason
    
    # Fallback for unknown states
    reason = f"Unknown v2 state {v2_state}, using as-is"
    return v2_state, reason


def map_status_v3_to_v1(order_status: Dict[str, Any]) -> Tuple[str, str]:
    """
    Map v3 nested status to v1 status.
    
    v3 uses orderStatus.current which can be FULFILLED, PAID, CANCELLED, etc.
    
    Args:
        order_status: v3 orderStatus dict with 'current' field
    
    Returns:
        Tuple of (v1_status, decision_reason)
    """
    current_status = order_status.get("current", "UNKNOWN")
    
    # Check history for tracking information
    tracking_number = None
    history = order_status.get("history", [])
    for event in history:
        if event.get("type") == "shipped" and event.get("tracking"):
            tracking_number = event.get("tracking")
            break
    
    return map_status_v2_to_v1(current_status, tracking_number)


def transform_v2_to_v1(order_v2: Dict[str, Any], audit: AuditTrail) -> Dict[str, Any]:
    """
    Transform v2 order to v1 format.
    
    Args:
        order_v2: v2 format order
        audit: AuditTrail to record decisions
    
    Returns:
        v1 format order
    """
    try:
        # Extract and validate basic fields
        order_id = order_v2.get("orderId")
        if not order_id:
            audit.add_warning("Missing orderId")
            order_id = "UNKNOWN"
        
        # Extract customer info
        customer = order_v2.get("customer", {})
        customer_id = customer.get("id", "UNKNOWN")
        customer_name = customer.get("name", "UNKNOWN")
        
        # Map status
        state = order_v2.get("state", "UNKNOWN")
        status, status_reason = map_status_v2_to_v1(state)
        audit.add_decision("status_mapping", status_reason)
        
        # Process amount/currency
        amount_obj = order_v2.get("amount", {"value": 0, "currency": "USD"})
        if isinstance(amount_obj, dict):
            amount_value = Decimal(str(amount_obj.get("value", 0)))
            currency = amount_obj.get("currency", "USD")
        else:
            amount_value = Decimal(str(amount_obj))
            currency = "USD"
        
        # Convert to USD if needed
        if currency != "USD":
            try:
                total_price = convert_currency_to_usd(amount_value, currency)
                audit.add_decision("currency_conversion", f"{currency} → USD at {EXCHANGE_RATES[currency]}")
            except ValueError as e:
                audit.add_warning(str(e))
                total_price = amount_value
        else:
            total_price = amount_value
        
        # Validate line items and price consistency
        line_items = order_v2.get("lineItems", [])
        if line_items:
            correct_total, price_audit = validate_price_consistency(line_items, total_price)
            audit.decisions.extend(price_audit.decisions)
            audit.warnings.extend(price_audit.warnings)
            total_price = correct_total
        
        # Normalize date
        created_at_str = order_v2.get("createdAt")
        try:
            created_at = normalize_date(created_at_str) if created_at_str else "UNKNOWN"
        except ValueError as e:
            audit.add_warning(f"Date parsing failed: {e}")
            created_at = "UNKNOWN"
        
        # Build v1 response
        v1_order = {
            "orderId": order_id,
            "status": status,
            "totalPrice": float(total_price),
            "customerId": customer_id,
            "customerName": customer_name,
            "createdAt": created_at,
            "items": line_items  # Keep original structure for now
        }
        
        return v1_order
    
    except Exception as e:
        audit.add_warning(f"Transformation error: {str(e)}")
        raise


def transform_v3_to_v1(order_v3: Dict[str, Any], audit: AuditTrail) -> Dict[str, Any]:
    """
    Transform v3 order to v1 format.
    
    Args:
        order_v3: Single v3 format order (from data[] array element)
        audit: AuditTrail to record decisions
    
    Returns:
        v1 format order
    """
    try:
        # Extract basic fields
        order_id = order_v3.get("orderId")
        if not order_id:
            audit.add_warning("Missing orderId")
            order_id = "UNKNOWN"
        
        # Extract customer info
        customer = order_v3.get("customer", {})
        customer_id = customer.get("id", "UNKNOWN")
        customer_name = customer.get("name", "UNKNOWN")
        
        # Map status from orderStatus object
        order_status = order_v3.get("orderStatus", {"current": "UNKNOWN"})
        status, status_reason = map_status_v3_to_v1(order_status)
        audit.add_decision("status_mapping", status_reason)
        
        # Process pricing object
        pricing = order_v3.get("pricing", {"total": 0, "currency": "USD"})
        if isinstance(pricing, dict):
            total_value = Decimal(str(pricing.get("total", 0)))
            currency = pricing.get("currency", "USD")
        else:
            total_value = Decimal(str(pricing))
            currency = "USD"
        
        # Convert to USD if needed
        if currency != "USD":
            try:
                total_price = convert_currency_to_usd(total_value, currency)
                audit.add_decision("currency_conversion", f"{currency} → USD at {EXCHANGE_RATES[currency]}")
            except ValueError as e:
                audit.add_warning(str(e))
                total_price = total_value
        else:
            total_price = total_value
        
        # Normalize timestamps
        timestamps = order_v3.get("timestamps", {})
        created_at_str = timestamps.get("created") if isinstance(timestamps, dict) else None
        try:
            created_at = normalize_date(created_at_str) if created_at_str else "UNKNOWN"
        except ValueError as e:
            audit.add_warning(f"Date parsing failed: {e}")
            created_at = "UNKNOWN"
        
        # Build v1 response
        v1_order = {
            "orderId": order_id,
            "status": status,
            "totalPrice": float(total_price),
            "customerId": customer_id,
            "customerName": customer_name,
            "createdAt": created_at,
            "items": []  # v3 doesn't explicitly expose line items in base structure
        }
        
        return v1_order
    
    except Exception as e:
        audit.add_warning(f"Transformation error: {str(e)}")
        raise


def to_legacy(order_data: Dict[str, Any]) -> Tuple[Dict[str, Any], AuditTrail]:
    """
    Transform v2/v3 order to v1 (legacy) format.
    
    Main entry point for compatibility layer.
    
    Key requirements:
    1. Detect version
    2. Map status contextually (FULFILLED → SHIPPED)
    3. Validate price consistency
    4. Convert currency to USD
    5. Handle timezone conversion
    6. Record decisions in audit trail
    
    Args:
        order_data: Response body from v2 or v3 API
    
    Returns:
        Tuple of (v1_format_order, audit_trail)
    
    Raises:
        ValueError: If version cannot be detected or transformation fails
    """
    audit = AuditTrail()
    
    try:
        # Detect version
        version = detect_version(order_data)
        audit.add_decision("version_detection", version)
        
        # Transform based on version
        if version == "v2":
            v1_order = transform_v2_to_v1(order_data, audit)
        elif version == "v3":
            # For v3, extract first order from data array
            data_array = order_data.get("data", [])
            if not data_array:
                raise ValueError("v3 response has empty data array")
            v1_order = transform_v3_to_v1(data_array[0], audit)
        else:
            # Already v1 or unknown
            v1_order = order_data
            audit.add_decision("no_transformation", f"{version} already compatible")
        
        return v1_order, audit
    
    except Exception as e:
        audit.add_warning(f"Transformation failed: {str(e)}")
        raise


def normalize_error_response(status_code: int, body: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize v2/v3 error responses to v1 format {error, message}.
    
    Args:
        status_code: HTTP status code
        body: Error response body
    
    Returns:
        Normalized error dict with 'error' and 'message' keys
    """
    # Try to extract error from body
    if isinstance(body, dict):
        error = body.get("error") or body.get("code") or f"HTTP_{status_code}"
        message = body.get("message") or body.get("detail") or "An error occurred"
    else:
        error = f"HTTP_{status_code}"
        message = str(body)
    
    return {
        "error": error,
        "message": message
    }


def classify_response(status_code: int, body: Dict[str, Any]) -> str:
    """
    Classify response type for error handling strategy.
    
    Returns:
        "DEPRECATED" | "TRANSIENT" | "CLIENT_ERROR" | "OUTAGE" | "OK"
    """
    if 200 <= status_code < 300:
        return "OK"
    
    if status_code == 404:
        return "CLIENT_ERROR"
    
    if status_code == 400:
        return "CLIENT_ERROR"
    
    if status_code == 429:
        return "TRANSIENT"
    
    if status_code == 503:
        return "OUTAGE"
    
    if status_code == 410:
        return "DEPRECATED"
    
    if 500 <= status_code < 600:
        return "OUTAGE"
    
    return "TRANSIENT"
