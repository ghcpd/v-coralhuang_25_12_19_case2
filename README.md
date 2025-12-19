# Backward Compatibility Layer for API Evolution

This project implements a backward-compatibility layer to support API evolution from v1 to v2 to v3, ensuring legacy consumers can continue using the v1 contract without modification.

## API Version Differences

### v1 (Legacy)
- **Schema**: Flat structure
- **Status**: `PAID | CANCELLED | SHIPPED`
- **Currency**: USD only
- **Date**: `YYYY-MM-DD`
- **Fields**: `orderId`, `status`, `totalPrice`, `customerId`, `customerName`, `createdAt`, `items`

### v2 (Current)
- **Schema**: Nested structures (`amount`, `customer`)
- **Status**: `PAID | CANCELLED | SHIPPED | FULFILLED`
- **Currency**: Multi-currency support
- **Date**: ISO-8601
- **Fields**: `orderId`, `state`, `amount` (with `value` and `currency`), `customer` (with `id` and `name`), `createdAt`, `lineItems`

### v3 (New)
- **Schema**: Pagination wrapper with `data` array, deep nesting
- **Status**: Complex `orderStatus` with `current` and `history`
- **Pricing**: Derived fields (`subtotal`, `tax`, `discount`, `total`)
- **Timestamps**: `created` and `fulfilled`
- **Fields**: Wrapped in `data[]`, with `orderId`, `orderStatus`, `pricing`, `customer`, `timestamps`

## Compatibility and Transformation Strategy

The compatibility layer automatically detects the API version based on response structure:
- **v3**: Presence of top-level `data` array
- **v2**: Presence of top-level `orderId`

Transformations include:
- **Status Mapping**: Context-aware mapping (e.g., `FULFILLED` → `SHIPPED`)
- **Price Validation**: Detect and correct inconsistencies between declared and calculated totals
- **Currency Normalization**: Convert all amounts to USD
- **Date Normalization**: Convert ISO-8601 to `YYYY-MM-DD`
- **Audit Trail**: Record all transformation decisions and warnings

## How Version Detection Works

Version detection is structure-based and does not rely on external metadata:

```python
def detect_version(order_data: Dict[str, Any]) -> str:
    if 'data' in order_data and isinstance(order_data['data'], list):
        return 'v3'
    elif 'orderId' in order_data:
        return 'v2'
    else:
        raise ValueError("Unable to detect version")
```

## How to Run Tests Locally

1. Ensure Python 3.6+ is installed
2. Install dependencies (if any): `pip install -r requirements.txt`
3. Run the test suite: `python run_tests.py`

## How to Interpret Test Results

The test runner will output results for each test case:
- `✓ TestName: Details` - Passed
- `✗ TestName: Details` - Failed

At the end, a summary shows `passed/total` and exits with code 0 (all pass) or 1 (failures).

Tests cover:
- Version detection
- Currency conversion
- Date normalization
- Status mapping
- Price validation and recalculation
- Full transformation pipelines
- Edge cases (currency mismatches, timezone handling)

## Assumptions and Known Limitations

- Currency conversion uses fixed mock rates (not real-time)
- v3 assumes single order per response (first item in `data` array)
- Tracking number detection for status mapping is simplified (checks for 'trackingNumber' in string representation)
- No external API calls; all data is mocked
- Timezone handling assumes UTC or offset formats in ISO dates

## Project Structure

- `compatibility_layer.py`: Core transformation functions
- `test_suite.py`: Unit tests
- `run_tests.py`: Test runner script
- `requirements.txt`: Dependencies
- `README.md`: This documentation
- `e2e_api_regression_harness.py`: Read-only test harness (not modified)