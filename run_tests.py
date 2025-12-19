#!/usr/bin/env python3
"""
Test Runner for Backward Compatibility Layer

Runs all tests and exits with appropriate code.
"""

import sys
import unittest
from test_suite import TestCompatibilityLayer

def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestCompatibilityLayer)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)