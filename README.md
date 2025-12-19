Compatibility Layer README

Overview
--------
This repository provides a compatibility layer to transform newer API responses (v2/v3) into a v1-compatible format and a deterministic test suite to validate transformations.

API Differences
---------------
- v1: flat schema: orderId, status (PAID|CANCELLED|SHIPPED), totalPrice (USD), customerId, customerName, createdAt (YYYY-MM-DD), items
- v2: nested: orderId, state (PAID|CANCELLED|SHIPPED|FULFILLED), amount {value,currency}, customer {id,name}, createdAt (ISO-8601), lineItems
- v3: wrapper: {data: [...]}, deep nesting including orderStatus.current, pricing {subtotal,tax,total,currency}, timestamps

Transformation Strategy
-----------------------
- Version detection: detect_version inspects payload keys: 'data' -> v3, 'orderId' -> v2
- Status mapping: _map_status maps FULFILLED -> SHIPPED (with audit decision: physical if tracking present, digital otherwise). Only v1 enums are emitted.
- Price validation: For v2, we compare declared amount (converted to USD) to the sum of line items (converted to USD). If inconsistent, we use the recalculated sum and emit a non-fatal warning in the audit trail.
- Currency normalization: deterministic exchange rates in compat/compat.py (EUR, JPY) convert amounts to USD. Unknown currencies default to 1:1 with a warning.
- Date normalization: ISO-8601 strings are parsed and converted safely to YYYY-MM-DD dates (timezone-aware using dateutil)
- Audit trail: All decisions and warnings are recorded in an AuditTrail object which is returned alongside legacy payloads. The legacy payload itself remains schema-pure (no audit fields)

Files
-----
- compat/compat.py: compatibility functions and helpers
- tests/test_compat.py: pytest suite covering required scenarios
- run_tests.py and run_tests (shell wrapper): one-click runner that executes the test suite
- requirements.txt, requirements-dev.txt

How to run tests
----------------
1. Create a virtualenv and install deps:
   python -m venv .venv
   .\.venv\Scripts\activate  (or source .venv/bin/activate)
   python -m pip install -r requirements.txt -r requirements-dev.txt

2. Run tests:
   python run_tests.py
   or
   ./run_tests

Interpretation of results
-------------------------
- The runner exits with code 0 and prints a summary when all checks pass.
- Tests verify correctness of mapping, currency conversion, date normalization, audit warnings, and harness integration.

Assumptions and Limitations
---------------------------
- Exchange rates are fixed deterministic values for test purposes. Replace with a robust rates service in production.
- v3 payload handling is best-effort for deep mapping (we map subtotal to items if no explicit line items exist).
- to_legacy returns (legacy_dict, AuditTrail) to keep audit data separate from the v1 payload.

Contact
-------
- Implemented by: GitHub Copilot
- Model: vsc-5mini-mix22-arm5-step330
