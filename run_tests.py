#!/usr/bin/env python3
import sys
import pytest

if __name__ == "__main__":
    # Run pytest discovery in the workspace
    ret = pytest.main(["-q", "--disable-warnings", "tests"]) 
    sys.exit(ret)
