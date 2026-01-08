# API Compatibility Layer (v3/v2 → v1)

🔧 **Goal:** Provide a reusable compatibility layer that transforms v2/v3 API responses into the legacy v1 contract for unmodified legacy consumers.

## API Versions

- **v1 (Legacy)**
  - Flat schema: orderId, status, totalPrice, customerId, customerName, createdAt (YYYY-MM-DD), items[]
  - USD only
  - Naive date format (YYYY-MM-DD)

- **v2 (Current)**
  - Nested fields: `state`, `amount` {value,currency}, `customer`, `createdAt` (ISO-8601), `lineItems`
  - Multi-currency support

- **v3 (New)**
  - `data[]` wrapper; each item contains `orderStatus` ({current, history}), `pricing` (subtotal,tax,discount,total,currency), `timestamps` (created, fulfilled), deep nesting

## Components

- `compat_layer` (module)
  - `request_json(method, path, query)` – deterministic mocked responses used by tests
  - `detect_version(order_data)` – infers version from structure (v3: top-level `data[]`, v2: `orderId` at root)
  - `to_legacy(order_data)` – transforms v2/v3 into v1-compatible dict and returns an `AuditTrail` with decisions and warnings
  - `normalize_error_response(status_code, body)` – maps common error shapes to `{error, message}`
  - `classify_response(status_code, body)` – quick classification: `OK`, `DEPRECATED`, `TRANSIENT`, `CLIENT_ERROR`, `OUTAGE`

- `tests/` – pytest test suite covering behavior and edge cases
- `run_tests.py` – single-command test runner (also `./run_tests` shell wrapper)
- `requirements.txt` – minimal pinned deps for deterministic tests

## Transformation Strategy

- **Version detection:** structural inspection only (no headers/URLs)
- **Status mapping:** `FULFILLED` -> `SHIPPED`. Presence/absence of `trackingNumber` recorded in the audit (`physical` vs `digital`) but both map to v1 `SHIPPED` per spec
- **Price validation:** calculate sum(lineItems) in USD; if it differs from declared total, prefer calculated value and emit a non-fatal warning (audit)
- **Currency normalization:** deterministic fixed rates (in `CURRENCY_RATES`) convert all prices into USD for the v1 `totalPrice` and item `price`
- **Date normalization:** ISO-8601 → `YYYY-MM-DD` in UTC using `python-dateutil` for robust timezone handling
- **Audit trail:** `AuditTrail` object returns `decisions` and `warnings` separate from the v1 payload (the v1 payload remains unchanged besides required fields)

## How to run tests locally

1. Create a virtual environment and install deps:

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows PowerShell
pip install -r requirements.txt
```

2. Run tests (single command):

```bash
python run_tests.py
# or
./run_tests
```

- The runner exits with non-zero code on any failing test (suitable for CI).

## Interpreting test results

- Tests assert that the compatibility layer:
  - Correctly detects v2/v3
  - Maps status contextually and records decisions
  - Recalculates totals and emits warnings for mismatches
  - Converts currencies and normalizes dates
  - Normalizes errors and classifies responses

- A passing test suite means all core requirements and selected edge cases are satisfied.

## Assumptions & Limitations

- Currency rates are deterministic and hard-coded for test determinism (replace with a rate service for production).
- `request_json` provides deterministic mock cases used by the test suite. In production this would call a real API.
- v3 payloads are expected to contain a single item in `data[]` for per-order transforms; pagination is outside the scope of the v1 conversion but can be added later.
- Unknown currencies are treated as USD but will generate a warning (this behavior is deterministic and testable).

---

If you'd like, I can expand the test matrix or add property-based tests for more coverage.🧪