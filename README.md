Compatibility Layer for v2/v3 -> v1 API Transformation

Overview
--------
This workspace implements a reusable compatibility and test environment that
validates transformations from newer API versions (v2, v3) back to the legacy
v1 contract. The original harness (e2e_api_regression_harness.py) is intentionally
left read-only; this project injects implementations at runtime and runs a
comprehensive test suite.

API Evolution (summary)
-----------------------
- v1 (legacy): flat schema, USD-only, simple YYYY-MM-DD date
  - keys: orderId, status (PAID|CANCELLED|SHIPPED), totalPrice, customerId, customerName, createdAt, items
- v2: nested structures, multi-currency, amount object, ISO-8601 timestamps
  - keys: orderId, state (PAID|CANCELLED|SHIPPED|FULFILLED), amount {value,currency}, customer, createdAt, lineItems
- v3: wrapped in data[], deep nesting, derived pricing (subtotal/tax/discount/total), timestamps map
  - keys: data: [{orderId, orderStatus:{current,...}, pricing:{...}, timestamps:{created,fulfilled}}]

What this compatibility layer does
----------------------------------
- Auto-detects source version (v3 if top-level data list present, else v2)
- Context-aware status mapping
  - FULFILLED -> SHIPPED (physical if tracking/fulfilled timestamp present, otherwise digital)
- Price validation and auto-repair
  - Detects mismatches between declared totals and computed components
  - Uses calculated component value and emits non-fatal warnings (captured in audit trail)
- Currency normalization
  - Deterministic exchange rates used for tests (EUR, JPY -> USD)
- ISO-8601 -> YYYY-MM-DD date normalization (timezone-safe)
- Audit trail capturing decisions and warnings

Files added
-----------
- compat_layer.py  : compatibility implementations + deterministic test data
- run_tests.py     : runner that injects functions into the read-only harness and executes it
- README.md        : this file
- requirements.txt : minimal (no external deps needed)

How version detection works
---------------------------
- If the payload has a top-level "data" array -> considered v3
- Else if payload has "orderId" at root -> considered v2
- Unknown shapes raise a detection error (defensive)

Running tests (one command)
---------------------------
From the repository root run:

    python run_tests.py

The runner will inject the compatibility functions into the read-only
harness, execute its test suite, print human-friendly results and exit with
code 0 on success or non-zero on any failure. This makes it CI-friendly.

Assumptions & Limitations
-------------------------
- Exchange rates are deterministic fixtures for tests (not live FX)
- The test matrix is deliberately small and focused on core transformation
  edge cases requested in the task (price mismatch, status mapping, currency, timezone)
- The harness is not modified on disk; we inject behaviour at runtime which
  keeps the legacy file immutable while enabling full validation

If you need additional cases or different exchange rates, add them to
compat_layer.TEST_CASES and extend compat_layer.run_all_tests accordingly.

License: MIT-style (for test/demo purposes)
