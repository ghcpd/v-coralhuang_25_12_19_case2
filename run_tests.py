#!/usr/bin/env python
"""
Test Runner: Execute all API compatibility layer tests

Usage:
    python run_tests.py
    ./run_tests.py

Exit Codes:
    0 - All tests passed
    1 - One or more tests failed
"""

import sys
import os

# Add current directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import test suite
from test_suite import run_all_tests

if __name__ == "__main__":
    try:
        all_passed = run_all_tests()
        sys.exit(0 if all_passed else 1)
    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
