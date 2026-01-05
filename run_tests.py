#!/usr/bin/env python3
"""Run the compatibility layer tests and execute the read-only harness by
injecting the implemented functions at runtime.

Usage:
    python run_tests.py

This script imports e2e_api_regression_harness.py as a module, replaces its
TODO functions with the implementations from compat_layer.py, and runs main().
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(__file__)
HARNESS_PATH = os.path.join(HERE, "e2e_api_regression_harness.py")

spec = importlib.util.spec_from_file_location("harness", HARNESS_PATH)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

# import our implemented layer
import compat_layer

# inject implementations
h.request_json = compat_layer.request_json
h.detect_version = compat_layer.detect_version
h.to_legacy = compat_layer.to_legacy
h.normalize_error_response = compat_layer.normalize_error_response
h.classify_response = compat_layer.classify_response

# replace the harness run_tests with our suite (which returns harness.CheckResult)
def _wrapped_run_tests():
    return compat_layer.run_all_tests(h)

h.run_tests = _wrapped_run_tests

if __name__ == "__main__":
    # run the harness main which will print results and exit with 0 on success
    try:
        h.main()
    except SystemExit as e:
        # propagate the harness exit code
        code = int(e.code) if isinstance(e.code, int) else 1
        sys.exit(code)
    except Exception as e:
        print("Runner error:", e)
        sys.exit(2)
