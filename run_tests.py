#!/usr/bin/env python3
"""Run test suite and exit with non-zero on failures."""
import sys
import pytest

if __name__ == "__main__":
    # Run pytest programmatically
    ret = pytest.main(["-q", "tests"])  # returns number of failed tests
    sys.exit(ret)
